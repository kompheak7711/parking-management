# V1-056 sub-slice 10a — Post-settlement correction record: review record

Sub-slice: 10a (migration `20261101_97`). Base commit: 3b46ae9 (the slice 10 design checkpoint).
Rule IDs: BR-SETTLE-012, BR-SETTLE-013, BR-AUTH-010; DB-SETTLE-003, DB-SETTLE-005; owner answers to
Q-2026-10-06-36.

## Before the build

- Read in order: AGENTS.md, ops/NOW.md, ops/V1_055_RUN_RULES.md, ops/V1_056_TAKEOVER.md, the plan's
  slice 10 design note, ops/V1_056_QUESTIONS.md (Q-24, Q-35, Q-36), the 8g review record and the
  V1-056 notes in docs/010. Start state checked: tree clean, HEAD 3b46ae9 (the ops/NOW.md line
  right after the design commit 5c7906f).
- Owner answers to Q-2026-10-06-36 recorded (docs/010, ops/V1_056_QUESTIONS.md) and built into the
  design note: five kinds plus the forfeiture reversal and the wrong-Unit fix after closure,
  sub-slices 10a to 10h. Answer 6 checked against the earlier rules before use (no difference;
  docs/010). Follow-up points that do not block 10a are in Q-2026-10-06-37 (they block 10b, 10d,
  10e and 10g).
- Pre-code design written to the plan's 10a entry (read only; within the design note, DB-SETTLE-003
  and DB-SETTLE-005 as amended by owner answer 2).
- During the design note update a script matched an earlier "Sub-slices" heading and replaced far
  more of the plan than intended; the plan had no other uncommitted change, so it was restored
  from the last commit (`git restore ops/V1_056_PLAN.md`) and the edit was redone, limited to the
  slice 10 design note. No other file was affected.
- Read-only search of all backend tests for affected tests: the 26 head-revision assertions in 14
  modules; tests that name the two patched refusal functions (`test_final_settlement_closed_refusal_migration.py`
  checks their trigger names, order and grants; `test_final_settlement_credit_application_migration.py`
  their grants): unchanged, because CREATE OR REPLACE keeps the identity, owner and privileges and
  no earlier test writes a correction link; the whole-schema privilege check in
  `test_lease_enforcement_api_migration.py` (the new tables grant nothing); the forward-only catalog
  tests compare fixed revision pairs.

## Built

- Migration `20261101_97`: `app.settlement_corrections` (DB-SETTLE-003) and
  `app.settlement_correction_effects` (DB-SETTLE-005 with the approved links except
  `deposit_application_reversal_id`, which comes with its table in 10c-2), their append-only,
  validation and deferred checks; internal functions `app.begin_settlement_correction`,
  `app.link_settlement_correction_effect`, `app.settlement_correction_linked`,
  `app.settlement_correction_id`; relaxing patches of `app.refuse_closed_final_settlement_change`
  (8e-1) and `app.refuse_final_settlement_credit_application_reversal` (8e-2). Forward-only.
- No Python change (no variant writer and no route yet).
- Tests: `test_settlement_correction_migration.py` (7, last in `scripts/database-test.sh`); 7
  traceability entries appended; 26 head-revision assertions; docs/004 DB-SETTLE-003 and
  DB-SETTLE-005, docs/010, the plan, ops/V1_056_QUESTIONS.md.

Static checks, each in its own tool call: `ruff format` on the two new files (both reformatted);
`ruff check src tests` and the migration (two long lines in the new test, split); `ruff format`
on the test (unchanged); `ruff check` (clean); `ruff format --check src tests` (299 files already
formatted); `mypy` (one redundant cast in the new test, removed); `mypy` (no issues in 299 source
files); `ruff check` and `ruff format --check` again (clean).

