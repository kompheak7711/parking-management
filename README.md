# Property Rental Management

Business management application built with React, TypeScript, FastAPI, and PostgreSQL.

## Status

Phase 1 foundation is in progress. The backend foundation provides a
packaged FastAPI service, environment-backed settings, minimal liveness and
database-backed readiness endpoints, backend quality gates, a non-root container, and
a bounded PostgreSQL development and migration foundation. A bounded frontend
foundation provides a strict React/TypeScript/Vite build and a non-business bootstrap
surface. The business schema, authentication, business APIs, worker, business screens,
and production deployment posture remain future work.

## Main components

- `frontend/` — React, TypeScript, and Vite frontend foundation
- `backend/` — FastAPI application, tests, package configuration, and Dockerfile
- `docs/` — authoritative requirements, architecture, and business documentation
- `ops/` — compact implementation state and next-work queue
- `scripts/` — development and maintenance utilities
- `compose.yaml` — authoritative loopback-only PostgreSQL development service

## Prerequisites

- Git
- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/)
- Docker Desktop or another Docker-compatible builder (for container verification)
- Node.js 22 or newer and npm

## Frontend setup

```text
make frontend-install
make frontend
```

The development UI listens on `http://127.0.0.1:5173`. Only public values prefixed
with `VITE_` are exposed by Vite. `VITE_APP_BUILD_ID` accepts a non-secret version or
commit identifier; `VITE_APP_ENVIRONMENT` accepts a public environment label. Neither
variable is required for local development.

## Backend setup

```text
make install
make dev
```

Settings are read from the process environment. `.env.example` documents available
values for local/deployment tooling; the backend does not implicitly read a local
`.env` file or bake it into an image.

The development API listens on `http://127.0.0.1:8000`. Its liveness endpoint is:

```text
GET /api/v1/health/live
{"status":"ok","version":"development"}
```

Readiness uses only the protected runtime `APP_DATABASE_URL` identity and returns no
diagnostics. PostgreSQL checks have bounded connection and execution timeouts:

```text
GET /api/v1/health/ready
{"status":"ok"}
```

Missing configuration or a failed check returns HTTP 503 with only
`{"status":"unavailable"}`. Both outcomes include `X-Request-ID`.

Set `APP_BUILD_VERSION` to a non-secret release version or commit identifier when
building/deploying. The Docker image accepts the same value as a build argument:

```text
docker build --build-arg APP_BUILD_VERSION=<version-or-commit> -t property-rental-backend backend
```

## Verification

Run the non-mutating quality gates:

```text
make test
make lint
make format-check
make typecheck
make build
```

`make format` intentionally rewrites backend and frontend source files;
`make format-check` does not. `make test` also validates the machine-readable TEST-117 manifest at
`ops/traceability.json`. Unit/API tests skip the real PostgreSQL suite unless its
three connection URLs are supplied.

GitHub Actions runs the same backend and frontend formatting, linting, strict type
checking, test, production-build, and traceability gates on pushes and pull requests.
It also audits the locked runtime/development dependency sets and runs the isolated
PostgreSQL migration gate exclusively through `make database-test`. The TEST-118
audit fails when a newly introduced material `BR-*` or `PR-*` heading has no mapping
in `ops/traceability.json`. Workflow actions and CI tool versions are immutable pins;
project dependencies continue to install only from `backend/uv.lock` and
`frontend/package-lock.json`.

## PostgreSQL and migrations

Alembic is the reviewed, versioned schema tool; psycopg is the PostgreSQL driver used
by migrations and integration tests. These are the only Phase 1C dependencies. Copy
the variable names from `.env.example` into protected process configuration and set
three distinct local passwords; do not source or commit `.env` files. Then start the
single development service with `docker compose up -d --wait postgres`. Identity
initialization runs only for a fresh PostgreSQL data directory; this foundation does
not alter an existing volume automatically. If an existing development volume lacks
these identities, stop and handle that data explicitly rather than deleting or
reinitializing it through project automation.

