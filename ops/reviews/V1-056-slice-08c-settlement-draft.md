# V1-056 sub-slice 8c — Final Settlement draft: review record

Sub-slice: 8c (migration `20261025_90`). Not committed. Base commit: 83f5896.
Rule IDs: BR-AUTH-010, BR-SETTLE-004, BR-SETTLE-005, BR-SETTLE-006, BR-SETTLE-007, BR-SETTLE-008,
BR-SETTLE-017, BR-DEP-027, BR-CREDIT-006, BR-CREDIT-008, BR-REFUND-014, BR-REFUND-015, DL-032;
owner answers to Q-2026-10-05-20 (strict order), -21, -23 (answer 4: receipt reversal waits in
both directions), -25, -28 (replaced one-time charges listed under `information`) and -29
(Credit rules).

## Runs before review round 1

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U1 | backend unit, full | 1 failed (`test_traceability.py::test_traceability_manifest_covers_executable_tests`: the 11 new tests had no manifest entry), 3449 passed, 1657 skipped | first run of 8c | `V1-056-slice-08c-unit-test-run.txt` |
| U2 | backend unit, full | 3450 passed, 1657 skipped, 1 warning (known Starlette deprecation) | after correction 1 of cause "traceability" (11 entries appended) | `V1-056-slice-08c-unit-test-run-2.txt` |
| P1 | PostgreSQL, full (`./scripts/database-test.sh`) | migration `20261025_90` failed with `syntax error at end of input` (a `CASE` inside a PL/pgSQL `IF` condition ends the condition at its `THEN`), so 109 failed and 1517 errors at setup, 190 passed | first run of 8c | `V1-056-slice-08c-full-test-run.txt` |
| P2 | PostgreSQL, full | 1816 passed, 1 warning (same) | after correction 1 of cause "migration SQL syntax" (the `CASE` put in parentheses) | `V1-056-slice-08c-full-test-run-2.txt` |

Static checks before U1 (separate commands, no test run): `ruff format` on the changed Python
files, `ruff check src tests` (one long line fixed, then clean), `ruff format --check src tests`
(286 files formatted), `mypy` (no issues).

Read-only search for affected tests before P1: 26 head-revision assertions in 14 modules moved
from `20261024_89` to `20261025_90` (the revision lookup in the preview module keeps 89); the
preview's `information` is asserted only in
`test_final_settlement_preview_migration.py::test_withdrawn_one_time_charges_do_not_block_and_voided_ones_are_listed`
(two assertions narrowed, docs/010 note); the patched receipt reversal functions are checked
elsewhere only for owner, privileges and definer settings, which `CREATE OR REPLACE` keeps; the
whole-catalog function tests are pinned to earlier revisions; the new module runs right after the
preview module. After the P1 correction the search was unchanged.

Between P2 and round 1 (no run): two traceability entries named DB-SETTLE-002 (the closure
snapshot table, 8e); changed to DB-SETTLE-001, where docs/004 now records the draft. docs/004,
docs/010 and the plan notes written.

## Round 1 (2026-10-05)

Both reviewers were fresh read-only subagents given the diff, the rule IDs, the takeover file and
the owner answers; neither edited anything or ran a test.

### Security review: 0 blockers, 1 should-fix, 4 notes

- SF1: `record_final_settlement_draft` checks the plan in one statement and computes the source
  digest in a later one; under READ COMMITTED a one-call allocation, Credit or Charge change can
  commit between them, so the stored plan and closing balance describe one state and the digest
  another, and the 8e stale check would pass. No money moves wrongly (8e re-checks), but the
  documented guarantee breaks. Fix: one statement for both; 8e the same and compare its
  recomputed result with the stored one.
- N2: 8e must take the Settlement advisory lock, then the per-Deposit advisory and row locks in id
  order, before writing its decision; the closure should serialize with the recorder.
- N3: the new `deposit_ids` branches and the preview's `replacement.id::text` lookup use no index
  (bounded by the 3 s timeout; fine at V1 scale).
- N4: all four receipt-reversal waits exist and fail safe; a Deposit created on the Lease between
  the lock loop and the preview would only lead to two pending drafts that block each other.
