# V1-056 sub-slice 10e-2b-3 — a Pet Deposit receipt after closure needs its correction's link — review record

Sub-slice: 10e-2b-3 (owner answer 2 to Q-2026-10-12-89, an approved tightening; answer (a) to
Q-2026-10-12-90). Migration `20261224_150` (one exact-text patch). Base commit: 1fbf8e2. Built on
2026-10-17. Not pushed.

Rule IDs: BR-SETTLE-012, BR-SETTLE-013; DB-DEP-002, DB-SETTLE-005.
Design: ops/V1_056_PLAN.md, "10e-2b-3 pre-code design" and "10e-2b-3 as built".

## Built

- Migration `20261224_150_pet_deposit_receipt_correction_link.py`: an exact-text patch of
  `app.validate_deposit_receipt`: once the Lease's Final Settlement is closed, a Pet Deposit
  receipt of that Lease is refused (P5S01, "A closed Final Settlement changes only through a
  post-settlement correction", the 8e-1 message) unless a correction of that Settlement, confirmed
  in the current transaction, links it (`app.settlement_correction_linked`). No new function,
  table, trigger, constraint or grant.
- Tests: new `test_settlement_pet_receipt_link_migration.py` (3 tests; last in
  `scripts/database-test.sh`).
- Committed tests changed: the 27 head-revision assertions in 15 modules (revision strings only; a
  script checked each file's count).
- Traceability: three entries appended (3,178 to 3,180).
- Docs: docs/004 DB-DEP-002; docs/010; plan.
- Records of the owner answers to the 10e-2d report (Q-2026-10-17-123 (a), the three readings, the
  re-forfeit refusal, the known limit, the 10g-2 placement) ride in this commit.

Read-only search for affected tests (before T1 and P1): every direct `INSERT INTO
app.deposit_receipts` in the backend tests (all before a closure, or Security Deposit receipts),
every Pet call to `seed_historical_deposit_receipt`, `seed_pet_deposit` and the fixtures' Pet
helpers (all before the Settlement closes), every direct call of
`app.write_correction_deposit_receipt` (the writer refuses before any insert), and every test that
reads the body of `app.validate_deposit_receipt` (the migration 122 test compares fixed revisions).
None affected beyond the 27 revision strings.

## Runs

| Run | Result |
|---|---|
| D1 | catalog dump of the receipt check, the receipt writer, the link check and the Payment source check (read only; no `REDACTED` marker) |
| M1 | passed (`20261224_150` head) |
| FF1/FC1/L1/Y1 | passed (formatter first: one file reformatted; no line over 100 characters outside the migration, which keeps `# ruff: noqa: E501`) |
| T1 | 26 passed (the four receipt correction modules that write right Pet receipts, and the new module) |
| U1 | 3847 passed |
| M2 | passed |
| P1 | 2255 passed (the known Starlette deprecation and Pydantic alias warnings) |
| FF2/FC2/L2/Y2 | passed (after the round 1 fixes; formatter first) |
| M3 | passed |
| T2 | 13 passed (the 10e-2d module and the new module) |
| P2 | 2256 passed (the known Starlette deprecation and Pydantic alias warnings); the function's comment text changed after P1 |
| FF3/FC3/L3/Y3 | passed (after the round 2 fixes; formatter first, no file changed) |
| M4 | passed |
| T3 | 3 passed (the new module) |
| U2 | 3847 passed (includes `test_traceability.py`, round 2 should-fix) |
| P3 | 2256 passed (the known Starlette deprecation and Pydantic alias warnings): the full run after the last test and migration change |

No check or run failed, so no correction was counted. Full outputs of every targeted and full run
are in `~/Development/prm-run-logs/v1-056-10e-2b-3-*.txt` (format, lint and type checks are short
and not saved).

## Review round 1 (fresh read-only subagents, during P1; told to write no files at all, scratch files included, and to run no test, script or database command)

Security: 0 blockers, 0 should-fix, six notes. Independent: 0 blockers, 1 should-fix (records), six
notes. Both confirm: the check is fail-closed (`IS NOT TRUE` binds tighter than `AND`; a NULL
Settlement refuses; `final_settlements.lease_id` is unique); only the owner and the definer writer
insert receipts, and the writer links first; a correction of another Settlement does not open the
Deposit; the race claim holds (the confirm runs at READ COMMITTED, locks the Settlement row and
then every Deposit, its digest includes each Deposit's held value, and it writes the closure
last); the patch keeps owner, privileges and settings; the 27 revision strings are the only
committed test changes; no fixture inserts a Pet receipt after a closure.

- Should-fix (independent S1; security N1 the same): designed test (2), a link to a correction of
  this Settlement confirmed in an earlier transaction, never reaches the receipt check: the effect
  trigger `app.validate_settlement_correction_effect` (migration 97) refuses that link first
  (23514, "A correction effect is written with its correction"). The module had tested another
  Lease's correction in the same transaction instead, with no record of the change. Fixed: the
  plan's as-built line names the change; the test now also asserts the 23514 refusal of an
  earlier-transaction link (the security reviewer's set-up below).
- Taken (security N4): the "nothing written" checks were always true because every attempt was
  rolled back; one refused attempt now runs on an autocommit connection, so a passing insert would
  commit and the check is real.
- Taken (security N3, independent N1): the lock wording (migration docstring and function comment,
  docs/004, plan) now names the earlier balance trigger (`app.serialize_deposit_state`) and says
  that a writer at a stricter isolation level fails on the Deposit's serialization guard (40001).
- Taken (independent N6, the known limit of 10e-2d): the claim is right (no case where staff cannot
  finish); with several return-only corrections, one `HELD_VALUE_REFUND` per correction (wording
  fixed in the plan and docs/010); the second half was untested: the reviewer's set-up below is now
  a test in the new module.
- Notes kept: refusal order (the Payment source check and the one-active-receipt check come first,
  so a second Pet receipt from the same Payment after closure gets 23505); the linked Pet path is
  run by the four receipt correction modules (T1 and P1) and, since round 1, by the new module's
  known-limit test; Security
  Deposit receipts after closure have no table rule (safe today: no Security writer after closure;
  10e-2b-4's writer refuses after closure itself, and its service maps P5S01 to a conflict);
  optional race tests (set-ups below, not built: the claim is shown by reading and both reviewers
  confirmed it).

### Round 1 test set-ups (written in full, run rule of 2026-10-13)

- Security N1 (built, in `test_after_closure_a_pet_deposit_receipt_needs_its_own_settlement_s_correction`):
  `case = pet_lease_case(url)`; `closed(case)`; `case["person"] = approver(url)`;
  `case["disposition"] = disposition_of(url, case["security"])`; record the
  `FORFEITURE_REVERSAL` with `reversal_command(case, settlement_refund(case, "security", 10_000))`
  and confirm it (committed); `[correction] = rows(url, "SELECT id FROM app.settlement_corrections
  WHERE final_settlement_id=%s", case["settlement"])`; in a new connection
  `pet_receipt(c, case, 1_000, correction[0]) == ("23514", "A correction effect is written with its
  correction")`, rolled back; `receipts(url, case["pet"]) == []`.
- Security N2 (optional, not built): the receipt waits for the closing confirm.
  `case = pet_lease_case(url)`; `draft = record_settlement(case, ())`; a `closer` connection runs
  `SELECT app.confirm_final_settlement_draft(prop, human, draft_id, 'financial.approve')` and holds
  its locks without committing; a thread opens a connection with `application_name`
  "pet-receipt-race" and calls `pet_receipt` (rolled back); poll as the admin URL (autocommit,
  10 s) until `pg_stat_activity` shows that application waiting on a Lock with the closer's pid in
  `pg_blocking_pids`; commit the closer; the thread's result is `("P5S01", CLOSED)`; no receipt.
  The reverse order: a holder connection seeds a Payment and inserts a Pet receipt without
  committing; a thread runs the confirm SQL (rolled back if it ever succeeds); once the thread is
  blocked, commit the holder; the thread gets P5S02 and `closed_at IS NULL` still holds.
- Independent N6 (built, `test_staff_finish_a_forfeited_right_receipt_after_a_held_value_refund_empties_the_deposit`):
  `case = payback_ground_case(url)` (after closure the Pet Deposit holds 0, count 0, path
  `NOTHING_HELD`, ground BR-DEP-022, forfeiture `NONE`; the Security Deposit refunded 10,000 by
  `FORFEITURE_REVERSAL`, `case["refund"]`); the Settlement's 3,000 Pet Refund is the Pet Deposit's
  Refund without a review; `earlier = return_only(case, that_refund, 3_000)` (held 3,000, count
  3,000, `DL_032`); `record_correction(case, 5_000, 5_000)` is refused (55000, "A forfeiture in a
  receipt correction takes only the new receipt's money") with `counts(url)` unchanged;
  `confirm_held(case, record_held(case, held_command(case, earlier, settlement_refund(case, "pet",
  3_000))))` (held 0, count 0; no open debt, so all 3,000 is refunded); then
  `confirm(case, record_correction(case, 5_000, 5_000))` passes and forfeits the whole 5,000 on
  BR-DEP-022, linked to the correction.
- Independent S1 optional variant (covered by the N1 set-up): commit a `FORFEITURE_REVERSAL`, then
  in a new transaction `SELECT app.link_settlement_correction_effect(<that correction>,
  'deposit_receipt_id', <new uuid>)` is refused with 23514 and that message.

## Review round 2 (fresh read-only subagents, during P2; told to write no files at all, scratch files included, and to run no test, script or database command)

Security: 0 blockers, 0 should-fix, four notes. Independent: 0 blockers, 1 should-fix (a run),
five notes. Both confirm every round 1 fix as the record says, the migration and its comment text,
the tests' numbers and that nothing is committed by accident (the autocommit helper's check is
real; the known-limit test's refused service call is a committing call, so its `counts` check is
real), the 27 revision strings as the only committed test change, and the records.

Fixed under the round-3 rule (a run, tests and text only; no code logic change):
- Should-fix (independent S1): `test_traceability.py` (a unit test, not in the PostgreSQL suite)
  had not run since the third traceability entry: run in U2 (passed).
- Security note 1 (taken): the test helper returned `(None, None)` for a client-side error, the
  same value as a pass; it now re-raises an error without a SQLSTATE.
- Independent N4 (taken, stricter assertions in the new test): the held-value Refund's 3,000 from
  the Pet Deposit, the forfeiture not reversed, and the right 5,000 Pet receipt linked to the
  correction.
- Text: the migration docstring and the function comment (security note 2: "holds the lock first
  and commits", REPEATABLE READ or SERIALIZABLE, the Payment source trigger in the order),
  docs/004 (line wraps, the same wording), docs/010 (only services that map P5S01 read it as a
  conflict), the plan (a "carried into 10e-2b-4" line: the writer's own after-closure refusal for
  both Deposit types, the P5S01 mapping in the Deposit service, READ COMMITTED, and 10e-2d security
  note 7), this record (independent N1 and N2).
- Notes kept: the 40001 claim for a stricter isolation level is shown by reading (security note 3,
  optional test below, not built); a future role given INSERT on the receipts without EXECUTE on
  the link check would get 42501 on every Pet receipt, as the Security branch since migration 122
  (security note 4; no such role exists); the savepoint passes prove only the BEFORE triggers,
  enough because this migration changes nothing deferred.

### Round 2 test set-up (written in full, run rule of 2026-10-13)

- Security note 3 (optional, not built): `case = pet_lease_case(url)`; `draft =
  record_settlement(case, ())`; a `writer` connection at REPEATABLE READ reads `closed_at` of the
  Settlement (None; its snapshot is taken); `confirm_settlement(case, draft)` commits the closure
  elsewhere; the writer seeds a Payment (if that raises 40001 because the confirm touched a
  Customer-level guard, seed it as the first statement instead) and inserts a Pet receipt:
  `psycopg.errors.SerializationFailure` with `app.serialize_deposit_state` in the error context;
  rolled back; no receipt.

## Review round 3 (fresh read-only subagents, after U2 and during P3; told to write no files at all, scratch files included, and to run no test, script or database command)

Independent: clean (0 blockers, 0 should-fix; three text notes). Security: clean (0 blockers, 0
should-fix; one cosmetic note). Both confirm every round 2 fix (the helper re-raise, the stricter
assertions match the data shapes they read, the wording), the migration, that no committed test
got weaker, the records, and no path that writes a Pet Deposit receipt after closure without the
right link. The independent reviewer's single `python3 -c` only parsed ops/traceability.json and
wrote nothing.

Notes taken as text (no code, migration, test or fixture change): P3 added to the Runs table; the
docs/010 build bullet names rounds 2 and 3; the docs/004 line break after "changes only" and this
record's ragged wrap are cosmetic (the rendered text is the same) and stay.

Status: committed (see git log). Not pushed.
