"""The benchmark question set: 50 questions, English and Hinglish, over the three demo
students.

Answers to policy questions are fixed by the synthetic documents (docs/policies). Answers
about a student's records are computed from the database when the benchmark runs (the
data is generated relative to the day it is seeded), with the same functions the
dashboard uses; the chat must reach them through its tools.

Each question lists the facts a correct answer must contain, the tools a correct pipeline
calls (each entry is a set of alternatives, any one of which will do), and the sections
an answer should cite. Questions tagged `regression` reproduce failures found when the
system was tested by hand (docs/PLAN.md, 2026-10-27).
"""
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from campusgpt import student
from campusgpt.evaluation.scoring import AnyOf, At, Fact, Num, Text, When
from campusgpt.student import (
    AssignmentDue,
    ClassMeeting,
    ClassSlot,
    CourseAttendance,
    Eligibility,
    Fee,
    Profile,
    UpcomingExam,
)

STUDENTS = {"regular": "student.regular@demo.campusgpt.example",
            "shortage": "student.shortage@demo.campusgpt.example",
            "fees": "student.fees@demo.campusgpt.example"}

ATTENDANCE, CALCULATE = "get_my_attendance", "calculate_attendance_requirement"
SEARCH, ELIGIBILITY = "search_university_documents", "check_end_term_eligibility"
CLASSES, EXAMS, FEES = "get_my_classes", "get_my_exams", "get_my_fee_status"
ASSIGNMENTS, SUMMARY, PROFILE = "get_my_assignments", "get_my_weekly_summary", "get_my_profile"

ATTENDANCE_POLICY, EXAMS_POLICY = "Attendance Policy", "Examination Regulations"
FEE_POLICY, HOSTEL, SCHOLARSHIPS = "Fee Payment and Refund Policy", "Hostel Rules", \
    "Scholarship Scheme"
INTEGRITY = "Academic Integrity Policy"


@dataclass
class Records:
    """One demo student's records as of `now`: the ground truth for record questions."""
    now: datetime
    profile: Profile
    attendance: list[CourseAttendance]
    exams: list[UpcomingExam]
    assignments: list[AssignmentDue]
    fees: list[Fee]
    timetable: list[ClassSlot]
    upcoming: list[ClassMeeting]          # every remaining class this term
    eligibility: Eligibility

    def course(self, title: str) -> CourseAttendance:
        [c] = [c for c in self.attendance if c.title.lower() == title.lower()]
        return c

    @property
    def lowest(self) -> CourseAttendance:
        return min(self.attendance, key=lambda c: c.percentage)

    @property
    def highest(self) -> CourseAttendance:
        return max(self.attendance, key=lambda c: c.percentage)

    @property
    def owed(self) -> list[Fee]:
        return [f for f in self.fees
                if f.balance > 0 and f.status not in ("waived", "cancelled")]

    def classes_on(self, offset_days: int) -> list[ClassMeeting]:
        day = self.now.date() + timedelta(days=offset_days)
        return [m for m in self.upcoming if m.date == day]


async def records(db: AsyncSession, student_id: int, now: datetime) -> Records:
    today = now.date()
    timetable = await student.timetable(db, student_id)
    return Records(
        now, await student.profile(db, student_id),
        await student.attendance(db, student_id, today),
        await student.upcoming_exams(db, student_id, now),
        await student.assignments_due(db, student_id, now),
        await student.fees(db, student_id, today), timetable,
        student.upcoming_classes(timetable, now, 1000),
        await student.eligibility(db, student_id, today))


Facts = list[Fact] | Callable[[Records], list[Fact]]
Ask = str | Callable[[Records], str]


@dataclass
class Question:
    id: str
    category: str          # policy | records | combined
    lang: str              # en | hinglish
    who: str               # key of STUDENTS
    ask: Ask
    facts: Facts
    tools: list[set[str]] = field(default_factory=list)
    cites: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    def text(self, r: Records) -> str:
        return self.ask(r) if callable(self.ask) else self.ask

    def expected(self, r: Records) -> list[Fact]:
        return self.facts(r) if callable(self.facts) else self.facts


