from __future__ import annotations

from typing import Any


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


def recommend_chart(
    columns: list[str],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Heuristic chart recommendation from tabular result shape."""
    if not columns or not rows:
        return {"type": "table", "label_key": None, "value_keys": [], "reason": "empty"}

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
            "value_keys": [],
            "reason": "no_numeric_columns",
        }

    label_key = categorical[0] if categorical else columns[0]
    preferred = ("revenue", "amount", "total", "sales", "value", "count", "profit", "margin")
    ranked = sorted(
        [c for c in numeric if c != label_key],
        key=lambda c: (
            0 if c.lower() in preferred else 1,
            0 if any(p in c.lower() for p in preferred) else 1,
            columns.index(c),
        ),
    )
    value_keys = ranked[:3]
    if not value_keys:
        value_keys = numeric[:1]

    n = len(rows)
    chart_type = "bar"
    reason = "category_vs_metric"
    temporal = bool(categorical) and _looks_temporal(label_key, rows)

    # Time comes first: a date axis is a line (or a bar for very few points),
    # never a pie — slices of a whole make no sense across periods.
    if temporal:
        chart_type = "line" if n >= 3 else "bar"
        reason = "temporal_series" if chart_type == "line" else "few_periods"
    elif len(value_keys) > 1:
        # Several measures compare best side by side.
        chart_type = "bar"
        reason = "multi_metric"
    elif n <= 6 and categorical:
        # Pie only for a small set of parts that add up to a meaningful whole.
        chart_type = "pie"
        reason = "few_categories"

    return {
        "type": chart_type,
        "label_key": label_key,
        "value_keys": value_keys,
        "reason": reason,
    }


def _looks_temporal(label_key: str, rows: list[dict[str, Any]]) -> bool:
    name = label_key.lower()
    if any(tok in name for tok in ("date", "time", "month", "year", "week", "day")):
        return True
    sample = str(rows[0].get(label_key, "")).lower()
    return any(m in sample for m in ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec", "-"))


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
