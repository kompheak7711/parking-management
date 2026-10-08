# V1-056 sub-slice 10c-2a-4 — Inspection supersede refused after closure: review record

Sub-slice: 10c-2a-4 (migration `20261108_104`). Base commit: 77812cd (the Q-2026-10-08-50 stop),
with the owner answers to Q-2026-10-08-50 and Q-2026-10-08-51 recorded in the working tree.
Committed as the 10c-2a-4 checkpoint after review round 2 (commit hash in ops/NOW.md).

Rule IDs: BR-MOVEOUT-006, BR-SETTLE-012, BR-SETTLE-013, DB-MOVEOUT-001; owner answer 2 to
Q-2026-10-07-44, owner answers to Q-2026-10-08-49 and Q-2026-10-08-50.

## Built

- Migration `20261108_104`: `app.move_out_inspection_record` and its insert trigger
  `app.validate_move_out_inspection_source` patched in place (exact-text patch of the stored
  definition, `CREATE OR REPLACE`; owner, SECURITY DEFINER, settings and grants kept): a supersede
  on a Lease whose Final Settlement is closed is refused (P5S01) after the Lease row lock, by
  reading the Settlement row `FOR SHARE`, before anything is written. An inspection that
  supersedes nothing is not checked.
- Service: `PostgresMoveOutInspectionService._error` maps P5S01 to a conflict.
- Tests: new module `test_inspection_supersede_after_closure_migration.py` (6 tests at P1, 7 after
  the owner answer to Q-51; last in `scripts/database-test.sh`); one unit test
  (`test_move_out_inspection.py`); the 10b test's set-up (owner answer to Q-49, accepted in Q-50);
  the 10c-2a-2 inspection test (owner exception, Q-50); 26 head-revision assertions in 14 modules;
  traceability 7 entries at P1, 8 at the end, and notes on the two changed tests.
- Docs: docs/002 BR-MOVEOUT-006 "Amended by" line; docs/004 inspection section; docs/010 (owner
  answers to Q-49 and Q-50, sub-slice entry, updated tests entry); plan design; run rule (exact-text
  edits for long documents).

## Runs

Static checks, each in its own tool call (`ruff format src tests`, `ruff check src tests`,
`ruff format --check src tests`, `mypy`): clean. Migration-only check (a throwaway copy of
`scripts/database-test.sh` in the session scratchpad running `uv run alembic upgrade head`)
reached `20261108_104 (head)`. Read-only search of all backend tests: the inspection supersedes in
tests are in `test_move_out_inspection_migration.py` (three tests),
`test_one_time_charges_migration.py` and `test_move_out_inspection_consumers_migration.py` (no
Final Settlement, READ COMMITTED, unaffected; the first file was missing from this list until
review round 2), the 10b test and the 10c-2a-2 test (both changed); no other
test reads the two patched functions' text at head (`test_move_out_inspection_migration.py`
checks their grants, unchanged, and compares migrations 59 and 60 only); the head-revision
modules; the unit inspection test; traceability.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U1 | backend unit, full | 3590 passed, 1774 skipped, 1 warning (Starlette) | first run of 10c-2a-4 | `V1-056-slice-10c-2a-4-unit-test-run.txt` |
| P1 | PostgreSQL, full (under `caffeinate -dims`) | 1937 passed, 2 warnings (Starlette; pydantic alias) | first run of 10c-2a-4 | `V1-056-slice-10c-2a-4-full-test-run.txt` |

Before U1 a first attempt failed at the shell redirect (a relative output path resolved before
`cd backend`); pytest did not start, so it is not a run.

## Review round 1 (2026-10-08; fresh read-only subagents, given the diff, the rule IDs, the owner answers and the takeover file)

Security: 0 blockers, 2 should-fix, 1 note. Independent: 0 blockers, 1 should-fix, 3 notes.

