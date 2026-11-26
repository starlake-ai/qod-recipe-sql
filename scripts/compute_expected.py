"""Rebuild expected/ from data/ with scripts/expected.sql.

    uv run python scripts/compute_expected.py
"""

import json
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
TOP5_SQL = (
    "SELECT customer_id, name, order_count, lifetime_value FROM customers_enriched "
    "ORDER BY lifetime_value DESC, customer_id LIMIT 5"
)


def main() -> None:
    con = duckdb.connect()
    con.execute(f"SET file_search_path = '{ROOT.as_posix()}'")
    con.execute((ROOT / "scripts" / "expected.sql").read_text())
    cur = con.execute(TOP5_SQL)
    cols = [d[0] for d in cur.description]
    rows = [{c: (str(v) if c == "lifetime_value" else v) for c, v in zip(cols, r)} for r in cur.fetchall()]
    (ROOT / "expected").mkdir(exist_ok=True)
    (ROOT / "expected" / "top5.json").write_text(json.dumps(rows, indent=2) + "\n")
    n = con.execute("SELECT count(*) FROM daily_revenue").fetchone()[0]
    (ROOT / "expected" / "daily_revenue_rows.txt").write_text(f"{n}\n")


if __name__ == "__main__":
    main()
