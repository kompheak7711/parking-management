# V1-056 sub-slice 10c-2b-2b — returned Pet Refund-review Refund after closure: review record

Sub-slice: 10c-2b-2b (migration `20261113_109`). Base commit: 6e9cf17. Not committed (commit hash in
ops/NOW.md once committed).

Rule IDs: BR-SETTLE-013, BR-REFUND-014, DL-053, DL-032, BR-DEP-022, BR-AUTH-010; owner answer 6 to
Q-2026-10-08-55, the owner answer to Q-2026-10-08-60 and the owner instructions of 2026-10-09
(the 10c-2b-2a round-3 gap; no correction links a forfeiture for now; Q-53 and Q-57 stay open).

## Built

- Migration `20261113_109`:
  - Approved tightening: `app.require_correctable_usd_refund` refuses a Pet Refund-review Refund
    whose Lease's Final Settlement is closed (P5S01), after the Deposit lock, so the one-call
    verified return and the one-call reversal of a return are refused after closure;
    `app.validate_general_refund_correction` refuses every other row for such a Refund (P5S01)
    except the verified return of its own `REFUND_RETURN` correction.
  - `app.settlement_refund_return_settlement` (replaced) also names the closed Settlement of a
    Pet Refund-review Refund's Lease, so `REFUND_RETURN` returns it (return only: held by the Pet
    Deposit; with a new Refund the DL-032 step, only on the DL-032 path).
  - Approved tightening (Q-60): `app.record_lease_deposit_forfeiture_draft` refuses outside READ
    COMMITTED (55000).
- Service: the Refund service maps P5S01 to a conflict (routes 409); the returned-Refund command
  refuses a return date without a UTC form (10c-2b-1 round-3 note).
- Tests: new module `test_settlement_pet_refund_return_migration.py` (4 tests at P1, 6 after
  review round 1) on a new fixture (a DL-053 Refund paid and partly returned with one call before
  closure); two unit tests; 27 head-revision assertions; 8 traceability entries.
- Docs: docs/004 (DB-SETTLE-005, DB-REFUND-002, DB-DEP-007), docs/005 (API-066), docs/010 (owner
  answers of 2026-10-09, the sub-slice entry with three choices, updated tests, the owner answers
  to the report), the questions file (Q-60 and Q-59 answers, new Q-2026-10-09-61 and
  Q-2026-10-09-62 with their answers), the plan (2b entry, before-10h item, 11c note, slice 12
  items).

## Read-only search of every backend test

No committed test returns or reverses with one call a Pet Refund-review Refund of a Lease whose
Final Settlement is closed (the Pet Refund tests use Leases that never close; the Settlement Refund
tests correct only 8d Refunds). No test records a Lease forfeiture draft outside READ COMMITTED.
No test reads the bodies of the patched functions at head (only privilege checks and the
forward-only tests of earlier revisions, which upgrade to their own revision). No function is
added, so the function lists are unchanged. The 27 head-revision assertions move to
`20261113_109`.

## Runs

Static checks each in its own call. Type check failed once (cause A, test helper: the `tzinfo`
subclass lacked `dst` and `tzname`; correction 1 of 2), then clean. After review round 1: lint
failed once (cause C, import order in the new module; correction 1 of 2), then clean; format and
type check clean. T1 and T2 cover the new module only; the full runs cover the 27 head-revision
assertions (as in 10c-2b-2a). Migration-only check (throwaway copy of `scripts/database-test.sh`): 108 upgrades, head
`20261113_109`, before P1 and again after the review round 1 fixes.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| T1 | PostgreSQL, targeted: the new module (a check before the full run) | 4 passed | first run | `V1-056-slice-10c-2b-2b-targeted-test-run.txt` |
| U1 | backend unit, full (under `caffeinate -dims`) | 1 failed, 3634 passed, 1809 skipped | cause B: traceability entries missing for the 6 new tests; correction 1 of 2 (entries added) | `V1-056-slice-10c-2b-2b-unit-test-run.txt` |
| U2 | backend unit, full (under `caffeinate -dims`) | 3635 passed, 1809 skipped, 1 warning (Starlette) | after cause B | `V1-056-slice-10c-2b-2b-unit-test-run-2.txt` |
| P1 | PostgreSQL, full (under `caffeinate -dims`) | 1972 passed, 2 warnings (Starlette; the known Pydantic `UnsupportedFieldAttributeWarning`, slice 12 item) | first full run | `V1-056-slice-10c-2b-2b-full-test-run.txt` |
| T2 | PostgreSQL, targeted: the new module (covers every changed function body: the forward-only test pins them; no other test reads them at head) | 6 passed | review round 1 fixes | `V1-056-slice-10c-2b-2b-targeted-test-run-2.txt` |
| U3 | backend unit, full (under `caffeinate -dims`) | 3635 passed, 1811 skipped, 1 warning (Starlette) | review round 1 fixes | `V1-056-slice-10c-2b-2b-unit-test-run-3.txt` |

