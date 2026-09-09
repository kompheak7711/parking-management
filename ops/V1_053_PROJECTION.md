# V1-053 Customer ledger projection foundation

This slice implements the source projection and pure money/paging contracts under
`V1_053_SCOPE.md`. It is a foundation checkpoint, not a complete V1-053 product.
The authenticated API, database read boundary, snapshot revision query and dedicated
Customer UI remain required in the following integration slice.

## Authoritative sources and effects

Migration `20260909_48` adds five nonwritable, security-invoker views. It changes no
source tables, commands, published migrations or financial policy, and grants no
application-role access. Downgrade is refused. All amounts are integer USD cents;
aggregate SQL uses NUMERIC to avoid bigint overflow and the Python wire model uses
canonical decimal strings. Incoming KHR and its original exact FX evidence remain
source audit fields; a ledger read does not reprice them.

| Existing source family | History representation |
| --- | --- |
| Issued Invoice and line | Original obligations and each line's composition |
| Invoice line Adjustment and reversal | Separate signed obligation effects |
| Issued Invoice void | Removal of the adjusted obligation at the void instant |
| Draft Invoice void | Preserved event with zero issued-obligation effect |
| Separate Late-payment Charge | Original charge, signed corrections and reversals |
| Late-payment waiver | Preserved event with zero charge effect |
| Confirmed Payment and reversal | Received and reversed unallocated USD value |
| Payment Allocation and reversal | Consumption of payer funds and reduction of beneficiary obligations |
| Credit recognition and reversal | Transfer between unallocated Payment and available Credit |
| Credit application and reversal | Consumption of Credit and reduction of obligations |
| Security/Pet Deposit receipt and reversal | Transfer from unallocated Payment into its separate liability |
| Deposit requirement Adjustment | Preserved requirement event with zero held-balance effect |
| Deposit disposition and reversal | Signed change in the identified deposit liability |
| USD Refund and correction | Consumption or return to the exact original source bucket |

Reservation cancellation Refunds retain their existing coordinated correction path.
A general partial return is still refused where that path is required. Payment,
Credit, Security Deposit and Pet Deposit Refunds keep their distinct source ownership.
Optional Receipt issue/reprint presentation events are omitted. No Final Settlement
or deposit-to-obligation source tables/commands exist at this predecessor; future
implementation must explicitly extend and reconcile the projection when those
sources become available. This slice does not invent those policies or events.

## Projection layers

`customer_ledger_effects` emits one row per balance component and source event.
Invoice line, separate Charge and originating source UUIDs remain available.
Third-party allocations put payer-fund effects under the payer and obligation
effects under the beneficiary; they do not transfer Customer ownership.

`customer_account_ledger` groups components into one event header per Property,
Customer, kind and source UUID. The recorded source amount occurs once per header;
component amounts remain independently reconcilable. Its six effect columns keep
Invoice, Charge, Credit, unallocated Payment, Security and Pet Deposit separate.

`customer_ledger_history` calculates six cumulative balances from immutable events.
An event's resulting position means **after every committed event at that instant**,
including all equal-time peers. SQL RANGE windows make equal-time results independent
of random UUID order. Display order is timestamp, fixed event-kind order, event kind,
and source UUID. Filters must apply after the history window. An integration must
label this instant-based meaning clearly and must not imply an invented order of
simultaneous transactions.

`customer_ledger_balance_sources` independently calls the accepted current source
formulas. `customer_financial_position` sums positive Invoice/Charge outstanding into
total owed and exposes Credit, unallocated Payment and both deposit liabilities
separately. It never silently nets available funds against obligations.

## Required read integration

Use a bounded transaction with one coherent snapshot for source revision, history,
composition and current position. Tests demonstrate REPEATABLE READ READ ONLY
coherence across a concurrent financial commit. Compare all six final history
balances and each source component with the independent source oracle; equal totals
with wrong composition must fail reconciliation. Reads must not touch source guards.

The pure cursor binds a Property/Customer/filter fingerprint, source revision and
full stable event key. Changed revisions require restarting pagination; a cursor is
not authorization. The next slice must compute and validate that source revision,
apply authenticated fresh actor/capability and object scope, bound query work and
page size, and withhold any financial response on a mismatch. The current views have
no direct runtime/financial/bootstrap/PUBLIC grants and no API route is wired yet.

## Verification and preserved corrections

The new tests comprise 44 parameterized pure cases and 24 real PostgreSQL cases.
They cover the canonical $500 Rent/$10 Trash/$300 Allocation/$21 Charge/$231 final
allocation, source identity and composition, third-party ownership, all implemented
source families above, equal-time peers, exact large sums, KHR provenance, concurrent
reads, role denial, source preservation and fresh/populated upgrade behavior.
Traceability registers every new executable test while retaining every prior entry.

Preliminary failures and raw source snapshots remain in external immutable evidence.
The canonical fixture was corrected to issue Initial Rent on its actual move-in
business date; the Security Refund fixture was corrected to use the existing
coordinated correction path after proving general-return denial. No financial
boundary or expected canonical amount was weakened. Style correction 2 preserves
both complete executable ASTs; type correction 1 asserts a source row is present.
Focused checks pass. Full applicable exact-candidate checks and fresh independent
Astra/max/Standard/enforced-read-only review remain required before acceptance.
