"""Tests for the schema, the synthetic data generator, the loader and the validation checks."""
import math
from datetime import date

import numpy as np
import psycopg
import pytest
from argon2 import PasswordHasher

from campusgpt.seed.generate import generate, term_for
from campusgpt.seed.load import load
from campusgpt.seed.validate import validate
from tests.conftest import AS_OF, DEMO_PASSWORD, SEED, STUDENTS


def student_by_email(conn, email):
    return conn.execute("SELECT s.id FROM students s JOIN users u ON u.id = s.user_id "
                        "WHERE u.email = %s", (email,)).fetchone()[0]


# -- generator ---------------------------------------------------------------------------
def test_same_inputs_give_identical_data(dataset):
    again = generate(STUDENTS, SEED, AS_OF, DEMO_PASSWORD)
    for table, rows in dataset.rows.items():
        if table == "users":  # password hashes are salted, everything else must match
            rows = [r[:2] + r[3:] for r in rows]
            other = [r[:2] + r[3:] for r in again.rows[table]]
        else:
            other = again.rows[table]
        assert rows == other, table
    for (e1, s1, m1), (e2, s2, m2) in zip(dataset.attendance, again.attendance, strict=True):
        assert e1 == e2 and s1 == s2 and np.array_equal(m1, m2)


def test_different_seed_gives_different_data(dataset):
    other = generate(STUDENTS, SEED + 1, AS_OF, DEMO_PASSWORD)
    assert other.rows["students"] != dataset.rows["students"]


@pytest.mark.parametrize("as_of", [date(2026, 7, 25), date(2026, 12, 1), date(2026, 2, 1)])
def test_as_of_outside_teaching_window_is_rejected(as_of):
    with pytest.raises(ValueError, match="must fall between"):
        term_for(as_of)


def test_even_term_generates_even_semesters():
    ds = generate(150, SEED, date(2026, 3, 10), DEMO_PASSWORD)
    assert ds.term.code == "2026-EVEN"
    assert {row[5] for row in ds.rows["students"]} <= {2, 4, 6, 8}


# -- loaded database -----------------------------------------------------------------------
def test_all_validation_checks_pass(seeded):
    failures = {name: n for name, n in validate(seeded).items() if n}
    assert failures == {}


def test_row_counts_match_the_dataset(conn, dataset):
    for table, n in dataset.counts().items():
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == n, table


def test_reloading_replaces_data_and_resets_sequences(seeded, dataset):
    load(seeded, dataset)
    with psycopg.connect(seeded) as conn:
        assert conn.execute("SELECT count(*) FROM students").fetchone()[0] == STUDENTS
        # A new row without an explicit id must get the next free id, not collide.
        new_id = conn.execute("INSERT INTO users (email, role) VALUES ('new@x.example', "
                              "'admin') RETURNING id").fetchone()[0]
        assert new_id == len(dataset.rows["users"]) + 1
        conn.rollback()


def test_attendance_view_matches_raw_records(conn):
    sid = student_by_email(conn, "student.regular@demo.campusgpt.example")
    view = conn.execute("SELECT enrollment_id, classes_attended, classes_held "
                        "FROM attendance_summary WHERE student_id = %s ORDER BY 1",
                        (sid,)).fetchall()
    raw = conn.execute("SELECT e.id, count(*) FILTER (WHERE a.present), count(*) "
                       "FROM enrollments e JOIN attendance a ON a.enrollment_id = e.id "
                       "WHERE e.student_id = %s GROUP BY e.id ORDER BY 1", (sid,)).fetchall()
    assert view == raw and len(view) == 5


def test_boundary_attendance_cases_exist(conn):
    """Some enrollments sit exactly at the 75% threshold and some one class below it."""
    rows = conn.execute("SELECT classes_attended, classes_held FROM attendance_summary"
                        ).fetchall()
    at_threshold = [r for r in rows if r[0] == math.ceil(0.75 * r[1])]
    just_below = [r for r in rows if r[0] == math.ceil(0.75 * r[1]) - 1]
    assert at_threshold and just_below


# -- demo accounts --------------------------------------------------------------------------
def test_demo_accounts_can_log_in_and_others_cannot(conn):
    hasher = PasswordHasher()
    rows = conn.execute("SELECT email, password_hash FROM users").fetchall()
    demo = {email: h for email, h in rows if email.endswith("@demo.campusgpt.example")}
    assert len(demo) == 4
    assert all(hasher.verify(h, DEMO_PASSWORD) for h in demo.values())
    assert all(h is None for email, h in rows if email not in demo)


def test_shortage_demo_student_is_short_only_in_dbms(conn):
    sid = student_by_email(conn, "student.shortage@demo.campusgpt.example")
    rows = dict(conn.execute(
        "SELECT c.title, a.percentage FROM attendance_summary a "
        "JOIN course_offerings o ON o.id = a.offering_id JOIN courses c ON c.id = o.course_id "
        "WHERE a.student_id = %s", (sid,)).fetchall())
    assert rows.pop("Database Management Systems") < 75
    assert all(p >= 75 for p in rows.values())


def test_fees_demo_student_has_overdue_tuition(conn):
    sid = student_by_email(conn, "student.fees@demo.campusgpt.example")
    status = conn.execute("SELECT payment_status FROM invoice_balances WHERE student_id = %s "
                          "AND description LIKE 'Tuition%%'", (sid,)).fetchone()[0]
    assert status == "overdue"


def test_regular_demo_student_has_paid_and_has_work_due_this_week(conn):
    sid = student_by_email(conn, "student.regular@demo.campusgpt.example")
    statuses = {r[0] for r in conn.execute(
        "SELECT payment_status FROM invoice_balances WHERE student_id = %s", (sid,))}
    assert statuses == {"paid"}
    due_soon = conn.execute(
        "SELECT count(*) FROM assignments a JOIN enrollments e ON e.offering_id = a.offering_id "
        "WHERE e.student_id = %s AND a.due_at::date BETWEEN %s AND %s + 7",
        (sid, AS_OF, AS_OF)).fetchone()[0]
    assert due_soon >= 1


# -- database constraints ----------------------------------------------------------------------
@pytest.mark.parametrize("statement", [
    # marks above the assignment maximum (enforced by trigger)
    "UPDATE submissions SET marks = 1000 WHERE id = (SELECT min(id) FROM submissions)",
    # a student enrolled twice in the same offering
    ("INSERT INTO enrollments (student_id, offering_id) "
    "SELECT student_id, offering_id FROM enrollments LIMIT 1"),
    # negative invoice amount
    "UPDATE invoices SET amount = -1 WHERE id = 1",
    # unknown role
    "UPDATE users SET role = 'superuser' WHERE id = 1",
    # attendance for a session that does not exist
    "INSERT INTO attendance VALUES (999999999, 1, true)",
])
def test_database_rejects_invalid_data(conn, statement):
    with pytest.raises(psycopg.errors.IntegrityError):
        conn.execute(statement)
