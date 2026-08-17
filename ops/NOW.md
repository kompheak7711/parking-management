# Phase 2D deployment scaffolding — verified and published

- Outcome: the bounded `SEC-045/047/049/050` deployment-identity and protected-source
  scaffolding plus its native-Linux PostgreSQL repair are verified and published.
- Root cause: `scripts/database-test.sh` generated all six Compose secret sources as `0600`.
  File-backed Compose secrets are bind mounts without uid/gid/mode remapping on native Linux.
  The official PostgreSQL image reads the standard admin source before privilege drop, but runs
  custom init scripts as PostgreSQL uid 999; the other five sources were therefore unreadable.
  Docker Desktop ownership mapping made the same files readable locally and masked the defect.
- Repair: each source is now `0444` inside a private `0700` temporary directory. Compose still
  mounts the sources read-only, cleanup removes the directory, and no role or grant changed.
- Diagnostics: failed startup now emits container logs before cleanup through an in-memory
  redactor that replaces all six generated passwords; no secret value enters command arguments.
- Regression evidence: the native-Linux permission harness failed with exit 17 before the mode
  correction and passed afterward. The failure-path harness initially observed only `up/down`;
  it now verifies `up/logs/down`, a preserved exit status, and no emitted 64-hex password.
- Verification: `make database-test` passed 38 real-PostgreSQL tests. `make test` passed 69
  backend tests with 38 expected dedicated-gate skips and 3 frontend tests. Format, format-check,
  lint, typecheck, build, automation, TEST-118, deployment-config, Compose render, client-bundle,
  secret/argument scan, JSON, diff-check, migration-head, and canonical-integrity gates passed.
- Dependency review: locked backend runtime/development `pip-audit` and frontend `npm audit`
  found no known vulnerabilities. `shellcheck` was unavailable; POSIX `sh -n` passed.
- Scope: five distinct non-superuser roles and six protected-file mounts remain intact.
  `docs/001-010`, dependencies, migrations, production values, and remote configuration are
  unchanged. No production credential, deployment, remote-access, or destructive operation occurred.
- Publication: a concurrent process committed and pushed the five reviewed paths as `3306e94`
  during the required Hermes review. Local HEAD, upstream, and remote branch all equal that SHA.
- Independent review: all local, PostgreSQL, security, traceability, dependency, canonical,
  Compose, shell, JSON, secret-signature, quality, build, and automation gates passed on `3306e94`.
- Remote verification: GitHub Actions workflow `CI`, run `32042322805`, completed with
  conclusion `success` for exact commit `3306e94af555845873565a864fb71657fbaf8390`.
- Blockers: none.
- Exact next candidate: bounded Phase 2E password-hashing and verification service against
  existing `DB-AUTH-002`, excluding login/API/UI, sessions, MFA, recovery, bootstrap,
  production secrets, deployment, remote access, and canonical-document changes.
- Exact next action: dispatch the approved Phase 2E candidate immediately.
