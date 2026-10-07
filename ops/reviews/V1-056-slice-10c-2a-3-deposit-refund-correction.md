# V1-056 sub-slice 10c-2a-3 — Refund of a Deposit-paid charge: review record

Sub-slice: 10c-2a-3 (migration `20261107_103`). Base commit: f152b56 (the Q-2026-10-07-47 stop), with
the owner answers to Q-2026-10-07-46 and Q-2026-10-07-47 recorded in the working tree (docs/010,
questions file, plan). Committed as the 10c-2a-3 checkpoint after the limited review that the owner
answer to Q-2026-10-08-48 asked for (commit hash in ops/NOW.md).

Rule IDs: DL-032, BR-SETTLE-008, BR-SETTLE-013, BR-CREDIT-006, BR-CREDIT-008, BR-CREDIT-014,
BR-DEP-027, BR-REFUND-014, BR-REFUND-015, BR-AUTH-010; owner answers 1 to 3 to Q-2026-10-07-41, 1
and 2 to Q-2026-10-07-42, 3 and 4 to Q-2026-10-07-44, Q-2026-10-07-46, Q-2026-10-07-47.

## Built so far

- Migration `20261107_103`: the 10c-1b recorder, confirm, result, line sources and release plan
  extended in place (Deposit applications released newest first with Payments and Credits; the
  shared DL-032 step after the release; Credit Refunds only for what is left; the Lease row lock
  in the 8e-3 order; a new Customer choice at BR-DEP-027 terminations); the 8a-1 refusal lets
  through only an Adjustment linked to a correction of its Invoice's own Settlement confirmed in
  this transaction by that correction's approver; new internal functions
  `app.settlement_correction_adjustment_allowed` and `app.settlement_refund_overlay`. The
  overpayment rule is already enforced at commit by `app.validate_invoice_adjustment_effect`
  (outstanding at the Adjustment's time, Deposit applications included); a test shows it.
- Service: `RecordRefundCorrectionCommand` gains `steps` and `pet_remainder`; the request carries
  `plan`.
- Tests: new module `test_settlement_deposit_refund_correction_migration.py` (7 tests, last in
  `scripts/database-test.sh`); the six 10c-1b tests rebuilt on a real closure (owner answer to
  Q-47): test 1 (real closure; the unpaid-line check moved to the end, on a charge issued after
  closure), test 2 (two-Signer closure; amounts 600 and 200), test 3 (third party pays a 1,500
  charge issued after closure; amounts 500 and 1,000), test 4 (real closure; Deposit-paid
  expectation narrowed to the DL-032 step's refusal; stale and method checks on a paid charge
  issued after closure; amounts 500, 700, 1,000), tests 5 and 6 (the Customer pays the line before
  a closure that refunds both Deposits; the Credit application is the newest source; Refund 100);
  10c-2a-2 module: stale test covers every result key, `blocked_by` checks the Lease row lock with a
  10-second deadline; one unit test expectation narrowed (`test_settlement_correction.py`: the
  request carries the empty plan); 26 head-revision assertions; traceability 7 entries and one note.
- Docs (fresh session, 2026-10-07): docs/004 (DB-DEP-005 8a-1 amendment, DB-SETTLE-005 10c-2a-3
  paragraph, the DB-REFUND 10c-1b note amended), docs/010 (sub-slice entry; updated tests entry
  listing each rebuilt 10c-1b test with what changed and why, and the two owner-accepted changes
  beyond setup), the plan's as-built note.

## Runs

Static checks, each in its own tool call (format, `ruff check src tests`, `ruff format --check src
tests`, `mypy`): clean after fixes (two lint slips; one tuple unpacking bug found by mypy).
Migration-only check before P1 and P2: reached `20261107_103`. Read-only search: the 10c-1b
module, the unit test above and the 10c-2a-2 module; no other test reads the changed functions.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U1 | backend unit, full | 3589 passed, 1765 skipped, 1 warning (Starlette) | first run of 10c-2a-3 | `V1-056-slice-10c-2a-3-unit-test-run.txt` |
| P1 | PostgreSQL, full | 2 failed, 1926 passed, 2 warnings | first run of 10c-2a-3 | `V1-056-slice-10c-2a-3-full-test-run.txt` |
| P2 | PostgreSQL, full | 3 failed, 1925 passed, 1 warning | after correction 1 of causes A and B | `V1-056-slice-10c-2a-3-full-test-run-2.txt` |
| U2 | backend unit, full | 3589 passed, 1765 skipped, 1 warning (Starlette) | correction 2 of cause A (the test's traceability note changed) | `V1-056-slice-10c-2a-3-unit-test-run-2.txt` |
| P3 | PostgreSQL, full (under `caffeinate -dims`) | 1928 passed, 2 warnings (Starlette; pydantic alias) | correction 2 of cause A; cause C needs no change | `V1-056-slice-10c-2a-3-full-test-run-3.txt` |
| U3 | backend unit, full | 3589 passed, 1766 skipped, 1 warning (Starlette) | review round 1 fixes (traceability: one new entry, three notes) | `V1-056-slice-10c-2a-3-unit-test-run-3.txt` |
| P4 | PostgreSQL, full (under `caffeinate -dims`) | 1 failed, 1928 passed, 2 warnings | review round 1 fixes | `V1-056-slice-10c-2a-3-full-test-run-4.txt` |
| P5 | PostgreSQL, full (under `caffeinate -dims`) | 1929 passed, 1 warning (Starlette) | correction 1 of cause D | `V1-056-slice-10c-2a-3-full-test-run-5.txt` |
| U4 | backend unit, full | 3589 passed, 1766 skipped, 1 warning (Starlette) | review round 2 fixes; before round 3 (standing rule) | `V1-056-slice-10c-2a-3-unit-test-run-4.txt` |
| P6 | PostgreSQL, full (under `caffeinate -dims`) | 1929 passed, 1 warning (Starlette) | review round 2 fixes; before round 3 (standing rule) | `V1-056-slice-10c-2a-3-full-test-run-6.txt` |
| U5 | backend unit, full | 3589 passed, 1768 skipped, 1 warning (Starlette) | owner answer to Q-2026-10-08-48 (two tests, traceability) | `V1-056-slice-10c-2a-3-unit-test-run-5.txt` |
| P7 | PostgreSQL, full (under `caffeinate -dims`) | 1931 passed, 3 warnings (Starlette; two pydantic alias warnings in `test_credit_refund_api_migration.py`) | owner answer to Q-2026-10-08-48 | `V1-056-slice-10c-2a-3-full-test-run-7.txt` |

In P1 and P2 all nine 10c-1b tests (six rebuilt) and the whole 10c-2a-2 module passed. Before U2
and P3 (fresh session): static checks clean, each in its own call (`ruff format src tests`: 307
unchanged; `ruff check src tests`; `ruff format --check src tests`; `mypy`: 307 files); the
migration-only check (a throwaway copy of `scripts/database-test.sh` in the session scratchpad
that runs `uv run alembic upgrade head`) reached `20261107_103 (head)`; the read-only search of all
backend tests for the changed and new functions, the service commands and the 8a-1 message found
the three modules above, the unit test, `test_deposit_application_reversal_migration.py` (its
function list compares migrations 100 and 101 only), `test_final_settlement_migration.py` (the
patched trigger function keeps SECURITY DEFINER and its search path) and
`test_settlement_charge_reduction_migration.py` (the 10c-1a recorder's own refusal); all passed
in P3.

- Cause A (test fixture; correction 1 of 2 used): P1, the Rent and Trash fixture of the forfeiture
  module adds a Trash service period that overlaps one on the shared Property
  (`property_service_approval_periods_no_overlap`); corrected by a three-line Initial Invoice with
  the `mixed_rent_case` service terms. P2, the same test: that Invoice owes 95,700 (Rent 92,903,
  Trash 1,597, Internet 1,200), more than the Pet Deposit's 20,000, so the set-up "the Pet Deposit
  pays every line" is wrong. Correction 2 of 2 (owner approved, 2026-10-07): at the Settlement the
  remaining Pet Deposit, by the Customer's choice, pays both Service lines and part of the Rent,
  and Rent debt stays; the Refund of the first Service line reverses only that line's
  application, the other lines' applications stay active (the Q-46 case), and the released value
  pays the Rent still owed under a new Customer choice for this correction (Q-44 answer 3), so
  nothing is refunded (Q-42 answer 2). Passed in P3.
- Cause B (test; correction 1 of 2 used): PostgreSQL releases a transaction's locks when a
  statement fails, so the step-only lock check now runs the step to success after a release by
  hand and probes with `FOR NO KEY UPDATE NOWAIT`. Not reached in P2 (cause C); passed in P3.
- Cause C (root cause found in the fresh session; no change): in P2, after the cause A test
  failed, the next two tests failed in `signed_with_initial` with `Signature evidence is invalid`
  (`app.record_lease_signature`, line 17). Line 17 raises only when `p_signed_at` is NULL or after
  `statement_timestamp()`, or the reason is blank; the reason is a constant, so the signature time
  was later than the database's statement time. The fixture `signature_command`
  (`test_lease_lifecycle_migration.py`) takes `signed_at` from the host clock
  (`datetime.now(UTC)`) before it opens a fresh connection, so the host clock was ahead of the
  database container's clock at that moment. No database row and no Python state enter that
  comparison; the cause A test patches no clock and holds no connection after it fails, so it
  left nothing behind (its services reuse the shared Property's existing terms, as
  `mixed_rent_case`). Evidence for the clock: the host power log shows the display went to sleep
  at 21:56:18 and woke at 22:04:49, just before the new module ran (P2 ended 22:05:20); P1 ran
  right after a `caffeinate` session, P2 without one; three samples in the fresh session showed the
  container clock in step with the host. Not product code (the database rightly refuses a
  signature in the future) and not shared test state, so nothing was changed; P3 ran under
  `caffeinate -dims` and passed. For the owner: the lease signature fixtures still take host time,
  so a host clock ahead of the Docker VM clock can fail them again; hardening them to database time
  (as the financial fixture clocks were) would change shared historical helpers and is not done
  here (slice 12 item in the plan).
- Cause D (test helper, my review round 1 change; correction 1 of 2 used): P4 failed
  `test_the_relaxed_checks_accept_only_a_correction_s_own_records` with "DID NOT RAISE": the
  round-1 version of `failure` rolled back right after the action, so a refusal that the test
  expects at commit (a Credit Refund whose details name a Deposit, a deferred check) never ran.
  Corrected: `failure` runs `SET CONSTRAINTS ALL IMMEDIATE` after the action (the deferred checks,
  as a commit runs them) and then always rolls back. Passed in P5.

## Review round 1 (2026-10-07; fresh read-only subagents, given the diff, the rule IDs, the owner answers and the takeover file)

Security: 0 blockers, 1 should-fix, 3 notes. Independent: 0 blockers, 2 should-fix, 6 notes.

- Security SF-1 (fixed): the confirm locked the corrected Invoice `FOR UPDATE` before
  `app.lock_settlement_correction_plan` locked the step's Payments, Credits and the Lease's
  Late-payment Charges; a one-call writer that locks a Charge and then its source Invoice could
  deadlock with it (40P01; no money effect). Fix: the confirm takes the step's locks first; the
  lock function (patched in migration 103, same signature) takes a `REFUND` draft's own Invoice
  `FOR UPDATE` in its id-ordered Invoice pass after the Charges; the confirm reads the Invoice
  after that. Tests: the source order (Settlement draft lock, Lease, source Payment, lock function,
  Invoice) and a two-connection test (while another session holds a step Credit's Payment, the
  confirm waits there and the other session can still lock the Invoice `NOWAIT`); the catalog test
  lists the lock function as changed.
- Independent SF1 (fixed): no test released a Payment allocation and a Deposit application of one
  line in one correction. New test
  `test_a_mixed_line_releases_the_newest_payment_before_the_deposit_application`: the newest
  Payment allocation released whole (5,000), then 1,000 of the older Pet Deposit application,
  reversed whole (7,500); the released Credit pays the line before the Pet Deposit (Q-42 answer
  2); the Pet Deposit pays the rest by a new Customer choice and 6,000 is refunded while the
  unpaid Initial Rent stays (BR-DEP-027); every other line's paying sources are unchanged (read
  through `app.settlement_refund_line_sources` before and after); no Credit Refund. The Refund to
  another signed Signer (BR-REFUND-015) stays covered by the 10c-2a-2 step test; the `REFUND`
  recorder passes the step's recipient and agreement to the same plan check unchanged.
- Independent SF2 (answered, plan item): `test_a_deposit_application_on_another_line_of_the_invoice_stays`
  and `mixed_rent_case` are date-bound (Lease 2026-07-27 to 2027-06-30 on the single shared
  Property's Service terms); their dates cannot follow today without new approval periods that
  overlap the existing ones; slice 12 item with the date they stop working (after 2027-06-30 at
  the latest).
- Notes fixed: a remaining Pet Deposit choice equal to an earlier confirmed correction's choice is
  refused too (test in the BR-DEP-027 test; the text-only comparison is a known limit in docs/010);
  the test 1 refusal asserts the message; a comment that the 8e-1 refusal fires before 8a-1 for an
  unlinked Adjustment; `failure` rolls back always (see cause D); the docs/010 wording of tests 5
  and 6.
- Notes answered in docs/010 (sub-slice entry, choices 7 and 8): the Q-46 exception does not
  check the Adjustment type or the correction kind (the owner's answer does not; only `REFUND`
  reaches it today; BR-INV-044 still refuses a debit of a paid line); a `REFUND` draft recorded
  before migration 103 fails closed (22023, nothing written) and none exists in a persistent
  database. Not taken: a test of an Adjustment linked to another Settlement's correction (the 8e-1
  check refuses it first; optional).
- Owner's checks, independent reviewer: the six rebuilt 10c-1b tests are not weakened (each
  compared with HEAD; every behavioural assertion kept); the docs/010 list is accurate (one
  wording note, fixed); the release is newest first across the three kinds and stops once the
  paid part is covered; the re-posted rests keep every other line's amounts; no path changes how
  another already-paid line is paid.
- After the fixes: static checks clean (one import order slip fixed); migration-only check
  reached `20261107_103 (head)`; U3, P4 (cause D), P5 green.

## Review round 2 (2026-10-08; new fresh read-only subagents, given the full diff, the rule IDs, the owner answers, the takeover file and this record)

Security: 0 blockers, 1 should-fix. Independent: 0 blockers, 0 should-fix, 5 notes. One
should-fix in total, so round 3 under the standing rule (owner, 2026-10-04).

- Security SF (fixed): the confirm locked the released sources' Payments and Credits in its own
  id-ordered passes before `app.lock_settlement_correction_plan` locked the Credit steps' Payments
  and Credits in another pass, so Payments were not locked in one id order; a Customer with
  Credits used on two Leases could link two Leases' lock sets (a crossed order with another
  correction or a Settlement confirm, 40P01; no money effect). Fix: the confirm takes no Payment or
  Credit lock of its own; the lock function (migration 103 patch, same signature) adds, for a
  `REFUND` draft, the released sources' Credits to its Credit pass and their Payments to its
  single id-ordered Payment pass. The comment before the lock function in migration 102 is a
  historical migration and is not edited; the confirm's comment, docs/004 and docs/010 state the
  order. Tests: the confirm's source has no Payment or Credit lock; the lock function alone on an
  empty-plan `REFUND` draft makes a second connection's `FOR UPDATE NOWAIT` on the released
  Payment and `FOR KEY SHARE NOWAIT` on the corrected Invoice get 55P03.
