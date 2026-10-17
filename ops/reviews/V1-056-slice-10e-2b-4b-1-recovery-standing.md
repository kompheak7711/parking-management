# V1-056 sub-slice 10e-2b-4b-1 — a recovery counts as returned money only while its charge stands — review record

Sub-slice: 10e-2b-4b-1 (owner answer (a) to Q-2026-10-17-125; owner answer 5 to the 10e-2b-4a
report). Migration `20261226_152` (one new internal function, one exact-text patch of
`app.lease_deposit_payback_count_as`, two replacements). Base commit: dc30530. Built on 2026-10-17.
Not pushed.

Rule IDs: BR-SETTLE-013, BR-DEP-022, DL-032, DL-053, BR-INV-044; DB-DEP-004, DB-REFUND-002.
Design: ops/V1_056_PLAN.md, "10e-2b-4b-1 pre-code design" and "10e-2b-4b-1 as built".

## Built

- Migration `20261226_152_pet_payback_recovery_standing.py`: `app.refund_recovery_standing_at`
  (no grant): what still stands of a recovery's charge at a time; the count's Pet Refund-review
  part counts each recovery at its own time by what stands now, and another Refund's payout is
  undone only as far as its recovery charge stands now (one rule, the answer's "alike").
- Tests: new module `test_pet_payback_recovery_standing_migration.py` (seven tests, last in
  `scripts/database-test.sh`).
- Committed tests changed: the 10e-2b-4a tie test's set-up only (found by T1; its hand-built
  charge-back named an obligation that does not exist, which now stands at 0; it now names a real
  issued 3,000 charge; every assertion unchanged); the 27 head-revision assertions in 15 modules
  (revision strings only; a script checked each file's count).
- Traceability: the tie test's note updated (entry 3,183, after the first 1,598), seven entries
  appended (3,184 to 3,190).
- Docs: docs/004 (DB-DEP-004 pointer, DB-DEP-005 bullet), docs/010, plan, questions
  (Q-2026-10-17-126 from review round 1).

Read-only search for affected tests (before T1 and P1): every committed database test that adjusts,
reduces or VOIDs a recovery charge and then reads the count, the pay-back value, the Deposit path or
a forfeiture: none (`test_payment_return_migration.py` only imports a helper;
`test_settlement_correction.py` is a unit test). The hand-built tie test was missed by that search
(it names no real charge) and was found by T1.

## Runs

| Run | Result |
|---|---|
| D1 | catalog dump for the pre-code design (read only; no `REDACTED` marker) |
| M1 | passed (`20261226_152` head) |
| FF1/FC1 | passed (formatter first; long-line search first, none) |
| L1 | FAILED: `I001 Import block is un-sorted or un-formatted` in the new test module. Lint correction 1 of 2 (cause: import order); fixed with `ruff check --select I001 --fix` on that file |
| FF2/FC2/L2/Y1 | passed |
| T1 | FAILED: 33 passed, 1 failed: `test_a_charge_back_at_the_instant_of_a_return_reversal_counts_alike_in_either_id_order` (`assert 0 == 3000`). Test correction 1 of 2 (cause A: the committed hand-built charge-back names no real charge) |
| FF3/FC3/L3/Y2 | passed (long-line search first, none) |
| T2 | 34 passed (the new module, the 10e-2d module and the three Pet pay-back modules) |
| U1 | 3847 passed |
| M2 | passed |
| P1 | 2264 passed (the known Starlette deprecation and Pydantic alias warnings) |
| FF4/FC4 | passed (after the round 1 fixes; long-line search first: two lines found and rewrapped before the lint) |
| L4 | FAILED: `I001` in the new test module (the new imports). Lint correction 2 of 2 (same cause: import order); fixed the same way |
| FF5/FC5/L5/Y3 | passed |
| T3 | 36 passed (the same five modules) |
| U2 | 3847 passed (includes `test_traceability.py`) |
| M3 | passed (after the design change) |
| P2 | 2266 passed (the known Starlette deprecation warning) |
| FF6/FC6/L6/Y4 | passed (after the round 2 fixes; long-line search first: two lines rewrapped before the lint; the new imports sorted by hand before the lint, so the import-order cause had no third failure) |
| T4 | 21 passed (the new module and the 10e-2d module) |
| U3 | 3847 passed (includes `test_traceability.py` on the final manifest) |
| M4 | passed |
| P3 | 2267 passed (the known Starlette deprecation and Pydantic alias warnings): the full run after the last test change, before round 3 |
| UT1 | `test_traceability.py` passed (after the round 3 text fixes in docs; no code, migration or test file changed after P3) |

Full outputs of every targeted and full run, each attempt in its own file, are in
`~/Development/prm-run-logs/v1-056-10e-2b-4b-1-*.txt` (format, lint and type checks are short and
not saved).

## Review round 1 (fresh read-only subagents, during P1; told to write no files at all, scratch files included, and to run no test, script or database command)

Independent: 1 blocker, 5 should-fix, notes. Security: 2 blockers, 2 should-fix, notes.

- Blocker (both, independent B1 and security B1, fixed by a design change): the first build placed
  each change of a recovery charge at its own time. The count floors at 0, so a forgiveness after a
  payout was swallowed while a later restoration was added in full (the reviewers' real path: the
  bc set-up, a `CHARGE_REDUCTION` of the review recovery charge, then the 10f-2 reversal of its
  Adjustment gave 2,000 instead of 0); and a forgiveness after payouts took money that came back
  later (security: 15,000 recovery, a 10,000 Pet Refund-review Refund, 3,000 of it back, a credit of
  the whole charge gave 0 instead of 3,000). Fixed as the security reviewer proposed: the recovery
  counts at its own time by what stands now, one rule with the 10e-2d payout undo (the answer's
  "alike"); `app.refund_recovery_standing_changes` is not built. Both set-ups are tests now.
- Security B2 (a missing rule, asked): a restoration after a forfeiture that the lower count
  allowed is not refused, so the Customer owes the money again while the Property keeps the
  forfeiture: Q-2026-10-17-126 (recommendation (a)); a known limit in the slice 12 list.
- Security S1 (asked with B2): a recovery charge with no Lease can be forgiven by one staff member
  after closure, which lowers the closed Lease's Pet count; harmless alone, a loss path with B2.
- Independent S1 (fixed): the migration docstring and docs no longer claim "tightening only".
- Independent S2 (covered): the two blocker tests tell the old placement from the new rule.
- Independent S3 (fixed, tests): a draft recorded before a forgiveness, and one recorded before a
  restoration (the direction that would take the Customer's money), are stale at their confirm
  (P5S02) and write nothing.
- Independent S4 (fixed, test): test (1) also reduces part of the Settlement Refund's recovery
  charge (4,000, then 2,500, then 500).
- Independent S5 and security S2 (partly): a paid recovery charge, a DEBIT-Adjustment restoration
  and a `REFUND` correction of a recovery charge are not tested; the security reviewer traced the
  `REFUND` case and found the count right (the application reversal drops out, the credit lowers
  what stands, the released Refund counts as a payout). Put to round 2.
- Notes taken: test (3) asserts the forgiven review recovery is not charged back again (one
  recovery row); the DEBIT-first reading of `LEAST` named in the docstring and docs/004; this
  record (independent N8).
- Notes kept: the receipt-correction and forfeiture confirms take no lock shared with
  `invoices.adjust`, a VOID or a 10f-1 reversal of a recovery Invoice on another Lease or no Lease
  (independent N4); the confirm reads the count again under its own locks, and a forgiveness that
  commits after it is the known limit above.

### Round 1 test set-ups (written in full, run rule of 2026-10-13)

- Independent B1: `bc_case` (`payback_ground_case`, `correct_pet_receipt`, then the Security
  receipt's correction with 5,000 Security and 5,000 Pet: the own-Deposit count 5,000, the count
  0); `reduce_charge(review_line, 2_000)` (own-Deposit 3,000, count 0); the 10f-2
  ADJUSTMENT_REVERSAL of that reduction's Adjustment: standing 2,000, count 0, own-Deposit 5,000.
- Security B1: `qualified`, a 15,000 Pet Refund-review Refund, its Payment's return (count 15,000);
  a second seeded 15,000 Pet receipt; a 10,000 Pet Refund-review Refund (5,000); VOID of the
  charge's Invoice (0); the same charge billed again and issued (5,000); 3,000 of the later Refund
  comes back (8,000); a credit Adjustment of the whole 15,000 charge (3,000).
- Independent S3a: `bc_case`; a correction of the Pet receipt with a 4,500 right receipt, PET_REST
  3,000 onto the Settlement Refund's recovery line and 1,500 onto the review Refund's, recorded at
  own-Deposit 5,000; `reduce_charge(review_line, 2_000)`; the confirm is stale, nothing written.
- Independent S3b: `bc_case`; `reduce_charge(review_line, 2_000)`; the same correction with PET_REST
  3,000 onto the Settlement Refund's recovery line (1,500 forfeited planned); the 10f-2 reversal;
  the confirm is stale, nothing written.
- Independent S4: test (1) with reductions of 1,000 (Settlement recovery), 1,500 (review recovery),
  2,000 (Settlement recovery): counts 4,000, 2,500, 500.
- Security B2 (for Q-2026-10-17-126, not built): count 15,000; a 15,000 Pet receipt; VOID of the
  recovery Invoice (count 0); a BR-DEP-022 forfeiture of 15,000; the same charge billed again and
  issued: count 15,000, held 0, the Customer owes 15,000 again.

## Review round 2 (fresh read-only subagents, during P2; same instructions)

Independent: 0 blockers, 5 should-fix (tests and text). Security: 0 blockers, 2 should-fix (a text
gate and tests). Both confirm the round 1 design change is needed and safe and follows the answer
("takes out what ... removed", "alike"); with every charge standing whole every earlier result is
unchanged; the SQL, every new test's cents, the tie-test set-up change (nothing weaker), the 27
revision strings and the traceability changes; Q-2026-10-17-126 is rightly a question, not a
blocker (both options restrict correction paths the owner approved).

Fixed under the round-3 rule (tests and text only; no code or migration change):
- Independent 1 and security S2 (test): `test_a_standing_charge_counts_at_most_the_recovered_amount_paid_or_not`
  (DEBIT 2,000, credit 3,000, DEBIT 1,000, a 5,000 Payment, credit 12,000: 15,000, 14,000,
  15,000, 15,000, 3,000). The DEBIT-first reading is put to the owner as point 2 of Q-126.
- Independent 2 and security S2 (test): test (2) bills the charge again on a DRAFT first and
  asserts it counts 0 until issued.
- Independent 3 (test): both stale-draft tests assert the draft stays PENDING and that no
  forfeiture, receipt, Deposit application or correction is written.
- Independent 4 and security N1 (text): the module docstring and the least-privilege docstring.
- Independent 5 (text): Q-126's "what goes ahead" (three approved corrections after closure, or one
  approved forfeiture around a one-person VOID and re-bill of a no-Lease charge); docs/004 and
  docs/010 say a draft is stale when its forfeitures or source change, otherwise it confirms.
- Security S1 (text): 10e-2b-4b-2 waits for the answer to Q-126 (plan, questions).
- Security N2 (test): the VOID-without-event branch is asserted just before the VOID's time
  (15,000 with the event, 0 without), not only at the end.
- Security N5 (text): Q-126 gives dollars, the outcome without the VOID, the bc-set-up loss, and
  what option (a) must cover (a shared lock, the no-Lease charge, a Settlement confirm that keeps
  the Pet Deposit).
- Notes kept: a stale-draft test of the count alone (a no-Lease recovery charge; security N4,
  optional); a finite `p_as_of` is used only by the new VOID assertion (independent note); the
  cap cannot tell a recovery from an unrelated DEBIT on the same line (security N3, part of Q-126);
  a `REFUND` correction of a paid recovery charge stays untested (round 1 security S2: traced and
  found right, docs/004 states the path).

### Round 2 test set-ups

- DEBIT and cap: `qualified`, a 15,000 Pet Refund-review Refund, its Payment's return (15,000);
  `debit` 2,000 (line 17,000; standing and count 15,000); credit 3,000 (14,000); `debit` 1,000
  (15,000); `pay` 5,000 (line owes 10,000; 15,000); credit 12,000 (line owes 0; 3,000).
- DRAFT: after each VOID of test (2), `create_draft` of the obligation (standing 0, count 0), then
  `issue` (15,000, or 5,000 after the later review Refund).

## Review round 3 (fresh read-only subagents, after U3 and P3; same instructions)

Independent: clean (no blocker, no should-fix; three notes). Security: clean (no blocker, no
should-fix; four notes). Both confirm every round 2 fix, that no committed test got weaker, the
27 revision strings, the traceability changes (entry 3,183's note, seven entries appended, 3,190
in all), deny-by-default and the docs.

Notes taken (text only, in docs and records; no code, migration or test file changed): a later
DEBIT Adjustment is named among the restorations (docs/004, docs/010); Q-126 point 2 says the
build does not depend on the order (a DEBIT after a forgiveness counts again), and its "what goes
ahead" names the one-person credit-and-DEBIT route of a no-Lease charge; the runs table lists U3,
M4, P3 (the round 3 reviewers had not seen them in this record); the untested `REFUND` path is
carried in the round 2 notes. Notes kept: the same DEBIT wording in the migration and test
docstrings (not changed after P3); the committed tie test still drops the recovery foreign key,
now unneeded but harmless (rolled back).

Status: committed (see git log). Not pushed.
