# Phase 1D minimal database-backed readiness

- Objective: implement only API-081, DEPLOY-023, DEPLOY-057, and SEC-039 readiness
  behavior through the existing runtime database boundary.
- Current task: complete and verified on `implementation/foundation`; changes remain
  uncommitted and unpushed as requested.
- Endpoint: `GET /api/v1/health/ready` performs an authenticated `SELECT 1` through
  `APP_DATABASE_URL`, with two-second connection and statement timeouts.
- Contract: success returns HTTP 200 with only `{"status":"ok"}`; missing runtime
  configuration or any database-check failure returns HTTP 503 with only
  `{"status":"unavailable"}`.
- Security: both outcomes retain `X-Request-ID`; unauthenticated responses expose no
  SQL, URL, credential, exception, configuration path, host, identity, or diagnostic.
- Testability: application construction accepts an injected readiness check for focused
  unit/API failure tests; production defaults to the real psycopg check. No pooling,
  dependency, migration, lifecycle, logging, or broad error-envelope work was added.
- Verification: focused health/traceability tests passed (21); `make format-check`,
  `make lint`, `make typecheck`, and `make test` passed (23 passed, 6 real-database
  tests skipped by the normal gate); `make database-test` passed all 6 real PostgreSQL
  tests including runtime readiness; `make build` passed package build and import.
- Scope review: canonical docs 001-010, dependency manifests, migrations, Compose,
  Makefile, `.env.example`, and `scripts/database-test.sh` are unchanged.
- Blocker: none.
- Exact next action: review the Phase 1D diff and publish only if separately requested;
  otherwise select the next bounded queue item under a fresh approval.
