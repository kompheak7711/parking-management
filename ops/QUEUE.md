# Foundation queue

1. Phase 1F GitHub Actions CI foundation — completed and published.
2. Automation visibility and watchdog guardrails — completed and published.
3. Phase 2A provider-neutral authenticated actor boundary — completed and published.
4. Phase 2B provider-neutral capability authorization boundary — completed and published
   as `a931f0a`; local gates and GitHub Actions run `32002986112` passed.
5. Phase 2C Property-local business-date foundation — completed and published.
6. Phase 2C single-Property identity scope primitive — completed and published.
7. Authentication/account/session plan reconciliation to authoritative docs 003-010 and
   `DL-055` through `DL-059` — completed as a bounded read-only tranche.
8. Phase 2D local human-account persistence foundation — completed and independently
   verified locally; intentionally uncommitted and unpublished.
9. Phase 2D password-credential persistence foundation — exact next candidate: add one
   forward-only PostgreSQL migration for bounded `DB-AUTH-002` salted adaptive verifier
   encoding and metadata storage with focused real-PostgreSQL and traceability tests.
   Exclude hashing-library selection or use, login/API/UI, rate limiting, sessions,
   MFA/recovery/bootstrap, credentials, remote access, and canonical-doc changes. High
   risk; approved and ready under the durable authorization below after the current
   publication-ready uncommitted tranche is published.
10. Design backup/restore/human administration database identities and production
   secret provisioning only in a separately authorized deployment tranche
   (SEC-045/047/049/050).

Remaining v1 application tranches are authorized when bounded by canonical documents
001-010 and all publication gates; unresolved policy and protected production work still
require owner review.
