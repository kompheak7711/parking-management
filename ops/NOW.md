# V1-017 Protected Initial Owner CLI Bootstrap — published and CI-verified

- The reviewed 28-path V1-017 implementation is published on `implementation/foundation` as
  `d2be562bb54d0111dd2448e94fd33065e71fef22`.
- The CLI-only bootstrap implements the approved password, TOTP, one-time recovery-code,
  ceremony-deadline, atomic PostgreSQL, least-privilege identity, permanent closure, and
  secret-free audit rules. No bootstrap or Owner-reset HTTP operation exists.
- The first independent review returned FAIL on effective `PUBLIC` target authority,
  fresh-cluster cross-database access, boundary-space blocklist parsing, single-use and exact
  HTTP-inventory proof, and stale compact evidence. All five findings are corrected in scope.
- The second fresh review confirmed those corrections and found one remaining evidence defect:
  the negative HTTP inventory compared exact paths but not the complete runtime method surface.
  It now compares every runtime path-and-method pair and all eight OpenAPI HTTP verbs, including
  `HEAD`, `OPTIONS`, and `TRACE`; focused and full backend verification pass after the correction.
- Current PostgreSQL evidence passes all 105 tests with no skips, including clean and unsafe
  large-object states, `PUBLIC` table authority rejection before mutation, fresh-cluster
  cross-database confinement, real production service plus pseudo-TTY rollback, and production
  recovery generation followed by one successful consumption and rejected reuse.
- Current executable evidence passes: focused V1-017 65; full backend 313 with 105 expected
  database-environment skips whose complete set passed separately; frontend 3; explicit health
  20. Backend/frontend formatting, lint, strict typing, builds, runtime/development dependency
  audits, deterministic automation/roadmap, deployment configuration, traceability, JSON,
  28-path scope, secret-pattern, canonical integrity, and `git diff --check` pass.
- A third fresh read-only Codex review returned explicit PASS after independently checking the
  complete 28-path diff, exact runtime/OpenAPI method inventory, large-object fail-closed matrix,
  traceability, compact evidence, and `git diff --check`; no concrete defect remains.
- GitHub Actions run `32382252402` passed all four jobs for the implementation commit: backend
  quality/tests/build/traceability, frontend quality/tests/build, PostgreSQL migration, and
  dependency security.
- Status is `published`. Blockers and Owner action: none. This focused metadata reconciliation
  records the completed publication; stop without selecting or beginning V1-018. The separate
  continuation automation remains untouched, and the property-rental supervisor remains disabled.
