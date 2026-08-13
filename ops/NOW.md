# Phase 1C publication checkpoint

- Objective: deliver only the authorized bounded PostgreSQL development/runtime and
  additive migration foundation.
- Current task: complete and published on `implementation/foundation` as
  `2c71a29a0900436837f3c535a430f3a092a619b8`; no implementation cycle is active.
- Runtime: PostgreSQL 17.6 is bound to loopback. The real-database gate creates one
  disposable Compose project, generates distinct credentials internally, discovers
  its assigned host port, and removes its container and volume on exit.
- Privileges: `prm_migrator` owns schema changes; `prm_runtime` does not own or alter
  the schema and currently receives only `USAGE` plus baseline `SELECT`.
- Migration contract: Alembic has one reviewed head, `20260813_01`; upgrades are
  transactional and forward-only. The baseline adds only `app.schema_baseline` and
  invents no business schema or policy.
- Tests: 18 passed, including 5 real PostgreSQL tests for empty upgrade, identity/DDL
  separation, injected transactional failure/history preservation, additive check
  behavior, and bounded nonblocking current-head upgrade.
- Quality: Ruff format/lint, strict mypy, package build/import, Compose config/health,
  container build/import, lock check, runtime/dev dependency audits, secret-literal
  scan, canonical-doc integrity, and diff checks passed.
- Coverage: DEPLOY-001/032/033 and TEST-010/100/102 are satisfied for this baseline.
  DEPLOY-034, TEST-101/103/104, and SEC-045–050 are accurately partial until
  business schema, financial data, backup/restore identities, and production secret
  posture exist; details are in `ops/STATE.json`.
- Security recovery: four stale disposable database environments were deleted, all
  local development database credentials were rotated, no credential entered Git,
  and the repaired gate completed without printing or persisting credentials.
- Blocker: none.
- Exact next action: prepare the bounded Phase 1D API infrastructure/readiness
  tranche against the real runtime database dependency; expose no diagnostics on
  the unauthenticated readiness response.
