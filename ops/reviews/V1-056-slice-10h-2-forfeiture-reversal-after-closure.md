# V1-056 sub-slice 10h-2 — the 6b forfeiture reversal after closure, and the 10h-1 triggers at READ COMMITTED only — review record

Sub-slice: 10h-2 (owner answer 4 to Q-2026-10-06-36, answer 6 to Q-2026-10-10-69, answer (a) to
Q-2026-10-19-143). Migration `20270110_167` (one internal function, one trigger, three exact-text
replacements). Base commit: 0da89ef (10h-1b). Built on 2026-10-20 in the same session as the
10h-1b commit. Not pushed.

## Built

- `app.lease_deposit_reversal_source`: P5S01 "The Lease's Final Settlement is closed; reverse this
  forfeiture through a correction of that Final Settlement" when the forfeiture's governing Lease
  or its Deposit's Lease has a closed Final Settlement, after its already-reversed check (design
  change confirmed needed and safe in review round 1: a committed test expects 22023 for an
  already reversed forfeiture after the closure). The 6b recorder and confirm refuse; a waiting
  draft stays pending. The forfeiture service already maps P5S01 to a conflict.
- New internal `app.refuse_closed_settlement_forfeiture_reversal()` (no grant) and BEFORE INSERT
  row trigger `a0_deposit_disposition_reversals_final_settlement`: locks the Deposit row, holds the
  closed Settlement rows of the governing Lease and the Deposit's Lease FOR SHARE, and refuses
  (P5S01, the 8e-1 text) a reversal that a correction of each, confirmed in the same transaction,
  does not link. As built (review round 1, text corrected): an open Settlement is not locked, so
  there is no deadlock with a running confirm; the Deposit lock orders the writer against a
  closing confirm; a REPEATABLE READ writer fails on the Deposit state guard (40001).
- Q-2026-10-19-143 (a): the two 10h-1 trigger functions refuse (55000) a reversal written at an
  isolation level other than READ COMMITTED, as their first statement. Search (the answer's
  condition): every app path at a stricter level is read-only; no script sets one; no test writes
  a reversal at one. The 8e-1 refusal is not changed (the answer names the 10h-1 triggers).
- Committed tests changed (standing rule of 2026-10-19 with Q-2026-10-19-144):
  - `test_settlement_forfeiture_reversal_migration.py::test_a_second_active_forfeiture_of_the_deposit_refuses_its_reversal`:
    the 6b draft after the closure is asserted refused (a conflict, P5S01, nothing written), then
    the same reversal is written as the owner with `app.reverse_deposit_disposition_v2` and only
    the new trigger disabled in that transaction (new helper `reverse_forfeiture_by_hand`); comment
    and docstring updated; every check and amount unchanged.
  - `::test_a_forfeiture_reversal_refuses_other_forfeitures_waiting_drafts_and_stale_drafts`: its
    two 6b drafts recorded after the closure (one waiting, one making the correction draft stale)
    now come from the new helper `waiting_six_b_draft` (the recorder's refusal asserted first, then
    the draft written by the owner through `app.insert_financial_draft` with the recorder's payload
    and digest); every check and amount unchanged. My pre-code search missed this test, because
    its helper `six_b_draft` calls the service, not the database function; found while building.
  - The 27 head-revision strings in 15 modules.
- New module `test_settlement_forfeiture_reversal_after_closure_migration.py` (four tests, last in
  `scripts/database-test.sh`). Docs: docs/002 BR-SETTLE-013, docs/004 DB-SETTLE-005, docs/005,
  docs/010; traceability appended (four entries).

## Runs

| Run | Result |
|---|---|
| D1 | catalog dump of the 6b source, recorder and confirm, `app.reverse_deposit_disposition_v2`, `app.serialize_deposit_state`, `app.serialize_deposit_balance_event` and the two 10h-1 trigger functions; no `REDACTED` marker; `~/Development/prm-run-logs/v1-056-10h-2-D1.txt` |
| I1/FF1/FC1/L1/Y1 | passed (long-line and unused-import search first: nothing found) |
| M1 | passed |
| T1 | 91 passed, 1 failed (9 modules in the full-suite order; cause A below) |
| I2/FF2/FC2/L2/Y2 | passed |
| T2 | 6 passed (the fixed module) |
| U1 | 3867 passed |
| M2 | passed |
| P1 | 2402 passed |
| (after the round 1 fixes) | |
| I3/FF3/FC3/L3/Y3 | passed |
| M3 | passed (the migration comment changed) |
| T3 | 10 passed (the two changed test modules) |
| U2 | 3867 passed |
| M4 | passed |
| P2 | 2403 passed |

