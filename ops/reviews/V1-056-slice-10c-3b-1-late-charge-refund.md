# V1-056 sub-slice 10c-3b-1 — REFUND of a Late-payment Charge paid by Payments or Credits: review record

Sub-slice: 10c-3b-1 (migration `20261117_113`). Base commit: ef56af5. Not committed (commit hash in
ops/NOW.md once committed).

Rule IDs: BR-SETTLE-013, BR-LATE-005, BR-CREDIT-006, BR-CREDIT-008, BR-CREDIT-014, BR-REFUND-014,
DL-032, BR-AUTH-010; owner answers to Q-2026-10-07-38 (b), Q-2026-10-07-41 answer 2,
Q-2026-10-07-42 answers 1 and 2, Q-2026-10-09-66, answer 4 to Q-2026-10-09-65 and
Q-2026-10-09-68. Pre-code design: ops/V1_056_PLAN.md (10c entry, "10c-3b pre-code design";
"10c-3b-1 as built").

## Owner question during the build

- Q-2026-10-09-68 (asked in the session before any code): the shared plan check refused a released
  Charge allocation in its Credit overlay (it joined `allocation.invoice_id`, which a Charge
  allocation does not have); the design did not list this reader. Owner answer: patch it (the
  recommendation). Recorded in docs/010 and the questions file.

## Built

