# V1-052 bounded staff financial UI

Accepted base `013851d02b6712f949293db82ced82d2afb82ff9`; independent review75592 completed with zero HIGH/MEDIUM/LOW. Acceptance receipt SHA256 ce97cce0a2c9b40d42a4570385b34384145164563ef64b6f390ffd6c4e3b3809. This stage implements the staff bridge under ops/V1_052_SCOPE.md and ops/CODEX_TAKEOVER_V1_048_053.md. Standing review authorization is external, SHA256 d509c66234abf96872d9c7d9682adc2a1ed315c97772b5793dbbe9426dd6eeff. No credentials, secrets, customer or production data may be transmitted. All earlier failed candidates, reports and regression qualifications remain preserved.

## Existing boundaries and source scope

The accepted clients provide 14 financial reads, 12 financial commands, actor-authorized Property/method/capability references, provisional KHR preview and source-bound context sequences. Use these boundaries; no new backend/SQL/role/grant/dependency/financial policy or canonical document changes are expected for staff screens. Property discovery returns only explicitly scoped financial grants. The server retains final eligibility, balance, FIFO, FX and concurrency authority.

App currently renders feature panels and already excludes InvoiceManagement while logout is pending. Add FinancialManagement keyed by session actor and exclude it while logout is pending. Use verified financial Property discovery rather than inferring financial access from configuration access. New source should remain in small domain modules: financial display/input helpers; controller/read-context helpers; shared confirmation and recovery presentation; Payment/Allocation/Receipt screens; Credit screens; Refund screens; and App/style integration. The exact allowed path inventory is frozen below. Do not modify existing financial client/recovery/sequence contracts merely for convenience.

Use current panel, field, table, notice and dialog styling. Build actual staff forms and explicit original/current fact displays. No editable JSON, generic recursive evidence rendering, new router, plaintext storage, client-generated financial policy, or unrelated UI redesign. Relevant authorities are UI-001–020,063–074,106/107; API-057–066/092/094; BR-PAY/RECEIPT/CREDIT/REFUND/MONEY; DL-060 and existing capability/security rules. The V1-052 frozen scope remains the inclusion/exclusion authority.

## Workspace, read and command lifecycle

1. Discover authorized Properties using the actor-bound reference client with ordered page continuation. Show loading, empty, unavailable and retry states. Selecting a Property creates a new keyed workspace; fetch its fresh capabilities and load actor-bound financial recovery. Never infer grants from a role or another panel. Read-only users should not require crypto to view authorized records.
2. Each workspace owns an abort lifecycle and operation-generation checks. On Property/actor change, logout, unmount or superseded selection, abort reads, invalidate continuations and dismiss confirmations. No late Promise may restore old facts or write a new screen. Ensure React StrictMode setup/cleanup creates a fresh live controller instead of reusing an aborted controller. Selection changes also clear stale proposals/FX previews/target context before rendering.
3. Show Payment, Receipt, Credit and Refund navigation only where related explicit read or action capabilities exist. A user with an action grant alone can load the exact source through the existing action context. Do not require the general read grant and do not auto-call unauthorized history routes. Resource identifiers are useful source references; labels and immutable numbered identities should accompany them where available. Customer access stays separately authorized; do not fetch general Customer/contact data merely because payments.record is true. Link to the existing Customer workspace for separately authorized lookup, or accept an explicit Customer reference.
4. General history pages can be viewed page by page with clear continuation and refresh controls. Action contexts and Payment reversal impact/result must load a complete sequential context before enabling dependent confirmation. Use actual validated reference-client replies so private provenance is retained. Stop on a stale revision, wrong scope, duplicate/repeated cursor, oversized result, failure or aborted context; never label a partial collection complete. Accumulate a defensive bounded display budget and provide explicit unavailable behavior rather than financial truncation. Reversal sequence exposes completeness but not stored items: the controller must keep detached page items only after append succeeds, and render a completed collection only after the sequence is complete.
5. Source/target/proposal loads are explicit staff actions. Refresh relevant context before preparing a financial confirmation. The command remains subject to final server guards. Exact reviewed command data must be captured before the dialog is shown, then sent through financialRecovery.submit only on its explicit confirm button. Editing source/target/amount/reason, changing workspace or dismissing invalidates that confirmation. Prevent same-tick duplicate submissions with a synchronous busy reference in addition to disabled controls.
6. Recovery ready enables new commands; pending, other-property, foreign, unavailable and invalidated do not. Show an explicit explanation for each. Pending review displays the original operation, Property, source/target and exact amount/evidence from the decoded validated intent. An explicit replay confirmation calls recovery.replay with the original key. Do not offer discard, replacement, key regeneration, automatic retry/replay or clearing. Only the accepted recovery layer retires a key after validated success or a freshly submitted definitive 400/412/422 rejection. Initial and later 409 remain unresolved. Later failures cannot prove a formerly lost response uncommitted.
7. Submit/replay success renders the validated command result and then refreshes authorized source/current context. A subsequent read failure must not undo or obscure the confirmed success, and must not relabel stale derived balances as current. Unknown/malformed/lost success and storage-clear failure show recovery state with safe correlation references. No raw exception/SQL/body/payload logging or console output.

