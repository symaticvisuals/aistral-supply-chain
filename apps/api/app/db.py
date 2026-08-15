import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException

from app.settings import settings


class DatabaseMissing(RuntimeError):
    """The pack database is not where settings say it is."""


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open the pack database read-only.

    Read-only is enforced by SQLite itself via the URI, not by convention — this
    service must never be able to write to the client's operational file.
    """
    db_path = path or settings.db_path
    if not db_path.exists():
        raise DatabaseMissing(
            f"No database at {db_path}. Put the assignment pack next to the repo "
            f"or set KESTREL_DB_PATH in apps/api/.env"
        )
    # check_same_thread=False because FastAPI resolves a sync dependency and runs
    # the sync endpoint on its threadpool, and under concurrent load those are
    # different threads — the connection is handed between them. It is still only
    # ever touched by one thread at a time, and never shared between requests.
    # Without this, three simultaneous requests fail at random with
    # "SQLite objects created in a thread can only be used in that same thread".
    conn = sqlite3.connect(
        f"file:{db_path}?mode=ro", uri=True, check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def session(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
    finally:
        conn.close()


def get_conn() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency. One connection per request, closed when it ends.

    Per-request is the right unit: queries run in ~0.1s, so pooling buys nothing,
    and no two requests ever touch the same connection. See connect() for why
    check_same_thread has to be off even so.
    """
    try:
        conn = connect()
    except DatabaseMissing as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        yield conn
    finally:
        conn.close()
