"""Endpoint contracts, driven off the synthetic fixture.

The app's own get_conn dependency is overridden so these never touch the pack —
the contract must hold on any data, not just the one database we have.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.db import get_conn
from app.main import app


@pytest.fixture
def client(fixture_db):
    def _conn():
        c = sqlite3.connect(f"file:{fixture_db}?mode=ro", uri=True)
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()

    app.dependency_overrides[get_conn] = _conn
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_fill_returns_the_decomposition(client):
    body = client.get("/metrics/fill?window=fy26q1").json()
    svc = body["service"]
    assert svc["execution_pct"] == pytest.approx(200 / 3)
    assert svc["availability_pct"] == pytest.approx(75.0)
    assert svc["service_pct"] == pytest.approx(50.0)
    assert svc["identity_holds"] is True


def test_fill_never_reports_service_without_both_factors(client):
    svc = client.get("/metrics/fill?window=fy26q1").json()["service"]
    assert {"execution_pct", "availability_pct", "service_pct"} <= svc.keys()


def test_fill_reports_all_three_unit_definitions(client):
    fill = client.get("/metrics/fill?window=fy26q1").json()["fill"]
    assert fill["case_pct"] == pytest.approx(200 / 3)
    assert fill["case_only_pct"] == pytest.approx(80.0)
    assert fill["case_only_lines_dropped"] == 1


def test_fill_ladder_has_every_scope_and_a_constant_execution(client):
    ladder = client.get("/metrics/fill?window=fy26q1").json()["ladder"]
    assert [r["scope_id"] for r in ladder] == [
        "attempted", "stockout", "kestrel_fault", "all_cancels"
    ]
    assert len({round(r["execution_pct"], 9) for r in ladder}) == 1


def test_fill_names_every_excluded_outlet(client):
    exc = client.get("/metrics/fill?window=fy26q1").json()["exclusions"]
    names = {o["outlet_name"] for o in exc["excluded_outlets"]}
    assert names == {"ZZ_TEST_OUTLET", "Closed Shop", "Deleted Shop"}
    assert exc["total_orders_excluded"] > 0


def test_fill_flags_the_contested_judgement(client):
    body = client.get("/metrics/fill?window=fy26q1").json()
    assert body["scope"]["contested"] == ["CR01_CREDIT"]
    assert any("arguable" in n for n in body["notes"])


def test_stockout_scope_drops_the_contested_reason(client):
    body = client.get("/metrics/fill?window=fy26q1&scope=stockout").json()
    assert body["scope"]["contested"] == []


def test_outlets_returns_both_orderings(client):
    body = client.get("/metrics/fill/outlets?window=fy26q1&limit=5").json()
    assert "by_units_short" in body and "by_fill_pct" in body
    assert "overlap" in body
    assert set(body["exposure"]) == {"by_units_short", "by_fill_pct"}


def test_outlets_excludes_test_closed_and_deleted(client):
    body = client.get("/metrics/fill/outlets?window=fy26q1").json()
    ids = {r["outlet_id"] for r in body["by_units_short"]}
    assert ids == {101}


def test_quality_lists_blocking_findings_first(client):
    body = client.get("/metrics/quality?window=fy26q1").json()
    severities = [f["severity"] for f in body["findings"]]
    assert severities == sorted(
        severities, key=lambda s: {"blocks_metric": 0, "advisory": 1, "clean": 2}[s]
    )
    assert body["blocking"] == [
        f["id"] for f in body["findings"] if f["severity"] == "blocks_metric"
    ]


def test_quality_reports_the_test_outlet(client):
    findings = {f["id"]: f for f in client.get("/metrics/quality").json()["findings"]}
    test_outlets = findings["TEST_OUTLETS_ACTIVE"]
    assert test_outlets["severity"] == "advisory"
    names = {o["outlet_name"] for o in test_outlets["evidence"]["outlets"]}
    assert "ZZ_TEST_OUTLET" in names


@pytest.mark.parametrize(
    ("path", "fragment"),
    [
        ("/metrics/fill?scope=whatever", "Unknown scope"),
        ("/metrics/fill?window=nonsense", "Unrecognised window"),
        ("/metrics/fill?region=ZZZ", "Unknown region"),
    ],
)
def test_bad_input_is_a_400_that_explains_itself(client, path, fragment):
    r = client.get(path)
    assert r.status_code == 400
    assert fragment in r.json()["detail"]


def test_region_filter_selects_and_excludes(client):
    base = "/metrics/fill?window=fy26q1&region="
    assert client.get(base + "WST").json()["orders_counted"] == 3
    assert client.get(base + "NTH").json()["orders_counted"] == 0


def test_default_window_skips_an_incomplete_quarter(client):
    """Fixture data ends 2026-05-08, mid-Q1, so the default falls back to FY25 Q4.

    Comparing a part-quarter against full ones is how a board number lies.
    """
    w = client.get("/metrics/fill").json()["window"]
    assert w["id"] == "fy25q4"
    assert w["is_latest_complete"] is True
    assert (w["start"], w["end"]) == ("2026-01-01", "2026-03-31")


def test_health_reports_the_database(client):
    body = client.get("/health").json()
    assert body["service"] == "kestrel-api"
    assert "database" in body and "path" in body["database"]
