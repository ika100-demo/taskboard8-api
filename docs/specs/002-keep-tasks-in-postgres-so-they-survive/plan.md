---
spec_id: 002-keep-tasks-in-postgres-so-they-survive
shape: service-python
spec_hash: 98a20a2bd7b5
summary: Tasks kept in the system's Postgres (async psycopg, a connection per request, schema ensured under an advisory lock), 503 and a real /ready while the database is down, tested against a throwaway Postgres
tasks:
  - id: t1
    title: Add psycopg and the throwaway-Postgres test harness
    files: [pyproject.toml, uv.lock, devbox.json, tests/conftest.py]
    covers: [AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.6]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: Add the Database layer (timeouts, schema once under advisory lock, unavailable mapping, ping)
    files: [src/taskboard8_api/db.py, tests/test_database_unit.py, docs/env-vars.md]
    covers: [AC-002.4, AC-002.5, AC-002.6]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t3
    title: Back the task routes with Postgres, map outages to 503 and make /ready check the database
    files: [src/taskboard8_api/tasks/store.py, src/taskboard8_api/tasks/router.py, src/taskboard8_api/tasks/__init__.py, src/taskboard8_api/main.py, tests/test_task_store_unit.py]
    covers: [AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6]
    parallel_safe: true
    depends_on: [t2]
---

# Plan — 002 Keep tasks in Postgres so they survive restarts and are shared by every instance

Design and contract: [design.md](design.md). The driver and connection decisions are in
[ADR-001](../../adr/001-postgres-access-psycopg-connection-per-request.md).

The work runs in three levels, each one building on the one before:

1. t1: the dependency and the test database.
2. t2: the database layer that imports psycopg and is tested against that database.
3. t3: the store and HTTP wiring that import the database layer.

No gitops task. The system plan's gitops part already injects `DATABASE_URL` from the `postgres` resource. The port,
probe paths and image stay the same.

## t1 — Add psycopg and the throwaway-Postgres test harness

**Files:** pyproject.toml, uv.lock, devbox.json, tests/conftest.py
**Covers:** AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.6
**Goal:** `devbox run test` starts a real, throwaway Postgres itself and stops it at the end, locally and in CI with
no extra service. Every test starts from an empty `tasks` table. The acceptance tests get the fixtures that design.md
names (under "Test harness").

**Implementation notes:**
- `pyproject.toml`: add `"psycopg[binary]>=3.2"` to `[project] dependencies`. Refresh `uv.lock` with `uv lock` inside
  `devbox shell`. Never use `uv add` or `pip`.
- `devbox.json`: add `"postgresql@17"` to `packages` only. Do not touch any recipe (they are template-owned).
- `tests/conftest.py` keeps the existing `client` fixture. Add a small `PostgresServer` helper class there with
  `start()`, `stop()` and `url`:
  - Locate `initdb` and `pg_ctl` with `shutil.which`. If either is missing, call `pytest.exit` with the message from
    design.md.
  - Run `initdb -D <tmp> -U postgres -A trust -E UTF8 --no-sync` with a temporary directory from `tmp_path_factory`
    or `tmp_path`.
  - Pick a free port by binding `127.0.0.1:0`.
  - Start with `pg_ctl -D <dir> -l <dir>/log -w -o "-p <port> -c listen_addresses=127.0.0.1 -c unix_socket_directories='' -c fsync=off -c synchronous_commit=off -c full_page_writes=off" start`.
  - Stop with `pg_ctl -D <dir> -m fast -w stop`, also when the tests fail.
  - Pass `-D` everywhere and ignore the `PGHOST` and `PGDATA` that the devbox plugin sets.
- `postgres_url` (session, autouse): starts one server and sets `os.environ["DATABASE_URL"]` to
  `postgresql://postgres@127.0.0.1:<port>/postgres`. It overrides any value the developer has set.
- `_empty_tasks_table` (function, autouse): connects to `postgres_url` with psycopg (sync is fine) and runs
  `TRUNCATE tasks` only when `to_regclass('public.tasks')` is not null. It never drops the table.
- `restartable_postgres` (function): a second server, started. It exposes `.url`, `.stop()` and `.start()` on the
  same data dir and port, and is stopped at teardown.
- `refused_database_url` (function): a URL on a free port of `127.0.0.1` where nothing listens.
- `blackhole_database_url` (function): a background `socket` listener on `127.0.0.1` that accepts connections and
  never sends anything. It is closed at teardown.
- `tests/` is excluded from mypy, but keep the code ruff-clean. No passwords in URLs (trust auth), so detect-secrets
  stays quiet.

**Done when:** `devbox run test` starts and stops Postgres by itself, and every existing test passes unchanged with
the harness active, including `tests/test_tasks.py` (still in-memory at this point). `devbox run quality` and
`devbox run security` are green. The new acceptance tests cannot pass yet.

## t2 — Add the Database layer (timeouts, schema once under advisory lock, unavailable mapping, ping)

**Files:** src/taskboard8_api/db.py, tests/test_database_unit.py, docs/env-vars.md
**Covers:** AC-002.4, AC-002.5, AC-002.6
**Goal:** Build `taskboard8_api.db` exactly as the interface in design.md describes. It gives every database
operation the contract's time bounds, turns every way the database can be unreachable into `DatabaseUnavailable`,
ensures the schema once per URL under the advisory lock, and offers a `ping()` for `/ready` that never raises.

