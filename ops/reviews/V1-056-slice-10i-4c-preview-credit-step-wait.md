# V1-056 sub-slice 10i-4c — the preview lists another Settlement's waiting correction draft that uses a Lease person's Credit — review record

Sub-slice: 10i-4c, the last part of sub-slice 10i-4 (owner answer (a) to Q-2026-10-20-146).
Migration `20270117_174` (one exact-text replacement of the pending-draft filter of
`app.final_settlement_preview`, two parts each checked to match once). Base commit: e742339
(10i-4b). Built on 2026-10-20 in the same session as 10i-4a and 10i-4b. Not pushed. The commit
hash is in `git log` (this record is part of that commit).

## Built

- The preview's pending-draft filter also lists another Settlement's waiting
  `SETTLEMENT_CORRECTION` draft of any variant whose plan (`payload->'plan'->'steps'`, read only
  when an array) has a `CUSTOMER_CREDIT` step on a Credit held by a person of the Lease, or of the
  variant `REFUND` (the line and the Late-payment Charge Refund corrections) whose plan overlay
  (`payload->'plan_overlay'->'credits'`, read only when an object) has a key that is such a
  Credit. A released Payment allocation is keyed by its allocation and is not listed (its Credit
  exists only after the confirm). A Settlement's own drafts are not listed for it. The issue's
  shape and the identity rule are unchanged; signature, owner, settings and grants kept.
- Effects: the Settlement draft recorder, the 8e-3 confirm and every correction plan run the same
  preview, so the other Lease does not close, and a closed Settlement of such a Customer takes no
  correction step, while the draft waits. Withdrawal and rejection do not run the preview.
- Not built (Q-2026-10-20-149, recommendation (a)): the `REFUND_RETURN` overlay part.

## Committed tests changed

The 27 head-revision strings in 15 modules (revision strings only; a script checked each file's
count). No other committed test changes: the targeted run T1 (49 modules: every correction module
with two Leases, the Credit-step modules, the preview, draft and confirm modules, the 10h-3 and
10h-4a modules) passed except the new module's test 1, and the full runs P1 and P2 passed.

## New tests

Module `test_settlement_preview_credit_step_wait_migration.py` (last in
`scripts/database-test.sh`):
`test_a_waiting_correction_whose_plan_uses_a_credit_holds_the_other_lease`,
`test_a_waiting_refund_that_releases_value_into_a_credit_holds_the_other_lease`,
`test_the_credit_step_wait_migration_is_least_privilege_and_forward_only`. Set-up note (test 1,
run T1 cause A): A's draft is recorded before B exists, because B's own Initial Rent Credit is
also the Customer's and DL-032 would make A's plan apply it too; B is unblocked by the withdrawal
and closes with a plan in which K pays 300 of B's line. Traceability: 3 entries appended (round 2
note: BR-SETTLE-012 added to two of them); the first 1,598 entries untouched.

## Reviews

Round 1:
- Independent: no blocker; should-fix 1, the design's 8e-3 confirm refusal of a B draft recorded
  before the correction was untested (added to test 2: B's confirm is refused, 55000, the draft
  stays pending and B's line unchanged; after A's confirm the early draft is withdrawn and B
  closes); should-fix 2, a traceability note said K pays on the closed Lease (corrected). Notes:
  the hidden identity form and the rejection path are not tested separately (the identity CASE is
  unchanged and tested in the 10h-3 and preview modules; the filter's decision test treats a
  rejection like a withdrawal); no test of a `REFUND` overlay with only a released allocation key;
  the amounts add up; some return-reversal modules were not in T1 (the full runs cover them).
- Security: clean. Notes: the holds are the same class as the earlier holds (an approver can
  reject); two drafts recorded at the same moment hold each other until one is decided; a closure
  draft of B that uses a Credit does not stop a later correction draft of A on it, and B's confirm
  then waits; the jsonb scans are bounded; no test of malformed payloads (the app cannot store
  them; they match nothing); the overlay part covers `REFUND` only (Q-149).

Round 2 (one fresh reviewer with both checklists): clean. Notes: test 1 could assert that its
overlay has no Credit key; the hidden identity form (as above); BR-SETTLE-012 in the
traceability entries and the withdraw step in the test 2 note (both added, text only).

No should-fix in round 2, so no round 3.

## Runs (logs in ~/Development/prm-run-logs/, prefix `v1-056-10i-4c-`)

| Run | Result | Cause |
|---|---|---|
| FF1 (one file reformatted), I1, FC1, L1, Y1 | pass | backend checks |
| U1 | 3,871 passed | unit suite |
| M1 | pass | migration-only check |
| T1 | 769 passed, 1 failed | cause A (1 of 2): test 1 recorded A's draft after B existed; DL-032 refused A's plan (55000, "Each Customer's Credit must pay that Customer's open debt...") |
| FF2, I2, FC2, L2, Y2 | pass | after the cause A fix |
| T2 | 3 passed | targeted, the new module |
| M2 | pass | migration-only check |
| P1 | 2,438 passed | full PostgreSQL run |
| FF3, I3, FC3, L3, Y3 | pass | after the round 1 test changes |
| T3 | 3 passed | targeted, the new module |
| U2 | 3,871 passed | unit suite |
| M3 | pass | migration-only check |
| P2 | 2,438 passed | full PostgreSQL run |

One correction (T1, cause A, 1 of 2). No `LockNotAvailable` failure. After P2 only text changed
(docs, plan, traceability notes and ids, this record, NOW.md).
