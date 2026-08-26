# V1-035 Move-in, occupancy, and reservation-to-lease orchestration — implementation published; closure pending

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
- Status: implementation published; the V1-035 closure commit and its own
  exact-SHA CI result remain pending under the existing authorization.
- Blockers: none.
- Exact next action: create and push only the V1-035 closure commit, require
  successful exact-SHA GitHub Actions, then reconcile closure-valid compact
  state before activating V1-036.

<!-- AUTOMATION_STATUS_BEGIN -->

- Automation publication state: V1-034 is published and closure-valid; V1-035's
  implementation is published and CI-green but its closure remains pending;
  V1-036 and later tranches remain held.
- Automation exact next action: keep the Property Rental supervisor disabled,
  publish and validate only the V1-035 closure, and do not inspect or repair
  Hermes-wrapper drift.

<!-- AUTOMATION_STATUS_END -->
