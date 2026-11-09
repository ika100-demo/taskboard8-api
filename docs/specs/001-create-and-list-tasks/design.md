# Design — 001 Create and list tasks

## Decisions

- **Request validation is done by Pydantic models plus one explicit date check; error bodies come from FastAPI's own `RequestValidationError` handler** (A5). No custom exception handler, so `422` bodies look the same as on every other FastAPI endpoint.
- **`title` is a strict string** (`StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200)`): numbers, booleans, `null`, arrays and objects are rejected rather than coerced. Pydantic strips the whitespace first and then checks the length, so the 1–200 limit applies to the trimmed value (AC-001.3, AC-001.5, A3).
- **`due_date` is checked by a `mode="before"` validator before Pydantic parses it as a `date`.** The validator accepts `None` or a string that fully matches `[0-9]{4}-[0-9]{2}-[0-9]{2}`. Anything else raises `ValueError`. Pydantic's lax `date` parsing on its own would accept Unix timestamps (`1764547200`) and zero-time datetimes (`"2026-12-01T00:00:00"`), which breaks AC-001.4. Once the format check passes, Pydantic's `date` parsing rejects dates that do not exist on the calendar (`"2026-02-30"`). The value is stored as `datetime.date` and serialised as `"YYYY-MM-DD"` (A4: past dates are accepted).
- **Tasks live in an in-memory `TaskStore` owned by the app instance (`app.state.task_store`), created by an app factory `create_app()`.** Every call builds a fresh, empty service, so acceptance tests can get a "freshly started service" (AC-001.7) and exact lists (AC-001.6) without any reset hooks. `taskboard8_api.main:app = create_app()` stays the uvicorn entry point, and the Dockerfile does not change. The store is guarded by a `threading.Lock`, because FastAPI runs the sync handlers in a thread pool.
- **`id` is `str(uuid.uuid4())`.** The contract treats it as an opaque, non-empty string, and clients must not parse it (A2).
- Unknown body fields are ignored, which is Pydantic's default `extra="ignore"` (A7).
- No ADR: in-memory storage is a temporary choice that this spec states itself, and the error format is the framework default that ADR-000 already adopts.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `src/taskboard8_api/tasks/__init__.py` | package marker, no re-exports | new |
| `src/taskboard8_api/tasks/models.py` | `TaskCreate` (request, validation) and `Task` (response) | new |
| `src/taskboard8_api/tasks/store.py` | `TaskStore`: thread-safe, in-memory, keeps creation order | new |
| `src/taskboard8_api/tasks/router.py` | `APIRouter` with `POST /tasks` and `GET /tasks`, plus the `get_task_store` dependency | new |
| `src/taskboard8_api/main.py` | `create_app()` factory; includes the tasks router; module-level `app = create_app()` | changed |

Python interfaces (binding for coders and for the acceptance-test fixture):

```python
# tasks/models.py
class TaskCreate(BaseModel):      # extra fields ignored
    title: Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200)]
    due_date: date | None = None  # before-validator: None or str matching ^[0-9]{4}-[0-9]{2}-[0-9]{2}$

class Task(BaseModel):
    id: str
    title: str
    due_date: date | None         # JSON: "YYYY-MM-DD" or null

# tasks/store.py
class TaskStore:
    def add(self, title: str, due_date: date | None) -> Task: ...   # assigns a uuid4 id, appends
    def list(self) -> list[Task]: ...                               # a copy, oldest first

# main.py
def create_app() -> FastAPI: ...  # new app, empty TaskStore on app.state.task_store
app: FastAPI                       # = create_app(), uvicorn entry
```

**Acceptance-test fixture:** use one `TestClient(create_app())` per test, so each test starts from an empty store. The shared module-level `app` that the existing `client` fixture in `tests/conftest.py` uses keeps its tasks across tests.

## Contract

All bodies are `application/json`. Authentication is not required (non-goal).

### `POST /tasks` — create a task

Request body (a JSON object):

| Field | Type | Rule |
|---|---|---|
| `title` | string, required | Leading and trailing whitespace is removed (Python `str.strip()`). The trimmed value must be 1–200 characters. A non-string value is rejected. |
| `due_date` | string or `null`, optional | Exactly `YYYY-MM-DD` and a real calendar date. Absent or `null` means no due date. Any other value or format (`"01.12.2026"`, `"2026-12-01T10:00:00"`, `"20261201"`, a number) is rejected. |
| anything else | — | ignored |

Responses:

- `201 Created`, body `{"id": string, "title": string, "due_date": string | null}`, with exactly these three keys. `title` is the trimmed value, `due_date` is `"YYYY-MM-DD"` or `null`, and `id` is non-empty and unique within the instance (AC-001.1, AC-001.2, AC-001.5).
- `422 Unprocessable Entity` for any invalid body, including malformed JSON or a body that is not an object. The body is FastAPI's standard validation error format, and no task is stored (AC-001.3, AC-001.4):
  ```json
  {"detail": [{"type": "string_too_short", "loc": ["body", "title"], "msg": "...", "input": "   ", "ctx": {...}}]}
  ```
  `detail` is a non-empty array. For a field error, each entry's `loc` starts with `"body"` and ends with the field name (`"title"` or `"due_date"`). Tests may assert the status, that `detail` is a non-empty list and the `loc` field name. They must not assert `type` or `msg` text.

Example: `POST /tasks {"title": "  Buy milk  ", "due_date": "2026-12-01"}` returns `201 {"id": "3f2c…", "title": "Buy milk", "due_date": "2026-12-01"}`.

### `GET /tasks` — list tasks

- `200 OK`, body: a JSON array of task objects (same shape as the `201` body), in creation order, oldest first. On an instance where nothing has been created it is `[]` (AC-001.6, AC-001.7). No query parameters are read.

## Observability

- `structlog` event `task_created` with the `task_id` field. The title is not logged, because it is user content.
- The request metrics work unchanged: the middleware labels the routes `/tasks`.

## Risks

- **More than one replica:** each instance has its own list (a non-goal), so a create followed by a list can land on different pods and the list then misses the task. Tests are unaffected in-process. The deployed smoke test for AC-001.6 needs a single replica in dev. The gitops entry's default is one replica; nothing to change.
- **Smoke tests on a shared instance:** a deployed instance already holds other tasks. The smoke test for AC-001.6 (`@pytest.mark.writes`) therefore creates three `smoke-<uuid>` tasks and checks that they appear in creation order as a subsequence of `GET /tasks`, not as the whole list. A read-only smoke test checks only that `GET /tasks` returns `200` with a JSON array, so staging and prod keep a passing smoke check.
- **Unbounded memory:** there is no task limit (non-goal). A restart clears the list.