def policy(id, lang, ask, facts, *cites, who="regular", tags=()) -> Question:
    return Question(id, "policy", lang, who, ask, facts, [{SEARCH}], cites, tags)


def pct(attended: int, held: int) -> Num:
    return Num(round(100 * attended / held, 2))


def rupees(amount: Decimal) -> Num:
    return Num(float(amount), tolerance=0.5)


def total_owed(r: Records) -> Fact:
    return AnyOf(rupees(sum(f.balance for f in r.owed)), [rupees(f.balance) for f in r.owed])


def next_class(r: Records) -> list[Fact]:
    m = r.upcoming[0]
    return [Text(m.title, m.code), At(m.starts_at.timetz().replace(tzinfo=None))]


def tomorrow(r: Records) -> list[Fact]:
    """Tomorrow's classes, or (on a day without classes) the next one."""
    meetings = r.classes_on(1)
    if not meetings:
        return [Text(r.upcoming[0].title, r.upcoming[0].code)]
    return [Text(m.title, m.code) for m in meetings]


def due_this_week(r: Records) -> list[Fact]:
    week = [a for a in r.assignments
            if not a.submitted and a.due_at <= r.now + timedelta(days=7)]
    return [Text(a.course, a.code) for a in week]


def next_exam(r: Records) -> list[Fact]:
    e = r.exams[0]
    return [When(e.starts_at.date()), Text(e.title, e.code)]


def after_missing(r: Records, title: str, n: int) -> Num:
    c = r.course(title)
    return pct(c.attended, c.held + n)


