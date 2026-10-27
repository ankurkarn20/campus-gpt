"""The academic calendar: terms, teaching days and holidays.

Shared by the seed generator (which schedules classes on teaching days) and the eligibility
check (which projects how many classes are still to come), so both agree on the calendar.
"""
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta

# Fixed national holidays (month, day): no classes.
HOLIDAYS = [(1, 26), (8, 15), (10, 2)]


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

    @property
    def last_teaching_day(self) -> date:
        return self.end_term_start - timedelta(days=1)

    def semesters(self, duration: int) -> list[int]:
        return [s for s in range(1 if self.odd else 2, duration + 1, 2)]

    def is_teaching_day(self, day: date) -> bool:
        """Classes run on weekdays from the start of term to the last teaching day, except
        on holidays and during the mid-term examination week."""
        return (self.start <= day <= self.last_teaching_day and day.weekday() < 5
                and (day.month, day.day) not in HOLIDAYS
                and not self.mid_term_week <= day < self.mid_term_week + timedelta(days=6))


def no_class_reason(term: Term, day: date) -> str | None:
    """Why there are no classes on `day`, or None on a teaching day."""
    if term.is_teaching_day(day):
        return None
    if day < term.start:
        return "before the term starts"
    if day > term.last_teaching_day:
        return "teaching has ended for the term (end-term examinations)"
    if day.weekday() >= 5:
        return "weekend"
    if (day.month, day.day) in HOLIDAYS:
        return "public holiday"
    return "mid-term examination week"


def term_for(day: date) -> Term:
    """The term containing `day`: odd terms run from late July, even terms from January."""
    if day.month >= 7:
        start, end, odd = date(day.year, 7, 20), date(day.year, 12, 5), True
        code = f"{day.year}-ODD"
    else:
        start, end, odd = date(day.year, 1, 12), date(day.year, 5, 23), False
        code = f"{day.year}-EVEN"
    start -= timedelta(days=start.weekday())  # align to Monday
    return Term(code, start, end, odd)


def days(start: date, end: date) -> Iterator[date]:
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def classes_left(term: Term, weekdays: Iterable[int], today: date) -> int:
    """Classes of a course meeting on `weekdays` (0 = Monday) from `today` (classes are
    recorded the day after they are held) up to the last teaching day."""
    meets = set(weekdays)
    return sum(1 for d in days(today, term.last_teaching_day)
               if d.weekday() in meets and term.is_teaching_day(d))
