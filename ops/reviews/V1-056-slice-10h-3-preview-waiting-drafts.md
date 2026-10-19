# V1-056 sub-slice 10h-3 — the Final Settlement preview's waiting drafts — review record

Sub-slice: 10h-3 (owner answer (a) to Q-2026-10-17-120 point 3). Migration `20270111_168` (one
exact-text replacement of `app.final_settlement_preview`, three parts each checked to match
once). Base commit: e3dd3b9 (the owner answers to the 10h-2 report and the 10h-3 pre-code design).
Built on 2026-10-20 in a fresh session. Not pushed.

## Built

- The preview's pending-draft check also lists: another Lease's waiting `SETTLEMENT_CORRECTION`
  draft of the variant `PAYMENT_MOVE` whose correct Invoice is an Invoice of the Lease; a waiting
  `PAYMENT_RETURN` draft whose Payment has an active allocation on an obligation of the Lease, an
  active Customer Credit held by a Lease person, an active application of one of its Credits on
  such an obligation, or an active receipt into a Deposit of the Lease; a waiting 10f-1
  `ADJUSTMENT_REVERSAL` draft of an Adjustment on an Invoice of the Lease. The Deposit branch is
  limited to its three earlier kinds (both reviewers: the `FORFEITURE_REVERSAL` and
  `DEPOSIT_RECEIPT_CORRECTION` correction payloads carry a top-level `deposit_id`, so without the
  limit they would block their own record and confirm). The issue's shape and the identity rule
  do not change. Services and routes are unchanged.
- Implementer's readings (design, confirmed sound by the independent reviewer): (i) the Credit
  branch, not named in the 10h sketch; (ii) a Payment's unallocated value is not read; (iii) every
  correction plan runs the same preview, so such a waiting draft on a closed Lease's sources also
  holds that Settlement's correction steps until it is confirmed, rejected or withdrawn.
- Committed tests changed (standing rule of 2026-10-19 with Q-2026-10-19-144):
  - `test_payment_return_migration.py::test_a_closed_settlement_s_records_are_refused_and_a_later_payment_is_returned`
  - `test_adjustment_reversal_migration.py::test_a_closed_settlement_s_adjustment_waits_for_a_correction`
  - `test_settlement_adjustment_reversal_migration.py::test_refusals_waiting_drafts_stale_drafts_and_withdrawal`

  Each recorded a Payment return or 10f-1 draft before the closure and closed while it waited,
  which 10h-3 refuses. Each now records the draft with the real recorder in an owner transaction
  that is rolled back (new support module `waiting_draft_test_support.py`), asserts there that
  the preview lists the draft (`PENDING_DRAFT`, not ready) and that the Settlement draft recorder
  refuses (55000 "The Final Settlement has blocking issues", nothing written; added in review
  round 1, independent should-fix), closes for real, and writes the same draft (kind, payload,
  source revision and reason the recorder stored) as the owner through
  `app.insert_financial_draft`. No withdrawn draft is left, so every draft count, check and amount
  is unchanged versus HEAD (independent reviewer confirmed); comments and a docstring sentence
  say why; no name became wrong.
  - The 27 head-revision strings in 15 modules.
