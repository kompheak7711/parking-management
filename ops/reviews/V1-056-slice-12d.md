# V1-056 slice 12d review record: a waiting REFUND_RETURN correction holds the other Lease

Built 2026-10-25 in the cloud session on branch `wip/slice-12c` after e9acfd1 (slice 12c).
Migration `20270218_206_preview_refund_return_wait` (head). Decision log DL-093 (owner answer (a)
to Q-2026-10-20-149).

## What was built

- One exact-text change of `app.final_settlement_preview`: the 10i-4c plan-overlay branch for
  another Settlement's waiting `REFUND` correction draft also covers `REFUND_RETURN`. Same
  signature, owner, settings and privileges (`CREATE OR REPLACE` from `pg_get_functiondef`).
- Tests in `backend/tests/test_settlement_preview_refund_return_wait_migration.py`: the real
  path (the draft holds the Customer's other Lease, its Settlement draft is refused with 55000
  and nothing written, the draft is not listed for its own Settlement, the other Lease closes
  after the withdrawal) and a catalog test (only the preview changes, once; forward-only).
- Shown to fail without the change (the main test, with the migration's patch turned off,
  fails at the blocking check), then passes with it.

## Review round 1 (one read-only agent, independent and security)

- No blocker. The reviewer checked that a Credit Refund's `REFUND_RETURN` draft keys its plan
  overlay by the Credit id like `REFUND` (migration 108), a Deposit Refund return writes no
  Credit key, every wait path (Settlement record, 8e-3 confirm, correction plans) reads the
  same preview, and no migration after 174 rewrote the preview.
- Should-fix taken: this record. Nits taken: a blank line before the docs/007 entry; DL-093
  names BR-SETTLE-012 and the 10i-4c side effect (a closed Settlement of the Customer takes no
  correction step the preview covers while the draft waits; two drafts recorded at the same
  moment can hold each other); the test docstring says K holds no other money here.
  Not taken (tests only, the same changed line): the 8e-3 confirm refusal, the release after a
  confirm, a correction step of a closed Settlement and a stranger Lease (all covered for the
  same branch by the 10i-4c tests); the trigger and structure check of the 174 catalog test.
- No round 2: no blocker and one should-fix, a record only (fewer rounds rule).
- Runs: the new suite, `test_settlement_preview_credit_step_wait_migration.py` and
  `test_settlement_refund_return_migration.py` passed on PostgreSQL (11 tests);
  `tests/test_traceability.py` 28 passed; ruff format, ruff check and mypy clean (480 files);
  TEST-118 audit passed (base 062805c, 17 new material identifiers).
