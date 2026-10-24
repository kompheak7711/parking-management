# V1-059 part A — backups, restore test, alerts, health status and logs — review record

Built on 2026-10-24 in a cloud session, from `implementation/foundation` at 3950b87 (login L5),
on the work branch `claude/project-thread-42lf25`. Scope given by the owner's request ("start
V1-059 now") and the coordinator's split: DL-071 answers 1 to 8 and 17 only. No migration, and
no change to Invoice, Receipt, Refund, Customer or Meter code (those are part B, after V1-056
slices 11 and 12). Nothing ran on the office computer or on real data.

## Built

- `backup_encryption.py`: AES-256-GCM files with the `cryptography` library (random 12-byte
  nonce per file; header and nonce authenticated; the opened file appears only after the tag
  check); the key file must be private and hold a 32-byte base64 key.
- `backup_retention.py`: hourly 2 days, daily 30 days, monthly 12 months; the first good backup
  of a Phnom Penh day and month becomes the daily and monthly copy; the newest good backup is
  never deleted.
- `backup_job.py` (`property-rental-backup run | offhost-copy | restore-test | verify`):
  `pg_dump --snapshot` on one exported snapshot with the row count of every table, checked with
  `pg_restore --list`, sealed, opened again and compared, stored with a DEPLOY-042 manifest;
  off-host copy checked by SHA-256 and refused without the drive's `PRM-OFFHOST-DRIVE` marker;
  restore test only into an empty database named `prm_restore_test...`, comparing the schema
  revision and every table's row count; status files for the health page.
- `operations_status.py`, `operations_config.py`, `operations_check.py`
  (`property-rental-ops-check run | record-migration`), `telegram_alerts.py`: the warning rules
  shared by the health page and the Telegram alerts (NEW, STILL every 12 hours, FIXED; an
  undelivered message tried again at most once an hour; FIXED kept until delivered).
- `operations_status_api.py`: `GET /api/v1/operations/status` with `operations.status.read`
  (DL-081 Q-2026-10-21-158 (a)); setting `APP_OPERATIONS_STATUS_DIRECTORY`.
- `log_retention.py` (`property-rental-log-retention`): operational log files older than 90 days.
- `config/deployment/production-operations.json`, the two Telegram placeholder examples,
  `config/deployment/host/` (systemd timers and services, journal 90 days, Docker logs to the
  journal); `scripts/validate-deployment-config.py` `check_operations` (remote access off, the
  outbound list exactly `api.telegram.org`, backup times and retention, 92-day restore test,
  90-day logs, Owner and Manager recipients, secret files only, no Telegram token committed).
- `scripts/backup-restore-check.sh`: the whole path on a throwaway PostgreSQL 17.6.
- `docs/V1_059_OPERATIONS_RUNBOOK.md`; "Built in V1-059 part A" notes in docs/009 (DEPLOY-015,
  016, 043, 045, 051, 052) and docs/005 (API-081).
- Frontend dev dependencies: `vite` 7.3.6 to 7.3.7, `vitest` 4.1.11 to 4.1.12, `source-map-js`
  1.2.1 to 1.2.2 (lockfile; with `chai` 6.3.0 and `tinyrainbow` 3.2.0): `npm audit` 0. The
  `braces` advisory GHSA-vfj7-8cjw-p6xm of ops/NOW.md 2026-10-03 is no longer reported by
  `npm audit` for the locked `braces` 3.0.3, so `typescript-eslint` stays at 8.44.1 and its 35
  lint errors are not needed. npm 10.9.4 failed with an arborist error (`edgesOut`), so the
  lockfile was written with `npx npm@11.6.2`.

## Decided by Claude under the owner's 2026-10-23 22:30 rule (no money, no Customer data)

1. Office computer examples assume Linux with systemd (OOD-DEPLOY-002 stays open).
2. Thresholds: no good backup in 2 hours; daily off-host copy 50 hours; weekly 8 days; restore
   test 92 days; free disk under 10 percent or 5 GB; certificate within 21 days; check older than
   15 minutes; STILL every 12 hours; retry once an hour.