Cause A (a hand-built set-up; correction 1 of 2): `reverse_forfeiture_by_hand` enabled the
trigger again while the table had pending deferred trigger events (`ObjectInUse`); it now runs
`SET CONSTRAINTS ALL IMMEDIATE` first.

Full outputs in `~/Development/prm-run-logs/v1-056-10h-2-*.txt`, one file per attempt.

## Review round 1 (fresh read-only subagents, during P1; told to write no files at all, scratch files included, and to run no test, script or database command)

Independent: no blocker, 2 should-fix, 6 notes. Security: no blocker, 1 should-fix, 5 notes.
Handled:
1. Independent S1, security N1 (text): the trigger comment, docs/004 and plan item (2) described a
   Settlement-row wait and a 40P01 deadlock; the `closed_at` filter means an open Settlement is
   never locked. Rewritten to the as-built mechanism (the code is kept; it avoids the deadlock):
   a Lease forfeiture's governing Lease is its Deposit's Lease
   (`app.validate_lease_deposit_disposition`); the 8e-3 confirm takes each Deposit and its state
   guard before it closes and re-checks its digest afterwards (P5S02); a writer that waited reads
   the committed closure; a REPEATABLE READ writer fails on the guard (40001).
2. Independent S2, security S1 (test): new test
   `test_on_a_lease_with_no_settlement_a_reversal_is_recorded_only_at_read_committed`. Reviewers'
   set-up: `test_payment_allocation_migration.source` with a proposal allocation, and
   `test_credit_application_migration.source` with a designated application; both reversals at
   REPEATABLE READ and SERIALIZABLE give 55000 with nothing written, then pass through the
   services at READ COMMITTED.
3. Independent N3: the hand-built waiting 6b draft (a waiting 6b draft blocks the closure with
   `PENDING_DRAFT`) is explained in the test docstring and the plan.
4. Independent N4: docs/002 names the returned-Payment and receipt corrections that also link;
   BR-DEP-019 needs no change; docs/004 names the fail-closed two-Settlement case.
5. Independent N1, security N2 to N4: slice 12 notes (the 8e-1 refusal has no isolation check;
   the new trigger has none of its own; the allocation service maps 55000 to "unavailable"; the
   untested other-Lease correction and Deposit-Lease branch).
6. Independent N2 confirmed the design change; N5 this record; N6 the plan's path list.
7. Security N5 (a 6b draft left pending after a closure blocks the correction's record until it
   is withdrawn): availability only; the new test shows the withdrawal.

## Review round 2 (fresh read-only subagents, during P2; same instructions)

Independent: no blocker, no should-fix, 4 notes. Security: no blocker, no should-fix, 3 notes.
Both confirmed every round 1 item, the owner answers, the design change, the comment and docs
against the code (the 8e-3 confirm in migration 94, `app.validate_lease_deposit_disposition` in
migration 27), the writers of `app.deposit_disposition_reversals` (the 6b path refused; the
forfeiture reversal, returned-Payment and receipt corrections link first; the Reservation
outcome correction refused for a Deposit with a closed Lease Settlement), and the committed test
changes versus HEAD. No round 3 needed.

Notes handled as text only after P2 (docs and ops files only; no code, migration or test file):
the superseded pre-code sentence in plan item (2) is marked; docs/004 quotes the 8e-1 text;
docs/010 says "closed Settlement rows"; security note 1 (a REPEATABLE READ 6b recorder with an
old snapshot can still record a waiting draft after the closure; no money moves; it blocks the
correction's record until withdrawn) and independent note 4 (a tighter whole-table precondition
in the no-Settlement test) are slice 12 notes (5) and (6). Kept as is: the migration docstring's
"those Settlement rows" (the trigger comment, docs/004, docs/010 and the plan say closed rows).