`MIGRATION_DATABASE_URL` uses `prm_migrator`, which owns schema changes.
`APP_DATABASE_URL` uses the non-owning `prm_runtime` identity. The application never
falls back to migration credentials. `TEST_ADMIN_DATABASE_URL` is test-only and must
name the local `prm_admin` bootstrap identity when tests are run directly.

Run `make migrate` to apply forward migrations. It never resets or recreates a
database and downgrade functions deliberately refuse destructive rollback. Run
`make database-test` to create one isolated PostgreSQL Compose project with freshly
generated credentials and an automatically assigned loopback port. The wrapper
discovers that actual port, runs the real migration gate, and removes its container
and volume on exit. Credentials are generated inside the wrapper and are neither
printed nor persisted. Direct test invocation still refuses non-loopback hosts,
unexpected database/role names, missing passwords, or reused identity passwords.

## Development workflow

1. Create or select a Git branch.
2. Review the relevant requirements and business rules.
3. Prepare an implementation plan.
4. Implement a focused change.
5. Run tests, type checks, formatting checks, lint, and builds.
6. Review the diff.
7. Commit only verified work.

## Autonomous supervision

OpenClaw checks compact state every 30 minutes without invoking a model when no
approved work is actionable. Each unchanged actionable fingerprint receives at most
one supervisor attempt, and a cycle above 100,000 tokens stops with an alert instead
of being retried automatically.

The 30-minute interval is only an idle wake-up cadence. After Hermes reports completion,
OpenClaw immediately verifies and publishes the tranche; if compact state advances to
a different explicitly authorized tranche, the dispatcher starts the next supervisor
cycle without waiting for another scheduled tick. Immediate chaining is capped at six
distinct tranches per wake-up to prevent an erroneous state transition from creating an
unbounded model loop.

Each actionable state produces a compact deterministic task packet and a fresh model
session. Explicitly low-risk mechanical tranches use the local Ollama route first;
unknown or sensitive tranches fail closed to Codex. A model-written low-risk label is
only a hint; deterministic sensitive-term checks can override it to high risk. Local
failure or unchanged compact state receives at most one fresh Codex escalation. Local
runs are limited to one tranche, two repair attempts, three no-progress tool calls,
and a 30,000-token budget.

The model-free preflight also enforces durable handoff invariants learned from prior
recovery incidents. An approved candidate with a missing `next_action` is dispatched
from its already-approved task instead of silently idling. A verified
`complete_uncommitted` or `complete_unpublished` tranche covered by standing
authorization is routed to independent publication verification and cannot demand a
redundant owner commit/push instruction. These cases are regression-tested by
`make automation-test` and any future repair must add or extend a deterministic test.

Automation repairs follow a permanent prevention protocol:

1. Identify and record the root cause; do not stop at retrying the failed cycle.
2. Repair the executable enforcement path that permitted the failure.
3. Add or extend a deterministic regression test that fails without the repair.
4. Update the supervisor prompt when agent behavior or authorization semantics change.
5. Update the watchdog and daily report when compact-state interpretation or
   owner-visible reporting changes.
6. Run `make automation-test`, then commit the focused repair so its rationale remains
   recoverable from Git history.

Only legitimately affected files are changed. A repair does not mechanically rewrite
all automation files; the regression test is the mandatory proof that the same defect
cannot silently recur.

A separate model-free watchdog sends Telegram only for a new publication or approval
request, a stalled approved tranche, an unhealthy supervisor, or recovery. Identical
events are deduplicated. The daily 08:00 Asia/Phnom_Penh report includes automation
health, last check and state update, repository synchronization, 24-hour model usage,
the reason for being idle, blockers, commits, and the exact next owner action.

## Security

`.env` is local-only. Do not commit passwords, API keys, database credentials,
customer information, production database backups, or other secrets. The liveness
response deliberately exposes only process status and a non-secret build identity.