- Independent N1 (fixed by the same test): no test reached the round-1 Invoice patch (the
  two-connection test's draft has steps on that Invoice); the empty-plan test above does.
- Independent N2 (fixed): `blocked_by` docstring and docs/010 now say "blocked by the holder while
  it holds or waits for a lock on app.leases".
- Independent N3 (answered, docs): the earlier-correction choice check runs when the draft is
  recorded; a second draft recorded with the same text before the first is confirmed becomes stale
  once the first correction changes the Settlement's open total and closing balances (the security
  reviewer confirmed the plan recheck compares them); docs/004 and docs/010 say so.
- Independent N4 (fixed): the mixed-line test also shows a Deposit-first plan refused (55000,
  Credit before Deposits).
- Independent N5 (fixed): the plan's as-built note, the traceability notes; NOW.md and this record
  at the commit.
- Owner's checks (both reviewers): the six rebuilt 10c-1b tests are not weakened; the release is
  newest first across the three kinds, stops once the paid part is covered, and no other
  already-paid line changes how it is paid.
- After the fixes: static checks clean, each in its own call; migration-only check reached
  `20261107_103 (head)`; read-only search: the same four modules; U4 and P6 green.

## Review round 3 (2026-10-08; new fresh read-only subagents; standing rule: no should-fix allowed)

