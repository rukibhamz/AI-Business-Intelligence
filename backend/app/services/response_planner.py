"""Decide how an answer should be presented, and write it in plain language.

Two guardrails live here:

1. **Format** — not every question wants a chart. A count wants a number, an
   explanation wants prose, a lookup wants a table, and only a comparison or a
   trend genuinely wants a chart. `plan_response` picks one.
2. **Grounding** — the narrative is computed from the rows that were actually
   returned. Nothing is asserted that the result set does not support.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from app.services.chart_recommend import recommend_chart

ResponseFormat = Literal["metric", "narrative", "chart", "table", "empty", "diagnostic"]

# --- question intent cues ---------------------------------------------------

_CHART_WORDS = (
    "chart",
    "graph",
    "plot",
    "visuali",  # visualise / visualize / visualization
    "trend",
    "over time",
    "breakdown",
    "distribution",
    "compare",
    "comparison",
    "versus",
    " vs ",
    "by month",
    "by week",
    "by day",
    "by year",
    "by region",
    "by category",
    "by store",
    "by product",
    "share of",
    "proportion",
)

_NARRATIVE_WORDS = (
    "why",
    "explain",
    "summar",  # summary / summarise / summarize
    "describe",
    "tell me about",
    "what happened",
    "how did",
    "how is",
    "how are",
    "insight",
    "analy",  # analyse / analyze / analysis
    "interpret",
    "what does",
    "what do you",
    "should we",
    "recommend",
    "overview",
    "takeaway",
)

_TABLE_WORDS = (
    "list",
    "table",
    "rows",
    "show me the",
    "which records",
    "detail",
    "raw",
    "export",
)

_METRIC_WORDS = (
    "how many",
    "how much",
    "count",
    "total",
    "sum",
    "average",
    "median",
    "what is the",
)


def _matches(question: str, words: tuple[str, ...]) -> bool:
    q = f" {question.lower().strip()} "
    return any(w in q for w in words)


def _is_number(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (int, float)):
        return True
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


def _numeric_columns(columns: list[str], rows: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for col in columns:
        values = [row.get(col) for row in rows]
        hits = sum(1 for v in values if _is_number(v))
        if hits >= max(1, int(len(rows) * 0.6)):
            out.append(col)
    return out


def _fmt(value: float) -> str:
    if abs(value - round(value)) < 0.005:
        return f"{round(value):,}"
    return f"{value:,.2f}"


# --- format selection -------------------------------------------------------


def is_blank_result(columns: list[str], rows: list[dict[str, Any]]) -> bool:
    """True when the query matched nothing.

    An aggregate over zero rows still returns one row — `SUM(x)` yields NULL —
    so "no rows" and "one row of NULLs" mean the same thing to a reader.
    """
    if not columns or not rows:
        return True
    return all(
        row.get(col) is None or str(row.get(col)).strip() == ""
        for row in rows
        for col in columns
    )


def plan_response(
    question: str,
    columns: list[str],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return {format, chart, reason} for a result set."""
    if is_blank_result(columns, rows):
        reason = "no_rows" if not rows else "null_aggregate"
        return {"format": "empty", "chart": None, "reason": reason}

    numeric = _numeric_columns(columns, rows)
    categorical = [c for c in columns if c not in numeric]
    chart = recommend_chart(columns, rows)
    chartable = chart["type"] != "table" and bool(chart.get("value_keys"))

    wants_chart = _matches(question, _CHART_WORDS)
    wants_table = _matches(question, _TABLE_WORDS)
    wants_narrative = _matches(question, _NARRATIVE_WORDS)
    wants_metric = _matches(question, _METRIC_WORDS)

    # A single number is an answer, not a chart.
    if len(rows) == 1 and len(numeric) == 1 and len(columns) <= 2:
        return {"format": "metric", "chart": None, "reason": "single_value"}

    # One record with many fields reads as a table, never as a chart.
    if len(rows) == 1:
        return {"format": "table", "chart": None, "reason": "single_row"}

    # Explicit asks win, as long as the data can support them.
    if wants_chart and chartable:
        return {"format": "chart", "chart": chart, "reason": "asked_for_chart"}
    if wants_table:
        return {"format": "table", "chart": None, "reason": "asked_for_table"}
    if wants_narrative:
        # Prose leads; a chart rides along only for a genuine series.
        support = chart if (chartable and len(rows) >= 3) else None
        return {"format": "narrative", "chart": support, "reason": "asked_for_explanation"}

    # No numeric column means there is nothing to plot.
    if not numeric:
        return {"format": "table", "chart": None, "reason": "no_numeric_columns"}

    # Wide result sets are easier to read as a table.
    if len(columns) > 6 and not wants_chart:
        return {"format": "table", "chart": None, "reason": "wide_result"}

    if wants_metric and len(rows) <= 2 and numeric:
        return {"format": "metric", "chart": None, "reason": "aggregate_question"}

    # A clean category/measure or time/measure shape is what charts are for.
    if chartable and categorical and 2 <= len(rows) <= 60:
        return {"format": "chart", "chart": chart, "reason": chart.get("reason", "series")}

    return {"format": "table", "chart": None, "reason": "default_table"}


