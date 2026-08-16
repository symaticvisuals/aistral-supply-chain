"""Concurrent requests must all succeed.

This exists because they did not. The dashboard fetches three endpoints with
Promise.all, and roughly two of every three returned 500:

    sqlite3.ProgrammingError: SQLite objects created in a thread can only be
    used in that same thread.

FastAPI resolves the sync `get_conn` dependency on one threadpool thread and may
run the sync endpoint on another. Sequential tests never caught it — every
earlier test in this suite passed while the API was broken under real use.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.db import connect
from app.main import app
from app.settings import settings

PATHS = [
    "/metrics/morning?as_of=2026-05-01",
    "/metrics/fill?window=fy26q1&scope=attempted",
    "/metrics/fill/outlets?window=fy26q1&limit=5",
    "/metrics/quality?window=fy26q1",
    "/health",
]


@pytest.fixture
def client(fixture_db, monkeypatch):
    """Points settings at the fixture instead of overriding the dependency.

    Overriding get_conn would supply the test's own connection and skip
    app.db.connect entirely — which is exactly where the threading flag lives,
    so the test would pass no matter how broken production was. It did, until
    this was changed.
    """
    monkeypatch.setattr(settings, "kestrel_db_path", str(fixture_db))
    return TestClient(app)


def test_a_connection_can_be_used_from_a_different_thread(fixture_db):
    """The precise invariant the production bug violated.

    FastAPI creates the connection while resolving the dependency on one
    threadpool thread and runs the endpoint on another. TestClient cannot
    reproduce that — it funnels everything through one portal — so this asserts
    the property directly against app.db.connect. Remove check_same_thread and
    this raises sqlite3.ProgrammingError.
    """
    conn = connect(fixture_db)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            value = pool.submit(
                lambda: conn.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"]
            ).result()
        assert value > 0
    finally:
        conn.close()


def test_the_dashboards_three_calls_survive_being_simultaneous(client):
    """Exactly what the page does on every load."""
    paths = PATHS[:3]
    with ThreadPoolExecutor(max_workers=len(paths)) as pool:
        results = list(pool.map(lambda p: (p, client.get(p)), paths))
    failed = [(p, r.status_code) for p, r in results if r.status_code != 200]
    assert not failed, f"concurrent requests failed: {failed}"


def test_every_endpoint_under_sustained_concurrency(client):
    """Twenty overlapping requests across all endpoints, no 500s."""
    work = PATHS * 4
    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(lambda p: client.get(p).status_code, work))
    assert set(codes) == {200}, f"unexpected statuses: {sorted(set(codes))}"


def test_connections_are_not_shared_between_requests(client):
    """Two concurrent calls to the same endpoint must not collide."""
    path = "/metrics/fill?window=fy26q1&scope=attempted"
    with ThreadPoolExecutor(max_workers=6) as pool:
        bodies = list(pool.map(lambda _: client.get(path).json(), range(6)))
    # Same inputs, same answer, every time — no cross-request bleed.
    assert all(b["service"] == bodies[0]["service"] for b in bodies)
