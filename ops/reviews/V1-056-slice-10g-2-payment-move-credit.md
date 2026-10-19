# V1-056 sub-slice 10g-2 — the narrow Credit and Refund refusal inside the PAYMENT_MOVE correction — review record

Sub-slice: 10g-2 (owner answer (a) to Q-2026-10-17-121: inside the `PAYMENT_MOVE` correction of a
closed Final Settlement only, the blanket Credit and Refund refusal becomes a narrow one). Migration
`20270107_164` (one new internal function, one whole-body replacement, one exact-text patch). Base
commit: 056ddbd. Built on 2026-10-19 in one fresh session. Not pushed.

## Built

- Migration `20270107_164_settlement_payment_move_credit.py`: new internal
  `app.wrong_unit_move_source(property, allocation, target invoice, settlement correction)` (no
  grant), built from the current slice 7 body of `app.payment_move_source` by two exact-text
  replacements (its name and fourth argument; the refusal keeps the blanket condition and, for a
  correction, also needs a release row of this Payment on the wrong Invoice; a NULL fourth argument
  reads as the blanket rule); `app.payment_move_source` calls it with false (whole-body
  replacement, same signature, settings and privileges); `app.settlement_payment_move_source`
  calls it with true (one exact-text replacement).
- Committed tests changed: the 27 head-revision strings in 15 modules (revision strings only).
- New module `test_settlement_payment_move_credit_migration.py` (last in `scripts/database-test.sh`).
- Docs: docs/002 (BR-PAY-042 amendment, a BR-SETTLE-013 pointer), docs/004 (DB-PAY-008 and the
  DB-SETTLE-005 10g paragraph), docs/010, plan (pre-code design, slice 12 known limits), questions
  (owner answers to the 10e-2b-4f report; new Q-2026-10-19-139); traceability appended.

## Runs

| Run | Result |
|---|---|
| D1 | catalog dump of the move sources, the Credit and Refund value functions, the move check and the slice 7 recorder and confirm (no `REDACTED` marker), saved in `~/Development/prm-run-logs/v1-056-10g-2-D1.txt` |
| I1/FF1/FC1/L1/Y1 | passed (long-line search first; the import sort fixed one import order of the new module, a normal step; each check in its own call) |
| M1 | passed |
| T1 | 40 passed (the slice 7 move, the 10g and the new module, in the full-suite order) |
| U1 | 3866 passed |
| M2 | passed |
| P1 | 2377 passed (the known deprecation warning) |
| I2/FF2/FC2/L2/Y2 | passed (after the round 1 fixes; long-line search first, one long test line rewrapped before the checks) |
| M3 | passed (the migration changed in round 1) |
| T2 | 43 passed |
| U2 | 3866 passed |
| M4 | passed |
| P2 | 2378 passed, 2 failed: `test_refund_migration.py::test_usd_refund_correction_rejects_unverified_or_inconsistent_value[changes1]` and `[changes2]`, each the known DL-067 `LockNotAvailable` (`LOCK TABLE ... IN SHARE MODE NOWAIT` in `app.assert_payment_excess_eligible`), in a module this sub-slice does not change |
| P2-rerun | the two failed tests only, once, under `caffeinate -dims` (standing run rule of 2026-10-18): 2 passed |
| I3/FF3/FC3/L3/Y3 | passed (after the round 2 fixes; long-line search first; the formatter joined one line of the new module, a normal step) |
| T3 | 8 passed (the new module, the only test file changed since T2) |
| U3 | 3866 passed (before round 3) |
| M5 | passed |
| P3-stopped | stopped by me after it collected 2380 items: its command also ran a read-only `git status` count in the same call, against the run rule that a script runs alone; nothing ran to an end; the log is kept as `v1-056-10g-2-P3-stopped.txt` and no container was left |
| P3 | 2380 passed (alone; the known deprecation warning and two known pydantic alias warnings; before round 3; the last full run) |
| FF4/FC4/L4/Y4 | passed (after the round 3 text fixes; no code, migration or test file changed after P3; the formatter changed nothing) |
| U4 | 3866 passed |

No check failed. P2 failed only with the known `LockNotAvailable` and passed on its rerun; no
correction was counted. One run-rule slip: the first P3 command joined a `git status` count;
stopped at once and run again alone.

Full outputs in `~/Development/prm-run-logs/v1-056-10g-2-*.txt`, one file per attempt.

## Review round 1 (fresh read-only subagents, during P1; told to write no files at all, scratch files included, and to run no test, script or database command)

Independent: no blocker, 3 should-fix, 7 notes; reading (1) confirmed, reading (2) confirmed with a
wording fix, reading (3) partly rejected. Security: no blocker, 3 should-fix, 4 notes; privileges,
locks and the slice 7 reduction checked.

Fixed:

