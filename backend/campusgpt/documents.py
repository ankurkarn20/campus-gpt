"""Policy documents: extract text, clean it, split it into chunks, embed and store them.

The same pipeline indexes the bundled synthetic policies (`make policies`) and documents
uploaded by an administrator. Chunks follow the document's own sections, so every search
result can be cited as "document, section".

    python -m campusgpt.documents load ../docs/policies    # index every policy file there
"""
import argparse
import asyncio
import hashlib
import io
import re
import sys
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from campusgpt.embedding import embed_passages
from campusgpt.models import Document, DocumentChunk, User

MAX_CHUNK_CHARS = 1200      # about 250 words; BGE-small reads at most 512 tokens
OVERLAP_MAX_CHARS = 400     # a short paragraph is repeated at the start of the next chunk
CATEGORIES = ("academic", "examinations", "fees", "hostel", "scholarships", "notices", "other")
FILE_TYPES = (".md", ".txt", ".pdf")


class UnsupportedDocument(ValueError):
    """The file type is not supported or no text could be extracted from it."""


@dataclass
class Block:
    """A run of text under one heading (and, for PDFs, on one page)."""
    section: str | None
    page: int | None
    text: str


@dataclass
class Chunk:
    section: str | None
    page: int | None
    content: str


# -- extraction ----------------------------------------------------------------------------
MD_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
MD_TABLE_RULE = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
METADATA = re.compile(r"^(category|effective from)\s*:\s*(.+)$", re.IGNORECASE)


def markdown_blocks(text: str) -> tuple[str | None, dict[str, str], list[Block]]:
    """Split Markdown at its headings. Returns the title (first # heading), metadata lines
    such as "Category: fees", and the blocks. Block quotes before the first section (the
    "synthetic document" banner) are not indexed."""
    title, meta, blocks = None, {}, []
    trail: list[tuple[int, str]] = []        # enclosing headings below the title
    lines: list[str] = []

    def flush():
        body = "\n".join(lines).strip()
        if body:
            blocks.append(Block(" > ".join(h for _, h in trail) or None, None, body))
        lines.clear()

    for line in text.splitlines():
        if m := MD_HEADING.match(line):
            level, heading = len(m.group(1)), m.group(2).strip()
            if level == 1 and title is None:
                flush()
                title = heading
                continue
            flush()
            trail = [(lvl, h) for lvl, h in trail if lvl < level] + [(level, heading)]
        elif not trail and line.startswith(">"):
            continue
        elif not trail and (m := METADATA.match(line.strip())):
            meta[m.group(1).lower()] = m.group(2).strip()
        elif not MD_TABLE_RULE.match(line):
            lines.append(line.replace("**", "").replace("__", ""))
    flush()
    return title, meta, blocks


PAGE_NUMBER = re.compile(r"^\s*(page\s*)?\d+(\s*(of|/)\s*\d+)?\s*$", re.IGNORECASE)
PDF_HEADING = re.compile(r"^(\d{1,2}\.?\s+[A-Z][^.:]{2,70}|[A-Z][A-Z &,'-]{3,60})$")
NEW_PARAGRAPH = re.compile(r"^(\d+(\.\d+)+\s|[-•*–]\s|\(?[a-z0-9]\)\s)")


def clean_pdf_pages(pages: list[str]) -> list[list[str]]:
    """Lines of each page without running headers, footers and page numbers, with words
    hyphenated across line breaks joined again."""
    split = [[ln.strip() for ln in re.sub(r"(\w)-\n(\w)", r"\1\2", p).splitlines()]
             for p in pages]
    # A line found on at least half the pages (and three or more) is a header or footer.
    counts = Counter(ln for page in split for ln in set(page) if ln)
    repeated = {ln for ln, n in counts.items() if len(pages) >= 3 and n >= len(pages) / 2}
    return [[ln for ln in page if ln and ln not in repeated and not PAGE_NUMBER.match(ln)]
            for page in split]


def pdf_blocks(data: bytes) -> list[Block]:
    from pypdf import PdfReader
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as e:  # pypdf raises many types for damaged files
        raise UnsupportedDocument(f"could not read the PDF: {e}") from e
    blocks, section = [], None
    for page_no, lines in enumerate(clean_pdf_pages(pages), start=1):
        paragraphs: list[str] = []
        for line in lines:
            if PDF_HEADING.match(line):
                if paragraphs:
                    blocks.append(Block(section, page_no, "\n".join(paragraphs)))
                    paragraphs = []
                section = line
            elif paragraphs and not NEW_PARAGRAPH.match(line):
                paragraphs[-1] += " " + line
            else:
                paragraphs.append(line)
        if paragraphs:
            blocks.append(Block(section, page_no, "\n".join(paragraphs)))
    return blocks


def extract(file_name: str, data: bytes) -> tuple[str | None, dict[str, str], list[Block]]:
    """Title (if the file names one), metadata and text blocks of an uploaded file."""
    suffix = Path(file_name).suffix.lower()
    if suffix == ".pdf":
        title, meta, blocks = None, {}, pdf_blocks(data)
    elif suffix in (".md", ".txt"):
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as e:
            raise UnsupportedDocument("the file is not UTF-8 text") from e
        title, meta, blocks = markdown_blocks(text)
    else:
        raise UnsupportedDocument(f"unsupported file type {suffix or '(none)'}; "
                                  f"use {', '.join(FILE_TYPES)}")
    if not any(b.text.strip() for b in blocks):
        raise UnsupportedDocument("no text could be extracted (is it a scanned PDF?)")
    return title, meta, blocks


# -- chunking ------------------------------------------------------------------------------
def unwrap(paragraph: str) -> str:
    """Join hard-wrapped lines; list items and table rows keep their own lines."""
    return re.sub(r"[ \t]*\n[ \t]*(?![-*|•])", " ", paragraph)


