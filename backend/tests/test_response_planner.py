"""The presentation guardrail: chart vs prose vs table vs a bare number."""

import pytest

from app.services.chart_recommend import recommend_chart
from app.services.response_planner import describe_result, plan_response

SERIES_COLS = ["order_date", "revenue"]
SERIES_ROWS = [{"order_date": f"2026-0{i}-01", "revenue": 1000 + i * 250} for i in range(1, 7)]

REGION_COLS = ["region", "revenue"]
REGION_ROWS = [
    {"region": "North", "revenue": 6670},
    {"region": "West", "revenue": 4650},
    {"region": "South", "revenue": 2605},
    {"region": "East", "revenue": 798},
]

WIDE_COLS = ["order_date", "region", "product", "category", "revenue", "cost", "quantity"]
WIDE_ROWS = [
    {c: (100 if c in ("revenue", "cost", "quantity") else f"v{i}") for c in WIDE_COLS}
    for i in range(10)
]


@pytest.mark.parametrize(
    "question,columns,rows,expected",
    [
        ("How many records do we have?", ["row_count"], [{"row_count": 12}], "metric"),
        ("Show revenue by region", REGION_COLS, REGION_ROWS, "chart"),
        ("revenue trend over time", SERIES_COLS, SERIES_ROWS, "chart"),
        ("Why did revenue drop last month?", SERIES_COLS, SERIES_ROWS, "narrative"),
        ("Explain our regional performance", REGION_COLS, REGION_ROWS, "narrative"),
        ("list all orders", WIDE_COLS, WIDE_ROWS, "table"),
        ("show me the raw rows", WIDE_COLS, WIDE_ROWS, "table"),
        ("what products do we sell", ["product"], [{"product": f"P{i}"} for i in range(5)], "table"),
        ("anything at all", [], [], "empty"),
    ],
)
def test_format_matches_the_question(question, columns, rows, expected):
    assert plan_response(question, columns, rows)["format"] == expected


def test_a_count_question_never_gets_a_chart():
    plan = plan_response("how many orders", ["row_count"], [{"row_count": 42}])
    assert plan["format"] == "metric"
    assert plan["chart"] is None


def test_a_table_answer_never_gets_a_chart():
    plan = plan_response("list all orders", WIDE_COLS, WIDE_ROWS)
    assert plan["chart"] is None


def test_a_single_record_is_a_table_not_a_chart():
    plan = plan_response("details for the biggest order", WIDE_COLS, WIDE_ROWS[:1])
    assert plan["format"] == "table"
    assert plan["chart"] is None


def test_dates_are_never_a_pie_chart():
    # A pie implies parts of a whole; periods are not parts.
    assert recommend_chart(SERIES_COLS, SERIES_ROWS)["type"] == "line"


def test_few_categories_use_a_pie():
    assert recommend_chart(REGION_COLS, REGION_ROWS)["type"] == "pie"


def test_narrative_is_grounded_in_the_returned_rows():
    plan = plan_response("Explain our regional performance", REGION_COLS, REGION_ROWS)
    text = describe_result(
        "Explain our regional performance", REGION_COLS, REGION_ROWS, plan, source_name="Sales"
    )
    # Every figure quoted must be derivable from the rows above.
    assert "North" in text  # the actual leader
    assert "14,723" in text  # the actual total
    assert "East" in text  # the actual laggard


def test_empty_result_says_so_plainly():
    plan = plan_response("revenue by region", [], [])
    text = describe_result("revenue by region", [], [], plan)
    assert "nothing" in text.lower()
    assert "no figure to report" in text.lower()
