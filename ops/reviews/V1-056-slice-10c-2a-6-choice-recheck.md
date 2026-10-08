# V1-056 sub-slice 10c-2a-6 — Customer choice checked again in the shared step: review record

Sub-slice: 10c-2a-6 (migration `20261110_106`). Base commit: 902abe2 (the 10c-2a-6 pre-code
design and stop for Q-2026-10-08-54). Not committed (commit hash in ops/NOW.md once committed).

Rule IDs: BR-DEP-027, BR-SETTLE-013, BR-AUTH-010; owner answer 3 to Q-2026-10-07-44, owner answer
1 to Q-2026-10-08-52 (approved tightening), owner answer to Q-2026-10-08-54 (option (a)).

## Built

- Migration `20261110_106`: `app.post_settlement_correction_plan` patched in place (exact-text
  patch through `pg_get_functiondef`; owner, SECURITY DEFINER, settings and privileges kept):
  right after the step's locks and before it reads the plan and compares the result, a
  `CUSTOMER_CHOICE` text for the remaining Pet Deposit equal to the confirmed Final Settlement's
  choice or to another confirmed correction's choice of the same Settlement is refused (55000, the
  recorders' messages). The current draft's own decision is left out by its id. Covers every
  variant that runs the step (`REFUND`, `PET_DAMAGE_RECLASSIFICATION`, later ones).
- Service: `confirm_refund` docstring names the refusal; no logic change (55000 is a conflict).
- Tests: new module `test_settlement_correction_choice_recheck_migration.py` (2 tests at P1, 3
  after review round 1; last in `scripts/database-test.sh`); 26 head-revision assertions in 14
  modules; the committed 10c-2a-2 test `test_a_br_dep_027_termination_after_closure` changes its
  choice text only (owner answer to Q-2026-10-08-54); traceability: 3 entries appended (2 at P1,
  1 after review round 1).
