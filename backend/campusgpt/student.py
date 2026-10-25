"""Read-only data access for one student (Repository pattern). Every function takes the
student id from the caller's session; none accepts another student's identity. The chat
tools reuse these functions, so the dashboard and the chatbot always agree.

`today` and `now` are parameters rather than read from the clock so that results are
reproducible against a dataset generated for a fixed date.
"""
import heapq
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from fractions import Fraction

from sqlalchemy import and_, column, or_, select, table
from sqlalchemy.ext.asyncio import AsyncSession

from campusgpt.calc import ATTENDANCE_TARGET, classes_can_miss, classes_needed
from campusgpt.models import (
    Assignment,
    Course,
    CourseOffering,
    Department,
    Enrollment,
    Exam,
    Notice,
    Program,
    Student,
    Submission,
)

# Views defined in the initial migration.
attendance_summary = table("attendance_summary", column("student_id"), column("offering_id"),
                           column("classes_held"), column("classes_attended"))
invoice_balances = table("invoice_balances", column("student_id"), column("description"),
                         column("amount"), column("due_date"), column("status"),
                         column("paid"), column("balance"))

WEEK = timedelta(days=7)


@dataclass
class CourseAttendance:
    code: str
    title: str
    held: int
    attended: int
    percentage: float
    status: str            # ok | at_risk (cannot miss another class) | short (below target)
    classes_needed: int
    can_miss: int


@dataclass
class UpcomingExam:
    code: str
    title: str
    exam_type: str
    starts_at: datetime
    duration_minutes: int
    room: str


@dataclass
class AssignmentDue:
    code: str
    course: str
    title: str
    due_at: datetime
    max_marks: int
    submitted: bool


@dataclass
class Fee:
    description: str
    amount: Decimal
    paid: Decimal
    balance: Decimal
    due_date: date
    status: str            # paid | pending | partially_paid | overdue | waived | cancelled


@dataclass
class NoticeItem:
    title: str
    body: str
    published_at: datetime
    audience: str


@dataclass
class ActionItem:
    """One entry of "what do I need to take care of this week"."""
    kind: str              # fee_overdue | attendance_short | exam | assignment | fee_due
    title: str
    detail: str
    when: date | None


@dataclass
class Profile:
    name: str
    roll_no: str
    program: str
    department: str
    semester: int
    section: str


async def profile(db: AsyncSession, student_id: int) -> Profile:
    s, program, dept = (await db.execute(
        select(Student, Program.name, Department.name).select_from(Student)
        .join(Program, Program.id == Student.program_id)
        .join(Department, Department.id == Program.department_id)
        .where(Student.id == student_id))).one()
    return Profile(s.name, s.roll_no, program, dept, s.current_semester, s.section)


def rupees(amount: Decimal) -> str:
    """Indian digit grouping: 160000 -> ₹1,60,000.00."""
    whole, paise = f"{amount:.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    groups = [head[max(i - 2, 0):i] for i in range(len(head), 0, -2)][::-1]
    return "₹" + ",".join([*groups, tail]) + "." + paise


def _course_join(q, offering_col):
    return (q.join(CourseOffering, CourseOffering.id == offering_col)
             .join(Course, Course.id == CourseOffering.course_id))


async def attendance(db: AsyncSession, student_id: int) -> list[CourseAttendance]:
    a = attendance_summary.c
    q = _course_join(select(Course.code, Course.title, a.classes_held, a.classes_attended),
                     a.offering_id).where(a.student_id == student_id).order_by(Course.code)
    out = []
    for code, title, held, attended in await db.execute(q):
        needed, spare = classes_needed(attended, held), classes_can_miss(attended, held)
        short = held > 0 and Fraction(attended, held) < ATTENDANCE_TARGET
        out.append(CourseAttendance(
            code, title, held, attended,
            percentage=round(100 * attended / held, 2) if held else 100.0,
            status="short" if short else "at_risk" if held and spare == 0 else "ok",
            classes_needed=needed, can_miss=spare))
    return out


async def upcoming_exams(db: AsyncSession, student_id: int, now: datetime) -> list[UpcomingExam]:
    q = (_course_join(select(Course.code, Course.title, Exam.exam_type, Exam.starts_at,
                             Exam.duration_minutes, Exam.room), Exam.offering_id)
         .join(Enrollment, Enrollment.offering_id == Exam.offering_id)
         .where(Enrollment.student_id == student_id, Exam.starts_at >= now)
         .order_by(Exam.starts_at))
    return [UpcomingExam(*row) for row in await db.execute(q)]


