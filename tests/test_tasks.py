"""Acceptance tests for spec 001 (create and list tasks)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from taskboard8_api.main import create_app


@pytest.fixture()
def tasks_client() -> Iterator[TestClient]:
    """A client on a fresh app, so every test starts with an empty store."""
    yield TestClient(create_app())


def test_create_task_with_due_date(tasks_client: TestClient) -> None:  # AC-001.1
    response = tasks_client.post("/tasks", json={"title": "Buy milk", "due_date": "2026-12-01"})
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "title", "due_date"}
    assert isinstance(body["id"], str)
    assert body["id"]
    assert body["title"] == "Buy milk"
    assert body["due_date"] == "2026-12-01"


def test_create_task_without_due_date(tasks_client: TestClient) -> None:  # AC-001.2
    response = tasks_client.post("/tasks", json={"title": "Buy milk"})
    assert response.status_code == 201
    assert response.json()["due_date"] is None


def test_create_task_with_null_due_date(tasks_client: TestClient) -> None:  # AC-001.2
    response = tasks_client.post("/tasks", json={"title": "Buy milk", "due_date": None})
    assert response.status_code == 201
    assert response.json()["due_date"] is None


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"title": 5},
        {"title": None},
        {"title": ["a"]},
        {"title": ""},
        {"title": "   "},
        {"title": "a" * 201},
        {"title": " " + "a" * 201 + " "},
    ],
)
def test_invalid_title_is_rejected(tasks_client: TestClient, body: dict) -> None:  # AC-001.3
    response = tasks_client.post("/tasks", json=body)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert detail
    assert detail[0]["loc"][0] == "body"
    assert detail[0]["loc"][-1] == "title"
    listing = tasks_client.get("/tasks")
    assert listing.status_code == 200
    assert listing.json() == []


def test_title_of_200_characters_is_accepted(tasks_client: TestClient) -> None:  # AC-001.3
    response = tasks_client.post("/tasks", json={"title": " " + "a" * 200 + " "})
    assert response.status_code == 201
    assert response.json()["title"] == "a" * 200


@pytest.mark.parametrize(
    "due_date",
    ["2026-02-30", "01.12.2026", "2026-12-01T10:00:00", "20261201", 20261201, ""],
)
def test_bad_due_date_rejected(tasks_client: TestClient, due_date: object) -> None:  # AC-001.4
    response = tasks_client.post("/tasks", json={"title": "Buy milk", "due_date": due_date})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert detail
    assert detail[0]["loc"][0] == "body"
    assert detail[0]["loc"][-1] == "due_date"
    assert tasks_client.get("/tasks").json() == []


def test_title_is_trimmed(tasks_client: TestClient) -> None:  # AC-001.5
    response = tasks_client.post("/tasks", json={"title": "  Buy milk  "})
    assert response.status_code == 201
    assert response.json()["title"] == "Buy milk"
    assert [task["title"] for task in tasks_client.get("/tasks").json()] == ["Buy milk"]


def test_list_returns_tasks_in_creation_order(tasks_client: TestClient) -> None:  # AC-001.6
    titles = ["first", "second", "third"]
    created = [
        tasks_client.post("/tasks", json={"title": title, "due_date": "2026-12-01"}).json()
        for title in titles
    ]
    response = tasks_client.get("/tasks")
    assert response.status_code == 200
    listed = response.json()
    assert isinstance(listed, list)
    assert listed == created
    assert [task["title"] for task in listed] == titles
    assert len({task["id"] for task in listed}) == 3
    for task in listed:
        assert set(task) == {"id", "title", "due_date"}


def test_list_is_empty_on_fresh_service(tasks_client: TestClient) -> None:  # AC-001.7
    response = tasks_client.get("/tasks")
    assert response.status_code == 200
    assert response.json() == []