QUESTIONS: list[Question] = [
    # -- policy, English -------------------------------------------------------------------
    policy("p01", "en", "What is the minimum attendance I need in each course?",
           [Num(75)], f"{ATTENDANCE_POLICY} §2"),
    policy("p02", "en", "What is the lowest attendance that can be condoned?",
           [Num(65)], f"{ATTENDANCE_POLICY} §4"),
    policy("p03", "en", "How soon after returning to classes must I apply for condonation?",
           [Num(7)], f"{ATTENDANCE_POLICY} §4"),
    policy("p04", "en", "For how many courses can attendance be condoned in one term?",
           [Num(2)], f"{ATTENDANCE_POLICY} §4"),
    policy("p05", "en", "Within how many days must I report attendance that was recorded "
           "wrongly?", [Num(7)], f"{ATTENDANCE_POLICY} §5"),
    policy("p06", "en", "How much does re-evaluation of an answer script cost?",
           [Num(1000)], f"{EXAMS_POLICY} §6"),
    policy("p07", "en", "How many days do I have to apply for re-evaluation?",
           [Num(7)], f"{EXAMS_POLICY} §6"),
    policy("p08", "en", "What is the fee for a supplementary exam?",
           [Num(1500)], f"{EXAMS_POLICY} §5"),
    policy("p09", "en", "What is the minimum pass mark in a course?",
           [Num(40)], f"{EXAMS_POLICY} §1"),
    policy("p10", "en", "How late can I enter the exam hall after the exam starts?",
           [Num(30)], f"{EXAMS_POLICY} §3"),
    policy("p11", "en", "What happens if I am caught with my phone in the exam hall?",
           [Text("unfair means")], f"{EXAMS_POLICY} §3", f"{INTEGRITY} §3", f"{INTEGRITY} §5"),
    # A paraphrase: the document says "re-evaluation", the question "rechecked".
    policy("p12", "en", "How do I get my answer sheet rechecked after the results?",
           [Num(1000), Num(7)], f"{EXAMS_POLICY} §6", tags=("paraphrase",)),
    policy("p13", "en", "What is the late fee for paying tuition after the due date?",
           [Num(100), Num(5000)], f"{FEE_POLICY} §2"),
    policy("p14", "en", "How much is the end-term examination fee?",
           [Num(3500)], f"{FEE_POLICY} §1"),
    policy("p15", "en", "If I withdraw within 15 days of the term starting, how much of the "
           "tuition fee is refunded?", [Num(80)], f"{FEE_POLICY} §5"),
    policy("p16", "en", "Can I pay my tuition fee in instalments?",
           [Num(50), Num(60)], f"{FEE_POLICY} §3"),
    policy("p17", "en", "What time do the hostel gates close?",
           [At(time(22, 30))], f"{HOSTEL} §3"),
    policy("p18", "en", "How far in advance do I need to apply for hostel leave?",
           [Num(24)], f"{HOSTEL} §4"),
    policy("p19", "en", "What CGPA do I need for the merit-cum-means scholarship?",
           [Num(8)], f"{SCHOLARSHIPS} §2"),
    policy("p20", "en", "What is the penalty for submitting an assignment late?",
           [Num(10), Num(48)], f"{INTEGRITY} §2"),
    # -- policy, Hinglish ------------------------------------------------------------------
    policy("h01", "hinglish", "Exam dene ke liye kitni attendance chahiye?",
           [Num(75)], f"{ATTENDANCE_POLICY} §2", f"{ATTENDANCE_POLICY} §3",
           f"{EXAMS_POLICY} §2"),
    policy("h02", "hinglish", "Re-evaluation ki fees kitni hai?",
           [Num(1000)], f"{EXAMS_POLICY} §6"),
    policy("h03", "hinglish", "Hostel ka gate kitne baje band hota hai?",
           [At(time(22, 30))], f"{HOSTEL} §3"),
    policy("h04", "hinglish", "Tuition fees late bharne pe kitna fine lagta hai?",
           [Num(100), Num(5000)], f"{FEE_POLICY} §2"),
    policy("h05", "hinglish", "Supplementary exam ki fees kya hai?",
           [Num(1500)], f"{EXAMS_POLICY} §5"),
    policy("h06", "hinglish", "Agar exam hall mein phone pakda gaya toh kya hoga?",
           [Text("unfair means")], f"{EXAMS_POLICY} §3", f"{INTEGRITY} §3", f"{INTEGRITY} §5"),
    # -- the student's records, English ----------------------------------------------------
    Question("r01", "records", "en", "regular", "What is my attendance in Machine Learning?",
             lambda r: [pct(r.course("Machine Learning").attended,
                            r.course("Machine Learning").held)], [{ATTENDANCE}]),
    Question("r02", "records", "en", "shortage", "Which of my courses are below 75% attendance?",
             lambda r: [Text(c.title, c.code) for c in r.attendance if c.status == "short"],
             [{ATTENDANCE}]),
    Question("r03", "records", "en", "shortage",
             lambda r: f"How many classes in a row do I need to attend in {r.lowest.title} "
                       "to get back to 75%?",
             lambda r: [Num(r.lowest.classes_needed)], [{ATTENDANCE, CALCULATE, ELIGIBILITY}]),
    Question("r04", "records", "en", "regular", "how many holidays can i take in computer network",
             lambda r: [Num(r.course("Computer Networks").can_miss)], [{ATTENDANCE, CALCULATE}],
             tags=("regression",)),
    Question("r05", "records", "en", "shortage",
             lambda r: f"If I miss the next 2 classes of {r.highest.title}, what will my "
                       "attendance be?",
             lambda r: [after_missing(r, r.highest.title, 2)], [{CALCULATE}]),
    Question("r06", "records", "en", "regular", "When is my next exam?", next_exam, [{EXAMS}]),
    Question("r07", "records", "en", "fees", "How much fee do I still owe?",
             lambda r: [total_owed(r)], [{FEES}]),
    Question("r08", "records", "en", "regular", "Which assignments are due this week?",
             due_this_week, [{ASSIGNMENTS, SUMMARY}]),
    Question("r09", "records", "en", "regular", "next class when", next_class, [{CLASSES}],
             tags=("regression",)),
    Question("r10", "records", "en", "regular", "where is my compiler design class",
             lambda r: [Text(s.room) for s in r.timetable if s.title == "Compiler Design"],
             [{CLASSES}], tags=("regression",)),
    Question("r11", "records", "en", "fees", "Are any of my fees overdue?",
             lambda r: [rupees(f.balance) for f in r.owed if f.status == "overdue"], [{FEES}]),
    Question("r12", "records", "en", "regular", "What is my roll number?",
             lambda r: [Text(r.profile.roll_no)], []),        # it is in the instructions
    # -- the student's records, Hinglish ---------------------------------------------------
    Question("k01", "records", "hinglish", "shortage", "DBMS mein meri attendance kitni hai?",
             lambda r: [pct(r.course("Database Management Systems").attended,
                            r.course("Database Management Systems").held)], [{ATTENDANCE}]),
    Question("k02", "records", "hinglish", "regular", "kal kaunsi classes hain?", tomorrow,
             [{CLASSES}]),
    Question("k03", "records", "hinglish", "fees", "mera kitna fees baaki hai?",
             lambda r: [total_owed(r)], [{FEES}]),
    Question("k04", "records", "hinglish", "regular",
             "Computer Networks mein kitni chutti le sakta hoon?",
             lambda r: [Num(r.course("Computer Networks").can_miss)], [{ATTENDANCE, CALCULATE}],
             tags=("regression",)),
    Question("k05", "records", "hinglish", "shortage", "agla exam kab hai?", next_exam,
             [{EXAMS}]),
    # -- records and rules together --------------------------------------------------------
    Question("c01", "combined", "en", "shortage", "Can I sit all my end-term exams?",
             lambda r: [Text(r.lowest.title, r.lowest.code), Num(r.lowest.classes_left),
                        *([rupees(sum(f.balance for f in r.owed))] if r.owed else [])],
             [{ELIGIBILITY}], (f"{EXAMS_POLICY} §2",)),
    Question("c02", "combined", "en", "fees", "Will I get my admit card?",
             lambda r: [rupees(f.balance) for f in r.owed], [{ELIGIBILITY, FEES}],
             (f"{EXAMS_POLICY} §2",)),
    Question("c03", "combined", "en", "regular", "Am I eligible for my end-term exams?",
             [Text("yes", "eligible for all", "you are eligible", "you're eligible",
                   "you can sit")], [{ELIGIBILITY}], (f"{EXAMS_POLICY} §2",)),
    Question("c04", "combined", "en", "shortage",
             "My DBMS attendance is low. Can it be condoned, and down to what minimum?",
             lambda r: [Num(65), pct(r.course("Database Management Systems").attended,
                                     r.course("Database Management Systems").held)],
             [{ATTENDANCE, ELIGIBILITY, CALCULATE}, {SEARCH, ELIGIBILITY}],
             (f"{ATTENDANCE_POLICY} §4",)),
    Question("c05", "combined", "en", "fees",
             "How much late fee will I be charged on my overdue tuition?",
             [Num(100), Num(5000)], [{FEES, ELIGIBILITY}, {SEARCH}], (f"{FEE_POLICY} §2",)),
    Question("c06", "combined", "hinglish", "shortage",
             "Agar main DBMS ki ek aur class miss karun toh kya main end-term de paunga?",
             [Text("condonation", "condone", "condoned")],
             [{ELIGIBILITY, CALCULATE, ATTENDANCE}],
             (f"{ATTENDANCE_POLICY} §4", f"{EXAMS_POLICY} §2")),
    Question("c07", "combined", "en", "regular",
             "If I miss 3 Machine Learning classes for a hostel leave, will I still be above 75%?",
             lambda r: [after_missing(r, "Machine Learning", 3)], [{CALCULATE}]),
]