1. Independent should-fix 1 and security should-fix 2 (text and test): reading (3) said a release
   cannot appear between the record and the confirm; it can (a release whose Credit was reversed
   may already exist at the record, and a correction of the same Settlement that writes a linked
   credit Adjustment, such as a `REFUND` correction, writes release rows after the closure). The
   confirm reads the source again under its locks, so it fails closed. The plan and docs/010 are
   corrected. New test (the independent reviewer's set-up):
   `test_a_refund_after_the_record_refuses_the_confirm_when_the_wrong_money_was_released`:
   `paid_by(first, 12_500)`, allocate 12,500 on the other line, a 300 credit Adjustment on that
   line, the released Credit reversed in one call, `close_other_line_paid(first, ((credit,
   400),))`, the correction of the re-posted 12,200 recorded, a 300 Payment Refund, then the
   confirm: 55000 with the blanket message, the draft PENDING, outstanding (0, 12,500).
2. Independent should-fix 2 (test): no test proved the Payment filter. New test (the reviewer's
   set-up): `test_another_payment_s_release_on_the_wrong_invoice_does_not_block_the_correction`:
   a 12,400 Payment identified for the other damage Invoice pays 12,000 and its 400 becomes Credit;
   another Payment pays the last 500; a 300 credit Adjustment releases from the other Payment
   (newest first, asserted); the closure applies 400, 400 and 300; the correction moves 12,000
   (the first line owes 12,000, the second 500, the Payment's Credit stays 400); the slice 7 draft
   is refused.
3. Independent should-fix 3 (test): the least-privilege test now compares the slice 7 source's
   whole new definition (its old header, then only the call).
4. Security should-fix 3 (test): `test_a_release_of_the_wrong_money_still_blocks_the_correction`
   now runs for the payer's own Payment and for a third party's Payment identified for the Lease,
   whose released Credit belongs to the Lease Customer, not the payer; both refused. Its second
   part (a released Credit reversed while other value remains is still refused) is covered by
   item 1 (a Refund remains).
5. Both reviewers' note (hardening): a NULL fourth argument failed open; the refusal now reads
   `NOT COALESCE(p_settlement_correction,false) OR EXISTS(...)`, so a NULL falls back to the
   blanket rule (only internal callers with literals today; no grant).
6. Security should-fix 1 (owner): a release of the wrong Payment's allocation on a Late-payment
   Charge of the wrong Invoice (a Late-payment Charge `REFUND` correction after closure: the
   `REFUND` variant with `target_kind` `LATE_PAYMENT_CHARGE`, migration `20261117_113`; name
   corrected in round 2) is not read. The independent reviewer read this as consistent with
   BR-PAY-040 (the Charge is its own obligation, like another Invoice); the owner's answer names
   the wrong Invoice. Written as Q-2026-10-19-139 (recommendation (a) in round 1, changed to (b)
   in round 2, below) and a slice 12 known limit until answered.
7. Notes taken: independent note (the correction stays refused for good after the closure when
   the Settlement applied the released Credit or a correction refunded it, as the owner's "still
   refused" says): slice 12 known limit and docs/010; security note N3 ("stay with the payer" was
   wrong for released Credits of other Customers): the migration docstring and the plan say "stay
   where they are"; independent notes: the BR-SETTLE-013 pointer in docs/002, the rule-ID lists
   aligned (BR-CREDIT-002 removed from the docstring and the plan), the reading (2) wording on
   `CREDIT_APPLICATION` releases (they reverse no allocation and create no new Credit), the plan's
   as-built line names the module's tests, this record.
8. Not taken: security note N2 (a correction-specific message): the message stays the slice 7 one,
   so both paths keep one refusal text; the slice 11 screen can explain that after closure the
   Credit may not be reversible. Security note N4 (Deposit receipts the Payment funded are not
   read by either rule): pre-existing, the move does not touch them.

## Review round 2 (fresh read-only subagents, during P2; same instructions)

Independent: no blocker, 3 should-fix (all text), 7 notes; every round 1 fix confirmed, the
exact-text strings checked byte for byte, nothing weakened; the Q-139 handling accepted (N7).
Security: no blocker, 1 should-fix (text), 2 notes; the round 1 fixes, races, privileges and data
exposure checked; the Q-139 handling accepted (N1). Fixed under the round-3 rule (tests and
text):

1. Independent should-fix 1 (text): "`LATE_CHARGE_REFUND` correction" named no real variant; Q-139,
   the plan's known limit (1) and this record now name the Late-payment Charge `REFUND` correction
   (the `REFUND` variant with `target_kind` `LATE_PAYMENT_CHARGE`, migration `20261117_113`).
2. Independent should-fix 2 (text): the plan now has the 10g-2 as-built line (the COALESCE
   hardening, the corrected reading (3), the seven tests by name, Q-139 and the limits).
3. Independent should-fix 3 (text): known limit (2) in the plan and docs/010 now says the
   correction stays refused for good whenever any Credit of the Payment, the released one or
   another, was applied or refunded by the Settlement or by a correction; a Refund blocks until it
   is returned in full.
4. Security should-fix 1 (text): Q-139 and the plan's known limit (1) now say that in the other
   order (the move first, the Charge Refund second) both corrections are accepted under every
   rule, so option (a) refuses only one order. With that, the recommendation of Q-139 is changed
   to (b) (keep it as built). (Round 3 corrected the wording "the same state is reached" and the
   reason for (b); see below.) The reviewer's real-path set-up for (a), if the
   owner chooses it: `case = two_signer_case(url, overdue_rent=True)` (its Charge comes from the
   Rent Invoice); `second = leaving_case(url, start_offset=this_month(url))` on the same Property
   (every case builder reuses the one Property and adds a Unit), the correct Invoice
   `invoice_of(url, second["other_line"])` owing 12,500; before the closure a 13,000
   `seed_payment` of the Primary Tenant with no Invoice named, 10,000 designated on `rent_line`
   (the wrong allocation W); close as `settled_case` does
   (`test_settlement_late_charge_refund_migration.py:126-147`, inline after that allocation);
   after the closure the same Payment's last 3,000 posted `DIRECT_CHARGE` to `case["charge"]`
   (the `pay_charge` command, `:203-235`), then the Charge `REFUND` correction `command(case,
   3_000)` recorded and confirmed (`:271-293`); assert a release row whose reversed allocation is
   the Charge allocation and `payment_credit_value_at(P)=3000`; the 10g correction of W: accepted
   as built, 55000 with the blanket message and no new draft under (a); a confirm-time variant
   (record the move, confirm the Charge Refund, confirm the move: 55000, PENDING); and the
   reverse order (the move first, then the Charge Refund: accepted only when the Charge `REFUND`
   draft carries a Credit step that applies the released 3,000 to the 10,000 the move brought
   back on `rent_line`, because its DL-032 step refuses a Refund of released Credit while that
   Customer has open debt on the Lease; the whole 3,000 then pays that debt and nothing is
   refunded; corrected in review round 3, security).
5. Notes taken (tests): independent N2, the one body called with NULL (55000, the blanket
   message) and with true (12,500 moved) in the owner's example test; N3, the confirm-time test
   asserts the Payment's Credit 0, Refund 300 and the release row of this Payment on the wrong
   Invoice before the confirm; N5, the least-privilege test also compares every `app` constraint
   (`pg_get_constraintdef`); N6, the closure helper's parameter `credits` renamed `applied` (it
   shadowed the imported service).
6. Notes taken (plan): independent N4, the four `slice_7_draft_refusal` assertions change with
   10h (the 10h entry names them).
7. Not taken: security N2 (an extra test where a `REFUND` correction of the same Settlement
   writes a release between the record and the confirm): optional; the confirm-time test already
   proves that the confirm reads the release condition again, and the reviewer's set-up is kept
   here for slice 12: the Payment has two allocations on the wrong Invoice; a `REFUND` correction
   of the same Settlement, recorded after the move draft, releases the newer one first; then the
   confirm of the older one's move is refused with 55000. Independent N7's optional "What goes
   ahead" line about the 11e route: no route waits, because the case is accepted as built.

## Review round 3 (fresh read-only subagents, during P3; same instructions)

Independent: no blocker, 1 should-fix (text only), 3 notes; every round 2 fix confirmed, nothing
of rounds 1 and 2 weakened; the migration, tests and docs checked again. Security: no blocker, 2
should-fix (both text only), 4 notes; races, privileges, the direct test calls and data exposure
checked, no new path.

Fixed under the round-3 text rule of 2026-10-16 (text only; no code, migration, test or fixture
change; no round 4):

1. Independent should-fix 1 and security should-fix 1 (text): "the same state is reached" in the
   reverse order was wrong: both corrections are accepted, but every `REFUND` correction's DL-032
   step first applies the Credit it releases to its Customer's open debt on the Lease (owner
   answer 2 to Q-2026-10-07-42), which then includes the debt the move brought back, and refunds
   only the rest. Q-139 ("The case", including "refund what its DL-032 step does not apply"), the
   plan's known limit (1), docs/010 and the round 2 set-up above are corrected.
2. Security should-fix 2 (text): the reason for (b) now is that a Charge allocation is never part
   of the moved allocation or of its release chain (Charge allocations never move), so its release
   never turns the moved value into Credit or a Refund; Q-139 also says that the built Invoice
   rule depends on order in the same way for the Payment's other allocations on the wrong Invoice
   and protects in both orders only against a release of part of the moved allocation itself.
3. Independent notes taken (text): N1, known limit (2) said "for good" also for a refunded Credit;
   it now says "for good" only when such a Credit was applied, and "at least until the Refund
   comes back in full and the Credit is reversed" when it was refunded (plan and docs/010); N2,
   Q-139 names sub-slice 10c-3b-1; N3, P3 is in the runs table (it ran during this round).
4. Security notes N1 to N4: confirmations only (no new race or bypass; privileges and settings;
   the direct calls on the owner connection weaken nothing; no data exposure).
