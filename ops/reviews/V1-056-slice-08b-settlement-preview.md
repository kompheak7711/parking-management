# V1-056 sub-slice 8b — Final Settlement preview: review record

Sub-slice: 8b (migration `20261024_89`). Not committed. Base commit: d8cb04f.
Rule IDs: BR-SETTLE-002, BR-SETTLE-003, BR-SETTLE-006, BR-SETTLE-011, BR-SETTLE-017, BR-CREDIT-008,
BR-DEP-022, BR-DEP-023, BR-DEP-026, BR-DEP-027, DL-032; owner answers to Q-2026-10-05-20, -21, -23, -24.

## Runs before review round 1

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U1 | backend unit, full | 3445 passed, 1645 skipped, 1 warning (known Starlette deprecation) | first run of 8b | `V1-056-slice-08b-unit-test-run.txt` |
| P1 | PostgreSQL, full (`./scripts/database-test.sh`) | 1803 passed, 1 warning (same) | first run of 8b | `V1-056-slice-08b-full-test-run.txt` |

Static checks before U1 (separate commands, no test run): `ruff format` on the four changed Python
files, then `ruff check src tests` (one import-order fix with `--fix`, then clean),
`ruff format --check src tests` (285 files formatted), `mypy` (no issues in 285 files).
No correction was used.

Read-only search for affected tests before P1: 26 head-revision assertions moved from
`20261023_88` to `20261024_89` (the revision lookup in `test_deposit_application_ledger_migration.py`
and one comment in `test_migrations.py` keep 88); the whole-catalog function tests are pinned to
earlier revisions; draft, Settlement and application counts in other tests are scoped by id; the 8a-1
least-privilege list still holds (`app.lease_deposit_kept_rule` is replaced in place). The new module
runs after the Utility modules, because `test_utility_consumption_migration.py` deletes every
Utility rate in a transaction and a final Utility Invoice line references a rate.

## Round 1 (2026-10-05)

### Independent review: 2 blockers, 4 should-fix, 6 notes

- B1 (blocker): a Deposit with a ground and nothing held is `FORFEITURE_REQUIRED` for ever; the
  forfeiture draft refuses a Deposit that holds nothing (migration 83). Typical: BR-LEASE-005 for
  an unpaid Security Deposit, BR-DEP-022 with an unpaid Pet Deposit, a reversed receipt. The plan
  says "still held". Planned fix: `FORFEITURE_REQUIRED` and its issue only when the held amount is
  above zero; otherwise path `NOTHING_HELD` (never applied, no issue); test that a BR-LEASE-005
  termination with an unpaid Security Deposit can become ready.
- B2 (blocker): the Late-payment loop reads only UNPAID Invoices; the review allows PARTIALLY_PAID
  too (migration 39). Planned fix: loop over UNPAID and PARTIALLY_PAID, test a partly paid overdue
  Invoice, correct docs/004.
- S1: the cleaning rule (rate in force at the move-out, else the current rate) differs from the
  slice 4 command (current rate only, zero refused); a rate set to 0 after the move-out blocks until a
  positive rate is restored; the in-force branch is untested. Needs the owner (Q-2026-10-05-25).
- S2: step 5 `CUSTOMER_ONLY` for a reversed BR-DEP-022 Pet Deposit is in no rule: BR-DEP-027 names
  only the unpaid-Initial, non-pet violation and 30-day default terminations, and the answer to
  Q-2026-10-05-24 says that Pet Deposit "follows the Pet Deposit steps of DL-032". Needs the owner
  to confirm the reading (Q-2026-10-05-25).
- S3: tests missing for a BR-DEP-027 termination (Security `FORFEITURE_REQUIRED`, Pet `DL_032`,
  step 5) and for two Customers (per-Customer obligations and Credit bounded to its own Customer).
  Planned fix: both tests.