## Review round 1 (2026-10-09; fresh read-only subagents, independent and security)

Independent: 0 blockers, 2 should-fix, 8 notes. Security: 0 blockers, 0 should-fix, 4 notes.

- Independent SF1 (fixed, test): the 55000 refusal of a new Refund off the DL-032 path and the
  return-only form off that path were untested. New
  `test_a_returned_pet_refund_off_the_dl032_path_is_only_held` on the fixture with a BR-DEP-022
  termination (both Deposits forfeited before closure): the new-Refund form is refused at record
  (55000) and no draft is recorded; the return-only form is accepted and the kept Pet Deposit
  holds 2,000; a forfeiture after closure is refused (P5S01). This is the case of
  Q-2026-10-09-61.
- Independent SF2, security N2 (fixed, test): the insert check's refusal of an unlinked
  `VALUE_CORRECTION` row was not reached. The first test now writes such a row directly with
  `refunds.correct` and with `financial.approve` (P5S01 each).
- Security N1 (fixed, comment, docs and test): the "a closure committed meanwhile is seen" comment
  holds at READ COMMITTED; at REPEATABLE READ with an older snapshot the caller fails on the
  Deposit guard the closure updated (40001). Migration comment and docs/004 corrected; new
  `test_a_stale_repeatable_read_one_call_correction_fails_on_the_deposit_guard` (two snapshots
  taken before the Settlement confirm; both one-call paths fail with 40001).
- Independent N3 (plan): the 10c-2b-2a lock-order note now holds with the Deposit lock taken
  first by the refused one-call path; written in the plan entry.
- Independent N4 (plan, docs/010): the future `RETURN_REVERSAL` must also pass the new P5S01
  refusal; written.
- Independent N5, security N4 (plan, 11e list): the action contexts still offer the return and
  its reversal for such a Refund after closure (409 now); written.
- Independent N6, security N3 (fixed): the service's P5S01 message is generic ("Refund command
  conflicts with a closed Final Settlement"); the 409 has no body.
- Independent N7 (not added): no route test for the 409; the route's existing `_invoke` maps every
  `RefundConflictError` to 409 and the service mapping is unit-tested.
- Independent N8 (kept): the counts after a refused call document that nothing is written; they
  cannot fail because the call's transaction rolls back (harmless).
- Independent N9 (docs/004): the forfeiture recorder replays an exact repeat before the READ
  COMMITTED check, as the receipt reversal recorder does; written.
- Independent N10 (10d/10h list): the Lease forfeiture reversal draft still has no closed-Settlement
  check, as planned; written in the plan entry.

## Review round 2 (2026-10-09; new fresh read-only subagents, independent and security)

Independent: 0 blockers, 2 should-fix (documentation), 6 notes; every round 1 finding verified as
fixed or answered. Security: 0 blockers, 0 should-fix, 3 notes; every round 1 note verified. Under
the standing rule one round 3 follows, after one full unit run and one full PostgreSQL run.

- Independent SF1 (fixed, plan): the hold-flag item that docs/010 choice (3) sends to the slice 12
  list was missing there; added as a slice 12 open item, with the reason it is not built.
- Independent SF2 (fixed, questions file): Q-2026-10-09-61 claimed that before closure the same
  return always makes the Settlement require a forfeiture; true only for a Pet Deposit with the
  ground and no forfeiture (`NOTHING_HELD` to `FORFEITURE_REQUIRED`); a `KEPT` Pet Deposit with
  returned money blocks nothing before closure and is never refunded. The question now states both
  cases, notes that the gap already exists before closure for `KEPT`, and that option (a) means a
  second disposition there.
- Independent N3 (fixed, test): the BR-DEP-022 test now checks that the ledger reconciles.
- Independent N4 (fixed, docstring and traceability): the stale REPEATABLE READ test checks the
  fail-closed claim of the migration comment; the guard predates migration 109.
- Independent N5 (fixed, this record): the type check after round 1 was clean; T1 and T2 cover
  only the new module, the full runs cover the head-revision assertions.
- Independent N6 (fixed): BR-DEP-022 added to the rule-ID lists (this record, the migration
  docstring, the docs/010 entry).
