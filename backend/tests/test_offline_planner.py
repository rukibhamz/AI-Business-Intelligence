"""The offline planner: management questions without an AI key.

The case study's questions name a metric and a dimension without ever saying
"by" — "Which products have unusually high return rates?". Before this, they all
fell to `SELECT * LIMIT 10`, which was then summarised as though it answered.
"""

import json

import pytest

from app.models import DataSource
from app.services.schema_context import (
    build_measurement_rules,
    build_schema_prompt,
    canonical_columns,
    heuristic_plan,
    heuristic_sql,
)

COLUMNS = [
    "order_date", "store", "region", "product", "employee", "campaign",
    "marketing_spend", "units", "revenue", "cost", "returned",
    "delivery_partner", "delivery_days", "customer_rating", "customer_segment",
    "revenue_target", "stock_on_hand",
]

MAPPING = {
    "order_date": "Date", "store": "Store ID", "region": "Region",
    "product": "Product", "employee": "Employee", "campaign": "Campaign",
    "marketing_spend": "Marketing Spend", "units": "Quantity",
    "revenue": "Revenue", "cost": "Cost", "returned": "Returns",
    "delivery_partner": "Delivery Partner", "delivery_days": "Delivery Days",
    "customer_rating": "Rating", "customer_segment": "Customer Segment",
    "revenue_target": "Target", "stock_on_hand": "Stock",
}

SCHEMA = {
    "tables": [
        {
            "name": "sales",
            "columns": [{"name": c, "type": "string"} for c in COLUMNS],
        }
    ]
}


def source(*, mapped: bool = True) -> DataSource:
    config = {"primary_table": "sales"}
    if mapped:
        config["field_mapping"] = MAPPING
    return DataSource(
        id=1,
        name="NexaSphere Sales",
        source_type="file",
        schema_json=json.dumps(SCHEMA),
        connection_config=json.dumps(config),
    )


def plan(question: str, *, mapped: bool = True) -> str:
    sql = heuristic_sql(source(mapped=mapped), question)
    assert sql, f"no SQL for {question!r}"
    return sql


# --- the brief's nine questions ---------------------------------------------


def test_return_rate_question_computes_a_rate_per_product():
    sql = plan("Which products have unusually high return rates?")
    assert "GROUP BY `product`" in sql
    assert "SUM(`returned`) * 100.0 / NULLIF(SUM(`units`), 0)" in sql
    assert "ORDER BY 2 DESC" in sql  # worst offender first


def test_campaign_roi_question_counts_a_repeated_budget_once():
    """A campaign budget written on every row is one budget, not one per row."""
    sql = plan("Which marketing campaigns generate the best return on investment?")
    assert "GROUP BY `campaign`" in sql
    assert "SUM(DISTINCT `marketing_spend`)" in sql
    assert "SUM(`marketing_spend`)" not in sql.replace("SUM(DISTINCT `marketing_spend`)", "")


def test_best_and_top_no_longer_swallow_a_metric_question():
    """"best" used to trigger a raw row dump before the metric rules ran."""
    sql = plan("Which marketing campaigns generate the best return on investment?")
    assert not sql.startswith("SELECT * ")


def test_delivery_question_averages_days_and_rating_per_partner():
    sql = plan("Which delivery partners are associated with delays or poor customer ratings?")
    assert "GROUP BY `delivery_partner`" in sql
    assert "AVG(`delivery_days`)" in sql
    assert "AVG(`customer_rating`)" in sql


def test_segment_question_returns_revenue_profit_and_margin():
    sql = plan("Which customer segments are the most valuable?")
    assert "GROUP BY `customer_segment`" in sql
    assert "SUM(`revenue`)" in sql
    assert "SUM(`revenue`) - SUM(`cost`) AS profit" in sql
    assert "margin_pct" in sql


def test_employee_question_covers_profitability_not_just_revenue():
    sql = plan("Which employees perform well based on both revenue and profitability?")
    assert "GROUP BY `employee`" in sql
    assert "margin_pct" in sql


def test_target_question_compares_against_the_latest_period():
    """Six months of revenue against a one-period target reads as 700%."""
    sql = plan("Where is the business failing to meet its targets?")
    assert "GROUP BY `store`" in sql
    assert "attainment_pct" in sql
    assert "SUBSTR(`order_date`, 1, 7) = (SELECT MAX(SUBSTR(`order_date`, 1, 7))" in sql
    assert "ORDER BY 2 ASC" in sql  # furthest behind first


def test_stock_question_reports_lowest_cover_first():
    sql = plan("Which stores are experiencing stockouts or excess inventory?")
    assert "GROUP BY `store`" in sql
    assert "AVG(`stock_on_hand`)" in sql
    assert "MIN(`stock_on_hand`)" in sql
    assert "ORDER BY 2 ASC" in sql


