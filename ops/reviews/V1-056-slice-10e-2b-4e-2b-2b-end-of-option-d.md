# V1-056 sub-slice 10e-2b-4e-2b-2b — the end of option (d) — review record

Sub-slice: 10e-2b-4e-2b-2b (owner answer to Q-2026-10-18-127: option (a), and option (d) only
until (a) is built). Migration `20270104_161` (one exact-text patch of
`app.record_lease_deposit_receipt`, one replacement). Base commit: 7a24347. Built on 2026-10-18
and 2026-10-19 in one fresh session. Not pushed.

## Built

- Migration `20270104_161_deposit_receipt_refund_out_allowed.py`: the option (d) refusal of
  sub-slice 10e-2b-4d (55000, "The Deposit has a Refund that is not fully returned; this receipt
  is not recorded here") is removed from the receipt writer; a comment names its end. A relaxing
  change; no other function, table, trigger, constraint or grant changes.
- Committed tests changed (owner answer ends (d); standing rules): two renamed tests in
  `test_deposit_receipt_leftover_migration.py`, one line of
  `test_payment_return_shared_deposit_migration.py::test_two_recipients_pay_the_shortfall_newest_refund_first`
  (a rolled-back writer call, new helper `receipt_rolled_back`), docstrings; 27 head-revision
  strings.
- New module `test_deposit_receipt_refund_out_migration.py` (six tests).
- Docs: docs/004 (DB-DEP-002, DB-REFUND-002 example, two DB-DEP-007 pointers), docs/010, plan
  (pre-code design, Q-127 line, slice 11 receipt-screen note, slice 12 known limit), questions
  (new Q-2026-10-19-137); traceability (two renamed entries and two notes changed in place after
  entry 1,598; six entries appended).

## Runs

| Run | Result |
|---|---|
| D1 | catalog dump of the writer and `app.deposit_has_unresolved_refund` (no `REDACTED` marker), saved in `~/Development/prm-run-logs/v1-056-10e-2b-4e-2b-2b-D1.txt` |
| FF1/FC1/L1/Y1 | passed (long-line search and import sort first; formatter changed nothing) |
| M1 | passed |
| T1 | 26 passed |
| U1 | 3866 passed |
| P1 | 2351 passed (the deprecation warning and the known pydantic alias warning) |
| FF2/FC2/L2/Y2 | passed (after the round 1 fixes; import sort first) |
| T2 | FAILED: 1 failed, 27 passed: the after-closure test's new full uses-list assertion (round 1 independent note 2 expected the review Refund listed with undo 0; the plan stops at the shortfall and lists only the application) (cause A, a test expectation, correction 1 of 2) |
| FF3/FC3/L3/Y3 | passed (after the fix: the full list is only the application) |
| T3 | 28 passed (the passing rerun after T2) |
| U2 | 3866 passed |
| M2 | passed |
| P2 | 2353 passed (the same two warnings) |
| FF4/FC4/L4/Y4 | passed (after the round 2 fixes) |
| T4 | 7 passed (the new module, the only test file changed since T3) |
| U3 | 3866 passed (before round 3) |
| M3 | passed |
| P3 | 2354 passed (the same two warnings; before round 3) |
| FF5/FC5/L5/Y5 | passed (after the round 3 fixes) |
| T5 | 7 passed (the new assertion holds) |
| U4 | 3866 passed |
| M4 | passed |
| P4 | 2354 passed (the same two warnings; the last full run before the commit) |

Full outputs in `~/Development/prm-run-logs/v1-056-10e-2b-4e-2b-2b-*.txt`, one file per attempt.

## Review round 1 (fresh read-only subagents, during P1; told to write no files at all, scratch files included, and to run no test, script or database command)

Independent: no blocker, 3 should-fix (two tests, one text), 6 notes. Security: no blocker, 1
should-fix, 5 notes. Both confirmed that (a) is built in all three paths at HEAD, that the
migration's before-text equals the text migration 156 inserted and matches once, and the
implementer's reading (1): every state reachable without (d) is also reachable with the receipts
first (the receipt bound counts active receipts, a Refund is at most what the Deposit holds at its
time, the pay-back count reads no receipt events, and the planners read the current held value and
order only the uses), so ending (d) creates no stuck bounced Payment and no new refused case. The
stale-draft behaviour holds (the return's source digest carries the Deposit's held value and
latest time; the writer dates the receipt after the latest balance event).

Fixed (tests, text and a known limit with its owner question):

1. Independent should-fix 1 (test): the renamed test lost its HEAD end check, which is still true
   under (a). Kept: after C's receipt, verified returns of 4,000 (the Deposit holds 14,000, the
   Refund still out) and 6,000 (the Deposit holds 20,000, written (2,2,2), the Refund resolved).
