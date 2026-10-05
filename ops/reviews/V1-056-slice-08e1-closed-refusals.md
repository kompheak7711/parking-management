# V1-056 sub-slice 8e-1 — Refusals after a Final Settlement closes: review record

Sub-slice: 8e-1 (migration `20261027_92`). Not committed. Base commit: b3d6fc2 (the 8e pre-code
review, split and Q-2026-10-06-32).
Rule IDs: BR-SETTLE-012, BR-SETTLE-013; owner answer 7 to Q-2026-10-05-20 (approved tightening).

## Before the build (read only)

- Pre-code review committed as b3d6fc2: every 8e note mapped, path search of one-call changes to
  a Lease's obligations after closure, split into 8e-1, 8e-2 and 8e-3, Q-2026-10-06-32 for 8e-2
  and 8e-3 (8e-1 does not depend on it).
- Read-only search for affected tests before P1: 26 head-revision assertions in 14 modules moved
  from `20261026_91` to `20261027_92` (only the revision string); catalog-wide function tests are
  pinned to earlier revisions; no test names a trigger of the seven guarded tables (only
  `invoice_lines`, which is not guarded); no earlier test writes to a guarded table after a
  closure (the two closures in `test_final_settlement_migration.py` and
  `test_final_settlement_refund_migration.py` write none); with an open Settlement the guard
  returns before any refusal, so the 8a-1 Deposit-application refusals are unchanged; the new
  module runs last.

## Built

- `app.refuse_closed_final_settlement_change` (SECURITY DEFINER, no grant) as the first BEFORE
  INSERT trigger (`a0_<table>_final_settlement_closed`) on `invoice_void_events`,
  `invoice_adjustments`, `invoice_adjustment_reversals`, `late_payment_decisions`,
  `late_payment_charge_corrections`, `invoices` and `authorized_nonrecurring_obligations`; for a
  Lease with a Final Settlement it locks the target Invoice, then the Settlement row FOR SHARE,
  and refuses with `P5S01` when the Settlement is closed.
- `P5S01` mapped to a conflict in `invoice.py`, `late_payment.py`, `final_utility_invoice.py`,
  `billing.py` and `unpaid_initial_termination.py`.
- Tests: `test_final_settlement_closed_refusal_migration.py` (6 at round 1; 10 after the round-1
  and round-2 fixes) and `test_final_settlement_closed_refusal.py` (2 unit); 8 traceability entries
  appended at round 1 (12 after the fixes); the module
  added to `scripts/database-test.sh`; docs/004 (DB-SETTLE-001), docs/005 (API-072), docs/010.

Static checks (separate commands): `ruff format` on the changed files; `ruff check src tests`
(one long line and one import order fixed, then clean); `ruff format --check src tests` (289
files formatted); `mypy` (one re-exported import fixed, then no issues in 289 source files).

## Runs before review round 1

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U1 | backend unit, full | 3454 passed, 1678 skipped, 1 warning (known Starlette deprecation) | first run of 8e-1 | `V1-056-slice-08e1-unit-test-run.txt` |
| P1 | PostgreSQL, full (`./scripts/database-test.sh`) | 1839 passed, 2 warnings | first run of 8e-1 | `V1-056-slice-08e1-full-test-run.txt` |

The second P1 warning is the known intermittent pydantic `UnsupportedFieldAttributeWarning` (alias
`idempotency_key`) in
`test_credit_refund_api_migration.py::test_credit_refund_http_real_competing_refunds_cannot_double_consume_credit`
(slice 12 item); recorded, not hidden. No correction used.

## Round 1 (2026-10-06)

Both reviewers were fresh read-only subagents given the diff, the rule IDs, the takeover file, the
plan's 8e pre-code review and the owner answer; neither edited anything or ran a test.

### Independent review: 1 blocker, 1 should-fix, 4 notes

- B1: the guard is BEFORE INSERT only. `app.correct_invoice_draft` (`PATCH /invoices/{id}`)
  updates a DRAFT's `lease_id` to the Lease of the replacement charge, and `app.issue_invoice`
  (`POST /invoices/{id}/issue`) issues it by UPDATE. After closure staff can take any draft (no
  Lease, or another Lease), point it at a charge of the closed Lease whose Invoice was VOIDed
  before closure (the preview lists such a charge only as information) or that a draft correction
  replaced, and issue it: a new charge on the closed Lease with one-call routes. The plan's path
  search lists both routes; docs/005 and docs/010 over-claim. Fix: a BEFORE UPDATE OF lease_id,
  status trigger on `app.invoices` (a new Lease on the row, or DRAFT to issued), DRAFT to VOID
  allowed, with tests. Verified by reading `app.correct_invoice_draft` (migration 36, line 306)
  and `app.protect_invoice_header_history` (migration 29, line 2094).
