"""Why a measure moved, and what to do about it.

The case these cover is the one that used to come back empty: "why did revenue
fall". A single SELECT has nothing to compare, so the answer has to be built
from a period comparison and an attribution.
"""

import json

import pytest

from app.models import DataSource
from app.services.analytics import Dataset
from app.services.diagnostics import (
    UNMEASURED_PREFIX,
    build_evidence_prompt,
    build_partial_context,
    build_partial_prompt,
    build_recommendations,
    diagnose,
    diagnosis_result_payload,
    parse_advisory_json,
    partial_result_payload,
    render_advice,
    render_diagnosis,
    render_partial,
    resolve_measure,
)
from app.services.response_planner import classify_intent

MAPPING = {
    "order_date": "Date",
    "region": "Region",
    "revenue": "Revenue",
    "cost": "Cost",
    "units": "Quantity",
}


def source() -> DataSource:
    return DataSource(
        id=1,
        name="Sales",
        source_type="file",
        schema_json=json.dumps({"tables": []}),
        connection_config=json.dumps({"field_mapping": MAPPING}),
    )


def dataset(rows: list[dict], mapping: dict | None = None) -> Dataset:
    columns = list(rows[0].keys()) if rows else []
    return Dataset(
        source=source(),
        columns=columns,
        rows=rows,
        total=len(rows),
        truncated=False,
        mapping=MAPPING if mapping is None else mapping,
    )


def sales_rows() -> list[dict]:
    """Four months. North collapses in April; South is flat throughout."""
    rows: list[dict] = []
    for month in ("01", "02", "03"):
        rows.append(
            {
                "order_date": f"2026-{month}-10",
                "region": "North",
                "revenue": 1000.0,
                "cost": 600.0,
                "units": 100,
            }
        )
        rows.append(
            {
                "order_date": f"2026-{month}-12",
                "region": "South",
                "revenue": 500.0,
                "cost": 300.0,
                "units": 50,
            }
        )
    rows.append(
        {
            "order_date": "2026-04-10",
            "region": "North",
            "revenue": 200.0,
            "cost": 500.0,
            "units": 20,
        }
    )
    rows.append(
        {
            "order_date": "2026-04-12",
            "region": "South",
            "revenue": 500.0,
            "cost": 300.0,
            "units": 50,
        }
    )
    return rows


# --- intent -----------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "why did revenue fall",
        "why did the revenue fall?",
        "what caused the drop in sales",
        "explain the decline in profit",
        "what happened in April",
    ],
)
def test_why_questions_are_diagnostic(question):
    assert classify_intent(question) == "diagnostic"


@pytest.mark.parametrize(
    "question",
    [
        "what should we do about the loss",
        "how do we prevent another loss",
        "suggest ways to improve revenue",
        "give me recommendations",
        "next steps?",
        "how can we recover from this",
    ],
)
def test_advice_questions_are_advisory(question):
    assert classify_intent(question) == "advisory"


@pytest.mark.parametrize(
    "question",
    [
        "tell me which model you are",
        "who are you?",
        "what are you",
        "are you an AI",
        "what can you do",
        "how do you work",
    ],
)
def test_identity_questions_are_meta(question):
    assert classify_intent(question) == "meta"


@pytest.mark.parametrize(
    "question",
    [
        "total revenue by region",
        "show me revenue by month",
        "list the top 10 products",
        "what is the total revenue",
        "which model sells the most",
    ],
)
def test_ordinary_questions_still_take_the_sql_path(question):
    assert classify_intent(question) == "factual"


def test_followup_least_inherits_prior_ranking_and_period():
    from app.services.response_planner import expand_question_with_context

    resolved = expand_question_with_context(
        "what about the least?",
        "what were my highest selling products in june",
    )
    assert "lowest" in resolved.lower() or "least" in resolved.lower()
    assert "june" in resolved.lower()
    assert "product" in resolved.lower()


# --- diagnosis --------------------------------------------------------------


def test_diagnose_reports_the_period_comparison():
    result = diagnose(dataset(sales_rows()), "why did revenue fall")
    assert result is not None
    assert result["measure_label"] == "revenue"
    assert result["direction"] == "down"
    assert result["current"] == 700.0
    assert result["previous"] == 1500.0
    assert result["change"] == -800.0
    assert result["period_label"] == "Apr 2026"
    assert result["previous_label"] == "Mar 2026"


