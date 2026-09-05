# V1-048 frozen implementation scope

Base: 3edda3d72487695dc8e2b5af3e9313090c96defa, fully closed V1-047.
Tracking card: 652e776c-2a91-4ebd-bfed-90aa8d5de247. Direct Codex only;
OpenClaw remains disabled. Owner authority: V1-048 through V1-053 takeover.

## Included

- Payments and immutable linked Payment reversals, unique receipt identity,
  payer and Property/Lease/Invoice/Charge intent consistency, human attribution.
- Existing Payment Method snapshots and confirmed exchange-rate evidence;
  USD integer cents, KHR whole units, exact ceiling conversion, manual source
  failure provenance and channel-actual evidence precedence without later repricing.
- Validated Deposit receipt Payment links, availability serialization and reversal
  prerequisites; net corrected Refund effects preserve original financial history.
- Forward-only transactional migration: reject historical orphan receipt evidence
  rather than fabricate Payment facts. Synthetic test fixtures explicitly fund receipts.
- Database role boundaries, audit evidence, immutability and concurrency tests.

## Excluded successor work

Allocation services (V1-049), receipt/reprint snapshots (V1-050), Credit and general
Refund services (V1-051), staff Payment API/UI (V1-052), Customer ledger (V1-053).
Payment confirmation does not settle an Invoice, create Credit or initiate Refund.
No production migration/deployment or production/customer data access.

## Authorities and acceptance

Canonical BR-PAY-001–018 and reversal prerequisites, BR-MONEY-001–013,
DB-PAY Payment/FX/reversal entities; TEST-059, TEST-067 and TEST-069–074 only
to the extent of persistence. Allocation/Credit/Refund portions are deferred explicitly.
Independent Astra max scope inspection completed before candidate freeze; it is
not an implementation approval. Require a fresh immutable exact-SHA zero-finding review.

Acceptance: fresh and prior-head migration, explicit orphan rejection with rollback,
validated source FK, human-only actions, denied runtime direct writes, snapshots,
USD/KHR arithmetic and confirmed history, cross-source checks, immutable reversals,
Deposit availability/concurrency, corrected Refund unwind, complete existing regressions,
format/lint/types/builds/audits, normal publication, exact-SHA CI and ref equality.
