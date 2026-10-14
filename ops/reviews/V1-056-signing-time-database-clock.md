# V1-056 signing time from the database clock — review record

Sub-slice: signing time from the database clock (owner answer (a) to Q-2026-10-14-110). No
migration. Base commit: 4b6841a (sub-slice 10e-3d-2b-2).
Built on 2026-10-14. Not pushed.

Rule IDs: BR-AUDIT-003; API-036, API-038; UI-038, UI-040.
Owner answer (a) to Q-2026-10-14-110: "A Lease signing time comes from the database's own clock,
not from the browser. This also means nobody can make a signature look earlier by setting a
laptop clock back. Build it next, as a small sub-slice, with the route and screen changes it
needs. If it needs a tightening, or a change to committed tests beyond what this answer covers,
ask me first." Design: ops/V1_056_PLAN.md, bullet "Signing time from the database clock".

## Built

- Routes (`backend/src/property_rental/lease_api.py`): `LeaseSignatureSource`
  (`PATCH /lease-signers/{signer_id}`) and `LeaseSignSource` (`POST /leases/{lease_id}/sign`)
  drop `signed_at`; `extra="forbid"` stays, so a body that still sends it is refused with 422
  (field `body.signed_at`) before the handler runs; both routes pass `signed_at=None`.
- Service (`backend/src/property_rental/lease.py`): `LeaseRecordSignatureCommand.signed_at` and
  `LeaseSignCommand.signed_at` become `datetime | None` (a given time must still carry a time
  zone); both calls pass `COALESCE(%s::timestamptz,statement_timestamp())`, so with no time the
  database functions receive the statement time their own checks compare with. No database
  function changes.
- Screen and client: `LeaseSignatureSource` in `frontend/src/leaseClient.ts` drops `signed_at`;
  `frontend/src/LeaseManagement.tsx` no longer sends `new Date().toISOString()` for a Signer
  signature or the Lease signing.
- Implementer's reading (named for the owner; both round 1 reviewers found it acceptable): the
  service commands keep an optional explicit time, which no route passes, so the committed
  database tests keep checking the database's own refusals through the service.
- Committed tests changed (owner answer covers the request shape; each compared with HEAD by the
  round 1 independent reviewer: nothing weaker): the bodies of
  `test_lease_api.py::test_signer_signing_renewal_and_termination_are_explicit_commands` and
  `test_lease_api_migration.py::test_http_create_update_sign_and_replay_use_runtime_role` drop
  `signed_at`; TEST-FE-186's source drops it;
  `test_lease_lifecycle_migration.py::test_commands_are_idempotent_versioned_audited_and_preserve_signer_rules`
  gains one line, `assert additional_signature.signed_at is not None`, so the type check accepts
  its arithmetic on the now optional time.
- New tests: `test_lease_api.py::test_signing_routes_take_no_signing_time_from_the_request`,
  `test_lease.py::test_signing_commands_accept_no_time_and_keep_the_time_zone_rule`,
  `test_lease_api_migration.py::test_http_signing_time_is_the_database_time`, TEST-FE-674 and
  TEST-FE-675 (`frontend/src/LeaseManagement.test.tsx`). Traceability: five entries appended.
- Docs: docs/002 BR-AUDIT-003, docs/005 API-036 and API-038, docs/006 UI-040, docs/010, the plan,
  ops/V1_056_QUESTIONS.md (owner answers; new Q-2026-10-14-112), ops/V1_055_RUN_RULES.md (owner
  answer 4: design changes during a build).

## Runs

Static checks each in its own call, formatter first. Outputs in `~/Development/prm-run-logs/`
(`V1-056-signing-time-*`); every targeted and full run under `caffeinate -dims`.

