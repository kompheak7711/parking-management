# V1-056 slice 10 — the two real-path tests before 10h: review record

Tests only (no migration, no production code). Base commit: 25f925b. Commit hash in ops/NOW.md once
committed.

Rule IDs: BR-SETTLE-008, BR-SETTLE-013, DL-032, BR-REFUND-015, BR-DEP-023. Tasks: ops/V1_056_PLAN.md,
"Before 10h — a real-path test of the Q-2026-10-09-65 case" (owner answer 2 to Q-2026-10-09-67)
and "Before 10h — a real-path test of a `FORFEITURE_REVERSAL` Deposit Refund to another signed
Signer" (owner answer 1 to Q-2026-10-10-71). Built early, while 10e-1c, 10e-2, 10c-2a-7, 10c-3c-2,
10c-2b-5 and 10e-3 wait for Q-2026-10-10-76, Q-2026-10-11-79 and Q-2026-10-11-80 (owner rule of
2026-10-10: build the next independent sub-slice while one waits).

## Built

- New module `backend/tests/test_settlement_real_path_migration.py` (last in
  `scripts/database-test.sh`):
  - `test_the_q65_case_is_settled_security_first_on_the_real_path` and
    `test_the_q65_case_is_settled_pet_first_on_the_real_path`: the Q-65 state on the real path
    (before closure the Customer pays 2,300 of the other damage line; the Settlement refunds 200 of
    the Security Deposit and 7,500 of the Pet Deposit; after closure two return-only corrections
    bring back 200 and 300; a later inspection's pet finding is billed as a 50 Damage
    `EXTRA_CHARGE` and 100 of other debt as a Miscellaneous one; no Credit), then the committed
    plan-check sequence through real `HELD_VALUE_REFUND` corrections in both orders, with the same
    refusals, ending in the DL-032 order on real balances and records.
  - `test_a_kept_deposit_is_refunded_to_the_agreed_second_signer_on_the_real_path`: a real
    two-Signer Lease (the second Signer added and signed through the Lease service before the Lease
    is signed with the Reservation), voluntary early leaving, the Security Deposit forfeited
    through the draft and kept, a real closure; without the written agreement the Refund to the
    second Signer is refused (22023); with it the `FORFEITURE_REVERSAL` refunds the 10,000 to the
    second Signer, recorded with the method, note and agreement and booked once on the Primary
    Tenant's ledger with the Signer as paid-to.
- `ops/traceability.json`: three entries appended. The plan's two tasks marked done.

## Runs

Static checks each in its own call (`ruff check src tests`, `ruff format --check src tests`,
`mypy`): clean; `ruff format` was run on the new file once before the first check, and lint failed
once after the round-1 fixes (one line over 100 characters, split; correction 1 of 2). No migration,
so no migration-only check. Read-only search: no committed test reads the new module; the
`scripts/database-test.sh` list check needs the new entry, which is added.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| T1 | PostgreSQL, targeted: the new module | 3 passed | first run | `V1-056-slice-10-real-path-targeted-test-run.txt` |
| U1 | backend unit, full (under `caffeinate -dims`) | 3743 passed, 1875 skipped, 1 warning | traceability entries | `V1-056-slice-10-real-path-unit-test-run.txt` |
| P1 | PostgreSQL, full (under `caffeinate -dims`) | 2038 passed, 3 warnings (Starlette; two of the known Pydantic alias warnings) | first full run | `V1-056-slice-10-real-path-full-test-run.txt` |
| T2 | PostgreSQL, targeted: the new module | 3 passed | round-1 fixes | `V1-056-slice-10-real-path-targeted-test-run-2.txt` |
| U2 | backend unit, full (under `caffeinate -dims`) | 3743 passed, 1875 skipped, 1 warning | round-1 traceability change | `V1-056-slice-10-real-path-unit-test-run-2.txt` |
| P2 | PostgreSQL, full (under `caffeinate -dims`) | 2038 passed, 2 warnings | round-1 test changes (owner run rule) | `V1-056-slice-10-real-path-full-test-run-2.txt` |

Secret check of all six outputs: no database URL with a password, no `password=`, no 64-character
hex string.

## Review round 1 (independent and security; during P1)

Security: 0 blockers, 0 should-fix, 6 notes, all answered without a change: the Payment rows of the
fixtures are seeded as the table owner and the Deposits received outside a service (the suite's
established setup; no service receives a Pet Deposit; the corrections under test all run on the
real path); a Staff-cannot-confirm check is already in the 10c-2b-1, 10c-2b-3, 10b and 10d modules;
the full run output was checked again when complete (above); the local path in warnings is the
owner's own, as in earlier outputs; the extra user and Unit of the second `setup_reservation_sources`
call are synthetic and harmless.

Independent: 0 blockers, 1 should-fix, 8 notes.

- SF-1 (the reference note of the agreed-Signer Refund not asserted): fixed.
- N2 (no refusal without the written agreement on the real path): added (22023 and its message, no
  draft written).
- N3 (docstring claimed order): reworded; the order is shown by the refusals and balances.
- N4 (what each return-only correction left per Deposit): asserted at the start (300, 0, 200, 0)
  and at the end (0, 0).
- N5 (ledger rows): exactly one `REFUND_PAID` row on the Primary Tenant; no rows for the Signer.
- N6: two signed Signers and the rent line paid are asserted; the 100 line is asserted not pet
  damage.
- N7: the two-Signer entry also names BR-SETTLE-008 and DL-032.
- N8 (extra user and Unit): answered as above (harmless synthetic data; no change).
- N9 (plan bullets): marked done.

## Review round 2 (independent; during P2)

The security reviewer of round 1 found nothing to fix and the round-1 changes are tests only, so
round 2 is the independent review. 0 blockers, 0 should-fix, 5 notes:

- N1 (assert the Settlement preview owes nothing after the two-Signer closure), N3 (check on the
  correction effects that the Deposit application comes before the Refund in the two corrections
  that pay debt and refund at once) and N4 (BR-REFUND-014 and BR-DEP-026 in the two-Signer entry):
  slice 12 items, so that no test file and no file a unit test reads changes after U2 and P2.
- N2 (the extra user and Unit): answered in round 1.
- N5 (the plan's Done lines and order line): fixed (the record named; "built early" noted).

Round 2 has no blocker and no should-fix, so the sub-slice is committed. Only documents changed after
P2 (the plan and this record).
