"""HTTP routes for tasks."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Request

from taskboard8_api.tasks.models import Task, TaskCreate
from taskboard8_api.tasks.store import TaskStore

router = APIRouter(tags=["tasks"])
log = structlog.get_logger()


def get_task_store(request: Request) -> TaskStore:
    store: TaskStore = request.app.state.task_store
    return store


StoreDep = Annotated[TaskStore, Depends(get_task_store)]


@router.post("/tasks", status_code=201, response_model=Task)
async def create_task(body: TaskCreate, store: StoreDep) -> Task:
    """Create a task."""
    task = await store.add(body.title, body.due_date)
    log.info("task_created", task_id=task.id)
    return task


@router.get("/tasks", response_model=list[Task])
async def list_tasks(store: StoreDep) -> list[Task]:
    """List tasks in creation order."""
    return await store.list()
