# V1-015 Login, MFA, Logout, Reauthentication, and Session API — verified, unpublished

- Implemented: local login, TOTP enrollment/challenge, recovery-code challenge, authenticated
  session inspection, logout, and current-session reauthentication over an injected atomic flow.
- Browser protection: exact configured HTTPS origin, constant-time double-submit CSRF checks,
  Secure host-only cookies, HttpOnly session/preauthentication material, strict cookie-state
  transitions, no-store responses, generic rejection/rate-limit responses, and no SMS method.
- Runtime boundary: the transport fails closed with canonical 503 until the separately approved
  persistent authentication-flow adapter is configured; external identity providers remain excluded.
- Traceability: API-008 through API-010, API-096 through API-097, SEC-012 through SEC-018,
  TEST-108, TEST-128, and TEST-131 through TEST-132 are covered by 19 API/security tests and one
  bounded traceability assertion.
- Verification: focused authentication/traceability passed 36; full backend passed 253 with 83
  expected environment skips; frontend passed 3; real PostgreSQL passed 83; lint, formatting,
  strict typing, backend/frontend builds, deployment configuration, dependency audit, roadmap,
  automation routing, JSON validation, and diff checks passed.
- Independent security re-review found no blocker within the approved transport/API scope.
- Roadmap: V1-001 through V1-014 are published; V1-015 is complete but uncommitted/unpublished;
  V1-016 remains the next dependency-ready approved candidate.
- Blockers: none. Owner action: none.
- Exact next action: independently publish the verified V1-015 tranche under standing authorization,
  then activate V1-016 recovery-code, administrative, and emergency recovery orchestration.
