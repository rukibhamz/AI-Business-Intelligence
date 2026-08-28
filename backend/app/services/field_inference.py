"""Give a column a business role when the vocabulary has never heard of it.

`CANONICAL_FIELDS` is a fixed list, and analytics keys off it: a column that
matches nothing in it becomes "Unmapped", which means the dashboard cannot chart
it, findings cannot flag it, and a diagnosis cannot attribute a change to it.
That is the right behaviour for a row id and the wrong behaviour for
`shipping_zone`, `supplier`, `warranty_months` or `refund_amount` — real
business columns the list simply does not happen to name.

So a column the keyword heuristic rejects is classified by what its **values**
look like instead of what it is called:

    supplier        120 distinct strings over 5,000 rows  ->  dimension
    refund_amount   continuous numbers, wide range        ->  measure
    nps_score       0-100, named like a rate              ->  rate
    order_ref       distinct on nearly every row          ->  unusable

A dimension can be grouped by, a measure can be totalled, a rate can be compared
but never summed. That is the whole of what analytics needs to know, and it is
recoverable from the data without asking anyone.

The canonical name is derived from the column name, so it reads as itself:
`shipping_zone` becomes "Shipping Zone" and appears in the mapping screen, the
charts and the SQL prompt under that name.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from app.services.analytics import to_date, to_number

#: What analytics may do with a field.
Role = Literal["dimension", "measure", "rate", "date"]

#: Rows scanned when classifying. The shape of a column is obvious long before
#: the end of a large file.
SAMPLE_ROWS = 5000

#: Above this share of distinct values, a text column is an identifier or free
#: text rather than a category — grouping by it produces one row per record.
_MAX_DISTINCT_RATIO = 0.5
#: And an absolute ceiling, so a large file cannot sneak a 10,000-value column
#: past the ratio test.
_MAX_DISTINCT_VALUES = 200
#: Below this many rows the ratio test is meaningless, so only the ceiling applies.
_MIN_ROWS_FOR_RATIO = 20

#: Names that mean the number is a ratio, so it must never be summed.
_RATE_HINTS = ("rate", "ratio", "pct", "percent", "margin", "share", "score", "index")
#: Names that mean the number identifies something rather than measuring it.
_ID_HINTS = ("id", "ref", "reference", "code", "number", "no", "sku", "uuid", "guid", "key")
#: Columns worth nobody's attention, whatever their values look like. Matched
#: as whole words, not substrings: a short fragment like "_c" also appears in
#: `freight_charge`, and rejecting the dataset's main money column is a far
#: worse error than keeping a notes field. (The same trap `sales_rep` fell into
#: when short keywords were matched by substring.)
_NOISE_TOKENS = frozenset(
    {
        "unnamed", "column", "columns", "index", "row", "rows",
        "note", "notes", "comment", "comments", "description", "remark", "remarks",
    }
)
#: Placeholder names a spreadsheet export produces: c1, col_3, field 2, x.
_GENERIC_COLUMN = re.compile(
    r"^_*(?:col|column|c|field|f|var|v|x)[\s_\-]*\d*$", re.IGNORECASE
)


def _tokens(name: str) -> set[str]:
    """The words in a column name, however it was punctuated.

    Splitting on separators alone leaves "Unnamed: 0" as {"unnamed:", "0"}, and
    a header exported from a spreadsheet is exactly where the odd punctuation
    turns up.
    """
    return set(re.findall(r"[a-z0-9]+", name.lower()))


def _is_noise(name: str) -> bool:
    return bool(_tokens(name) & _NOISE_TOKENS) or bool(_GENERIC_COLUMN.match(name.strip()))


#: A value that is a number and nothing else. `to_number` is deliberately
#: forgiving — it has to read "₦1,200" and "(500)" — so it also reads "R0" as 0,
#: which would let every order reference pass as a numeric column.
_NUMERIC = re.compile(r"^[-+(]?\s*[$£€₦¥]?\s*\d[\d,]*(?:\.\d+)?\s*[)%]?$")


def _strictly_numeric(value: Any) -> float | None:
    text = str(value).strip()
    if not text or not _NUMERIC.match(text):
        return None
    return to_number(text)


#: Short forms that read wrong title-cased — "Nps Score" instead of "NPS Score".
_ACRONYMS = frozenset(
    {
        "nps", "roi", "csat", "sku", "aov", "kpi", "id", "url", "vip", "sme",
        "ytd", "mtd", "vat", "eta", "sla", "gmv", "arpu", "cac", "ltv",
    }
)


def humanize_field(column: str) -> str:
    """`shipping_zone` -> `Shipping Zone`, so the field reads as itself."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(column or ""))
    words = [w for w in re.split(r"[^A-Za-z0-9]+", spaced) if w]
    out = [
        word.upper()
        if word.lower() in _ACRONYMS or (word.isupper() and len(word) <= 4)
        else word.capitalize()
        for word in words
    ]
    return " ".join(out) or str(column)


def _is_rate(name: str) -> bool:
    """True when the number is a ratio or a score, so it must never be summed.

    Both forms count: `return_rate` names it as a token, `roi_pct` glues it on
    as a suffix.
    """
    if _tokens(name) & set(_RATE_HINTS):
        return True
    return any(name.lower().endswith(hint) for hint in _RATE_HINTS)


