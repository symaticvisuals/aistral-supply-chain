"""The snapshot, written where the API can read it without a web server.

Separate file from the pack, which is opened read-only and must stay that way,
and separate from handled.db, which is user actions rather than observations.

Every run is kept rather than overwritten. Prices are the one thing here that
genuinely changes week to week, and a snapshot store that keeps only the last
one cannot answer "did this move" — which is most of what a price is for.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.bazaarpulse.crawl import Snapshot
from app.settings import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS scrape_run (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    base_url TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    crawl_delay_s REAL NOT NULL,
    robots_found INTEGER NOT NULL,
    pages_ok INTEGER NOT NULL,
    pages_rejected INTEGER NOT NULL,
    listings INTEGER NOT NULL,
    repeat_appearances INTEGER NOT NULL,
    history_rows INTEGER NOT NULL,
    details_fetched INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS listing (
    run_id INTEGER NOT NULL,
    listing_id TEXT NOT NULL,
    city TEXT,
    retailer TEXT,
    title TEXT NOT NULL,
    pack_text TEXT,
    category TEXT,
    price_inr REAL,
    price_source TEXT,
    mrp_inr REAL,
    availability TEXT,
    rating REAL,
    rating_count INTEGER,
    last_seen TEXT,
    detail_path TEXT,
    detail_price_inr REAL,
    first_seen_on TEXT,
    PRIMARY KEY (run_id, listing_id)
);

CREATE TABLE IF NOT EXISTS price_history (
    run_id INTEGER NOT NULL,
    listing_id TEXT NOT NULL,
    observed_on TEXT NOT NULL,
    price_inr REAL NOT NULL,
    PRIMARY KEY (run_id, listing_id, observed_on)
);

CREATE TABLE IF NOT EXISTS scrape_finding (
    run_id INTEGER NOT NULL,
    finding_id TEXT NOT NULL,
    severity TEXT NOT NULL,
    statement TEXT NOT NULL,
    evidence TEXT NOT NULL,
    PRIMARY KEY (run_id, finding_id)
);

CREATE TABLE IF NOT EXISTS fetch_log (
    run_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    purpose TEXT,
    outcome TEXT NOT NULL,
    status INTEGER,
    tries INTEGER NOT NULL,
    size INTEGER NOT NULL,
    note TEXT
);

CREATE INDEX IF NOT EXISTS listing_by_city ON listing (run_id, city);
CREATE INDEX IF NOT EXISTS fetch_by_outcome ON fetch_log (run_id, outcome);
"""


@contextmanager
def connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    db = path or settings.bazaarpulse_path
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
    finally:
        conn.close()


def write(snapshot: Snapshot, path: Path | None = None) -> int:
    """Write one run and return its id. All of it or none of it."""
    history_rows = sum(len(v) for v in snapshot.history.values())
    with connect(path) as conn:
        with conn:
            cursor = conn.execute(
                "INSERT INTO scrape_run (base_url, started_at, finished_at,"
                " crawl_delay_s, robots_found, pages_ok, pages_rejected,"
                " listings, repeat_appearances, history_rows, details_fetched)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (snapshot.base_url, snapshot.started_at, snapshot.finished_at,
                 snapshot.crawl_delay_s, int(snapshot.robots_found),
                 snapshot.pages_ok, snapshot.pages_rejected,
                 len(snapshot.listings), snapshot.repeats, history_rows,
                 len(snapshot.detail_price)),
            )
            run_id = int(cursor.lastrowid or 0)

            conn.executemany(
                "INSERT INTO listing (run_id, listing_id, city, retailer,"
                " title, pack_text, category, price_inr, price_source,"
                " mrp_inr, availability, rating, rating_count, last_seen,"
                " detail_path, detail_price_inr, first_seen_on)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (run_id, row.listing_id, row.city, row.retailer, row.title,
                     row.pack_text, row.category, row.price_inr,
                     row.price_source, row.mrp_inr, row.availability,
                     row.rating, row.rating_count, row.last_seen,
                     row.detail_path,
                     snapshot.detail_price.get(row.listing_id),
                     snapshot.first_seen_on.get(row.listing_id))
                    for row in snapshot.rows
                ],
            )

            conn.executemany(
                "INSERT OR REPLACE INTO price_history"
                " (run_id, listing_id, observed_on, price_inr)"
                " VALUES (?,?,?,?)",
                [(run_id, listing_id, observed_on, price)
                 for listing_id, series in snapshot.history.items()
                 for observed_on, price in series],
            )

            conn.executemany(
                "INSERT INTO scrape_finding"
                " (run_id, finding_id, severity, statement, evidence)"
                " VALUES (?,?,?,?,?)",
                [(run_id, f.id, f.severity, f.statement, json.dumps(f.evidence))
                 for f in snapshot.findings],
            )

            conn.executemany(
                "INSERT INTO fetch_log"
                " (run_id, url, purpose, outcome, status, tries, size, note)"
                " VALUES (?,?,?,?,?,?,?,?)",
                [(run_id, a.url, a.purpose, a.outcome, a.status, a.tries,
                  a.size, a.note)
                 for a in snapshot.attempts],
            )
    return run_id


def latest_run(path: Path | None = None) -> sqlite3.Row | None:
    with connect(path) as conn:
        return conn.execute(
            "SELECT * FROM scrape_run WHERE finished_at IS NOT NULL"
            " ORDER BY run_id DESC LIMIT 1"
        ).fetchone()


def listings(run_id: int, path: Path | None = None) -> list:
    with connect(path) as conn:
        return conn.execute(
            "SELECT * FROM listing WHERE run_id = ? ORDER BY listing_id",
            (run_id,),
        ).fetchall()


def findings(run_id: int, path: Path | None = None) -> list:
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM scrape_finding WHERE run_id = ? ORDER BY finding_id",
            (run_id,),
        ).fetchall()
    return [{**dict(r), "evidence": json.loads(r["evidence"])} for r in rows]
