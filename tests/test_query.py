import json
from decimal import Decimal
from pathlib import Path

import query

ROOT = Path(__file__).resolve().parent.parent


def _expected():
    return json.loads((ROOT / "expected" / "top5.json").read_text())


def test_check_passes_on_expected_rows():
    rows = [dict(r, lifetime_value=Decimal(r["lifetime_value"])) for r in _expected()]
    assert query.compare(rows, _expected()) == []


def test_check_reports_mismatch():
    rows = [dict(r, lifetime_value=Decimal(r["lifetime_value"])) for r in _expected()]
    rows[1]["lifetime_value"] = Decimal("1.00")
    diff = query.compare(rows, _expected())
    assert diff and str(rows[1]["customer_id"]) in diff[0]


def test_check_reports_missing_rows():
    rows = [dict(r, lifetime_value=Decimal(r["lifetime_value"])) for r in _expected()][:3]
    assert query.compare(rows, _expected())


def test_defaults_match_recipe_install(monkeypatch):
    for var in ("QOD_HOST", "QOD_PORT", "QOD_USER", "QOD_PASSWORD", "QOD_TENANT", "QOD_POOL"):
        monkeypatch.delenv(var, raising=False)
    cfg = query.config_from_env()
    assert (cfg.tenant, cfg.pool, cfg.password, cfg.port, cfg.user) == (
        "default", "bi", "recipe-admin", 31338, "admin")
    assert cfg.superuser and cfg.tls and not cfg.tls_verify


def test_daily_check_compares_values():
    want = {"rows": 82, "total": "15000.00"}
    assert query.compare_daily(82, Decimal("15000.00"), want) == []
    diff = query.compare_daily(82, Decimal("14999.99"), want)
    assert diff and "15000.00" in diff[0]
    assert query.compare_daily(81, Decimal("15000.00"), want)