def test_growth_question_puts_revenue_and_margin_side_by_side():
    sql = plan("Is revenue growth leading to stronger profitability?")
    assert "SUBSTR(`order_date`, 1, 7) AS period" in sql
    assert "SUM(`revenue`) AS revenue" in sql
    assert "margin_pct" in sql
    assert "ORDER BY period ASC" in sql


def test_revenue_and_profit_question_groups_by_the_named_dimension():
    sql = plan("Which products, stores or regions generate the most revenue and profit?")
    assert "GROUP BY `product`" in sql
    assert "AS profit" in sql


# --- robustness --------------------------------------------------------------


def test_planner_works_on_a_source_nobody_mapped():
    """Column names alone are enough to recognise the fields."""
    sql = plan("Which products have unusually high return rates?", mapped=False)
    assert "GROUP BY `product`" in sql
    assert "return_rate_pct" in sql


def test_dimension_can_be_named_in_the_plural_or_singular():
    for question in (
        "which store is behind on target",
        "which stores are behind on targets",
    ):
        assert "GROUP BY `store`" in plan(question)


@pytest.mark.parametrize(
    "question",
    [
        "revenue by region",
        "how much did we make in April",
        "count of records per store",
    ],
)
def test_existing_question_shapes_still_work(question):
    assert heuristic_sql(source(), question)


def test_an_ununderstood_question_is_reported_as_untargeted():
    """The rows are real, but they do not answer the question."""
    result = heuristic_plan(source(), "what is the meaning of all this")
    assert result["sql"].startswith("SELECT * ")
    assert result["targeted"] is False


def test_a_targeted_question_is_reported_as_targeted():
    result = heuristic_plan(source(), "Which products have unusually high return rates?")
    assert result["targeted"] is True


def test_canonical_columns_prefers_the_confirmed_mapping():
    assert canonical_columns(source(), COLUMNS)["Revenue"] == "revenue"
    assert canonical_columns(source(mapped=False), COLUMNS)["Revenue"] == "revenue"


# --- measurement rules handed to the LLM ------------------------------------
#
# Tested against a live provider, the model summed a campaign budget repeated on
# every row (1.1x return where the true figure is 152x), divided returned units
# by the row count, and stacked six months of revenue against a one-period
# target. None of that is visible in a schema listing.


def test_measurement_rules_stop_a_repeated_budget_being_summed():
    rules = build_measurement_rules(source(), COLUMNS)
    assert "SUM(DISTINCT marketing_spend)" in rules
    assert "MAX(marketing_spend)" in rules


def test_measurement_rules_pin_the_return_rate_denominator():
    rules = build_measurement_rules(source(), COLUMNS)
    assert "SUM(returned) / SUM(units)" in rules
    assert "COUNT(*)" in rules  # named as the wrong denominator


def test_measurement_rules_scope_a_target_to_one_period():
    rules = build_measurement_rules(source(), COLUMNS)
    assert "MAX(revenue_target)" in rules
    assert "never SUM(revenue_target)" in rules
    assert "ONE period" in rules


def test_measurement_rules_derive_profit_when_there_is_no_profit_column():
    rules = build_measurement_rules(source(), COLUMNS)
    assert "SUM(revenue) - SUM(cost)" in rules


def test_measurement_rules_only_mention_columns_that_exist():
    lean = ["order_date", "region", "revenue"]
    rules = build_measurement_rules(source(mapped=False), lean)
    assert "marketing_spend" not in rules
    assert "returned" not in rules
    assert "growth or a trend" in rules  # the date rule still applies


def test_measurement_rules_ride_along_with_the_schema_prompt():
    prompt = build_schema_prompt(source())
    assert "Measurement rules for this dataset" in prompt
    assert "SUM(DISTINCT marketing_spend)" in prompt


def test_measurement_rules_define_a_stockout_precisely():
    """A level that never reaches zero is thin cover, not a stockout."""
    rules = build_measurement_rules(source(), COLUMNS)
    assert "stockout is a level zero and nothing else" in rules
    assert "thin cover, not a stockout" in rules
    assert "AVG(stock_on_hand)" in rules and "MIN(stock_on_hand)" in rules


def test_stockout_definition_uses_the_reorder_level_when_there_is_one():
    columns = [*COLUMNS, "reorder_point"]
    mapped = source()
    config = json.loads(mapped.connection_config)
    config["field_mapping"] = {**MAPPING, "reorder_point": "Reorder Level"}
    mapped.connection_config = json.dumps(config)
    rules = build_measurement_rules(mapped, columns)
    assert "at or below `reorder_point`" in rules
