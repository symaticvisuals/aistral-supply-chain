"""Ticking a case off the queue writes to a file everyone reads."""

import datetime as dt
import sqlite3

import pytest
from app.db import get_conn
from app.main import app
from app.metrics.morning import item_label, morning
from app.settings import settings
from fastapi.testclient import TestClient


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


def test_a_warm_delivery_is_one_readable_line():
    assert (
        item_label("cold_chain", {"outlet": "Metro Trading Co", "max_temp_c": 13.6})
        == "Metro Trading Co, 13.6C"
    )


def test_morning_items_carry_an_id_and_a_label(conn):
    result = morning(conn, dt.date(2026, 5, 2))
    event = next(e for e in result["events"] if e["kind"] == "cold_chain")
    item = event["items"][0]
    assert item["case_id"] == "cold_chain:DN0002"
    assert item["label"] == "Balaji Provision, Rs 400 chilled at 12.4C"


def test_marking_a_case_done_is_visible_on_the_next_read(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "handled_db_path", str(tmp_path / "handled.db"))
    first = client.get("/metrics/morning?as_of=2026-05-02").json()
    event = next(e for e in first["events"] if e["kind"] == "cold_chain")
    case_id = event["items"][0]["case_id"]
    assert event["items"][0]["done"] is False

    posted = client.post(
        "/metrics/morning/handle",
        json={"case_id": case_id, "as_of": "2026-05-02", "done": True},
    )
    assert posted.status_code == 200

    again = client.get("/metrics/morning?as_of=2026-05-02").json()
    item = next(e for e in again["events"] if e["kind"] == "cold_chain")["items"][0]
    assert item["done"] is True


def test_unmarking_puts_the_case_back(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "handled_db_path", str(tmp_path / "handled.db"))
    case_id = "cold_chain:DN0002"
    client.post(
        "/metrics/morning/handle",
        json={"case_id": case_id, "as_of": "2026-05-02", "done": True},
    )
    client.post(
        "/metrics/morning/handle",
        json={"case_id": case_id, "as_of": "2026-05-02", "done": False},
    )
    body = client.get("/metrics/morning?as_of=2026-05-02").json()
    item = next(e for e in body["events"] if e["kind"] == "cold_chain")["items"][0]
    assert item["done"] is False


def test_handle_rejects_a_junk_day(client):
    res = client.post(
        "/metrics/morning/handle",
        json={"case_id": "cold_chain:DN0002", "as_of": "yesterday", "done": True},
    )
    assert res.status_code == 400
