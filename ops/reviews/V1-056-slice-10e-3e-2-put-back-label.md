# V1-056 sub-slice 10e-3e-2 — the put-back label on the staff screen — review record

Sub-slice: 10e-3e-2 (owner answer (b) to Q-2026-10-14-109). Frontend only: no migration, no
route, no backend change. Base commit: d95f70b. Built on 2026-10-16. Not pushed.

Rule IDs: BR-CREDIT-006; DB-CREDIT-002, DB-CREDIT-005. Design: ops/V1_056_PLAN.md, "10e-3e-2
pre-code note" and its as-built line (10e-3e entry).

## Built

- `frontend/src/financialActionContext.ts` (the one-call reversal context check): the payment's
  `within_invoice_basis` list and each line's `attribution_basis` list accept
  `PUT_BACK_BY_CORRECTION` for a Credit payment only (`...(allocation ? [] : [...])`, the
  pattern of the existing `THIRD_PARTY_DESIGNATED` entry). Review round 1 fix (fail-closed):
  a line and its payment carry the label together or not at all, as the database's header and
  detail agreement (sub-slice 10e-3e). Only the re-posted rest of a correction's put-back (a
  `credits.apply` Credit payment) reaches this screen; the put-back itself stays refused by the
  `credits.apply` check, and the re-posted rest's one-call reversal stays refused by the
  database (P5S01, migration 100) and reaches the user as a conflict.
- Implementer's reading of "the two lists" (confirmed by both round 1 reviewers): the label stays
  refused on a Payment allocation and its lines, because the database writes it only on a Credit
  payment and its detail; a Credit payment on a Late-payment Charge still accepts only
  `NOT_APPLICABLE` or `CUSTOMER_DESIGNATED`.
- Tests (`frontend/src/financialReferenceClient.test.ts`): TEST-FE-676 (the five synthetic
  Invoice Credit payment reversal contexts of three Credit payments, two not reversed and three
  reversed, with the label on the payment and every line, are accepted and kept as sent);
  TEST-FE-677 (refused, `INVALID_RESPONSE`: an allocation with the label on the payment, on the
  lines and on both; a Charge payment with the label alone, with its lines, and a Charge line
  alone; a Credit payment or a line that carries it alone). No committed test changed.
- Traceability: TEST-FE-676 and TEST-FE-677 appended. Docs: docs/010 (one entry), the plan.
  docs/005 and docs/006 list no labels, so they do not change.

## Runs

| Run | Result |
|---|---|
| FF1/FC1/FL1/FY1 | frontend format (formatter first), format check, lint, type check passed |
| F1 | 1595 passed, 1 failed: TEST-FE-087 (`App.test.tsx`, local sign-in, "Unable to find role=button"), the known intermittent timing test outside this change; recorded and not retried (ops/V1_056_TAKEOVER.md section 5). The new tests passed |
| B1 | frontend build passed (the existing chunk-size warning) |
| U1 | backend unit 3804 passed (traceability) |
| FF2/FC2/FL2/FY2 | passed (after the round 1 fixes) |
| F2 | 1596 passed (after the round 1 fixes; also the first full frontend run after F1's TEST-FE-087 failure) |
| B2 | build passed |
| U2 | 3804 passed |
| FF3/FC3/FL3/FY3 | passed (after the round 2 fixes) |
| F3 | 1596 passed (after the last code and test change) |
| B3 | build passed |

No PostgreSQL run: no migration, backend code or backend test changed. After F3 and B3 only text
changed (docs/010, the plan, this record, ops/NOW.md). Corrections: none counted (no check
failed; F1's only failure is the known intermittent test outside the change).

## Review round 1 (fresh read-only subagents; told to write no file and run no command but git and file reads)

Independent: 0 blockers, 1 should-fix, notes. Security: clean (0 blockers, 0 should-fix, 4 notes).

- Independent should-fix (fail-closed check, fixed): the lines list accepted the label on a line
  of a Late-payment Charge payment or under a payment with another label, which the database
  forbids (migration 41; migration 133 header and detail agreement). Fix option A taken: the
  agreement check in `detail()`, with TEST-FE-677 cases for a Charge line and a Credit payment or
  line alone.
- Notes taken (text and tests): the code comment and TEST-FE-676's name say only the re-posted
  rest reaches the screen (both reviewers); the texts say five contexts of three Credit payments,
  not two; DB-CREDIT-005 in the traceability entries; TEST-FE-676 asserts every line's label; the
  test helper also clears `proposal_generated_at`.
- Security findings: staff cannot choose or send the label (the Apply screen offers no such
  choice; the reversal sends only a reason; the proposal reply check still refuses the label); a
  reversal attempt reaches the database, which refuses it (P5S01); no new data is shown; no
  route, capability, SQL, logging, session or CSRF change.
- Note kept (information): a reversal attempt shows the general conflict text, not a put-back
  message, as option (b) says.

## Review round 2 (fresh read-only subagents; same limits)

Independent: 0 blockers, 1 should-fix (test), 3 notes. Security: clean.

- Independent should-fix (test, fixed under the round-3 rule of 2026-10-13): the allocation and
  Charge cases of TEST-FE-677 were also refused by the new agreement check, so they did not prove
  their own rule. Added `[allocation, true, true]` and `[charge, true, true]`, which only the
  allocation lists and the Charge rule refuse; the test helper clears the designation and
  proposal only on a Credit payment (an allocation keeps its own fields).
- Notes taken: TEST-FE-676 asserts the five samples; a missing fixture throws instead of
  returning; docs/010 names DB-CREDIT-005.
- Security notes kept: the five-sample count (taken); the long test title (no max-len rule in the
  frontend lint).

## Review round 3 (fresh read-only subagents; same limits)

Independent: clean (0 blockers, 0 should-fix, notes). Security: clean (0 blockers, 0 should-fix,
2 notes). The independent reviewer traced every TEST-FE-677 case to the check that refuses it:
`[allocation, true, true]` proves the two allocation lists together, `[charge, true, true]` the
Charge rule, `[credit, true, false]` and `[credit, false, true]` the agreement check; the other
cases are extra coverage; TEST-FE-676 proves acceptance; the agreement check refuses no valid
reply (the database keeps header and detail in agreement, and the re-posted rest copies the
label to both).

Text notes taken (no code or test change): the docs/010 wording "so each rule has a case only it
refuses"; the plan's as-built line names the round 2 fix.

Notes kept (optional, slice 12 list): the screen could require an empty
`proposed_amount_usd_cents` on a labelled line (security); a zero-line allocation reply would
test the allocation payment list alone (independent); the plan's pre-code note still says two
contexts (the as-built line says five).
