"""Held-out questions: 20 questions written on 9 Nov 2026, after the fixes of 30 Oct, and
never used to change the system. They are run once per model and reported separately
(docs/evaluation/RESULTS.md, "Held-out questions"), so a failure here is reported, not
fixed and re-run.

Same format and scoring as questions.py; ids start with "x".
"""
from datetime import time

from campusgpt.evaluation.questions import (
    ATTENDANCE,
    ATTENDANCE_POLICY,
    CALCULATE,
    CLASSES,
    ELIGIBILITY,
    EXAMS_POLICY,
    FEE_POLICY,
    FEES,
    HOSTEL,
    INTEGRITY,
    SCHOLARSHIPS,
    SEARCH,
    AnyOf,
    At,
    Num,
    Question,
    Records,
    Text,
    When,
    pct,
    policy,
)


def first_class_tomorrow(r: Records) -> list:
    """Tomorrow's first class, or (on a day without classes) the next one."""
    m = (r.classes_on(1) or r.upcoming)[0]
    return [Text(m.title, m.code), At(m.starts_at.timetz().replace(tzinfo=None))]


def fee_due_dates(r: Records) -> list:
    return [AnyOf(*(When(f.due_date) for f in r.owed))]


HELDOUT: list[Question] = [
    # -- policy, English -------------------------------------------------------------------
    policy("x01", "en", "Can I leave the exam hall 20 minutes after the paper starts?",
           [Text("one hour", "1 hour", "60 minutes")], f"{EXAMS_POLICY} §3"),
    policy("x02", "en", "What happens if I submit my assignment 3 days late?",
           [Text("zero")], f"{INTEGRITY} §2"),
    policy("x03", "en", "When are admit cards released for the end-terms?",
           [Num(5)], f"{EXAMS_POLICY} §2"),
    policy("x04", "en", "Till what time can visitors meet us in the hostel?",
           [At(time(19, 0))], f"{HOSTEL} §5"),
    policy("x05", "en", "How much is the hostel security deposit?",
           [Num(10000)], f"{HOSTEL} §2"),
    policy("x06", "en", "Above what similarity score does an assignment get reviewed for "
           "plagiarism?", [Num(20)], f"{INTEGRITY} §4"),
    policy("x07", "en", "I missed my mid-term because I was sick. How long do I have to ask "
           "for a retake?", [Num(5)], f"{EXAMS_POLICY} §4"),
    policy("x08", "en", "What does a single room in the hostel cost per term?",
           [Num(60000)], f"{HOSTEL} §2"),
    # -- policy, Hinglish ------------------------------------------------------------------
    policy("x09", "hinglish", "Scholarship continue rakhne ke liye kitni attendance chahiye?",
           [Num(75)], f"{SCHOLARSHIPS} §4"),
    policy("x10", "hinglish", "Fees kitne din tak na bharun toh registration hold ho jata hai?",
           [Num(30)], f"{FEE_POLICY} §2"),
    policy("x11", "hinglish", "Ek term ka mess charge kitna hai?",
           [Num(24000)], f"{HOSTEL} §2"),
    # -- the student's records -------------------------------------------------------------
    Question("x12", "records", "en", "regular", "Show me my attendance in all my courses",
             lambda r: [pct(c.attended, c.held) for c in r.attendance], [{ATTENDANCE}]),
    Question("x13", "records", "en", "shortage", "Which course has my lowest attendance?",
             lambda r: [Text(r.lowest.title, r.lowest.code)], [{ATTENDANCE}]),
    Question("x14", "records", "en", "fees", "When was my fee payment due?",
             fee_due_dates, [{FEES}]),
    Question("x15", "records", "en", "regular", "Which programme and semester am I in?",
             lambda r: [Text(r.profile.program), Num(r.profile.semester)],
             []),                              # it is in the instructions
    Question("x16", "records", "en", "regular",
             lambda r: f"How many {r.highest.title} classes can I skip and still stay at 75%?",
             lambda r: [Num(r.highest.can_miss)], [{ATTENDANCE, CALCULATE}]),
    Question("x17", "records", "en", "regular", "What time is my first class tomorrow?",
             first_class_tomorrow, [{CLASSES}]),
    Question("x18", "records", "hinglish", "shortage",
             "meri sabse kam attendance kis subject mein hai?",
             lambda r: [Text(r.lowest.title, r.lowest.code)], [{ATTENDANCE}]),
    # -- records and rules together --------------------------------------------------------
    Question("x19", "combined", "en", "fees", "Can I see my grades while my tuition is unpaid?",
             [Text("hold", "cannot see", "can't see", "won't be able")],
             [{FEES, ELIGIBILITY}, {SEARCH}], (f"{FEE_POLICY} §2",)),
    Question("x20", "combined", "en", "shortage",
             lambda r: f"My attendance in {r.lowest.title} is short. Can I still write its "
                       "mid-term and quizzes?",
             [Text("yes", "can still", "not affected", "still take", "still write")],
             [{SEARCH, ELIGIBILITY}], (f"{ATTENDANCE_POLICY} §3",)),
]