def test_diagnose_attributes_the_fall_to_the_segment_that_moved():
    result = diagnose(dataset(sales_rows()), "why did revenue fall")
    assert result["dimension"] == "Region"
    north = next(d for d in result["drivers"] if d["label"] == "North")
    assert north["change"] == -800.0
    assert north["direction"] == "down"
    assert north["share"] == 100.0
    # South did not move, so it is not offered as an explanation.
    assert all(d["label"] != "South" for d in result["drivers"])


def test_diagnose_splits_the_move_into_price_and_volume():
    result = diagnose(dataset(sales_rows()), "why did revenue fall")
    factor = next(f for f in result["factors"] if f["kind"] == "price_volume")
    # Price per unit is 10 throughout, so the whole move is volume.
    assert factor["dominant"] == "volume"
    assert factor["price_effect"] == 0.0
    assert factor["volume_effect"] == pytest.approx(-800.0)
    # The split reconciles exactly with the observed change.
    assert factor["volume_effect"] + factor["price_effect"] == pytest.approx(
        result["change"]
    )


def test_diagnose_flags_the_margin_squeeze():
    result = diagnose(dataset(sales_rows()), "why did revenue fall")
    factor = next(f for f in result["factors"] if f["kind"] == "margin")
    assert factor["squeezed"] is True
    assert factor["margin_before"] == pytest.approx(40.0)
    # April: 700 revenue against 800 cost.
    assert factor["margin_now"] < 0


def test_diagnose_names_a_segment_that_stopped_contributing():
    rows = [r for r in sales_rows() if not (r["order_date"].startswith("2026-04") and r["region"] == "North")]
    result = diagnose(dataset(rows), "why did revenue fall")
    factor = next(f for f in result["factors"] if f["kind"] == "churn")
    assert factor["labels"] == ["North"]
    assert factor["lost_value"] == 1000.0


def test_diagnose_warns_when_the_latest_period_is_thin():
    rows = sales_rows()
    # Give March plenty of records and April only the one.
    rows = [r for r in rows if not r["order_date"].startswith("2026-04")] + [
        {
            "order_date": "2026-03-15",
            "region": "South",
            "revenue": 100.0,
            "cost": 50.0,
            "units": 10,
        }
        for _ in range(6)
    ] + [
        {
            "order_date": "2026-04-02",
            "region": "North",
            "revenue": 200.0,
            "cost": 100.0,
            "units": 20,
        }
    ]
    result = diagnose(dataset(rows), "why did revenue fall")
    factor = next(f for f in result["factors"] if f["kind"] == "coverage")
    assert factor["partial"] is True


def test_diagnose_measures_what_the_question_names():
    data = dataset(sales_rows())
    assert resolve_measure(data, "why did revenue fall")[1] == "revenue"
    assert resolve_measure(data, "why did costs go up")[1] == "cost"
    assert resolve_measure(data, "why are units down")[1] == "quantity"


def test_followup_inherits_the_measure_from_the_previous_question():
    """"What do we do about it?" names no metric; the question before it does."""
    result = diagnose(
        dataset(sales_rows()),
        "what should we do about it",
        previous_question="why did costs go up",
    )
    assert result["measure_label"] == "cost"


def test_diagnose_declines_without_a_date_column():
    rows = [{"region": "North", "revenue": 10.0}, {"region": "South", "revenue": 20.0}]
    assert diagnose(dataset(rows, {"region": "Region", "revenue": "Revenue"}), "why") is None


def test_diagnose_declines_with_a_single_period():
    """One period is nothing to compare against, so there is no move to explain."""
    rows = [
        {"order_date": "2026-04-10", "region": "North", "revenue": 1.0, "cost": 0, "units": 1},
        {"order_date": "2026-04-10", "region": "South", "revenue": 2.0, "cost": 0, "units": 1},
    ]
    assert diagnose(dataset(rows), "why did revenue fall") is None


def test_short_spans_compare_days_rather_than_months():
    """A few days of data still answers "why", against the day before."""
    rows = [
        {"order_date": "2026-04-10", "region": "North", "revenue": 100.0, "cost": 0, "units": 10},
        {"order_date": "2026-04-11", "region": "North", "revenue": 40.0, "cost": 0, "units": 4},
    ]
    result = diagnose(dataset(rows), "why did revenue fall")
    assert result["granularity"] == "day"
    assert result["period_label"] == "11 Apr"
    assert result["change"] == -60.0


