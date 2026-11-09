# Design — 002 Keep tasks in Postgres so they survive restarts and are shared by every instance

## Decisions

- **Driver and connection handling: async psycopg 3, one connection per request, no pool. The schema is ensured in
  code under an advisory lock.** See [ADR-001](../../adr/001-postgres-access-psycopg-connection-per-request.md). This
  keeps outage behaviour deterministic: no connection outlives a request, so the next request after an outage
  reconnects (AC-002.4, AC-002.6), and nothing connects at start-up (AC-002.5).
- **`DATABASE_URL` is read when a connection is opened, not at import or in `create_app()`.** If it is unset or
  blank, the database counts as unreachable (AC-002.4). The URL is passed to psycopg unchanged (`postgresql://` is
  native), and the `PG*` variables are never used as a fallback. Reading the URL late lets the module-level `app` and
  every `create_app()` instance in tests pick up the database the test session starts. Tests switch databases with
  `monkeypatch.setenv/delenv("DATABASE_URL")`.
- **Time bounds:**
  - Every connection is opened with `connect_timeout=2` and `options="-c statement_timeout=3000"`, as the contract
    requires.
  - A request's whole database operation (connect, schema check, statement) also runs inside
    `asyncio.timeout(4.5)`. That is the client-side cap, so a hung server or network still gives `503` within 5 s
    (AC-002.4).
  - `/ready` runs `SELECT 1` on a fresh connection inside `asyncio.timeout(0.5)` (AC-002.5).
- **One error type for "unavailable".** `db.Database` turns the following into `DatabaseUnavailable`:
  - `DATABASE_URL` unset or blank;
  - any `psycopg.Error` raised while connecting, which includes a malformed URL;
  - `psycopg.OperationalError` and `psycopg.InterfaceError` raised by statements (statement timeout, admin
    shutdown, a dropped connection);
  - `OSError` and `TimeoutError`.

  Other errors, which are programming bugs, propagate as `500`. One exception handler in `create_app()` maps
  `DatabaseUnavailable` to `503 {"detail": "database unavailable"}`.
- **Validation still runs first.** The request body is validated by FastAPI before the handler runs, and the store
  dependency only returns the store object without touching the database, so an invalid body gets `422` even during
  an outage (AC-002.4).
- **Order and id.** Rows are ordered by `seq bigint GENERATED ALWAYS AS IDENTITY`, which the database assigns, so the
  order is one creation order across all instances (AC-002.1, AC-002.2). `id` stays `str(uuid.uuid4())`, generated in
  Python, stored as `uuid` and read back as `id::text`. That is the same canonical lowercase hyphenated string as
  before.
- **Handlers become `async def`.** The task routes and `/ready` await the async store. `/health`, `/ping` and
  `/metrics` stay as they are.
- **Test database: the devbox `postgresql` package plus a pytest session fixture in `tests/conftest.py`.**
  - The fixture runs `initdb` and `pg_ctl` into a throwaway temporary directory, on a free TCP port of
    `127.0.0.1`, with trust auth, fsync off and Unix sockets off.
  - It exports `DATABASE_URL` and stops the server at the end of the session.
  - The `test` recipe stays untouched, so `devbox run test` starts the database with no extra service, locally and in
    CI.
  - The fixture never reads the developer's own `DATABASE_URL`, `PGHOST` or `PGDATA` (the devbox postgresql plugin
    sets the last two), so tests never touch a real database.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `src/taskboard8_api/db.py` | `Database`: reads `DATABASE_URL`, opens one connection per operation with the timeouts, ensures the schema once per URL under the advisory lock, maps failures to `DatabaseUnavailable`, `ping()` for `/ready` | new |
