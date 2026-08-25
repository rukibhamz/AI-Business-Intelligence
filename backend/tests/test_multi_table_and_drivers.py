"""Multi-table sources, change attribution, and the currency setting."""

import json

import pytest

from app.models import DataSource
from app.services.analytics import (
    Dataset,
    build_findings,
    build_time_index,
    explain_change,
)
from app.services.app_settings import CURRENCIES, DEFAULT_CURRENCY, _valid_currency
from app.services.field_mapping import columns_from_schema
from app.services.profiling import attach_profiles
from app.services.schema_context import pick_primary_table, score_table, table_names

# A database connection typically exposes housekeeping tables alongside the
# one that actually holds the business facts.
SCHEMA = {
    "tables": [
        {
            "name": "audit_log",
            "columns": [
                {"name": "id", "type": "integer"},
                {"name": "actor", "type": "string"},
                {"name": "action", "type": "string"},
            ],
        },
        {
            "name": "sales",
            "columns": [
                {"name": "order_date", "type": "string"},
                {"name": "store", "type": "string"},
                {"name": "product", "type": "string"},
                {"name": "revenue", "type": "number"},
                {"name": "cost", "type": "number"},
                {"name": "units", "type": "integer"},
            ],
        },
        {
            "name": "settings",
            "columns": [{"name": "id", "type": "integer"}, {"name": "value", "type": "string"}],
        },
    ]
}


def source(schema=None) -> DataSource:
    return DataSource(
        id=1,
        name="Warehouse",
        source_type="mysql",
        schema_json=json.dumps(schema or SCHEMA),
        connection_config="{}",
    )


# --- multi-table ------------------------------------------------------------


def test_every_table_is_visible():
    assert table_names(source()) == ["audit_log", "sales", "settings"]


def test_the_business_table_is_chosen_not_the_first_one():
    """Analytics used to read tables[0] — here that is the audit log."""
    assert pick_primary_table(source()) == "sales"


def test_a_table_with_measures_and_a_date_outscores_a_housekeeping_table():
    tables = {t["name"]: t for t in SCHEMA["tables"]}
    assert score_table(tables["sales"]) > score_table(tables["audit_log"])
    assert score_table(tables["sales"]) > score_table(tables["settings"])


def test_columns_are_read_from_the_named_table():
    schema_json = json.dumps(SCHEMA)
    assert "revenue" in columns_from_schema(schema_json, "sales")
    assert "actor" in columns_from_schema(schema_json, "audit_log")


def test_columns_fall_back_to_the_first_table_when_unknown():
    assert columns_from_schema(json.dumps(SCHEMA), "nope") == ["id", "actor", "action"]


def test_profiles_attach_to_the_named_table():
    schema = json.loads(json.dumps(SCHEMA))
    attach_profiles(schema, {"revenue": {"kind": "number", "min": "1", "max": "9"}}, "sales")
    sales = next(t for t in schema["tables"] if t["name"] == "sales")
    audit = next(t for t in schema["tables"] if t["name"] == "audit_log")
    assert any(c.get("profile") for c in sales["columns"])
    assert not any(c.get("profile") for c in audit["columns"])


def test_single_table_sources_are_unaffected():
    one = {"tables": [{"name": "only", "columns": [{"name": "revenue", "type": "number"}]}]}
    assert pick_primary_table(source(one)) == "only"


def test_a_source_with_no_schema_has_no_primary_table():
    assert pick_primary_table(source({"tables": []})) is None


# --- change attribution -----------------------------------------------------

COLUMNS = ["order_date", "region", "product", "revenue", "cost"]
MAPPING = {
    "order_date": "Date",
    "region": "Region",
    "product": "Product",
    "revenue": "Revenue",
    "cost": "Cost",
}


def build_dataset(rows):
    return Dataset(
        source=DataSource(id=1, name="Sales", source_type="file"),
        columns=COLUMNS,
        rows=rows,
        total=len(rows),
        truncated=False,
        mapping=MAPPING,
    )


def steady_then_collapse():
    rows = []
    for month in ["01", "02", "03", "04", "05"]:
        for region, revenue in [("West", 4000), ("North", 3000), ("South", 2000)]:
            rows.append(
                {
                    "order_date": f"2026-{month}-10",
                    "region": region,
                    "product": "TV",
                    "revenue": revenue,
                    "cost": revenue * 0.6,
                }
            )
    for region, revenue in [("West", 200), ("North", 3000), ("South", 2000)]:
        rows.append(
            {
                "order_date": "2026-06-10",
                "region": region,
                "product": "TV",
                "revenue": revenue,
                "cost": revenue * 0.6,
            }
        )
    return rows


def test_a_change_is_attributed_to_the_segment_that_caused_it():
    dataset = build_dataset(steady_then_collapse())
    index = build_time_index(dataset, "order_date")
    explanation = explain_change(dataset, index, "revenue")
    assert explanation is not None
    assert "West" in explanation
    assert "region" in explanation.lower()


def test_the_trend_finding_carries_the_driver():
    findings = build_findings(build_dataset(steady_then_collapse()))
    trend = next(f for f in findings if f["id"].endswith("-trend"))
    assert "West" in trend["body"], trend["body"]


def test_no_driver_is_claimed_when_the_move_is_spread_evenly():
    """Attributing an even decline to one segment would be misleading."""
    rows = []
    for month in ["01", "02", "03", "04", "05", "06"]:
        drop = 0.5 if month == "06" else 1.0
        for region in ["West", "North", "South"]:
            rows.append(
                {
                    "order_date": f"2026-{month}-10",
                    "region": region,
                    "product": "TV",
                    "revenue": 3000 * drop,
                    "cost": 1800 * drop,
                }
            )
    dataset = build_dataset(rows)
    index = build_time_index(dataset, "order_date")
    explanation = explain_change(dataset, index, "revenue", dimensions=("Region",))
    # Three equal contributors: no single one explains 40%+ of the move.
    assert explanation is None or "West" not in explanation or "," in explanation


# --- currency ---------------------------------------------------------------


def test_the_default_currency_is_naira():
    assert DEFAULT_CURRENCY == "NGN"
    assert CURRENCIES["NGN"]["symbol"] == "₦"


@pytest.mark.parametrize("value", [None, "", "zzz", "dollars", 123])
def test_an_unknown_currency_falls_back_to_the_default(value):
    assert _valid_currency(value) == "NGN"


@pytest.mark.parametrize("code", ["USD", "usd", " gbp ", "KES"])
def test_supported_currencies_are_accepted_case_insensitively(code):
    assert _valid_currency(code) == code.strip().upper()


def test_every_currency_has_a_label_and_symbol():
    for code, meta in CURRENCIES.items():
        assert len(code) == 3
        assert meta["label"] and meta["symbol"]
