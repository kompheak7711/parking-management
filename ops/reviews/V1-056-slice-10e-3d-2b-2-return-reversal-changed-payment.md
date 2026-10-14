# V1-056 sub-slice 10e-3d-2b-2 — a return's money on a payment a later Refund correction or pet-damage reclassification changed: review record

Sub-slice: 10e-3d-2b-2 (migration `20261208_134`). Base commit: c2283fa (the 10e-3d-2b-2 design).
Built on 2026-10-14. Not pushed.

Rule IDs: BR-SETTLE-008, BR-SETTLE-013, BR-SETTLE-016, BR-CREDIT-014, BR-DEP-027, DL-032;
DB-SETTLE-005.
Owner answers: (a) to Q-2026-10-13-107 (the money a changing correction took back out of a
payment pays out first on its Refunds, the oldest first, then on its payments, the newest first;
the mistaken money keeps its place in that stream); answer 4 of 2026-10-14 (a return reversal's
put-back keeps each part's place, with the reversed return's money cut out). Design: ops/V1_056_PLAN.md,
10e-3d entry, "10e-3d-2b-2 pre-code design"; as built: the bullet after it.

## Built

- Migration `20261208_134`: new internal `app.settlement_returned_value_placed` (the parts with
  their offsets; `app.settlement_returned_value_parts` now calls it); new internal PL/pgSQL
  `app.settlement_returned_value_follow(p_settlement, p_kind, p_source, p_record_kind, p_record,
  p_offset, p_part, p_until)`; exact-text patches: the `swept_state` CTE of
  `app.settlement_return_reversal_source_state` replaced whole (placed takes, each payment part
  followed, rows summed per own flag, correction and record), the recovery scope
  `app.settlement_return_reversal_refund` (relaxing: also a Refund the source lists in
  `own_parts`), and the `CHANGED_APPLICATION` message of
  `app.assert_settlement_return_reversal_allowed`. No writer, lock or grant change.
- Implementer's readings beyond the written design (named for the owner): (1) a reversed return's
  stretches on a payment its reversal changed are its placed parts followed up to that reversal
  (`p_until`), so a put-back of a put-back is followed (the committed chain test needs it; the
  design said it stays open); (2) the put-back is checked against this Settlement, not against
  the reversed payment's Settlement link (a rest a Refund correction re-posts has none, migration
  100); (3) the recovery scope patch (the design listed no other function); (4) the planned
  put-back-then-Refund-correction test is built in the other order (in the planned order the
  Refund correction's released Credit first pays the 300 the first reversal reopened, so there is
  no Refund).
- Tests: new module `test_settlement_return_reversal_changed_payment_migration.py` (eight tests,
  last in `scripts/database-test.sh`); committed tests changed under the owner's standing rules:
  `test_a_part_on_a_payment_a_refund_correction_changed_waits` renamed
  `..._is_followed_into_its_payment_written_again` (successor module),
  `test_an_own_payment_a_refund_correction_changed_waits` renamed
  `..._is_followed_into_its_refund_and_payment` (own-parts module), the `CHANGED` message
  constant (left module), unused imports (successor module), 27 head-revision assertions in 15
  modules (`20261208_134`). Traceability: two entries renamed, eight appended.
- Docs: docs/004 DB-SETTLE-005 paragraph, docs/010 (owner answers of 2026-10-14, as built,
  updated tests), the plan (as-built bullet), ops/V1_056_QUESTIONS.md (owner answers,
  Q-2026-10-14-110, Q-2026-10-14-111), ops/V1_055_RUN_RULES.md (signature rule retired, catalog
  dump rule).

## Owner request of 2026-10-14: where the real app gets the signing time (read only)

The staff Lease screen sends the browser's clock (`new Date().toISOString()`,
`frontend/src/LeaseManagement.tsx` lines 434 and 461); the two Lease signing routes pass it
unchanged; `app.record_lease_signature` and `app.sign_lease` (through
`app.sign_lease_with_reservation`) refuse a time later than the database's statement time with
no tolerance (migration 24 lines 286 and 408). Written as Q-2026-10-14-110 (recommendation (a)).
Nothing built.

## Runs

Static checks each in its own call, formatter first. Outputs in `~/Development/prm-run-logs/`
(`V1-056-slice-10e-3d-2b-2-*`); every targeted and full run under `caffeinate -dims`.

