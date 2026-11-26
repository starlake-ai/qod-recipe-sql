"""Generate the recipe dataset into data/. Deterministic: re-running gives
byte-identical files. Stdlib only.

    python scripts/gen_data.py
"""

import csv
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data"

FIRST = ["Ada", "Ben", "Chloe", "Dev", "Elena", "Femi", "Grace", "Hugo", "Ines", "Jun"]
LAST = ["Martin", "Okafor", "Silva", "Nguyen", "Kowalski", "Haddad", "Rossi", "Tanaka", "Moreau", "Berg"]
COUNTRIES = ["FR", "DE", "US", "BR", "JP", "NG"]
PRODUCTS = {
    "duck-mug": "12.50",
    "lake-poster": "24.00",
    "quack-tee": "19.90",
    "parquet-socks": "8.75",
    "sql-hoodie": "54.00",
    "arrow-pin": "3.20",
}

N_CUSTOMERS = 50
CUSTOMERS_WITH_ORDERS = 45  # customers 46..50 never order: the models must keep them with 0
N_ORDERS = 200
START = date(2026, 1, 1)
DAYS = 90  # 2026-01-01 .. 2026-03-31


def main() -> None:
    rng = random.Random(42)
    OUT.mkdir(exist_ok=True)

    with open(OUT / "customers.csv", "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["customer_id", "name", "country", "signup_date"])
        for cid in range(1, N_CUSTOMERS + 1):
            name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
            signup = date(2025, 1, 1) + timedelta(days=rng.randrange(365))
            w.writerow([cid, name, rng.choice(COUNTRIES), signup.isoformat()])

    orders = []
    with open(OUT / "orders.csv", "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["order_id", "customer_id", "order_date"])
        for oid in range(1, N_ORDERS + 1):
            cid = rng.randint(1, CUSTOMERS_WITH_ORDERS)
            day = START + timedelta(days=rng.randrange(DAYS))
            orders.append(oid)
            w.writerow([oid, cid, day.isoformat()])

    with open(OUT / "order_items.csv", "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["order_id", "product", "quantity", "unit_price"])
        for oid in orders:
            for product in rng.sample(sorted(PRODUCTS), rng.randint(1, 4)):
                w.writerow([oid, product, rng.randint(1, 3), PRODUCTS[product]])


if __name__ == "__main__":
    main()
