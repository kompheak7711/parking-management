# V1-037 Security and Pet Deposit persistence/domain services — verified

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
- Publication: not started.
- V1-038: remains held at `approved_ready` and untouched.
- Blockers: none.
- Exact next action: publish separate V1-037 implementation and closure commits with
  successful exact-SHA GitHub Actions while the supervisor remains disabled.

<!-- AUTOMATION_STATUS_BEGIN -->

- Automation publication state: V1-037 is verified locally but unpublished.
- Automation exact next action: keep the supervisor disabled and V1-038 held while
  V1-037 completes publication.

<!-- AUTOMATION_STATUS_END -->
