# V1-052 Payment reversal context

Bounded necessary read stage from independently accepted431f23a. UI073/074 and
API060 require original Payment, complete active dependency impact and affected
current results. SEC022 keeps payments.reverse independent of payments.read.
This stage adds no financial command, general read grant, provider, package,
canonical policy, Settlement or staff screen. Existing write guards are authoritative.

## Exact action and source scope

GET /api/v1/properties/{property_id}/payments/{payment_id}/reversal-context
requires explicit payments.reverse for that Property, a fresh active HUMAN and an
existing exact Payment in that Property. No global/object-only/role inference.
The route and service enforce the existing grant before the source projection;
metadata binds actor, Property and request. Duplicate/unknown query and expectation
headers fail safely. All responses/errors are private/no-store with safe correlation.

Query view is impact or result (default impact), limit1..100/default50 and an
optional finite canonical cursor carrying revision plus kind/identity. A continuation
must match the current relevant revision; mismatch returns409 and requires reloading
the context. No idempotency key, encrypted intent, financial reservation or command.

## Data and completeness

Every response includes the accepted original Payment/Receipt/FX resource and its
separately derived current position, with an explicit view and revision. Read the
source resource and page in one REPEATABLE READ READ ONLY transaction,3sconnect/lock,
5sstatement and UTC. A NEW forward-only migration46 grants prm_runtime only the
narrow projection function, with fixed search_path, fresh actor/exact-source checks
and no underlying table-write/read privilege expansion. No existing migration edits.

Impact pages identify active Allocations and their target-line details, Credit
recognitions and applications/details, source Payment's active Deposit Receipts,
active Dispositions on those Deposits, and unresolved Refund value from the Payment,
its active Credit or those Deposits. Deduplicate shared Deposit descendants. Each
item binds immutable event/source/target identities and exact original amount/date;
Refunds show original payout and net unreturned USD. Nested amounts overlap parent
accounting and must not be summed into a new Payment balance. The existing Payment
position supplies direct consumption categories. History is not deleted or fabricated.

Result pages identify unique historically affected Invoice, separate Charge, Credit
and Deposit targets with authoritative current financial balances/statuses. These
are original related identities and current derived facts, not an assertion that the
Payment reversal itself automatically changed a target. They support safe explicit
replay after reload without remembered plaintext pre-reversal state. No unbounded
proposal/audit expansion or invented Settlement/Deposit-Application fields.

Current schema has no Deposit Applications. If the existing dynamic helper reports
an unsupported active application on a relevant Deposit, return unavailable rather
than falsely report complete impact. A final page alone does not prove prior pages
were read; clients must validate sequence, identity, scope, view and revision.

## Relevant revision evidence

Reuse existing read-only revision counters: root Payment/status; sums/counts for
ALL historically associated Deposit revisions; and, for result, corresponding
historically affected Invoice/Charge financial guard revisions. Historical graph
edges stay included after reversal. Verify every included mutable projection has a
covered guard, adding minimal append-only inventory evidence if coverage is absent.
Never call serialization/locking/write functions from the reader. Fingerprint only
fixed-size scoped revision evidence; no persisted snapshot or unrelated global
database revision. New relevant writes invalidate continuation; completed evidence
and balances cannot silently mix across revisions. Final write guards remain final.

## Exact client and verification

Extend the existing finite read-only financialReferenceClient with this one route;
reuse its deadline/abort/body-ownership/byte/correlation protections. Validate the
accepted Payment resource through the existing financial response contract and the
new exact page schema, source/target relation, amounts, ordering, revision and
continuation. Preserve whole valid original labels. No reserve/clear/write dispatch.

Required unit/API/isolated PostgreSQL/client/real-browser regressions include fresh
action-only actor, scope/identity denial, all current direct/nested dependency kinds,
partial/full Refund returns and correction reversals, active/reversed events, more
than100items, changed-between-page rejection, other-Payment target changes, current
result balances, unsupported future active applications, no app-table/guard writes,
timeouts, exact large integers, abort/stale actor/Property and preserved pending key.
All existing tests/trace mappings and every accepted/rejected candidate/report/log
remain intact. Full exact gates and fresh complete431-base Astra/max/Standard/
enforced-read-only zero-finding review are required before bounded acceptance.

Standing independent review authority through53 remains external, SHA256
d509c66234abf96872d9c7d9682adc2a1ed315c97772b5793dbbe9426dd6eeff, applies to successors
and approved handoffs, and excludes secrets/credentials/customer/production data.
Respect automatic enforcement; no hash-only approval. Separate Workboard transmission
hold remains unresolved and must not be retried. After this stage continue required
action references/staff UI/full52closure before53; closed53pauseSAME/OpenClawdisabled/no54.

## Draft verification and preserved corrections

The draft passed87unit/API/inventory,20focused PostgreSQL,113client,23traceability,
backend/frontend static checks and7actual Chromium reference/context groups.
A full952-test PostgreSQL run passed before the final voided-Invoice correction;
the containing candidate still requires fresh full953PostgreSQL and all exact gates.
Current Invoice results follow the existing authoritative snapshot: DRAFT/VOID
outstanding is zero. Historical Deposits in result pages must also reject unsupported
active applications, even after original receipts are reversed. Both gaps have retained
red/green evidence. One Deposit/Payment receipt is unique in the existing schema;
fixtures preserve that invariant and cover shared Deposits funded by other Payments.
An initial targeted frontend red skipped112tests because its helper had stopped;
it is explicitly non-evidence. The installed red and actual corrected test are retained.
Original financial commands, serialization guards and prior migrations are unchanged.
No staff UI, bounded acceptance, publication or version closure is claimed here.
