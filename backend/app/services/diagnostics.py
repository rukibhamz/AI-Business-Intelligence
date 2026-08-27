"""Diagnostic answers: why a measure moved, and what to do about it.

Ask AI answers most questions by writing one SQL query and summarising the
rows it returns. That shape cannot answer "why did revenue fall" — a cause is
not a column, and a single SELECT has nothing to compare against. This module
answers those questions the way an analyst would:

1. Compare the latest period against the one before it.
2. Attribute the change to the segments that actually moved it.
3. Read the supporting factors (margin, price vs volume, churned segments).
4. Derive actions the evidence supports — remediation for a fall, reinforcement
   for a rise.

Every figure here is computed from rows loaded from the source. Nothing is
asserted that the data does not show; when the data cannot support a diagnosis
the caller is told why, and falls back to the ordinary SQL path.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any

from app.services.analytics import (
    DIMENSION_FIELDS,
    Dataset,
    TimeIndex,
    bucket_totals,
    build_comparison_index,
    build_time_index,
    to_number,
)
from app.services.field_mapping import suggest_mapping

#: Measures a "why" question can be about, in fallback order.
_MEASURE_FALLBACK = ("Revenue", "Profit", "Quantity", "Cost")

#: Words in the question that name the measure being asked about.
_MEASURE_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("revenue", "sales", "turnover", "income", "takings", "top line"), "Revenue"),
    (("profit", "margin", "bottom line", "earnings"), "Profit"),
    (("cost", "expense", "spend", "cogs", "overhead"), "Cost"),
    (("quantity", "units", "volume", "orders", "sold"), "Quantity"),
    (("stock", "inventory"), "Stock"),
    (("rating", "satisfaction", "csat", "nps"), "Rating"),
    (("return", "refund"), "Returns"),
)

#: Words that name a margin. A margin is profit *over* revenue, so it is not
#: any one column and it is never summed: profit can rise in the same period a
#: margin falls, and answering one when asked the other contradicts the question.
_MARGIN_WORDS = (
    "margin",
    "margins",
    "profitability",
    "profit rate",
    "markup",
)

#: How much of the total movement one dimension must concentrate before it is
#: reported as *the* explanation rather than noise.
_MIN_CONCENTRATION = 0.35


def _pct(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return (current - previous) / abs(previous) * 100


def _fmt(value: float) -> str:
    if abs(value - round(value)) < 0.005:
        return f"{round(value):,}"
    return f"{value:,.2f}"


def _signed(value: float) -> str:
    return f"{'+' if value >= 0 else '-'}{_fmt(abs(value))}"


def _fmt_unit(value: float, unit: str) -> str:
    """A level. A rate carries its sign of being a rate; money does not."""
    return f"{value:,.1f}%" if unit == "%" else _fmt(value)


def _signed_unit(value: float, unit: str) -> str:
    """A movement. Rates move in percentage points, not percent of a percent."""
    if unit == "%":
        return f"{'+' if value >= 0 else '-'}{abs(value):,.1f} points"
    return _signed(value)


# ---------------------------------------------------------------------------
# Resolving what the question is about
# ---------------------------------------------------------------------------


def ensure_mapping(dataset: Dataset) -> Dataset:
    """Fall back to inferred field mapping when the operator confirmed none.

    A diagnosis needs to know which column is the date and which is the money.
    An unmapped source can still be read: the same name heuristics that seed
    the mapping screen work here.
    """
    usable = set(dataset.mapping.values()) - {"Unmapped", "Ignore"}
    if usable:
        return dataset
    inferred = suggest_mapping(dataset.columns)
    return dataclasses.replace(dataset, mapping=inferred)


#: Name given to the profit column when it has to be derived.
DERIVED_PROFIT = "profit_derived"


def ensure_profit(dataset: Dataset) -> Dataset:
    """Give the dataset a profit column when it has revenue and cost but no profit.

    Asked "why did margin fall", a source with only revenue and cost would
    otherwise fall back to revenue — and answer that revenue *rose*, which is
    the opposite of what was asked.
    """
    if dataset.column_for("Profit"):
        return dataset
    revenue_col = dataset.column_for("Revenue")
    cost_col = dataset.column_for("Cost")
    if not revenue_col or not cost_col:
        return dataset

    rows: list[dict[str, Any]] = []
    for row in dataset.rows:
        revenue = to_number(row.get(revenue_col))
        cost = to_number(row.get(cost_col))
        enriched = dict(row)
        enriched[DERIVED_PROFIT] = None if revenue is None or cost is None else revenue - cost
        rows.append(enriched)

    return dataclasses.replace(
        dataset,
        rows=rows,
        columns=[*dataset.columns, DERIVED_PROFIT],
        mapping={**dataset.mapping, DERIVED_PROFIT: "Profit"},
    )


@dataclasses.dataclass(frozen=True)
class MeasureSpec:
    """What a diagnosis is about.

    A *sum* measure is one column added up over a period. A *ratio* is computed
    from the period's totals — a margin is total profit over total revenue — so
    it must never be summed, neither across rows nor across periods. "Total
    margin" is not a figure, and the average of per-row margins is not the
    period's margin.
    """

    label: str
    kind: str  # "sum" | "ratio"
    column: str | None = None  # the summed column
    numerator: str | None = None
    denominator: str | None = None
    unit: str = ""  # "" for money and counts, "%" for a rate
    #: False when nothing in the question named this measure and it was picked
    #: by fallback. The answer has to say so: "how do we reduce churn" measured
    #: on revenue is not an answer about churn.
    matched: bool = True

    @property
    def is_ratio(self) -> bool:
        return self.kind == "ratio"


#: The scaffolding an advisory or diagnostic question is built from: question
#: words, pronouns, the verbs of asking for advice, and the vocabulary of a
#: movement. Whatever survives this is the question's *subject*.
_QUESTION_SCAFFOLD = frozenset(
    """
    what how why when where which who whom whose should shall can could would will
    do does did done doing are is was were be been being have has had
    we i they you us our my your their the a an and or but not no nor
    about with for from on in into to of at by as that this these those it its
    any some most more less least best better worse worst good bad great
    now next then soon later still yet again another other same
    go going get getting make making take taking put keep keeping give giving
    fix fixing solve solving improve improving increase increasing decrease
    decreasing reduce reducing grow growing boost boosting raise raising lower
    lowering prevent preventing avoid avoiding stop stopping address addressing
    recover recovering recovery reverse reversing turn turning around correct
    correcting change changing help helping handle handling deal
    advise advice recommend recommended recommendation recommendations suggest
    suggestion suggestions action actions step steps plan plans idea ideas
    option options way ways thing things something anything
    happen happened happening wrong right well badly really actually
    business company situation performance numbers number figures figure data
    result results overall generally
    drop dropped drops fall fell falling fallen decline declined declining dip
    slump loss losses losing lost spike surge jump jumped rise rose rising risen
    growth gain gains gained collapse shortfall gap trend move movement moving
    down up bad worse
    """.split()
)


def question_subject_words(question: str | None) -> set[str]:
    """The content words a question carries, once the scaffolding is removed.

    An empty set means the question named no subject at all — "what should we
    do" — which is a fair thing to answer on the headline figure. A non-empty
    set that matches no measure means the question is about something this data
    does not hold, which is not.
    """
    if not question:
        return set()
    return {
        word
        for word in re.findall(r"[a-z][a-z'\-]*", question.lower())
        if len(word) > 2 and word not in _QUESTION_SCAFFOLD
    }


#: Questions about something that has not happened. Rows record the past, so a
#: hypothetical or a forecast cannot be measured from them however well the
#: subject is mapped — "should we open a new store" is not answered by the
#: history of the stores that exist.
_SPECULATIVE_PATTERNS = (
    r"\bshould\s+(?:we|i|they)\s+(?:open|launch|start|build|hire|expand|enter|invest|buy|acquire|introduce|switch|close|discontinue)\b",
    r"\b(?:if|when)\s+we\s+(?:were|did|do|open|launch|start|hire|raise|cut)\b",
    r"\bwould\s+(?:it|we|they|that|this)\s+(?:be|make|help|work|improve|increase|reduce)\b",
    r"\bwhat\s+(?:would|will)\s+happen\b",
    r"\b(?:forecast|forecasts|predict|prediction|projection|projected|expected)\b",
    r"\bnext\s+(?:year|quarter|month|week)\b",
    r"\bhow\s+much\s+(?:would|will)\b",
)


def is_speculative(question: str | None) -> bool:
    if not question:
        return False
    q = question.lower().strip()
    return any(re.search(p, q) for p in _SPECULATIVE_PATTERNS)


def asks_about_margin(*questions: str | None) -> bool:
    return any(
        any(w in f" {q.lower()} " for w in _MARGIN_WORDS) for q in questions if q
    )


def margin_columns(dataset: Dataset) -> tuple[str, str] | None:
    """(profit column, revenue column) when a margin can honestly be computed.

    `ensure_profit` has already derived profit from revenue and cost where it
    could, so reaching here without a profit column means the data genuinely
    cannot express a margin.
    """
    revenue_col = dataset.column_for("Revenue")
    profit_col = dataset.column_for("Profit")
    if revenue_col and profit_col and revenue_col != profit_col:
        return profit_col, revenue_col
    return None


def resolve_measure_spec(dataset: Dataset, *questions: str | None) -> MeasureSpec | None:
    """What the question is about, as something that can actually be measured.

    A margin question resolves to a ratio or to nothing. It must not quietly
    resolve to profit: on data where cost outgrew revenue, profit rises in the
    same period the margin falls, and the answer then contradicts the question.
    """
    # Rows are a record of the past. A question about what has not happened is
    # not answerable from them, however well its subject is mapped.
    grounded = not is_speculative(questions[0] if questions else None)

    for question in questions:
        if not question:
            continue
        q = f" {question.lower()} "
        if any(w in q for w in _MARGIN_WORDS):
            pair = margin_columns(dataset)
            if not pair:
                return None
            profit_col, revenue_col = pair
            return MeasureSpec(
                label="margin",
                kind="ratio",
                numerator=profit_col,
                denominator=revenue_col,
                unit="%",
                matched=grounded,
            )
        for words, canonical in _MEASURE_HINTS:
            if any(w in q for w in words):
                column = dataset.column_for(canonical)
                if column:
                    return MeasureSpec(
                        label=canonical.lower(),
                        kind="sum",
                        column=column,
                        matched=grounded,
                    )

    # No question named a measure this data holds. Whether that is a problem
    # depends on whether the question named a subject at all: "what should we
    # do" has none and the headline figure answers it fairly, while "how do we
    # reduce customer churn" names one this data cannot measure, and answering
    # that on revenue would be answering a different question.
    subject = question_subject_words(questions[0] if questions else None)
    known = {word for column in dataset.columns for word in re.split(r"[\s_\-]+", column.lower())}
    known |= {
        word
        for canonical in dataset.canonical
        for word in canonical.lower().split()
    }
    matched = grounded and (not subject or bool(subject & known))

    for canonical in _MEASURE_FALLBACK:
        column = dataset.column_for(canonical)
        if column:
            return MeasureSpec(
                label=canonical.lower(), kind="sum", column=column, matched=matched
            )
    return None


def resolve_measure(dataset: Dataset, *questions: str | None) -> tuple[str, str] | None:
    """The summable column the question is about. Returns (column, label).

    Used where only a column will do — the partial-context path breaks a single
    column down by segment. `resolve_measure_spec` is the full answer.
    """
    spec = resolve_measure_spec(dataset, *questions)
    if spec is not None and not spec.is_ratio:
        return spec.column, spec.label

    # A margin question, or one whose margin could not be computed. Profit is
    # the closest thing to break down; the caller states the limitation.
    order = ("Profit", *_MEASURE_FALLBACK) if asks_about_margin(*questions) else _MEASURE_FALLBACK
    for canonical in order:
        column = dataset.column_for(canonical)
        if column:
            return column, canonical.lower()
    return None


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------


def _totals_for_bucket(
    dataset: Dataset,
    index: TimeIndex,
    column: str,
    measure: str,
    bucket_key: str,
) -> dict[str, float]:
    totals: dict[str, float] = {}
    for row, key in zip(dataset.rows, index.row_bucket, strict=False):
        if key != bucket_key:
            continue
        label = str(row.get(column, "")).strip()
        value = to_number(row.get(measure))
        if not label or value is None:
            continue
        totals[label] = totals.get(label, 0.0) + value
    return totals


def bucket_ratios(
    dataset: Dataset, index: TimeIndex, spec: MeasureSpec
) -> dict[str, float]:
    """A ratio per period, computed from that period's totals.

    Periods whose denominator is zero are left out entirely rather than
    reported as 0% — a margin on no revenue is undefined, not flat.
    """
    numerators = bucket_totals(dataset, index, spec.numerator)
    denominators = bucket_totals(dataset, index, spec.denominator)
    out: dict[str, float] = {}
    for bucket in index.buckets:
        denominator = denominators.get(bucket.key, 0.0)
        if denominator == 0:
            continue
        out[bucket.key] = numerators.get(bucket.key, 0.0) / denominator * 100
    return out


def attribute_ratio_change(
    dataset: Dataset,
    index: TimeIndex,
    spec: MeasureSpec,
    current_key: str,
    previous_key: str,
    *,
    max_drivers: int = 4,
) -> dict[str, Any] | None:
    """Split a ratio move into the percentage points each segment contributed.

    A segment's share of the period margin is its own profit over the *whole
    period's* revenue. Differencing that across the two periods gives a set of
    contributions that sum exactly to the observed move, so no share is an
    estimate — and it captures both halves of what actually happens to a
    blended rate: a segment's own margin changing, and a segment growing or
    shrinking as a proportion of the mix.
    """
    best: dict[str, Any] | None = None

    total_now = _bucket_sum(dataset, index, spec.denominator, current_key) or 0.0
    total_before = _bucket_sum(dataset, index, spec.denominator, previous_key) or 0.0
    if total_now == 0 or total_before == 0:
        return None

    for canonical in DIMENSION_FIELDS:
        column = dataset.column_for(canonical)
        if not column:
            continue

        num_now = _totals_for_bucket(dataset, index, column, spec.numerator, current_key)
        num_before = _totals_for_bucket(dataset, index, column, spec.numerator, previous_key)
        den_now = _totals_for_bucket(dataset, index, column, spec.denominator, current_key)
        den_before = _totals_for_bucket(
            dataset, index, column, spec.denominator, previous_key
        )
        labels = set(num_now) | set(num_before) | set(den_now) | set(den_before)
        if len(labels) < 2 or len(labels) > 200:
            continue

        contributions = []
        for label in labels:
            share_now = num_now.get(label, 0.0) / total_now * 100
            share_before = num_before.get(label, 0.0) / total_before * 100
            contributions.append((label, share_now, share_before, share_now - share_before))

        total_move = sum(abs(delta) for _, _, _, delta in contributions)
        if total_move <= 0:
            continue

        contributions.sort(key=lambda item: abs(item[3]), reverse=True)
        concentration = sum(abs(c[3]) for c in contributions[:2]) / total_move

        if best is None or concentration > best["concentration"]:
            drivers = []
            for label, share_now, share_before, delta in contributions[:max_drivers]:
                if delta == 0:
                    continue
                own_now = den_now.get(label)
                own_before = den_before.get(label)
                drivers.append(
                    {
                        "dimension": canonical,
                        "label": label,
                        # Contribution points, so current - previous == change.
                        "current": round(share_now, 2),
                        "previous": round(share_before, 2),
                        "change": round(delta, 2),
                        "change_pct": None,
                        "share": round(abs(delta) / total_move * 100, 1),
                        "direction": "up" if delta > 0 else "down",
                        # The segment's own rate, which is what a reader acts on.
                        "own_now": (
                            round(num_now.get(label, 0.0) / own_now * 100, 1)
                            if own_now
                            else None
                        ),
                        "own_before": (
                            round(num_before.get(label, 0.0) / own_before * 100, 1)
                            if own_before
                            else None
                        ),
                    }
                )
            if not drivers:
                continue
            best = {
                "dimension": canonical,
                "column": column,
                "concentration": concentration,
                "drivers": drivers,
                # Denominator totals, so "stopped contributing" keeps meaning
                # "recorded no revenue" rather than "had no margin".
                "current_totals": den_now,
                "previous_totals": den_before,
            }

    if best is None:
        return None
    if best["concentration"] < _MIN_CONCENTRATION:
        return best if best["drivers"] else None
    return best


def attribute_change(
    dataset: Dataset,
    index: TimeIndex,
    measure: str,
    current_key: str,
    previous_key: str,
    *,
    max_drivers: int = 4,
) -> dict[str, Any] | None:
    """Find the dimension that best explains the move, with per-segment deltas.

    Picks the dimension that concentrates the movement most tightly — the one
    where a couple of segments account for most of it — because that is the
    dimension a reader can act on.
    """
    best: dict[str, Any] | None = None

    for canonical in DIMENSION_FIELDS:
        column = dataset.column_for(canonical)
        if not column:
            continue

        current = _totals_for_bucket(dataset, index, column, measure, current_key)
        previous = _totals_for_bucket(dataset, index, column, measure, previous_key)
        labels = set(current) | set(previous)
        if len(labels) < 2 or len(labels) > 200:
            continue

        deltas = [
            (label, current.get(label, 0.0) - previous.get(label, 0.0)) for label in labels
        ]
        total_move = sum(abs(d) for _, d in deltas)
        if total_move <= 0:
            continue

        deltas.sort(key=lambda item: abs(item[1]), reverse=True)
        top_two = sum(abs(d) for _, d in deltas[:2])
        concentration = top_two / total_move

        if best is None or concentration > best["concentration"]:
            drivers = []
            for label, delta in deltas[:max_drivers]:
                if delta == 0:
                    continue
                prev_value = previous.get(label, 0.0)
                drivers.append(
                    {
                        "dimension": canonical,
                        "label": label,
                        "current": round(current.get(label, 0.0), 2),
                        "previous": round(prev_value, 2),
                        "change": round(delta, 2),
                        "change_pct": (
                            round(p, 1) if (p := _pct(current.get(label, 0.0), prev_value)) is not None else None
                        ),
                        "share": round(abs(delta) / total_move * 100, 1),
                        "direction": "up" if delta > 0 else "down",
                    }
                )
            if not drivers:
                continue
            best = {
                "dimension": canonical,
                "column": column,
                "concentration": concentration,
                "drivers": drivers,
                "current_totals": current,
                "previous_totals": previous,
            }

    if best is None or best["concentration"] < _MIN_CONCENTRATION:
        return best if best and best["drivers"] else None
    return best


# ---------------------------------------------------------------------------
# Supporting factors
# ---------------------------------------------------------------------------


def _bucket_sum(
    dataset: Dataset, index: TimeIndex, column: str, bucket_key: str
) -> float | None:
    seen = False
    total = 0.0
    for row, key in zip(dataset.rows, index.row_bucket, strict=False):
        if key != bucket_key:
            continue
        value = to_number(row.get(column))
        if value is None:
            continue
        seen = True
        total += value
    return total if seen else None


def _bucket_rows(index: TimeIndex, bucket_key: str) -> int:
    return sum(1 for key in index.row_bucket if key == bucket_key)


def _margin_factor(
    dataset: Dataset,
    index: TimeIndex,
    measure_label: str,
    current_key: str,
    previous_key: str,
) -> dict[str, Any] | None:
    """Did cost move with revenue, or against it?

    Margin is always revenue against cost, whichever measure the question was
    about — asking why profit moved makes the cost side more relevant, not less.
    """
    if measure_label not in ("revenue", "profit"):
        return None
    revenue_col = dataset.column_for("Revenue")
    cost_col = dataset.column_for("Cost")
    if not revenue_col or not cost_col:
        return None

    current = _bucket_sum(dataset, index, revenue_col, current_key)
    previous = _bucket_sum(dataset, index, revenue_col, previous_key)
    cost_now = _bucket_sum(dataset, index, cost_col, current_key)
    cost_before = _bucket_sum(dataset, index, cost_col, previous_key)
    if None in (current, previous, cost_now, cost_before) or previous <= 0 or current <= 0:
        return None

    margin_now = (current - cost_now) / current * 100
    margin_before = (previous - cost_before) / previous * 100
    cost_pct = _pct(cost_now, cost_before)
    detail = (
        f"Cost moved {_signed(cost_now - cost_before)}"
        + (f" ({cost_pct:+.0f}%)" if cost_pct is not None else "")
        + f", so margin went from {margin_before:.0f}% to {margin_now:.0f}%."
    )
    return {
        "kind": "margin",
        "detail": detail,
        "margin_now": round(margin_now, 1),
        "margin_before": round(margin_before, 1),
        "cost_change": round(cost_now - cost_before, 2),
        "cost_direction": "up" if cost_now > cost_before else "down",
        "squeezed": margin_now < margin_before,
    }


def _margin_mechanics_factor(
    dataset: Dataset,
    index: TimeIndex,
    spec: MeasureSpec,
    current_key: str,
    previous_key: str,
) -> dict[str, Any] | None:
    """Why the margin itself moved: which side of the ratio outgrew the other.

    A margin only moves when revenue and cost grow at different rates. Naming
    which one ran ahead is the mechanism — everything else is where it happened.
    """
    if not spec.is_ratio:
        return None
    revenue_col = dataset.column_for("Revenue")
    cost_col = dataset.column_for("Cost")
    if not revenue_col or not cost_col:
        return None

    revenue_now = _bucket_sum(dataset, index, revenue_col, current_key)
    revenue_before = _bucket_sum(dataset, index, revenue_col, previous_key)
    cost_now = _bucket_sum(dataset, index, cost_col, current_key)
    cost_before = _bucket_sum(dataset, index, cost_col, previous_key)
    if None in (revenue_now, revenue_before, cost_now, cost_before):
        return None
    revenue_pct = _pct(revenue_now, revenue_before)
    cost_pct = _pct(cost_now, cost_before)
    if revenue_pct is None or cost_pct is None:
        return None

    if cost_pct > revenue_pct:
        mechanism = "cost outgrew revenue, which is what pulled the margin down"
    elif cost_pct < revenue_pct:
        mechanism = "revenue outgrew cost, which is what lifted the margin"
    else:
        mechanism = "cost and revenue moved together, leaving the margin unchanged"

    return {
        "kind": "margin_mechanics",
        "detail": (
            f"Revenue moved {_signed(revenue_now - revenue_before)} ({revenue_pct:+.0f}%) "
            f"and cost {_signed(cost_now - cost_before)} ({cost_pct:+.0f}%), so {mechanism}."
        ),
        "revenue_change_pct": round(revenue_pct, 1),
        "cost_change_pct": round(cost_pct, 1),
        "cost_outgrew_revenue": cost_pct > revenue_pct,
    }


def _price_volume_factor(
    dataset: Dataset,
    index: TimeIndex,
    measure_label: str,
    current_key: str,
    previous_key: str,
    current: float,
    previous: float,
) -> dict[str, Any] | None:
    """Split a revenue move into how much was sold and what it sold for.

    Δrevenue = (Δunits × old price) + (Δprice × new units), which sums exactly
    to the observed change — so neither half is an estimate.
    """
    if measure_label != "revenue":
        return None
    qty_col = dataset.column_for("Quantity")
    if not qty_col:
        return None
    qty_now = _bucket_sum(dataset, index, qty_col, current_key)
    qty_before = _bucket_sum(dataset, index, qty_col, previous_key)
    if not qty_now or not qty_before:
        return None

    price_before = previous / qty_before
    price_now = current / qty_now
    volume_effect = (qty_now - qty_before) * price_before
    price_effect = (price_now - price_before) * qty_now
    dominant = "volume" if abs(volume_effect) >= abs(price_effect) else "price"

    if dominant == "volume":
        detail = (
            f"Units sold went {_signed(qty_now - qty_before)} "
            f"({qty_before:,.0f} to {qty_now:,.0f}), worth {_signed(volume_effect)} of the move; "
            f"average price accounts for {_signed(price_effect)}."
        )
    else:
        detail = (
            f"Average price went from {_fmt(price_before)} to {_fmt(price_now)}, "
            f"worth {_signed(price_effect)} of the move; "
            f"units sold account for {_signed(volume_effect)}."
        )
    return {
        "kind": "price_volume",
        "detail": detail,
        "dominant": dominant,
        "volume_effect": round(volume_effect, 2),
        "price_effect": round(price_effect, 2),
        "units_now": round(qty_now, 2),
        "units_before": round(qty_before, 2),
    }


def _churn_factor(attribution: dict[str, Any] | None) -> dict[str, Any] | None:
    """Segments that contributed last period and nothing at all this period."""
    if not attribution:
        return None
    current = attribution["current_totals"]
    previous = attribution["previous_totals"]
    gone = [
        (label, value)
        for label, value in previous.items()
        if value > 0 and current.get(label, 0.0) == 0
    ]
    if not gone:
        return None
    gone.sort(key=lambda kv: kv[1], reverse=True)
    named = ", ".join(f"{label} ({_fmt(value)})" for label, value in gone[:3])
    dimension = str(attribution["dimension"]).lower()
    return {
        "kind": "churn",
        "detail": (
            f"{len(gone)} {dimension} value(s) recorded nothing this period "
            f"after contributing last period: {named}."
        ),
        "labels": [label for label, _ in gone[:3]],
        "lost_value": round(sum(v for _, v in gone), 2),
    }


def _coverage_factor(
    index: TimeIndex, current_key: str, previous_key: str
) -> dict[str, Any] | None:
    """Warn when the latest period simply has less data in it than the last.

    A month that is only half over looks like a collapse. Saying so is the
    difference between a real finding and a false alarm.
    """
    rows_now = _bucket_rows(index, current_key)
    rows_before = _bucket_rows(index, previous_key)
    if rows_before <= 0 or rows_now == 0:
        return None
    ratio = rows_now / rows_before
    if ratio >= 0.6:
        return None
    return {
        "kind": "coverage",
        "detail": (
            f"The latest {index.unit_label} holds {rows_now:,} record(s) against "
            f"{rows_before:,} in the previous one, so it may be incomplete rather "
            "than genuinely down."
        ),
        "rows_now": rows_now,
        "rows_before": rows_before,
        "partial": True,
    }


def _baseline_factor(
    totals: dict[str, float], keys: list[str], current: float, unit: str = ""
) -> dict[str, Any] | None:
    """Place the latest period against the trailing average, not just last period."""
    history = [totals[k] for k in keys[:-1]]
    if len(history) < 2:
        return None
    baseline = sum(history) / len(history)
    # A rate moves in points against its baseline. "40% above a 40% margin" is
    # a number nobody can act on.
    if unit == "%":
        gap, change = current - baseline, None
    else:
        change = _pct(current, baseline)
        if change is None:
            return None
        gap = None
    return {
        "kind": "baseline",
        "detail": (
            f"Against the {len(history)}-period trailing average of "
            f"{_fmt_unit(baseline, unit)}, the latest period is "
            + (f"{_signed_unit(gap, unit)}." if unit == "%" else f"{change:+.0f}%.")
        ),
        "baseline": round(baseline, 2),
        "change_pct": round(change, 1) if change is not None else None,
        "change_points": round(gap, 2) if gap is not None else None,
    }


# ---------------------------------------------------------------------------
# The diagnosis
# ---------------------------------------------------------------------------


def diagnose(
    dataset: Dataset,
    question: str,
    *,
    previous_question: str | None = None,
    history: list[str] | None = None,
) -> dict[str, Any] | None:
    """Explain how the measure in `question` moved, and what moved it.

    Returns None when the data cannot support a diagnosis - no date column, no
    measure, or a single period to compare. The caller falls back to the normal
    query path rather than inventing an explanation.
    """
    dataset = ensure_profit(ensure_mapping(dataset))

    date_col = dataset.column_for("Date", "Timestamp")
    if not date_col:
        return None

    # The current question wins, then the chat's own history newest-first: a
    # thread that has moved from revenue to margin is asking about margin now.
    spec = resolve_measure_spec(dataset, question, *(history or []), previous_question)
    if not spec:
        return None
    measure_label = spec.label

    # Not `build_time_index`: that one buckets for a readable trend line, which
    # on a short span is one point per day. Comparing the last two of those
    # compares two trading days, not two periods.
    index = build_comparison_index(dataset, date_col)
    if index is None or len(index.buckets) < 2:
        return None

    if spec.is_ratio:
        totals = bucket_ratios(dataset, index, spec)
        periods = [b for b in index.buckets if b.key in totals]
    else:
        totals = bucket_totals(dataset, index, spec.column)
        periods = list(index.buckets)
    if len(periods) < 2:
        return None

    keys = [b.key for b in periods]
    current_key, previous_key = keys[-1], keys[-2]
    current, previous = totals[current_key], totals[previous_key]
    if current == 0 and previous == 0:
        return None

    change = current - previous
    # A rate moves in percentage points. The percent change *of* a percentage
    # ("margin fell 136%") is a number no one can act on, so it is not reported.
    change_pct = None if spec.is_ratio else _pct(current, previous)
    direction = "flat" if abs(change) < 1e-9 else ("down" if change < 0 else "up")

    if spec.is_ratio:
        attribution = attribute_ratio_change(dataset, index, spec, current_key, previous_key)
    else:
        attribution = attribute_change(dataset, index, spec.column, current_key, previous_key)

    factors: list[dict[str, Any]] = []
    for factor in (
        _coverage_factor(index, current_key, previous_key),
        _margin_mechanics_factor(dataset, index, spec, current_key, previous_key),
        _price_volume_factor(
            dataset, index, measure_label, current_key, previous_key, current, previous
        ),
        _margin_factor(dataset, index, measure_label, current_key, previous_key),
        _churn_factor(attribution),
        _baseline_factor(totals, keys, current, spec.unit),
    ):
        if factor:
            factors.append(factor)

    series = [
        {"period": bucket.label, "value": round(totals[bucket.key], 2)}
        for bucket in periods
    ]

    return {
        "measure": spec.column or f"{spec.numerator} / {spec.denominator}",
        "measure_label": measure_label,
        "measure_kind": spec.kind,
        "unit": spec.unit,
        "measure_matched": spec.matched,
        "direction": direction,
        "current": round(current, 2),
        "previous": round(previous, 2),
        "change": round(change, 2),
        "change_pct": round(change_pct, 1) if change_pct is not None else None,
        "period_label": periods[-1].label,
        "previous_label": periods[-2].label,
        "granularity": index.granularity,
        "dimension": attribution["dimension"] if attribution else None,
        "concentration": (
            round(attribution["concentration"] * 100, 1) if attribution else None
        ),
        "drivers": attribution["drivers"] if attribution else [],
        "factors": factors,
        "series": series,
        "rows_analyzed": len(dataset.rows),
        "truncated": dataset.truncated,
    }


# ---------------------------------------------------------------------------
# Deterministic narrative - used when no model is configured, and as the
# fallback whenever the model call fails.
# ---------------------------------------------------------------------------


#: Said when the question named something the data does not measure. Without
#: it, "how do we reduce churn" comes back as revenue advice that never
#: mentions churn — the same failure the SQL path guards with UNTARGETED.
UNMEASURED_PREFIX = (
    "This data does not carry a figure for what you asked about, so I cannot "
    "answer that question directly from it. What it does show is this:"
)


def render_diagnosis(diagnosis: dict[str, Any], *, source_name: str | None = None) -> str:
    measure = diagnosis["measure_label"]
    where = f" in {source_name}" if source_name else ""
    unit = diagnosis.get("unit", "")
    change_pct = diagnosis["change_pct"]
    pct_text = f" ({change_pct:+.0f}%)" if change_pct is not None else ""

    if diagnosis["direction"] == "flat":
        lead = (
            f"{measure.capitalize()}{where} held steady at "
            f"{_fmt_unit(diagnosis['current'], unit)} in {diagnosis['period_label']}, "
            f"level with {diagnosis['previous_label']}."
        )
    else:
        verb = "fell" if diagnosis["direction"] == "down" else "rose"
        lead = (
            f"{measure.capitalize()}{where} {verb} from "
            f"{_fmt_unit(diagnosis['previous'], unit)} in {diagnosis['previous_label']} to "
            f"{_fmt_unit(diagnosis['current'], unit)} in {diagnosis['period_label']}, "
            f"a move of {_signed_unit(diagnosis['change'], unit)}{pct_text}."
        )

    sentences = [lead]

    drivers = diagnosis.get("drivers") or []
    if drivers and diagnosis.get("dimension"):
        dimension = str(diagnosis["dimension"]).lower()
        same_way = [d for d in drivers if d["direction"] == diagnosis["direction"]]
        listed = (same_way or drivers)[:2]
        parts = [
            f"{d['label']} ({_signed_unit(d['change'], unit)}, "
            f"{d['share']:.0f}% of the movement)"
            for d in listed
        ]
        sentences.append(f"The move is concentrated by {dimension}: {', '.join(parts)}.")
        # For a rate the driver figure is a contribution, not the segment's own
        # rate. Saying which is which is the difference between a reader
        # trusting the number and misreading it.
        if unit == "%":
            own = [d for d in listed if d.get("own_before") is not None and d.get("own_now") is not None]
            if own:
                sentences.append(
                    "Those are contributions to the blended figure; on its own, "
                    + ", ".join(
                        f"{d['label']} went from {d['own_before']:,.1f}% to {d['own_now']:,.1f}%"
                        for d in own[:2]
                    )
                    + "."
                )
        offset = [d for d in drivers if d["direction"] != diagnosis["direction"]]
        if offset:
            best = offset[0]
            sentences.append(
                f"Working the other way, {best['label']} moved "
                f"{_signed_unit(best['change'], unit)}."
            )

    for factor in diagnosis.get("factors", [])[:2]:
        sentences.append(factor["detail"])

    if not diagnosis.get("measure_matched", True):
        sentences.insert(0, UNMEASURED_PREFIX)

    return " ".join(sentences)


def render_advice(
    diagnosis: dict[str, Any],
    recommendations: list[dict[str, str]],
    *,
    source_name: str | None = None,
) -> str:
    """The diagnosis, then the first thing to do about it.

    Someone who asked what to do should be told, not handed a description and
    left to draw the conclusion.
    """
    text = render_diagnosis(diagnosis, source_name=source_name)
    first = next((r for r in recommendations if r["priority"] == "now"), None)
    first = first or (recommendations[0] if recommendations else None)
    if first:
        text += f" Start with “{first['title']}”: {first['detail']}"
    return text


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------


def _recommendation(
    title: str, detail: str, basis: str, priority: str, *, kind: str
) -> dict[str, str]:
    return {
        "title": title,
        "detail": detail,
        "basis": basis,
        "priority": priority,
        "kind": kind,
    }


def build_recommendations(diagnosis: dict[str, Any]) -> list[dict[str, str]]:
    """Actions the evidence supports, each tied to the figure that prompted it.

    These are analyst-standard responses to a specific, measured pattern - not
    a guess at the business's strategy. Every one names the number behind it so
    a reader can judge it for themselves.
    """
    out: list[dict[str, str]] = []
    measure = diagnosis["measure_label"]
    direction = diagnosis["direction"]
    factors = {f["kind"]: f for f in diagnosis.get("factors", [])}
    drivers = diagnosis.get("drivers") or []
    dimension = str(diagnosis.get("dimension") or "").lower()
    unit = diagnosis.get("unit", "")

    # Advice about the wrong subject is worse than none. When the question named
    # something the data does not measure, the first action is to make it
    # measurable — everything below is about a different figure.
    if not diagnosis.get("measure_matched", True):
        out.append(
            _recommendation(
                "Connect the data this question needs",
                "The subject of your question is not measured in the connected data, "
                f"so the only figure available is {measure}. Add or map the column "
                "that records it, then ask again — the actions below are about "
                f"{measure}, not about what you asked.",
                f"No column on this source maps to the subject of the question; "
                f"{measure} was used as the headline figure instead.",
                "now",
                kind="coverage_gap",
            )
        )

    # An incomplete latest period outranks everything: fix the data first.
    if factors.get("coverage"):
        out.append(
            _recommendation(
                "Confirm the period is complete before acting",
                "Check whether the latest period has finished loading. Re-run this "
                "question once the data is in; a partial period reads as a collapse.",
                factors["coverage"]["detail"],
                "now",
                kind="data_quality",
            )
        )

    losing = [d for d in drivers if d["direction"] == "down"]
    gaining = [d for d in drivers if d["direction"] == "up"]

    if direction == "down" and losing:
        worst = losing[0]
        out.append(
            _recommendation(
                f"Recover {worst['label']}",
                f"{worst['label']} is the largest single contributor to the fall. Review what "
                "changed there this period - demand, availability, pricing, staffing or a lost "
                f"account - before spreading effort across the rest of the "
                f"{dimension or 'business'}.",
                f"{worst['label']} moved {_signed_unit(worst['change'], unit)}, "
                f"{worst['share']:.0f}% of the total movement.",
                "now",
                kind="driver",
            )
        )
        if len(losing) > 1:
            second = losing[1]
            out.append(
                _recommendation(
                    f"Check whether {second['label']} shares the same cause",
                    f"{second['label']} moved the same way. If both fell for one reason, fix "
                    "that reason once; if not, they need separate responses.",
                    f"{second['label']} moved {_signed_unit(second['change'], unit)} "
                    f"({second['share']:.0f}% of the movement).",
                    "next",
                    kind="driver",
                )
            )

    churn = factors.get("churn")
    if churn:
        out.append(
            _recommendation(
                "Re-engage what stopped contributing",
                "These recorded nothing at all this period. Confirm whether they were lost or "
                "simply not reported, then win back the ones that were lost.",
                churn["detail"],
                "now",
                kind="churn",
            )
        )

    price_volume = factors.get("price_volume")
    if price_volume and direction == "down":
        if price_volume["dominant"] == "volume":
            out.append(
                _recommendation(
                    "Rebuild volume, not price",
                    "The shortfall came from selling fewer units rather than selling cheaper. "
                    "Look at demand generation, stock availability and lost baskets before "
                    "discounting, which would deepen the gap.",
                    price_volume["detail"],
                    "now",
                    kind="price_volume",
                )
            )
        else:
            out.append(
                _recommendation(
                    "Review price realisation",
                    "Units held up but the average price fell, which points to discounting, "
                    "mix shifting to cheaper lines, or unapproved markdowns. Audit the "
                    "discounts applied this period.",
                    price_volume["detail"],
                    "now",
                    kind="price_volume",
                )
            )

    mechanics = factors.get("margin_mechanics")
    if mechanics and direction == "down":
        if mechanics["cost_outgrew_revenue"]:
            out.append(
                _recommendation(
                    "Close the gap between cost and revenue growth",
                    "Cost is growing faster than revenue, which is the whole of the "
                    "margin move. Separate input cost from discounting before choosing "
                    "a response — they need opposite fixes.",
                    mechanics["detail"],
                    "now",
                    kind="margin",
                )
            )
        else:
            out.append(
                _recommendation(
                    "Check the mix, not the rates",
                    "Revenue outgrew cost, so the blended margin fell because the mix "
                    "shifted towards thinner-margin lines. Confirm which lines gained "
                    "share before treating this as a cost problem.",
                    mechanics["detail"],
                    "now",
                    kind="margin_mix",
                )
            )

    margin = factors.get("margin")
    if margin and margin.get("squeezed"):
        cause = (
            "Cost rose while revenue did not"
            if margin.get("cost_direction") == "up"
            else "Cost did not fall as fast as revenue"
        )
        out.append(
            _recommendation(
                "Protect the margin",
                f"{cause}, so every unit now earns less. Re-open supplier terms and hold "
                "discretionary spend until the trend turns.",
                margin["detail"],
                "next",
                kind="margin",
            )
        )

    if direction == "up" and gaining:
        best = gaining[0]
        out.append(
            _recommendation(
                f"Repeat what worked in {best['label']}",
                "Establish whether the gain is repeatable or one-off, then apply the same "
                f"change to the rest of the {dimension or 'business'} while it still counts.",
                f"{best['label']} moved {_signed_unit(best['change'], unit)}, "
                f"{best['share']:.0f}% of the total movement.",
                "now",
                kind="driver",
            )
        )

    if direction == "down" and gaining:
        best = gaining[0]
        out.append(
            _recommendation(
                f"Borrow from {best['label']}",
                f"{best['label']} grew while the rest fell. Find out what it did differently "
                "and apply it to the segments that dropped.",
                f"{best['label']} moved {_signed_unit(best['change'], unit)} against the trend.",
                "next",
                kind="offset",
            )
        )

    guard_dimension = dimension or "segment"
    out.append(
        _recommendation(
            f"Watch {measure} by {guard_dimension} on a shorter cycle",
            f"Track {measure} per {guard_dimension} every {diagnosis['granularity']} and set "
            "an alert on a repeat move of this size, so the next one surfaces while it can "
            "still be acted on.",
            f"{measure.capitalize()} moved {_signed_unit(diagnosis['change'], unit)} in one "
            f"{diagnosis['granularity']}.",
            "watch",
            kind="monitoring",
        )
    )

    return out[:5]


# ---------------------------------------------------------------------------
# Optional LLM pass
#
# The model never sees raw rows here and never computes anything. It receives
# the evidence this module measured and writes it up - so a wrong number is
# impossible, and the deterministic version below is always a valid fallback.
# ---------------------------------------------------------------------------

DIAGNOSTIC_SYSTEM = """You are a business intelligence analyst explaining a change in a metric.

