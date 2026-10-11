# V1-056 sub-slice 10e-1c — a Refund already paid from a returned Payment: review record

Sub-slice: 10e-1c (migration `20261122_118`). Base commit: bb97083. Built in one session, which
stopped at the context limit during the review round 1 fixes; finished in a fresh session on
2026-10-11 (the "Still to do" list below, review round 2) and committed locally (see git log; the
commit right after bb97083). Not pushed.

Rule IDs: BR-SETTLE-013, BR-SETTLE-016, BR-PAY-042, BR-CREDIT-014, BR-REFUND-015, BR-AUTH-010;
DB-REFUND-002 (amended), DB-PAY-009, DB-SETTLE-005; owner answer (a) to Q-2026-10-10-72 point 1,
owner answers A, B and C to Q-2026-10-11-78, owner answer (a) to Q-2026-10-11-79, the owner check
of 2026-10-11 on the correction's own receipt reversal. Design: ops/V1_056_PLAN.md (10e-1c entry).

## Built (working tree)

- Migration `backend/migrations/versions/20261122_118_payment_return_refund_recovery.py`:
  `app.refund_corrections` gains the kind `RECOVERED_BY_CHARGE` and the column
  `recovery_obligation_id` (relaxing; a new check ties them); new internal functions (no grant):
  `refund_recovery_allowed`, `payment_return_recoveries` (the plan: recipient, net amount, Lease or
  none, charge form, blocking flags), `assert_payment_return_recoveries_allowed`,
  `assert_payment_return_recoveries_planned` (round 1), `write_correction_one_time_charge` (the 10b
  EXTRA_CHARGE writes moved here by a span replacement), `write_payment_return_recoveries`,
  `write_payment_return_receipt_reversal` (with the explicit Property check), `refund_recovery_json`,
  `payment_return_recoveries_written`; exact-text patches of the general refund correction check,
  its audit trigger, the Credit ledger cursor, both return sources, refusals, confirms, the 10e-1b
  write helper (now runs its own source, digest and refusal check), both results, the 10b confirm,
  and (round 1) the financial action context and the Refund resource (they leave the new column
  out).
- `backend/src/property_rental/credit.py`: the Credit ledger cursor accepts
  `REFUND_RECOVERED_BY_CHARGE`.
- Tests: new module `backend/tests/test_payment_return_recovery_migration.py` (last in
  `scripts/database-test.sh`); the three committed assertions of Q-79 (a) changed:
  `test_each_refusal_of_the_source_state_is_checked` and
  `test_refusals_stale_drafts_withdrawal_and_reads` (10e-1a),
  `test_refusals_stale_drafts_and_a_deposit_that_would_still_hold_money` (10e-1b), names kept;
  27 head-revision assertions in 15 modules move to `20261122_118`.
- `ops/traceability.json`: 10 entries appended, 3 notes updated (two more entries are still to add,
  see below).

## Runs (before the round 1 fixes)

Static checks each in its own call: clean (type check: one correction, cause = my new test code).
Migration-only check (throwaway copy of the test script, scratchpad): 117 upgrades, head
`20261122_118`, before T1, before T2 and after the round 1 migration fixes.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| T1 | PostgreSQL targeted: new module, 10e-1a, 10e-1b, 10b modules | 3 failed, 33 passed | first run | `V1-056-slice-10e-1c-targeted-test-run.txt` |
| T2 | same | 1 failed, 35 passed | T1 fixes | `...-targeted-test-run-2.txt` |
| T3 | new module | 10 passed | T2 fix | `...-targeted-test-run-3.txt` |
| U1 | backend unit, full (caffeinate) | 3744 passed, 1884 skipped, 1 warning | first unit run | `...-unit-test-run.txt` |
| P1 | PostgreSQL full (caffeinate) | 2048 passed, 2 warnings (known) | first full run | `...-full-test-run.txt` |

