# V1-056 sub-slice 10e-2b-4e-2b-3 — the two-person reversal of a receipt recorded while a Refund is out — review record

Sub-slice: 10e-2b-4e-2b-3 (owner answer (a) to Q-2026-10-19-137, with the narrowing of its review
rounds 2 and 3: a wrong receipt must always be fixable by two people). Migration `20270105_162`
(one new internal function, two exact-text patches of one replacement each). Base commit:
3a80dd6. Built on 2026-10-19 in one fresh session. Not pushed.

## Built

- Migration `20270105_162_deposit_receipt_reversal_after_refund.py`: new internal
  `app.deposit_receipt_reversal_after_refund_allowed(receipt, reversal, actor)` (no grant);
  `app.reverse_deposit_receipt` and `app.validate_deposit_receipt_reversal` let the two-person 8r
  reversal pass the unresolved-Refund refusal when it holds. A relaxing change.
- Committed tests changed (owner answer turns a refusal into an acceptance; standing rules): one
  renamed test in `test_deposit_receipt_refund_out_migration.py` (its end check is HEAD's), the
  module docstring and three unused imports; 27 head-revision strings.
- New module `test_deposit_receipt_reversal_after_refund_migration.py`.
- Docs: docs/004 (DB-DEP-002, DB-DEP-007), docs/010, plan (pre-code design, slice 11 receipt-route
  note, slice 12 known limit), questions and run rules (owner answers of 2026-10-19);
  traceability (one renamed entry changed in place after entry 1,598; new entries appended).

## Runs

| Run | Result |
|---|---|
| D1 | catalog dump of the receipt reversal functions (no `REDACTED` marker), saved in `~/Development/prm-run-logs/v1-056-10e-2b-4e-2b-3-D1.txt` |
| FF1/FC1/L1/Y1 | passed (long-line search and import sort first; formatter changed nothing) |
| M1 | passed |
| T1 | 24 passed |
| U1 | 3866 passed |
| M2 | passed |
| P1 | 2361 passed (the deprecation warning and the known pydantic alias warnings) |
| FF2/FC2/L2/Y2 | passed (after the round 1 fixes; import sort first) |
| M3 | passed (the migration changed in round 1) |
| T2 | 25 passed |
| U2 | 3866 passed |
| P2 | 2362 passed (the deprecation warning) |
| FF3/FC3/L3/Y3 | passed (after the round 2 fixes; long-line search and import sort first) |
| T3 | 8 passed (the new module, the only test file changed since T2) |
| U3 | 3866 passed (before round 3) |
| M4 | passed |
| P3 | 2362 passed (the deprecation warning and the known pydantic alias warnings; before round 3) |
| FF4/FC4/L4/Y4 | passed (after the round 3 fixes; FF4 first ran in the same call as the import sort, a run-rule slip, and was run again alone: FF4-rerun, unchanged) |
| T4 | 8 passed (the new assertions hold) |
| U4 | 3866 passed |
| M5 | passed |
| P4 | 2362 passed (the last full run before the commit) |

Full outputs in `~/Development/prm-run-logs/v1-056-10e-2b-4e-2b-3-*.txt`, one file per attempt.

## Review round 1 (fresh read-only subagents, during P1; told to write no files at all, scratch files included, and to run no test, script or database command)

Independent: no blocker, 3 should-fix (all text), 5 notes. Security: no blocker, 3 should-fix (two
tests, one text), 5 notes. Both confirmed that the rule matches the owner answer, that each
refusal test isolates one condition, that the patches match the current text once with sound
precedence, that NULLs fail closed, that the new function has no grant, and that the binding
cannot be met by another path (the reversal id is the table's key, the receipt is reversed once,
the returns use fresh random ids, the corrections need a closed Settlement; the one-call path:
see round 2, item 3).

Fixed:

1. Both, should-fix (text): the v2 function is also called by `app.confirm_payment_return` in its
   branch with no recovery (a fresh random reversal id) and by the owner one-call path (corrected
   in round 2, item 3); plan design
   and docs/004 corrected.
2. Independent should-fix 1 (text): docs/010 as-built and "Updated tests" entries (the rename).
3. Independent should-fix 2 (text): plan slice 11 receipt-route note, plan slice 12 known limit
   (done, and what stays), docs/004 DB-DEP-007 (the posting sentence and a 10e-2b-4e-2b-3 line).
4. Security should-fix 1 (tests): the binding test now also refuses (55000, rolled back) hand-built
   rows that reuse the reversal id of (a) a withdrawn draft, (b) a rejected draft, (c) a draft
   whose CONFIRMED decision is dated before the transaction began (the check passes once the same
   decision is dated in it), (d) another receipt's draft confirmed in the same transaction (D's
   receipt after a 10,000 increase of the required total); plus the owner one-call path
   (independent note 3). Set-ups (the reviewer's): A 10,000, a 10,000 Pet Refund-review Refund,
   C 10,000; for (c), user triggers of `app.financial_draft_decisions` disabled inside the
   rolled-back transaction.
5. Security should-fix 2 (test): a waiting `PAYMENT_RETURN` draft of A (no recovery planned, C's
   money covers the Refund) is stale (P5S02) once C's receipt is reversed; recorded again it plans
   and charges back 10,000; the Deposit holds 0 and the Refund's net is 0.
6. Notes taken: the helper's comment and docs/004 say the decision is bound by the reversal id, not
   by the time alone, and the helper also binds the draft's Property and Deposit (security note
   1, independent note 1; fail closed); the least-privilege test asserts only the owner holds any
   privilege on the new function (security note 5); the slice 12 list names the stuck case of a
   receipt whose money a later event took and gave back (security note 3), same-time events
   (security note 4) and the one-holder policy (security note 2, DL-069).