## Domain screens

### Payment and KHR confirmation

Payment list: authorized Property, optional payer/status/accepted-method filters, newest payment date ordering, explicit next page/refresh, original currency/amount, USD value, method snapshot, payer and RECEIVED/REVERSED state. Detail separates immutable payment/receipt/FX/channel/reversal facts from server-calculated current disposition categories and available unallocated USD. Do not total nested histories into a new balance or label Payment excess as Credit. Link explicit authorized actions and separate history displays.

Payment form captures payer Customer, accepted method, received local timestamp, evidence, optional Lease/identified Invoice or Charge intent, normal versus third-party scope, payer-intent memo and channel reference. KHR is incoming only. USD accepts exact cents; KHR accepts whole riel and explicit USD accounting amount. Date-time inputs explicitly say Asia/Phnom_Penh and encode +07:00, not the browser's local zone. Use integer/BigInt parsing, never floating-point multiplication or Number coercion for money. Preserve full valid text within the accepted request bounds.

KHR preview is explicit and provisional. Show returned reference source/value/time, fallback evidence, fixed0.5% markup, rounded system rate, exact unrounded amount and payable KHR as noneditable results. Only a server-declared approved-source outage plus manual permission exposes manual fallback inputs; generic provider errors do not. Discard stale previews when their relevant input changes or a new request starts. Actual channel evidence remains separate and immutable; do not silently replace it with preview results. Read the exact accepted migration43 confirmation rules before deciding any client consistency gate. Final payment creation still selects the authoritative rate; preview is not a persisted quote. Confirmation states that creating Payment/Receipt does not allocate, recognize Credit, create Deposit or settle an Invoice.

Migration43 inspection confirms that actual channel USD value takes precedence; otherwise actual channel KHR amount is converted using actual rate or system rate with the accepted nearest-cent rule. Without actual channel amount, the received KHR must agree with ceiling of USD at the used rate. Channel reference must match Payment reference and any actual channel KHR amount must equal received KHR. Therefore do not require all valid channel-confirmed receipts to equal the provisional system-payable figure or recompute authoritative channel USD in the browser. Capture the explicit original fields and show the applicable source facts; final server confirmation enforces their coherence. The optional channel block needs transaction reference, confirmed timestamp and at least one actual currency/amount/USD/rate fact.

### Allocation, original Receipt and Payment reversal

Allocation uses the action-authorized Payment context and its server position. Present the server FIFO proposal with exact target/line amounts, due/issued/number ordering evidence, original payment designation and continuation status. Confirming a proposal posts only that returned bounded batch. MORE_ELIGIBLE requires a new explicit proposal after the confirmed batch, never auto-posting. A separate manual designated Invoice workspace loads the exact target context/complete current lines, captures explicit line amounts and Customer designation reference, checks positive amounts and obvious source/line/total bounds, and submits the accepted DESIGNATED target/details shape. A Charge target is a separate obligation with its own amount and outstanding balance; direct and designated modes must follow the existing command schema. No broad target discovery grant is inferred.

Original Allocation reversal loads the complete exact Allocation context without replacement-target input. Show immutable original header/detail amounts, target and attribution, current availability/outstanding and any existing linked reversal. Require reason and explicit consequence confirmation. Original remains visible after success; refresh source/current facts and preserve the validated reversal result. General Allocation history uses authorized allocationList, including selected-detail pagination, without pretending that one page is the complete collection.

