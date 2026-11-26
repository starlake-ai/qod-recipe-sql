"""Query the recipe's tables through the Quack on Demand FlightSQL edge.

    uv run query.py            print the top 5 customers by lifetime value
    uv run query.py --check    same, then compare with expected/ (exit 1 on a mismatch)
    uv run query.py --probe    run SELECT 1, exit 0 when the gateway answers

Connection settings come from QOD_* env vars. The defaults match the
throwaway gateway run.sh starts: 127.0.0.1:31338, tenant `default`, pool `bi`,
user `admin`, password `recipe-admin`, TLS with a self-signed certificate.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent

TOP5_SQL = (
    "SELECT customer_id, name, order_count, lifetime_value FROM customers_enriched "
    "ORDER BY lifetime_value DESC, customer_id LIMIT 5"
)
DAILY_COUNT_SQL = "SELECT count(*) AS n FROM daily_revenue"


@dataclass(frozen=True)
class QodConfig:
    host: str
    port: int
    user: str
    password: str
    tenant: str
    pool: str
    superuser: bool
    tls: bool
    tls_verify: bool


def _env_bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default).lower()).lower() == "true"


def config_from_env() -> QodConfig:
    return QodConfig(
        host=os.environ.get("QOD_HOST", "127.0.0.1"),
        port=int(os.environ.get("QOD_PORT", "31338")),
        user=os.environ.get("QOD_USER", "admin"),
        password=os.environ.get("QOD_PASSWORD", "recipe-admin"),
        tenant=os.environ.get("QOD_TENANT", "default"),
        pool=os.environ.get("QOD_POOL", "bi"),
        superuser=_env_bool("QOD_SUPERUSER", True),
        tls=_env_bool("QOD_TLS", True),
        tls_verify=_env_bool("QOD_TLS_VERIFY", False),
    )


def connect(cfg: QodConfig):
    """An ADBC FlightSQL connection scoped to the tenant and pool."""
    from adbc_driver_flightsql import DatabaseOptions
    from adbc_driver_flightsql import dbapi as flight_sql

    hdr = DatabaseOptions.RPC_CALL_HEADER_PREFIX.value
    db_kwargs = {
        "username": cfg.user,
        "password": cfg.password,
        hdr + "tenant": cfg.tenant,
        hdr + "pool": cfg.pool,
    }
    if cfg.superuser:
        db_kwargs[hdr + "superuser"] = "true"
    if cfg.tls and not cfg.tls_verify:
        # The gateway ships an auto-generated self-signed certificate.
        db_kwargs[DatabaseOptions.TLS_SKIP_VERIFY.value] = "true"
    scheme = "grpc+tls" if cfg.tls else "grpc"
    # The edge runs each statement standalone: ask for autocommit up front.
    return flight_sql.connect(uri=f"{scheme}://{cfg.host}:{cfg.port}", db_kwargs=db_kwargs, autocommit=True)


def fetch(conn, sql: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql)
        table = cur.fetch_arrow_table()
    return table.to_pylist()


def _norm(row: dict) -> dict:
    out = {}
    for key, value in row.items():
        if isinstance(value, (Decimal, float)) or key == "lifetime_value":
            value = f"{Decimal(str(value)):.2f}"
        out[key] = value
    return out


def compare(rows: list[dict], expected: list[dict]) -> list[str]:
    """Differences between the rows the gateway returned and expected/, one
    line each; empty when they match."""
    diffs = []
    got = [_norm(r) for r in rows]
    want = [_norm(r) for r in expected]
    if len(got) != len(want):
        diffs.append(f"expected {len(want)} rows, got {len(got)}")
    for g, w in zip(got, want):
        if g != w:
            diffs.append(f"customer_id {w.get('customer_id')}: expected {w}, got {g}")
    return diffs


def _print_table(rows: list[dict]) -> None:
    if not rows:
        print("  (no rows)")
        return
    cols = list(rows[0])
    cells = [[str(_norm(r)[c]) for c in cols] for r in rows]
    widths = [max(len(c), *(len(row[i]) for row in cells)) for i, c in enumerate(cols)]
    print("  " + " | ".join(c.ljust(w) for c, w in zip(cols, widths)))
    print("  " + "-+-".join("-" * w for w in widths))
    for row in cells:
        print("  " + " | ".join(v.ljust(w) for v, w in zip(row, widths)))


def main(argv: list[str]) -> int:
    cfg = config_from_env()
    if "--probe" in argv:
        try:
            with connect(cfg) as conn:
                fetch(conn, "SELECT 1 AS ok")
            return 0
        except Exception:
            return 1

    with connect(cfg) as conn:
        rows = fetch(conn, TOP5_SQL)
        print("top 5 customers by lifetime value (via FlightSQL):")
        _print_table(rows)
        if "--check" not in argv:
            return 0
        diffs = compare(rows, json.loads((ROOT / "expected" / "top5.json").read_text()))
        n_daily = fetch(conn, DAILY_COUNT_SQL)[0]["n"]
        want_daily = int((ROOT / "expected" / "daily_revenue_rows.txt").read_text())
        if n_daily != want_daily:
            diffs.append(f"daily_revenue: expected {want_daily} rows, got {n_daily}")

    if diffs:
        print("check FAILED:", file=sys.stderr)
        for d in diffs:
            print("  " + d, file=sys.stderr)
        return 1
    print(f"check OK: top 5 matches expected/, daily_revenue has {n_daily} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