- S1: the tests do not reach every path the plan's 8e-1 entry promises: Rent only through the
  owner-level `create_recurring_rent_invoice` (same proof as the owner INSERT), no Rent generator
  or scheduled run item, final and catch-up Utility only at the mapping level, no hand-back,
  moved-in credit, cleaning, Damage or other-Signer draft, no Payment reversal or Credit
  recognition after closure, and the open-Settlement branch that locks the target Invoice is
  never run.
- Notes: N1 lock order for 8e-3 (`app.correct_late_payment_charge` locks the Charge before its
  Invoice; the confirm should lock Charges before Invoices or map 40P01 to a conflict); N2 slice
  10 needs a deliberate, auditable exemption from the guard; N3 `P5S01` reaches the user as a bare
  409 (the final Utility reason is None and the message says "sources changed or are in use"); N4
  the two-connection test's docstring says the closure "then sees" the change, which is not
  asserted.

### Security review: 1 blocker, 2 should-fix, 6 notes

- B1: the same as independent B1 (also a draft with the Lease that exists at closure can be issued;
  only the 8e-3 re-check of `INVOICE_DRAFT_NOT_ISSUED` stops that).
- S1 (needs the owner): a scheduled Rent run that includes a Lease with a closed Settlement can
  never succeed. `app.lease_is_billable_for_recurring_period` still treats a TERMINATED Lease as
  billable for full months up to its actual termination date; the item is recorded as `ERROR`
  (`RENT_PERSISTENCE_P5S01`), the attempt becomes `FAILED` (`ITEM_FAILURE`), and only a later
  `GENERATED` or `SKIPPED` item clears it, so every retry fails again. `app.void_invoice` refuses a
  run-generated Rent Invoice unless its run SUCCEEDED, so VOID and the hand-back resolution are
  blocked for every other Lease's Rent Invoice of that run. It happens when a Rent period was not
  billed before closure (the preview has no Rent-period blocking issue). Verified by reading
  `app.finish_scheduled_billing_attempt` (migration 35, line 1213) and `app.void_invoice`
  (migration 36, lines 477 to 512). docs/005 ("continues") hides this.
- S2: the same coverage gaps as independent S1; asks at least for a scheduled Rent run item, one
  final or catch-up Utility call and the B1 tests.
- Notes: N1 a VOID of a DRAFT Invoice of a closed Lease is refused too (a draft is not an
  obligation), moot once B1 is fixed and 8e-3 blocks closure on `INVOICE_DRAFT_NOT_ISSUED`; N2
  8e-3 lock order (Charges before Invoices; `FOR NO KEY UPDATE` for the confirm's Invoice locks;
  40P01 and 55P03 map to 503 today in `invoice.py`, `late_payment.py`, `billing.py`); N3 slice 10
  must not use a session setting for its exemption (any role can call `set_config`), but a linked
  correction row in the same transaction; N4 guard `app.late_payment_charges` too (defense in
  depth; its only writer inserts the guarded Decision first); N5 bare 409, the Late-payment 409
  returns a review that still says `eligible: true`, and charges with no Lease for the former
  tenant stay open (outside answer 7); N6 checks that passed (definer, search path, revokes, no
  grant, no close or reopen path, trigger order, lock order with today's writers, no data leak,
  every caller maps `P5S01` to a conflict, open paths write no guarded table).

### Outcome

STOPPED before any fix: security S1 needs an owner decision on how a billing run treats a Lease
whose Settlement is closed (Q-2026-10-06-33). The fixes for B1, the test gaps and the notes are
listed there. No run after round 1. Corrections used: none.

## Owner answers and fixes after round 1 (2026-10-06)

Owner answered Q-2026-10-06-33: (1) a billing run skips a closed Lease with a new reason code, with
a test that a VOID on an open Lease is never refused because another Lease in the same run is
closed; (2) closure is blocked while a Rent month of the Lease is still unbilled (built in 8e-3);
(3) a VOID of a draft Invoice of a closed Lease stays refused, and closure is blocked while the
Lease has any draft Invoice (the 8b preview issue `INVOICE_DRAFT_NOT_ISSUED` already does this;
8e-3 checks it again under its locks). Owner answered Q-2026-10-06-32 (1 to 4, the
recommendations; 8e-2 proceeds without a further stop). Recorded in docs/010 and the questions
file; the round-1 notes are in the plan.

Fixes made:
- B1 (both reviewers): the same guard also runs BEFORE UPDATE OF `lease_id`, `status` on
  `app.invoices` (`a0_invoices_final_settlement_closed_update`) when a row gets a Lease or a DRAFT
  with a Lease is issued. Test of exactly that path: while the Settlement is open a draft of a
  no-Lease charge is corrected onto a VOIDed charge of the Lease; after closure its issue is
  refused (P5S01, conflict), a new correction onto a Lease charge is refused, and nothing is
  written.
