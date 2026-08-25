from __future__ import annotations

import json
import re
from typing import Any

from app.models import DataSource
from app.services.profiling import describe_profile, schema_date_range
from app.services.schema_types import SourceSchema, parse_schema_json


def _column_line(column: dict) -> str:
    return f"{column['name']}:{column['type']}{describe_profile(column.get('profile'))}"


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
        cols = ", ".join(_column_line(c) for c in table["columns"])
        lines.append(f"- {table['name']}({cols})")

    span = schema_date_range(schema)
    if span:
        lines.append(f"\nThis dataset covers {span[0]} to {span[1]}.")
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
            cols = ", ".join(_column_line(c) for c in table["columns"])
            lines.append(f"- {table['name']}({cols})")
        span = schema_date_range(schema)
        if span:
            lines.append(f"  (covers {span[0]} to {span[1]})")
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


def table_names(source: DataSource) -> list[str]:
    return [t["name"] for t in get_source_schema(source)["tables"]]


def score_table(table: dict) -> int:
    """How much business meaning a table's columns carry.

    A MySQL connection often exposes many tables; the one worth analysing is
    the one that actually holds measures and a date, not whichever happens to
    come first alphabetically.
    """
    from app.services.field_mapping import suggest_canonical

    measures = {"Revenue", "Cost", "Profit", "Quantity", "Price", "Marketing Spend"}
    dimensions = {
        "Store ID", "Region", "Product", "Category", "Customer",
        "Employee", "Campaign", "Channel", "Customer Segment",
    }

    score = 0
    fields = {suggest_canonical(c["name"]) for c in table.get("columns", [])}
    score += 6 * len(fields & measures)
    score += 2 * len(fields & dimensions)
    if fields & {"Date", "Timestamp"}:
        score += 5
    return score


def pick_primary_table(source: DataSource) -> str | None:
    """The table analytics should read for this source."""
    tables = get_source_schema(source)["tables"]
    if not tables:
        return None
    ranked = sorted(
        tables,
        key=lambda t: (-score_table(t), tables.index(t)),
    )
    return ranked[0]["name"]


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



_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10,
    "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}


def _date_column(schema: SourceSchema) -> tuple[str, dict] | None:
    """The first column profiled as a date, with its profile."""
    for table in schema["tables"]:
        for column in table["columns"]:
            profile = column.get("profile") or {}
            if profile.get("kind") == "date":
                return column["name"], profile
    return None


def _month_range_filter(question: str, schema: SourceSchema) -> str | None:
    """Turn "between march and may" into a half-open date filter.

    The year comes from the profiled range of the data, never from today's
    calendar — the whole point is not to invent a year the data lacks.
    """
    found = _date_column(schema)
    if not found:
        return None
    column, profile = found

    months = [
        _MONTHS[word]
        for word in re.findall(r"[a-z]+", question.lower())
        if word in _MONTHS
    ]
    if not months:
        return None

    start_month, end_month = min(months), max(months)
    year = str(profile.get("max", ""))[:4]
    if not year.isdigit():
        return None

    start = f"{year}-{start_month:02d}-01"
    end_year, next_month = int(year), end_month + 1
    if next_month > 12:
        next_month, end_year = 1, end_year + 1
    end = f"{end_year}-{next_month:02d}-01"
    return f"{quote_ident(column)} >= '{start}' AND {quote_ident(column)} < '{end}'"


#: Question words that name a metric, mapped to the canonical fields it needs.
#: Order matters — the most specific reading of a question wins.
_ASK_RETURNS = ("return rate", "returns", "returned", "refund", "sent back")
_ASK_ROI = ("roi", "return on investment", "return on spend", "campaign", "marketing")
_ASK_TARGET = ("target", "quota", "goal", "behind", "shortfall", "failing to meet")
_ASK_DELIVERY = ("delivery", "deliver", "delays", "delayed", "late", "logistics", "shipping")
_ASK_RATING = ("rating", "satisfaction", "csat", "review", "happy", "unhappy")
_ASK_STOCK = ("stock", "stockout", "stocked out", "inventory", "excess", "overstock")
_ASK_PROFIT = ("profit", "margin", "profitability", "profitable", "earn", "bottom line")
_ASK_GROWTH = ("growth", "growing", "trend", "over time", "month on month", "trajectory")
_ASK_VALUE = ("valuable", "most revenue", "best", "top", "biggest", "highest", "generate")