2. Independent should-fix 2 (test): the receipt correction after closure on the same set-up.
   Set-up (the reviewer's): `refund_then_receipt_case`; the `DEPOSIT_RECEIPT_CORRECTION` of A's
   receipt with no right receipt: one plan entry, shortfall 10,000, give-back 10,000, the only use
   with an undo the Settlement's 10,000 application (undo 10,000, kept 0), no recovery; after the
   confirm one application reversal, no new application or receipt, the Pet Deposit holds 0, the
   pet line owes 12,500, the Refund's net stays 10,000, C's receipt stays, A stays RECEIVED with
   10,000 available, the Settlement row is unchanged and the ledger reconciles.
3. Independent should-fix 3 (text): the plan's Q-127 known-limit line gains a "Done" sentence
   (two recipients, both corrections, the end of (d), the 4e-2a rename of the after-closure
   test).
4. Security should-fix 1 (known limit, test, owner question): with (d) gone one `payments.allocate`
   holder can record a Payment into a Pet Deposit whose Refund is out, and before closure no
   receipt reversal undoes it until the Refund is returned in full (the receipt reversal check,
   55000, "Deposit receipt has active dependent financial history"). Named in docs/004 DB-DEP-002,
   the slice 11 receipt-screen note and the slice 12 list; Q-2026-10-19-137 asks the owner
   (recommendation (a): a small relaxing sub-slice that lets the reversal pass for a receipt newer
   than every unresolved Refund while the held history stays at 0 or more). Pinning test (the
   reviewer's set-up): `pet_case`; A 10,000; a 10,000 Pet Refund-review Refund; C 10,000; the
   confirm of C's receipt reversal draft refused (55000, that message), nothing written, the
   Deposit holds 10,000, C has 0 available; after the Refund's full verified return (holds 20,000)
   the draft is withdrawn, recorded again and confirmed: the Deposit holds 10,000 and C has 10,000.
5. Notes taken: the waiting-receipt test asserts the receipt is dated after the Refund and the
   Refund is still out (independent note 1); the after-closure test asserts the Security Deposit
   at 0, the other line at 2,500 and the full uses list (independent note 2; the note said the
   list also holds the review Refund with undo 0, but T2 showed the plan stops at the shortfall,
   so the full list is only the application); this record (note 3); two docstring rewraps (note
   4). Not taken, for the
   owner or slice 12: the optional race test of a receipt and a return confirm in both lock orders,
   C's bounce after closure after A's return charged nothing, and the two-recipient chain on the
   real path (security note 5 (a) to (c); set-ups: (a) `pet_case`, A 10,000, a 10,000 Refund, A's
   draft plans 10,000; the confirm uncommitted while C's receipt waits (the receipt is recorded
   after it, recoveries [10,000], net 0, the Deposit holds 10,000) or the receipt uncommitted while
   the confirm waits (stale); (b) test 1 up to A's return, terminate with no ground, settle without
   a Pet step and close: C's `RETURNED_PAYMENT` correction recovers 10,000 as a
   `CLOSED_SETTLEMENT_LEASE` charge; (c) in the two-recipient set-up record C's 5,000 for real: A's
   return charges nobody, B's recovers 7,000 from the Signer's Refund and 3,000 from the Primary
   Tenant's, C's the last 5,000); the two-recipient shortfall after closure has no test of its own
   (independent note 6, pre-existing).

## Review round 2 (fresh read-only subagents, during P2; same instructions)

Independent: no blocker, 4 should-fix (all text), 4 notes. Security: no blocker, 1 should-fix
(text), 4 notes. Both confirmed every round 1 fix, the migration (before-text equal to what 156
inserted; no later migration touches the writer), the committed test diff against HEAD (only the
(d) refusals become acceptances, plus exactly 27 revision strings; nothing weaker), traceability
(the first 1,598 entries identical to HEAD; four entries changed in place, six appended) and the
new tests (to the cent, real path, dates from the database). Security: no route reaches the
receipt writer yet (`PostgresDepositService.record_receipt` has no HTTP caller), and the
rolled-back calls roll back as they say. Fixed under the round-3 rule (text, and test notes):

1. Independent should-fix 1 (text): Q-137's "who pays does not change" was false for option (a)
   as worded. Counterexample (the reviewer's): `pet_case`; A 10,000; a 10,000 Pet Refund-review
   Refund (holds 0); C 10,000 (holds 10,000); A's return charges nothing (holds 0); D 10,000
   (holds 10,000); option (a) would let C's reversal pass (the held history never below 0), ending
   with D's money paying the Refund and nobody charged. Option (a) is narrowed: no return or
   correction of another Payment of that Deposit confirmed after the receipt; the strict time
   comparison with each unresolved Refund's processing time (security note 2) is named.
2. Security should-fix 1 (text): the known limit understated its effects: the Rent stays owed, so
   the DL-054 Warning Notice and Serious Nonpayment Default can follow (a termination on it keeps
   the Security Deposit, BR-LEASE-028); after a pet noncompliance termination (BR-DEP-022) the
   money is forfeited by a draft instead of refunded, and after closure the receipt correction
   needs a forfeiture reversal correction first; the slice 11 receipt route and screen wait for
   the owner's answer to Q-137. Updated in Q-137 (title too), docs/004 DB-DEP-002, docs/010, the
   plan's slice 12 line and slice 11 note. Security note 1 (the ways out, among them a second Pet
   Refund-review Refund, and the warning never to record a return that did not happen) and
   independent note 3 (only a Payment that names no owed target can be recorded there) are in
   Q-137 and the docs.
3. Independent should-fix 2 (text): the plan's as-built line added (the design said the return
   steps go and listed four tests).
