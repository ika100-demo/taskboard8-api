# ADR-001: Postgres access with async psycopg 3, a connection per request, and the schema ensured in code

## Status

Accepted (spec 002-keep-tasks-in-postgres-so-they-survive).

## Context

Tasks move from process memory into the system's Postgres database (`DATABASE_URL`, provided by the system's gitops
repo). The system contract has strict rules for an outage. A task request answers `503` within 5 seconds. `/ready`
answers within 500 ms (the kubelet probe times out after 1 s). The process never exits because the database is
down, not even at start-up. After an outage the service serves again within 30 seconds without a restart. The schema
has to be created idempotently on the first successful connection, guarded by an advisory lock, so that replicas
starting together do not race. The load is small: one table, a few requests per second at most.

Two choices outlive this feature: which driver to use and how connections are managed, and how the schema evolves.

## Decision

- **Driver: `psycopg[binary]` 3, async API (`psycopg.AsyncConnection`).** It takes the `postgresql://` URL as is, so the
  scheme is never rewritten. Its async connect and queries can be cancelled. That gives client-side wall-clock bounds
  with `asyncio.timeout` (4.5 s per request, 0.5 s for `/ready`) that libpq's integer `connect_timeout` (2 s minimum)
  cannot give on its own. No ORM: the queries are two plain SQL statements.
- **One connection per request, no pool.** Each request opens a connection with `connect_timeout=2` and
  `statement_timeout=3000`, does its work and closes it. No connection outlives a request, so after an outage the very
  next request reconnects. There are no background reconnect threads, no backoff, and no broken pooled connections
  to detect. Nothing connects at start-up, so start-up never fails because of the database.
- **The schema is ensured in code, without a migration tool.** The schema is a list of idempotent DDL statements
  (`CREATE TABLE IF NOT EXISTS ...`). It runs once per process and database URL, on the first successful connection,
  in one transaction that first takes `pg_advisory_xact_lock(<constant key>)`. A `DATABASE_URL` that is unset or blank
  counts as an unreachable database. The service never falls back to the `PG*` variables.

## Consequences

**Positive:** outage behaviour is deterministic and easy to test (stop the database and the next request gets `503`;
start it again and the next request succeeds). The service stays stateless, and start-up has no ordering dependency
on the database. Adds only one runtime dependency.

**Negative:** every request pays a connection set-up (TCP plus SCRAM auth, a few milliseconds in-cluster). When
traffic grows, switch to `psycopg_pool.AsyncConnectionPool` behind the same `Database.run()` interface, with a
per-checkout health check and reconnect settings that keep the 30-second recovery. Schema changes beyond additive,
idempotent DDL (renames, backfills, drops) need a migration tool. The first spec that needs one introduces it and
supersedes the schema part of this ADR.
