# V1-056 sub-slice 10e-1b — RETURNED_PAYMENT correction: review record

Sub-slice: 10e-1b (migration `20261121_117`). Base commit: c3379bf. Not committed (commit hash in
ops/NOW.md once committed).

Rule IDs: BR-SETTLE-013, BR-SETTLE-016, BR-PAY-042, BR-CREDIT-014, BR-DEP-023, BR-AUTH-010;
DB-PAY-009, DB-SETTLE-003, DB-SETTLE-005, DB-DEP-006; owner answers 1 and 5 to Q-2026-10-06-36,
answers 2, 3 and 5 to Q-2026-10-06-37, answers (a) to Q-2026-10-10-72 points 2 and 3 and (a) to
Q-2026-10-10-77. Design: ops/V1_056_PLAN.md (10e-1b entry and "10e-1b pre-code design").

## Owner answers given in this session (2026-10-10)

- Q-2026-10-10-72 points 2 and 3 (a), the point 1 detail confirmed; Q-2026-10-10-75 point 1 (A),
  point 2 (b); new Q-2026-10-10-76 (blocks 10c-2b-5 only). Recorded and committed as c3379bf.
- Standing instruction: while one sub-slice waits for an owner answer, the next sub-slice that
  does not depend on it may be built without asking.
- Permission allow list for `.claude/settings.local.json` (never committed; ignored through
  `.git/info/exclude`).
- Q-2026-10-10-77 (review round 1 SF-3): (a), keep the amount check (below).

## Built

- Migration `20261121_117`: recorder `app.record_settlement_returned_payment_draft` and confirm
  `app.confirm_settlement_returned_payment` (EXECUTE to `prm_financial` only); internal
  `app.settlement_returned_payment_input`, `_source`, `app.assert_settlement_returned_payment_allowed`,
  `app.settlement_returned_payment_result` and the write helper
  `app.post_settlement_returned_payment` (no role). Exact-text patches: `app.validate_payment_return`
  (relaxing: a `RETURNED_PAYMENT` correction draft with its own correction) and
  `app.lock_settlement_correction_plan` (a `RETURNED_PAYMENT` branch; the Charge, Invoice and
  Deposit passes also take what that branch adds outside the Lease).
- Service: `RecordReturnedPaymentCorrectionCommand`, `SettlementCorrectionService.record_returned_payment`
  and `confirm_returned_payment`.
- Tests: new module `test_settlement_returned_payment_migration.py` (last in
  `scripts/database-test.sh`); three unit tests in `test_settlement_correction.py`; 27
  head-revision assertions in 15 modules move to `20261121_117`; traceability entries.
- Docs: docs/004 (DB-PAY-009 as built in 10e-1b), docs/010 (sub-slice entry, updated tests, owner
  answers, round-1 line), the plan (10e-1b pre-code design, slice 12 items).

## Read-only search of every backend test

- 27 head-revision assertions in 15 modules: only the expected revision changes; the 10e-1a module
  keeps its own revision in its forward-only test.
- The tests that read the correction lock function's source count its single Payment pass, its
  single Credit pass and its intervals; the patch keeps all three. No other test reads
  `app.validate_payment_return` beyond its privileges; every forward-only test upgrades only to
  its own revision.

## Runs

Static checks each in its own call (`ruff check src tests`, `ruff format --check src tests`,
`mypy`). Migration-only check (throwaway copy of `scripts/database-test.sh` running
`alembic upgrade head`, in the session scratchpad) before T1 and again before T2: 116 upgrades,
head `20261121_117`.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| T1 | PostgreSQL, targeted: the new module | 7 passed | first run | `V1-056-slice-10e-1b-targeted-test-run.txt` |
| U1 | backend unit, full (under `caffeinate -dims`) | 3743 passed, 1870 skipped, 1 warning (Starlette) | first unit run | `V1-056-slice-10e-1b-unit-test-run.txt` |
| P1 | PostgreSQL, full (under `caffeinate -dims`) | 2033 passed, 2 warnings (Starlette; the known Pydantic alias warning) | first full run | `V1-056-slice-10e-1b-full-test-run.txt` |

