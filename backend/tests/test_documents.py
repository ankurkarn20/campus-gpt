"""Document ingestion (extract, clean, chunk, embed, store) and hybrid retrieval."""
import asyncio
from itertools import pairwise

import pytest
from sqlalchemy import func, select

from campusgpt import documents
from campusgpt.chat import check_citations
from campusgpt.config import get_settings
from campusgpt.documents import (
    MAX_CHUNK_CHARS,
    Block,
    UnsupportedDocument,
    chunk_blocks,
    clean_pdf_pages,
    extract,
    markdown_blocks,
)
from campusgpt.llm import ScriptedProvider, TextChunk, ToolCall
from campusgpt.models import Document, DocumentChunk
from campusgpt.retrieval import search
from campusgpt.tools import citation
from tests.conftest import POLICIES, SHORTAGE, in_session, login
from tests.test_chat import ask, of, use

# -- extraction and chunking ----------------------------------------------------------------
SAMPLE = """# Library Rules

> SYNTHETIC DOCUMENT. Fictional.

Category: other

## 1. Borrowing

1.1 Students may borrow **four** books
for two weeks.

| Item | Days |
|---|---|
| Book | 14 |

### 1.2 Renewals

Books can be renewed once.

## 2. Fines

A fine of Rs 5 per day is charged.
"""


def test_markdown_sections_title_and_metadata():
    title, meta, blocks = markdown_blocks(SAMPLE)
    assert title == "Library Rules"
    assert meta == {"category": "other"}
    assert [b.section for b in blocks] == ["1. Borrowing", "1. Borrowing > 1.2 Renewals",
                                           "2. Fines"]
    assert "SYNTHETIC" not in " ".join(b.text for b in blocks)      # banner not indexed
    assert "**" not in blocks[0].text and "|---|" not in blocks[0].text


def test_chunks_unwrap_lines_but_keep_table_rows():
    chunks = chunk_blocks(markdown_blocks(SAMPLE)[2])
    assert chunks[0].content == ("1.1 Students may borrow four books for two weeks.\n\n"
                                 "| Item | Days |\n| Book | 14 |")


def test_long_sections_are_split_with_overlap_and_never_merged():
    paragraphs = [f"Rule {i}. " + "word " * 60 for i in range(12)]       # ~320 chars each
    blocks = [Block("A", None, "\n\n".join(paragraphs)), Block("B", None, "Short.")]
    chunks = chunk_blocks(blocks)
    a = [c for c in chunks if c.section == "A"]
    assert len(a) > 1 and all(len(c.content) <= MAX_CHUNK_CHARS for c in chunks)
    for first, second in pairwise(a):         # the last paragraph is carried over
        assert second.content.startswith(first.content.split("\n\n")[-1])
    assert all(f"Rule {i}." in " ".join(c.content for c in a) for i in range(12))
    assert chunks[-1].section == "B" and chunks[-1].content == "Short."


def test_overlong_paragraph_is_split_at_sentences():
    sentence = "This sentence is about forty characters. "
    chunks = chunk_blocks([Block(None, None, sentence * 80)])
    assert len(chunks) >= 3
    assert all(len(c.content) <= MAX_CHUNK_CHARS for c in chunks)
    assert all(c.content.endswith("characters.") for c in chunks)


def test_pdf_cleaning_drops_headers_footers_and_joins_hyphenation():
    pages = [f"Synthetic University\n{n}. Fees\nA late fee of Rs {n}00 is char-\nged daily."
             f"\nPage {n} of 3" for n in range(1, 4)]
    assert clean_pdf_pages(pages)[1] == ["2. Fees", "A late fee of Rs 200 is charged daily."]


