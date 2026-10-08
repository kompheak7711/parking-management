# V1-056 sub-slice 10c-2b-1 — returned Credit Refund of a correction: review record

Sub-slice: 10c-2b-1 (migration `20261111_107`). Base commit: 065c67b (the 10c-2b pre-code design
and stop for Q-2026-10-08-55). Not committed (commit hash in ops/NOW.md once committed).

Rule IDs: BR-SETTLE-013, BR-CREDIT-006, BR-CREDIT-008, BR-CREDIT-014, BR-REFUND-014, DL-032,
BR-AUTH-010; owner answer 4 to the sub-slice 10c-1b review record (approved tightening), answer 4
to Q-2026-10-07-41, answers 1 and 2 to Q-2026-10-07-42, answers 1, 2 and 4 to Q-2026-10-08-55.

## Built

- Migration `20261111_107`:
  - Tightening: `app.require_correctable_usd_refund` refuses (P5202) a Refund with a
    `settlement_correction_refund_details` row, so the one-call verified return and the one-call
    reversal refuse a correction's Refund; `app.validate_general_refund_correction` refuses (23514)
    every row for such a Refund except the verified return of its own `REFUND_RETURN` correction
    (`app.settlement_refund_return_allowed`), which carries `financial.approve`.
  - New variant `REFUND_RETURN`: input check, source state, plan check, overlay, recorder
    (`final_settlements.prepare`), result, confirm (`financial.approve`, human, READ COMMITTED,
    draft lock, Settlement draft lock, Lease row `FOR UPDATE`, the shared lock function, stale
    checks, Refund methods `FOR SHARE`, `app.begin_settlement_correction`, the verified return
    linked first, the shared DL-032 step, the optional new Credit Refund with its details row,
    `SET CONSTRAINTS ALL IMMEDIATE`, audit). Grants: recorder and confirm to `prm_financial` only.
  - Relaxing: `app.settlement_correction_refund_allowed` also counts what the correction's own
    returns gave back to the Credit.
  - `app.lock_settlement_correction_plan`: the returned Refund's Credit joins the id-ordered
    Payment and Credit passes.
  - Only a correction's Credit Refund is accepted (`app.settlement_refund_return_settlement`); the
    Deposit Refunds are sub-slice 10c-2b-2.
- Service: `RecordRefundReturnCorrectionCommand`, `record_refund_return`,
  `confirm_refund_return` (P5S02 stale).
- Tests: new module `test_settlement_refund_return_migration.py` (6 tests, last in
  `scripts/database-test.sh`); 3 unit tests in `test_settlement_correction.py`; 26 head-revision
  assertions in 14 modules; 9 traceability entries appended.
- Docs: docs/004 (DB-SETTLE-005 and DB-REFUND-002 "As built" paragraphs), docs/010 (owner answers
  to Q-2026-10-08-55, the sub-slice entry with six choices for the owner, updated tests), the
  questions file (Q-2026-10-08-55 answered), the plan (answers and as-built note).

## Read-only search of every backend test

Tests that correct a Refund with one call or insert `refund_corrections` rows: only an 8f
`CREDIT_CUSTOMER` Refund (no correction details row) and the 8d Settlement Deposit Refund test
(refused before the new check, same code and message). Tests that read the source of a changed
function: the lock function's one Payment pass and one Credit pass (10c-2a-3) and the
`PET_DAMAGE_RECLASSIFICATION` branch (10c-2a-5) still hold; the 8d `require_correctable_usd_refund`
call keeps P5202 and its message; grants of the changed functions are unchanged. The 14
head-revision modules.

## Runs