Check causes before T1 (each correction 1 of 2): lint cause L (four string lines over 100
characters in the new test module, split); format cause F (two changed test files, `ruff format`
on those two files only).

## Review round 1 (2026-10-10; fresh read-only subagents, independent and security; during P1)

Security: 0 blockers, 0 should-fix, 5 notes. Grants, Staff-cannot-confirm, the relaxed
`payment_returns` check, the linked passage through the 8e-2, remainder, receipt-closure and
Deposit-application-reversal checks, the scope of the relaxed slice 7 and 8g refusals, no dynamic
SQL, no leaks, isolation and draft-identity tricks were traced and found sound.

- Security N1 (the 10e-1a note: the wrong-Unit pass hardening must be revisited before a second
  writer of `payment_returns`): revisited; no wider exposure, because the helper reverses only the
  returned Payment's records and the confirm sets its constraints immediate; what remains needs a
  hand-built `prm_financial` transaction. Optional hardening is a slice 12 item.
- Security N2 (the helper runs no refusal itself): answered: it is internal with no grant and its
  only caller runs the source and refusal check under the same locks; docs/010 choice (2) and the
  plan now say every caller must do so; an in-helper check is a slice 12 item.
- Security N3 (the lock function reads the targets before its Payment pass): answered: a change in
  between changes the confirm's source digest, so the draft is stale (fails closed); the comment
  now says so.
- Security N4 (= independent N2, the forfeiture reversal dated before the correction): text fixed
  in docs/004, docs/010 and the plan (as in 10d).
- Security N5 (the database trusts the actor and authorization string): the existing trust
  boundary of every confirm; the API path checks the capability first.

Independent: 0 blockers, 3 should-fix, 7 notes. The owner points, history, cents, capabilities,
grants, both exact-text patches (rebuilt offline: each replacement matches once), the reversal
guards, lock order, chronology and stale/replay/reused-id handling were traced and found sound.

- SF-1 (wrong message when only another Settlement relied on the Payment): fixed. The check first
  requires a record this Settlement relied on; if another Settlement did, the message says to use
  the correction of the Final Settlement that did; the known-limit message comes only when both
  did. Tested (a Payment only the first Settlement relied on, recorded under the second).
- SF-2 (two refusals untested): fixed. On the real sources, a forfeiture with another governing
  Lease and a Deposit application of another Settlement are each refused with 55000 and their
  message; the unchanged sources pass.
- SF-3 (the owner text's example "a returned Pet Refund-review Refund" does not happen; the code
  checks the amount): owner answer (a) to Q-2026-10-10-77: keep the amount check, correct the
  example in the docs, and test a fully returned Refund on a funded Deposit. Test added: the
  Settlement's Pet Deposit Refund (5,400) brought back whole by a return-only correction, then the
  Pet Deposit's Payment returned; the Pet Deposit ends at 0.
