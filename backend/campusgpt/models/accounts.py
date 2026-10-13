"""Users and login sessions."""
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from campusgpt.models.base import Base, created_at_column, id_column

ROLES = ("student", "admin")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(f"role IN {ROLES}", name="role"),)

    id: Mapped[int] = id_column()
    email: Mapped[str] = mapped_column(String(254), unique=True)
    # NULL means the account cannot log in (most synthetic students).
    password_hash: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = created_at_column()


class UserSession(Base):
    """A login session. The id is the SHA-256 hex digest of the random session token,
    so a leaked database row cannot be replayed as a cookie."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = created_at_column()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
