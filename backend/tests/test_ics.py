"""Calendar export (.ics): RFC 5545 formatting and the student's events."""
from datetime import datetime, timedelta

import icalendar
import pytest

from campusgpt.ics import escape, fold
from tests.conftest import ADMIN, NOW, SHORTAGE, login
from tests.test_student import dashboard


@pytest.mark.parametrize("text", [
    "SUMMARY:" + "x" * 200,
    "DESCRIPTION:" + "उपस्थिति कम है " * 20,      # multi-byte characters near the boundary
    "SUMMARY:short",
])
def test_folding_keeps_lines_within_75_octets(text):
    folded = fold(text)
    assert all(len(line.encode()) <= 75 for line in folded.split("\r\n"))
    assert folded.replace("\r\n ", "") == text


def test_text_is_escaped():
    assert escape("a,b;c\\d\ne") == "a\\,b\\;c\\\\d\\ne"


def export(client):
    r = client.get("/api/student/calendar.ics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/calendar")
    assert 'filename="campusgpt.ics"' in r.headers["content-disposition"]
    return r.text


def test_export_contains_the_students_events(client):
    data = dashboard(client, SHORTAGE)
    text = export(client)
    assert "\n" not in text.replace("\r\n", "")                # CRLF only

    cal = icalendar.Calendar.from_ical(text)
    events = list(cal.walk("VEVENT"))
    exams = data["exams"]
    todo = [a for a in data["assignments"] if not a["submitted"]]
    fees = [f for f in data["fees"] if float(f["balance"]) > 0
            and f["due_date"] >= NOW.date().isoformat()
            and f["status"] not in ("waived", "cancelled")]
    classes = [e for e in events if str(e["DESCRIPTION"]).startswith("Class with")]
    assert len(events) - len(classes) == len(exams) + len(todo) + len(fees) > 0
    assert len({str(e["UID"]) for e in events}) == len(events)
    # Every remaining class this term: weekdays only, from the next class on.
    term_end = datetime(2026, 11, 22, 23, 59, tzinfo=NOW.tzinfo)
    starts = sorted(e["DTSTART"].dt for e in classes)
    assert starts[0] == datetime.fromisoformat(data["next_classes"][0]["starts_at"])
    assert all(NOW < t < term_end and t.astimezone(NOW.tzinfo).weekday() < 5 for t in starts)
    # classes_left counts from the start of today (this morning's classes are not recorded
    # until tomorrow); the calendar lists only classes not yet started.
    earlier_today = sum(1 for t in data["timetable"] if t["weekday"] == NOW.weekday()
                        and t["starts_at"] < NOW.strftime("%H:%M:%S"))
    assert len(classes) == sum(c["classes_left"] for c in data["attendance"]) - earlier_today

    first = exams[0]
    [ev] = [e for e in events
            if e["DTSTART"].dt == datetime.fromisoformat(first["starts_at"])
            and str(e["SUMMARY"]).endswith(f"({first['code']})")]
    assert str(ev["LOCATION"]) == f"Room {first['room']}"
    assert ev["DTEND"].dt - ev["DTSTART"].dt == timedelta(minutes=first["duration_minutes"])
    # Reminders for exams, deadlines and fees; none for every single class.
    assert all(bool(e.walk("VALARM")) == (e not in classes) for e in events)


def test_export_is_stable_and_names_no_one(client):
    data = dashboard(client, SHORTAGE)
    first, second = export(client), export(client)
    uids = [line for line in first.split("\r\n") if line.startswith("UID:")]
    assert uids == [line for line in second.split("\r\n") if line.startswith("UID:")]
    # Nothing that identifies the student is written into the file.
    roll_no = client.get("/api/auth/me").json()["student"]["roll_no"]
    assert roll_no not in first and SHORTAGE not in first
    assert data["exams"]


def test_only_students_export(client):
    assert client.get("/api/student/calendar.ics").status_code == 401
    login(client, ADMIN)
    assert client.get("/api/student/calendar.ics").status_code == 403
