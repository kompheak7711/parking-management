# V1-056 sub-slice 10e-2b-4e-1 — a returned Payment of a shared Deposit charges back only the shortfall — review record

Sub-slice: 10e-2b-4e-1 (owner answer (a) to Q-2026-10-18-127, the return before closure; option
(d) stays until 10e-2b-4e-2, review round 2). Migration
`20261231_157` (four new internal functions, exact-text patches). Base commit: 179d6ee. Built on
2026-10-18 in a fresh session. Not pushed. Sub-slice 10e-2b-4e-2 (the two corrections after
closure) waits for the owner's answer to Q-2026-10-18-134 point 1.

## Built

- Migration `20261231_157_payment_return_shared_deposit_shortfall.py`: new internal
  `app.payment_return_shared_deposit_recoveries`, `app.payment_return_draft_source`,
  `app.payment_return_shortfall_recovery_amount`, `app.payment_return_shared_receipt_reversal_allowed`
  (no grant); patches of `app.record_payment_return_draft`, `app.assert_payment_return_recoveries_allowed`,
  `app.assert_payment_return_recoveries_planned`, `app.write_payment_return_recoveries`,
  `app.validate_general_refund_correction`, `app.validate_deposit_receipt_reversal` and
  `app.confirm_payment_return` (the receipt writer patch of rounds 0 and 1 was dropped in round 2).
- Tests: new module `test_payment_return_shared_deposit_migration.py` (eleven tests); committed
  tests changed as docs/010 lists (one rename in the 4b module, case (2) of
  `test_the_refused_cases_on_real_sources`); 27 head-revision strings.
- Docs: docs/004 (DB-REFUND-002, DB-DEP-002, DB-DEP-007 notes), docs/010, plan (pre-code design,
  as-built line, the Q-127 and Q-133 known-limit lines, slice 12 items), Q-2026-10-18-134; the
  owner's answers to Q-2026-10-18-133 and the 4d report recorded in docs/010 and the questions
  file; traceability appended.

## Runs

| Run | Result |
|---|---|
| D1 | catalog dump (the return functions, the receipt reversal check, the refund correction check; no `REDACTED` markers) |
| D2 | catalog dump (`app.record_payment_return_draft`, `app.assert_settlement_returned_payment_allowed`; no `REDACTED` markers) |
| FF1/FC1/L1/Y1 | passed (long-line search first: one line fixed; formatter changed one file) |
| M1 | passed |
| T1 | did not start: the script was run from `backend/` (it needs the repository root); cause A (run start), correction 1 of 2 |
| T2 | 2 failed, 98 passed: `test_payment_return_recovery_migration.py::test_the_refused_cases_on_real_sources` (a "no draft" count of the now accepted case 2, cause C: committed test update incomplete, 1 of 2) and `test_deposit_receipt_record_migration.py::test_after_closure_a_deposit_funded_by_two_payments_keeps_a_bounced_payment_received` (the correction got "no planned recovery" instead of "would still hold money": the `RETURNED_PAYMENT` source extends `app.payment_return_source`; cause B: design, 1 of 2; design change below) |
| FF2/FC2/L2/Y2 | passed (long-line search first: one line fixed) |
| M2 | passed |
| T3 | 100 passed (the passing run after T1 and T2) |
| U1 | 3866 passed |
| M3 | passed |
| P1 | 2321 passed |
| FF3/FC3 | passed (after the round 1 fixes; formatter no change; long-line search first: one line fixed) |
| L3 | failed: RUF059, an unpacked variable never used in the new test module (cause D: lint, 1 of 2) |
| FF4/FC4/L4/Y3 | passed (the passing checks after L3) |
| M4 | passed |
| T4 | 105 passed |
| U2 | 3866 passed |
| M5 | passed |
| P2 | 2326 passed |
| FF5/FC5/L5/Y4 | passed (after the round 2 fixes; long-line search first: one line fixed; formatter no change) |
| M6 | passed |
| T5 | 104 passed |
| U3 | 3866 passed (before round 3) |
| M7 | passed |
| P3 | 2325 passed (the full run after the last code and test change, before the round 3 verdicts; two more warnings are the known pydantic alias warning of the slice 12 list) |
| FC6/L6/Y5 | after the round 3 text fixes (no code change) |