- Docs: docs/004 (the step paragraph; the `REFUND` paragraph "when the draft is recorded and again
  in the shared step at the confirm"); docs/010 owner answer, sub-slice entry and updated-tests
  entry; questions file (Q-2026-10-08-54 answered); plan (10c-2a-6 pre-code design and answer).

## Runs

Static checks clean, each in its own tool call (`make backend-format-check`, `make backend-lint`,
`make backend-typecheck`). Migration-only check (the scratchpad copy of `scripts/database-test.sh`
regenerated from the current script, running `uv run --extra dev alembic upgrade head`): 105
upgrades, reached `20261110_106 (head)` at the first attempt. Read-only search of all backend
tests: the 14 head-revision modules; every test that runs the step (`post`, `POST_PLAN`) or uses a
Customer choice (10c-2a-2, 10c-2a-3 and 10c-2a-5 modules; the Final Settlement modules use a choice
only in Settlement drafts, which the step does not read); only the 10c-2a-2 test above reuses a
choice in a correction.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U1 | backend unit, full (under `caffeinate -dims`) | 3606 passed, 1788 skipped (every skip a database URL reason), 1 warning (Starlette) | first run of 10c-2a-6 | `V1-056-slice-10c-2a-6-unit-test-run.txt` |
| P1 | PostgreSQL, full (under `caffeinate -dims`) | 1951 passed, 1 warning (Starlette) | first run of 10c-2a-6 | `V1-056-slice-10c-2a-6-full-test-run.txt` |

No correction.

## Review round 1 (2026-10-08; fresh read-only subagents, given the diff, the rule IDs, the owner answers, the takeover file and this record)

Independent: 0 blockers, 0 should-fix, 4 notes. Security: 0 blockers, 0 should-fix, 3 notes.

- Untested Final Settlement branch (independent N1 and security N1, the same note; fixed, test
  only): since the committed 10c-2a-2 test uses a new choice text, no test ran the step's refusal
  of the Final Settlement's own choice. New test
  `test_the_step_refuses_the_final_settlement_s_own_choice`: the set-up of that test as at HEAD
  (a hand-built correction reusing `CHOICE.customer_choice`), refused by the step (55000), the
  draft pending, no correction row, balances unchanged.
- "Not stale" claim (independent N2; fixed, test only): the owner's-case test now asserts that the
  refused draft's source revision and recorded step result equal those of the draft recorded with
  another choice, which then confirms; so without the re-check the refused draft would have
  confirmed.
- Exact body (security N2; fixed, test only): the forward-only test asserts the new body is
  exactly the old one with the single replacement (`STEP_REPLACEMENTS`).
- Wrap (independent N3; fixed): the docs/004 line re-wrapped.
- Committed test (independent N4, as the owner asked): compared with HEAD; only the
  `customer_choice` text and a two-line comment changed; name, set-up, `staff_reason` and every
  assertion identical; not weakened.
- No index for the choice queries (security N3; slice 12 item, not changed): the queries scan
  every financial draft by `kind` and `payload->>'final_settlement_id'` while the step's locks
  are held; the recorders and the 10c-2a-5 confirm use the same pattern, so all of them change
  together (a Property filter or an expression index).

Both reviewers confirmed: the patch anchor matches the 102 source once and no later migration
replaces the step; variables in scope; the current draft excluded; CONFIRMED decisions only; the
JSON paths of `REFUND`, `PET_DAMAGE_RECLASSIFICATION` and `FINAL_SETTLEMENT` drafts; the
Settlement's draft lock held at the re-check; no exception handler in the chain, so a refusal
rolls everything back; the service maps 55000 to a conflict; owner, SECURITY DEFINER, search path
and privileges kept; the 26 head-revision changes; no historical migration changed.

After the round-1 fixes: static checks each in its own call; the format check failed once on the
new test module (one string assignment wrapped; cause: format, correction 1 of 2), then clean;
lint and type check clean. Migration-only check again (unchanged migration): 105 upgrades, reached
`20261110_106 (head)`. Only the new module, docs and traceability changed since P1.

| Run | Kind | Result | Cause | Output |
|---|---|---|---|---|
| U2 | backend unit, full (under `caffeinate -dims`) | 3606 passed, 1789 skipped (every skip a database URL reason), 1 warning (Starlette) | review round 1 fixes | `V1-056-slice-10c-2a-6-unit-test-run-2.txt` |
| P2 | PostgreSQL, full (under `caffeinate -dims`) | 1952 passed, 1 warning (Starlette); new module 3 passed | review round 1 fixes | `V1-056-slice-10c-2a-6-full-test-run-2.txt` |

## Review round 2 (2026-10-08; new fresh read-only subagents, independent and security, given the diff, the rule IDs, the owner answers, the takeover file and this record)

Independent: 0 blockers, 0 should-fix, 5 notes. Security: 0 blockers, 0 should-fix, 1 note (plus
round 1 N3 carried, not counted). No should-fix, so 10c-2a-6 is committed (hash in ops/NOW.md).
No round 3 is needed.

- Record and plan counts (independent N1; fixed, text only): this record now says 3 tests and 3
  traceability entries; the plan's as-built line names the round-1 test.
- "Not stale" wording (independent N2; fixed, text only): docs/010 choice (1) and the plan say the
  re-check comes before the step's own comparison; a variant's earlier stale checks (the `REFUND`
  confirm's source digest and release) still come first, so a draft that is both stale and reuses
  a choice gets P5S02 and stays pending (harmless; recording it again meets the recorder's check).
- Unpinned filters (independent N3; slice 12 item, tests only): no test shows that a withdrawn or
  rejected correction draft's choice, or another Settlement's correction with the same text, does
  not block a confirm; a missing filter would over-refuse, never bypass; the recorders share the
  pattern.
- Concurrency (independent N4 and security N1, the same note; slice 12 item, tests only): no
  two-connection test of two confirms with the same choice; both reviewers verified by reading
  that both confirms take the Settlement's draft lock before the decision and the re-check runs in
  a later statement at READ COMMITTED with a fresh snapshot.
- docs/004 short line (independent N5; not changed, cosmetic, as at HEAD).
- Committed test: both reviewers compared it with HEAD; only the choice text and a two-line
  comment changed; not weakened.
