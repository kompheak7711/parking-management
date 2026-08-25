# V1-033 Lease, signer, occupant, and occupancy persistence — complete

- Candidate: `V1-033` — Lease, signer, occupant, and occupancy persistence.
- Authorization: existing durable V1 roadmap authorization plus direct Owner takeover;
  no renewed routine authorization was required.
- Baseline: clean, synchronized `implementation/foundation` at V1-032 closure
  `58120e839618cea4861372300487cb1a0d07c511`.
- Scheduler: exact Property Rental supervisor remained disabled throughout direct work.
- Scope: durable Lease, signer, occupant, and occupancy persistence with database
  constraints, exclusivity, concurrency protection, and historical preservation.
- Authorities: `BR-LEASE-*`, `BR-OCC-*`, `DB-LEASE-*`, and `TEST-030-035`.
- Dependency: published V1-029 Reservation persistence.
- Excluded: billing, V1-034 service behavior, later tranches, canonical changes,
  and Hermes-wrapper changes.
- Canonical specifications: read-only.
- Token ceiling and automation protections: unchanged.
- Verification: PASS — complete profile 15/15, including 255 disposable PostgreSQL
  tests, 602 backend tests, 184 frontend tests, and 182 automation tests.
- Independent review: PASS — zero final findings across the exact seven-path patch;
  reviewed fingerprint `f885ffd3c890c044ab9dfcb7f635cd2564c8997703a57ce151ab84569c363151`.
- Publication: implementation commit `f3173a2b64204563fb7dec2b7d8ca81e388a6276`;
  exact-SHA GitHub Actions run `32907415482` passed all four jobs.
- Status: complete under the existing sequential direct-takeover authorization.
- Blockers: none.
- Exact next action: require successful exact-SHA CI for this closure, then perform the
  authorized V1-034 predecessor/synchronization/no-overlap preflight before editing.

<!-- AUTOMATION_STATUS_BEGIN -->

- Automation publication state: V1-033 is published and its implementation exact-SHA
  CI is green; V1-034 remains held pending this closure commit's CI gate.
- Automation exact next action: keep the Property Rental supervisor disabled and
  V1-034 held until this separate closure commit is exact-SHA CI-green.

<!-- AUTOMATION_STATUS_END -->