# --- grounded narrative -----------------------------------------------------


def describe_result(
    question: str,
    columns: list[str],
    rows: list[dict[str, Any]],
    plan: dict[str, Any],
    *,
    source_name: str | None = None,
    coverage: str | None = None,
) -> str:
    """A plain-language answer built only from the returned rows."""
    if is_blank_result(columns, rows):
        where = f" in {source_name}" if source_name else ""
        message = (
            f"Nothing{where} matches those criteria, so there is no figure to report."
        )
        if coverage:
            message += f" {coverage}"
        return message

    numeric = _numeric_columns(columns, rows)
    categorical = [c for c in columns if c not in numeric]
    fmt = plan.get("format")
    where = f" in {source_name}" if source_name else ""

    if fmt == "metric" and numeric:
        col = numeric[0]
        value = _to_number(rows[0].get(col))
        if value is not None:
            label = col.replace("_", " ")
            return f"{label.capitalize()} is {_fmt(value)}{where}."

    if fmt == "table" and len(rows) == 1:
        parts = [f"{c.replace('_', ' ')} {rows[0].get(c)}" for c in columns[:4]]
        return f"One matching record{where}: {', '.join(parts)}."

    label_key = plan.get("chart", {}).get("label_key") if plan.get("chart") else None
    if not label_key:
        label_key = categorical[0] if categorical else columns[0]
    measure = None
    if plan.get("chart") and plan["chart"].get("value_keys"):
        measure = plan["chart"]["value_keys"][0]
    elif numeric:
        measure = numeric[0]

    sentences: list[str] = []
    sentences.append(
        f"{len(rows)} row{'s' if len(rows) != 1 else ''} returned{where}."
    )

    if measure:
        totals: dict[str, float] = {}
        for row in rows:
            key = str(row.get(label_key, "")).strip() or "(blank)"
            val = _to_number(row.get(measure))
            if val is None:
                continue
            totals[key] = totals.get(key, 0.0) + val

        if totals:
            grand = sum(totals.values())
            ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
            top_label, top_value = ranked[0]
            measure_label = measure.replace("_", " ")

            sentences.append(
                f"Total {measure_label} is {_fmt(grand)}."
                if len(ranked) > 1
                else f"{measure_label.capitalize()} is {_fmt(top_value)}."
            )

            if len(ranked) > 1:
                share = (top_value / grand * 100) if grand else 0
                sentences.append(
                    f"{top_label} leads with {_fmt(top_value)}"
                    + (f" ({share:.0f}% of the total)." if grand else ".")
                )
                bottom_label, bottom_value = ranked[-1]
                if bottom_label != top_label:
                    sentences.append(
                        f"{bottom_label} is lowest at {_fmt(bottom_value)}."
                    )

    return " ".join(sentences)


# --- optional LLM narrative -------------------------------------------------

NARRATIVE_SYSTEM = """You are a business intelligence analyst.
Given a user's question and the exact rows a SQL query returned, answer in
2-4 short sentences of plain English.

Rules:
- Use ONLY the numbers present in the rows. Never invent or extrapolate.
- Lead with the direct answer to the question.
- Mention the most important figure and any clear outlier.
- No markdown, no bullet points, no preamble like "Based on the data".
- If the rows do not answer the question, say so plainly.
"""


