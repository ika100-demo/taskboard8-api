---
spec_id: 002-keep-tasks-in-postgres-so-they-survive
title: Keep tasks in Postgres so they survive restarts and are shared by every instance
status: approved
priority: P1
shape: service-python
parent: ika100-demo/taskboard8-gitops:001-persistent-tasks-and-web-task-board
---

# 002 — Keep tasks in Postgres so they survive restarts and are shared by every instance

## Problem

The taskboard8 Task API keeps tasks in its own memory, so every restart or new rollout wipes the list, and two running instances would each show a different list. Nobody can rely on a task still being there tomorrow. On top of that, the only way to see or record a task is to call the API by hand: the web app still shows the template's starter page. This spec makes tasks durable in a Postgres database that the system declares, and turns the web app into a task board where people can see all tasks and add new ones.

## System context

Slice of the system plan `001-persistent-tasks-and-web-task-board` in `ika100-demo/taskboard8-gitops` for `taskboard8-api` (service-python). The system criteria and the contract below are binding: every criterion of this spec implements one of them and names it: `(system AC-<NNN>.<n>)`.

### System criteria

- **AC-001.1** Given three tasks created through `POST /tasks` of the Task API, when every instance of the Task API is restarted, then `GET /tasks` returns `200` with exactly those three tasks, each with the same `id`, `title` and `due_date` as before, in the order they were created.
- **AC-001.2** Given the Task API running with two instances, when a task is created through one request, then every later `GET /tasks`, whichever instance answers it, contains that task.
- **AC-001.3** Given the database is unreachable, when a client sends `GET /tasks` or a valid `POST /tasks`, then the response is `503`, the Task API's `/ready` answers `503` while `/health` still answers `200`, and no task is created; when the database is reachable again, then within 30 seconds and without a restart of the Task API, `GET /tasks` answers `200` with the tasks that existed before the outage.

### Contract

### Task API (taskboard8-api), unchanged from taskboard8-api spec 001

Base URL inside the environment: `http://taskboard8-api` (Service port 80 -> container 8080), given to the web app as
`TASK_API_URL` (no trailing slash). All bodies `application/json`; no authentication.

- `GET /tasks` -> `200`, a JSON array of tasks, oldest first (creation order), `[]` when none. A task is exactly
  `{"id": string, "title": string, "due_date": "YYYY-MM-DD" | null}`; `id` is an opaque non-empty string (do not parse),
  `title` is already trimmed, 1 to 200 characters.
- `POST /tasks` with `{"title": string, "due_date": "YYYY-MM-DD" | null}` (`due_date` may be omitted) -> `201` with the
  created task (same shape). The API trims `title`; the trimmed value must be 1 to 200 characters. Unknown fields are
  ignored.
  - `422` invalid body (FastAPI's standard `{"detail": [...]}`); nothing is stored.
  - `503` the database is unreachable (only for a valid body; validation runs first, so an invalid body still gets
    `422`); nothing is stored.
- `GET /ready` -> `200` when a `SELECT 1` on the database succeeds within 500 ms, else `503`. `GET /health` -> `200`
  whenever the process runs, never touches the database.
- Persistence: tasks are kept in the system's Postgres database (`DATABASE_URL`); order is the order of creation
  across all instances.

### Web app internal route (taskboard8-web, used only by its own browser code)

- `POST /api/tasks` with `{"title": string, "due_date": "YYYY-MM-DD" | null}`. The route trims the title and rejects
  an empty or over-200-character title itself with `422` (the browser has already checked; this guards direct calls)
  without calling the Task API; otherwise it forwards to the Task API's `POST /tasks`.
  - `201` with the Task API's task, unchanged.
  - `502` `{"error": "task_api_unavailable"}` for anything else from the Task API (unreachable, timeout, `5xx`, `422`
    or any unlisted status); the page then shows `The task could not be saved. Please try again.`
- Title length is counted in Unicode code points after `String.prototype.trim()` (Python counts the same way); the
  Task API's rule is authoritative.
- Due date input: an `<input type="date">`; empty means `null`. Display strings are exactly those of the spec:
  `No due date`, `No tasks yet.`, `Enter a title.`, `The title can be at most 200 characters.`,
  `Tasks could not be loaded. Please try again later.`, `The task could not be saved. Please try again.`

### Errors

- Task API error format: `422` is FastAPI's `{"detail": [ ... ]}`; `503` has a JSON body `{"detail": "database
  unavailable"}`, but callers and tests assert only the status, never the body (spec A4).
- The web app treats the Task API's answers as follows. `GET /tasks`: only `200` with a JSON array is success;
  anything else (connection error, timeout, any non-`200` status, a body that is not an array) shows
  `Tasks could not be loaded. Please try again later.` with page status `200`. `POST /tasks`: only `201` is success;
  everything else, `422` included, is "could not be saved" and the form keeps its input.
- The web app's own route answers only `201`, `422` or `502` as listed above; its browser code treats any other
  status or a network error like `502`.
- No retries anywhere: a person retries by reloading or submitting again (no live refresh, A8).

### Timeouts

- Web server -> Task API, `GET /tasks` and `POST /tasks`: 5 seconds total each (`AbortSignal.timeout(5000)`); on
  expiry the call counts as unavailable (messages above). The page is rendered on each request, so a slow API delays
  the page by at most 5 seconds before it shows the load error.
- Browser -> web `POST /api/tasks`: 10 seconds; on expiry the page shows the save error and keeps the form input.
- Task API -> Postgres: connect timeout 2 seconds, statement timeout 3 seconds, so a task request answers `503`
  within 5 seconds when the database is down or hanging; `/ready`'s check is bounded to 500 ms (the kubelet probe
  times out after 1 second). Broken connections are dropped and a new one is opened on the next request, so after
  the database is back the API serves again on its next request and `/ready` turns `200` at the next 5-second probe.