You are given EVIDENCE that was computed from the customer's own data: a period
comparison, the segments that moved, and supporting factors. Write the answer.

Rules:
- Use ONLY figures that appear in the evidence. Never invent, extrapolate, or
  bring in outside knowledge about the industry.
- Lead with the direct answer: what moved, by how much, and what moved it.
- Name the segments that drove it and how much of the movement each accounts for.
- Where the evidence shows a mechanism (price vs volume, margin, a segment that
  stopped contributing, an incomplete period), say so.
- Be explicit that these are the segments the change is concentrated in. The data
  shows WHERE the change happened; it does not prove WHY. Do not state a business
  cause as fact - suggest what to check.
- If the evidence says nothing in the question named the measure, open by saying
  the data cannot answer that question, then give what it does show. Never let a
  fallback figure stand in for a subject the data does not measure.
- 3-5 sentences. Plain English. No markdown, no bullets, no preamble.
"""

ADVISORY_SYSTEM = """You are a business intelligence analyst advising on what to do next.

You are given EVIDENCE computed from the customer's own data, and a set of
CANDIDATE ACTIONS derived from it. Reply with STRICT JSON, no markdown fences:

{"answer": "<3-5 sentences>", "recommendations": [{"title": "<max 8 words>",
"detail": "<1-2 sentences on what to do>", "basis": "<the figure that justifies it>",
"priority": "now|next|watch"}]}

