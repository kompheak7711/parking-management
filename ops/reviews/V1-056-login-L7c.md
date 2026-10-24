# V1-056 login sub-slice L7c — the local run on the Mac mini — review record

Sub-slice L7c of the login slice (ops/V1_056_PLAN.md section 7.3, L7). No migration. Base
commit: 8c1194d (L7b). Built on 2026-10-24 in the cloud session. Decisions: owner answers (a) to
Q-2026-10-21-155 and Q-2026-10-21-159; technical points Q-2026-10-24-189 and its amendment,
decided by Claude under the owner's 2026-10-23 22:30 rule. The commit hash is in `git log` (this
record is part of that commit).

## Built

- `scripts/local/`: `make-secrets.sh`, `database.sh`, `migrate.sh`, `make-certificate.sh`,
  `start-api.sh`, `bootstrap-owner.sh`, `common.sh`, and `with-protected-key.py`, the only part
  run with sudo (installed root-owned in `/usr/local/libexec/prm`): it opens the root-only TOTP
  key, puts it on descriptor 4 and runs the API or the Owner set-up as the person who ran sudo.
- `npm run dev:local`: the screen server on HTTPS for the Mac's `.local` name, forwarding `/api`
  to the API on 127.0.0.1:8000. `config/password-blocklist.txt` (70 lines).
- README "Local run on the Mac mini": the runbook (steps 0 to 9, every day, each year).
- Tests: `test_local_run_scripts.py` (11).

## Trial in the cloud container (before review)

Secrets made, the compose database started from the secret files, the migrations ran, the
Owner set-up ran through a pseudo-terminal with the key on descriptor 4 (10 recovery codes
shown), the API inner part started with the key on descriptor 4 in production mode, and a
sign-in with the password and the TOTP code through the HTTPS screen server reached
`authenticated`; a sign-in from another address got 403. No password or database address in the
API or screen-server output. The trial found that the database container cannot read 0600
password files (its start-up script reads them as its own postgres user): they are now 0444
inside the 0700 folder, as `scripts/database-test.sh` does. It also found that the set-up shows
the TOTP key as text, not a QR code: the runbook now says how to type it in Google
Authenticator.

## Review round 1 (one independent agent, read-only, no files written)

- Blocker, fixed: the Mac's local name is often mixed case (such as Soks-Mac-mini), browsers send
  the Origin in lower case and the API compares it exactly, so every sign-in would get 403.
  `prm_local_hostname` now gives the lower-case name (new test).
- Should-fix, all done: (1) `setgroups(getgrouplist())` fails on macOS for more than 16 groups:
  now `initgroups`, with a clean refusal, and the test checks the groups; (2) running the key step
  again would replace the key and lock every account out of its codes: `set -C`; (3) the proxy
  sent no X-Forwarded-For, so every device was 127.0.0.1 for sign-in waits and audit: `xfwd`
  (uvicorn trusts it from 127.0.0.1 only); (4) `dev:local` served plain HTTP to the Wi-Fi without
  the certificate: it now refuses to start (checked); (5) `--key` could name another root-only
  file under that name (a hard link): the helper now needs one link, a root-owned folder others
  cannot write, and no symbolic link, and the helper and key paths in `common.sh` no longer come
  from the environment; (6) the helper relied on sudo to close other descriptors: it closes them
  itself (test passes one); (7) wording: the set-up shows a key, not a QR code; (8) "Nothing is
  downloaded" was wrong: step 0 lists the installs and the image; (9) the authority lasted 825
  days with no renewal: 10 years, with a warning 60 days before, and openssl failures now say
  so; (10) missing refusal tests added (symbolic link, folder, hard link, folder others can
  change, group mismatch, extra descriptor, the API inner part without the key, the set-up's own
  options in a terminal, Python 3.9 syntax of the helper).
- Notes taken: the runbook says what to repeat every day and each year, Firefox does not use the
  Mac's trusted certificates, `open -R` shows the hidden `.local` file for AirDrop, a changed
  local name needs a new certificate; `bootstrap_cli` takes no shortened options
  (`allow_abbrev=False`); the helper drops sudo's USERNAME and MAIL and sets SHELL; the screen
  server denies `.local` explicitly. Notes kept: sudo logs the command line with the username (not
  a secret).
