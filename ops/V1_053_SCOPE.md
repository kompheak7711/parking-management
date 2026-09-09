# V1-053 frozen scope — read-only Customer Account Ledger

## Authority and predecessor

Direct continuous Codex authority through V1-053 remains in
`ops/CODEX_TAKEOVER_V1_048_053.md` (SHA256
4e3e824e19b7c9e7aa8f3cc2cef5859e5f645c8793b4600aa541c4d9ad552455).
Independent reviews use GPT-6 Astra, max reasoning, Standard mode and enforced
read-only access. Financial, authorization, concurrency and migration implementation
uses Astra xhigh Standard. Provider-side configuration attestation is unavailable;
record observed launch configuration. No model substitution.

V1-052 is fully closed at `0926300c5c91b26deedb682e454622065826b0ad`,
with product `fba87feba842837f7cc7c068477670bfdb4c08f8`. Product and terminal
reviews have zero findings; exact CI34253440448 and CI34265209149 passed all four
jobs; normal publication and required ref equality were verified. Existing card
74197a0e-ae91-459f-a9ce-6744e4097ff6 is DONE with proof
30271f13-5ce9-45c9-a27f-f7326b6eaa81. All 17 comments and original notes survive.
Final external closure receipt:
/Users/sokompheak/.codex/.chatgpt-projects/g-p-6a721755d4048191b2550824162f9521/v1052-closure-verification-0926300.json
SHA256 d51d90cec48d8d5fe2da707183b63c2c20f5a9922144217999ab66a4cc13b351.
It discharges immutable pending fields without rewriting the candidate. Dependencies
V1-047 and V1-052 are complete. V1-047 closure at
b022d833f3cbde0cc201a28ecd081e3179d7348c and its evidence remain preserved.

The activation candidate contains only this scope and NOW/STATE/QUEUE/roadmap.
It materializes 52 complete before allowing V1-053 product implementation, which
requires passing activation checks and one fresh independent zero-finding review.
Use existing main checkout and sole root coordinator
01a07991-38a6-7f33-b84d-0ad0620e2997. Preserve the clean V1-052 product checkout
and all 127 worktrees. Do not create another worktree or implementation agent.
Tracking-only card d362ed27-0bdb-4318-9c8a-0976c931d706 remains blocked to prevent
OpenClaw admission; there is no OpenClaw assignment, claim, attempt or dispatch.

## Current implementation and required change

Accepted billing, Payment, Allocation, Credit, Refund and Deposit services retain
authoritative financial facts and correction histories. The current Customer API
exposes Customer resources and a partial financial summary. There is no implemented
unified Customer Account Ledger endpoint, relational projection or dedicated UI.
Add a derived view and its staff read interface, reusing existing source formulas and
authorization boundaries. Do not create another source of financial truth.

## Canonical requirements

- BR-LEDGER-001–007, PR-LEDGER-001–007 and DL-052 define one reconstructable,
  chronological Customer financial view with operational language.
- API-093 specifies `GET /customers/{customer_id}/account-ledger`; UI-104 defines its
  dedicated read-only interface. The roadmap's nonexistent `UI-LEDGER-*` alias is
  replaced by the existing exact UI-104 identifier; canonical specifications stay
  unchanged. Supporting common API/UI requirements still apply.
- DB-DER-010 and DB-VIEW-009 define the relational `customer_account_ledger` and
  `customer_financial_position` projections, stable source identities and ordering.
- SEC-019–029 and SEC-070 require authenticated capability and Property/object scope,
  with ledger read permission separate from every source mutation capability.
- DL-060 requires USD accounting and USD-only Refunds. Original incoming KHR and FX
  evidence remains audit provenance; a read must never revalue historical money.
- Source Invoice/line, separate Late-payment Charge, Payment/Allocation/reversal,
  Credit/application/reversal, Refund/correction, and Security/Pet Deposit rules
  remain authoritative. Read the affected canonical sections before each slice.

## Included product scope

1. Derive all applicable existing authoritative financial events for one Customer:
   charged obligations and composition, Invoice and line Adjustments/voids, separate
   Late-payment Charges and corrections, received/reversed Payments, allocation
   and reversal effects, Credit recognition/application/reversal, Refunds and returned
   value corrections, and separately identified Security/Pet Deposit movements.
   Retain source timestamps, business dates, source kinds and UUIDs, Invoice/line and
   Charge links, original money/FX evidence where applicable, effect and resulting
   position. Optional Receipt presentation events have zero financial effect.
2. Deterministic chronology uses business instant, stable event-kind order and source
   UUID. Corrections remain separate chronological events. Reconstruct historical
   effects from immutable facts; never assign today's mutable balance to past events.
   Preserve pagination order, filters and stable links without dropping equal-time
   events. Consistent source reads must reconcile across concurrent financial writes.
