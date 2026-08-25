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

    if "by" in q and order_col:
        return (
            f"SELECT * FROM {quote_ident(table)} "
            f"ORDER BY {quote_ident(order_col)} DESC LIMIT {limit}"
        )

    if any(k in q for k in ("top", "highest", "best", "largest")) and order_col:
        return (
            f"SELECT * FROM {quote_ident(table)} "
            f"ORDER BY {quote_ident(order_col)} DESC LIMIT {limit}"
        )

    if any(k in q for k in ("count", "how many")):
        return f"SELECT COUNT(*) AS row_count FROM {quote_ident(table)}"

    return f"SELECT * FROM {quote_ident(table)} LIMIT {limit}"


def schema_as_json(source: DataSource) -> dict:
    return json.loads(source.schema_json) if source.schema_json else {"tables": []}
