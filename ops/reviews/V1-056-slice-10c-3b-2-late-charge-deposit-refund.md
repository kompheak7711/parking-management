# V1-056 sub-slice 10c-3b-2 — REFUND of a Deposit-paid Late-payment Charge: review record

Sub-slice: 10c-3b-2 (migration `20261118_114`). Base commit: 2b5f7c9. Not committed (commit hash in
ops/NOW.md once committed).

Rule IDs: BR-SETTLE-013, BR-SETTLE-008, BR-LATE-005, BR-CREDIT-014, BR-REFUND-014, DL-032,
BR-AUTH-010; owner answer 1 to Q-2026-10-09-66, the owner answer to Q-2026-10-07-46,
Q-2026-10-07-41 answers 1 and 2, Q-2026-10-07-42 answers 1 and 2. Pre-code check:
ops/V1_056_PLAN.md (10c entry, "10c-3b-2 pre-code check"; "10c-3b-2 as built").

## Owner rules given at the start of the session (2026-10-09)

- Two run rules written in ops/V1_055_RUN_RULES.md: a full PostgreSQL run again before the commit
  when any code, migration or test file changed after the last full run (text-only changes may
  skip it, as in the Q-44 and Q-67 answers); every run output checked for passwords and other
  secrets before it goes into a repo file.
- The 10c-3b-1 VOLATILE change came after its full run; the first full run of 10c-3b-2 (P1) covers
  it.

## Built

