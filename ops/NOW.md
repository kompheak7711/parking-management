# V1-029 Reservation and reservation-deposit persistence — published

- Candidate: `V1-029` — Reservation and reservation-deposit persistence.
- Authorization: existing durable V1 roadmap authorization plus direct Owner takeover;
  no renewed routine authorization is required.
- Baseline: clean, synchronized `implementation/foundation` at V1-028 closure
  `def558530fd3feb7a2a773c9d84576b3f14b7e51`.
- Scheduler: exact Property Rental supervisor remains disabled throughout direct work.
- Overlap: no repository worker or automation process overlaps this cycle.
- Scope: reservation lifecycle persistence, Unit exclusivity, expiry and extension history,
  and reservation-deposit continuity with reconstructable source linkage.
- Authorities: `BR-RES-*`, `BR-DEP-001` through `BR-DEP-006`, `DB-RES-*`, and
  `TEST-024` through `TEST-029`.
- Dependencies: published V1-023 Property/Unit persistence and V1-025 Unit APIs.
- Excluded: lease creation, canonical changes, unresolved policy invention, and every
  V1-030 action.
- Canonical specifications: read-only.
- Token ceiling and automation protections: unchanged.
- Verification: complete deterministic profile passed 15/15, including 579 backend
  tests with 207 expected environment skips, 178 frontend tests, 212 real disposable
  PostgreSQL tests, and 182 automation-routing tests.
- Independent review: PASS with zero material findings on the final 11-path candidate
  after five material findings were corrected. Reviewed-patch SHA-256:
  `833a292fe30c73efcee4a72670c9f39880670f2cff80a66d23ba98655af2ec49`.
- Publication: implementation commit `232c4da45fed4f2f17019773f83559f089352ce9`
  is pushed and exact-SHA GitHub Actions run `32857259164` passed all four jobs.
- Status: complete, verified, review-clean, published, and CI-green.
- Blockers: none.
- Exact next action: keep V1-030 held and the Property Rental supervisor disabled;
  await explicit Owner direction before restoring autonomous execution or activating
  V1-030.

<!-- AUTOMATION_STATUS_BEGIN -->

- Automation publication state: V1-029 is published and exact-SHA CI-green.
- Automation exact next action: Keep V1-030 and the Property Rental supervisor held.

<!-- AUTOMATION_STATUS_END -->
