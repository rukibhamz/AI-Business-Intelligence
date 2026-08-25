"""Date-range questions.

Regression: "how much did we make between march and may?" produced SQL with an
invented year (2023) against 2026 data, matched nothing, and reported a NULL
aggregate as "one matching record".
"""

import json

import pytest

from app.models import DataSource
from app.services.profiling import describe_profile, profile_rows, schema_date_range
from app.services.response_planner import describe_result, is_blank_result, plan_response
from app.services.schema_context import build_schema_prompt, heuristic_sql

ROWS = [
    {"order_date": "2026-03-04", "region": "North", "revenue": "1200.50"},
    {"order_date": "2026-04-02", "region": "North", "revenue": "1500"},
    {"order_date": "2026-05-09", "region": "South", "revenue": "830"},
    {"order_date": "2026-08-19", "region": "West", "revenue": "640"},
]
COLUMNS = ["order_date", "region", "revenue"]


def build_source(with_profiles: bool = True) -> DataSource:
    columns = [
        {"name": "order_date", "type": "string"},
        {"name": "region", "type": "string"},
        {"name": "revenue", "type": "number"},
    ]
    if with_profiles:
        profiles = profile_rows(COLUMNS, ROWS)
        for column in columns:
            column["profile"] = profiles[column["name"]]
    return DataSource(
        id=1,
        name="Regional Sales",
        source_type="file",
        schema_json=json.dumps({"tables": [{"name": "sample", "columns": columns}]}),
        connection_config="{}",
    )


# --- profiling --------------------------------------------------------------


def test_date_column_is_profiled_with_its_real_range():
    profile = profile_rows(COLUMNS, ROWS)["order_date"]
    assert profile["kind"] == "date"
    assert profile["min"] == "2026-03-04"
    assert profile["max"] == "2026-08-19"


def test_low_cardinality_text_is_profiled_as_a_category():
    profile = profile_rows(COLUMNS, ROWS)["region"]
    assert profile["kind"] == "category"
    assert profile["values"] == ["North", "South", "West"]


def test_numeric_column_is_profiled_with_bounds():
    profile = profile_rows(COLUMNS, ROWS)["revenue"]
    assert profile["kind"] == "number"
    assert profile["min"] == "640"
    assert profile["max"] == "1500"  # whole numbers are not padded with .00


def test_profile_renders_a_hint_for_the_prompt():
    hint = describe_profile(profile_rows(COLUMNS, ROWS)["order_date"])
    assert "2026-03-04" in hint and "2026-08-19" in hint


# --- the prompt the planner actually sees -----------------------------------


def test_prompt_tells_the_model_the_real_date_span():
    prompt = build_schema_prompt(build_source())
    # Without this the model guesses a year and matches nothing.
    assert "2026-03-04" in prompt
    assert "2026-08-19" in prompt
    assert "covers" in prompt.lower()


def test_prompt_lists_category_values():
    assert "North" in build_schema_prompt(build_source())


def test_prompt_still_works_without_profiles():
    prompt = build_schema_prompt(build_source(with_profiles=False))
    assert "order_date" in prompt


def test_schema_date_range_reports_the_span():
    schema = json.loads(build_source().schema_json)
    assert schema_date_range(schema) == ("2026-03-04", "2026-08-19")


# --- offline fallback -------------------------------------------------------


def test_fallback_filters_a_month_range_using_the_data_year():
    sql = heuristic_sql(build_source(), "how much did we make between march and may?")
    assert "SUM(`revenue`)" in sql
    assert "2026-03-01" in sql
    assert "2026-06-01" in sql  # half-open, so May is included


def test_fallback_handles_a_single_month():
    sql = heuristic_sql(build_source(), "total revenue in April")
    assert "2026-04-01" in sql and "2026-05-01" in sql


def test_fallback_combines_a_date_range_with_a_group_by():
    sql = heuristic_sql(build_source(), "revenue between march and may by region")
    assert "GROUP BY `region`" in sql
    assert "2026-03-01" in sql


def test_fallback_never_invents_a_year_without_profiles():
    """No profile means no known year, so no date filter is fabricated."""
    sql = heuristic_sql(build_source(with_profiles=False), "revenue between march and may")
    assert "2026" not in sql and "2023" not in sql


# --- empty results ----------------------------------------------------------


@pytest.mark.parametrize(
    "columns,rows",
    [
        ([], []),
        (["total_revenue"], []),
        (["total_revenue"], [{"total_revenue": None}]),  # SUM() over zero rows
        (["a", "b"], [{"a": None, "b": ""}]),
    ],
)
def test_no_match_is_reported_as_empty(columns, rows):
    assert is_blank_result(columns, rows)
    assert plan_response("how much did we make in 2019", columns, rows)["format"] == "empty"


def test_empty_answer_names_the_range_that_exists():
    plan = plan_response("how much did we make in 2019", ["total_revenue"], [{"total_revenue": None}])
    text = describe_result(
        "how much did we make in 2019",
        ["total_revenue"],
        [{"total_revenue": None}],
        plan,
        source_name="Regional Sales",
        coverage="Regional Sales covers 2026-03-04 to 2026-08-19.",
    )
    assert "no figure to report" in text
    assert "2026-03-04" in text
    # The old bug rendered the NULL as if it were a real record.
    assert "None" not in text


def test_a_real_aggregate_is_still_a_metric():
    plan = plan_response("how much did we make", ["total_revenue"], [{"total_revenue": 6555.75}])
    assert plan["format"] == "metric"
