# V1-039 Invoice, line, adjustment, and billing-run persistence — implementation published; closure pending

- Candidate: `V1-039` — Invoice, line, adjustment, and billing-run persistence.
- Authorization: existing durable V1 roadmap authorization plus direct Owner takeover;
  no renewed routine authorization is required.
- Baseline: clean synchronized `implementation/foundation` at V1-038 reconciliation
  commit `99f1008842390a090261f68a94e7e8717bb26608`.
- Preflight: PASS; no repository worker, mutation process, lock, or restoration
  continuation overlapped this direct cycle.
- Scheduler: the Property Rental supervisor remains disabled and not running.
- Scope: immutable Invoice headers and lines, authorized non-recurring obligation
  sources, append-only Adjustments and reversals, exceptional VOID evidence,
  late-payment decision/charge persistence, durable billing-run identity, and
  PostgreSQL duplicate/overlap guards.
- Authorities: `BR-INV-*`, `DB-INV-*`, and `TEST-053` through `TEST-058`.
- Dependencies: published V1-027 configuration persistence and V1-035 move-in and
  Reservation-to-Lease orchestration.
- Excluded: Payment persistence, billing calculation/services, worker execution,
  Invoice API/UI, V1-040, canonical changes, and Hermes-wrapper changes.
- Canonical specifications: read-only.
- Implementation: complete for the bounded forward-only Invoice, line, calculation
  component, Adjustment/reversal, VOID, authorized-obligation, late-payment
  decision/Charge/correction, and billing-run persistence boundary.
- Independent review history: thirty-three fresh external read-only reviews found 139 material
  issues; all 139 were corrected with deterministic PostgreSQL regressions. Session and
  evidence paths are preserved in `ops/STATE.json`.
- Latest correction: Billing Run retries now serialize every Invoice selected by their
  cumulative latest source evidence and VOID chronology follows the latest successful attempt;
  two-component Service lines preserve one common rate snapshot or correctly retain distinct
  component rates. Evidence:
  `/private/tmp/property-rental-v1-039-independent-review-final-after-thirty-first.txt`.
- Final independent review: PASS with no material findings and no reviewer edits. Evidence:
  `/private/tmp/property-rental-v1-039-independent-review-final-after-thirty-second.txt`.
- Focused verification: PASS `325/325` real disposable PostgreSQL tests.
- Complete verification: PASS `15/15`; backend `629` passed with `314` expected environment
  skips, frontend `213` passed, disposable PostgreSQL `325` passed, and automation routing
  `185` passed. Evidence:
  `/private/tmp/property-rental-v1-039-thirty-second-review-corrections-final-verification.json`.
- Implementation publication: commit
  `069495af56e098eda08f16f12ae6db07607ab1ab`; exact-SHA GitHub Actions run
  `33138732828` passed all four jobs.
- Status: implementation published; the separate V1-039 closure commit and its own
  exact-SHA CI result remain pending.
- V1-040: held at `approved_ready`; no activation or implementation is permitted.
- Blockers: none.
- Exact next action: create and push only the V1-039 closure commit, require successful
  exact-SHA GitHub Actions, then reconcile closure-valid compact state while V1-040
  remains held.

<!-- AUTOMATION_STATUS_BEGIN -->

- Automation publication state: V1-039's implementation is published and exact-SHA
  CI-green but its closure remains pending; V1-040 remains held.
- Automation exact next action: keep the supervisor disabled and V1-040 held until
  V1-039 completes closure publication and reconciliation.

<!-- AUTOMATION_STATUS_END -->