Migration-only check before P1 (owner rule): the throwaway copy of `scripts/database-test.sh` in
the session scratchpad ran `alembic upgrade head` on a fresh container twice (before the tests were
written, and after `ruff format` changed the migration's layout); both reached `20261101_97`.

## Runs before review round 1

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U1 | backend unit, full | 3498 passed, 1722 skipped, 1 warning (Starlette) | first run of 10a | `V1-056-slice-10a-unit-test-run.txt` |
| P1 | PostgreSQL, full (`./scripts/database-test.sh`) | 1885 passed, 1 warning (Starlette) | first run of 10a | `V1-056-slice-10a-full-test-run.txt` |

No correction used.

## Round 1 (2026-10-06)

Both reviewers were fresh read-only subagents given the combined diff, the rule IDs, the takeover
file, the plan's 10a design and the owner answers; neither edited anything or ran a test.

### Independent review: 1 blocker, 3 should-fix, 6 notes

- B1: "the same transaction" (header time not earlier than `transaction_timestamp()`) was not
  exact under READ COMMITTED: a transaction that started before another stamped and committed its
  header saw that header as its own, so it could add effects to a committed correction, and on the
  Invoice UPDATE path (issue, or moving a draft onto the Lease) a record linked by the other
  transaction passed the 8e-1 refusal. Fixed: `app.begin_settlement_correction` stores the
  top-level transaction id (`pg_current_xact_id()`, the same inside an exception block) in the
  CONFIRMED decision's result; the effect check, `app.settlement_correction_linked` and the deferred
  check compare it with the current one. Choice: the decision result rather than a new header
  column, so DB-SETTLE-003 keeps its columns (docs/010 choice 3).
- S1: the "another Settlement" header case used an open Settlement, and the header's own closure
  and time bounds were not tested. Fixed: the second Settlement is closed; headers before the
  closure and later than the clock plus 5 seconds are refused with the check's message.
- S2: the "linked only to a committed correction" case never linked the reversal. Fixed: the
  docstring and the traceability note say "unlinked"; a new test links a no-Lease Invoice draft in
  a committed correction and shows that correcting it onto a charge of the closed Lease in a later
  transaction is refused (a conflict), while a draft linked by a correction confirmed in the same
  transaction moves.
- S3: the plan dropped the stale check and replay of the old 10a text. Fixed: both are in the
  notes for every variant writer.
- N1 link only records the writer itself writes, in the same call: fixed (writer notes).
- N2 snapshots: fixed (the test compares the Settlement row and the counts of its three snapshot
  tables).
- N3 the no-time-limit check read one function only: fixed (all eight functions: one `interval`,
  no `age(`).
- N4 the Settlement lookup cast the id to text: fixed (the payload value is checked as a uuid and
  cast).
- N5 the approver helper's docstring: fixed.
- N6 lost "Uses the 10c reversal records" in the plan, and owner words mixed with agent choices in
  docs/010 and the question file: fixed.

### Security review: 0 blockers, 1 should-fix, 6 notes

No application role can change a closed Settlement's obligations, pass the 8e-1 or 8e-2 refusal, or
touch the Settlement row or its snapshots after 10a (paths checked: direct writes by every role,
the eight new functions, creating and confirming a `SETTLEMENT_CORRECTION` draft, statement order,
savepoints and exception blocks, `SET CONSTRAINTS`, forged effect rows, another Settlement's
header, a committed link, records with no link, the Settlement row and snapshots, definer rights
and `search_path`, dynamic SQL, error text).

- S1: a linked record id lets any later statement of the same transaction through the refusals
  (for example `app.adjust_invoice` with a chosen id, or `app.issue_invoice` of a linked draft), so
  a future writer must not return with a linked record unwritten or in DRAFT. Fixed: the writer
  notes require every linked record to be written in its final state before the writer returns,
  checked at its end.
- N1 the time-based rule: fixed with B1.
- N2 the Invoice UPDATE path was untested: fixed (the new test).
- N3 `NOT linked(...)` would pass on NULL: fixed (`IS NOT TRUE` in both refusals; the function
  never returns NULL).
- N4 the database checks only the `financial.approve` reference and an active person: answered;
  the same split as every draft since slice 2; the writer notes say the service and the 11e route
  check the capability first.
- N5 as independent S2: fixed; the 8e-2 test also tries another Settlement's correction now.
- N6 "no role may read" ignores the backup role: fixed in docs/004 ("no application role").

## Runs after the round-1 fixes

Static checks, each in its own tool call: `ruff format` on the two edited files (both
reformatted), `ruff check` (one long line in the test, split; then clean), `ruff format --check
src tests` (299 files), `mypy` (no issues in 299 source files). Read-only search: since P1 only the
migration, the new test module, docs, traceability, the plan and this record changed. Migration-only
check before P2: reached `20261101_97`.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U2 | backend unit, full | 3498 passed, 1723 skipped, 1 warning (Starlette) | after the round-1 fixes | `V1-056-slice-10a-unit-test-run-2.txt` |
| P2 | PostgreSQL, full | 6 failed, 1880 passed, 3 warnings | after the round-1 fixes | `V1-056-slice-10a-full-test-run-2.txt` |
| P3 | PostgreSQL, full | 1886 passed, 2 warnings | after correction 1 of cause "uuid pattern braces in the migration f-string" | `V1-056-slice-10a-full-test-run-3.txt` |

P2: every failure was in the new module, with one cause: the uuid pattern added for N4
(`{8}`, `{4}`, `{12}`) sat inside the migration's Python f-string, so Python replaced the braces and
the stored pattern never matched; `app.begin_settlement_correction` refused every draft as "Final
Settlement was not found" (P0002). Correction 1 of 2 for that cause: the braces are doubled; a
throwaway container (outside the repo) applied the migrations and printed the stored pattern, which
matched a uuid. Static checks again, each in its own tool call (format unchanged, lint clean,
format check 299 files, `mypy` clean). U2 was not repeated: the change is inside a SQL string that
no unit test runs. The P2 and P3 warnings beyond Starlette are the known intermittent pydantic
`UnsupportedFieldAttributeWarning` in `test_credit_refund_api_migration.py` (slice 12 item).

## Round 2 (2026-10-06)

Fresh read-only reviewers again (the full diff, the round-1-to-2 diff, this record, the owner
answers); neither edited anything or ran a test.

### Independent review: 0 blockers, 1 should-fix, 4 notes

Every round-1 fix verified against the code: the transaction id is the top-level one inside
exception blocks and at commit; a result without it fails closed; the doubled braces; `IS NOT TRUE`;
removing any other check fails a test; bookkeeping.

- SF1: no test proves the blocker B1 fix: every "committed correction" case ran in a transaction
  that started after the other committed, which the round-1 rule refused too. Fixed: a new
  two-connection test starts two transactions, commits a correction from a third, and shows that
  neither earlier transaction can reuse the committed link to pass the 8e-1 refusal (P5S01) or add
  an effect to it (23514).
- N1 "exact" holds only within one cluster (a logical restore restarts the transaction counter):
  fixed with security S1 below.
- N2 the transaction id in the decision result is within docs/004 and readable by draft readers:
  answered; the 11e routes leave it out of responses (plan note); docs/004 DB-SETTLE-003 now says
  the deferred check needs the confirmation in the same transaction.
- N3 the header's own closed check and the uuid-format check had no direct test: fixed (a header
  for a draft of a still-open Settlement is refused at insert; a draft with a malformed Settlement
  id is not found).
