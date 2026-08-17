# Phase 2N Recovery-Code Consumption Persistence Orchestration Foundation — published

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
  tests, builds/import, deployment validation, dependency audits, traceability, scope, secret, and
  canonical-integrity gates passed. Backend passed 179 with 52 expected dedicated-gate skips;
  frontend passed 3; `make database-test` passed 52 on real PostgreSQL. Independent pre-commit
  review and GitHub Actions run `32074820742` passed all four jobs.
- Publication: the exact eight-path tranche is published at `eee69be`; local, upstream, and remote
  SHAs matched and the committed file list matched the reviewed scope.
- Blockers: none. Owner action: none.
- Exact next candidate: Phase 2O Recovery-Code Regeneration Persistence Orchestration Foundation,
  approved-ready under the durable remaining-v1 authorization and existing recovery authorities.
  Bound it to protected invalidation of the prior set, atomic creation of one replacement set with
  independently salted verifier material, one-time caller-owned presentation, immutable secret-free
  evidence, and focused deterministic/real-PostgreSQL tests. Exclude public API/UI, account or MFA
  mutation, session revocation, rate limiting, enumeration handling, administrative/emergency
  recovery, bootstrap, production operations, canonical changes, and policy invention.
- Exact next action: dispatch only this approved-ready Phase 2O candidate through model-free
  preflight.
