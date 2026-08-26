"""Coverage of the AI BuildFest case study questions.

Two classes of regression are guarded here:

1. **Field collisions.** Two columns claiming one canonical field made metrics
   read the wrong column — marketing spend became cost of goods and doubled the
   reported margin.
2. **Grain.** A campaign budget is written on every row of its campaign, so
   summing rows multiplies it by the row count and crushes ROI.
"""

import pytest

from app.models import DataSource
from app.services.analytics import (
    Dataset,
    aggregate_by_grain,
    average_by,
    build_findings,
    build_overview,
    is_repeated_per_group,
    overall_return_rate,
    profit_by,
    ratio_by,
    return_rate_by,
    returns_basis,
    to_flag,
    total_by_grain,
)
from app.services.field_mapping import (
    CANONICAL_FIELDS,
    resolve_conflicts,
    suggest_canonical,
)

COLUMNS = [
    "order_date", "store", "region", "channel", "product", "category",
    "employee", "campaign", "marketing_spend", "units", "unit_price",
    "revenue", "cost", "returned", "delivery_partner", "delivery_days",
    "customer_rating", "customer_segment", "revenue_target",
]

MAPPING = {
    "order_date": "Date", "store": "Store ID", "region": "Region",
    "channel": "Channel", "product": "Product", "category": "Category",
    "employee": "Employee", "campaign": "Campaign",
    "marketing_spend": "Marketing Spend", "units": "Quantity",
    "unit_price": "Price", "revenue": "Revenue", "cost": "Cost",
    "returned": "Returns", "delivery_partner": "Delivery Partner",
    "delivery_days": "Delivery Days", "customer_rating": "Rating",
    "customer_segment": "Customer Segment", "revenue_target": "Target",
}


def row(date, store, product, campaign, spend, units, revenue, cost, returned,
        partner="SwiftLogix", days=2, rating=4.5, target=5000):
    return {
        "order_date": date, "store": store, "region": "West", "channel": "Store",
        "product": product, "category": "Appliances", "employee": "Adaobi",
        "campaign": campaign, "marketing_spend": spend, "units": units,
        "unit_price": 100, "revenue": revenue, "cost": cost, "returned": returned,
        "delivery_partner": partner, "delivery_days": days,
        "customer_rating": rating, "customer_segment": "Retail",
        "revenue_target": target,
    }


ROWS = [
    row("2026-01-12", "Ikeja", "TV", "Blitz", 1200, 14, 5880, 3900, 0),
    row("2026-01-26", "Lekki", "Fryer", "Blitz", 1200, 31, 2945, 1980, 3),
    row("2026-02-09", "Ikeja", "TV", "Push", 800, 11, 4620, 3080, 1),
    row("2026-02-23", "Kano", "Washer", "Push", 800, 7, 4270, 3010, 0),
]


def make_dataset(rows=None, mapping=None, columns=None) -> Dataset:
    return Dataset(
        source=DataSource(id=1, name="NexaSphere", source_type="file"),
        columns=columns or COLUMNS,
        rows=rows if rows is not None else ROWS,
        total=len(rows if rows is not None else ROWS),
        truncated=False,
        mapping=mapping or MAPPING,
    )


# --- vocabulary -------------------------------------------------------------


@pytest.mark.parametrize(
    "column,expected",
    [
        ("marketing_spend", "Marketing Spend"),
        ("ad_spend", "Marketing Spend"),
        ("cost", "Cost"),
        ("cogs", "Cost"),
        ("returned", "Returns"),
        ("refund_count", "Returns"),
        ("employee", "Employee"),
        ("sales_rep", "Employee"),
        ("campaign", "Campaign"),
        ("delivery_partner", "Delivery Partner"),
        ("courier", "Delivery Partner"),
        ("delivery_days", "Delivery Days"),
        ("customer_rating", "Rating"),
        ("csat_score", "Rating"),
        ("revenue_target", "Target"),
        ("sales_quota", "Target"),
        ("customer_segment", "Customer Segment"),
        ("channel", "Channel"),
        ("stock_on_hand", "Stock"),
        ("reorder_level", "Reorder Level"),
    ],
)
def test_case_study_concepts_have_canonical_fields(column, expected):
    assert expected in CANONICAL_FIELDS
    assert suggest_canonical(column) == expected


