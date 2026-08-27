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

from app.services.chart_recommend import is_ratio_column, recommend_chart

ResponseFormat = Literal[
    "metric", "narrative", "chart", "table", "empty", "diagnostic", "meta"
]

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


#: Abbreviations that turn up in generated SQL, and what they mean in a
#: sentence. A reader should never have to parse `avg_stock_level`.
_COLUMN_WORDS = {
    "avg": "average",
    "average": "average",
    "min": "lowest",
    "minimum": "lowest",
    "max": "highest",
    "maximum": "highest",
    "qty": "quantity",
    "num": "number of",
    "cnt": "count of",
    "pct": "%",
    "percent": "%",
    "pc": "%",
    "roi": "ROI",
    "aov": "average order value",
    "yoy": "year on year",
    "mom": "month on month",
    "id": "ID",
    "sku": "SKU",
    "vip": "VIP",
    "sme": "SME",
}

#: Words that add nothing once the sentence already says "total".
_COLUMN_NOISE = ("total",)


def humanize_column(name: str, *, drop_total: bool = False) -> str:
    """`avg_stock_level` -> `average stock level`; `roi_pct` -> `ROI %`."""
    raw = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(name or ""))
    words = [w for w in re.split(r"[\s_]+", raw) if w]
    if drop_total and len(words) > 1 and words[0].lower() in _COLUMN_NOISE:
        words = words[1:]
    spoken = [_COLUMN_WORDS.get(w.lower(), w.lower()) for w in words]
    return re.sub(r"\s+%", " %", " ".join(spoken)).strip() or str(name)


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
    *,
    sql: str | None = None,
) -> dict[str, Any]:
    """Return {format, chart, reason} for a result set."""
    if is_blank_result(columns, rows):
        reason = "no_rows" if not rows else "null_aggregate"
        return {"format": "empty", "chart": None, "reason": reason}

    numeric = _numeric_columns(columns, rows)
    categorical = [c for c in columns if c not in numeric]
    chart = recommend_chart(columns, rows, question=question, sql=sql)
    chartable = chart["type"] != "table" and bool(chart.get("value_keys"))

    wants_chart = _matches(question, _CHART_WORDS)
    wants_table = _matches(question, _TABLE_WORDS)
    wants_narrative = _matches(question, _NARRATIVE_WORDS)
    wants_metric = _matches(question, _METRIC_WORDS)
    # "as a bar chart" is presentation, not a request for prose about charts.
    presentation_only = bool(
        re.search(
            r"(?i)\b(?:as|in|like)\s+(?:a\s+)?(?:bar|line|pie)\s*charts?\b|"
            r"\b(?:bar|line|pie)\s*charts?\b",
            question,
        )
    )
    if presentation_only:
        wants_narrative = False
        wants_chart = True

    # A single number is an answer, not a chart.
    if len(rows) == 1 and len(numeric) == 1 and len(columns) <= 2:
        return {"format": "metric", "chart": None, "reason": "single_value"}

    # Explicit asks win, as long as the data can support them.
    if wants_chart and chartable:
        return {"format": "chart", "chart": chart, "reason": "asked_for_chart"}
    if wants_table:
        return {"format": "table", "chart": None, "reason": "asked_for_table"}
    if wants_narrative:
        # Prose leads; a chart rides along only for a genuine series.
        support = chart if (chartable and len(rows) >= 3) else None
        return {"format": "narrative", "chart": support, "reason": "asked_for_explanation"}

    # One record: management gets a sentence, not a one-row grid — unless they
    # asked for the raw table.
    if len(rows) == 1:
        return {"format": "narrative", "chart": None, "reason": "single_row_prose"}

    if wants_metric and len(rows) <= 2 and numeric:
        return {"format": "metric", "chart": None, "reason": "aggregate_question"}

    # No numeric column — prose for a short list; a grid only when it is long
    # or they asked for one.
    if not numeric:
        if len(rows) > 15:
            return {"format": "table", "chart": None, "reason": "long_text_result"}
        return {"format": "narrative", "chart": None, "reason": "text_result"}

    # Wide result sets are easier to read as a table.
    if len(columns) > 6 and not wants_chart:
        return {"format": "table", "chart": None, "reason": "wide_result"}

    # A clean category/measure or time/measure shape is what charts are for.
    if chartable and categorical and 2 <= len(rows) <= 60:
        return {"format": "chart", "chart": chart, "reason": chart.get("reason", "series")}

    # Default for management: plain language, with a supporting chart when the
    # shape warrants one — not a raw grid.
    if len(rows) > 25:
        return {"format": "table", "chart": None, "reason": "long_result"}
    support = chart if (chartable and len(rows) >= 3) else None
    return {"format": "narrative", "chart": support, "reason": "default_narrative"}


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
            label = humanize_column(col)
            return f"{label.capitalize()} is {_fmt(value)}{where}."

    if len(rows) == 1 and fmt in ("table", "narrative"):
        parts = [f"{humanize_column(c)} {rows[0].get(c)}" for c in columns[:4]]
        return f"One matching record{where}: {', '.join(parts)}."

    label_key = plan.get("chart", {}).get("label_key") if plan.get("chart") else None
    if not label_key:
        label_key = categorical[0] if categorical else columns[0]
    # Describe the leading numeric column: whoever wrote the query put the
    # measure the question asked about first. The chart may plot several.
    # Describe the column the chart plots — both follow what the query sorted
    # by, so the sentence and the picture answer the same question.
    measure = None
    chart_keys = (plan.get("chart") or {}).get("value_keys") or []
    if chart_keys and chart_keys[0] in numeric:
        measure = chart_keys[0]
    elif numeric:
        measure = numeric[0]

    sentences: list[str] = []
    # Management answers lead with the insight, not a row-count preamble.
    if fmt not in ("narrative", "chart", "metric"):
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
            # "Total total_profit" reads as a stutter; the column already says it.
            measure_label = humanize_column(measure, drop_total=True)
            ratio = is_ratio_column(measure)

            if len(ranked) == 1:
                sentences.append(f"{measure_label.capitalize()} is {_fmt(top_value)}.")
            elif ratio:
                # A rate has a range, not a total.
                sentences.append(
                    f"{measure_label.capitalize()} runs from {_fmt(ranked[-1][1])} to "
                    f"{_fmt(top_value)} across the {len(ranked)} rows."
                )
            else:
                sentences.append(f"Total {measure_label} is {_fmt(grand)}.")

            if len(ranked) > 1:
                share = (top_value / grand * 100) if grand and not ratio else 0
                sentences.append(
                    f"{top_label} is highest at {_fmt(top_value)}"
                    + (f" ({share:.0f}% of the total)." if share else ".")
                )
                bottom_label, bottom_value = ranked[-1]
                if bottom_label != top_label:
                    sentences.append(
                        f"{bottom_label} is lowest at {_fmt(bottom_value)}."
                    )

            # "Most revenue and profit" is two questions. When the result also
            # carries a rate, the ranking on it is the other half of the answer.
            companion = next(
                (c for c in numeric if c != measure and is_ratio_column(c)), None
            )
            if companion and len(rows) > 1:
                by_companion: dict[str, float] = {}
                for row in rows:
                    key = str(row.get(label_key, "")).strip() or "(blank)"
                    val = _to_number(row.get(companion))
                    if val is not None:
                        by_companion.setdefault(key, val)
                if len(by_companion) > 1:
                    ordered = sorted(by_companion.items(), key=lambda kv: kv[1], reverse=True)
                    sentences.append(
                        f"On {humanize_column(companion)}, {ordered[0][0]} leads at "
                        f"{_fmt(ordered[0][1])} and {ordered[-1][0]} trails at "
                        f"{_fmt(ordered[-1][1])}."
                    )

    if not sentences:
        key = categorical[0] if categorical else columns[0]
        values = [
            str(row.get(key, "")).strip()
            for row in rows[:8]
            if str(row.get(key, "")).strip()
        ]
        if values:
            label = humanize_column(key)
            if len(values) == 1:
                joined = values[0]
            else:
                joined = ", ".join(values[:-1]) + f" and {values[-1]}"
            more = f" ({len(rows) - len(values)} more)" if len(rows) > len(values) else ""
            return f"The {label} values{where} are {joined}{more}."
        return f"{len(rows)} matching row{'s' if len(rows) != 1 else ''}{where}."

    return " ".join(sentences)


