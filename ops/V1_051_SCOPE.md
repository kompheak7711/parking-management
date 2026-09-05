# V1-051 frozen implementation scope

## Authority and predecessor

Direct Codex only, authorized through V1-053 by ops/CODEX_TAKEOVER_V1_048_053.md
SHA2564e3e824e19b7c9e7aa8f3cc2cef5859e5f645c8793b4600aa541c4d9ad552455.
Coordinator and financial/migration/concurrency/security implementation: GPT-6 Astra
xhigh Standard. Fresh independent exact-SHA reviewers: Astra max Standard, read-only.
No model fallback. Provider-side model/service-tier attestation is not claimed.

Immediate predecessor V1-050 is fully closed at terminal
cc3d18e682401cc8a9ade10295572fe1a1344317, product3d16b65c631593a81c87bd7be290c9a820cb791a.
Product and terminal fresh independent reviews have zero HIGH/MEDIUM/LOW findings.
Both normally published; exact CI33985062450 and33986122538 attempt1/all4jobsSUCCESS.
Main/tracking/fetched/live refs equal terminalcc3d; same cardd26f24b3 DONE,
final commentbcdb1010-2476-40fb-af51-900ddc8ff9d8.
Closure receipt /Users/sokompheak/.codex/.chatgpt-projects/g-p-6a721755d4048191b2550824162f9521/v1050-closure-verification.md
SHA256616f7c7f39189d643bb485ea315ac4812313dc788738fb48cef28955dd979cc2
discharges immutable cc3d pending terminal fields. Do not repeat V1-050 closure.
Roadmap dependencies V1-037 and V1-049 are complete.

V1-051 tracking-only cardc5621f97-7ad1-4b1c-b04f-c854376c2ad8 is blocked
solely to prevent OpenClaw admission. No OpenClaw assignment, claim, attempt or dispatch.
Preserve this ID and all evidence. Supervisor658ffdaf-1ac1-45a6-a842-f5f7d7a226eb
stays disabled; native Codex follow-up stays active through V1-053.

## Included financial services

- Append-only payer-authorized Credit recognition from identified eligible unallocated
  Payment excess, source/payer/authorization/reason/time linkage, USD-only derived
  Credit balance, and original KHR Payment/FX evidence through the immutable source.
  No automatic retention, fabricated future Invoice, negative balance or silent
  Deposit conversion. Applicable existing obligations must be handled before true
  overpayment is recognized; preserve payer intent and third-party source restrictions.
- Same-Customer applications across applicable Lease relationships to eligible issued
  Invoices or positive confirmed separate Late-payment Charges. Explicit authorization,
  within-Invoice Rent-first then recurring-Service proposal and confirmation or valid
  Customer designation, authoritative line/category detail summing to the header,
  exact positive source/target bounds. Direct Charge applications affect only that Charge.
- Permanent application and recognition reversals, derived available/applied/refunded
  positions and complete Credit-source event history. Recognition reversal requires
  all applications and Refund commitments resolved explicitly.
- Extend the existing Refund/correction tables and Deposit services rather than create
  a competing Refund history. Support eligible unallocated Payment excess, Customer
  Credit, existing Property-caused Reservation cancellation Refunds and the already
  qualified active-Lease Pet Deposit exception. Recompute source availability and
  recipient/Property/source/review linkage transactionally.
- Direct KHR Payment excess refunds preserve the corresponding original KHR excess,
  original USD basis and Payment-confirmation exchange record. Later KHR refunds of
  USD Credit use the applicable confirmed System Exchange Rate and approved upward
  rounding, preserving both amounts, exact rate/time/calculation/source. No binary
  floats, live FX provider or new currency policy.
- Authorized append-only linked Refund corrections and correction reversals under
  DB-REFUND-002. An API-066 value correction requires evidence of value demonstrably
  returned, exact currency/amount, return time/reference, actor/reason/authorization
  and idempotency. It records the approved generic VALUE_CORRECTION, not a new
  Refund status, collection right or returned-funds operational workflow. Reverse
  only one active original correction with exact opposite reconciled effects;
  net value stays between zero and the immutable original Refund.
- Keep the Reservation full-refund invariant and source lifecycle linkage intact.
  Active-Lease Pet Refund requires the matching qualifying review, permanent pet
  departure and resolved applicable obligations; never refund active Security Deposit,
  apply Deposit to an Invoice, terminate the Lease, fabricate settlement or cap liability.