| `src/taskboard8_api/tasks/store.py` | `TASKS_SCHEMA` DDL; `TaskStore` (async `add`, `list`) on top of `Database` | rewritten (was in-memory) |
| `src/taskboard8_api/tasks/router.py` | same routes, `async def` handlers awaiting the store | changed |
| `src/taskboard8_api/main.py` | `create_app()` wires `Database(schema=TASKS_SCHEMA)` and `TaskStore`, registers the `DatabaseUnavailable` → `503` handler, async `/ready` | changed |
| `src/taskboard8_api/tasks/__init__.py` | docstring no longer says "in-memory" | changed |
| `tests/conftest.py` | Postgres test harness (fixtures below) plus the existing `client` | changed |
| `devbox.json` | adds the package `postgresql@17` (recipes untouched) | changed |
| `pyproject.toml`, `uv.lock` | adds the runtime dependency `psycopg[binary]>=3.2` | changed |

Python interfaces (binding for coders and for test fixtures):

```python
# db.py
CONNECT_TIMEOUT_S = 2            # libpq connect_timeout
STATEMENT_TIMEOUT_MS = 3000      # options="-c statement_timeout=3000"
OPERATION_BUDGET_S = 4.5         # asyncio.timeout around one run()
READY_TIMEOUT_S = 0.5            # asyncio.timeout around ping()
SCHEMA_LOCK_KEY = 0x74626B38     # pg_advisory_xact_lock key ("tbk8")

class DatabaseUnavailable(Exception): ...

class Database:
    def __init__(self, schema: Sequence[str] = ()) -> None: ...
    async def run(self, op: Callable[[psycopg.AsyncConnection[Any]], Awaitable[T]]) -> T: ...
        # within asyncio.timeout(OPERATION_BUDGET_S):
        #   url = os.environ.get("DATABASE_URL", "").strip() or raise DatabaseUnavailable
        #   async with await AsyncConnection.connect(url, autocommit=True, connect_timeout=2,
        #                                            options="-c statement_timeout=3000") as conn:
        #       if url not in self._ensured: ensure schema (below); self._ensured.add(url)
        #       return await op(conn)
        # failures as listed in Decisions -> DatabaseUnavailable; log "database_unavailable" (reason=exception class)
    async def ping(self, timeout: float = READY_TIMEOUT_S) -> bool: ...
        # SELECT 1 on a fresh connection within asyncio.timeout(timeout); any failure -> False; never raises

# ensure schema: async with conn.transaction():
#     SELECT pg_advisory_xact_lock(SCHEMA_LOCK_KEY); then each statement of `schema`, in order
# no in-process lock: concurrent first requests both run the idempotent DDL, serialised by the advisory lock

# tasks/store.py
TASKS_SCHEMA: tuple[str, ...]    # the DDL in "Data" below

class TaskStore:
    def __init__(self, db: Database) -> None: ...
    async def add(self, title: str, due_date: date | None) -> Task: ...   # uuid4 id, INSERT, returns the Task
    async def list(self) -> list[Task]: ...                               # SELECT id::text, title, due_date ORDER BY seq

# main.py
def create_app() -> FastAPI: ...  # app.state.database, app.state.task_store; no DB access at construction or start-up
app: FastAPI                       # = create_app(), uvicorn entry (Dockerfile unchanged)
```

### Test harness (`tests/conftest.py`), binding for acceptance tests

| Fixture | Scope | Gives |
|---|---|---|
| `postgres_url` | session, autouse | Starts the throwaway Postgres and sets `os.environ["DATABASE_URL"]` to `postgresql://postgres@127.0.0.1:<port>/postgres`. Fails the session with "Postgres binaries not found: run the tests through `devbox run test`" when `initdb`/`pg_ctl` are missing. |
| `_empty_tasks_table` | function, autouse | Before each test, on the session database: `TRUNCATE tasks` when the table exists (`to_regclass('public.tasks')`), so every test starts from an empty table. It never drops the table. |
| `restartable_postgres` | function | A second throwaway cluster, already running: `.url: str`, `.stop()` (`pg_ctl stop -m fast -w`), `.start()` (same data dir and port, waits until it accepts connections). Used for outage and recovery tests (AC-002.4, AC-002.6) and for schema tests on a fresh database, so the session database is never stopped or dropped. |
| `refused_database_url` | function | A URL on `127.0.0.1` at a free port where nothing listens (a stopped database: connection refused). |
| `blackhole_database_url` | function | A URL to a local TCP listener that accepts connections and never answers (a hanging database). |
| `client` | function | Unchanged: `TestClient(app)` on the module-level app. |

