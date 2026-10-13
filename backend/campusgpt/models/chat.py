"""Conversations, messages and the audit log."""
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Identity, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from campusgpt.models.base import Base, created_at_column, id_column

MESSAGE_ROLES = ("user", "assistant", "tool")
AUDIT_OUTCOMES = ("success", "denied", "error")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = id_column()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = created_at_column()


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (CheckConstraint(f"role IN {MESSAGE_ROLES}", name="role"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    # Database records and document chunks the answer was based on.
    sources: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_column()


class AuditLog(Base):
    """Security-relevant events. detail must never contain passwords, tokens or record
    contents -- only identifiers and outcomes."""

    __tablename__ = "audit_logs"
    __table_args__ = (CheckConstraint(f"outcome IN {AUDIT_OUTCOMES}", name="outcome"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(40))
    tool_name: Mapped[str | None] = mapped_column(String(60))
    outcome: Mapped[str] = mapped_column(String(16))
    detail: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_column()
