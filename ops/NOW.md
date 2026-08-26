# V1-037 Security and Pet Deposit persistence/domain services — complete

- Candidate: `V1-037` — Security and pet deposit persistence and domain services.
- Authorization: existing durable V1 roadmap authorization plus direct Owner takeover;
  no renewed routine authorization is required.
- Baseline: clean synchronized `implementation/foundation` at V1-036 reconciliation
  correction `ab3f4b349688d4e897eca5640165e98502ef7c52`.
- Preflight: PASS; no repository worker, mutation process, lock, or restoration
  continuation overlapped this direct cycle.
- Scheduler: the Property Rental supervisor remains disabled and not running.
- Scope: separate Security and Pet Deposit liabilities; approved-pet/signed-term
  qualification; required-amount history; receipt-reversal history; Lease-governed
  disposition/reversal history; derived balances; and active-Lease Pet Deposit Refund
  qualification without creating the Refund.
- Authorities: `BR-DEP-*`, `PR-DEP-*`, `DB-DEP-*`, `TEST-036` through `TEST-039`,
  and `TEST-126`.
- Dependency: published V1-035 move-in orchestration and its Security Deposit continuity.
- Excluded: Final Settlement, Deposit API/UI, actual active-Lease Refund execution,
  V1-038 implementation, canonical changes, and Hermes-wrapper changes.
- Canonical specifications: read-only.
- Implementation: protected forward-only migration, separate Deposit identities,
  PostgreSQL source/uniqueness/balance constraints, append-only corrections and
  reversals, idempotent Property-scoped financial-role commands, stable derived
  balances, and permanent pet-departure/refund-review evidence. General Deposit
  receipt creation is deliberately withheld until authoritative Payment persistence.
- Verification: PASS; focused Deposit/domain checks, disposable PostgreSQL `285/285`,
  and complete deterministic verification profile `15/15` (`618` backend, `196`
  frontend, and `185` automation tests).
- Review: PASS. The first external review found six material issues; all six were
  corrected. A fresh external Codex read-only review of the corrected final diff
  reported zero material findings and made no edits.
- Implementation publication: commit
  `67de8cbaff6a26a4c1cc7ee9d9f80b7c98e97656`; exact-SHA GitHub Actions run
  `32965578375` passed all four jobs on attempt 2 after one unrelated pre-existing
  frontend timing test passed its focused rerun and the exact-SHA job rerun.
- Closure: commit `ff89c5148f90fa10b49a6c8d2f562a6dd6269387`;
  exact-SHA GitHub Actions run `32966323183` passed all four jobs.
- Status: complete, published, independently reviewed, and closure-valid.
- V1-038: remains held at `approved_ready`; no product work or activation occurred.
- Held-successor routing: the invalid noncanonical `UI-DEP-*` placeholder was
  materialized to the existing exact Deposit-related UI requirements `UI-030`,
  `UI-033`, `UI-035`, `UI-043`, `UI-044`, `UI-071`, `UI-073`, `UI-074`,
  `UI-076`, and `UI-107`; no V1-038 product work or activation occurred.
- Blockers: none.
- Exact next action: keep V1-038 held at `approved_ready` and keep the Property
  Rental supervisor disabled; do not activate the successor automatically.

<!-- AUTOMATION_STATUS_BEGIN -->

- Automation publication state: V1-037 implementation and closure are published
  and exact-SHA CI-green; V1-038 remains the held approved successor.
- Automation exact next action: keep the supervisor disabled and V1-038 held while
  awaiting explicit direct-takeover or activation direction.

<!-- AUTOMATION_STATUS_END -->
