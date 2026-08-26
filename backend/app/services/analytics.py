"""Live analytics derived from connected data sources.

Everything here is computed from real rows pulled through the source
connectors - there is no sample or placeholder data. When a dataset lacks
the fields a metric needs, the metric is omitted and the reason is reported
back to the UI so it can render an honest empty state.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.models import DataSource
from app.services.schema_registry import parse_connection_config, preview_source_data

MAX_ROWS = 20000

# The comparisons the case study asks for by name. These are charted before any
# other dimension so a broader one cannot crowd them out.
CASE_STUDY_DIMENSIONS = frozenset(
    {"Product", "Store ID", "Region", "Employee", "Campaign", "Customer Segment"}
)

# Canonical fields usable as a breakdown dimension, best first.
DIMENSION_FIELDS = (
    "Store ID",
    "Region",
    "Category",
    "Product",
    "Campaign",
    "Employee",
    "Delivery Partner",
    "Customer Segment",
    "Channel",
    "Country",
    "Customer",
    "Status",
)

_DATE_PATTERNS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%m-%d-%Y",
    "%Y-%m",
    "%b %d, %Y",
    "%d %b %Y",
    "%B %d, %Y",
)


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------


#: How a spreadsheet writes "yes". pandas writes True/False; exports from
#: retail systems use Y/N, yes/no, or 1/0.
_TRUTHY = {"true", "t", "yes", "y", "1", "returned", "return"}
_FALSY = {"false", "f", "no", "n", "0", "", "none", "null", "nan"}


def to_flag(value: Any) -> float | None:
    """1.0 or 0.0 for a boolean column, whatever spelling it uses.

    A return flag written as the text "True" sums to zero in SQL and in Python,
    which reads as "nothing was ever returned" rather than as a type mismatch.
    """
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if value is None:
        return 0.0
    text = str(value).strip().lower()
    if text in _TRUTHY:
        return 1.0
    if text in _FALSY:
        return 0.0
    return None


def looks_like_flag(values: Iterable[Any], *, sample: int = 200) -> bool:
    """True when a column only ever holds a yes/no value."""
    seen = 0
    for value in values:
        if value is None or str(value).strip() == "":
            continue
        if to_flag(value) is None:
            return False
        seen += 1
        if seen >= sample:
            break
    return seen > 0


def to_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return None if math.isnan(number) or math.isinf(number) else number
    text = str(value).strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    cleaned = re.sub(r"[^\d.\-]", "", text.replace(",", ""))
    if cleaned in ("", "-", ".", "-."):
        return None
    try:
        number = float(cleaned)
    except ValueError:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return -number if negative else number


def to_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    head = text.replace("T", " ").split(" ")[0]
    for pattern in _DATE_PATTERNS:
        try:
            return datetime.strptime(head, pattern).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def _safe_div(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _pct_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return (current - previous) / abs(previous) * 100.0


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------


@dataclass
class Dataset:
    source: DataSource
    columns: list[str]
    rows: list[dict[str, Any]]
    total: int
    truncated: bool
    mapping: dict[str, str] = field(default_factory=dict)

    @property
    def canonical(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for column, canon in self.mapping.items():
            if canon in ("Unmapped", "Ignore") or column not in self.columns:
                continue
            out.setdefault(canon, []).append(column)
        return out

    def column_for(self, *canonicals: str) -> str | None:
        index = self.canonical
        for canon in canonicals:
            cols = index.get(canon)
            if cols:
                return cols[0]
        return None

    def numbers(self, column: str) -> list[float]:
        return [n for n in (to_number(row.get(column)) for row in self.rows) if n is not None]

    def sum_of(self, column: str) -> float:
        return sum(self.numbers(column))


async def load_dataset(source: DataSource, *, limit: int = MAX_ROWS) -> Dataset:
    config = parse_connection_config(source)
    mapping = config.get("field_mapping")
    if not isinstance(mapping, dict):
        mapping = {}

    # Read the table the operator selected, not simply the first one.
    preview = await preview_source_data(
        source, table=config.get("primary_table"), limit=limit, offset=0
    )
    rows = list(preview.get("rows") or [])
    columns = list(preview.get("columns") or [])
    total = int(preview.get("total") or len(rows))

    return Dataset(
        source=source,
        columns=columns,
        rows=rows,
        total=total,
        truncated=total > len(rows),
        mapping={str(k): str(v) for k, v in mapping.items()},
    )


# ---------------------------------------------------------------------------
# Time bucketing
# ---------------------------------------------------------------------------


@dataclass
class Bucket:
    key: str
    label: str
    start: date


def _granularity(span_days: int) -> str:
    if span_days <= 62:
        return "day"
    if span_days <= 1500:
        return "month"
    return "year"


def _bucket_for(value: date, granularity: str) -> Bucket:
    if granularity == "day":
        return Bucket(value.isoformat(), value.strftime("%d %b"), value)
    if granularity == "month":
        start = date(value.year, value.month, 1)
        return Bucket(start.strftime("%Y-%m"), start.strftime("%b %Y"), start)
    start = date(value.year, 1, 1)
    return Bucket(str(value.year), str(value.year), start)


@dataclass
class TimeIndex:
    granularity: str
    buckets: list[Bucket]
    row_bucket: list[str | None]
    min_date: date
    max_date: date

    @property
    def unit_label(self) -> str:
        return self.granularity


def build_time_index(dataset: Dataset, date_column: str) -> TimeIndex | None:
    parsed: list[date | None] = [to_date(row.get(date_column)) for row in dataset.rows]
    valid = [d for d in parsed if d is not None]
    if len(valid) < 2:
        return None

    lo, hi = min(valid), max(valid)
    granularity = _granularity((hi - lo).days)

    seen: dict[str, Bucket] = {}
    row_bucket: list[str | None] = []
    for value in parsed:
        if value is None:
            row_bucket.append(None)
            continue
        bucket = _bucket_for(value, granularity)
        seen.setdefault(bucket.key, bucket)
        row_bucket.append(bucket.key)

    buckets = sorted(seen.values(), key=lambda b: b.start)
    return TimeIndex(granularity, buckets, row_bucket, lo, hi)


def bucket_totals(dataset: Dataset, index: TimeIndex, column: str) -> dict[str, float]:
    totals = {b.key: 0.0 for b in index.buckets}
    for row, key in zip(dataset.rows, index.row_bucket, strict=False):
        if key is None:
            continue
        value = to_number(row.get(column))
        if value is not None:
            totals[key] += value
    return totals


# ---------------------------------------------------------------------------
# Dimension aggregation
# ---------------------------------------------------------------------------


def aggregate_by(
    dataset: Dataset,
    dimension: str,
    measure: str,
    *,
    limit: int = 12,
) -> list[dict[str, Any]]:
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for row in dataset.rows:
        raw = row.get(dimension)
        label = str(raw).strip() if raw is not None else ""
        if not label:
            continue
        value = to_number(row.get(measure))
        if value is None:
            continue
        totals[label] = totals.get(label, 0.0) + value
        counts[label] = counts.get(label, 0) + 1

    ordered = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    return [
        {"label": label, "value": round(value, 2), "count": counts[label]}
        for label, value in ordered[:limit]
    ]


def row_profit(
    row: dict[str, Any],
    revenue_col: str,
    profit_col: str | None,
    cost_col: str | None,
) -> float | None:
    """Profit for one row: the mapped column, or revenue minus cost."""
    if profit_col:
        return to_number(row.get(profit_col))
    if not cost_col:
        return None
    revenue = to_number(row.get(revenue_col))
    cost = to_number(row.get(cost_col))
    if revenue is None or cost is None:
        return None
    return revenue - cost


def profit_by(
    dataset: Dataset,
    dimension: str,
    *,
    limit: int = 12,
    min_revenue: float = 0.0,
) -> list[dict[str, Any]]:
    """Revenue, profit and margin per dimension value, biggest revenue first.

    The case study asks which products, stores and employees do well on revenue
    *and* profit. Ranking on revenue alone hides the segment that sells hardest
    and earns least, which is the whole point of the scenario.
    """
    revenue_col = dataset.column_for("Revenue")
    profit_col = dataset.column_for("Profit")
    cost_col = dataset.column_for("Cost")
    if not revenue_col or not (profit_col or cost_col):
        return []

    totals: dict[str, dict[str, float]] = {}
    for row in dataset.rows:
        raw = row.get(dimension)
        label = str(raw).strip() if raw is not None else ""
        if not label:
            continue
        revenue = to_number(row.get(revenue_col))
        profit = row_profit(row, revenue_col, profit_col, cost_col)
        if revenue is None or profit is None:
            continue
        bucket = totals.setdefault(label, {"revenue": 0.0, "profit": 0.0, "count": 0.0})
        bucket["revenue"] += revenue
        bucket["profit"] += profit
        bucket["count"] += 1

    out: list[dict[str, Any]] = []
    for label, bucket in totals.items():
        if bucket["revenue"] < min_revenue:
            continue
        margin = _safe_div(bucket["profit"], bucket["revenue"])
        out.append(
            {
                "label": label,
                "revenue": round(bucket["revenue"], 2),
                "profit": round(bucket["profit"], 2),
                "margin": round(margin * 100, 1) if margin is not None else None,
                "count": int(bucket["count"]),
            }
        )
    out.sort(key=lambda item: item["revenue"], reverse=True)
    return out[:limit]


def roi_by(
    dataset: Dataset,
    dimension: str,
    spend_col: str,
    revenue_col: str,
    *,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Return on spend per dimension value, best first.

    Spend is read at its own grain — a campaign budget written on every row of
    the campaign is one budget, not one per row.
    """
    spend_by = {
        item["label"]: item["value"]
        for item in aggregate_by_grain(dataset, dimension, spend_col, limit=limit * 4)
    }
    revenue_by = {
        item["label"]: item["value"]
        for item in aggregate_by(dataset, dimension, revenue_col, limit=limit * 4)
    }
    out = [
        {
            "label": label,
            "value": round((revenue_by[label] - spend) / spend, 2),
            "spend": round(spend, 2),
            "revenue": round(revenue_by[label], 2),
            "count": 0,
        }
        for label, spend in spend_by.items()
        if spend > 0 and label in revenue_by
    ]
    out.sort(key=lambda item: item["value"], reverse=True)
    return out[:limit]


