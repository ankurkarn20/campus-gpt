"""ORM models. Importing this package registers every table on Base.metadata."""
from campusgpt.models.academic import (
    Assignment,
    Attendance,
    ClassSession,
    Course,
    CourseOffering,
    Department,
    Enrollment,
    Exam,
    Faculty,
    Invoice,
    Payment,
    Program,
    Student,
    Submission,
    TimetableSlot,
)
from campusgpt.models.accounts import User, UserSession
from campusgpt.models.base import Base
from campusgpt.models.chat import AuditLog, Conversation, Message
from campusgpt.models.documents import Document, DocumentChunk, DocumentFile, IngestionJob, Notice

__all__ = [
    "Assignment", "Attendance", "AuditLog", "Base", "ClassSession", "Conversation", "Course",
    "CourseOffering", "Department", "Document", "DocumentChunk", "DocumentFile", "Enrollment",
    "Exam", "Faculty", "IngestionJob", "Invoice", "Message", "Notice", "Payment", "Program",
    "Student", "Submission", "TimetableSlot", "User", "UserSession",
]
