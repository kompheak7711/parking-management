# V1-056 sub-slice 10b — Post-settlement extra charge: review record

Sub-slice: 10b (migration `20261102_98`). Base commit: cfa5208 (the 10a checkpoint).
Rule IDs: BR-SETTLE-013, BR-SETTLE-012, BR-SETTLE-016, BR-INV-044, BR-AUTH-010; DB-SETTLE-003,
DB-SETTLE-005; owner answer 6 to Q-2026-10-06-36, owner answer 4 to Q-2026-10-06-37.

## Before the build

- Read in order: AGENTS.md, ops/NOW.md, ops/V1_055_RUN_RULES.md, ops/V1_056_TAKEOVER.md, the
  plan's slice 10 design note (10a to 10h), ops/V1_056_QUESTIONS.md (Q-36, Q-37), the 10a review
  record and the V1-056 notes in docs/010. Start state checked: tree clean, HEAD cfa5208.
- Owner answers to Q-2026-10-06-37 (2026-10-07) recorded in docs/010 and
  ops/V1_056_QUESTIONS.md; docs/004 DB-SETTLE-005 amended (the new link, the two exceptions to the
  same-Lease rule and their condition) and DB-PAY-009 `payment_returns` added (built in 10e).
- Long documents edited only with exact-text edits (owner instruction after the 10a plan slip);
  `git diff --stat` checked after each edit: docs/010 +1, questions +11/-1, docs/004 +10/-1 then
  +27/-1, plan +7, traceability +115, docs/004 +47/-1 in total, docs/010 +3 in total, plan +8 in
  total. No edit changed more than intended.
- Pre-code design written to the plan's 10b entry (read only; within the design note).
- Read-only search of all backend tests for affected tests: the 26 head-revision assertions in 14
  modules; tests naming the patched or rebuilt functions (`test_final_settlement_closed_refusal_migration.py`
  checks the guard's definer settings, grants and trigger order: unchanged by CREATE OR REPLACE;
  the 10a module's least-privilege and no-time-limit checks: no `interval` or `age(` added to
  the rebuilt functions, catalog test pinned to 96→97); the whole-schema privilege checks in
  `test_lease_enforcement_api_migration.py` (nothing granted to PUBLIC); the 10a test that
  commits a correction with a linked DRAFT Invoice (`test_an_invoice_draft_moves_onto_the_closed_lease_only_inside_its_own_correction`),
  which the new commit check changes (docs/010 note); no other test links an Invoice.

## Built

- Migration `20261102_98`: the link `authorized_nonrecurring_obligation_id` on
  `app.settlement_correction_effects` (deferrable, unique; the one-link check rebuilt with it);
  `app.settlement_correction_linked` and `app.link_settlement_correction_effect` rebuilt with it;
  the 8e-1 refusal accepts a linked one-time charge record; the deferred commit check on Invoice
  links (`app.assert_settlement_correction_invoice_issued`); the recorder
  `app.record_settlement_extra_charge_draft` and the confirm `app.confirm_settlement_extra_charge`
  (EXECUTE to `prm_financial` only); internal helpers for the input shape, the source state, the
  plan check and the result (no grant). Forward-only.
- Service: `backend/src/property_rental/settlement_correction.py` (`SettlementCorrectionService`).
- Tests: `test_settlement_correction.py` (unit, 4 tests), `test_settlement_extra_charge_migration.py`
  (PostgreSQL, 6 tests, last in `scripts/database-test.sh`); 10 traceability entries appended;
  26 head-revision assertions; the 10a test expectations above.
- Docs: docs/004 DB-SETTLE-005 (amendment and as built), DB-PAY-009; docs/010 (owner answers,
  10b entry, updated tests); the plan's 10b entry; ops/V1_056_QUESTIONS.md. docs/005 unchanged
  (no route; slice 11e).

