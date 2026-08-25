from __future__ import annotations

import re
from typing import Any

CANONICAL_FIELDS = [
    "Unmapped",
    "Ignore",
    "Date",
    "Timestamp",
    "Revenue",
    "Cost",
    "Profit",
    "Quantity",
    "Price",
    "Store ID",
    "Region",
    "Country",
    "Product",
    "Customer",
    "Name",
    "Category",
    "Status",
]

# keyword → canonical
_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("date", "dt", "day", "txn_date", "order_date"), "Date"),
    (("time", "timestamp", "ts"), "Timestamp"),
    (("revenue", "rev", "sales", "gross", "amount", "total"), "Revenue"),
    (("cost", "cogs", "expense"), "Cost"),
    (("profit", "margin"), "Profit"),
    (("qty", "quantity", "units", "count"), "Quantity"),
    (("price", "unit_price"), "Price"),
    (("store", "loc_id", "location", "branch"), "Store ID"),
    (("region", "area", "zone"), "Region"),
    (("country", "nation"), "Country"),
    (("product", "sku", "item"), "Product"),
    (("customer", "client", "buyer"), "Customer"),
    (("name", "title"), "Name"),
    (("category", "type", "segment"), "Category"),
    (("status", "state"), "Status"),
]


def suggest_canonical(column_name: str) -> str:
    key = column_name.lower().strip()
    key = re.sub(r"[^a-z0-9_]+", "_", key)
    for tokens, canonical in _HINTS:
        if any(tok in key for tok in tokens):
            return canonical
    return "Unmapped"


def suggest_mapping(columns: list[str]) -> dict[str, str]:
    return {col: suggest_canonical(col) for col in columns}


def columns_from_schema(schema_json: str | None) -> list[str]:
    if not schema_json:
        return []
    import json

    try:
        data = json.loads(schema_json)
    except json.JSONDecodeError:
        return []
    tables = data.get("tables") or []
    if not tables:
        return []
    return [c["name"] for c in tables[0].get("columns", [])]


def enrich_config_with_mapping(
    config: dict[str, Any],
    columns: list[str],
    *,
    force_reset: bool = False,
) -> dict[str, Any]:
    """Ensure field_mapping exists; suggest for new columns."""
    out = dict(config)
    existing = out.get("field_mapping") if isinstance(out.get("field_mapping"), dict) else {}
    if force_reset or not existing:
        out["field_mapping"] = suggest_mapping(columns)
        out["mapping_status"] = "pending"
    else:
        mapping = dict(existing)
        for col in columns:
            if col not in mapping:
                mapping[col] = suggest_canonical(col)
        # drop removed columns
        mapping = {k: v for k, v in mapping.items() if k in columns}
        out["field_mapping"] = mapping
        if out.get("mapping_status") not in ("pending", "confirmed"):
            out["mapping_status"] = "pending"
    return out