- N4 leftover wording ("written in the same transaction", "no role may read or write"): fixed in
  the tests, docs/010, the plan and the traceability note.

### Security review: 0 blockers, 1 should-fix, 2 notes

Paths checked: every function that writes a draft decision (only the internal
`app.begin_settlement_correction` can write a CONFIRMED `SETTLEMENT_CORRECTION` decision or its
result), draft creation, draft reads, the same-transaction rule, `SET CONSTRAINTS` and exception
blocks, forged rows, another Settlement's correction, records with no link, the Settlement row and
snapshots, grants, definer rights and `search_path`, the migration f-strings, error text.

- S1: a logical restore into a new cluster restarts the transaction counter, so a stored
  transaction id can later belong to one new transaction (xid wraparound is not a concern: xid8
  carries the epoch). Fixed: the effect check, the link check and the deferred check also need
  the decision written after the current transaction started (`decided_at>=transaction_timestamp()`;
  `decided_at` is the clock time of the same transaction's decision).
- N1 draft reads return the transaction id: answered as independent N2 (11e note).
- N2 the database could refuse a commit while a linked Invoice is still DRAFT: answered; the first
  writer that links an Invoice (10b) adds that check with its own test (plan writer notes).

## Runs before round 3

Static checks, each in its own tool call: `ruff format` on the two edited files (unchanged),
`ruff check` (clean), `ruff format --check src tests` (299 files), `mypy` (no issues in 299 source
files). Read-only search: since P3 only the migration (three time bounds, docstring), the new test
module, docs, traceability, the plan and this record changed. Migration-only check before P4:
reached `20261101_97`.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U3 | backend unit, full | 3498 passed, 1724 skipped, 1 warning (Starlette) | standing rule before round 3 | `V1-056-slice-10a-unit-test-run-3.txt` |
| P4 | PostgreSQL, full | 1887 passed, 3 warnings | standing rule before round 3 | `V1-056-slice-10a-full-test-run-4.txt` |

The two P4 warnings beyond Starlette are the known intermittent pydantic
`UnsupportedFieldAttributeWarning` in `test_credit_refund_api_migration.py` (slice 12 item).

Round 2 has no blocker and 2 should-fix in total, so the standing rule allows one round 3.

## Round 3 (2026-10-06, standing round-3 rule)

### Independent review: 0 blockers, 0 should-fix, 4 notes

Every round-2 fix verified against the code: the `decided_at` bound in all three checks; under the
round-1 time-only rule both halves of the two-connection test fail, and both pass now; the
still-open header case and the malformed-id case each isolate their check; final sweep of the
owner's rules, tables, checks, the two relaxed refusals, grants, lock order (the same order as the
Settlement recorder and confirm), tests, docs, traceability, head-revision assertions and runs.

