# V1-033 Lease, signer, occupant, and occupancy persistence — verified, awaiting publication

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
  reviewed fingerprint `21f2408af2fd650584e3a464090f28db439fa1809099a3164875b2a60d0317a2`.
- Publication: pending separate implementation commit, exact-SHA CI, and closure commit.
- Status: verified under the existing sequential direct-takeover authorization.
- Blockers: none.
- Exact next action: publish the reviewed V1-033 implementation and require successful
  exact-SHA GitHub Actions while V1-034 remains held.

<!-- AUTOMATION_STATUS_BEGIN -->

- Automation publication state: V1-032 is published and exact-SHA CI-green; V1-033
  is verified and awaiting its separate publication gates.
- Automation exact next action: keep the Property Rental supervisor disabled and
  V1-034 held until V1-033 passes every publication gate.

<!-- AUTOMATION_STATUS_END -->