| Run | Kind | Result | Cause |
|---|---|---|---|
| — | backend formatter, format check, lint | clean | first |
| Y1 | backend `mypy` | 3 errors: `datetime \| None` arithmetic in the committed lifecycle test (`operator`, `arg-type`); `unreachable` after narrowing in the new route test | cause A (types, optional time in a committed test) 1 of 2; cause B (types, narrowing in a new test) 1 of 2 |
| — | backend formatter, format check, lint, `mypy` | clean | after the fixes |
| — | frontend formatter, format check | clean | first |
| L1 | frontend lint | 2 errors `@typescript-eslint/no-unsafe-assignment` (`expect.any` in the two new tests) | cause C (frontend lint) 1 of 2 |
| — | frontend formatter, format check, lint, type check | clean | after the fix |
| F1 | frontend tests, full | 38 files, 1594 passed | first |
| — | frontend build | built (the known chunk-size note) | first |
| T1 | PostgreSQL targeted: the seven signing modules | 48 passed | first |
| U1 | backend unit, full | 3804 passed, 1996 skipped, 1 known warning | first |
| M1 | migration-only check | passed (head `20261208_134`, 133 upgrades) | before P1 |
| P1 | PostgreSQL full | 2160 passed, 3 known warnings (Starlette; pydantic `UnsupportedFieldAttributeWarning` twice) | first |
| — | backend formatter, format check, lint, `mypy` | clean | round 1 fixes |
| T2 | PostgreSQL targeted: `test_lease_api_migration.py`, `test_lease_lifecycle_migration.py` | 10 passed | round 1 fixes |
| U2 | backend unit, full (covers the round 1 changes of `test_lease.py` and `test_lease_api.py`) | 3804 passed, 1996 skipped, 1 known warning | round 1 fixes |
| M2 | migration-only check | passed (head `20261208_134`) | before P2 |
| P2 | PostgreSQL full | 2160 passed, 2 known warnings (Starlette; pydantic `UnsupportedFieldAttributeWarning` once) | round 1 fixes (test files changed after P1) |
| U3 | backend unit, targeted: `tests/test_traceability.py` | 28 passed | round 3 note (traceability notes changed after U2) |

Corrections used: cause A (types, optional time in a committed test) 1 of 2; cause B (types,
narrowing in a new test) 1 of 2; cause C (frontend lint, `no-unsafe-assignment`) 1 of 2. No
`Signature evidence is invalid` failure in any run.

## Review round 1 (fresh read-only subagents, during P1; told to write no file anywhere and run nothing)

Independent: 0 blockers, 3 should-fix, 7 notes. Security: 0 blockers, 1 should-fix, 3 notes.

- Should-fix (both): the new database test's Lease signing check was circular: `app.sign_lease`
  writes the `lease.sign` command row with the time it was given (migration 24 line 463), not
  with the statement time, so `leases.signed_at = lease_commands.occurred_at` holds for any time.
  Fixed: the Lease signing time is compared with `app.lease_signing_outcomes.occurred_at`, which
  `app.sign_lease_with_reservation` stamps with `statement_timestamp()` (migration 69); the
  `lease.sign` command row is now only counted (one row). The test comment, the plan text and the
  traceability note are corrected.
- Should-fix (independent, test): no retry test of the Lease signing route. Fixed: the same
  request (same Idempotency-Key, If-Match "3" and body) is sent again after the Lease reached
  version 4; it answers 200 with the first signing time (only a replay can), and one `lease.sign`
  row and one outcome row remain.
- Should-fix (independent, text): docs/010 had no entry for the sub-slice and the plan said "No
  assertion changes" although the lifecycle test gained one line. Fixed: docs/010 sub-slice and
  "Updated tests" entries name each committed-test change; the plan names the added line; this
  record is written.
- Notes taken (stricter tests): the two route 422s and the database test's 422 now pin
  `error.fields == ["body.signed_at"]` (as `test_invoice_api.py` does); the unit test also
  asserts that a given time changes the request digest (the time stays bound into it).
