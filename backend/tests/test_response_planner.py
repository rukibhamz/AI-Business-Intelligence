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
        ("what products do we sell", ["product"], [{"product": f"P{i}"} for i in range(5)], "narrative"),
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


def test_a_single_record_is_prose_not_a_grid():
    plan = plan_response("what is the biggest order", WIDE_COLS, WIDE_ROWS[:1])
    assert plan["format"] == "narrative"
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


# --- rates are not totals ----------------------------------------------------


def test_a_rate_column_is_described_as_a_range_not_a_total():
    """"Total return rate is 21%" is not a figure — it is three rates added up."""
    columns = ["product", "return_rate_pct"]
    rows = [
        {"product": "Power Bank", "return_rate_pct": 14.5},
        {"product": "Blender", "return_rate_pct": 4.0},
        {"product": "Laptop", "return_rate_pct": 0.5},
    ]
    plan = plan_response("which products have high return rates", columns, rows)
    text = describe_result("which products have high return rates", columns, rows, plan)
    assert "Total" not in text
    assert "runs from" in text
    assert "Power Bank is highest at 14.50" in text


def test_a_measure_column_still_reports_a_total():
    columns = ["region", "revenue"]
    rows = [{"region": "North", "revenue": 100.0}, {"region": "South", "revenue": 300.0}]
    plan = plan_response("revenue by region", columns, rows)
    text = describe_result("revenue by region", columns, rows, plan)
    assert "Total revenue is 400" in text


def test_a_companion_rate_answers_the_second_half_of_the_question():
    """"Most revenue and profit" is two questions; the rate is the other half."""
    columns = ["product", "revenue", "margin_pct"]
    rows = [
        {"product": "Volume", "revenue": 10000.0, "margin_pct": 8.0},
        {"product": "Earner", "revenue": 4000.0, "margin_pct": 75.0},
    ]
    plan = plan_response("which products make the most revenue and profit", columns, rows)
    text = describe_result(
        "which products make the most revenue and profit", columns, rows, plan
    )
    assert "Volume is highest at 10,000" in text
    assert "Earner leads at 75" in text


def test_a_rate_and_a_count_do_not_share_a_chart_axis():
    """14.5% plotted beside 620 units makes the rate invisible."""
    columns = ["product", "return_rate_pct", "units"]
    rows = [
        {"product": "Power Bank", "return_rate_pct": 14.5, "units": 620},
        {"product": "Blender", "return_rate_pct": 4.0, "units": 300},
    ]
    plan = plan_response("which products have high return rates", columns, rows)
    assert plan["chart"]["value_keys"] == ["return_rate_pct"]


def test_measures_of_the_same_family_still_plot_together():
    columns = ["product", "revenue", "profit", "margin_pct"]
    rows = [
        {"product": "A", "revenue": 100.0, "profit": 30.0, "margin_pct": 30.0},
        {"product": "B", "revenue": 50.0, "profit": 10.0, "margin_pct": 20.0},
    ]
    plan = plan_response("revenue and profit by product", columns, rows)
    assert plan["chart"]["value_keys"] == ["revenue", "profit"]


def test_rates_are_never_drawn_as_a_pie():
    """Return rates are not slices of anything — they do not sum to 100%."""
    columns = ["product", "return_rate_pct"]
    rows = [
        {"product": "Power Bank", "return_rate_pct": 14.5},
        {"product": "Blender", "return_rate_pct": 4.0},
        {"product": "Laptop", "return_rate_pct": 0.5},
    ]
    plan = plan_response("which products have high return rates", columns, rows)
    assert plan["chart"]["type"] == "bar"


def test_an_average_shares_an_axis_with_the_quantity_it_averages():
    """avg stock and lowest stock are both stock — one chart, two series."""
    columns = ["store", "avg_stock", "lowest_stock"]
    rows = [
        {"store": "Kano", "avg_stock": 132.8, "lowest_stock": 48},
        {"store": "PH", "avg_stock": 6.1, "lowest_stock": 2},
    ]
    plan = plan_response("which stores are low on stock", columns, rows)
    assert plan["chart"]["value_keys"] == ["avg_stock", "lowest_stock"]


def test_a_rating_does_not_share_an_axis_with_delivery_days():
    columns = ["partner", "avg_delivery_days", "avg_rating"]
    rows = [
        {"partner": "RapidHaul", "avg_delivery_days": 7.6, "avg_rating": 2.5},
        {"partner": "SwiftLogix", "avg_delivery_days": 1.7, "avg_rating": 4.5},
    ]
    plan = plan_response("which partners are slow", columns, rows)
    assert plan["chart"]["value_keys"] == ["avg_delivery_days"]


def test_hyphenated_labels_are_not_mistaken_for_dates():
    """"Abuja-Central" is a store. It drew a trend line across four shops."""
    columns = ["store", "avg_stock"]
    rows = [
        {"store": "Abuja-Central", "avg_stock": 74.0},
        {"store": "Kano-Main", "avg_stock": 132.8},
        {"store": "PH-Trans", "avg_stock": 6.1},
    ]
    plan = plan_response("which stores are low on stock", columns, rows)
    assert plan["chart"]["type"] != "line"


def test_real_period_labels_still_draw_a_line():
    columns = ["period", "revenue"]
    rows = [
        {"period": "2026-04", "revenue": 100.0},
        {"period": "2026-05", "revenue": 120.0},
        {"period": "2026-06", "revenue": 90.0},
    ]
    plan = plan_response("revenue over time", columns, rows)
    assert plan["chart"]["type"] == "line"


def test_month_name_labels_still_draw_a_line():
    columns = ["month", "revenue"]
    rows = [
        {"month": "Apr 2026", "revenue": 100.0},
        {"month": "May 2026", "revenue": 120.0},
        {"month": "Jun 2026", "revenue": 90.0},
    ]
    plan = plan_response("revenue trend", columns, rows)
    assert plan["chart"]["type"] == "line"


def test_month_on_month_by_product_uses_bars():
    columns = ["month", "revenue"]
    rows = [
        {"month": "2026-04", "revenue": 100.0},
        {"month": "2026-05", "revenue": 120.0},
        {"month": "2026-06", "revenue": 90.0},
    ]
    plan = plan_response(
        "month on month comparison for each product sold",
        columns,
        rows,
    )
    assert plan["format"] == "chart"
    assert plan["chart"]["type"] == "bar"


def test_explicit_bar_chart_request_forces_bars():
    columns = ["month", "revenue"]
    rows = [
        {"month": "2026-04", "revenue": 100.0},
        {"month": "2026-05", "revenue": 120.0},
        {"month": "2026-06", "revenue": 90.0},
    ]
    plan = plan_response(
        "month on month comparison for each product sold as a bar chart",
        columns,
        rows,
    )
    assert plan["chart"]["type"] == "bar"


def test_bar_chart_followup_rewrites_to_prior_question():
    from app.services.response_planner import expand_question_with_context

    resolved = expand_question_with_context(
        "as a bar chart",
        "month on month comparison for each product sold",
    )
    assert "month on month" in resolved.lower()
    assert "bar chart" in resolved.lower()
