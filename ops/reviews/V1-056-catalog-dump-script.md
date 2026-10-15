# V1-056 catalog dump script — review record

Change: new committed script `scripts/catalog-dump.sh` and a pointer to it in the run rule
"Catalog dumps" of `ops/V1_055_RUN_RULES.md`. Tooling only; no migration, code or test change.
Base commit: 139f708. Built on 2026-10-15. Not pushed.

Why: sub-slice 10e-3d-2c patches `app.settlement_return_reversal_source_state`,
`app.assert_settlement_return_reversal_allowed` and other functions whose current bodies are the
result of many exact-text patches (migrations 125 to 135). The run rule of 2026-10-14 says a
catalog dump needed again is added as a committed script under `scripts/` in its own small
reviewed commit, must not print the database password or the database URL, and a copy in a tmp
folder is never run.

## What the script does

`sh scripts/catalog-dump.sh <app function name> [...]`, from the repo root:

- refuses no name, or a name with anything but a-z, 0-9 and _ (exit 2), before any container
  starts;
- starts a fresh throwaway PostgreSQL container exactly as `scripts/migration-check.sh` does
  (generated passwords in a 0700 temporary directory, loopback port 0, cleanup on exit and on
  HUP, INT and TERM);
- runs `uv run alembic upgrade head` as the migration role, its log kept in the temporary
  directory and printed only on failure, redacted;
- reads `pg_get_functiondef` of every function or procedure of schema `app` with each given name
  (every overload), in one read-only transaction that is rolled back; the names are bound query
  parameters, never part of the SQL text; a name with no function exits 1;
- prints everything through the same redaction filter as `scripts/migration-check.sh`.

## Runs

| Run | Kind | Result | Cause |
|---|---|---|---|
| D1 | catalog dump, 11 functions (the return reversal source, refusal, recovery scope, confirm, lock, walk, placed, follow, result, recovery writer, Refund correction check) | exit 0, 134 upgrades, 11 definitions | first |
| D2 | catalog dump, 10 functions (recovery checks, balance and net reads, the recorder, the users) | exit 0, 134 upgrades, 10 definitions | first |

No check or run failed. The outputs are kept outside the repo (the job's tmp folder); they are
function definitions only and hold no password or URL (redacted output; scanned before use).

## Review round 1 (fresh read-only subagents, told to write no file and run nothing)

Independent: 0 blockers, 0 should-fix, 6 notes. Security: 0 blockers, 0 should-fix, 7 notes.
Clean; no round 2 needed.

- Independent: argument checks, parameterised SQL with no single quotes in the program text,
  one read-only transaction, exit codes on every failure path, cleanup identical to
  `scripts/migration-check.sh`, POSIX sh portability; every output of alembic, uv, Python and
  psycopg passes the redaction filter; umask, secret directory, file modes, filter and traps are
  byte-identical to `scripts/migration-check.sh`; `--project-name` gives a fresh volume removed by
  `down --volumes`, so no persistent database is reached.
- Security: no path prints a password, generated secret or database URL (psycopg errors name host,
  port and user only; a 64-hex password is caught by its value, the URL rule and the hex rule);
  names validated and bound; the port is published on loopback only (compose file); the read is
  read-only and rolled back.
- Notes (not taken; tooling only): the redaction runs over the definitions too, so a 16+ character
  lowercase hex run, a `password=` text or a `postgres://` text in a function body would be
  replaced by a marker (the run rule now says to check a copied definition for markers); Python's
  stderr is merged into the dump output; an invalid name is echoed raw; `docker compose port`
  stderr is not redacted (as in `scripts/migration-check.sh`); the URL is in the exported
  environment of the child processes (as in `scripts/migration-check.sh`); the alembic log and the
  dump sit unredacted in the 0700 temporary directory until exit; the script must start from the
  repo root; a name over 63 bytes is cut by PostgreSQL (harmless, a parameter only); the root
  `.env` was not read by the security reviewer (the guard refused it; it affects
  `scripts/migration-check.sh` the same way).

Commit after the standard secret scan of the staged diff.
