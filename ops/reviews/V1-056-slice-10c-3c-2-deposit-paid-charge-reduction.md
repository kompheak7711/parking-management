# V1-056 sub-slice 10c-3c-2 — a charge reduction of the unpaid rest of a partly Deposit-paid obligation — review record

Sub-slice: 10c-3c-2 (owner answers (a) to Q-2026-10-10-70 and Q-2026-10-11-80; owner answers of
2026-10-16 to the 10c-3c-1 report: answer 3, tests that reach the two `CHARGE_REDUCTION` writers,
and answer (a) to Q-2026-10-16-117 with the standing rename rule). Migration `20261218_144` (a
relaxing change). Base commit: 1f67050. Built on 2026-10-16. Not pushed.

Rule IDs: BR-SETTLE-013, BR-SETTLE-012, BR-LATE-005, BR-AUTH-010, DL-032; DB-SETTLE-005,
DB-DEP-005. Design: ops/V1_056_PLAN.md, "10c-3c-2 pre-code note" and its as-built line. No owner
question raised.

## Built

- Migration `20261218_144_settlement_deposit_paid_charge_reduction.py`: exact-text patches, each
  anchor checked to appear once, of `app.settlement_charge_reduction_plan` (Invoice-line form) and
  `app.settlement_late_charge_reduction_plan` (Late-payment Charge form). The old Deposit refusal
  (the line form: any Deposit application on the Invoice; the Charge form: any active one on the
  Charge) is replaced by a refusal with the same message (55000) only for an obligation that an
  active Deposit application paid and that has no unpaid rest. A reduction within the unpaid rest
  passes; above a positive rest stays refused ("The charge reduction would release paid value").
  Catalog dump D1 showed both plan bodies equal the migration 99 and 111 texts.
- Committed tests changed (owner answers and standing rules):
  - `test_settlement_charge_reduction_migration.py`: `test_an_invoice_paid_by_a_deposit_application_takes_no_charge_reduction_yet`
    renamed `test_an_invoice_line_a_deposit_application_partly_paid_takes_a_reduction_of_its_unpaid_rest`;
    the 500 reduction is recorded and confirmed, checked to the cent (Q-80).
  - `test_settlement_late_charge_deposit_refund_migration.py`:
    `test_an_older_deposit_application_stays_and_only_the_linked_charge_correction_passes` records
    the 1,000 reduction within the Charge's unpaid rest and its preparer withdraws it (standing rule
    of 2026-10-11; the Q-70 answer changes this result); `test_a_linked_charge_correction_passes_8a_1_but_no_charge_is_paid_more_than_its_new_amount`
    renamed `test_a_linked_charge_correction_under_a_draft_naming_no_charge_is_refused_by_8a_1`
    (Q-117; name, docstring and traceability note only).
  - The 27 head-revision assertions in 15 modules move to `20261218_144` (script, count per file
    checked).
  - `test_settlement_late_charge_reduction_migration.py` does not change (the Q-80 text).
- New module `test_settlement_deposit_paid_charge_reduction_migration.py` (last in
  `scripts/database-test.sh`): the Q-70 example to the cent (Charge form), the Invoice-line form
  on the key card line, a line with no Deposit application on an Invoice whose other lines the Pet
  Deposit paid (round 1), the kept Deposit refusal after each confirm, least privilege and
  forward-only.
- Traceability: entries 2760, 2892 and 2894 updated in place; four entries appended.
- Docs: docs/004 (the 10c-1a, 10c-2a-3 and 10c-3a paragraphs, a new paragraph after the 10c-3c-1
  one), docs/010 (owner answers, as built, updated tests, reviews and runs), the plan (pre-code
  note, as-built line, slice 12 items), ops/V1_056_QUESTIONS.md (Q-116, Q-117 answered),
  ops/V1_055_RUN_RULES.md (the standing rename rule).

Read-only search for affected tests (before P1, P2 and P3): only migrations 99, 111 and 144 name
the two plan functions; the recorders are called by the two reduction modules, the
late-charge Deposit Refund module (imported helper), the new module and the unit module
`test_settlement_correction.py` (mocked); the Deposit message is asserted for a recorder only in
the 10c-1a, 10c-3a and 10c-3b-2 tests named above (the other assertions are 8a-1 trigger cases).

## Runs

| Run | Result |
|---|---|
| D1 | catalog dump (9 functions), no `REDACTED` marker |
| FF1/FC1/L1/Y1 | backend format (formatter first, no change), format check, lint, type check passed; before L1 the long-line search found one test line and one docstring line, wrapped by hand |
| M1 | passed (`20261218_144` head) |
| T1 | 18 passed (the new module and the three changed modules) |
| U1 | 3804 passed |
| M2 | passed |
| P1 | 2210 passed (warnings: the known Starlette deprecation and two Pydantic alias warnings of the unchanged Credit Refund API tests) |
| FF2/FC2 | passed (after the round 1 fixes; formatter first, no change) |
| L2 | failed: I001 import order in the new module (cause: import order; correction 1 of 2, moved one import by hand) |
| FF3/FC3/L3/Y2 | passed (the passing rerun after L2) |
| T2 | 19 passed |
| U2 | 3804 passed |
| M3 | passed |
| P2 | 2211 passed (warnings: Starlette and one Pydantic alias warning) |
| FF4/FC4/L4/Y3 | passed (after the round 2 fixes; formatter first, no change) |
| M4 | passed |
| T3 | 19 passed (the 10c-3a module back at HEAD included) |
| U3 | 3804 passed |
| M5 | passed |
| P3 | 2211 passed (warnings: Starlette and one Pydantic alias warning) |