**Implementation notes:**
- Constants and signatures as in design.md (`CONNECT_TIMEOUT_S`, `STATEMENT_TIMEOUT_MS`, `OPERATION_BUDGET_S`,
  `READY_TIMEOUT_S`, `SCHEMA_LOCK_KEY`, `DatabaseUnavailable`, `Database.run`, `Database.ping`).
- `run()`:
  - Read `DATABASE_URL` on every call. If it is unset or blank, raise `DatabaseUnavailable`.
  - Wrap connect, schema and `op` in `asyncio.timeout(OPERATION_BUDGET_S)`.
  - Connect with `psycopg.AsyncConnection.connect(url, autocommit=True, connect_timeout=2, options="-c statement_timeout=3000")`
    and always close the connection.
- Schema: when the URL is not in `self._ensured`, open `async with conn.transaction()`, run
  `SELECT pg_advisory_xact_lock(%s)` with `SCHEMA_LOCK_KEY`, then each statement of `schema` in order. Add the URL to
  `_ensured` only after the transaction commits. No in-process lock.
- Error mapping exactly as listed in design.md's Decisions. Anything else propagates. Log `database_unavailable` at
  warning level with `reason=type(exc).__name__`, and never include the URL or the exception message.
- `ping(timeout)`: `SELECT 1` on a fresh connection inside `asyncio.timeout(timeout)`. Return `True` or `False` and
  never raise. Log failures at debug level.
- Unit tests (`tests/test_database_unit.py`, using the t1 fixtures; schema tests use `restartable_postgres`, never the
  session database):
  - `ping` is `True` on `postgres_url`.
  - `ping` is `False` within 1 s for an unset URL, `refused_database_url`, `blackhole_database_url` and a
    `db.invalid` host.
  - `run` raises `DatabaseUnavailable` within 5 s in the same four cases.
  - The schema is created on the first `run` and not again on the second.
  - Two `Database` instances running their first `run` at the same time (`asyncio.gather`) on a fresh cluster both
    succeed.
  - After `restartable_postgres.stop()`, `run` raises `DatabaseUnavailable`. After `start()`, the next `run`
    succeeds without a new `Database`.
- `docs/env-vars.md`: add a "Database" section. `DATABASE_URL` has no default. It is required for task routes and
  `/ready`, and when unset they answer `503`. It is a `postgresql://` URL injected by the system's `postgres`
  resource. The `PG*` variables are ignored.
- mypy strict and ruff clean.

**Done when:** `tests/test_database_unit.py` passes under `devbox run test`, and `devbox run quality` and
`devbox run security` are green. The acceptance tests still need t3.

## t3 — Back the task routes with Postgres, map outages to 503 and make /ready check the database

**Files:** src/taskboard8_api/tasks/store.py, src/taskboard8_api/tasks/router.py, src/taskboard8_api/tasks/__init__.py, src/taskboard8_api/main.py, tests/test_task_store_unit.py
**Covers:** AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6
**Goal:** Replace the in-memory store with a Postgres-backed `TaskStore` on top of `Database`, and wire it into
`create_app()`. Add the `DatabaseUnavailable` → `503` handler and make `/ready` reflect the database. The HTTP
contract of spec 001 stays exactly as it is.

**Implementation notes:**
- `tasks/store.py`:
  - `TASKS_SCHEMA` is a tuple holding the one `CREATE TABLE IF NOT EXISTS tasks (...)` statement from design.md's
    Data section.
  - `TaskStore(db)` uses `db.run(...)`. `add(title, due_date)` generates `str(uuid.uuid4())`, runs the `INSERT` and
    returns the `Task` built from its inputs.
  - `list()` runs `SELECT id::text, title, due_date FROM tasks ORDER BY seq` and returns `list[Task]`.
- `tasks/router.py`: same routes, `response_model`s and status codes, with `async def` handlers that await the store.
  `get_task_store` still only returns `request.app.state.task_store`, so validation (`422`) runs before any database
  access. Keep the `task_created` log line.
- `main.py` `create_app()`:
  - `app.state.database = Database(schema=TASKS_SCHEMA)` and `app.state.task_store = TaskStore(app.state.database)`.
  - `app.add_exception_handler(DatabaseUnavailable, ...)` returns `JSONResponse({"detail": "database unavailable"}, status_code=503)`.
  - Nothing connects at construction or in a lifespan.
- `/ready` becomes `async def ready(request: Request) -> JSONResponse`. It answers `200 {"status": "ready"}` when
  `await request.app.state.database.ping()` is true, and `503 {"status": "unavailable"}` otherwise. `/health`,
  `/ping` and `/metrics` stay unchanged. Keep `app = create_app()` as the uvicorn entry, so the Dockerfile does not
  change.
- `tasks/__init__.py`: the docstring becomes "Task models and Postgres-backed storage."
- `tests/test_task_store_unit.py`: rewrite it for the Postgres `TaskStore`, since the in-memory API is gone. Cover an
  empty list, insertion order across two `TaskStore` instances on the same database, distinct ids, `due_date`
  round-trip (`None` and a date), and `DatabaseUnavailable` from `add` and `list` when `DATABASE_URL` is unset.
- Do not edit `tests/test_tasks.py`, `tests/test_health.py`, the smoke tests or the new acceptance tests. They must
  pass as they are, now against Postgres. The read-only `GET /tasks` smoke stays.

**Done when:** every acceptance test for AC-002.1 to AC-002.6 passes, spec 001's `tests/test_tasks.py` and
`tests/test_health.py` still pass unchanged, and `devbox run ci` is green, including the coverage gate.