Rules:
- Use ONLY figures from the evidence. Never invent numbers or outside facts.
- The answer states what happened and what the priority response is.
- Give 3 to 5 recommendations, most urgent first. Each must be an action someone
  can take, and each "basis" must quote a figure from the evidence.
- Keep, merge or sharpen the candidate actions; drop any the evidence does not
  support. Do not recommend anything the evidence cannot justify.
- Never claim to know the cause. Recommend what to check, fix, or watch.
- If the evidence says nothing in the question named the measure, the first
  sentence of "answer" must say the data cannot answer that question, and the
  recommendations must be about the figures you were given - never dressed up as
  advice on the subject that was asked about.
"""


def build_evidence_prompt(
    question: str,
    diagnosis: dict[str, Any],
    *,
    source_name: str | None = None,
    currency: str | None = None,
    candidates: list[dict[str, str]] | None = None,
    context_block: str | None = None,
) -> str:
    lines = [f"Question: {question}"]
    # "What should we do about it?" only means something against the turn
    # before it. The evidence below is still the only source of figures.
    if context_block and context_block.strip():
        lines.extend(["", context_block.strip(), ""])
    if source_name:
        lines.append(f"Data source: {source_name}")
    if currency:
        lines.append(
            f"Currency: {currency}. Write money amounts in {currency}; "
            "never use a different currency symbol."
        )

    change_pct = diagnosis["change_pct"]
    unit = diagnosis.get("unit", "")
    lines.append("")
    lines.append("EVIDENCE")
    lines.append(f"Measure: {diagnosis['measure_label']} (column {diagnosis['measure']})")
    if not diagnosis.get("measure_matched", True):
        lines.append(
            "IMPORTANT: nothing in the question named this measure. It is the "
            "headline figure on this data, chosen because the subject of the "
            "question is not measured here at all. Your answer MUST open by "
            "saying plainly that the data cannot answer the question that was "
            "asked, and must not imply the figures below are about that subject."
        )
    if unit == "%":
        lines.append(
            "This measure is a RATE, computed from each period's totals. It moves in "
            "percentage points, never in percent or in currency. Never total it across "
            "periods or segments."
        )
    lines.append(
        f"Latest period {diagnosis['period_label']}: {_fmt_unit(diagnosis['current'], unit)}; "
        f"previous period {diagnosis['previous_label']}: "
        f"{_fmt_unit(diagnosis['previous'], unit)}; "
        f"change {_signed_unit(diagnosis['change'], unit)}"
        + (f" ({change_pct:+.1f}%)" if change_pct is not None else "")
    )
    lines.append(f"Period granularity: {diagnosis['granularity']}")

    series = diagnosis.get("series") or []
    if series:
        recent = series[-8:]
        lines.append(
            "Series (oldest first): "
            + ", ".join(
                f"{point['period']}={_fmt_unit(point['value'], unit)}" for point in recent
            )
        )

    drivers = diagnosis.get("drivers") or []
    if drivers:
        lines.append(
            f"Segments by {diagnosis['dimension']} "
            f"(this dimension holds {diagnosis['concentration']:.0f}% of the movement "
            "in its top two segments):"
        )
        if unit == "%":
            lines.append(
                "  Each segment's figures below are its CONTRIBUTION to the blended "
                "rate in percentage points, which is why they sum to the total move. "
                "'own rate' is that segment's rate measured on its own."
            )
        for driver in drivers:
            pct = driver["change_pct"]
            own = ""
            if driver.get("own_before") is not None and driver.get("own_now") is not None:
                own = (
                    f"; own rate {driver['own_before']:,.1f}% -> {driver['own_now']:,.1f}%"
                )
            lines.append(
                f"- {driver['label']}: {_fmt_unit(driver['previous'], unit)} -> "
                f"{_fmt_unit(driver['current'], unit)}, "
                f"change {_signed_unit(driver['change'], unit)}"
                + (f" ({pct:+.0f}%)" if pct is not None else "")
                + f", {driver['share']:.0f}% of the total movement"
                + own
            )
    else:
        lines.append("No dimension concentrated the movement; it is spread across segments.")

    factors = diagnosis.get("factors") or []
    if factors:
        lines.append("Supporting factors:")
        for factor in factors:
            lines.append(f"- {factor['detail']}")

    lines.append(
        f"Rows analysed: {diagnosis['rows_analyzed']:,}"
        + (" (source truncated to this sample)" if diagnosis.get("truncated") else "")
    )

    if candidates:
        lines.append("")
        lines.append("CANDIDATE ACTIONS")
        for item in candidates:
            lines.append(
                f"- [{item['priority']}] {item['title']}: {item['detail']} "
                f"(basis: {item['basis']})"
            )

    return "\n".join(lines)


_PRIORITIES = ("now", "next", "watch")


def parse_advisory_json(content: str) -> tuple[str | None, list[dict[str, str]]]:
    """Read the model's JSON reply. Returns (answer, recommendations).

    Anything malformed yields empty values so the caller falls back to the
    deterministic write-up rather than showing the user broken output.
    """
    import json

    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE)
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None, []
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        return None, []
    if not isinstance(data, dict):
        return None, []

    answer = data.get("answer")
    answer = answer.strip() if isinstance(answer, str) and answer.strip() else None

    out: list[dict[str, str]] = []
    for raw in data.get("recommendations") or []:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title", "")).strip()
        detail = str(raw.get("detail", "")).strip()
        if not title or not detail:
            continue
        priority = str(raw.get("priority", "next")).strip().lower()
        out.append(
            {
                "title": title[:120],
                "detail": detail,
                "basis": str(raw.get("basis", "")).strip(),
                "priority": priority if priority in _PRIORITIES else "next",
                "kind": "model",
            }
        )
    return answer, out[:5]


def diagnosis_result_payload(diagnosis: dict[str, Any]) -> dict[str, Any]:
    """The series behind the diagnosis, shaped like any other query result.

    Charting, the rows table and CSV export all read this shape, so a diagnostic
    answer supports the same follow-through as a normal one.
    """
    measure = diagnosis["measure_label"].replace(" ", "_")
    # A rate is charted on its own axis and never totalled; the name is what
    # tells the chart and the table which it is.
    if diagnosis.get("unit") == "%" and not measure.endswith("_pct"):
        measure = f"{measure}_pct"
    return {
        "columns": ["period", measure],
        "rows": [
            {"period": point["period"], measure: point["value"]}
            for point in diagnosis.get("series", [])
        ],
        "sql": None,
    }


# ---------------------------------------------------------------------------
# When a full diagnosis is impossible
#
# No date column, one period, no mapped measure — the change cannot be
# measured. That is an answer in itself, and the data still has something to
# say. Rather than dropping back to "write a SELECT and summarise it", which is
# what returned nothing in the first place, the question goes to the model with
# whatever comparison the data does support, plus a plain statement of what is
# missing.
# ---------------------------------------------------------------------------

PARTIAL_SYSTEM = """You are a business intelligence analyst.

