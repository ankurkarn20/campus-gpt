"""Deterministic answer checks. An answer is correct when every expected fact appears in
it: a number (within a tolerance, so 68.4 matches 68.42 and 1,60,000 matches 160000), a date
or a time in any common format, or one of several phrases. No model judges the answers.
"""
import re
from dataclasses import dataclass
from datetime import date, time

WORD_NUMBERS = {w: n for n, w in enumerate([
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
    "nineteen", "twenty"])}
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]


def normalise(answer: str) -> str:
    """Lower case, digit-group separators removed (1,60,000 -> 160000), dashes unified."""
    text = re.sub(r"(?<=\d),(?=\d)", "", answer.lower())
    return text.replace("–", "-").replace("—", "-").replace(" ", " ")


def numbers(text: str) -> list[float]:
    found = [float(n) for n in re.findall(r"(?<![\d.])\d+(?:\.\d+)?", text)]
    found += [WORD_NUMBERS[w] for w in re.findall(r"[a-z]+", text) if w in WORD_NUMBERS]
    return found


class Fact:
    label: str

    def found(self, text: str) -> bool:
        """`text` is normalised."""
        raise NotImplementedError


@dataclass
class Num(Fact):
    value: float
    tolerance: float = 0.05

    @property
    def label(self) -> str:
        return f"{self.value:g}"

    def found(self, text):
        return any(abs(n - self.value) <= self.tolerance for n in numbers(text))


class Text(Fact):
    """Any one of the phrases, matched case-insensitively on word boundaries."""

    def __init__(self, *phrases: str):
        self.phrases = phrases
        self.label = " | ".join(phrases)

    def found(self, text):
        return any(re.search(rf"(?<!\w){re.escape(normalise(p))}(?!\w)", text)
                   for p in self.phrases)


@dataclass
class When(Fact):
    day: date

    @property
    def label(self) -> str:
        return self.day.isoformat()

    def found(self, text):
        d, month = self.day.day, MONTHS[self.day.month - 1]
        mon = rf"(?:{month}|{month[:3]}\.?)"
        patterns = [rf"(?<!\d)0?{d}(?:st|nd|rd|th)?(?:\s+of)?\s+{mon}(?![a-z])",
                    rf"(?<![a-z]){mon}\s+0?{d}(?!\d)",
                    rf"{self.day.isoformat()}",
                    rf"(?<![\d/.-])0?{d}[/.-]0?{self.day.month}(?![\d])"]
        return any(re.search(p, text) for p in patterns)


@dataclass
class At(Fact):
    clock: time

    @property
    def label(self) -> str:
        return self.clock.strftime("%H:%M")

    def found(self, text):
        h, m = self.clock.hour, self.clock.minute
        h12, suffix = (h % 12 or 12), ("pm" if h >= 12 else "am")
        ampm = rf"\s*{suffix[0]}\.?\s?m\.?"
        minutes = f":{m:02d}"
        patterns = [rf"(?<!\d){h:02d}:{m:02d}(?!\d)", rf"(?<![\d:]){h}:{m:02d}(?!\d)",
                    rf"(?<![\d:])0?{h12}{minutes}{ampm}(?![a-z])"]
        if m == 0:
            patterns.append(rf"(?<![\d:])0?{h12}{ampm}(?![a-z])")
        if h >= 12:                    # an afternoon or evening time written as "10:30"
            patterns.append(rf"(?<![\d:])0?{h12}:{m:02d}(?!\d)")
        return any(re.search(p, text) for p in patterns)


class AnyOf(Fact):
    """At least one of the facts (e.g. a total, or every part of it)."""

    def __init__(self, *options: "Fact | list[Fact]"):
        self.options = [o if isinstance(o, list) else [o] for o in options]
        self.label = " or ".join(" + ".join(f.label for f in o) for o in self.options)

    def found(self, text):
        return any(all(f.found(text) for f in option) for option in self.options)


def check(answer: str, facts: list[Fact]) -> list[bool]:
    text = normalise(answer)
    return [f.found(text) for f in facts]


def cites_expected(citations: list[str], expected: tuple[str, ...]) -> bool:
    """Whether a citation names one of the expected sections or a clause of one."""
    return any(c == e or c.startswith(e + ".") for c in citations for e in expected)