Security: 0 blockers, 0 should-fix, 2 notes. Independent: 0 blockers, 2 should-fix, 3 notes.
STOPPED under the standing rule (Q-2026-10-08-48). Nothing fixed after round 3; nothing
committed.

- Independent SF-1 (test coverage): at HEAD, 10c-1b tests 5 and 6 were the only PostgreSQL tests
  that confirmed a `REFUND` correction whose amount included an unpaid part (12,200 with 12,100
  unpaid; 12,300 with 12,200 unpaid), so test 5's final `outstanding == 0` proved that the unpaid
  part is removed with the paid part (docs/004: "An unpaid part of the amount is removed with
  it"). After the rebuild both correct 100 on a fully paid line; no test now confirms a `REFUND`
  with 0 < outstanding < amount, and docs/010 states the new amounts but not the lost coverage. It
  matters more now: on a Deposit-paid line that keeps debt, `amount - outstanding` drives the
  release and the overlay must equal the real state after the Adjustment (the reviewer's
  derivation says it does; no test shows it). Proposed fix: two tests in the new module (a Payment-
  paid charge after closure partly paid, Refund above the paid part; a Deposit-paid line that still
  owes, Refund removing the unpaid part and releasing part of the Deposit application), the six
  rebuilt tests unchanged, and a docs/010 sentence.
- Independent SF-2 (plan text): the plan's "Notes for the writers" (10c-2a-2 entries, lines 305
  and 313) still tell 10c-2b and 10d to lock "its own sources (for example the Payment of an
  allocation it releases), then call the lock function", the separate pass that round 2 removed;
  the lock function's new branch runs only for `REFUND`. Proposed fix: amend both notes (a variant
  takes no lock of its own after the Lease row; it extends the lock function for its variant).
