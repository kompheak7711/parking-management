# V1-038 Deposit receipt, qualification, disposition API/UI — active

- Candidate: `V1-038` — Deposit receipt, qualification, disposition API/UI.
- Authorization: existing durable V1 roadmap authorization plus direct Owner takeover;
  no renewed routine authorization is required.
- Baseline: clean synchronized `implementation/foundation` at V1-037 reconciliation
  commit `11efdf2036e308d62735362ace275739658e049a`.
- Preflight: PASS; no repository worker, mutation process, lock, or restoration
  continuation overlapped this direct cycle.
- Scheduler: the Property Rental supervisor remains disabled and not running.
- Scope: authorized Deposit resource, receipt, qualification, disposition, correction,
  and active-Lease Pet Deposit Refund qualification API/UI with permanent source history.
- Authorities: `API-039` through `API-042`, `API-094`, `UI-030`, `UI-033`,
  `UI-035`, `UI-043`, `UI-044`, `UI-071`, `UI-073`, `UI-074`, `UI-076`,
  `UI-107`, `TEST-036` through `TEST-039`, and `TEST-126`.
- Dependency: published V1-037 Deposit persistence/domain services.
- Excluded: ordinary active-Lease Security Deposit Refund, Final Settlement
  implementation, actual Refund execution, V1-039, canonical changes, and
  Hermes-wrapper changes.
- Canonical specifications: read-only.
- Scope correction: Owner-approved. New Payment-backed receipt creation is deferred
  to V1-048/V1-052, and Final Settlement disposition is deferred to V1-056. Existing
  receipt history remains readable and reversible; no provisional Payment is invented.
- Implementation: complete for bounded Deposit resources, existing receipt/source
  history and reversals, supported disposition correction, approved conditional Pet
  Deposit creation, and split pet-departure/refund-review qualification.
- Verification: PASS; focused API/UI checks, disposable PostgreSQL `300/300`, and
  complete deterministic verification `15/15` (`629` backend with `289` expected
  environment skips, `213` frontend, and `185` automation-routing tests); evidence:
  `/private/tmp/property-rental-v1-038-final-verification-6.json`.
- Review: PASS; fresh external Codex read-only review of the exact final diff found no
  material issues and made no edits; session
  `01a0406f-c4e8-7e82-9419-c77d93a4bba5`; evidence:
  `/private/tmp/property-rental-v1-038-final-independent-review-7.txt`.
- Publication: pending.
- Status: verified unpublished implementation awaiting publication and exact-SHA CI.
- V1-039: held at `approved_ready`; no activation or implementation is permitted.
- Blockers: none.
- Exact next action: publish the independently reviewed V1-038 implementation, require
  successful exact-SHA CI, then reconcile closure while keeping V1-039 held.

<!-- AUTOMATION_STATUS_BEGIN -->

- Automation publication state: V1-038 passes complete 15/15 verification and fresh
  exact-final-diff independent review; V1-039 remains the held approved successor.
- Automation exact next action: keep the supervisor disabled and V1-039 held until
  corrected V1-038 publication and exact-SHA CI succeed.

<!-- AUTOMATION_STATUS_END -->
