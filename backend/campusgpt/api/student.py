"""Endpoints for the logged-in student. The student id always comes from the session."""
from dataclasses import asdict
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from campusgpt import ics, student
from campusgpt.auth import CurrentUser, require_role
from campusgpt.db import get_db

router = APIRouter(prefix="/api/student", tags=["student"])

IST = ZoneInfo("Asia/Kolkata")


def get_now() -> datetime:
    """Dependency for the current time, overridden in tests to match the seeded dataset."""
    return datetime.now(IST)


@router.get("/dashboard")
async def dashboard(user: CurrentUser = Depends(require_role("student")),
                    db: AsyncSession = Depends(get_db),
                    now: datetime = Depends(get_now)) -> dict:
    sid, today = user.student_id, now.astimezone(IST).date()
    attendance = await student.attendance(db, sid, today)
    exams = await student.upcoming_exams(db, sid, now)
    assignments = await student.assignments_due(db, sid, now)
    fees = await student.fees(db, sid, today)
    slots = await student.timetable(db, sid)
    return {
        "today": date.isoformat(today),
        "this_week": [asdict(i) for i in
                      student.this_week(today, attendance, exams, assignments, fees)],
        "attendance": [asdict(c) for c in attendance],
        "exams": [asdict(e) for e in exams],
        "assignments": [asdict(a) for a in assignments],
        "fees": [asdict(f) for f in fees],
        "notices": [asdict(n) for n in await student.notices(db, sid, now)],
        "eligibility": asdict(await student.eligibility(db, sid, today)),
        "timetable": [asdict(s) for s in slots],
        "next_classes": [asdict(m) for m in student.upcoming_classes(slots, now)],
    }


@router.get("/calendar.ics", response_class=Response)
async def calendar(user: CurrentUser = Depends(require_role("student")),
                   db: AsyncSession = Depends(get_db),
                   now: datetime = Depends(get_now)) -> Response:
    """Remaining classes, upcoming exams, unsubmitted assignments and fees still to pay, as
    an iCalendar file."""
    sid = user.student_id
    slots = await student.timetable(db, sid)
    body = ics.calendar(sid, now, student.upcoming_classes(slots, now, limit=500),
                        await student.upcoming_exams(db, sid, now),
                        await student.assignments_due(db, sid, now),
                        await student.fees(db, sid, now.astimezone(IST).date()))
    return Response(body, media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="campusgpt.ics"'})
