# V1-056 sub-slice 10i-2 — an increase counts for the unpaid-Initial ground only five days after its record — review record

Sub-slice: 10i-2, the second part of the Q-112 times sub-slice (owner answer (b) to
Q-2026-10-19-138). Migration `20270115_172` (one new internal function, one exact-text
replacement checked to match once). Base commit: the 10i-1 commit. Built on 2026-10-20 in the
same session as 10i-1. Not pushed. The commit hash is in `git log` (this record is part of that
commit).

## Built

- New internal `app.deposit_ground_required_total_at(deposit, as_of)` (SQL, STABLE, SECURITY
  DEFINER, `search_path=pg_catalog`; EXECUTE revoked from PUBLIC and the runtime, financial and
  bootstrap roles): the first amount, every DECREASE recorded at or before the time, and every
  INCREASE recorded at or before the time whose Asia/Phnom_Penh business date plus five days is
  before the time's business date.
- `app.require_lease_termination_context`: the BR-LEASE-005 Security Deposit branch compares the
  held value with the new total. Every other reader keeps `app.deposit_required_total_at`.

## Committed tests changed

1. `test_deposit_required_total_readers_migration.py::test_an_increase_counts_for_the_ground_from_its_record_time`
   renamed under the standing rule `test_an_increase_counts_for_the_ground_only_five_days_after_its_record`
   (owner answer (b) changes its result): the increase recorded now no longer counts for a
   termination now; the last termination is refused (the ground reads 50,000). Traceability
   entry updated (id and note).
2. Text only: that module's docstring and the docstring of
   `test_a_termination_dated_before_a_decrease_reads_the_earlier_total_known_limit`.
3. The 27 head-revision strings in 15 modules (revision strings only; a script checked each
   file's count).

## New tests

Module `test_deposit_increase_ground_delay_migration.py` (last in `scripts/database-test.sh`):
`test_an_increase_counts_only_after_its_business_date_plus_five_days`,
`test_an_increase_before_lease_start_plus_five_days_gets_its_own_five_days`,
`test_a_decrease_counts_at_once_also_beside_an_uncounted_increase`,
`test_the_increase_ground_delay_migration_is_least_privilege_and_forward_only`. The past-dated
increases are written by hand (the writer stamps its own clock time since 10i-1), with the
comment the set-up rule asks for. Traceability: 4 entries appended; the first 1,598 entries
untouched.

## Reviews

Round 1:
- Independent: clean. Notes: a docs/002 line too long (rewrapped); docs/010 entries and this
  record still to be written (done); a run crossing midnight in Phnom Penh between steps could
  fail a test (milliseconds; the same as other suites); the ground total can fall below the first
  amount, even below zero, for five days (only "not met"); no test of an increase recorded before
  Lease Start (the ground's unchanged Start rule covers it); the least-privilege test checks
  EXECUTE but not the helper's settings.
- Security: one should-fix, a gap that existed before 10i-2 and is outside the owner's answer: a
  Security Deposit created after signing (`app.create_lease_security_deposit`, any time, any first
  amount) counts for the ground at once, the same harm as Q-138 through a create command. Not
  built (a business rule the answer does not cover): written as Q-2026-10-20-148
  (recommendation (a): its first amount counts only after its creation date plus five days),
  added to the slice 12 list. Notes: the ground reads Deposits with no filter on their existence
  at an explicit earlier time (the Q-112 point 2 limit); the decrease-beside-increase reading is
  safe.

Round 2 (one reviewer with both the independent and the security checklist; only text had
changed since round 1): one should-fix, the wording of Q-148 option (a) suggested that some
walk-in Deposits are made with the signing (they are all created after signing); fixed, with the
reviewer's suggested wording and the note that neither command has an HTTP route yet. Notes: this
record; NULL handling fails closed.

Round 3 (the round 3 text rule: the only round 2 should-fix was a text fix): clean (independent
and security checklist). Notes: this line and NOW.md were still to be written (done); the
least-privilege test checks the helper's EXECUTE rights, not its definer flag or settings (set
correctly by the migration).

## Runs (logs in ~/Development/prm-run-logs/, prefix `v1-056-10i-2-`)

| Run | Result | Cause |
|---|---|---|
| FF1, I1, FC1, L1, Y1 | pass | checks |
| U1 | 3,869 passed | unit suite |
| M1 | pass | migration-only check |
| T1 | 468 passed | targeted, 28 modules |
| P1 | 2,430 passed | full PostgreSQL run |

No failed check or run; no correction. After P1 only text changed (the question, docs, plan,
this record, NOW.md), so U1 and P1 stand for the runs before round 3.
