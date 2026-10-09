# V1-056 sub-slice 10c-2b-3 — the refund-only form HELD_VALUE_REFUND: review record

Sub-slice: 10c-2b-3 (migration `20261114_110`). Base commit: ab434af. Not committed (commit hash in
ops/NOW.md once committed).

Rule IDs: BR-SETTLE-008, BR-SETTLE-013, BR-CREDIT-006, BR-CREDIT-008, BR-CREDIT-014,
BR-REFUND-014, BR-REFUND-015, DL-032, BR-AUTH-010; owner answer 3 to Q-2026-10-07-42, answers 1, 2
and 4 to Q-2026-10-08-55, answer 2 to Q-2026-10-08-59. Pre-code design: ops/V1_056_PLAN.md (10c
entry, "10c-2b-3 pre-code design").

## Built

- Migration `20261114_110`:
  - New: `app.record_settlement_held_value_refund_draft` (recorder, `final_settlements.prepare`)
    and `app.confirm_settlement_held_value_refund` (confirm, `financial.approve`), executable only
    by the financial role; internal helpers `app.settlement_held_credit_value`,
    `app.settlement_held_credit_left`, `app.settlement_held_value_input`,
    `app.settlement_held_value_source_state`, `app.settlement_held_value_plan` (no role).
  - Patched: `app.lock_settlement_correction_plan` takes the held Credit in its id-ordered passes;
    `app.settlement_correction_refund_allowed` counts what the earlier correction left in the
    Credit (BR-CREDIT-014).
  - The result reuses `app.settlement_refund_return_result`.
- Service: `RecordHeldValueRefundCorrectionCommand`, `record_held_value_refund`,
  `confirm_held_value_refund` (stale P5S02).
- Tests: new module `test_settlement_held_value_refund_migration.py` (6 tests); 3 unit tests; 27
  head-revision assertions; 9 traceability entries.
- Docs: docs/004 (DB-SETTLE-005), docs/010 (the sub-slice entry with four choices, updated
  tests), the plan (pre-code design).

## Read-only search of every backend test

The tests that read the lock function's source count its Payment and Credit lock passes (one
each); the patch adds a Credit to the existing array, no pass. The direct calls of the relaxed
Credit Refund check use REFUND corrections, for which the new term is 0. The forward-only tests of
earlier revisions upgrade to their own revision. No function list at head is pinned. The 27
head-revision assertions move to `20261114_110`.

## Runs

Static checks each in its own call. Lint failed once (cause D, import order in the unit test
module; correction 1 of 2), then clean; format and type check clean. Migration-only check
(throwaway copy of `scripts/database-test.sh`): 109 upgrades, head `20261114_110`.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| T1 | PostgreSQL, targeted: the new module (a check before the full run) | 1 failed, 5 passed | cause E (test): the off-DL-032 test counted every held-value draft of the shared database, not only this Settlement's; correction 1 of 2 | `V1-056-slice-10c-2b-3-targeted-test-run.txt` |
| U1 | backend unit, full (under `caffeinate -dims`) | 3652 passed, 1817 skipped, 1 warning (Starlette) | first unit run | `V1-056-slice-10c-2b-3-unit-test-run.txt` |
| P1 | PostgreSQL, full (under `caffeinate -dims`) | 1980 passed, 1 warning (Starlette) | first full run, after cause E | `V1-056-slice-10c-2b-3-full-test-run.txt` |

## Review round 1 (2026-10-09; fresh read-only subagents, independent and security)

Independent: 0 blockers, 4 should-fix, 6 notes. Security: 0 blockers, 2 should-fix, 4 notes. They
overlap; no fix is made yet. STOPPED for the owner (Q-2026-10-09-63): two findings decide what
"linked to that correction" limits.

- Independent SF1, security N3 (owner point 1): the Deposit form does not check what the named
  earlier correction itself left, so the same correction can be named again after its own money is
  gone (attribution only; no overpayment). The same holds for a Credit correction whose Credit is
  empty when the plan has other steps (security N5).
