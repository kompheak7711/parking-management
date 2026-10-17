# V1-056 sub-slice 10e-2b-4b-2a — a forgiven recovery charge is not restored while a forfeiture relies on it — review record

Sub-slice: 10e-2b-4b-2a (owner answer (a) to Q-2026-10-17-126 point 1; the 10e-2b-4b-2 split).
Migration `20261227_153` (three new internal functions, four deferred constraint triggers on the
Invoice tables, one AFTER INSERT trigger on `app.deposit_dispositions`). Base commit: c42a6c3.
Built on 2026-10-17. Not pushed.

Rule IDs: BR-SETTLE-013, BR-DEP-022, DL-032, DL-053, BR-INV-044; DB-DEP-004, DB-REFUND-002.
Design: ops/V1_056_PLAN.md, "10e-2b-4b-2 split and the 10e-2b-4b-2a pre-code design" and
"10e-2b-4b-2a as built".

## Built

- Migration `20261227_153_pet_payback_restoration_refusal.py`: `app.refuse_recovery_charge_restoration`
  (the refusal, 55000), `app.validate_recovery_charge_restoration` (the trigger function of the
  four deferred constraint triggers: a DEBIT Adjustment, the reversal of a credit Adjustment, an
  Invoice inserted as issued or issued later when another Invoice of the obligation exists) and
  `app.validate_forfeiture_recovery_standing` (review round 1: the AFTER INSERT trigger on the
  forfeiture table, 40001), all with no grant.
- Tests: new module `test_pet_payback_restoration_refusal_migration.py` (nine tests, last in
  `scripts/database-test.sh`).
