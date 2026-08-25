from __future__ import annotations

import json
import re

from app.models import DataSource
from app.services.schema_types import SourceSchema, parse_schema_json


def get_source_schema(source: DataSource) -> SourceSchema:
    schema = parse_schema_json(source.schema_json)
    if schema and schema["tables"]:
        return schema
    return {"tables": []}


def build_schema_prompt(source: DataSource) -> str:
    schema = get_source_schema(source)
    if not schema["tables"]:
        return "No schema available for this data source."

    lines: list[str] = [
        f"Data source: {source.name} (type={source.source_type})",
        "Tables:",
    ]
    for table in schema["tables"]:
        cols = ", ".join(f"{c['name']}:{c['type']}" for c in table["columns"])
        lines.append(f"- {table['name']}({cols})")
    return "\n".join(lines)


def build_workspace_schema_prompt(sources: list[DataSource]) -> str:
    """Schema catalog for all ingested sources (LLM picks one dataset)."""
    if not sources:
        return "No data sources are available in the workspace."

    lines: list[str] = [
        "Workspace datasets (query ONE source at a time — do not join across sources):",
    ]
    for source in sources:
        schema = get_source_schema(source)
        lines.append(f"\n### SOURCE_ID={source.id} · {source.name} ({source.source_type})")
        if not schema["tables"]:
            lines.append("(no schema)")
            continue
        for table in schema["tables"]:
            cols = ", ".join(f"{c['name']}:{c['type']}" for c in table["columns"])
            lines.append(f"- {table['name']}({cols})")
    return "\n".join(lines)


def pick_source_for_question(sources: list[DataSource], question: str) -> DataSource | None:
    """Score sources by name/column keyword overlap; used when no LLM / no explicit id."""
    if not sources:
        return None
    if len(sources) == 1:
        return sources[0]

    q = question.lower()
    tokens = {t for t in re.findall(r"[a-z0-9_]+", q) if len(t) > 2}
    best: DataSource | None = None
    best_score = -1
    for source in sources:
        score = 0
        name_l = source.name.lower()
        for t in tokens:
            if t in name_l:
                score += 5
        schema = get_source_schema(source)
        for table in schema["tables"]:
            for col in table["columns"]:
                cl = col["name"].lower()
                for t in tokens:
                    if t == cl or t in cl:
                        score += 2
        if score > best_score:
            best_score = score
            best = source
    return best or sources[0]


def first_table_name(source: DataSource) -> str | None:
    schema = get_source_schema(source)
    if not schema["tables"]:
        return None
    return schema["tables"][0]["name"]


def quote_ident(name: str) -> str:
    """Safe identifier quoting for generated SQL (letters, numbers, underscore)."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ValueError(f"Unsafe identifier: {name}")
    return f"`{name}`"


def _dimension_after_by(question: str, columns: list[str]) -> str | None:
    """Resolve the column named after "by" / "per" / "for each" in a question."""
    match = re.search(r"\b(?:by|per|for each|grouped by)\s+(.+)$", question, re.IGNORECASE)
    if not match:
        return None
    tail = re.sub(r"[^a-z0-9_ ]+", " ", match.group(1).lower())
    words = [w for w in tail.split() if w]
    if not words:
        return None

    def norm(name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", name.lower())

    # Longest phrase first so "store id" beats "store".
    for size in (3, 2, 1):
        for start in range(len(words) - size + 1):
            phrase = norm("".join(words[start : start + size]))
            if not phrase:
                continue
            for col in columns:
                c = norm(col)
                if c == phrase or c.endswith(phrase) or phrase.endswith(c):
                    return col
    return None


def heuristic_sql(source: DataSource, question: str) -> str | None:
    """Simple offline NL→SQL for demos when no API key is configured."""
    table = first_table_name(source)
    if not table:
        return None

    schema = get_source_schema(source)
    columns = [c["name"] for c in schema["tables"][0]["columns"]]
    q = question.lower()

    top_match = re.search(r"top\s+(\d+)", q)
    limit = int(top_match.group(1)) if top_match else 10
    limit = max(1, min(limit, 100))

    # Prefer common metric columns
    order_col = None
    for candidate in ("revenue", "amount", "total", "sales", "value", "count"):
        for col in columns:
            if col.lower() == candidate:
                order_col = col
                break
        if order_col:
            break

    if order_col is None:
        for col in columns:
            if any(k in col.lower() for k in ("rev", "amt", "total", "sale", "price")):
                order_col = col
                break

    # "<measure> by <dimension>" is an aggregation, not a sorted dump. Without
    # a GROUP BY the answer would describe rows instead of the dimension asked
    # about (e.g. listing dates when the question said "by region").
    group_col = _dimension_after_by(q, columns)

    # "over time" / "trend" means group by the date column even without a "by".
    if group_col is None and any(k in q for k in ("over time", "trend", "by month", "monthly", "daily")):
        for col in columns:
            if any(k in col.lower() for k in ("date", "day", "month", "time", "period")):
                group_col = col
                break

    counting = any(k in q for k in ("count", "how many", "number of"))

    # A counting question wants COUNT(*) for its dimension, not a measure sum.
    if group_col and counting:
        return (
            f"SELECT {quote_ident(group_col)}, COUNT(*) AS record_count "
            f"FROM {quote_ident(table)} "
            f"GROUP BY {quote_ident(group_col)} "
            f"ORDER BY 2 DESC LIMIT {limit}"
        )

    if group_col and order_col and group_col != order_col:
        temporal = any(
            k in group_col.lower() for k in ("date", "day", "month", "time", "period", "year")
        )
        order_by = "1 ASC" if temporal else "2 DESC"
        return (
            f"SELECT {quote_ident(group_col)}, "
            f"SUM({quote_ident(order_col)}) AS {quote_ident(order_col)} "
            f"FROM {quote_ident(table)} "
            f"GROUP BY {quote_ident(group_col)} "
            f"ORDER BY {order_by} LIMIT {limit}"
        )

    if group_col and not order_col:
        return (
            f"SELECT {quote_ident(group_col)}, COUNT(*) AS record_count "
            f"FROM {quote_ident(table)} "
            f"GROUP BY {quote_ident(group_col)} "
            f"ORDER BY 2 DESC LIMIT {limit}"
        )

    if any(k in q for k in ("top", "highest", "best", "largest")) and order_col:
        return (
            f"SELECT * FROM {quote_ident(table)} "
            f"ORDER BY {quote_ident(order_col)} DESC LIMIT {limit}"
        )

    if counting:
        return f"SELECT COUNT(*) AS row_count FROM {quote_ident(table)}"

    return f"SELECT * FROM {quote_ident(table)} LIMIT {limit}"


def schema_as_json(source: DataSource) -> dict:
    return json.loads(source.schema_json) if source.schema_json else {"tables": []}
