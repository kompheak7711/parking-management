# V1-056 login sub-slice L3b — the wrong-try count and the waits — review record

Sub-slice L3b of the login slice (ops/V1_056_PLAN.md section 7.3). Migration `20270128_185`.
Base commit: 5c61c6f (L3a-2). Built on 2026-10-23 in a fresh session. Stopped after review round 3
found a blocker that needed a code change (Q-2026-10-23-177); the owner answered (a) to Q-175, Q-176
and Q-177 the same day; the fix, review round 4 and the commit followed. Not pushed. The commit hash
is in `git log` (this record is part of that commit).

## Owner rule

The owner's wait rule, given on 2026-10-23 as amended on 2026-10-21 (DL-080 item 10 amended by
DL-081): after 3 wrong tries in a row the person waits 5 minutes; after 2 more (5 in a row) 15
minutes; after that every 2 more wrong tries mean another 15-minute wait, until a correct sign-in.
The rest as Q-2026-10-21-154 (a). The repository still said "5 tries, 15 minutes" before this
sub-slice; the amendment is now recorded in DL-081, docs/005 API-096, docs/006 UI-109, docs/008
SEC-012 and docs/004 DB-AUTH-011. Reading recorded: "in a row" has no time limit (Q-176).

## Built

- Migration `20270128_185`: append-only `app.sign_in_wrong_tries`, `app.sign_in_waits` (a check
  allows only 5 or 15 minutes for a username, 15 for a source) and `app.sign_in_try_clears`;
  definer functions `app.sign_in_wait_seconds`, `app.record_sign_in_wrong_try` and
  `app.clear_sign_in_wrong_tries` (READ COMMITTED only, username lock then source lock, EXECUTE for
  `prm_runtime` only; the clear only for the active account whose username gives the digest).
- `local_authentication.py`: `SignInWaitBoundary`; a try during a wait is refused before the lookup
  and the password check; every refused password check records one wrong try.
- `auth_flow.py`: `_PostgresSignInWaits`, sha256 keys of the normalized username and the source;
  429 with `Retry-After` on a wait; the MFA branch asks again for a wait under the locks; the
  session transaction clears first and then compares the sha256 digest of the stored verifier the
  password was checked against with the one it reads (no second Argon2id check; Q-177 (a)).
- `auth_api.py`, `app.py`: `AuthenticationRateLimited(retry_after_seconds)`; the 429 answer adds
  `Retry-After` and `no-store`.
- Tests: PostgreSQL `test_sign_in_wait_migration.py` (15, last in `scripts/database-test.sh`); unit
  tests in `test_local_authentication.py` (5), `test_auth_flow.py` (1), `test_authentication_api.py`
  (1). Traceability: 18 entries appended; notes changed on the flood-guard and reset-race tests.