def target_basis(
    dataset: Dataset,
    index: TimeIndex | None,
    dimension: str,
    target_col: str,
    revenue_col: str,
) -> dict[str, Any] | None:
    """Actual against target on a like-for-like basis.

    A target repeated on every row is one target per location, and a location's
    target describes a period — so the honest comparison is the latest period's
    revenue, not every period's revenue stacked against a single target. Without
    dates there is nothing to slice by, and the whole dataset is used.
    """
    targets = {
        item["label"]: item["value"]
        for item in aggregate_by_grain(dataset, dimension, target_col, limit=100)
    }
    targets = {label: value for label, value in targets.items() if value > 0}
    if not targets:
        return None

    if index is None or not index.buckets:
        actuals = {
            item["label"]: item["value"]
            for item in aggregate_by(dataset, dimension, revenue_col, limit=100)
        }
        return {"targets": targets, "actuals": actuals, "period": None}

    latest = index.buckets[-1].key
    actuals: dict[str, float] = {}
    for row, key in zip(dataset.rows, index.row_bucket, strict=False):
        if key != latest:
            continue
        label = str(row.get(dimension, "")).strip()
        value = to_number(row.get(revenue_col))
        if not label or value is None:
            continue
        actuals[label] = actuals.get(label, 0.0) + value

    # A location with no rows in this period has no comparable actual — counting
    # it as zero would report every quiet store as catastrophically behind.
    comparable = {label: value for label, value in targets.items() if label in actuals}
    if not comparable:
        return {
            "targets": targets,
            "actuals": {
                item["label"]: item["value"]
                for item in aggregate_by(dataset, dimension, revenue_col, limit=100)
            },
            "period": None,
        }

    return {"targets": comparable, "actuals": actuals, "period": index.buckets[-1].label}


