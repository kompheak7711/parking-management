# V1-056 sub-slice 10c-1a — Post-settlement charge reduction: review record

Sub-slice: 10c-1a (migration `20261103_99`). Base commit: 469c831 (the 10b checkpoint record).
Rule IDs: BR-SETTLE-013, BR-SETTLE-012, BR-INV-045, BR-AUTH-010; DB-SETTLE-003, DB-SETTLE-005;
owner answer 1 to Q-2026-10-06-36.

## Before the build

- Read in order: AGENTS.md, ops/NOW.md, ops/V1_055_RUN_RULES.md, ops/V1_056_TAKEOVER.md, the
  plan's slice 10 design note, ops/V1_056_QUESTIONS.md (Q-36, Q-37), the 10b review record and
  the V1-056 notes in docs/010. Start state checked: tree clean, HEAD 469c831.
- Owner answers to the three 10b points (2026-10-07) recorded in docs/010; BR-MOVEOUT-006
  (docs/002) gained the "Amended by" line for a Damage extra charge after closure.
- Split of 10c (no owner answer needed): 10c-1a `CHARGE_REDUCTION`, 10c-1b `REFUND` of lines paid
  by Payments or Credits, 10c-2 lines paid by a Deposit application. A wrong Late-payment Charge
  after closure has no fix: Q-2026-10-07-38 (a recommendation; it blocks only a later 10c-3, not
  10c-1a or 10c-1b).
- Pre-code design written to the plan's 10c entry (read only; within the design note).
- Long documents edited only with exact-text edits; `git diff --stat` checked after each edit:
  before round 1: docs/002 +2, docs/010 +1 then +3 in total, questions +8, plan +6, docs/004 +17,
  traceability +90; after the round-1 fixes in total docs/002 +4, docs/004 +20, traceability +103.
  No edit changed more than intended.
- Read-only search of all backend tests for affected tests: the 26 head-revision assertions in 14
  modules (updated); no other test names the new functions; the whole-catalog privilege checks
  (`test_lease_enforcement_api_migration.py`, nothing granted to PUBLIC) are not affected because
  the new functions are revoked from PUBLIC; the tests that compare the whole function list do so
  inside their own temporary databases at their own revisions. The migration only adds
  functions, so no earlier test sees a changed function.

## Built

- Migration `20261103_99`: the recorder `app.record_settlement_charge_reduction_draft` and the
  confirm `app.confirm_settlement_charge_reduction` (EXECUTE to `prm_financial` only); internal
  helpers for the input shape, the source state, the plan check and the result (no grant).
  Additive and forward-only: no table, trigger or earlier function changes.
- Service: `SettlementCorrectionService.record_charge_reduction` and `confirm_charge_reduction`
  with `RecordChargeReductionCorrectionCommand` (`property_rental/settlement_correction.py`).
- Tests: `test_settlement_correction.py` (unit, 4 new tests, 26 cases),
  `test_settlement_charge_reduction_migration.py` (PostgreSQL, 4 tests before round 1, 5 after; last in
  `scripts/database-test.sh`); 8 traceability entries appended (9 after round 1); 26 head-revision assertions.
- Docs: docs/004 DB-SETTLE-005 (as built); docs/010 (owner answers to the 10b report, the 10c-1a
  entry, updated tests); the plan's 10c entry; ops/V1_056_QUESTIONS.md (Q-2026-10-07-38).
  docs/005 unchanged (no route; slice 11e).

New checks named for the owner (10b answer 2): the recorder and the confirm refuse a reduction
that would release paid value and an Invoice that a Deposit application paid. Neither refuses
anything staff can do today: after closure every Adjustment is already refused (8e-1), and before
closure this command does not run (it needs a closed Settlement).

Static checks, each in its own tool call: `ruff format` on the four new or edited Python files
(unchanged), `ruff check` (clean), `ruff format --check` over src, tests and the new migration (304
files already formatted), `mypy` (no issues). One extra format check over every migration file was
run by mistake (wrong scope): it lists 12 old, unedited migration files that were never formatted;
nothing was changed; the documented scope is src, tests and the new migration.

Migration-only check before P1 (owner rule): the throwaway copy of `scripts/database-test.sh` in
the session scratchpad ran `alembic upgrade head` on a fresh container and reached `20261103_99`.

