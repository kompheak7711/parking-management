# Phase 1D minimal database-backed readiness

- Objective: implement only API-081, DEPLOY-023, DEPLOY-057, and SEC-039 readiness
  behavior through the existing runtime database boundary.
- Current task: complete and published on `implementation/foundation` as
  `a32b2e615a377d362fa4bea3ac5132634560b1ca`; no implementation cycle is active.
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
- Verification: lock, Ruff format/lint, strict mypy, traceability, package/import,
  container build/import/non-root, runtime and development dependency audit, secret,
  scope, diff, and canonical-integrity gates passed. The normal suite passed 23 tests
  with 6 dedicated database tests skipped; `make database-test` passed all 6 against
  its repository-managed isolated PostgreSQL service.
- Scope review: canonical docs 001-010, dependency manifests, migrations, Compose,
  Makefile, `.env.example`, and `scripts/database-test.sh` are unchanged.
- Blocker: none.
- Exact next action: in a future cycle, select one bounded Phase 1D API-infrastructure
  queue item; the next candidate is consistent safe error envelopes before business
  endpoints (API-013/014, TEST-088, SEC-039).
