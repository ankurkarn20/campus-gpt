"""Read-only data access for one student (Repository pattern). Every function takes the
student id from the caller's session; none accepts another student's identity. The chat
tools reuse these functions, so the dashboard and the chatbot always agree.

`today` and `now` are parameters rather than read from the clock so that results are
reproducible against a dataset generated for a fixed date.
"""
import heapq
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from fractions import Fraction
from zoneinfo import ZoneInfo

from sqlalchemy import and_, column, extract, func, or_, select, table
from sqlalchemy.ext.asyncio import AsyncSession

from campusgpt import term as calendar
from campusgpt.calc import (
    ATTENDANCE_TARGET,
    MAX_CONDONED_COURSES,
    attendance_outlook,
    classes_can_miss,
    classes_needed,
)
from campusgpt.models import (
    Assignment,
    ClassSession,
    Course,
    CourseOffering,
    Department,
    Enrollment,
    Exam,
    Faculty,
    Notice,
    Program,
    Student,
    Submission,
    TimetableSlot,
)

# Views defined in the initial migration.
attendance_summary = table("attendance_summary", column("student_id"), column("offering_id"),
                           column("classes_held"), column("classes_attended"))
invoice_balances = table("invoice_balances", column("student_id"), column("term"),
                         column("description"),
                         column("amount"), column("due_date"), column("status"),
                         column("paid"), column("balance"))

WEEK = timedelta(days=7)
IST = ZoneInfo("Asia/Kolkata")


@dataclass
class CourseAttendance:
    code: str
    title: str
    held: int
    attended: int
    percentage: float
    status: str            # ok | at_risk (cannot miss another class) | short (below target)
    classes_needed: int
    can_miss: int          # never more than classes_left
    classes_left: int      # still to be held this term, from the timetable


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


def _weekdays():
    """Scalar subquery: the weekdays (0 = Monday) an offering meets, from its timetable."""
    return (select(func.array_agg(TimetableSlot.weekday))
            .where(TimetableSlot.offering_id == attendance_summary.c.offering_id)
            .scalar_subquery())


async def attendance(db: AsyncSession, student_id: int, today: date) -> list[CourseAttendance]:
    term = calendar.term_for(today)
    a = attendance_summary.c
    q = _course_join(select(Course.code, Course.title, a.classes_held, a.classes_attended,
                            _weekdays()),
                     a.offering_id).where(a.student_id == student_id).order_by(Course.code)
    out = []
    for code, title, held, attended, weekdays in await db.execute(q):
        needed, spare = classes_needed(attended, held), classes_can_miss(attended, held)
        left = calendar.classes_left(term, weekdays or [], today)
        short = held > 0 and Fraction(attended, held) < ATTENDANCE_TARGET
        out.append(CourseAttendance(
            code, title, held, attended,
            percentage=round(100 * attended / held, 2) if held else 100.0,
            status="short" if short else "at_risk" if held and spare == 0 else "ok",
            classes_needed=needed, can_miss=min(spare, left), classes_left=left))
    return out


DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@dataclass
class ClassSlot:
    """A weekly class in the student's timetable."""
    day: str
    weekday: int           # 0 = Monday
    starts_at: time
    ends_at: time
    code: str
    title: str
    room: str
    faculty: str


@dataclass
class ClassMeeting:
    """One upcoming class."""
    date: date
    day: str
    starts_at: datetime
    ends_at: datetime
    code: str
    title: str
    room: str
    faculty: str


async def timetable(db: AsyncSession, student_id: int) -> list[ClassSlot]:
    t = TimetableSlot
    q = (_course_join(select(t.weekday, t.starts_at, t.duration_minutes, Course.code,
                             Course.title, t.room, Faculty.name), t.offering_id)
         .join(Faculty, Faculty.id == CourseOffering.faculty_id)
         .join(Enrollment, Enrollment.offering_id == t.offering_id)
         .where(Enrollment.student_id == student_id).order_by(t.weekday, t.starts_at))
    return [ClassSlot(DAY_NAMES[wd], wd, start,
                      (datetime.combine(date.min, start) + timedelta(minutes=minutes)).time(),
                      code, title, room, faculty)
            for wd, start, minutes, code, title, room, faculty in await db.execute(q)]


def upcoming_classes(slots: list[ClassSlot], now: datetime, limit: int = 5) -> list[ClassMeeting]:
    """The next `limit` classes after `now` (in IST), on teaching days only: none on
    holidays, in the mid-term week, or after the last teaching day."""
    now = now.astimezone(IST)
    term = calendar.term_for(now.date())
    out = []
    for day in calendar.days(now.date(), term.last_teaching_day):
        if not term.is_teaching_day(day):
            continue
        for s in slots:
            start = datetime.combine(day, s.starts_at, tzinfo=IST)
            if s.weekday == day.weekday() and start > now:
                out.append(ClassMeeting(day, s.day, start,
                                        datetime.combine(day, s.ends_at, tzinfo=IST),
                                        s.code, s.title, s.room, s.faculty))
                if len(out) == limit:
                    return out
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


# Invoice descriptions written by the seed generator, followed by the term code.
EXAM_FEE_PREFIX = "End-term examination fee"
TUITION_PREFIX = "Tuition fee"


