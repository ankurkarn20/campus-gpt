"""The evaluation: answer scoring, the question set's ground truth, the chat configurations,
retrieval metrics, the text-to-SQL baseline and the report."""
import asyncio
import json
from dataclasses import asdict
from datetime import date, time

import pytest
from sqlalchemy import func, select

from campusgpt import chat, security
from campusgpt.evaluation import report, run, text_to_sql
from campusgpt.evaluation.questions import QUESTIONS, STUDENTS, records
from campusgpt.evaluation.scoring import AnyOf, At, Num, Text, When, check, cites_expected
from campusgpt.llm import ScriptedProvider, TextChunk
from campusgpt.models import Conversation, Student
from tests.conftest import NOW, in_session


@pytest.mark.parametrize("answer, fact, expected", [
    ("You owe ₹1,60,000.00", Num(160000, 0.5), True),
    ("Attendance: 68.4%", Num(68.42), True),
    ("Attendance: 68%", Num(68.42), False),
    ("within seven days", Num(7), True),
    ("in 17 days", Num(7), False),
    ("on 2 Nov 2026", When(date(2026, 11, 2)), True),
    ("on November 2nd", When(date(2026, 11, 2)), True),
    ("on 2026-11-02 at 10:00", When(date(2026, 11, 2)), True),
    ("on 12 November", When(date(2026, 11, 2)), False),
    ("at 2 PM", At(time(14)), True),
    ("at 14:00", At(time(14)), True),
    ("at 2:30 pm", At(time(14)), False),
    ("gates close at 10:30 pm", At(time(22, 30)), True),
    ("gate raat 10:30 baje band", At(time(22, 30)), True),
    ("treated as unfair means", Text("unfair means"), True),
    ("the room is A-1011", Text("A-101"), False),
    ("₹3,500 exam fee and ₹1,60,000 tuition", AnyOf(Num(163500), [Num(160000), Num(3500)]),
     True),
])
def test_facts_are_matched_in_any_common_form(answer, fact, expected):
    assert check(answer, [fact]) == [expected]


def test_citations_of_a_clause_count_for_its_section():
    assert cites_expected(["Attendance Policy §4.2"], ("Attendance Policy §4",))
    assert not cites_expected(["Attendance Policy §41"], ("Attendance Policy §4",))


def test_retry_after_reads_the_hosted_models_wait():
    assert run.retry_after("Please try again in 7.5s.") == 8.5
    assert run.retry_after("Please try again in 12m30s.") == 751
    assert run.retry_after("rate limited") == 20


def test_the_question_set():
    assert len(QUESTIONS) == 50 and len({q.id for q in QUESTIONS}) == 50
    assert sum(q.lang == "hinglish" for q in QUESTIONS) >= 10
    assert {q.who for q in QUESTIONS} == set(STUDENTS)
    assert all(q.cites for q in QUESTIONS if q.category == "policy")


def test_every_question_has_ground_truth_for_the_demo_students(seeded, test_url):
    async def truth(db):
        out = {}
        for who, email in STUDENTS.items():
            _, st = await security.account(db, email)
            out[who] = await records(db, st.id, NOW)
        return out
    r = asyncio.run(in_session(test_url, truth))
    for q in QUESTIONS:
        facts = q.expected(r[q.who])
        assert facts and q.text(r[q.who]), q.id


def evaluate(test_url, provider, configs, only):
    async def go(db):
        return [x async for x in run.chat_eval(db, provider, "scripted", configs, NOW,
                                               lambda _, qid: qid in only)]
    return asyncio.run(in_session(test_url, go, commit=True))


def test_configurations_switch_documents_and_records_off(indexed, test_url, monkeypatch):
    from campusgpt.config import get_settings
    monkeypatch.setattr(get_settings(), "rag_prefetch_min_similarity", 0.0)  # always prefetch
    provider = ScriptedProvider([[TextChunk("…")]])
    results = evaluate(test_url, provider, ["full", "rag", "db", "plain"], {"r04"})
    tools = {r.config: r.tools for r in results}
    assert tools == {"full": ["search_university_documents", "get_my_attendance"],
                     "rag": ["search_university_documents"], "db": ["get_my_attendance"],
                     "plain": []}
    full, rag, db, plain = provider.offered
    assert "search_university_documents" in full and len(full) > 5
    assert rag == ["search_university_documents"]
    assert "search_university_documents" not in db and len(db) == len(full) - 1
    assert plain == []
    assert "You are CampusGPT" not in provider.seen[3][0]["content"]
    # The benchmark's conversations are removed afterwards.
    count = asyncio.run(in_session(test_url, lambda s: s.scalar(
        select(func.count()).select_from(Conversation)
        .where(Conversation.title.startswith(run.TITLE)))))
    assert count == 0