T1 causes (each correction 1 of 2): A migration (a Payment Refund's recovery row must be dated after
its own new charge, which the Payment's chronology reads); B test (missing amount argument); C test
(the Settlement draft needs the Pet Deposit choice). T2 cause D test (the fixtures share one
Property; the "other Property" is now a random id). Secret check of all five outputs: no database
URL with a password, no `password=`, no 64-character hex string.

## Review round 1 (fresh read-only subagents, during P1)

Independent: 1 blocker, 4 should-fix, 8 notes. Security: 0 blockers, 2 should-fix, 8 notes.

Fixed in the working tree (not yet run):
- B1 (the staff screen parser accepts exactly 17 correction keys): the context and the Refund
  resource leave `recovery_obligation_id` out; the new T4 test checks the keys.
- Security SF-1 / independent N3: the 10e-1a result lists the recoveries by the charge's audit
  correlation (the draft), not by the Payment's receipts.
- Security SF-2: the 10e-1b write helper re-checks the source digest (P5S02) before it writes.
- N1: all `invoice-lease:` keys in one id-ordered pass before any row lock (10e-1a after the
  `payment-return:` lock; 10e-1b after the Settlement's draft lock, own Lease included).
- N2: `assert_payment_return_recoveries_planned` cross-checks the plan against the source; test
  added (empty plan refused).
- N4: every closed Settlement the Refund belongs to must link the row. N5: a Credit released from
  an Invoice with no Lease is charged with no Lease (no fallback to the Payment's Lease).
- N8: a waiting draft naming a Refund the return recovers counts as waiting.
- Security notes: the recovery charge must be created in this transaction; the Deposit route
  counts only receipts not reversed; the span replacement checks marker order; the charge writer
  checks the Lease's Property.
- S3 (real-source refusals) and S4 (a third-party payer who is not a signed Customer gets a charge
  with no Lease): tests written (`test_the_refused_cases_on_real_sources`,
  `test_a_third_party_payer_who_is_not_a_signed_customer_is_charged_with_no_lease`); N6 partly: T4
  now verifies a 100 return first and expects the 200 net.
- S2 (refusals beyond owner answer B): written as Q-2026-10-11-81 (three points); until answered
  they stay refused, as before 10e-1c.

Still to do in the next session, in this order (all done 2026-10-11; see "Fresh session" below):
1. S1: rewrite the three changed rows of `test_each_refusal_of_the_source_state_is_checked` on real
   sources (a Payment Refund, a released Credit Refund, a Pet Refund-review Refund): assert the
   planned recovery exactly (kind, recipient, Lease or none, amount, charge form) and that the check
   passes.
2. N7 and the security test gap: in `test_a_recovery_is_written_only_inside_the_return_of_its_payment`
   add (a) a VALUE_CORRECTION row with valid return evidence and an obligation id, expecting
   constraint `refund_recovery_obligation_shape`; (b) inside a confirmed return of another Payment
   (owner transaction), a `refund-recovery:` charge and a RECOVERED_BY_CHARGE row for this Refund,
   expecting 23514.
3. Security note: assert in the least-privilege test that each new function's `proacl` has only
   the owner entry.
4. Traceability entries for the two new tests; update the T4 entry note (net 200, keys).
5. Static checks (each in its own call), migration-only check, read-only search, T run of the new
   module and the three changed modules, U2, P2 (caffeinate), secret check.
6. Review round 2 (independent compares the changed tests with HEAD again).
7. Docs: docs/004 (DB-REFUND-002 amendment; DB-PAY-009 and DB-DEP-007 as built in 10e-1c), docs/010
   (sub-slice entry with the known limits and choices, updated tests note naming the three changed
   assertions under the new standing rule, round 1 line), the plan (10e-1c as built), this record.
8. Commit, NOW.md line.

Answered in writing (no change): a real second Property for the P0002 case (the fixtures share
one Property; a Property the Deposit is not of proves the check); `btrim` of the reason (the draft
reason is already validated); local paths in run outputs (the owner's own, as in earlier records);
drafts recorded before revision 118 become stale (P5S02) because the source gained `recoveries` —
staff record them again; a correction that writes a recovery on another open Lease or with no Lease
is the same writer as the tested 10e-1a path (slice 12 test item); a recovered Refund whose money
later comes back cannot take a verified return (net 0; a known limit for docs/010).

## Fresh session (2026-10-11): the "Still to do" list

Owner instructions of 2026-10-11 for this session: finish the list; confirm the three charge cases
of the Q-72 and Q-78 answers with a test each; add the recovery charge to the slice 11 read list;
two new run scripts (separate commit); the owner answers to Q-2026-10-11-81.

1. S1 done: `test_each_refusal_of_the_source_state_is_checked` (10e-1a) builds three real sources (a
   Payment Refund of 300 with no Lease, a released Credit Refund of 3,000, a Pet Refund-review Refund
   of 15,000), checks each planned recovery exactly (kind, source, recipient, Lease or none, amount,
   charge form, no closed Settlement, both flags false) and that the check passes.
2. N7 done: `test_a_recovery_is_written_only_inside_the_return_of_its_payment` adds (a) a
   VALUE_CORRECTION with valid return evidence naming a charge: constraint
   `refund_recovery_obligation_shape`; (b) inside the confirmed return of another Payment of the same
   payer (owner transaction): a `refund-recovery:` charge and a RECOVERED_BY_CHARGE row are refused
   (23514, "only inside the return of its Payment"), nothing written.
3. Done: the least-privilege test asserts each new function's only privilege entry is its owner's.
4. Done: traceability entries for `test_a_third_party_payer_who_is_not_a_signed_customer_is_charged_with_no_lease`,
   `test_the_refused_cases_on_real_sources` and the new test below; notes updated (T4 net 200 and
   keys, S1, N7, proacl).
5. The three charge cases, each tested: (a) the correction's own closed Settlement's Lease, the person
   its signed Customer: `EXTRA_CHARGE` (`test_a_settlement_refund_paid_from_a_bounced_payment_is_charged_back_as_an_extra_charge`,
   `test_a_kept_deposit_refunded_to_the_agreed_signer_is_charged_to_that_signer`); (b) an open Lease,
   the person its signed Customer: an ordinary Miscellaneous one-time charge on the Lease
   (`test_a_pet_refund_on_a_signed_lease_is_charged_on_the_lease_when_its_payment_bounces`,
   `test_a_recovered_credit_refund_shows_in_the_credit_history`, and new in this session for a second
   Signer, owner answer C: `test_a_pet_refund_paid_to_an_agreed_signer_is_charged_to_that_signer_on_the_open_lease`);
   (c) no Lease, or not a signed Customer: a Miscellaneous one-time charge with no Lease
   (`test_a_payment_refund_with_no_lease_is_charged_with_no_lease`,
   `test_a_third_party_payer_who_is_not_a_signed_customer_is_charged_with_no_lease`).
6. Slice 11 read list: plan, 11c (the recovery charge on the Refund read, the action context and
   the screens).

Static checks, each in its own call: format check (1 correction: an unformatted constant from the
previous session), lint (1 correction: import order in two modules and an unused import from the
previous session), mypy clean. Migration-only check (`scripts/migration-check.sh`, new): 117
upgrades, head `20261122_118`. Read-only search of every backend test for the patched and new
functions, the table and the revisions: the modules found are all in T4 or P2.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| T4 | PostgreSQL targeted (`scripts/database-targeted-test.sh`): new module, 10e-1a, 10e-1b, 10b modules | 39 passed, 1 warning | round-1 fixes and the still-to-do tests | `...-targeted-test-run-4.txt` |
| U2 | backend unit, full (caffeinate) | 3744 passed, 1887 skipped, 1 warning | round-1 fixes changed tests | `...-unit-test-run-2.txt` |
| P2 | PostgreSQL full (`scripts/database-test.sh`, caffeinate) | 2051 passed, 2 warnings (known) | round-1 fixes changed the migration and tests (run rule) | `...-full-test-run-2.txt` |

Secret check of the three outputs: no database URL, no `password=`, no 64-character hex string.

## Review round 2 (2026-10-11; fresh read-only subagents, independent and security; during P2)

Independent: 0 blockers, 0 should-fix, 5 notes. It compared each of the three changed committed
tests with HEAD bb97083: only the ended refusal's assertions and docstrings changed, names kept,
nothing else weaker; every round-1 fix is present; each charge case has a test; no new test
depends on the real clock.
- N1 (the three synthetic rows were removed from the committed loop rather than changed; for the
  same inputs the new result is "has no planned recovery", asserted in the new module): named in
  the docs/010 tests note and the report; not changed after P2.
- N2 (round-1 N5 and N8 have no behaviour test): slice 12 items in docs/010.
- N3 (a `LEASE` or `NO_LEASE` recovery linked to a correction is untested): slice 12 item.
- N4 (BR-PAY-042 is not mapped in the new traceability entries): slice 12 item, so that no file a
  unit test reads changes after U2.
- N5 (docs, plan and record not yet updated): done in this step.

Security: scope A (migration, tests) 0 blockers, 0 should-fix, 4 notes; scope B (the two new
scripts) 0 blockers, 0 should-fix, 4 notes. Confirmed: no grants on the new functions (now
tested), no Staff path to a recovery row or charge, the public one-time charge recorder cannot
forge a `refund-recovery:` reference, a Reservation outcome Refund is also refused by the history
trigger, a recovery cannot be reversed, the amount is exact under the lock, a changed source cannot
be written, no injection, run outputs clean.
- A-N1 (the recovery check accepts the return of any Payment with an unreversed receipt on the
  Deposit; only the plan check refuses a Deposit two Payments funded; the charge's audit
  correlation is not bound to the return): slice 12 hardening.
- A-N2 (the 55000 refusal checks the charge Lease's Settlement, the insert check the Refund's own
  Settlement; a draft passing the first could fail at confirm with 23514): answered: a Refund that
  a closed Settlement or its correction paid makes the Payment relied on by that Settlement, so the
  `PAYMENT_RETURN` draft and another Settlement's correction already refuse it; nothing wrong can be
  written; slice 12 hardening (report the Refund's own Settlement in the plan).
- A-N3 (the negative tests prove three conditions of the recovery check; the others fail with the
  same message): slice 12 test item (change one condition at a time in a confirmed-return context).
- A-N4 (a net that goes A, 0, A between the pre-lock read and the digest could take a Lease key lock
  after row locks: a deadlock risk, reported as a conflict, no integrity risk): slice 12 hardening.
- Scope B notes (trap exit codes, a wider URL pattern and `password=` redaction, the docker compose
  stderr not redacted, `PYTEST_ADDOPTS` and `PYTEST_PLUGINS` passed through): handled in the scripts
  commit.

Round 2 has no blocker and no should-fix, so no round 3 is needed.

Changed committed tests (standing rule of 2026-10-11, owner answer (a) to Q-2026-10-11-79), names
kept: `test_refusals_stale_drafts_withdrawal_and_reads` and
`test_each_refusal_of_the_source_state_is_checked` (10e-1a),
`test_refusals_stale_drafts_and_a_deposit_that_would_still_hold_money` (10e-1b).

Owner answers recorded: Q-2026-10-11-81 (docs/010, questions, plan: 10e-4 after 10e-3; Reservation
outcome recovery as possible later work). New question: Q-2026-10-11-82 (blocks 10e-4 only).
