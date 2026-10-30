"""Answer verification: every figure in an answer must come from what the model was given.

The model sees the instructions (today's date, the student's profile, prefetched passages
and records), the student's messages and the tool results. A number, date or time in the
answer that appears in none of them, and is not a total or difference of record fields,
was invented. Rounding is allowed (68 or 68.4 for
68.42), as are the parts of dates and times (2 for 2026-11-02, 2 PM for 14:00).

This catches invented figures (an exam date, a room, an amount), not wrong claims made with
real figures ("you are short in a course at 84%"); those need the record tools' verdicts.
"""
import re
from dataclasses import dataclass
from typing import Any

# A citation in an answer: [Attendance Policy §4] or [Attendance Policy §4.2].
CITATION = re.compile(r"\[([^\[\]]+?§\s*\d+(?:\.\d+)*)\]")
# A number as written in an answer: 1,60,000 / 68.42 / 2nd. Not part of a word or code
# (CSE301), and not a section number (§4.2) or a list marker (handled below).
NUMBER = re.compile(r"(?<![\w§.,])(\d+(?:,\d+)*(?:\.\d+)?)(?:st|nd|rd|th)?(?![\w.]\d|\w)")
LIST_MARKER = re.compile(r"^\s*\d+[.)]\s", re.MULTILINE)
SCALE = re.compile(r"\s*(lakh|lac|crore)", re.IGNORECASE)
MULTIPLIER = {"lakh": 1e5, "lac": 1e5, "crore": 1e7}


@dataclass(frozen=True)
class Claim:
    text: str          # as written, e.g. "1,60,000" or "68.4"
    value: float
    tolerance: float   # half a unit of the last digit written: 68.4 covers 68.35-68.45


def claims(answer: str) -> list[Claim]:
    """The numbers an answer states, leaving out citations and list markers."""
    text = LIST_MARKER.sub(" ", CITATION.sub(" ", answer))
    out = []
    for m in NUMBER.finditer(text):
        written = m.group(1)
        digits = written.replace(",", "")
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        value, tolerance = float(digits), 0.5 * 10 ** -decimals
        if scale := SCALE.match(text, m.end()):
            factor = MULTIPLIER[scale.group(1).lower()]
            value, tolerance = value * factor, tolerance * factor
        out.append(Claim(written + (scale.group(0) if scale else ""), value, tolerance))
    return out


def _numbers(text: str) -> set[float]:
    found = set()
    for m in re.finditer(r"\d+(?:,\d+)*(?:\.\d+)?", text):
        found.add(float(m.group().replace(",", "")))
    # Times: 14:00 is also 2 (PM).
    for m in re.finditer(r"(?<!\d)([01]?\d|2[0-3]):[0-5]\d", text):   # also 2026-11-06T14:00
        hour = int(m.group(1))
        if hour > 12:
            found.add(float(hour - 12))
    return found


def _strings(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return [] if value is None or isinstance(value, bool) else [str(value)]


def _totals(value: Any) -> set[float]:
    """Arithmetic a correct answer does on records: the total of a field over a list (the
    balance of all invoices), and sums and differences of two fields of one record
    (classes held minus attended). Only over tool results, never over policy text, whose
    many small numbers would make nearly any figure a sum of two of them."""
    out: set[float] = set()
    if isinstance(value, list):
        rows = [v for v in value if isinstance(v, dict)]
        for key in {k for r in rows for k, v in r.items() if _number(v) is not None}:
            out.add(sum(_number(r.get(key)) or 0 for r in rows))
        for v in value:
            out |= _totals(v)
    elif isinstance(value, dict):
        nums = [n for v in value.values() if (n := _number(v)) is not None]
        for i, a in enumerate(nums):
            for b in nums[i + 1:]:
                out |= {a + b, a - b, b - a}
        for v in value.values():
            out |= _totals(v)
    return out


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and re.fullmatch(r"-?\d+(?:\.\d+)?", value):
        return float(value)
    return None


def grounding(messages: list[dict], sources: list[dict]) -> set[float]:
    """Every number the model was given (instructions, the student's messages, tool results)
    and the totals and differences of record fields."""
    texts = [m["content"] for m in messages
             if m["role"] in ("system", "user") and isinstance(m.get("content"), str)]
    texts += [s for source in sources for s in _strings(source["result"])]
    known = {n for t in texts for n in _numbers(t)}
    for source in sources:
        if source["tool"] != "search_university_documents":
            known |= _totals(source["result"])
    return known


def _supported(claim: Claim, known: set[float]) -> bool:
    return any(abs(claim.value - k) <= claim.tolerance for k in known)


def unsupported(answer: str, messages: list[dict], sources: list[dict]) -> list[str]:
    """Figures in the answer that nothing the model was given supports, each once."""
    known = grounding(messages, sources)
    out = []
    for c in claims(answer):
        if c.text not in out and not _supported(c, known):
            out.append(c.text)
    return out


def feedback(figures: list[str], citations: list[str]) -> str:
    """The message that asks the model to correct its answer."""
    problems = []
    if figures:
        problems.append("these figures appear in none of the records or passages you were "
                        "given: " + ", ".join(figures))
        problems.append("call the tools for any record you have not fetched")
    if citations:
        problems.append("these citations match no retrieved passage: " + ", ".join(citations)
                        + "; cite only a passage's \"cite\" value, or search the documents")
    return ("(Automatic check by CampusGPT, not written by the student.) Your answer is not "
            "supported: " + "; ".join(problems) + ". Write the whole answer again, using only "
            "figures from tool results and passages, in the language the student used. Do not "
            "mention this check.")