# --- optional LLM narrative -------------------------------------------------

NARRATIVE_SYSTEM = """You brief a busy manager on what the query result means.
Given a user's question and the exact rows a SQL query returned, answer in
2-4 fluent sentences of plain English — natural speech, not a template.

Rules:
- Use ONLY the numbers present in the rows. Never invent or extrapolate.
- Lead with the direct answer; put the key number in the first sentence.
- Sound like a colleague talking, not a dashboard dumping labels
  ("Revenue was £12,400 in June, led by…" not "The total_revenue field shows…").
- Mention the most important figure and any clear outlier or contrast.
- No markdown, no bullet points, no preamble like "Based on the data" or
  "According to the query results".
- Round large amounts readably when the rows already show decimals.
- If the question implies a threshold (stockouts, missed targets, unusually high
  rates) and no row crosses it, say so AND still give the figures: name the
  highest and the lowest. "The data does not show X" on its own is not an answer
  when the rows carry the measure asked about.
- Only say the rows cannot answer the question when the measure it asks about is
  genuinely absent from them.
- Write column names as words: "average stock level", never avg_stock_level.
- The rows are what one query returned, not the whole dataset. Never write that
  something is "the only one" or that "there are no others to compare" — the
  query may simply have asked for a single row. Describe what is there without
  claiming anything about what is not.
- Requests for a bar, line, or pie chart are presentation only. Never refuse an
  answer because the user asked for a chart type — summarise the figures in the
  rows anyway. Chart rendering is handled outside your reply.
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
# Meta questions (identity, how the product works) never touch the data.

QuestionIntent = Literal["diagnostic", "advisory", "factual", "meta"]

#: About the product / assistant — not the business data.
_META_PATTERNS = (
    r"\b(?:which|what)\s+model\s+(?:are\s+you|do\s+you\s+use|is\s+this|am\s+i\s+talking)\b",
    r"\btell\s+me\s+which\s+model\s+you\s+are\b",
    r"\bwho\s+are\s+you\b",
    r"\bwhat\s+are\s+you\b",
    r"\bare\s+you\s+(?:an?\s+)?(?:ai|llm|gpt|claude|gemini|chat\s*gpt|a\s+bot|a\s+model)\b",
    r"\bwhat\s+(?:llm|ai\s+(?:model|provider)|language\s+model)\s+(?:do\s+you|are\s+you|is\s+this)\b",
    r"\bhow\s+(?:do\s+you\s+work|does\s+this\s+(?:app|tool|product|platform)\s+work)\b",
    r"\bwhat\s+can\s+you\s+(?:do|help(?:\s+me|\s+us)?)\b",
    r"\bhelp\s+me\s+(?:use|with)\s+(?:this|the)\s+(?:app|tool|product|platform)?\b",
    r"\b(?:introduce\s+yourself|your\s+(?:name|role|purpose))\b",
)

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


def looks_like_followup(question: str) -> bool:
    """Short continuations that only make sense with the prior question."""
    q = question.lower().strip()
    if not q:
        return False
    words = re.findall(r"[a-z0-9']+", q)
    if re.search(
        r"(?:as|in|like)\s+(?:a\s+)?(?:bar|line|pie)\s*charts?|"
        r"^(?:show|make|draw|plot|render).*(?:bar|line|pie)\s*charts?|"
        r"^(?:bar|line|pie)\s*charts?$",
        q,
    ):
        return True
    if len(words) <= 8 and re.search(
        r"^\s*(?:what|how)\s+about\b|"
        r"^\s*and\s+(?:the\s+|for\s+|by\s+)?|"
        r"^\s*(?:the\s+)?(?:least|most|lowest|highest|worst|best|same)\b|"
        r"^\s*same\s+(?:for|but|with|in)\b|"
        r"^\s*(?:instead|vice\s+versa|opposite)\b|"
        r"\b(?:those|them|that|it)\b",
        q,
    ):
        return True
    return len(words) <= 4


def expand_question_with_context(
    question: str,
    previous_question: str | None,
) -> str:
    """Resolve a follow-up into a standalone question the SQL path can answer.

    Factual queries used to see only the bare follow-up ("what about the least?"),
    which has no measure or period — so the model failed or dumped untargeted rows.
    """
    q = (question or "").strip()
    prev = (previous_question or "").strip()
    if not q or not prev or not looks_like_followup(q):
        return q

    # "as a bar chart" / "show it as a line chart" — same analysis, new presentation.
    if re.search(
        r"(?i)(?:as|in|like)\s+(?:a\s+)?(?:bar|line|pie)\s*charts?|"
        r"(?:show|make|draw|plot|render).*(?:bar|line|pie)\s*charts?|"
        r"^(?:bar|line|pie)\s*charts?$",
        q,
    ):
        chart_word = "bar"
        if re.search(r"(?i)\bline\b", q):
            chart_word = "line"
        elif re.search(r"(?i)\bpie\b", q):
            chart_word = "pie"
        base = re.sub(
            r"(?i)\s*(?:as|in)\s+(?:a\s+)?(?:bar|line|pie)\s*charts?\s*$",
            "",
            prev,
        ).strip(" ?")
        return f"{base} as a {chart_word} chart"

    rewritten = q
    # Flip ranking language so "the least" inherits "highest selling… in June".
    flips = (
        (r"\bhighest\b", "lowest"),
        (r"\bhigh(?:er|est)?\s+selling\b", "lowest selling"),
        (r"\btop\b", "bottom"),
        (r"\bmost\b", "least"),
        (r"\bbest\b", "worst"),
        (r"\blowest\b", "highest"),
        (r"\blow(?:er|est)?\s+selling\b", "highest selling"),
        (r"\bbottom\b", "top"),
        (r"\bleast\b", "most"),
        (r"\bworst\b", "best"),
    )
    ql = q.lower()
    if re.search(r"\b(?:least|lowest|worst|bottom)\b", ql):
        base = prev
        for pattern, repl in flips[:5]:
            base = re.sub(pattern, repl, base, flags=re.IGNORECASE)
        rewritten = base
    elif re.search(r"\b(?:most|highest|best|top)\b", ql) and re.search(
        r"\b(?:least|lowest|worst|bottom)\b", prev, flags=re.IGNORECASE
    ):
        base = prev
        for pattern, repl in flips[5:]:
            base = re.sub(pattern, repl, base, flags=re.IGNORECASE)
        rewritten = base
    elif re.match(r"(?i)^\s*(?:what|how)\s+about\b", q):
        # "what about by region?" → keep prior and append the new clause.
        clause = re.sub(r"(?i)^\s*(?:what|how)\s+about\s+", "", q).strip(" ?")
        rewritten = f"{prev.rstrip(' ?')} — {clause}" if clause else prev

    return rewritten


def question_prompt_block(
    question: str,
    previous_question: str | None,
    context_block: str | None = None,
) -> str:
    """User-message block for SQL generation, including follow-up context.

    The transcript goes in whenever there is one, not only for a question that
    *looks* like a follow-up: "and by region?" is obvious, but "which was worst"
    is not, and both need the turn before them to mean anything.
    """
    resolved = expand_question_with_context(question, previous_question)
    history = f"{context_block.strip()}\n\n" if context_block and context_block.strip() else ""
    if previous_question and looks_like_followup(question):
        return (
            f"{history}"
            f"PREVIOUS QUESTION: {previous_question.strip()}\n"
            f"FOLLOW-UP: {question.strip()}\n"
            f"RESOLVED QUESTION: {resolved}\n\n"
            f"Write SQL for the resolved question."
        )
    return f"{history}Question: {resolved}"


def classify_intent(question: str) -> QuestionIntent:
    """Meta, diagnostic, advisory, or an ordinary factual lookup.

    Meta is checked first so identity questions never hit the SQL path.
    Advisory wins over diagnostic when both match: "why did revenue fall and
    what do we do" still needs the diagnosis, and the advisory path performs
    one anyway.
    """
    if _matches_any(question, _META_PATTERNS):
        return "meta"
    if _matches_any(question, _ADVISORY_PATTERNS):
        return "advisory"
    if _matches_any(question, _DIAGNOSTIC_PATTERNS):
        return "diagnostic"
    return "factual"


def answer_meta_question(
    question: str,
    *,
    platform_name: str = "Cognitive Logic",
) -> str:
    """Plain-language reply for product/identity questions — no SQL, no rows.

    Never names the underlying LLM, provider, or Settings profile.
    """
    name = (platform_name or "").strip() or "Cognitive Logic"
    q = question.lower().strip()

    identity = (
        f"I'm {name}, your business intelligence assistant. "
        "I turn questions about your connected datasets into answers. "
        "I do not invent figures; every business number I give you comes from your data."
    )

    if re.search(r"\bwhat\s+can\s+you\b|\bhelp\b|\bhow\s+do\s+you\s+work\b", q):
        return (
            f"{identity} Ask in plain language — totals, trends, comparisons, or why a "
            "figure moved — and I'll reply with a number, a short explanation, or a chart."
        )

    return identity