- Notes for the owner, written as Q-2026-10-14-112 (nothing waits): other times the screens still
  take from the device clock (the termination `occurred_at`, which `app.terminate_lease` refuses
  when later than the statement time, as signing did; the Reservation `approved_at` and the
  holding deposit receipt's `received_at`); the runtime database role can still pass an earlier time to the two database functions
  directly (closing that is a tightening that changes committed tests).
- Other notes: `statement_timestamp()` in the outer SELECT is the value the called functions
  see, so the "not later than the statement time" check cannot fail, and the order checks hold
  (earlier statements stamped `added_at` and earlier signatures); the 422 echoes only the field
  location, never the value; the SQL is built from constant pieces with bound parameters; the
  capability, CSRF and If-Match checks run unchanged before the service call; a 422 before 401 or
  CSRF is how every `extra="forbid"` route behaves; an old browser tab gets a 422 until it
  reloads; the in-memory test flow now returns a SIGNED resource with no time (HEAD never asserted
  it); no secret or personal data in the diff or the run outputs; the traceability manifest's
  existing entries are byte-identical, five appended.

## Review round 2 (fresh read-only subagents, during P2; told to write no file anywhere and run nothing)

Independent: 0 blockers, 3 should-fix, 6 notes. Security: 0 blockers, 1 should-fix, 4 notes.
Both checked each round 1 fix against the migrations (the Lease signing time against the
signing outcome row, which `app.sign_lease_with_reservation` stamps with `statement_timestamp()`;
no later migration patches either function), and the independent reviewer compared every changed
committed test with HEAD (`git diff HEAD -U0`: two removed body lines and one removed body line in
the two backend tests, one removed source line in TEST-FE-186, one added always-true type
assertion in the lifecycle test): acceptable, nothing weaker.

- Should-fix (both, text): Q-2026-10-14-112 point 2 said the signing outcome and audit rows are
  stamped with the real time "in any case"; the Signer's and the Lease's `signed_at` and the
  `lease.sign` history row (which the Lease timeline shows) take a given time. Fixed: the
  question now lists which records keep the database time and which take a given time.
- Should-fix (independent, text): docs/010 and the plan said the committed database tests keep
  checking "a time before the Signer was added"; no committed test does (the explicit-time
  refusals are a Signer signature one day later, and a Lease signing one microsecond earlier than
  a signature and one day later). Fixed in both: the check is unchanged and has no committed test.
- Should-fix (independent, run): no recorded run of `test_lease.py` and `test_lease_api.py` after
  their round 1 changes. Already covered: U2 (full unit suite, 3804 passed) ran after those
  changes; recorded in the table above.
- Notes taken (text): Q-112 point 1 now names the Reservation field (`received_at` of the holding
  deposit receipt), the 5-second allowance the database gives `received_at` and `approved_at`,
  and that the database-time rule may not fit a received-money time; it also names the mixed
  clocks (database signing time, device termination time; a termination recorded within a slow
  device's lag after the signing is refused); docs/006 UI-040 says where the screen shows the
  times (Signer rows, Lease timeline); the unit test's traceability note names the digest-binding
  assertion.
- Other notes: the equal `signed_at` on the two retries is not the proof (the flow re-reads the
  Lease); the 200 answer is (the test comment says only a replay can give it); this record quotes
  the owner's words verbatim ("laptop clock", "ask me first"), the questions file and docs/010
  paraphrase them; no secret in the diff, the untracked record or the run outputs (the only hits
  are prose words and a migration title); no env file listed.

Under the owner's round-3 rule of 2026-10-13 (round 2 had no blocker; every should-fix was text
or a run already done), the fixes are made and round 3 runs without asking. The round 2 fixes are
text only (questions, plan, docs/006, docs/010, traceability notes, this record), so U2 and P2
stay the last full runs before the commit.

## Review round 3 (fresh read-only subagents, after P2; told to write no file anywhere and run nothing)

Independent: 0 blockers, 0 should-fix, 3 notes: clean. Security: 0 blockers, 0 should-fix,
2 notes: clean.

- Independent: confirmed each round 2 fix against the migrations (19, 23, 24, 69) and the code;
  compared every changed committed test with HEAD again (`git diff HEAD -U0`: three removed body or
  source lines, one added always-true type assertion; at HEAD none asserted the given time):
  nothing weaker; checked from file times that U2 and P2 ran after the last code or test change
  (last test change 16:14:51; U2 16:17 to 16:22, P2 16:17 to 16:32; later changes are text only).
  Notes, fixed before the commit: docs/010 said both round 1 reviewers compared the tests (only
  the independent reviewers did; reworded) and had no review-rounds entry (added); the traceability
  notes changed after U2, so its file is checked by a JSON parse and `tests/test_traceability.py`
  before the commit; a stray space in this record's quote of the SQL
  (`COALESCE(%s::timestamptz,statement_timestamp())` in the code).
- Security: no request can set or influence the signing times (the two route builders pass
  `None`; no other builder, script, worker or CLI; replays read no time); SQL constant with bound
  parameters (10 placeholders, 10 values); capability, CSRF, If-Match and actor checks unchanged
  and before the service; the 422 returns field paths only; Q-2026-10-14-112 accurate; the
  standard secret scan of the diff, this record and the nine run outputs is clean, no env file.
  Notes: Q-112 point 2 could also name the history copies of the given time (added); the service's
  optional explicit time stays the named implementer's reading.
