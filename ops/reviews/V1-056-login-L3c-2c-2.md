# V1-056 login sub-slice L3c-2c-2 — signing in with a recovery code — review record

Sub-slice L3c-2c-2 of the login slice (ops/V1_056_PLAN.md section 7.3, L3c). Migration
`20270202_190`. Base commit: 210eecf (L3c-2c-1). Built on 2026-10-24 in the same session as
L3c-2b and L3c-2c-1. Not pushed. The commit hash is in `git log` (this record is part of that
commit).

## Backup

- After the L3c-2c-1 commit: `git bundle create --all` into the iCloud Drive folder
  `PRM-backups` (`prm-backup-2026-10-24-210eecf.bundle`, 12,222,872 bytes, sha256
  `6361745c5d59e52a7ab7def7af92136959095fd99084f0f20669048b8ba42250`), `git bundle verify` okay.

## Built

- Migration `20270202_190` (additive): the proof's `recovery_code_id` (unique, a foreign key to
  `app.recovery_codes`, checked against the method; insert and select privileges for the runtime
  role) and the proof guard replaced with the `recovery_code` condition: a `challenge`, and a
  code of a live set of its account, made no earlier than the challenge's sign-in code, consumed
  by the account since the challenge.
- `auth_flow.py` (as built after review rounds 1 and 2): `complete_mfa` with `recovery_code` on
  one connection:
  - a connection lock on the account's codes' making key (refused at once when held);
  - the wait checked in its own short transaction;
  - the usable codes read (live set, made no earlier than the challenge's sign-in code, at most
    10);
  - the typed code compared with each outside any transaction;
  - a wrong code counted as a try of kind `recovery_code`;
  - for the right code, one transaction: the clear, the code consumed through
    `app.perform_account_recovery`, and the shared tail with a `recovery_code` proof.

  `PROOF_COUNTS`: a `recovery_code` proof counts while its challenge's sign-in code is active and
  its code's set is live.
- Tests: PostgreSQL `test_recovery_code_sign_in_migration.py` (15 tests, one parametrized four
  ways), last in `scripts/database-test.sh`. Traceability: 15 entries appended, 1 note changed.
