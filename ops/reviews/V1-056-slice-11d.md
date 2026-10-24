# V1-056 slice 11d review record: the wrong-Unit Payment move draft route

Built 2026-10-24 in the cloud session on branch `wip/slice-11` after f202221. No migration.

## What was built

- `POST /properties/{p}/payment-allocations/{allocation_id}/move-drafts`
  (`payments.allocations.reverse`; hidden 404 without it; Origin, CSRF, `Idempotency-Key`) in
  `draft_record_api.py`, over `PaymentMoveService.record`. It records a `PAYMENT_MOVE` draft of
  variant `WRONG_UNIT_MOVE`; a `financial.approve` holder confirms it through the shared confirm.
- Named refusals (`api_refusals.py`, block "V1-056 slice 11d"): 409 for the state of the
  allocation in the path; 422 on `target_invoice_id` for a correct Invoice that is not found, on
  the same Unit or has nothing owed; 422 on both acknowledgements for a draft over 16,000 bytes.
- The shared confirm names the same state refusals for kind `PAYMENT_MOVE` only
  (`financial_draft_api.CONFIRM_REFUSALS`); a paid correct Invoice or a stale draft answers
  `DRAFT_OUT_OF_DATE`. Final Settlement corrections (kind `SETTLEMENT_CORRECTION`, variant
  `PAYMENT_MOVE`) keep their plain answers until 11e.
- `POST /payment-allocations/{id}/reverse` now answers 409 `ALLOCATION_MOVED` and
  `FINAL_SETTLEMENT_CLOSED` for its two database messages.
- Messages were read from the head catalog (temporary probe test, not committed); the
  named-message guard in `test_financial_draft_api_migration.py` covers them.
- docs/005 paragraph "V1-056 slice 11d" at the end of API-101.

## Review round 1 (one read-only agent)

No blocker. Every mapped text matches a message the database raises today (migrations 85, 148,
164 and 165), and none collides with another meaning in the record path.

- S1 (fixed): the one-call reversal's two named refusals were not tested over HTTP. Test added
  (`test_the_one_call_reversal_names_a_moved_or_relied_on_allocation`), with the plain 409 and
  the reused key.
- S2 (fixed): the PAYMENT_MOVE names at the shared confirm had no unit test, and "Payment move
  draft is stale" was untested. Test added (`test_a_payment_move_draft_confirm_names_its_database_refusals`),
  which also locks the plain answer of a Final Settlement correction of variant PAYMENT_MOVE.
- S3 (fixed): the move answer check is now tested with another Property and another kind.
- N1 (fixed): a Final Settlement that closes between the confirm's check and its reversal insert
  now answers `PAYMENT_MOVE_THROUGH_CORRECTION` at confirm.
- N2 (fixed): `PAYMENT_MOVE_TOO_LARGE` is 422 on both acknowledgements, and its message names the
  line split too. `PAYMENT_MOVE_NOT_INVOICE_ALLOCATION` stays 409: it describes the allocation in
  the path.
- N3 (fixed): docs say which codes only recording raises, and "record a new draft if the move is
  still needed".
- N4 (fixed): `ALLOCATION_REVERSAL_REFUSALS` is a read-only mapping like its siblings; this record
  exists.
- N5 (left as is): no real-path test of an allocation or a target Invoice of another Property.
  The test database has one Property shared by all tests; the SQL guards on the Property
  (migration 165) and the unit tests cover the answers.
- Also fixed while running: the out-of-date real-path test left a pending draft in the shared
  Property, which broke the draft list test when it ran after it. The approver now rejects it.

## Review round 2 (one read-only agent, the round 1 fixes)

No blocker.

- S1 (fixed): the stale move draft case of the new confirm test raised the P5S02 stale error,
  which answers `DRAFT_OUT_OF_DATE` before the table is read, so it passed for the wrong reason.
  The database raises "Payment move draft is stale" as 55000 (a conflict); the case now raises
  the conflict error, so it proves the table entry.
- N4 (fixed): the Final Settlement correction case asserts the 409 status too; a positive control
  shows the right answer with the path's Property and kind.
- N6, N7 (fixed): traceability notes name the new cases; the reversal tests list API-059, and
  API-059 has a one-paragraph pointer to the slice 11d paragraph.
- N5 (left as is): the out-of-date real-path test rejects its draft only when every earlier
  assertion passed; a failing run already fails the slice.
- Confirmed: the 422 `PAYMENT_MOVE_TOO_LARGE` path, the exact-text match of `database_refusal`,
  the `PAYMENT_MOVE_THROUGH_CORRECTION` text from the 165 allocation-reversal trigger at confirm,
  the reject route and capability, and that docs and ops are append-only.

## Runs

Unit: `test_payment_move_api.py` and `test_financial_draft_api.py` 48 passed; the allocation,
receipt and draft API files with the route inventory and traceability tests 299 passed before
the round 1 fixes; after them 301 passed. After round 2: see the last line. Targeted PostgreSQL:
`test_payment_move_api_migration.py` (2) and `test_financial_draft_api_migration.py` (2) passed.
After round 2: typecheck clean (458 files); `test_payment_move_api.py`, `test_financial_draft_api.py`
and the traceability tests 76 passed; the two targeted PostgreSQL files 4 passed.
