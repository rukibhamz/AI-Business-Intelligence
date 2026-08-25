"""Live analytics derived from connected data sources.

Everything here is computed from real rows pulled through the source
connectors - there is no sample or placeholder data. When a dataset lacks
the fields a metric needs, the metric is omitted and the reason is reported
back to the UI so it can render an honest empty state.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable

from app.models import DataSource
from app.services.schema_registry import parse_connection_config, preview_source_data

MAX_ROWS = 20000

# Canonical fields usable as a breakdown dimension, best first.
DIMENSION_FIELDS = (
    "Store ID",
    "Region",
    "Category",
    "Product",
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

    preview = await preview_source_data(source, limit=limit, offset=0)
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
    for row, key in zip(dataset.rows, index.row_bucket):
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

    for canon, col in dimension_cols[:3]:
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
            findings.append(
                _finding(
                    f"{prefix}-trend",
                    severity,
                    f"{latest_label} {measure_label} {verb} "
                    f"{abs(change):.0f}% against the trailing average",
                    f"{latest_label} recorded {latest:,.0f} versus a {len(history)}-"
                    f"{index.unit_label} trailing average of {baseline:,.0f}.",
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
