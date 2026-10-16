# V1-056 sub-slice 10f-2 — the mistaken credit Adjustment reversal after closure — review record

Sub-slice: 10f-2 (owner answer 7 to Q-2026-10-06-36; answer (a) to Q-2026-10-16-118; answer (b)
to Q-2026-10-16-119, recorded at the start of this session). Migration `20261221_147` (relaxing
patches and new functions). Base commit: dd8fbcb. Built on 2026-10-16. Not pushed.

Rule IDs: BR-SETTLE-012, BR-SETTLE-013, BR-SETTLE-016, BR-INV-044, BR-CREDIT-006, BR-CREDIT-008,
BR-AUTH-010; DB-SETTLE-003, DB-SETTLE-005, DB-INV-010, DB-CREDIT-002. Design: ops/V1_056_PLAN.md,
"10f-2 pre-code design" and "10f-2 as built".

## Built

- Migration `20261221_147_settlement_adjustment_reversal.py`: new writers
  `app.record_settlement_adjustment_reversal_draft` (`final_settlements.prepare`) and
  `app.confirm_settlement_adjustment_reversal` (`financial.approve`), EXECUTE to the financial
  role; new internal `app.begin_settlement_correction(uuid,uuid,uuid,text,jsonb)` (the variant's
  result keys in the decision; the framework keys win), `app.adjustment_reversal_source(uuid,uuid,uuid)`
  (the 10f-1 releases and amounts with the correction's refusals) and
  `app.settlement_adjustment_reversal_result`; exact-text patches of
  `app.adjustment_reversal_result`, `app.validate_credit_application_put_back`,
  `app.validate_adjustment_reversal_put_back` and `app.adjustment_reversal_put_back_allowed` (a
  `SETTLEMENT_CORRECTION` draft of the variant `ADJUSTMENT_REVERSAL` is accepted too; the allowed
  function also needs the put-back linked to that correction). No table, column, trigger or other
  grant change.
- Service: `property_rental/adjustment_reversal.py` gains `RecordSettlementAdjustmentReversalCommand`,
  `settlement_adjustment_reversal_draft_id`, `record_correction` and `confirm_correction`.
- Tests: new `test_settlement_adjustment_reversal_migration.py` (7 tests, last in
  `scripts/database-test.sh`); four new unit tests in `test_adjustment_reversal.py`.
- Committed tests changed: none, except the 27 head-revision assertions in 15 modules (revision
  strings only; a script checked each file's count) and the module docstring of
  `test_adjustment_reversal.py` (it names 10f-2 too).
- Traceability: 11 entries appended (3,146 to 3,156); three notes of this sub-slice's own new
  entries updated in place after review round 1 and round 2.
- Docs: docs/002 (BR-CREDIT-006 exception, BR-SETTLE-013 amendment), docs/004 (DB-INV-010,
  DB-CREDIT-002, DB-SETTLE-005), docs/010 (owner answers, build, updated tests, reviews), the plan
  (as-built note), ops/V1_056_QUESTIONS.md (Q-119 answered), ops/V1_055_RUN_RULES.md (new rule).

Implementer's readings (design-change rule; confirmed needed and safe by the round 1
independent reviewer): (1) the begin overload, because decisions are append-only and the
four-argument function writes the decision itself; (2) the waiting-draft check in the recorder,
not the source, because the source is computed again at confirm while the draft waits; (3) the
refusal order in the source (the another-Lease check before the correction check, after T1); (4)
the patched 10f-1 result function plus the new correction result.

Read-only search for affected tests (before T1 and P1): every backend test naming
`begin_settlement_correction`, `adjustment_reversal_source`, `adjustment_reversal_result`,
`confirm_adjustment_reversal`, the three put-back check functions, and every test enumerating
function grants. Found: four-argument `begin_settlement_correction` calls (still unambiguous with
the overload), catalog comparisons between fixed earlier revisions, grant checks of named
signatures; none affected.

## Runs

| Run | Result |
|---|---|
| D1 | catalog dump (read only; one `REDACTED` marker, a numeric literal in a function not copied) |
| M1 | passed (`20261221_147` head) |
| FF1/FC1/L1/Y1 | passed (formatter first: one file reformatted) |
| T1 | 1 failed, 68 passed: another Lease's Adjustment recorded after this closure got the correction refusal before the another-Lease refusal (cause A, refusal order in the source, code; correction 1 of 2) |
| T2 | 69 passed (the passing rerun after T1) |
| U1 | 3835 passed |
| M2 | passed |
| P1 | 2233 passed (warnings: the known Starlette deprecation and the Pydantic alias warning of the unchanged Credit Refund API tests) |
| FF2/FC2/L2/Y2 | passed (after the round 1 test fixes) |
| T3 | 7 passed (the new module, after the round 1 test fixes) |
| U2 | 3835 passed |
| M3 | passed |
| P2 | 2234 passed (the same known warnings; the Pydantic alias warning counted twice) |
| U3 | 28 passed (`tests/test_traceability.py`, after the round 2 text fixes) |

After P2 only text changed (docs/004, docs/010, ops/traceability.json notes, the plan, this
record, and ops/NOW.md at the commit). Full outputs of the catalog dump, the migration checks and
the test runs are in `~/Development/prm-run-logs/v1-056-10f-2-*.txt` (format, lint and type checks
are short and not saved). Before each lint run the changed service and test files were searched
for lines over 100 characters (none; the migration keeps `# ruff: noqa: E501` as earlier ones).

## Review round 1 (fresh read-only subagents, during P1; told to write no file at all, scratch files included, and to run no test, script or database command)

Independent: 0 blockers, 4 should-fix, notes; readings 1 to 4 needed and safe. Security: 0
blockers, 1 should-fix, 5 notes.

- Should-fix (both): no test refused on the new link clause or the variant filter, nor on the
  transaction binding for this kind. Fixed with the reviewer's set-up (the 10f-1b room set-up),
  as `test_a_correction_s_put_back_needs_its_link_and_this_transaction_s_decision`:
  1. `rent_and_service_invoice`; pay the Service line S in full.
  2. A credit Adjustment of S on the Service line: Credit C = S.
  3. Apply `part = S // 2` of C designated on the Rent line.
  4. Record and confirm the 10f-1 reversal: put-back S − part.
  5. Reverse the Rent-line application of C: C holds `part`; the release has room.
  6. Control: `listed_put_back` (10f-1 kind, this transaction) on the Service line passes.
  7. `listed_correction_put_back`: a hand-written `SETTLEMENT_CORRECTION` draft
     (`final_settlements.prepare`) with payload `{'variant':…, 'invoice_adjustment_id':…}`, its
     decision through `app.confirm_financial_draft_record(...,'SETTLEMENT_CORRECTION',...)` (or
     written directly with `decided_at` one second before the transaction), no correction header
     and no effect; a labelled put-back of 1 on the Service line; `SET CONSTRAINTS ALL IMMEDIATE`;
     always rolled back. Variant `ADJUSTMENT_REVERSAL`, this transaction: 23514 from the deferred
     check; another transaction id, a decision dated before the transaction, or variant
     `CHARGE_REDUCTION`: 23514 from the label insert trigger.
- Should-fix (independent): the 10f-1 confirm after closure was asserted only as a conflict.
  Fixed: pinned to P5S02 (its source's refusal is part of the digest); the plan's test (3) wording
  corrected in the as-built note.
- Should-fix (independent): the correction draft's own withdrawal. Fixed: the preparer withdraws
  the stale draft, records again and confirms (restored 400, line owes 0, Credit 0).
- Should-fix (independent): the as-built docs. Written.
- Notes taken: the Invoice version (+2) and status after confirm; the begin overload's key
  precedence and its 22023 for a result that is not an object (rolled back; security note 1); the
  resolution test's docstring (it runs on a started Settlement).
- Notes kept: for slice 11, strip the decision's `transaction_id` in the general draft reads for
  this variant and the 10f-1 kind, the 11e route checks `financial.approve` before any call, the
  database cause must not be logged or returned; for 10h, a put-back has no Final Settlement, so
  the ordinary Credit application reversal can still reverse it after closure; for slice 12, the
  begin overload copies the four-argument body, the source overload repeats four 10f-1 refusals
  (debit and VOID branches untested there), the unreachable 55000 after the stale check (as
  10f-1), a test of the reversal of a charge reduction on a partly Deposit-paid line, and the
  readers of correction-linked Credit applications (Payment-return classification, return-reversal
  follow) now also see these put-backs.

## Review round 2 (fresh read-only subagents, during P2; same limits)

Security: clean (0 blockers, 0 should-fix, 6 notes). Independent: 0 blockers, 1 should-fix, 5
notes.

- Should-fix (independent): the docs/004 DB-SETTLE-005 paragraph sat at the end of DB-SETTLE-007.
  Fixed: moved to the end of DB-SETTLE-005 and its lead cites DB-SETTLE-005. Text only, so round 3
  runs under the round-3 rule of 2026-10-13.
- Notes taken (text): the traceability note says "snapshot counts" (the helper compares the row
  and the snapshot row counts); the docs/010 wording separates the result function (reads the
  draft) from the three checks (the transaction binding).
- Notes kept for the slice 12 list: a test that the link must name this decision's own correction
  (security note 1, unreachable through public functions); the deferred filter's binding and
  variant filters are proven only through the insert trigger, which refuses first (as 10f-1b); no
  case links an effect to a different put-back; a confirm of the withdrawn correction draft (55000
  already decided, optional). Security notes 3 to 6 repeat the round 1 slice 11 and 10h notes.

## Review round 3 (fresh read-only subagents, after P2 and U3; round-3 rule of 2026-10-13: round 2 had no blocker and only a text should-fix)

Independent: clean (0 blockers, 0 should-fix, 7 notes). Security: clean (0 blockers, 0
should-fix, 3 notes).

- Independent: the round 2 fixes are right; the code matches Q-118 (a) and Q-119 (b) and the
  design; amounts pinned to the cent; no committed test weaker (27 revision strings, additions and
  one module docstring); docs, traceability (3,145 to 3,156, no duplicate id) and the run logs
  match this record.
- Security: grants, definer settings, the transaction and `decided_at` binding, the begin
  overload's key precedence, the `CHARGE_REDUCTION` exception, the amount caps, no
  `transaction_id` in results or replays, no dynamic SQL; the docs claim nothing beyond the code.
- Notes taken (text): the docs/010 review entry and the plan's round 2 and 3 lines; this record's
  docstring, warnings and long-line lines; a docs/004 line rewrapped.
- Notes kept for the slice 12 list: no test isolates the `occurred_at >= closed_at` branch of the
  source (defensive: the 8e-1 refusal blocks an unlinked Adjustment after closure); the begin
  overload does not check the draft's variant itself (only the 10f-2 confirm calls it, after its
  own variant check); the general draft reads' `transaction_id` (slice 11, as before).
- Process: every review agent's task text said to write no files at all, scratch files included
  (owner answer 2 of 2026-10-16); none reported writing one.
