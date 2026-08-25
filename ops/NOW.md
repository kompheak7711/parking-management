# V1-030 Reservation lifecycle and availability services — verified, unpublished

- Candidate: `V1-030` — Reservation lifecycle and availability services.
- Authorization: existing durable V1 roadmap authorization plus direct Owner takeover;
  no renewed routine authorization is required.
- Baseline: clean, synchronized `implementation/foundation` at V1-029 closure
  `f96e55c3ffb61263ec4b8e8d5e5a7f104af4546d`.
- Scheduler: exact Property Rental supervisor remains disabled throughout direct work.
- Overlap: no repository worker or automation process overlaps this cycle.
- Scope: create, extend, expire, and cancel Reservations with transactional Unit
  availability, legal transitions, optimistic concurrency, and idempotent retries.
- Authorities: `BR-RES-003` through `BR-RES-022`, `PR-RES-*`, and `TEST-024`
  through `TEST-029` within the explicit V1-030 boundaries.
- Dependency: published V1-029 Reservation and Security Deposit persistence.
- Excluded: move-in completion, V1-031 Security Deposit outcome orchestration,
  canonical changes, unresolved policy invention, and every later tranche.
- Canonical specifications: read-only.
- Token ceiling and automation protections: unchanged.
- Status: implementation complete; the complete deterministic profile passed 15/15,
  including 221 disposable PostgreSQL tests. Fresh exact-diff review passed after
  two material findings were corrected and regression-tested.
- Blockers: none.
- Exact next action: publish V1-030, require successful exact-SHA GitHub Actions,
  then reconcile closure while keeping V1-031 and the supervisor held.

<!-- AUTOMATION_STATUS_BEGIN -->

- Automation publication state: V1-030 is independently reviewed and verified but unpublished.
- Automation exact next action: Keep V1-031 and the supervisor held while V1-030 passes publication and exact-SHA CI gates.

<!-- AUTOMATION_STATUS_END -->