- After the fixes the trial ran again on a new database: same results.

## Review round 2 (one fresh agent, read-only, no files written)

- Blocker, fixed: the trial started the API's inner part as root, so it never read the key after
  the helper's drop. As the person's user, opening `/dev/fd/4` again is refused on Linux for a
  root-only file (checked: errno 13 through the real helper), and macOS may refuse it too.
  `read_protected_totp_key` now copies an inherited `/dev/fd/<n>` descriptor (`os.dup`) instead
  of opening the path; the root-only test
  `test_an_inherited_root_only_key_is_read_after_the_drop_to_another_user` fails without it.
  The bootstrap reads descriptor 4 directly and was not affected.
- Should-fix, done: the inner parts checked only the variable, not that descriptor 4 is open:
  both now check it, and the test covers both cases.
- Notes taken: uvicorn gets `--proxy-headers --forwarded-allow-ips 127.0.0.1` itself (not its
  defaults); a local name the API could never match is refused before the API starts (test); the
  certificate message names only the `.local` address; the python3 check moved to step 0; the
  runbook checks the owners of `/usr/local`, `etc` and `libexec` before installing the helper and
  says how to re-install it; the helper also checks the real group; the docs say "the bootstrap's
  checks plus" the helper's own. Notes kept: a client's X-Forwarded-Proto is ignored (nothing uses
  the scheme); the helper closes descriptors up to 65536 (sudo closes the rest).
- Every round 1 fix checked: present and correct; `fs.deny` keeps Vite's four defaults.

## Review round 3 (one fresh agent, read-only, no files written)

- No blocker. Every round 2 fix checked: the descriptor pattern is anchored, a closed or odd
  descriptor is refused and never waits, the root-owned checks still run on the copy, `( : <&4 )`
  works in bash 3.2 POSIX mode and dash, the name checks stop every caller under `set -e`, and the
  forwarded address cannot be faked from the Wi-Fi.
- Should-fix, done (new test only): `test_an_inherited_descriptor_that_is_closed_a_pipe_or_not_root_owned_is_refused`
  runs without root.
- Notes taken: the Owner set-up's inner part is tested like the API's (the test is renamed
  `test_the_inner_parts_refuse_to_start_without_the_key_descriptor`); step 0 says `make install`
  only (it runs the frontend install too); a name starting or ending with a hyphen is refused.
  Notes kept: the screen server lets in any `.local` name (the certificate and the API's origin
  check cover only the Mac's own name); descriptor 4 stays open in the API process, which runs as
  the person and holds the key in memory anyway; the certificate test ran on the container's
  OpenSSL, so step 6 on the Mac is the first LibreSSL run (every option used is supported, and a
  failure now says so).
- Round 3 findings were tests and text only, so no round 4 (run rule).

## Runs

- Static checks: ruff, format and mypy (backend, 437 files); prettier, eslint and tsc on the
  changed frontend files: clean.
- Targeted: `test_local_run_scripts.py`, `test_runtime_secrets.py`, `test_traceability.py`: 48
  passed, 1 skipped (the non-root fstat test, as root).
- End to end in the container, three times on a new database (before review, after round 1, after
  round 2): see above.
- On the branch with L7a, L7b and L7c (from ebc0b7a): before L7c, U1 (full backend unit) 4,043
  passed and P1 (full PostgreSQL) 2,679 passed; with L7c, U2 4,056 passed, F2 (frontend format,
  lint, types, tests and build) 1,635 passed, and T1 (bootstrap and key tests on PostgreSQL) 38
  passed, 1 failed: `test_runtime_secrets.py::test_the_password_blocklist_is_read_once_and_needed_with_a_database_outside_development`
  reads the database setting the PostgreSQL script sets (it is not in the PostgreSQL gate and passes
  in the unit runs; the same kind of fix as the V1-059 status test later, slice 12 list).
