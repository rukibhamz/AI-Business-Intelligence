"""Columns the curated vocabulary has never heard of, given a usable role.

`CANONICAL_FIELDS` names the concepts a retail brief cares about. A logistics
file, a clinic's file or a school's file is full of real business columns that
list does not happen to contain, and before this they were all "Unmapped" —
invisible to charts, findings and attribution alike.

The judgement being tested is which columns are worth using and for what. A
wrong "no" loses a column; a wrong "yes" charts one bar per order reference or
sums a satisfaction score.
"""

import pytest

from app.services.analytics import Dataset
from app.services.field_inference import (
    describe_field_roles,
    humanize_field,
    infer_fields,
    infer_role,
    infer_role_from_profile,
)


def values(*seq, repeat=1):
    return list(seq) * repeat


# --- naming -----------------------------------------------------------------


@pytest.mark.parametrize(
    "column,expected",
    [
        ("shipping_zone", "Shipping Zone"),
        ("freightCharge", "Freight Charge"),
        ("nps", "NPS"),
        ("on-time-pct", "On Time Pct"),
    ],
)
def test_a_field_is_named_after_its_column(column, expected):
    assert humanize_field(column) == expected


# --- what a column is for ---------------------------------------------------


def test_a_low_cardinality_text_column_is_a_dimension():
    assert infer_role("supplier", values("Acme", "Beta", "Gamma", repeat=40)) == "dimension"


def test_a_continuous_number_is_a_measure():
    assert infer_role("freight_charge", [40_000 + i * 950 for i in range(400)]) == "measure"


def test_a_rate_is_never_a_measure():
    """Summing a score produces a number that means nothing."""
    for column in ("on_time_pct", "return_rate", "csat_score", "roi_ratio", "gross_margin"):
        assert infer_role(column, [70 + i % 20 for i in range(50)]) == "rate", column


def test_an_identifier_is_not_usable():
    assert infer_role("consignment_ref", [f"CN-{i}" for i in range(400)]) is None
    assert infer_role("order_id", list(range(100_000, 100_400))) is None


def test_a_dense_integer_sequence_reads_as_an_identifier_even_unnamed():
    """Issued consecutively: the range is as wide as the count."""
    assert infer_role("seq", list(range(5_000, 5_400))) is None


def test_a_wide_integer_spread_is_a_measure_not_an_identifier():
    """The trap: whole and near-unique describes a money column too."""
    assert infer_role("charge", [40_000 + i * 137 for i in range(400)]) == "measure"


def test_free_text_is_not_a_dimension():
    assert infer_role("internal_notes", [f"a note about order {i}" for i in range(80)]) is None


def test_a_column_of_one_value_explains_nothing():
    assert infer_role("country", ["Nigeria"] * 200) is None


def test_placeholder_columns_are_ignored():
    for column in ("Unnamed: 0", "col_3", "c1", "row_number"):
        assert infer_role(column, values("a", "b", "c", repeat=20)) is None, column


def test_a_short_noise_word_inside_a_real_name_is_not_noise():
    """`freight_charge` contains "_c"; matching that as noise loses the money column."""
    assert infer_role("freight_charge", [1000.5 + i for i in range(50)]) == "measure"
    assert infer_role("description_code", values("a", "b", repeat=30)) is None


def test_dates_are_recognised():
    assert infer_role("dispatch_date", [f"2026-0{1 + i % 6}-14" for i in range(30)]) == "date"


def test_a_numeric_code_with_few_values_can_still_label_a_group():
    assert infer_role("store_no", values(1, 2, 3, repeat=30)) == "dimension"


# --- putting it together ----------------------------------------------------


LOGISTICS = [
    {
        "consignment_ref": f"CN-{100000 + i}",
        "dispatch_date": "2026-03-01",
        "lane": ["Lagos-Kano", "Lagos-Ibadan", "Abuja-Jos"][i % 3],
        "freight_charge": 40_000 + (i % 37) * 950,
        "on_time_pct": 96 - (i % 3) * 14,
        "internal_notes": f"note {i}",
    }
    for i in range(120)
]


def test_only_the_unmapped_columns_are_inferred():
    mapping = {"dispatch_date": "Date", "lane": "Unmapped"}
    inferred, roles = infer_fields(list(LOGISTICS[0].keys()), LOGISTICS, mapping)
    assert "dispatch_date" not in inferred, "a confirmed mapping is never overwritten"
    assert inferred["lane"] == "Lane"
    assert roles["Lane"] == "dimension"


def test_a_curated_field_name_is_not_reused():
    """Two columns claiming one field is how a metric reads the wrong column."""
    rows = [{"region": "West", "Region": "North"} for _ in range(30)]
    inferred, _ = infer_fields(["region", "Region"], rows, {"region": "Region"})
    assert "Region" not in inferred


def test_the_dataset_vocabulary_grows_with_what_was_inferred():
    ds = Dataset(
        source=None,
        columns=list(LOGISTICS[0].keys()),
        rows=LOGISTICS,
        total=len(LOGISTICS),
        truncated=False,
        mapping={"dispatch_date": "Date"},
    )
    assert "Lane" in ds.dimensions()
    assert "Freight Charge" in ds.measures()
    # A rate is usable but never summable, so it is in neither list.
    assert ds.inferred["On Time Pct"] == "rate"
    assert "On Time Pct" not in ds.measures()
    # And the unusable columns stay out of both.
    assert "Consignment Ref" not in ds.dimensions()
    assert "Internal Notes" not in ds.dimensions()


def test_the_inferred_columns_resolve_like_curated_ones():
    ds = Dataset(
        source=None,
        columns=list(LOGISTICS[0].keys()),
        rows=LOGISTICS,
        total=len(LOGISTICS),
        truncated=False,
        mapping={},
    )
    assert ds.column_for("Lane") == "lane"
    assert ds.column_for("Freight Charge") == "freight_charge"


# --- what the SQL prompt is told ---------------------------------------------


def test_the_prompt_states_what_may_be_grouped_summed_and_never_summed():
    profiles = {
        "lane": {"kind": "category", "values": ["Lagos-Kano"]},
        "freight_charge": {"kind": "number"},
        "on_time_pct": {"kind": "number"},
        "dispatch_date": {"kind": "date"},
    }
    block = describe_field_roles(list(profiles), profiles)
    assert "GROUP BY these: lane" in block
    assert "SUM these: freight_charge" in block
    assert "NEVER SUM these" in block and "on_time_pct" in block


def test_roles_read_from_a_profile_match_roles_read_from_rows():
    assert infer_role_from_profile("on_time_pct", {"kind": "number"}) == "rate"
    assert infer_role_from_profile("freight_charge", {"kind": "number"}) == "measure"
    assert infer_role_from_profile("lane", {"kind": "category"}) == "dimension"
    assert infer_role_from_profile("internal_notes", {"kind": "text"}) is None
    assert infer_role_from_profile("anything", None) is None
