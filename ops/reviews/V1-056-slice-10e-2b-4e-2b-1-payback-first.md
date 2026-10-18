# V1-056 sub-slice 10e-2b-4e-2b-1 — a shared Deposit with pay-back money gives back from its forfeiture first — review record

Sub-slice: 10e-2b-4e-2b-1 (owner answer (a) to Q-2026-10-18-135; owner answer 2 to the
10e-2b-4e-2a report: a test of newest first for a Pet Refund-review Refund paid before closure).
Migration `20270102_159` (exact-text patches of two functions). Base commit: 4479070. Built on
2026-10-18 in a fresh session. Not pushed. Sub-slice 10e-2b-4e-2b-2 (the receipt correction of a
shared Deposit and the end of option (d)) follows.

## Built

- Migration `20270102_159_settlement_returned_payment_payback_first.py`: patches of
  `app.settlement_returned_payment_shared` (each shared Deposit reads its active forfeitures, both
  pay-back counts and `payback_first`; `give_back`; the forfeitures of a `payback_first` Deposit
  first; `shared_deposits` gains `give_back_usd_cents`, `payback_first`, `payback_usd_cents`) and
  `app.assert_settlement_returned_payment_allowed` (the ends check: one entry per shared Deposit,
  its total recomputed from the live state; the B1 end-held branch reads the plan's total).
- Tests: new module `test_settlement_returned_payment_payback_first_migration.py` (five tests);
  the B1 test of the 10e-2a module renamed and parametrized (docs/010); 27 head-revision strings.
- Docs: docs/004 (DB-DEP-007 note), docs/010, plan (split, pre-code design, as-built line, slice
  12 item), the owner's answers to the 4e-2a report recorded (docs/010, questions); traceability
  appended, the renamed entry updated.

## Runs

| Run | Result |
|---|---|
| D1 | catalog dump (no `REDACTED` markers), saved in `~/Development/prm-run-logs/v1-056-10e-2b-4e-2b-1-D1.txt` |
| M1 | passed |
| FF1/FC1/L1/Y1 | passed (long-line search and import order first: two lines wrapped; formatter no change) |
| T1 | 48 passed |
| U1 | 3866 passed |
| M2 | passed |
| P1 | 2332 passed (two warnings: the deprecation warning and the known pydantic alias warning of the slice 12 list) |
| FF2/FC2/L2/Y2 | passed (after the round 1 fixes; long lines wrapped first; formatter no change) |
| M3 | passed |
| T2 | 50 passed |
| U2 | 3866 passed |
| P2 | 2334 passed (one warning: the deprecation warning) |
| FF3/FC3/L3/Y3 | passed (after the round 2 fixes; long lines searched first; formatter no change) |
| M4 | passed |
| T3 | 51 passed |
| U3 | 3866 passed (before round 3) |
| P3 | 2335 passed (one warning: the deprecation warning; before round 3) |
| FF4/FC4/L4/Y4 | passed (after the round 3 text and assertion fixes; formatter no change) |
| T4 | 10 passed (the two changed test modules: the last targeted run) |
| U4 | 3866 passed |
| M5 | passed |
| P4 | 2335 passed (three warnings: the deprecation warning and the known pydantic alias warning twice; the full run after the last test change) |

Full outputs in `~/Development/prm-run-logs/v1-056-10e-2b-4e-2b-1-*.txt`, one file per attempt
(the migration checks and the catalog dump included). No check or run failed so far.

## Review round 1 (fresh read-only subagents, during P1; told to write no files at all, scratch files included, and to run no test, script or database command)

Independent: no blocker, 4 should-fix, 5 notes. Security: no blocker, 2 should-fix, 3 notes. Both
worked the owner's example and the round 2 case to the cent (the forfeiture keeps 1,000, the
table's pay-back limit holds at the kept write, the held history never goes negative, the check
after the writes passes), and both found every plan HEAD accepted unchanged.