- Docs: DL-081 (amendment, as built, updated tests), DB-AUTH-011, API-096, UI-109, SEC-012, plan,
  questions Q-2026-10-23-174 (decided under the owner's 2026-10-22 rule), 175, 176, 177.

## Committed tests changed

- The 27 head-revision strings (`20270127_184` to `20270128_185`) in 15 modules.
- `test_auth_flow_migration.py::test_the_flood_guard_refuses_a_username_after_20_tries_and_a_source_after_100`
  (owner's rule, standing rule): the wait answer from the 3rd wrong try for the username and the
  20th from one source; the flood guard still refuses the 21st and 101st try; the username's wait
  survives a new flow object; another account signs in from another source.
- `test_auth_flow_migration.py::test_a_password_reset_during_sign_in_leaves_no_session_made_with_the_old_password`:
  docstring and traceability note only (the session transaction now compares the verifier; Q-177
  (a)); the test body is unchanged and passes.

## Read-only search for affected tests

- Sign-ins in `test_auth_flow_migration.py`, `test_session_actor_migration.py` and
  `test_session_revocation_time_migration.py`: at most 2 wrong tries per username and fewer than 20
  per source except the flood-guard test (changed above).
- No committed test truncates or lists the referencing tables of `app.user_accounts`; the catalog
  tests filter by name.

## Reviews

- **Round 1** (one independent and one security agent; after U1, T1, T2, M1, M2, P1).
  - Security blocker: the correct password of an MFA account had no locked wait check after the
    password check. Fixed (design change: the wait read takes the locks; the MFA branch asks again).
  - Should-fixes done: the clear after the second password check; the clear tied to the actor's
    username digest; tests for the flow's fail-closed clear, the lock re-check, the mismatched
    actor and the wait lengths; "pseudonymous" wording and Q-175; docs/010 and the questions file;
    the stale traceability note; the wait-length check; a 30-second test margin.
  - Test set-ups (reviewers'): MFA race — wrap `flow._authentication.authenticate` so that after the
    real call 3 tries and a 5-minute wait are written as the table owner; the login must answer the
    wait. Flow clear race — 3 earlier tries and a wait ending in 4 minutes written as the owner,
    `_PostgresSignInWaits.wait_seconds` patched to None; the login must answer 180 to 240 seconds,
    no session, no clear.
- **Round 2** (one fresh agent, both checklists; after U2, P2): no blocker; round 1 design change
  confirmed. Should-fixes (tests and text) done: the lock test over all three functions (holder
  takes the username lock as the owner; a thread calls the function as the runtime role; `pg_locks`
  for the current database shows an ungranted advisory lock; the holder writes the 3rd try and a
  5-minute wait and commits; for the clear an active account with 2 earlier tries); a non-ASCII
  username clear test; Q-175 and Q-176 text; DB-AUTH-011 sentence; stricter privilege assertion.
- **Round 3** (one fresh agent, both checklists; after U3, P3): one BLOCKER, no should-fix.
  - B1: a burst of up to 20 parallel tries per process all pass the first wait check; a correct
    password is checked a second time in the session transaction before the clear meets the wait,
    so its 429 comes about one Argon2 later than the wrong ones: a timing oracle for about 20
    passwords per burst. Proposed fix: compare the stored verifier the first check used with the one
    the session transaction reads, instead of a second Argon2; test that a correct sign-in meeting a
    parallel wait makes exactly one password check. Needs a code change and a new test, so the
    round 3 rule stops: Q-2026-10-23-177. Owner answer (a) (2026-10-23): built as proposed, with
    the test (exactly one `verify_password` call on the flow clear-race path).
  - Notes: `has_any_column_privilege` would be a stronger privilege assertion; a username renamed
    between lookup and clear leaves the count uncleared (fails toward stricter limits); the locked
    wait read serializes sign-ins from one source (the L7 binding).

- **Round 4** (one fresh agent, both checklists; after U4 and P4): no blocker; the timing oracle
  closed (one Argon2id check on every path; the reset guard holds and now also refuses a reset to
  the same password). Done after it: S1 `verifier_digest` is `repr=False`, with an assertion; S2
  text (the L4 binding in the plan, NOW.md); note N1: the clear is the first statement of the
  session transaction, so a correct password that meets a wait answers after the same work as a
  wrong one; note N3: new test `test_a_reset_to_the_same_password_during_sign_in_is_refused`. Then
  every check, the targeted tests, the unit run and the full run again (FF8 to P5). Notes kept: the
  flow does not audit a correct password refused by the second wait read or the clear (L3c or L5);
  `LocalAccountCredential.verifier_encoding` shows in `repr` (pre-existing); a correct password
  refused by a concurrent reset records no wrong try.

## Owner answers (2026-10-23)

- Q-2026-10-23-177 (a): the comparison instead of the second password check, round 4, commit only
  without a blocker.
- Q-2026-10-23-175 (a): the keyed digest in L3c (a key derived from the protected key file; no new
  package, no new secret, the key never printed); removing rows older than 30 days on the slice 12
  list.
- Q-2026-10-23-176 (a): no time limit, as built.

## Runs (logs in ~/Development/prm-run-logs/, prefix `v1-056-login-L3b-`)

| Run | Result | Cause |
|---|---|---|
| FF1 (two files reformatted), I1, FC1 | pass | backend checks |
| L1 | fail | cause A (1 of 1): a tuple concatenation in the new test (RUF005) |
| FF2, I2, FC2, L2, Y1 | pass | after the cause A fix |
| U1 | 3,910 passed | unit suite |
| M1 | pass | migration-only check |
| T1 | 502 passed, 1 failed | cause B (1 of 1): the new test truncated a parent table without CASCADE |
| FF3, I3, FC3, L3, Y2 | pass | after the cause B fix |
| T2 | 7 passed | targeted: `test_sign_in_wait_migration.py` |
| M2 | pass | migration-only check |
| P1 | 2,537 passed | full PostgreSQL run (before round 1) |
| FF4 (one file reformatted), I4, FC4, L4 | pass | after the round 1 fixes |
| Y3 | fail | cause C (1 of 1): one variable name used for two types |
| FF5, I5, FC5, L5, Y4 | pass | after the cause C fix |
| M3 | pass | migration-only check |
| T3 | 26 passed | targeted: the four sign-in modules |
| U2 | 3,910 passed | unit suite |
| M4 | pass | migration-only check |
| P2 | 2,542 passed | full PostgreSQL run (before round 2) |
| FF6, I6, FC6, L6, Y5 | pass | after the round 2 fixes |
| T4 | 14 passed | targeted: `test_sign_in_wait_migration.py` |
| U3 | 3,910 passed | unit suite (before round 3) |
| M5 | pass | migration-only check |
| P3 | 2,544 passed | full PostgreSQL run (before round 3) |
| FF7 (one file reformatted), I7, FC7, L7, Y6 | pass | after the Q-177 (a) fix |
| T5 | 28 passed | targeted: the four sign-in modules |
| U4 | 3,910 passed | unit suite |
| M6 | pass | migration-only check |
| P4 | 2,544 passed | full PostgreSQL run (before round 4) |
| FF8 (one file reformatted), I8, FC8, L8, Y7 | pass | after the round 4 fixes |
| T6 | 29 passed | targeted: the four sign-in modules |
| U5 | 3,910 passed | unit suite |
| M7 | pass | migration-only check |
| P5 | 2,545 passed | full PostgreSQL run (last, before the commit) |

- T1 covered the 15 head-revision modules and the four sign-in modules (503 tests).
- No `LockNotAvailable` failure. Only the known Starlette and pydantic warnings.
- No frontend file changed.
- Still pending (not touched): the test rename in `test_deposit_receipt_refund_out_migration.py`.