- New module `test_settlement_preview_waiting_drafts_migration.py` (six tests, last in
  `scripts/database-test.sh`). Test 4 is the only one that reaches the Late-payment Charge
  allocation path (`pay_charge`). Docs: docs/002 BR-SETTLE-002, docs/004 (the preview's issues),
  docs/010; traceability appended (six entries).

## Runs

| Run | Result |
|---|---|
| D1 | catalog dump of the preview, `app.payment_return_source`, both `app.adjustment_reversal_source` overloads and `app.record_adjustment_reversal_draft`; no `REDACTED` marker |
| FF1/I1/FC1 | passed (I1 sorted one import) |
| L1 | failed: 3 long lines (cause A, 1 of 2) and 5 F811 fixture redefinitions (cause B, 1 of 2), all in the new module |
| FF2/I2/FC2/L2 | passed (queries moved to a constant; the fixture imported as `migrated_database_url as migrated_database_url`) |
| Y1 | failed: `None` passed to `shown`'s variant (cause C, 1 of 2) |
| FF3/I3/FC3/L3/Y2 | passed (local `no_variant` helper) |
| M1 | passed |
| T1 | 94 passed (9 modules in full-suite order) |
| U1 | 3867 passed |
| M2 | passed |
| P1 | 2408 passed |
| (after the round 1 fixes) | |
| FF4/I4/FC4/L4/Y3 | passed |
| T2 | 32 passed (the four changed test modules) |
| U2 | 3867 passed |
| M3 | passed |
| P2 | 2408 passed |
| (after the round 2 fixes) | |
| FF5/I5/FC5/L5/Y4 | passed |
| M4 | passed (the migration changed) |
| T3 | 109 passed (11 modules in full-suite order) |
| U3 | 3867 passed |
| M5 | passed |
| P3 | 2409 passed |

Full outputs in `~/Development/prm-run-logs/v1-056-10h-3-*.txt`, one file per attempt.

## Review round 1 (fresh read-only subagents, during P1; told to write no files at all, scratch files included, and to run no test, script or database command)

Independent: no blocker, 1 should-fix, 7 notes. Security: no blocker, 2 should-fix, 8 notes.
Handled (tests and text only; no code or migration change):
1. Independent S1: the helper now also asserts the Settlement draft recorder's refusal in the
   rolled-back transaction (reviewer's set-up: an empty plan reaches the blocking-issues
   refusal, the FINAL_SETTLEMENT draft count unchanged).
2. Security S1, independent N2: the identity rule for the new kinds: a
   `final_settlements.prepare`-only reader sees `{"code": "PENDING_DRAFT"}`; a holder of
   `payments.reverse` or `invoices.adjust` sees the draft. A correction draft is shown to every
   preview reader (its preparer capability is `final_settlements.prepare`), so "hidden" does not
   apply to it.
3. Security S2, independent N3: while the draft waits it is the preview's only blocking issue;
   after each withdrawal the preview is ready with no blocking issue.
4. Independent N1: test 1 also asserts that the second Settlement draft is not recorded while the
   correction waits (count unchanged), then records it and keeps the confirm checks with a second
   correction draft.
5. Security N2: test 2 asserts that each Payment has exactly one active record (allocation,
   Credit or receipt), so each case proves its own branch.
6. Security N6: docs/002 says "confirmed by an approver, rejected or withdrawn".
7. Independent N7: docs/004 says the Credit branch reads any active Credit a Settlement Customer
   holds from that Payment, with money left or not (fail closed).
8. Security N1, independent N4: the Credit-application sub-branch has no test of its own. It is a
   fail-closed duplicate: a Credit pays only its holder's obligations (BR-CREDIT-008), and every
   Customer named on an issued, non-VOID Invoice of the Lease is in `v_people`, so the Credit
   branch lists such a Payment first. Kept as a defensive check.
9. Slice 12 notes (security N3 to N5 and N8): see the plan's slice 12 list.
10. Independent N5: this record lists the three changed committed tests.

## Review round 2 (fresh read-only subagents, during P2; same instructions)

Independent: no blocker, no should-fix, 6 notes. Security: no blocker, 1 should-fix, 5 notes. So
the round 3 rule applies (the one should-fix is a fail-closed check that adds a refusal):
1. Security S1 (code; design change under the run rule, for the round 3 reviewers to confirm):
   a closed Settlement's waiting `RETURNED_PAYMENT` correction draft reaches the whole Payment,
   so an open Lease where that Payment has an active record could close while it waits, and its
   confirm would then be refused (two closed Settlements relied on the Payment; owner answer (a)
   to Q-2026-10-10-72 point 3), leaving the bounced Payment with no way back. Branch (b) of the
   migration now also lists such a draft, except one of the Settlement being previewed (so a
   Settlement's own correction never holds its own corrections). The design sentence that other
   correction variants never wait on an open Lease's sources is corrected in the plan. Search of
   committed tests (every module that records a `RETURNED_PAYMENT` correction): none leaves one
   waiting while another Lease of its Payment is previewed, recorded, confirmed or corrected
   (`test_a_record_on_another_open_lease_is_reversed_and_linked` records and confirms at once).
   New test `test_a_waiting_returned_payment_correction_blocks_the_other_lease_of_its_payment`
   (reviewer's set-up, through `two_settlements_case(url, close_second=False)`); test 5 also checks
   the new branch, the own-Settlement exclusion and the Deposit-branch limit by body count
   (independent N6).
2. Security N3: the helper asserts the waiting draft is the preview's only blocking issue.
3. Security N2, independent N1, N2 and N4 (text): docs/010 says "confirmed, rejected or
   withdrawn" and names the recorder refusal of the rolled-back recording; the plan's reading
   (iii) says "rejected"; the docs/004 Credit-branch bracket is moved next to that branch.
4. Independent N5: traceability of tests 2 and 3 names BR-AUTH-010 and the round 1 additions.
5. Security N1 nit: the slice 12 note on the 10-entry capability list now says the list was
   already full before 10h-3.
6. Security S1, related and not verified (the Credit-refund corrections `REFUND` and
   `HELD_VALUE_REFUND`): a slice 12 note.
7. Independent N3 (the "nothing written" counts cannot fail when the refusal rolls back): kept
   as is; the refusal tuple is the check, and the counts document the expectation.

## Review round 3 (fresh read-only subagents, after U3 and P3; same instructions)

Independent: no blocker, no should-fix, 5 notes. Security: no blocker, no should-fix, notes only.
Both confirm the round 2 design change is needed and safe: the `RETURNED_PAYMENT` confirm is
refused once another closed Settlement relied on the Payment (migration 117, about line 126),
the RETURNED_PAYMENT record and confirm run neither the preview nor the plan, every plan caller
passes its own Settlement (excluded), `final_settlements.lease_id` is unique, and no committed
test leaves such a draft waiting across another Lease's preview, closure or correction. Round 3
is clean, so there is no round 4. Text-only notes handled after P3 (ops files only; no code,
migration or test file):
1. Independent N1: this record says six tests and six traceability entries.
2. Independent N2: the plan's "New tests" list names the round 2 test. Kept as is: the new test
   module's docstring does not name the `RETURNED_PAYMENT` branch (its test docstring does), so
   no test file changes after P3.
3. Independent N3, security slice 12 note: the slice 12 note (1) also names
   `final_settlements.prepare` holders and other Settlements' waiting `RETURNED_PAYMENT`
   correction drafts at upgrade time.
4. Independent N4, security race note: the slice 12 note (2) also covers this variant.
5. Independent N5, security first note: U3 (3867) and P3 (2409) ran after the round 2 change.
