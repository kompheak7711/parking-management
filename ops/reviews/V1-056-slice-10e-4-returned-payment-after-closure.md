# V1-056 sub-slice 10e-4 — a returned Payment used on a closed Lease after closure: review record

Sub-slice: 10e-4 (migration `20261201_127`). Base commit: d9f6d52. Built in one session on
2026-10-13; this record is committed with it (see git log; the commit right after d9f6d52). Not
pushed.

Rule IDs: BR-SETTLE-013, BR-SETTLE-016, BR-PAY-042; DB-PAY-009, DB-SETTLE-005; owner answer (c)
to Q-2026-10-11-81 point 3 and the owner answer to Q-2026-10-11-82. Design: ops/V1_056_PLAN.md
(the "10e-4" bullets: pre-code design and as built).

The same commit records the owner answers of 2026-10-13 (Q-2026-10-12-96 (a), sub-slice 10e-3c;
Q-2026-10-12-97 (a), sub-slice 10e-3d; the two stricter 10e-2 assertions accepted and the new run
rule; placement of 10e-3c, 10e-3d and 10e-2d) in docs/010, the questions file, the run rules and
the plan, and opens Q-2026-10-13-98 (a Payment that names no Lease, used on a closed Lease, with
part refunded: the Refund gets a no-Lease charge; nothing waits).

## Built

