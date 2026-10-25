"""The student dashboard: correct figures, the weekly summary, roles and isolation."""
from decimal import Decimal

import pytest

from campusgpt.calc import classes_needed
from campusgpt.student import rupees
from tests.conftest import ADMIN, FEES, REGULAR, SHORTAGE, login


def dashboard(client, email):
    login(client, email)
    r = client.get("/api/student/dashboard")
    assert r.status_code == 200
    return r.json()


def student_id(conn, email):
    return conn.execute("SELECT s.id FROM students s JOIN users u ON u.id = s.user_id "
                        "WHERE u.email = %s", (email,)).fetchone()[0]


def test_requires_a_logged_in_student(client):
    assert client.get("/api/student/dashboard").status_code == 401
    login(client, ADMIN)
    assert client.get("/api/student/dashboard").status_code == 403


@pytest.mark.parametrize("email", [REGULAR, SHORTAGE, FEES])
def test_attendance_matches_the_database_for_that_student_only(client, conn, email):
    rows = conn.execute(
        "SELECT c.code, a.classes_held, a.classes_attended FROM attendance_summary a "
        "JOIN course_offerings o ON o.id = a.offering_id JOIN courses c ON c.id = o.course_id "
        "WHERE a.student_id = %s ORDER BY c.code", (student_id(conn, email),)).fetchall()
    got = [(c["code"], c["held"], c["attended"]) for c in dashboard(client, email)["attendance"]]
    assert got == rows


def test_attendance_shortage_is_flagged_with_classes_needed(client):
    d = dashboard(client, SHORTAGE)
    short = [c for c in d["attendance"] if c["status"] == "short"]
    assert [c["title"] for c in short] == ["Database Management Systems"]
    c = short[0]
    assert c["percentage"] < 75 and c["can_miss"] == 0
    assert c["classes_needed"] == classes_needed(c["attended"], c["held"]) > 0
    assert any(i["kind"] == "attendance_short" for i in d["this_week"])


def test_overdue_fee_tops_the_weekly_summary(client):
    d = dashboard(client, FEES)
    assert any(f["status"] == "overdue" and "Tuition" in f["description"] for f in d["fees"])
    assert d["this_week"][0]["kind"] == "fee_overdue"


def test_regular_student_has_nothing_alarming(client):
    d = dashboard(client, REGULAR)
    assert all(c["status"] != "short" for c in d["attendance"])
    assert not any(f["status"] == "overdue" for f in d["fees"])
    assert {i["kind"] for i in d["this_week"]} <= {"exam", "assignment", "fee_due"}


def test_upcoming_items_are_in_the_future_and_sorted(client):
    d = dashboard(client, SHORTAGE)
    exams = [e["starts_at"] for e in d["exams"]]
    due = [a["due_at"] for a in d["assignments"]]
    assert exams == sorted(exams) and due == sorted(due)
    assert all(t >= d["today"] for t in exams + due)


def test_notices_are_for_everyone_or_the_students_department(client, conn):
    dept = conn.execute(
        "SELECT d.code FROM students s JOIN programs p ON p.id = s.program_id "
        "JOIN departments d ON d.id = p.department_id WHERE s.id = %s",
        (student_id(conn, SHORTAGE),)).fetchone()[0]
    notices = dashboard(client, SHORTAGE)["notices"]
    assert notices and {n["audience"] for n in notices} <= {"all", dept}


@pytest.mark.parametrize("amount,text", [
    ("0", "₹0.00"), ("999.5", "₹999.50"), ("3500", "₹3,500.00"),
    ("160000", "₹1,60,000.00"), ("12345678.9", "₹1,23,45,678.90"),
])
def test_rupees_use_indian_grouping(amount, text):
    assert rupees(Decimal(amount)) == text