1. Both, should-fix (fixed, fail closed): the ends check accepted any `give_back_usd_cents` not
   below the shortfall that matched its own uses, for every shared Deposit; `bool_and` skipped a
   NULL entry beside a valid one; a duplicated entry passed. Fix: exactly one entry per shared
   Deposit (`count(*)=1`), `bool_and(COALESCE(...,false))`, the total recomputed from the live
   state (`CASE WHEN plain AND active forfeitures > 0 AND count_as(d,NULL,0,true) > 0 THEN
   GREATEST(shortfall, LEAST(forfeited, GREATEST(receipt - held + count_as(d,NULL,0,false), 0)))
   ELSE shortfall END`, the held value and the forfeitures read from the database), and the
   shortfall checked against the live held value. Tests (hand-built, in the review-Refund test):
   15,000 matched by its own uses, a duplicated entry, an entry with no total beside a valid one,
   each refused with the ends message (the reviewers' example).
2. Both, should-fix (tests): the B1 end-held branch had no refusal test. With the new ends check
   a plain Deposit's forfeiture-only plan of 1,000 is refused by the ends check (its total is not
   the rule's 5,000); with the Deposit marked not plain (its total is then its 1,000 shortfall)
   the end-held branch refuses it (55000, the pay-back message): both asserted in the renamed
   test's `returned_first` case, with a plan whose give-backs miss its total (4,999).
3. Both, should-fix (tests; the reviewers' set-ups): option (a)'s second clause on the real path:
   `test_a_forfeiture_smaller_than_the_shortfall_gives_back_whole_then_the_refund` (A 5,000,
   B 1,000, pay-back 4,000, forfeiture 2,000, Settlement Refund 4,000; plan
   `[FORFEITURE 2,000/2,000/0, REFUND 4,000/3,000/1,000]`; 3,000 charged to the Customer on the
   Lease, net 1,000, no forfeiture active, the Deposit holds 0); security: two forfeitures,
   `test_two_forfeitures_give_back_newest_first_and_keep_part_of_the_older` (A 5,000, B 5,000, two
   one-call owner dispositions of 3,000; plan `[newer 3,000/3,000/0, older 3,000/2,000/1,000]`;
   kept 1,000 forfeited again; nobody charged).
4. Independent should-fix 4 (text): docs/004 DB-DEP-007 note, the docs/010 as-built and updated
   tests entries and the plan's as-built line written.
5. Notes taken: the B1 claim reworded to "no plan of a plain Deposit reaches it" (both); exact
   forfeiture assertions (the original 6,000 reversed, the new 1,000 the only active one) and the
   Settlement row unchanged in the renamed test (independent 6); the report names that
   `payback_first` also covers a review Refund still to recover with no returned money (only the
   order changes; independent 8) and that reading (2) gives back more than the shortfall
   (independent 9). Security note 3 (a kept forfeiture uses the Lease's current kept rule and a
   NULL rule gives the receipt correction's message; pre-existing, fails closed) is a slice 12
   item. Independent note 7 (the committed test is weaker only where the answer turns refusals
   into acceptances, and in the end-held branch, now covered by item 2) needs no change.

## Review round 2 (fresh read-only subagents, during P2; same instructions)

Both: no blocker; every round 1 fix confirmed (the check's inputs and formula equal the
planner's; no correct plan is refused at the confirm, which recomputes the source and calls the
check before any write; both real-path tests right to the cent). Independent: 1 should-fix, 6
notes. Security: 1 should-fix, 4 notes. Fixed under the round-3 rule (tests, text and fail-closed
refusals):

1. Security should-fix 1 and independent note 2 (fail closed): the check still trusted the
   plan's `receipt_usd_cents`, `held_usd_cents` and `plain`, and GREATEST and LEAST skip a NULL.
   The reviewer's set-ups, both accepted before the fix: (a) the B1 case with the pet entry's
   shortfall 0, no `receipt_usd_cents`, total 0 and no uses; (b) the round 2 case's forfeiture-only
   plan (total 1,000, undo 1,000, kept 5,000) with `plain` false and `held_usd_cents` 8,000. Fix:
   the returned Payment's active receipt in the Deposit is read live (`p_source->'payment'->>'id'`)
   and must be present and equal the entry's; the entry's held value must equal the live one; a
   Deposit that is not plain must give back nothing (the planner lists no uses for it); the live
   receipt is used in the rule. Both set-ups, a source with no plan entry (security note 5), a
   shortfall that is not the live one (independent note 1) and a receipt raised with the
   shortfall and the total (independent note 2) are refused in the tests (55000, the ends
   message). With the receipt and the held value live, no source the database builds reaches the
   B1 end-held branch (a plain Deposit's total keeps the end held at or above the count while a
   forfeiture stays; a not-plain Deposit is refused earlier by the Reservation outcome refusal);
   the round 1 test of that branch (the not-plain plan with uses) now gets the ends refusal, and
   the branch stays as defence in depth. (Corrected in review round 3: a hand-built source can
   still reach it, below.)
2. Independent should-fix 1 (test; its set-up): the `LEAST(forfeited, ...)` cap had no test:
   `test_the_forfeiture_gives_back_at_most_what_it_keeps` (A 5,000, B 2,000, forfeiture 3,000, the
   Settlement Refund of 4,000 returned by a return-only correction; the rule asks 5,000, the
   forfeiture gives back its 3,000 in full, nobody is charged, the Deposit ends holding 2,000).
3. Independent note 4 (fail closed): a plan entry for a Deposit that is not a shared Deposit of
   the source is refused (tested with an entry for the Security Deposit).
4. Notes taken: the `blank` case (refused by the duplicate count, not by NULL-safety) is dropped;
   the NULL total stays tested as a single entry (independent note 3); docs/004 says only drafts
   with a shared Deposit go stale and that the Deposit holds at least the count while a
   forfeiture stays, and the plan's 4e-2a known limit says Q-135 is answered and built
   (independent note 5); the pay-back count of 3,000 against a held value of 0 after the
   forfeiture-smaller test is asserted (security note 2); P2 recorded (independent note 6). Not
   taken: B1 reading the live forfeitures instead of the source's list (security, optional); the
   prepare-time snapshot gap of the source and the check (security note 4: a one-off 55000,
   fails closed, availability only).

## Review round 3 (fresh read-only subagents, during P3; same instructions)

Security: clean (no blocker, no should-fix; five notes). Independent: no blocker, one should-fix
(text, with optional assertions in a green test), four notes. Both confirmed every round 2 fix,
the SQL, that every planner plan still passes (record and confirm), and the money to the cent in
every real-path test. Fixed under the round-3 text rule of 2026-10-16, no round 4 (no code,
migration or fixture change; if a new assertion had failed, the work would stop):

1. Independent should-fix 1 (text): "no source that passes the check reaches the B1 end-held
   branch" was wrong for hand-built sources: B1 reads the source's `forfeitures` list, while the
   total reads the live forfeitures. The reviewer's set-up: in the cap test's state (receipt
   5,000, held 4,000, pay-back count 4,000, forfeiture 3,000, total 3,000), add a pet forfeiture
   of 1,000 the database does not hold to `source["forfeitures"]`: the total passes and the
   end-held branch refuses (4,000 > 4,000 + 3,000 - 5,000). Reworded in docs/004, docs/010, the
   plan, this record and the shared test's comment: no source the database builds reaches the
   branch; a hand-built source can, and is refused. Three new assertions in the green
   `test_the_forfeiture_gives_back_at_most_what_it_keeps`: that source is refused with the
   pay-back message; with `held_usd_cents` 6,000 or `receipt_usd_cents` 3,000 (which would hide
   it from the branch) it is refused by the total first (these isolate the held and receipt
   equality clauses, which no test isolated before).
2. Notes taken: this record's test count (five); docs/004 names the entry's own `plain` flag in
   the rule (independent note 3). Not taken: the migration docstring describes only the round 1
   record check (both reviewers' note; the round 2 additions are in its SQL comments, docs/004 and
   this record; a migration change is outside the round-3 text rule); a per-use check of each
   plan entry (undo plus kept equal to the amount, the amount equal to the live record,
   forfeitures first; security note 1; not reachable, the confirm rebuilds the plan and checks the
   digest), slice 12 list; the entry's `plain` flag is not recomputed (security note 2: a
   not-plain Deposit is refused earlier by the Reservation outcome refusal); the 90 bytes per
   entry against the 16,000-byte draft limit (security note 4). Independent note 4 (the shared
   module's hand-built checks needed no change) needs nothing.
