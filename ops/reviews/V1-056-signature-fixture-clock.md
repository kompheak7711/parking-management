# V1-056 signature fixture clock — Lease signing times from the database clock: review record

Sub-slice: the signature fixture clock (owner instruction of 2026-10-14; test set-up only). Base
commit: 860729c (10e-3e). Built on 2026-10-14. Not pushed. No migration.

Rule IDs: TEST-019 (tests must not depend on the machine's current time). Owner instruction:
find the cause of the `Signature evidence is invalid` failures read-only; if it is a time
difference between the Mac and the database, change only the test set-up so it no longer depends
on the two clocks agreeing; do not loosen the app's own signature check; mark the related slice 12
item done. Plan: ops/V1_056_PLAN.md ("Signature fixture clock" bullet before 10h; the slice 12
item marked DONE).

## Cause (read-only)

- `app.record_lease_signature` and `app.sign_lease` (migration `20260826_24`, lines 286 and 408)
  refuse `p_signed_at > statement_timestamp()` with no tolerance (`Signature evidence is invalid`,
  `Signing evidence is invalid`, 22023). Further checks compare the same time with the database
  clock: a signer's `added_at <= p_signed_at` (line 304), every signer's `signed_at <= p_signed_at`
  (line 448), a termination's `p_occurred_at` not before the Lease's `signed_at` and not after the
  statement time (lines 562 and 563).
- The fixtures took the signing time from the host clock (`datetime.now(UTC)`: the default of
  `signature_command`, and every `LeaseSignCommand` and HTTP signing body). The database runs in
  the Docker VM, whose clock can lag the host clock. The slack is only the time between the
  fixture's reading and the database statement (the service opens a new connection first), a few
  milliseconds, so a lag that small fails the fixture, far below the about 80 ms resolution of the
  K1 check (`docker run ... date` between two Mac readings). So the clocks looked in step
  afterwards.
- Run logs: every saved failure is `Signature evidence is invalid` in `app.record_lease_signature`
  (10e-3d-1 P4: 1; 10e-3d-2b-1a P3: 1; 10e-3e P3: 13). In 10e-3e P3 the 13 failures are one
  consecutive stretch of signing tests at the end of a 16-minute run, and the next signing tests
  passed: a drift that grew, then a resync. The independent reviewer found no other cause (the
  other branches of the check cannot fire: the time is never null and the reason is a fixed
  trimmed text).

## Built

- `backend/tests/test_lease_lifecycle_migration.py`: new helper `database_now()` (reads
  `SELECT clock_timestamp()` through the runtime-role URL, as `database_now()` in
  `test_utility_baseline_migration.py` does through the financial URL); `signature_command`'s
  default uses it; every signing time in the module uses it; the termination time too (it may not
  be before the signing time, which now comes from the database); the invalid future case is the
  database time plus one day; the concurrent signing test reads the time once before its threads
  start (round 1 security note N2).
- `test_lease_api_migration.py`, `test_lease_deposit_forfeiture_migration.py`,
  `test_lease_end_date_month_end_migration.py`, `test_lease_signing_reservation_migration.py`,
  `test_settlement_real_path_migration.py`, `test_unpaid_initial_termination_migration.py`: each
  signing time from `database_now()`; unused `UTC` and `datetime` imports removed.
- 22 host-clock readings replaced in the seven files; none left there. No assertion, expectation,
  test name or traceability entry changed. No app code, migration, grant or check changed.
- Read-only search: 54 test modules import the changed helpers directly or through other test
  modules (of 128 database test modules); the full PostgreSQL run covers them.
- Docs: ops/V1_056_PLAN.md (sub-slice bullet, order of 2026-10-14, slice 12 item marked DONE, new
  slice 12 item), docs/010, ops/V1_056_QUESTIONS.md (the owner answers to Q-2026-10-14-109 and the
  10e-3e report, recorded first in this session).

## Runs

Static checks each in its own call, formatter first. Outputs in `~/Development/prm-run-logs/`
(`V1-056-signature-clock-*`); every targeted and full run under `caffeinate -dims`. No correction
was needed (no check or run failed).

| Run | Kind | Result | Cause |
|---|---|---|---|
| — | formatter, format check, lint, `mypy` | clean | first |
| T1 | PostgreSQL targeted: the seven changed modules | 47 passed | first |
| U1 | backend unit, full | 3802 passed, 1987 skipped, 1 known warning | first |
| M1 | migration-only check | passed (head `20261207_133`) | before P1 |
| P1 | PostgreSQL full | 2151 passed, 2 known warnings (Starlette; pydantic `UnsupportedFieldAttributeWarning` once) | first |
| — | formatter, format check, lint, `mypy` | clean | round 1 fixes |
| T2 | PostgreSQL targeted: lifecycle module | 6 passed | round 1 fix (N2) |
| U2 | backend unit, full | 3802 passed, 1987 skipped, 1 known warning | round 1 fix |
| M2 | migration-only check | passed | before P2 |
| P2 | PostgreSQL full | 2151 passed, 2 known warnings (Starlette; pydantic `UnsupportedFieldAttributeWarning` once) | round 1 fix (a test file changed after P1) |

No `Signature evidence is invalid` failure in any run of this sub-slice.

## Review round 1 (fresh read-only subagents, during P1; told to write no file anywhere and run nothing)

Independent: 0 blockers, 1 should-fix, 5 notes.
- Cause confirmed; no other plausible cause. The change also removes two hidden failures in the
  other direction (host clock behind the database): the co-signer's `added_at <= p_signed_at`
  check (55000) and the `ORDER BY occurred_at` assertion of the HTTP test.
- Coverage: no missed site; no other database test builds a signing time from the host clock;
  termination times after signing already come from the database clock. No new dependence in the
  other direction (termination, Invoice `signer.signed_at <= issued_at` with a fixed `issued_at`,
  billing cutoff on the database clock, date-only checks).
- No weakening: the refusal cases are kept and measured from the database clock; the month-end
  test's expected cause is now reached reliably.
- Should-fix (text): mark the slice 12 item done, a docs/010 note and this record. Fixed.
- Notes: `reservation_business_date` still reads the host clock for the business date (only
  within milliseconds of midnight in Asia/Phnom_Penh; not the signature check): new slice 12 item;
  `db_now(url)` in the unpaid-Initial module is a similar helper (reuse optional; one helper is used
  everywhere instead); the run rule "Signature tests and the clock" may be revisited by the owner
  after this lands; the only remaining risk is the VM clock stepping back between the read and the
  statement.

Security: 0 blockers, 0 should-fix, 3 notes.
- No app code, migration or check changed; the signature and termination checks stand at
  migration 24 lines 286, 408 and 563; no secret, no env or untracked file; the helper runs one
  fixed query as the runtime role and prints nothing.
- N1: a failed connection's long traceback can show the connection string (a suite-wide pattern,
  already on the slice 12 list from 10c-3b-2). N2: the concurrent test's time read before
  `barrier.wait()` could leave the other thread waiting forever if it failed (`Barrier(2)` has no
  timeout); fixed: the time is read once before the threads start. N3: the helper reads the database
  named by `APP_DATABASE_URL`; the throwaway-database fixtures switch that variable to their
  database (independent review item 6), so it is the same server and database.