- Notes: (independent) the docs/004 10c-1b paragraph still describes the old lock order and "a
  Deposit-paid Invoice stays refused" without an "as amended by 10c-2a-3" marker; the source
  assertion "no Payment or Credit lock of its own" matches only the old text (add
  `serialize_payment_state` and aliases); docs/010 choice 5 should say "except the Refund method,
  `FOR SHARE`, last". (Security) no test pins the single Payment pass inside the lock function
  (count the lock statements in its source); a Payment id in the draft payload is not joined to
  `app.payments`, but a missing one fails closed (23503) and only the definer recorder writes it.
- Owner's checks: both reviewers found the six rebuilt tests keep every assertion (the independent
  reviewer: test 5's final check is now vacuous, SF-1) and the release follows Q-41 answer 2 (newest
  first, only until the paid part is covered; no other already-paid line changes how it is paid).
  Security check of the lock order: one global order, no cycle with the one-call writers, the
  Settlement confirm, another Lease's correction or the move-out inspection; no check before its
  lock; non-`REFUND` drafts unchanged.

## Owner answer to Q-2026-10-08-48 (2026-10-08) and the fixes

Option (a), an owner exception like Q-43 (recorded in docs/010 and the questions file).

- SF-1: two new tests in the new module, each amount checked to the cent; the six rebuilt tests
  unchanged; docs/010 says where their lost coverage moved.
  `test_a_refund_above_the_paid_part_also_removes_the_unpaid_part` (a 1,500 charge after closure,
  1,000 paid, Refund 1,200: unpaid 500 removed, allocation reversed whole, 300 re-posted, 700
  Credit recognized and refunded, charge 300 fully paid);
  `test_a_deposit_paid_line_that_still_owes_is_refunded_above_its_paid_part` (a line paid 7,500 by
  the Pet Deposit that owes 5,000, Refund 6,000: unpaid 5,000 removed, 1,000 released, the
  application reversed whole, 7,500 back to the Pet Deposit, the stored overlay equals the state
  after the release, the plan pays 6,500 and refunds 1,000; the Pet Deposit totals 20,000; no
  Credit; no other line changed). The mixed-line test's set-up became the shared `pet_paid_case`.
