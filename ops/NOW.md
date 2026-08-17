# Phase 2N Recovery-Code Consumption Persistence Orchestration Foundation — complete_uncommitted

- Outcome: the bounded provider-neutral consumption service composes the published lifecycle and
  Argon2id-compatible verifier boundary with exact-set PostgreSQL row locking and one guarded
  single-row lifecycle update. Successful consumption atomically stores immutable secret-free
  actor, time, correlation, provenance, reason, and previous/resulting-state evidence.
- Fail-closed behavior: missing, unmatched, ambiguous, consumed, invalidated, malformed, and
  verifier-failure paths remain generic rejections. Persistence failures return one generic failure;
  candidate and verifier material are excluded from results, exceptions, audit evidence, and SQL
  provenance.
- Scope: public API/UI, account/MFA mutation, session revocation, rate limiting, enumeration
  handling, regeneration, administrative/emergency recovery, bootstrap, production operations,
  credentials, remote access, canonical edits, architecture changes, and policy invention remain
  excluded.
- Verification: focused recovery/traceability checks passed 62; full format, lint, strict typecheck,
  tests, builds/import passed; backend passed 179 with 52 expected dedicated-gate skips; frontend
  passed 3; `make database-test` passed 52 on real PostgreSQL; `make automation-test` passed.
  Independent pre-commit review passed with no blockers.
- Blockers: none. Owner action: none.
- Exact next candidate: publish this verified eight-path Phase 2N tranche only.
- Exact next action: stage exactly `backend/src/property_rental/recovery_code_consumption.py`,
  `backend/src/property_rental/recovery_code_lifecycle.py`, `backend/tests/test_migrations.py`,
  `backend/tests/test_recovery_code_consumption.py`, `backend/tests/test_traceability.py`,
  `ops/NOW.md`, `ops/STATE.json`, and `ops/traceability.json`; verify the staged set; commit with
  subject `feat: add recovery code consumption foundation`; push `implementation/foundation`;
  verify local/upstream/remote SHA equality and GitHub Actions; then reconcile publication state.