def test_marketing_spend_is_not_swallowed_by_cost():
    """The regression: it used to fall through to the generic cost keyword."""
    assert suggest_canonical("marketing_spend") != "Cost"


# --- collision resolution ---------------------------------------------------


def test_two_columns_cannot_claim_the_same_measure():
    mapping, conflicts = resolve_conflicts({"cost": "Cost", "marketing_spend": "Cost"})
    assert list(mapping.values()).count("Cost") == 1
    assert conflicts and "Cost" in conflicts[0]


def test_the_better_named_column_wins_the_field():
    mapping, _ = resolve_conflicts({"marketing_spend": "Cost", "cost": "Cost"})
    assert mapping["cost"] == "Cost"
    assert mapping["marketing_spend"] == "Unmapped"


def test_losers_are_unmapped_not_deleted():
    mapping, _ = resolve_conflicts({"units": "Quantity", "returned": "Quantity"})
    assert set(mapping) == {"units", "returned"}
    assert "Unmapped" in mapping.values()


def test_unmapped_and_ignore_may_repeat():
    mapping, conflicts = resolve_conflicts({"a": "Ignore", "b": "Ignore", "c": "Unmapped"})
    assert mapping == {"a": "Ignore", "b": "Ignore", "c": "Unmapped"}
    assert conflicts == []


def test_a_clean_mapping_reports_no_conflict():
    _, conflicts = resolve_conflicts(MAPPING)
    assert conflicts == []


# --- grain ------------------------------------------------------------------


def test_a_budget_repeated_per_campaign_is_detected():
    assert is_repeated_per_group(make_dataset(), "marketing_spend", "campaign")


def test_a_genuine_per_row_measure_is_not_treated_as_repeated():
    assert not is_repeated_per_group(make_dataset(), "revenue", "campaign")


def test_repeated_values_are_counted_once_per_group():
    dataset = make_dataset()
    # Two campaigns at 1200 and 800; naive SUM over 4 rows gives 4000.
    assert total_by_grain(dataset, "marketing_spend", "campaign") == 2000
    assert dataset.sum_of("marketing_spend") == 4000


def test_grain_aware_aggregate_matches_the_stated_budget():
    result = {r["label"]: r["value"] for r in aggregate_by_grain(make_dataset(), "campaign", "marketing_spend")}
    assert result == {"Blitz": 1200, "Push": 800}


# --- derived metrics --------------------------------------------------------


def test_return_rate_per_product():
    rates = {r["label"]: r["value"] for r in ratio_by(make_dataset(), "product", "returned", "units", min_denominator=1)}
    assert rates["Fryer"] == pytest.approx(3 / 31 * 100, abs=0.01)
    assert rates["TV"] == pytest.approx(1 / 25 * 100, abs=0.01)


def test_average_by_computes_a_mean_not_a_sum():
    rows = [
        row("2026-01-01", "A", "P", "C", 100, 1, 10, 5, 0, partner="Slow", days=10, rating=2.0),
        row("2026-01-02", "A", "P", "C", 100, 1, 10, 5, 0, partner="Slow", days=6, rating=3.0),
    ]
    result = average_by(make_dataset(rows), "delivery_partner", "delivery_days")
    assert result[0]["value"] == 8.0


# --- the bug that started this ----------------------------------------------


