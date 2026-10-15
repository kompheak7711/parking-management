# V1-056 sub-slice 10e-3d-2d-2a — a return reversal undoes another Lease's correction's Credit payment through a companion correction — review record

Sub-slice: 10e-3d-2d-2a (owner answers (a) to Q-2026-10-13-100 point 2 and Q-2026-10-13-103 point 3;
split of 10e-3d-2d-2, owner allowed: 2d-2a companion and application parts, 2d-2b Refund parts and
another Settlement's bounced Payment take, 2d-2c the Q-2026-10-15-113 answer). Migration
`20261212_138`. Base commit: bd4d654 (the 10e-3d-2d-2 pre-code design and the owner answers to the
10e-3d-2d-1 report). Built on 2026-10-15. Not pushed.

Rule IDs: BR-SETTLE-013, BR-SETTLE-016, BR-CREDIT-006, BR-CREDIT-014, BR-AUTH-010, DL-032;
DB-SETTLE-005. Design: ops/V1_056_PLAN.md, "10e-3d-2d-2 pre-code design" and "10e-3d-2d-2a as
built".

## Built

- Migration `20261212_138`: three new internal functions (no grant):
  `app.settlement_credit_application_owner`, `app.settlement_correction_companion_id`,
  `app.settlement_return_reversal_companion_source`; exact-text patches (each anchor found as often
  as listed, else the migration stops) of the walk, successor, follow, placed, source, refusal,
  confirm, result, the Settlement and correction Credit application writer, the correction Credit
  application check and the put-back rule. No table, column, constraint, trigger or grant change.
- Tests: new module `backend/tests/test_settlement_return_reversal_companion_migration.py` (seven
  tests), last in `scripts/database-test.sh`; committed tests changed in
  `test_settlement_returned_value_other_settlements_migration.py` (two renames, one allowed check;
  owner answer (a) to Q-2026-10-13-103 point 3); the 27 head-revision assertions in 15 modules move
  to `20261212_138` (revision strings only, `sed`). Traceability: two entries renamed (after the
  first 1,598), notes updated, seven appended.
- Docs: docs/004 (DB-SETTLE-005 paragraph), docs/010, the plan (design, as built, one slice 12
  item).

Design changes during the build (implementer's; confirmed needed and safe by both round 2
reviewers; none changes who pays or how much): (1) no derived ids in the source's `companions`;
(2) no companion merge in the placed function (P1 timeouts; a reversal taker is always opened by its
return reversal record); (3) `app.settlement_credit_application_owner` (round 1 blocker); (4) the
successor and follow functions rank only the reversal's own Settlement's `reapply` entries; (5)
records dated after every companion header; (6) the companion audit events after
`SET CONSTRAINTS ALL IMMEDIATE`.

## Runs

Static checks each in its own call, formatter first (`ruff format src tests`). Outputs in
`~/Development/prm-run-logs/` (`V1-056-slice-10e-3d-2d-2a-*`); every targeted and full run under
`caffeinate -dims`.

| Run | Kind | Result | Cause |
|---|---|---|---|
| D1 to D4 | catalog dumps (pre-code read) | printed (D3 printed only the headers because of my `sed` range; D4 is its passing rerun) | not checks |
| M1 | migration-only check | passed (head `20261212_138`) | first |
| FC1, L1 | format check, lint | passed | first |
| Y1 | `mypy` | failed: a `str` line id passed where a `UUID` is expected (new test) | cause A (types), correction 1 of 2 |
| FC2, L2, Y2 | format check, lint, `mypy` | passed | passing reruns after A1 |
| T1 | targeted: new and 2d-1 modules | 8 passed, 1 failed (my expected correction list on the second Settlement missed its earlier extra-charge correction) | cause B (test expectation), correction 1 of 2 |
| FC3, L3, Y3 | format check, lint, `mypy` | passed | after B1 |
| T2 | targeted: new module | 5 passed | passing rerun after T1 |
| U1 | backend unit, full | 3804 passed, 2016 skipped, 1 known warning | first |
| M2 | migration-only check | passed | before P1 |
| P1 | PostgreSQL full | 7 failed, 2173 passed: 3 statement timeouts in deep follow chains (successor, own-parts modules) and 4 "The return reversal source is incomplete" (own-parts and changed-payment modules) | cause C (speed: the placed merge's OR join and the walk's draft scan), correction 1 of 2; cause D (the round 1 blocker: an application with no Final Settlement of its own), correction 1 of 2 |
| M3 | migration-only check | passed | after C1 and D1 |
| FC4 | format check | passed | round 1 fixes |
| L4 | lint | failed: line too long (new test docstring) | cause E (long line), correction 1 of 2 |
| Y4 | `mypy` | failed: an `object` indexed (new test helper) | cause A (types), correction 2 of 2 |
| FC5, Y5 | format check, `mypy` | passed | passing reruns after A2 |
| L5 | lint | failed: line too long (the same docstring, my rewrap left one long line) | cause E (long line), correction 2 of 2 |
| T3 | targeted: new, 2d-1, successor, own-parts, changed-payment modules | 31 passed | passing rerun after P1 (C1, D1) and the round 1 tests |
| FC6, L6, Y6 | format check, lint, `mypy` | passed | passing reruns after E2 |
| U2 | backend unit, full | 3804 passed, 2017 skipped, 1 known warning | round 1 fixes |
| M4 | migration-only check | first call did not start (`sh` was given a relative path from another working directory; not a check); rerun passed | before P2 |
| P2 | PostgreSQL full | 2181 passed, 2 known warnings (Starlette; pydantic) | passing rerun after P1 |
| FC7, L7, Y7 | format check, lint, `mypy` | passed | round 2 fixes |
| T4 | targeted: new and 2d-1 modules | 11 passed | round 2 tests |
| U3 | backend unit, full | 3804 passed, 2018 skipped, 1 known warning | round 2 fixes (traceability); before round 3 (standing round-3 rule) |
| M5 | migration-only check | passed | before P3 |
| P3 | PostgreSQL full | 2182 passed, 2 known warnings (Starlette; pydantic) | round 2 test changed after P2; before round 3 (standing round-3 rule) |
| FC8, L8, Y8 | format check (after `ruff format src tests`, 343 files unchanged), lint, `mypy` | passed | owner answer (a) to Q-2026-10-15-114 (2026-10-16): the round 3 assertions and texts |
| T5 | targeted: new module | 7 passed, 1 known warning (Starlette) | the changed test and migration docstring; the new assertions pass |
| U4 | backend unit, full | 3804 passed, 2018 skipped, 1 known warning | traceability text changed |
| M6 | migration-only check | passed (head `20261212_138`) | before P4 |
| P4 | PostgreSQL full | 2182 passed, 1 known warning (Starlette) | last full run before the commit (after the read-only search: only the committed successor module calls that function; no test reads a migration docstring) |

Corrections per cause: A (types) 2 of 2; B (test expectation) 1 of 2; C (speed) 1 of 2; D
(owner of a re-posted application) 1 of 2; E (long line) 2 of 2.

## Review round 1 (fresh read-only subagents, during P1; told to write no file and run nothing)

Independent: 1 blocker, 5 should-fix, notes. Security: 0 blockers, 1 should-fix, 5 notes.

- Blocker (independent): an ordinary Credit application with a NULL `final_settlement_id` (the
  rest a `REFUND` correction writes again) was treated as another Settlement's (P1 showed it).
  Fixed: `app.settlement_credit_application_owner`.
- Should-fix (independent): the successor and follow ranking (fixed); records dated before the
  companion header (fixed); missing tests (fixed: the guard refusal, the put-back rule from the
  companion's draft; not built: a Rent-line companion put-back and two companions, see round 2);
  the remaining `OTHER_SETTLEMENT` case on the real path (fixed with the reviewer's set-up, below);
  the records (docs/010, plan as built: written).
- Should-fix (security): the fail-closed tests (fixed, including an entry of another Property).
- Notes kept as text or slice 12: the companion prepared by the approver (design reading; the
  approver supplies nothing the companion uses); a draft pre-recorded at the derived id makes R's
  confirm fail (23505, denial only: docs/004); payload-driven locks limited to the Property, refused
  as stale after the locks; the generic draft reads still return the decision's transaction id
  (pre-existing, before the slice 10 HTTP work).

Reviewer's set-up (independent, round 1; built in
`test_a_take_whose_correction_also_refunded_from_the_credit_stays_one_open_part`):
1. `two_lease_case(url, monkeypatch, returned=1_500, credit_paid=1_500)` (X0 = 1,500; the second
   Lease's correction pays the whole charge L1 from the Credit).
2. `return_only(first, refund, 300)` (X1; the Credit holds 300).
3. A 300 charge L2 on the second Lease (EXTRA_CHARGE correction).
4. A REFUND correction of the second Lease: `refund_command(second, L1, 200,
   SettlementCreditStep(credit, LINE, L2, 300))` (releases L1's 1,500, writes 1,300 again, pays L2
   300 from the Credit, refunds 200 from the Credit; its draw is X1's 300).
5. X1's source: `swept == []`, one `OTHER_SETTLEMENT` part of 300; X1's reversal refused with the
   10e-3d-2d-1 message, nothing written.

## Review round 2 (fresh read-only subagents, during P2; told to write no file and run nothing)

Independent: 0 blockers, 2 should-fix, notes. Security: 0 blockers, 0 should-fix, 6 notes. Both
confirmed the design changes (1) to (6) as needed and safe. Both should-fix are a test and text, so
under the round-3 rule they were fixed and round 3 runs without asking.

- Should-fix S1 (test): the successor and follow ranking had no test. Built with the reviewer's
  set-up, the two corrections in the order that lists the other Settlement's entry first:
  `test_an_own_put_back_listed_after_a_companion_s_is_followed_by_a_later_reversal`. As built in
  round 2 it ran only the follow function's ranking (X3's confirmed reversal); the successor
  function has had no caller since migration 134, so its ranking is asserted by a direct call
  since the round 3 fixes (SF1 below).
- Should-fix S2 (text): the plan as built names both renames and the deviations from the design's
  "Tests" note (docs/010 too).
- Notes taken: test 5 also asserts `credit_applications == []`; the hand-built source of the renamed
  committed test sets `credit_applications`, `reapply` and `companions` to `[]` as at HEAD; docs/004
  names the audit Customer and the 23505 case. Notes recorded for slice 12: the result function's
  companions query; the link fallback; the boolean cast; the tests below; reject or withdraw of a
  companion id.

Reviewer's set-up S1 (independent, round 2; built as described above): X0 returns 200, X1 300; the
second Lease's charge 300 is paid from the Credit by a REFUND_RETURN of its Settlement Pet Deposit
Refund (X0's 200 and 100 of X1's); X3 returns 300; the first Lease's charge 400 is paid from the
Credit by a REFUND_RETURN of its own Settlement Pet Deposit Refund (X1's 200 and 200 of X3's); X1's
reversal lists the second Lease's payment first; X3's reversal then follows X3's money into X1's
reversal's own put-back and is confirmed (under the old ranking it stops as `CHANGED`).

Reviewer's set-ups not built (independent, round 2; for 10e-3d-2d-2b or slice 12):
- (a) Companion put-back on a B Rent line: as the two-return case, X1 and X3 bring back 300 each;
  `open_rent_line(url, second)` from `test_settlement_return_reversal_put_back_migration.py` opens
  B's Initial Rent line; B's REFUND_RETURN pays 600 of it from the Credit (with a Pet Deposit step
  for any rest); X1's reversal puts 300 back through the companion with `within_invoice_basis` and
  the detail basis `PUT_BACK_BY_CORRECTION`, restoring B's application; a hand-built ordinary
  application with that label is refused (23514).
- (b) Two companions: two more Leases of the same Customer (`second_lease` twice, before any
  return); X1 brings back 600; each other Lease's REFUND_RETURN pays a 300 charge from the Credit;
  X1's reversal writes two companions (Settlement id order), each with one 300 reversal; drafts and
  corrections +3; the count of X1 (600, 600, 600, 0) from each of the three Settlements; every record
  dated after the later companion header.

## Review round 3 (fresh read-only subagents, during P3; told to write no file and run nothing)

Independent: 0 blockers, 1 should-fix, 5 notes. Security: 0 blockers, 0 should-fix, 3 notes.
Round 3 is not clean, so under the round-3 rule (2026-10-13) the sub-slice STOPPED before its
commit; nothing is committed; all files are in the working tree (Q-2026-10-15-114).

- Should-fix SF1 (independent, test or text): `app.settlement_returned_value_successor` has had no
  caller since migration 134 (the source function now calls the follow function), so the new test
  `test_an_own_put_back_listed_after_a_companion_s_is_followed_by_a_later_reversal` runs only the
  follow function's ranking patch, not the successor's; five texts (the test docstring, its
  traceability note, the docs/010 "Updated tests" bullet, the plan's as-built bullet and this record)
  say both are tested. Fix offered by the reviewer: in that test, after X1's reversal, assert that
  `app.settlement_returned_value_successor('CREDIT', <the first Lease's 400 application>)` returns
  X1's reversal's own put-back (NULL under the old ranking); or correct the five texts. No effect in
  production (the function is never called).
- Notes (independent): N1 the migration docstring says "The follow function is not changed",
  contradicting its round 1 ranking patch ("still stops at" is meant); N2 the run table lacked M5
  and P3 (added above); N3 the design's put-back example (500 paid, 200 put back, X3 keeps 100) was
  built as 600 paid, 300 put back, X3 keeps 0 (the same rule), not named among the deviations; N4
  traceability entry of the renamed `..._is_listed_and_an_open_part_is_refused_first` still names
  only sub-slice 10e-3d-2d-1; N5 the read-only search for tests that read a stored source with exact
  keys is not written here (P1 to P3 show nothing broke; the search at build found no test asserting
  the source's key set), and the S1 test could also assert X3's reversal amount (200).
- Notes (security): docs/004 wording of the 23505 case (R stays pending; it is rejected or
  withdrawn and recorded again with a new idempotency key, which gives a new companion id; the line
  is also longer than the paragraph's wrap); the result function's companions query matches by a
  payload key, not by Property (slice 12 item); the reapply branch fails closed on a NULL owner
  (unreachable).
- Verified by round 3 (independent): every round 1 and round 2 fix is real; the follow ranking test
  fails under the old ranking; the run table agrees with the text; each changed committed test
  compared with HEAD is not weaker beyond owner answer (a) to Q-2026-10-13-103 point 3; traceability
  entries 1 to 3,080 byte-identical, entries 3,081 to 3,083 edited (renames and notes), seven
  appended, ids unique. Security: deny-by-default, the companion's single path, routing, lock order,
  data exposure and append-only history unchanged since round 2; no secret in the new texts.

## Owner answer and round 3 fixes (2026-10-16, fresh session)

Owner answer (a) to Q-2026-10-15-114, a one-time exception: the assertion, the round 3 notes, the
checks and runs, then the commit without a round 4 (docs/010, ops/V1_056_QUESTIONS.md). No code
under test changed; the migration file changed only in its docstring.

- SF1 (new assertion): in
  `test_an_own_put_back_listed_after_a_companion_s_is_followed_by_a_later_reversal`, after X1's
  reversal, `app.settlement_returned_value_successor('CREDIT', <the first Lease's 400 payment>)`
  returns X1's reversal's own put-back (NULL under the old ranking: the old count takes the 400
  payment's entry as R's second linked put-back, and R has only one). The five texts now say which
  function each part of the test proves: the test docstring, its traceability note, the docs/010
  "Updated tests" bullet, the plan's as-built bullet and S1 above.
- N1 (text): the migration docstring no longer says "The follow function is not changed"; it says
  the follow function still stops open at a payment another Settlement's correction changed, and
  that the successor function has no caller and is tested directly.
- N2 (text): M5 and P3 were already added to the run table during round 3.
- N3 (text): the put-back example built as 600 paid, 300 put back, X3 keeps nothing (the design
  said 500, 200 and 100) is named among the deviations in the plan's as-built bullet and docs/010.
- N4 (text): the traceability note of
  `test_a_take_by_another_settlement_s_correction_is_listed_and_an_open_part_is_refused_first`
  now names sub-slices 10e-3d-2d-1 and 10e-3d-2d-2a.
- N5 (text and one assertion): the read-only search (2026-10-16) of the twelve backend test modules
  that read a return reversal source (`settlement_return_reversal_source_state`, a draft's stored
  `source`, or `draft_source`): none compares a stored source's whole key set; the whole-dict
  literals found are hand-built sources whose inner `source` object holds only `value_usd_cents`,
  and a hand-built source with no `companions` key is still allowed when no other Settlement's
  application is listed (P1 to P3 green). The S1 test now asserts that X3's reversal reverses
  exactly the 200 put-back.
- Security note (text): docs/004 now says that after a 23505 at a companion's derived id R stays
  pending and staff reject or withdraw it and record it again with a new idempotency key, which
  gives a new companion id; the paragraph is rewrapped.
- Owner answer 5: slice 12 item for the successor function with no caller (plan, slice 12 list).

The approver and `final_settlements.prepare` (owner answer 3; read-only check of the code): the
service authorizes the return reversal confirm with `financial.approve` only
(`settlement_correction.py`, `confirm_return_reversal`), and `app.insert_financial_draft` checks
only that the actor is an active human of the Property; `prepare_capability` is the label the
`SETTLEMENT_CORRECTION` kind requires (table check), not a check of the actor's grants. So an
approver without `final_settlements.prepare` confirms R normally, and the companion draft records
that approver as `prepared_by` under the label `final_settlements.prepare`. Every companion test
already runs this case: the tests' approver (`approving`) holds only `financial.approve`.
