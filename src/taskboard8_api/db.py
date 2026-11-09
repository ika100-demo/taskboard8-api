"""Postgres access: a connection per operation, bounded in time, schema ensured lazily."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, TypeVar

import psycopg
import structlog

CONNECT_TIMEOUT_S = 2
STATEMENT_TIMEOUT_MS = 3000
OPERATION_BUDGET_S = 4.5
READY_TIMEOUT_S = 0.5
SCHEMA_LOCK_KEY = 0x74626B38  # "tbk8"

T = TypeVar("T")

log = structlog.get_logger()


class DatabaseUnavailable(Exception):  # noqa: N818 # name fixed by the spec contract
    """The database cannot be reached or did not answer in time."""


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


async def _connect(url: str) -> psycopg.AsyncConnection[Any]:
    return await psycopg.AsyncConnection.connect(
        url,
        autocommit=True,
        connect_timeout=CONNECT_TIMEOUT_S,
        options=f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
    )


class Database:
    """Opens one connection per operation; there is no pool and nothing connects at startup."""

    def __init__(self, schema: Sequence[str] = ()) -> None:
        self._schema = tuple(schema)
        self._ensured: set[str] = set()

    async def _ensure_schema(self, conn: psycopg.AsyncConnection[Any], url: str) -> None:
        if url in self._ensured:
            return
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(%s)", (SCHEMA_LOCK_KEY,))
            for statement in self._schema:
                await conn.execute(statement)  # type: ignore[call-overload]
        self._ensured.add(url)

    async def run(self, op: Callable[[psycopg.AsyncConnection[Any]], Awaitable[T]]) -> T:
        """Run ``op`` on a fresh connection; raise DatabaseUnavailable on connection trouble."""
        operation = getattr(op, "__qualname__", "operation")
        try:
            async with asyncio.timeout(OPERATION_BUDGET_S):
                url = _database_url()
                if not url:
                    raise DatabaseUnavailable("DATABASE_URL is not set")
                try:
                    conn = await _connect(url)
                except psycopg.Error as exc:
                    raise DatabaseUnavailable("connect failed") from exc
                async with conn:
                    try:
                        await self._ensure_schema(conn, url)
                        return await op(conn)
                    except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
                        raise DatabaseUnavailable("statement failed") from exc
        except DatabaseUnavailable as exc:
            cause = exc.__cause__ or exc
            log.warning("database_unavailable", reason=type(cause).__name__, operation=operation)
            raise
        except (OSError, TimeoutError) as exc:
            log.warning("database_unavailable", reason=type(exc).__name__, operation=operation)
            raise DatabaseUnavailable("database unreachable") from exc

    async def ping(self, timeout: float = READY_TIMEOUT_S) -> bool:
        """Return True when ``SELECT 1`` succeeds within ``timeout``; never raises."""
        try:
            async with asyncio.timeout(timeout):
                url = _database_url()
                if not url:
                    return False
                async with await _connect(url) as conn:
                    await conn.execute("SELECT 1")
            return True
        except Exception as exc:
            log.debug("database_ping_failed", reason=type(exc).__name__)
            return False