Acceptance tests model "restart" and "two instances" with separate `create_app()` instances on the same
`DATABASE_URL` (AC-002.1, AC-002.2). They model an unreachable database with `monkeypatch.delenv("DATABASE_URL")`,
`refused_database_url`, `blackhole_database_url`, `postgresql://postgres@db.invalid:5432/postgres` (wrong host), or
`restartable_postgres.stop()`. A restart that runs the lifespan uses `with TestClient(create_app()) as c:`.

## Contract

The HTTP contract of [spec 001's design](../001-create-and-list-tasks/design.md#contract) is unchanged: same fields,
validation, `201`/`200`/`422` bodies, and the same rules about what tests may assert. This spec adds:

- `GET /tasks` and a valid `POST /tasks`: `503 Service Unavailable` with body `{"detail": "database unavailable"}`
  when the database is unreachable, answered within 5 s, and nothing is stored (AC-002.4). Tests assert only the
  status, never the body (system spec A4). An invalid `POST /tasks` body is still `422` with nothing stored, even
  during an outage.
- `GET /ready`: `200 {"status": "ready"}` when `SELECT 1` succeeds within 500 ms. Otherwise `503
  {"status": "unavailable"}`, answered within 1 s (AC-002.5). Tests assert the status. The `200` body stays exactly as
  before (`tests/test_health.py`).
- `GET /health`: `200 {"status": "ok"}` whenever the process runs. It never touches the database (AC-002.5).
- Persistence: tasks survive any restart of the service and are shared by all instances on the same `DATABASE_URL`.
  `GET /tasks` lists them in one creation order across instances (AC-002.1, AC-002.2, AC-002.3). After the database
  comes back, the next request is served (`/ready` is `200` at the next probe), well within 30 s (AC-002.6).

## Data

```sql
CREATE TABLE IF NOT EXISTS tasks (
    seq      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id       uuid   NOT NULL UNIQUE,
    title    text   NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
    due_date date
)
```

The table lives in the `public` schema of the database `DATABASE_URL` names. The CloudNativePG application user owns
that database, so it may create the table there, PostgreSQL 15 and later included. Insert:
`INSERT INTO tasks (id, title, due_date) VALUES (%s, %s, %s)`. List: `SELECT id::text, title, due_date FROM tasks
ORDER BY seq`.

## Configuration

`DATABASE_URL` is required for task routes and readiness. Unset, they answer `503` while `/health` stays `200`. The
gitops part of the system plan already injects it (with `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`,
which this service ignores). No gitops change. Add `DATABASE_URL` to `docs/env-vars.md`.

## Observability

- `structlog` event `database_unavailable` (warning) with `reason=<exception class name>` and `operation`. It never
  logs the URL, which holds the password, or the exception message, which may echo the host and user.
- `/ready` failures are logged at debug level only, because the probe runs every 5 s.
- `task_created` stays as it is. The request metrics show `503`s under `route="/tasks"`, with no new metrics.

## Risks

- **Connection set-up on every request:** a few milliseconds of latency per request in-cluster. Acceptable for this
  load. ADR-001 names the pool upgrade path.
- **A commit that lands just as the 4.5 s budget runs out** can store a task and still answer `503`. That needs a
  database hanging for more than 4 s after the commit. The client then retries and gets a duplicate. Accepted, since
  there are no retries in the system (contract: "No retries anywhere").
- **`initdb` refuses to run as root.** GitHub-hosted runners and developer machines are not root. A root
  self-hosted runner fails with a clear message from the harness.
- **Smoke:** the existing smoke tests stay as they are, and the read-only `GET /tasks → 200` smoke keeps staging and
  prod checked. Persistence across restarts and instances is checked in-process only, so no smoke test is added.
