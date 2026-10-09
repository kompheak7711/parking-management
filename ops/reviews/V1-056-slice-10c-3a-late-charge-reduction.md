# V1-056 sub-slice 10c-3a — CHARGE_REDUCTION of an unpaid Late-payment Charge: review record

Sub-slice: 10c-3a (migration `20261115_111`). Base commit: 551df1a. Not committed (commit hash in
ops/NOW.md once committed).

Rule IDs: BR-SETTLE-013, BR-LATE-005, BR-AUTH-010; owner answer to Q-2026-10-07-38
(recommendation (a)). Pre-code design: ops/V1_056_PLAN.md (10c entry, "10c-3 pre-code design"; 10c-3
is split into 3a, an unpaid Charge, and 3b, a paid one).

## Built

- Migration `20261115_111`:
  - New: `app.record_settlement_late_charge_reduction_draft` (recorder, `final_settlements.prepare`)
    and `app.confirm_settlement_late_charge_reduction` (confirm, `financial.approve`), executable
    only by the financial role; internal `app.settlement_late_charge_reduction_input`,
    `app.settlement_late_charge_obligation`, `app.settlement_late_charge_reduction_source_state`,
    `app.settlement_late_charge_reduction_plan`, `app.settlement_late_charge_reduction_result` (no
    role).
  - Patched: `app.confirm_settlement_charge_reduction` (the Invoice-line confirm) refuses a draft
    with a `target_kind`, on the replay path and the main path.
- Service: `RecordLateChargeReductionCorrectionCommand`, `record_late_charge_reduction`,
  `confirm_late_charge_reduction` (stale P5S02).
- Tests: new module `test_settlement_late_charge_reduction_migration.py` (5 tests); 3 unit tests;
  27 head-revision assertions; 8 traceability entries.
- Docs: docs/004 (DB-SETTLE-005), docs/010 (the sub-slice entry, updated tests), the plan (pre-code
  design; 10h test note).

## Read-only search of every backend test

Only the 10c-1a module reads the patched Invoice-line confirm at head, in its check that its
functions use no `interval` or `age(` (still true); its forward-only test upgrades only to its own
revision. No function list at head is pinned. The 27 head-revision assertions move to
`20261115_111`.

## Runs

Static checks each in its own call. Lint failed twice in the new test module: cause H (lines over
100 characters; corrections 1 and 2 of 2, two SQL strings, then a docstring line after the round-1
test edits) and cause J (import order, correction 1 of 2); type check failed once (cause I, a
redundant cast; correction 1 of 2); then all clean. Migration-only check (throwaway copy of
`scripts/database-test.sh`, rebuilt after the new module was listed): 110 upgrades, head
`20261115_111`.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| T1 | PostgreSQL, targeted: the new module and the 10c-1a module (a check before the full run) | 10 passed | first run | `V1-056-slice-10c-3a-targeted-test-run.txt` |
| U1 | backend unit, full (under `caffeinate -dims`) | 3663 passed, 1825 skipped, 1 warning (Starlette) | first unit run | `V1-056-slice-10c-3a-unit-test-run.txt` |
| P1 | PostgreSQL, full (under `caffeinate -dims`) | 1988 passed, 2 warnings (Starlette; a pydantic `alias` warning in the unchanged `test_credit_refund_api_migration.py`, recorded, not changed) | first full run | `V1-056-slice-10c-3a-full-test-run.txt` |

## Review round 1 (2026-10-09; fresh read-only subagents, independent and security)

Independent: 0 blockers, 2 should-fix (tests), 6 notes. Security: 0 blockers, 0 should-fix, 3
notes (two the same as the independent should-fix). No code defect was found.

- Independent SF1, security N2: the replay half of the cross-variant guard had no test. Fixed: the
  same approver's confirmed Charge draft is not found by the Invoice-line confirm, and a confirmed
  Invoice-line draft is not found by the Charge confirm.
- Independent SF2, security N1: the Lease and Charge row locks before the stale and plan checks
  were untested. Fixed: a stale draft waits for the Lease row and for the Charge row another session
  holds (`lock_timeout`, 55P03) instead of being reported stale at once. (Corrected after review
  round 2: the reviewers of round 1 and this record said the locks were the only guard because the
  Charge correction row's validator ignores applications; that is false. Migration `20260905_39`
  made the deferred validator refuse a result below the active applications (23514), and the
  confirm runs it at `SET CONSTRAINTS ALL IMMEDIATE`, so the backstop already exists; the locks give
  a clean stale refusal and a fixed lock order.)
- Independent N1: the one-call writer still checks P4608 before the closed-Settlement refusal; the
  new path checks Deposit applications first, which is what the 8a-1 note asked; written in docs/010.
- Independent N2: the Charge form counts only Deposit applications not reversed, the Invoice-line
  form any; written in docs/010.
- Independent N3: added a no-time-limit source check of the new functions (BR-SETTLE-013).
- Independent N4: the VOID refusal is a backstop (an Invoice is not voided after closure, and the
  Charge correction row refuses a VOID Invoice); written in docs/010.
- Independent N5, security N3: the accepted "until 10h" gap now covers a Late-payment Charge too;
  written in docs/010 and in the plan's 10h entry (its test covers the Charge path).
- Independent N6: P1 was still running when read; it passed (1988).

After the round-1 fixes (test-only changes in the new module, docs, traceability notes; no code
change since P1): static checks clean (see Runs).

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| T2 | PostgreSQL, targeted: the new module (covers every changed test; no function body changed since P1) | 5 passed | round-1 test fixes | `V1-056-slice-10c-3a-targeted-test-run-2.txt` |
| U2 | backend unit, full (under `caffeinate -dims`) | 3663 passed, 1825 skipped, 1 warning (Starlette) | traceability notes changed after U1 (`test_traceability.py` reads them) | `V1-056-slice-10c-3a-unit-test-run-2.txt` |

## Review round 2 (2026-10-09; fresh read-only subagents, independent and security)

Independent: 0 blockers, 0 should-fix, 4 notes. Security: 0 blockers, 0 should-fix, 3 notes. Both
found every round-1 item fixed: the lock test fails without either early lock (P5S02 instead of
55P03), and the replay-path tests fail without either patch tuple. Under the takeover rules the
commit follows; no round 3 is needed.

- Independent N1, security N1: the "validator ignores applications" claim was false (migration
  `20260905_39`); corrected in the plan's 10c-3 design and above. The plan's 10c-3b note now says
  its linked reversals must be written before that validator runs. No code change.
- Independent N2: docs/010 said the refusals run "again at the confirm (55000)"; at the confirm a
  change shows first as a stale draft (P5S02); corrected (text only).
- Independent N3: docs/010 choice (3) (a Payment of the Rent line does not make a Charge draft
  stale) has no test; slice 12 list.
- Independent N4: U2 was not in this record; added.
- Security N2: in the database, "only financial.approve confirms" is the authorization string, a
  human identity and an active actor; the capability itself is checked in the service, as in every
  earlier confirm (the trust model of slice 2); no change.
- Security N3: the confirm's stamp steps past the Charge's latest correction only, but the row's
  serializer also orders it after every allocation and Credit application on the Charge; a future
  stamped allocation (at most 5 seconds) would make the confirm fail closed (23514, nothing
  written). Not changed (a code change after the green runs would need new runs); slice 12 list,
  and the plan's 10c-3b note asks for it.

Text fixes after round 2 (plan, docs/010, this record): no test reads them, so no new run.