- Integrate Credit applications/reversals with authoritative Invoice-line, Invoice and
  Charge balances/statuses and adjustment/void/correction guards. Integrate Credit
  recognition/reversal and direct Refund/corrections with current AND historical
  Payment disposition/source-budget/reversal guards without double counting Credit
  refunds or replacing existing Allocation/Deposit consumers. Preserve V1-050's
  single captured disposition snapshot in Receipt display and immutable identity.
- Separate independently grantable exact-Property capabilities for Credit read,
  recognition, application, each reversal, Refund read/create/correction; fresh
  active-actor checks, server-trusted calculations, transactional replay and conflict
  handling, append-only audit and fail-closed unknown outcomes. No role bundle grants.

## Staged dependencies and excluded work

HTTP/staff UI and Payment/Receipt screens are V1-052; unified Customer Account Ledger
is V1-053. This version includes Credit-specific history/service read models only.
Final Settlement calculation/closure/API/UI and settlement-linked Deposit disposition
are V1-056, requiring V1-055 as well as this version. V1-051 must not fabricate an
eligible settlement source or offer its Refund path without authoritative prerequisites.
Keep unsupported settlement-linked requests fail-closed; later V1-056 integrates its
approved source into this Refund history. No V1-054 or later activation in this takeover.

Exclude vendor Accounts Payable, new financial policy or canonical rewrites,
Refund pending/failed/delivery business statuses, new collection/refund rights,
negative Payments, original financial-record rewrites, silent backfill, new dependencies
or external providers. Production access/deployment/credentials, customer data, paid
activation, destructive operations, force push/history rewrite and retained-worktree
deletion remain unauthorized.

## Canonical authorities

001: Customer Credit/Application/Reversal, Refund/Correction, Deposit and Money concepts.
002: BR-CREDIT-001..013, BR-REFUND-001..013, BR-DEP-012, BR-PAY-019..040
and applicable existing FX/excess/reversal rules.
003: PR-CREDIT-001..013, PR-REFUND-001..013.
004: DB-CREDIT-001..005, DB-REFUND-001/002, DB-LEASE-010/011 and existing
Payment/Allocation/Deposit/derived-balance contracts.
005: API-061..066 and API-094 service semantics; HTTP routing deferred.
007: TEST-064..070, TEST-126 and existing Payment/Allocation/Receipt regressions.
008: SEC-019..031 and applicable financial identity/history/privilege boundaries.
010: precedence rules, DL-027..031 and DL-053. No new business/security decision is made.

## Bounded implementation plan and acceptance

1. Freeze active scope/sole coordinator identity in compact state; preserve all previous
   evidence and worktrees. Create isolated codex/v1-051-direct checkout from the accepted
   V1-050 terminal plus local activation. Cumulative publication review base remains cc3d.
2. Add forward-only migration41 and necessary service boundaries. Never edit published
   migrations38/39/40. Assert integration contracts, safe retained-history upgrade and
   transactional history/source invariants; no fabricated legacy financial records.
3. Add synthetic unit and real isolated PostgreSQL tests for every actual authority
   assertion: USD/KHR evidence/rounding, same-Customer and exact-Property isolation,
   distinct authorization, replay/key conflict, atomic rollback/audit, history/reversal,
   source and target bounds, overlapping Payment/Credit/Deposit/Refund operations,
   backdated chronology, concurrent spending/correction and Repeatable Read safety.
   Preserve prior Receipt snapshot and migration-race regressions.
4. Run focused tests, full PostgreSQL/migration gate, backend/frontend
   formatting/lint/type/tests/build/import, automation/configuration/traceability,
   secret/publication/diff checks and official PyPI/npm metadata-only audits.
   Account for all skips/failures without weakening requirements.
5. Freeze a clean immutable cumulative candidate; fresh independent Astra max Standard
   read-only review must find zero HIGH/MEDIUM/LOW issues before normal authorized push.
   Preserve failed checkpoints; use bounded materially different corrections.
6. Verify exact-SHA GitHub Actions/all four jobs and reviewed/local/upstream/fetched/live
   ref equality. Accept this same Workboard card and separately reconcile terminal
   durable closure with exact review/publication/CI evidence as required.
7. Only after V1-051 fully closed activate V1-052; continue through V1-053 with no routine
   authorization questions. At V1-053 closed pause native follow-up, leave OpenClaw
   disabled and do not activate V1-054.
