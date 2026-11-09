"""Request and response models for tasks."""

import re
from datetime import date
from typing import Annotated, Any

from pydantic import BaseModel, StringConstraints, field_validator

_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class TaskCreate(BaseModel):
    """Payload for creating a task."""

    title: Annotated[
        str,
        StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200),
    ]
    due_date: date | None = None

    @field_validator("due_date", mode="before")
    @classmethod
    def _check_due_date(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, str) and _DATE_RE.fullmatch(v):
            return v
        raise ValueError("due_date must be a date in the form YYYY-MM-DD")


class Task(BaseModel):
    """A stored task."""

    id: str
    title: str
    due_date: date | None
