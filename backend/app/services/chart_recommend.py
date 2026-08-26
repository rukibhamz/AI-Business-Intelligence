from __future__ import annotations

import re
from typing import Any

#: Column names whose values are rates, averages or ratios. Summing them
#: produces a number that means nothing — "total return rate" is not a thing,
#: and a rate does not share a chart axis with a count.
_RATIO_HINTS = (
    "_pct",
    "percent",
    "rate",
    "ratio",
    "avg",
    "average",
    "mean",
    "margin",
    "attainment",
    "rating",
    "score",
    "per_",
)


def is_ratio_column(name: str) -> bool:
    """True when the values are rates or averages — never total these."""
    key = name.lower()
    return any(hint in key for hint in _RATIO_HINTS)


#: Percentages have their own scale; so does a 1-5 rating. Everything else —
#: money, counts, and the averages and minimums of them — shares one axis.
_PERCENT_HINTS = ("_pct", "percent", "rate", "ratio", "margin", "attainment", "share")
_SCORE_HINTS = ("rating", "score", "csat", "nps")


def axis_family(name: str) -> str:
    """Which columns can be drawn against the same axis.

    An average of a quantity belongs with that quantity: avg stock and lowest
    stock are both stock. A percentage does not belong with either.
    """
    key = name.lower()
    if any(hint in key for hint in _PERCENT_HINTS):
        return "percent"
    if any(hint in key for hint in _SCORE_HINTS):
        return "score"
    return "amount"


def _is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if value is None:
        return False
    text = str(value).strip().replace(",", "")
    if not text:
        return False
    try:
        float(text)
        return True
    except ValueError:
        return False


