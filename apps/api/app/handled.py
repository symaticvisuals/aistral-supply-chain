"""Cases someone has already handled.

The pack database is read-only, so this lives in a second file. Marking a case
done writes here and every morning list reads it — the fourth phone call stops
because the item has left everyone's queue, not just one browser.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from app.settings import settings

_CREATE = """
CREATE TABLE IF NOT EXISTS handled (
    case_id TEXT NOT NULL,
    as_of TEXT NOT NULL,
    handled_at TEXT NOT NULL,
    PRIMARY KEY (case_id, as_of)
)
"""


@contextmanager
def _connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """A connection that is actually closed afterwards.

    `with sqlite3.connect(...)` commits the transaction but leaves the handle
    open — every morning read opens two of these, so relying on refcounting to
    reclaim them is not something to leave in an API.
    """
    db = path or settings.handled_path
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    try:
        conn.execute(_CREATE)
        yield conn
    finally:
        conn.close()


def marked(as_of: str, path: Path | None = None) -> set[str]:
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT case_id FROM handled WHERE as_of = ?", (as_of,)
        ).fetchall()
    return {r[0] for r in rows}


def set_done(
    case_id: str, as_of: str, done: bool, path: Path | None = None
) -> None:
    with _connect(path) as conn:
        if done:
            conn.execute(
                "INSERT OR REPLACE INTO handled (case_id, as_of, handled_at) "
                "VALUES (?, ?, ?)",
                (case_id, as_of, datetime.now(UTC).isoformat()),
            )
        else:
            conn.execute(
                "DELETE FROM handled WHERE case_id = ? AND as_of = ?",
                (case_id, as_of),
            )
        conn.commit()


def annotate(events: list[dict], as_of: str, path: Path | None = None) -> None:
    done = marked(as_of, path)
    for event in events:
        for item in event["items"]:
            item["done"] = item.get("case_id") in done
