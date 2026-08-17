# Local-account persistence foundation

- Objective: begin production-authentication implementation only through the smallest
  persistence tranche required by the approved local-account policy.
- Planning result: authoritative authentication requirements in docs 003-010 and
  `DL-055` through `DL-059` were reconciled against the existing provider-neutral actor,
  capability, Property/object-scope, migration, and traceability seams.
- Exact next candidate: add one forward-only PostgreSQL migration for `DB-AUTH-001`
  local human-account storage and focused real-PostgreSQL/traceability tests. Enforce an
  immutable UUID actor identity, transactionally unique normalized username,
  display/audit identity, lifecycle state, MFA-policy class, timestamps, provenance, and
  least-privilege runtime access.
- Excluded from that candidate: password verifiers, login/API/UI, MFA verifier or recovery
  state, sessions, recovery/bootstrap operations, credentials, remote access, and any
  canonical-document change.
- Risk class: high (authentication, identity, audit provenance, and database migration).
- Approval status: approved_ready under the durable authorization for bounded remaining
  v1 application tranches in `ops/QUEUE.md`; this read-only cycle did not implement it.
- Exact next action: implement the bounded `DB-AUTH-001` local human-account persistence
  migration and focused real-PostgreSQL/traceability tests, independently verify every
  applicable gate, and commit/push only if all gates pass.
- Blockers: none for the bounded candidate. Hashing/MFA/session/recovery/bootstrap library
  and operational choices remain deferred to separately bounded later tranches.
- Last verified result: planning-only diff is limited to compact ops state; docs 001-010,
  code, tests, credentials, and remote configuration remain unchanged.
- Idle reason: none; the approved implementation candidate is ready for dispatch.
- Owner action: none before dispatch of the already-authorized candidate; fresh approval
  is required for any scope expansion or protected production operation.