- Independent SF2, security SF1 (tests): the cap "at most what the earlier correction left" is
  never the binding limit in a test (every Credit holds exactly what was left), and the relaxed
  check is never asked to refuse an amount.
- Independent SF3, security SF2 (b) to (e) (tests): database-level guards of the two definer
  functions (authorization, non-human approver, REPEATABLE READ, malformed input, key reuse,
  replay) and a NOWAIT check of the lock patch.
- Independent SF4, security SF2 (a) (test): a return-only correction of another Settlement named
  in this Settlement's draft (P0002).
- Notes, owner point 2: choice (1), whether value used through the ordinary Credit paths lowers
  what the earlier correction left (independent N6), and whether this correction's own step
  applications lower the cap (security N4).
- Notes, docs: the plan's design text differs from the code (the left value also subtracts the
  linked corrections' Credit applications; only the Credit form has the record-time "writes
  nothing" check; independent N5); choice (2) also applies to the Credit form, untested
  (independent N7); choice (4) is untrue until the point 1 gate exists.
- Notes, code: the audit event's `customer_id` of a Deposit correction is the earlier Refund's
  recipient (independent N9, security N6); one correction may carry two Refund recipients, as in
  `REFUND_RETURN` (independent N8); method and note are required even when nothing is refunded
  (independent N10); the future `RETURN_REVERSAL` must make the left value subtract reversed
  returns (independent N6).

## Owner answers to Q-2026-10-09-63 (2026-10-09) and the round 1 fixes

Owner: point 1 option (a) (an earlier correction is named only while it still has value left;
docs/010 says how it is counted; a test that naming it again changes nothing); point 2 keep as
built, a known limit in docs/010. Recorded in docs/010 and ops/V1_056_QUESTIONS.md.

- Code (migration `20261114_110`, not committed, so changed in place): new internal
  `app.settlement_held_deposit_value(uuid,uuid)` (the Deposit's value left: the earlier
  correction's return less the Deposit applications and Refunds from that Deposit of the linked
  `HELD_VALUE_REFUND` corrections); `app.settlement_held_value_plan` refuses with 55000 a Deposit
  correction with nothing left and a Credit correction whose Credit holds nothing, also with other
  steps; the source digest holds the Deposit's value left; the draft's `customer_id` of a Deposit
  correction is the Deposit's owner and the confirm's audit event names the recipient of the step's
  Deposit Refund (or the owner when nothing was refunded); the audit event lists every Deposit
  balance the step settled (`settled_deposits`, from option (a) as written).
- Tests (new module, now 9 tests): every round-1 test item (cap binding twice, the relaxed check
  refusing 1 cent, E's own step paying debt, P0002 for another Settlement, the database guards, the
  NOWAIT row locks, the Q-59 answer 2 path), the owner's test for point 1, the empty-Credit
  refusal with a Deposit Refund step, the audit `customer_id` on a two-Signer Settlement.
