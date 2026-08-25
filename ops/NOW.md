# V1-029 Reservation and reservation-deposit persistence — active

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
- Status: implementation complete; four initial independent-review findings and one
  follow-up traceability finding are corrected; final post-correction 15/15
  verification and fresh exact-diff review passed; publication is pending.
- Blockers: none.
- Exact next action: publish the reviewed V1-029 candidate, require successful
  exact-SHA GitHub Actions, then reconcile closure while keeping V1-030 and the
  supervisor held.

<!-- AUTOMATION_STATUS_BEGIN -->

- Automation publication state: V1-029 is active under direct takeover.
- Automation exact next action: Review and publish V1-029 without activating V1-030 or enabling the supervisor.

<!-- AUTOMATION_STATUS_END -->