- N5: no change is a tightening that needs the owner.

### Independent review: 0 blockers, 4 should-fix, 8 notes

- S1: same as security SF1.
- S2 (needs the owner): a Credit step may name any line; the existing Credit application refuses
  Credit on an Invoice with Rent or Service lines unless it follows the Rent-first proposal or a
  Customer designation (BR-CREDIT-006, migration 41).
- S3 (needs the owner): docs/010 choice (2), Credit required only before a Deposit pays that
  Customer, relaxes DL-032 step 2 and BR-SETTLE-004 ("apply authorized Customer Credit first").
- S4: no test reaches the BR-CREDIT-008 refusal (one Customer only) although its traceability
  entry claims it; no Late-payment Charge target, no accepted Refund to another signed Signer,
  no two-Customer Credit-first case.
- Notes: choices (1), (3), (4), (5) are within the plan; the digest leaves out pet-damage
  classification, Signer status and Refund method state, so 8e must re-run the checks and compare
  the stored result; the 16,000-byte payload allows about 90 short steps; a JSON-null
  `target_kind` gives 55000 instead of 22023; the lock-order claim has no two-connection test;
  the wait guard takes no lock itself (8e must lock first); BR-DEP-019 is a loose traceability
  fit; the `OR` in the receipt-guard join stops the partial index from being used.

### Outcome

STOPPED before any fix: S2 and S3 need the owner (Q-2026-10-05-29, with the planned fixes for SF1,
S1, S4 and the notes). No run after round 1.

## Owner answer and fixes before round 2 (2026-10-05)

