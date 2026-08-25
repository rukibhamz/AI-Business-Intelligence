"""AI field mapping: prompt construction and, above all, output validation.

The model's answer reaches the database, so anything it invents — a column that
does not exist, a field outside the canonical list — must be discarded rather
than stored.
"""

import pytest

from app.services.ai_mapping import (
    _extract_json,
    build_mapping_prompt,
    mapping_is_useful,
    validate_mapping,
)
from app.services.field_mapping import CANONICAL_FIELDS

COLUMNS = [
    {
        "name": "c1",
        "type": "string",
        "profile": {"kind": "date", "min": "2026-01-08", "max": "2026-03-29"},
    },
    {
        "name": "amt_tot",
        "type": "number",
        "profile": {"kind": "number", "min": "540.25", "max": "1720"},
    },
    {
        "name": "c2",
        "type": "string",
        "profile": {"kind": "category", "values": ["Kisumu", "Mombasa", "Nairobi"]},
    },
]
ROWS = [
    {"c1": "2026-01-08", "amt_tot": "1450.00", "c2": "Nairobi"},
    {"c1": "2026-01-22", "amt_tot": "930.50", "c2": "Mombasa"},
]


# --- prompt -----------------------------------------------------------------


def test_prompt_carries_the_evidence_not_just_names():
    prompt = build_mapping_prompt(COLUMNS, ROWS, source_name="Sales")
    assert "2026-01-08" in prompt  # date range
    assert "Nairobi" in prompt  # category values
    assert "1450.00" in prompt  # a real sample value
    assert "540.25" in prompt  # numeric bounds


def test_prompt_lists_every_canonical_field():
    prompt = build_mapping_prompt(COLUMNS, ROWS, source_name="Sales")
    for field in CANONICAL_FIELDS:
        assert field in prompt


def test_prompt_handles_columns_without_profiles():
    prompt = build_mapping_prompt([{"name": "x", "type": "string"}], [], source_name="S")
    assert '"x"' in prompt


# --- parsing ----------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        '{"c1": "Date"}',
        '```json\n{"c1": "Date"}\n```',
        '```\n{"c1": "Date"}\n```',
        'Here is the mapping:\n{"c1": "Date"}\nHope that helps.',
    ],
)
def test_json_is_recovered_from_common_wrappers(content):
    assert _extract_json(content) == {"c1": "Date"}


@pytest.mark.parametrize("content", ["not json at all", "", "[1, 2, 3]"])
def test_unparseable_content_is_rejected(content):
    assert _extract_json(content) is None


# --- validation (the important part) ----------------------------------------


def test_valid_mapping_passes_through():
    mapping, rejected = validate_mapping({"c1": "Date", "amt_tot": "Revenue"}, ["c1", "amt_tot"])
    assert mapping == {"c1": "Date", "amt_tot": "Revenue"}
    assert rejected == []


def test_hallucinated_column_is_discarded():
    mapping, rejected = validate_mapping({"c1": "Date", "not_a_column": "Revenue"}, ["c1"])
    assert mapping == {"c1": "Date"}
    assert any("not_a_column" in r for r in rejected)


def test_invented_field_is_discarded():
    mapping, rejected = validate_mapping({"c1": "GrossMarginPercent"}, ["c1"])
    assert mapping == {}
    assert any("GrossMarginPercent" in r for r in rejected)


def test_matching_is_case_insensitive():
    mapping, _ = validate_mapping({"C1": "date", "AMT_TOT": "revenue"}, ["c1", "amt_tot"])
    assert mapping == {"c1": "Date", "amt_tot": "Revenue"}


def test_non_string_values_are_discarded_not_crashed():
    mapping, rejected = validate_mapping({"c1": 42, "amt_tot": None}, ["c1", "amt_tot"])
    assert mapping == {}
    assert len(rejected) == 2


# --- auto-confirm gate ------------------------------------------------------


@pytest.mark.parametrize(
    "mapping,expected",
    [
        ({"a": "Revenue", "b": "Date"}, True),
        ({"a": "Quantity"}, True),
        ({"a": "Price"}, True),
        ({"a": "Date", "b": "Region"}, False),  # dimensions only — no metric
        ({"a": "Unmapped", "b": "Ignore"}, False),
        ({}, False),
    ],
)
def test_auto_confirm_requires_a_measure(mapping, expected):
    """Without a measure the dashboard has nothing to compute, so a human
    should still look at it."""
    assert mapping_is_useful(mapping) is expected
