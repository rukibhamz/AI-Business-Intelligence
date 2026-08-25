from __future__ import annotations

import re
from typing import Any

# Canonical business fields. Analytics keys off these, so a concept missing
# here is invisible to KPIs and findings no matter what the data contains.
CANONICAL_FIELDS = [
    "Unmapped",
    "Ignore",
    # time
    "Date",
    "Timestamp",
    # money and volume
    "Revenue",
    "Cost",
    "Profit",
    "Price",
    "Quantity",
    "Discount",
    "Target",
    "Marketing Spend",
    # quality / service
    "Returns",
    "Rating",
    "Delivery Days",
    # stock
    "Stock",
    "Reorder Level",
    # dimensions
    "Store ID",
    "Region",
    "Country",
    "Channel",
    "Product",
    "Category",
    "Customer",
    "Customer Segment",
    "Employee",
    "Campaign",
    "Delivery Partner",
    "Name",
    "Status",
]

#: Fields that describe one thing per row. Two columns claiming the same one
#: means a metric would silently read the wrong column, so extras are demoted.
EXCLUSIVE_FIELDS = frozenset(CANONICAL_FIELDS) - {"Unmapped", "Ignore"}

#: Fields whose value repeats across the rows of a group (a campaign's budget
#: is stated on every one of its rows), so summing every row double-counts.
REPEATED_PER_GROUP_FIELDS = frozenset({"Marketing Spend", "Target", "Reorder Level"})

# keyword → canonical. Order matters: the first match wins, so specific
# patterns must precede the generic ones they would otherwise be swallowed by.
_HINTS: list[tuple[tuple[str, ...], str]] = [
    # Service and quality first — "delivery_date" is about delivery, not Date.
    (("delivery_partner", "courier", "carrier", "logistics", "shipper", "3pl"), "Delivery Partner"),
    (("delivery_days", "delivery_time", "days_to_deliver", "lead_time", "ship_days"), "Delivery Days"),
    (("rating", "csat", "satisfaction", "nps", "review_score", "stars"), "Rating"),
    (("return", "returns", "returned", "refund", "rma"), "Returns"),
    # Named concepts that contain generic money words, before the money hints:
    # "sales_rep" is a person, "sales_quota" is a target.
    (("employee", "staff", "agent", "rep", "salesperson", "seller", "cashier"), "Employee"),
    (("campaign", "promotion", "promo"), "Campaign"),
    (("segment", "tier", "customer_type", "cohort"), "Customer Segment"),
    (("channel", "medium"), "Channel"),
    (("marketing_spend", "ad_spend", "campaign_spend", "media_spend", "adspend"), "Marketing Spend"),
    (("target", "quota", "goal", "budget", "forecast"), "Target"),
    (("discount", "markdown"), "Discount"),
    # Money and volume.
    (("revenue", "rev", "sales", "gross", "amount", "turnover", "total"), "Revenue"),
    (("cogs", "cost", "expense", "spend"), "Cost"),
    (("profit", "margin"), "Profit"),
    (("unit_price", "price", "rate"), "Price"),
    (("qty", "quantity", "units", "unit", "volume"), "Quantity"),
    # Stock.
    (("reorder", "safety_stock", "min_stock"), "Reorder Level"),
    (("stock", "inventory", "on_hand", "soh"), "Stock"),
    # Remaining dimensions.
    (("store", "loc_id", "location", "branch", "outlet", "shop"), "Store ID"),
    (("region", "area", "zone", "territory"), "Region"),
    (("country", "nation"), "Country"),
    (("product", "sku", "item", "model"), "Product"),
    (("customer", "client", "buyer", "account"), "Customer"),
    (("category", "type", "class"), "Category"),
    (("status", "state"), "Status"),
    # Time last: a more specific concept above should win the column.
    (("timestamp", "datetime"), "Timestamp"),
    (("date", "dt", "day", "month", "period"), "Date"),
    (("name", "title"), "Name"),
]


#: Substrings shorter than this must match a whole word. Without it "rep"
#: inside "report_date" would claim the Employee field.
_MIN_SUBSTRING_LEN = 5


def _matches_hint(key: str, words: set[str], token: str) -> bool:
    if token in words:
        return True
    return len(token) >= _MIN_SUBSTRING_LEN and token in key


def suggest_canonical(column_name: str) -> str:
    key = column_name.lower().strip()
    key = re.sub(r"[^a-z0-9]+", "_", key)
    words = {w for w in key.split("_") if w}
    for tokens, canonical in _HINTS:
        if any(_matches_hint(key, words, tok) for tok in tokens):
            return canonical
    return "Unmapped"


def suggest_mapping(columns: list[str]) -> dict[str, str]:
    return resolve_conflicts({col: suggest_canonical(col) for col in columns})[0]


def _affinity(column: str, field: str) -> int:
    """How strongly a column name argues for a field. Higher wins a conflict."""
    name = re.sub(r"[^a-z0-9]+", "", column.lower())
    target = re.sub(r"[^a-z0-9]+", "", field.lower())
    if name == target:
        return 100
    if target in name:
        return 60
    # A column whose own keywords independently point at this field.
    if suggest_canonical(column) == field:
        return 40
    return 0


def resolve_conflicts(
    mapping: dict[str, str],
) -> tuple[dict[str, str], list[str]]:
    """Ensure at most one column per exclusive field.

    Two columns on the same field is not a harmless duplicate: metrics read the
    first match, so mapping both `cost` and `marketing_spend` to "Cost" makes
    marketing spend masquerade as cost of goods and doubles the reported margin.
    The stronger candidate keeps the field; the rest become "Unmapped".
    """
    claimants: dict[str, list[str]] = {}
    for column, field in mapping.items():
        if field in EXCLUSIVE_FIELDS:
            claimants.setdefault(field, []).append(column)

    resolved = dict(mapping)
    conflicts: list[str] = []

    for field, columns in claimants.items():
        if len(columns) < 2:
            continue
        # Best name affinity wins; ties fall back to the original order.
        ranked = sorted(
            columns,
            key=lambda c: (-_affinity(c, field), columns.index(c)),
        )
        winner, losers = ranked[0], ranked[1:]
        for loser in losers:
            resolved[loser] = "Unmapped"
        conflicts.append(
            f'"{field}" claimed by {len(columns)} columns '
            f'({", ".join(columns)}); kept "{winner}", unmapped the rest'
        )

    return resolved, conflicts


def columns_from_schema(schema_json: str | None, table: str | None = None) -> list[str]:
    """Column names for a table — the first one unless another is named."""
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
    chosen = next((t for t in tables if t.get("name") == table), tables[0])
    return [c["name"] for c in chosen.get("columns", [])]


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
        mapping, conflicts = resolve_conflicts(suggest_mapping(columns))
        out["field_mapping"] = mapping
        out["mapping_status"] = "pending"
    else:
        mapping = dict(existing)
        for col in columns:
            if col not in mapping:
                mapping[col] = suggest_canonical(col)
        # drop removed columns
        mapping = {k: v for k, v in mapping.items() if k in columns}
        mapping, conflicts = resolve_conflicts(mapping)
        out["field_mapping"] = mapping
        if out.get("mapping_status") not in ("pending", "confirmed"):
            out["mapping_status"] = "pending"

    if conflicts:
        out["mapping_conflicts"] = conflicts
    else:
        out.pop("mapping_conflicts", None)
    return out
