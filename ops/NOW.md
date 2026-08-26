# V1-036 Lease, signer, occupancy, and move-in API/UI — verified unpublished

- Candidate: `V1-036` — Lease, signer, occupancy, and move-in API/UI.
- Authorization: existing durable V1 roadmap authorization plus direct Owner takeover;
  no renewed routine authorization is required.
- Baseline: synchronized `implementation/foundation` at V1-035 closure
  reconciliation `3d172bcb4a220dfbce75defc3a329389a5201daf`.
- Preflight: PASS; no repository worker, mutation process, lock, or restoration
  continuation overlaps this direct cycle.
- Scheduler: exact Property Rental supervisor remains disabled and not running.
- Scope: implement `API-035` through `API-038`, `UI-036` through `UI-045`,
  and `TEST-030` through `TEST-035` as the accessible staff Lease, signer,
  Occupancy, and move-in workflow.
- Authorities: exact `API-035` through `API-038`, `UI-036` through `UI-045`,
  and `TEST-030` through `TEST-035`.
- Dependencies: published V1-033 Lease persistence, V1-034 lifecycle services,
  and V1-035 atomic move-in orchestration.
- Excluded: billing, move-out, V1-037 work, canonical changes, and
  Hermes-wrapper changes.
- Canonical specifications: read-only.
- Token ceiling and automation protections: unchanged.
- Implementation: bounded Lease draft, signer, Service/pet/deposit evidence,
  signing, termination, Occupancy, source-linked history, and move-in API/UI
  workflows are complete with authorization, Property scope, CSRF,
  optimistic-concurrency, idempotency, privacy, and accessibility controls.
- Review corrections: canonical `/api/v1` routing, exact Reservation-Unit
  Security Deposit linkage, resolvable timeline sources, recoverable failed
  draft input, capability/lifecycle-sensitive renewal, omitted-field-safe PATCH,
  transactionally bounded Signers, cursor-paginated timeline anchors, and
  truthful evidence.
- Verification: PASS; focused backend `54/54`, focused frontend `12/12`, real
  disposable PostgreSQL `272/272`, and corrected complete deterministic
  verification profile `15/15` (`614` backend, `196` frontend, and `185`
  automation tests).
- Status: verified and unpublished; fresh corrected exact-diff review is pending.
- Blockers: none.
- Exact next action: obtain a fresh read-only independent review of the exact
  corrected final diff, then publish and require exact-SHA GitHub Actions before
  the separate V1-036 closure commit.

<!-- AUTOMATION_STATUS_BEGIN -->

- Automation publication state: V1-035 is published and exact-SHA CI-green;
  V1-036 is verified unpublished under direct takeover and V1-037 remains held.
- Automation exact next action: keep the Property Rental supervisor disabled and
  review and publish only V1-036 without activating V1-037 or inspecting
  Hermes-wrapper drift.

<!-- AUTOMATION_STATUS_END -->