def count_by(dataset: Dataset, dimension: str, *, limit: int = 12) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in dataset.rows:
        raw = row.get(dimension)
        label = str(raw).strip() if raw is not None else ""
        if not label:
            continue
        counts[label] = counts.get(label, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    return [{"label": label, "value": count, "count": count} for label, count in ordered[:limit]]


def is_repeated_per_group(
    dataset: Dataset,
    measure: str,
    dimension: str,
) -> bool:
    """True when a measure states one value per group rather than per row.

    A campaign budget is written onto every row of that campaign, so summing
    all rows multiplies it by the row count. Detect that shape instead of
    trusting SUM blindly.
    """
    seen: dict[str, set[float]] = {}
    for row in dataset.rows:
        key = str(row.get(dimension, "")).strip()
        value = to_number(row.get(measure))
        if not key or value is None:
            continue
        seen.setdefault(key, set()).add(round(value, 6))

    if len(seen) < 2:
        return False
    # Repeated means constant within every group, and at least one group had
    # several rows to be constant across.
    multi_row_groups = sum(
        1 for key in seen if sum(1 for r in dataset.rows if str(r.get(dimension, "")).strip() == key) > 1
    )
    return multi_row_groups > 0 and all(len(values) == 1 for values in seen.values())


def total_by_grain(dataset: Dataset, measure: str, dimension: str | None) -> float:
    """Sum a measure, counting a per-group value once rather than per row."""
    if dimension and is_repeated_per_group(dataset, measure, dimension):
        per_group: dict[str, float] = {}
        for row in dataset.rows:
            key = str(row.get(dimension, "")).strip()
            value = to_number(row.get(measure))
            if key and value is not None:
                per_group[key] = value
        return sum(per_group.values())
    return dataset.sum_of(measure)


def aggregate_by_grain(
    dataset: Dataset,
    dimension: str,
    measure: str,
    *,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Aggregate a measure per dimension value, honouring per-group values."""
    if not is_repeated_per_group(dataset, measure, dimension):
        return aggregate_by(dataset, dimension, measure, limit=limit)

    per_group: dict[str, float] = {}
    counts: dict[str, int] = {}
    for row in dataset.rows:
        key = str(row.get(dimension, "")).strip()
        value = to_number(row.get(measure))
        if not key or value is None:
            continue
        per_group[key] = value
        counts[key] = counts.get(key, 0) + 1

    ordered = sorted(per_group.items(), key=lambda kv: kv[1], reverse=True)
    return [
        {"label": label, "value": round(value, 2), "count": counts[label]}
        for label, value in ordered[:limit]
    ]


def returns_basis(dataset: Dataset, returns_col: str) -> tuple[bool, str | None]:
    """How this dataset records returns, and what to divide by.

    Two encodings are common and they need different denominators:

    * a **count of returned units** — divide by units sold;
    * a **per-row flag** (`return_flag` holding true/false) — divide by the
      number of rows, because the row is the order, not the unit.

    Getting this wrong is not a rounding error: summing the text "True" gives
    zero, and the product returned a third of the time reads as flawless.
    """
    flag = looks_like_flag(row.get(returns_col) for row in dataset.rows)
    if flag:
        return True, None
    return False, dataset.column_for("Quantity")


def returns_value(row: dict[str, Any], column: str, *, is_flag: bool) -> float | None:
    return to_flag(row.get(column)) if is_flag else to_number(row.get(column))


def return_rate_by(
    dataset: Dataset,
    dimension: str,
    returns_col: str,
    *,
    min_denominator: float = 5.0,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Return rate per dimension value, worst first, in percent."""
    is_flag, quantity_col = returns_basis(dataset, returns_col)
    if not is_flag and not quantity_col:
        return []

    nums: dict[str, float] = {}
    dens: dict[str, float] = {}
    for row in dataset.rows:
        key = str(row.get(dimension, "")).strip()
        if not key:
            continue
        value = returns_value(row, returns_col, is_flag=is_flag)
        if value is None:
            continue
        nums[key] = nums.get(key, 0.0) + value
        # A flag counts orders; a count of units divides by units sold.
        if is_flag:
            dens[key] = dens.get(key, 0.0) + 1
        else:
            units = to_number(row.get(quantity_col))
            if units is not None:
                dens[key] = dens.get(key, 0.0) + units

    out = []
    for key, den in dens.items():
        if den < min_denominator:
            continue
        out.append(
            {
                "label": key,
                "value": round(nums.get(key, 0.0) / den * 100, 2),
                "count": int(den),
            }
        )
    out.sort(key=lambda item: item["value"], reverse=True)
    return out[:limit]


def overall_return_rate(dataset: Dataset, returns_col: str) -> float | None:
    """Return rate across the whole dataset, as a fraction."""
    is_flag, quantity_col = returns_basis(dataset, returns_col)
    if not is_flag and not quantity_col:
        return None
    returned = 0.0
    total = 0.0
    for row in dataset.rows:
        value = returns_value(row, returns_col, is_flag=is_flag)
        if value is None:
            continue
        returned += value
        if is_flag:
            total += 1
        else:
            units = to_number(row.get(quantity_col))
            if units is not None:
                total += units
    return _safe_div(returned, total)


def ratio_by(
    dataset: Dataset,
    dimension: str,
    numerator: str,
    denominator: str,
    *,
    min_denominator: float = 1.0,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Per-dimension ratio such as return rate — numerator over denominator."""
    nums: dict[str, float] = {}
    dens: dict[str, float] = {}
    for row in dataset.rows:
        key = str(row.get(dimension, "")).strip()
        if not key:
            continue
        n = to_number(row.get(numerator))
        d = to_number(row.get(denominator))
        if n is not None:
            nums[key] = nums.get(key, 0.0) + n
        if d is not None:
            dens[key] = dens.get(key, 0.0) + d

    out = []
    for key, den in dens.items():
        if den < min_denominator:
            continue
        out.append(
            {
                "label": key,
                "value": round(nums.get(key, 0.0) / den * 100, 2),
                "count": int(den),
            }
        )
    out.sort(key=lambda item: item["value"], reverse=True)
    return out[:limit]


def average_by(
    dataset: Dataset,
    dimension: str,
    measure: str,
    *,
    limit: int = 12,
    ascending: bool = False,
) -> list[dict[str, Any]]:
    """Mean of a measure per dimension value — ratings, delivery days."""
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for row in dataset.rows:
        key = str(row.get(dimension, "")).strip()
        value = to_number(row.get(measure))
        if not key or value is None:
            continue
        totals[key] = totals.get(key, 0.0) + value
        counts[key] = counts.get(key, 0) + 1

    out = [
        {"label": key, "value": round(total / counts[key], 2), "count": counts[key]}
        for key, total in totals.items()
    ]
    out.sort(key=lambda item: item["value"], reverse=not ascending)
    return out[:limit]


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


def _kpi(
    kpi_id: str,
    label: str,
    value: Any,
    fmt: str,
    *,
    delta_pct: float | None = None,
    higher_is_better: bool = True,
    caption: str | None = None,
) -> dict[str, Any]:
    direction: str | None = None
    if delta_pct is not None and abs(delta_pct) >= 0.05:
        direction = "up" if delta_pct > 0 else "down"
    tone: str | None = None
    if direction:
        good = (direction == "up") == higher_is_better
        tone = "positive" if good else "negative"
    return {
        "id": kpi_id,
        "label": label,
        "value": value,
        "format": fmt,
        "delta_pct": round(delta_pct, 1) if delta_pct is not None else None,
        "direction": direction,
        "tone": tone,
        "caption": caption,
    }


def build_overview(dataset: Dataset) -> dict[str, Any]:
    kpis: list[dict[str, Any]] = []
    charts: list[dict[str, Any]] = []
    notices: list[str] = []

    revenue_col = dataset.column_for("Revenue")
    cost_col = dataset.column_for("Cost")
    profit_col = dataset.column_for("Profit")
    quantity_col = dataset.column_for("Quantity")
    date_col = dataset.column_for("Date", "Timestamp")

    index = build_time_index(dataset, date_col) if date_col else None
    period_caption = None
    if index and len(index.buckets) >= 2:
        period_caption = f"{index.buckets[-1].label} vs {index.buckets[-2].label}"

    def delta_for(column: str | None) -> float | None:
        if not column or not index or len(index.buckets) < 2:
            return None
        totals = bucket_totals(dataset, index, column)
        return _pct_change(totals[index.buckets[-1].key], totals[index.buckets[-2].key])

    total_revenue = dataset.sum_of(revenue_col) if revenue_col else None
    total_cost = dataset.sum_of(cost_col) if cost_col else None

    total_profit: float | None = None
    if profit_col:
        total_profit = dataset.sum_of(profit_col)
    elif total_revenue is not None and total_cost is not None:
        total_profit = total_revenue - total_cost

    if total_revenue is not None:
        kpis.append(
            _kpi(
                "revenue",
                "Total Revenue",
                round(total_revenue, 2),
                "currency",
                delta_pct=delta_for(revenue_col),
                caption=period_caption,
            )
        )

    if total_cost is not None:
        kpis.append(
            _kpi(
                "cost",
                "Total Cost",
                round(total_cost, 2),
                "currency",
                delta_pct=delta_for(cost_col),
                higher_is_better=False,
                caption=period_caption,
            )
        )

    if total_profit is not None:
        profit_delta = delta_for(profit_col) if profit_col else None
        if profit_delta is None and index and len(index.buckets) >= 2 and revenue_col and cost_col:
            rev = bucket_totals(dataset, index, revenue_col)
            cst = bucket_totals(dataset, index, cost_col)
            last, prev = index.buckets[-1].key, index.buckets[-2].key
            profit_delta = _pct_change(rev[last] - cst[last], rev[prev] - cst[prev])
        kpis.append(
            _kpi(
                "profit",
                "Total Profit",
                round(total_profit, 2),
                "currency",
                delta_pct=profit_delta,
                caption=period_caption,
            )
        )

    if total_revenue and total_profit is not None:
        margin = _safe_div(total_profit, total_revenue)
        if margin is not None:
            margin_delta = None
            if index and len(index.buckets) >= 2 and revenue_col:
                rev = bucket_totals(dataset, index, revenue_col)
                last, prev = index.buckets[-1].key, index.buckets[-2].key
                last_profit: float | None = None
                prev_profit: float | None = None
                if profit_col:
                    prof = bucket_totals(dataset, index, profit_col)
                    last_profit, prev_profit = prof[last], prof[prev]
                elif cost_col:
                    cst = bucket_totals(dataset, index, cost_col)
                    last_profit = rev[last] - cst[last]
                    prev_profit = rev[prev] - cst[prev]
                if last_profit is not None and prev_profit is not None:
                    last_margin = _safe_div(last_profit, rev[last])
                    prev_margin = _safe_div(prev_profit, rev[prev])
                    if last_margin is not None and prev_margin is not None:
                        margin_delta = (last_margin - prev_margin) * 100.0
            kpis.append(
                _kpi(
                    "margin",
                    "Profit Margin",
                    round(margin * 100, 2),
                    "percent",
                    delta_pct=margin_delta,
                    caption="percentage points" if margin_delta is not None else period_caption,
                )
            )

    if quantity_col:
        kpis.append(
            _kpi(
                "quantity",
                "Units",
                round(dataset.sum_of(quantity_col), 2),
                "number",
                delta_pct=delta_for(quantity_col),
                caption=period_caption,
            )
        )

    # --- operational KPIs the case study asks about ------------------------
    returns_col = dataset.column_for("Returns")
    spend_col = dataset.column_for("Marketing Spend")
    rating_col = dataset.column_for("Rating")
    delivery_col = dataset.column_for("Delivery Days")
    target_col = dataset.column_for("Target")
    stock_col = dataset.column_for("Stock")
    campaign_col = dataset.column_for("Campaign")
    store_col = dataset.column_for("Store ID")

    if returns_col:
        # A flag counts orders, a quantity counts units — say which was counted.
        is_flag, units_col = returns_basis(dataset, returns_col)
        rate = overall_return_rate(dataset, returns_col)
        if rate is not None:
            returned = sum(
                v
                for v in (
                    returns_value(row, returns_col, is_flag=is_flag) for row in dataset.rows
                )
                if v is not None
            )
            total = len(dataset.rows) if is_flag else dataset.sum_of(units_col or "")
            noun = "orders" if is_flag else "units"
            kpis.append(
                _kpi(
                    "return_rate",
                    "Return Rate",
                    round(rate * 100, 2),
                    "percent",
                    higher_is_better=False,
                    caption=f"{returned:,.0f} of {total:,.0f} {noun}",
                )
            )

    if spend_col and total_revenue:
        # Campaign budgets repeat on every row of the campaign, so counting
        # them per row would inflate spend and crush the ROI figure.
        spend = total_by_grain(dataset, spend_col, campaign_col)
        roi = _safe_div(total_revenue - spend, spend)
        if roi is not None:
            kpis.append(
                _kpi(
                    "marketing_roi",
                    "Marketing ROI",
                    round(roi, 2),
                    "number",
                    caption=f"on {spend:,.0f} spend",
                )
            )

    if rating_col:
        ratings = dataset.numbers(rating_col)
        if ratings:
            kpis.append(
                _kpi(
                    "avg_rating",
                    "Avg Rating",
                    round(sum(ratings) / len(ratings), 2),
                    "number",
                    caption=f"across {len(ratings):,} rated orders",
                )
            )

    if delivery_col:
        days = dataset.numbers(delivery_col)
        if days:
            kpis.append(
                _kpi(
                    "avg_delivery",
                    "Avg Delivery Days",
                    round(sum(days) / len(days), 2),
                    "number",
                    higher_is_better=False,
                    caption=f"across {len(days):,} deliveries",
                )
            )

    # A target belongs to a period. Stacking every period's revenue against one
    # target reads as runaway over-attainment, so compare the latest period.
    if target_col and revenue_col and store_col and total_revenue:
        basis = target_basis(dataset, index, store_col, target_col, revenue_col)
        if basis:
            target = sum(basis["targets"].values())
            actual = sum(basis["actuals"].values())
            attainment = _safe_div(actual, target)
            if attainment is not None:
                period = basis["period"]
                kpis.append(
                    _kpi(
                        "target_attainment",
                        "Target Attainment",
                        round(attainment * 100, 2),
                        "percent",
                        caption=(
                            f"{period}: {actual:,.0f} of {target:,.0f}"
                            if period
                            else f"{actual:,.0f} of {target:,.0f}"
                        ),
                    )
                )

    if stock_col:
        stock_values = dataset.numbers(stock_col)
        if stock_values:
            out_of_stock = sum(1 for v in stock_values if v <= 0)
            kpis.append(
                _kpi(
                    "stock_on_hand",
                    "Stock On Hand",
                    round(sum(stock_values), 2),
                    "number",
                    caption=f"{out_of_stock} line(s) at zero" if out_of_stock else "no stockouts",
                )
            )

    measure_col = revenue_col or profit_col or quantity_col
    measure_label = "Revenue" if revenue_col else ("Profit" if profit_col else "Units")

    dimension_cols = [(canon, dataset.column_for(canon)) for canon in DIMENSION_FIELDS]
    dimension_cols = [(canon, col) for canon, col in dimension_cols if col]

    for canon, col in dimension_cols[:2]:
        ranked = (
            aggregate_by(dataset, col, measure_col, limit=1)
            if measure_col
            else count_by(dataset, col, limit=1)
        )
        if not ranked:
            continue
        top = ranked[0]
        unit = measure_label if measure_col else "Records"
        kpis.append(
            _kpi(
                f"top_{canon.lower().replace(' ', '_')}",
                f"Top {canon}",
                str(top["label"]),
                "text",
                caption=f"{unit}: {top['value']:,.0f}",
            )
        )

    kpis.append(
        _kpi(
            "records",
            "Records Analyzed",
            len(dataset.rows),
            "number",
            caption=f"of {dataset.total:,} total" if dataset.truncated else "complete dataset",
        )
    )

    # --- Charts ------------------------------------------------------------
    if index and measure_col:
        series_keys = [k for k in (revenue_col, profit_col, cost_col) if k]
        if not series_keys:
            series_keys = [measure_col]
        totals_by_key = {key: bucket_totals(dataset, index, key) for key in series_keys}
        points: list[dict[str, Any]] = []
        for bucket in index.buckets:
            point: dict[str, Any] = {"label": bucket.label}
            for key in series_keys:
                point[key] = round(totals_by_key[key][bucket.key], 2)
            points.append(point)
        charts.append(
            {
                "id": "trend",
                "title": f"{measure_label} trend by {index.unit_label}",
                "type": "line",
                "label_key": "label",
                "value_keys": series_keys,
                "data": points,
                "format": "currency" if revenue_col else "number",
            }
        )
    elif measure_col and not date_col:
        notices.append(
            'Map a column to "Date" to unlock trend charts and period-over-period comparisons.'
        )

    # Take the first few dimensions that actually vary. Slicing before this
    # check meant a constant Region could crowd out Product or Campaign.
    # The case study asks to compare across products, stores, regions,
    # employees, campaigns and segments, so those six are charted first — a
    # dimension it does not name (Category, Channel) must not take their slot.
    named_first = sorted(
        dimension_cols, key=lambda item: item[0] not in CASE_STUDY_DIMENSIONS
    )
    charted = 0
    for canon, col in named_first:
        if charted >= 8:
            break

        # Revenue and profit together: the brief asks which segments earn, not
        # just which sell. A thin-margin leader is invisible on revenue alone.
        paired = profit_by(dataset, col, limit=10) if revenue_col else []
        if len(paired) >= 2:
            charts.append(
                {
                    "id": f"by_{canon.lower().replace(' ', '_')}",
                    "title": f"Revenue and profit by {canon}",
                    "type": "bar" if len(paired) > 5 else "hbar",
                    "label_key": "label",
                    "value_keys": ["revenue", "profit"],
                    "data": [
                        {"label": r["label"], "revenue": r["revenue"], "profit": r["profit"]}
                        for r in paired
                    ],
                    "format": "currency",
                }
            )
            charted += 1
            continue

        if measure_col:
            data = aggregate_by(dataset, col, measure_col, limit=10)
            value_label = measure_label
            fmt = "currency" if revenue_col else "number"
        else:
            data = count_by(dataset, col, limit=10)
            value_label = "Records"
            fmt = "number"
        if len(data) < 2:
            continue
        charted += 1
        charts.append(
            {
                "id": f"by_{canon.lower().replace(' ', '_')}",
                "title": f"{value_label} by {canon}",
                "type": "bar" if len(data) > 5 else "hbar",
                "label_key": "label",
                "value_keys": ["value"],
                "data": data,
                "format": fmt,
            }
        )

    # Which campaigns pay back, not just which are biggest.
    spend_col = dataset.column_for("Marketing Spend")
    campaign_col = dataset.column_for("Campaign")
    if spend_col and campaign_col and revenue_col:
        roi = roi_by(dataset, campaign_col, spend_col, revenue_col, limit=10)
        if len(roi) >= 2:
            charts.append(
                {
                    "id": "roi_by_campaign",
                    "title": "Return on spend by Campaign",
                    "type": "bar" if len(roi) > 5 else "hbar",
                    "label_key": "label",
                    "value_keys": ["value"],
                    "data": roi,
                    "format": "number",
                }
            )

    if not revenue_col:
        notices.append(
            'No column is mapped to "Revenue", so financial KPIs are unavailable. '
            "Open Data Sources to adjust the field mapping."
        )
    if not dimension_cols:
        notices.append(
            'Map a column to a dimension such as "Region", "Category", or "Store ID" '
            "to see breakdown charts."
        )

    return {
        "kpis": kpis,
        "charts": charts,
        "notices": notices,
        "period": {
            "granularity": index.granularity if index else None,
            "start": index.min_date.isoformat() if index else None,
            "end": index.max_date.isoformat() if index else None,
            "buckets": len(index.buckets) if index else 0,
        },
    }


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


def explain_change(
    dataset: Dataset,
    index: TimeIndex,
    measure: str,
    *,
    dimensions: tuple[str, ...] = DIMENSION_FIELDS,
    max_drivers: int = 2,
) -> str | None:
    """Name the segments that moved a measure between the last two periods.

    A finding that says revenue fell is only half an answer; management needs
    to know where it fell. This attributes the change to the dimension values
    that contributed most of it.
    """
    if len(index.buckets) < 2:
        return None

    latest_key = index.buckets[-1].key
    prior_keys = {b.key for b in index.buckets[:-1]}
    periods = max(1, len(index.buckets) - 1)

    best: tuple[float, str, list[str]] | None = None

    for canonical in dimensions:
        column = dataset.column_for(canonical)
        if not column:
            continue

        latest: dict[str, float] = {}
        baseline: dict[str, float] = {}
        for row, key in zip(dataset.rows, index.row_bucket, strict=False):
            label = str(row.get(column, "")).strip()
            value = to_number(row.get(measure))
            if not label or value is None or key is None:
                continue
            if key == latest_key:
                latest[label] = latest.get(label, 0.0) + value
            elif key in prior_keys:
                baseline[label] = baseline.get(label, 0.0) + value

        labels = set(latest) | set(baseline)
        if len(labels) < 2:
            continue

        # Compare the latest period against the average of the earlier ones.
        deltas = [
            (label, latest.get(label, 0.0) - baseline.get(label, 0.0) / periods)
            for label in labels
        ]
        total_move = sum(abs(d) for _, d in deltas)
        if total_move <= 0:
            continue

        deltas.sort(key=lambda item: abs(item[1]), reverse=True)
        top = deltas[:max_drivers]
        share = sum(abs(d) for _, d in top) / total_move

        # Prefer the dimension that concentrates the movement most tightly.
        if best is None or share > best[0]:
            best = (
                share,
                canonical,
                [
                    f"{label} ({'+' if delta >= 0 else '-'}{abs(delta):,.0f})"
                    for label, delta in top
                    if abs(delta) > 0
                ],
            )

    if not best or not best[2] or best[0] < 0.4:
        return None

    share, canonical, parts = best
    lead = "Mostly" if share >= 0.7 else "Largely"
    return f"{lead} {canonical.lower()}: {', '.join(parts)}."


def _finding(
    finding_id: str,
    severity: str,
    title: str,
    body: str,
    action: str,
    *,
    context: str,
    metric: str | None = None,
) -> dict[str, Any]:
    return {
        "id": finding_id,
        "severity": severity,
        "title": title,
        "body": body,
        "action": action,
        "context": context,
        "metric": metric,
    }


def build_findings(dataset: Dataset) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    prefix = f"s{dataset.source.id}"

    revenue_col = dataset.column_for("Revenue")
    cost_col = dataset.column_for("Cost")
    profit_col = dataset.column_for("Profit")
    date_col = dataset.column_for("Date", "Timestamp")
    measure_col = revenue_col or profit_col or dataset.column_for("Quantity")
    measure_label = "revenue" if revenue_col else ("profit" if profit_col else "volume")

    index = build_time_index(dataset, date_col) if date_col else None

    # 1. Period movement against the trailing baseline.
    if index and measure_col and len(index.buckets) >= 3:
        totals = bucket_totals(dataset, index, measure_col)
        keys = [b.key for b in index.buckets]
        latest_label = index.buckets[-1].label
        history = [totals[k] for k in keys[:-1]]
        baseline = sum(history) / len(history)
        latest = totals[keys[-1]]
        change = _pct_change(latest, baseline)
        if change is not None and abs(change) >= 20:
            if change <= -35:
                severity, verb = "critical", "fell"
            elif change < 0:
                severity, verb = "warning", "fell"
            else:
                severity, verb = "opportunity", "rose"
            action = (
                "Compare the underlying rows for this period in Ask AI to isolate which "
                "segment drove the move before acting on it."
                if change < 0
                else "Confirm the uplift is repeatable, then shift budget toward whatever "
                "changed in this period."
            )
            # Say where the movement came from, not just that it happened.
            driver = explain_change(dataset, index, measure_col)
            findings.append(
                _finding(
                    f"{prefix}-trend",
                    severity,
                    f"{latest_label} {measure_label} {verb} "
                    f"{abs(change):.0f}% against the trailing average",
                    f"{latest_label} recorded {latest:,.0f} versus a {len(history)}-"
                    f"{index.unit_label} trailing average of {baseline:,.0f}."
                    + (f" {driver}" if driver else ""),
                    action,
                    context=latest_label,
                    metric=f"{change:+.0f}% vs trailing avg",
                )
            )

    # 2. Concentration and spread across the strongest dimension.
    dimension_col: str | None = None
    dimension_name: str | None = None
    for canon in DIMENSION_FIELDS:
        col = dataset.column_for(canon)
        if col:
            dimension_col, dimension_name = col, canon
            break

    if dimension_col and dimension_name and measure_col:
        ranked = aggregate_by(dataset, dimension_col, measure_col, limit=50)
        total = sum(item["value"] for item in ranked)
        if len(ranked) >= 3 and total > 0:
            leader = ranked[0]
            share = leader["value"] / total * 100
            if share >= 40:
                findings.append(
                    _finding(
                        f"{prefix}-concentration",
                        "warning",
                        f"{leader['label']} accounts for {share:.0f}% of {measure_label}",
                        f"Across {len(ranked)} {dimension_name.lower()} values, "
                        f"{leader['label']} contributes {leader['value']:,.0f} "
                        f"of {total:,.0f}.",
                        f"Build a retention plan for {leader['label']} and identify the next "
                        f"two {dimension_name.lower()} values worth growing.",
                        context=f"{dimension_name} mix",
                        metric=f"{share:.0f}% concentration",
                    )
                )

            average = total / len(ranked)
            laggard = ranked[-1]
            if average > 0 and laggard["value"] < average * 0.35:
                gap = _pct_change(laggard["value"], average)
                findings.append(
                    _finding(
                        f"{prefix}-laggard",
                        "warning",
                        f"{laggard['label']} is underperforming the "
                        f"{dimension_name.lower()} average",
                        f"{laggard['label']} contributed {laggard['value']:,.0f} against an "
                        f"average of {average:,.0f} across {len(ranked)} values.",
                        f"Review whether {laggard['label']} is genuinely underperforming or "
                        "whether its rows are incomplete in the source data.",
                        context=f"{dimension_name} mix",
                        metric=f"{gap:+.0f}% vs average" if gap is not None else None,
                    )
                )

            if average > 0 and leader["value"] > average * 1.75 and share < 40:
                findings.append(
                    _finding(
                        f"{prefix}-leader",
                        "opportunity",
                        f"{leader['label']} outperforms its peers by "
                        f"{leader['value'] / average:.1f}x",
                        f"{leader['label']} contributed {leader['value']:,.0f} versus a peer "
                        f"average of {average:,.0f}.",
                        f"Document what {leader['label']} does differently and test it on the "
                        "next two ranked values.",
                        context=f"{dimension_name} mix",
                        metric=f"{leader['value'] / average:.1f}x average",
                    )
                )

    # 3. Margin movement.
    if revenue_col and (profit_col or cost_col) and index and len(index.buckets) >= 3:
        rev = bucket_totals(dataset, index, revenue_col)
        if profit_col:
            prof = bucket_totals(dataset, index, profit_col)
        else:
            cst = bucket_totals(dataset, index, cost_col)
            prof = {k: rev[k] - cst[k] for k in rev}
        margins: list[tuple[str, float]] = []
        for bucket in index.buckets:
            margin = _safe_div(prof[bucket.key], rev[bucket.key])
            if margin is not None:
                margins.append((bucket.label, margin * 100))
        if len(margins) >= 3:
            latest_label, latest_margin = margins[-1]
            baseline = sum(m for _, m in margins[:-1]) / len(margins[:-1])
            drop = baseline - latest_margin
            if drop >= 3:
                findings.append(
                    _finding(
                        f"{prefix}-margin",
                        "critical" if drop >= 8 else "warning",
                        f"Margin compressed {drop:.1f} points in {latest_label}",
                        f"Margin was {latest_margin:.1f}% in {latest_label} against a trailing "
                        f"average of {baseline:.1f}%.",
                        "Check whether cost per unit moved or the product mix shifted toward "
                        "lower-margin lines.",
                        context=latest_label,
                        metric=f"-{drop:.1f} pts",
                    )
                )
            elif drop <= -3:
                findings.append(
                    _finding(
                        f"{prefix}-margin-up",
                        "opportunity",
                        f"Margin expanded {abs(drop):.1f} points in {latest_label}",
                        f"Margin reached {latest_margin:.1f}% in {latest_label} against a "
                        f"trailing average of {baseline:.1f}%.",
                        "Identify which lines drove the expansion and protect their pricing.",
                        context=latest_label,
                        metric=f"+{abs(drop):.1f} pts",
                    )
                )

    # 4. Stale data.
    if index:
        age = (date.today() - index.max_date).days
        if age > 45:
            findings.append(
                _finding(
                    f"{prefix}-stale",
                    "warning",
                    f"Newest record is {age} days old",
                    f"The latest date in {dataset.source.name} is "
                    f"{index.max_date.isoformat()}. Metrics on this page describe that "
                    "period, not today.",
                    "Re-upload the dataset or reconnect the database so the dashboard tracks "
                    "current performance.",
                    context="Data freshness",
                    metric=f"{age} days stale",
                )
            )

    # 4b. Revenue rising while margin falls — the case study's headline risk.
    if revenue_col and (profit_col or cost_col) and index and len(index.buckets) >= 4:
        rev = bucket_totals(dataset, index, revenue_col)
        if profit_col:
            prof = bucket_totals(dataset, index, profit_col)
        else:
            cst = bucket_totals(dataset, index, cost_col)
            prof = {k: rev[k] - cst[k] for k in rev}

        keys = [b.key for b in index.buckets]
        half = max(2, len(keys) // 2)
        early, late = keys[:half], keys[half:]

        early_rev = sum(rev[k] for k in early)
        late_rev = sum(rev[k] for k in late)
        early_margin = _safe_div(sum(prof[k] for k in early), early_rev)
        late_margin = _safe_div(sum(prof[k] for k in late), late_rev)

        if early_margin is not None and late_margin is not None:
            rev_change = _pct_change(late_rev, early_rev)
            margin_drop = (early_margin - late_margin) * 100
            if rev_change is not None and rev_change > 5 and margin_drop > 2:
                findings.append(
                    _finding(
                        f"{prefix}-divergence",
                        "critical",
                        f"Revenue is up {rev_change:.0f}% but margin is down "
                        f"{margin_drop:.1f} points",
                        f"Revenue rose from {early_rev:,.0f} to {late_rev:,.0f} while margin "
                        f"fell from {early_margin * 100:.1f}% to {late_margin * 100:.1f}%. "
                        "Growth is being bought rather than earned.",
                        "Check whether discounting, product mix, or rising unit costs are "
                        "behind it before pushing more volume.",
                        context="Growth quality",
                        metric=f"+{rev_change:.0f}% rev / -{margin_drop:.1f} pts margin",
                    )
                )

    # 4c. Products returned far more often than the rest.
    returns_col = dataset.column_for("Returns")
    product_col = dataset.column_for("Product")
    if returns_col and product_col:
        rates = return_rate_by(dataset, product_col, returns_col, min_denominator=5)
        overall = overall_return_rate(dataset, returns_col)
        basis_noun = "orders" if returns_basis(dataset, returns_col)[0] else "units"
        if len(rates) >= 2 and overall:
            worst = rates[0]
            if worst["value"] > overall * 100 * 1.5 and worst["value"] >= 5:
                findings.append(
                    _finding(
                        f"{prefix}-returns",
                        "critical" if worst["value"] >= 15 else "warning",
                        f"{worst['label']} is returned {worst['value']:.1f}% of the time",
                        f"Against an overall return rate of {overall * 100:.1f}%, "
                        f"{worst['label']} runs at {worst['value']:.1f}% across "
                        f"{worst['count']:,} {basis_noun}.",
                        "Inspect quality, listing accuracy, and packaging for this line "
                        "before it erodes more margin.",
                        context="Returns",
                        metric=f"{worst['value']:.1f}% returned",
                    )
                )

    # 4d. Campaign ROI spread.
    spend_col = dataset.column_for("Marketing Spend")
    campaign_col = dataset.column_for("Campaign")
    if spend_col and campaign_col and revenue_col:
        spend_by = {
            item["label"]: item["value"]
            for item in aggregate_by_grain(dataset, campaign_col, spend_col, limit=50)
        }
        revenue_by = {
            item["label"]: item["value"]
            for item in aggregate_by(dataset, campaign_col, revenue_col, limit=50)
        }
        roi = [
            (name, (revenue_by[name] - spend) / spend)
            for name, spend in spend_by.items()
            if spend > 0 and name in revenue_by
        ]
        if len(roi) >= 2:
            roi.sort(key=lambda item: item[1], reverse=True)
            best, worst = roi[0], roi[-1]
            # A campaign can be profitable and still be the wrong place for the
            # budget. Alerting only below break-even hid a nine-fold spread.
            spread = (1 + best[1]) / (1 + worst[1]) if worst[1] > -1 else None
            unprofitable = worst[1] < 1
            lopsided = spread is not None and spread >= 3
            if best[1] > worst[1] and (unprofitable or lopsided):
                if unprofitable:
                    severity = "critical" if worst[1] < 0 else "warning"
                    title = f"{worst[0]} returns {worst[1]:.2f}x on spend"
                else:
                    severity = "opportunity"
                    title = (
                        f"Marketing spend works {spread:.1f}x harder in {best[0]} "
                        f"than {worst[0]}"
                    )
                findings.append(
                    _finding(
                        f"{prefix}-campaign-roi",
                        severity,
                        title,
                        f"{best[0]} returns {best[1]:.2f}x while {worst[0]} returns "
                        f"{worst[1]:.2f}x on a spend of {spend_by[worst[0]]:,.0f}.",
                        f"Shift budget from {worst[0]} toward {best[0]} and re-test before "
                        "the next cycle.",
                        context="Marketing",
                        metric=f"{worst[1]:.2f}x vs {best[1]:.2f}x",
                    )
                )

    # 4e. Delivery partners that are slow or poorly rated.
    partner_col = dataset.column_for("Delivery Partner")
    delivery_col = dataset.column_for("Delivery Days")
    rating_col = dataset.column_for("Rating")
    if partner_col and (delivery_col or rating_col):
        slowest = average_by(dataset, partner_col, delivery_col)[0] if delivery_col else None
        worst_rated = (
            average_by(dataset, partner_col, rating_col, ascending=True)[0]
            if rating_col
            else None
        )
        all_days = dataset.numbers(delivery_col) if delivery_col else []
        avg_days = sum(all_days) / len(all_days) if all_days else None
        all_ratings = dataset.numbers(rating_col) if rating_col else []
        avg_rating = sum(all_ratings) / len(all_ratings) if all_ratings else None

        slow = bool(slowest and avg_days and slowest["value"] > avg_days * 1.3)
        poor = bool(worst_rated and avg_rating and worst_rated["value"] < avg_rating * 0.85)
        if slow or poor:
            partner = (slowest if slow else worst_rated)["label"]
            bits = []
            if slow and slowest:
                bits.append(f"{slowest['value']:.1f} days against a {avg_days:.1f} day average")
            if poor and worst_rated:
                bits.append(
                    f"a {worst_rated['value']:.1f} rating against {avg_rating:.1f} overall"
                )
            findings.append(
                _finding(
                    f"{prefix}-delivery",
                    "warning",
                    f"{partner} is underperforming on delivery",
                    f"{partner} shows " + " and ".join(bits) + ".",
                    f"Review the contract and volume share for {partner} against the "
                    "best-performing partner before renewal.",
                    context="Delivery",
                    metric=bits[0] if bits else None,
                )
            )

    # 4f. Locations behind target.
    target_col = dataset.column_for("Target")
    store_col = dataset.column_for("Store ID")
    if target_col and revenue_col and store_col:
        basis = target_basis(dataset, index, store_col, target_col, revenue_col) or {}
        targets = basis.get("targets", {})
        actuals = basis.get("actuals", {})
        target_period = basis.get("period")
        behind = sorted(
            [
                (name, actuals.get(name, 0.0) / target)
                for name, target in targets.items()
                if target > 0 and actuals.get(name, 0.0) < target
            ],
            key=lambda item: item[1],
        )
        if behind:
            worst_name, worst_ratio = behind[0]
            gap = targets[worst_name] - actuals.get(worst_name, 0.0)
            findings.append(
                _finding(
                    f"{prefix}-target",
                    "critical" if worst_ratio < 0.8 else "warning",
                    f"{len(behind)} location(s) behind target, worst is {worst_name}"
                    + (f" in {target_period}" if target_period else ""),
                    f"{worst_name} reached {worst_ratio * 100:.0f}% of its target, short by "
                    f"{gap:,.0f}.",
                    f"Review pipeline and staffing at {worst_name}, and confirm the target "
                    "is still realistic for the period.",
                    context="Targets",
                    metric=f"{worst_ratio * 100:.0f}% of target",
                )
            )

    # 4g. Stockouts.
    stock_col = dataset.column_for("Stock")
    if stock_col and product_col:
        out_of_stock = sorted(
            {
                str(row.get(product_col, "")).strip()
                for row in dataset.rows
                if (to_number(row.get(stock_col)) or 0) <= 0
                and str(row.get(product_col, "")).strip()
            }
        )
        if out_of_stock:
            shown = ", ".join(out_of_stock[:4])
            more = f" and {len(out_of_stock) - 4} more" if len(out_of_stock) > 4 else ""
            findings.append(
                _finding(
                    f"{prefix}-stockout",
                    "critical",
                    f"{len(out_of_stock)} product(s) are out of stock",
                    f"No stock on hand for {shown}{more}.",
                    "Reorder these lines and check whether the reorder point is set too low.",
                    context="Inventory",
                    metric=f"{len(out_of_stock)} at zero",
                )
            )

    # 4h. The segment that sells hardest and earns least — the divergence the
    # case study is built around, seen across segments rather than over time.
    if revenue_col and (profit_col or cost_col):
        overall_revenue = dataset.sum_of(revenue_col)
        overall_profit = (
            dataset.sum_of(profit_col)
            if profit_col
            else overall_revenue - dataset.sum_of(cost_col)
        )
        overall_margin = _safe_div(overall_profit, overall_revenue)
        widest: tuple[float, str, dict[str, Any], dict[str, Any]] | None = None

        for canon in DIMENSION_FIELDS:
            column = dataset.column_for(canon)
            if not column:
                continue
            ranked = [r for r in profit_by(dataset, column, limit=50) if r["margin"] is not None]
            if len(ranked) < 3:
                continue
            leader = ranked[0]
            by_margin = sorted(ranked, key=lambda r: r["margin"], reverse=True)
            richest = by_margin[0]
            if richest["label"] == leader["label"]:
                continue
            gap = richest["margin"] - leader["margin"]
            if gap < 5:
                continue
            if widest is None or gap > widest[0]:
                widest = (gap, canon, leader, richest)

        if widest:
            gap, canon, leader, richest = widest
            overall_text = (
                f" against {overall_margin * 100:.1f}% overall" if overall_margin else ""
            )
            findings.append(
                _finding(
                    f"{prefix}-margin-mix",
                    "warning" if gap >= 8 else "info",
                    f"{leader['label']} leads {canon.lower()} on revenue but earns "
                    f"{gap:.1f} points less margin",
                    f"{leader['label']} took {leader['revenue']:,.0f} at "
                    f"{leader['margin']:.1f}% margin{overall_text}, while "
                    f"{richest['label']} turns {richest['margin']:.1f}% on "
                    f"{richest['revenue']:,.0f}.",
                    f"Find out what {richest['label']} does differently on price, mix or "
                    f"cost, and apply it to {leader['label']} before chasing more volume "
                    "there.",
                    context=f"{canon} mix",
                    metric=f"{leader['margin']:.1f}% vs {richest['margin']:.1f}%",
                )
            )

    # 4i. Inventory cover: too thin and too deep both cost money.
    stock_col = dataset.column_for("Stock")
    reorder_col = dataset.column_for("Reorder Level")
    cover_name, cover_col = (
        ("Store ID", store_col) if store_col else ("Product", product_col)
    )
    if stock_col and cover_col:
        levels = {
            item["label"]: item["value"]
            for item in aggregate_by_grain(dataset, cover_col, stock_col, limit=100)
        }
        stocked = {k: v for k, v in levels.items() if v > 0}
        if len(levels) >= 3 and stocked:
            ordered = sorted(stocked.values())
            median = ordered[len(ordered) // 2]

            below_reorder: list[tuple[str, float, float]] = []
            if reorder_col:
                reorder_levels = {
                    item["label"]: item["value"]
                    for item in average_by(dataset, cover_col, reorder_col, limit=100)
                }
                below_reorder = [
                    (label, value, reorder_levels[label])
                    for label, value in stocked.items()
                    if reorder_levels.get(label) and value < reorder_levels[label]
                ]

            if below_reorder:
                below_reorder.sort(key=lambda item: item[1] / item[2])
                label, value, level = below_reorder[0]
                findings.append(
                    _finding(
                        f"{prefix}-restock",
                        "warning",
                        f"{len(below_reorder)} {cover_name.lower()}(s) below reorder level",
                        f"{label} holds {value:,.0f} against a reorder level of "
                        f"{level:,.0f}. Stock runs out before it is replaced.",
                        "Raise a replenishment order for these lines and review whether the "
                        "reorder point matches current demand.",
                        context="Inventory",
                        metric=f"{value:,.0f} of {level:,.0f}",
                    )
                )
            elif median > 0:
                thin = sorted(
                    [(k, v) for k, v in stocked.items() if v <= median * 0.3],
                    key=lambda item: item[1],
                )
                if thin:
                    label, value = thin[0]
                    findings.append(
                        _finding(
                            f"{prefix}-thin-cover",
                            "warning",
                            f"{label} is carrying {value / median * 100:.0f}% of typical stock",
                            f"{label} holds {value:,.0f} against a typical "
                            f"{cover_name.lower()} level of {median:,.0f}. Thin cover turns "
                            "demand into lost sales rather than revenue.",
                            f"Check whether {label} is under-ordering or simply selling "
                            "faster than it is replenished.",
                            context="Inventory",
                            metric=f"{value:,.0f} vs {median:,.0f} typical",
                        )
                    )

            if median > 0:
                deep = sorted(
                    [(k, v) for k, v in stocked.items() if v >= median * 3],
                    key=lambda item: item[1],
                    reverse=True,
                )
                if deep:
                    label, value = deep[0]
                    findings.append(
                        _finding(
                            f"{prefix}-excess-stock",
                            "info",
                            f"{label} holds {value / median:.1f}x the typical stock",
                            f"{label} carries {value:,.0f} against a typical "
                            f"{cover_name.lower()} level of {median:,.0f}. That is working "
                            "capital sitting still, and it ages.",
                            f"Move the excess to {cover_name.lower()}s that are short, or "
                            "discount it deliberately rather than writing it down later.",
                            context="Inventory",
                            metric=f"{value:,.0f} vs {median:,.0f} typical",
                        )
                    )

    # 5. Data quality.
    unmapped = [
        col for col, canon in dataset.mapping.items() if canon == "Unmapped" and col in dataset.columns
    ]
    if unmapped:
        shown = ", ".join(unmapped[:4])
        more = f" and {len(unmapped) - 4} more" if len(unmapped) > 4 else ""
        plural = "s" if len(unmapped) != 1 else ""
        findings.append(
            _finding(
                f"{prefix}-unmapped",
                "warning",
                f"{len(unmapped)} column{plural} not mapped to a canonical field",
                f"{dataset.source.name} has unmapped columns: {shown}{more}. "
                "They are invisible to KPIs and findings.",
                "Open Data Sources and map these columns so they contribute to analysis.",
                context="Data quality",
                metric=f"{len(unmapped)} unmapped",
            )
        )

    for canon in ("Revenue", "Date"):
        col = dataset.column_for(canon)
        if not col or not dataset.rows:
            continue
        if canon == "Revenue":
            missing = sum(1 for row in dataset.rows if to_number(row.get(col)) is None)
        else:
            missing = sum(1 for row in dataset.rows if to_date(row.get(col)) is None)
        ratio = missing / len(dataset.rows) * 100
        if ratio >= 10:
            findings.append(
                _finding(
                    f"{prefix}-missing-{canon.lower()}",
                    "critical" if ratio >= 30 else "warning",
                    f"{ratio:.0f}% of rows have an unusable {canon} value",
                    f"{missing:,} of {len(dataset.rows):,} analyzed rows could not be read as "
                    f"a {canon.lower()} from column {col}.",
                    f"Clean the {canon.lower()} column at the source, or re-map it if the "
                    "wrong column is currently selected.",
                    context="Data quality",
                    metric=f"{missing:,} rows",
                )
            )

    if dataset.truncated and dataset.total:
        findings.append(
            _finding(
                f"{prefix}-truncated",
                "info",
                f"Analysis covers the first {len(dataset.rows):,} of {dataset.total:,} rows",
                "The dataset exceeds the live-analysis row cap, so totals below are partial.",
                "Narrow the dataset at the source, or use Ask AI to run an aggregate query "
                "across the full table.",
                context="Coverage",
                metric=f"{len(dataset.rows) / dataset.total * 100:.0f}% covered",
            )
        )

    order = {"critical": 0, "warning": 1, "opportunity": 2, "info": 3}
    findings.sort(key=lambda f: order.get(f["severity"], 9))
    return findings


def coverage_report(dataset: Dataset) -> dict[str, Any]:
    index = dataset.canonical
    expected = ["Revenue", "Cost", "Profit", "Quantity", "Date", *DIMENSION_FIELDS]
    return {
        "mapped": sorted(index.keys()),
        "missing": [f for f in expected if f not in index],
        "unmapped_columns": [col for col, canon in dataset.mapping.items() if canon == "Unmapped"],
    }


def summarize_sources(sources: Iterable[DataSource]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for source in sources:
        config = parse_connection_config(source)
        raw = config.get("field_mapping")
        mapping = raw if isinstance(raw, dict) else {}
        canon = {str(v) for v in mapping.values()}
        row_count = config.get("row_count")
        try:
            row_count = int(row_count) if row_count is not None else None
        except (TypeError, ValueError):
            row_count = None
        out.append(
            {
                "id": source.id,
                "name": source.name,
                "source_type": source.source_type,
                "mapping_status": config.get("mapping_status"),
                "row_count": row_count,
                "analyzable": bool(canon - {"Unmapped", "Ignore"}),
            }
        )
    return out
