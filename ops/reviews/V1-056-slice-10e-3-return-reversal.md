# V1-056 sub-slice 10e-3 — a return recorded by mistake (`RETURN_REVERSAL`): review record

Sub-slice: 10e-3 (migration `20261129_125`). Base commit: e9cbb85. Built in one session on
2026-10-12 and committed locally (see git log; the commit right after e9cbb85). Not pushed.

Rule IDs: BR-SETTLE-013, BR-SETTLE-016, DL-032, BR-REFUND-015, BR-CREDIT-008, BR-AUTH-010;
DB-REFUND-002, DB-SETTLE-005; owner answer (a) to Q-2026-10-08-57 and the Q-2026-10-11-78 rule
(the person who received the refund money pays it back). Design: ops/V1_056_PLAN.md (the "10e-3
pre-code design" and "10e-3 as built" bullets).

The same commit records the owner answers of 2026-10-12 to Q-2026-10-12-92 (sub-slice 10e-2b-4,
both Deposit types, under `payments.allocate`, no draft) and Q-2026-10-12-93 (a), and opens
Q-2026-10-12-94 (who pays back a Deposit Refund paid to an agreed Signer) and Q-2026-10-12-95 (a
reversal whose uses to undo are more than its return brought back); each new question blocks only
its own case, which is refused until answered.

## Built

- Migration `backend/migrations/versions/20261129_125_settlement_return_reversal.py`:
  - New functions: the recorder `app.record_settlement_return_reversal_draft`
    (`final_settlements.prepare`) and the confirm `app.confirm_settlement_return_reversal`
    (`financial.approve`, a person, READ COMMITTED), both granted to `prm_financial` only; eight
    internal functions with no grant (input, the users of a return, the source state, the
    refusals, the named Deposit application reversal writer, the reversal row check, the recovery
    scope check, the result).
  - Exact-text patches: `app.validate_general_refund_correction` (the linked reversal row; the
    reversal branch reads every Deposit Refund's source by `source_deposit_id`),
    `app.refund_recovery_allowed` (the recovery context of a `RETURN_REVERSAL`),
    `app.write_payment_return_recoveries` (the charge wording), `app.lock_settlement_correction_plan`
    (the branch), `app.settlement_held_deposit_value` and `app.settlement_held_credit_value` (a
    reversed return leaves nothing).
- Service: `RecordReturnReversalCorrectionCommand`, `SettlementCorrectionService.record_return_reversal`
  and `confirm_return_reversal`, `RETURN_REVERSAL_CONFIRM_STALE_STATES`.
- Tests: new PostgreSQL module `backend/tests/test_settlement_return_reversal_migration.py` (7 tests,
  last in `scripts/database-test.sh`); three unit tests in `backend/tests/test_settlement_correction.py`.
- Changed committed tests (owner standing rule of 2026-10-11): only the 27 head-revision assertions
  in 15 modules (`20261128_124` to `20261129_125`). No fixture changed.
- `ops/traceability.json`: ten entries appended. docs/004 (DB-SETTLE-005, DB-REFUND-002), docs/010,
  the plan, ops/V1_056_QUESTIONS.md, ops/NOW.md.

## Runs

Static checks, each in its own call, with the repo scope (`src tests`), and the new migration file
on its own: lint, format and mypy clean every time (no correction). Migration-only check
(`scripts/migration-check.sh`): 124 upgrades, head `20261129_125`, before T1 and again after the
round 1 code changes, before T3. Read-only search of every backend test for the patched functions
and the general check's messages: the behaviour changes reach only rows linked to a
`RETURN_REVERSAL` correction (a new path); catalog tests of earlier migrations compare fixed
revisions; the modules that exercise the changed branches are in T1 (the patched functions also
run in every correction confirm and in the returned-Payment and receipt correction modules, all in
the full runs P1 and P2).

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U0 | backend unit, the new unit tests only | 18 passed | quick check | not saved |
| T1 | PostgreSQL targeted: new module, refund return, held value, Deposit refund return, Pet refund return, payment return recovery, refund modules | 84 passed, 1 failed | first run | `V1-056-slice-10e-3-targeted-test-run.txt` |
| T2 | PostgreSQL targeted: new module | 6 passed | test-order cause A, correction 1 of 2 | `V1-056-slice-10e-3-targeted-test-run-2.txt` |
| U1 | backend unit, full (caffeinate) | 3802 passed, 1927 skipped, 1 warning (known) | first full unit run | `V1-056-slice-10e-3-unit-test-run.txt` (excerpt) |
| P1 | PostgreSQL full (caffeinate) | 2091 passed, 3 warnings (known kinds) | first full run | `V1-056-slice-10e-3-full-test-run.txt` |
| T3 | PostgreSQL targeted: new module | 7 passed | review round 1 fixes (code and tests) | `V1-056-slice-10e-3-targeted-test-run-3.txt` |
| U2 | backend unit, full (caffeinate) | 3802 passed, 1928 skipped, 1 warning (known) | review round 1 fixes | `V1-056-slice-10e-3-unit-test-run-2.txt` (excerpt) |
| P2 | PostgreSQL full (caffeinate) | 2092 passed, 1 warning (known) | review round 1 fixes | `V1-056-slice-10e-3-full-test-run-2.txt` |

T1's failure (cause A, my test's order): in the two-Signer test the reversal's 1,000 recovery
charge was open Lease debt, so the later held-value Refund to the second Signer was refused before
the Q-94 refusal was reached; the agreed-Signer part now runs before the first reversal. P1's two
extra warnings are the known pydantic `UnsupportedFieldAttributeWarning` kind in
`test_credit_refund_api_migration.py` (not touched by this slice; P2 shows only the Starlette
warning, so they depend on test order). The unit-run files are excerpts (every line except the
SKIPPED lines); the full outputs are in `~/Development/prm-run-logs/`. Secret check of every
output: no database URL, no `password=`, no 64-character hex string. They show the local home path
in a pytest warning, as earlier records do. After P2 only text changed (docs, questions, plan,
traceability notes, this record).

## Review round 1 (fresh read-only subagents, during P1)

Independent: 0 blockers, 3 should-fix, 5 notes. Security: 0 blockers, 1 should-fix, 6 notes.

Fixed:
- Independent SF1: a reversal could charge back more than its return brought back, when a
  `REFUND_RETURN` with a new Refund also paid out money its source already held (BR-SETTLE-008
  sweeps every DL-032 balance). Refused (55000) until the owner answers the new Q-2026-10-12-95;
  tested on the real path (1,000 return only, then 500 with a 1,500 Refund).
- Independent SF2: a database guards test (malformed input 22023, the recorder and confirm
  authorization strings 42501, a service identity P4506, READ COMMITTED 55000, another Settlement
  P0002, nothing written); the recorder replay; a reversal row written inside the correction before
  the undo is refused by the new `source_deposit_id` branch.
- Independent SF3: docs/004 (the old "No row reverses such a return" sentence; the 10e-3 paragraph
  in DB-SETTLE-005 and the DB-REFUND-002 paragraph), docs/010 (entry and "Updated tests"), the
  plan's as-built bullet.
- Security SF-1: a recovery of a Refund the reversed correction did not pay, written inside the
  draft's own hand-begun correction, is refused (tested).
- Security notes taken as hardening: the availability check refuses a missing value; the recovery
  scope check also requires the Refund in the draft's recorded recoveries with the Deposit's own
  Customer as recipient; the confirm checks that the stored payload names exactly what its source
  reads (P0002).

Answered in writing (docs/010): Staff confirming is refused by the service and the confirm's
authorization string, as every correction (`prm_financial` is the trust boundary); the over-undo
case is Q-95; the lock function reads the source twice (time only); the no-Lease recovery is the
10e-1c path, tested there; a preparer who also holds `financial.approve` may confirm their own draft
(the known slice 12 item).

## Review round 2 (fresh read-only subagents, during P2)

Security: 0 blockers, 0 should-fix, 5 notes; every round 1 item resolved. Independent: 0 blockers,
1 should-fix, 3 notes; every round 1 item resolved; it compared every changed committed test with
HEAD (27 head-revision lines in 15 modules) and found nothing weaker; traceability only appended.

Fixed (text only): independent SF1, the docs/010 entry did not name the Q-95 refusal; the stale
sentence in Q-94; docs/004 names the recovery check's recorded-recoveries condition.

Listed in docs/010 (slice 12): the "reverse that later return first" refusal also stops a reversal
whose new Refund was partly returned for real, and a later return of the whole new Refund leaves
that later correction's left value counting money its source no longer holds (no money moves); the
untested recorder READ COMMITTED refusal, the Deposit form of "no longer available" and a hand-built
recovery of a paid but unlisted Refund; the reversal check does not itself require the undo first
(owner-only begin and link functions); it relies on `app.begin_settlement_correction` for the
approver, as the `REFUND_RETURN` check does; a returned Credit whose Payment is no longer RECEIVED
fails closed with an unmapped 23514.

## Review round 3 (owner standing rule; U2 and P2 ran on the final code before it)

Independent: 0 blockers, 0 should-fix, 4 notes (text only); it checked the rules, the capability
checks, the SQL, the 27 head-revision lines, traceability (all 2,990 earlier entries identical, 10
appended) and every run count against this record. Fixed as text: this record's T1 sentence; Q-95
option (b) now reads "as designed, without the refusal"; the plan's as-built bullet names the
charge wording ("paid from value a mistaken Refund return brought back" instead of the design's
"paid from a Refund return recorded by mistake"); ops/NOW.md is in the commit's paths.