- Committed tests changed: the 27 head-revision assertions in 15 modules (revision strings only; a
  script checked each file's count). No other committed expectation changed.
- Traceability: nine entries appended (3,191 to 3,199); no earlier entry changed.
- Docs: docs/004 (DB-DEP-004 pointer, DB-DEP-005 bullet), docs/010, plan (pre-code design,
  as-built line, slice 12 known limit of Q-126 marked ended), questions (owner answers).

Read-only search for affected tests (before T1 and before each full run): every committed
database test that issues, DEBITs or reverses an Adjustment of a recovery charge after a
forfeiture of its Pet Deposit (only `test_pet_payback_recovery_standing_migration.py` restores a
recovery charge, always with no forfeiture of the Pet Deposit), every test that lists triggers
of the changed tables at head (`test_final_settlement_closed_refusal_migration.py` reads only
BEFORE triggers), and every test that forfeits a Pet Deposit after forgiving a recovery charge
(the forgiveness is always dated before the forfeiture): none expected to change.

## Runs

| Run | Result |
|---|---|
| D1 | catalog dump for the pre-code design (read only; two `REDACTED` markers in `app.adjust_invoice` amount limits, not copied) |
| FF1/FC1/L1/Y1 | passed (formatter first; long-line search first, none in the test module) |
| M1 | passed (`20261227_153` head) |
| T1 | 49 passed (the new module, the 10e-2b-4b-1 module, the 10f-1 and 10f-2 modules, the DEBIT line block module, the Payment return recovery module) |
| U1 | 3847 passed (includes `test_traceability.py`) |
| M2 | passed |
| P1 | 2272 passed (the known Starlette deprecation and Pydantic alias warnings) |
| FF2/FC2 | passed (after the round 1 fixes; long-line search first: one line rewrapped before the lint) |
| L2 | FAILED: `F821 Undefined name url` in the new test module (the split helper). Lint correction 1 of 2 (cause: undefined name) |
| FF3/FC3/L3/Y2 | passed |
| M3 | passed (after the round 1 migration change) |
| T2 | FAILED: 63 passed, 1 failed: `test_after_closure_a_charge_reduction_is_not_reversed_while_its_forfeiture_is_active` (`The remaining Pet Deposit needs the Customer's choice or the staff reason`). Test correction 1 of 2 (cause A: the new `FORFEITURE_REVERSAL` step of a Pet Deposit needs `pet_remainder`) |
| FF4/FC4/L4/Y3 | passed |
| T2 modules | the new module, the 10e-2b-4b-1 module, `test_settlement_deposit_receipt_payback_forfeiture_migration.py`, `test_lease_deposit_forfeiture_migration.py`, `test_settlement_forfeiture_reversal_migration.py`, the 10f-1 and 10f-2 modules |
| T3 | 8 passed (the new module) |
| U2 | 3847 passed (includes `test_traceability.py`) |
| M4 | passed |
| P2 | 2275 passed (the known Starlette deprecation and Pydantic alias warnings) |
| FF5/FC5/L5/Y4 | passed (after the round 2 fixes; long-line search first, none) |
| M5 | passed (after the round 2 migration change) |
| T4 | FAILED: 48 passed, 1 failed: `test_a_forfeiture_timed_before_a_charge_issued_ahead_of_the_clock_is_refused` (`invoices_issuance_shape`: the hand-built retime moved `issued_at` past `updated_at`). Test correction 2 of 2 (cause A: test set-up); fixed by moving `updated_at` with it. Modules: the new module, the 10e-2b-4b-1 module, the 10e-2d pay-back forfeiture module, the slice 6 forfeiture module, the 10d module |
| FF6/FC6/L6/Y5 | passed (the first edit attempt of the fix did not apply; these checks ran on the unchanged file) |
| FF7/FC7/L7/Y6 | passed (after the fix) |
| T5 | 9 passed (the new module) |
| U3 | 3847 passed (includes `test_traceability.py`; before round 3) |
| M6 | passed |
| P3 | 2276 passed (the known Starlette deprecation and Pydantic alias warnings): the full run after the last code and test change, before the round 3 verdicts |
| UT1 | `test_traceability.py` 28 passed (after the round 3 text fixes in the plan and this record; no code, migration or test file changed after P3) |

Full outputs of every targeted and full run, each attempt in its own file, are in
`~/Development/prm-run-logs/v1-056-10e-2b-4b-2a-*.txt` (format, lint and type checks are short and
not saved).

## Review round 3 (fresh read-only subagents, during P3; same instructions)

Independent: clean (no blocker, no should-fix; four notes). Security: clean (no blocker, no
should-fix; three notes). Both confirm every round 2 fix: the forfeiture-side first-issue branch
refuses only a charge dated ahead of the clock or committed while the forfeiture waited (a
recovery insert takes the Deposit lock and is committed with its charge); the receipt correction's
forfeiture is always dated after the charges it issues (each later writer takes the earlier time
plus 1 microsecond), so its own writes never trip it; the Final Settlement confirm writes no
forfeiture; the first-issue filter is sound (no committed forfeiture that read a charge is
dropped); no committed test got weaker (27 revision strings only); traceability only appended
(3,190 to 3,199); least privilege; the denial of service is bounded (40001 maps to a conflict, no
retry loop).

Taken (text only, no code, migration or test file changed after P3): the plan's "What exists"
bullet no longer lists the Final Settlement confirm among the forfeiture writers (independent
N2). Notes kept: a stray line break in the test module docstring (independent N3, cosmetic; not
changed after P3); forfeitures recorded before migration 153 were never checked by the
forfeiture-side trigger, so the restoration check trusts their times (independent N4; nothing is
live); an optional assertion that the round 2 test's standing is 0 at both times (security N2);
the round 2 notes N1 and N3 stand (security N3).

## Review round 2 (fresh read-only subagents, during P2; same instructions)

Independent: 0 blockers, 1 should-fix (text), 7 notes; both round 1 design changes confirmed
needed and safe (the forfeiture-side trigger: a VOID or credit is not a Deposit balance event, so
the draft's P5801 staleness misses it, and it refuses a committed path only in a race or while an
instant is dated ahead; the structural rule and the first-issue filter, which considers strictly
more forfeitures than the recovery-time filter). Security: 0 blockers, 1 should-fix (a fail-closed
check that adds a refusal), 7 notes.

Fixed under the round-3 rule (a fail-closed check that adds a refusal, a test and text):
- Security S1 (fail-closed check): a recovery charge can be issued at a time chained ahead of the
  clock (up to about 5 seconds); a forfeiture timed before that issue reads the charge in its
  count, but the restoration check's first-issue filter dropped it, and the forfeiture-side
  trigger compared 0 with 0. The forfeiture-side trigger now also refuses (40001) when a recovery
  charge of that Pet Deposit was first issued after the forfeiture's time (a recovery insert takes
  the Deposit lock, so a recovery visible to the trigger was visible to the count read; the
  receipt correction times its forfeiture after the recovery rows it writes). Its message became
  "A recovery charge of this Pet Deposit changed after this forfeiture's time; record it again".
  New hand-built, rolled-back test with the reviewer's set-up (the forgiven charge's issue moved
  30 seconds ahead; the one-call forfeiture is refused). The independent reviewer's N1 is the same
  case (it proposed comparing at the first issue, which misses a VOID dated before an ahead-dated
  issue).
