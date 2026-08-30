# V1-043 Utility meter, reading, preview, and billing UI/API — corrective closure pending

- Candidate: `V1-043` — Utility meter, reading, preview, and billing UI/API.
- Authorization: Owner standing direct-Codex authorization for V1-042 through V1-060;
  this release card is limited to the exact independently reviewed V1-043 SHA.
- Baseline: clean synchronized `implementation/foundation` at V1-042 corrective
  reconciliation commit `a7a7b9d3d63da0d9c24c55c2a4a8e1fa94c81af9`.
- Original implementation: exact cumulative commit
  `4bf6c75d2709ddf8e989892364038795df7040b1`, published and exact-SHA
  CI-green in run `33323322907`.
- Original closure: operational-only commit
  `81d981a7fd8eb3abb681bd7be94762b4add82f15`, exact-SHA CI-green in run
  `33323808705`.
- Superseded reconciliation: commit
  `fc461aed518d4ca49d68f8b5479c22787ec1cfdc`; GitHub Actions run
  `33324280423` failed its PostgreSQL job twice at 431/432 because the deposit
  chronology fixture mixed runner-local and Property-local business dates.
- Corrected release target: exact commit
  `01f6be3350590f1882e8056ad214df9ebc22c002`, direct parent
  `fc461aed518d4ca49d68f8b5479c22787ec1cfdc`; commit 12 and 26 cumulative
  paths from baseline. Its sole child diff is
  `backend/tests/test_deposit_migration.py` (8 insertions, 1 deletion).
- Scope: Property-scoped Meter lifecycle and history, validated and pending Reading
  history, replacement and correction evidence, bounded single and bulk Reading entry,
  authoritative preview, Rate history, and accessible authenticated Utility UI/API.
- Authorities: `API-044` through `API-049`, `UI-056` through `UI-062`,
  `TEST-046` through `TEST-052`, `TEST-117`, `TEST-118`, and `TEST-119`.
- Excluded: silent estimation, product corrections during release, canonical changes,
  Invoice issuance, scheduled billing, deployment, production data, and V1-044 work.
- Corrected independent review: Workboard card
  `4545b9fe-505c-4117-905e-6587eb4d2903` returned PASS with zero findings for
  exact SHA `01f6be3`; reviewer made no edits and property-manager acceptance is
  recorded.
- Corrected local release verification: chronology 2/2 in default +07 and 2/2 in
  `TZ=UTC`; focused backend 19/19 and frontend 20/20; Decimal precision-19
  probe 8 valid/25 rejected with caller context unchanged; complete profile 15/15;
  real `TZ=UTC` PostgreSQL 432/432 with zero failures and zero skips; all full
  format, lint, strict type, build/import, test, dependency, traceability, Alembic,
  deployment, publication, automation, and diff gates passed.
- Corrected target publication: GitHub Actions run `33326888594` passed all four
  jobs for exact SHA `01f6be3350590f1882e8056ad214df9ebc22c002`.
- Status: V1-043 is functionally complete and the corrected implementation is
  published and exact-SHA CI-green; this corrective closure and final
  reconciliation remain pending.
- V1-044: remains held at `approved_ready`; no activation, implementation, or dispatch
  has occurred.
- Scheduler: no scheduler weakening or activation occurred.
- Blockers: none.
- Exact next action: publish this corrective closure commit, require successful
  exact-SHA GitHub Actions, then create at most one ops-only reconciliation commit,
  require its exact-SHA CI, prove final synchronization, and release only to REVIEW.

<!-- AUTOMATION_STATUS_BEGIN -->

- Automation publication state: corrected V1-043 target `01f6be3` is published and
  exact-SHA CI-green; corrective closure and final reconciliation are pending.
- Automation exact next action: keep V1-044 held and undispatched while corrective
  closure, reconciliation CI, and final synchronization complete.

<!-- AUTOMATION_STATUS_END -->