#: Where each metric naturally lands when the question names no dimension.
_NATURAL_DIMENSION = {
    "returns": ("Product", "Category"),
    "roi": ("Campaign",),
    "target": ("Store ID", "Region"),
    "delivery": ("Delivery Partner",),
    "rating": ("Delivery Partner", "Product", "Store ID"),
    "stock": ("Store ID", "Product"),
}

#: Words a question uses to name a dimension, beyond the column name itself.
_DIMENSION_WORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("product", "products", "sku", "item", "items", "line", "lines"), "Product"),
    (("store", "stores", "outlet", "outlets", "branch", "branches", "location", "locations"), "Store ID"),
    (("region", "regions", "area", "areas", "territory", "territories"), "Region"),
    (("employee", "employees", "staff", "rep", "reps", "salesperson", "team"), "Employee"),
    (("campaign", "campaigns", "promotion", "promotions"), "Campaign"),
    (("segment", "segments", "customer segment", "customer segments"), "Customer Segment"),
    (("partner", "partners", "courier", "couriers", "carrier"), "Delivery Partner"),
    (("category", "categories"), "Category"),
    (("channel", "channels"), "Channel"),
    (("customer", "customers", "client", "clients", "buyer"), "Customer"),
    (("country", "countries"), "Country"),
)


def canonical_columns(source: DataSource, columns: list[str]) -> dict[str, str]:
    """Canonical field -> column name for the table being queried.

    Uses the operator's confirmed mapping when there is one and infers from
    column names when there is not, so the offline planner understands a source
    nobody has mapped yet.
    """
    from app.services.field_mapping import suggest_mapping
    from app.services.schema_registry import parse_connection_config

    config = parse_connection_config(source)
    mapping = config.get("field_mapping")
    if not isinstance(mapping, dict) or not mapping:
        mapping = suggest_mapping(columns)

    out: dict[str, str] = {}
    for column, canonical in mapping.items():
        if column in columns and canonical not in ("Unmapped", "Ignore"):
            out.setdefault(str(canonical), str(column))
    return out


def _asks(question: str, words: tuple[str, ...]) -> bool:
    return any(w in question for w in words)


def _named_dimension(question: str, canon: dict[str, str]) -> str | None:
    """The dimension the question names, whether or not it says "by"."""
    for words, canonical in _DIMENSION_WORDS:
        column = canon.get(canonical)
        if not column:
            continue
        if any(re.search(rf"\b{re.escape(w)}\b", question) for w in words):
            return column
        if re.search(rf"\b{re.escape(column.lower())}\b", question):
            return column
    return None


def _first(canon: dict[str, str], *canonicals: str) -> str | None:
    for name in canonicals:
        if canon.get(name):
            return canon[name]
    return None


def _grouped(
    table: str,
    dimension: str,
    selects: list[str],
    order: str,
    limit: int,
    where_sql: str,
) -> str:
    columns = ", ".join([quote_ident(dimension), *selects])
    return (
        f"SELECT {columns} FROM {quote_ident(table)}{where_sql} "
        f"GROUP BY {quote_ident(dimension)} ORDER BY {order} LIMIT {limit}"
    )


def _profit_expr(canon: dict[str, str]) -> str | None:
    """SUM of profit, from the profit column or from revenue minus cost."""
    profit = canon.get("Profit")
    if profit:
        return f"SUM({quote_ident(profit)})"
    revenue, cost = canon.get("Revenue"), canon.get("Cost")
    if revenue and cost:
        return f"SUM({quote_ident(revenue)}) - SUM({quote_ident(cost)})"
    return None