- SF-1 (both reviewers, verified; OPEN, Q-2026-10-08-51): the claim "at REPEATABLE READ the row
  lock fails with 40001" holds only when the Settlement row is in the caller's snapshot. A
  REPEATABLE READ or SERIALIZABLE transaction whose snapshot predates the Settlement start sees
  no Settlement row, so `FOR SHARE` returns nothing, the trigger (same snapshot) passes too, and
  the Lease row lock raises nothing (the start and the confirm lock the Lease row but never
  update it). A supersede after closure then commits. Only a direct `prm_financial` session can
  do this: the service always writes at READ COMMITTED. The fix both reviewers name (refuse a
  supersede outside READ COMMITTED, as the confirm and the correction confirms do) also refuses
  such a supersede before closure, a further tightening, so the owner decides.
- Security SF-2 (fixed): `blocked_by` accepts any lock on `app.leases`, which every inspection
  command holds (`app.lease_enforcement_scope`), and both holders also hold the Settlement row; so
  the two lock-wait tests would still pass if the command waited on the Settlement row (refusal
  moved before the Lease lock). New helper `blocked_on_lease_row` (plan module): `blocked_by`
  plus a tuple lock on an `app.leases` row and none on an `app.final_settlements` row; used by the
  10c-2a-2 inspection test and the new confirm-race test. Independent note C is the same point
  (fixed by this helper; the removal of only the command's copy of the refusal stays caught by
  the catalog test, because the trigger then refuses the same insert before anything is
  written).
- Note A (both; fixed): "the Settlement confirm and every correction lock the Lease row FOR UPDATE
  first" and "the 8e-1 refusal's order" were wrong (the extra charge takes the Lease `FOR SHARE`;
  the charge reduction takes no Lease lock; 8e-1 locks no Lease). Correctness holds because the
  confirm is the only writer of `closed_at` and locks the Lease row `FOR UPDATE` first. Wording
  fixed in the migration docstring and comment, docs/004 and docs/010. The Q-50 text in the
  questions file is a dated record and is left as written.
- Independent note B (fixed): the replay of a supersede committed before closure was claimed but
  not tested; test 2 now replays it after closure (201, the same body, nothing written).
- Owner's checks (independent reviewer): every supersede after closure is refused before any write
  at READ COMMITTED (except SF-1); no reader assumes one inspection chain per Lease (confirmed,
  per migration); the 10b test is not weakened (one set-up hunk; name, docstring and every
  assertion as at HEAD; the "not current" refusal still meaningful); the 10c-2a-2 test still
  proves the lock (now stricter), then the refusal, the line stays pet damage and is paid from the
  Pet Deposit to the cent; the docs/010 claim about the step's re-check is accurate apart from
  SF-1; no deadlock cycle (every writer that holds the Settlement row in a conflicting mode takes
  the Lease row first).
- After the fixes: static checks clean, each in its own call. No run yet (stopped for Q-51).

## Owner answer to Q-2026-10-08-51 (2026-10-08) and the SF-1 fix

