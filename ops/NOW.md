# V1-019 authentication and account administration UI — verified for publication

- Candidate: `V1-019` — Authentication and account administration UI.
- Authorization: existing durable V1 authorization; no renewed Owner decision was consumed.
- Implemented: local sign-in, generic enumeration-safe failure, TOTP enrollment and challenge,
  one-time recovery-code issuance/replacement and challenge, session restoration/expiry, logout,
  recent reauthentication, capability-checked account administration, complete paginated
  authorization history, role-bundle configuration, Owner-only administrative recovery, account
  disablement, and applicable-session revocation.
- Safety: no first-Owner web route, no SMS or security-question flow, no role-label authority,
  no persistent display of MFA/recovery material, explicit UTC timestamps, and explicit
  consequence confirmation for protected account/session/recovery commands.
- Automation recovery: the exact stored Hermes `sign_in` result from session
  `39182e96abab6d976b148209cb6a6336` was recovered without another model call after the
  sender/receiver JSON contract mismatch was repaired and published at `347954b`.
- Verification: complete profile PASS 15/15; backend 337 passed with 105 expected local
  environment skips; disposable PostgreSQL 105 passed; frontend 32 passed; automation routing
  127 passed. Local review findings were corrected. The 60,000-token ceiling remains unchanged.
- Scheduler: supervisor `658ffdaf-1ac1-45a6-a842-f5f7d7a226eb` remains disabled while this
  repository-bound direct-takeover task verifies and publishes V1-019.
- V1-020: not started.
- Exact next action: publish the reviewed V1-019 candidate, require successful GitHub Actions,
  reconcile durable state, and restore the existing supervisor without overlap.

<!-- AUTOMATION_STATUS_BEGIN -->
- Automation candidate state: V1-019 locally verified and reviewed; publication pending.
- Automation exact next action: publish, prove CI, reconcile, then restore the supervisor.
<!-- AUTOMATION_STATUS_END -->
