# V1-014 Persistent Browser-Session and Revocation Store — verified, unpublished

- Objective: recover the bounded automation lifecycle and complete the approved V1-014
  persistence foundation without canonical changes, API/UI, cookie transport, remote access,
  production operations, or secrets.
- Automation root cause: structured successor selection retained the published predecessor's
  top-level lifecycle and repair object; preflight trusted unmatched repair metadata and dispatcher
  attempt identity omitted an explicit roadmap tranche ID.
- Automation repair: successor selection now activates the complete successor lifecycle and
  initializes repair metadata tagged with its tranche ID. Preflight ignores unmatched repair
  metadata; dispatcher attempt/exhaustion identity includes the explicit dispatched tranche ID.
- Regression: deterministically recreates exhausted V1-013 repair state, selects/activates V1-014,
  seeds the legacy exhausted fingerprint, and proves V1-014 still receives attempts 1 and 2.
- Persistence: forward-only migration `20260819_07` stores unique SHA-256 token verifiers, actor,
  fixed 30-minute idle and 24-hour absolute boundaries, creation provenance, and bounded revocation
  evidence. It stores no plaintext token, cookie, role, or capability authority.
- Integrity: identity/verifier/creation state and revoked rows are immutable; activity cannot revive
  an expired session or extend absolute expiry; delete/truncate are rejected; runtime privileges are
  column-bounded to verifier lookup, creation, activity, and revocation transitions.
- Traceability: DB-AUTH-004, API-097, TEST-131, SEC-015, SEC-017, and DL-057 are implemented here.
  SEC-016 cookie/CSRF transport and SEC-018 reauthentication were reviewed and remain correctly
  excluded for V1-015 API/UI scope.
- Verification: backend passed 233 with 83 expected database skips; frontend passed 3; isolated real
  PostgreSQL passed 83; lint, formatting, strict type checks, backend/frontend builds, traceability,
  roadmap, deployment configuration, and automation routing passed.
- Independent review found one invalid boundary: creation could persist activity at absolute expiry.
  A test-first repair reproduced the failure, added a strict pre-expiry invariant, and passed focused
  and full PostgreSQL verification. Independent re-review found no remaining blocking defects.
- Blockers: none. Owner action: none.
- Exact next action: publish the verified V1-014 tranche under standing authorization, then activate
  V1-015 Login, MFA, logout, reauthentication, and session API.
