"""Calendar export: the student's remaining classes, upcoming exams, assignment deadlines and
fee due dates as
an iCalendar file (RFC 5545) that Google Calendar, Outlook and phone calendars import.

Written by hand, the format being small: CRLF line endings, lines folded at 75 octets, text
escaped, times in UTC. Every event has a stable UID, so importing a newer export updates
the events instead of duplicating them.
"""
import hashlib
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta

from campusgpt.student import AssignmentDue, ClassMeeting, Fee, UpcomingExam, rupees

PRODID = "-//CampusGPT//Student calendar//EN"
UID_DOMAIN = "campusgpt.example"
EXAM_LABEL = {"quiz": "Quiz", "mid_term": "Mid-term exam", "end_term": "End-term exam"}


def escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def fold(line: str) -> str:
    """Split a content line into chunks of at most 75 octets, never inside a UTF-8
    character; continuation lines start with a space."""
    out, current, size = [], "", 0
    for ch in line:
        n = len(ch.encode())
        limit = 75 if not out else 74       # the leading space counts on continuations
        if size + n > limit:
            out.append(current)
            current, size = "", 0
        current += ch
        size += n
    out.append(current)
    return "\r\n ".join(out)


def utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def uid(*parts: object) -> str:
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:24]
    return f"{digest}@{UID_DOMAIN}"


def _event(uid_: str, stamp: datetime, start: list[str], summary: str, description: str,
           location: str | None = None, alarm: timedelta | None = None) -> list[str]:
    lines = ["BEGIN:VEVENT", f"UID:{uid_}", f"DTSTAMP:{utc(stamp)}", *start,
             f"SUMMARY:{escape(summary)}", f"DESCRIPTION:{escape(description)}"]
    if location:
        lines.append(f"LOCATION:{escape(location)}")
    if alarm:
        hours = int(alarm.total_seconds() // 3600)
        lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{escape(summary)}",
                  f"TRIGGER:-PT{hours}H", "END:VALARM"]
    return lines + ["END:VEVENT"]


def calendar(student_id: int, now: datetime, classes: Iterable[ClassMeeting],
             exams: Iterable[UpcomingExam], assignments: Iterable[AssignmentDue],
             fees: Iterable[Fee]) -> str:
    """The .ics text. `student_id` only salts the UIDs; it is not written to the file."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", "X-WR-CALNAME:CampusGPT"]
    for c in classes:
        lines += _event(
            uid(student_id, "class", c.code, c.starts_at.isoformat()), now,
            [f"DTSTART:{utc(c.starts_at)}", f"DTEND:{utc(c.ends_at)}"],
            f"{c.title} ({c.code})", f"Class with {c.faculty}, room {c.room}.",
            location=f"Room {c.room}")
    for e in exams:
        label = EXAM_LABEL.get(e.exam_type, e.exam_type)
        end = e.starts_at + timedelta(minutes=e.duration_minutes)
        lines += _event(
            uid(student_id, "exam", e.code, e.exam_type, e.starts_at.isoformat()), now,
            [f"DTSTART:{utc(e.starts_at)}", f"DTEND:{utc(end)}"],
            f"{label}: {e.title} ({e.code})",
            f"{label}, {e.duration_minutes} minutes, room {e.room}. Be seated 15 minutes "
            "before the start with your ID card and admit card.",
            location=f"Room {e.room}", alarm=timedelta(hours=24))
    for a in assignments:
        if a.submitted:
            continue
        lines += _event(
            uid(student_id, "assignment", a.code, a.title, a.due_at.isoformat()), now,
            [f"DTSTART:{utc(a.due_at - timedelta(minutes=30))}", f"DTEND:{utc(a.due_at)}"],
            f"Due: {a.title} ({a.code})",
            f"Submit on the learning portal by {a.due_at:%d %b %Y, %H:%M}. "
            f"{a.course}, {a.max_marks} marks.",
            alarm=timedelta(hours=24))
    for f in fees:
        if f.balance <= 0 or f.status in ("waived", "cancelled") or f.due_date < now.date():
            continue
        day: date = f.due_date
        lines += _event(
            uid(student_id, "fee", f.description, day.isoformat()), now,
            [f"DTSTART;VALUE=DATE:{day:%Y%m%d}",
             f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}"],
            f"Fee due: {f.description}",
            f"{rupees(f.balance)} outstanding.",
            alarm=timedelta(hours=72))
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(line) for line in lines) + "\r\n"
