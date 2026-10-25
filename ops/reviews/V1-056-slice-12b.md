# V1-056 slice 12b review record: the scheduled worker bills a late Utility period

Built 2026-10-25 in the cloud session on branch `wip/slice-12` after 434da58 (slice 12a).
Migration `20270216_204_late_utility_run` (head). Decision log DL-091 (DL-071 answer 18).

## What was built

- A late Utility run: a successor of the last SUCCEEDED Utility run of the same dates, started
  only by the scheduled worker, with a logical key `utilities-late/start/end/day/run id` that
  names the run it continues. `app.protect_billing_run_history`,
  `app.snapshot_billing_run_eligible_sources`, `app.start_scheduled_billing_run` and
  `app.record_scheduled_utility_item` are patched by exact text.
- `app.scheduled_late_utility_candidates` (new, `prm_financial` only): the late run the same
  worker left RUNNING (with its key), and the dates of each finalized, responsible period with no
  Invoice line that no run of its dates ever snapshotted. A late run snapshots exactly those
  periods.
- `ScheduledBillingWorker.run_once` runs late candidates after the ordinary runs within the same
  bound; a failed late run is reported (`late_utility:error:`) and the charge pass still runs.
- Due Date of a late Invoice (decided by Claude under the owner's 2026-10-23 22:30 rule): the
  later of the on-time Due Date and the issue date plus the Property's configured days.

## Review round 1 (one read-only agent)

- Blocker B1 (fixed, design): a fresh snapshot took every finalized period of the dates, so a
  period skipped as `NOT_MOVED_IN` was billed by the worker after the move-in. Now only periods
  no run of the dates ever snapshotted.
- Blocker B2 (fixed, design): a period whose Invoice was voided was tried again, hit the UNIQUE
  Invoice line and kept the late run RUNNING forever.
- Should-fix taken: S1 a failed late run no longer skips the charge pass; S2 only the scheduled
  worker starts a late run (22023 for an API call or a Rent run); S3 docs corrected; S4 tests
  added (move-in after a skip, API refusal, failed late run in the worker). Nits: N2 key built
  with `to_char`. Not taken: N4 (the on-time expression is written twice), N6 (see Known limits).

## Review round 2 (one read-only agent)

- Blocker B1 (fixed, design): a period billed by the catch-up command (and later voided), or
  billed through a Utility case, was still snapshotted and errored on the UNIQUE line. The late
  snapshot now uses the candidate predicate: no Invoice line, responsible Lease, never
  snapshotted.
- Should-fix taken: S1 a second late period of the same dates on the same day replayed a no-op
  run until midnight (the key now names the run it continues); S2 the snapshot and the
  candidates disagreed on responsibility (same predicate now); S3 tests check the sqlstate.
  Nits: N1 `BillingRunNotFound` caught; N3 and N4 documented in docs/004.

## Known limits (recorded, not built)

- An ordinary Utility run whose business date is after the on-time Due Date (every period of
  its dates finalized late, no earlier run) records an error and is retried each pass
  (pre-existing; round 1 N6). Fixing it changes a Due Date rule for ordinary runs, so it is left
  for the owner.
- No real-PostgreSQL test drives the worker loop through the candidate function, and the
  on-time Due Date branch of a late Invoice is not covered by a database test (it needs
  configured days of 4 or fewer on the shared test Property).

## Review round 3 (one read-only agent)

No blocker. The candidate and snapshot predicates match column by column (the snapshot can only
hold more, never less); the key fits 200 characters and the Python pattern; the grants hold.

- Should-fix taken: S-A a late run resumed on a later day issued an Invoice already overdue (the
  Due Date was counted from the run's business date); it now counts from the Property's date
  when the Invoice is issued. A small code change, so it was checked by its own targeted run.
- Nits taken: N-2 the candidates require the run they continue to be dated on or before today;
  N-5 the worker unit test uses the real key format.
- Not taken (recorded): N-1 the start function does not check the key's day or run id (only the
  worker starts late runs, under the per-dates lock); N-3 if staff catch-up bill and then void a
  period while a late run that holds it is stopped on an error, that run errors on every pass
  (UNIQUE Invoice line) and holds back the late runs of its dates until it is fixed by hand;
  N-4 late runs are recognised by the key prefix (no such key existed before this migration);
  `ValueError` from a command is not caught by the worker (nothing reaches it).
