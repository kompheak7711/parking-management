# V1-036 Lease, signer, occupancy, and move-in API/UI — complete

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
- Independent review: PASS; a fresh read-only review covered the exact final
  21-path diff, found zero material issues, and made no edits.
- Implementation publication: commit
  `b8013879399cd3c7c598ee1f85974e2f042b794a`; exact-SHA GitHub Actions run
  `32952625712` passed all four jobs.
- Closure: commit `9653fd2cb4afa06b250e4b7a7f5ad1e7de4265ef`;
  exact-SHA GitHub Actions run `32953192588` passed all four jobs.
- Status: complete, published, independently reviewed, and closure-valid under
  the existing sequential authorization.
- Blockers: none.
- Exact next action: keep V1-037 held at `approved_ready` and keep the Property
  Rental supervisor disabled; do not activate the successor automatically.

<!-- AUTOMATION_STATUS_BEGIN -->

- Automation publication state: V1-036 implementation and closure are published
  and exact-SHA CI-green; V1-037 remains the held approved successor.
- Automation exact next action: keep the Property Rental supervisor disabled and
  do not activate V1-037 or inspect Hermes-wrapper drift.

<!-- AUTOMATION_STATUS_END -->
