"""Endpoints for the logged-in student. The student id always comes from the session."""
from dataclasses import asdict
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from campusgpt import student
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
    attendance = await student.attendance(db, sid)
    exams = await student.upcoming_exams(db, sid, now)
    assignments = await student.assignments_due(db, sid, now)
    fees = await student.fees(db, sid, today)
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
    }
