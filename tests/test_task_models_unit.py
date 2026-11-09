from datetime import date
from typing import Any

import pytest
from pydantic import ValidationError

from taskboard8_api.tasks.models import Task, TaskCreate


def test_title_trimmed() -> None:
    assert TaskCreate(title="  Buy milk  ").title == "Buy milk"  # type: ignore[call-arg]


def test_title_length_limits_after_trim() -> None:
    assert len(TaskCreate.model_validate({"title": " " + "a" * 200 + " "}).title) == 200
    with pytest.raises(ValidationError):
        TaskCreate.model_validate({"title": " " + "a" * 201 + " "})


@pytest.mark.parametrize("title", ["", "   ", 1, True, None, []])
def test_title_invalid(title: Any) -> None:
    with pytest.raises(ValidationError):
        TaskCreate.model_validate({"title": title})


def test_title_missing() -> None:
    with pytest.raises(ValidationError):
        TaskCreate.model_validate({})


def test_due_date_valid_null_absent() -> None:
    assert TaskCreate.model_validate({"title": "a", "due_date": "2026-12-01"}).due_date == date(
        2026, 12, 1
    )
    assert TaskCreate.model_validate({"title": "a", "due_date": None}).due_date is None
    assert TaskCreate.model_validate({"title": "a"}).due_date is None


@pytest.mark.parametrize(
    "value",
    [
        "2026-02-30",
        "01.12.2026",
        "2026-12-01T10:00:00",
        "2026-12-01T00:00:00",
        "20261201",
        20261201,
    ],
)
def test_due_date_invalid(value: Any) -> None:
    with pytest.raises(ValidationError):
        TaskCreate.model_validate({"title": "a", "due_date": value})


def test_extra_ignored() -> None:
    assert TaskCreate.model_validate({"title": "a", "x": 1}).title == "a"


def test_task_serialisation() -> None:
    t = Task(id="1", title="a", due_date=date(2026, 12, 1))
    assert t.model_dump(mode="json") == {"id": "1", "title": "a", "due_date": "2026-12-01"}
    assert Task(id="1", title="a", due_date=None).model_dump(mode="json")["due_date"] is None
