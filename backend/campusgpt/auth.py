"""Authentication: password checks, server-side sessions and the FastAPI dependencies that
resolve the logged-in user.

The browser holds a random session token in an HTTP-only cookie; the database stores only
its SHA-256 digest, so a leaked sessions table cannot be replayed. A student's identity is
always taken from the session, never from request bodies or model output.
"""
import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from campusgpt.config import get_settings
from campusgpt.db import get_db
from campusgpt.models import AuditLog, Student, User, UserSession

COOKIE_NAME = "campusgpt_session"

_hasher = PasswordHasher()
# Verified against when the email is unknown, so both cases take the same time.
_DUMMY_HASH = _hasher.hash(secrets.token_hex(16))


@dataclass(frozen=True)
class CurrentUser:
    id: int
    email: str
    role: str
    student_id: int | None  # None for admins


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _password_matches(password_hash: str | None, password: str) -> bool:
    try:
        _hasher.verify(password_hash or _DUMMY_HASH, password)
    except (VerificationError, InvalidHashError):
        return False
    return password_hash is not None


async def authenticate(db: AsyncSession, email: str, password: str) -> User | None:
    """Return the user if the credentials are valid. Writes an audit entry either way."""
    user = await db.scalar(select(User).where(User.email == email.strip().lower()))
    ok = _password_matches(user.password_hash if user else None, password)
    if ok and _hasher.check_needs_rehash(user.password_hash):
        user.password_hash = _hasher.hash(password)
    db.add(AuditLog(user_id=user.id if user else None, action="login",
                    outcome="success" if ok else "denied"))
    return user if ok else None


async def start_session(db: AsyncSession, user: User) -> str:
    """Create a session row and return the raw token for the cookie."""
    token = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(hours=get_settings().session_hours)
    db.add(UserSession(id=token_digest(token), user_id=user.id, expires_at=expires))
    return token


async def end_session(db: AsyncSession, token: str) -> int | None:
    """Delete the session; return its user id, or None if it did not exist."""
    return await db.scalar(
        delete(UserSession).where(UserSession.id == token_digest(token))
        .returning(UserSession.user_id))


async def user_for_token(db: AsyncSession, token: str) -> CurrentUser | None:
    """The user owning an unexpired session with this token, if any."""
    row = (await db.execute(
        select(User, Student.id)
        .join(UserSession, UserSession.user_id == User.id)
        .outerjoin(Student, Student.user_id == User.id)
        .where(UserSession.id == token_digest(token),
               UserSession.expires_at > datetime.now(UTC))
    )).first()
    if row is None:
        return None
    user, student_id = row
    return CurrentUser(user.id, user.email, user.role, student_id)


async def current_user(request: Request, db: AsyncSession = Depends(get_db)) -> CurrentUser:
    """Dependency: the logged-in user, or 401."""
    token = request.cookies.get(COOKIE_NAME)
    user = await user_for_token(db, token) if token else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not logged in")
    return user


def require_role(*roles: str):
    """Dependency factory: the logged-in user if their role is one of `roles`, else 403."""
    async def check(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed for your role")
        return user
    return check