- Docs: API-096 and DB-AUTH-004 amendments, DL-081 lines, Q-2026-10-24-182 (decided under the
  owner's 2026-10-22 rule), plan.

## Committed tests changed

- The 27 head-revision strings (`20270201_189` to `20270202_190`) in 15 modules;
  `test_sign_in_wait_migration.py` moves `HEAD` (and its docstring) to `20270202_190`.
- With the approved plan (L3c-2c builds the recovery-code challenge):
  `test_sign_in_code_migration.py::test_a_sign_in_code_needs_the_protection_key_that_protected_it`
  no longer expects `recovery_code` to answer unavailable; a sign-in code given as a recovery code
  is now refused and counted (asserted after the unchanged unavailable cases; stricter). Its
  traceability note changed with it.
- `test_recovery_code_flow_migration.py`'s `recovery_code_session` set-up wrote a `recovery_code`
  proof by hand; the new check refuses it, so it now uses the real path (the first codes, then a
  sign-in with one of them). Every check is kept. Since review round 2 a recovery-code session
  needs its code's set to be live, so that account has a live set. The regeneration names it, so
  there only the session can refuse, as at HEAD. The first-codes refusal is now explained by the
  live set as well; its session condition is shown by the other cases and the regeneration. The
  refusal of the old hand-written proof is the first case of the new guard test.

## Read-only search for affected tests

- Every test naming `recovery_code` (`test_sign_in_code_migration.py`, `test_auth_flow.py`,
  `test_authentication_api.py` with its own fake flow, `test_recovery_code_flow_migration.py`):
  only the two set-ups above change.
- Every insert into `app.browser_session_mfa_proofs`: the L3c-2a, L3c-2b and L3c-2c-1 tests
  write `totp` proofs (the new column empty, the check satisfied), except the one set-up above.

## Reviews

- **Round 1** (one independent and one security agent, read-only, during P1): no blocker.
  Should-fixes done (fail-closed checks, tests, text):
  - security S2: the wait is checked again under the try lock (no Argon2id work during a
    wait), and a wrong code is counted inside the locked transaction, so the next try sees it.
    Reviewer's set-up: three wrong tries recorded, the first check made to see none,
    `Argon2idRecoveryCodeVerifierProvider.matches` counted.
  - The proof guard also needs the code's set to be live.
  - `recovery_code_id` has a foreign key to `app.recovery_codes`; no committed test empties that
    table.
  - The unused SELECT grant on the new column is dropped.
  - At most 10 codes are read (`LIMIT`).
  - The audit correlation id is written to the decision log. `access_admin_flow.correlation_id`
    cannot be imported here, because that module imports this one.
  - Tests:
    - another account's valid code;
    - a wait met under the lock;
    - a regeneration committed during the check (reviewer's set-up: the first `matches` call
      invalidates the set as the table owner and commits);
    - the check constraint with a `totp` proof the guard accepts (reviewer's set-up);
    - a code of an invalidated set;
    - the positive control after a refused parallel try;
    - the audit event rolled back in the window test;
    - the L3c-2c-1 recovery-code case with its set invalidated, so only the session refuses the
      first codes, as before (independent 1: otherwise weaker than HEAD).
  - The binding S3 is recorded as set aside in part (independent 6), with the round 1 security
    reviewer's confirmation that keeping Argon2id is adequate. A code easier to copy by hand
    stays open for L7.
  - Kept as a note, with its reason (security S1): `prm_runtime` can still mark a code consumed
    directly. The guard therefore proves "consumed by the account since the challenge", not
    "through the audited recovery". A compromised runtime role could forge a `totp` proof the
    same way, so this goes on the slice 12 list: definer functions only, then revoke the
    grants.
  - New binding for L4: the lock order with the set and the account row.
  - Other notes kept:
    - the answer time shows how many codes are left;
    - the lock and account-recovery refusals were not logged (round 2 adds a rejected log line);
    - a parallel TOTP sign-in after the revocation keeps its session;
    - a recovery-code session has the normal lifetimes.
- **Round 2** (one fresh independent and one fresh security agent, read-only, during P2): no
  blocker. Every round 1 fix was confirmed, and so were keeping Argon2id and keeping S1 as a
  note. Should-fixes done. One restructuring, allowed because it was the only change of its kind;
  the rest are fail-closed refusals, tests and text.
  - **Wait locks (both reviewers):** the round 1 wait check held the sign-in wait locks of the
    username and the source during the hashing. The try now runs on one connection with a
    connection lock (`pg_try_advisory_lock`) on the codes' making key:
    - the wait check commits at once;
    - the codes are read and committed;
    - the hashing runs outside any transaction;
    - a wrong try is counted in its own transaction;
    - the right code is written in one transaction;
    - closing the connection ends the lock.

    Reviewer's set-up for the test: a probe with a 1-second lock timeout runs
    `app.sign_in_wait_seconds` for another account from the same source, from inside the first
    `matches` call.
  - **Security F2:** a code counts only if its set was made no earlier than the sign-in code the
    challenge was made for, in the flow and in the guard. Otherwise codes from before a sign-in
    code reset would come back with the new code before L4. The bootstrap writes the Owner's code
    and codes at one statement time.
  - **Security F3:** a `recovery_code` proof counts only while its code's set is live, so replacing
    the codes ends the session. The select grant on the new column is back, now used.
    Reviewer's set-up: session A with a recovery code, session B with the sign-in code, B
    regenerates, A no longer live.
  - **Security N1:** a wrong recovery code is a wrong try of kind `recovery_code`.
  - The refusals by the lock and by the account recovery are logged as rejected.
  - Tests:
    - the clear and the audit event rolled back in the regeneration-during-check test (one wrong
      try first);
    - the correlation id in the log;
    - the select privilege pinned.
  - The L3c-2c-1 refusal test's recovery-code case now keeps its live set, and its regeneration
    names that set (run T3 showed the round 1 set-up no longer works, see the committed-test
    section).
  - The L4 binding is corrected: the account's key lock can come first, through the clear's
    foreign key.
  - Text: the grants, the counts, the logging and "white space".
  - Notes kept:
    - the runtime role can also reset any account through `app.perform_account_recovery` in
      `administrative` mode (slice 12 least-privilege list, with S1);
    - for L3d: whether a recovery code can satisfy high-risk reauthentication.
- **Round 3** (one fresh agent, both checklists, read-only, during P3): no blocker. Every round 2
  fix is confirmed: the connection lock is released on every path, nothing is half-written, and
  the bootstrap writes the Owner's code and codes at one statement time. The L3c-2c-1 set-up
  change is allowed by the run rule in substance, and its regeneration branch is not weaker
  than HEAD.
  - One should-fix, a new assertion in a built test (the round-3 text and assertion rule),
    done. The guard test also refuses a code of a live set made before the challenge's sign-in
    code. Reviewer's set-up: an account with codes; its sign-in code turned off and a new one
    set up; a challenge for the new code; as the table owner, one old code consumed by the
    account, the challenge completed and a session added; the proof refused with "used since".
  - Text: a test docstring (kind `recovery_code`) and a traceability note (insert and select
    privileges).
  - Notes kept: the base sentences of DL-081 and the plan describe the first build, and the
    round lines after them correct it; only the lock and account-recovery refusals are logged.

## Runs (logs in ~/Development/prm-run-logs/, prefix `v1-056-login-L3c-2c-2-`)

| Run | Result | Cause |
|---|---|---|
| FF1 | 32 files reformatted | the implementer's mistake: the formatter was run on `src tests migrations` instead of the repository's `src tests`; the 30 committed migrations it reformatted had no other change and were restored from HEAD at once (`git restore --source=HEAD` of exactly those 30 paths; the new migration kept); no check had run on them |
| FF2, I1, FC1, L1 | pass | backend checks with the repository's command |
| Y1 | fail | cause A (1 of 2): a test helper returned an untyped row value |
| FF3, I2, FC2, L2, Y2 | pass | after the cause A fix |
| M1 | pass | migration-only check |
| T1 | 592 passed | targeted: 15 head-revision modules and the eight sign-in modules |
| U1 | 3,923 passed | unit suite |
| P1 | 2,626 passed | full PostgreSQL run (before round 1) |
| FF4, I3, FC3, L3, Y3 | pass | after the round 1 fixes |
| T2 | 94 passed | the six sign-in modules |
| U2 | 3,923 passed | unit suite |
| M2 | pass | migration-only check |
| P2 | 2,629 passed | full PostgreSQL run (before round 2) |
| FF5 (one file reformatted), I4, FC4, L4, Y4 | pass | after the round 2 fixes |
| T3 | 1 failed, 96 passed | cause B (1 of 2): the round 1 set-up of the L3c-2c-1 recovery-code case invalidated the set, which since round 2 ends that session |
| FF6, I5, FC5, L5, Y5 | pass | after the cause B fix |
| T4 | 97 passed | the six sign-in modules |
| U3 | 3,923 passed | unit suite |
| M3 | not run | started in `backend/` by the implementer (batched with another call); stopped before any step (not a failure cause) |
| M4 | pass | migration-only check, from the repository root |
| P3 | 2,632 passed | full PostgreSQL run (before round 3) |
| FF7, I6, FC6, L6, Y6 | pass | after the round 3 assertion and text fixes |
| T5 | 97 passed | the six sign-in modules (the new assertion passes) |
| U4 | 3,923 passed | unit suite |
| P4 | 2,632 passed | full PostgreSQL run (last) |

- After P4 only text changed: this record and ops/NOW.md.
- Only the known Starlette and pydantic warnings.
- Every saved run output scanned for secrets: only test and migration file names and one test
  source line (`session_token=` in the T3 failure trace) match.
- No frontend file changed.
