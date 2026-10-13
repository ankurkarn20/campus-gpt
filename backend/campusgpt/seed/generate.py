"""Deterministic generator for the synthetic university.

The same (students, seed, as_of) always produces exactly the same rows. All randomness comes
from one seeded NumPy generator and one seeded Faker instance.

Time model: the current term is the one containing `as_of`. Classes, past assessments and
payments happen before `as_of`; some quizzes, assignment deadlines and the examination fee
fall in the days after it, so "what do I need to do this week?" always has an answer.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import numpy as np
from argon2 import PasswordHasher
from faker import Faker

from campusgpt.seed import catalog

IST = ZoneInfo("Asia/Kolkata")
EMAIL_DOMAIN = "students.campusgpt.example"   # .example is reserved: never a real address
DEMO_DOMAIN = "demo.campusgpt.example"
ATTENDANCE_THRESHOLD = 0.75


@dataclass(frozen=True)
class Term:
    code: str
    start: date          # Monday of the first teaching week
    end: date            # last day of end-term examinations
    odd: bool

    @property
    def mid_term_week(self) -> date:
        return self.start + timedelta(weeks=7)

    @property
    def end_term_start(self) -> date:
        return self.end - timedelta(days=12)

    def semesters(self, duration: int) -> list[int]:
        return [s for s in range(1 if self.odd else 2, duration + 1, 2)]


def term_for(as_of: date) -> Term:
    if as_of.month >= 7:
        start, end, odd = date(as_of.year, 7, 20), date(as_of.year, 12, 5), True
        code = f"{as_of.year}-ODD"
    else:
        start, end, odd = date(as_of.year, 1, 12), date(as_of.year, 5, 23), False
        code = f"{as_of.year}-EVEN"
    start -= timedelta(days=start.weekday())  # align to Monday
    term = Term(code, start, end, odd)
    earliest, latest = start + timedelta(weeks=5), term.end_term_start - timedelta(days=14)
    if not earliest <= as_of <= latest:
        raise ValueError(
            f"as_of {as_of} must fall between {earliest} and {latest} for term {code}, so the "
            "dataset has both past and upcoming activity. Pass --as-of with a date in range."
        )
    return term


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=IST)


@dataclass
class DemoAccount:
    email: str
    role: str
    description: str
    student_id: int | None = None


@dataclass
class Dataset:
    """Generated rows, keyed by table name, in insertion order."""

    as_of: date
    term: Term
    rows: dict[str, list[tuple]] = field(default_factory=dict)
    # attendance is large, so it is kept as one boolean matrix per offering
    # (enrollments x sessions) and expanded into rows only while loading.
    attendance: list[tuple[list[int], list[int], np.ndarray]] = field(default_factory=list)
    demo_accounts: list[DemoAccount] = field(default_factory=list)

    def attendance_rows(self):
        for enrollment_ids, session_ids, present in self.attendance:
            for j, session_id in enumerate(session_ids):
                column = present[:, j]
                for i, enrollment_id in enumerate(enrollment_ids):
                    yield (session_id, enrollment_id, bool(column[i]))

    def counts(self) -> dict[str, int]:
        counts = {name: len(rows) for name, rows in self.rows.items()}
        counts["attendance"] = sum(m.size for _, _, m in self.attendance)
        return counts


# Column lists for each table, in load order.
COLUMNS = {
    "departments": ("id", "code", "name"),
    "programs": ("id", "department_id", "code", "name", "duration_semesters"),
    "users": ("id", "email", "password_hash", "role"),
    "faculty": ("id", "department_id", "name", "designation"),
    "courses": ("id", "department_id", "code", "title", "credits", "semester"),
    "students": ("id", "user_id", "program_id", "roll_no", "name", "current_semester",
                 "section", "is_synthetic"),
    "course_offerings": ("id", "course_id", "faculty_id", "term", "section"),
    "enrollments": ("id", "student_id", "offering_id"),
    "class_sessions": ("id", "offering_id", "held_on"),
    "exams": ("id", "offering_id", "exam_type", "starts_at", "duration_minutes", "room"),
    "assignments": ("id", "offering_id", "title", "due_at", "max_marks"),
    "submissions": ("id", "assignment_id", "enrollment_id", "submitted_at", "marks"),
    "invoices": ("id", "student_id", "term", "description", "amount", "due_date", "status"),
    "payments": ("id", "invoice_id", "amount", "paid_at", "method"),
    "notices": ("id", "published_by", "title", "body", "audience", "published_at",
                "is_synthetic"),
}
ATTENDANCE_COLUMNS = ("session_id", "enrollment_id", "present")


class Generator:
    def __init__(self, students: int, seed: int, as_of: date, demo_password: str):
        if students < 100:
            raise ValueError("generate at least 100 students")
        self.n_students = students
        self.as_of = as_of
        self.term = term_for(as_of)
        self.rng = np.random.default_rng(seed)
        self.fake = Faker("en_IN")
        self.fake.seed_instance(seed)
        self.demo_password = demo_password
        self.tuition_due = self.term.start + timedelta(days=11)
        self.exam_fee_due = as_of + timedelta(days=18)
        self.ds = Dataset(as_of=as_of, term=self.term)
        self.rows = self.ds.rows
        for table in COLUMNS:
            self.rows[table] = []

    # -- helpers ---------------------------------------------------------------
    def _choice(self, options, p=None):
        return options[int(self.rng.choice(len(options), p=p))]

    def _add(self, table: str, row: tuple) -> int:
        """Append a row whose first column is the next sequential id; return the id."""
        rows = self.rows[table]
        row_id = len(rows) + 1
        rows.append((row_id, *row))
        return row_id

    def _days(self, start: date, end: date):
        day = start
        while day <= end:
            yield day
            day += timedelta(days=1)

    # -- generation steps --------------------------------------------------------
    def generate(self) -> Dataset:
        self._structure()
        self._people()
        self._offerings()
        self._attendance()
        self._assessments()
        self._fees()
        self._notices()
        self._demo_passwords()
        return self.ds

    def _structure(self):
        self.dept_id = {}
        for code, name in catalog.DEPARTMENTS.items():
            self.dept_id[code] = self._add("departments", (code, name))
        self.programs = []
        for code, dept, name, duration, prefix, share, fee in catalog.PROGRAMS:
            pid = self._add("programs", (self.dept_id[dept], code, name, duration))
            self.programs.append({"id": pid, "code": code, "dept": dept, "duration": duration,
                                      "prefix": prefix, "share": share, "fee": fee})
        self.course_ids = defaultdict(list)          # (dept, semester) -> [course id]
        self.course_title = {}
        for dept, semesters in catalog.COURSES.items():
            for semester, titles in semesters.items():
                for k, title in enumerate(titles, start=1):
                    credits = 2 if "Project" in title or "Internship" in title else (
                        3 if k == 5 else 4)
                    cid = self._add("courses", (self.dept_id[dept], f"{dept}{semester}{k:02d}",
                                                title, credits, semester))
                    self.course_ids[dept, semester].append(cid)
                    self.course_title[cid] = title

    def _people(self):
        # Administrators come first so their ids are stable.
        self.admin_user = self._add("users", (f"admin@{DEMO_DOMAIN}", None, "admin"))
        self.ds.demo_accounts.append(DemoAccount(f"admin@{DEMO_DOMAIN}", "admin",
                                                 "Academic office administrator"))
        self.faculty_ids = defaultdict(list)
        designations = list(catalog.DESIGNATION_WEIGHTS)
        weights = list(catalog.DESIGNATION_WEIGHTS.values())
        for dept, count in catalog.FACULTY_PER_DEPARTMENT.items():
            for _ in range(count):
                designation = self._choice(designations, p=weights)
                title = "Dr. " if designation != "Assistant Professor" or self.rng.random() < 0.4 \
                    else ""
                name = f"{title}{self.fake.first_name()} {self.fake.last_name()}"
                self.faculty_ids[dept].append(
                    self._add("faculty", (self.dept_id[dept], name, designation)))

        # The first students are the demo accounts, fixed so they exist for any seed and size.
        demo_specs = [
            ("regular", "BTECH-CSE-CS", 5,
             "Cyber Security, semester 5: good attendance, all fees paid"),
            ("shortage", "BTECH-CSE", 3,
             "CSE, semester 3: attendance below 75% in Database Management Systems"),
            ("fees", "BTECH-ECE", 7, "ECE, semester 7: tuition fee overdue"),
        ]
        if not self.term.odd:   # even term: use the following semester
            demo_specs = [(k, p, sem + 1, d) for k, p, sem, d in demo_specs]
        by_code = {p["code"]: p for p in self.programs}
        shares = np.array([p["share"] for p in self.programs])
        program_idx = self.rng.choice(len(self.programs), size=self.n_students, p=shares)
        self.students = []
        self.demo = {}
        roll_seq = defaultdict(int)
        for n, idx in enumerate(program_idx):
            if n < len(demo_specs):
                key, code, semester, description = demo_specs[n]
                program = by_code[code]
            else:
                program = self.programs[int(idx)]
                semester = int(self.rng.choice(self.term.semesters(program["duration"])))
            admission_year = self.as_of.year - (semester - 1) // 2 - (0 if self.term.odd else 1)
            roll_seq[program["prefix"], admission_year] += 1
            seq = roll_seq[program["prefix"], admission_year]
            roll = f"{admission_year}{program['prefix']}{seq:04d}"
            female = self.rng.random() < 0.45
            first = self.fake.first_name_female() if female else self.fake.first_name_male()
            last = self.fake.last_name()
            student = {"program": program, "semester": semester, "roll": roll,
                           "name": f"{first} {last}", "first": first, "last": last}
            if n < len(demo_specs):
                student["demo"] = key
                self.demo[key] = student
                self.ds.demo_accounts.append(
                    DemoAccount(f"student.{key}@{DEMO_DOMAIN}", "student", description))
            self.students.append(student)

        # Sections: students of a department and semester, in roll-number order, in groups.
        groups = defaultdict(list)
        for s in self.students:
            groups[s["program"]["dept"], s["semester"]].append(s)
        for (dept, semester), members in groups.items():
            members.sort(key=lambda s: s["roll"])
            n_sections = -(-len(members) // catalog.SECTION_SIZE)
            for k, s in enumerate(members):
                s["section"] = chr(ord("A") + k * n_sections // len(members))
        self.groups = groups

        for s in self.students:
            if "demo" in s:
                email = f"student.{s['demo']}@{DEMO_DOMAIN}"
            else:
                first, last = (re.sub(r"[^a-z]", "", part.lower())
                               for part in (s["first"], s["last"]))
                email = f"{first[:20]}.{last[:20]}.{s['roll'].lower()}@{EMAIL_DOMAIN}"
            s["user_id"] = self._add("users", (email, None, "student"))
            s["id"] = self._add("students", (s["user_id"], s["program"]["id"], s["roll"],
                                             s["name"], s["semester"], s["section"], True))
        for account in self.ds.demo_accounts:
            if account.role == "student":
                key = account.email.split("@")[0].split(".", 1)[1]
                account.student_id = self.demo[key]["id"]

    def _offerings(self):
        self.offerings = []           # dicts with id, course_id, dept, members
        faculty_cursor = defaultdict(int)
        for (dept, semester), members in sorted(self.groups.items()):
            sections = sorted({s["section"] for s in members})
            for course_id in self.course_ids[dept, semester]:
                for section in sections:
                    pool = self.faculty_ids[dept]
                    faculty_id = pool[faculty_cursor[dept] % len(pool)]
                    faculty_cursor[dept] += 1
                    oid = self._add("course_offerings",
                                    (course_id, faculty_id, self.term.code, section))
                    section_members = [s for s in members if s["section"] == section]
                    enrollment_ids = [self._add("enrollments", (s["id"], oid))
                                      for s in section_members]
                    self.offerings.append({"id": oid, "course_id": course_id, "dept": dept,
                                               "students": section_members,
                                               "enrollment_ids": enrollment_ids})

    def _attendance(self):
        term, as_of = self.term, self.as_of
        holidays = {date(as_of.year, m, d) for m, d in catalog.HOLIDAYS}
        mid_week = {term.mid_term_week + timedelta(days=k) for k in range(6)}
        last_class = min(as_of - timedelta(days=1), term.end_term_start - timedelta(days=1))

        # Each student has an underlying attendance habit: most attend regularly, some don't.
        habit = {}
        for s in self.students:
            group = self.rng.choice(3, p=[0.80, 0.16, 0.04])
            a, b = [(20, 3), (12, 4), (5, 4)][group]
            habit[s["id"]] = float(self.rng.beta(a, b))
        habit[self.demo["regular"]["id"]] = 0.93
        habit[self.demo["shortage"]["id"]] = 0.86
        self.habit = habit

        self.attendance_stats = {}    # enrollment id -> (attended, held)
        for off in self.offerings:
            days = sorted(self.rng.choice(5, size=3, replace=False))  # Mon..Fri
            held = [d for d in self._days(term.start, last_class)
                    if d.weekday() in days and d not in holidays and d not in mid_week]
            session_ids = [self._add("class_sessions", (off["id"], d)) for d in held]
            off["session_dates"] = held
            p = np.array([habit[s["id"]] for s in off["students"]])
            p = np.clip(p + self.rng.normal(0, 0.05, size=len(p)), 0.2, 0.99)
            present = self.rng.random((len(p), len(held))) < p[:, None]

            for i, s in enumerate(off["students"]):
                target = None
                if s.get("demo") == "shortage" and self.course_title[off["course_id"]] == \
                        "Database Management Systems":
                    target = round(0.68 * len(held))
                elif "demo" not in s and self.rng.random() < 0.02:
                    # Boundary cases: exactly at, or one class short of, the threshold.
                    at_threshold = int(np.ceil(ATTENDANCE_THRESHOLD * len(held)))
                    target = at_threshold - int(self.rng.integers(0, 2))
                if target is not None:
                    row = np.zeros(len(held), dtype=bool)
                    row[self.rng.choice(len(held), size=target, replace=False)] = True
                    present[i] = row
                if s.get("demo") in ("regular", "shortage") and target is None:
                    # keep the demo students' other courses comfortably above the threshold
                    while present[i].mean() < 0.82:
                        present[i, int(self.rng.choice(np.flatnonzero(~present[i])))] = True

            for i, eid in enumerate(off["enrollment_ids"]):
                self.attendance_stats[eid] = (int(present[i].sum()), len(held))
            self.ds.attendance.append((off["enrollment_ids"], session_ids, present))

    def _assessments(self):
        term, as_of = self.term, self.as_of
        rooms = [f"{block}-{floor}{n:02d}" for block in "ABC" for floor in (1, 2, 3)
                 for n in range(1, 11)]
        for off in self.offerings:
            title = self.course_title[off["course_id"]]
            # Exams: mid-term (week 8), an upcoming quiz, and the end-term.
            mid_day = term.mid_term_week + timedelta(days=int(self.rng.integers(0, 6)))
            quiz_day = as_of + timedelta(days=int(self.rng.integers(1, 15)))
            if quiz_day.weekday() == 6:
                quiz_day += timedelta(days=1)
            end_day = term.end_term_start + timedelta(days=int(self.rng.integers(0, 11)))
            if end_day.weekday() == 6:
                end_day -= timedelta(days=1)
            for exam_type, day, minutes in (("mid_term", mid_day, 90), ("quiz", quiz_day, 30),
                                            ("end_term", end_day, 180)):
                hour = 10 if self.rng.random() < 0.5 else 14
                self._add("exams", (off["id"], exam_type, at(day, hour), minutes,
                                    self._choice(rooms)))

            # Four assignments: two early, one recently due, one due soon.
            dues = [term.start + timedelta(weeks=3, days=4),
                    term.start + timedelta(weeks=6, days=4),
                    as_of - timedelta(days=int(self.rng.integers(3, 13))),
                    as_of + timedelta(days=int(self.rng.integers(2, 11)))]
            for k, due in enumerate(dues, start=1):
                max_marks = int(self._choice([10, 20, 25]))
                due_at = at(due, 23, 59)
                aid = self._add("assignments", (off["id"], f"{title}: Assignment {k}", due_at,
                                                max_marks))
                past = due < as_of
                graded = k <= 2 or (k == 3 and self.rng.random() < 0.3)
                for s, eid in zip(off["students"], off["enrollment_ids"]):
                    diligence = float(np.clip(self.habit[s["id"]] + self.rng.normal(0, 0.1),
                                              0.05, 0.99))
                    if s.get("demo") == "regular":
                        diligence = 0.99
                    if past:
                        if self.rng.random() > diligence:
                            continue
                        late = self.rng.random() < 0.08
                        offset = timedelta(hours=float(self.rng.uniform(1, 48)))
                        submitted = due_at + offset if late else due_at - timedelta(
                            hours=float(self.rng.uniform(0.5, 96)))
                    else:
                        if self.rng.random() > 0.15 * diligence:
                            continue
                        submitted = datetime.combine(as_of, time(0), tzinfo=IST) - timedelta(
                            hours=float(self.rng.uniform(1, 72)))
                    marks = None
                    if past and graded:
                        quality = float(np.clip(self.rng.normal(0.5 + 0.4 * diligence, 0.12),
                                                0, 1))
                        marks = Decimal(str(round(max_marks * quality * 2) / 2))
                    self._add("submissions", (aid, eid, submitted, marks))

    def _fees(self):
        term, as_of = self.term, self.as_of
        tuition_due, exam_due = self.tuition_due, self.exam_fee_due
        methods = ["upi", "netbanking", "card", "bank_transfer"]
        method_p = [0.5, 0.25, 0.15, 0.10]
        for s in self.students:
            fee = Decimal(s["program"]["fee"])
            waived = "demo" not in s and self.rng.random() < 0.03
            tid = self._add("invoices", (s["id"], term.code, f"Tuition fee {term.code}",
                                         fee, tuition_due, "waived" if waived else "issued"))
            eid = self._add("invoices", (s["id"], term.code,
                                         f"End-term examination fee {term.code}",
                                         Decimal(catalog.EXAM_FEE), exam_due, "issued"))
            if not waived:
                behaviour = {"regular": "on_time", "fees": "unpaid",
                             "shortage": "on_time"}.get(s.get("demo")) or self._choice(
                    ["on_time", "late", "partial", "unpaid"], p=[0.85, 0.06, 0.04, 0.05])
                if behaviour == "on_time":
                    paid_on = tuition_due - timedelta(days=int(self.rng.integers(0, 25)))
                    self._pay(tid, fee, paid_on, methods, method_p)
                elif behaviour == "late":
                    paid_on = tuition_due + timedelta(days=int(self.rng.integers(1, 30)))
                    self._pay(tid, fee, min(paid_on, as_of - timedelta(days=1)), methods,
                              method_p)
                elif behaviour == "partial":
                    self._pay(tid, (fee / 2).quantize(Decimal(1)), tuition_due, methods,
                              method_p)
            pays_exam_fee = s.get("demo") == "regular" or (
                "demo" not in s and self.rng.random() < 0.35)
            if pays_exam_fee:
                paid_on = as_of - timedelta(days=int(self.rng.integers(1, 11)))
                self._pay(eid, Decimal(catalog.EXAM_FEE), paid_on, methods, method_p)

    def _pay(self, invoice_id, amount, day, methods, method_p):
        paid_at = at(day, int(self.rng.integers(9, 22)), int(self.rng.integers(0, 60)))
        self._add("payments", (invoice_id, amount, paid_at, self._choice(methods, p=method_p)))

    def _notices(self):
        term, as_of = self.term, self.as_of
        depts = list(catalog.DEPARTMENTS)
        mid = term.mid_term_week
        planned = []    # (published on, kind, audience, event date, extra values)

        def plan(published, kind, event=None, audience="all", **extra):
            if published <= as_of:
                planned.append((published, kind, audience, event, extra))

        # Notices tied to the term calendar
        plan(term.start - timedelta(days=12), "tuition", self.tuition_due)
        plan(term.start + timedelta(days=1), "guidelines")
        plan(mid - timedelta(days=5), "library", mid - timedelta(days=2))
        plan(as_of - timedelta(days=4), "exam_fee", self.exam_fee_due)
        for dept in depts:
            plan(mid - timedelta(days=10), "mid_term", mid, dept)
            plan(mid + timedelta(days=14), "attendance", mid + timedelta(days=24), dept)
        for m, d in catalog.HOLIDAYS:
            holiday = date(as_of.year, m, d)
            if term.start <= holiday <= term.end:
                plan(holiday - timedelta(days=6), "holiday", holiday,
                     holiday=catalog.HOLIDAY_NAMES[m, d])

        # Recurring announcements spread across the term so far
        first = term.start - timedelta(days=14)
        kinds, weights = ["guest", "placement", "hackathon", "scholarship"], [0.6, 0.2, 0.1, 0.1]
        while len(planned) < catalog.NOTICE_COUNT:
            published = first + timedelta(days=int(self.rng.integers(0, (as_of - first).days)))
            kind = self._choice(kinds, p=weights)
            dept = self._choice(depts)
            plan(published, kind, published + timedelta(days=int(self.rng.integers(4, 21))),
                 dept if kind == "placement" else "all", dept=dept,
                 topic=self._choice(catalog.GUEST_LECTURE_TOPICS))

        for published, kind, audience, event, extra in sorted(planned, key=lambda n: n[0]):
            values = {"term": term.code, "exam_fee": f"{catalog.EXAM_FEE:,}",
                          "date": event.strftime("%d %B %Y") if event else "",
                          "dept": audience if audience != "all" else extra.get("dept", "")}
            values.update(extra)
            title, body = catalog.NOTICE_TEMPLATES[kind]
            self._add("notices", (self.admin_user, title.format(**values),
                                  body.format(**values), audience,
                                  at(published, int(self.rng.integers(9, 18))), True))

    def _demo_passwords(self):
        """Only demo accounts can log in; every other synthetic user has no password."""
        hasher = PasswordHasher()
        demo_emails = {a.email for a in self.ds.demo_accounts}
        users = self.rows["users"]
        for i, (uid, email, _, role) in enumerate(users):
            if email in demo_emails:
                users[i] = (uid, email, hasher.hash(self.demo_password), role)


def generate(students: int, seed: int, as_of: date, demo_password: str) -> Dataset:
    return Generator(students, seed, as_of, demo_password).generate()