- Migration `20261118_114`:
  - New internal `app.settlement_correction_charge_correction_allowed(uuid,uuid,uuid)` (no role;
    the twin of `app.settlement_correction_adjustment_allowed`).
  - Patched (exact text, relaxing; owner, SECURITY DEFINER, settings and grants kept): the 8a-1
    refusal `app.refuse_deposit_applied_obligation_change()` (its Charge branch lets through only a
    Charge correction linked to a correction of its Charge's own Settlement, confirmed in this
    transaction by that correction's approver); the plan `app.settlement_late_charge_refund_plan`
    (the Deposit refusal removed; a Deposit source keeps `application_usd_cents`); the confirm
    `app.confirm_settlement_late_charge_refund` (the Deposit application reversal branch in Phase 1,
    the Credit-application branch names its kind, the reversals in the confirmed audit, comments).
- No service, route or table change.
- Tests: new module `test_settlement_late_charge_deposit_refund_migration.py` (5 tests); the 27
  head-revision assertions move to `20261118_114`; one changed expectation in the committed 10c-3b-1
  test (see below); 5 traceability entries and one traceability note updated.
- Docs: docs/004 (the 8a-1 text of DB-DEP-005 and the DB-SETTLE-005 as-built paragraph), docs/010
  (sub-slice entry, updated tests), the plan (as built).

## Read-only search of every backend test

- 27 head-revision assertions in 15 modules (26 in 14 modules and the 10c-2b-1 module's head
  assertion): only the expected revision changes.
- `test_the_refund_is_refused_for_unpaid_too_large_deposit_paid_or_other_lease_charges`
  (10c-3b-1): expected the Deposit-paid refusal "until sub-slice 10c-3b-2"; one expectation changed
  under the run rule for historical tests (name kept, a short comment, docs/010 note).
- Still true, unchanged: `test_deposit_application_reversal_migration.py` (P4603 for a linked Charge
  correction written by an actor who is not the correction's approver), `test_final_settlement_migration.py`
  (P4603 for an unlinked row), the 10c-3a Deposit-paid reduction refusal, the 10c-3b-1 head-level
  source checks of the confirm and plan (no `age(`, intervals of one microsecond only), and every
  forward-only test (each upgrades only to its own revision).

## Runs

Static checks each in its own call: lint, format and type check clean (before T1, after the T1
correction, after the fifth test). Once, after the fifth test, lint ran in the same call as a JSON
syntax check of ops/traceability.json and a `git diff --stat`; lint then ran again alone (clean).
Migration-only check (throwaway copy of `scripts/database-test.sh` running `alembic upgrade head`):
113 upgrades, head `20261118_114`; the dumped bodies of the patched refusal and plan were read.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| T1 | PostgreSQL, targeted: the new module (4 tests) and the changed 10c-3b-1 test | 4 passed, 1 failed | first run | `V1-056-slice-10c-3b-2-targeted-test-run.txt` |
| T2 | PostgreSQL, targeted: the failed test | 1 passed | T1 cause A | `V1-056-slice-10c-3b-2-targeted-test-run-2.txt` |
| U1 | backend unit, full (under `caffeinate -dims`) | 3679 passed, 1845 skipped, 1 warning (Starlette) | first unit run | `V1-056-slice-10c-3b-2-unit-test-run.txt` |
| P1 | PostgreSQL, full (under `caffeinate -dims`) | 2008 passed, 2 warnings (Starlette; the known Pydantic alias warning, slice 12) | first full run; also covers the 10c-3b-1 VOLATILE change | `V1-056-slice-10c-3b-2-full-test-run.txt` |
| T3 | PostgreSQL, targeted: the fifth test (added after P1) | 1 passed | new test | `V1-056-slice-10c-3b-2-targeted-test-run-3.txt` |

Failure causes:

- T1 cause A (test expectation): the mixed-Charge test expected the Credit application's
  `target_kind` `INVOICE_LINE`; a Credit application on an Invoice line records `INVOICE`
  (correction 1 of 2).

Secret check (owner run rule): every run output above was searched for database URLs with a
password, `password=` and 64-character hex strings; none found.

The fifth test changed a test file after P1, so a full PostgreSQL run follows before the commit
(owner run rule).

## Review round 1 (2026-10-10; fresh read-only subagents, independent and security; after T3)

Independent: 0 blockers, 0 should-fix, 7 notes. Security: 0 blockers, 0 should-fix, 3 notes. Both
traced every path to a Charge correction on a Deposit-paid Charge; the allow function is the exact
twin of the Adjustment one plus the Charge join; unlinked rows are stopped first by 8e-1 (P5S01);
the reversal stamp meets every check of `app.validate_deposit_application_reversal`; the
validator's locks are already held by the lock function; each new test fails without its patch;
the changed committed test differs from HEAD by one expected message and text only.

- Independent N1 (the migration docstring lists BR-DEP-014, the other records BR-CREDIT-014 and
  BR-REFUND-014): fixed (docstring only).
- Independent N2 (no test proves three conditions of the allow function: the correction's own
  Settlement, a closed Settlement, `financial.approve` on the decision): not changed; the 8e-1
  refusal already requires a link to a correction of the same closed Settlement in the
  transaction, and the Adjustment twin has the same gap. Slice 12 list: direct tests of these
  conditions for both allow functions.
- Independent N3 (test 3 claims BR-REFUND-014 but asserts no method or note): fixed, both Refunds'
  method and note are asserted.
- Independent N4 (fixture docstring said the Primary Tenant still owes 80,000 of Rent): fixed
  (text).
- Independent N5 (docs/004 DB-DEP-006 still said no writer exists; the 10c-3b-2 paragraph did not
  name the allow function): fixed (text).
- Independent N6 (the fifth test is covered only by T3; the owner rule needs a full run before the
  commit): agreed; P2 follows.
- Independent N7 (lint once joined with other commands): recorded above; for the owner.
- Security N1 (the allow function is not tied to a correction variant or to the draft's own
  Charge; the 10c-3a confirm is held back only by its plan check): not changed; owner choice (1) in
  docs/010. For the owner: optional hardening (require the correction's draft to have
  `target_kind` `LATE_PAYMENT_CHARGE` and to name this Charge), for both allow functions in slice 12
  or with the next correction kind that links a Charge correction.
- Security N2 (a partly released Deposit application is reversed whole, so the Customer's Credit
  pays its rest first and more of the Deposit than was released can be refunded): as designed
  (choice (2) of 10c-2a-3; Credit before Deposits, Q-42 answer 1); now stated as choice (4) in the
  docs/010 entry.
- Security N3 (a failing assertion would print the database URL with its throwaway password): the
  suite-wide pattern already on the slice 12 list (10c-3b-1 security round 2, note 1); every run
  output of this sub-slice was scanned before it went into the repo (owner run rule).

Fixes after round 1: one test assertion added (test 3), the rest text only (migration docstring,
test docstring, docs/004, docs/010, this record). Static checks each in its own call: format
failed once (cause B, the wrapping of the new assertion; correction 1 of 2, the formatter's layout
applied by hand), then lint, format and type check clean. Migration-only check again (the
docstring changed): 113 upgrades, head `20261118_114`.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| T4 | PostgreSQL, targeted: the mixed-Charge test | 1 passed | round-1 assertion | `V1-056-slice-10c-3b-2-targeted-test-run-4.txt` |
| U2 | backend unit, full (under `caffeinate -dims`) | 3679 passed, 1846 skipped, 1 warning (Starlette) | traceability changed after U1 | `V1-056-slice-10c-3b-2-unit-test-run-2.txt` |
| P2 | PostgreSQL, full (under `caffeinate -dims`) | 2009 passed, 3 warnings (Starlette; two instances of the known Pydantic alias warning, slice 12) | the fifth test and the round-1 assertion changed a test file after P1 (owner run rule) | `V1-056-slice-10c-3b-2-full-test-run-2.txt` |

Secret check of T4, U2 and P2 (owner run rule): no database URL with a password, no `password=`,
no 64-character hex string.

## Review round 2 (2026-10-10; fresh read-only subagents, independent and security; during P2)

Independent: 0 blockers, 1 should-fix, 2 notes. Security: 0 blockers, 0 should-fix, 3 notes. Both
accepted every round-1 answer and found no other path.

- Independent SF1 (the round-1 N5 fix listed the writers of `deposit_application_reversals` but
  left out the pet classification correction confirm of 10c-2a-5): fixed (docs/004 text); the only
  inserts are in migrations 103, 105 and 114.
- Independent N1 (choice (4) said each Refund recipient passes BR-REFUND-015; that rule covers the
  Deposit Refund recipient): fixed (docs/010 text: the Deposit Refund recipient passes BR-REFUND-015,
  each Credit Refund goes to its Credit's Customer).
- Independent N2 and security N3 (the Runs table stopped at T3): fixed above.
- Security N1 (owner choice (1) accepted; the allow function also does not check the Charge
  correction row's own `correlation_id` or `authorization_reference`; safe today because the 10c-3a
  confirm re-runs its plan, which refuses a Deposit-paid Charge, and a `CHARGE_REVERSAL` releases
  every source): added to the optional hardening for the owner (require `NEW.correlation_id` to be
  the correction and a draft with `target_kind` `LATE_PAYMENT_CHARGE` naming this Charge, in both
  allow functions).
- Security N2 (choice (4) accepted: money is conserved; the confirm re-checks the plan on the real
  state and compares the whole recorded result): no change.

The round-2 fixes are text only (docs/004, docs/010, this record); no PostgreSQL test reads them,
so P2 stands (owner answers to Q-2026-10-07-44 and Q-2026-10-09-67). Standing round-3 rule: round 2
has no blocker and one should-fix, so one round 3 follows, after a full backend unit run (the
docs changed after U2) and with P2 as the full PostgreSQL run of the code under review.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U3 | backend unit, full (under `caffeinate -dims`) | 3679 passed, 1846 skipped, 1 warning (Starlette) | standing round-3 rule, after the round-2 text fixes | `V1-056-slice-10c-3b-2-unit-test-run-3.txt` |

Secret check of U3: none found.

## Review round 3 (2026-10-10; fresh read-only subagents, independent and security; standing rule)

Independent: 0 blockers, 0 should-fix, 5 notes. Security: 0 blockers, 0 should-fix, 3 notes (it
also scanned every 10c-3b-2 run output: no secret). Round 3 passes; the commit follows.

- Independent N1 (the plan's as-built point (3) spoke of two "never a source" comments; the second
  patched comment is the 8e-1 comment, now naming 8a-1): fixed (plan text).
- Independent N2 (DB-DEP-006 said the rest of a partly released Deposit application is applied
  again only as a Deposit step; under Credit before Deposits the Customer's Credit may pay it
  first): fixed (docs/004 text).
- Independent N3 (P2 counted as the full PostgreSQL run before round 3: it ran during round 2,
  finished before round 3, and only text changed after it): for the owner to confirm this reading;
  earlier sub-slices ran a fresh full run after round 2 because code changed there.
- Independent N4 (three deferred items were only in this record): added to the plan's Slice 12
  list.
- Independent N5 (after closure the unpaid rest of a partly Deposit-paid Charge cannot be reduced
  on its own, as for an Invoice line): by design; now stated in the docs/010 entry.
- Security N1 and N2 (owner choice (1) and choice (4) acceptable; the hardening stays optional and
  should come before any new writer links a Charge correction): recorded in the plan's Slice 12
  list.
- Security N3 (the Deposit reversal branch is a plain `ELSE`, as the Invoice-line form; fails
  closed because the sources are recomputed under locks and compared with the draft): no change.

Fixes after round 3: text only (docs/004, docs/010, the plan, this record). No PostgreSQL test
reads them; static checks and one unit run follow (as the owner answers to Q-2026-10-07-44 and
Q-2026-10-09-67).

Static checks each in its own call: lint, format and type check clean.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U4 | backend unit, full (under `caffeinate -dims`) | 3679 passed, 1846 skipped, 1 warning (Starlette) | round-3 text fixes | `V1-056-slice-10c-3b-2-unit-test-run-4.txt` |

Secret check of U4: none found. Committed next (commit hash in ops/NOW.md).

## Owner answers to the report (2026-10-10; Q-2026-10-10-69, docs/010)

- Round 3 N3: the owner confirmed the reading: P2 counts as the full PostgreSQL run before round 3.
- Security N1 and N2: choice (4) accepted; the optional hardening stays on the slice 12 list, and
  any sub-slice that adds a new writer that links an Adjustment or a Charge correction does it
  first.
- Round 3 N5: the owner asked whether the unpaid rest of a partly Deposit-paid Charge can still be
  reduced after closure; no path reduces only that rest (Q-2026-10-10-70, for the owner before
  10h).
- Changed committed test, compared with its version at 0139619 (owner answer 5; read-only,
  2026-10-10). Round 1 compared it with HEAD 2b5f7c9; `git log 0139619..4710bdf` shows that only
  cc01b84 changed `backend/tests/test_settlement_late_charge_refund_migration.py`, so HEAD and
  0139619 held the same version. `git diff 0139619 4710bdf` on that file: in
  `test_the_refund_is_refused_for_unpaid_too_large_deposit_paid_or_other_lease_charges` one
  expected message changes from "A Deposit application paid this obligation at Final Settlement"
  to "Every remaining Deposit balance must be applied or refunded", with a two-line comment; the
  test docstring and the module docstring change their text. The SQLSTATE 55000, the unchanged
  draft count and the zero Charge corrections are still asserted, and no other line changes.
  Result: not weakened.