- Migration `backend/migrations/versions/20261201_127_returned_payment_used_after_closure.py`,
  exact-text patches only (no new function, constraint, trigger or grant):
  - `app.settlement_returned_payment_source`: new key `used_on_lease` (the Payment names the
    Settlement's Lease, or an active allocation of the Payment, or an active application of one of
    its Credits that is not reversed, is on an Invoice of that Lease or a Late-payment Charge of
    such an Invoice).
  - `app.assert_settlement_returned_payment_allowed`: with no closed Settlement relying on the
    Payment, it passes when `used_on_lease` is JSON `true` or a planned recovery is charged on this
    Settlement's Lease; in that branch a source without a `relied_on` key is refused (55000).
  - `app.assert_payment_return_recoveries_allowed`: for the `PAYMENT_RETURN` draft (no Settlement)
    the refusal of a recovery on a closed Settlement's Lease names the returned-Payment correction
    (implementer's wording, from the design the owner kept).
- `backend/src/property_rental/settlement_correction.py`: docstring of the command only.
- Tests: `backend/tests/test_returned_payment_after_closure_migration.py` (8 tests), last in
  `scripts/database-test.sh`.
- Changed committed tests (owner standing rule of 2026-10-11): the 27 head-revision assertions in
  15 modules (`20261130_126` to `20261201_127`); in `test_payment_return_recovery_migration.py`,
  under owner answer (c) to Q-81: `test_the_cases_a_return_still_refuses` (the two no-Settlement
  message checks expect `NAMES_CORRECTION`, was `CLOSED`), `test_the_refused_cases_on_real_sources`
  case (3) (the `PAYMENT_RETURN` refusal has the new message; the correction records the Payment
  with its 300 Refund planned as an `EXTRA_CHARGE`, was the `NOT_RELIED` refusal; the draft count
  names that one draft); names kept, docstrings updated, three unused imports removed. No fixture
  changed.
- `ops/traceability.json`: the notes of the two changed entries; eight entries appended. One batch
  of note changes and two appended entries (review round 1) was made by a count-checked exact-text
  replacement in a short script instead of the Edit tool; the result is the same text edit, and
  `git diff --stat` was checked after it; every other ops/ and docs/ edit used the Edit tool.
- docs/004 (DB-PAY-009 section: as-built paragraph; two older sentences corrected), docs/010,
  the plan, the questions file, ops/NOW.md.

## Runs

Static checks, each in its own call: `ruff check src tests`, `ruff format --check src tests`,
the same two on the new migration file, and `mypy`; clean except the first format check.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| C1 | throwaway catalog read (migration upgrade, function definitions dumped to the job scratch directory; not a test run) | 126 upgrades | pre-code design | not saved |
| M1 | migration-only check | passed | first | not saved |
| F1 | `ruff format --check src tests` | 1 file would change | cause A (format, my new test), correction 1 of 2 | not saved |
| T1 | PostgreSQL targeted: new module, payment return recovery, returned Payment, payment return, return reversal | 49 passed, 2 failed | cause B (my test helper read the Refund id from the wrong key), correction 1 of 2 | `V1-056-slice-10e-4-targeted-test-run.txt` |
| T2 | PostgreSQL targeted: new module | 6 passed | cause B fixed | `-targeted-test-run-2.txt` |
| M2 | migration-only check | passed | before P1 | not saved |
| U1 | backend unit, full (caffeinate) | 3802 passed, 1939 skipped, 1 warning (known) | first full unit run | `-unit-test-run.txt` (excerpt) |
| P1 | PostgreSQL full (caffeinate) | 2103 passed, 2 warnings (known kinds) | first full run | `-full-test-run.txt` |
| M3 | migration-only check | passed | round 1 fixes | not saved |
| T3 | PostgreSQL targeted: new module, payment return recovery, returned Payment, payment return | 41 passed | round 1 fixes | `-targeted-test-run-3.txt` |
| U2 | backend unit, full (caffeinate) | 3802 passed, 1941 skipped, 1 warning | round 1 fixes | `-unit-test-run-2.txt` (excerpt) |
| P2 | PostgreSQL full (caffeinate) | 2105 passed, 3 warnings (known kinds) | round 1 fixes, before round 3 | `-full-test-run-2.txt` |

Read-only search of every backend test before T1 and before P1: the patched functions and the
changed messages are used only in the new module, `test_payment_return_recovery_migration.py`,
`test_settlement_returned_payment_migration.py` (its `NOT_RELIED` Payment names no Lease and is
not used, so it stays refused) and `test_payment_return_migration.py`; no test compares the
returned-Payment source keys. The warnings are the known Starlette deprecation and the pydantic
`UnsupportedFieldAttributeWarning` in `test_credit_refund_api_migration.py`. After P2 only text
changed (docs, plan, questions, docstrings in the migration and the new test module, this record).
Secret check of every saved output: no database URL with a password, no `password=` value, no
64-character hex secret. The full unit outputs are in `~/Development/prm-run-logs/`; the excerpts
keep the output without the SKIPPED lines of the summary.

## Review round 1 (fresh read-only subagents, during U1 and P1)

Security: 0 blockers, 1 should-fix, 5 notes. Independent: 0 blockers, 3 should-fix, 10 notes; no
committed test weaker.

Fixed: security SF1 (the relaxed branch passed a source without `relied_on` and loose boolean
strings: refused, tested); independent SF1 (real-path tests of the allocation branch with a
reversed allocation as a control, and of the Credit-application branch), SF2 (docs/004 and
docs/010), SF3 (plan entries for 10e-3c, 10e-3d, 10e-2d and the order); notes on docstrings, stale
drafts, dollars in the owner examples, link and Settlement-row assertions, the changed committed
docstring. Answered in writing (docs/010): the two-Lease and two-recovery limits, the named-Lease
way in, the message staff do not see until slice 11c, the message wording.

## Review round 2 (fresh read-only subagents, during U2 and P2)

Security: 0 blockers, 0 should-fix, 3 notes. Independent: 0 blockers, 2 should-fix, 9 notes; no
committed test weaker.

Fixed as text: independent SF1 (the docs and docstrings overstated when a Refund gets an
`EXTRA_CHARGE`: the 10e-1c rules put a Payment Refund on the Lease the Payment names;
Q-2026-10-13-98 asks the owner to confirm), SF2 (the plan's as-built bullet, this record); notes on
the older docs/004 sentence, the named-Lease way in, the 22023 refusal, the two-Lease limit with a
recovery, slice 11c, the Q-96 example in dollars. Slice 12 items: the check function could
require every list key of its source as an array (pre-existing, unreachable); a
Payment-of-another-Property refusal test on the relaxed path.

## Review round 3 (owner standing rule; U2 and P2 ran on the final code before it)

Independent: 0 blockers, 0 should-fix, 7 notes; it compared every changed committed test with HEAD
(27 head-revision lines in 15 modules, revision only; `test_payment_return_recovery_migration.py`
only in the cases owner answer (c) covers) and found nothing weaker; traceability: two notes
changed, eight entries appended. Security: 0 blockers, 0 should-fix, 6 notes; the saved run
outputs hold no secret.

Fixed as text after round 3: the placement quote (the owner said "before 10h" for Q-96 and Q-97),
a long docs/004 line, the command docstring (all three ways in), this record (line 4, this
section, the final static checks), ops/NOW.md. Final static checks after the last text change, each
in its own call: `ruff check src tests` clean, `ruff format --check src tests` clean, `mypy` clean
(the migration file was last checked clean after the round 2 text fixes). Left as notes (slice 12
items or owner points): a migration SQL comment typo ("a Refund of whose value"; changing it would
change the stored body); the check could also refuse a source built for another Settlement
(defence in depth; no caller can pass one); tests of a stale draft after the qualifying allocation
is reversed and of a Payment of another Property on the relaxed path; Q-2026-10-13-98 is committed
with (a) before the owner's confirmation (the `PAYMENT_RETURN` draft already gave that Payment the
same no-Lease charge before revision 127). No code changed after P2.
