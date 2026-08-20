# Property Rental Management

Business management application built with React, TypeScript, FastAPI, and PostgreSQL.

## Status

The application foundation is in progress. The backend provides a
packaged FastAPI service, environment-backed settings, minimal liveness and
database-backed readiness endpoints, backend quality gates, a non-root container, and
a bounded PostgreSQL development and migration foundation. It also exposes the bounded
local login, TOTP MFA enrollment/challenge, recovery-code challenge, logout, session
inspection, and reauthentication API over secure browser-cookie and CSRF transport. The
backend also provides atomic recovery-code, authorized Owner-to-Manager/Staff, and controlled
server-side emergency Owner recovery orchestration with recovery-specific rate limiting,
applicable-session revocation, and immutable secret-free audit evidence; it exposes no
unauthenticated Owner-reset endpoint. A
bounded frontend foundation provides a strict React/TypeScript/Vite build and a non-business
bootstrap surface. Business workflow APIs, the runtime authentication-flow adapter, worker,
business screens, and production deployment posture remain future work.

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

Settings are read from protected process configuration. `.env.example` contains public
settings and secret-file path names only; it contains no credential or key value. The
backend does not implicitly read a local `.env` file or bake one into an image.

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

Set `APP_ALLOWED_BROWSER_ORIGIN` to the exact HTTPS browser origin permitted to submit
authentication mutations. It defaults to `https://localhost`. Authentication routes fail
closed with `503 Service Unavailable` until an atomic runtime authentication-flow adapter
is configured; no in-memory or external-identity fallback is used.

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
by migrations and integration tests. These are the only Phase 1C dependencies. Create
six distinct local-only password files at the ignored `.local/secrets/` paths named by
`.env.example`, using an external protected input method and restrictive permissions;
never put their values in Git, logs, or command arguments. Export only the corresponding
`*_FILE` path variables, then start the single development service with
`docker compose up -d --wait postgres`. Identity
initialization runs only for a fresh PostgreSQL data directory; this foundation does
not alter an existing volume automatically. If an existing development volume lacks
these identities, stop and handle that data explicitly rather than deleting or
reinitializing it through project automation.

`MIGRATION_DATABASE_URL` uses `prm_migrator`, which owns schema changes.
`APP_DATABASE_URL` uses the non-owning `prm_runtime` identity. The application never
falls back to migration credentials. `TEST_ADMIN_DATABASE_URL` is test-only and must
name the local `prm_admin` bootstrap identity when tests are run directly.

The five managed identities and protected source names are defined in
`config/deployment/identity-secret-contract.json`; environment-specific files in the same
directory contain source references only. `prm_backup` is read-only, `prm_restore` has no
standing data access, and exceptional `prm_human_admin` access has monitoring but no table
mutation. See `docs/DEPLOYMENT_IDENTITY_SECRET_SCAFFOLDING.md`. Validate committed examples
with `make deployment-config-check`. Deployment tooling must additionally run
`python3 scripts/validate-deployment-config.py check-profile <profile>` after mounting every
protected source; production fails closed while any source is absent or placeholder-only.

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
approved work is actionable. Each unchanged actionable fingerprint receives one
implementation attempt and at most one repair attempt. Exhaustion is persisted and
alerted once instead of silently appearing healthy. A cycle above 60,000 tokens stops
instead of being retried automatically.

Attempt identity is explicitly scoped by roadmap tranche ID. Structured successor
selection activates the successor lifecycle and initializes a repair object bearing that
same tranche ID; preflight ignores repair counters, failures, and protection flags whose
recorded tranche ID does not match the dispatched tranche. Published predecessor repair
exhaustion therefore cannot consume a successor's independent bounded attempts.

The 30-minute interval is only an idle wake-up cadence. After Hermes reports completion,
OpenClaw immediately verifies and publishes the tranche; if compact state advances to
a different explicitly authorized tranche, the dispatcher starts the next supervisor
cycle without waiting for another scheduled tick. Immediate chaining is capped at six
distinct tranches per wake-up to prevent an erroneous state transition from creating an
unbounded model loop.

Each actionable state produces a compact deterministic task packet, a task file delivered
through the validated Hermes wrapper, and a fresh model session. Explicitly low-risk
mechanical tranches use the local Ollama route first;
unknown or sensitive tranches fail closed to Codex. A model-written low-risk label is
only a hint; deterministic sensitive-term checks can override it to high risk. Local
failure or unchanged compact state receives at most one fresh Codex escalation. Local
runs are limited to one tranche, two repair attempts, three no-progress tool calls,
and a 30,000-token budget.

The model-free preflight also enforces durable handoff invariants learned from prior
recovery incidents. An approved candidate with a missing `next_action` is dispatched
from its already-approved task instead of silently idling. A verified
`verified_unpublished`, `complete_uncommitted`, or `complete_unpublished` tranche covered by standing
authorization is routed to independent publication verification and cannot demand a
redundant owner commit/push instruction. These cases are regression-tested by
`make automation-test` and any future repair must add or extend a deterministic test.
The executable rule primarily uses structured approval lifecycle fields—not an open-ended
list of worker-written status labels—so any future label with implementation complete,
publication incomplete, approved scope, and no blockers follows the same publication path.
Any other unrecognized status under durable authorization enters a bounded state-contract
repair instead of silent idle; a state that cannot be safely normalized produces one
deduplicated Telegram alert.
Implementers must record an uncommitted completed tranche as `complete_uncommitted`.
For recovery from the previously emitted `verified_unpublished` and
`implemented_awaiting_supervisor_review` aliases,
preflight routes the same mandatory publication action instead of silently idling.
Published state with an explicitly approved next candidate is also actionable: preflight
routes that candidate immediately and the task packet takes its phase and risk metadata,
so publication does not create an unnecessary approval or scheduler wait.
If Hermes instead emits the exact unselected/not-approved placeholder while the queue
still grants durable bounded-v1 authorization, or omits the candidate using any other wording,
preflight ignores the prose and reads `ops/V1_ROADMAP.json`. One unique safe successor
is materialized, committed, pushed, CI-checked, and dispatched without a model. No unique safe
successor produces one deduplicated `HANDOFF_MISSING` alert. Concrete protected or
policy-dependent candidates remain non-actionable and still require the Owner.
If a clean upstream-synchronized HEAD has advanced beyond the commit recorded by a
pre-publication state, the dispatcher performs compact-state reconciliation, commit,
push, and GitHub Actions polling deterministically without invoking a model. A
`not_approved` candidate cannot be dispatched through stale publication state.

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

Ordinary technical failures within an already approved tranche carry durable standing
repair authority. OpenClaw may automatically diagnose, repair, add regression coverage,
reverify, commit, push, and recheck GitHub Actions for at most two attempts. Successful
repair activity is silent. Owner attention is required only after the attempt limit or
when a correction crosses canonical/architecture policy, business or financial policy,
destructive data operations, actual production secrets or credentials, production
deployment, remote access, history rewriting, suspected secret exposure, or the original
approved scope.

A separate model-free watchdog sends Telegram after every newly published roadmap tranche,
including the verified commit, roadmap progress, and exact next action. It also reports an
approval request, a stalled approved tranche, an unhealthy supervisor, or recovery. Identical
events are deduplicated. The daily 08:00 Asia/Phnom_Penh report includes automation
health, last check and state update, repository synchronization, 24-hour model usage,
the reason for being idle, blockers, commits, and the exact next owner action.

## Security

`.env` is local-only. Do not commit passwords, API keys, database credentials,
customer information, production database backups, or other secrets. The liveness
response deliberately exposes only process status and a non-secret build identity.