Static checks, each in its own tool call: `ruff format` on the five new or edited files
(unchanged), `ruff check` (one unused import and one long line in the new test module, fixed;
then a second long line, fixed; then clean), `ruff format --check src tests` and the migration
(303 files), `mypy` (no issues).

Migration-only check before P1 (owner rule): the throwaway copy of `scripts/database-test.sh` in
the session scratchpad ran `alembic upgrade head` on a fresh container and reached `20261102_98`.

## Runs before review round 1

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U1 | backend unit, full | 1 failed, 3530 passed, 1730 skipped, 1 warning (Starlette) | first run of 10b | `V1-056-slice-10b-unit-test-run.txt` |
| U2 | backend unit, full | 3531 passed, 1730 skipped, 1 warning (Starlette) | after correction 1 of cause "missing traceability entries" | `V1-056-slice-10b-unit-test-run-2.txt` |
| P1 | PostgreSQL, full | 6 failed, 1887 passed, 2 warnings | first run of 10b | `V1-056-slice-10b-full-test-run.txt` |
| P2 | PostgreSQL, full | 1893 passed, 3 warnings | after correction 1 of each of causes A, B and C below | `V1-056-slice-10b-full-test-run-2.txt` |

U1: `test_traceability_manifest_covers_executable_tests` failed because the 10 new tests had no
traceability entries yet; correction 1 of 2 for that cause: the entries were appended.

P1, three causes, each corrected once (1 of 2):

- A (4 tests, a migration fault): the deferred Invoice validator `app.validate_invoice_record()`
  is not a definer function; the writer left it to COMMIT, where it ran under the financial role
  and failed with "permission denied for table lease_signers" (42501). Fix: the writer runs `SET
  CONSTRAINTS ALL IMMEDIATE` itself once every linked record is written, as the Invoice writers
  do (plan note for every later writer).
- B (the 10a test): my first change to it issued the moved draft in the same transaction, but
  `app.correct_invoice_draft` sets `ALL IMMEDIATE` while the linked Invoice is still DRAFT, so
  the new commit check refuses it there. Fix: that half now expects the new check's refusal
  (23514) and an unchanged draft; the guarded UPDATE passed before it (not P5S01).
- C (the `decided_at` test): `SET session_replication_role` needs a superuser and the test
  connects as the table owner. Fix: the owner disables the one effect trigger inside the
  transaction, runs the commit check with `SET CONSTRAINTS ALL IMMEDIATE` and always rolls back;
  the test then checks the trigger is still enabled.

Before P2: static checks again, each in its own tool call (format unchanged, lint clean, format
check 303 files, `mypy` clean); migration-only check reached `20261102_98`; read-only search:
since P1 only the migration (one statement) and the two test modules changed. U2 was not repeated:
the changes are inside a SQL string and PostgreSQL tests, which the unit run skips. The P1 and P2
warnings beyond Starlette are the known intermittent pydantic `UnsupportedFieldAttributeWarning`
in `test_credit_refund_api_migration.py` (slice 12 item).

## Round 1 (2026-10-07)

Both reviewers were fresh read-only subagents given the diff, the new files, the rule IDs, the
takeover file, the plan's slice 10 design note with the 10b pre-code design and the owner
answers; neither edited anything or ran a test.

### Independent review: 0 blockers, 1 should-fix, 9 notes

- SF1: no database test showed that the recorder refuses an authorization reference other than
  `final_settlements.prepare`. Fixed: the first test calls it with `financial.approve`,
  `invoices.create` and NULL (42501 each) and checks that no draft row was written. The optional
  inactive-approver case was not added: P4506 comes from the shared `require_invoice_command_actor`
  that every draft confirm uses and is tested there.
- N1 (lock gap with a superseding inspection, which locks the Lease row): fixed; the confirm
  locks the Lease row FOR SHARE after the Settlement draft lock and before the `invoice-lease`
  lock, as the Settlement confirm orders them.
- N2 (the amount regex allowed up to 9,999,999,999,999,999 cents): fixed; the input check also
  refuses more than 9,000,000,000,000,000 (the cap of the other money writers).