Full outputs of the targeted, unit and full runs (T1 to T5, U1 to U3, P1 to P3) in
`~/Development/prm-run-logs/v1-056-10e-2b-4e-1-*.txt`. The catalog dumps D1 and D2 went to the
session's scratch folder and the migration checks M1 to M7 were read in the session; neither was
saved there (review round 3 note; neither is a test run).

## Design change during the build (design-change run rule)

Change (2) of the pre-code design patched `app.payment_return_source`. Targeted run T2 showed that
the `RETURNED_PAYMENT` correction's source is `app.payment_return_source(...)||{...}`, so the new
Deposit keys reached the correction and changed a committed after-closure refusal message. The
`PAYMENT_RETURN` recorder and confirm read a new `app.payment_return_draft_source` instead (two
one-line patches), and `app.payment_return_source` stays unchanged. Round 1 independent reviewer:
needed and safe (the only other callers are the recorder and the confirm; the confirm's Lease
lock pass still reads the full recovery list, a superset).

## Review round 1 (fresh read-only subagents, during P1; told to write no files at all, scratch files included, and to run no test, script or database command)

Independent: no blocker, 3 should-fix, 4 notes. Security: no blocker, 1 should-fix (tests), 4
notes. Both: money in cents, append-only, the shortfall math and the newest-first window right,
both table guards reachable only inside a confirmed `PAYMENT_RETURN` of the same transaction, the
corrections and the return reversal unchanged, the rolled-back owner-transaction test sound,
committed test changes exactly the owner-answer cases, traceability appended after entry 1,598.

1. Independent should-fix 1 (fixed): the planned check compared a shared Deposit's shortfall
   before the forfeiture and application refusals, so a wholly forfeited shared Deposit got "no
   planned recovery". Fix: skip the comparison while a forfeiture or application is active.
2. Independent should-fix 2 (fixed): removing (d) reopened the deliberate path for a Deposit whose
   unreturned Refunds went to two people (its return stays refused, Q-134 point 2). Fix: (d) stays
   for that Deposit only.
3. Independent should-fix 3 and security should-fix 1 (fixed, tests): a shortfall that reaches an
   older Refund; the two-recipient refusal and its shortfall-0 variant; a receipt between the
   record and the confirm.
4. Notes taken: a shared Deposit with a Reservation outcome Refund or a closed-Settlement charge
   keeps those refusals with a shortfall of 0 (both reviewers); the hand-built check with
   `shortfall_share` and a Settlement (independent note 5); the dependency of the amount check on
   `app.refund_recovery_allowed` named in a comment (security note 4); docs/004 now says the rule
   holds before closure only and names the order-of-events effect (security note 2, independent
   note 7); the plan's as-built line. Kept: the `SHARED` constant of the 4b module (the new
   two-recipient test imports it).

### Round 1 test set-ups (as the reviewers gave them; built in the new module, except where round 2 changed them as noted)

- Shortfall reaching the older Refund (independent 3a): `shared_case(url, (12_000, 5_000))`, the
  Deposit holds 3,000; A's return: older Refund recovers [2,000], newer [5,000], nets 10,000 and 0,
  the Deposit holds 0, B's receipt stays.
- Two recipients (independent 3b, security 1a): a joint-Lease Pet Deposit; A 20,000 (the seeded
  receipt of `joint_qualified`), the required total raised by 20,000, B 10,000; Refunds 8,000 to
  the Primary Tenant, then 7,000 to the second Signer with the agreement (held 15,000): A's draft
  refused 55000 with the shared-Deposit message, nothing written; a receipt from C refused (the
  kept (d)). Variant: Refunds 3,000 and 2,000 (held 25,000): recorded and confirmed with no
  recovery, the Deposit holds 5,000. (The reviewers' set-up had A 10,000; `joint_qualified` seeds
  20,000, so the amounts follow it.)
