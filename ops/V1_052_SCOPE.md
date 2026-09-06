# V1-052 frozen scope — staff Payment, Allocation, Receipt, Credit and Refund API/UI

## Authority, predecessor and ownership

The owner authorizes direct continuous Codex through V1-053 under
ops/CODEX_TAKEOVER_V1_048_053.md, SHA256
4e3e824e19b7c9e7aa8f3cc2cef5859e5f645c8793b4600aa541c4d9ad552455.
Routine implementation, bounded corrections, non-destructive migrations, commits,
independent review and normal publication require no additional authorization.

Immediate predecessor V1-051 is FULLY CLOSED at terminal
f8a33bad25a7993952ec1ccece1b9c2df942b3d6; product7cec08509343f90a369b27d8a230b2fa850b5622.
Fresh independent Astra max Standard product/terminal reviews: zero HIGH/MEDIUM/LOW.
Exact tests PASS; normal publication; CI34027889695/34030703203 attempt1 all4SUCCESS;
main/tracking/fetched/live equality verified; same cardc5621f97 DONE/proof935d944b.
Final receipt /Users/sokompheak/.codex/.chatgpt-projects/g-p-6a721755d4048191b2550824162f9521/v1051-closure-verification.md
SHA25692fa6965749c1b8a6e9f8b8c5eaa164a8418e0e720c58d62ef2b35ed7da65d86
discharges immutable pending fields. Dependencies V1-049/050/051 are complete.
The activation materializes V1-051 complete/count51 before V1-052 implementation.

One tracking-only card74197a0e-ae91-459f-a9ce-6744e4097ff6 was created only after
absence of an existing V1-052 card/worker/worktree was verified. Its blocked status
prevents OpenClaw admission; it is not an owner-policy blocker. No agent assignment,
claim, attempt or OpenClaw dispatch. Direct root Codex only; retain all126 existing
worktrees and create at most one isolated codex/v1-052-direct checkout after the
activation checkpoint is independently accepted. Reconcile again before creation.

Coordinator Astra xhigh Standard. Implementation Astra xhigh Standard because this
version crosses financial transactions, FX, authorization and concurrency; migration
work also requires xhigh. Fresh independent exact-SHA reviewers Astra max Standard,
read-only. Never silently substitute models; provider attestation is not claimed.

## Existing implementation and required bridge

Published migrations38–41 establish immutable Payment/FX facts, allocation and
reversal commands, one Receipt identity/reprints, USD Credit and source-bounded
USD Refund/correction history. PaymentAllocationService, ReceiptService,
CustomerCreditService and RefundService supply accepted service boundaries.
Configuration already supplies server-calculated exchange-rate confirmation with
an injected approved-source provider and capability-protected manual fallback.
Deposit API/UI already supplies Pet departure/qualifying review and reversal paths.
Invoice UI supplies actor-bound, exact-idempotency financial recovery patterns.

The new staff HTTP/React bridge is missing. Add only the command/read projections
needed to expose these accepted rules. Payment confirmation currently has persistence
guards but lacks its staff HTTP/service command; add its bounded transactional
service without replacing upstream history or inventing a second money event.

## Included scope

- API-057/058 and UI-063/064/065: paginated scoped Payment list/detail and explicit
  confirmation with payer Customer, optional Lease/designated Invoice or separate
  Charge intent, accepted configurable method, amount/currency, received/date facts,
  payer/reference evidence and applicable FX. Only RECEIVED/REVERSED statuses;
  immutable accepted-method snapshots and original KHR/FX remain visible. Do not
  auto-allocate, auto-recognize Credit, create Deposit or imply Invoice settlement.
- KHR is incoming Payment conversion only. Reuse approved ABA-equivalent reference
  selection and fallback capability/source-failure evidence. Server applies exact
  1.005 markup and both upward-rounding rules; calculated fields are not editable.
  Preserve authoritative channel-settlement facts. No new provider, paid activation,
  production network/credentials or browser-computed authoritative exchange rate.
- API-059/060 and UI-066/067/073/074: show authoritative available value, original
  active/reversed allocations, eligible targets and deterministic FIFO/within-Invoice
  proposals. Staff explicitly confirm manual posting or permitted designation.
  Separate Charge effects never appear to settle the source Invoice. Reversal shows
  original event, affected downstream obligations/Deposit/Credit/Refund dependencies,
  reason and explicit confirmation. Reuse coordinated service guards; unresolved
  Deposit dispositions/applications or required verified Refund returns block reversal.
- API-092/UI-106: link the unique immutable numbered Receipt, show original facts
  and separately derived current context, and implement authorized reasoned reprint
  with append-only history. Reprint never creates another Payment or Receipt identity.
  Reversed Payments retain their historical Receipt. Use accessible printable display;
  do not introduce a competing Receipt amount ledger or delivery business workflow.
- API-061–063/UI-068–070: distinguish unallocated Payment excess from recognized
  USD Credit; show source/list/detail/complete paginated ledger. Expose payer-authorized
  recognition, eligible same-Customer Invoice/Charge application, and approved linked
  application/recognition reversals. Show server availability/target consequences;
  no automatic retention, fabricated future Invoice or Deposit conversion.
- API-064–066/UI-071/072: paginated Refund list/detail/source eligibility and explicit
  source-bounded creation using the existing Payment/Credit and eligible Deposit
  paths. EVERY Refund is paid/recorded USD under DL-060. Show original KHR/FX audit
  provenance without offering KHR payout or a Refund-date rate. Completed events,
  not invented pending/failed business statuses or generic delivery methods.