async def assignments_due(db: AsyncSession, student_id: int,
                          now: datetime) -> list[AssignmentDue]:
    q = (_course_join(select(Course.code, Course.title, Assignment.title, Assignment.due_at,
                             Assignment.max_marks, Submission.id.is_not(None)),
                      Assignment.offering_id)
         .join(Enrollment, Enrollment.offering_id == Assignment.offering_id)
         .outerjoin(Submission, and_(Submission.assignment_id == Assignment.id,
                                     Submission.enrollment_id == Enrollment.id))
         .where(Enrollment.student_id == student_id, Assignment.due_at >= now)
         .order_by(Assignment.due_at))
    return [AssignmentDue(*row) for row in await db.execute(q)]


async def fees(db: AsyncSession, student_id: int, today: date) -> list[Fee]:
    """Invoices with balances. Overdue is judged against `today` (the view uses the clock)."""
    v = invoice_balances.c
    q = (select(v.description, v.amount, v.paid, v.balance, v.due_date, v.status)
         .where(v.student_id == student_id).order_by(v.due_date))
    out = []
    for description, amount, paid, balance, due, admin_status in await db.execute(q):
        if admin_status != "issued":
            status = admin_status
        elif balance <= 0:
            status = "paid"
        elif due < today:
            status = "overdue"
        else:
            status = "partially_paid" if paid > 0 else "pending"
        out.append(Fee(description, amount, paid, balance, due, status))
    return out


async def notices(db: AsyncSession, student_id: int, now: datetime, limit: int = 5,
                  query: str | None = None) -> list[NoticeItem]:
    """Latest notices addressed to everyone or to the student's department, optionally
    only those containing every word of `query`."""
    dept = (select(Department.code).join(Program).join(Student)
            .where(Student.id == student_id).scalar_subquery())
    q = (select(Notice.title, Notice.body, Notice.published_at, Notice.audience)
         .where(or_(Notice.audience == "all", Notice.audience == dept),
                Notice.published_at <= now)
         .order_by(Notice.published_at.desc()).limit(limit))
    for word in (query or "").split():
        pattern = f"%{word.replace('%', '').replace('_', '')}%"
        q = q.where(or_(Notice.title.ilike(pattern), Notice.body.ilike(pattern)))
    return [NoticeItem(*row) for row in await db.execute(q)]


def this_week(today: date, attendance: list[CourseAttendance], exams: list[UpcomingExam],
              assignments: list[AssignmentDue], fees: list[Fee],
              limit: int = 8) -> list[ActionItem]:
    """Rank what needs attention in the next seven days with a binary heap (heapq):
    urgency first (overdue fees, attendance shortage, then dated events), then date."""
    horizon = today + WEEK
    heap: list[tuple[int, date, int, ActionItem]] = []

    def push(urgency: int, item: ActionItem):
        heapq.heappush(heap, (urgency, item.when or today, len(heap), item))

    for f in fees:
        if f.status == "overdue":
            push(0, ActionItem("fee_overdue", f"{f.description} is overdue",
                               f"Pay {rupees(f.balance)} (was due {f.due_date:%d %b})", f.due_date))
        elif f.status in ("pending", "partially_paid") and f.due_date <= horizon:
            push(3, ActionItem("fee_due", f"{f.description} due {f.due_date:%a %d %b}",
                               f"{rupees(f.balance)} outstanding", f.due_date))
    for c in attendance:
        if c.status == "short":
            push(1, ActionItem("attendance_short", f"Attendance in {c.title} is {c.percentage}%",
                               f"Attend the next {c.classes_needed} classes to reach 75%", None))
    for e in exams:
        if e.starts_at.date() <= horizon:
            kind = e.exam_type.replace("_", "-")
            push(2, ActionItem("exam", f"{e.title} {kind} on {e.starts_at:%a %d %b, %H:%M}",
                               f"Room {e.room}, {e.duration_minutes} minutes", e.starts_at.date()))
    for a in assignments:
        if not a.submitted and a.due_at.date() <= horizon:
            push(2, ActionItem("assignment", f"Submit “{a.title}” ({a.code})",
                               f"Due {a.due_at:%a %d %b, %H:%M}", a.due_at.date()))
    return [heapq.heappop(heap)[3] for _ in range(min(limit, len(heap)))]