Static checks, each in its own tool call: format check failed once (two new test files; cause:
format, correction 1 of 2), then clean; lint failed once (import order, an unused import and a long
line in the new test module; cause: lint, correction 1 of 2), then clean; type check clean.
Migration-only check (scratchpad copy of `scripts/database-test.sh` running `alembic upgrade head`):
first attempt failed with a syntax error (a `CASE ... THEN` inside a PL/pgSQL `IF` condition; cause:
migration syntax, correction 1 of 2: the CASE is now in parentheses); then 106 upgrades, head
`20261111_107`. Repeated before P3: 106 upgrades, head `20261111_107`.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U1 | backend unit, full (under `caffeinate -dims`) | 3628 passed, 1795 skipped (every skip a database URL reason), 1 warning (Starlette) | first run of 10c-2b-1 | `V1-056-slice-10c-2b-1-unit-test-run.txt` |
| P1 | PostgreSQL, full (under `caffeinate -dims`) | 5 failed, 1953 passed, 1 warning | cause A (migration): the input key check compared `array_agg(key ORDER BY key)` with a literal array, and the database collation sorts `returned_amount_usd_cents` before `return_method_reference`, so every valid input was refused; correction 1 of 2: `ORDER BY key COLLATE "C"` in both key checks | `V1-056-slice-10c-2b-1-full-test-run.txt` |
| P2 | PostgreSQL, targeted: the new module only (it is the only caller of the corrected function) | 1 failed, 5 passed | cause B (test): the test expected the original Refund's net value 500 after both returns; it is 0 (the 500 is the new Refund); correction 1 of 2: expectation 0 and the new Refund's net value 500 | `V1-056-slice-10c-2b-1-targeted-test-run-2.txt` |
| P3 | PostgreSQL, full (under `caffeinate -dims`) | 1958 passed, 1 warning (Starlette) | after the corrections of causes A and B | `V1-056-slice-10c-2b-1-full-test-run-3.txt` |

After each correction the static checks ran again, each in its own tool call (format, lint, type
check), clean.

## Review round 1 (2026-10-08; fresh read-only subagents, given the diff, the rule IDs, the owner answers, the takeover file and this record)

Independent: 0 blockers, 2 should-fix, 6 notes. Security: 0 blockers, 1 should-fix (the same test
gap as independent SF1), 6 notes. Both reviewers found no path that writes a return or a Refund for
a correction's Refund outside its confirmed `REFUND_RETURN` correction.

