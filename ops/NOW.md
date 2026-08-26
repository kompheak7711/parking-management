# V1-035 Move-in, occupancy, and reservation-to-lease orchestration — verified unpublished

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
- Verification: PASS; focused real PostgreSQL suite `269/269` and complete
  deterministic verification profile `15/15`.
- Status: implementation complete and verified; fresh exact-diff review and
  publication remain pending under the existing authorization.
- Blockers: none.
- Exact next action: obtain a fresh read-only review of the exact verified V1-035
  diff, then create and push its implementation commit and require successful
  exact-SHA GitHub Actions.

<!-- AUTOMATION_STATUS_BEGIN -->

- Automation publication state: V1-034 is published and closure-valid; V1-035 is
  verified unpublished through direct Codex takeover; V1-036 and later tranches
  remain held.
- Automation exact next action: keep the Property Rental supervisor disabled,
  independently review and publish only V1-035, and do not inspect or repair
  Hermes-wrapper drift.

<!-- AUTOMATION_STATUS_END -->
