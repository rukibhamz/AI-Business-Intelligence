"""Map a dataset's columns onto canonical business fields using the AI provider.

The keyword heuristic in `field_mapping.py` only reads column *names*, so it
misses anything not named in English business jargon (`amt_tot`, `col_3`,
`Umsatz`) and mislabels look-alikes (`order_id` is not a "Store ID").

This asks the configured model instead, and gives it evidence — inferred type,
the profiled range or category values, and a few real cell values — so the
decision rests on what the column actually contains. The model's answer is
never trusted blind: unknown columns and unknown field names are discarded and
the heuristic fills any gap.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.services.field_mapping import (
    CANONICAL_FIELDS,
    resolve_conflicts,
    suggest_canonical,
)

#: What each canonical field means, so the model maps on intent not vocabulary.
FIELD_GUIDE = {
    "Date": "the calendar date a record belongs to",
    "Timestamp": "a date *and* time",
    # money and volume
    "Revenue": "money coming in — sales, gross amount, turnover",
    "Cost": "cost of goods sold for the row — NOT marketing or advertising spend",
    "Profit": "revenue minus cost, or a stated margin amount",
    "Price": "the per-unit price, not a line total",
    "Quantity": "how many units were sold — a count, not money",
    "Discount": "money taken off the price — markdown, promotion amount",
    "Target": "the revenue or sales goal to hit — quota, budget, forecast",
    "Marketing Spend": "advertising or campaign budget — keep separate from Cost",
    # quality and service
    "Returns": "units returned or refunded — a count of returns, not a flag name",
    "Rating": "customer satisfaction score — rating, CSAT, NPS, stars",
    "Delivery Days": "how long delivery took, in days",
    # stock
    "Stock": "units currently on hand — inventory level",
    "Reorder Level": "the stock threshold that triggers reordering",
    # dimensions
    "Store ID": "which shop, branch, or physical location",
    "Region": "a geographic grouping above a store — area, zone, territory",
    "Country": "a country name or ISO country code",
    "Channel": "how the sale happened — store, online, phone, corporate",
    "Product": "the item or SKU sold",
    "Category": "a grouping of products — electronics, appliances",
    "Customer": "who bought — client, buyer, account",
    "Customer Segment": "the tier a customer belongs to — retail, corporate, VIP",
    "Employee": "the staff member or sales rep responsible",
    "Campaign": "the marketing campaign or promotion a row belongs to",
    "Delivery Partner": "the courier or logistics company that delivered",
    "Name": "a person's or entity's display name with no more specific role",
    "Status": "a state such as paid, shipped, cancelled",
    "Ignore": "technical columns with no business meaning — row ids, surrogate "
    "keys, internal flags, audit timestamps",
    "Unmapped": "use when genuinely unsure; never guess",
}

SYSTEM_PROMPT = """You map spreadsheet and database columns onto a fixed set of
business fields for a BI tool.

You are given each column's name, inferred type, value range or category list,
and a few real values. Decide what each column means from that evidence — the
name alone can mislead.

Rules:
- Reply with ONLY a JSON object: {"column name": "Field", ...}
- Use every column exactly once. Use only the field names provided.
- A money amount per row is Revenue; a per-unit figure is Price.
- A count of things is Quantity, never Revenue.
- Each field may be used AT MOST ONCE. If two columns look similar, give the
  field to the better fit and map the other to its own field or "Unmapped" —
  e.g. cost of goods is "Cost" while an advertising budget is "Marketing Spend".
- Primary keys, surrogate ids, and audit columns are "Ignore".
- If two columns could be the same field, pick the better fit and map the other
  to its next-best field, or "Unmapped".
- When the evidence does not clearly support a field, answer "Unmapped".
- No prose, no markdown fences, no explanation.
"""


def build_mapping_prompt(
    columns: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    *,
    source_name: str,
    max_samples: int = 3,
) -> str:
    lines = [f'Dataset: "{source_name}"', "", "Available fields:"]
    for field in CANONICAL_FIELDS:
        lines.append(f"- {field}: {FIELD_GUIDE.get(field, '')}".rstrip())

    lines.append("")
    lines.append("Columns:")
    for column in columns:
        name = column["name"]
        profile = column.get("profile") or {}
        bits = [f'type={column.get("type", "unknown")}']
        kind = profile.get("kind")
        if kind == "date":
            bits.append(f'dates {profile.get("min")}..{profile.get("max")}')
        elif kind == "number":
            bits.append(f'range {profile.get("min")}..{profile.get("max")}')
        elif kind == "category":
            bits.append(f'values: {", ".join(profile.get("values", [])[:8])}')
        if profile.get("null_ratio"):
            bits.append(f'{profile["null_ratio"]:.0%} empty')

        samples = []
        for row in rows[:max_samples]:
            value = row.get(name)
            if value is not None and str(value).strip():
                samples.append(str(value)[:40])
        if samples:
            bits.append(f'e.g. {" | ".join(samples)}')

        lines.append(f'- "{name}" ({"; ".join(bits)})')

    return "\n".join(lines)


def _extract_json(content: str) -> dict[str, Any] | None:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # Some models wrap the object in a sentence; take the outermost braces.
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def validate_mapping(
    raw: dict[str, Any],
    columns: list[str],
) -> tuple[dict[str, str], list[str]]:
    """Keep only real columns mapped to real fields. Returns (mapping, rejected)."""
    by_lower = {c.lower(): c for c in columns}
    fields_by_lower = {f.lower(): f for f in CANONICAL_FIELDS}

    mapping: dict[str, str] = {}
    rejected: list[str] = []

    for key, value in raw.items():
        column = by_lower.get(str(key).strip().lower())
        if column is None:
            rejected.append(f"unknown column {key!r}")
            continue
        field = fields_by_lower.get(str(value).strip().lower())
        if field is None:
            rejected.append(f"unknown field {value!r} for {key!r}")
            continue
        mapping[column] = field

    return mapping, rejected


async def ai_suggest_mapping(
    columns: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    *,
    source_name: str,
    api_key: str | None,
    model: str,
    base_url: str,
    timeout: float = 45.0,
) -> dict[str, Any] | None:
    """Return {"mapping": {...}, "rejected": [...]} or None when unavailable."""
    if not api_key or not columns:
        return None

    prompt = build_mapping_prompt(columns, rows, source_name=source_name)
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        content = data["choices"][0]["message"]["content"]
    except Exception:
        # Mapping must never block ingestion; the heuristic still applies.
        return None

    parsed = _extract_json(content)
    if not parsed:
        return None

    names = [c["name"] for c in columns]
    mapping, rejected = validate_mapping(parsed, names)
    if not mapping:
        return None

    # Anything the model skipped falls back to the keyword heuristic.
    for name in names:
        if name not in mapping:
            mapping[name] = suggest_canonical(name)
            rejected.append(f"no answer for {name!r}")

    # The model can still hand two columns the same field; that silently
    # corrupts metrics, so resolve it before the mapping is stored.
    mapping, conflicts = resolve_conflicts(mapping)

    return {"mapping": mapping, "rejected": rejected, "conflicts": conflicts}


def mapping_is_useful(mapping: dict[str, str]) -> bool:
    """True when the mapping gives analytics something to work with.

    A dataset needs at least one measure to produce any KPI, so a mapping
    without one is not worth auto-confirming.
    """
    measures = {"Revenue", "Cost", "Profit", "Quantity", "Price"}
    return any(field in measures for field in mapping.values())