- SF1 (independent SF1, security SF1; fixed, test only): the relaxed check's conditions were not
  all tested and no test reached the trigger's refusal of a reversal row (the one-call reversal is
  refused earlier, P5202). `test_the_relaxed_refund_correction_check_accepts_nothing_else` now also
  tries, inside a correction confirmed by hand, a row with the draft's return date plus 1
  microsecond and a row naming another correction Refund than the draft's; after a real return, a
  `CORRECTION_REVERSAL` row of it, linked to a later correction and unlinked, under
  `financial.approve` and `refunds.corrections.reverse`; each refused (23514, the "only through a
  post-settlement correction" message), drafts pending. Not built: a Refund paid by a correction of
  another Settlement (security, "ideally"; it needs a second closed Lease; the condition is also
  covered by the link and draft conditions, which tie the row to one Settlement's correction).
- SF2 (independent SF2; fixed, test only): no database test of the new functions' own
  authorization refusals. The first test now calls the confirm with `final_settlements.prepare`
  (42501), the confirm by a billing service identity (P4506 "Invoice command requires an active
  human actor": a non-person actor has no active user account, so it is refused before the human
  check, which stays as defence in depth like every correction confirm), and the recorder with
  `financial.approve`, `refunds.correct` and no reference (42501); the draft stays pending.
- Security N3 (fixed): the service sent `returned_at` with the caller's offset; PostgreSQL refuses
  offsets of 16 hours or more (22009, which the service maps to "unavailable"). It now sends the
  instant in UTC; the unit test checks a +16:00 instant is sent as UTC.
- Security N4, independent N5 (fixed, text only): the confirm's lock comment and the plan note now
  say that after the Refund methods and `app.begin_settlement_correction` the Refund correction
  check locks the returned Refund row `FOR UPDATE` at the return's insert, and why that is safe.
- Independent N6 (fixed, test only): the Deposit Refund step refusal asserts its sqlstate and
  message.
- Independent N7 (fixed, text only): the docs/010 "Updated tests" sentence named only the 8f and 8d
  one-call returns; it now says the search covered Refunds paid by a Final Settlement or a
  correction, and that ordinary Refunds keep their one-call returns.
- Independent N8 (fixed, text only): this record now says the static checks ran again after each
  correction.
- Independent N3, security N2 (owner item, docs/010 choice (1)): the new Refund is what is left in
  the Credit after the step, at most the returned amount, the rule of the committed `REFUND`
  confirm (owner answer 2 to Q-2026-10-07-42, the same words "refunds only the rest"); when the
  Credit held other value, the debt may be paid from that value and the whole returned amount
  refunded. The total to the Customer is the same and no other Customer's money leaves. Kept for
  consistency with the `REFUND` confirm; the owner may ask for the stricter cap (the returned
  amount less what the step applied from this Credit).
- Independent N4 (plan, 11e item): the frontend reversal-context validator expects `refunds.correct`
  on the reversed return; a correction's return would show "invalid financial response" instead of
  a clear refusal (the backend refuses with P5202).
- Security N6 (known, 11e): the runtime-role draft reads of sub-slice 6b return the decision's
  transaction id; confirmed `REFUND_RETURN` drafts appear there too. Already in the plan for 11e.
- Security N7: owner answers 5 and 6 to Q-2026-10-08-55 (receipt reversal draft and Pet
  Refund-review Refund after closure) are sub-slice 10c-2b-2, before any push.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U2 | backend unit, full (under `caffeinate -dims`) | 3628 passed, 1795 skipped (every skip a database URL reason), 1 warning (Starlette) | review round 1 fixes | `V1-056-slice-10c-2b-1-unit-test-run-2.txt` |
| P4 | PostgreSQL, full (under `caffeinate -dims`) | 1958 passed, 1 warning (Starlette) | review round 1 fixes | `V1-056-slice-10c-2b-1-full-test-run-4.txt` |

Before P4: static checks clean, each in its own call; migration-only check 106 upgrades, head
`20261111_107`.

Round 1, security N5 (no database test of the confirm's own approver checks): answered by the SF2
fix above (it was the same point as independent SF2); security round 1 had 6 notes (N2 to N7), all
answered above.

## Review round 2 (2026-10-08; new fresh read-only subagents, independent and security)

Independent: 0 blockers, 1 should-fix, 4 notes. Security: 0 blockers, 0 should-fix, 6 notes. Both
confirmed every round-1 fix in the code. Under the standing rule (no blocker, at most 2 should-fix)
one round 3 follows, after the full unit and PostgreSQL runs below.

- SF1 (independent; fixed, text only): docs/005 API-066 did not say that its two routes now answer
  422 for a Refund paid by a post-settlement correction (and, since 8d, by a Final Settlement).
  API-066 gains an "Amended by" paragraph; docs/010 names it.
- Independent N2 (fixed, text only): the round-1 security note count; N5 now answered above.
- Independent N3 (plan, 11e): the "Record verified USD return" action is still offered for a
  correction's Refund and an 8d Settlement Deposit Refund and now answers 422; added to the 11e
  item.
- Independent N4 and security N3 (fixed, code and test): the relaxed check now also needs the
  draft's return method reference and evidence, and one return per correction; the test tries a
  row with another method reference, one with other evidence, and, inside one correction confirmed
  by hand, the draft's own return (it passes) followed by a second return (refused).
- Independent N5 (a) (fixed, test only): the "new Refund asked for, nothing left" branch: the first
  confirmed return of the debt test asks for a new Refund and pays none; a return-only correction
  and a last return with a partial Refund follow (800, 400, 800 of 2,000; charge 1,500 paid
  800 + 400 + 300; Refund 500). (b) (fixed, text only): the lock test's docstring says the Refund
  correction and Refund checks also lock that Credit, so the forward-only test pins the lock
  function's patch. (c) (fixed, test only): the three one-call refusals assert P5202 and its
  message.
- Security N1 (plan, slice 12; optional defence in depth, as in 10c-1b): when the new Refund goes
  to the payer the database does not check the "at most the returned amount" cap (the relaxed check
  runs only for a non-payer); the confirm's `LEAST` does.
- Security N2 (owner item, docs/010 choice (6)): a return recorded by mistake has no fix.
- Security N4 (fixed, code and test): an impossible return date or an offset PostgreSQL refuses is
  now 22023 (an exception block around the cast) instead of 22008 or 22009; tested directly.
- Security N5: no test of the "Refund of the correction's own Settlement" condition alone (it needs
  a second closed Lease); redundant today with the draft and link conditions.
- Security N6: the open owner and 11e items above, already tracked.

After the fixes, static checks each in its own call: format failed once (a missing blank line in
the new test module; cause: format, correction 2 of 2, the last for that cause), then clean; type
check failed once (a variable name reused with another exception type in the new test; cause: type,
correction 1 of 2), then clean; lint clean. Migration-only check: 106 upgrades, head
`20261111_107`.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| P5 | PostgreSQL, targeted: the new module only (a check before the full run) | 6 passed | review round 2 fixes | `V1-056-slice-10c-2b-1-targeted-test-run-5.txt` |
| U3 | backend unit, full (under `caffeinate -dims`) | 3628 passed, 1795 skipped (every skip a database URL reason), 1 warning (Starlette) | review round 2 fixes; the standing rule's unit run before round 3 | `V1-056-slice-10c-2b-1-unit-test-run-3.txt` |
| P6 | PostgreSQL, full (under `caffeinate -dims`) | 1958 passed, 1 warning (Starlette) | review round 2 fixes; the standing rule's PostgreSQL run before round 3 | `V1-056-slice-10c-2b-1-full-test-run-6.txt` |

## Review round 3 (2026-10-08; new fresh read-only subagents, independent and security; the standing rule's round 3)

Independent: 0 blockers, 0 should-fix, 4 notes. Security: 0 blockers, 0 should-fix, 4 notes. Both
confirmed every round-2 fix and found no new problem in them. No should-fix, so 10c-2b-1 is
committed (hash in ops/NOW.md).

- Independent N1 (carried into 10c-2b-2): the relaxed check binds every field of the return row to
  the draft except `reason`; defence in depth only.
- Independent N2, security N1 (carried into 10c-2b-2): the service raises `OverflowError` or
  `ValueError`, not `FinalSettlementInvalidError`, for an aware `returned_at` at the edge of the
  date range; no route until 11e.
- Independent N3 (fixed, text only): the plan's as-built note now names the round-2 bindings.
- Independent N4 (carried into 10c-2b-2): no test returns a correction's Deposit Refund through the
  10c-2b-1 form (refused 55000 today); 10c-2b-2 extends the function and tests it.
- Security N2 (slice 12, already listed): the payer cap is enforced by the confirm's `LEAST` only.
- Security N3 (11e, already listed): the runtime draft reads return the decision's transaction id.
- Security N4 (owner item, docs/010 choice (6)): a mistaken return has no fix; the "own Settlement"
  condition alone stays untested (redundant with the draft and link bindings).

Text fix after round 3 (plan only); no code or test changed, so no run after P6 and U3.

## For the owner

- docs/010 choice (1): the new Refund is the Credit's value left after the step, at most the
  returned amount (the committed `REFUND` rule); the stricter reading (the returned amount less
  what the step applied from this Credit) needs your answer.
- docs/010 choice (6): a return recorded by a correction is never reversed; a mistaken return
  needs a later correction kind.
- Owner answers 5 and 6 to Q-2026-10-08-55 are built in 10c-2b-2, before any push.