- Migration `20261117_113`:
  - Relaxed `app.invoice_credit_excess_releases`: `invoice_adjustment_id` nullable; new nullable
    `late_payment_charge_correction_id` (FK `invoice_credit_excess_release_charge_correction_fkey`,
    ON DELETE RESTRICT; index `invoice_credit_excess_release_charge_correction_idx`); check
    `invoice_credit_excess_release_one_link` (exactly one link); the reason check now pairs each
    reason with its link. Grants unchanged.
  - New: recorder `app.record_settlement_late_charge_refund_draft` (`final_settlements.prepare`)
    and confirm `app.confirm_settlement_late_charge_refund` (`financial.approve`), executable only
    by the financial role; internal `app.settlement_late_charge_refund_input`, `_sources`,
    `_source_state`, `_overlay`, `_plan`, `_result` and `app.settlement_late_charge_instant` (no
    role).
  - Patched (exact text): the Invoice-line REFUND confirm (refuses a draft with a `target_kind`,
    replay and main path), the lock function (the Charge FOR UPDATE), the release validator (Charge
    branch), the Credit recognition validator (the Charge's Customer), the relaxed Credit Refund
    check and the plan's Credit key (join through the Charge correction effect), the two audit
    labels (the release row's reason), and the shared plan check's Credit overlay (Q-68).
- Service: `RecordLateChargeRefundCorrectionCommand`, `record_late_charge_refund`,
  `confirm_late_charge_refund` (stale P5S02).
- Tests: new module `test_settlement_late_charge_refund_migration.py` (9 tests after review round
  1); 3 unit tests; 27 head-revision assertions; 12 traceability entries.
- Docs: docs/004 (DB-INV-003 relaxed table, DB-SETTLE-005 as built), docs/010 (owner approval,
  sub-slice entry, updated tests), the plan (as built), the questions file (Q-68).

## Read-only search of every backend test

The source checks of the patched functions in other modules still hold: the lock order of the
Invoice-line REFUND confirm (10c-2a-3), one Payment pass and one Credit pass in the lock function,
no `interval` other than the listed ones and no `age(` (10c-1b, 10c-2a-2). Every forward-only test
upgrades only to its own revision. No test reads the release table's structure. The 27
head-revision assertions move to `20261117_113`.

## Runs

Static checks each in its own call. Lint failed twice for cause A (lines over 100 characters in the
new test module; corrections 1 and 2 of 2); format failed once (cause B, one wrapped expression;
correction 1 of 2, by the formatter); type check failed once after the round-1 fixes (cause G, a
dict needed an annotation; correction 1 of 2); then all clean. Migration-only check (throwaway copy
of `scripts/database-test.sh` running `alembic upgrade head`): 112 upgrades, head `20261117_113`,
three times (first build, after the name change, after the round-1 fix).

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| T1 | PostgreSQL, targeted: the new module (a check before the full run) | 4 passed, 4 failed | first run | `V1-056-slice-10c-3b-1-targeted-test-run.txt` |
| T2 | PostgreSQL, targeted: the new module | 7 passed, 1 failed | T1 test causes A to D | `V1-056-slice-10c-3b-1-targeted-test-run-2.txt` |
| U1 | backend unit, full (under `caffeinate -dims`) | 3679 passed, 1840 skipped, 1 warning (Starlette) | first unit run | `V1-056-slice-10c-3b-1-unit-test-run.txt` |
| P1 | PostgreSQL, full (under `caffeinate -dims`) | 2003 passed, 1 warning (Starlette) | first full run | `V1-056-slice-10c-3b-1-full-test-run.txt` |
| T3 | PostgreSQL, targeted: the new module | 8 passed, 1 failed | round-1 fixes | `V1-056-slice-10c-3b-1-targeted-test-run-3.txt` |
| T4 | PostgreSQL, targeted: the new module | 9 passed | T3 cause F | `V1-056-slice-10c-3b-1-targeted-test-run-4.txt` |
| U2 | backend unit, full (under `caffeinate -dims`) | 3679 passed, 1841 skipped, 1 warning | traceability changed | `V1-056-slice-10c-3b-1-unit-test-run-2.txt` |

Failure causes (each with its corrections; no code defect in the money paths):

- T1 test cause T-A: the third-party test expected the released Credit off the payer's ledger; the
  payer's ledger lists the Credits of the payer's Payment. Narrowed to the Refund, as the committed
  10c-1b test (correction 1 of 2).
- T1 test cause T-B: the Credit-application fixture recognized a Payment excess while the Charge was
  open ("Applicable obligations must be handled before excess disposition"); the Payment is now
  identified for the paid key card Invoice (correction 1 of 2).
- T1 test cause T-C: the test expected no read grant on the release table; the runtime and
  financial roles keep their existing read grant. The test now checks that no role writes it and
  the forward-only test that the grants are unchanged (correction 1 of 2).
- Identifier length (T1 then T2, one cause, corrections 1 and 2 of 2, the allowance used up):
  PostgreSQL shortens names over 63 characters. T1: the default FK name (test expectation); T2: the
  index name. Fixed in the migration with explicit names for both.
- T3 test cause T-F: the round-1 check test set `session_replication_role`, which the test role may
  not (42501). The checks are now shown by their exact definitions (correction 1 of 2).

No PostgreSQL run after T4 other than the targeted ones: the only code change after P1 is the
VOLATILE label of `app.settlement_late_charge_instant`, which only the new confirm calls (a
read-only search found it only in the migration and the new module), so the targeted run covers
every affected test. The T1 output held one database password of the throwaway test container in
an assertion message (line 25); it is redacted (`[REDACTED]`) and no other run file holds one
(independent review round 1, S2).

## Review round 1 (2026-10-09; fresh read-only subagents, independent and security; read while P1 ran)

Security: 0 blockers, 0 should-fix, 5 notes. Independent: 0 blockers, 2 should-fix, 8 notes.

- Independent S1 (the Charge correction's stamp does not step past Credit applications on the
  Charge): does not reproduce. `app.allocation_target_latest_at('LATE_PAYMENT_CHARGE',...)` counts
  Credit applications and their reversals on the Charge since migration `20260906_41`, Deposit
  applications since `20261021_86` and their reversals since `20261105_101` (citations corrected
  after review round 2); checked on a database at head. The stamp follows every
  allocation, Credit application, reversal and correction on the Charge, as the plan and docs/010
  say. Comment made precise; no other change.
- Independent S2 (a database password in the T1 output): fixed, redacted (see Runs).
- Independent N5 and security N4 (the instant function is STABLE but reads the clock): fixed,
  VOLATILE.
- Independent N1 (the lock patch had no behaviour test): fixed, the guards test holds the lock
  function and shows that a key-share lock of the Charge and of its source Invoice waits.
- Independent N2 (the relaxed-table test did not reach the two checks): fixed, their exact
  definitions are asserted (the release validator refuses every other bad row first).
- Independent N3 (the third-party test proves less than the design text): the plan's as-built
  line now says so (difference 7).
- Independent N4 (no test releases a Settlement Credit application on the Charge): fixed, a new
  test on a really closed Settlement whose Primary Tenant's Credit paid part of the Charge at
  closure; the linked reversal passes 8e-2, the re-posted rest's one-call reversal stays refused.
- Independent N6 (the release order in the result follows `created_at`, then the id): as the
  Invoice-line form; each release row is written in its own statement, so the clock orders them.
  Not changed.
- Independent N7 (BR-CREDIT-006 had no traceability entry): added to the Credit-step test.
- Independent N8 (records incomplete, the identifier-length allowance): this record; counted as one
  cause with two corrections.
- Security N1 (the release validator's Charge branch does not check that the Charge correction is
  linked to a correction confirmed in this transaction): not changed; the same as the Adjustment
  branch since migration 67; no role writes the table and the only writer is the new confirm.
  Optional hardening for slice 12.
- Security N2 (the recognition patch does not tie the Credit's Payment to the reversed
  allocation's Payment): not changed; the same gap as the Adjustment branch; the confirm passes the
  allocation's Payment and the amount stays bounded by the Payment's available value. Slice 12.
- Security N3 (the plan keeps no `application_usd_cents` for a Deposit source, and Phase 1 treats
  every other source as a Credit application): fails closed today; written into the plan as a
  10c-3b-2 task (difference 8).
- Security N5 (the database trusts the authorization string; capabilities are checked in the
  service): the existing design of every correction; re-checked in 11e with the routes.

## Review round 2 (2026-10-09; fresh read-only subagents, independent and security)

Independent: 0 blockers, 0 should-fix, 6 notes. Security: 0 blockers, 0 should-fix, 5 notes. Both
found every round-1 finding fixed or correctly answered (the independent reviewer verified the S1
answer against the migrations, each patched function's test fails without its patch, and the
targeted-run argument after P1). Under the takeover rules the commit follows; no round 3 is needed.

- Independent N1: the S1 answer cited the wrong migrations; corrected above (text only).
- Independent N2: the Credit-step test claimed BR-CREDIT-008 for the Signer's debt, but no step
  names that debt; the claim is narrowed in the test docstring and its traceability note (text
  only). Slice 12 list: a refused step of the released Charge Credit to another Customer's line.
- Independent N3: every confirmed Refund runs on a fully paid Charge; a partly paid Charge is
  covered at record time only. Slice 12 list.
- Independent N4: a test comment named the reversal's audit too; corrected (text only).
- Independent N5: the open-Settlement and VOID-Invoice refusals of the new plan function have no
  test in the new module (the design did not list them). Slice 12 list.
- Independent N6: docstring typo "re- posts"; corrected (text only).
- Security notes 1 to 5: (1) tests pass the database URL into assertion messages, so a failure can
  print a password into a run output: every run file is scanned before each commit (35 modules use
  the pattern; slice 12 may hide the password in the fixture's URL text); (2) and (3) carry-overs
  of round-1 N1 and N5; (4) the third-party payer's released value goes to the Charge's Customer,
  as designed (BR-CREDIT-014); (5) the 10c-3b-2 task (difference 8).

Text fixes after round 2 (the test module's docstring and one comment, one traceability note and
this record): `diff` against a copy taken before the edits shows only those three test lines
changed. Static checks each in its own call: lint, format and type check clean.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U3 | backend unit, full (under `caffeinate -dims`) | 3679 passed, 1841 skipped, 1 warning | traceability note changed after round 2 | `V1-056-slice-10c-3b-1-unit-test-run-3.txt` |

No PostgreSQL run after the text fixes: no PostgreSQL test reads a docstring, a comment or a
traceability note. Committed next (commit hash in ops/NOW.md).