- When the Task API's only pod is not ready, its Service has no endpoints: the web app sees a connection error and
  shows its error messages; that is the intended behaviour.

### Provided by the system

The gitops part of this plan wires these for this repo; rely on them, do not ask for them again:

- resource `postgres`: env `DATABASE_URL`, `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`

### Notes for this repo

Storage only changes: the HTTP contract of spec 001-create-and-list-tasks (docs/specs/001-create-and-list-tasks/design.md)
stays exactly as it is, and its acceptance tests stay green, now against Postgres.
Config: `DATABASE_URL` (CloudNativePG URL with scheme `postgresql://`, user, password, host, port 5432 and database; PG* are injected too). If your driver
needs `postgresql+psycopg://`, rewrite the scheme in code, never in gitops. Missing `DATABASE_URL` = database unreachable.
Schema: ensured idempotently on the first successful connection (not only at start-up), guarded by a Postgres advisory
lock so two replicas starting together do not race. Order by a database-generated monotonically increasing column
(identity/bigserial), not by a timestamp. `id` stays an opaque uuid4 string.
Tests run against a real Postgres that `devbox run test` starts itself (devbox `postgresql` package with a throwaway
data dir per session, or an equivalent) so they pass locally and in CI with no extra service; each test starts from an
empty table. "Restart" and "two instances" are tested with separate `create_app()` instances on one database.
Smoke: keep the existing ones; a read-only `GET /tasks` -> 200 smoke must remain for staging/prod.

## Stories

<!-- As a <persona>, I want <goal>, so that <benefit>. -->

## Acceptance criteria

- **AC-002.1** Given three tasks created through `POST /tasks` against a database, when the service is stopped and a new service process is started against the same database (`DATABASE_URL`), then `GET /tasks` answers `200` with exactly those three tasks, each with the same `id`, `title` and `due_date`, in the order they were created (system AC-001.1)
- **AC-002.2** Given two service instances connected to the same database, when a task is created through `POST /tasks` on one of them, then every later `GET /tasks` on either instance contains that task, and tasks created alternately on both instances are listed by both in the one order they were created (system AC-001.2)
- **AC-002.3** Given an empty database, when a client sends `GET /tasks`, then the answer is `200` with `[]`; and every rule of the unchanged task contract (`201` body with exactly `id`, `title`, `due_date`; trimmed titles; `422` for an invalid title or due date with nothing stored) holds with tasks kept in the database (system AC-001.1)
- **AC-002.4** Given the database is unreachable (stopped, wrong host, or `DATABASE_URL` unset), when a client sends `GET /tasks` or a valid `POST /tasks`, then the answer is `503` within 5 seconds and no task is created; an invalid `POST /tasks` still answers `422` (system AC-001.3)
- **AC-002.5** Given the database is unreachable, when `/ready` and `/health` are called, then `/ready` answers `503` within 1 second and `/health` answers `200`; the process keeps running and does not exit, also when the database is already unreachable at start-up (system AC-001.3)
- **AC-002.6** Given the database became unreachable after tasks were created, when it is reachable again, then within 30 seconds and without restarting the service `/ready` answers `200` and `GET /tasks` answers `200` with the tasks that existed before the outage (system AC-001.3)

## Non-goals

## Assumptions

<!-- Spec 149: decisions taken by default, approved with the spec. One bullet each: - **A1** <the decision> (other option: <…>; affects AC-…). A revised one is struck through (~~…~~), never deleted. -->

## Open questions

<!-- Only what may not be decided by default (spec 149): security or access, money, destroying or migrating data, or a request too ambiguous to build. Approval is refused while any is open. Strike answered ones (~~…~~) and fold the answer into the criteria. -->

## Changelog

- 2026-11-10 created from the system plan, with its criteria (spec 147)
- 2026-11-10 approved