After P3 only text changed (docs/010, the plan, this record, ops/NOW.md). Full outputs are in
`~/Development/prm-run-logs/v1-056-10c-3c-2-*.txt`.

## Review round 1 (fresh read-only subagents, during P1; told to write no file and run no test, script or database command)

Independent: 0 blockers, 1 should-fix, notes. Security: 0 blockers, 1 should-fix, notes.

- Should-fix (both, the same): no test of the implementer's reading (a line with no Deposit
  application on an Invoice where another line is Deposit-paid). Both reviewers confirmed the
  reading is needed (the old refusal was an "until 10c-2" stopgap over the whole Invoice) and safe
  (the same unpaid-rest rule; the Invoice-wide 8a-1 refusal still lets only the hardened linked row
  through). Fixed: `test_another_line_of_an_invoice_the_pet_deposit_partly_paid_is_reduced_within_its_rest`
  (real closure of an Initial Invoice with a Rent line and two Service lines; the set-up of the
  committed `test_a_deposit_application_on_another_line_of_the_invoice_stays`, fixed dates).
- Notes taken: a `held` check after the Invoice-line confirm; DB-DEP-005 in the Charge test's
  traceability entry; the plan's "while the Settlement is still open"; a docstring wrap in the
  renamed test; an inline comment at a changed expectation; docs/004 (as-built paragraph and two
  older paragraphs).
- Security findings: no money is released or moved (both plans cap at the unpaid rest, which
  counts active Deposit applications; the deferred checks run at `SET CONSTRAINTS ALL IMMEDIATE`);
  only the correction's own linked row passes 8a-1; human `financial.approve` confirm, READ
  COMMITTED, locks before the digest; privileges kept; no injection in the patch helper; no
  secret or database URL in the diff.

## Review round 2 (fresh read-only subagents, during P2; same limits)

Independent: 0 blockers, 2 should-fix. Security: clean (0 blockers, 0 should-fix, notes).

- Should-fix 1 (independent): Q-2026-10-11-80 told the owner that the 10c-3a test
  `test_a_charge_a_deposit_paid_or_of_another_lease_is_refused` does not change, because the build
  keeps the Deposit refusal's message for an obligation with no unpaid rest; the first build
  dropped that message and changed the test to "would release paid value". Fixed in the migration
  (a fail-closed change that keeps a refusal, within the round-3 rule of 2026-10-13): each patch
  keeps the Deposit refusal for an obligation that an active Deposit application paid and that has
  no unpaid rest; the 10c-3a module and its traceability entry are back to HEAD; both new
  real-path tests assert the kept refusal after their confirm.
- Should-fix 2 (independent): docs/004's 10c-1a paragraph still said a Deposit-paid Invoice stays
  refused. Fixed.
- Notes taken: the new fixed-date test named in the slice 12 date-bound item; docs/004 wording (a
  Deposit change "on the obligation" makes the draft stale; the 8a-1 pass applies "while an active
  Deposit application is on the Invoice or the Charge"). Kept (slice 12, optional): `adjustments`
  of the reduced line after the confirm is implied by the single effect; the reversal-then-stale
  case.
- The independent reviewer compared every changed committed test with HEAD: nothing weaker.
  Security: the round 1 should-fix is fixed and shows that only the named line changes.

## Review round 3 (fresh read-only subagents, after U3 and P3; same limits)

Independent: clean (0 blockers, 0 should-fix). Security: clean (0 blockers, 0 should-fix).

- Independent: both round 2 should-fix items fixed; the kept branch matches the Q-80 text (it
  fires only when the unpaid rest is at most 0, so nothing the Q-70 answer allows is refused); a
  line paid by a Deposit and a Payment with nothing outstanding keeps the Deposit message, as at
  HEAD; the changed committed tests compared with HEAD again, nothing weaker; traceability
  append-only beyond the first 1,598 entries (four appended; 2760, 2892, 2894 changed in place).
- Notes taken (text): the plan's as-built wording ("Of point (3) above, only these committed test
  changes remain"); this record and the docs/010 entries written before the commit.
- Notes not taken (slice 12 list): the migration docstring could name the per-line scope of the
  kept refusal (docs/004 does; no migration file change after P3); two optional assertions (the
  per-line scope on the other-line case; a Deposit-plus-Payment line with nothing outstanding).
- Security: the kept branches have correct precedence and no NULL path (every helper COALESCEs;
  the line and Charge rows were found just above); the helpers are internal SECURITY DEFINER
  functions with the fixed search path; deny-by-default, the Staff-confirm refusal, the stale
  check and the no-money-moves property hold; no injection; no secret.
