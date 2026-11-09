---
spec_id: 001-create-and-list-tasks
title: Create and list tasks
status: draft
priority: P1
shape: service-python
---

# 001 — Create and list tasks

## Problem

The Task API offers only health, readiness and ping endpoints today, so a client (a web front end, a script, a teammate with curl) has nowhere to record a task and read it back. Creating and listing tasks is the smallest useful slice of a task board and the base every later feature (completing, editing, deleting tasks) builds on. Tasks are kept in the service's memory for now, so the API can be used and tested before any storage is chosen.

## Stories

As an API client, I want to create a task with a title and, if I have one, a due date, so that I can record what needs doing.

As an API client, I want to list all tasks, so that I can see what has been recorded.

## Acceptance criteria

- **AC-001.1** Given a running service, when a client sends `POST /tasks` with JSON body `{"title": "Buy milk", "due_date": "2026-12-01"}`, then the response is `201` with a JSON object holding `id` (a non-empty string), `title` `"Buy milk"` and `due_date` `"2026-12-01"`. (smoke)
- **AC-001.2** Given a running service, when a client sends `POST /tasks` with only `{"title": "Buy milk"}`, then the response is `201` and the returned task has `due_date` `null`.
- **AC-001.3** Given a running service, when a client sends `POST /tasks` whose `title` is missing, not a string, empty, only whitespace, or longer than 200 characters after trimming, then the response is `422`, and a following `GET /tasks` does not contain a new task.
- **AC-001.4** Given a running service, when a client sends `POST /tasks` whose `due_date` is not a calendar date in the form `YYYY-MM-DD` (for example `"2026-02-30"`, `"01.12.2026"` or `"2026-12-01T10:00:00"`), then the response is `422` and no task is created.
- **AC-001.5** Given a title with leading or trailing whitespace such as `"  Buy milk  "`, when the task is created, then the returned and listed `title` is `"Buy milk"`.
- **AC-001.6** Given three tasks created one after another, when a client sends `GET /tasks`, then the response is `200` with a JSON array of exactly those three tasks, each with `id`, `title` and `due_date`, in the order they were created, and every `id` is distinct. (smoke)
- **AC-001.7** Given a freshly started service in which no task has been created, when a client sends `GET /tasks`, then the response is `200` with an empty JSON array `[]`.

## Non-goals

- Persistence: tasks are lost when the service restarts, and each running instance has its own task list.
- Reading a single task, editing, completing or deleting tasks.
- Pagination, filtering, sorting options or search on the list.
- Users, ownership or per-user task lists.
- Authentication or authorization: any client that can reach the service may create and list tasks; who can reach it is decided by the service's exposure in the system's deployment.
- A limit on the number of tasks kept in memory.

## Assumptions

- **A1** Tasks live at `POST /tasks` and `GET /tasks`, fields named `id`, `title`, `due_date` (other option: `dueDate` camelCase, or a `/api/v1` prefix; affects AC-001.1, AC-001.2, AC-001.6).
- **A2** `id` is an opaque string assigned by the service, unique within the running instance (other option: sequential integers from 1; affects AC-001.1, AC-001.6).
- **A3** A title is 1 to 200 characters after trimming surrounding whitespace; the trimmed title is stored (other option: no length limit, or store as sent; affects AC-001.3, AC-001.5).
- **A4** A due date is a plain calendar date `YYYY-MM-DD` without time or time zone; dates in the past are accepted (other option: full timestamp, or reject past dates; affects AC-001.4).
- **A5** Invalid input answers `422` with the framework's standard validation error body (other option: `400` with a custom error shape; affects AC-001.3, AC-001.4).
- **A6** The list is a bare JSON array in creation order, oldest first (other option: an object `{"tasks": [...]}`, or newest first; affects AC-001.6, AC-001.7).
- **A7** Unknown fields in the create body are ignored (other option: reject with `422`; affects AC-001.1).

## Open questions

- ~~May anyone who can reach the service create and list tasks without authentication?~~ Answered 2026-11-09: yes, no authentication in this spec; who can reach the service is decided by its exposure in the system's deployment. See the non-goal on authentication and AC-001.1, AC-001.6.

## Changelog

- 2026-11-09 created
- 2026-11-09 amended: open question on authentication answered (no authentication; access set by deployment exposure), recorded as a non-goal; criteria unchanged
