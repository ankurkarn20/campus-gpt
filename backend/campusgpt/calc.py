"""Deterministic calculations the chatbot and dashboard rely on. Exact arithmetic
(fractions.Fraction), so eligibility is never decided by a floating-point rounding error."""
import math
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