def test_margin_uses_cost_of_goods_not_marketing_spend():
    """Marketing spend once landed on Cost, reporting double the real margin."""
    overview = build_overview(make_dataset())
    kpis = {k["label"]: k["value"] for k in overview["kpis"]}

    revenue = sum(float(r["revenue"]) for r in ROWS)
    cogs = sum(float(r["cost"]) for r in ROWS)
    assert kpis["Total Cost"] == pytest.approx(cogs)
    assert kpis["Total Profit"] == pytest.approx(revenue - cogs)
    assert kpis["Profit Margin"] == pytest.approx((revenue - cogs) / revenue * 100, abs=0.01)
    # The marketing budget must not be mistaken for cost of goods.
    assert kpis["Total Cost"] != sum(float(r["marketing_spend"]) for r in ROWS)


def test_operational_kpis_are_produced():
    kpis = {k["label"] for k in build_overview(make_dataset())["kpis"]}
    assert {"Return Rate", "Marketing ROI", "Avg Rating", "Avg Delivery Days"} <= kpis


def test_marketing_roi_uses_the_stated_budget():
    kpis = {k["label"]: k["value"] for k in build_overview(make_dataset())["kpis"]}
    revenue = sum(float(r["revenue"]) for r in ROWS)
    expected = (revenue - 2000) / 2000  # 2000 = 1200 + 800, counted once each
    assert kpis["Marketing ROI"] == pytest.approx(round(expected, 2), abs=0.01)


# --- new findings fire on data built to trigger them ------------------------


def test_growth_with_falling_margin_is_flagged():
    """The case study's headline scenario."""
    rows = []
    for i, month in enumerate(["01", "02", "03", "04", "05", "06"], start=1):
        # Revenue climbs while cost climbs faster.
        revenue, cost = 1000 + i * 200, 500 + i * 220
        rows.append(row(f"2026-{month}-10", "A", "P", "C", 100, 10, revenue, cost, 0))
    findings = build_findings(make_dataset(rows))
    assert any(f["id"].endswith("-divergence") for f in findings), [f["title"] for f in findings]


def test_a_product_returned_far_more_than_the_rest_is_flagged():
    rows = [
        row("2026-01-10", "A", "Good", "C", 100, 100, 1000, 500, 1),
        row("2026-02-10", "A", "Good", "C", 100, 100, 1000, 500, 1),
        row("2026-03-10", "A", "Faulty", "C", 100, 100, 1000, 500, 40),
    ]
    findings = build_findings(make_dataset(rows))
    returns = [f for f in findings if f["id"].endswith("-returns")]
    assert returns and "Faulty" in returns[0]["title"]


def test_a_loss_making_campaign_is_flagged():
    rows = [
        row("2026-01-10", "A", "P", "Good Campaign", 100, 10, 5000, 2000, 0),
        row("2026-02-10", "A", "P", "Bad Campaign", 9000, 10, 1000, 400, 0),
    ]
    findings = build_findings(make_dataset(rows))
    roi = [f for f in findings if f["id"].endswith("-campaign-roi")]
    assert roi and "Bad Campaign" in roi[0]["title"]


def test_a_slow_delivery_partner_is_flagged():
    rows = [
        row("2026-01-10", "A", "P", "C", 100, 10, 100, 50, 0, partner="Fast", days=2, rating=4.8),
        row("2026-02-10", "A", "P", "C", 100, 10, 100, 50, 0, partner="Fast", days=2, rating=4.7),
        row("2026-03-10", "A", "P", "C", 100, 10, 100, 50, 0, partner="Slow", days=12, rating=1.9),
    ]
    findings = build_findings(make_dataset(rows))
    delivery = [f for f in findings if f["id"].endswith("-delivery")]
    assert delivery and "Slow" in delivery[0]["title"]


def test_a_store_behind_target_is_flagged():
    rows = [
        row("2026-01-10", "Winner", "P", "C", 100, 10, 9000, 4000, 0, target=5000),
        row("2026-02-10", "Laggard", "P", "C", 100, 10, 1000, 400, 0, target=8000),
    ]
    findings = build_findings(make_dataset(rows))
    target = [f for f in findings if f["id"].endswith("-target")]
    assert target and "Laggard" in target[0]["title"]