- N1 the `decided_at` bound has no test: answered; 10b, which rebuilds
  `app.settlement_correction_linked` for its new link, adds that test (plan writer notes); the
  check fails closed and only a logical restore could make it matter.
- N2 the reuse half of the two-connection test shows the refusal on the INSERT path, not the
  Invoice UPDATE path: answered; it still separates the two rules, and the effect half proves the
  fix directly (no change).
- N3 the plan and docs/004 DB-SETTLE-003 did not mention the round-2 bound, and two docs/004 lines
  were not wrapped: fixed.
- N4 one test docstring still said "written in the same transaction": fixed.

### Security review: 0 blockers, 0 should-fix, 2 notes

Paths checked: grants, definer rights and `search_path` (no application role has TEMPORARY on the
database), forged decisions (only the internal `app.begin_settlement_correction` writes a
CONFIRMED correction decision), forged headers and effects, committed and concurrent corrections,
statement order, savepoints and exception blocks, `SET CONSTRAINTS`, another Settlement's
correction, the Settlement row and snapshots, dynamic SQL in the migration, error text, routes and
logs. The round-2 bound is a `timestamptz` comparison (time zone does not matter) and a decision
written by `begin` in the same transaction always meets it.

- N1 the `decided_at` bound has no test: answered as independent N1.
- N2 a server clock stepped backwards between the transaction start and the confirmation refuses
  a legitimate correction (fails closed; a retry succeeds; the `occurred_at` bound behaves the
  same): answered; recorded here for the runbook (slice 12).

### Outcome

Round 3 has no blocker and no should-fix, so 10a is committed under the standing round-3 rule.
After round 3 only text changed: docs/004, the plan, this record, docs/010 and one test
docstring (re-checked by `ruff format --check`, `ruff check` and `mypy`, each in its own tool
call; no executable line changed). The committed migration and tests are exactly what U3 and P4
ran. Final runs: U3 backend unit 3498 passed; P4 full PostgreSQL 1887 passed. Corrections used:
uuid pattern braces in the migration f-string, 1 of 2. Every run output is small (at most about
140 KB) and committed; nothing was moved to `~/Development/prm-run-logs/`. Owner questions open:
Q-2026-10-06-37 (blocks 10b, 10d, 10e and 10g; not 10a).
