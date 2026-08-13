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

## Security

`.env` is local-only. Do not commit passwords, API keys, database credentials,
customer information, production database backups, or other secrets. The liveness
response deliberately exposes only process status and a non-secret build identity.
