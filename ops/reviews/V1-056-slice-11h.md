# V1-056 slice 11h review record: Refund methods with Settings access

Built 2026-10-25 in the cloud session on branch `wip/slice-11` after 6df9b3b. Migration
`20270214_202_refund_methods_settings_access` (head). Decision log DL-089 (owner answer of
2026-10-25 01:32, BR-REFUND-014).

## What was built

- `app.create_refund_method` and `app.set_refund_method_active` are replaced (same signatures
  and grants): they need `settings.manage`, run one at a time under the Refund method list lock,
  check their input, refuse a used code or a reused id, refuse turning off the last method that
  is on, and audit each real change. A repeat that changes nothing writes nothing.
- `RefundService.add_refund_method` and `set_refund_method_on` (runtime role, no writer URL);
  the routes `POST /properties/{property_id}/refund-methods` and
  `POST /properties/{property_id}/refund-methods/{refund_method_id}/state` with three 409 codes;
  the list read also accepts `settings.manage`.
- Client functions `addRefundMethod` and `setRefundMethodState` (no Idempotency-Key). The
  Settings screen comes with the V1-058 rebuild.
- Tests that called the two functions directly now pass `settings.manage`; 16 head assertions
  moved to `20270214_202`.

## Review round 1 (one read-only agent)

No blocker. The lock order, READ COMMITTED and REPEATABLE READ behaviour, the confirms' `FOR
SHARE ... AND active` locks, audit row checks, grants, error mapping and the client were
checked.

- Should-fix (fixed): a repeat of a create answered 503 when the method had been turned off
  since; the route now checks only the id (unit test added).
- Should-fix (fixed): the two-turn-offs test now also runs at REPEATABLE READ and expects 40001.
- Should-fix (kept, reason): the concurrency test turns off the seeded methods for the test,
  because the last-one rule needs every other method off; a fixture turns them on again, and
  the database tests run one at a time. The plain last-one test uses a rolled-back transaction.
- Nits taken: the refund.py comment says code, not name; the flow comment notes these writers
  need no writer URL; the frontend test is TEST-FE-S11H-001.
- Nits kept: two creates at once at REPEATABLE READ can end in a plain 409 (harmless; the
  screen reads the list again); the database trusts the `settings.manage` reference like the
  other Settings writers (the route and service check the capability first; slice 12 list
  item: check the actor's grant in the database for every Settings writer); Python `strip()`
  is stricter than `btrim` (safe).

## Review round 2 (one read-only agent)

No blocker. The three round-1 fixes confirmed; the seeded methods in the concurrency test are
acceptable (one sequential pytest process, each method registered with the fixture before it
is turned off). Every claim in the docs and DL-089 was checked against the code.

- Should-fix (fixed, text): docs/005 still said the Refund methods routes come later; an
  amendment line after it says they are built.
- Nits taken: a repeat of an add answers the method only for the same person (another person
  gets `REFUND_METHOD_ID_REUSED`), now said in docs/005 and DL-089, with a clearer refusal
  message; the flow comment moved to `refunds()`; tests for a NULL or zero id on add and a NULL
  id or state on turn; DL-089 says it replaces the slice 3a-1 `property.manage` line.

Round 2 had one text-only should-fix, so no round 3 (run rule).

## Runs

- Related database files: 185 passed; the new file: 5 passed, again after the round 2 tests.
- Unit: 466 passed (refund API, traceability, forms, route inventory), 431 again after round 2; ruff, mypy clean;
  frontend tsc, eslint, prettier clean, settlementClient tests 11 passed.
- Full PostgreSQL run of c95de5d (slice 11 complete, 2026-10-25, about 60 min): 2,750 passed, 1
  failed. `test_drafts_are_listed_confirmed_rejected_and_withdrawn_through_the_shared_routes`
  read the whole second page of pending drafts of the shared Property and found an older
  pending draft another module left. Test-only fix: the second page starts with this test's
  draft. The file passes alone (2 passed). No code change.
