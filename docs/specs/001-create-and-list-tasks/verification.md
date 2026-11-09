# Verification — 001 Create and list tasks

**Result:** pass
**Commit:** 753184f · **Base:** 9ff2124 · **Trace:** 7/7 criteria named by tests (smoke: AC-001.1, AC-001.6)

Acceptance tests are unchanged since the red commit `5a8ab4f` (`git diff 5a8ab4f..HEAD -- tests/` touches only the two new unit-test files). `devbox run ci` green; smoke tests skip in-process and run after deploy to dev.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-001.1 | met | `tests/test_tasks.py::test_create_task_with_due_date`; smoke `tests/test_smoke_tasks.py::test_smoke_ac_001_1_create_task` | `src/taskboard8_api/tasks/router.py:25-30`, `src/taskboard8_api/tasks/store.py:17-21` (uuid4 id), `src/taskboard8_api/tasks/models.py:31-36` | Asserts 201, `id` non-empty str, `title` "Buy milk", `due_date` "2026-12-01" (and exactly the three keys, per contract). Smoke uses a `smoke-<uuid>` title, as the smoke rules require, and is marked `writes`. |
| AC-001.2 | met | `tests/test_tasks.py::test_create_task_without_due_date`, `::test_create_task_with_null_due_date` | `src/taskboard8_api/tasks/models.py:19`, `:24-25` | 201 and `due_date` is `None` for an absent field and for explicit `null`. |
| AC-001.3 | met | `tests/test_tasks.py::test_invalid_title_is_rejected` (8 cases), `::test_title_of_200_characters_is_accepted` | `src/taskboard8_api/tasks/models.py:15-18` (strict, strip, 1..200) | Covers all five named cases: missing (`{}`), not a string (`5`, `null`, `["a"]`), empty, whitespace-only, >200 after trimming (`"a"*201` and `" "+"a"*201+" "`). Each case asserts 422, `loc` `["body", …, "title"]`, and that a following `GET /tasks` is `[]`. The 200-character boundary (with surrounding spaces) is accepted. Booleans are covered by `tests/test_task_models_unit.py:20`. |
| AC-001.4 | met | `tests/test_tasks.py::test_bad_due_date_rejected` (6 cases) | `src/taskboard8_api/tasks/models.py:9`, `:21-28` (fullmatch format check before `date` parsing) | All three examples from the criterion (`"2026-02-30"`, `"01.12.2026"`, `"2026-12-01T10:00:00"`) plus `"20261201"`, an integer and `""`. Each asserts 422, `loc` ends in `due_date`, and `GET /tasks` is `[]` (no task created). The zero-time datetime `"2026-12-01T00:00:00"` from design.md is covered by `tests/test_task_models_unit.py:45`. |
| AC-001.5 | met | `tests/test_tasks.py::test_title_is_trimmed` | `src/taskboard8_api/tasks/models.py:17` (`strip_whitespace=True`), `router.py:28` stores `body.title` | Asserts the returned title and the listed title are both `"Buy milk"`. |
| AC-001.6 | met | `tests/test_tasks.py::test_list_returns_tasks_in_creation_order`; smoke `tests/test_smoke_tasks.py::test_smoke_ac_001_6_created_tasks_are_listed_in_order` (writes), `::test_smoke_ac_001_6_list_tasks_is_a_json_array` (read-only) | `src/taskboard8_api/tasks/router.py:33-36`, `src/taskboard8_api/tasks/store.py:17-25` (append under a lock, copy on list) | In-process: 200, a list equal to exactly the three created objects in creation order, titles in order, 3 distinct ids, each with exactly `id`/`title`/`due_date`. The smoke test checks the subsequence on a shared instance, as design.md Risks prescribes. Distinct ids are implied there by the strictly ordered, distinct-title positions. |
| AC-001.7 | met | `tests/test_tasks.py::test_list_is_empty_on_fresh_service` | `src/taskboard8_api/main.py:48-58` (fresh `TaskStore` per `create_app()`) | 200 and `[]` on a fresh `TestClient(create_app())`. |

## Non-goals

- Persistence: none. The store is an in-memory list (`store.py:14`). ✔
- No single-task read, edit, complete or delete: the router has only `POST /tasks` and `GET /tasks` (`router.py:25`, `:33`). ✔
- No pagination, filtering, sorting or search: `list_tasks` reads no query parameters (`router.py:34`). ✔
- No users, ownership, authentication or authorization code. ✔
- No limit on the number of tasks. ✔
- Template-owned layout: this is an API without a page layout. The existing `/health`, `/ready`, `/ping` and `/metrics` routes keep their paths, handlers and response models. They are now registered inside `create_app()` (`main.py:52-55`), which plan t2 asks for explicitly. ✔

## Deviations from the plan

- `tests/test_tasks.py` and `tests/test_smoke_tasks.py` are in no task's `files`. These are the acceptance tests from the red commit `5a8ab4f`, written before the tasks by design. Acceptable.
- `docs/specs/001-create-and-list-tasks/{spec,design,plan}.md` changed: spec status `approved` → `building` plus its changelog line, and design/plan were added in the planning commits. These are spec artifacts, not code. Acceptable.
- Both tasks t1 and t2 are `done: true`.
- `store.py:23` annotates the return type as the string `"list[Task]"` because the method name `list` shadows the builtin inside the class body. This is cosmetic, does not change the interface, and is acceptable.

## Contract

Matches `design.md`:

- `POST /tasks` returns 201 with exactly `id`/`title`/`due_date`, and FastAPI's default 422 body. No custom exception handler was added.
- `GET /tasks` returns a bare array, oldest first.
- `id` is `str(uuid.uuid4())`.
- Unknown fields are ignored through Pydantic's default.
- `create_app()` puts a fresh `TaskStore` on `app.state.task_store`, and module-level `app = create_app()` stays the uvicorn entry point.
- `configure_logging`/tracing stay at module level.
- Observability: the `task_created` event logs `task_id` only, never the title (`router.py:29`).

The contract's 422 for malformed JSON or a non-object body comes from the framework default and has no acceptance test. No criterion asks for one, so this is not a gap against the spec. ✔

## Mutation check (report only)

12 of 14 mutants of the changed code were caught by the acceptance tests (86 %; spec 152, report only).

Survived (a test that names the criterion would fail if it checked this):
- `src/taskboard8_api/tasks/models.py:17 True → False`
- `src/taskboard8_api/tasks/models.py:17 1 → 2`
