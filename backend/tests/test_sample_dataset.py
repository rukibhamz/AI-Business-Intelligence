"""The demonstration dataset, and the patterns deliberately planted in it.

Every accuracy figure reported for this project was measured against this file.
That only means something if the file is the same file — so these lock two
things: that the generator is deterministic, and that each planted pattern is
actually present at the strength the write-up claims.

If one of these fails, the dataset changed. Recorded results no longer describe
what is on disk, and the digest in `make_nexasphere_dataset.EXPECTED_SHA256`
plus the write-up both need revisiting.
"""

import collections
import csv
import hashlib
import itertools

import pytest

from sample_data.make_nexasphere_dataset import (
    COLUMNS,
    EXPECTED_SHA256,
    REORDER_LEVEL,
    SLOW_PARTNER,
    build_rows,
    write,
)


@pytest.fixture(scope="module")
def rows():
    return build_rows()


def numeric(row, key):
    return float(row[key])


# --- reproducibility --------------------------------------------------------


def test_the_generator_is_deterministic(tmp_path):
    """Two runs must produce the same bytes, or a recorded figure means nothing."""
    first = write(tmp_path / "a.csv")
    second = write(tmp_path / "b.csv")
    assert first.read_bytes() == second.read_bytes()


def test_the_dataset_matches_the_recorded_digest(tmp_path):
    written = write(tmp_path / "nexasphere.csv")
    actual = hashlib.sha256(written.read_bytes()).hexdigest()
    assert actual == EXPECTED_SHA256, (
        "The dataset changed. Every accuracy figure recorded against it — in "
        "docs/submission and in the handoff — describes the previous file."
    )


def test_the_schema_is_the_one_the_brief_describes(tmp_path):
    written = write(tmp_path / "nexasphere.csv")
    with written.open(encoding="utf-8") as fh:
        header = next(csv.reader(fh))
    assert header == COLUMNS
    for required in ("order_date", "revenue", "cost", "returned", "marketing_spend"):
        assert required in header


def test_the_shape_is_six_months_of_trading(rows):
    assert len(rows) == 631
    assert rows[0]["order_date"] == "2026-01-01"
    assert rows[-1]["order_date"] == "2026-06-30"


# --- the planted patterns ---------------------------------------------------


def test_revenue_grows_while_margin_falls(rows):
    """The brief's headline risk, and the reason a profit total is not enough."""
    monthly = collections.defaultdict(lambda: [0.0, 0.0])
    for row in rows:
        bucket = monthly[row["order_date"][:7]]
        bucket[0] += numeric(row, "revenue")
        bucket[1] += numeric(row, "cost")

    periods = sorted(monthly)
    margins = [100 * (r - c) / r for r, c in (monthly[p] for p in periods)]

    assert monthly[periods[-1]][0] > monthly[periods[0]][0], "revenue should grow"
    assert margins[0] == pytest.approx(37.6, abs=0.1)
    assert margins[-1] == pytest.approx(26.8, abs=0.1)
    # Every step down, so no single month can be dismissed as noise.
    assert all(later < earlier for earlier, later in zip(margins, margins[1:], strict=False))


def test_one_product_is_returned_far_more_than_the_rest(rows):
    by_product = collections.defaultdict(lambda: [0, 0])
    for row in rows:
        bucket = by_product[row["product"]]
        bucket[0] += 1
        bucket[1] += row["returned"].lower() == "true"

    rates = {p: 100 * ret / total for p, (total, ret) in by_product.items()}
    worst = max(rates, key=rates.get)
    assert worst == "Soundbar Pro"
    assert rates[worst] == pytest.approx(32.9, abs=0.5)

    others = [v for k, v in rates.items() if k != worst]
    assert max(others) < 10, "the outlier must be unambiguous"


def test_one_delivery_partner_is_slow_and_poorly_rated(rows):
    by_partner = collections.defaultdict(lambda: [[], []])
    for row in rows:
        bucket = by_partner[row["delivery_partner"]]
        bucket[0].append(numeric(row, "delivery_days"))
        bucket[1].append(numeric(row, "customer_rating"))

    days = {p: sum(d) / len(d) for p, (d, _) in by_partner.items()}
    ratings = {p: sum(r) / len(r) for p, (_, r) in by_partner.items()}

    assert max(days, key=days.get) == SLOW_PARTNER
    assert min(ratings, key=ratings.get) == SLOW_PARTNER
    assert days[SLOW_PARTNER] == pytest.approx(8.5, abs=0.3)
    assert ratings[SLOW_PARTNER] == pytest.approx(2.67, abs=0.15)


def test_one_store_sits_below_its_reorder_level(rows):
    stock = {row["store"]: numeric(row, "stock_on_hand") for row in rows}
    below = [s for s, v in stock.items() if v < REORDER_LEVEL]
    assert below == ["Bodija"]
    assert stock["Bodija"] == 24


def test_the_campaign_budget_is_repeated_on_every_row(rows):
    """The grain trap: summing this column multiplies the budget by the row count.

    Without it the campaign-ROI question is trivial, and the defect that once
    reported 1.1x return where the truth was 152x could not recur.
    """
    for campaign, group in itertools.groupby(
        sorted(rows, key=lambda r: r["campaign"]), key=lambda r: r["campaign"]
    ):
        spends = {row["marketing_spend"] for row in group}
        assert len(spends) == 1, f"{campaign} should carry one budget, saw {spends}"

    naive = sum(numeric(r, "marketing_spend") for r in rows)
    once = sum(spend for _, spend in {(r["campaign"], numeric(r, "marketing_spend")) for r in rows})
    assert naive > once * 50, "summing per row must be wildly wrong, or this is not a trap"
    assert once == 4_700_000


def test_returns_are_written_as_text_not_as_a_flag(rows):
    """"True" sums to zero in SQL and in Python, which once zeroed every rate."""
    values = {row["returned"] for row in rows}
    assert values == {"True", "False"}


def test_several_locations_fall_short_of_target(rows):
    """Attainment reads the LATEST period against the target, not the half-year.

    The target is one period's figure repeated on every row. Summing six months
    of revenue against it is how the engine once reported 541% attainment, so
    the check here is deliberately the correct one — and it is also why a naive
    reading of this dataset finds no shortfall at all.
    """
    latest = max(row["order_date"][:7] for row in rows)

    half_year = collections.defaultdict(float)
    latest_period = collections.defaultdict(float)
    target = {}
    for row in rows:
        store, revenue = row["store"], numeric(row, "revenue")
        half_year[store] += revenue
        if row["order_date"][:7] == latest:
            latest_period[store] += revenue
        target[store] = numeric(row, "revenue_target")

    # Read the wrong way, every store looks comfortably ahead.
    assert not [s for s in half_year if half_year[s] < target[s]]

    # Read the right way, most of them are behind.
    short = [s for s in latest_period if latest_period[s] < target[s]]
    assert len(short) >= 3
    attainment = {s: 100 * latest_period[s] / target[s] for s in latest_period}
    assert min(attainment.values()) < 60, "at least one location clearly behind"