- Security S1 (owner answer 1): the scheduled Rent and Utility run items lock the Lease's
  Settlement row FOR SHARE and record a closed Lease as `SKIPPED` with `FINAL_SETTLEMENT_CLOSED`;
  the run item's allowed codes and `app.billing_run_has_missing_eligible_sources` accept it. Test:
  a Rent run with a closed and an open Lease skips the first, generates the second, succeeds, and
  the open Lease's Invoice is then VOIDed.
- Independent S1 / security S2 (test gaps): VOID, credit Adjustment and draft correction while the
  Settlement is open; the final Utility Invoice through its service after closure; a Payment
  reversal after closure; the Late-payment Charge table at its own trigger. The other writers that
  only reach the guarded tables are named in the plan's 8e-1 entry as proven by the table-level
  tests and the service mappings.
- Security N4: `app.late_payment_charges` is guarded too.
- Wording: docs/004, docs/005 (PATCH and issue routes, the run skip), docs/010, the
  two-connection test's docstring (independent N4).

Static checks (separate commands): `ruff format`, `ruff check src tests` (clean), `ruff format
--check src tests` (289 files formatted), `mypy` (no issues in 289 source files).

Read-only search before P2: no test reads the patched run functions or the run item CHECK text;
the callers of `app.billing_run_has_missing_eligible_sources` in `test_invoice_migration.py` only
gain an accepted code; the whole-catalog function test in `test_billing_service_migration.py` is
pinned to migration 53; with no Settlement or an open one the new checks return before any
refusal.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U2 | backend unit, full | 3454 passed, 1681 skipped, 1 warning (Starlette) | after the round-1 fixes | `V1-056-slice-08e1-unit-test-run-2.txt` |
| P2 | PostgreSQL, full | 2 failed, 1840 passed, 1 warning | after the round-1 fixes | `V1-056-slice-08e1-full-test-run-2.txt` |
| P3 | PostgreSQL, full | 1842 passed, 1 warning (Starlette) | after correction 1 of cause "run test period" and correction 1 of cause "draft VOID expectation" (test only, so U2 stands) | `V1-056-slice-08e1-full-test-run-3.txt` |

P2 failures, both in the new tests:
- `test_a_billing_run_skips_a_closed_lease_and_keeps_its_other_invoices_voidable`: the 1890
  period was also covered by two Leases of `test_billing_run_migration.py` (move-ins in 1889,
  end dates 30 June 1890), so the run had four items. Corrected: the test uses 1870, a year no
  fixture uses.
- `test_a_corrected_draft_cannot_bring_a_charge_onto_a_closed_lease`: the VOID of the corrected
  draft failed with 23514 `invoices_due_date_issued` (migration 64: only a DRAFT may lack a Due
  Date), before the guard: a one-time-charge draft has no Due Date until it is issued, so it can
  never be VOIDed, open or closed. Owner answer 3 (the VOID stays refused) holds. Corrected: the
  test expects that refusal; docs/004, docs/010 and the traceability note say so.

No pydantic warning in P2 or P3 (the known intermittent warning did not appear).

## Round 2 (2026-10-06)

Fresh read-only reviewers again (the diff, this record, the plan, the owner answers).

### Security review: 0 blockers, 1 should-fix, 5 notes

All round-1 findings confirmed fixed (every `UPDATE app.invoices` path listed; the WHEN clause
cannot be bypassed; the run skip needs a closed Settlement, which no role can write; grants,
definer settings and the CHECK unchanged except the added code). S-1: the Utility run skip is
never tested (new branching code inside the item's exception block; a fault would bring back the
round-1 S1 problem for Utility runs). Notes: N-1 the Rent run item takes the Settlement row
`FOR SHARE` before the Rent generator's Invoice locks, the reverse of the guard's and the planned
confirm's order (detected deadlock, heals on the next attempt); N-2 the item history trigger does
not check the new code (defense in depth only); N-3 docs/005 over-claimed on draft VOID; N-4
minor test gaps (a run with a started but open Settlement; moving a draft between Leases; an
inline comment); N-5 no assertion that the patched run functions keep their settings.

### Independent review: 0 blockers, 1 should-fix, 9 notes

All round-1 findings and the owner answer 1 build confirmed (anchors exactly once, CHECK identical
to migration 71's plus the code, variables set, earlier outcomes unchanged, no other list of
accepted codes needs the new one). S1: the same as security S-1. Notes: N1 the same as security
N-1; N2 the same as security N-3; N3 the inline comment in the two-connection test; N4 loose
traceability IDs (BR-RENT-018 on the run test; BR-SETTLE-011 on two tests); N5 the corrected-draft
test cited owner answer 1; N6 (pre-existing) a one-time-charge draft can never be VOIDed, so with
owner answer 3 closure waits until it is issued or corrected (open item); N7 stale NOW.md line
and counts in this record; N8 for 8e-3, lock the Lease row before the plan check so a writer whose
guard ran before the Settlement started cannot commit a charge after closure; N9 the same as
security N-2.