- S4: a Utility period with consumption that is finalized after the final Utility Invoice is not
  flagged (only the catch-up command bills it). Planned fix needs the owner because it adds a
  blocking issue the plan does not list (Q-2026-10-05-25).
- Notes: N1 the guard applies a DL_032 Deposit while a new forfeiture draft is pending (8e must
  re-check every blocking issue under its locks; plan note); N2 an unexpected read error maps to
  "replay the command", and an ambiguous termination record fails the whole preview (11e note);
  N3 the kept-rule error branches are untested (planned: one small test); N4 `PENDING_DRAFT` is not
  tested for the forfeiture reversal, receipt reversal, Pet Refund and Payment-source Refund drafts
  (planned: add the cheap ones); N5 the database checks only an active person, like the other
  runtime reads (accepted); N6 one Customer's Credit may show as an upper bound in two Settlements
  (accepted: upper bounds only).

### Security review: 0 blockers, 2 should-fix, 5 notes

- S1: `PENDING_DRAFT` returns `draft_id`, `kind` and `variant` of Refund, forfeiture and Payment
  move drafts to a holder of only `final_settlements.prepare`, while a reader without
  `financial.approve` sees only drafts of the capabilities it may prepare (slices 2 and 6b).
  Planned fix: the issue stays (so `ready` stays false), but its identity is shown only to a
  `financial.approve` holder or a holder of the draft's prepare capability; unit and database tests.
- S2: tests for an active SERVICE identity and a deactivated person (both 42501), and
  `app.lease_deposit_kept_rule` in the no-EXECUTE list. Planned fix: add them. The requested
  second-Property test is answered in writing: V1 stores one Property (`properties_singleton_key_unique`,
  migration 13), so another Property's Credit or draft cannot exist; the Property filters stay as
  defensive checks.
- Notes: N1 run the read in a read-only transaction (planned: `read_only` on the read connection);
  N2 no capability check in the database (accepted, same as the other runtime reads); N3 Credit ids,
  line descriptions and other Signers' ids are in the preview (accepted, API-071 lists Credit);
  N4 the Refund pending-draft match covers every Credit and Payment of the Settlement Customers,
  not only this Lease's (answered: a Customer's Credit and unallocated Payment value can pay this
  Lease's debt, so a pending Refund of them changes what is available; kept); N5 8e must re-check
  pending drafts under the Deposit lock, and a statement timeout on a read maps to "replay"
  (plan notes for 8e and 11e).

## Status

STOPPED after round 1 (takeover section 6: two findings need a rule decision and one fix adds a
blocking issue the plan does not list). Owner question: Q-2026-10-05-25 in ops/V1_056_QUESTIONS.md.
No fix is made yet; all 8b files are in the working tree.

## Owner answers and round-1 fixes (2026-10-05)

Owner answered Q-2026-10-05-25 (yes to all four; docs/010). Fixes made: B1 (`NOTHING_HELD` path),
B2 (PARTIALLY_PAID Invoices in the Late-payment check), S1 (current cleaning rate), S2 (staff step
everywhere except the three BR-DEP-027 terminations), S3 (BR-DEP-027 termination test, two-Customer
test, kept-rule error branches, forfeiture reversal and receipt reversal pending-draft cases),
S4 (`UTILITY_PERIOD_NOT_BILLED`), owner answer 4 (`ONE_TIME_CHARGE_NOT_INVOICED`), security S1
(pending-draft identity only for `financial.approve` or the draft's prepare capability; the preview
takes the reader's draft capabilities), security S2 (service identity, deactivated person, kept rule
in the no-EXECUTE list; second Property answered in writing), security N1 (read-only transaction).

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U2 | backend unit, full | 3446 passed, 1648 skipped, 1 warning | round-1 fixes | `V1-056-slice-08b-unit-test-run-2.txt` |
| P2 | PostgreSQL, full | 1 failed, 1805 passed | round-1 fixes; failure in the new test: `CheckViolation: Meter measurement unit conflicts with Utility Rate history` (the test's WATER meter used the helper's default KWH) | `V1-056-slice-08b-full-test-run-2.txt` |
| P3 | PostgreSQL, full | 1 failed, 1805 passed, 2 warnings | correction 1 of 2 for the P2 cause (WATER meter in M3); the 8b module passed; failure outside 8b: `test_refund_migration.py::test_usd_refund_khr_origin_uses_recorded_usd_without_repricing`, `LockNotAvailable` on `app.payment_allocations` from `LOCK TABLE ... IN SHARE MODE NOWAIT` in `app.assert_payment_excess_eligible` | `V1-056-slice-08b-full-test-run-3.txt` |