def minimal_pdf(pages: list[list[str]]) -> bytes:
    """A valid PDF with one line of Helvetica text per string, no PDF library needed."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", None,
               "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for lines in pages:
        ops = "".join(f"BT /F1 11 Tf 50 {760 - 16 * i} Td ({line}) Tj ET\n"
                      for i, line in enumerate(lines))
        objects.append(f"<< /Length {len(ops)} >>\nstream\n{ops}endstream")
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources "
                       f"<< /Font << /F1 3 0 R >> >> /Contents {len(objects)} 0 R >>")
        kids.append(f"{len(objects)} 0 R")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = b"%PDF-1.4\n", []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF"\
        .encode()
    return out


def test_pdf_text_sections_and_pages():
    pdf = minimal_pdf([["1. Borrowing", "Students may borrow four books.", "Page 1"],
                       ["2. Fines", "A fine of Rs 5 per day is charged.", "Page 2"]])
    title, _, blocks = extract("rules.pdf", pdf)
    assert title is None
    assert [(b.section, b.page, b.text) for b in blocks] == [
        ("1. Borrowing", 1, "Students may borrow four books."),
        ("2. Fines", 2, "A fine of Rs 5 per day is charged.")]


@pytest.mark.parametrize("name, data", [
    ("rules.docx", b"PK\x03\x04"), ("empty.md", b"# Title only\n"), ("bad.pdf", b"not a pdf"),
    ("latin1.txt", "caf\xe9".encode("latin-1"))])
def test_unusable_files_are_rejected(name, data):
    with pytest.raises(UnsupportedDocument):
        extract(name, data)


def test_every_policy_is_synthetic_and_has_a_category():
    for path in POLICIES.glob("*.md"):
        if path.stem != "README":
            text = path.read_text()
            assert "SYNTHETIC DOCUMENT" in text, path.name
            assert markdown_blocks(text)[1]["category"] in documents.CATEGORIES, path.name


@pytest.mark.parametrize("section, expected", [
    ("4. Condonation for medical reasons", "Attendance Policy §4"),
    ("2. Eligibility > 2.1 Rules", "Attendance Policy §2"),
    ("Overview", "Attendance Policy, Overview"), (None, "Attendance Policy")])
def test_citation(section, expected):
    assert citation("Attendance Policy", section) == expected


# -- storage ---------------------------------------------------------------------------------
def test_policies_are_indexed_once(indexed, test_url):
    async def check(db):
        report = await documents.load_directory(db, POLICIES)
        n_docs = await db.scalar(select(func.count()).select_from(Document)
                                 .where(Document.status == "active"))
        empty = await db.scalar(select(func.count()).select_from(DocumentChunk)
                                .where(DocumentChunk.content == ""))
        return report, n_docs, empty

    report, n_docs, empty = asyncio.run(in_session(test_url, check))
    assert {outcome for _, outcome in report} == {"unchanged"}
    assert n_docs == len(report) == 6 and empty == 0


def test_new_version_supersedes_the_old_one(indexed, test_url):
    updated = (POLICIES / "fee-policy.md").read_text().replace("Rs 100 per day", "Rs 250 per day")

    async def upload_new_version(db):
        old = await db.scalar(select(Document).where(Document.title.like("Fee Payment%"),
                                                     Document.status == "active"))
        doc = await documents.register(db, title=old.title, category="fees",
                                       file_name="fee-policy.md", data=updated.encode(),
                                       uploaded_by=old.uploaded_by)
        await documents.index(db, doc, updated.encode())
        await db.refresh(old)
        [hit] = await search(db, "late fee per day for tuition", k=1)
        return (old.status, old.superseded_by), (doc.id, doc.status, doc.version), hit

    old, new, hit = asyncio.run(in_session(test_url, upload_new_version))
    assert old == ("superseded", new[0])
    assert new[1:] == ("active", 2)
    assert hit.document_id == new[0] and "Rs 250 per day" in hit.content


# -- retrieval -------------------------------------------------------------------------------
QUESTIONS = [
    ("What is the late fee if I pay tuition late?", "Fee Payment and Refund Policy §2"),
    ("can I get my answer sheet rechecked", "Examination Regulations §6"),
    ("I was ill for two weeks, can my attendance shortage be excused?", "Attendance Policy §4"),
    ("what time does the hostel gate close at night", "Hostel Rules §3"),
    ("Can I sit the end-term exam if my exam fee is unpaid?", "Examination Regulations §2"),
    ("penalty for submitting an assignment one day late", "Academic Integrity Policy §2"),
    ("how much does a supplementary exam cost", "Examination Regulations §5"),
    ("refund if I withdraw 20 days after the term starts", "Fee Payment and Refund Policy §5"),
    ("hostel gate kitne baje band hota hai", "Hostel Rules §3"),
]


@pytest.mark.parametrize("question, expected", QUESTIONS)
def test_hybrid_search_finds_the_right_section(indexed, test_url, question, expected):
    passages = asyncio.run(in_session(test_url, lambda db: search(db, question, k=3)))
    assert expected in [citation(p.document, p.section) for p in passages]
    assert passages == sorted(passages, key=lambda p: -p.score)


def test_search_modes(indexed, test_url):
    async def run(db):
        return {mode: await search(db, "re-evaluation fee", k=5, mode=mode)
                for mode in ("hybrid", "semantic", "lexical")}

    results = asyncio.run(in_session(test_url, run))
    assert all(p.lexical_rank is None for p in results["semantic"])
    assert all(p.semantic_rank is None for p in results["lexical"])
    assert results["hybrid"][0].semantic_rank and results["hybrid"][0].lexical_rank


@pytest.mark.parametrize("question", ["", "   ", "the and of"])
def test_empty_or_stopword_questions(indexed, test_url, question):
    passages = asyncio.run(in_session(test_url, lambda db: search(db, question, mode="lexical")))
    assert passages == []


# -- chat tool -------------------------------------------------------------------------------
def test_chat_searches_documents_and_returns_citations(app, client, indexed):
    llm = use(app, ScriptedProvider([
        [ToolCall("c1", "search_university_documents",
                  '{"query": "attendance condonation medical"}')],
        [TextChunk("A shortage of up to 10 points can be condoned [Attendance Policy §4].")],
    ]))
    login(client, SHORTAGE)
    events = ask(client, "Can my attendance be excused if I was sick?")

    assert of(events, "status") == [{"text": "Searching university policies"}]
    tool = of(events, "tool")[0]
    assert tool["ok"] and "Attendance Policy §4" in [p["cite"] for p in tool["result"]]
    assert all(p["text"] and p["chunk_id"] for p in tool["result"])
    # The passages reach the model as the tool result.
    assert "Condonation" in llm.seen[1][-1]["content"]


def test_rule_questions_get_passages_before_the_model_answers(app, client, indexed,
                                                              monkeypatch):
    monkeypatch.setattr(get_settings(), "rag_prefetch_min_similarity", 0.62)
    llm = use(app, ScriptedProvider([[TextChunk("Phones are not allowed "
                                                "[Examination Regulations §3.3].")]]))
    login(client, SHORTAGE)
    events = ask(client, "Can I bring my phone into the exam hall if it is switched off?")

    tool = of(events, "tool")[0]
    assert tool["tool"] == "search_university_documents"
    assert "Examination Regulations §3" in [p["cite"] for p in tool["result"]]
    instructions = llm.seen[0][0]
    assert instructions["role"] == "system" and "Mobile phones" in instructions["content"]
    assert of(events, "done")[0]["citations"] == [
        {"cite": "Examination Regulations §3.3", "verified": True}]


def test_unrelated_questions_are_not_prefetched(app, client, indexed, monkeypatch):
    monkeypatch.setattr(get_settings(), "rag_prefetch_min_similarity", 0.62)
    use(app, ScriptedProvider([[TextChunk("Hello!")]]))
    login(client, SHORTAGE)
    events = ask(client, "hi")
    assert of(events, "tool") == [] and of(events, "done")[0]["citations"] == []


def search_source(*cites, ok=True):
    return {"tool": "search_university_documents", "ok": ok,
            "result": [{"cite": c} for c in cites]}


@pytest.mark.parametrize("answer, sources, expected", [
    ("Up to 10 points [Attendance Policy §4].", [search_source("Attendance Policy §4")],
     [("Attendance Policy §4", True)]),
    ("See [Attendance Policy § 3.1] and [Attendance Policy §3.1].",
     [search_source("Attendance Policy §3")], [("Attendance Policy §3.1", True)]),
    ("[Attendance Policy §31]", [search_source("Attendance Policy §3")],
     [("Attendance Policy §31", False)]),
    ("[Examination Policy §7]", [search_source("Examination Regulations §3")],
     [("Examination Policy §7", False)]),
    ("[Fee Payment and Refund Policy §2]", [], [("Fee Payment and Refund Policy §2", False)]),
    ("[Hostel Rules §3]", [search_source("Hostel Rules §3", ok=False)],
     [("Hostel Rules §3", False)]),
    ("No citations [here] at all.", [search_source("Hostel Rules §3")], []),
])
def test_citations_are_checked_against_retrieved_passages(answer, sources, expected):
    assert [(c["cite"], c["verified"]) for c in check_citations(answer, sources)] == expected