Receipt uses the stable original UUID/number/issued facts and its immutable identity snapshot. Display original payer, Payment, method/currency/USD/KHR/FX evidence and separately labelled current Payment context. Show existing paginated reprint actor/time/reason/delivery history only with receipts.read. Action-only reprint uses its exact context and required reason/optional delivery reference. Call the reprint command before showing a printable copy of the same identity; never create a second financial receipt in UI. Printing is explicit, with CSS limited to the selected receipt. The screen must not invent payment method/name fields absent from original authoritative facts.

Payment reversal loads all impact pages through PaymentReversalContextSequence. Display parents and line/dependency evidence with relationships, not a misleading sum of overlapping nested amounts. Link each required Allocation/Credit/Refund/Deposit action to its proper workspace and permission. Existing migration39 final guards require explicit downstream resolution; no automatic cascade. Deposit receipt/disposition reversal continues through existing DepositManagement, which already has direct Deposit-ID loading. Its existing scope/permissions remain authoritative. Once blockers are resolved, reload complete impact before confirming reason and expected RECEIVED status. After success or exact replay, load all result pages and show recomputed related Invoice, separate Charge, Credit and Deposit balances plus preserved original Payment/Receipt/reversal history. Failure to load results says they are unavailable; it does not negate the confirmed reversal.

### Credit

Credit list is selected Customer within authorized Property. Show immutable recognition/source Payment, original source currency/KHR/FX, recognized/applied/refunded/reversed/available USD categories and complete paginated ledger. Credit is distinct from both unallocated Payment and Deposit. Recognition requires the action context with explicit payer authorization reference, reason, positive USD amount within current availability and no outstanding applicable obligations. Server eligibility remains final.

Application uses exact Credit/target action context. Invoice mode shows complete target lines and supports returned within-Invoice proposal with amount, or explicit designated line amounts/reference. Charge mode shows the separate Charge with direct/designated exact USD application. Each is a Credit application, never a Payment Allocation. Recognition reversal and application reversal load exact originals/current facts with their separate grants, require reason and preserve linked reversal/original evidence. Already reversed or unavailable source facts cannot silently enable a new action.

### Refund and verified returns

Refund list/detail shows completed immutable payout facts, recipient/source, USD amount, original KHR/FX audit provenance where present, processing actor/authorization/time and linked correction history. No requested/pending/failed business status or generic delivery-method invention.

Create only from supported PAYMENT, CREDIT and PET_DEPOSIT source responses. Pet requires the exact qualifying review and Deposit relation. Show server eligible/max USD and full source evidence, collect explicit positive amount/reason, confirm original payout consequence. Link to existing qualifying Pet/Reservation workflows; do not add Reservation/Final Settlement/Security sources to a finite API that does not support them. Existing Reservation disposition workflow already preserves its own Refund policy.

Verified return loads exact Refund context and displays original payout/net value. Capture exact positive returned USD, local timestamp, actual method reference, evidence and reason. Bound obvious amount by current net original payout and explain that this records demonstrated return only, does not establish a collection right, and preserves the original payout. Correction reversal selects the exact original Refund/correction pair and loads its complete context instead of searching a first history page. Require reason/evidence, show original linked correction/reversal and current net consequence. Every payout and returned value is USD; no Refund-date FX or KHR input.

## Verification and transition

Before source edits, activate the bounded UI stage from independently accepted action context, preserving the previous root state objects and every trace entry. Record exact included paths, remaining lifecycle and regression evidence externally as well as the working ops state. Source files in this plan are suggestions until that inventory is frozen.

Focused tests must cover all12 commands through actual request construction and recovery, explicit confirm/cancel/duplicate-click behavior, original replay bytes/key, shared-store refusal, storage/WebLock failure, no automatic send, safe unknown/rejected/success handling, actor/Property changes and logout during every awaited phase, stale source/target/proposal/preview results, capability-sensitive reads/actions, complete context pagination and failures, each domain source/target/result display, exact amounts beyond JS safe aggregate range, original KHR/channel evidence, USD-only Refunds, valid debit-adjusted Invoice lines, complete reversal dependencies and current result behavior, print identity and reasoned reprint, and existing Deposit/Customer links without permission inference.

Use accessible labelled fields, semantic headings/tables, keyboard dialogs, Escape cancel, focus trap and opener/notice focus restoration. Test empty/forbidden/404/conflict/oversized/error/success states. Confirm dialogs need a descriptive title and consequence text, distinct primary action, and no send until explicit confirm. Disabled controls and status announcements must remain understandable to screen readers.

