"""Academic records: departments, programs, courses, enrollment, attendance, assessment, fees.

Derived values (attendance percentage, invoice balance and payment status) are not stored;
the views attendance_summary and invoice_balances compute them (see the initial migration).
"""
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from campusgpt.models.base import Base, id_column

DESIGNATIONS = ("Professor", "Associate Professor", "Assistant Professor")
EXAM_TYPES = ("quiz", "mid_term", "end_term")
INVOICE_STATUSES = ("issued", "waived", "cancelled")
PAYMENT_METHODS = ("upi", "card", "netbanking", "bank_transfer")


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = id_column()
    code: Mapped[str] = mapped_column(String(10), unique=True)
    name: Mapped[str] = mapped_column(String(120))


class Program(Base):
    __tablename__ = "programs"
    __table_args__ = (
        CheckConstraint("duration_semesters BETWEEN 2 AND 10", name="duration_semesters"),
    )

    id: Mapped[int] = id_column()
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), index=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    duration_semesters: Mapped[int] = mapped_column(SmallInteger)


class Faculty(Base):
    __tablename__ = "faculty"
    __table_args__ = (CheckConstraint(f"designation IN {DESIGNATIONS}", name="designation"),)

    id: Mapped[int] = id_column()
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    designation: Mapped[str] = mapped_column(String(40))


class Student(Base):
    __tablename__ = "students"
    __table_args__ = (
        CheckConstraint("current_semester BETWEEN 1 AND 10", name="current_semester"),
    )

    id: Mapped[int] = id_column()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id"), index=True)
    roll_no: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    current_semester: Mapped[int] = mapped_column(SmallInteger)
    section: Mapped[str] = mapped_column(String(4))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, server_default=true())


class Course(Base):
    __tablename__ = "courses"
    __table_args__ = (
        CheckConstraint("credits BETWEEN 1 AND 6", name="credits"),
        CheckConstraint("semester BETWEEN 1 AND 10", name="semester"),
        Index(None, "department_id", "semester"),
    )

    id: Mapped[int] = id_column()
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"))
    code: Mapped[str] = mapped_column(String(12), unique=True)
    title: Mapped[str] = mapped_column(String(160))
    credits: Mapped[int] = mapped_column(SmallInteger)
    semester: Mapped[int] = mapped_column(SmallInteger)


class CourseOffering(Base):
    """A course taught to one section in one term."""

    __tablename__ = "course_offerings"
    __table_args__ = (UniqueConstraint("course_id", "term", "section"),)

    id: Mapped[int] = id_column()
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    faculty_id: Mapped[int] = mapped_column(ForeignKey("faculty.id"), index=True)
    term: Mapped[str] = mapped_column(String(16))
    section: Mapped[str] = mapped_column(String(4))


class TimetableSlot(Base):
    """A weekly class meeting of an offering: the same weekday, time and room every teaching
    week (no classes on holidays or in the mid-term week; see campusgpt.term)."""

    __tablename__ = "timetable_slots"
    __table_args__ = (
        UniqueConstraint("offering_id", "weekday"),
        CheckConstraint("weekday BETWEEN 0 AND 4", name="weekday"),   # Monday..Friday
        CheckConstraint("duration_minutes > 0", name="duration"),
    )

    id: Mapped[int] = id_column()
    offering_id: Mapped[int] = mapped_column(ForeignKey("course_offerings.id"), index=True)
    weekday: Mapped[int] = mapped_column(SmallInteger)
    starts_at: Mapped[time] = mapped_column(Time)
    duration_minutes: Mapped[int] = mapped_column(SmallInteger)
    room: Mapped[str] = mapped_column(String(10))


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("student_id", "offering_id"),)

    id: Mapped[int] = id_column()
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"))
    offering_id: Mapped[int] = mapped_column(ForeignKey("course_offerings.id"), index=True)


class ClassSession(Base):
    """One class meeting of an offering."""

    __tablename__ = "class_sessions"
    __table_args__ = (UniqueConstraint("offering_id", "held_on"),)

    id: Mapped[int] = id_column()
    offering_id: Mapped[int] = mapped_column(ForeignKey("course_offerings.id"))
    held_on: Mapped[date] = mapped_column(Date)


class Attendance(Base):
    __tablename__ = "attendance"

    session_id: Mapped[int] = mapped_column(ForeignKey("class_sessions.id"), primary_key=True)
    enrollment_id: Mapped[int] = mapped_column(
        ForeignKey("enrollments.id"), primary_key=True, index=True
    )
    present: Mapped[bool] = mapped_column(Boolean)


class Exam(Base):
    __tablename__ = "exams"
    __table_args__ = (
        CheckConstraint(f"exam_type IN {EXAM_TYPES}", name="exam_type"),
        CheckConstraint("duration_minutes BETWEEN 10 AND 240", name="duration_minutes"),
    )

    id: Mapped[int] = id_column()
    offering_id: Mapped[int] = mapped_column(ForeignKey("course_offerings.id"), index=True)
    exam_type: Mapped[str] = mapped_column(String(16))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_minutes: Mapped[int] = mapped_column(SmallInteger)
    room: Mapped[str] = mapped_column(String(20))


class Assignment(Base):
    __tablename__ = "assignments"
    __table_args__ = (CheckConstraint("max_marks > 0", name="max_marks"),)

    id: Mapped[int] = id_column()
    offering_id: Mapped[int] = mapped_column(ForeignKey("course_offerings.id"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    max_marks: Mapped[int] = mapped_column(SmallInteger)


class Submission(Base):
    """marks is NULL until graded. A trigger enforces marks <= assignments.max_marks."""

    __tablename__ = "submissions"
    __table_args__ = (
        UniqueConstraint("assignment_id", "enrollment_id"),
        CheckConstraint("marks >= 0", name="marks_non_negative"),
    )

    id: Mapped[int] = id_column()
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"))
    enrollment_id: Mapped[int] = mapped_column(ForeignKey("enrollments.id"), index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    marks: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))


class Invoice(Base):
    """status is administrative (issued / waived / cancelled). Whether an issued invoice is
    paid, partially paid or overdue is derived from payments by the invoice_balances view."""

    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="amount"),
        CheckConstraint(f"status IN {INVOICE_STATUSES}", name="status"),
    )

    id: Mapped[int] = id_column()
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    term: Mapped[str] = mapped_column(String(16))
    description: Mapped[str] = mapped_column(String(160))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), server_default="issued")


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount"),
        CheckConstraint(f"method IN {PAYMENT_METHODS}", name="method"),
    )

    id: Mapped[int] = id_column()
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    method: Mapped[str] = mapped_column(String(16))