## Runs before review round 1

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U1 | backend unit, full | 3557 passed, 1734 skipped, 1 warning (Starlette) | first run of 10c-1a | `V1-056-slice-10c-1a-unit-test-run.txt` |
| P1 | PostgreSQL, full | 1897 passed, 1 warning (Starlette) | first run of 10c-1a | `V1-056-slice-10c-1a-full-test-run.txt` |

No correction was needed.

## Round 1 (2026-10-07)

Both reviewers were fresh read-only subagents given the diff, the new files, the rule IDs, the
takeover file, the plan's slice 10 design note with the 10c-1a pre-code design and the owner
answers; neither edited anything or ran a test.

### Independent review: 0 blockers, 0 should-fix, 11 notes

Verified with no finding: the owner-approved design, money and history, grants and definer
settings, no deadlock cycle, the match with `app.adjust_invoice`'s no-release branch and its
deferred checks, the 10a and 10b writer notes, the tests (the purely additive migration proved by
the catalog test).

- N1 (at the confirm the plan's 55000 refusals for a release of paid value or a Deposit
  application cannot be reached: a changed line is always P5S02; the migration comment and the
  docs/010 wording said otherwise): fixed; the comment above the confirm, docs/010 choice 2 and the
  plan's as-built sentence now say so.
- N2 (the docstring dropped "rebuilt from the stored records"; the replay's Invoice is its current
  state): fixed in the docstring.
- N3 (the human-approver refusal has no test): answered and partly covered. A user account always
  carries a HUMAN identity (the `sync_human_actor_identity` trigger), so a non-human actor is
  refused first by `app.require_invoice_command_actor` (P4506); the new test confirms with a
  billing service identity and gets P4506. The 42501 branch stays as defence in depth, as in 10b.
- N4 (two variants, no cross test): fixed; the new test sends an `EXTRA_CHARGE` draft to the
  reduction confirm and a reduction draft to the extra-charge confirm (P0002 each, both pending)
  and reuses a reduction draft key for an extra charge (P5205).
