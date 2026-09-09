# V1-053 bounded Customer Account Ledger UI

Activation requires accepted API4b7b320, its successful exact four-job GitHub CI
and required ref equality. This plan does not activate implementation by itself.
Use existing main implementation/foundation, root01a07991-38a6-7f33-b84d-0ad0620e2997,
GPT-6 Astra/xhigh/Standard because this slice covers financial interpretation,
authorization, privacy, exact money and asynchronous state. No new worker/worktree.

## Scope and behavior

Implement UI-104 and PR/BR-LEDGER001–007 using reviewed API-093 and SEC-070.
Provide a dedicated read-only account view for one Customer, accessible through
the ledger's own minimal Customer picker and from an existing Customer detail.
Use the separate ledger capability; existing Customer/financial command grants
never imply ledger access. Permission failures use clear staff-facing messages.

Display the authoritative current amount owed, invoice outstanding, separate
Late-payment Charges, available Customer Credit, unallocated Payment, Security
Deposit and Pet Deposit balances. Preserve the supplied seven exact amount fields,
their64digit bound, invoice-plus-charge equality and the six distinct balance
buckets. Use string/BigInt formatting; never parse money through floating point.

Provide chronological history with recorded amount, operational event labels,
individual balance effects, source dates/times, and resulting positions. Explain
that the position at a timestamp includes every event at that same timestamp.
Preserve microsecond ordering and stable timestamp/order/kind/UUID keys. Filters
select displayed history after the server's complete balance window and never
change what a displayed resulting balance means. All23existing event kinds remain
visible, with corrections/reversals as separate records.

Provide separately paginated positive balance composition and selected-event
source/component evidence. Distinguish an individual source amount from an event
header amount, and a page of composition from complete account totals. Stable
source navigation binds the actual event kind and UUID and opens its authoritative
read-only evidence through the ledger endpoint. A balance-source UUID is not
automatically an event UUID. Use operationally labeled facts and explicit original
source identities; preserve source links, category/description, reasons, original
Payment currency/amount/method and KHR/FX evidence without selecting a new rate.

## Read boundary and asynchronous state

Use a dedicated injectable client with fixed same-origin GET routes and session
cookies, canonical actor and optional Property headers, bounded response reading
and request deadlines. Validate request inputs, envelope fields, correlation and
actor/Property/Customer identity, section/filter/selected-event consistency,
revision, row shape/order/counts and exact amounts before rendering a response.
Respect the API's4MiB page bound plus bounded HTTP envelope overhead; do not reuse
the unrelated1MiB financial-reference ceiling. Validate cursor provenance against
the exact selection in memory, without duplicating Python fingerprint formatting.

Bind every history, composition and source page to one source_revision. Any409
invalidates all dependent financial views and cursors and requires refresh.
Actor, logout, Customer, Property, filter and source-selection transitions cancel
obsolete requests and suppress late responses; rendering checks the current scope
as well as completion callbacks. Keep ledger payloads/cursors in memory only.

Support loading, empty ledger, empty filter result, denied access, missing Customer,
unavailable service, invalid response, refresh conflict and retry states. Expose
complete bounded pagination and accessible keyboard/focus behavior. Preserve all
existing Customer command/reconciliation and financial recovery flows. The App
ledger is keyed by actor and unmounted when logout begins. A new entry control
does not trigger ledger network calls before the user opens it.

## Expected implementation paths

- frontend/src/customerLedgerClient.ts and customerLedgerClient.test.ts
- frontend/src/CustomerAccountLedger.tsx and CustomerAccountLedger.test.tsx
- frontend/src/CustomerLedgerEvidence.tsx
- frontend/src/App.tsx and App.test.tsx, limited integration
- frontend/src/CustomerManagement.tsx and CustomerManagement.test.tsx, optional entry callback
- frontend/src/styles.css, bounded ledger selectors if existing layouts need support
- Optional ledger-only shared test fixtures within frontend/src, recorded before use
- ops/V1_053_LEDGER_UI.md, NOW.md, STATE.json, QUEUE.md and traceability.json

