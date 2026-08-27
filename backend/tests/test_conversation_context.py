"""What a follow-up inherits from the turns before it.

"Why?" names no measure, no period and no segment. Until this module existed
only the previous question's *text* travelled forward, and only one turn of it,
so the third question in a chat could not refer to the first and "why?" after a
ranking re-derived from the whole dataset with no idea what was being asked
about.
"""

import json

from app.services.analytics import Dataset
from app.services.conversation_context import (
    MAX_RESULT_ROWS,
    Turn,
    build_context_block,
    context_questions,
    previous_question,
)
from app.services.diagnostics import diagnose
from app.services.response_planner import question_prompt_block
from tests.test_diagnostics import dataset, sales_rows


def turn(question, answer=None, columns=None, rows=None, sql=None):
    return Turn(
        question=question,
        answer=answer,
        columns=columns or [],
        rows=rows or [],
        sql=sql,
    )


RANKING = turn(
    "Which store had the highest revenue in February?",
    answer="Ikeja led at 12,400, ahead of Lekki at 9,100.",
    columns=["store", "revenue"],
    rows=[{"store": "Ikeja", "revenue": 12400}, {"store": "Lekki", "revenue": 9100}],
    sql="SELECT store, SUM(revenue) AS revenue FROM sales GROUP BY store",
)


# --- what a turn knows about itself -----------------------------------------


def test_a_turn_names_the_entities_its_answer_was_about():
    assert RANKING.label_column == "store"
    assert RANKING.entities == ["Ikeja", "Lekki"]


def test_a_turn_with_no_text_column_names_nothing():
    numbers = turn("total revenue", columns=["revenue"], rows=[{"revenue": 12400}])
    assert numbers.label_column is None
    assert numbers.entities == []


# --- the prompt block -------------------------------------------------------


def test_no_history_means_no_block():
    assert build_context_block([]) == ""


def test_the_block_carries_the_question_the_answer_and_the_entities():
    block = build_context_block([RANKING])
    assert "Which store had the highest revenue in February?" in block
    assert "Ikeja led at 12,400" in block
    assert "Ikeja, Lekki" in block
    assert "SELECT store" in block


def test_the_block_forbids_answering_from_stale_figures():
    """History resolves references. It is not a source of current numbers."""
    block = build_context_block([RANKING])
    assert "never from the figures below" in block


def test_the_block_keeps_every_turn_not_only_the_last():
    turns = [turn("revenue by region"), turn("what about profit?"), RANKING]
    block = build_context_block(turns)
    assert "[1]" in block and "[2]" in block and "[3]" in block
    assert "revenue by region" in block


def test_a_long_answer_is_truncated_rather_than_dropped():
    block = build_context_block([turn("q", answer="x" * 900)], max_answer_chars=100)
    assert "…" in block
    assert len(block) < 500


# --- ordering ---------------------------------------------------------------


def test_the_previous_question_is_the_most_recent_turn():
    assert previous_question([turn("first"), turn("second")]) == "second"
    assert previous_question([]) is None


def test_measure_resolution_reads_the_newest_question_first():
    """A chat that moves from revenue to margin is asking about margin now."""
    assert context_questions([turn("why did revenue fall"), turn("and the margin?")]) == [
        "and the margin?",
        "why did revenue fall",
    ]


# --- what it changes downstream ---------------------------------------------


def test_a_bare_followup_inherits_a_measure_from_two_turns_back():
    """Only the immediately previous question used to travel with a question."""
    history = context_questions(
        [turn("why did the margin fall?"), turn("show me the regions")]
    )
    result = diagnose(dataset(sales_rows()), "what should we do?", history=history)
    assert result["measure_label"] == "margin"


def test_the_newest_subject_wins_over_an_older_one():
    history = context_questions(
        [turn("why did revenue fall?"), turn("what about the margin?")]
    )
    result = diagnose(dataset(sales_rows()), "and now?", history=history)
    assert result["measure_label"] == "margin"


def test_the_sql_prompt_carries_the_transcript():
    block = build_context_block([RANKING])
    prompt = question_prompt_block("why?", RANKING.question, block)
    assert "RECENT CONVERSATION" in prompt
    assert "Ikeja" in prompt


def test_the_sql_prompt_is_unchanged_without_history():
    assert question_prompt_block("revenue by region", None, "") == (
        "Question: revenue by region"
    )


# --- reading turns back off stored queries ----------------------------------


def test_a_stored_query_becomes_a_turn():
    from app.services.conversation_context import _turn_from_query

    stored = type(
        "Q",
        (),
        {
            "natural_language": "revenue by store",
            "answer": "Ikeja led.",
            "generated_sql": "SELECT 1",
            "result_json": json.dumps(
                {
                    "columns": ["store", "revenue"],
                    "rows": [{"store": "Ikeja", "revenue": 1}],
                    "sql": "SELECT store FROM sales",
                }
            ),
            "response_format": "chart",
            "diagnosis_json": json.dumps({"diagnosis": {"measure_label": "margin"}}),
        },
    )()
    result = _turn_from_query(stored)
    assert result.question == "revenue by store"
    assert result.entities == ["Ikeja"]
    assert result.measure_label == "margin"
    # The result payload's own SQL wins over the column on the row.
    assert result.sql == "SELECT store FROM sales"


def test_a_turn_keeps_only_a_handful_of_result_rows():
    """A transcript must not crowd the schema out of the prompt."""
    from app.services.conversation_context import _turn_from_query

    stored = type(
        "Q",
        (),
        {
            "natural_language": "everything",
            "answer": None,
            "generated_sql": None,
            "result_json": json.dumps(
                {"columns": ["a"], "rows": [{"a": n} for n in range(50)]}
            ),
            "response_format": "table",
            "diagnosis_json": None,
        },
    )()
    assert len(_turn_from_query(stored).rows) == MAX_RESULT_ROWS


def test_unreadable_stored_json_does_not_break_a_turn():
    from app.services.conversation_context import _turn_from_query

    stored = type(
        "Q",
        (),
        {
            "natural_language": "q",
            "answer": None,
            "generated_sql": "SELECT 1",
            "result_json": "{not json",
            "response_format": None,
            "diagnosis_json": "{also not json",
        },
    )()
    result = _turn_from_query(stored)
    assert result.columns == [] and result.sql == "SELECT 1"


def test_dataset_import_is_available_for_the_diagnosis_tests():
    """Guards the shared fixture import above."""
    assert isinstance(dataset(sales_rows()), Dataset)
