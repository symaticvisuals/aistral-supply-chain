from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import DatabaseMissing, session
from app.routers import metrics
from app.schemas import HealthResponse
from app.settings import settings

app = FastAPI(title="Kestrel API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(metrics.router)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Reports whether the pack database is actually reachable.

    "If it does not open, I will not use it." A missing pack should produce one
    readable sentence here rather than an identical stack trace from every
    endpoint.
    """
    info: dict = {"path": str(settings.db_path), "connected": False}
    try:
        with session() as conn:
            row = conn.execute(
                "SELECT (SELECT COUNT(*) FROM orders) AS orders,"
                " (SELECT COUNT(*) FROM order_lines) AS order_lines,"
                " (SELECT COUNT(*) FROM outlets) AS outlets,"
                " (SELECT MAX(order_date) FROM orders) AS latest_order"
            ).fetchone()
        info |= {"connected": True, **dict(row)}
        status = "ok"
    except DatabaseMissing as exc:
        info["error"] = str(exc)
        status = "no_database"
    except Exception as exc:  # unreadable or unexpected schema
        info["error"] = f"{type(exc).__name__}: {exc}"
        status = "database_unusable"

    return HealthResponse(status=status, service="kestrel-api", database=info)