- Security N2 and independent N2 (test): the REPEATABLE READ tests pin the guard's own 40001
  message, so they cannot pass on the forfeiture's own 40001.
- Independent S1 (text): stale pre-code text in the plan marked as replaced (the rule, the lock
  and the built bullets), the slice 12 line "its later restoration is refused while a forfeiture
  that relied on the lower count is active", the test module docstring ("at or after the charge's
  first issue"), and a new slice 12 known limit: after closure two active forfeitures that both
  relied on the lower count cannot be reversed (owner answer 2 to Q-2026-10-10-71), so that
  charge's restoration stays refused (also for the owner report).
- Independent N7: T2's modules named in the runs table.
- Notes kept: the forfeiture-side 40001 is bounded (a forgiveness committed within the
  forfeiture's wait, or dated ahead by `app.credit_excess_instant` or
  `app.adjustment_reversal_instant`; each repeat needs an approved restoration; slice 11 words
  40001 as "try again") (security N1); rows dated ahead can make a restoration refused until a
  forfeiture is reversed (fail closed) (security N3); a VOID without a void event refuses any
  re-bill (fail closed) (security N4); the `v_first_issued` NULL branch is unreachable (security
  N5); the insert-as-issued trigger is defensive only (both N6/N4); `occurred_at>=now()` is checked
  by hand only (security N7); the payout-undo branch has no refusal test (independent N3,
  optional; set-up below); a new unlinked one-time charge for the same money is not a restoration
  (independent N5, slice 11 wording); the round 1 notes stand (independent N6).

### Round 2 test set-ups

- Security S1: `recovered_case(url, 15_000)`, `void`, `terminate`; on one owner connection the
  recovery Invoice's `issued_at` (and `updated_at`, for `invoices_issuance_shape`) moved 30
  seconds ahead with its triggers disabled and enabled again; the one-call forfeiture of 15,000 is
  refused (40001); rolled back.
- Independent N3 (not built, optional): `bc_case`; `reduce_charge(case, case["settled_line"],
  3_000)` (count 5,000 to 2,000); the own-receipt correction of test (4) with its DL-032 step on a
  line that still owes; the 10f-2 reversal of that reduction refused (55000, draft PENDING); the
  `FORFEITURE_REVERSAL` (`PET_REST`, `pet_remainder=STAFF`); the reversal confirms and
  `settled_line` owes 3,000 again.

## Review round 1 (fresh read-only subagents, during P1; told to write no files at all, scratch files included, and to run no test, script or database command)

Independent: 0 blockers, 5 should-fix, 6 notes. Security: 0 blockers, 2 should-fix, 6 notes.
Both confirm the reading of "relied on the lower count" (needed because the count keeps no
history; narrower than option (a)'s literal wording in that a restoration only back to the level
a forfeiture saw passes, which is safe), every restoration path (the only DEBIT writer, the only
two reversal writers, every `issued_at` writer, no un-VOID path, issued lines immutable),
least privilege, forward-only, the 27 revision strings and the traceability append.

- Independent S1 (fixed, design change the reviewer proposed): a forfeiture is timed by its
  statement's start (`statement_timestamp()`), before it waits for the Deposit lock and reads the
  count, and a forgiveness takes no Deposit lock; a forgiveness committed while a forfeiture waited
  is read by its count but not shown by its time, so a later restoration passed. New AFTER INSERT
  trigger `deposit_dispositions_recovery_standing`: a Pet Deposit forfeiture is refused (40001,
  "record it again") when a recovery charge of that Deposit stands lower now than at the
  forfeiture's time. The security reviewer's N1 is the same case (the reviewer judged it reachable
  only at database level).
