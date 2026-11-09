"""Unit tests for the Database layer (AC-002.4, AC-002.5, AC-002.6)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import psycopg
import pytest

from taskboard8_api.db import Database, DatabaseUnavailable

SCHEMA = [
    "CREATE TABLE IF NOT EXISTS probe (n integer)",
    "INSERT INTO probe VALUES (1)",
]


async def _one(conn: psycopg.AsyncConnection[Any]) -> int:
    cur = await conn.execute("SELECT 1")
    row = await cur.fetchone()
    assert row is not None
    return int(row[0])


async def _probe_rows(conn: psycopg.AsyncConnection[Any]) -> int:
    cur = await conn.execute("SELECT count(*) FROM probe")
    row = await cur.fetchone()
    assert row is not None
    return int(row[0])


def _unreachable(name: str, monkeypatch: pytest.MonkeyPatch, refused: str, blackhole: str) -> None:
    if name == "unset":
        monkeypatch.delenv("DATABASE_URL", raising=False)
    elif name == "blank":
        monkeypatch.setenv("DATABASE_URL", "   ")
    elif name == "refused":
        monkeypatch.setenv("DATABASE_URL", refused)
    elif name == "blackhole":
        monkeypatch.setenv("DATABASE_URL", blackhole)
    else:
        monkeypatch.setenv("DATABASE_URL", "postgresql://postgres@db.invalid:5432/postgres")


CASES = ["unset", "blank", "refused", "blackhole", "badhost"]


async def test_ping_true(postgres_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    assert await Database().ping() is True


@pytest.mark.parametrize("case", CASES)
async def test_ping_false_fast(
    case: str,
    monkeypatch: pytest.MonkeyPatch,
    refused_database_url: str,
    blackhole_database_url: str,
) -> None:
    _unreachable(case, monkeypatch, refused_database_url, blackhole_database_url)
    start = time.monotonic()
    assert await Database().ping() is False
    assert time.monotonic() - start < 1


@pytest.mark.parametrize("case", CASES)
async def test_run_unavailable_within_budget(
    case: str,
    monkeypatch: pytest.MonkeyPatch,
    refused_database_url: str,
    blackhole_database_url: str,
) -> None:
    _unreachable(case, monkeypatch, refused_database_url, blackhole_database_url)
    start = time.monotonic()
    with pytest.raises(DatabaseUnavailable):
        await Database().run(_one)
    assert time.monotonic() - start < 5


async def test_schema_created_once(
    restartable_postgres: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", restartable_postgres.url)
    db = Database(SCHEMA)
    assert await db.run(_probe_rows) == 1
    assert await db.run(_probe_rows) == 1


async def test_concurrent_first_runs(
    restartable_postgres: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", restartable_postgres.url)
    results = await asyncio.gather(Database(SCHEMA).run(_one), Database(SCHEMA).run(_one))
    assert results == [1, 1]


async def test_recovers_after_restart(
    restartable_postgres: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", restartable_postgres.url)
    db = Database(SCHEMA)
    assert await db.run(_one) == 1
    restartable_postgres.stop()
    with pytest.raises(DatabaseUnavailable):
        await db.run(_one)
    assert await db.ping() is False
    restartable_postgres.start()
    assert await db.run(_one) == 1
    assert await db.ping() is True
