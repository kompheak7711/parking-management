# Property Rental Management

Business management application built with React, TypeScript, FastAPI, and PostgreSQL.

## Status

Phase 1 foundation is in progress. The first bounded backend tranche provides a
packaged FastAPI service, environment-backed settings, a minimal liveness endpoint,
backend quality gates, and a production-oriented non-root container definition.
Database, authentication, readiness, business APIs, worker, frontend, and Compose
integration remain future work.

## Main components

- `frontend/` — React and TypeScript user interface (not initialized)
- `backend/` — FastAPI application, tests, package configuration, and Dockerfile
- `docs/` — authoritative requirements, architecture, and business documentation
- `ops/` — compact implementation state and next-work queue
- `scripts/` — development and maintenance utilities
- `compose.yaml` — local development services (not initialized)

## Prerequisites

- Git
- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/)
- Docker Desktop or another Docker-compatible builder (for container verification)

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

Set `APP_BUILD_VERSION` to a non-secret release version or commit identifier when
building/deploying. The Docker image accepts the same value as a build argument:

```text
docker build --build-arg APP_BUILD_VERSION=<version-or-commit> -t property-rental-backend backend
```

## Backend verification

Run the non-mutating quality gates:

```text
make test
make lint
make format-check
make typecheck
make build
```

`make format` intentionally rewrites backend Python files; `make format-check` does
not. `make test` also validates the machine-readable TEST-117 manifest at
`ops/traceability.json`. No current backend target starts, resets, migrates, or
deletes a database.

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