## Review round 2 (one fresh read-only subagent doing the independent and the security checklist, during P2; told to write no file anywhere and run nothing)

0 blockers, 0 should-fix, 5 notes. It verified the round 1 fix (the concurrent test reads the time
in the main thread before the executor starts; nothing in `sign()` runs before `barrier.wait()`;
the race and its assertions are unchanged; the time is read after both signatures), compared every
changed test with HEAD (exactly 22 host-clock readings removed, 15 in the lifecycle module; only the
helper, the concurrent-test read and imports otherwise; no assertion, expectation, refused case or
test name changed), and confirmed every factual claim of the plan bullet, docs/010 and this record
against the code and the run logs (the 22 readings, 54 of 128 modules, migration 24 lines 286, 304,
408, 448, 562 and 563, neither function redefined later, the failure counts, the 13 consecutive
failures, the K1 window, the run results). Security clean: only seven test files and text files
changed, no secret, connection string or personal data, the record the only untracked file.
- N1: this record lacked P2 and round 2 (added). N2: the docs line left out
  ops/V1_056_QUESTIONS.md (added). N3: docs/010 read as if the termination reading were in addition
  to the 22 (fixed: 21 signing readings and 1 termination reading). N4: the questions summary of the
  10e-3e answers leaves out the pending rename, which is already recorded there (Q-2026-10-13-105)
  and in docs/010 (no change). N5: the new slice 12 item named only `signed_with_initial` and
  assumed a lag of milliseconds (fixed: all users named; the window is the clock lag, which the K1
  checks bound only to some tenths of a second).
