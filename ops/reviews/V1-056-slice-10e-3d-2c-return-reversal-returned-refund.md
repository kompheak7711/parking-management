# V1-056 sub-slice 10e-3d-2c — a return's money that left through a bounced Payment or a wrong receipt — review record

Sub-slice: 10e-3d-2c (owner answer (a) to Q-2026-10-13-103 point 1: "charge the person who
received that Refund"; the Q-2026-10-11-78 rule). Migration `20261210_136`.
Base commit: 557ca6c (after the catalog dump script commit 58e5c48). Built on 2026-10-15. Not pushed.

Rule IDs: BR-SETTLE-013, BR-SETTLE-016, BR-REFUND-015, BR-CREDIT-014, DL-032; DB-SETTLE-005,
DB-REFUND-002. Design: ops/V1_056_PLAN.md, bullet "10e-3d-2c — money of a return that left through
a bounced Payment or a wrong receipt" (accepted by the owner on 2026-10-14) and its as-built note.

## Built

- Migration `20261210_136` (exact-text patches, each anchor found exactly once, else the migration
  stops): `app.settlement_returned_value_placed` (the take of a `RETURNED_PAYMENT` or
  `DEPOSIT_RECEIPT_CORRECTION` C of this Settlement through its Credit or receipt reversal is a
  `RETURNED_REFUND` part of the earlier return E's own Refund R), `app.settlement_returned_value_follow`
  (a stretch on a payment such a C reversed, when C also reversed the source, is a `RETURNED_REFUND`
  part with no record id; otherwise it stops open), `app.settlement_return_reversal_source_state`
  (follow rows named R; a Refund part above its net split off to R when C's recovery covers the
  excess and C reversed the source; R parts open when they add up to more than R's net after the
  reversal; one recovery entry of R; an own Refund that such a C charged back takes the walk path),
  `app.assert_settlement_return_reversal_allowed` (R parts listed exactly; the reworded refusal),
  `app.settlement_return_reversal_refund` (R in the recovery scope), `app.confirm_settlement_return_reversal`
  (R's charge-back written right after the reversal row, at its time),
  `app.validate_general_refund_correction` (the two relaxations below) and
  `app.write_payment_return_recoveries` (R's charge text and time). New internals
  `app.settlement_return_reversal_charge_back` and `app.settlement_return_reversal_paired_charge_back`
  (no grant). No table, column, constraint, trigger, lock or grant change.
- Tests: new module `backend/tests/test_settlement_return_reversal_returned_refund_migration.py`,
  last in `scripts/database-test.sh`; two committed tests renamed and allowed; the `REVERSED`
  message constant reworded; one test added to the tie-break module; the 27 head-revision
  assertions in 15 modules move to `20261210_136`. Traceability: two entries renamed, eight
  appended.
- Docs: docs/004 (DB-SETTLE-005 and DB-REFUND-002 paragraph; the 10e-3d-2b-3 Deposit tie sentence
  corrected), docs/010, the plan's as-built note, the 10e-3d-2b-3 record (correction section).

## Design changes during the build (run rule of 2026-10-14; each confirmed by the round 1 independent reviewer; none changes who pays or how much)

1. DC1. The general Refund correction check counts R's charge-back that the same
   `RETURN_REVERSAL` draft lists as available in the source for the reversal of E's return, and
   when it covers the whole reversal as standing for a Credit source whose Payment is no longer
   received. Needed: after C a reversed Credit's available value is 0 and its Payment is
   `REVERSED`; a Deposit holds 0.
2. DC2. R's charge-back is written right after the `CORRECTION_REVERSAL` with the same
   `occurred_at` (the writer takes it from the confirm's evidence key `returned_refund_at`, only
   inside a `RETURN_REVERSAL` for the Refund the evidence names; the general check allows that one
   paired row the latest time, never earlier). Needed: targeted run T1 failed with "Credit
   historical availability exceeded" and "Deposit historical held balance cannot be negative": the
   deferred history checks (migration 41) group events by time, so a later charge-back leaves the
   source below 0 between the two rows; a charge-back first is impossible (R's net is 0 and
   `resulting_net_refund_usd_cents >= 0`). R's charge-back row is so dated a few microseconds
   before the charge Invoice it names; nothing reads that order.
3. DC3. The design's fail-closed condition "R has an active return of its own other than E" is
   not built. Needed: the committed test the design names as allowed
   (`test_a_part_on_a_payment_a_receipt_correction_reversed_waits`) has one (the later correction's
   real 500 return of the same Refund). Safe: C charged only the net every return had lowered, so
   each return's reversal charges back only its own money; the cap (R parts at most R's net after
   E's reversal) stays.
4. DC4. An own use's Refund that a `RETURNED_PAYMENT` or `DEPOSIT_RECEIPT_CORRECTION` charged back
   sends the source down the walk path, so its part is charged back the same way (before: refused
   on the pooled path as no longer available).
5. DC5. The follow function hands such a stretch back with no record id; the source names R.

Also: the owner's two examples are tested in the renamed committed test (left-value module), not
repeated in the new module (DC6, confirmed).

## Committed tests that change (owner answer (a) to Q-2026-10-13-103 point 1; standing rules of 2026-10-11 and 2026-10-14)

- `test_settlement_returned_value_left_migration.py::test_a_payment_return_and_a_receipt_correction_count_what_they_take_from_a_return`
  renamed `test_a_payment_return_and_a_receipt_correction_take_a_return_s_money_its_reversal_charges_back`:
  its two refusals are replaced by confirmed reversals (R's recipients charged 300 and 1,000;
  totals 2,000 and 5,400; nets 0; the charge-back at the reversal's time; ledger reconciles), through
  the new helper `charged_back`; every count and the held-value refusal stay.
- `test_settlement_return_reversal_changed_payment_migration.py::test_a_part_on_a_payment_a_receipt_correction_reversed_waits`
  renamed `test_a_part_on_a_payment_a_receipt_correction_reversed_is_charged_to_the_refund_s_recipient`:
  the refusal is replaced by the confirmed reversal (1,000 charged, 4,900 in total; C reversed the
  payment; the Deposit and the debt unchanged); unused imports removed.
- The `REVERSED` constant is reworded (the swept and own-parts modules' hand-built opened cases
  still expect it). The 27 head-revision strings: revision only.
- Added: `test_settlement_returned_value_tie_break_migration.py::test_a_deposit_tie_made_by_hand_is_broken_by_write_order`
  (docstring of that module corrected).

## Runs

Static checks each in its own call, formatter first. Outputs in `~/Development/prm-run-logs/`
(`V1-056-slice-10e-3d-2c-*`); every targeted and full run under `caffeinate -dims`.

| Run | Kind | Result | Cause |
|---|---|---|---|
| D3 | catalog dump (history checks) | passed | read the deferred history checks after T1 |
| M1 | migration-only check | passed (head `20261210_136`, 135 upgrades) | first |
| FC1 | format check (after the formatter, 2 files) | passed | first |
| L1 | lint | failed: 4 lines over 100 | cause A, correction 1 of 2 |
| FC2 | format check | passed | after A1 |
| L2 | lint | failed: 1 line over 100 (the A1 rewrap) | cause A, correction 2 of 2 |
| Y1 | `mypy` | failed: 3 type errors in the new module | cause B, correction 1 of 2 |
| FC3, L3, Y2 | format check, lint, `mypy` | passed | passing reruns after A2 and B1 |
| T1 | targeted: new, left, changed-payment, swept, own-parts, return-reversal modules | 52 passed, 6 failed | cause C (fixture: a Credit made after the open charge is refused; C1) and cause D (the deferred history checks; D1, design change DC2) |
| M2 | migration-only check | passed | after D1 |
| FC4, L4, Y3 | format check, lint, `mypy` | passed | after C1 and D1 |
| T2 | targeted: same modules | 56 passed, 2 failed | cause C again (DL-032: two Credits pay before the Deposit), correction 2 of 2 |
| FC5, L5, Y4 | format check, lint, `mypy` | passed | after C2 |
| T3 | targeted: new module | 5 passed | passing rerun after T2 |
| U1 | backend unit, full | 3804 passed, 2004 skipped, 1 known warning | first |
| M3 | migration-only check | passed | before P1 |
| P1 | PostgreSQL full | 2168 passed, 3 known warnings (Starlette; pydantic `UnsupportedFieldAttributeWarning` twice) | first |
| FC6 | format check (round 1 fixes) | passed | round 1 fixes |
| L6 | lint | failed: import order in the tie-break module | cause E, correction 1 of 2 |
| Y5 | `mypy` | passed | round 1 fixes |
| FC7, L7, Y6 | format check, lint, `mypy` | passed | passing reruns after E1 |
| M4 | migration-only check | passed | migration changed (writer hardening) |
| T4 | targeted: new, left, changed-payment, tie-break modules | 28 passed | round 1 fixes |
| U2 | backend unit, full (covers `tests/test_traceability.py` after the new entries) | 3804 passed, 2007 skipped, 1 known warning | round 1 fixes |
| M5 | migration-only check | passed | before P2 |
| P2 | PostgreSQL full | 2171 passed, 1 known warning (Starlette) | round 1 fixes (test and migration files changed after P1) |
| FC8, L8, Y7 | format check (after the formatter), lint, `mypy` | passed | round 2 fixes |
| T5 | targeted: new module | 6 passed, 1 failed ("A return reversal draft of this correction is already waiting": the test recorded a second draft for the same return) | cause F (test set-up), correction 1 of 2 |
| FC9, L9, Y8 | format check, lint, `mypy` | passed | after F1 |
| T6 | targeted: new module | 7 passed | passing rerun after T5 |
| U3 | backend unit, full | 3804 passed, 2007 skipped, 1 known warning | before round 3 (standing round-3 rule) |
| M6 | migration-only check | passed | before P3 |
| P3 | PostgreSQL full | 2171 passed, 2 known warnings (Starlette; pydantic `UnsupportedFieldAttributeWarning` once) | before round 3 (standing round-3 rule; tests changed after P2) |

Corrections per cause (each sub-slice starts at 0): A (long lines) 2 of 2; B (types) 1 of 2;
C (test set-up of the worked example) 2 of 2; D (deferred history checks; design change DC2) 1 of
2; E (import order) 1 of 2; F (test set-up, duplicate draft) 1 of 2. After P3 only text changed
(this record, docs/010, ops/NOW.md). The catalog dump script and its own record are in the
separate commit 58e5c48 (docs/010 names it in this sub-slice's diff).

## Review round 1 (fresh read-only subagents, during P1; told to write no file and run nothing)

Independent: 0 blockers, 2 should-fix, 5 notes. Security: 0 blockers, 1 should-fix, 8 notes.

- Independent should-fix S1 (tests): (a) the source-level cap of the R parts (set-up Q1 below);
  (b) C of another Settlement; (c) the cover when C did not reverse the source (source level);
  (d) the cover when C's recovery is below the excess, on the real path; (e) DC2: the charge-back
  at the reversal's time and the helpers false or 0 on non-matching rows. Fixed: (a), (b), (c) in
  `test_the_returned_refund_parts_fail_closed`; (d) `test_a_refund_part_charged_back_only_in_part_stays_open`
  (500 of S's Refund returned before C); (e) in `charged_back` and
  `test_the_relaxed_refund_correction_checks_still_refuse`.
- Independent should-fix S2 (text): docs/004, docs/010 and the plan's as-built note. Fixed.
- Security should-fix (tests): show the relaxed checks still refusing: (a) a reversal row with no
  charge-back after it is refused at `SET CONSTRAINTS ALL IMMEDIATE` by the deferred Credit history
  check; (b) a charge-back row on another Refund, at another time or not linked is not paired;
  (c) after the confirm, neither helper counts. Fixed: `test_the_relaxed_refund_correction_checks_still_refuse`.
- Security note taken (hardening, fail-closed): the writer honours `returned_refund_at` only inside
  a `RETURN_REVERSAL` and only for the Refund the evidence names.
- Notes recorded, not changed: R's charge-back dated before its charge Invoice (both reviewers;
  docs/004, docs/010, migration docstring); the charge text "value whose return was recorded by
  mistake" reads strained (independent N2; recorded as a text item for slice 11e or the owner); the
  uniqueness check skips `RETURNED_REFUND` parts, so a hand-built source could name R both ways
  (unreachable: R was paid before E); the lookup of E's returned Refund orders by id (E has one
  return row); the walk path change found no committed test that changes; deny-by-default, no SQL
  injection, no data in messages, no route.
- The owner's instruction for the Deposit tie (set-up Q2 below): the 10e-3d-2b-3 record did not
  show a reviewer confirming that a Deposit tie cannot be made even by hand; the round 1
  independent reviewer found a way; the test is added and the earlier record corrected.

## Review round 2 (fresh read-only subagents, during P2; told to write no file and run nothing)

Independent: 0 blockers, 1 should-fix, 8 notes. Security: 0 blockers, 1 should-fix, 5 notes. Both
should-fix are a test or text, so under the round-3 rule (2026-10-13) they were fixed and round 3
runs without asking, after U3 and P3.

- Independent should-fix (text): the plan's as-built note must name both renames (old to new).
  Fixed (and the plan's 10e-3d-2b-3 note now points to the Deposit tie correction).
- Security should-fix (test): no test showed the general check refusing at the trigger. Fixed in
  `test_the_relaxed_refund_correction_checks_still_refuse`: a reversal row at the Refund's latest
  time (not a paired charge-back) and a charge-back written through the writer 1 microsecond before
  the reversal are both refused with "Refund correction must continue exact source history".
- Notes taken (tests and text): the no-charge-back block is now always rolled back by `finally`
  (security 1); the Deposit side shown too ("Deposit historical held balance cannot be negative",
  worked example; security 2, independent 4); paired negatives for another kind and another actor
  (security 3); docs/004 DB-REFUND-002 gains a 10e-3d-2c paragraph (independent 2); the new
  module's docstring names the renamed test on one line (independent 8).
- Notes not taken (recorded): the charge text branch reads only that `returned_refund_id` is set
  while the time also needs it to equal the Refund (unreachable: only the confirm sets it, for R);
  no test feeds the writer another Refund or variant; "no other row may tie" holds because the
  confirm writes one entry and the refusal function requires one (the general check alone would
  accept a second paired row on R, which `app.settlement_return_reversal_recovery_amount` then
  refuses as repeated); the walk-path condition does not filter the recovering correction by
  Settlement (it only picks the path; the cover does); the placed function's Settlement check is
  defence in depth (the takers come from this Settlement's walk); the new functions' owner is not
  asserted (as in earlier migrations); docs/010's 10e-3d-2b-3 entry keeps its text (the log is
  append-only; the 10e-3d-2c entry corrects it).
- Round 2 independent confirmed: every round 1 fix is real; DC1 to DC5 still needed and safe; the
  Deposit tie test really makes a tie and its arithmetic is right; the 27 head strings and the
  two renamed tests compared with HEAD, nothing weaker; traceability valid, only two renamed
  entries changed (indexes 3025 and 3062) and eight appended.

## Review round 3 (fresh read-only subagents, during P3; told to write no file and run nothing)

Independent: 0 blockers, 0 should-fix, 3 notes: clean. Security: 0 blockers, 0 should-fix,
0 notes: clean. No further round.

- Independent: each round 2 test reaches the refusal it claims (the reversal row at the latest
  time passes the earlier checks and fails only the tie term; the writer call 1 microsecond early
  fails the `occurred_at < v_latest` term; without the relaxations either insert would fail
  earlier, so the tests tell the versions apart); every by-hand transaction rolls back in
  `finally`. Committed tests compared with HEAD: the 15 modules rebuilt from HEAD with the revision
  string swapped match exactly; the two renamed tests keep every count and refusal of HEAD except
  the two refusals the owner's answer ends, replaced by stronger checks; the `REVERSED` constant
  changes wording only; the tie-break module only gains a test, two docstring lines and imports.
  Nothing is weaker. Traceability parses, 3,073 to 3,081 entries, the first 1,598 identical to
  HEAD. Notes: this runs table was incomplete (completed above); the docs/010 catalog dump entry
  belongs to commit 58e5c48 (named above); docs/004's "any other row is still refused" is true
  for the system as a whole (the general check alone would accept a second paired row, which
  `app.settlement_return_reversal_recovery_amount` refuses).
- Security: deny-by-default, the relaxations' reach, the writer's time key, the round 2 tests and
  the rollbacks checked again; clean.

Reviewer's set-up Q1 (independent, round 1; built in `test_the_returned_refund_parts_fail_closed`):

1. `case={**refunded_case(url),"url":url}`; `refund, credit = case["refund"], case["refund_credit"]`.
2. `earlier = return_only(case, refund, 300)`.
3. The Payment behind the Credit bounces (`RETURNED_PAYMENT`: charges 1,700, reverses the Credit).
4. In an always rolled-back owner transaction with the user triggers of `app.refunds` disabled:
   `UPDATE app.refunds SET usd_accounting_value_cents=usd_accounting_value_cents-100,
   refund_amount_minor=refund_amount_minor-100 WHERE id=<refund>` (R's net becomes -100).
5. The source lists no part as undone and no recovery; `swept_open` is one `RETURNED_REFUND` part
   of R, 300 (300 > -100 + 300); the refusal function raises the reworded `REVERSED` message.

Reviewer's set-up Q2 (independent, round 1; built, adapted, in
`test_a_deposit_tie_made_by_hand_is_broken_by_write_order`):

1. A correction X with two Deposit payments from one Deposit after a return-only E into it (built:
   E 1,000 of the Pet Deposit Refund; a third party pays 1,100 of a 1,500 charge; another 1,500
   charge; X brings back 700, its Credit pays 300 of the first charge, the Pet Deposit the other
   100 and the 1,500, and refunds 100, so E's money lies across X's two payments).
2. Read X's two payments in write order: older o, newer n (n's time and application order); low
   and high by UUID byte order.
3. In one owner connection, always rolled back in `finally`: disable the user triggers of
   `app.deposit_applications` and `app.settlement_correction_effects`, and
   `ALTER TABLE app.deposit_applications DROP CONSTRAINT deposit_applications_settlement_order`.
4. `UPDATE app.deposit_applications SET occurred_at=<n's>, application_order=<n's> WHERE id=o`.
5. Give low `max(effect_sequence)+1` of X.
6. E's placed parts follow the write order (low newest), not the id; the same on a second read.
7. After the rollback: the constraint exists, every trigger state is as before, the rows are as
   before. (`final_settlement_id` is NOT NULL, so a NULL-row variant is not possible.)