- Independent S2 and security S1 (fixed, tests): the lock had no test. New tests: forfeiture first
  and restoration first at READ COMMITTED (one side written and not committed, the other waiting
  on the Pet Deposit lock), and both directions at REPEATABLE READ (40001 on the Deposit guard).
  The independent reviewer's order 1 (the check at commit) does not apply: every restoring writer
  runs `SET CONSTRAINTS ALL IMMEDIATE` (both reviewers, N3 and S5), so the check runs inside it.
- Independent S3 (fixed, test): the "not before the charge existed" filter is checked by hand in
  test (3) (a forfeiture retimed to just before the charge's first issue does not block; standing
  there is 0).
- Independent S4 and security S2 (fixed, test): test (4) also reverses the 1,500 forfeiture with a
  `FORFEITURE_REVERSAL` correction (its 1,500 pays the Security Refund's open recovery charge,
  DL-032), and then the same 10f-2 draft confirms (2,000 owed again); the draft stays PENDING after
  the refusal.
- Independent S5 (fixed, text): the plan's function signature, the as-built line, the slice 12
  known limit marked ended, "inside the writer" instead of "at commit", the docs/004 location.
  Not taken: pointers under DB-INV-001, DB-INV-003 and DB-INV-010 (optional; the DB-DEP-005 bullet
  names the triggers).
- Security N2 and N4 (fixed, hardening): the time rule for a recovery's own first billing
  (`p_at<=recovered_at`) became structural (a DEBIT or a credit's reversal is always a restoration;
  an issue only when another Invoice of the obligation exists), and the forfeiture filter compares
  with the charge's first issue (a recovery can be dated up to about 5 seconds ahead); `p_at` and
  its fail-open NULL branch are gone.
- Notes kept: over-broad refusals, fail closed (a forfeiture made during a forgiveness that did
  not need the lower count; one timed at or after the restoring transaction's start; after
  closure two relying forfeitures cannot both be reversed, Q-2026-10-10-71 answer 2) (independent
  N1); lock order Invoice then Deposit against Deposit then Invoice can end in a deadlock (40P01,
  nothing written; the invoice service shows it as unavailable) (independent N2, security N5); the
  services show the refusal as a generic invalid command or conflict, so staff do not read
  "reverse the forfeiture first" (slice 11 words it) (independent N3, security N5); a recovery
  charge with no Lease has no Pet Deposit test (structural coverage) (independent N5, security N6);
  clock steps (independent N6); the security reviewer's extra boundary tests (N6), optional.
- Notes taken: DL-032 and DL-053 added to the new traceability entries (independent N4).

### Round 1 test set-ups (written in full, run rule of 2026-10-13)

- Independent S1: `recovered_case(url, 15_000)`, the termination; connection X holds the Pet
  Deposit row (`FOR UPDATE`); the owner's one-call forfeiture of 15,000 (with its termination
  context) waits; the VOID of the recovery Invoice commits; X rolls back; the forfeiture's count is
  0 but its time is before the VOID.
- Security S1.1: VOID, termination, the charge billed again on a DRAFT; an uncommitted 15,000
  forfeiture; the issue waits on the Deposit lock; after the commit the issue is refused (55000).
- Security S1.2: after the forfeiture's reversal, an uncommitted issue; the 15,000 one-call
  forfeiture waits; after the commit it is refused (23514, returned pay-back money).
- Security S1.3: a REPEATABLE READ snapshot, then the other side commits; the issue (or the
  forfeiture) in the old snapshot fails on the Deposit guard (40001).
- Independent S3: test (3)'s forfeiture retimed to the charge's first `issued_at` less 1
  microsecond (standing 0 there): the refusal function passes.
- Independent S4 / security S2: test (4) then a `FORFEITURE_REVERSAL` correction of the 1,500 with
  one step (`PET_REST`, the Pet Deposit, the Security Refund's recovery line, 1,500) and the staff
  remainder choice, then the 10f-2 draft confirms.

Status: committed (see git log). Not pushed.