def test_diagnose_reads_an_unmapped_source():
    """A source nobody mapped still has recognisable column names."""
    result = diagnose(dataset(sales_rows(), {}), "why did revenue fall")
    assert result is not None
    assert result["measure_label"] == "revenue"


# --- write-up ---------------------------------------------------------------


def test_narrative_states_the_move_and_names_the_driver():
    result = diagnose(dataset(sales_rows()), "why did revenue fall")
    text = render_diagnosis(result, source_name="Sales")
    assert "fell" in text
    assert "1,500" in text and "700" in text
    assert "North" in text
    assert "Apr 2026" in text


def test_narrative_handles_a_rise():
    rows = sales_rows()
    rows[-2]["revenue"] = 3000.0  # April North jumps instead of falling
    rows[-2]["units"] = 300
    result = diagnose(dataset(rows), "why did revenue jump")
    assert result["direction"] == "up"
    assert "rose" in render_diagnosis(result)


# --- recommendations --------------------------------------------------------


def test_recommendations_are_tied_to_the_driver():
    result = diagnose(dataset(sales_rows()), "what should we do about the drop")
    actions = build_recommendations(result)
    assert actions
    assert any("North" in a["title"] for a in actions)
    assert all(a["priority"] in ("now", "next", "watch") for a in actions)
    # Every action cites the figure behind it.
    assert all(a["basis"] for a in actions)


def test_recommendations_target_volume_when_volume_caused_it():
    result = diagnose(dataset(sales_rows()), "how do we fix this")
    actions = build_recommendations(result)
    volume = next(a for a in actions if a["kind"] == "price_volume")
    assert "volume" in volume["title"].lower()


def test_recommendations_always_include_a_monitoring_step():
    result = diagnose(dataset(sales_rows()), "how do we prevent another loss")
    actions = build_recommendations(result)
    assert any(a["kind"] == "monitoring" for a in actions)


def test_recommendations_lead_with_data_quality_when_the_period_is_partial():
    rows = [r for r in sales_rows() if not r["order_date"].startswith("2026-04")] + [
        {
            "order_date": "2026-03-15",
            "region": "South",
            "revenue": 100.0,
            "cost": 50.0,
            "units": 10,
        }
        for _ in range(6)
    ] + [
        {
            "order_date": "2026-04-02",
            "region": "North",
            "revenue": 200.0,
            "cost": 100.0,
            "units": 20,
        }
    ]
    actions = build_recommendations(diagnose(dataset(rows), "what should we do"))
    assert actions[0]["kind"] == "data_quality"


# --- payload and model parsing ----------------------------------------------


def test_result_payload_is_chartable():
    result = diagnose(dataset(sales_rows()), "why did revenue fall")
    payload = diagnosis_result_payload(result)
    assert payload["columns"] == ["period", "revenue"]
    assert len(payload["rows"]) == 4
    assert payload["rows"][-1] == {"period": "Apr 2026", "revenue": 700.0}


def test_advisory_json_survives_fences_and_junk():
    answer, actions = parse_advisory_json(
        '```json\n{"answer": "Revenue fell.", "recommendations": '
        '[{"title": "Recover North", "detail": "Call the accounts.", '
        '"basis": "North -800", "priority": "now"}]}\n```'
    )
    assert answer == "Revenue fell."
    assert actions[0]["title"] == "Recover North"
    assert actions[0]["priority"] == "now"


def test_advisory_json_rejects_unusable_output():
    assert parse_advisory_json("I could not answer that.") == (None, [])
    assert parse_advisory_json('{"answer": "hi", "recommendations": [{"title": ""}]}')[1] == []


def test_advisory_json_normalises_a_bad_priority():
    _, actions = parse_advisory_json(
        '{"answer": "x", "recommendations": [{"title": "T", "detail": "D", "priority": "URGENT"}]}'
    )
    assert actions[0]["priority"] == "next"


def test_advice_write_up_leads_with_the_first_action():
    result = diagnose(dataset(sales_rows()), "what should we do about the loss")
    actions = build_recommendations(result)
    text = render_advice(result, actions, source_name="Sales")
    assert "fell" in text
    assert "Start with" in text
    assert actions[0]["title"] in text