7. Not taken (optional): the one-cent dip with a second Pet Refund-review Refund (independent note
   4; set-up: A 10,000; Refund 1 10,000; C 10,000; a 1-cent Pet Refund-review Refund under the same
   review, then fully returned; C's reversal refused); condition (2) stays untested (independent
   note 2: the trigger and the recorder refuse first after closure).

## Review round 2 (fresh read-only subagents, during P2; same instructions)

Independent: no blocker, 2 should-fix (text), notes. Security: no blocker, 3 should-fix (two
tests, one text), 5 notes. Both confirmed every round 1 fix, that the new Property and Deposit
bindings cannot wrongly refuse the real 8r path (the recorder stores the Property and the payload
is `v_input || v_source`), the rule, the precedence of both patches, the cent figures of every
test, the changed committed test against HEAD (end check unchanged, nothing weaker), the 27
revision strings, and traceability (first 1,598 entries identical; one entry changed in place,
the rest appended). Fixed under the round-3 rule (tests and text):

1. Security should-fix 1 (test): (a) and (b) decided their drafts in an earlier transaction, so
   the time condition alone refused them. Now the withdrawal (`app.withdraw_financial_draft`) or
   rejection (`app.reject_financial_draft`) runs in the same owner transaction as the hand-built
   row, so only the CONFIRMED filter refuses it (rolled back; the draft is then withdrawn through
   the service).
2. Security should-fix 2 (test): in (c), after the re-dated decision passes, the helper returns
   false for another actor, another reversal id, A's receipt, and (with the user triggers of
   `app.financial_drafts` disabled inside the rolled-back transaction) a draft whose payload names
   another Deposit (round 3: A's receipt also fails conditions (3) and (4), so (d) alone shows the
   receipt binding). The Property binding stays untested (the fixtures share one Property; fail
   closed, defence in depth).
3. Independent should-fix 1 and security should-fix 3 (text): the owner one-call path passes an id
   its caller chooses, not a random one; it gains nothing because it has no application grant
   since migration 87 and because an id a waiting draft of that Deposit names meets the
   waiting-draft refusal, one a waiting draft of another Deposit or a withdrawn or rejected draft
   names fails condition (1) (round 3, security note 1), and one a confirmed draft names was
   already written by that confirm. Corrected in docs/004, the plan design and this record.
4. Independent should-fix 2 (text): docs/010 points to the "10e-2b-4e-2b-3 pre-code design" entry.
5. Notes taken: `hand_built` rolls back explicitly, and test (d) rolls back through the connection
   context on its expected path (security note 1; round 3 note 3); the plan's
   reading (3) says the REPEATABLE READ stale check sees only events committed before the
   confirm's snapshot and the guard catches later ones (security note 2); the least-privilege
   test asserts `prosecdef` and the search path (security note 3); docs/004 names the DL-069
   one-holder policy (security note 4); the plan's rule (1) names the round 1 bindings, the slice
   11 screen text says the reversal "may be refused" (independent notes); the module docstring
   names the round 1 and 2 tests. Not taken: re-running the hand-built insert after the re-dated
   decision in (c) (the helper call shows it), a separate test of the inner patch (the trigger
   backs it up), a `tgenabled` assertion after (c).

## Review round 3 (fresh read-only subagents, during P3; same instructions)

Independent: no blocker, one should-fix (text), notes. Security: no blocker, two should-fix (one
test, one test-or-text), three notes. Both confirmed every round 2 fix, the rule, the rollbacks,
the cent figures, the changed committed test against HEAD, the 27 revision strings and
traceability (first 1,598 entries identical; one entry changed in place; seven appended).

Fixed under the round-3 text rule of 2026-10-16 (text fixes and new assertions in tests already
built and green; no code, migration or fixture change; no round 4):

1. Independent should-fix 1 and security should-fix 2 (text): the (c) call with A's receipt does
   not isolate the receipt binding (A's receipt also fails conditions (3) and (4)); the test's
   docstring and comment, this record and the traceability note now say that (d) shows the receipt
   binding alone.
2. Security should-fix 1 (new assertions): (d) wraps D's confirm and the hand-built row in one
   `pytest.raises`, so a refusal of D's confirm would also pass. Two new assertions check the
   error's PL/pgSQL context: it names `validate_deposit_receipt_reversal` and not
   `confirm_deposit_receipt_reversal_draft`, so the refusal is the hand-built row's insert check.
3. Notes taken: the one-call case also asserts SQLSTATE 55000 (independent note, a new
   assertion); the module docstring's list reads as the list of tests (independent note);
   docs/004 DB-DEP-002 rewrapped and DB-DEP-007 says "a receipt, recorded strictly after every such
   Refund, whose money no later balance event relied on" (independent notes); docs/004, the plan
   and this record say an id a waiting draft of another Deposit names fails condition (1)
   (security note 1); round 2 item 5 corrected for (d)'s rollback (security note 3).
4. Not taken: security note 2 (the migration docstring says "confirmed in this transaction"; the
   SQL comment and docs/004 say "since this transaction began", which is accurate): the round-3
   rules exclude a migration change other than a user-facing message, so the docstring stays, for
   the owner; independent notes on asserting P5S02 by SQLSTATE in the stale test (the exception
   class maps it) and on the plan's design test list (docs/010 and this record give the as-built
   set).
