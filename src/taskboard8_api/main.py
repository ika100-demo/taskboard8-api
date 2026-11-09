"""FastAPI entry point for taskboard8-api."""

from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from . import __version__
from .db import Database, DatabaseUnavailable
from .logging_config import configure_logging
from .metrics import MetricsMiddleware
from .tasks.router import router as tasks_router
from .tasks.store import TASKS_SCHEMA, TaskStore
from .tracing import configure_tracing, tracing_enabled

configure_logging(level=os.environ.get("LOG_LEVEL", "INFO"))
if tracing_enabled():
    configure_tracing()


class HealthResponse(BaseModel):
    status: str


def health() -> HealthResponse:
    """Liveness probe — returns 200 as long as the process is responding."""
    return HealthResponse(status="ok")


async def ready(request: Request) -> JSONResponse:
    """Readiness probe — 200 when the database answers, else 503."""
    if await request.app.state.database.ping():
        return JSONResponse({"status": "ready"})
    return JSONResponse({"status": "unavailable"}, status_code=503)


async def database_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
    """Map a database outage to 503."""
    return JSONResponse({"detail": "database unavailable"}, status_code=503)


def ping() -> dict[str, str]:
    """Simple ping endpoint."""
    return {"pong": "taskboard8-api"}


def metrics() -> Response:
    """Prometheus scrape endpoint."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def create_app() -> FastAPI:
    """Build a fresh app with an empty task store."""
    app = FastAPI(title="taskboard8-api", version=__version__)
    app.add_middleware(MetricsMiddleware)
    app.add_api_route("/health", health, methods=["GET"], response_model=HealthResponse)
    app.add_api_route("/ready", ready, methods=["GET"])
    app.add_api_route("/ping", ping, methods=["GET"])
    app.add_api_route("/metrics", metrics, methods=["GET"])
    app.include_router(tasks_router)
    app.state.database = Database(schema=TASKS_SCHEMA)
    app.state.task_store = TaskStore(app.state.database)
    app.add_exception_handler(DatabaseUnavailable, database_unavailable_handler)
    return app


app = create_app()
