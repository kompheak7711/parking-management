# V1-056 slice 12a review record: Settings audit evidence and the hand-back KEEP order

Built 2026-10-25 in the cloud session on branch `wip/slice-12` after c95de5d (slice 11h).
Migration `20270215_203_settings_evidence_and_hand_back_keep` (head). Decision log DL-090.

## What was built

- `app.execute_service_rate`, `app.execute_utility_rate` and
  `app.set_one_time_charge_due_days` are patched by exact text to write `settings.manage` in
  their audit evidence (login L5 item, Q-2026-10-24-186).
- `app.hand_back_rent_invoice_basis` tests "nothing outstanding" first, so an Invoice a credit
  Adjustment took to zero is assessed `KEEP` (slice 11a review round 1, S2).
- `test_runtime_secrets.py::test_the_password_blocklist_is_read_once_and_needed_with_a_database_outside_development`
  removes `APP_DATABASE_URL` before its no-database case (login L7c item); the failure was
  reproduced with the setting present and passes after the change.
- 28 head assertions moved to `20270215_203`.

## Review round 1 (one read-only agent)

No blocker. All four patch strings are present once in the latest definition of each function;
no later migration replaces them. The KEEP change touches only an Invoice with nothing applied
and nothing outstanding, which the resolution already refused (as "assessment changed"); the
Final Settlement code reads only the resolutions table. Nothing reads the old audit labels.

- Should-fix (fixed, text): docs/005, DL-090 and the migration docstring said the case was
  refused as a blocked VOID; it was refused as `HAND_BACK_ASSESSMENT_CHANGED`, and now as
  `HAND_BACK_PAID_INVOICE_KEPT`.
- Nits taken: the API text of `HAND_BACK_PAID_INVOICE_KEPT` now fits an Invoice that owes
  nothing; DL-090 records the BR-RENT-030 reading; the unused noqa line is gone; the hand-back
  test checks the Invoice version and status do not change; the stale head comment in
  `test_sign_in_wait_migration.py`.

Round 1 had only text should-fix items, so no round 2 (run rules: fewer rounds, owner
2026-10-23 22:30).

## Runs

- Targeted PostgreSQL: the new file, hand-back, one-time charges, configuration, sign-in wait
  and runtime secrets modules passed (after the round 1 fixes: 26 passed).
- Unit: traceability, runtime secrets, invoice API passed; ruff, mypy clean.