def _pieces(paragraph: str) -> list[str]:
    """A paragraph, or its sentences if it is too long for one chunk."""
    if len(paragraph) <= MAX_CHUNK_CHARS:
        return [paragraph]
    out, current = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
        while len(sentence) > MAX_CHUNK_CHARS:          # no sentence breaks at all
            out.append(sentence[:MAX_CHUNK_CHARS])
            sentence = sentence[MAX_CHUNK_CHARS:]
        if current and len(current) + 1 + len(sentence) > MAX_CHUNK_CHARS:
            out.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    return out + [current] if current else out


def chunk_blocks(blocks: list[Block]) -> list[Chunk]:
    """Sliding window over paragraphs, never crossing a section boundary. A chunk holds as
    many whole paragraphs as fit in MAX_CHUNK_CHARS; when one is closed, its last paragraph
    is carried into the next if short, so a rule and its context stay together."""
    chunks = []
    for block in blocks:
        paragraphs = [p for raw in re.split(r"\n\s*\n", block.text)
                      for p in _pieces(unwrap(raw.strip())) if p]
        current: list[str] = []
        for p in paragraphs:
            if current and len("\n\n".join(current + [p])) > MAX_CHUNK_CHARS:
                chunks.append(Chunk(block.section, block.page, "\n\n".join(current)))
                carry = current[-1]
                current = [carry] if len(carry) <= OVERLAP_MAX_CHARS and \
                    len(carry) + 2 + len(p) <= MAX_CHUNK_CHARS else []
            current.append(p)
        if current:
            chunks.append(Chunk(block.section, block.page, "\n\n".join(current)))
    return chunks


def embedding_text(title: str, chunk: Chunk) -> str:
    """What is embedded: the content prefixed by where it comes from, which helps short
    chunks such as a bare table match questions about their topic."""
    where = f"{title} - {chunk.section}" if chunk.section else title
    return f"{where}\n{chunk.content}"


# -- storage -------------------------------------------------------------------------------
def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def register(db: AsyncSession, *, title: str, category: str, file_name: str,
                   data: bytes, uploaded_by: int) -> Document:
    """Create the document row (status 'processing'). A document with the same title as an
    active one becomes its next version; the old one stays searchable until the new one
    has been indexed."""
    latest = await db.scalar(select(func.max(Document.version)).where(
        func.lower(Document.title) == title.lower()))
    doc = Document(title=title, category=category, file_name=file_name,
                   content_sha256=sha256(data), uploaded_by=uploaded_by,
                   version=(latest or 0) + 1, status="processing")
    db.add(doc)
    await db.flush()
    return doc


async def _no_progress(_: str) -> None:
    pass


async def index(db: AsyncSession, doc: Document, data: bytes,
                on_progress: Callable[[str], Awaitable[None]] = _no_progress) -> int:
    """Extract, chunk, embed and store `doc`, then make it the active version. Runs in the
    caller's transaction, so on failure nothing becomes visible to search. `on_progress`
    is told what is happening (for the admin console). Returns the number of chunks."""
    await on_progress("Extracting text")
    _, _, blocks = extract(doc.file_name, data)
    chunks = chunk_blocks(blocks)
    await on_progress(f"Embedding {len(chunks)} chunks")
    vectors = await asyncio.to_thread(embed_passages,
                                      [embedding_text(doc.title, c) for c in chunks])
    db.add_all(DocumentChunk(document_id=doc.id, chunk_index=i, section=c.section,
                             page=c.page, content=c.content, embedding=v)
               for i, (c, v) in enumerate(zip(chunks, vectors, strict=True)))
    await on_progress("Saving")
    await db.execute(update(Document)
                     .where(func.lower(Document.title) == doc.title.lower(),
                            Document.status == "active", Document.id != doc.id)
                     .values(status="superseded", superseded_by=doc.id))
    doc.status = "active"
    await db.flush()
    return len(chunks)


# -- command line --------------------------------------------------------------------------
async def load_directory(db: AsyncSession, directory: Path) -> list[tuple[str, str]]:
    """Index every policy file in `directory` (README files excepted) as uploaded by the
    first administrator. Files whose exact content is already active are skipped."""
    admin = await db.scalar(select(User.id).where(User.role == "admin").order_by(User.id))
    if admin is None:
        raise RuntimeError("no admin user; run `make seed` first")
    report = []
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() not in FILE_TYPES or path.stem.lower() == "readme":
            continue
        data = path.read_bytes()
        if await db.scalar(select(Document.id).where(Document.content_sha256 == sha256(data),
                                                     Document.status == "active")):
            report.append((path.name, "unchanged"))
            continue
        title, meta, _ = extract(path.name, data)
        category = meta.get("category", "other").lower()
        doc = await register(db, title=title or path.stem.replace("-", " ").title(),
                             category=category if category in CATEGORIES else "other",
                             file_name=path.name, data=data, uploaded_by=admin)
        n = await index(db, doc, data)
        report.append((path.name, f"{n} chunks, version {doc.version}"))
    await db.commit()
    return report


async def _main(directory: Path, database_url: str | None) -> None:
    from campusgpt.db import make_async_engine
    engine = make_async_engine(database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            for name, outcome in await load_directory(db, directory):
                print(f"  {name:<32} {outcome}")
    finally:
        await engine.dispose()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    load = sub.add_parser("load", help="index every policy file in a directory")
    load.add_argument("directory", type=Path)
    load.add_argument("--database-url", help="defaults to DATABASE_URL from .env")
    args = parser.parse_args(argv)
    print(f"Indexing documents in {args.directory}")
    asyncio.run(_main(args.directory, args.database_url))
    return 0


if __name__ == "__main__":
    sys.exit(main())