Option (a), tightening approved (docs/010, questions file). Built: in both patched functions a
supersede outside READ COMMITTED is refused with 55000 ("A move-out inspection is superseded only
at READ COMMITTED"), checked before the Settlement read, before and after closure; an inspection
that supersedes nothing is not affected; the service mapping is unchanged (it always writes at
READ COMMITTED). Tests: `test_a_supersede_at_repeatable_read_cannot_miss_a_closure` now covers the
gap itself (a REPEATABLE READ snapshot taken right before the Settlement starts, the Settlement
started and closed, the snapshot still sees no Settlement row, the supersede refused with 55000,
nothing written); new `test_a_supersede_outside_read_committed_is_refused_also_before_closure`
(REPEATABLE READ and SERIALIZABLE refused, a non-superseding inspection at REPEATABLE READ
accepted, the same supersede at READ COMMITTED accepted); the trigger test refuses a direct
superseding row at REPEATABLE READ; the catalog test checks one `'55000'` per body, before the
Settlement read. The design note, docs/004, docs/010 choice (1), the migration docstring and the
traceability notes no longer claim 40001. A read-only search found no existing test that
supersedes outside READ COMMITTED (the service path forces READ COMMITTED; the direct calls in
`test_move_out_inspection_migration.py` run at the default READ COMMITTED), so no other
expectation changed.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U2 | backend unit, full | 3590 passed, 1775 skipped, 1 warning (Starlette) | review round 1 fixes and the owner answer to Q-51 | `V1-056-slice-10c-2a-4-unit-test-run-2.txt` |
| P2 | PostgreSQL, full (under `caffeinate -dims`) | 1938 passed, 2 warnings (Starlette; pydantic alias) | review round 1 fixes and the owner answer to Q-51 | `V1-056-slice-10c-2a-4-full-test-run-2.txt` |

Before U2 and P2: static checks clean, each in its own call (one import order slip in the new
module, fixed by hand); migration-only check reached `20261108_104 (head)`.

## Review round 2 (2026-10-08; new fresh read-only subagents, given the full diff, the rule IDs, the owner answers, the takeover file and this record)

Independent: 0 blockers, 0 should-fix, 3 notes. Security: 0 blockers, 0 should-fix, 3 notes. No
should-fix, so no round 3; 10c-2a-4 is committed after the text fixes below. No test reads the
changed text (docs/010, the plan, ops/NOW.md, this record), so no run after them.

- Security found no remaining path: at READ COMMITTED every statement of the command and the
  trigger takes a fresh snapshot (also from a STABLE caller or a cursor); the isolation level
  cannot change after the first snapshot; the Settlement start and confirm take the Lease row
  `FOR UPDATE` before they insert or close the Settlement; no other writer of
  `app.move_out_inspections`; no grant on the table; every refusal before the first write. No new
  lock cycle; privileges and settings kept; no data in messages. Each check is caught by a test if
  removed or moved (the isolation check by the gap test, the before-closure test and the trigger
  test; the P5S01 copies by the trigger test and the catalog counts; a read moved before the Lease
  lock by `blocked_on_lease_row` and the catalog order check).
- Independent owner checks: every requirement of Q-49, Q-50 and Q-51 met; the gap test takes its
  snapshot before the Settlement row exists and fails if the READ COMMITTED check is removed; no
  existing test supersedes outside READ COMMITTED; the 10b test not weakened (name, docstring and
  every assertion byte-identical; set-up only); the 10c-2a-2 test proves the lock more strictly
  (a waiter holds the contended row's tuple lock while it sleeps, so a wait on the Settlement row
  would make `blocked_on_lease_row` return False); no 40001 claim left except quotations of the
  corrected one.
- Notes and answers:
  - Independent 1 (fixed, text): ops/NOW.md and the plan still showed the Q-51 stop; the plan has
    an "As built after the owner answer to Q-2026-10-08-51" line and NOW.md the commit line.
  - Independent 2 (fixed, text): this record's counts and the first search list (above).
  - Independent 3 and security 1 (answered, text; carried into 10c-2a-5): since the 10c-2a-2 test
    change no test shows the step's own pet-damage re-check refusing through the step; the same
    check is still tested where the recorder calls it, and the Deposit application trigger is a
    third guard. The owner kept the re-check as a second guard (Q-50) and asked only for the
    docs/010 statement; docs/010 now says no test reaches it through the step, and the plan's
    10c-2a-5 entry carries a test through the step once a classification can change again. Not
    added here because a new test needs another full run and review for a path no command can
    reach today.
  - Security 2 (recorded, not changed): the inspection service's lock timeout is 3 seconds while
    `blocked_by` polls up to 10; in the two lock-wait tests a host slower than 3 seconds between
    the wait check and the holder's commit or rollback would give 55P03 (Unavailable) instead of
    P5S01: a false failure, never a false pass. The pattern existed before this sub-slice.
  - Security 3 (no change): both copies of the refusal raise the same SQLSTATE and message, so
    the behaviour tests cannot tell which refused; the command copy's place is pinned by the
    catalog order check; no security impact, because the trigger copy runs after its own Lease row
    lock before the row is stored.
  - Independent minor: the least-privilege traceability note does not mention the 55000 order
    assertion; not inaccurate; no change.
