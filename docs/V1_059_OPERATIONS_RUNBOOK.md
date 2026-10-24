# V1-059 Operations Runbook — backups, restore tests, alerts and logs

**Authority:** DL-071 answers 1 to 8 and 17 (owner, 2026-10-05); docs/009 DEPLOY-015,
DEPLOY-016, DEPLOY-039 to DEPLOY-047, DEPLOY-051, DEPLOY-052; docs/005 API-081.
**Built in:** V1-059 part A (2026-10-24). Nothing here has been run on the office computer or on
real data yet. Every step on the office computer, every real backup of real data, and the first
real `make migrate` wait for the owner's yes.

This runbook is written in plain English on purpose. Each part says what the system does, what a
person must do, and how to check it.

## 1. What the owner decided (DL-071)

| Rule | Value |
|---|---|
| Data loss at most | 1 hour (a backup every hour) |
| Working again within | 1 working day |
| Hourly copies kept | 2 days |
| Daily copies kept | 30 days |
| Monthly copies kept | 12 months |
| Last good copy | never deleted |
| Off-host copies | daily: external drive or second office computer; weekly: kept outside the building; no cloud storage |
| Restore test | every 3 months and before every release |
| Remote access | off in V1; office network only |
| Production computer | a separate small office computer used only for this system (not the development Mac mini) |
| Alerts | Telegram message to the Owner and the Manager, plus a warning on the health page; no Customer data |
| Technical logs kept | 90 days; audit and money history kept forever |

## 2. The pieces

| Piece | What it is |
|---|---|
| `config/deployment/production-operations.json` | Paths, hosts and limits. Every secret is a file under `/run/secrets/`. Checked by `make deployment-config-check`. |
| `property-rental-backup run` | One hourly backup (section 3). |
| `property-rental-backup offhost-copy` | Copies the newest good backup, still encrypted, to another place (section 4). |
| `property-rental-backup restore-test` | Restores the newest good backup into an empty throwaway database and compares it (section 5). |
| `property-rental-backup verify FILE` | Checks one backup file. |
| `property-rental-ops-check run` | Every 5 minutes: checks, records and sends Telegram alerts (section 6). |
| `property-rental-ops-check record-migration` | Records the outcome of a database update for the health page. |
| `property-rental-log-retention` | Once a day: deletes technical log files older than 90 days (section 7). |
| `GET /api/v1/operations/status` | The health page data, for holders of `operations.status.read` (the Owner and Manager bundles). |
| `config/deployment/host/` | Example systemd timers and services, the journal setting and the Docker log setting for a Linux office computer. |
| `scripts/backup-restore-check.sh` | Development check of the whole backup and restore path on a throwaway PostgreSQL 17.6 (section 8). |

**Where the secret files live.** On the office computer the secret files are kept in
`/etc/prm/secrets` (folder `0700`, files `0600`, owned by the `prm-ops` user), because `/run` is
emptied at every restart. The example systemd services show that folder to the jobs at
`/run/secrets` (`BindReadOnlyPaths=`), so the paths in `production-operations.json` stay the
same as inside the containers. The containers get the same files as Docker secrets.

