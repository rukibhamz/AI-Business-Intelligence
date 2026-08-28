"""A written answer may only state figures its evidence supports.

Asked "how do I improve laptop sales in Ibadan?", the model was handed a
region-level revenue comparison and replied that "Laptop 14 sold only 28 units
in Ibadan". The evidence carried no product breakdown at all; its only 28 was
`+28%` from the cost line, re-served as a unit count. The prompt already
forbade that. These make the ban enforceable.
"""

import pytest

from app.services.grounding import extract_figures, is_grounded, ungrounded_figures

#: Trimmed from the real prompt that produced the fabrication.
EVIDENCE = """
Question: how do i improve laptop sales in ibadan?
EVIDENCE
Measure: revenue (column revenue)
Latest period Jun 2026: 93,984,204; previous period May 2026: 77,302,356;
change +16,681,848 (+21.6%)
Segments by Region:
- Lagos: 30,674,269 -> 45,344,216, change +14,669,947 (+48%), 87% of the total movement
- Abuja: 22,515,987 -> 24,577,736, change +2,061,749 (+9%), 12% of the total movement
- Ibadan: 24,112,100 -> 24,062,252, change -49,848 (-0%), 0% of the total movement
Supporting factors:
- Cost moved +15,006,323 (+28%), so margin went from 30% to 27%.
Rows analysed: 631
"""


# --- the defect this exists for ---------------------------------------------


def test_the_fabricated_answer_is_rejected():
    shipped = (
        "The data cannot answer how to improve laptop sales in Ibadan. It shows the "
        "Laptop 14 sold only 28 units in Ibadan, far behind other products, and "
        "Ibadan revenue was flat at NGN 24,062,252 in Jun 2026."
    )
    assert not is_grounded(shipped, EVIDENCE)
    # "24,062,252" is real and stays unflagged; the invented ones do not.
    assert set(ungrounded_figures(shipped, EVIDENCE)) == {"14", "28"}


def test_a_number_borrowed_from_a_different_unit_is_rejected():
    """`+28%` in the evidence does not license "28 units" in the answer."""
    assert ungrounded_figures("We sold 28 units.", EVIDENCE) == ["28"]
    # The same figure, correctly used as a percentage, is fine.
    assert is_grounded("Cost rose 28%.", EVIDENCE)


# --- what must still pass ----------------------------------------------------


@pytest.mark.parametrize(
    "answer",
    [
        "Revenue rose to 93,984,204 in Jun 2026.",
        "Revenue grew 16,681,848, up 21.6%.",
        "Revenue rose 16.7 million against May.",
        "Lagos accounts for 87% of the movement.",
        "Margin went from 30% to 27%.",
        "Ibadan was flat, down 49,848.",
        "The comparison covers 631 rows.",
        "Lagos grew 48% while Abuja grew 9%.",
    ],
)
def test_supported_figures_pass(answer):
    assert is_grounded(answer, EVIDENCE), ungrounded_figures(answer, EVIDENCE)


def test_an_answer_with_no_figures_is_grounded():
    assert is_grounded("Cost is growing faster than revenue.", EVIDENCE)


def test_rounding_is_allowed_only_to_the_precision_stated():
    """22% is 21.6% rounded. 12.4% is not 12% — the decimal claims precision."""
    assert is_grounded("Revenue rose 22%.", EVIDENCE)
    assert ungrounded_figures("Returns ran at 12.4%.", EVIDENCE) == ["12.4%"]


def test_invented_magnitudes_are_rejected():
    assert ungrounded_figures("Ibadan revenue was 31,400,000.", EVIDENCE)
    assert ungrounded_figures("We shipped 415 laptops.", EVIDENCE)


def test_a_percentage_is_not_licensed_by_dividing_two_evidence_figures():
    """Otherwise any percentage is reachable, and the check means nothing."""
    # 24,112,100 / 93,984,204 is ~25.7%, and the evidence states neither.
    assert ungrounded_figures("Ibadan is 25.7% of revenue.", EVIDENCE) == ["25.7%"]


# --- mechanics ---------------------------------------------------------------


def test_years_are_labels_not_figures():
    assert extract_figures("Jun 2026 vs May 2026") == []


def test_units_are_read_off_the_number():
    figures = extract_figures("fell 3.6 points to 26.9% across 631 rows")
    assert [(round(v, 2), unit) for v, unit, _, _ in figures] == [
        (3.6, "points"),
        (26.9, "percent"),
        (631.0, "plain"),
    ]


def test_written_scales_are_expanded():
    values = [v for v, _, _, _ in extract_figures("16.7 million and 4.2k")]
    assert values == [16_700_000.0, 4_200.0]


def test_no_evidence_means_nothing_to_check():
    """A caller with no evidence gets no opinion, rather than a false alarm."""
    assert is_grounded("Revenue was 4,000.", "")
    assert is_grounded("", EVIDENCE)
