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
        "total revenue by region",
        "show me revenue by month",
        "list the top 10 products",
        "what is the total revenue",
    ],
)
def test_ordinary_questions_still_take_the_sql_path(question):
    assert classify_intent(question) == "factual"


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


def test_margin_question_measures_profit_not_revenue():
    """The brief's data carries revenue and cost, never a profit column.

    Resolving "why did margin fall" to revenue answered that revenue *rose* —
    the opposite of the question.
    """
    result = diagnose(dataset(sales_rows()), "why did profit margin fall?")
    assert result["measure_label"] == "profit"
    # April: 700 revenue against 800 cost.
    assert result["current"] == -100.0
    assert result["previous"] == 600.0
    assert result["direction"] == "down"


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