Use actual synthetic database-shaped fixtures for domain views and actual clients in component/browser tests where provenance matters. Browser checks should exercise real IndexedDB/WebCrypto and keyboard/focus with synthetic network responses only. No screenshots/customer/production data or provider activation required. Run frontend formatting/lint/real project type checks/tests/build, appropriate focused backend unchanged-boundary checks, traceability, then all required exact frozen-candidate gates and one complete-base Astra/max/Standard/read-only zero review. Schedule the full frontend suite alone because the preserved99 Customer timeout cause is unproven; do not change its timeout/assertion.

After bounded UI acceptance, the whole V1-052 cumulative diff from f8a33ba still needs release checks, fresh exact independent review, normal publication, exact-SHA CI/ref equality, SAME-card acceptance and durable closure. Only fully closed52 allows activation53. Fully closed53 pauses the SAME native follow-up, keeps OpenClaw disabled and leaves54 untouched. The separate Workboard transmission restriction remains an explicit potential closure blocker, not permission to retry.

## Accepted historical and execution constraints

The five additional database tests provide 15 new actual synthetic projections, appended to the original 34. Use these historical cases in eventual UI tests: multiple contributing applications and Refunds, another active application after reversing the selected original, several demonstrated returns and a selected correction reversal, fully returned Refunds after Credit/Payment reversal, changed current Customer name with original Receipt identity, and retained Reservation replacement evidence.

A Reservation's Deposit has canonical type SECURITY. Distinguish the legacy coordinated Reservation Refund by non-null source_lifecycle_event_id; the word Reservation is its lifecycle relationship, not a Deposit enum. Current Payment/Credit/Pet returns require demonstrated USD return fields. The legacy projection retains null original-minor and return fields and must never display invented proof of a money return. The current financial Refund command family supports Payment/Credit/Pet sources; verify the actual command's permitted source family before presenting a return or correction-reversal confirmation for a historical Reservation Refund. Route any retained Reservation outcome correction through its existing coordinated workflow and permissions.

Selected originals and current aggregate positions are different facts. Other allocations, applications, Refunds or return corrections can contribute to the current aggregate. Display the exact selected event separately from source totals and do not imply equality. A fully returned payout remains a historical Refund even when the source Payment or Credit was subsequently reversed. Read-only historical context must stay accessible; source status may prevent a new action without hiding the original evidence. Receipt reprint remains available under its own permission after Payment reversal.

Receipt identity is the original seven-field issuance record, including its one historical payer-name snapshot. The original issuer need not be the current reader. Do not look up a current Customer name to replace the snapshot or infer a new Customer grant. Issuance may follow Payment confirmation; the UI must not require equal timestamps. Existing microsecond comparisons remain in the validator; display formatting must not be reused for chronology or amount validation.

The action sequence still requires complete counts, original/adjusted/current totals, unchanged revision, actual private provenance and the cumulative 8 MiB limit. The new source/return/Receipt checks add no new write authority. Keep all original recovery behavior, explicit confirmation, original-key replay, abort/generation rules, independent grants and no automatic sending.


The financial panel belongs beside the existing Invoice panel, is keyed by the authenticated actor and is absent during logoutPending. Property discovery uses financialReferenceClient.workspaces. Every Property switch unmounts the previous keyed workspace and aborts its controller; generation checks also reject completion from old reads or confirmations. No configuration Property or Customer permission is inferred.

| Command | Capability | Fresh context before confirmation |
| --- | --- | --- |
| paymentRecord | payments.record | Accepted methods; provisional KHR preview if applicable |
| allocationPost | payments.allocate | allocation plus exact proposal or complete chosen target |
| allocationReverse | payments.allocations.reverse | allocation_reversal for original Allocation |
| paymentReverse | payments.reverse | Complete paymentReversalContext impact |
| receiptReprint | receipts.reprint | receipt_reprint for original Receipt |
| creditRecognize | credits.recognize | credit_recognition for source Payment |
| creditReverse | credits.reverse | credit_reversal for original Credit |
| creditApply | credits.apply | credit_application plus exact target/proposal |
| creditApplicationReverse | credits.applications.reverse | credit_application_reversal for original application |
| refundCreate | refunds.create | refundSource for PAYMENT, CREDIT or PET_DEPOSIT |
| refundReturn | refunds.correct | refund_return for original Refund |
| refundReturnReverse | refunds.corrections.reverse | refund_correction_reversal with original correction source_id and refund_id |

