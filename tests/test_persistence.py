"""Acceptance tests for spec 002 (keep tasks in Postgres)."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from taskboard8_api.main import create_app

WRONG_HOST_URL = "postgresql://postgres@db.invalid:5432/postgres"


def _create(c: TestClient, title: str, due_date: str | None = None) -> dict:
    response = c.post("/tasks", json={"title": title, "due_date": due_date})
    assert response.status_code == 201
    return response.json()


def test_tasks_survive_restart() -> None:  # AC-002.1
    with TestClient(create_app()) as first:
        created = [
            _create(first, "one", "2026-12-01"),
            _create(first, "two"),
            _create(first, "three", "2027-01-15"),
        ]
    with TestClient(create_app()) as second:
        response = second.get("/tasks")
    assert response.status_code == 200
    assert response.json() == created
    assert [t["title"] for t in response.json()] == ["one", "two", "three"]


def test_two_instances_share_tasks_in_one_order() -> None:  # AC-002.2
    a = TestClient(create_app())
    b = TestClient(create_app())
    created = []
    for i in range(6):
        writer = a if i % 2 == 0 else b
        created.append(_create(writer, f"task-{i}"))
        assert a.get("/tasks").json() == created
        assert b.get("/tasks").json() == created


def test_empty_database_lists_empty() -> None:  # AC-002.3
    response = TestClient(create_app()).get("/tasks")
    assert response.status_code == 200
    assert response.json() == []


def test_task_contract_holds_with_database() -> None:  # AC-002.3
    c = TestClient(create_app())
    response = c.post("/tasks", json={"title": "  Buy milk  ", "due_date": "2026-12-01"})
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "title", "due_date"}
    assert body["title"] == "Buy milk"
    assert body["due_date"] == "2026-12-01"
    assert c.post("/tasks", json={"title": "x"}).json()["due_date"] is None
    assert c.post("/tasks", json={"title": "   "}).status_code == 422
    assert c.post("/tasks", json={"title": "a" * 201}).status_code == 422
    assert c.post("/tasks", json={"title": "ok", "due_date": "2026-02-30"}).status_code == 422
    # fresh instance sees only the two valid tasks
    assert [t["title"] for t in TestClient(create_app()).get("/tasks").json()] == [
        "Buy milk",
        "x",
    ]


def _unreachable(kind: str, monkeypatch, refused, blackhole) -> None:
    if kind == "unset":
        monkeypatch.delenv("DATABASE_URL", raising=False)
    elif kind == "refused":
        monkeypatch.setenv("DATABASE_URL", refused)
    elif kind == "blackhole":
        monkeypatch.setenv("DATABASE_URL", blackhole)
    else:
        monkeypatch.setenv("DATABASE_URL", WRONG_HOST_URL)


KINDS = ["unset", "refused", "blackhole", "wrong_host"]


@pytest.mark.parametrize("kind", KINDS)
def test_unreachable_database_gives_503(
    kind: str, monkeypatch, refused_database_url: str, blackhole_database_url: str
) -> None:  # AC-002.4
    c = TestClient(create_app())
    _unreachable(kind, monkeypatch, refused_database_url, blackhole_database_url)
    start = time.monotonic()
    assert c.get("/tasks").status_code == 503
    assert time.monotonic() - start < 5
    start = time.monotonic()
    assert c.post("/tasks", json={"title": "nope"}).status_code == 503
    assert time.monotonic() - start < 5
    invalid = c.post("/tasks", json={"title": "   "})
    assert invalid.status_code == 422


def test_no_task_created_during_outage(
    monkeypatch, refused_database_url: str, postgres_url: str
) -> None:  # AC-002.4
    c = TestClient(create_app())
    monkeypatch.setenv("DATABASE_URL", refused_database_url)
    assert c.post("/tasks", json={"title": "ghost"}).status_code == 503
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    assert c.get("/tasks").json() == []


@pytest.mark.parametrize("kind", KINDS)
def test_ready_503_and_health_200_when_unreachable(
    kind: str, monkeypatch, refused_database_url: str, blackhole_database_url: str
) -> None:  # AC-002.5
    _unreachable(kind, monkeypatch, refused_database_url, blackhole_database_url)
    with TestClient(create_app()) as c:  # unreachable already at start-up
        start = time.monotonic()
        assert c.get("/ready").status_code == 503
        assert time.monotonic() - start < 1
        health = c.get("/health")
        assert health.status_code == 200
        assert c.get("/tasks").status_code == 503


def test_recovers_after_outage(monkeypatch, restartable_postgres) -> None:  # AC-002.6
    monkeypatch.setenv("DATABASE_URL", restartable_postgres.url)
    with TestClient(create_app()) as c:
        created = [_create(c, "before-1"), _create(c, "before-2", "2026-12-01")]
        restartable_postgres.stop()
        assert c.get("/tasks").status_code == 503
        assert c.get("/ready").status_code == 503
        restartable_postgres.start()
        deadline = time.monotonic() + 30
        ready = False
        while time.monotonic() < deadline:
            if c.get("/ready").status_code == 200:
                ready = True
                break
            time.sleep(0.5)
        assert ready
        response = c.get("/tasks")
        assert response.status_code == 200
        assert response.json() == created
