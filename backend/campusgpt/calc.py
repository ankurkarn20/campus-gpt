"""Deterministic calculations the chatbot and dashboard rely on. Exact arithmetic
(fractions.Fraction), so eligibility is never decided by a floating-point rounding error."""
import math
from dataclasses import dataclass
from fractions import Fraction

ATTENDANCE_TARGET = Fraction(3, 4)


def classes_needed(attended: int, held: int, target: Fraction = ATTENDANCE_TARGET) -> int:
    """Smallest x such that (attended + x) / (held + x) >= target, attending every class."""
    if held == 0 or Fraction(attended, held) >= target:
        return 0
    return math.ceil((target * held - attended) / (1 - target))


def classes_can_miss(attended: int, held: int, target: Fraction = ATTENDANCE_TARGET) -> int:
    """Largest y such that attended / (held + y) >= target: classes that can still be missed."""
    if held == 0 or Fraction(attended, held) < target:
        return 0
    return math.floor(attended / target - held)


# The Dean may condone a shortage down to this (Attendance Policy §4), for at most two
# courses a term.
CONDONATION_FLOOR = Fraction(13, 20)
MAX_CONDONED_COURSES = 2


@dataclass(frozen=True)
class Outlook:
    """Where a course's attendance can end up by the last teaching day."""
    status: str            # safe | on_track | condonation_needed | debarred
    attend_at_least: int   # of the classes left, to finish at 75% (or the best possible)
    best_percentage: float  # if every remaining class is attended


def attendance_outlook(attended: int, held: int, left: int) -> Outlook:
    """Final attendance is attended + x out of held + left after attending x of the `left`
    classes still to come. 'safe': 75% even missing all of them; 'on_track': 75% is
    reachable; 'condonation_needed': only 65-75% is reachable; 'debarred': not even 65%."""
    total = held + left
    if total == 0:
        return Outlook("safe", 0, 100.0)
    best = Fraction(attended + left, total)
    need = max(0, math.ceil(ATTENDANCE_TARGET * total - attended))
    if need == 0:
        status = "safe"
    elif need <= left:
        status = "on_track"
    else:
        status = "condonation_needed" if best >= CONDONATION_FLOOR else "debarred"
        need = left
    return Outlook(status, need, round(float(100 * best), 2))
