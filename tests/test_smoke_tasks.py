"""Smoke tests for spec 001 (AC-001.1, AC-001.6): they reach the service only through its URL."""

from __future__ import annotations

import json
import urllib.request
import uuid

import pytest


def _post(base_url: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        base_url + "/tasks",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, json.load(response)


def _list(base_url: str) -> tuple[int, object]:
    with urllib.request.urlopen(base_url + "/tasks", timeout=10) as response:
        return response.status, json.load(response)


@pytest.mark.smoke
@pytest.mark.writes
def test_smoke_ac_001_1_create_task(smoke_base_url: str) -> None:  # AC-001.1
    title = f"smoke-{uuid.uuid4()}"
    status, body = _post(smoke_base_url, {"title": title, "due_date": "2026-12-01"})
    assert status == 201
    assert isinstance(body["id"], str)
    assert body["id"]
    assert body["title"] == title
    assert body["due_date"] == "2026-12-01"


@pytest.mark.smoke
@pytest.mark.writes
def test_smoke_ac_001_6_created_tasks_are_listed_in_order(smoke_base_url: str) -> None:  # AC-001.6
    titles = [f"smoke-{uuid.uuid4()}" for _ in range(3)]
    ids = [_post(smoke_base_url, {"title": title})[1]["id"] for title in titles]
    status, listed = _list(smoke_base_url)
    assert status == 200
    assert isinstance(listed, list)
    positions = [next(i for i, task in enumerate(listed) if task["id"] == tid) for tid in ids]
    assert positions == sorted(positions)
    assert [listed[p]["title"] for p in positions] == titles


@pytest.mark.smoke
def test_smoke_ac_001_6_list_tasks_is_a_json_array(smoke_base_url: str) -> None:  # AC-001.6
    status, listed = _list(smoke_base_url)
    assert status == 200
    assert isinstance(listed, list)
    for task in listed:
        assert set(task) == {"id", "title", "due_date"}
