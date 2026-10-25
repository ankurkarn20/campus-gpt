"""Tools the chat model may call (Registry pattern).

Each tool is a read-only function registered with @tool. The model chooses a tool and its
arguments; execute() checks the caller's role, validates the arguments against the tool's
Pydantic model and runs it with the student id from the login session. No tool accepts a
student id, roll number or email as an argument, so the model cannot ask for anyone
else's records.
"""
import dataclasses
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from campusgpt import student
from campusgpt.calc import ATTENDANCE_TARGET, classes_can_miss, classes_needed
from campusgpt.models import AuditLog


class ToolNotPermitted(Exception):
    """The tool does not exist or the caller's role may not use it."""


class ToolValidationError(Exception):
    """The model supplied arguments that do not match the tool's schema."""


@dataclass
class ToolContext:
    db: AsyncSession
    user_id: int
    role: str
    student_id: int | None
    now: datetime

    @property
    def today(self) -> date:
        return self.now.date()


@dataclass
class ToolSpec:
    name: str
    description: str
    args: type[BaseModel]
    roles: frozenset[str]
    status: str                    # shown to the user while the tool runs
    fn: Callable[[ToolContext, Any], Awaitable[Any]]

    def definition(self) -> dict:
        """OpenAI-style function definition; the JSON Schema comes from the Pydantic model."""
        schema = self.args.model_json_schema()
        schema.pop("title", None)
        return {"type": "function",
                "function": {"name": self.name, "description": self.description,
                             "parameters": schema}}


TOOLS: dict[str, ToolSpec] = {}


def tool(name: str, description: str, *, status: str, args: type[BaseModel] | None = None,
         roles: tuple[str, ...] = ("student",)):
    def register(fn):
        TOOLS[name] = ToolSpec(name, description, args or NoArgs, frozenset(roles), status, fn)
        return fn
    return register


def definitions(role: str) -> list[dict]:
    return [t.definition() for t in TOOLS.values() if role in t.roles]