def test_advice_write_up_survives_having_no_actions():
    result = diagnose(dataset(sales_rows()), "what should we do")
    assert render_advice(result, [], source_name="Sales") == render_diagnosis(
        result, source_name="Sales"
    )


# --- when the data cannot support a comparison ------------------------------


def test_partial_context_reports_a_missing_date_column():
    rows = [
        {"region": "North", "revenue": 1000.0},
        {"region": "South", "revenue": 400.0},
    ]
    context = build_partial_context(
        dataset(rows, {"region": "Region", "revenue": "Revenue"}),
        "what caused the fall in revenue?",
    )
    assert context is not None
    assert any("date" in limit.lower() for limit in context["limits"])
    # It still hands over the comparison the data does support.
    assert context["breakdown"]["dimension"] == "Region"
    assert context["breakdown"]["rows"][0] == {"label": "North", "value": 1000.0}


def test_partial_context_reports_a_single_period():
    rows = [
        {"order_date": "2026-04-10", "region": "North", "revenue": 100.0, "cost": 0, "units": 1},
        {"order_date": "2026-04-10", "region": "South", "revenue": 200.0, "cost": 0, "units": 1},
    ]
    context = build_partial_context(dataset(rows), "why did revenue fall")
    assert any("one" in limit.lower() for limit in context["limits"])
    assert len(context["series"]) == 1
    assert context["period_span"] == "2026-04-10 to 2026-04-10"


def test_partial_context_reports_an_unmapped_measure():
    rows = [{"note": "a"}, {"note": "b"}]
    context = build_partial_context(dataset(rows, {"note": "Name"}), "why did revenue fall")
    assert any("revenue" in limit.lower() for limit in context["limits"])
    assert context["breakdown"] is None


def test_partial_context_needs_rows():
    """An empty source has nothing to say; the caller falls back to SQL."""
    assert build_partial_context(dataset([]), "why did revenue fall") is None


def test_partial_write_up_states_the_limit_and_what_is_there():
    rows = [
        {"region": "North", "revenue": 1000.0},
        {"region": "South", "revenue": 400.0},
    ]
    context = build_partial_context(
        dataset(rows, {"region": "Region", "revenue": "Revenue"}),
        "what caused the fall in revenue?",
    )
    text = render_partial(context, source_name="Sales")
    assert "cannot be measured" in text
    assert "North" in text
    assert "1,400" in text  # the grand total is reported alongside the leader


def test_partial_payload_prefers_the_series_then_the_breakdown():
    rows = [
        {"order_date": "2026-04-10", "region": "North", "revenue": 100.0, "cost": 0, "units": 1},
        {"order_date": "2026-04-10", "region": "South", "revenue": 200.0, "cost": 0, "units": 1},
    ]
    payload = partial_result_payload(build_partial_context(dataset(rows), "why did revenue fall"))
    assert payload["columns"] == ["period", "revenue"]

    flat = [{"region": "North", "revenue": 1.0}, {"region": "South", "revenue": 2.0}]
    payload = partial_result_payload(
        build_partial_context(
            dataset(flat, {"region": "Region", "revenue": "Revenue"}), "why did revenue fall"
        )
    )
    assert payload["columns"] == ["region", "revenue"]
    assert len(payload["rows"]) == 2


def test_partial_prompt_spells_out_the_limitations():
    rows = [
        {"region": "North", "revenue": 1000.0},
        {"region": "South", "revenue": 400.0},
    ]
    context = build_partial_context(
        dataset(rows, {"region": "Region", "revenue": "Revenue"}), "why did revenue fall"
    )
    prompt = build_partial_prompt(
        "why did revenue fall", context, source_name="Sales", currency="NGN"
    )
    assert "LIMITATIONS" in prompt
    assert "EVIDENCE" in prompt
    assert "North: 1,000" in prompt
    assert "NGN" in prompt


# --- profit and margin questions --------------------------------------------