**The status folder.** `/var/lib/prm/status` is owned by `prm-ops` and the group `prm-app`
(group id 10001, the backend container's group), mode `2750`. The jobs write each status file
`0640`, and the set-group-id bit gives it the `prm-app` group, so the backend can read it
through a read-only mount. Without this the health page would show the backups as missing.

The office computer's operating system is still open (OOD-DEPLOY-002). The examples in
`config/deployment/host/` assume a Linux computer with systemd (for example Ubuntu Server LTS),
decided by Claude under the owner's 2026-10-23 22:30 rule; another system needs the same jobs on
its own scheduler.

## 3. The hourly backup

What the job does, every hour (`prm-backup.timer`):

1. Connects with the read-only backup identity (`prm_backup`, `pg_read_all_data`). The address
   and password come from `/run/secrets/prm_production_backup_database_url`. They go to the
   PostgreSQL tools through a private password file, never on the command line or in a log.
2. Opens one consistent snapshot, counts the rows of every table in it, and runs
   `pg_dump --format=custom --snapshot=...` on that same snapshot.
3. Checks the dump with `pg_restore --list`. An empty or unreadable dump fails the job.
4. Seals the dump with AES-256-GCM (the `cryptography` library) and the key in
   `/run/secrets/prm_production_backup_encryption_key`, opens it again and compares the SHA-256.
5. Stores it in `/var/lib/prm/backups/hourly/`. The first good backup of a day (Phnom Penh time)
   is also linked into `daily/`, and the first of a month into `monthly/`. Each copy has a
   manifest: times, source identity (no password), schema revision, row counts, sizes, SHA-256
   checksums, destination, retention classes and outcome (DEPLOY-042).
6. Deletes expired copies: hourly after 2 days, daily after 30 days, monthly after 12 months.
   The newest good backup is never deleted, whatever its age.
7. Writes the outcome to `/var/lib/prm/status/backup.json` for the health page and the alerts.

The PostgreSQL client tools must be version 17 or newer, the same major version as the server
(`postgresql-client-17` on Ubuntu, path `/usr/lib/postgresql/17/bin`).

**The backup key.** Make it once with `openssl rand -base64 32`, save it as the key file with
mode `0600`, owned by the `prm-ops` user, in `/etc/prm/secrets`. Keep a second copy of the key on paper or a USB stick
in the office safe, apart from the backup drives (DEPLOY-039). Without the key no backup can be
opened. Never put the key in the repository, a message or a log.

## 4. Off-host copies

- **Prepare each drive once.** On the drive itself (while it is mounted), create the empty
  file `PRM-OFFHOST-DRIVE` at its top folder. The copy refuses a place without this file, so an
  unplugged drive (an empty mount folder on the production disk) fails the copy and raises the
  overdue warning instead of pretending to succeed.
- **Daily copy.** `prm-offhost-daily.timer` runs at 21:30 Phnom Penh time and copies the newest
  good backup to `/mnt/prm-offhost` (the always-connected external drive, or a folder shared by
  the second office computer). The copy is checked by SHA-256 against its manifest. Daily copies
  there are kept 30 days; the newest is never deleted.
- **Weekly copy, kept outside the building.** Once a week a person connects the weekly drive and
  runs:
  `sudo -u prm-ops /opt/prm/venv/bin/property-rental-backup --config /etc/prm/production-operations.json offhost-copy --kind weekly --destination /media/prm-weekly`
  then unmounts the drive and takes it out of the building. Weekly copies on that drive are kept
  about 12 months; the newest is never deleted.
- The copies are already encrypted, so a lost drive shows nothing without the key. Do not keep
  the key on the same drive.
- The health page warns when the daily copy is more than 50 hours old or the weekly copy more
  than 8 days old (thresholds decided by Claude under the owner's 2026-10-23 22:30 rule).

## 5. Restore test (every 3 months and before every release)

The restore test proves a backup can really be used (DEPLOY-045). It never touches the live
database: the target must be an empty database whose name starts with `prm_restore_test`.

1. On the office computer, start a throwaway PostgreSQL 17.6 container (not the live one) with
   the same database roles, for example with the steps of `scripts/backup-restore-check.sh`, and
   create the empty database `prm_restore_test`.
2. Put the throwaway database address in a private file, for example
   `/etc/prm/secrets/prm_restore_test_database_url` (mode `0600`).
3. Run:
   `sudo -u prm-ops /opt/prm/venv/bin/property-rental-backup --config /etc/prm/production-operations.json --pg-bin /usr/lib/postgresql/17/bin restore-test --target-database-url-file /etc/prm/secrets/prm_restore_test_database_url`
4. The job opens the newest good backup, checks its SHA-256, restores it in one transaction with
   its owners and grants, then compares the schema revision and the row count of every table
   with the manifest. Any difference fails the test.
5. Then the Owner or the Manager checks in the restored copy, by eye, one Customer's account
   ledger, one Lease with its Invoices, Payments and Receipts, one Deposit and one audit history
   page, and writes the date, the backup name and the result in the restore log (paper or a
   file `/var/lib/prm/restore-tests.txt`, which the log cleaning never touches). This person check stays until V1-060 adds an
   automatic ledger comparison.
6. Remove the throwaway container and its address file.

The outcome is written to `/var/lib/prm/status/restore-test.json`; the health page warns when
the last test failed or is more than 92 days old.

**A real restore** (after a failure) follows DEPLOY-044: decide the recovery point, record who
authorized it, keep the failed system for investigation, restore into a new database first, check
it as in step 4 and 5, and only then switch the application over. A real restore needs the
owner's yes every time.

## 6. Alerts and the health page

`prm-ops-check.timer` runs `property-rental-ops-check run` every 5 minutes. It checks:

| Check | Warning code |
|---|---|
| Database answers (read-only backup identity) | `database_unavailable` |
| Application readiness page | `api_unavailable`, `database_unavailable` |
| Backup failed / no good backup in 2 hours | `backup_failed`, `backup_stale` |
| Off-host copy failed / overdue | `offhost_copy_failed`, `offhost_daily_overdue`, `offhost_weekly_overdue` |
| Restore test failed / older than 92 days | `restore_test_failed`, `restore_test_overdue` |
| Billing run attempts failed twice in 24 hours, or a Reservation expiration run failed after a retry | `scheduled_job_repeated_failure` |
| Free disk under 10 percent or under 5 GB | `low_disk_space` |
| Database update failed | `migration_failed` |
| Security certificate expires within 21 days / cannot be read | `tls_certificate_expiring`, `tls_certificate_unreadable` |

When a critical warning starts, a Telegram message goes to the Owner and the Manager ("NEW: ...").
It is repeated every 12 hours while it lasts ("STILL: ...") and sent once when it ends
("FIXED: ..."); a FIXED message is kept until it is delivered. A message that cannot be
delivered is tried again at most once an hour, so a broken chat never causes a message every 5
minutes. A message holds only the fixed warning text; never a Customer name, amount or
detail. If a message cannot be sent, the health page shows "The last Telegram alert could not be
sent." The system keeps working (SEC-059).

The health page data (`GET /api/v1/operations/status`) shows the build, the database state, the
backup, off-host copy, restore test and migration records, the last scheduled-job times, the
Telegram state and the warnings. It needs `operations.status.read`, which only the Owner and
Manager bundles hold. The backend reads the status folder through
`APP_OPERATIONS_STATUS_DIRECTORY` (mount `/var/lib/prm/status` read-only into the backend
container). The health screen itself is built in the screen rebuild (UI-093, DL-074).

**Setting up Telegram (the owner does this; the token is a secret):**

1. In Telegram, talk to `@BotFather`, create a bot and copy its token.
2. The Owner and the Manager each send any message to the new bot, then read their chat id
   (for example with `@userinfobot`).
3. On the office computer only, write the token into
   `/etc/prm/secrets/prm_production_telegram_bot_token` and the two chat ids into
   `/etc/prm/secrets/prm_production_telegram_chat_ids` as
   `{"owner": "123456789", "manager": "987654321"}`; both files mode `0600`, owned by `prm-ops`.
4. Never paste the token into the repository, a chat with Claude, a screenshot or a log. The
   repository holds only the placeholders `config/deployment/production-telegram-bot-token.example`
   and `production-telegram-chat-ids.example.json`.
5. The office computer's firewall allows outbound HTTPS only to `api.telegram.org`
   (DEPLOY-016). No other outbound host is on the list in V1.

**Recording a database update.** After `make migrate` in a release, run
`property-rental-ops-check --config /etc/prm/production-operations.json record-migration --outcome succeeded --revision <the head revision>`,
or `--outcome failed` if it failed. A failed update shows on the health page and is sent by
Telegram.

## 7. Logs

- Technical logs are kept 90 days. The jobs above log one JSON line per event to the system
  journal; `config/deployment/host/journald-prm.conf` keeps the journal 90 days, and
  `docker-daemon.json` sends the containers' logs to the same journal.
- `property-rental-log-retention` deletes, once a day, the files in `/var/log/prm` ending in
  `.log`, `.jsonl`, `.log.gz` or `.jsonl.gz` that are older than 90 days. It never enters a
  sub-folder, never follows a link and never touches anything else.
- Audit and money history are in the database and are kept forever. No log job can reach them.

## 8. Development check

`sh scripts/backup-restore-check.sh` (from the repository root) runs the whole path on a
throwaway PostgreSQL 17.6 container: migrations, two backups, verify, an off-host copy, a restore
test into an empty database (every table compared), and a changed backup file refused. It needs
Docker and the `postgres:17.6` image, and prints no password, key or database address.

## 9. Not built yet

- An audit-write failure alert (DEPLOY-051) needs the application to record such failures
  first: V1-059 part B or V1-060.
- An automatic Customer Account Ledger comparison in the restore test (DEPLOY-045): V1-060.
- The health screen (UI-093): the screen rebuild.
- A release checklist line that a restore test passed shortly before each release (DL-071
  answer 5): with the V1-060 release gate.
- The production Compose file with the reverse proxy, TLS and the worker (DEPLOY-021): with the
  office computer setup, after the owner chooses its name, address and certificate method.
