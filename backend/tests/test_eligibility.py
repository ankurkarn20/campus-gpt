"""End-term eligibility: the attendance forecast, the term calendar, fee holds and the tool."""
from datetime import date

import pytest

from campusgpt.calc import Outlook, attendance_outlook
from campusgpt.llm import ScriptedProvider, TextChunk, ToolCall
from campusgpt.term import classes_left, term_for
from tests.conftest import AS_OF, FEES, REGULAR, SHORTAGE, login
from tests.test_chat import ask, of, use
from tests.test_student import dashboard


# -- arithmetic ------------------------------------------------------------------------------
@pytest.mark.parametrize("attended, held, left, expected", [
    (0, 0, 0, Outlook("safe", 0, 100.0)),
    (40, 40, 10, Outlook("safe", 0, 100.0)),          # 40/50 even missing all ten
    (30, 40, 0, Outlook("safe", 0, 75.0)),            # exactly 75% at the end
    (23, 34, 17, Outlook("on_track", 16, 78.43)),     # the shortage demo student's DBMS
    (30, 40, 10, Outlook("on_track", 8, 80.0)),       # 38/50 = 76%; 37/50 = 74% is not enough
    (29, 40, 0, Outlook("condonation_needed", 0, 72.5)),
    (19, 32, 18, Outlook("condonation_needed", 18, 74.0)),
    (13, 20, 0, Outlook("condonation_needed", 0, 65.0)),  # exactly the condonation floor
    (12, 20, 0, Outlook("debarred", 0, 60.0)),
    (10, 30, 10, Outlook("debarred", 10, 50.0)),
])
def test_attendance_outlook(attended, held, left, expected):
    assert attendance_outlook(attended, held, left) == expected


# -- calendar --------------------------------------------------------------------------------
def test_teaching_days_skip_weekends_holidays_mid_terms_and_exams():
    term = term_for(date(2026, 10, 13))
    assert term.code == "2026-ODD" and term.last_teaching_day == date(2026, 11, 22)
    assert term.is_teaching_day(date(2026, 11, 20))
    assert not term.is_teaching_day(date(2026, 10, 2))    # Gandhi Jayanti
    assert not term.is_teaching_day(date(2026, 9, 9))     # mid-term week
    assert not term.is_teaching_day(date(2026, 11, 21))   # Saturday
    assert not term.is_teaching_day(date(2026, 11, 23))   # end-term exams
    assert classes_left(term, [0, 2, 4], date(2026, 11, 16)) == 3    # Mon, Wed, Fri


def test_forecast_agrees_with_the_generated_timetable(conn):
    """Classes held so far plus classes left must equal the whole term's classes on the
    same weekdays: the generator and the forecast share one calendar."""
    term = term_for(AS_OF)
    rows = conn.execute("""
        SELECT offering_id, count(*), array_agg(DISTINCT extract(isodow FROM held_on)::int - 1)
        FROM class_sessions GROUP BY offering_id""").fetchall()
    assert rows
    for _, held, weekdays in rows:
        assert held + classes_left(term, weekdays, AS_OF) == \
            classes_left(term, weekdays, term.start)


# -- the demo students -----------------------------------------------------------------------
def test_regular_student_is_eligible_everywhere(client):
    e = dashboard(client, REGULAR)["eligibility"]
    assert e["term"] == "2026-ODD" and e["admit_card_ok"] and e["fee_holds"] == []
    assert {c["status"] for c in e["courses"]} <= {"safe", "on_track"}
    assert e["admit_cards_from"] == "2026-11-18" and e["end_term_starts"] == "2026-11-23"


def test_shortage_student_must_attend_almost_every_dbms_class(client):
    e = dashboard(client, SHORTAGE)["eligibility"]
    dbms = next(c for c in e["courses"] if c["title"] == "Database Management Systems")
    assert dbms["status"] == "on_track"
    assert dbms["attend_at_least"] == dbms["classes_left"] - 1
    # The exam fee is unpaid but not yet overdue: it still blocks the admit card.
    [hold] = e["fee_holds"]
    assert hold["description"].startswith("End-term examination fee") and not hold["overdue"]
    assert not e["admit_card_ok"]


def test_unpaid_tuition_blocks_the_admit_card(client):
    e = dashboard(client, FEES)["eligibility"]
    holds = {h["description"].split(" 20")[0]: h for h in e["fee_holds"]}
    assert set(holds) == {"Tuition fee", "End-term examination fee"}
    assert holds["Tuition fee"]["overdue"] and not e["admit_card_ok"]


# -- the chat tool ---------------------------------------------------------------------------
def test_eligibility_tool_returns_the_rules_it_applies(app, client, indexed):
    use(app, ScriptedProvider([
        [ToolCall("c1", "check_end_term_eligibility", '{"course": "DBMS"}')],
        [TextChunk("Attend 16 of the next 17 DBMS classes [Attendance Policy §3.1], and pay "
                   "the exam fee first [Examination Regulations §2.2].")],
    ]))
    login(client, SHORTAGE)
    events = ask(client, "Can I sit my DBMS end-term?")

    assert of(events, "status") == [{"text": "Checking your end-term eligibility"}]
    tool = of(events, "tool")[0]
    assert tool["ok"] and [c["code"] for c in tool["result"]["courses"]] == ["CSE301"]
    cites = {p["cite"] for p in tool["result"]["passages"]}
    # DBMS can still reach 75%, so only the examination rules apply.
    assert cites == {"Examination Regulations §2"}
    assert of(events, "done")[0]["citations"] == [
        {"cite": "Attendance Policy §3.1", "verified": False},
        {"cite": "Examination Regulations §2.2", "verified": True}]


def test_attendance_rules_are_included_when_condonation_is_needed(app, client, indexed):
    use(app, ScriptedProvider([[ToolCall("c1", "check_end_term_eligibility", "{}")],
                               [TextChunk("…")]]))
    login(client, FEES)
    result = of(ask(client, "Am I eligible for my end-term exams?"), "tool")[0]["result"]
    assert "condonation_needed" in {c["status"] for c in result["courses"]}
    cites = {p["cite"] for p in result["passages"]}
    assert {"Attendance Policy §3", "Attendance Policy §4"} <= cites


def test_summary_states_what_to_do_in_words(client):
    e = dashboard(client, SHORTAGE)["eligibility"]
    assert e["summary"].startswith("Not eligible yet: admit cards (issued from 18 Nov)")
    assert "(1) pay ₹3,500.00 End-term examination fee 2026-ODD" in e["summary"]
    assert "(2) Database Management Systems: eligible only by attending" in e["summary"]
    assert ".." not in e["summary"]
    assert dashboard(client, REGULAR)["eligibility"]["summary"].startswith(
        "Eligible for all end-term exams")