Static checks after the fixes: `ruff check` clean, `ruff format --check` clean, `mypy` clean (one
variable rename in the new test for mypy).

P3 analysis (read only): `test_refund_migration.py` runs at position 60 of the suite list, before
the 8b module (81), and P1 and P2 passed it; 8b changes no lock, table or function that path uses.
It matches the known intermittent NOWAIT lock failure (ops/NOW.md 2026-10-02 and 2026-10-03, 9f-3:
likely autovacuum, not proven). The second P3 warning is a pydantic `UnsupportedFieldAttributeWarning`
(alias `case_id`), not from 8b code. Under the run rules there is no retry without a correction, and
takeover section 6 stops the work when a test that passed before fails for a cause outside the
slice. STOPPED before review round 2 (Q-2026-10-05-26).

Owner answer to Q-2026-10-05-26 (2026-10-05): option (a), one more full PostgreSQL run (P4); stop if
`test_usd_refund_khr_origin_uses_recorded_usd_without_repricing` fails again; the P3 failure is
recorded in docs/010 with the earlier dates (2026-10-02, 2026-10-03); slice 12 item added to the plan.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| P4 | PostgreSQL, full | 1806 passed, 1 warning (known Starlette deprecation) | owner-approved rerun after the outside intermittent failure in P3 (Q-2026-10-05-26) | `V1-056-slice-08b-full-test-run-4.txt` |

`test_usd_refund_khr_origin_uses_recorded_usd_without_repricing` passed in P4. Next: review round 2.

## Round 2 (2026-10-05)

### Security review: 0 blockers, 0 should-fix, 4 notes

All round-1 security findings are fixed (draft identity masking, scoping tests, read-only transaction);
grants, search_path, Property scoping, the relaxed trigger and the `NOTHING_HELD` path checked.
Notes: N1 a database that applied the round-1 version of revision 89 would keep the old 3-argument
preview (answered: no persistent database ever applied revision 89; test databases are created
fresh each run; planned cheap test that the 3-argument function does not exist); N2 the empty,
NULL-element and over-10 capability inputs have no database test (planned: add them); N3 no preview
test of the Deposit draft capabilities (`deposits.dispose`, `deposits.correct`) (planned: one case);
N4 a prepare-only reader may guess a hidden draft's kind from other issues (accepted).

### Independent review: 0 blockers, 2 should-fix, 7 notes

- S1 (needs the owner): `ONE_TIME_CHARGE_NOT_INVOICED` also flags a charge source the business
  withdrew: a draft correction moves the Invoice draft to a replacement source, or a wrong one-time
  Invoice is VOIDed with a reason; a source cannot be cancelled, so the only way to clear the issue
  is to bill the wrong charge again and credit it away (BR-SETTLE-003 says valid obligations).
  Fails closed. Owner question Q-2026-10-05-27.
- S2 (fixed): ops/V1_056_PLAN.md lines 105, 113, 114, 116 and 129 amended with pointers to the
  answers to Q-2026-10-05-23, -24 and -25.
