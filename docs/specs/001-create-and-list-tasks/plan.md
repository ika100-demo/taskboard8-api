---
spec_id: 001-create-and-list-tasks
shape: service-python
spec_hash: 99e6b56dda29
summary: POST /tasks and GET /tasks backed by a per-instance in-memory store, with strict title and due-date validation
tasks:
  - id: t1
    title: Add task models (validation) and the in-memory TaskStore
    files: [src/taskboard8_api/tasks/__init__.py, src/taskboard8_api/tasks/models.py, src/taskboard8_api/tasks/store.py, tests/test_task_models_unit.py, tests/test_task_store_unit.py]
    covers: [AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: Expose POST/GET /tasks via a router and a create_app() factory
    files: [src/taskboard8_api/tasks/router.py, src/taskboard8_api/main.py]
    covers: [AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7]
    parallel_safe: true
    depends_on: [t1]
---

# Plan — 001 Create and list tasks

Design and contract: [design.md](design.md). Two levels: the domain package (t1), then the HTTP wiring (t2) that imports it. No gitops change: there are no new env vars, and the port and probes stay the same.

## t1 — Add task models (validation) and the in-memory TaskStore

**Files:** src/taskboard8_api/tasks/__init__.py, src/taskboard8_api/tasks/models.py, src/taskboard8_api/tasks/store.py, tests/test_task_models_unit.py, tests/test_task_store_unit.py
**Covers:** AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7
**Goal:** Build the `taskboard8_api.tasks` package with the request and response models, carrying every validation rule of the contract, and with a thread-safe in-memory store that keeps creation order. Nothing HTTP-specific yet.

**Implementation notes:**
- `__init__.py`: a module docstring only, no re-exports.
- `models.py`: `TaskCreate.title` is `Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200)]`, so non-strings are rejected and the length is checked after trimming (AC-001.3, AC-001.5).
- `TaskCreate.due_date: date | None = None` with a `@field_validator("due_date", mode="before")`. It returns `None` for `None`. A `str` must pass `re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", v)`, and anything else raises `ValueError`. Pydantic's `date` parsing then rejects impossible dates such as `2026-02-30` (AC-001.4).
- Keep Pydantic's default `extra="ignore"` (A7).
- `Task(BaseModel)`: `id: str`, `title: str`, `due_date: date | None`. Serialisation gives `"YYYY-MM-DD"` or `null`.
- `store.py`: `TaskStore` holds a `list[Task]` behind a `threading.Lock`. `add(title, due_date) -> Task` assigns `str(uuid.uuid4())` and appends. `list() -> list[Task]` returns a copy, oldest first (AC-001.6, AC-001.7).
- Unit tests for title: trimming, 200 vs 201 characters after trimming with surrounding spaces, whitespace-only, and the non-string types `1`, `true`, `null`, `[]`.
- Unit tests for due_date: valid, `null`, absent, `2026-02-30`, `01.12.2026`, `2026-12-01T10:00:00`, `2026-12-01T00:00:00`, `20261201`, an integer.
- Unit tests for the store: an empty list at start, insertion order, distinct ids, and that the returned list is a copy.
- mypy strict and ruff clean.

**Done when:** the unit tests pass under `devbox run test` and `devbox run quality` is clean. The acceptance tests cannot pass yet, because they need t2.

## t2 — Expose POST/GET /tasks via a router and a create_app() factory

**Files:** src/taskboard8_api/tasks/router.py, src/taskboard8_api/main.py
**Covers:** AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7
**Goal:** Serve the contract in design.md. Each `create_app()` call yields a fresh service with an empty store, and the module-level `app` remains the uvicorn entry point.

**Implementation notes:**
- `router.py`: `router = APIRouter(tags=["tasks"])`. `get_task_store(request: Request) -> TaskStore` returns `request.app.state.task_store`.
- `POST /tasks`: `status_code=201`, `response_model=Task`, sync handler taking `body: TaskCreate` and `Depends(get_task_store)`. It calls `store.add(body.title, body.due_date)` and logs `structlog` event `task_created` with `task_id`, never the title.
- `GET /tasks`: `response_model=list[Task]`, returns `store.list()`.
- No custom exception handler: FastAPI's default 422 body is the contract (A5).
- `main.py`: move the app construction into `def create_app() -> FastAPI`. That covers `FastAPI(...)`, `add_middleware(MetricsMiddleware)`, the existing `/health`, `/ready`, `/ping` and `/metrics` routes unchanged (register them on the app inside the factory, for example with `app.add_api_route` or an internal router), `include_router(tasks.router.router)` and `app.state.task_store = TaskStore()`.
- Keep `configure_logging(...)` and the tracing setup at module level, so they run once per process, then `app = create_app()`.
- The existing tests (`tests/test_health.py`, `tests/test_metrics.py`) import `taskboard8_api.main.app` and must still pass unchanged.

**Done when:** all acceptance tests for AC-001.1 to AC-001.7 pass in-process against `TestClient(create_app())`, the existing health and metrics tests still pass, and `devbox run ci` is green.
