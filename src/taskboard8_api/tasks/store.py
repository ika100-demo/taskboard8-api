"""Postgres-backed task store."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import psycopg

from taskboard8_api.db import Database
from taskboard8_api.tasks.models import Task

TASKS_SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS tasks (
        seq      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        id       uuid   NOT NULL UNIQUE,
        title    text   NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
        due_date date
    )
    """,
)


class TaskStore:
    """Keeps tasks in Postgres, listed in creation order."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def add(self, title: str, due_date: date | None) -> Task:
        task = Task(id=str(uuid.uuid4()), title=title, due_date=due_date)

        async def op(conn: psycopg.AsyncConnection[Any]) -> None:
            await conn.execute(
                "INSERT INTO tasks (id, title, due_date) VALUES (%s, %s, %s)",
                (task.id, task.title, task.due_date),
            )

        await self._db.run(op)
        return task

    async def list(self) -> list[Task]:
        async def op(conn: psycopg.AsyncConnection[Any]) -> list[Task]:
            cur = await conn.execute("SELECT id::text, title, due_date FROM tasks ORDER BY seq")
            rows = await cur.fetchall()
            return [Task(id=r[0], title=r[1], due_date=r[2]) for r in rows]

        return await self._db.run(op)
