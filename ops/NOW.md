# Phase 1C PostgreSQL runtime and migrations foundation

- Objective: deliver only the authorized bounded PostgreSQL development/runtime and
  additive migration foundation.
- Current task: verified complete; uncommitted on `implementation/foundation` at
  `3cd2d7cce688a6edb562fe38c14320ad6060d385`.
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
- Exact next action: review and publish only this Phase 1C tranche when explicitly
  authorized; then separately approve the minimal readiness tranche using the real
  runtime database dependency.