The action context constructor takes the complete request including operation, without a cursor. Append each original validated reference reply before detaching its data. Continue sequentially using nextCursor and retain no partial display after failure. The completed action sequence already enforces the 8 MiB cumulative budget. Payment reversal sequences retain their own internal graph and expose no data getter, so the UI loader must apply a cumulative byte limit before append, append the authentic reply, then accumulate detached items for display. This bounds both graph and display copies. Clear all UI-owned partial arrays on error and expose complete results only after sequence.complete. Use a maximum page count as an additional liveness bound; it is an availability limit, not a claim about business history completeness.

Capture a command with captureFinancialRequest before opening confirmation. Decode its exact wireBody through commandBody, detach and deep-freeze the command-only request snapshot, and derive the displayed finite domain summary from that same snapshot. Keep the captured wire bytes and check equality when submitting the frozen snapshot. CapturedFinancialRequest is not itself the recovery.submit input: it includes wireBody/query while FinancialRequest commands require body. Do not use a cast to pass the wrong shape. Invalidate the dialog on any source, target, form revision, actor or Property change. Use a synchronous busy guard before the first await.

Recovery replay uses the decoded PendingFinancialCommand only to render the original intent. Dispatch exclusively through financialRecovery.replay(scope, originalKey), which retains the saved bytes and bindings. Never turn that intent back into a fresh submission. New commands require ready; pending, other-property, foreign, unavailable and invalidated each show a finite explanation. Read-only screens remain available subject to their own grants even if crypto is unavailable.

Actual migration41 require_correctable_usd_refund rejects non-null source_lifecycle_event_id and non-USD Refunds for both verify_usd_refund_return and reverse_refund_correction. Legacy Reservation Refunds therefore remain readable but cannot expose these general correction commands. Their Deposit type is SECURITY, and their outcome correction stays in the existing Reservation lifecycle workflow.

Canonical BR-PROP-003 and financial workspace validation fix the timezone as Asia/Phnom_Penh. Form timestamps encode the explicitly labelled local time with +07:00. Preserve microseconds when displaying evidence and never use display formatting for chronology checks. Money parsing uses exact integer minor units and full bigint aggregate range; do not derive eligibility or recompute authoritative balances in the UI.


## Frozen path inventory

- frontend/src/FinancialManagement.tsx
- frontend/src/financialUi.ts
- frontend/src/financialUiContext.ts
- frontend/src/FinancialConfirmation.tsx
- frontend/src/FinancialRecoveryNotice.tsx
- frontend/src/FinancialPaymentWorkspace.tsx
- frontend/src/FinancialAllocationReceiptWorkspace.tsx
- frontend/src/FinancialCreditWorkspace.tsx
- frontend/src/FinancialRefundWorkspace.tsx
- frontend/src/FinancialEvidence.tsx
- frontend/src/FinancialManagement.test.tsx
- frontend/src/FinancialWorkspaces.test.tsx
- frontend/src/FinancialConfirmation.test.tsx
- frontend/src/financialUi.test.ts
- frontend/src/financialUiContext.test.ts
- frontend/src/test/financialWorkflows.browser.ts
- frontend/src/App.tsx
- frontend/src/App.test.tsx
- frontend/src/styles.css
- backend/tests/test_traceability.py
- ops/NOW.md
- ops/STATE.json
- ops/QUEUE.md
- ops/traceability.json
- ops/V1_052_FINANCIAL_STAFF_UI.md

Accepted backend runtime, migrations, grants, dependency manifests and financial clients are preserved. New gaps require their own explicit bounded scope; do not weaken accepted contracts for UI convenience.


## Bounded Credit proposal continuation correction

The original25-path inventory is extended only by `frontend/src/financialResponse.ts` and `frontend/src/financialClient.test.ts`, under the standing authorized bounded-correction lifecycle. The immutable initial activation remains unchanged. External scope receipt: /Users/sokompheak/.codex/.chatgpt-projects/g-p-6a721755d4048191b2550824162f9521/v1052-financial-staff-ui-credit-proposal-scope.json SHA256 28ef3e606ec4d3b6a8a15c34cd5ceb1acfe237f8875a0542483ba87e696df448.