- N3 (the records were stamped before the approval): fixed; the time and business date are read
  again after `app.begin_settlement_correction`, and the override is checked again against that
  issue date.
- N4 (the replay docstring; no READ COMMITTED guard; docs/010 described a 23505 race that READ
  COMMITTED cannot produce): fixed; docstring reworded, READ COMMITTED required (55000, tested),
  23505 no longer reported as stale.
- N5 (docs/010 said `app.issue_invoice` sets ALL IMMEDIATE while DRAFT): fixed;
  `app.create_invoice_draft` and `app.correct_invoice_draft`.
- N6 (the 10a test: two expectations changed although the run rule says "the one expectation";
  docstring and plan text stale): answered and fixed. The test has two halves, each with one
  changed expectation and its dependent row check; both follow from the one commit check the
  design note asks of 10b, and both are recorded in docs/010 (Updated tests). The docstring now
  says the linked draft passes the refusal and is then refused by the commit check; the plan
  bullet has an "as built" sentence. Reported to the owner.
- N7 (the commit check is a tightening, which takeover section 2 reserves for the owner):
  answered in docs/010 and the migration docstring: it refuses nothing any role could do before
  (the link functions have no grant and no correction existed before this migration), and it is
  the check the design note asks of the first writer that links an Invoice. Reported to the
  owner.
- N8 (docs/004 DB-INV-005 named only `app.record_one_time_charge`; the 10a paragraph still said
  one-time charge records stay refused): fixed in both places.
- N9 (an extra charge inside a 10e `RETURNED_PAYMENT` correction cannot reuse the confirm):
  plan note for 10e (move the writes into an internal helper then).

### Security review: 0 blockers, 2 should-fix, 3 notes

- SF1: the confirm derived its record ids from the draft id with md5, and a holder of
  `invoices.create` chooses one-time charge ids (and other routes choose Invoice and audit ids),
  so a client could take the derived id first and block every confirm of that draft (23505,
  then reported as "stale"). Fixed: fresh `gen_random_uuid()` ids for the one-time charge
  record, the Invoice, its line and every audit event; the result reads the records back through
  the correction's links; 23505 at confirm is a conflict again. Test: a Customer-only charge
  recorded with the id the old formula would derive no longer blocks the confirm.
- SF2: the commit check raised only when the linked Invoice existed and was DRAFT, so a caller
  that made it run at once (`SET CONSTRAINTS app.settlement_correction_effects_invoice_issued
  IMMEDIATE`) before the Invoice was written used it up; a VOID Invoice also passed. Fixed: the
  check is positive (the Invoice must exist and be UNPAID, PARTIALLY_PAID or PAID). Test: that
  named constraint set IMMEDIATE before the link of an Invoice not yet written is refused.
- N1 (READ COMMITTED): fixed with independent N4.
- N2 (`SET CONSTRAINTS ALL IMMEDIATE` runs every pending deferred check with the owner's rights
  and stays in force): plan note: a variant writer is the only statement of its transaction (the
  service runs one call per transaction).