def metric_sql(
    source: DataSource,
    question: str,
    table: str,
    columns: list[str],
    *,
    limit: int,
    where_sql: str,
) -> str | None:
    """Turn a management question into a grouped query, offline.

    The brief's questions ("Which products have unusually high return rates?")
    name a metric and a dimension without ever saying "by", which is all the
    older planner understood. Everything here is built from the canonical field
    mapping, so it works on any source whose columns have been recognised.
    """
    q = question.lower()
    canon = canonical_columns(source, columns)
    if not canon:
        return None

    dimension = _named_dimension(q, canon)
    revenue = canon.get("Revenue")

    def natural(kind: str) -> str | None:
        return dimension or _first(canon, *_NATURAL_DIMENSION.get(kind, ()))

    # --- rates and ratios, most specific first ----------------------------
    returns, quantity = canon.get("Returns"), canon.get("Quantity")
    if _asks(q, _ASK_RETURNS) and returns and quantity:
        dim = natural("returns")
        rate = (
            f"ROUND(SUM({quote_ident(returns)}) * 100.0 / "
            f"NULLIF(SUM({quote_ident(quantity)}), 0), 2) AS return_rate_pct"
        )
        units = f"SUM({quote_ident(quantity)}) AS units"
        if dim:
            return _grouped(table, dim, [rate, units], "2 DESC", limit, where_sql)
        return f"SELECT {rate}, {units} FROM {quote_ident(table)}{where_sql}"

    spend = canon.get("Marketing Spend")
    if _asks(q, _ASK_ROI) and spend and revenue:
        dim = natural("roi")
        # A campaign budget repeated on every row is one budget: summing the
        # distinct values counts it once, the way the analytics engine does.
        roi = (
            f"ROUND(SUM({quote_ident(revenue)}) * 1.0 / "
            f"NULLIF(SUM(DISTINCT {quote_ident(spend)}), 0), 2) AS revenue_per_spend"
        )
        selects = [
            roi,
            f"SUM({quote_ident(revenue)}) AS revenue",
            f"SUM(DISTINCT {quote_ident(spend)}) AS spend",
        ]
        if dim:
            return _grouped(table, dim, selects, "2 DESC", limit, where_sql)

    target = canon.get("Target")
    if _asks(q, _ASK_TARGET) and target and revenue:
        dim = natural("target")
        if dim:
            selects = [
                f"SUM({quote_ident(revenue)}) AS revenue",
                f"MAX({quote_ident(target)}) AS target",
                f"ROUND(SUM({quote_ident(revenue)}) * 100.0 / "
                f"NULLIF(MAX({quote_ident(target)}), 0), 1) AS attainment_pct",
            ]
            return _grouped(table, dim, selects, "4 ASC", limit, where_sql)

    days, rating = canon.get("Delivery Days"), canon.get("Rating")
    if _asks(q, _ASK_DELIVERY) and days:
        dim = natural("delivery")
        selects = [f"ROUND(AVG({quote_ident(days)}), 2) AS avg_delivery_days"]
        if rating:
            selects.append(f"ROUND(AVG({quote_ident(rating)}), 2) AS avg_rating")
        selects.append("COUNT(*) AS deliveries")
        if dim:
            return _grouped(table, dim, selects, "2 DESC", limit, where_sql)

    if _asks(q, _ASK_RATING) and rating:
        dim = natural("rating")
        selects = [
            f"ROUND(AVG({quote_ident(rating)}), 2) AS avg_rating",
            "COUNT(*) AS rated_orders",
        ]
        if dim:
            return _grouped(table, dim, selects, "2 ASC", limit, where_sql)

    stock = canon.get("Stock")
    if _asks(q, _ASK_STOCK) and stock:
        dim = natural("stock")
        selects = [
            f"ROUND(AVG({quote_ident(stock)}), 1) AS avg_stock",
            f"MIN({quote_ident(stock)}) AS lowest_stock",
        ]
        reorder = canon.get("Reorder Level")
        if reorder:
            selects.append(f"ROUND(AVG({quote_ident(reorder)}), 1) AS reorder_level")
        if dim:
            return _grouped(table, dim, selects, "2 ASC", limit, where_sql)

    # --- money, by segment or over time -----------------------------------
    profit = _profit_expr(canon)
    date_col = _first(canon, "Date", "Timestamp")

    if revenue and profit and _asks(q, _ASK_GROWTH) and date_col and not dimension:
        # "Is revenue growth leading to stronger profitability?" needs both
        # series side by side, period by period.
        period = f"SUBSTR({quote_ident(date_col)}, 1, 7) AS period"
        selects = [
            f"SUM({quote_ident(revenue)}) AS revenue",
            f"{profit} AS profit",
            f"ROUND(({profit}) * 100.0 / NULLIF(SUM({quote_ident(revenue)}), 0), 1) AS margin_pct",
        ]
        return (
            f"SELECT {period}, {', '.join(selects)} FROM {quote_ident(table)}{where_sql} "
            f"GROUP BY period ORDER BY period ASC LIMIT {max(limit, 24)}"
        )

    if revenue and dimension and (profit or _asks(q, _ASK_VALUE) or _asks(q, _ASK_PROFIT)):
        selects = [f"SUM({quote_ident(revenue)}) AS revenue"]
        if profit:
            selects.append(f"{profit} AS profit")
            selects.append(
                f"ROUND(({profit}) * 100.0 / "
                f"NULLIF(SUM({quote_ident(revenue)}), 0), 1) AS margin_pct"
            )
        return _grouped(table, dimension, selects, "2 DESC", limit, where_sql)

    return None


