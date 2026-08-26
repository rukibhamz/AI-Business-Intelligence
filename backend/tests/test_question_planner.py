"""Structured analysis plan + blank-result repair heuristics."""

from app.services.question_planner import (
    format_plan_for_sql,
    heuristic_analysis_plan,
    parse_analysis_plan,
    should_repair_blank,
)


def test_heuristic_fills_measure_dimension_and_rank():
    plan = heuristic_analysis_plan("What was the highest revenue product in June?")
    assert plan["measure"] == "revenue"
    assert plan["dimension"] == "product"
    assert plan["time_window"] == "june"
    assert plan["order"] == "desc"
    assert plan["limit"] == 1


def test_heuristic_followup_inherits_previous():
    plan = heuristic_analysis_plan(
        "what about the least?",
        previous_question="highest revenue product in March",
    )
    assert "revenue" in plan["resolved_question"].lower() or plan["measure"] == "revenue"
    assert plan["order"] == "asc" or "least" in plan["resolved_question"].lower()


def test_parse_analysis_plan_merges_json():
    raw = """
    ```json
    {
      "resolved_question": "Top region by revenue in 2025",
      "intent_summary": "top region / revenue / 2025",
      "measure": "revenue",
      "dimension": "region",
      "time_window": "2025",
      "order": "desc",
      "limit": 1,
      "filters": []
    }
    ```
    """
    plan = parse_analysis_plan(raw, fallback_question="top region")
    assert plan["resolved_question"] == "Top region by revenue in 2025"
    assert plan["measure"] == "revenue"
    assert plan["dimension"] == "region"
    assert plan["order"] == "desc"
    assert plan["limit"] == 1


def test_parse_analysis_plan_falls_back_on_garbage():
    plan = parse_analysis_plan("not json at all", fallback_question="revenue by region")
    assert plan["resolved_question"] == "revenue by region"
    assert plan["measure"] == "revenue"
    assert plan["dimension"] == "region"


def test_format_plan_includes_slots():
    plan = heuristic_analysis_plan("lowest return rate by partner last month")
    text = format_plan_for_sql(plan)
    assert "ANALYSIS PLAN" in text
    assert "Resolved question" in text
    assert plan["measure"] is None or plan["measure"] in text or "return" in text.lower()


def test_should_repair_blank_for_filtered_questions():
    plan = heuristic_analysis_plan("revenue in June")
    assert should_repair_blank("revenue in June", plan) is True


def test_should_not_always_repair_bare_counts():
    plan = heuristic_analysis_plan("how many rows are there")
    assert should_repair_blank("how many rows are there", plan) is False