- N5 (BR-INV-045 shown only with the Primary Tenant's Invoice): fixed; the new test reduces
  another Signer's Invoice: the Adjustment is that Signer's, on that Signer's ledger only.
- N6 (the Deposit-application test traced to BR-SETTLE-009): fixed; it traces to DB-DEP-005.
- N7 (no P4507 guard before `version=version+1`): answered; an Invoice version of 2147483647 is
  not reachable in practice; it would end as 22003, reported as unavailable, and nothing is written.
- N8 (the plan described the shape check after the stale check): fixed with an as-built sentence.
- N9 (Q-2026-10-07-38 is open; takeover section 6): answered; it blocks only a later 10c-3 for
  Late-payment Charges, as Q-37 blocked only later sub-slices; the 10c-1a checkpoint line in ops/NOW.md names it as open.
- N10 (BR-SETTLE-013 in docs/002 still says "extra charge or Refund"): fixed; an "Amended by" line
  names the kinds of the owner's answers to Q-36 and Q-37.
- N11 (the working tree also holds the documentation of the owner's answer to the 10b report):
  answered; disclosed above, committed with this sub-slice.

### Security review: 0 blockers, 0 should-fix, 5 notes

Verified with no finding: grants, deny-by-default, definer settings and no dynamic SQL, JSON input,
no change to a closed Settlement outside a linked correction, no forging or blocking of a
correction, races and deadlocks, no release of paid value, Deposit-applied Invoices, leaks, the
error mapping.

- N1 (at the confirm a 23514 from the chronology check, for example against a Payment allocation
  stamped up to five seconds ahead, is reported as invalid; the draft stays pending and a retry
  succeeds; no P4507 guard): answered; the same as the one-call `app.adjust_invoice` and the 10b
  confirm; nothing is written. Added to the plan's 10c-1a notes for 11e: the correction routes should word a
  23514 at confirm as "try again" rather than "invalid".
- N2 (the general draft reads still return the decision's transaction id, against "never
  returned" in the docstring and docs/004): fixed in wording (the result never returns it; the
  general draft reads until 11e, an existing plan note).
- N3 (the `settlement-correction:<id>` text is not reserved on Adjustments): answered in docs/004:
  the link, not the label, shows which Adjustment a correction wrote.
- N4 (missing negative tests): partly fixed with independent N4 (cross variants, key reuse), an
  unknown Property (P4501) and a service identity (P4506); answered for the rest: the inactive
  approver is the shared `require_invoice_command_actor` (P4506), tested where it is defined; the
  confirm-time shape re-check is reachable only by a draft the table owner wrote (as 10b round 3);
  the two-connection Payment race is covered by the lock order both reviewers checked (a Payment
  waits for the Invoice lock and then reads the reduced balance).
- N5 (advisory locks of application roles, the trusted actor and authorization reference,
  `SET CONSTRAINTS ALL IMMEDIATE` and one call per transaction): existing slice 12 items, unchanged.

## Runs after the round-1 fixes

Static checks, each in its own tool call: `ruff format` on the three edited Python files (one
reformatted), `ruff check` (clean), `ruff format --check` over src, tests and the new migration (304
files already formatted), `mypy` (no issues). Migration-only check before P2: reached
`20261103_99`. Read-only search: since P1 only the migration's comment above the confirm (outside
the function body), the service docstring, the new PostgreSQL test, traceability, docs, the plan
and this record changed; no other test is affected.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U2 | backend unit, full | 3557 passed, 1735 skipped, 1 warning (Starlette) | after the round-1 fixes (service docstring, traceability) | `V1-056-slice-10c-1a-unit-test-run-2.txt` |
| P2 | PostgreSQL, full | 1898 passed, 1 warning (Starlette) | after the round-1 fixes (new test) | `V1-056-slice-10c-1a-full-test-run-2.txt` |

## Round 2 (2026-10-07)

Fresh read-only reviewers again (the full diff, the new files, this record, the owner answers);
neither edited anything or ran a test. Both verified every round-1 fix and written answer.

### Independent review: 0 blockers, 0 should-fix, 5 notes

- N1 (this record said ops/NOW.md names Q-2026-10-07-38, but NOW.md was not yet changed): fixed;
  the 10c-1a checkpoint line names it as open, and the answer above says so.
- N2 (the plan said the digest covers the Invoice status; the code digests the issue state, which
  is the better choice; a new Deposit application shows as a changed Invoice, not line): fixed in
  the plan. The migration comment above the confirm ("a changed line") is left as built, so the
  committed migration is exactly what P2 ran; the result is the same (P5S02).
- N3 (this record still gave the counts before round 1): fixed; labelled and updated.
- N4 (the "another approver" check asserts only the conflict class): answered; it is the same
  pattern as the 10b test, and the conflict class is the contract; not changed, so the committed
  tests are exactly what P2 ran.
- N5 (the snapshot counts in `settlement_row` are 0 before and after, because the owner helper
  closes without snapshots): answered; the row JSON is the real check, the claim holds by
  construction (the confirm writes no snapshot table; the catalog test shows only added
  functions), the same pattern as 10a and 10b.

### Security review: 0 blockers, 0 should-fix, 2 notes

- N1 (until 10h a one-call reversal of a closure-era allocation or Credit application makes a paid
  Settlement line unpaid, and a `CHARGE_REDUCTION` can then remove what should have been a
  `REFUND`; no money leaves, the freed value stays on the Payment or Credit): added to the plan's
  10h entry (10h closes it and tests it) and reported to the owner below; the 11e screens may show
  the line's closure value next to the unpaid rest.
- N2 (the recorder's P0002 for an Invoice or line outside the Settlement reaches the service as
  "Lease or Final Settlement was not found"): plan note for 11e (as 10b's corrected-Invoice
  refusal).

### Outcome

Round 2 has no blocker and no should-fix, so 10c-1a is committed without a round 3. After round 2
only text changed: the plan, this record and ops/NOW.md. No executable line and no traceability
entry changed: the committed migration, service, tests and manifest are exactly what U2 and P2 ran.

Final runs: U2 backend unit 3557 passed; P2 full PostgreSQL 1898 passed. No correction was used.
Every run output is small and committed; nothing was moved to `~/Development/prm-run-logs/`.

Points for the owner (not blocking): Q-2026-10-07-38 (a wrong Late-payment Charge after closure
has no fix; recommendation with a sub-slice 10c-3); the new refusals of 10c-1a (a release of paid
value, a Deposit-applied Invoice) refuse nothing staff can do today; until 10h a one-call reversal
of a closure-era allocation followed by a `CHARGE_REDUCTION` removes a charge that was paid at
closure without a `REFUND` record (security round 2 N1; no money leaves).
