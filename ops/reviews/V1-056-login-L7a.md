# V1-056 login sub-slice L7a — recovery codes a person can copy by hand — review record

Sub-slice L7a of the login slice (ops/V1_056_PLAN.md section 7.3, L7; the L6 decision
Q-2026-10-24-187 point 15 left the easier format as an L7 item). No migration. Base commit:
5296730 (L6). Built on 2026-10-24 in the cloud session. Technical points in Q-2026-10-24-188,
decided by Claude under the owner's 2026-10-23 22:30 rule. The commit hash is in `git log`.

## Built

- `recovery_code_security.py`: a new code is 12 symbols of Crockford's Base32 (60 random bits
  from 8 bytes of `secrets.token_bytes`), shown `XXXX-XXXX-XXXX`. `canonical_recovery_code`
  turns a code of this shape, typed in ASCII in any case with or without dashes and spaces,
  into its 12 capitals (I and L read as 1, O as 0); any other text stays as given. `encode`
  hashes the canonical form; `matches` removes white space around the candidate and checks its
  canonical form.
- The screen's example is 7KQ4-M2XD-9PRT (`signInText.ts`).
- Tests in `test_recovery_code_security.py` (three new, two changed; docs/010 "Updated tests
  (login sub-slice L7a)").

## Review round 1 (one independent agent, read-only, no files written)

- No blocker. The generator was checked against an independent reference on 2,000 random
  inputs; no modulo bias (32 symbols, 5 bits each); the expected values are right; no input
  raises; two issued codes cannot collide (issued codes never hold I, L or O); 60 bits are
  ample with salted Argon2id verifiers and counted wrong tries; no caller, API model or screen
  depends on the old 43-sign shape.
- Should-fix, both done: (1) the docs/005 amendment said recovery codes are also checked as the
  reauthentication factor, which takes only `totp`: corrected; (2) a comment in `auth_flow.py`
  still said 256 bits: now 60.
- Note taken: `str.upper()` turned a dotless i or a long s into I or S, so non-ASCII letters
  were read as a code: the canonical form now needs ASCII text (test added). Notes kept: every
  caller of `matches` now removes white space around the candidate (the Owner's account recovery
  and the code lifecycle too; harmless, documented in docs/005); `encode` still refuses spaces
  inside its input, which only generated codes reach; the generator test keeps its locked name
  and note (256 bits) with a docstring saying 60 bits.

## Review round 2 (one fresh agent, read-only, no files written)

- No blocker. Every round 1 fix checked: the ASCII check runs on the stripped candidate; a
  dotless i, a long s, the Kelvin sign, full-width letters and a space or NUL inside a code are
  never read as a code; no text raises.
- Should-fix (two contract notes), both done: (1) `matches` raised for a candidate that is not
  text, where it answered no match before: it answers False again (tested with None); (2) the
  canonical form also removed tabs and control separators, more than the docs say: it now
  removes only ASCII spaces and dashes (a tab or control separator inside a code does not match;
  tested).
- Notes taken: the duplicate check of a new set compares canonical forms (the issue and replace
  routes, and the `auth_flow.py` helper that makes a set), so a generator that gave the same code in two cases would be
  refused; the first new test is renamed `test_a_recovery_code_is_twelve_symbols_of_the_hand_copy_alphabet`
  (the alphabet has 32 symbols) and checks the alphabet itself; the match test also tries
  control separators and non-ASCII letters. Notes kept: no new timing or enumeration side effect
  (only empty or white-space text skips Argon2, which depends on what was typed, not on a
  secret).

## Review round 3 (one fresh agent, read-only, no files written)

- No blocker. Every round 2 fix checked as correct.
- Should-fix, both done without a round 4 (a new test and text, under the round 3 rule):
  (1) no test proved the canonical duplicate check: two new tests give a generator two
  spellings of one code (7KQ4-M2XD-9PRT and 7kq4m2xd9prt) and expect the issue and the
  replacement to be refused before anything is stored or invalidated; both fail when the check
  goes back to comparing the codes as written; (2) this record and docs/010 said the server
  set-up also compares canonical forms: it compares the codes as written
  (`bootstrap_cli.py`, `initial_owner_bootstrap.py`), which is safe because its generator only
  writes canonical codes; the wording is corrected and the code is left as it is.
- Notes kept: `matches` removes any white space at the ends before the ASCII check (cannot widen
  a match); a verifier that is not text still raises (older than L7a; every caller passes text).

## Runs

- Static checks: ruff, format and mypy (backend); prettier, eslint and tsc (frontend): clean.
- Unit: the recovery-code, issuance, regeneration, auth flow, API and bootstrap modules passed;
  the traceability audit 29 passed.
- Frontend: `SignInScreens.test.tsx` and `App.test.tsx` 79 passed.
- T1 (targeted PostgreSQL: the recovery-code flow, sign-in, issuance and regeneration modules
  and the bootstrap): 100 passed.
- T2 (the same PostgreSQL modules and the security unit tests, after rounds 2 and 3): 118 passed.
- Put onto `implementation/foundation` after V1-059 part A (DL-082); the `ops/traceability.json` appends of both are kept. The full runs come at the end of L7b.