def to_jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return to_jsonable(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [to_jsonable(v) for v in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


async def execute(ctx: ToolContext, name: str, raw_args: str) -> Any:
    """Run one tool call from the model. Every call is audited."""
    spec = TOOLS.get(name)
    if spec is None or ctx.role not in spec.roles:
        ctx.db.add(AuditLog(user_id=ctx.user_id, action="tool_call", tool_name=name[:60],
                            outcome="denied"))
        raise ToolNotPermitted(name)
    try:
        args = spec.args.model_validate(json.loads(raw_args or "{}"))
    except (ValueError, ValidationError) as e:
        ctx.db.add(AuditLog(user_id=ctx.user_id, action="tool_call", tool_name=name,
                            outcome="error", detail={"reason": "invalid arguments"}))
        raise ToolValidationError(str(e)) from e
    result = to_jsonable(await spec.fn(ctx, args))
    ctx.db.add(AuditLog(user_id=ctx.user_id, action="tool_call", tool_name=name,
                        outcome="success", detail={"arguments": args.model_dump()}))
    return result


# -- argument models -----------------------------------------------------------------------
class NoArgs(BaseModel):
    pass


class CourseFilter(BaseModel):
    course: str | None = Field(None, description="Course code or part of its title, e.g. "
                                                  "'CSE301' or 'DBMS'. Omit for all courses.")


class AttendanceRequirementArgs(BaseModel):
    course: str = Field(description="Course code or part of its title")
    target_percent: float = Field(75, ge=1, le=100,
                                  description="Attendance target in percent (default 75)")
    miss_next: int = Field(0, ge=0, le=60, description="Number of upcoming classes the "
                                                       "student is thinking of missing")


class ExamArgs(CourseFilter):
    exam_type: Literal["quiz", "mid_term", "end_term"] | None = None


class AssignmentArgs(CourseFilter):
    include_submitted: bool = Field(True, description="Include already submitted work")


class NoticeArgs(BaseModel):
    query: str | None = Field(None, max_length=100,
                              description="Words that must appear, e.g. 'hackathon'")
    limit: int = Field(5, ge=1, le=20)


# Common short names students use for courses.
ALIASES = {"dbms": "database management", "oops": "object-oriented", "oop": "object-oriented",
           "daa": "analysis of algorithms", "coa": "computer organization",
           "cn": "computer networks", "os": "operating systems", "ml": "machine learning"}


def matches(course: str | None, code: str, title: str) -> bool:
    if not course:
        return True
    needle = course.strip().lower()
    needle = ALIASES.get(needle, needle)
    return needle == code.lower() or needle in title.lower()


# -- tools ---------------------------------------------------------------------------------
@tool("get_my_profile", "The student's name, roll number, program, semester and section.",
      status="Looking up your profile")
async def get_my_profile(ctx: ToolContext, args: NoArgs):
    return await student.profile(ctx.db, ctx.student_id)


@tool("get_my_attendance", "Attendance per course this term: classes held and attended, "
      "percentage, whether it is below the 75% requirement, classes needed to recover and "
      "classes that can still be missed.", status="Checking your attendance", args=CourseFilter)
async def get_my_attendance(ctx: ToolContext, args: CourseFilter):
    rows = [c for c in await student.attendance(ctx.db, ctx.student_id)
            if matches(args.course, c.code, c.title)]
    return rows or {"error": f"No enrolled course matches '{args.course}'."}


@tool("calculate_attendance_requirement", "Exact attendance arithmetic for one course: "
      "classes needed to reach a target, and the projected percentage if the student misses "
      "the next N classes. Use this instead of doing the arithmetic yourself.",
      status="Calculating attendance", args=AttendanceRequirementArgs)
async def calculate_attendance_requirement(ctx: ToolContext, args: AttendanceRequirementArgs):
    courses = [c for c in await student.attendance(ctx.db, ctx.student_id)
               if matches(args.course, c.code, c.title)]
    if len(courses) != 1:
        return {"error": f"'{args.course}' matches {len(courses)} courses; be more specific.",
                "courses": [c.code for c in courses]}
    c = courses[0]
    target = Fraction(str(args.target_percent)) / 100
    held, attended = c.held + args.miss_next, c.attended
    return {
        "course": f"{c.code} {c.title}", "target_percent": args.target_percent,
        "now": {"attended": c.attended, "held": c.held, "percent": c.percentage},
        "after_missing": {"missed": args.miss_next, "attended": attended, "held": held,
                          "percent": round(100 * attended / held, 2) if held else 100.0,
                          "meets_target": held == 0 or Fraction(attended, held) >= target},
        "classes_needed_in_a_row": classes_needed(attended, held, target),
        "can_still_miss": classes_can_miss(attended, held, target),
        "university_minimum_percent": float(ATTENDANCE_TARGET * 100),
    }


@tool("get_my_exams", "The student's upcoming exams (quiz, mid-term, end-term) with date, "
      "time, room and duration.", status="Checking your exam schedule", args=ExamArgs)
async def get_my_exams(ctx: ToolContext, args: ExamArgs):
    return [e for e in await student.upcoming_exams(ctx.db, ctx.student_id, ctx.now)
            if matches(args.course, e.code, e.title)
            and (args.exam_type is None or e.exam_type == args.exam_type)]


@tool("get_my_assignments", "Assignments due from now on, with due date, maximum marks and "
      "whether the student has submitted.", status="Checking your assignments",
      args=AssignmentArgs)
async def get_my_assignments(ctx: ToolContext, args: AssignmentArgs):
    return [a for a in await student.assignments_due(ctx.db, ctx.student_id, ctx.now)
            if matches(args.course, a.code, a.course)
            and (args.include_submitted or not a.submitted)]


@tool("get_my_fee_status", "The student's fee invoices: amount, paid, balance, due date and "
      "status (paid, pending, partially_paid, overdue, waived).", status="Checking your fees")
async def get_my_fee_status(ctx: ToolContext, args: NoArgs):
    return await student.fees(ctx.db, ctx.student_id, ctx.today)


@tool("search_notices", "Recent university notices for the student (all-university and their "
      "department), newest first.", status="Searching notices", args=NoticeArgs)
async def search_notices(ctx: ToolContext, args: NoticeArgs):
    return await student.notices(ctx.db, ctx.student_id, ctx.now, args.limit, args.query)


@tool("get_my_weekly_summary", "What the student needs to take care of in the next 7 days, "
      "most urgent first: overdue fees, attendance shortages, exams, assignments, fees due.",
      status="Preparing your week")
async def get_my_weekly_summary(ctx: ToolContext, args: NoArgs):
    db, sid = ctx.db, ctx.student_id
    return student.this_week(ctx.today, await student.attendance(db, sid),
                             await student.upcoming_exams(db, sid, ctx.now),
                             await student.assignments_due(db, sid, ctx.now),
                             await student.fees(db, sid, ctx.today))
