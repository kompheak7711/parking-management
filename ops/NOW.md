# V1-030 Reservation lifecycle and availability services — published

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
- Verification: complete deterministic profile passed 15/15, including 587 backend
  tests with 215 expected environment skips, 178 frontend tests, 221 real disposable
  PostgreSQL tests, and 182 automation-routing tests.
- Independent review: PASS after two material database-boundary findings were
  corrected and regression-tested. Reviewed implementation fingerprint:
  `280868704067d4b3fa43003aed801559ac711c2f719f7d6e723274fbc3468035`.
- Publication: implementation commit `1f41c41a9426f88ff03ca957a08d82b50cd13fec`
  is pushed and exact-SHA GitHub Actions run `32864460444` passed all four jobs.
- Status: complete, verified, review-clean, published, and CI-green.
- Blockers: none.
- Exact next action: keep V1-031 at `approved_ready` and the Property Rental
  supervisor disabled; await explicit Owner direction before starting V1-031 or
  restoring autonomous execution.

<!-- AUTOMATION_STATUS_BEGIN -->

- Automation publication state: V1-030 is published and exact-SHA CI-green.
- Automation exact next action: Keep V1-031 and the Property Rental supervisor held.

<!-- AUTOMATION_STATUS_END -->