- N3 (the decision's transaction id was returned): fixed; the result and the recorder's replay
  of a decided draft leave it out (tested).

## Runs after the round-1 fixes

Static checks, each in its own tool call: `ruff format` on the five edited files (one
reformatted), `ruff check` (clean), `ruff format --check src tests` and the migration (303
files), `mypy` (no issues). Migration-only check before P3: reached `20261102_98`. Read-only
search: since P2 only the migration, the service, the two new test modules, the 10a test's
docstring, docs, traceability notes of the new entries, the plan and this record changed.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U3 | backend unit, full | 3531 passed, 1730 skipped, 1 warning (Starlette) | after the round-1 fixes (service and unit test changed) | `V1-056-slice-10b-unit-test-run-3.txt` |
| P3 | PostgreSQL, full | 1893 passed, 1 warning (Starlette) | after the round-1 fixes | `V1-056-slice-10b-full-test-run-3.txt` |

One U3 attempt before this did not run: the shell could not open the relative output path, so
pytest never started; the command was repeated with an absolute path.

## Round 2 (2026-10-07)

Fresh read-only reviewers again (the full diff, the new files, this record, the owner answers);
neither edited anything or ran a test. Both verified every round-1 fix against the code.

### Independent review: 0 blockers, 1 should-fix, 6 notes

No deadlock cycle found (the Settlement confirm, the inspection writer, the one-time charge
recorder, `set_initial_rent_due_date`, physical move-out, Lease update triggers, other
corrections); no clock-dependent flake; every assertion reachable.

- SF1: this record claimed a test of the recorder's replay of a decided draft leaving out the
  transaction id; no test called the recorder after a confirm. Fixed: the first test records the
  same command again after the confirm and checks the state and the missing transaction id.
- N1 (the 10a test's traceability note still says "can"): answered; the manifest is
  append-only, so docs/010 (Updated tests) says the note is superseded by the test docstring.
- N2 (the confirm-time Due Date refusal had no test): fixed; the table owner records a draft as
  the recorder would have five days earlier with an override of yesterday; the confirm answers
  55000 with the message and the draft stays pending.
- N3 (database refusals covered only by the Python checks): fixed; one direct loop (an unknown
  key, an amount over the cap, a text amount, a fractional amount, an impossible date, a date
  without its reason, an untrimmed description) expects 22023 and no draft row, and a DRAFT
  Invoice of the Lease as the corrected Invoice is refused (55000).
- N4 (no time-limit scan of the 10b functions): fixed; no `interval` and no `age(` in the
  recorder, the confirm or the five internal functions.
- N5 (the new link's UNIQUE constraint and its place in the one-link check were not asserted):
  fixed with two catalog assertions.
- N6 (the migration docstring still said "still DRAFT"): fixed ("not issued").

### Security review: 0 blockers, 0 should-fix, 6 notes

Paths checked: grants; changing a closed Settlement outside a correction; the 8e-2 refusal;
forging or reusing a header, effect or link; blocking a correction (ids, unique keys, locks);
Staff confirming; non-human or inactive approvers; definer functions and `search_path`; SQL
injection and f-strings; JSON input; leaks; the test-only `DISABLE TRIGGER`; races and stale
drafts.

- N1 (the confirm never re-checked the stored charge's shape; its `charge` comparison was always
  equal): fixed; the confirm runs the recorder's shape check on the stored charge (P0002 if it
  differs) and the always-equal comparison is gone.
- N2 (two branches untested: the recorder's replay of a decided draft, a linked VOID Invoice):
  the first is fixed with independent SF1; the second is answered: the check is positive, so
  VOID fails by construction, and the early-run test already proves the positive form.
- N3 (the general draft reads still return the transaction id): plan note for 11e (strip it
  there too).
- N4 (`SET CONSTRAINTS ALL IMMEDIATE` inside the definer): answered; the plan note stays (one
  writer call per transaction).
- N5 (the unique `(customer_id, category, source_reference)` key would collide when one
  correction writes two charges of one category for one Customer): plan note for the 10e helper.
- N6 (pre-existing: application roles may take advisory locks; `prm_runtime` may insert audit
  events): slice 12 open item.

## Runs before round 3

Static checks, each in its own tool call: `ruff format` on the two edited Python files (one
reformatted), `ruff check` (clean), `ruff format --check src tests` and the migration (303
files), `mypy` (no issues). Migration-only check before P4: reached `20261102_98`. Read-only
search: since P3 only the migration (the shape re-check, the removed comparison, the docstring),
the new PostgreSQL test module, docs, traceability notes of the new entries, the plan and this
record changed.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U4 | backend unit, full | 3531 passed, 1730 skipped, 1 warning (Starlette) | standing rule before round 3 | `V1-056-slice-10b-unit-test-run-4.txt` |
| P4 | PostgreSQL, full | 1893 passed, 1 warning (Starlette) | standing rule before round 3 | `V1-056-slice-10b-full-test-run-4.txt` |

One U4 attempt before this did not run: it was started in parallel with the migration-only
check, the shared shell lost the `backend` directory and `uv` could not spawn pytest; the same
command ran again alone, writing the same output file.

Round 2 has no blocker and 1 should-fix in total, so the standing rule allows one round 3.

Correction to the round-2 text above (security N1): the confirm's shape re-check of the stored
charge answers 22023 when the stored charge fails the check outright, P0002 when it normalizes
to another form, and the stale check (P5S02) comes first when the revision differs too. Only the
table owner or a faulty future recorder could store such a draft; this branch has no test
(round 3 security note 1).

## Round 3 (2026-10-07, standing round-3 rule)

### Independent review: 0 blockers, 0 should-fix, 5 notes

Every round-2 fix verified against the code; final sweep of access, money, history, the 8e-1
refusal, the commit check, stale drafts and locks (no deadlock cycle), collisions, text limits,
records, runs and test dates.

- N1 (a Damage extra charge is prepared and authorized by the Settlement's approvers, not under
  `damage_charges.bill` as BR-MOVEOUT-006 says for a Damage charge; the one-finding rule comes from
  BR-MOVEOUT-006 and DB-INV-005): docs/010 now says so (owner answer 1 to Q-2026-10-06-36, design
  note point 3), and the Damage test's traceability entry also names BR-MOVEOUT-006. Reported to
  the owner.
- N2 (the result's scalar reads assume one charge per correction): 10e plan note.
- N3 (the after-approval Due Date re-check is reachable only across midnight): no change.
- N4 (plan wording: the confirm takes the draft lock before the replay): fixed in the plan.
- N5 (the docs/010 lead sentence still said "still DRAFT"): fixed ("not issued").

### Security review: 0 blockers, 0 should-fix, 3 notes

Paths checked: grants; the 8e-1 and 8e-2 refusals; forging, reusing or blocking a correction;
Staff confirming; non-human or inactive approvers; definer functions and `search_path`; SQL
injection and f-strings; JSON input; leaks; the test-only `DISABLE TRIGGER`; races and stale
drafts.

- N1 (the shape re-check's refusal codes and its missing test): the correction above.
- N2 (every draft confirm trusts the actor and the authorization reference the financial role
  passes) and N3 (`search_path=pg_catalog` without `pg_temp` last; no application role has
  TEMPORARY): pre-existing; slice 12 hardening item.

### Outcome

Round 3 has no blocker and no should-fix, so 10b is committed under the standing round-3 rule.
After round 3 only text changed: docs/010, the plan, this record and one added upstream id
(`BR-MOVEOUT-006`) in a new traceability entry. No executable line changed: the committed
migration, service and tests are exactly what U4 and P4 ran. Because the traceability manifest is
read by a unit test, that test alone ran again:

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U5 | backend unit, `tests/test_traceability.py` only (it covers every test that reads the manifest) | 28 passed | traceability metadata changed after round 3 | `V1-056-slice-10b-unit-test-run-5.txt` |

Final runs: U4 backend unit 3531 passed; P4 full PostgreSQL 1893 passed; U5 28 passed.
Corrections used, each 1 of 2: missing traceability entries (U1); the writer left the deferred
Invoice validators to COMMIT (P1, cause A); the 10a test expectation under the new commit check
(P1, cause B); `session_replication_role` needs a superuser (P1, cause C). Every run output is
small (at most about 150 KB) and committed; nothing was moved to `~/Development/prm-run-logs/`.

Points for the owner (not blocking): the 10a test changed two expectations (one per half), both
from the commit check the design note asks of 10b (docs/010, Updated tests); the commit check
refuses nothing any role could reach before, so it is not treated as a tightening (docs/010
choice 8); a Damage extra charge is authorized under `financial.approve`, not
`damage_charges.bill` (BR-MOVEOUT-006).