- Notes: N1 the promised B1 test used an unpaid Pet Deposit at pet noncompliance instead of an
  unpaid Security Deposit at BR-LEASE-005 and does not assert `ready`; `CUSTOMER_ONLY` is tested
  only for BR-LEASE-025; the refusal at the nothing-held test cannot tell the path guard from the
  amount check (planned: BR-LEASE-005 and BR-LEASE-028 cases, a ready assertion, a path-only
  refusal check); N2 the Payment-source Refund and Pet Refund pending-draft branches are untested
  (planned: Payment-source case); N3 the Settlement path counts a Reservation disposition too
  (planned: scope to dispositions of the Lease, a defensive change); N4 held at `infinity` against
  the forfeiture draft's `statement_timestamp()` (accepted: equal unless an event is dated in the
  future); N5 `_call(read_only=False)` sends `BEGIN READ WRITE` for commands (planned: `None`
  keeps the earlier behavior); N6 the "final Utility Invoice not yet created" half of
  `UTILITY_PERIOD_NOT_BILLED` is untested (planned: a case); N7 ops/NOW.md was out of date (fixed).

## Status

STOPPED after round 2 (standing rule would allow round 3, but should-fix S1 needs a rule decision):
Q-2026-10-05-27. No code change after P4; only the plan, this record, the questions file and
ops/NOW.md changed.

## Owner answer to Q-2026-10-05-27 and round-2 fixes (2026-10-05)

Option (b) plus the information list (docs/010). Built: `ONE_TIME_CHARGE_NOT_INVOICED` leaves out
VOIDed and replaced charges; `information` lists `VOIDED_CHARGE_NOT_BILLED_AGAIN`. Round-2 notes
taken: BR-LEASE-005 nothing-held case with `ready` and `CUSTOMER_ONLY` at BR-LEASE-005 and
BR-LEASE-028; path-only refusal check (message); Payment-source Refund pending draft; Deposit draft
capabilities in the masking test; empty, NULL-element and over-10 capability inputs; no 3-argument
preview; `UTILITY_PERIOD_NOT_BILLED` before the final Utility Invoice; reversed forfeiture only
through a disposition of the Deposit's own Lease; `read_only=None` for commands.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U3 | backend unit, full | 3446 passed, 1650 skipped, 1 warning | Q-27 answer and round-2 notes (standing rule: before round 3) | `V1-056-slice-08b-unit-test-run-3.txt` |
| P5 | PostgreSQL, full | 1808 passed, 3 warnings (Starlette deprecation; two pydantic `UnsupportedFieldAttributeWarning` raised inside `test_credit_refund_api_migration.py`, not 8b code) | same | `V1-056-slice-08b-full-test-run-5.txt` |

Static checks: `ruff check`, `ruff format --check`, `mypy` clean. Next: round 3.

## Round 3 (2026-10-05)

- Independent: 0 blockers, 0 should-fix, 8 notes. Taken now (docs only, no code change): the plan's
  8b bullet names the Q-27 answer and an 8e/11e item says the approver sees `information`; docs/004
  says a VOIDed cleaning charge is listed and still blocks; the implementer remark in the Q-27 answer
  is marked as a note; ops/NOW.md is updated with the checkpoint. Moved to the plan (slice 12 and
  8e/11e): untested VOIDed cleaning case and VOIDed charge billed again, the JSON lookup without an
  index, the capability limit kept above `PREPARE_CAPABILITIES`. Not changed: BR-DEP-027 text (its
  list does not say "only"; docs/010 records the Q-25 answer).
- Security: 0 blockers, 0 should-fix, 5 notes: the replaced flag never resets (safe today; plan);
  a draft correction may move a draft to another Lease's charge, so the replaced charge neither
  blocks nor is listed (owner item in the plan); the information list may name a Customer of the
  Lease who is not in `customers` (accepted); the own-Lease narrowing and `read_only=None` have no
  test (plan); 8e re-checks every blocking issue under the Deposit lock (plan).

Round 3 has no should-fix, so 8b is committed under the standing round-3 rule. Final runs: U3 3446
passed, P5 1808 passed. Corrections used: 1 of 2 for the WATER meter unit (P2). Owner-approved
rerun: P4 after the outside lock failure in P3.
