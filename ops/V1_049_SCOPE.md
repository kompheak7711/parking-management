# V1-049 frozen implementation scope

Predecessor: fully closed V1-048 terminal e3ae74f8ca2acab1991db9f724faf3df274bcc08;
product561dd06, terminal CI33960592925 attempt1 all4jobs success, exact refs equal,
existing V1-048 card652e776c DONE. Closure receipt SHA256
7e3dc8d7876d5fcf744addcc3b9ecb66d45b2200cab1fd8cb6dfa7eec91421c6.

Tracking-only card62275bf0-2739-448c-ae59-50794190ee72 stays blocked to prevent
OpenClaw admission. Direct Codex only; no OpenClaw supervisor/worker dispatch.
Authority: ops/CODEX_TAKEOVER_V1_048_053.md. Implementation uses Astra xhigh,
Standard for financial transactions, authorization, migrations and concurrency;
fresh independent exact-SHA reviewer uses Astra max Standard, read-only.

## Included

- Forward-only allocation header/detail/reversal persistence (DB-PAY-004/005/007),
  explicit human confirmation, immutable relational target/proposal/designation
  evidence, exact integer cents, audit, least-privilege command boundary.
- Read-only deterministic FIFO proposal: oldest Invoice Due Date, issue timestamp,
  stable Invoice number/ID; within each Invoice Rent then recurring Services,
  with stable source order for other applicable obligations. No automatic posting.
- Customer/third-party designation, scoped Invoice-line or separate Charge targets;
  jointly responsible non-Invoice-Customer signers use the designated path. Proposal
  provenance exists only for generated proposals, not fabricated for direct intent.
- Transactional idempotent allocation posting, allocation reversal and Payment
  reversal service boundary, enforcing positive source/target availability and
  no double consumption under supported isolation; unresolved downstream events
  must be explicitly unwound with their existing separate authorization.
- Integrate Payment availability, line/Invoice/Charge positions, Invoice status,
  existing adjustment/void/late-payment decision safety and historical as-of reads
  so an allocation or reversal cannot leave competing financial truth.
- Forward migration/fresh-head/retained-history, authorization, idempotency,
  stale snapshot/concurrent source-target, proposal ordering, partial/full balance,
  reversal chronology/audit and whole existing-regression tests with traceability.

## Excluded

Receipt/reprint (V1-050), general Credit/Refund services (V1-051), Payment staff
HTTP/UI exposure (V1-052), Customer ledger (V1-053). No silent Credit recognition,
Refund, Deposit conversion or future Invoice creation to consume excess. Existing
Deposit/refund commands retain their separate authority; do not silently cascade
unauthorized financial reversals. No production or customer data operations.

## Canonical authority

BR-PAY-019..040; DB-PAY-004/005/006/007, DB-DER-001/002/009/011, DB-TXN-001..004;
API-059/060 service semantics; TEST-060..063/067/068; SEC-026/028..031/045..048.
Existing Invoice, Charge and Deposit rules remain authoritative. Resolve genuine
policy contradictions; do not invent priority or permissions.

## Bounded execution and acceptance

1. Add allocation event storage and reusable authoritative financial projections.
2. Add non-posting proposals and explicit idempotent authorized command services.
3. Reconcile existing Invoice/Charge/Payment transitions against applications.
4. Verify focused edge cases, full PostgreSQL/backend/frontend/static/build/config/
   traceability/audits, preserving failed checkpoints and materially different fixes.
5. Freeze combined exact SHA; require fresh independent Astra max zero findings,
   normal reviewed publication, exact-SHA CI, ref equality, Workboard and durable
   closure before activating V1-050. No routine owner authorization required.