- Docs: docs/010 (owner answers, known limit, choices (2) and (4) reworded, updated tests), docs/004
  (the gates), traceability (3 new entries; the new entries' notes updated).

## Runs after the owner answers

Static checks each in its own call: lint failed once (cause F, import order in the new PostgreSQL
test module; correction 1 of 2), then clean; format and type check clean. Migration-only check
before P2 and before P3: 109 upgrades, head `20261114_110`. Read-only search of every backend test:
only the new module uses the changed functions; the head-revision assertions are unchanged.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U2 | backend unit, full (under `caffeinate -dims`) | 1 failed, 3651 passed, 1820 skipped | cause G: three new tests had no traceability entry (`test_traceability_manifest_covers_executable_tests`); correction 1 of 2 | `V1-056-slice-10c-2b-3-unit-test-run-2.txt` |
| U3 | backend unit, full | 3652 passed, 1820 skipped, 1 warning (Starlette) | after cause G | `V1-056-slice-10c-2b-3-unit-test-run-3.txt` |
| P2 | PostgreSQL, full (under `caffeinate -dims`) | 1983 passed, 1 warning (Starlette) | the round-1 fixes | `V1-056-slice-10c-2b-3-full-test-run-2.txt` |
| U4 | backend unit, full | 3652 passed, 1820 skipped, 1 warning | standing round-3 rule, after the round-2 test fixes | `V1-056-slice-10c-2b-3-unit-test-run-4.txt` |
| P3 | PostgreSQL, full | 1983 passed, 1 warning | standing round-3 rule, after the round-2 test fixes | `V1-056-slice-10c-2b-3-full-test-run-3.txt` |

## Review round 2 (2026-10-09; fresh read-only subagents, independent and security)

Both reviewers found every round-1 item fixed or answered. Independent: 0 blockers, 1 should-fix,
6 notes. Security: 0 blockers, 0 should-fix, 7 notes. Under the standing rule (no blocker, at most
2 should-fix) one round 3 follows, after U4 and P3.

- Independent SF-1 (both reviewers, security N1): the NOWAIT check of the Credit row would pass
  without the lock function's patch, because the Refund insert locks the Credit too. Fixed: the
  stale second draft now waits for a Credit row another session holds (`lock_timeout`, 55P03)
  before its stale check; without the patch it would be reported stale at once. The same weakness
  in the committed 10c-2b-1 test goes to the slice 12 list (docs/010).
- Independent N-1, security N3 (docs/010): at the confirm a used-up value makes the draft stale
  (P5S02), so the 55000 check there is a backstop. Fixed (docs/010).
- Independent N-2 (test): the audit test could not tell the recipient from the Deposit's owner.
  Fixed: a second return is paid to the Signer with the agreement; the audit names the Signer, the
  draft the owner.
- Independent N-3, security N4 (docs): the plan's as-built line, docs/010 choice (2) and docs/004.
  Fixed (docs/010, docs/004; the plan's as-built line is written with the commit).
- Security N6 (test): owner choice (a) of point 2 was not pinned. Fixed: test 1 now returns 1,800
  and 200; the step pays 1,500 and the Refund is 500 (the stricter rule would give 300).
- Independent N-4 (code hardening, an explicit Deposit branch): not changed; `REFUND_RETURN`
  returns only Credit and Deposit Refunds (`settlement_refund_return_settlement`), so the branch is
  unreachable for any other source.
- Independent N-5, security N2: the human-approver check is defence in depth (P4506 fires first),
  as in the other variants; written in docs/010.
- Security N7: the record-time "writes nothing" check is now a backstop; kept and documented.
- Independent N-6, security N5: P2 was still running when they read it; it passed (1983).

## Review round 3 (2026-10-09; standing round-3 rule, after U4 and P3; fresh read-only subagents)

Independent: 0 blockers, 0 should-fix, 3 notes. Security: 0 blockers, 0 should-fix, 4 notes. Both
confirm the round-2 fixes (the lock-patch test fails without the patch; the audit test tells the
recipient from the owner and from the earlier recipient; the owner answer 2 pin gives 500 against
300). Round 3 passes; the commit follows.

- Independent N1 (docs/010 choice (2): "refunds" too narrow, the step may apply the money to debt)
  and N2 (docs/010 answer (1) and docs/004: at the confirm this correction's own records are left
  out of the Credit cap): fixed as text after the runs; no test reads these documents.
- Independent N3: the comment before `app.settlement_held_value_plan` says "what it left in the
  Credit", though it returns the value left for the Deposit form too. Not changed (a migration
  comment; changing the migration after the green runs would need a new run); slice 12 list.
- Security N1 and N3: the known limits of owner answers 1 and 2 (docs/010); no escalation found.
- Security N2: a REPEATABLE READ recorder can pass the value-left gate on an old snapshot; its draft
  can never be confirmed (the digest is compared under the locks), so it fails closed; slice 12
  list.
- Security N4: the unreachable non-Credit, non-Deposit branch (as round 2 N-4); no change.
