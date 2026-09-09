# V1-053 active bounded slice — ledger read API

Reviewed foundation a45552e passed its own four-job CI34315960861 attempt1 and
all required ref checks. Its immutable acceptance and publication proof are
recorded below. The active worker remains root01a07991-38a6-7f33-b84d-0ad0620e2997 in the existing main checkout,
GPT-6 Astra/xhigh/Standard because this slice crosses finance, authorization,
migrations and concurrent reads. No new implementation agent or worktree.

Implement API-093 and SEC-070 under the existing frozen V1-053 scope. The dedicated
UI is the next dependent slice; neither this API checkpoint nor its publication
claims full version closure.

1. Add a strict immutable request contract around existing exact positions, filters
   and history cursors. The canonical Customer account-ledger GET supports bounded
   history, current composition and selected event-component pages. Separate page
   cursors bind Customer, Property, section, selection/filter and source revision.
   Validate actual anchor membership, not just cursor syntax. Pages are 1–100 rows.
2. Require only the explicit `customer_ledger.read` capability with canonical exact
   Property grants. No inference from Customer reads or source mutation grants.
   Fresh active HUMAN identity and canonical Customer/Property resolution occur
   inside the same REPEATABLE READ READ ONLY transaction as ledger reads. Add a
   minimal ledger-only Customer discovery endpoint without exposing Customer
   contacts, identity documents or unrelated financial capabilities.
3. Add only forward migration49 with narrow fixed-search-path definer read
   functions. No direct grants to the five projection views, no source commands,
   dynamic SQL, source/backfill/table/guard mutation or financial database URL.
   Read methods use application runtime credentials and existing bounded connection,
   statement and lock timeouts.
4. Reconcile every source balance and all six position buckets before responding.
   Derive a deterministic source revision from relevant complete projection facts
   and current composition in that snapshot. Prefer an incremental ordered hash
   in SQL with fixed accumulator size, avoiding an unbounded JSON response or a
   single aggregate string of all facts. Check oversized row/audit payloads and
   fail closed; never silently drop financial facts. The same revision is required
   across subsequent pages and sections; stale reads return refresh conflict.
5. Apply time/kind filters after the history window. Keep same-instant peer
   semantics and stable complete event keys. Return exact money strings, bounded
   original KHR/FX evidence, source identities and operational labels. Validate
   database response scope, exact amounts and shape before exposing data.
6. Wire strict GET routes into existing safe financial errors, correlation/privacy
   handling and dependency injection. Reject body, duplicate/unknown query fields,
   noncanonical identifiers/limits, invalid cursors and Idempotency-Key on reads.
   No API financial command, browser persistence or authentication-policy changes.

Tests: pure cursor/shape/money contracts; API capability/property/object/fresh-actor
denials and method/query/privacy handling; real runtime-role PostgreSQL reads,
fresh and populated48→49 migration with source preservation; current/history and
per-source reconciliation, filtered page ordering/ties/stale/nonexistent anchors,
concurrent source commit, empty and large values, source and view-write denials.
Carry the independent review's missing branches: DEBIT adjustments,
Credit-to-Charge/reversals, third-party reversals/deposits and mixed-kind ties.

After focused evidence, freeze a normal candidate and run applicable full
PostgreSQL/backend/automation gates sequentially, static/build/import, traceability,
security, preservation and required routing checks. Existing frontend evidence is
reusable only while its source and configuration remain byte-identical. Then ONE
fresh complete0926300-base Astra/max/Standard/enforced-read-only zero review,
normal authorized publication and own CI/ref verification before dedicated UI.
Preserve all failures/counters; maximum two materially different corrections per
unresolved finding. Full V1-053 release/Workboard/closure still mandatory; never54.

Activation 2026-09-09T05:58:53.296161+00:00; predecessor publication proof /Users/sokompheak/.codex/.chatgpt-projects/g-p-6a721755d4048191b2550824162f9521/v1053-security-publication-verified-a45552e.json SHA256223a1d765da6608a24b4ca1d139fd24bab3ad0793afbe0574e3aef989415befa.
Standing review and normal GitHub authorization receipts remain outside candidates;
all private-source submissions use normal enforcement and existing exclusions.

## Prepared implementation contract

The account-ledger GET defaults to history and limit50; limit1–100 is strict.
History accepts from/through RFC3339 instants and kind, after the complete history
window. Composition returns positive remaining source balances. Components selects
one event_kind/event_id and retains every source component. Responses carry exact
money strings, Property/Customer/name, source_revision, six separate position
buckets plus total owed, event_count, items and next_cursor. History positions
explicitly describe all equal-instant peers. Every continuation and cross-section
selection binds scope, filters/selection and revision; stale409 requires refresh.

The minimal customer-ledger/customers GET accepts limit/cursor and returns only
Customer UUID/legal_name with authenticated Property metadata. Both GETs reject
bodies, duplicate/unknown fields, command idempotency headers and mismatched actor
or Property headers. No command methods or financial credentials are added.
Migration49 grants only three narrow stable definer read functions to runtime;
all five direct projection views remain ungranted. RR/READ ONLY, connection3s,
lock3s and statement5s bound actual reads. A fixed-size incremental source hash,
1MiB per fact/audit and4MiB page limit fail closed without omitting source facts.

Focused tests passed:64pure-query,70HTTP and21real PostgreSQL cases. New source
branches include DEBIT/reversal, Credit-to-Charge/reversal, third-party Allocation
reversal, Deposit receipt reversal, mixed-kind equal instants and original KHR.
105event/history/composition pages are complete; a separate disposable database
proves equal-and-opposite per-source errors fail even when aggregate remains equal.
These are preliminary implementation results. Exact frozen full gates and fresh
independent review/publication/ownCI are still required before dedicated UI.