Migration41's `credit_application_proposal` returns a bounded batch: the original requested amount may exceed the returned amount. Its existing500-line backend regression proves501requested/500returned/1remaining followed by1/1/0. The accepted client incorrectly requires returned amount to equal requested amount. Record an actual-client red witness, then make the smallest coherent continuation correction with adversarial regressions. Retain exact original request binding, positive bounded batch, exact remaining value, explicit continuation and returned line totals; confirm only the returned batch. Never auto-post or silently resize the user's request. No backend, migration, role, dependency, canonical policy, command, recovery or scope protection change is included.

This correction is part of the eventual complete013-base staff UI candidate and independent review. It is not separately accepted by changing the inventory, and no prior failed report or test is superseded or deleted. All411 remaining protected files and28 historical root objects remain frozen.

## Focused verification before immutable candidate

All four financial workspaces,12 explicit command reviews, authenticated App integration, complete post-confirmation related reads and original-Receipt print layout are implemented.74helper/118workspace/32controller/11confirmation/46App/110Credit-client focused checks pass. Six Chromium groups cover20scenarios with real encrypted IndexedDB, WebCrypto, WebLocks, native keyboard/focus,360px dialog and Receipt-only print media; injected synthetic responses only, zero financial network requests. Original1733trace entries retained plus93new=1826;28trace/audit checks pass. Browser-derived Property label and modal action-name gaps were corrected with regressions. Shared-store foreign ownership is correctly described as another workflow; its final11presentation tests pass.

This is focused evidence only. Freeze a normal27-file candidate from013, run all applicable exact checks and obtain fresh complete013-baseAstra/max/Standard/enforced-read-only review with zero HIGH/MEDIUM/LOW under the externally retained standing authorization. All failed fixtures, test runs, browser diagnoses, previous candidate objects and reviews remain preserved. The unchangedbackend47migration and command/recovery boundaries remain authoritative. Cumulative52publication/CI/ref/SAMEcardclosure and53remain unfinished. The Workboard note hold is separate; no retry is authorized by the OpenAI source-review grant.

## Test-only clock correction after frozen74 gate failure

The immutable74ee3bb candidate passed1250frontend,2557backend,187static/build/import and189automation checks, but full PostgreSQL ended1001passed/2failed. One raw Refund rollback test still used host datetime.now(UTC); the unchanged original fails the same demonstrated-return guard with controlled host skew in both directions. The second PAYMENT-KHR Refund API503 remains cause-unproven; all6affected-family cases passed in a separately observed unchanged-source run. No retrospective timing or lock-holder cause is claimed.

Extend the complete013-base inventory by only backend/tests/test_refund_service_migration.py and backend/tests/test_financial_fixture_clock_migration.py, making29paths and409protected. Correction1 replaces only the raw fixture timestamp with the existing database_instant(connection) helper and adds a direct regression in the already isolated clock module. Preserve rollback command/event/audit assertions, real timestamps, production SQL chronology and NOWAIT guards. Seven correction paths include only these2test files and5existingops evidence files. Frozen74,failedlogs,diagnosticprobe,deterministicreds and allpriorhistory remain immutable. Full successor gates and a fresh complete013-base29path independent review are required under standing through53authority.

## Clock correction1 focused verification

All16selected PostgreSQL checks pass, including both preserved external synthetic host-skew red witnesses and the newly registered two-direction regression against the original rollback proof. Two-file format/ruff,187-file types and28trace checks pass;1827mappings preserve1826previous entries. The test fixture now obtains its demonstrated-return timestamp from the same authoritative database clock as existing neighboring fixtures. Production source, SQL chronology and all rollback assertions remain unchanged. The original API503 remains cause-unproven. Freeze a normal seven-path successor and require full exact gates plus an independent complete013-base29-path review. No acceptance or publication is claimed by these focused checks.

## Existing automation test synchronization correction

Preserved09bd8e8 passed1005PostgreSQL,2557backend,1250frontend,187static/build/import and27browser groups. The automation gate ran189tests with one error: after the second background restoration run, the existing fixture inspected its fake terminalizer log before the second unload completed. The retained late fake log and controlled0.2second second-unload delay reproduce the same1!=2assertion. The original diagnostic loader failed before test execution; its corrected AST selector reproduced the actual original scenario. All logs remain preserved.