def _looks_like_identifier(column: str, numbers: list[float]) -> bool:
    """Is this number naming something, or measuring it?

    Being whole and near-unique is not enough to tell them apart — a freight
    charge across 400 consignments is both, and rejecting a dataset's main money
    column is the worst outcome available here. What separates them is
    *density*: identifiers are issued consecutively, so their range is about as
    wide as their count, while a measured amount scatters across a far wider one.
    """
    if _tokens(column) & set(_ID_HINTS):
        return True
    if not numbers or len(set(numbers)) < len(numbers) * 0.9:
        return False
    if not all(float(n).is_integer() for n in numbers):
        return False
    distinct = len(set(numbers))
    span = max(numbers) - min(numbers) + 1
    return distinct >= 2 and span <= distinct * 2


def infer_role(column: str, values: list[Any]) -> Role | None:
    """What this column can be used for, or None when it cannot be used.

    Returning None matters as much as the positive cases: grouping a chart by an
    order reference draws one bar per order, which is worse than not charting.
    """
    name = str(column or "").lower()
    if _is_noise(name):
        return None

    present = [v for v in values[:SAMPLE_ROWS] if v is not None and str(v).strip() != ""]
    if len(present) < 3:
        return None

    dates = [d for d in (to_date(v) for v in present) if d is not None]
    if len(dates) >= len(present) * 0.8:
        return "date"

    numbers = [n for n in (_strictly_numeric(v) for v in present) if n is not None]
    if len(numbers) >= len(present) * 0.8:
        if _is_rate(name):
            return "rate"
        if _looks_like_identifier(column, numbers):
            # A numeric key can still label a group — "store 4" is a store — as
            # long as there are few enough of them to be worth grouping by.
            distinct = len(set(numbers))
            return "dimension" if distinct <= 50 else None
        return "measure"

    text = [str(v).strip() for v in present]
    distinct = len(set(text))
    if distinct < 2:
        return None  # one value for every row explains nothing
    if distinct > _MAX_DISTINCT_VALUES:
        return None
    if len(text) >= _MIN_ROWS_FOR_RATIO and distinct > len(text) * _MAX_DISTINCT_RATIO:
        return None
    return "dimension"


def infer_fields(
    columns: list[str],
    rows: list[dict[str, Any]],
    mapping: dict[str, str],
    *,
    taken: set[str] | None = None,
) -> tuple[dict[str, str], dict[str, Role]]:
    """Name and classify the columns the vocabulary left unmapped.

    Returns `({column: field name}, {field name: role})`. Existing mappings are
    never overwritten — the curated vocabulary always wins, because "Revenue"
    carries meaning that "Amount" does not.
    """
    inferred: dict[str, str] = {}
    roles: dict[str, Role] = {}
    used = set(taken or set()) | {
        canonical for canonical in mapping.values() if canonical not in ("Unmapped", "Ignore")
    }

    for column in columns:
        if mapping.get(column, "Unmapped") not in ("Unmapped", ""):
            continue
        role = infer_role(column, [row.get(column) for row in rows])
        if role is None:
            continue

        name = humanize_field(column)
        if name in used:
            # Two columns cannot claim one field, or a metric silently reads the
            # wrong one — the same rule the curated vocabulary enforces.
            continue
        used.add(name)
        inferred[column] = name
        roles[name] = role

    return inferred, roles


def infer_role_from_profile(column: str, profile: dict[str, Any] | None) -> Role | None:
    """The same classification, from a stored column profile instead of rows.

    Ingest already profiles every column, so the SQL prompt can be told what a
    column is for without re-reading the file. Kept beside `infer_role` so the
    naming rules — what counts as a rate, what counts as an identifier — have
    one definition rather than drifting apart.
    """
    if not profile:
        return None
    name = str(column or "").lower()
    if _is_noise(name):
        return None

    kind = profile.get("kind")
    if kind == "date":
        return "date"
    if kind == "category":
        return "dimension"
    if kind == "number":
        if _is_rate(name):
            return "rate"
        if _tokens(name) & set(_ID_HINTS):
            return "dimension"
        return "measure"
    return None


def describe_field_roles(
    columns: list[str],
    profiles: dict[str, Any],
    mapping: dict[str, str] | None = None,
) -> str:
    """The "what may I do with this column" block for the SQL prompt.

    A model given only names and types will happily `SUM(nps_score)`. Stating
    the role is cheaper than repairing the query that follows from not knowing
    it, and it is what lets a dataset outside the curated vocabulary be queried
    correctly rather than merely queried.
    """
    mapping = mapping or {}
    groupable: list[str] = []
    summable: list[str] = []
    rates: list[str] = []

    for column in columns:
        canonical = mapping.get(column)
        if canonical in ("Ignore",):
            continue
        role = infer_role_from_profile(column, profiles.get(column))
        if role == "dimension":
            groupable.append(column)
        elif role == "measure":
            summable.append(column)
        elif role == "rate":
            rates.append(column)

    lines: list[str] = []
    if groupable:
        lines.append(f"- GROUP BY these: {', '.join(groupable)}")
    if summable:
        lines.append(f"- SUM these: {', '.join(summable)}")
    if rates:
        lines.append(
            f"- NEVER SUM these, they are rates or scores: {', '.join(rates)}. "
            "Average them, or recompute from the totals they came from "
            "(SUM(part) / SUM(whole)), and never put one on the same axis as a count."
        )
    if not lines:
        return ""
    return "COLUMN ROLES (inferred from the values actually present):\n" + "\n".join(lines)
