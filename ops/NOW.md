# PostgreSQL native-Linux secret mount repair — verified for publication

- Objective: repair only the repeated PostgreSQL startup failure in GitHub Actions run
  `32040242139` for the existing `SEC-045/047/049/050` scaffolding; do not commit or push.
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
  unchanged. No credential, deployment, destructive operation, commit, or push occurred.
- Concurrent work: a separate process published unrelated automatic-repair changes as `a29e8d6`
  after the clean pre-write gate. This repair remained unstaged and uncommitted throughout.
- Independent review: all local, PostgreSQL, security, traceability, dependency, canonical,
  Compose, shell, JSON, secret-signature, quality, and build gates passed on base `a29e8d6`.
- Exact next action: stage only the five reviewed repair paths, check the cached scope and secret
  signatures, commit, push normally, and require every GitHub Actions job to pass.