- N1 (the confirm's forfeiture lock pass did not leave out reversed receipts): fixed.
- N2: see security N4.
- N3 (refusal lists and rule IDs incomplete in the docstring, docs/004 and docs/010): fixed.
- N4 (10e-2 cannot reuse the helper as claimed): text fixed; 10e-2 needs the helper split first.
- N5: see security N1.
- N6 (test gaps): tests added for a target outside the Lease (a moved allocation on another, open
  Lease, locked, reversed and linked), a service identity (P4506) and the Payment reversal dated
  last; a correction's own Credit application of the Payment's Credit is a slice 12 item.
- N7 (`OR ... = ANY(...)` in the lock passes may stop index use): slice 12 item (the rows locked
  are unchanged).

## Fixes after round 1

Migration (refusal order and message, the forfeiture lock filter, docstring, lock comment), the new
test module (three new tests, SF-2 checks, P4506, Payment reversal last), traceability (two new
entries, four notes updated), docs/004, docs/010 (Q-77 answer, round-1 line, corrected refusal
list and choice (2)), the plan (pre-code design text, slice 12 items) and the questions file
(Q-2026-10-10-77). Static checks each in its own call: lint, format and type check clean.
Migration-only check before T2: 116 upgrades, head `20261121_117`. Read-only search: the changed
comment adds none of the strings the lock-function source tests count; no other test reads the
changed refusal messages.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| T2 | PostgreSQL, targeted: the new module | 9 passed | round-1 fixes | `V1-056-slice-10e-1b-targeted-test-run-2.txt` |
| U2 | backend unit, full (under `caffeinate -dims`) | 3743 passed, 1872 skipped, 1 warning (Starlette) | round-1 fixes changed tests and traceability | `V1-056-slice-10e-1b-unit-test-run-2.txt` |
| P2 | PostgreSQL, full (under `caffeinate -dims`) | 2035 passed, 2 warnings (Starlette; the known Pydantic alias warning) | round-1 fixes changed the migration and tests (owner run rule) | `V1-056-slice-10e-1b-full-test-run-2.txt` |

Secret check (owner run rule) of T1, U1, P1, T2, U2 and P2: no database URL with a password, no
`password=`, no 64-character hex string.

## Review round 2 (2026-10-10; fresh read-only subagents, independent and security; during P2)

Independent: 0 blockers, 0 should-fix, 7 notes. Every round-1 fix was checked against the code
(SF-1 refusal order and three messages tested; SF-2 on edited real sources, the only practical
way because both refusals are extra guards today; SF-3 test; N1 filter); both exact-text patches
were rebuilt offline (each replacement matches once) and the lock-function patch adds no rows for
other variants, whose recorders keep their ids on the Lease.

- N1 (the plan's pre-code refusal list kept the old order): text fixed.
- N2 (the "only a received Payment" refusal is missing from docs/004 and docs/010 and untested here):
  docs fixed; the migration docstring is not changed, so that no migration file changes after P2
  (recorded here); the test is a slice 12 item.
- N3 (no test proves the new lock branch takes its locks; the open-Lease test docstring says
  "locks"): slice 12 item (a hold-and-probe test); the confirm stays correct without the lock
  (the reversal checks lock their targets, the digest fails closed); the test file is not changed
  after P2.
- N4 (docs/004 DB-DEP-006, DB-DEP-007 and DB-DEP-008 did not name 10e-1b as a writer): fixed.
- N5 (the receipt reversal's audit event keeps the statement time, before its row): stated in
  docs/004 (DB-PAY-009 and DB-DEP-007): read it through the link, not by time.
- N6 (BR-CREDIT-014 missing from the traceability entries): slice 12 item, so that no file a unit
  test reads changes after U2.
- N7 (the forward-only test checks which functions changed, not how): slice 12 item.

Security: 0 blockers, 0 should-fix, 4 notes. All round-1 answers hold and the round-1 fixes add no
weakness (the refusal order changes only the message; the lock filter matches the source and the
helper). Grants, Staff-cannot-confirm, the linked passage through every guard, the scope of the
relaxed refusals, isolation, injection, draft tricks and all seven run outputs (no secrets) were
traced and found sound.

- N1 (the direct receipt reversal skips checks inside the reversal function; each is covered today
  by the trigger, the Payment-Deposit Property check and the order of the steps; risk of future
  drift): slice 12 item (a drift test, or the checks moved into the trigger).
- N2 (the forfeiture and receipt reversals name the approver under `deposits.correct`): the
  existing slice 12 approver-naming item.
- N3 (`SET CONSTRAINTS ALL IMMEDIATE` stays for the caller's transaction): stricter, as every
  writer; no action.
- N4 (round-1 N1 and N2 re-checked: no exposure; the optional hardening applies before 10e-1c
  reuses the helper): already on the slice 12 list; the 10e-1c pre-code design takes it up.

Round 2 has no blocker and no should-fix, so 10e-1b is committed (takeover rules section 4; no
round 3 needed). Only documents changed after P2 (docs/004, docs/010, the plan and this record).