def heuristic_sql(source: DataSource, question: str) -> str | None:
    """Simple offline NL→SQL for demos when no API key is configured."""
    from app.services.schema_registry import parse_connection_config

    schema = get_source_schema(source)
    if not schema["tables"]:
        return None

    table = parse_connection_config(source).get("primary_table") or first_table_name(source)
    chosen = next((t for t in schema["tables"] if t["name"] == table), schema["tables"][0])
    table = chosen["name"]
    columns = [c["name"] for c in chosen["columns"]]
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

    where = _month_range_filter(q, schema)
    where_sql = f" WHERE {where}" if where else ""
    aggregating = any(k in q for k in ("how much", "total", "sum of", "sum ", "revenue in"))

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
            f"FROM {quote_ident(table)}{where_sql} "
            f"GROUP BY {quote_ident(group_col)} "
            f"ORDER BY 2 DESC LIMIT {limit}"
        )

    # "How much did we make between March and May" wants one number, not rows.
    if order_col and not group_col and (aggregating or where):
        alias = f"total_{order_col}"
        return (
            f"SELECT SUM({quote_ident(order_col)}) AS {quote_ident(alias)} "
            f"FROM {quote_ident(table)}{where_sql}"
        )

    if group_col and order_col and group_col != order_col:
        temporal = any(
            k in group_col.lower() for k in ("date", "day", "month", "time", "period", "year")
        )
        order_by = "1 ASC" if temporal else "2 DESC"
        return (
            f"SELECT {quote_ident(group_col)}, "
            f"SUM({quote_ident(order_col)}) AS {quote_ident(order_col)} "
            f"FROM {quote_ident(table)}{where_sql} "
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

    # Management questions ("which products have high return rates?") name a
    # metric and a dimension without saying "by". Try those before giving up.
    targeted = metric_sql(
        source, question, table, columns, limit=limit, where_sql=where_sql
    )
    if targeted:
        return targeted

    return f"SELECT * FROM {quote_ident(table)} LIMIT {limit}"


def heuristic_plan(source: DataSource, question: str) -> dict[str, Any]:
    """Offline SQL plus whether the planner actually understood the question.

    An untargeted row dump is not an answer, and summarising one as though it
    were is worse than saying nothing — the reader cannot tell the difference.
    """
    sql = heuristic_sql(source, question)
    if not sql:
        return {"sql": None, "targeted": False}
    untargeted = re.match(r"(?i)^\s*SELECT\s+\*\s+FROM\s+\S+\s+LIMIT\s+\d+\s*$", sql)
    return {"sql": sql, "targeted": not untargeted}


def schema_as_json(source: DataSource) -> dict:
    return json.loads(source.schema_json) if source.schema_json else {"tables": []}