def test_without_documents_the_eligibility_tool_gives_no_passages(indexed, test_url):
    from campusgpt import tools

    async def go(db):
        user, _ = await security.account(db, STUDENTS["shortage"])
        ctx = tools.ToolContext(db, user.id, "student", user.student_id, NOW, documents=False)
        return await tools.execute(ctx, "check_end_term_eligibility", "{}")
    assert asyncio.run(in_session(test_url, go))["passages"] == []
    assert chat.Pipeline(documents=False).offers("check_end_term_eligibility")


def test_an_answer_with_the_facts_is_correct(seeded, test_url):
    async def can_miss(db):
        _, st = await security.account(db, STUDENTS["regular"])
        return (await records(db, st.id, NOW)).course("Computer Networks").can_miss
    n = asyncio.run(in_session(test_url, can_miss))
    right = evaluate(test_url, ScriptedProvider([[TextChunk(f"You can miss {n} classes.")]]),
                     ["db"], {"r04"})
    wrong = evaluate(test_url, ScriptedProvider([[TextChunk(f"You can miss {n + 3}.")]]),
                     ["db"], {"r04"})
    assert right[0].correct and right[0].tools_ok and not wrong[0].correct


def test_retrieval_metrics(indexed, test_url):
    results = asyncio.run(in_session(test_url, lambda db: run.retrieval_eval(db, ("hybrid",))))
    assert len(results) == sum(q.category == "policy" for q in QUESTIONS)
    [all_, *_] = run.retrieval_summary(results)
    assert all_["n"] == len(results) and all_["hit@4"] > 0.8


def test_read_only_sql_cannot_change_the_database(seeded, test_url):
    async def go(db):
        with pytest.raises(Exception, match="read-only"):
            await text_to_sql.run_read_only(db, "DROP TABLE students")
        rows = await text_to_sql.run_read_only(db, "SELECT count(*) AS n FROM students")
        return rows, await db.scalar(select(func.count()).select_from(Student))
    rows, n = asyncio.run(in_session(test_url, go))
    assert rows == [{"n": n}] and n > 0


def test_the_text_to_sql_baseline_is_judged_like_campusgpt(seeded, test_url):
    attack = [a for a in security.ATTACKS if a.id == "by_roll_no"]
    leaky = ScriptedProvider([[TextChunk(
        "```sql\nSELECT s.roll_no, b.balance FROM students s JOIN invoice_balances b "
        "ON b.student_id = s.id\n```")]])

    async def go(db, provider):
        user, _ = await security.account(db, security.ATTACKER)
        return await text_to_sql.run_attacks(db, provider, NOW, attack), user.student_id
    [leaked], me = asyncio.run(in_session(test_url, lambda db: go(db, leaky)))
    assert leaked.verdict == "leaked" and leaked.rows == text_to_sql.MAX_ROWS
    assert leaked.leaks[-1].startswith("sql returned data of ")
    own = ScriptedProvider([[TextChunk(
        f"```sql\nSELECT balance FROM invoice_balances WHERE student_id = {me}\n```")]])
    [kept], _ = asyncio.run(in_session(test_url, lambda db: go(db, own)))
    assert kept.verdict == "blocked" and kept.error is None


def test_report_is_built_from_the_results(tmp_path):
    q = QUESTIONS[0]
    result = run.ChatResult(q.id, q.category, q.lang, "full", "m", q.ask, "75% [Attendance "
                            "Policy §2]", ["75"], [True], True, ["search_university_documents"],
                            True, [{"cite": "Attendance Policy §2", "verified": True}], True,
                            True, 1.5)
    (tmp_path / "chat-local.json").write_text(json.dumps(
        {"model": "m", "run_at": "x", "results": [asdict(result)]}))
    report.write(tmp_path, tmp_path / "RESULTS.md")
    text = (tmp_path / "RESULTS.md").read_text()
    assert "| m | Full CampusGPT | 1 | 100% |" in text and "| p01 |" in text
