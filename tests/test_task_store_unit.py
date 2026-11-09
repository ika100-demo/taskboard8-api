from datetime import date

import pytest

from taskboard8_api.db import Database, DatabaseUnavailable
from taskboard8_api.tasks.store import TASKS_SCHEMA, TaskStore


def _store() -> TaskStore:
    return TaskStore(Database(schema=TASKS_SCHEMA))


async def test_empty_at_start() -> None:
    assert await _store().list() == []


async def test_insertion_order_across_instances_and_distinct_ids() -> None:
    a, b = _store(), _store()
    await a.add("a", None)
    await b.add("b", None)
    await a.add("c", None)
    tasks = await b.list()
    assert [t.title for t in tasks] == ["a", "b", "c"]
    assert len({t.id for t in tasks}) == 3
    assert [t.id for t in await a.list()] == [t.id for t in tasks]


async def test_due_date_round_trip() -> None:
    s = _store()
    added = [await s.add("a", None), await s.add("b", date(2026, 12, 1))]
    assert await s.list() == added
    assert [t.due_date for t in added] == [None, date(2026, 12, 1)]


async def test_unavailable_without_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = _store()
    with pytest.raises(DatabaseUnavailable):
        await s.add("a", None)
    with pytest.raises(DatabaseUnavailable):
        await s.list()