def test_new_dimensions_are_available_for_comparison():
    overview = build_overview(make_dataset())
    titles = " ".join(c["title"] for c in overview["charts"])
    # Employees and campaigns were previously invisible to the dashboard.
    assert "Employee" in titles or "Campaign" in titles


# --- the six comparisons the brief names ------------------------------------


def test_named_dimensions_are_charted_before_broader_ones():
    """Category is not one of the six the case study names; Customer Segment is.

    A fixed chart cap filled in field order let Category take the last slot and
    drop Customer Segment — a comparison the brief asks for by name.
    """
    rows = []
    for month in ("01", "02", "03"):
        for i, store in enumerate(("Ikeja", "Abuja")):
            rows.append(
                row(
                    f"2026-{month}-1{i}",
                    store,
                    f"Product {i}",
                    f"Campaign {i}",
                    500,
                    2,
                    1000 + i * 10,
                    600,
                    0,
                    partner=f"Partner {i}",
                )
                | {
                    "region": f"Region {i}",
                    "channel": f"Channel {i}",
                    "category": f"Category {i}",
                    "employee": f"Employee {i}",
                    "customer_segment": f"Segment {i}",
                }
            )

    dataset = Dataset(
        source=DataSource(id=1, name="S", source_type="file", connection_config="{}"),
        columns=COLUMNS,
        rows=rows,
        total=len(rows),
        truncated=False,
        mapping=MAPPING,
    )
    chart_ids = {c["id"] for c in build_overview(dataset)["charts"]}
    for named in ("store_id", "region", "product", "campaign", "employee", "customer_segment"):
        assert f"by_{named}" in chart_ids, f"missing the {named} comparison"


# --- profit and margin per segment ------------------------------------------


def test_profit_by_ranks_on_revenue_and_reports_margin():
    rows = [
        row("2026-01-10", "Ikeja", "Volume", "C", 100, 10, 10000, 9000, 0),
        row("2026-01-11", "Ikeja", "Earner", "C", 100, 10, 4000, 1000, 0),
    ]
    ranked = profit_by(make_dataset(rows), "product")
    assert [r["label"] for r in ranked] == ["Volume", "Earner"]
    assert ranked[0]["margin"] == pytest.approx(10.0)
    assert ranked[1]["margin"] == pytest.approx(75.0)


def test_the_revenue_leader_with_a_thin_margin_is_flagged():
    """Ranking on revenue alone hides the line that sells hardest and earns least."""
    rows = [
        row("2026-01-10", "Ikeja", "Volume", "C", 100, 10, 10000, 9200, 0),
        row("2026-02-10", "Ikeja", "Volume", "C", 100, 10, 10000, 9200, 0),
        row("2026-01-11", "Ikeja", "Earner", "C", 100, 10, 4000, 1000, 0),
        row("2026-02-11", "Ikeja", "Steady", "C", 100, 10, 3000, 1800, 0),
    ]
    findings = build_findings(make_dataset(rows))
    mix = [f for f in findings if f["id"].endswith("-margin-mix")]
    assert mix, "expected a revenue-leader / thin-margin finding"
    assert "Volume" in mix[0]["title"]
    assert "Earner" in mix[0]["body"]


# --- inventory ---------------------------------------------------------------


def test_excess_inventory_is_reported_not_just_stockouts():
    rows = []
    for i, store in enumerate(("Ikeja", "Abuja", "Kano")):
        rows.append(
            row(f"2026-01-1{i}", store, f"P{i}", "C", 100, 10, 1000, 600, 0)
            | {"stock_on_hand": 100 if store != "Kano" else 900}
        )
    dataset = make_dataset(
        rows,
        mapping={**MAPPING, "stock_on_hand": "Stock"},
        columns=[*COLUMNS, "stock_on_hand"],
    )
    excess = [f for f in build_findings(dataset) if f["id"].endswith("-excess-stock")]
    assert excess and "Kano" in excess[0]["title"]


