# V1-056 slice 12c review record: the Owner removes wrong sign-in tries older than 30 days

Built 2026-10-25 in the cloud session on branch `wip/slice-12c` after fe3131c (slice 12b).
Migration `20270217_205_prune_old_sign_in_tries` (head). Decision log DL-092 (owner answer (a) to
Q-2026-10-23-175).

## What was built

- The guard of `app.sign_in_wrong_tries`, `app.sign_in_waits` and `app.sign_in_try_clears`
  allows a DELETE only with `prm.sign_in_prune` on in the transaction and only of a row older
  than 30 days; UPDATE and TRUNCATE stay refused. No application role has a privilege on them.
- `app.prune_sign_in_wrong_tries(after, limit)` (no application role may run it), the command
  `python -m property_rental.sign_in_prune` (`make prune-sign-in-tries`,
  `sh scripts/local/prune-sign-in-tries.sh`), a README line (once a month).
- Indexes on the two foreign keys to the tries.

## Review round 1 (one read-only agent, independent and security)

- Blocker 1 (fixed, design): keeping the newest try of each username kept for ever the rows the
  owner wanted removed (a password typed as a username is always its digest's newest try; old
  plain digests too). Now every old try goes, and the race it guarded against (a correct sign-in
  clearing through a try being removed) is closed by the username lock of the sign-in functions,
  taken in digest order for a bounded batch of usernames; the command loops over batches.
- Blocker 2 (fixed, design): removing a username's only old clear could bring a covered try back
  into the count. A latest clear now stays while a try it covers stays; tests compare the counts
  before and after.
- Should-fix taken: indexes on the two foreign keys; docs say "with `prm.sign_in_prune` on" (the
  table owner can set it by hand; only the owner may delete at all). Nits: the traceability
  notes name this record. Not taken: the first test's totals depend on running before the guard
  test in the module's database (file order); no concurrency test of the prune against a
  sign-in; no catalog test of the guard's owner and bindings (CREATE OR REPLACE keeps them).

## Review round 2 (one read-only agent, independent and security)

- No blocker, no should-fix. Nits taken: the latest-clear rule no longer depends on timing (it
  stays while a covered try is recent or named by a wait); old waits are removed before any
  username lock; the function refuses to run above READ COMMITTED and the command sets READ
  COMMITTED; the command also reports a `RuntimeError` as a failed event with no detail; a test
  adds a recent try after a reset so the reset's clear must stay. A repeated flag line removed.
  Not taken: an index on `tried_at` (the prune is monthly and by hand). A due-date wording point
  belongs to slice 12b's known limits.
- No round 3: round 2 had no blocker and no should-fix (run rules).
- Runs: `tests/test_sign_in_prune_migration.py` + `tests/test_sign_in_wait_migration.py`
  19 passed on PostgreSQL; `tests/test_local_run_scripts.py` 12 passed; ruff format, ruff check
  and mypy clean (479 files).