- A receipt between record and confirm (security 1b): `shared_case((15_000,))`; A's draft plans
  5,000; the required total raised by 5,000 and C's 5,000 receipt recorded; the confirm is stale
  (P5S02), nothing written; the draft is withdrawn and recorded again, plans no recovery, and its
  confirm leaves the Deposit at 0 with the Refund's net 15,000. Not built as given since round 2
  (option (d) refuses C's receipt while the Refund is out): built instead with a verified 2,000
  return between the record and the confirm (stale, then a 3,000 charge-back on the second draft,
  the Refund's net 10,000, the Deposit at 0).
- Forfeiture order (independent 1): `terminated_pet_lease_case(url, receipts=(5_000, 5_000))`,
  `forfeit_through_draft` of the Pet Deposit (10,000), no closure; A's return draft refused 55000
  with the forfeiture message.

## Review round 2 (fresh read-only subagents, during P2; same instructions)

Independent: no blocker, 2 should-fix, 5 notes. Security: no blocker, 1 should-fix, 3 notes. Both
confirmed every round 1 fix, the design change (`app.payment_return_draft_source`), the shortfall
math, that both table guards are reachable only inside a confirmed `PAYMENT_RETURN` of the same
transaction, that the corrections and the return reversal are unchanged, the committed test diff
(exactly the owner-answer cases plus 27 revision strings) and traceability after entry 1,598.

Should-fix (fixed under the round-3 rule: tests, text, and a kept refusal):
- Independent S1 and security S1: the narrowed option (d) checked recipients only at the receipt,
  so a shared Deposit could still reach unreturned Refunds to two people (a receipt before both
  Refunds, a pending Refund draft confirmed after the receipt, a reversed verified return); and
  without the full (d) a receipt recorded while a Refund is out, followed by a closure and a
  bounce, reaches the `RETURNED_PAYMENT` correction, which refuses a shared Deposit until 4e-2,
  while the owner kept (d) "until (a) is built". Fix: option (d) stays unchanged until 4e-2 (the
  receipt writer is not patched; the two committed 4d (d) tests keep their HEAD form; the round 1
  two-recipient receipt refusal and the deliberate-path test are dropped; the receipt-between test
  became a verified partial return between the record and the confirm); Q-134 point 2 names the
  three ways as a known limit.
- Independent S2: the plan's Q-127 known-limit line updated (what 4e-1 built, the rename).

Notes taken: Q-134 point 1 (b) reworded (same total owed, other records); docs/004 and the plan
say only a draft whose Payment has an active Deposit receipt goes stale; DB-DEP-007 named in the
migration docstring and in two traceability entries. For slice 12 (not taken): the insert check
bounds only the amount, not the recipient or the newest-first order (defence in depth; only the
planner, which no role may call, decides; security N2); the closed-Settlement half of `plain` is
unreachable on this path and its Reservation-outcome half has no test (a Reservation Deposit with
two receipts, cancelled with an outcome Refund; independent N4); one Payment funding a shared and
a sole Deposit has no test (independent N5; two receipts of one Payment in one Deposit cannot
exist, one active receipt per Payment); a race test of the two-recipient receipt refusal is moot
with the full (d) kept (security N3).

Process note: while reworking traceability in round 2 a script re-serialized the whole file
(formatting only, no entry changed); it was rebuilt at once from HEAD with exact-text
replacements and appends, checked to equal the intended entries, before any run or commit, and
`git diff` shows only the intended lines.

## Review round 3 (fresh read-only subagents, during P3; same instructions)

Security: no blocker, no should-fix; 3 notes. Independent: no blocker, 2 should-fix (text and
record only), 6 notes. Both: the round 2 fixes right and complete, the receipt writer not patched
and the 4d module back to HEAD, the migration correct, the committed test diff exactly the two
owner-answer cases plus 27 revision strings, traceability only three changed lines plus appended
entries after entry 1,598.

Should-fix (fixed under the round-3 text rule of 2026-10-16, no round 4; no code, migration,
test or fixture change): stale wording of the dropped receipt-writer change (this record's round
1 set-up heading and the 1b set-up, the plan's split line, the docs/004 order-of-events example);
the log line above (which outputs were saved) and the round 2 slice 12 items, now in the plan's
slice 12 list.

Notes taken (text): the stale "to be confirmed" in docs/010; the plan's "changes no function the
two corrections use" now says "for a shared Deposit" with why; the plan's Q-127 line now says the
dodges no longer block the return and follow rule (a) (security N3); the Q-133 known-limit line
names the owner's answer (a); the record's Docs list names the Q-133 records. For slice 12 (not
taken, plan list): `COALESCE` of the shortfall in the amount check (security N1), the
least-privilege test's roles and definer settings (security N2), a shortfall of exactly 0 and the
"nothing to charge back" tail of the renamed 4b test (independent N3, N4). Not taken: independent
N5 (the migration docstring and docs/010 cite the after-closure rule IDs of the whole 10e-2b-4e
work; the traceability entries cite the IDs each test proves).