Round 2 has no blocker and one should-fix (the same finding from both reviewers), so the standing
rule allows one round 3 after the full backend unit and PostgreSQL runs.

## Fixes after round 2 and runs before round 3

- S1 / S-1: `test_a_utility_run_skips_only_a_closed_lease_and_keeps_its_other_invoices_voidable`
  (1872 Leases and rate; one Settlement closed, one started and open; SKIPPED with
  `FINAL_SETTLEMENT_CLOSED` and no Invoice, GENERATED, run SUCCEEDED, the billed Invoice VOIDed).
- Notes taken: N-5 (the two patched run functions keep definer, search path and grants, in the
  least-privilege test); N2/N-3 docs/005; N3 inline comment; N4 traceability IDs (BR-INV-050 on
  both run tests, BR-SETTLE-012 instead of BR-SETTLE-011); N5 citation; N7 NOW.md and counts;
  N1/N-1, N8 and N6 as plan notes for 8e-3 and 11e or slice 12; N9/N-2 recorded as optional
  hardening in the plan (as for `NOT_MOVED_IN`).
- Static checks (separate commands): `ruff format`, `ruff check src tests` (one import order
  fixed, then clean), `ruff format --check src tests` (289 files), `mypy` (no issues).
- Read-only search before P4: since P3 only the new test module, docs and records changed;
  migration 92 unchanged; the 1872 rate and Leases are written by the last module only.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U3 | backend unit, full | 3454 passed, 1682 skipped, 1 warning (Starlette) | standing rule before round 3 | `V1-056-slice-08e1-unit-test-run-3.txt` |
| P4 | PostgreSQL, full | 1843 passed, 1 warning (Starlette) | standing rule before round 3 | `V1-056-slice-08e1-full-test-run-4.txt` |

## Round 3 (2026-10-06, standing round-3 rule)

### Security review: 0 blockers, 0 should-fix, 4 notes

The round-2 should-fix is fixed and proven by the new Utility run test (only the new branch can
write `FINAL_SETTLEMENT_CLOSED`; a fault would have given `ERROR` and a FAILED attempt). Confirmed:
no new grant, definer settings and grants kept on the guard and the two patched run functions, no
one-call INSERT or UPDATE path onto a closed Lease, no run skip without a closed Settlement, no
data leak, `P5S01` reaches the client as 409, no tightening beyond the owner's answers, docs match
the code. Notes: N1 the plan note on the Rent run item's deadlock outcome was imprecise (taken:
plan wording corrected); N2 the optional item-history check (already in the plan); N3 NOW.md
counts (updated at the checkpoint); N4 one docs/005 line too long (rewrapped). Also confirmed: a
DRAFT can still be corrected away from a closed Lease (not an obligation; 8e-3 blocks closure
while any draft exists, owner answer 3).

### Independent review: 0 blockers, 0 should-fix, 4 notes

The round-2 should-fix and the round-2 notes are correct; nothing wrong, unsafe, untested where it
matters, inconsistent or tightened beyond the answers in the whole sub-slice; traceability
append-only (the first 2678 entries byte-equal to b3d6fc2; 12 entries appended); no clock-tied
dates; no weakened assertions. Notes: N1 the migration docstring's last paragraph calls the nine
triggers "additive or relaxing" although they are the owner-approved tightening named in its first
paragraph (not changed, so the committed migration is exactly the code U3 and P4 ran; this record
and docs/010 state it); N2 security round-2 N-4's "moving a draft between Leases" was not answered
in writing: not taken as a test, because it meets the same condition
(`OLD.lease_id IS DISTINCT FROM NEW.lease_id`) as the tested move from no Lease onto the closed
Lease; N3 a traceability note said "every guarded table" for a test that covers seven of eight
(reworded); N4 docs/005's "a draft that has a Due Date gets 409" follows from the table test and
the mapping, with no service-level test (information; 8e-3 blocks closure while any draft exists).

### Outcome

Round 3 has no blocker and no should-fix, so 8e-1 is committed under the standing round-3 rule.
After round 3 only documents changed (the plan note wording, one traceability note, a docs/005
line wrap, this record, NOW.md); the committed migration, code and tests are exactly what U3 and
P4 ran. Final runs: U3 backend unit 3454 passed; P4 full PostgreSQL 1843 passed. Corrections used:
run test period 1 of 2, draft VOID expectation 1 of 2.