- SF-2: both plan notes amended (a variant takes no lock of its own after the Lease row; it extends
  the lock function for its variant).
- Notes: docs/004 10c-1a and 10c-1b paragraphs marked "as amended by 10c-2a-3"; docs/010 choice 5
  names the Refund method lock (`FOR SHARE`, last); the lock test also asserts no
  `serialize_payment_state` in the confirm and one Payment pass and one Credit pass in the lock
  function. Security note 2 (a payload Payment id not joined to `app.payments`) fails closed; no
  change.
- Runs: static checks clean, each in its own call; migration-only check reached
  `20261107_103 (head)`; read-only search: the same four modules; U5 and P7 green.

## Limited review after Q-2026-10-08-48 (2026-10-08; new fresh read-only subagents, given the changes since round 3 as an interdiff and the full diff)

Independent: 0 blockers, 0 should-fix, 5 notes. Security: 0 blockers, 0 should-fix, 3 notes. Both
confirmed that no migration, product code or grant changed since round 3; the independent
reviewer worked both new tests by hand and found that each fails if the unpaid part is kept or the
release or the Deposit return is wrong; the six rebuilt tests are unchanged since round 3; the
source assertions match the stored bodies. Under the owner's answer, 10c-2a-3 is committed with
no further change to the reviewed content. Open notes, carried into the 10c-2a-4 pre-code design
(plan text) or slice 12 (test hardening), none changing behaviour:

- Plan text: the amended notes (plan 10c-2a-2 entries) keep the old clauses in front of the
  amendment ("after its own source locks", "before its own sources"); delete them, say "its single
  id-ordered Payment, Credit and Invoice passes", and add the exception "except the Refund method,
  `FOR SHARE`, last"; the 10c-2a-3 pre-code design's "Confirm:" bullet needs an "as amended by
  security review round 2" marker; the as-built note should list the two new tests.
- docs/004 wording: "corrects such a line only with a `REFUND`" should read "such an Invoice's
  lines" (the 10c-1a refusal is per Invoice).
- Test hardening (slice 12): the lock test's source assertions match exact text only (use a regex
  over `app.payments` and `app.customer_credits` row locks, or `"app.payments" not in` the confirm
  and one `app.payments` in the lock function); the unpaid-part Payment test could also assert its
  stored overlay (a wrong overlay already fails it as stale at the step).