def test_margin_question_measures_a_margin_not_a_column():
    """A margin is profit over revenue, and neither column is that ratio.

    Resolving "why did margin fall" to revenue answered that revenue *rose*.
    Resolving it to profit is wrong the same way for the opposite reason —
    see the test below, where profit rises in the period the margin falls.
    """
    result = diagnose(dataset(sales_rows()), "why did profit margin fall?")
    assert result["measure_label"] == "margin"
    assert result["measure_kind"] == "ratio"
    assert result["unit"] == "%"
    # March: 1,500 revenue, 900 cost -> 40%. April: 700 revenue, 800 cost.
    assert result["previous"] == pytest.approx(40.0)
    assert result["current"] == pytest.approx(-14.29, abs=0.01)
    assert result["direction"] == "down"
    # A percent change *of* a percentage is not a figure anyone can act on.
    assert result["change_pct"] is None


def margin_squeeze_rows() -> list[dict]:
    """Two months where profit RISES while margin FALLS: 18.75% -> 15.0%.

    This is the case that makes "margin" and "profit" different questions.
    """
    rows = []
    for day, store, revenue, cost in (
        ("2026-01-05", "Ikeja", 4000.0, 3200.0),
        ("2026-01-12", "Lekki", 4000.0, 3300.0),
        ("2026-01-20", "Abuja", 8000.0, 6500.0),
        ("2026-03-05", "Ikeja", 6000.0, 5200.0),
        ("2026-03-12", "Lekki", 6000.0, 5100.0),
        ("2026-03-20", "Abuja", 12000.0, 10100.0),
    ):
        rows.append(
            {
                "order_date": day,
                "region": store,
                "revenue": revenue,
                "cost": cost,
                "units": int(revenue / 100),
            }
        )
    return rows


def test_margin_and_profit_are_answered_as_different_questions():
    data = margin_squeeze_rows()

    margin = diagnose(dataset(data), "what should we do about the margin?")
    assert margin["measure_label"] == "margin"
    assert margin["previous"] == pytest.approx(18.75)
    assert margin["current"] == pytest.approx(15.0)
    assert margin["direction"] == "down"

    profit = diagnose(dataset(data), "why did profit change?")
    assert profit["measure_label"] == "profit"
    assert profit["previous"] == pytest.approx(3000.0)
    assert profit["current"] == pytest.approx(3600.0)
    assert profit["direction"] == "up"


def test_margin_drivers_are_contribution_points_that_sum_to_the_move():
    result = diagnose(dataset(sales_rows()), "why did margin fall?")
    drivers = result["drivers"]
    assert drivers
    # Contributions are exact, not estimates: they add up to the whole move.
    assert sum(d["change"] for d in drivers) == pytest.approx(result["change"], abs=0.05)
    # current - previous == change, so the evidence prompt reads consistently.
    for driver in drivers:
        assert driver["current"] - driver["previous"] == pytest.approx(
            driver["change"], abs=0.02
        )
    north = next(d for d in drivers if d["label"] == "North")
    assert north["change"] == pytest.approx(-69.52, abs=0.05)
    # The segment's own rate is carried too — that is what a reader acts on.
    assert north["own_before"] == pytest.approx(40.0)
    assert north["own_now"] == pytest.approx(-150.0)


def test_margin_is_written_in_points_never_in_currency():
    result = diagnose(dataset(sales_rows()), "why did margin fall?")
    text = render_diagnosis(result, source_name="Sales")
    assert "40.0%" in text
    assert "points" in text
    # The margin move is -54.3 points; -54 on its own would read as money.
    assert "-54.3 points" in text


def test_margin_recommendations_name_the_side_that_outgrew_the_other():
    result = diagnose(dataset(margin_squeeze_rows()), "what should we do about the margin?")
    mechanics = next(f for f in result["factors"] if f["kind"] == "margin_mechanics")
    assert mechanics["cost_outgrew_revenue"] is True
    actions = build_recommendations(result)
    assert any(a["kind"] == "margin" for a in actions)


def test_margin_result_payload_is_named_as_a_rate():
    """The chart and the table decide by column name whether to total a column."""
    payload = diagnosis_result_payload(diagnose(dataset(sales_rows()), "why did margin fall?"))
    assert payload["columns"] == ["period", "margin_pct"]


def test_a_margin_question_without_cost_does_not_answer_about_revenue():
    rows = [
        {"order_date": row["order_date"], "region": row["region"], "revenue": row["revenue"]}
        for row in sales_rows()
    ]
    mapping = {"order_date": "Date", "region": "Region", "revenue": "Revenue"}
    assert diagnose(dataset(rows, mapping), "why did margin fall?") is None


