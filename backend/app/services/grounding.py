"""Check that a written answer only states figures its evidence supports.

Every prompt in this codebase tells the model to use only the figures it was
given. That instruction is necessary and not sufficient — asked "how do I
improve laptop sales in Ibadan?", a model given a region-level revenue
comparison replied that "Laptop 14 sold only 28 units in Ibadan". There is no
product breakdown in that evidence at all; the sole `28` in it was `+28%` from
the cost line, re-served as a unit count.

So the rule is enforced here rather than merely asked for, the same way
`parse_practices` drops a practice whose source URL was never retrieved: the
answer is checked against the evidence it was built from, and one unsupported
figure sends the whole answer back to the deterministic renderer. That renderer
says the same thing from the same numbers, so the cost of a false positive is
fluency; the cost of a false negative is a wrong figure in a decision.

Numbers are compared **with their unit**, which is the part that matters. A bare
value check passes `28 units` against `+28%` — the two are the same number and
completely different claims.
"""

from __future__ import annotations

import re
from typing import Literal

#: What a number is counting. Two figures only match when both agree.
Unit = Literal["percent", "points", "plain"]

#: Relative slack for a restated figure. Models legitimately round — 16,681,848
#: becomes "16.7 million" — but they should not drift further than that.
_TOLERANCE = 0.01

#: Written multipliers a model uses when rounding a large figure.
_SCALES = {
    "k": 1_000, "thousand": 1_000,
    "m": 1_000_000, "mn": 1_000_000, "million": 1_000_000,
    "bn": 1_000_000_000, "billion": 1_000_000_000,
}

#: A number, its optional written scale, and whatever unit marker follows it.
_NUMBER = re.compile(
    r"""(?<![\w.])
    (?P<value>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)
    \s*
    (?P<scale>k|m|mn|bn|thousand|million|billion)?
    \s*
    (?P<unit>%|percent(?:age)?\s+points?|points?|pts?)?
    """,
    re.IGNORECASE | re.VERBOSE,
)

#: Years read as labels, not quantities — "Jun 2026" is not a figure to check.
_YEAR = re.compile(r"(?:19|20)\d{2}")


def _unit_of(scale: str | None, marker: str | None) -> Unit:
    if marker:
        low = marker.lower()
        if low == "%" or low.startswith("percent") and "point" not in low:
            return "percent"
        if "point" in low or low.startswith("pt"):
            return "points"
    return "plain"


def _half_unit(raw: str, multiplier: float) -> float:
    """Half a unit of the precision the figure was actually written to.

    This is what separates a rounding from a different number. Evidence saying
    21.6% supports an answer saying "22%" — one decimal place of rounding — but
    not one saying "12.4%" against evidence of 12%, because stating a decimal
    claims a precision the evidence never had.
    """
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    return 0.5 * (10 ** -decimals) * multiplier


def extract_figures(text: str) -> list[tuple[float, Unit, str, float]]:
    """Every number in `text`, as (value, unit, as-written, rounding slack).

    Percentages keep their sign-free magnitude: an answer saying a figure fell
    3.6 points and evidence saying it moved -3.6 points agree.
    """
    out: list[tuple[float, Unit, str]] = []
    for match in _NUMBER.finditer(text or ""):
        raw = match.group("value")
        if _YEAR.fullmatch(raw):
            continue
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        scale = match.group("scale")
        multiplier = _SCALES[scale.lower()] if scale else 1
        out.append(
            (
                abs(value * multiplier),
                _unit_of(scale, match.group("unit")),
                match.group(0).strip(),
                _half_unit(raw.replace(",", ""), multiplier),
            )
        )
    return out


def _supported(value: float, unit: Unit, slack: float, allowed) -> bool:
    for other, other_unit, _, _other_slack in allowed:
        if unit != other_unit:
            continue
        if abs(value - other) <= max(slack, abs(other) * _TOLERANCE):
            return True
    # Deliberately no allowance for a percentage "derived" from two figures in
    # the evidence. With a dozen numbers to divide, almost any percentage can be
    # reached that way, so the allowance would license the arithmetic these
    # prompts exist to keep the model out of. Every share the answer may state
    # is already computed and present.
    return False


def ungrounded_figures(answer: str, evidence: str) -> list[str]:
    """Figures the answer states that the evidence does not support.

    Returns the offending text as written, so a caller can log what was rejected
    rather than only that something was.
    """
    if not answer or not evidence:
        return []
    allowed = extract_figures(evidence)
    if not allowed:
        return []
    return [
        written
        for value, unit, written, slack in extract_figures(answer)
        if not _supported(value, unit, slack, allowed)
    ]


def is_grounded(answer: str, evidence: str) -> bool:
    return not ungrounded_figures(answer, evidence)
