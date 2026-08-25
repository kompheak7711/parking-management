# V1-032 Reservation API, UI, expiration worker, and end-to-end tests — published

- Candidate: `V1-032` — Reservation API, UI, expiration worker, and end-to-end tests.
- Authorization: existing durable V1 roadmap authorization plus direct Owner takeover;
  no renewed routine authorization was required.
- Baseline: clean, synchronized `implementation/foundation` at V1-031 closure
  `ccdeb953cdcbc53bc2104dc49be2f6e61b05f0b5`.
- Scheduler: exact Property Rental supervisor remained disabled throughout direct work.
- Scope: authenticated Reservation create/read/extend/cancel workflows, accessible
  staff UI, and singleton-safe retry-safe automatic expiration.
- Authorities: `API-032-034`, `UI-031` through `UI-035`, `TEST-024-029`, and
  `TEST-096-099`.
- Dependencies: published V1-029 persistence, V1-030 lifecycle services, and
  V1-031 cancellation/deposit outcomes.
- Excluded: Lease implementation, V1-033 work, canonical changes, Hermes-wrapper
  changes, and every later tranche.
- Canonical specifications: read-only.
- Token ceiling and automation protections: unchanged.
- Verification: complete profile PASS (15/15), including 241 real PostgreSQL tests,
  601 backend tests, 184 frontend tests, and 182 automation-routing tests.
- End-to-end gate: authenticated HTTP create, extend, and cancel reach the real API,
  service, transaction, and PostgreSQL layers with security, replay, concurrency,
  history, financial continuity, response-contract, and rollback assertions.
- Independent review: PASS with zero material findings; reviewer made no edits.
- Publication: implementation commit `8209e119db0f4d7e58f596df56524efebdab87a0`
  is pushed and exact-SHA GitHub Actions run `32895759675` passed all four jobs.
- Status: complete, verified, review-clean, published, and CI-green.
- Blockers: none.
- Exact next action: keep V1-033 at `approved_ready` and the Property Rental
  supervisor disabled; proceed only under the existing sequential takeover boundary.

<!-- AUTOMATION_STATUS_BEGIN -->

- Automation publication state: V1-032 is published and exact-SHA CI-green.
- Automation exact next action: Keep V1-033 and the Property Rental supervisor held.

<!-- AUTOMATION_STATUS_END -->