Extend the inventory only by scripts/test_openclaw_automation.py:30complete013-basepaths and408protected. Five correction paths include that test and four existing ops records. Add the missing completion wait using the existing2second deadline/10ms poll and a controlled delayed second-unload subcase. Preserve exact unload counts,notification idempotency and fail-closed assertions. Runtime automation,real schedulers,product source,SQL and dependencies remain unchanged. This is correction1 for a distinct test synchronization finding. Fresh successor gates and complete-base independent review remain required; the original74API503 remains cause-unproven.

## Automation correction1 focused verification

The existing restoration test passes all12subcases:11original and one controlled0.2second delayed second-terminalizer case. The missing second-run completion wait uses the existing2second deadline/10ms poll; strict exact two-unload-pair assertions remain unchanged. AST comparison proves every original assertion is preserved and all source outside this one test method remains byte-identical. Scoped formatting/syntax and baseline-lint parity pass with no new findings. Supplementary whole-script lint exposes four preexisting unmodified findings (BLE001,FURB192,twoSIM117); the failed check and full-format draft remain preserved, unrelated formatter changes restored, no rule disabled.28trace/audit checks pass with1827unchanged entries. Freeze the normal five-path successor and require all exact gates plus fresh complete013-base30-path independent review. Full automation will run alone; no claim that concurrent backend work was necessary for the original race.

## Independent review correction1 after0308d33

Fresh Astra/max/Standard/enforced-read-only review86189 rejected the complete30-file/3-commit change from013 with0HIGH/3MEDIUM/2LOW. The root confirmed all findings: competing asynchronous form preparations can replace another confirmation; loaded mutable positions remain labelled current across commands; Payment detail omits original received/evidence/Receipt facts and explicit Receipt handoff; proposal Customer row is duplicated; money table cells align left contrary toUI-020. The report,96independent commands,exact passing gates and all prior failed candidates/regressions remain preserved.

Correction1 uses19existing paths and retains all30complete paths/408protected files. Add shared preparation ownership and cancellation/supersession guards; invalidate or clearly mark mutable reads stale after revision while preserving immutable originals/confirmed results; show exact original receipt evidence and a separate-grant Receipt handoff; remove duplicate keys/facts and right-align money cells. Cover integrated cross-form cancellation, post-command/reload failures, original/legacy/forbidden Receipt evidence, unique rows and computed browser alignment. Preserve1827priortrace mappings,all28historical root objects,unchangedbackend/SQL/automation/dependencies/transport/recovery/storage/canonical docs. Each of the5distinct findings is at correction attempt1; no global reset or waiver. A normal successor and fresh complete013-base zero review are mandatory before acceptance. The cumulative release draft remains conditional and unactivated.

## Review correction1 focused verification

All5confirmed findings are addressed. Shared scope-bound preparation ownership is reserved before async work and invalidated on supersession,cancellation,refresh,replay,command start and unmount. Completed preparation is single-use. Revision-bound tasks reject both obsolete completions and obsolete run callbacks; retained read snapshots preserve original facts while hiding stale current positions/history and explaining required authorized reload. Original received timestamp keeps six fractional digits/offset; evidence/Receipt number/reference and legacy-null distinctions are explicit. Original Receipt handoff independently checks read/reprint grants and actor/Property/lifecycle signal, opens the exact original identity via GET and never confirms a reprint. Duplicate Customer facts are removed.39monetary headers/cells and decimal inputs align right with exact currency labels/overflow retained.

243focused tests,28trace tests,final types/scoped lint/format pass; all1827trace mappings retained plus11new=1838. Three new Chromium groups verify360px money alignment,competing preparation,originalReceipt GET and stale positions after explicit Refund;0financialnetwork. Six original groups also pass in the first wrapper result. That wrapper selected the old runner and failed the9group expectation; corrected runner initially used an overly strict accessible method name. Both wrapper failures retained; focused3groups pass after selector correction. Browser evidence predates final formatting,obsolete-run callback guard and removal of a redundant explicit scroll method; final component/type/lint tests cover these and the frozen successor will execute all9UIgroups. Three local HMR console errors remain qualified; no clean-console claim or raw console transmission. Expected2race/5snapshot+duplicate/4Receipt red cases and earlier test harness/type/lint failures are preserved. No rules suppressed, no business/backend/SQL/automation/transport/recovery/storage/canonicaldoc change. Fresh full013-base independent zero review is required.
