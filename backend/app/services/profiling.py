"""Column profiles: what values a column actually holds.

Without this the SQL planner only sees column names and types, so a question
like "how much did we make between March and May" produces a date filter with
an invented year and matches nothing. Profiles put the real ranges and the
real category values in front of the planner.
"""

from __future__ import annotations

from typing import Any, TypedDict

from app.services.analytics import to_date, to_number

#: Text columns with at most this many distinct values are listed in full.
MAX_ENUM_VALUES = 12
#: Rows scanned when profiling. Enough to be representative, cheap to compute.
PROFILE_SAMPLE_ROWS = 5000


class ColumnProfile(TypedDict, total=False):
    kind: str  # "date" | "number" | "category" | "text"
    min: str
    max: str
    values: list[str]
    null_ratio: float


def profile_column(values: list[Any]) -> ColumnProfile:
    present = [v for v in values if v is not None and str(v).strip() != ""]
    total = len(values) or 1
    null_ratio = round(1 - len(present) / total, 3)

    if not present:
        return {"kind": "text", "null_ratio": null_ratio}

    # Dates first: a date column is usually also parseable as text.
    dates = [d for d in (to_date(v) for v in present) if d is not None]
    if len(dates) >= len(present) * 0.8:
        return {
            "kind": "date",
            "min": min(dates).isoformat(),
            "max": max(dates).isoformat(),
            "null_ratio": null_ratio,
        }

    numbers = [n for n in (to_number(v) for v in present) if n is not None]
    if len(numbers) >= len(present) * 0.8:
        return {
            "kind": "number",
            "min": _trim(min(numbers)),
            "max": _trim(max(numbers)),
            "null_ratio": null_ratio,
        }

    distinct = sorted({str(v).strip() for v in present})
    if len(distinct) <= MAX_ENUM_VALUES:
        return {"kind": "category", "values": distinct, "null_ratio": null_ratio}

    return {"kind": "text", "null_ratio": null_ratio}


def _trim(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.2f}"


def profile_rows(columns: list[str], rows: list[dict[str, Any]]) -> dict[str, ColumnProfile]:
    sample = rows[:PROFILE_SAMPLE_ROWS]
    return {col: profile_column([row.get(col) for row in sample]) for col in columns}


def describe_profile(profile: ColumnProfile | None) -> str:
    """One-line hint appended to a column in the planner prompt."""
    if not profile:
        return ""
    kind = profile.get("kind")
    if kind == "date":
        return f" [dates {profile.get('min')} to {profile.get('max')}]"
    if kind == "number":
        return f" [{profile.get('min')} to {profile.get('max')}]"
    if kind == "category":
        values = profile.get("values") or []
        return f" [one of: {', '.join(values)}]"
    return ""


def attach_profiles(
    schema: dict[str, Any],
    profiles: dict[str, ColumnProfile],
    table: str | None = None,
) -> dict[str, Any]:
    """Write profiles onto a table's columns — the first unless named."""
    tables = schema.get("tables") or []
    if not tables:
        return schema
    chosen = next((t for t in tables if t.get("name") == table), tables[0])
    for column in chosen.get("columns", []):
        found = profiles.get(column["name"])
        if found:
            column["profile"] = found
    return schema


def schema_date_range(schema: dict[str, Any]) -> tuple[str, str] | None:
    """Overall date span across a schema's date columns, if any."""
    lo: str | None = None
    hi: str | None = None
    for table in schema.get("tables") or []:
        for column in table.get("columns", []):
            profile = column.get("profile") or {}
            if profile.get("kind") != "date":
                continue
            if profile.get("min") and (lo is None or profile["min"] < lo):
                lo = profile["min"]
            if profile.get("max") and (hi is None or profile["max"] > hi):
                hi = profile["max"]
    return (lo, hi) if lo and hi else None