4. Independent should-fix 3 (text): this record (note 5 above, the runs table).
5. Independent should-fix 4 (text): the slice 11 receipt-route note now marks the Refund-out
   refusal "(until 10e-2b-4e-2b-2b)".
6. Notes taken (tests): the receipt-correction test asserts the full uses list and
   `payback_first` (independent note 1) and is parametrized for C's receipt too (independent note
   4: the way out the known limit names; same set-up, `receipt_by(url, pet, second)`: the same
   plan, the Deposit holds 0, A's receipt stays, C has 10,000 available, both Payments RECEIVED);
   the known-limit test also refuses after a partial verified return of 4,000 (holds 14,000) and
   its docstring says when the draft is withdrawn (independent note 2). Notes not taken: security
   notes 2 to 4 confirm option (a) narrowed is safe, list the remaining one-person paths (the
   known limit on purpose, repeatable staling of a waiting return draft, which debt the money pays
   under 4e-1 reading (4)) and the clean checks.

## Review round 3 (fresh read-only subagents, during P3; same instructions)

Security: clean (no blocker, no should-fix; 3 notes). It confirmed the round 2 text against the
rules (BR-DEP-022, BR-DEP-026, DL-054, BR-LEASE-028), that no route reaches the writer and the
one-call receipt reversal route still answers with the draft rule, that option (a) as narrowed is
safe (Refund and receipt times are strictly ordered under the Deposit lock), and the tests, the
migration and traceability (first 1,598 entries identical; four changed in place, six appended).
Independent: no blocker, one should-fix (text), 6 notes; it confirmed every round 2 fix, the
cent figures of both changed tests, the Q-137 counterexample and the facts of the effects text.

Fixed under the round-3 text rule of 2026-10-16 (text fixes and one new assertion in a test
already built and green; no code, migration or fixture change; no round 4):

1. Independent should-fix 1 (text): the slice 11 note and Q-137 read as if any answer unblocks
   the receipt route and as if the screen warning held under (a). Now: the route and screen wait
   for the owner's answer and, if it is (a), until (a) is built; the warning follows the answer.
2. Notes taken (text): the second Pet Refund-review Refund named among the ways out in docs/004
   and the plan's slice 12 line (independent note 2); docs/004 says the money is forfeited by a
   Lease Deposit forfeiture draft that the Settlement requires (independent note 3) and that the
   `FORFEITURE_REVERSAL` correction itself runs the DL-032 step, an untested combined path
   (security note 2); the traceability note of the parametrized test (independent note 4);
   docs/010 names the `FORFEITURE_REVERSAL` step and the test with two cases (security note 3,
   independent note 6); Q-137 option (a) asks the build to state its second condition by its
   effect (the held value stayed at or above the receipt's amount at every balance event after
   it), which also covers a verified-return reversal that relied on the receipt (security note 1;
   set-up: A 10,000; a 10,000 Refund verified returned in full; C 10,000; A's receipt reversed;
   the verified return reversed; D 10,000).
3. New assertion (independent note 5): after the second refusal of the known-limit test, C has 0
   available; the docstring says the second draft is withdrawn too.