3. Recompute current Invoice composition and separate positive Charge outstanding,
   total owed, available Customer Credit, unallocated Payment, Security Deposit and
   Pet Deposit liabilities. Never net Credit, unallocated Payment or deposits against
   obligations without an authoritative application, or count a Payment/application
   twice. Deposit liabilities remain distinct from Customer Credit.
4. Expose a bounded, authenticated, read-only API with strict Customer/Property scope,
   a distinct ledger read capability, deterministic pagination/filter contracts,
   exact integer/decimal-safe money transport, safe error/correlation handling and
   query limits. Unauthorized access must reveal no financial source details.
   Reading must perform no financial command, source write or implicit correction.
5. Provide a dedicated staff ledger from the Customer workflow with operational
   labels, chronology, source links, composition and clearly separate balance groups.
   Support loading, empty, forbidden, error/retry, pagination and keyboard/focus states.
   Use exact money display including aggregates beyond JavaScript safe integers.
   Do not add financial command controls or plaintext financial browser persistence.
6. Add only necessary forward-only projection/read-capability migrations and narrow
   privileges. Do not edit published migrations, rebuild/reset existing databases,
   invent historical timestamps or backfill fabricated financial events. Validate
   source preservation and fresh/upgrade behavior on isolated synthetic PostgreSQL.
7. Existing authoritative source facts must not be silently omitted. Final Settlement
   commands and deposit-to-obligation policy belong to their later roadmap scope;
   do not implement them early or fabricate their events. Inspect current schema for
   already-supported source facts and explicitly account for source coverage and
   later integration boundaries in tests and the API contract.

## Excluded scope and safety

No General Ledger, Chart of Accounts, journal posting, vendor Accounts Payable,
editable ledger, automatic application/netting, source-history rewriting, new financial
policy, KHR Refunds, new paid provider, framework replacement or unrelated modules.
Do not change canonical policy documents. No production access/deployment/credentials,
customer data, paid activation, destructive operations, force push, history rewriting
or deletion of retained worktrees. OpenClaw remains disabled throughout.

Standing independent-review and normal private-source publication authorities through
V1-053 remain in the external authority receipts. Carry them into each review request
and approved handoff. Publish reviewed commits only to
git@github.com:kompheak7711/property-rental-management.git, implementation/foundation,
without force. The specific approved V1-052 board payload is completed; future board
actions remain under applicable lifecycle authority and normal permission enforcement.
Do not transmit credentials, secrets, customer data or production data to reviewers.

## Bounded implementation and verification

1. Freeze/test/review this activation contract first. Fresh activation gates cover
   automation, exact canonical identifier expansion, dependencies/closure evidence,
   state routing, preserved history, configuration, traceability and publication guard.
   Reuse unchanged runtime tests; do not rerun them merely for records or approval.
2. Record and implement bounded source projection/reconciliation, API authorization,
   and frontend integration slices. Preserve accepted and failed candidates, reports,
   logs and correction counters. At most two materially different automatic corrections
   for the same unresolved finding; distinct findings retain separate histories.
3. Test canonical $500 Rent/$10 service/$300 allocation/$21 separate Charge/$231
   subsequent allocation example; partial/full applications, original and reversal
   chronology, void/Adjustments, Payment excess, Credit and Refund corrections,
   Deposit separation, equal timestamps, large exact amounts, empty Customers,
   pagination, scope/capability denials and concurrent source reads.
4. Prove source immutability and current/history reconciliation with real isolated
   PostgreSQL and fresh/upgrade migrations. Cover unauthorized direct database access,
   UI/API read-only behavior, safe failures, pagination and complete source coverage.
   Run required PostgreSQL/backend/automation/frontend full suites sequentially.
5. Run applicable formatting/lint/types/build/import, traceability, security/dependency,
   diff/secrets, migration and synthetic browser checks. Account for every failure
   and skip. Obtain fresh exact-SHA Astra max Standard enforced-read-only review of
   complete base-to-head changes, including focused financial authorization/security.
   Require zero findings; do not waive a failed gate with unrelated passing evidence.
6. Normally publish reviewed product/integration/release/closure commits, require each
   required exact-commit CI and ref proof, reconcile the preserved tracking card and
   durable records. At fully closed V1-053 pause the SAME native follow-up, keep
   OpenClaw disabled and do not activate V1-054.

Expected product paths: new backend ledger projection/service/API modules, app wiring,
new migration(s) and registration, focused unit/API/real-PostgreSQL tests, ledger client
and UI/tests plus Customer/App integration, traceability and bounded ops records.
Only necessary existing source read adapters may change; source command behavior and
published migrations remain outside the ledger implementation scope.