| Run | Kind | Result | Cause |
|---|---|---|---|
| L1 | lint | 5 unused imports (successor module) | cause A, lint, 1 of 2 |
| — | formatter, format check, lint, `mypy` | clean | after the fix |
| M1 | migration-only check | failed: `column holding.own does not exist` | cause B, migration SQL, 1 of 2 |
| M2 | migration-only check | passed (head `20261208_134`) | after the fix |
| T1 | PostgreSQL targeted: the seven return reversal modules | 62 passed, 1 failed (`test_a_part_keeps_its_place_through_a_refund_correction_and_a_return_reversal`: the put-back check compared the reversed payment's empty Settlement link) | cause C, follow function, 1 of 2 |
| M3 | migration-only check | passed | after the fix |
| T2 | PostgreSQL targeted: same modules | 63 passed | after the fix |
| U1 | backend unit, full | 3802 passed, 1992 skipped, 1 known warning | first |
| P1 | PostgreSQL full | 2156 passed, 1 known warning (Starlette) | first |
| — | formatter, format check, lint, `mypy` | clean | round 1 fixes |
| M4 | migration-only check | passed | round 1 fixes |
| T3 | PostgreSQL targeted: same modules | 65 passed | round 1 fixes |
| U2 | backend unit, full | 3802 passed, 1994 skipped, 1 known warning | round 1 fixes |
| P2 | PostgreSQL full | 2158 passed, 3 known warnings (Starlette; pydantic `UnsupportedFieldAttributeWarning` twice) | round 1 fixes (code changed after P1) |
| L2 | lint | 1 import block not sorted (new test module) | cause D, lint (import order), 1 of 2; fixed with `ruff check --fix` on that file |
| — | formatter, format check, lint, `mypy` | clean | round 2 fixes |
| T4 | PostgreSQL targeted: the new module | 8 passed | round 2 fixes |
| U3 | backend unit, full | 3802 passed, 1995 skipped, 1 known warning | before round 3 |
| M5 | migration-only check | passed (a first attempt did not start: the shell was in `backend/`, `sh: scripts/migration-check.sh: No such file or directory`; not a check failure) | before P3 |
| P3 | PostgreSQL full | 2159 passed, 2 known warnings (Starlette; pydantic `UnsupportedFieldAttributeWarning` once) | before round 3 (a test file changed after P2) |

Corrections used: cause A (lint, unused imports) 1 of 2; cause B (migration SQL) 1 of 2; cause C
(follow function) 1 of 2; cause D (lint, import order) 1 of 2. No `Signature evidence is invalid`
failure in any run.

## Review round 1 (fresh read-only subagents, during P1; told to write no file anywhere and run nothing)

Independent: 0 blockers, 2 should-fix, 7 notes. Security: 0 blockers, 2 should-fix, notes.

- Should-fix (both reviewers): only an active payment checked that the stretch lies inside it; a
  stretch past a reversed payment's end could map into the next reversed payment's slot of a
  Refund correction's stream. Not reachable (the placed function gives in-bounds stretches);
  fixed (fail closed): a part not inside its payment stops open. The fail-closed test's "past what
  Q paid out" case really tested this; reworded.
- Should-fix (security): the recursion through `p_until` was not bounded (`v_steps` is per call),
  and "each step back reads only earlier corrections" was not enforced; with inconsistent data
  two return reversals could call each other until `stack depth limit exceeded` (54001) inside the
  confirm's locks. Fixed (fail closed): with `p_until`, a payment is followed only through changes
  by corrections strictly earlier than `p_until` (`occurred_at`, then id); tested by hand.
- Should-fix (independent, tests): the Deposit form through a payment a Refund correction wrote
  again, the pet-damage reclassification form and more fail-closed inputs were missing. Built with
  the reviewer's set-ups below; another Settlement and the two `p_until` cases added to the
  fail-closed test. A reversal by no correction cannot be reached on the real path (only
  corrections reverse such payments after closure). (Corrected in review round 2: a reversal by
  another correction kind is reachable through `RETURNED_PAYMENT` and `DEPOSIT_RECEIPT_CORRECTION`,
  the sub-slice 10e-3d-2c cases; its real-path test was added in round 2.)
- Notes: readings (1) and (2) sound (migration 100 lines 668-677 write the re-posted rest without
  a Settlement link); reading (3) sound and bounded (server-built source, digest-checked; the
  Refund must be the listed correction's, of the same Settlement, from the draft's source, named
  in `recoveries` with its recipient), name it to the owner; reading (4): the put-back-then-Refund
  order stays untested (buildable, but the released Credit then pays the reopened 300); the
  newest-first order can tie on time and fall to the random id (since migration 130): written as
  Q-2026-10-14-111; each put-back step recomputes the walk twice (cost grows with chain length);
  docs to update (done).
- Security notes: no grant (EXECUTE revoked from PUBLIC and the three roles, tested), no dynamic
  SQL, every relation schema-qualified, no secret or personal data in the diff.

### Reviewer set-ups (independent reviewer, round 1; both built and passing in T3)

(a) Deposit payment through a Refund correction (migration 103), with no release-order tie: on
`refunded_case`, `pet_paid = pet_refund(case)`, an unpaid 1,500 charge; a return-only correction
of the Credit Refund whose step lets the Credits pay 500 and 300 of the charge (the line owes 700);
E = 1,000 of the Pet Deposit Refund back (return only); S brings back 500 of it with a new Refund:
the Pet Deposit pays the 700 at the remainder stage (`pet_remainder=STAFF`) and refunds 800 (E's
money is 300 in S's Refund and the whole 700 payment); a Refund correction of 300 of the line
(`deposit_refund_command`, steps: Pet remainder 400, Pet Refund 300, `pet_remainder=STAFF`)
releases only S's 700 payment (the newest). E's reversal: swept S's Refund 300, Q's Refund 300,
Q's 400 payment 400; recoveries 300 and 300; the 400 reversed with nothing put back; the line owes
400, the Pet Deposit 0, nets 500 and 0, the ledger reconciles.

(b) Pet-damage reclassification (migration 105): the set-up of
`test_parts_applied_again_at_two_stages_follow_the_dl_032_order` up to the pet-damage
reclassification (the Pet-first 1,000 holds E's 600, then F's 400), then a second reclassification
of the same line to not pet damage with a Pet remainder step of 1,000 (`pet_remainder=STAFF`):
the Pet-first payment is reversed whole and paid again at the remainder stage. E's reversal:
swept S1's 700 (part 400) and Q's 1,000 (part 600), both reversed; put back 300 on the charge line,
then 400 on the other line, both at the remainder stage (S1's first, as the older); 1,000 owed
again; the Pet Deposit 0; the ledger reconciles.

## Review round 2 (fresh read-only subagents, during P2; told to write no file anywhere and run nothing)

Security: 0 blockers, 0 should-fix, 3 notes (the 100-step limit is per call, so total work grows
with a chain of return reversals inside the confirm's locks; it still aborts and writes nothing;
the put-back check is a sum check and relies on the cut stretches not overlapping each other,
which holds today; a time tie can only refuse, never misplace).

Independent: 0 blockers, 2 should-fix, notes. It traced both new real-path tests to the cent and
compared each changed committed test with HEAD (27 revision-only lines in 15 modules; the
`CHANGED` constant; five unused imports removed from the successor module; the two renamed tests
now allowed with exact parts, results, balances and reconciliation): nothing else weaker.
- Should-fix (test): no real-path test produced an open `CHANGED_APPLICATION` part end to end any
  more (the two renamed tests were the only ones). Fixed under the round-3 rule:
  `test_a_part_on_a_payment_a_receipt_correction_reversed_waits` (E's 1,000 in S's Pet Deposit
  payment, which a `DEPOSIT_RECEIPT_CORRECTION` reverses: one open part at that payment, E's
  reversal refused with the new message, nothing written).
- Should-fix (text): the plan and this record said a reversal by another correction kind cannot
  be reached; it can (`RETURNED_PAYMENT`, `DEPOSIT_RECEIPT_CORRECTION`, the 10e-3d-2c cases).
  Fixed.
- Notes: Deposit ties are broken by `application_order` before the id, so the Q-2026-10-14-111 tie
  affects Credit payments only (refusing on a tie is another option for the owner); the put-back
  mismatch or overlap, Q's extra effects and "past what Q paid out" stay untested backstops;
  BR-DEP-027 added to this record's rule IDs; cost grows with chain length.

## Review round 3 (fresh read-only subagents, during P3; told to write no file anywhere and run nothing)

Under the owner's round-3 rule of 2026-10-13 (round 2 had no blocker; both should-fix were a test
and a text change). U3 and P3 ran before the commit.

Security: 0 blockers, 0 should-fix. It checked the migration again (least privilege, definer
settings, no dynamic SQL, fail closed, bounded recursion, the recovery scope bound to the
server-built and digest-checked source), that the new test only reads and asserts nothing is
written on the refused path, and scanned the whole diff and the untracked files (no secret,
connection string or personal data). Notes: total work per confirm still multiplies with chain
length (cost, not safety); the refused-path counts leave out the reversal tables (enough: a refused
record writes only a draft and rolls back); add rounds 2 and 3 here (done).

Independent: 0 blockers, 0 should-fix. It traced the new receipt-correction test by hand through
the walk, the placed function and the follow function (one open part, nothing swept, the
completeness check holds, the first refusal is the new message), confirmed the text fixes, and
compared each changed committed test with HEAD again (27 revision-only lines in 15 modules; the
`CHANGED` string; the successor module's five unused imports and its renamed test; the own-parts
module's renamed test, which dropped `credit_applications == []` because it is no longer true and
now asserts the reversal list, the recovery, both own parts and reconciliation: stronger, not
weaker). Notes (text, fixed before the commit): "seven tests" in this record and docs/010 (eight);
docs/010 and the migration docstring do not list BR-DEP-027 (docs/010 fixed; the migration file is
left unchanged after P3); optional: the new test could also pin the open part's correction and
empty `own_parts`/`own_open`.