def build_narrative_prompt(
    question: str,
    columns: list[str],
    rows: list[dict[str, Any]],
    *,
    source_name: str | None = None,
    currency: str | None = None,
    max_rows: int = 40,
) -> str:
    sample = rows[:max_rows]
    lines = [f"Question: {question}"]
    if source_name:
        lines.append(f"Data source: {source_name}")
    if currency:
        lines.append(
            f"Currency: {currency}. Write money amounts in {currency}; "
            "never use a different currency symbol."
        )
    lines.append(f"Columns: {', '.join(columns)}")
    lines.append(f"Rows returned: {len(rows)}")
    if len(rows) > max_rows:
        lines.append(f"(showing the first {max_rows})")
    for row in sample:
        lines.append(" | ".join(f"{c}={row.get(c)}" for c in columns))
    return "\n".join(lines)


def sanitize_narrative(text: str) -> str:
    """Strip markdown scaffolding an LLM may add despite instructions."""
    cleaned = re.sub(r"^```[a-z]*\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"^[\s>*\-•]+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\*\*(.+?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\s*\n\s*", " ", cleaned)
    return cleaned.strip()


# --- question intent --------------------------------------------------------
#
# Format decides how an answer looks. Intent decides how it is *produced*: a
# "why" question cannot be answered by one SELECT and a summary of its rows, and
# a request for advice is not answered by rows at all. Both need the diagnostic
# path, which compares periods and attributes the change before writing.

QuestionIntent = Literal["diagnostic", "advisory", "factual"]

#: Asking what caused a movement.
_DIAGNOSTIC_PATTERNS = (
    r"\bwhy\b",
    r"\bwhat\s+(?:caused|drove|led\s+to|is\s+driving|are\s+driving|is\s+causing)\b",
    r"\bwhat(?:'s|\s+is)\s+behind\b",
    r"\bwhat\s+happened\b",
    r"\breasons?\s+(?:for|behind|why)\b",
    r"\broot\s+cause\b",
    r"\bexplain\s+(?:the\s+)?(?:drop|fall|decline|decrease|dip|spike|jump|increase|rise|change|growth|loss)\b",
    r"\b(?:driver|drivers)\s+of\b",
    r"\bwhat\s+is\s+going\s+on\s+with\b",
)

#: Asking what to do about it.
_ADVISORY_PATTERNS = (
    r"\bwhat\s+(?:should|can|could|would|do)\s+(?:we|i|they|you|the\s+\w+)\b",
    r"\bhow\s+(?:do|can|should|would|might)\s+(?:we|i|they|you)\b",
    r"\bhow\s+to\s+\w+",
    r"\brecommend\w*\b",
    r"\bsuggest\w*\b",
    r"\badvice\b",
    r"\baction\s+plan\b",
    r"\bnext\s+steps?\b",
    r"\bwhat\s+now\b",
    r"\b(?:ways?|steps?|ideas?|options?|plans?)\s+to\b",
    r"\b(?:remediate|remedy|mitigate|turn\s+(?:this\s+)?around|course\s+correct)\b",
    r"\b(?:fix|solve|address|reverse|stop|prevent|avoid|recover\s+from)\s+(?:this|it|that|the\b|these|our\b|another\b)",
    r"\bhelp\s+(?:me|us)\s+\w+",
    r"\bwhat\s+would\s+you\s+do\b",
    r"\bshould\s+(?:we|i)\b",
)

#: Words that make a bare follow-up ("and the loss?") read as being about a move.
_MOVEMENT_WORDS = (
    "fall",
    "fell",
    "falling",
    "drop",
    "dropped",
    "dropping",
    "decline",
    "declined",
    "decrease",
    "decreased",
    "down",
    "dip",
    "slump",
    "loss",
    "losses",
    "shrink",
    "shrank",
    "underperform",
    "spike",
    "surge",
    "jump",
    "jumped",
    "rise",
    "rose",
    "growth",
    "grew",
    "up",
)


def _matches_any(question: str, patterns: tuple[str, ...]) -> bool:
    q = question.lower().strip()
    return any(re.search(p, q) for p in patterns)


def mentions_movement(question: str) -> bool:
    q = f" {question.lower().strip()} "
    return any(f" {w} " in q or f" {w}?" in q or f" {w}," in q for w in _MOVEMENT_WORDS)


def classify_intent(question: str) -> QuestionIntent:
    """Diagnostic, advisory, or an ordinary factual lookup.

    Advisory wins when both match: "why did revenue fall and what do we do"
    still needs the diagnosis, and the advisory path performs one anyway.
    """
    if _matches_any(question, _ADVISORY_PATTERNS):
        return "advisory"
    if _matches_any(question, _DIAGNOSTIC_PATTERNS):
        return "diagnostic"
    return "factual"