- Link existing API-094/UI-107 qualifying Pet workflow; departure alone never allows
  refund or terminates a Lease. Matching Pet Deposit/review, remaining eligibility,
  resolved obligations and separate permissions remain authoritative. Preserve existing
  Property-caused Reservation full-refund rules. Do not refund active Security Deposit.
- Refund corrections record only demonstrably returned USD value, exact positive
  cents and bounded cumulative/net value, return timestamp/method reference, evidence,
  reason, actor and authorization. Preserve original payout; no collection right.
  Expose approved linked correction reversals only under existing service/rule limits.
- Capability-sensitive shell navigation and controls; exact-Property/object/actor
  server authorization, browser mutation/CSRF protection, bounded strict inputs and
  pagination, safe error/correlation responses, no sensitive logging or plaintext
  browser persistence. Use exact integer/decimal-safe transport/display for money and
  FX, including values outside JavaScript safe integers where aggregate responses allow.
- Explicit consequence confirmations and actor-bound idempotent command recovery:
  persist only reviewed encrypted intent, never tokens/plaintext financial data;
  block new commands while outcomes are unknown; explicit exact-payload/key replay,
  no automatic financial replay after expiry/reload, no actor/property crossover.
  Loading/empty/forbidden/error/conflict/success and keyboard/focus states are required.
- Necessary forward-only migration42 or later for missing command/read/capability
  boundaries, with narrow privilege, fresh actor checks and immutable audit/replay.
  Never edit published migrations38–41, backfill invented financial facts, weaken
  existing guards, or reset an existing database. Use isolated synthetic PostgreSQL.

## Canonical authority and affected paths

Roadmap API-057–066/API-092, UI-PAY-* (numeric UI-063–074 and UI-106/107),
TEST-059–074/125/126. Supporting BR-PAY-001–040, BR-RECEIPT-001–006,
BR-CREDIT-001–013, BR-REFUND-001–013, BR-MONEY-001–013, DL-051/060;
PR-CAP-005/007 and corresponding PR-PAY/RECEIPT/CREDIT/REFUND/MONEY;
existing DB-PAY/RECEIPT/CREDIT/REFUND, API-001–014 common contracts,
SEC-019–029/030–031/036–046, UI-001–020 common financial/accessibility behavior.

Expected paths: new bounded backend financial API/Payment service modules, app.py
wiring, affected existing accepted-service read adapters where needed, only NEW
migration files and migration-suite registration; focused unit/API/PostgreSQL tests;
frontend Payment/Credit/Refund/Receipt clients/components/tests, App integration and
existing design styles/recovery helpers only as needed; traceability and ops records.
Canonical policy changes, unrelated modules, dependency or framework replacements
are excluded. Read additional affected canonical sections before implementing them.

## Bounded plan, tests and release gates

1. Reconcile closed51 and tracking/scheduler state; freeze this activation/scope-only
   candidate with fresh records/configuration/roadmap/traceability/guard/whitespace
   tests and independent Astra max read-only review before product implementation.
2. In the sole isolated checkout, record each bounded slice active before edits:
   Payment confirmation/read foundation; HTTP adapters for accepted services;
   staff client/recovery; UI integration and financial workflow regressions.
   Preserve accepted slices and failed checkpoints, no duplicate workers.
3. Test strict inputs, actor/object/Property capability separation, CSRF, replay/key
   conflict/unknown outcome, safe read pagination and no data leaks; exact money/FX,
   immutable source/method/Receipt identity, no implicit value movement, concurrency,
   source/target bounds, reversal dependencies and USD-only Refund/partial returns.
   Cover Pet/Reservation restrictions and unsupported Settlement sources fail-closed.
4. Run full applicable isolated PostgreSQL fresh/upgrade/retained-history gates,
   backend and frontend tests, formatting/lint/types/build/imports, migration graph,
   automation/configuration, actual assertion-level traceability, secret/diff checks,
   official package-name/version-only audits and local synthetic browser smoke.
   Account for every skip/failure; at most two materially different corrections per
   unresolved finding, preserving reports and never weakening required tests.
5. Freeze complete product base-to-head candidate from f8a33ba. Require fresh
   independent Astra max Standard read-only zero HIGH/MEDIUM/LOW and exact tests
   before normal push to the explicitly authorized implementation/foundation branch.
   Verify exact GitHub CI, all refs, same-card acceptance and durable terminal closure.
6. Only then activate V1-053 unified read-only Customer Account Ledger. At53closed,
   pause native follow-up, keep OpenClaw disabled and do not activate V1-054.

## Exclusions and human stops

No unified Customer Account Ledger (V1-053), Final Settlement source/calculation/
closure (V1-056), new collection/refund rights, KHR Refunds, generic financial PATCH/
DELETE, vendor Accounts Payable, historical rewriting or silent financial mutation.
Show only currently API-supported eligible Refund sources; never invent a Settlement
source because a future canonical workflow describes it. No new business/security
policy, role grants, external provider or paid dependency.
Production access/deployment/credentials, customer data, paid-service activation,
destructive/irreversible operations, force-push/history rewrite and retained-worktree
deletion remain unauthorized. Stop only for the owner's stated genuine policy/safety
conditions or exhausted bounded materially different recovery, not routine permission.