Owner answered Q-2026-10-05-29: (1) option (a), BR-CREDIT-006 applies (Rent-first proposal or
the Customer's designation as text); (2) option (a), each Customer's Credit is always used against
that Customer's own open debt, up to what it can pay, before any Deposit. Recorded in docs/010 and
ops/V1_056_QUESTIONS.md. Fixes made: the plan check returns the source revision from the same call
(one snapshot); `app.final_settlement_rent_first_line` and the designation key on Credit steps;
the always-use Credit rule; a JSON-null `target_kind` is 22023; the preview replacement lookup
compares UUIDs; tests: a payment after the draft makes it stale (a payment between two statements
of one call cannot be scheduled from a test), two Signers (Credit of another Customer refused,
Credit required with no Deposit paying that Customer, Refund to the other signed Signer with the
agreement accepted), a Late-payment Charge and a Rent line paid by the Pet Deposit, the Rent-first
order on a real mixed Initial Rent Invoice; traceability corrected (BR-CREDIT-008 moved to the
two-Signer test, BR-DEP-019 removed); 8e and slice 12 notes in the plan.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U3 | backend unit, full | 3450 passed, 1661 skipped, 1 warning | after the round-1 fixes | `V1-056-slice-08c-unit-test-run-3.txt` |
| P3 | PostgreSQL, full | 1820 passed, 1 warning | after the round-1 fixes | `V1-056-slice-08c-full-test-run-3.txt` |

Read-only search before P3: no other module references the changed or new functions; head
revisions unchanged since P2.

## Round 2 (2026-10-05)

### Security review: 0 blockers, 1 should-fix, 4 notes

- SF1 is fixed for the plan inputs and the digest. Should-fix: the preview's Late-payment review
  (`app.late_payment_review_snapshot`, migration 37, no volatility given, so VOLATILE) takes its
  own snapshot inside the STABLE call, so "one snapshot" is not exact. Fails safe in 8c (a Charge
  it sees changes the digest); in 8e the confirm must serialize with Late-payment Decisions or the
  function must become STABLE. Answered: wording corrected (migration comments, docs/004,
  docs/010) and the 8e requirement added to the plan; an earlier accepted function is not changed.
- Notes: step ids are stored as sent (8e casts to uuid; plan note); a pending Settlement draft
  blocks receipt reversals of its Deposits (owner-approved; 11e shows the blocking draft); a
  second unindexed scan of draft revision events (slice 12); lock order consistent.

### Independent review: 0 blockers, 1 should-fix, 7 notes

- SF-1: no test sent a Credit step on an Invoice with Rent or Service lines through the plan
  check, and none recorded a designation. Fixed: `mixed_rent_case` (Initial Rent Invoice with Rent,
  Trash Collection and Internet lines, never moved in, 500,000 of Credit) and
  `test_credit_on_a_mixed_rent_invoice_follows_the_proposal_or_a_designation` (Service before Rent
  and second Service before first refused; proposal order recorded; designation lets Internet go
  first and is stored; order equals `app.credit_application_proposal`).
- Notes taken: N1 as security SF above; N2 the new helper added to the least-privilege tuple; N3
  8e needs a writer for the `OTHER_APPLICABLE_OBLIGATION` basis (plan note); N4 traceability note
  reworded; N6 docs/010 8c entry reworded to the always-use rule; N7 NOW.md updated at the
  checkpoint. N5 (Credit to a Late-payment Charge) not added: the path has no Invoice key and no
  ordering rule; recorded here.

Round 2 has no blocker and 2 should-fix in total, so the standing rule allows one round 3 after
the full backend unit and PostgreSQL runs.

## Runs before round 3

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U4 | backend unit, full | 3450 passed, 1662 skipped, 1 warning | after the round-2 fixes (standing rule) | `V1-056-slice-08c-unit-test-run-4.txt` |
| P4 | PostgreSQL, full | 1 failed (`test_credit_on_a_mixed_rent_invoice_follows_the_proposal_or_a_designation`: the fixture recognized the Credit after the Initial Rent Invoice existed, refused with "Applicable obligations must be handled before excess disposition"), 1820 passed | after the round-2 fixes | `V1-056-slice-08c-full-test-run-4.txt` |
| P5 | PostgreSQL, full | 1821 passed, 2 warnings | after correction 1 of cause "mixed Rent fixture order" (Credit recognized before the Invoice; test-only, so U4 stands) | `V1-056-slice-08c-full-test-run-5.txt` |

The second warning in P4 and P5 is pydantic's `UnsupportedFieldAttributeWarning` raised while
`test_credit_refund_api_migration.py::test_credit_refund_competition_fixture_isolates_unrelated_shared_writer`
builds an API schema; 8c changes no API module; recorded, not hidden.

## Round 3 (2026-10-05)

### Security review: 0 blockers, 0 should-fix, 7 notes

The round-2 should-fix is answered acceptably: the Late-payment review is the only VOLATILE
function on the plan and digest path, it fails safe in 8c, and the 8e requirement is in the plan.
Notes confirm deny-by-default, no confirm or effect without `financial.approve`, no cross-Property
or cross-Customer leak or injection, consistent lock order, sound replay; the owner-approved
receipt reversal wait; no tightening that needs the owner.

### Independent review: 0 blockers, 0 should-fix, 5 notes

Both round-2 should-fix items are resolved (the Rent-first rule and the designation bypass are
proven through the plan check; the wording and the 8e requirement are in place). Notes: (1) only
an unknown Refund method is tested, not an inactive one (slice 12 item); (2) at a termination where
the staff step is allowed, the remaining Pet Deposit may pay debt the Security Deposit could pay and
the Security Deposit is then refunded (listed as choice (4a) in docs/010 for the owner); (3) NOW.md
and this header were stale (updated); (4) two inline SQL comments in migration 90 (the payload
comment in the recorder and the digest comment in the plan check) still say "same snapshot"
without the Late-payment exception that the docstring and the plan check header state; left as
they are, so the committed migration is exactly the code that P5 ran; (5) a charge both VOIDed and
replaced is listed twice under `information` (slice 12 item).

### Outcome

Round 3 has no should-fix, so 8c is committed under the standing round-3 rule. Final runs: U4
backend unit 3450 passed; P5 full PostgreSQL 1821 passed. Corrections used: traceability 1 of 2,
migration SQL syntax 1 of 2, mixed Rent fixture order 1 of 2.

P1 output is 52 MB (1,517 setup errors with tracebacks), so the commit holds
`V1-056-slice-08c-full-test-run-excerpt.txt` (the first error and the summary); the full file stays
in the working directory, untracked.
