"""Attendance arithmetic, checked against brute force."""
from fractions import Fraction

import pytest

from campusgpt.calc import classes_can_miss, classes_needed


def test_design_document_example():
    assert classes_needed(41, 60) == 16      # 57 / 76 = 75%


@pytest.mark.parametrize("held", range(61))
def test_matches_brute_force(held):
    target = Fraction(3, 4)
    for attended in range(held + 1):
        need = next(x for x in range(1000)
                    if held + x == 0 or Fraction(attended + x, held + x) >= target)
        assert classes_needed(attended, held) == need
        if held and Fraction(attended, held) >= target:
            miss = max(y for y in range(1000) if Fraction(attended, held + y) >= target)
            assert classes_can_miss(attended, held) == miss
        else:
            assert classes_can_miss(attended, held) == 0