def _to_number(value: Any) -> float | None:
    if not _is_number(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return float(str(value).strip().replace(",", ""))


#: A pie is right for parts of one whole. A ranking is not that — "which store
#: is best" wants lengths side by side, not slices.
#: "breakdown" belongs to the comparison cues below, which make bars — one word
#: cannot decide two different chart types.
_SHARE_WORDS = ("share of", "proportion", "split", "mix", "percent of", "% of", "distribution")


def ordered_measure(sql: str | None, columns: list[str]) -> str | None:
    """The column a query sorted by — which is the column it was asked about.

    A query answering "which product is returned most" selects the order counts
    *and* the rate, then sorts by the rate. Charting the counts plots the
    ingredients and hides the answer, so the sort is the most reliable signal of
    which column carries the point.
    """
    if not sql or not columns:
        return None
    match = re.search(r"\border\s+by\s+(.+?)(?:\s+limit\b|$)", sql, re.IGNORECASE | re.DOTALL)
    if not match:
        return None

    first = match.group(1).split(",")[0].strip()
    first = re.sub(r"\s+(asc|desc)\s*$", "", first, flags=re.IGNORECASE).strip()
    first = first.strip("`\"[] ")

    if first.isdigit():  # ORDER BY 2 — a column position, 1-based
        index = int(first) - 1
        return columns[index] if 0 <= index < len(columns) else None

    return {c.lower(): c for c in columns}.get(first.lower())


#: Questions whose answer is the ratio, even when an amount sits beside it.
_RATIO_QUESTIONS = (
    "margin", "profitability", "profitable", "return rate", "roi",
    "return on", "attainment", "rate", "per unit", "efficiency",
)


def prefers_ratio(question: str | None) -> bool:
    q = f" {(question or '').lower()} "
    return any(word in q for word in _RATIO_QUESTIONS)


def wants_share(question: str | None) -> bool:
    q = f" {(question or '').lower()} "
    return any(word in q for word in _SHARE_WORDS)


def recommend_chart(
    columns: list[str],
    rows: list[dict[str, Any]],
    *,
    question: str | None = None,
    sql: str | None = None,
) -> dict[str, Any]:
    """Heuristic chart recommendation from tabular result shape.

    Pass the question when available so comparisons and explicit "bar chart"
    asks are not forced into a time-series line.
    """
    if not columns or not rows:
        return {
            "type": "table",
            "label_key": None,
            "label_keys": [],
            "value_keys": [],
            "reason": "empty",
        }

    numeric: list[str] = []
    categorical: list[str] = []
    for col in columns:
        values = [row.get(col) for row in rows]
        nums = sum(1 for v in values if _is_number(v))
        if nums >= max(1, len(rows) * 0.6):
            numeric.append(col)
        else:
            categorical.append(col)

    if not numeric:
        return {
            "type": "table",
            "label_key": columns[0],
            "label_keys": [columns[0]],
            "value_keys": [],
            "reason": "no_numeric_columns",
        }

    label_key = categorical[0] if categorical else columns[0]

    # "Which store/product combination" returns two categorical columns, and
    # labelling by the first alone prints Lagos three times with no way to tell
    # the bars apart. When the leading column repeats, the label is the pair.
    label_keys = [label_key]
    if len(categorical) > 1:
        leading = [str(row.get(label_key, "")) for row in rows]
        if len(set(leading)) < len(rows):
            label_keys = categorical[:2]
    preferred = ("revenue", "amount", "total", "sales", "value", "count", "profit", "margin")
    answer_column = ordered_measure(sql, columns)
    if answer_column not in numeric:
        # The query sorted by its label — a time series. The measure then comes
        # from the question: "is growth leading to profitability" is answered by
        # the margin line, not by the revenue line beside it.
        answer_column = None
        if prefers_ratio(question):
            answer_column = next((c for c in numeric if is_ratio_column(c)), None)
    ranked = sorted(
        [c for c in numeric if c != label_key],
        key=lambda c: (
            # Whatever the query sorted by is the answer; the rest is working.
            0 if c == answer_column else 1,
            0 if c.lower() in preferred else 1,
            0 if any(p in c.lower() for p in preferred) else 1,
            columns.index(c),
        ),
    )
    # A rate and a count do not share an axis: plotting 14.5% beside 620 units
    # makes the rate invisible and the chart a lie. Keep the family the leading
    # measure belongs to.
    if ranked:
        leading = axis_family(ranked[0])
        ranked = [c for c in ranked if axis_family(c) == leading]

    value_keys = ranked[:3]
    if not value_keys:
        value_keys = numeric[:1]

    n = len(rows)
    chart_type = "bar"
    reason = "category_vs_metric"

    # Vertical bars only fit a handful of short labels: beyond that the axis
    # silently drops most of them, so the reader sees twenty bars and four
    # names that do not line up. Horizontal bars give every label its own row.
    longest_label = max(
        (len(" · ".join(str(row.get(k, "")) for k in label_keys)) for row in rows),
        default=0,
    )
    crowded = n > 8 or longest_label > 16
    temporal = bool(categorical) and _looks_temporal(label_key, rows)
    q = f" {(question or '').lower().strip()} "
    forced = _forced_chart_type(q)
    wants_comparison = _wants_comparison_chart(q)

    # Time comes first: a date axis is a line (or a bar for very few points),
    # never a pie — slices of a whole make no sense across periods.
    # Month-on-month / per-product comparisons stay bars: a single line across
    # mixed product-periods is harder to read than grouped bars.
    if temporal and not wants_comparison and forced not in ("bar", "pie"):
        chart_type = "line" if n >= 3 else "bar"
        reason = "temporal_series" if chart_type == "line" else "few_periods"
    elif crowded and categorical:
        chart_type = "hbar"
        reason = "many_categories" if n > 8 else "long_labels"
    elif len(value_keys) > 1:
        # Several measures compare best side by side.
        chart_type = "bar"
        reason = "multi_metric"
    elif wants_comparison:
        chart_type = "bar"
        reason = "comparison"
    elif (
        n <= 6
        and categorical
        and axis_family(value_keys[0]) == "amount"
        and wants_share(question)
    ):
        # Pie only for a small set of parts that add up to a meaningful whole,
        # and only when the question is about that split. A ranking reads as
        # lengths, not slices, and rates are not parts of anything.
        chart_type = "pie"
        reason = "share_of_total"

    if forced and chart_type != "table":
        # Honour an explicit ask when the shape can still be drawn.
        if forced == "pie" and (temporal or len(value_keys) > 1 or n > 8):
            pass  # keep the safer default
        else:
            chart_type = forced
            reason = f"asked_for_{forced}"

    return {
        "type": chart_type,
        "label_key": label_key,
        "label_keys": label_keys,
        "value_keys": value_keys,
        "reason": reason,
    }


def _forced_chart_type(q: str) -> str | None:
    """bar / line / pie when the user named the chart type."""
    if re.search(r"\bbar\s*charts?\b|\bas\s+bars?\b|\bin\s+a\s+bar\b", q):
        return "bar"
    if re.search(r"\bline\s*charts?\b|\bas\s+a\s+line\b|\btrend\s+line\b", q):
        return "line"
    if re.search(r"\bpie\s*charts?\b|\bas\s+a\s+pie\b", q):
        return "pie"
    return None


def _wants_comparison_chart(q: str) -> bool:
    """Month-on-month and side-by-side compares read better as bars than lines."""
    cues = (
        "month on month",
        "month-on-month",
        "month over month",
        "mom ",
        " year on year",
        "year-over-year",
        "yoy ",
        "compare",
        "comparison",
        " versus ",
        " vs ",
        "each product",
        "per product",
        "by product",
        "for each",
        "side by side",
        "breakdown",
    )
    return any(cue in q for cue in cues)


#: A label reads as a period when it parses like one — "2026-06", "12 Mar",
#: "Q3 2026". A bare hyphen does not qualify: "Abuja-Central" is a store, and
#: treating it as a date drew a trend line across four unrelated shops.
_TEMPORAL_VALUE = re.compile(
    r"^\s*(?:"
    r"\d{4}(?:[-/]\d{1,2}){0,2}"                      # 2026, 2026-06, 2026-06-27
    r"|\d{1,2}[-/]\d{1,2}(?:[-/]\d{2,4})?"            # 27/06, 27-06-2026
    r"|\d{1,2}\s+[a-z]{3,}"                           # 27 June
    r"|[a-z]{3,}\s+\d{1,2}"                           # June 27
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*\d{2,4}"
    r"|q[1-4][\s-]*\d{2,4}"                           # Q3 2026
    r"|w(?:ee)?k\s*\d{1,2}"                           # week 12
    r")\s*$",
    re.IGNORECASE,
)


def _looks_temporal(label_key: str, rows: list[dict[str, Any]]) -> bool:
    name = label_key.lower()
    if any(tok in name for tok in ("date", "time", "month", "year", "week", "day", "period", "quarter")):
        return True
    sample = [str(row.get(label_key, "")).strip() for row in rows[:5]]
    present = [v for v in sample if v]
    if not present:
        return False
    # Every label has to read as a period, not just the first one.
    return all(_TEMPORAL_VALUE.match(v) for v in present)


def serialize_rows_for_chart(
    rows: list[dict[str, Any]],
    label_key: str | None,
    value_keys: list[str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows[:50]:
        item: dict[str, Any] = {}
        if label_key:
            item[label_key] = row.get(label_key)
        for key in value_keys:
            item[key] = _to_number(row.get(key))
        out.append(item)
    return out
