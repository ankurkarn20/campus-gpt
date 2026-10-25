"""Login, logout and the current user's identity."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from campusgpt import auth, student
from campusgpt.auth import COOKIE_NAME, CurrentUser, current_user
from campusgpt.config import get_settings
from campusgpt.db import get_db
from campusgpt.models import AuditLog

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)


class StudentProfile(BaseModel):
    name: str
    roll_no: str
    program: str
    semester: int
    section: str


class Me(BaseModel):
    email: str
    role: str
    student: StudentProfile | None = None


async def _me(db: AsyncSession, user: CurrentUser) -> Me:
    me = Me(email=user.email, role=user.role)
    if user.student_id is not None:
        p = await student.profile(db, user.student_id)
        me.student = StudentProfile(name=p.name, roll_no=p.roll_no, program=p.program,
                                    semester=p.semester, section=p.section)
    return me


@router.post("/login")
async def login(body: LoginRequest, response: Response,
                db: AsyncSession = Depends(get_db)) -> Me:
    user = await auth.authenticate(db, body.email, body.password)
    if user is None:
        await db.commit()  # keep the audit entry for the failed attempt
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    token = await auth.start_session(db, user)
    await db.commit()
    settings = get_settings()
    response.set_cookie(COOKIE_NAME, token, max_age=settings.session_hours * 3600,
                        httponly=True, secure=settings.cookie_secure, samesite="lax",
                        path="/")
    return await _me(db, await auth.user_for_token(db, token))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        user_id = await auth.end_session(db, token)
        if user_id is not None:
            db.add(AuditLog(user_id=user_id, action="logout", outcome="success"))
        await db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/me")
async def me(user: CurrentUser = Depends(current_user),
             db: AsyncSession = Depends(get_db)) -> Me:
    return await _me(db, user)
