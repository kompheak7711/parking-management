# V1-056 sub-slice 10c-3c-1 — the 8a-1 allow functions need the row's own correlation and a draft naming the obligation — review record

Sub-slice: 10c-3c-1 (owner answer 3 to Q-2026-10-10-69 and answer (a) to Q-2026-10-10-70, an
approved tightening). Migration `20261217_143`. Base commit: 4227a37. Built on 2026-10-16. Not
pushed.

Rule IDs: BR-SETTLE-012, BR-SETTLE-013, BR-AUTH-010, DL-032; DB-SETTLE-005, DB-DEP-005. Design:
ops/V1_056_PLAN.md, "10c-3c-1 pre-code note" and its as-built line. Question raised:
Q-2026-10-16-117 (blocks nothing).

## Built

- Migration `20261217_143_settlement_correction_allow_hardening.py`: two new internal overloads,
  `app.settlement_correction_adjustment_allowed(uuid,uuid,uuid,uuid,text)` and
  `app.settlement_correction_charge_correction_allowed(uuid,uuid,uuid,uuid)` (SECURITY DEFINER,
  `search_path=pg_catalog`, revoked from PUBLIC and the three application roles), each the old body
  plus a join to the correction's draft and two conditions (the row's reference or correlation
  names the correction; the draft names exactly the obligation); an exact-text patch of
  `app.refuse_deposit_applied_obligation_change()` makes its two calls use them with the row's own
  values. The old three-argument functions stay, with no caller. Catalog dumps D1 (the two old
  functions) and D2 (the refusal) gave the anchors.
- Committed tests changed (owner standing rule; the approved hardening changes two hand-built
  results; expectations, docstrings and comments only, names kept):
  `test_settlement_deposit_refund_correction_migration.py::test_an_older_deposit_application_on_the_line_stays_and_unlinked_adjustments_stay_refused`
  (23514 to 55000) and
  `test_settlement_late_charge_deposit_refund_migration.py::test_a_linked_charge_correction_passes_8a_1_but_no_charge_is_paid_more_than_its_new_amount`
  (23514 to P4603; its in-transaction call of the old function is no longer reached; the name no
  longer fits, Q-2026-10-16-117).
- New module `test_settlement_correction_allow_hardening_migration.py` (last in
  `scripts/database-test.sh`): the commit-time checks kept with matching rows (both variants, both
  row kinds, 23514), one refused case per new condition (55000 for an Adjustment, P4603 for a
  Charge correction), least privilege and forward-only.
- 27 head-revision assertions in 15 modules moved to `20261217_143` (script, count per file
  checked). Traceability: the two committed tests' notes extended in place (indexes 2795 and 2894),
  three entries appended.
- Docs: docs/004 (a paragraph after the 10c-3b-2 one), docs/010 (as built, updated tests, review
  and runs), the plan, Q-2026-10-16-117.

Read-only search for affected tests: only the five writers of migrations 99, 100/103, 111 and
113/114 link `invoice_adjustment_id` or `late_payment_charge_correction_id`; among the tests only
the two committed hand-built cases above link such a row without meeting the new rule.

## Runs

| Run | Result |
|---|---|
| D1, D2 | catalog dumps (the old allow functions; the refusal), no `REDACTED` marker |
| FF1/FC1/L1/Y1 | backend format (formatter first; it wrapped the two long code lines the long-line search had found), format check, lint, type check passed |
| M1 | passed (`20261217_143` head) |
| T1 | 18 passed (the new module and the two changed committed modules) |
| U1 | 3804 passed |
| M2 | passed |
| P1 | 2207 passed (warnings: the known Starlette deprecation and one Pydantic alias warning of the unchanged Credit Refund API tests) |
| U2 | 3804 passed (after DL-032 was added to the three new traceability entries) |

No check or run failed, so no correction. After P1 only text changed (traceability upstream ids,
covered by U2; docs/004, docs/010, the plan, the questions file, this record, ops/NOW.md).

## Review round 1 (fresh read-only subagents, during P1; told to write no file and run no test, script or database command)

Independent: clean (0 blockers, 0 should-fix, 5 notes). Security: clean (0 blockers, 0
should-fix, 4 notes).

- Independent: both overloads are the old bodies plus the draft join and the two conditions;
  every writer's current form meets the rule (99 with its 111 patch, 103 with its 113 patch, 111,
  113 with its 114 patch); no writer is missed; the anchors appear once; the committed tests were
  compared with HEAD: only the affected expectation, docstrings and comments changed, nothing else
  weaker, and the moved coverage exists in the new module; keeping the test name follows the run
  rules (the rename rule covers only refused to allowed), so the owner is asked (Q-117).
- Notes taken (text): N1 the plan's wording of the "another line" case (the pet line is on another
  one-time-charge Invoice); N2 the `CHARGE_REDUCTION` writers never reach the allow functions today
  (their recorders refuse a Deposit-paid obligation), so they are shown by reading only, written in
  docs/004, docs/010 and the plan; N3 DL-032 in the three new traceability entries.
- Notes kept (slice 12 list): N4 no "answers false outside its transaction" check of the new Charge
  function; N5 (also security) the row's `authorization_reference` and an Adjustment's
  `adjustment_type` are not bound to the draft (outside the approved scope; a further tightening).
- Security: privileges and revokes match 103 and 114; no application role can reach the drafts,
  decisions, corrections or effects tables or the internal writers, so a hand-crafted draft is not
  reachable from the app; fail-closed for NULL references, JSON null `target_kind`, other kinds,
  other transactions and other Settlements; no legitimate correction is refused; no injection in the
  patch helper; no secret or database URL in the tests. Notes kept: the "another correction" cases
  use a random id (the docstring overstates it slightly); the stale test name (Q-117); the old
  functions with no caller (slice 12).