def test_thin_cover_is_reported_before_it_reaches_zero():
    rows = []
    for i, store in enumerate(("Ikeja", "Abuja", "Kano")):
        rows.append(
            row(f"2026-01-1{i}", store, f"P{i}", "C", 100, 10, 1000, 600, 0)
            | {"stock_on_hand": 500 if store != "Kano" else 20}
        )
    dataset = make_dataset(
        rows,
        mapping={**MAPPING, "stock_on_hand": "Stock"},
        columns=[*COLUMNS, "stock_on_hand"],
    )
    thin = [f for f in build_findings(dataset) if f["id"].endswith("-thin-cover")]
    assert thin and "Kano" in thin[0]["title"]


# --- marketing ---------------------------------------------------------------


def test_campaign_roi_flags_a_wide_spread_even_when_both_are_profitable():
    rows = [
        row("2026-01-10", "Ikeja", "P", "Efficient", 100, 10, 9000, 4000, 0),
        row("2026-01-11", "Ikeja", "P", "Wasteful", 4000, 10, 9000, 4000, 0),
    ]
    roi = [f for f in build_findings(make_dataset(rows)) if f["id"].endswith("-campaign-roi")]
    assert roi, "a nine-fold efficiency gap should not pass silently"
    assert "Efficient" in roi[0]["title"] or "Efficient" in roi[0]["body"]


# --- returns recorded as a flag ---------------------------------------------
#
# A live run reported "All return rates are 0.0" on a dataset where one product
# came back 30% of the time. The column held the text "True", which sums to zero
# in both SQL and Python — so nothing was ever counted as returned.


def flag_rows():
    """Sixteen orders of two products; the microwave comes back three times in four."""
    rows = []
    for i in range(8):
        rows.append(
            row(f"2026-01-0{i + 1}", "Ikeja", "Microwave X200", "C", 100, 1, 1000, 600, 0)
            | {"returned": "True" if i < 6 else "False"}
        )
    for i in range(8):
        rows.append(
            row(f"2026-02-0{i + 1}", "Ikeja", "Smart TV", "C", 100, 1, 2000, 1200, 0)
            | {"returned": "False"}
        )
    return rows


def flag_dataset():
    return make_dataset(flag_rows(), mapping={**MAPPING, "returned": "Returns"})


def test_a_text_boolean_is_read_as_a_return():
    assert to_flag("True") == 1.0
    assert to_flag("true") == 1.0
    assert to_flag("YES") == 1.0
    assert to_flag("False") == 0.0
    assert to_flag("no") == 0.0
    assert to_flag("") == 0.0
    assert to_flag("banana") is None


def test_a_flag_column_is_recognised_as_one():
    dataset = flag_dataset()
    is_flag, units = returns_basis(dataset, "returned")
    assert is_flag is True
    assert units is None  # orders, not units, are the denominator


def test_a_counted_returns_column_still_divides_by_units():
    dataset = make_dataset()
    is_flag, units = returns_basis(dataset, "returned")
    assert is_flag is False
    assert units == "units"


def test_the_return_rate_of_a_flagged_product_is_not_zero():
    rates = return_rate_by(flag_dataset(), "product", "returned", min_denominator=1)
    worst = rates[0]
    assert worst["label"] == "Microwave X200"
    assert worst["value"] == pytest.approx(75.0)  # 6 of 8 orders
    assert rates[-1]["value"] == 0.0


def test_the_overall_return_rate_counts_orders_for_a_flag():
    assert overall_return_rate(flag_dataset(), "returned") == pytest.approx(0.375)


def test_a_flagged_outlier_still_raises_a_finding():
    dataset = flag_dataset()
    returns = [f for f in build_findings(dataset) if f["id"].endswith("-returns")]
    assert returns, "a product returned in 3 of 4 orders should be flagged"
    assert "Microwave X200" in returns[0]["title"]