Preserve backend API/runtime/migrations, source commands, canonical specifications,
dependency inputs and unrelated frontend behavior. Future Settlement and deposit
application policies remain outside this version. Ledger controls issue reads.

## Verification and lifecycle

Add meaningful client tests for canonical inputs/identity/privacy metadata, exact
small/large64digit values and illegal numeric money, event/section/row/order/anchor
consistency, source-revision and cursor provenance, bounded/deadline/abort failures,
malformed responses, and safe errors. Add component and App/Customer integration
tests for all23event kinds, six balances/current owed, canonical rent/service/Charge
example, composition and component pages, original KHR evidence, filters/tied
microseconds, stale/conflicting reads, late responses after every scope transition,
denied/missing/unavailable/empty states, refresh/retry, focus/keyboard navigation,
read-only network behavior and preserved existing command/recovery gates.

Use actual browser evidence with synthetic fixtures, including successful navigation
and source details, pagination/filter/empty/error/stale behavior, actor/logout
isolation, exact money, responsive layout and financial-network/privacy assertions.
Keep every failure and source-bound regression. At most two materially different
automatic corrections per unresolved finding; never loop on unchanged failures.

Freeze a normal UI candidate, run fresh full frontend formatting/lint/types/tests/
build and required automation/traceability/preservation/import/routing checks.
Reuse backend/PG/security evidence only when its entire relevant source/config/
environment remains identical, with explicit proof; do not repeat passed suites
merely because a commit hash changed. Any new relevant runtime change requires
its appropriate fresh checks. Obtain ONE fresh Astra/max/Standard/enforced-read-only
zero-finding review of the complete0926300-to-candidate change. Publish normally
to the authorized exact repository/branch, require own exact four-job CI and all
refs, then complete V1-053 integration/release/Workboard/durable closure checkpoints.
The existing53card is closed only after the complete product and lifecycle gates.
Pause the SAME native follow-up only when53is fullyclosed; leave OpenClaw disabled.
Never activate V1-054, deploy production, access customer data/credentials, force
push, rewrite history, or delete retained worktrees.

## Bounded browser harness

Add frontend/src/test/customerLedger.browser.tsx as an opt-in synthetic browser harness, consistent with existing frontend browser checks. It imports the actual ledger components/client and synthetic fixtures, never a production entry point. Run the existing Playwright CLI against an owned loopback Vite server with all financial network requests blocked; record runtime viewport, interaction, pagination, stale/scope, source/KHR/money, focus and privacy evidence outside the candidate.

## Invoice void amount correction

Preserve an explicitly absent recorded amount as null in both history and source components. Issued and draft Invoice void projections omit that amount; display “Not recorded” and retain their authoritative balance effects. Never substitute zero. Present recorded amounts still require canonical exact nonnegative decimal strings. Regression IDs TEST-FE-584–586 cover issued and draft voids, paginated components, malformed present amounts and the dedicated view. Preserve rejected0ca4c53 and its one-MEDIUM report, the four reproduced failures, same-body eight-pass correction, and the separate test-only TypeScript guard correction.

## Executable test registration correction

The 41 new ledger identities are TEST-FE-548 through588. Only new ledger client IDs546/547 were reassigned to587/588; preserved V1-052 browser identities546/547 and all1944 earlier mappings remain unchanged. TEST-117 discovers the ledger client suite, parameterized component cases and the executable browser verification function. Its uniqueness and complete inventory equality assertions remain mandatory; TEST-118 requirement coverage is separate. Backend verification must include current traceability.json and frontend test sources as inputs. Prior API-era full backend reuse for UI58d6cf5 is invalidated and preserved as rejected evidence; freshly execute the affected trace contract and complete backend suite. Product/API/migrations/source commands are unchanged. The browser assertion export is freshly executed, including empty-evidence denial, after both void scenario assertions; earlier browser evidence remains preserved.