The user asked why something changed. The EVIDENCE below is everything their
data can actually support — and it names what is missing, so the comparison
they asked for cannot be computed.

Rules:
- Open by saying plainly what cannot be answered and why, in one sentence.
- Then give what the data does show, using ONLY figures from the evidence.
- Never invent numbers, causes, periods, or outside facts.
- Close with the one thing that would make the question answerable (a date
  column, a second period of data, a mapped revenue field — whatever is named
  in the limitations).
- 3-5 sentences. Plain English. No markdown, no bullets, no preamble.
"""


def build_partial_context(
    dataset: Dataset,
    question: str,
    *,
    previous_question: str | None = None,
    history: list[str] | None = None,
    max_labels: int = 8,
) -> dict[str, Any] | None:
    """What the data can show about the question, and what it cannot.

    Returns None only for an empty dataset — anything with rows in it has
    something honest to report.
    """
    dataset = ensure_profit(ensure_mapping(dataset))
    if not dataset.rows:
        return None

    limits: list[str] = []
    resolved = resolve_measure(dataset, question, *(history or []), previous_question)
    measure_col, measure_label = resolved if resolved else (None, None)
    if not resolved:
        limits.append(
            "No revenue, profit, cost or quantity column is mapped on this source, "
            "so there is no figure to compare."
        )

    date_col = dataset.column_for("Date", "Timestamp")
    index = build_time_index(dataset, date_col) if date_col else None
    series: list[dict[str, Any]] = []
    period_span: str | None = None

    if not date_col:
        limits.append(
            "This source has no date or timestamp column, so movement over time "
            "cannot be measured."
        )
    elif index is None:
        limits.append(
            f"The values in {date_col} could not be read as dates, so periods "
            "cannot be compared."
        )
    else:
        period_span = f"{index.min_date.isoformat()} to {index.max_date.isoformat()}"
        if len(index.buckets) < 2:
            limits.append(
                f"All the data falls in one {index.granularity} "
                f"({index.buckets[0].label}), so there is no earlier period to "
                "compare it against."
            )
        if measure_col:
            totals = bucket_totals(dataset, index, measure_col)
            series = [
                {"period": bucket.label, "value": round(totals[bucket.key], 2)}
                for bucket in index.buckets
            ]

    breakdown: dict[str, Any] | None = None
    if measure_col:
        for canonical in DIMENSION_FIELDS:
            column = dataset.column_for(canonical)
            if not column:
                continue
            totals: dict[str, float] = {}
            for row in dataset.rows:
                label = str(row.get(column, "")).strip()
                value = to_number(row.get(measure_col))
                if not label or value is None:
                    continue
                totals[label] = totals.get(label, 0.0) + value
            if len(totals) < 2:
                continue
            ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
            breakdown = {
                "dimension": canonical,
                "rows": [
                    {"label": label, "value": round(value, 2)}
                    for label, value in ranked[:max_labels]
                ],
                "total": round(sum(totals.values()), 2),
            }
            break

    if measure_col and not breakdown:
        limits.append(
            "No segment column (region, product, store, category…) is mapped, so "
            "the figure cannot be broken down."
        )

    return {
        "measure_label": measure_label,
        "measure": measure_col,
        "limits": limits,
        "series": series,
        "breakdown": breakdown,
        "period_span": period_span,
        "rows_analyzed": len(dataset.rows),
        "truncated": dataset.truncated,
    }


def build_partial_prompt(
    question: str,
    context: dict[str, Any],
    *,
    source_name: str | None = None,
    currency: str | None = None,
) -> str:
    lines = [f"Question: {question}"]
    if source_name:
        lines.append(f"Data source: {source_name}")
    if currency:
        lines.append(
            f"Currency: {currency}. Write money amounts in {currency}; "
            "never use a different currency symbol."
        )

    lines.append("")
    lines.append("EVIDENCE")
    lines.append(f"Rows analysed: {context['rows_analyzed']:,}")
    if context.get("measure_label"):
        lines.append(f"Measure asked about: {context['measure_label']}")
    if context.get("period_span"):
        lines.append(f"Data covers: {context['period_span']}")

    series = context.get("series") or []
    if series:
        lines.append(
            "Totals by period: "
            + ", ".join(f"{point['period']}={_fmt(point['value'])}" for point in series[-8:])
        )

    breakdown = context.get("breakdown")
    if breakdown:
        lines.append(
            f"Totals by {breakdown['dimension']} (whole dataset, "
            f"grand total {_fmt(breakdown['total'])}):"
        )
        for row in breakdown["rows"]:
            lines.append(f"- {row['label']}: {_fmt(row['value'])}")

    lines.append("")
    lines.append("LIMITATIONS")
    for limit in context.get("limits") or ["None."]:
        lines.append(f"- {limit}")

    return "\n".join(lines)


def render_partial(context: dict[str, Any], *, source_name: str | None = None) -> str:
    """The honest version of "I cannot tell you why", with what is there."""
    where = f" in {source_name}" if source_name else ""
    sentences: list[str] = []

    limits = context.get("limits") or []
    if limits:
        sentences.append(f"That change cannot be measured{where}: {limits[0][0].lower()}{limits[0][1:]}")
    else:
        sentences.append(f"There is no measurable movement to explain{where}.")

    series = context.get("series") or []
    measure = context.get("measure_label") or "the measure"
    if len(series) >= 2:
        sentences.append(
            f"By period, {measure} runs "
            + ", ".join(f"{point['period']} {_fmt(point['value'])}" for point in series[-4:])
            + "."
        )
    elif series:
        sentences.append(
            f"{measure.capitalize()} totals {_fmt(series[0]['value'])} in "
            f"{series[0]['period']}, the only period on file."
        )

    breakdown = context.get("breakdown")
    if breakdown and breakdown["rows"]:
        top = breakdown["rows"][0]
        sentences.append(
            f"By {str(breakdown['dimension']).lower()}, {top['label']} is largest at "
            f"{_fmt(top['value'])} of {_fmt(breakdown['total'])} total."
        )

    if len(limits) > 1:
        sentences.append(limits[1])

    return " ".join(sentences)


def partial_result_payload(context: dict[str, Any]) -> dict[str, Any]:
    """Whatever comparison exists, shaped like any other query result."""
    measure = (context.get("measure_label") or "value").replace(" ", "_")
    series = context.get("series") or []
    if series:
        return {
            "columns": ["period", measure],
            "rows": [{"period": p["period"], measure: p["value"]} for p in series],
            "sql": None,
        }

    breakdown = context.get("breakdown")
    if breakdown:
        label = str(breakdown["dimension"]).lower().replace(" ", "_")
        return {
            "columns": [label, measure],
            "rows": [{label: r["label"], measure: r["value"]} for r in breakdown["rows"]],
            "sql": None,
        }
    return {"columns": [], "rows": [], "sql": None}
