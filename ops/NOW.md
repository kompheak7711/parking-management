# Deployment identities and secret-source scaffolding — verified for publication

- Objective: implement only the owner-authorized `SEC-045/047/049/050` design and local
  configuration-scaffolding tranche; create no production secret and do not commit or push.
- Outcome: five distinct managed database identities now have machine-readable contracts and
  fresh-local-Compose scaffolding: runtime, migration, read-only backup, connect-only restore,
  and monitoring-only exceptional human administration.
- Secret separation: development, test, staging, and production profiles contain protected-file
  references only. Database identities, ordinary application secret input, and backup encryption
  input use distinct environment-bound sources.
- Fail-closed gate: `make deployment-config-check` validates committed profiles; deployment-mode
  validation rejects missing, direct, empty, or recognized placeholder protected sources without
  printing contents. Production remains intentionally unresolved and unconfigured.
- Administration boundary: human administration has no standing table DML or financial-history
  edit path. Restore has no standing data access and requires a later separately authorized
  controlled runbook/elevation procedure.
- Secret handling: Compose mounts password files; the PostgreSQL initializer uses `psql \getenv`
  instead of secret-bearing command arguments. Test credentials are disposable, private, silent,
  and removed with the isolated test volume.
- Verification: `make database-test` passed 38 real-PostgreSQL tests. Full `make test` passed
  67 backend tests with 38 dedicated-gate skips and 3 frontend tests. Lint, format-check,
  typecheck, build, automation, TEST-118, deployment-config, Compose-render, client-bundle,
  changed-file secret/argument, JSON, diff-check, migration-head, and canonical-integrity gates
  passed.
- Dependency review: locked backend runtime/development `pip-audit` and frontend `npm audit`
  reported no known vulnerabilities. `shellcheck` was unavailable; POSIX `sh -n` passed.
- Canonical scope: `docs/001-010` are unchanged. No package, schema migration, production value,
  remote/secret-store operation, business policy, destructive operation, commit, or push occurred.
- Supervisor review: added fail-closed rejection and traceability for protected-source path
  traversal; all affected gates passed afterward.
- Blockers: none for publication of this bounded working tree. Real production provisioning,
  restore authority/runbook, backup execution/encryption, and deployment remain explicitly deferred.
- Exact next action: stage only reviewed paths, recheck the cached diff and secret signatures,
  commit, push normally, and verify GitHub Actions plus local/upstream/remote identity.