- Independent N7 (fixed, plan): the BR-DEP-022 fixture variant named in the plan entry.
- Independent N8 (owner report): docs/010 choice (1), P5S01 and 409 instead of P5202 and 422,
  stays visible in the report.
- Security N1 (fixed, test): the stale connections are opened inside the `try` that closes them,
  with a lock timeout.
- Security N2 (10d/10h list, already recorded): the Lease forfeiture reversal draft after closure
  can bring money back into a Deposit without a correction; the payout is then a linked approved
  correction, but the inflow is not. Stays planned for 10d/10h.
- Security N3 (plan, slice 12 list): the in-function lock-order comment of
  `app.confirm_settlement_refund_return` is reworded when that function is next replaced.

After the round 2 fixes: format, lint and type check clean, each in its own call;
migration-only check 108 upgrades, head `20261113_109`. No change to the read-only test search.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U4 | backend unit, full (under `caffeinate -dims`) | 3635 passed, 1811 skipped, 1 warning (Starlette) | standing rule before round 3 | `V1-056-slice-10c-2b-2b-unit-test-run-4.txt` |
| P2 | PostgreSQL, full (under `caffeinate -dims`) | 1 failed, 1973 passed, 2 warnings | standing rule before round 3; the new module passed (6); failure outside 10c-2b-2b: `test_refund_migration.py::test_usd_refund_blocks_source_reversal_until_full_verified_return[False]`, `LockNotAvailable` on `app.payment_allocations` from `LOCK TABLE ... IN SHARE MODE NOWAIT` in `app.assert_payment_excess_eligible` (a direct Payment Refund insert; it passed in P1) | `V1-056-slice-10c-2b-2b-full-test-run-2.txt` |

STOPPED before review round 3 (Q-2026-10-09-62): a test outside the sub-slice that passed before
failed (takeover section 6; run rule: no retry). Nothing committed.

## Owner answers to the report (2026-10-09) and the owner-approved rerun

Owner answers (recorded in docs/010, the questions file and the plan; no code or test changed):
Q-2026-10-09-62 option (a), one more full PostgreSQL run, stop if it fails again; the second test
joins the slice 12 `LockNotAvailable` item, whose cause is also looked for in the lock code;
Q-2026-10-09-61 stays open before 10h with Q-53 and Q-57, rewritten with the options keep and pay
back (recommendation: pay back), no correction that links a forfeiture until answered; P5S01 and
409 kept for both return routes, with an 11c note to move the 10c-2b-1 refusal (P5202, 422) to 409
later. Standing checks before the run: migration-only check 108 upgrades, head `20261113_109`; no
code or test change since the read-only search.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U5 | backend unit, full (under `caffeinate -dims`) | 3635 passed, 1811 skipped, 1 warning (Starlette) | the owner's instruction 5 (full unit run with P3) | `V1-056-slice-10c-2b-2b-unit-test-run-5.txt` |
| P3 | PostgreSQL, full (under `caffeinate -dims`) | 1974 passed, 2 warnings (Starlette; the known Pydantic `UnsupportedFieldAttributeWarning`) | owner-approved rerun after the outside lock failure in P2 (Q-2026-10-09-62) | `V1-056-slice-10c-2b-2b-full-test-run-3.txt` |

## Review round 3 (2026-10-09; new fresh read-only subagents, independent and security; the standing rule's round 3)

Independent: 0 blockers, 0 should-fix, 4 notes. Security: 0 blockers, 0 should-fix, 4 notes. No
should-fix, so 10c-2b-2b is committed (hash in ops/NOW.md). Text fixes after round 3 (no code or
test changed):

- Independent N1 (questions file): the superseded options and recommendation of Q-2026-10-09-61
  are marked as superseded (kept as written).
- Independent N2 (docs/010): the "no other committed test changed" sentence moved back into the
  updated-tests bullet; the P3 result added there.
- Independent N3, security N2 (this record, NOW.md): the owner answers, U5, P3 and this round
  added; the NOW.md stop line marked superseded and the commit line added.
- Independent N4 (no change): the replaced Settlement lookup is pinned only for its privileges by
  the forward-only test, as in 107 and 108; its new branch is proven by the return tests.
- Security N1 (10d/10h, owner report): the Lease forfeiture reversal draft after closure can bring
  money back into a kept Pet Deposit without a correction; a later `REFUND_RETURN` could then pay
  it out, linked. Not caused by 109; stays planned for 10d/10h.
- Security N3 (no change): `_draft_call` does not map P5S01; no draft path raises it today; map it
  if a later slice adds one.
- Security N4 (no change): a custom tzinfo raising an exception other than `ValueError`,
  `TypeError` or `OverflowError` still escapes the command check; not reachable over HTTP.
