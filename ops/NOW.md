# V1-035 Move-in, occupancy, and reservation-to-lease orchestration — complete

- Candidate: `V1-035` — Move-in, occupancy, and reservation-to-lease orchestration.
- Authorization: existing durable V1 roadmap authorization plus direct Owner takeover;
  no renewed routine authorization is required.
- Baseline: clean, synchronized `implementation/foundation` at V1-034 closure
  reconciliation `de5a2823bb10d2905bc876bed1bc694a478a82e9`; exact-SHA GitHub
  Actions run `32930511076` passed all four jobs.
- Preflight: PASS; no repository worker, mutation process, lock, or restoration
  continuation overlaps this direct cycle.
- Scheduler: exact Property Rental supervisor remains disabled and not running.
- Scope: enforce move-in prerequisites, Reservation-deposit continuity, Unit
  occupancy, and reconstructable Reservation-to-Lease source links and history.
- Authorities: `BR-LEASE-015`, `BR-LEASE-016`, `BR-OCC-*`, `TEST-028`, and
  `TEST-033` through `TEST-035`.
- Dependencies: published V1-032 Reservation workflows and published V1-034 Lease
  lifecycle services.
- Excluded: move-out, V1-036 API/UI, V1-037 work, canonical changes, and
  Hermes-wrapper changes.
- Canonical specifications: read-only.
- Token ceiling and automation protections: unchanged.
- Verification: PASS; focused real PostgreSQL suite `269/269`, complete
  deterministic verification profile `15/15`, and fresh exact-diff independent
  review with zero findings.
- Implementation publication: commit
  `bf77d714a932b83bfe1bbbf54b5ded003a1291de`; exact-SHA GitHub Actions run
  `32933925926` passed all four jobs.
- Closure: commit `45b3a7af4ab7ff83996bcba3dc441a4d7592bbdd`;
  exact-SHA GitHub Actions run `32934543309` passed all four jobs.
- Status: complete, published, independently reviewed, and closure-valid under
  the existing sequential authorization.
- Blockers: none.
- Exact next action: complete the authorized V1-036 predecessor,
  synchronization, supervisor-disabled, and no-overlap preflight before editing.

<!-- AUTOMATION_STATUS_BEGIN -->

- Automation publication state: V1-035 implementation and closure are published
  and exact-SHA CI-green; V1-036 is the next approved successor and V1-037
  remains held.
- Automation exact next action: keep the Property Rental supervisor disabled and
  preflight V1-036 without activating V1-037 or inspecting Hermes-wrapper drift.

<!-- AUTOMATION_STATUS_END -->
