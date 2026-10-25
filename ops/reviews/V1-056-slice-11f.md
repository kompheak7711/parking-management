# V1-056 slice 11f review record: the slice 11 browser client

Built 2026-10-25 in the cloud session on branch `wip/slice-11` after b995a2c. No migration, no new
route.

## What was built

- `frontend/src/settlementClient.ts` (new): one function for each of the 37 slice 11 routes
  (11a cleaning rate, cleaning charge and hand-back; 11b shared drafts; 11c-1 Refund methods;
  11c-3, 11c-4, 11d and 11e-2 drafts on their own record and the Deposit routes; 11e-1 Final
  Settlement; 11e-2 and 11e-3 corrections).
- `frontend/src/settlementForms.ts` (new, generated): the request forms, written from the routes'
  OpenAPI request models by `backend/tests/test_settlement_forms_ts.py`, which also fails when the
  file and the models differ.
- A refusal reaches the screen with its code, text, fields (without the `body.` prefix of a plain
  form check), rule ids and current version; a 503 or a network failure is a separate unavailable
  error.
- Decided by Claude under the owner's 2026-10-23 22:30 rule: one new client module for the slice,
  so the V1-058 screen work changes no existing client; the screens are built by the V1-058
  thread.
- docs/005 paragraph "V1-056 slice 11f" at the end of API-072.

## Review round 1 (one read-only agent)

- B1 (fixed): the hand-back resolution sent no `If-Match`, so it could never succeed (the server
  answers 412 without it). It now takes the Invoice version and sends it.
- S2 (fixed): plain form checks name fields as `body.x`; the client strips the prefix and drops
  repeats, as `invoiceClient.ts` does.
- S3 (fixed): the docs named the Property header for routes that do not take it.
- Nits fixed: the CSRF cookie is read inside try/catch; the confirm answer is typed as
  `{draft, result}`; the cleaning rate and charge take no key (their own ids are the retry
  identity); comments on the draft-list cursor and the generator header.
- Left: the generated forms cannot show rules between fields; the server checks them and answers
  422 on the field (said in the file header).

## Review round 2 (one read-only agent, the round 1 fixes)

No blocker. Should-fix fixed: the upstream ids of the client tests now name the rules they test
(API-014, API-015, API-018, SEC-016). Nits fixed: the docs wrap and wording, a comment that a retry
after a lost answer keeps the same key and version, and a test that a version that is not a whole
number of 1 or more is never sent.

## Runs

- Frontend: `settlementClient.test.tsx` 10 passed; the full suite before the round fixes, 1,649
  passed in 40 files; lint, typecheck and format clean.
- Backend: `test_settlement_forms_ts.py` and `test_traceability.py`, 30 passed; full mypy clean.