@dataclass
class CourseEligibility:
    code: str
    title: str
    held: int
    attended: int
    percentage: float
    classes_left: int
    status: str             # safe | on_track | condonation_needed | debarred
    attend_at_least: int    # of classes_left
    best_percentage: float  # attending every remaining class
    verdict: str = ""       # the outcome in words, so the chat model need not interpret it


@dataclass
class FeeHold:
    description: str
    balance: Decimal
    due_date: date
    overdue: bool


@dataclass
class Eligibility:
    """Forecast for the end-term examinations (Examination Regulations §2): per course, the
    attendance the student can still reach; for the admit card, the fees still unpaid."""
    term: str
    last_teaching_day: date
    end_term_starts: date
    admit_cards_from: date
    admit_card_ok: bool          # no unpaid exam or tuition fee
    fee_holds: list[FeeHold]
    courses: list[CourseEligibility]
    # More courses need condonation than the two a term allows (Attendance Policy §4.4).
    condonation_limit_exceeded: bool
    summary: str = ""


# A course where at most this many of the remaining classes can be missed is worth a mention.
TIGHT_MARGIN = 2


def course_verdict(c: CourseEligibility) -> str:
    left, need, best = c.classes_left, c.attend_at_least, c.best_percentage
    if c.status == "safe":
        return f"Eligible: stays at or above 75% even if all {left} classes left are missed."
    if c.status == "on_track":
        which = f"all {left}" if need == left else f"at least {need} of the {left}"
        return (f"Eligible only by attending {which} classes left (then at least 75%); "
                f"missing more means falling below 75%.")
    if c.status == "condonation_needed":
        return (f"Cannot reach 75%: at most {best}% even attending all {left} classes left. "
                "Can sit the exam only if the shortage is condoned (medical or other approved "
                "reason, at least 65%).")
    return (f"Will be debarred from this end-term exam: at most {best}% even attending all "
            f"{left} classes left, below the 65% minimum for condonation.")


def eligibility_summary(e: Eligibility) -> str:
    todo = [f"pay {rupees(h.balance)} {h.description} "
            f"({'overdue since' if h.overdue else 'due'} {h.due_date:%d %b})"
            for h in e.fee_holds]
    todo += [f"{c.title}: {c.verdict[0].lower()}{c.verdict[1:].rstrip('.')}" for c in e.courses
             if c.status != "safe"
             and (c.status != "on_track" or c.classes_left - c.attend_at_least <= TIGHT_MARGIN)]
    if not todo:
        return ("Eligible for all end-term exams: no fee holds, and attendance in every course "
                "can stay at or above 75%.")
    if any(c.status == "debarred" for c in e.courses):
        lead = "Will be debarred from at least one end-term exam."
    elif e.fee_holds:
        lead = (f"Not eligible yet: admit cards (issued from {e.admit_cards_from:%d %b}) are "
                "withheld until all fees are paid.")
    else:
        lead = "Eligible, on conditions."
    return f"{lead} To do: " + " ".join(f"({i}) {t}." for i, t in enumerate(todo, 1))


async def eligibility(db: AsyncSession, student_id: int, today: date) -> Eligibility:
    term = calendar.term_for(today)
    a = attendance_summary.c
    # The weekdays each course meets, read from the classes held so far (0 = Monday).
    weekdays = (select(func.array_agg(extract("isodow", ClassSession.held_on).distinct()))
                .where(ClassSession.offering_id == a.offering_id).scalar_subquery())
    q = (_course_join(select(Course.code, Course.title, a.classes_held, a.classes_attended,
                             weekdays), a.offering_id)
         .where(a.student_id == student_id).order_by(Course.code))
    courses = []
    for code, title, held, attended, isodays in await db.execute(q):
        left = calendar.classes_left(term, [int(d) - 1 for d in isodays or []], today)
        o = attendance_outlook(attended, held, left)
        courses.append(CourseEligibility(
            code, title, held, attended,
            percentage=round(100 * attended / held, 2) if held else 100.0,
            classes_left=left, status=o.status, attend_at_least=o.attend_at_least,
            best_percentage=o.best_percentage))
        courses[-1].verdict = course_verdict(courses[-1])

    v = invoice_balances.c
    unpaid = await db.execute(
        select(v.description, v.balance, v.due_date)
        .where(v.student_id == student_id, v.term == term.code, v.status == "issued",
               v.balance > 0,
               or_(v.description.startswith(EXAM_FEE_PREFIX),
                   v.description.startswith(TUITION_PREFIX)))
        .order_by(v.due_date))
    holds = [FeeHold(d, balance, due, due < today) for d, balance, due in unpaid]
    condonations = sum(c.status == "condonation_needed" for c in courses)
    e = Eligibility(
        term=term.code, last_teaching_day=term.last_teaching_day,
        end_term_starts=term.end_term_start,
        admit_cards_from=term.end_term_start - timedelta(days=5),
        admit_card_ok=not holds, fee_holds=holds, courses=courses,
        condonation_limit_exceeded=condonations > MAX_CONDONED_COURSES)
    e.summary = eligibility_summary(e)
    return e


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
