# Local-account persistence foundation — publication ready

- Outcome: the bounded `DB-AUTH-001` tranche is complete in the working tree and remains
  intentionally uncommitted and unpublished.
- Implemented: one forward-only PostgreSQL migration for UUID actor identity, transactional
  normalized-username uniqueness, display/audit identity, explicit active/disabled
  lifecycle, required/optional MFA-policy class separate from authority, managed
  timestamps, creation provenance, immutable actor identity, and read-only runtime access.
- Scope held: no password verifier, login/API/UI, MFA verifier/recovery state, session,
  recovery/bootstrap, dependency, credential, remote/production, or docs/001-010 change.
- Last verified result: independent review found no in-scope implementation defect;
  `make database-test` passed 19 real-PostgreSQL tests and `make automation-test` passed.
  Full test, lint, format-check, typecheck, and build gates also passed.
- Blockers: none. Commit and push were expressly excluded from this Hermes attempt.
- Exact next candidate: one forward-only PostgreSQL migration for bounded `DB-AUTH-002`
  salted adaptive password-verifier encoding and metadata storage, with focused
  real-PostgreSQL constraints, least privilege, forward-migration, and traceability tests.
- Next risk/approval: high; publication and the bounded next candidate remain covered by
  `ops/QUEUE.md` durable authorization, with no unresolved policy or production operation.
- Exact next action: commit and push only the publication-ready DB-AUTH-001 changed paths,
  verify the published commit and remote branch, then dispatch bounded DB-AUTH-002 in a
  separate attempt.
