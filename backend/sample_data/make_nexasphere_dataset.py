"""Generate the NexaSphere demonstration dataset used for end-to-end testing.

The case study describes a multi-store retail business but ships no data large
enough to exercise the engine — the questions it asks are about trends,
attribution and rates, and none of those mean anything over a dozen rows.

So this writes six months of trading in the brief's exact schema, with a set of
patterns *deliberately planted* in it. That is the point of the file: because
the patterns are known in advance, the engine's output can be checked rather
than merely read. It is pointed at the CSV with no hint of what to look for, and
every figure it reports is compared against what was seeded here.

Deterministic by design (`random.seed(SEED)`), so the file it writes is
byte-identical on every run and on every machine. Regenerating it does not
invalidate a result recorded against it.

    python -m sample_data.make_nexasphere_dataset                # writes here
    python -m sample_data.make_nexasphere_dataset --out path.csv
    python -m sample_data.make_nexasphere_dataset --verify path.csv

WHAT IS PLANTED, AND WHAT THE ENGINE SHOULD FIND
------------------------------------------------------------------------------
1. Cost inflates ~3% a month while demand grows ~5.5%, so revenue rises every
   month and margin falls every month. This is the brief's headline risk, and it
   is invisible in a revenue total and in a profit total, because both go up.
   Expect: margin 37.6% in January to 26.8% in June.
2. One product line (Soundbar Pro) is returned at 31%; everything else at ~4.5%.
   Expect: it is named, at roughly 33%, against an ~8.6% overall rate.
3. One delivery partner (NaijaExpress) takes 6-11 days and is rated 2.1-3.2,
   against 1-4 days and 4.1-5.0 for the others.
   Expect: it is named on both delay and rating.
4. One store (Bodija) holds stock below its reorder level all half-year.
   Expect: it is named as below reorder level, 24 against 40.
5. Campaign budgets differ sharply in efficiency. Each budget is written on
   every row of its campaign, so a naive SUM multiplies it by the row count and
   destroys the ratio — this is what makes the row a real test.
   Expect: the budget counted once, and a wide spread between campaigns.
6. Store targets are set so several locations fall short.
   Expect: the shortfall reported against the latest period, not the half-year.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import random
from datetime import date, timedelta
from pathlib import Path

#: Fixed so the file is reproducible. Changing it changes every figure recorded
#: against this dataset, so treat it as part of the data, not a knob.
SEED = 20260827

#: The SHA-256 of the file this script produces. Checked by --verify, so a
#: reader can confirm the dataset behind a reported figure is the one they hold.
EXPECTED_SHA256 = "832e1fbc260fb7e8848dd90ba1c64d0d53a77058f66ca92bc04d5fff4ea59505"

START = date(2026, 1, 1)
DAYS = 181  # 1 January to 30 June inclusive

STORES = [("Ikeja", "Lagos"), ("Lekki", "Lagos"), ("Wuse", "Abuja"), ("Bodija", "Ibadan")]

#: (name, category, list price, cost as a fraction of price)
PRODUCTS = [
    ("Smart TV 55", "Electronics", 420_000, 0.62),
    ("Soundbar Pro", "Electronics", 145_000, 0.58),
    ("Laptop 14", "Electronics", 520_000, 0.70),
    ("Air Fryer XL", "Appliances", 98_000, 0.55),
    ("Washing Machine", "Appliances", 385_000, 0.66),
    ("Blender 900W", "Appliances", 42_000, 0.52),
    ("Office Chair", "Furniture", 76_000, 0.50),
    ("Standing Desk", "Furniture", 210_000, 0.60),
]

#: (campaign, total budget). The budget is repeated on every row of its campaign
#: — the grain trap described in the module docstring.
CAMPAIGNS = [("NewYear Blitz", 1_200_000), ("Eid Savings", 900_000), ("Back to School", 2_600_000)]

PARTNERS = ["SwiftLogix", "NaijaExpress", "CourierPlus"]
SEGMENTS = ["Retail", "SME", "Corporate"]
CHANNELS = ["Store", "Online", "Phone"]
STAFF = ["Adaobi Nwosu", "Emeka Obi", "Fatima Bello", "Tunde Alabi", "Ngozi Eze"]

TARGET = {"Ikeja": 42_000_000, "Lekki": 38_000_000, "Wuse": 35_000_000, "Bodija": 26_000_000}

#: Bodija runs below the reorder level of 40 for the whole period.
STOCK = {"Ikeja": 180, "Lekki": 165, "Wuse": 150, "Bodija": 24}
REORDER_LEVEL = 40

#: The planted anomalies, as probabilities and ranges rather than hard-coded
#: rows, so they read as a tendency in the data rather than a handful of
#: outliers a threshold could trivially catch.
RETURN_RATE_HIGH = 0.31  # Soundbar Pro
RETURN_RATE_BASE = 0.045  # everything else
SLOW_PARTNER = "NaijaExpress"

COLUMNS = [
    "order_date", "store", "region", "channel", "product", "category", "employee",
    "campaign", "marketing_spend", "units", "unit_price", "revenue", "cost",
    "returned", "delivery_partner", "delivery_days", "customer_rating",
    "customer_segment", "revenue_target", "stock_on_hand", "reorder_level",
]


def build_rows() -> list[dict]:
    rng = random.Random(SEED)
    rows: list[dict] = []

    for offset in range(DAYS):
        day = START + timedelta(days=offset)
        month = day.month

        # Cost outruns price month on month. Revenue still grows, because demand
        # grows faster — which is exactly what hides the margin problem.
        cost_drift = 1.0 + 0.030 * (month - 1)
        demand = 1.0 + 0.055 * (month - 1)
        campaign, budget = CAMPAIGNS[min((month - 1) // 2, 2)]

        for _ in range(rng.randint(2, 5)):
            store, region = rng.choice(STORES)
            product, category, price, cost_ratio = rng.choice(PRODUCTS)

            units = max(1, int(rng.gauss(3.2 * demand, 1.1)))
            unit_price = round(price * rng.uniform(0.94, 1.02))
            revenue = unit_price * units
            cost = round(revenue * cost_ratio * cost_drift)

            returned = rng.random() < (
                RETURN_RATE_HIGH if product == "Soundbar Pro" else RETURN_RATE_BASE
            )

            partner = rng.choice(PARTNERS)
            if partner == SLOW_PARTNER:
                days, rating = rng.randint(6, 11), round(rng.uniform(2.1, 3.2), 1)
            else:
                days, rating = rng.randint(1, 4), round(rng.uniform(4.1, 5.0), 1)

            rows.append(
                {
                    "order_date": day.isoformat(),
                    "store": store,
                    "region": region,
                    "channel": rng.choice(CHANNELS),
                    "product": product,
                    "category": category,
                    "employee": rng.choice(STAFF),
                    "campaign": campaign,
                    "marketing_spend": budget,
                    "units": units,
                    "unit_price": unit_price,
                    "revenue": revenue,
                    "cost": cost,
                    # Text, not 0/1 — a real export writes the word, and "True"
                    # sums to zero in both SQL and Python if nobody notices.
                    "returned": "True" if returned else "False",
                    "delivery_partner": partner,
                    "delivery_days": days,
                    "customer_rating": rating,
                    "customer_segment": rng.choice(SEGMENTS),
                    "revenue_target": TARGET[store],
                    "stock_on_hand": STOCK[store],
                    "reorder_level": REORDER_LEVEL,
                }
            )

    return rows


def write(path: Path) -> Path:
    rows = build_rows()
    path.parent.mkdir(parents=True, exist_ok=True)
    # newline="" so the csv module controls line endings and the digest holds
    # on every platform.
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarise(path: Path) -> None:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    num = lambda r, k: float(r[k])  # noqa: E731
    revenue = sum(num(r, "revenue") for r in rows)
    cost = sum(num(r, "cost") for r in rows)
    returned = [r for r in rows if r["returned"].lower() == "true"]

    print(f"{path.name}: {len(rows)} rows, {rows[0]['order_date']} to {rows[-1]['order_date']}")
    print(f"  revenue {revenue:,.0f}   cost {cost:,.0f}   margin {100 * (revenue - cost) / revenue:.2f}%")
    print(f"  returns {len(returned)} of {len(rows)} orders ({100 * len(returned) / len(rows):.1f}%)")

    by_month: dict[str, list[float]] = {}
    for row in rows:
        bucket = by_month.setdefault(row["order_date"][:7], [0.0, 0.0])
        bucket[0] += num(row, "revenue")
        bucket[1] += num(row, "cost")
    print("  planted margin slide:")
    for key in sorted(by_month):
        rev, cst = by_month[key]
        print(f"    {key}  revenue {rev:>12,.0f}   margin {100 * (rev - cst) / rev:5.1f}%")

    print(f"  sha256 {digest(path)}")


def main() -> None:
    default = Path(__file__).resolve().parent / "nexasphere_h1_2026.csv"
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=default, help="where to write the CSV")
    parser.add_argument(
        "--verify",
        type=Path,
        metavar="CSV",
        help="check an existing file against the expected digest instead of writing",
    )
    args = parser.parse_args()

    if args.verify:
        actual = digest(args.verify)
        ok = actual == EXPECTED_SHA256
        print(f"{args.verify}\n  {'MATCHES' if ok else 'DIFFERS FROM'} the expected dataset")
        print(f"  expected {EXPECTED_SHA256}\n  actual   {actual}")
        raise SystemExit(0 if ok else 1)

    path = write(args.out)
    summarise(path)
    if digest(path) != EXPECTED_SHA256:
        print("  WARNING: digest differs from the recorded dataset")


if __name__ == "__main__":
    main()