def test_derived_profit_does_not_override_a_real_profit_column():
    rows = [
        {**row, "profit": row["revenue"] - row["cost"] - 10} for row in sales_rows()
    ]
    mapping = {**MAPPING, "profit": "Profit"}
    result = diagnose(dataset(rows, mapping), "why did profit fall")
    assert result["measure"] == "profit"
    assert result["current"] == -120.0  # the stated column, not revenue - cost


def test_margin_factor_reads_revenue_even_when_asked_about_profit():
    result = diagnose(dataset(sales_rows()), "why did profit fall")
    factor = next(f for f in result["factors"] if f["kind"] == "margin")
    assert factor["margin_before"] == pytest.approx(40.0)
    assert factor["squeezed"] is True
    assert factor["cost_direction"] == "down"


# --- period granularity -----------------------------------------------------


def _span_rows(start: str, days: int, step: int = 1) -> list[dict]:
    from datetime import date, timedelta

    begin = date.fromisoformat(start)
    return [
        {
            "order_date": (begin + timedelta(days=offset)).isoformat(),
            "region": "North" if offset % 2 else "South",
            "revenue": 100.0 + offset,
            "cost": 60.0,
            "units": 10,
        }
        for offset in range(0, days, step)
    ]


def test_a_short_span_compares_weeks_not_two_trading_days():
    """A 40-day upload used to compare the last two *days* that had rows in them.

    That reads as a collapse whenever the final day happens to be quiet, and
    the advice then says the measure "moved in one day".
    """
    result = diagnose(dataset(_span_rows("2026-02-01", 40)), "why did revenue fall?")
    assert result["granularity"] == "week"
    assert "week of" in result["period_label"]


def test_a_span_inside_one_month_still_finds_two_periods():
    """Three weeks inside one calendar month is a single monthly bucket."""
    result = diagnose(dataset(_span_rows("2026-02-02", 20)), "why did revenue fall?")
    assert result["granularity"] == "week"
    assert len(result["series"]) >= 2


def test_a_span_of_days_still_compares_days():
    result = diagnose(dataset(_span_rows("2026-02-02", 6)), "why did revenue fall?")
    assert result["granularity"] == "day"


def test_a_long_span_still_compares_months():
    """The existing behaviour at the top end is unchanged."""
    result = diagnose(dataset(sales_rows()), "why did revenue fall")
    assert result["granularity"] == "month"


# --- answering only what the data can answer --------------------------------


def test_a_question_with_no_subject_is_answered_on_the_headline_figure():
    """"What should we do" names nothing, so the headline figure answers it."""
    result = diagnose(dataset(sales_rows()), "what should we do")
    assert result["measure_matched"] is True
    assert UNMEASURED_PREFIX not in render_diagnosis(result)


def test_a_subject_the_data_does_not_measure_is_declared_not_answered():
    """Revenue advice under a churn question is advice about a different thing."""
    result = diagnose(dataset(sales_rows()), "how can we reduce customer churn")
    assert result["measure_matched"] is False
    assert render_diagnosis(result).startswith(UNMEASURED_PREFIX)
    actions = build_recommendations(result)
    assert actions[0]["kind"] == "coverage_gap"


def test_a_hypothetical_is_not_answered_from_history():
    """Rows record what happened; opening a new store has not happened."""
    result = diagnose(dataset(sales_rows()), "should we open a new store in Kano?")
    assert result["measure_matched"] is False
    assert render_diagnosis(result).startswith(UNMEASURED_PREFIX)


def test_a_forecast_is_not_answered_from_history():
    result = diagnose(dataset(sales_rows()), "what will revenue be next quarter?")
    assert result["measure_matched"] is False


def test_a_measured_subject_carries_no_disclaimer():
    for question in ("how do we improve sales", "what should we do about the margin?"):
        result = diagnose(dataset(sales_rows()), question)
        assert result["measure_matched"] is True, question
        assert UNMEASURED_PREFIX not in render_diagnosis(result), question


def test_the_evidence_prompt_tells_the_model_not_to_answer_the_wrong_question():
    result = diagnose(dataset(sales_rows()), "how can we reduce customer churn")
    prompt = build_evidence_prompt("how can we reduce customer churn", result)
    assert "nothing in the question named this measure" in prompt
