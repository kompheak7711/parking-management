# Password-credential persistence — verified for publication

- Outcome: the bounded `DB-AUTH-002` tranche is complete in the working tree and remains
  intentionally uncommitted and unpublished.
- Implemented: one forward-only PostgreSQL migration after `20260817_02` for an
  account-linked, algorithm-neutral modular password-verifier encoding, matching algorithm
  metadata, positive integral work-factor metadata, credential lifecycle timestamps,
  responsible-actor/audit provenance, immutable identity/creation time, and narrow runtime
  column reads.
- Constraints: plaintext-shaped/mismatched encodings, invalid work-factor metadata, orphaned
  credentials, unattributed/stale-provenance changes, and audit-only mutation are rejected.
- Scope held: no hashing library or generation/checking, login/API/UI, rate limiting,
  sessions, MFA/recovery/bootstrap, dependency, credential, remote/production operation,
  product-policy, or canonical-document change.
- Last verified result: `make database-test` passed 37 real-PostgreSQL tests;
  `make automation-test`, full test, lint, format-check, typecheck, and build gates passed.
  JSON validation, `git diff --check`, and canonical-doc integrity also passed.
- Security review: two independent focused reviews were performed; all concrete migration,
  privilege, audit-attribution, downgrade-regression, and traceability findings were
  addressed. `SEC-043` remains mapped to the existing allowlisted logging-redaction test;
  `SEC-069` is recorded as the completed review process, not overclaimed as a DB test.
- Current blockers: none for DB-AUTH-002 completion or standing-authorized publication.
- Exact next candidate: design backup, restore, human-administration database identities and
  production secret provisioning as a separate `SEC-045/047/049/050` deployment tranche.
- Next risk/approval: high and not approved because it includes
  protected deployment identities and production-secret provisioning.
- Exact next action after publication: owner separately authorizes the high-risk
  `SEC-045/047/049/050` deployment tranche before any implementation begins.