3. Off-host retention: daily copies 30 days, weekly copies about 12 months, never the newest.
4. Secret files on the host in `/etc/prm/secrets`, shown to the jobs at `/run/secrets`.
5. No decision log number yet: the V1-056 thread also adds DL entries; the merge gives this
   work its DL number.

## Review round 1 (one independent agent, read-only, correctness and security)

- No blocker.
- Should-fix, all done: (1) off-host copy could "succeed" onto an empty mount folder: now needs
  the drive marker; (2) the backend could not read the status files under the jobs' `0077`
  umask: files `0640` by `fchmod`, folder `2750`, group shared with the container (runbook 2);
  (3) one broken chat sent a message every 5 minutes: retry at most once an hour; (4) a FIXED
  message was lost when its delivery failed: kept until delivered, and NEW is used until a
  message about the warning was delivered; (5) `/run/secrets` is emptied at restart: host files
  in `/etc/prm/secrets`, bound read-only at `/run/secrets`; (6) an unsealed dump could survive a
  crash: leftover work folders removed under the lock before each step; (7) the restore log
  would be deleted by the 90-day log cleaning: moved to `/var/lib/prm/restore-tests.txt`.
- Notes done: restore test has its own lock and work folder (the hourly backup is never skipped
  for it); tool error output keeps only the tool's own lines (a CONTEXT line can quote a row);
  any unexpected error records `unexpected_error`; the restore-test interval is fixed at 92 days
  in the validator so the page and the alerts agree; orphan sealed or partial files older than a
  day are removed; the token scan reads binary files safely; the off-host check drops cached
  pages before reading the copy back.
- Notes left: the restore-test safety check is the database name (enough to keep the live `prm`
  database safe); daily and monthly copies are hard links of the hourly file (a periodic
  `verify` of the newest copy is a later improvement); `retention` and `interval_minutes` in the
  configuration are checked by the validator but the code uses the same fixed DL-071 values;
  the weekly copy is manual by design; "a restore test before every release" becomes a V1-060
  release-gate line (runbook section 9).

## Runs (logs in ~/prm-run-logs/ of the cloud container)

| Run | Result |
|---|---|
| New unit tests (9 modules) after the review fixes | 101 passed with the deployment and route inventory tests |
| B1 `scripts/backup-restore-check.sh` (before review) | passed: 2 backups, verify, off-host copy, restore test (181 tables, 79 rows), changed file refused |
| B2 same, after the review fixes | passed |
| F1 frontend, during the backend run | 1 failed (TEST-FE-258 focus after a command, timing), 1,607 passed |
| F2 frontend, during the backend run | 1 failed (TEST-FE-420 5-second timeout), 1,607 passed |
| F3 frontend, run alone | 1,608 passed |
| Frontend lint, typecheck, format, build | clean |
| Backend ruff check, ruff format, mypy (434 files) | clean |
| `make deployment-config-check` | valid |
| U2 full backend unit run (after the review fixes) | 3 failed, 4,026 passed, 2,509 skipped: three guard tests that list new names on purpose (the dotted-label list, the OpenAPI route inventory, the traceability manifest) |
| Guard fixes | the new log events, configuration field names and work file names added to `NON_CAPABILITY_LABELS` in `test_access_control.py` (its comment says a new label is added there); `/api/v1/operations/status` added to the expected operations of `test_initial_owner_bootstrap_cli.py`; 42 entries appended to `ops/traceability.json` (append only) |
| T1 targeted run after the last fix (the 9 new modules, the three guard modules, deployment, route inventory, health) | 182 passed |
| B3 `scripts/backup-restore-check.sh` after the last code change | passed |

F1 and F2 failed only under CPU load from the parallel backend run, each a different test, and
both pass alone: TEST-FE-258 and TEST-FE-420 join TEST-FE-087, TEST-FE-128 and TEST-FE-488 on
the V1-060 flaky list (DL-071 answer 13: fixed, not rerun, before the release candidate).
No PostgreSQL test file changed (no migration, no database code); the backup path against
PostgreSQL 17.6 is covered by the backup check script.
