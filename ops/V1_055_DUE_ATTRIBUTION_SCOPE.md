> **SUPERSEDED 2026-09-30.** The owner withdrew the within-line due-date attribution policy. This scope is historical only and authorizes no work; see `docs/010_DECISION_LOG.md`, entry "V1-055 owner rule changes and withdrawal of within-line due-date attribution — 2026-09-30".

# V1-055 — governing due dates and within-line attribution

Accepted base: `cdf1492e0d920bc70ef690ab34183d1bbc578d2f`. Standing owner authority and accepted earliest-due-first policy apply. Full scope and preservation receipt: `/Users/sokompheak/.codex/.chatgpt-projects/g-p-6a721755d4048191b2550824162f9521/v1055-invoice-due-attribution-scope.json`.

- Governing debit due-date/source evidence without changing original Invoice due date
- Deterministic earliest-due-first allocation only within one Invoice line for undesignated Payments/Customer Credits
- Append-preserved source attribution, explicit correction/reversal and exact historical/replay behavior
- Connected overdue/nonpayment calculations and directly affected Invoice command/UI inputs
- Affected regression, migration, concurrency, authorization, history, audit and final mandatory gates

Plan:
1. Implement/test pure deterministic within-line proposal over already source-validated remaining amounts; no database calls
2. Inspect and freeze precise forward storage/command attribution design including legacy records, credit adjustments and reversals before migration edits
3. Implement connected SQL/command/readers and minimal affected UI, preserving old exact replay and explicit unresolved missing evidence
4. Run fresh affected tests and applicable mandatory gates; reuse unchanged evidence only with proven identity
5. Freeze normal local exact candidate and obtain independent complete-stage Astra/max/Standard/read-only/never review; corrections follow standing policy

Limits:
- No change to between-Invoice FIFO, Rent-before-Service, customer designations or staff confirmation
- No invented historical dates, silent historical re-attribution or transaction rewrite
- No alteration of application locks/timeouts/retry policy or accepted refund fixture
- No extra recovery diagnostic invocation or consumed-allowance reset
- No whole-version closure, publication, V1-056 activation or production

No stage acceptance until connected persistence, readers, workflows, applicable mandatory gates and fresh independent zero-finding review pass. Financial-stage testing does not authorize repetition of consumed recovery diagnostics or modification of the accepted fixture.

Storage design frozen at `/Users/sokompheak/.codex/.chatgpt-projects/g-p-6a721755d4048191b2550824162f9521/v1055-invoice-due-attribution-storage-design.md` (SHA256 `de540feaf72431199323f5cfaff3bae9835c9b9b123fd7042a116a5546f83e1c`).
The same authorized stage now includes `backend/src/property_rental/invoice_due_history.py` and `backend/tests/test_invoice_due_history.py`: explicit legacy evidence, as-of source parts and exact reversal projection. The original proposal module/tests remain unchanged. No database run, fixture correction or acceptance is implied. Connected transport/UI paths will be named before their edits.


Payment/Credit dated confirmation contract: /Users/sokompheak/.codex/.chatgpt-projects/g-p-6a721755d4048191b2550824162f9521/v1055-invoice-due-application-helper-contract.md. The current bounded step admits backend/tests/test_invoice_due_application_migration.py alongside the existing migration62: no-write source-part proposal/explicit-selection helper and fresh affected verification. Connected transport/UI files must be named before their edits. All prior limits and required acceptance remain in force.


Generated proposal step: /Users/sokompheak/.codex/.chatgpt-projects/g-p-6a721755d4048191b2550824162f9521/v1055-invoice-due-generated-proposals-plan.md admits backend/tests/test_invoice_due_proposal_migration.py for14fresh affected cases. Only existing proposal producers and mandatory suite registration change. Posting/HTTP/UI and full independent acceptance remain pending.


Atomic posting step: /Users/sokompheak/.codex/.chatgpt-projects/g-p-6a721755d4048191b2550824162f9521/v1055-invoice-due-atomic-posting-plan.md admits backend/tests/test_invoice_due_posting_migration.py for25fresh connected cases. Only existing migration62 and mandatory suite registration change. No accepted Refund fixture edit,lock/timeout change or historical allowance reset; explicit preview/callers/staff and final independent acceptance remain pending.


Read-only designation builder: /Users/sokompheak/.codex/.chatgpt-projects/g-p-6a721755d4048191b2550824162f9521/v1055-invoice-due-designation-builder-plan.md admits backend/tests/test_invoice_due_preview_migration.py for22fresh cases. Only migration62 and suite registration change. No existing function,accepted fixture,lock/timeout/retry,grant or historical allowance change. Authorized wrappers/transport/staff and final review remain required.


Authorized read-only previews: /Users/sokompheak/.codex/.chatgpt-projects/g-p-6a721755d4048191b2550824162f9521/v1055-invoice-due-preview-wrappers-plan.md admits backend/tests/test_invoice_due_preview_wrappers_migration.py for43fresh cases/13functions. Only migration62 and suite registration change. No existing function,accepted fixture,lock/timeout/retry or historical allowance change. Grants use only existing read service roles. Connected transport/staff and full independent acceptance remain pending.


## Python preview boundary — 2026-09-16T11:05:59.518035+00:00

Standing lifecycle authority applies. SQL preview wrappers43cases and their exact source evidence remain locally verified. This step adds no database invocation and does not accept the financial stage.

Admit exactly due_preview.py, allocation_read.py, credit.py, test_due_preview.py and test_due_preview_services.py under backend source/tests, plus existing records/specification paths. Preserve every current SQL/helper/fixture and command transaction. Add a frozen detached DesignationPreviewInput with strict Payment/Credit DESIGNATED shapes, normalized reference, exact positive bounded amounts, unique targets/lines/sources, matching line/target totals,100targets/500details/500explicit-source-parts and250KB UTF8 envelope. Only three-field source_parts are accepted as preview selections; computed due_attribution/version is not preview input. A preview is never a command and has no key.

Add AllocationReadService.designation_preview and CustomerCreditService.application_preview. Require their existing exact Property action capabilities before connection, valid non-nil source/actor identities and immutable detached input. Use only runtime/read database URLs, repeatable-read/read-only coherent transactions,existing3second connection/lock and5second statement limits,UTC and exact JSON loader. Verified SQL wrappers recheck the current active HUMAN and all source/target context. Match existing safe not-found/invalid/authorization/conflict/unavailable error families without exposing database text. Do not alter existing methods or command locks/recovery/retry.

Extend only the strict Credit DESIGNATED Invoice parser to accept either the exact historical shape or a complete versioned confirmation. New confirmation requires a positive bounded integer invoice_version and due_attribution on every detail: exact basis and1..500six-field parts,typed identity/date/time,positive bounded amount/outstanding,unique source identity,exact detail and whole-command sums/counts. Keep original JSON encoding untouched for replay. Never admit preview source_parts to posting; reject mixed versioned/legacy detail shapes and premature metadata. Existing historical/PROPOSAL/Charge parsing remains unchanged. SQL remains authoritative for freshness,authorization and current balances.

Run fresh formatting/lint/strict-type checks for affected paths, new pure/service tests plus existing Credit and allocation read tests affected by this integration. No database diagnostic or previously completed unchanged SQL gate will be repeated. Capture exact test-function and parameterized-case counts after collection; preserve failed checks and bounded correction history. Subsequent real-service migration tests,HTTP/client/staff integration,shared callers,dated overdue/Rent/Invoice and full independent financial/integrated acceptance remain mandatory. No publication or version transition.


## Real-service preview integration — 2026-09-16T11:30:54.351270+00:00

Standing lifecycle authority covers this new integration gate. Prior215Python/43SQL preview cases remain complete and unchanged. No historical recovery diagnostic or allowance reset.

Admit only test_invoice_due_preview_service_migration.py and mandatory database-test suite registration. Preserve all application source,SQL,shared helpers and accepted fixtures. Use existing funds,due_connection and legacy_due_connection. Commit synthetic setup before separate runtime/financial service calls. Do not hold test-only pending mutations across command calls. New local instrumentation wraps real runtime psycopg connections without changing SQL,transactions,locks,timeouts or assertions; immediately before preview it records actual generated host/port/database,prm_runtime role,READ ONLY,REPEATABLE READ,3slock,5sstatement,UTC and wrapper visibility. No credentials or financial rows in observer metadata.

Six functions/eighteen cases in declaration order: default or explicit source preview-to-service-post and exact replay for each Payment/Credit(4); unknown or freshly disabled HUMAN despite capability(4); missing capability or wrong Property capability before connection(4); stale preview after committed approved debit before posting(2); missing source mapped safely(2); actual61legacy service post then62upgrade,exact historical service replay and read-only current preview without rewriting legacy evidence(2). Initial Credit recognition always uses the unchanged true-excess-before-Invoice helper. Historical holder diagnosis is not reopened.

Before execution require affected format/lint/strict types,exact18-case collection and bound source/helper hashes. One fresh disposable gate:180seconds execution,30seconds owned cleanup,210seconds total;stop first failure with no automatic retry. Require36phase-specific actual fixture-target/schema observations,14actual runtime-preview connection observations,four capability-denied cases with zero preview connections,two61to62upgrades/removals and54passing phases,no skips. Verify all owned container/network/volume/generated-secret cleanup. On failure preserve evidence and consumed invocation before any bounded materially different correction analysis; never reset an existing family.

Passing verifies this integration only. HTTP/client read classification,staff source/date confirmation,shared callers,dated overdue/Rent/Invoice and all financial/integrated acceptance and fresh independent exact-SHA reviews remain required. No publication or56activation.


## Non-mutating HTTP previews — 2026-09-16T11:54:26.152089+00:00

Standing lifecycle authority applies. Admit exactly the two existing Allocation/Receipt and Credit/Refund API modules,existing Allocation/Receipt fake-flow test module,and new test_due_preview_api.py. Existing SQL,services and migration fixtures stay unchanged. The fake flow gains only the new protocol method so old tests continue type checking; its existing methods/tests remain unchanged.

Add POST /api/v1/payments/{payment_id}/allocation-preview and POST /api/v1/customer-credits/{credit_id}/application-preview. Payment uses existing {intent} envelope;Credit uses existing {currency:USD,intent} envelope. Reuse existing strict bounded JSON dependencies and input models. Reject unknown queries,duplicate headers,missing/invalid Origin/CSRF and any Idempotency-Key. Resolve current actor/resource/Property with exact payments.allocate or credits.apply capability and bind financial metadata. Validate and detach the shared DesignationPreviewInput before forwarding;invalid body is422. Existing safe query error mapping gives400invalid service state,404opaque missing/unauthorized,409conflict,503unavailable. No command constructor,key,201status,Location,financial URL or recovery receipt.

Extend Payment flow Protocol/Postgres flow with designation_preview forwarding only to AllocationReadService(runtime). Credit uses flow.credits() read mode and its verified application_preview. Return200with existing data/meta envelope only when response is an object and source/Property identities exactly match resolved context;malformed response503,context mismatch404. Preserve existing route behavior and shared context helpers.

Fresh affected static checks and full-app tests cover both new routes for normal/explicit/Charge selections,body/currency/count/type bounds,exact forwarding without write calls,authentication/capability/scope,Origin/CSRF/duplicate/key/query controls,response scope/malformed shapes,safe errors and no command header/OpenAPI requirement. Re-run affected existing Allocation/Receipt and Credit/Refund API tests. No database invocation or unchanged service/SQL/Python gate repetition. Client POST-read classification/body/CSRF/response contracts and staff confirmation remain a later bounded integration;full financial/integrated gates and fresh independent reviews remain required. No publication or56.


## Client preview contract — 2026-09-16T12:18:04.748952+00:00

Standing lifecycle authority applies. This bounded substep admits only frontend/src/financialDuePreview.ts and its new test module, plus already admitted records/specification paths. Existing source, commands, transport, screens, SQL and fixtures remain unchanged.

Provide one detached strict preview-body validator for Payment/Credit DESIGNATED selections, reusing exact JSON, UUID, integer, normalized text and calendar/timestamp primitives. Match the approved body/currency envelope and backend limits: 100 Payment targets, one Credit target, 500 lines/explicit source parts in the whole selection, positive bounded integers and exact sums, unique identities, 250KB intent and depth24. Reject computed confirmation fields in selection, unsafe values, duplicate JSON and unknown keys without changing captured values.

Validate returned preview source/Property, amount/availability/part count and complete confirmation against the captured request. Preserve target, line and explicit source order/identity/amount/reference; require current positive Invoice version and exact six-field dated parts, valid approved date/aware timestamp, unique sources, bounded outstanding and no over-application. Explicit sources require CUSTOMER_DESIGNATED and an exact match; default sources require EARLIEST_DUE. Do not recompute allocation policy or rewrite server facts. Charge targets retain their separate exact shape. Enforce 500 total parts and 200KB confirmation intent. No caller, transport or command behavior changes in this substep.

Verify the two new files with format/lint, whole frontend type checking (new imports must integrate), and only fresh dedicated unit cases for valid default/explicit/mixed targets, exact big integers, descriptor-safe detachment, all input/response bounds, mismatched context/order/sums/choices and unchanged captured source facts. One bounded unit invocation with180second ceiling and no automatic retry. No database invocation, dependency addition, old recovery allowance change or acceptance claim. Next connect the contract to explicit POST-read classification/body/CSRF and staff confirmation, then all required financial/integrated gates and independent reviews. No publication or56.


## Explicit POST-read transport — 2026-09-16T12:43:13.785546+00:00

Standing lifecycle authority applies. Admit exactly financialContracts.ts,financialClient.ts,financialResponse.ts,financialUi.ts,test/financialFixtures.ts and new financialDuePreviewTransport.test.ts under frontend/src. Existing preview validators,SQL,backend,financial recovery/store and staff components remain unchanged. Existing traceability inventory/records paths are already admitted.

Add two finite operations: allocationPreview POST /payments/:id/allocation-preview and creditPreview POST /customer-credits/:id/application-preview, both200. Introduce an explicit preview-operation type/predicate and exclude it from FinancialCommandOperation. Body-capable request capture must accept only the strict existing preview validator and preserve original wire bytes. Reject query/path/body ambiguity. Existing GET and command capture validation remains unchanged. Change the UI command request type from presence-of-body to actual command operation identity, so previews are permitted by existing read helpers and denied by existing recovery and confirmation guards.

Transport POST previews with exact JSON body,Content-Type and current CSRF;include existing current actor/Property/request identity,credentials,no-store and redirect/deadline/abort rules. Never assign or accept an Idempotency-Key for preview reads. Validate successful response source/Property and complete dated selection with the verified preview reply validator. Keep all old command/recovery semantics intact. Finite synthetic fixture map gains only the two new operation entries;old fixture arrays/responses stay unchanged.

Dedicated fresh tests cover finite capture/type classification,read helpers,exact bytes and detachment,headers/no command identity,CSRF failure before dispatch,invalid request/body/query/target,returned context/selection/date failures,HTTP errors,deadline and abort behavior,denial of direct and stored preview recovery,unchanged existing operation registry. Re-run affected existing financialContracts,financialClient,financialRecovery,financialUi and financialUiContext unit suites once,under180seconds,stopfirstfailure/noautomaticretry. Fresh format/lint on changed files,whole frontend types and production build are mandatory. Reuse144unchanged scalar/preview contract cases via unchanged module and shared scalar source binding;do not rerun database or historical recovery gates. Keep safe exact serializer/primitives,legacy command bodies,shared recovery and accepted fixtures unchanged. Financial/staff and full independent acceptance remain pending;no publication or56.


## Dated Credit confirmation client — 2026-09-16T13:08:01.618166+00:00

Standing lifecycle authority applies. Admit exactly frontend/src/financialContracts.ts and two new files financialDueConfirmation.ts/financialDueConfirmation.test.ts;existing traceability/records paths remain admitted. Preserve preview validators,transport,response,recovery/store,UI/backend/SQL and all fixtures.

Add an exact typed validator for dated Invoice confirmation details matching backend due_preview.validate_due_confirmation:positive Invoice version <=9999999999,unique1..500line IDs,positive exact amounts <=9e15,exact line/whole totals,exact due_attribution basis/parts keys,EARLIEST_DUE or CUSTOMER_DESIGNATED,unique typed source IDs,strict approved dates/aware timestamps,positive outstanding <=signedBIGINT,no over-application and whole500part bound. Preserve captured order,bytes,source dates and integer facts;perform no allocation calculations or normalization. Original sources must identify their parent line,consistent with the source contract.

Extend only Credit DESIGNATED Invoice intent validation when invoice_version is present:admit that field and require complete dated details through the new validator. Legacy no-version path keeps its exact prior shape and checks;Charge and all other command branches stay unchanged. Missing/extra/mixed fields reject. This permits exact stored legacy replay validation;it does not permit new legacy postings at the server,which still requires a fresh preview.

Fresh focused cases cover accepted dated Credit/Payment/designated/generated/Charge capture,exact raw-byte preservation and detached values,invalid versions/dates/timestamps/source identities/amounts/sums/duplicates/counts,mixed legacy/new fields and old captured command/recovery compatibility. Run only new suite plus affected existing financialContracts/financialRecovery/financialUi suites once,180second ceiling,noautomaticretry. Fresh format/lint,whole frontend types and production build;reuse unchanged preview validator/transport/HTTP/SQL gates via exact hashes and unchanged existing function/body branches. No database run,old allowance reset or stage acceptance. Then staff source/date selection and confirmation,connected overdue/callers,remaining gates and independent complete financial/integrated reviews. No publication or56.


## Authorized paginated dated-source read — 2026-09-16T13:34:35.292463+00:00

Standing financial-stage authority applies. This initial bounded implementation changes only unpublished migration62,adds test_invoice_due_sources_migration.py and registers it in the mandatory database test script. All current SQL function bodies,services,fixtures,locks/timeouts/retries and prior allowances remain unchanged. Only upgrade receives one call to the new function creator.

Add app.financial_invoice_due_sources_page(property,actor,purpose,source,invoice,line,limit,expected_revision,after_kind,after_id) as STABLE SECURITY DEFINER,pg_catalog search_path,UTC. Restrict purpose to allocation/credit_application,limit1..100 and paired canonical cursor fields. Reuse existing financial_action_context_page with the exact source/Invoice context to enforce current active HUMAN,Property,Customer and third-party restrictions. Require the line to belong to that Invoice and Invoice status UNPAID/PARTIALLY_PAID/PAID. Reject unsupported application context and unresolved legacy attribution;never return missing attribution as empty/zero. Do not grant direct access to private history helpers. Grant only the new read wrapper to existing prm_runtime;revoke PUBLIC,financial and bootstrap access.

Read current private invoice_line_due_position_at under the caller's existing read-only repeatable-read transaction and3s/5sdeadlines. Return only positive eligible sources ordered by approved date,source occurrence,kind under C collation andUUID. Page limit+1 internally and return at most limit rows,has_more,total item count,current aggregate,Invoice version and server as_of timestamp. Each source row contains exactly source_kind,source_id,approved_due_date,source_occurred_at,remaining_usd_cents. Wire result <=100000bytes;no nested unbounded history or blocker arrays. Empty is valid only for a fully attributed zero-balance line.

Revision SHA256 binds actor,Property,purpose,source,Invoice,line,page limit,existing complete action-context revision evidence/context/target and the complete line projection excluding its changing as_of field. Continued reads require the same revision and an existing positive source anchor;changed financial facts or a transferred/modified revision reject withP4507. A missing or malformed anchor rejects22023. Current source pairs determine the full due-order anchor server-side;clients cannot invent ordering values. No locks,keys,commands,state writes or new allocation policy. Preview/posting still revalidate all current facts before a separately confirmed command.

Planned49fresh cases across8functions:6read-only ordered pagination cases;16invalid parameter/cursor cases;12source/Property/Customer/line/fresh-actor cases;6stale debit/post/page-limit cases;2depleted-source cases;2real61to62legacy-blocker cases;1role/function metadata case;4missing/forged anchor cases. Preserve all current source/proposal/preview and accepted fixture evidence. Exact collection determines the manifest;required actual generated database/schema entry/exit observations for every case,read-only runtime observations in6positive cases and2ownedlegacy removals. One fresh feature DBgate,180second execution+30second owned cleanup=210total,stopfirstfailure/skip/inconclusive observation/timeout/cleanupfailure/restriction,noautomaticretry. This is new feature verification,not another lock diagnostic. Do not execute until static checks,exact collection and complete prepared manifest pass.

After SQL verification,freeze the Python/API/client contract: GET /properties/{property}/financial-due-sources with exact purpose/source_id/invoice_id/invoice_line_id/limit/cursor;current payments.allocate or credits.apply capability before connection;source-context wrapper in existing runtime read-only transaction;bounded cursor revision:kind:uuid;409for stale/unresolved evidence. Staff source choices remain separate from line totals and cannot exceed the500confirmed-part budget. Connect selected parts to existing POST previews and display their authoritative dated evidence before explicit confirmation. Those connected paths require separate admission and fresh affected gates. Full financial/integrated independent reviews and V1-055 closure remain mandatory;no publication or56.


## Authorized dated-source Python/API read — 2026-09-16T14:08:11.342159+00:00

Standing financial-stage authority admits only the five paths recorded here. Add financial_due_sources.py with an immutable request,finite allocation/credit_application purposes,non-nil UUIDs,strict1..100limit and canonical revision:source-kind:UUIDcursor. Require exact payments.allocate or credits.apply capability for the Property before any database connection. Reuse unchanged FinancialReferenceService._read for one fresh HUMAN/Property-checked read-only repeatable-read transaction,3second connection/lock and5second statement deadlines,UTC. Call only the already verified financial_invoice_due_sources_page wrapper with all ten bound arguments;no writes,locks,retries,keys or calculations.

Validate the exact bounded SQL response:matching Property/purpose/source/Invoice/line;positive Invoice version;lowercase64hexrevision;finite aware timestamps and calendar dates;exact nonnegative BIGINT aggregate/count;strict boolean has_more;at most limit positive source rows;canonical unique typed IDs;ORIGINAL_LINE identity matches selected line;strict approved-date/occurrence/kind/UUIDordering. Reject anchor repeats and malformed/inconsistent counts,empty/zero facts or totals. Complete first-page balances must sum exactly;partial pages must not exceed aggregate. Preserve all raw financial facts. Enforce100000UTF8bytes. Changed or unresolved attribution returns a typed conflict;malformed rows/unexpected SQL faults fail unavailable. Preserve P4501notfound,P4506authorization,22023invalid and42501authorization handling.

Add GET /api/v1/properties/{property_id}/financial-due-sources with only purpose,source_id,invoice_id,invoice_line_id,limit,cursor query fields. Require the existing authenticated billing actor and action capability,bound selected Property header,canonical exact query values,duplicate/unknown-field rejection,and reject command Idempotency-Key. Return existing data/page/meta shape and exact next_cursor. Map input400,notfound404,changed/unresolved409,authorization403,unavailable503,unauthenticated401. Keep response/log details redacted. Register one optional injected flow and default read-only service in create_app;add only the new exact URL alternative to existing private/no-store cache classification. Existing routers,commands,recovery,SQL and shared fixtures stay unchanged.

Prepare strict static/collection and focused mocked service/HTTP tests covering finite requests/cursors,sole action grants,denied scopes before connection,exact transaction/query/actor binding,typed response facts/order/bounds/continuation,SQL errors,route input/header scope/status/cache behavior. Reuse unchanged SQL49case evidence;this scope invokes no database fixtures. Run affected existing action-context service/API and health checks because app registration changes. Freeze exact ordered collection before one test execution,stop firstfailure,record all failures/limits and do not retry unchanged checks. Real-service integration and complete financial/integrated tests/reviews remain following required gates;no V1-055 publication or56activation.


## Authorized dated-source real service/HTTP integration — 2026-09-16T14:51:29.210901+00:00

Standing authority admits only test_financial_due_sources_migration.py and its mandatory database-test.sh registration. All application,SQL,source/Payment/Credit helpers and existing fixtures remain unchanged. Use the current actual generated disposable database and genuine owned61to62legacy fixture. Bind runtime URLs to the fixture's actual database using the already verified service_urls helper;never assume the primary test database for legacy tests.

Prepare12cases across6functions,each Payment/Credit:three-page HTTP traversal through create_app's default real read service;stale continuation after a committed debit;capability denial before any runtime connection;disabled actor rejected by fresh runtime read;missing source returns safe404;real61to62unknown-attribution history returns409without invented dates or writes. Happy pages preserve order,source IDs,approved dates,remaining amounts,metadata/private cache and no financial changes. Capability denial uses the direct service boundary so HTTP cannot mask a missing service guard. All other cases exercise the real HTTP boundary and real runtime role.

The test observer delegates every real connection/query unchanged. At the service's existing fresh-actor query,after its transaction settings are established,it records actual database/host/port/runtime role/read-only/repeatable-read/UTC/3second lock/5second statement settings and wrapper visibility. Record actual runtime connection count as well. Expected observations per purpose:3happy,2stale,0denied,1inactive,1missing,1legacy,total16. Require24phase-linked actual migrator fixture/schema observations,16runtime observations and matching connection counts,two owned legacy upgrades/removals,and36passed phases. The zero-connection capability cases must remain zero;no mocked database outcome or altered deadline/lock/assertion.

One fresh feature database gate only,180seconds execution plus30seconds owned cleanup,210total. Bind exact12case collection/order and all product/fixture/helper/observer/launcher hashes before launch. Fixed Python hashseed0for collection/execution. Stop firstfailure/skip/order mismatch/required observation failure/timeout/cleanup failure/permission or safety restriction;no automatic retry. Preserve18consumed financial database runs and every historical recovery/correction limit. This is initial new integration verification,not a lock diagnostic or repeat of the completed49SQL/410PythonAPI gates.

After passing observations/cleanup,register traceability and update the live handoff. Then freeze the finite client read/source-selection contract and staff dated confirmation integration. Full financial/integrated independent reviews and V1-055 closure gates remain mandatory;no publication or56.


## Authorized dated-source client contract — 2026-09-16T15:06:03.060712+00:00

Standing authority admits two new files only:financialDueSources.ts and its test. No existing application,transport,shared financial contracts,SQL,fixtures or assertions change. First establish the finite client request/response boundary;transport registration and staff choices will be separately admitted after this check.

Capture a detached bounded request with operation financialDueSources,purpose allocation or credit_application,source_id,invoice_id,invoice_line_id,optional limit1..100 and canonical revision:kind:UUIDcursor. Normalize request UUIDs consistently with existing clients;strictly reject null/extra/unknown fields. Build only finite query fields. Validate a detached100KB dated-source data response and bounded pagination,canonical IDs bound to captured Property/purpose/source/Invoice/line,version1..9999999999,revision,aware microsecond timestamps,calendar dates,exact bigint balances/counts and positive remaining amounts. Enforce original-line identity,unique sources,strict approved-date/instant/kind/UUID order,nonfuture occurrences,count/aggregate/page/continuation coherence and exact next cursor. Return authoritative facts without financial allocation calculation. Transport remains responsible for metadata and request provenance;this helper alone confers no authorization or posting permission.

Add focused contract cases covering both purposes,detached requests/replies,finite query,initial/continued/zero/100-item pages,microsecond/offset ordering,exact BIGINT values,all binding/cursor/schema/type/date/count/budget failures. Shared helpers unchanged;reuse their previously verified cases. Run changed-file format/lint,full frontend type check,one bounded new-file test invocation(max180seconds,bail1,no parallel files),then production type/build checks. No database execution. Stop on failure/timeout/restriction;preserve evidence and assess bounded corrections against existing families,never automatically retry or reset exhausted allowances. Register new trace IDs and28changed traceability checks only after pass. Full financial/integrated independent review remains mandatory.

After local verification,admit the finite operation into the existing FinancialReferenceClient with actor/Property/request metadata binding,existing bounded private transport and WeakMap receipt provenance. Then add source selection and dated staff preview/confirmation without changing allocation policy,legacy replay,between-Invoice/category ordering or500part limits. No publication or V1-056activation from this component.


## Authorized dated-source reference transport — 2026-09-16T16:58:12.835117+00:00

All owner-approved cursor correction gates passed. Continue under standing lifecycle authority with exactly the existing financialReferenceClient.ts and new financialDueSourcesTransport.test.ts. The123case validator,all existing tests/shared fixtures,backend/SQL,recovery and financial commands remain unchanged. No database run or correction allowance reset.

Register finite financialDueSources GET /api/v1/properties/:property/financial-due-sources,using the verified detached request capture and query helpers. Validate returned data/page with the verified100KB validator within the unchanged1MiBtransport envelope. Preserve common exact actor/Property/request metadata binding,headers,credentials,no-store,redirect refusal,abort/deadline/stream cleanup and safe error behavior. No body,CSRF or idempotency key for this read. Existing branches remain semantically unchanged.

Create a dedicated WeakMap provenance registry accessible only for validated replies from this client. Its frozen receipt binds actor,Property,request,purpose,source,Invoice,line,requested cursor/limit,next cursor and serialized validated data. Copies/forgeries carry no receipt;public reply mutation cannot change the receipt. This provenance supports subsequent staff pagination/selection checks but is not posting authorization. No automatic posting or invented financial facts.

Tests cover both purposes/default and explicit page sizes,finiteURL/privateGETheaders,captured request/scope mutation,large exact amounts,immutable/unforgeable provenance,continued pages and stale409,invalid requests before fetch,metadata/shape/cursor mismatches,non200 responses,oversized or malformed bytes,abort/deadline and cancellation. Run changed-file format/lint60seconds each,full frontend types90,one new transport+affected existing financialReferenceClient.test.ts invocation180seconds,bail1/no file parallelism,then production types/build90each. Reuse unchanged123validator cases instead of rerunning them. Stop on firstfailure,missing required count/status,timeout or restriction;no automatic retry or further correction is authorized by the completed cursor exception. Preserve every failure before any decision.

On pass,register traceability and update live handoff/samefollowup;then admit paginated source selection and dated Payment/Credit staff confirmation. Full financial stage and integrated independent reviews plus all version gates remain mandatory. No publication or V1-056activation from this component.


## Dated-source sequence scope — 2026-09-16T18:55:47.705075+00:00

Implement only a new FinancialDueSourcesSequence and focused tests. Existing transport, validator, application financial calculations, fixtures and database behavior remain unchanged. BR-PAY-036, PR-PAY-036, UI-066 and TEST-112 require current dated facts, preserved customer designations and explicit staff confirmation. This sequence provides bounded complete read facts only; it never allocates or authorizes posting.

Accept only genuine immutable transport provenance for the captured actor, Property, purpose, source, Invoice, line and limit. Reject copied or mutated replies, skipped/repeated cursors and reused request identifiers. Revalidate pages with the existing validator. Compare stable snapshot fields while allowing statement as_of to advance. Verify global strict approved-date/instant/kind/UUID order and source uniqueness across pages, exact final count and aggregate. Expose detached data only when complete; permanently clear and fail closed after a rejected append. Cap accumulated facts at the existing 8MiB context-read budget and 32767 source rows, with no silent truncation. No allocation calculation or command key.

Use actual reference-client responses in tests; do not fabricate provenance. Cover Payment and Credit, empty/full/multiple pages, advancing clock and equivalent offset timestamps, exact BIGINT, frozen captured inputs, detached output, metadata/cursor/stable-fact mismatch, cross-page duplicate/order violations, missing final rows or money, changed public replies, terminal failure, count bound and no incomplete-data exposure. Reuse unchanged425transport and123validator cases. New focused sequence tests only, static format/lint60seconds each, fullfrontend types90, tests180, production types/build90each. Preserve first failed result before applying any separately authorized routine correction; no unchanged retries, new fixture/database diagnostics or relaxation. Routine corrections remain at most2materiallydifferent per distinct cause, all earlier consumed allowances unchanged.

After local pass register traceability and handoff. Sequence acceptance remains provisional until independent fullfinancial/stage/integrated review. Continue source-selection UI and explicit dated Payment/Credit confirmation afterward, then remaining55gates. Full55closure only; no56.


## Dated-source loader — 2026-09-16T19:03:27.764065+00:00

Add only the two new loader/source tests. Use the verified FinancialDueSourcesSequence and existing FinancialReferenceClient to assemble genuine complete snapshots for the upcoming staff source selector. Capture actor/Property/signal and request before the first asynchronous read. Check abort before and after each response; no partial exposure. Limit to1000pages matching existing context loaders and throw the existing RESPONSE_TOO_LARGE error on exhaustion. No network retry,command,CSRF/key change,allocation calculation or silent truncation. All financial/fixture/database code unchanged.

Twelve focused cases using genuine transport replies cover Payment/Credit,empty data,before/after-read abort,current actor mismatch,stale409/unavailability,forged receipts,captured input/scope mutation,and1000page bound. New tests only;reuse48sequence/425transport/123validator cases. Format/lint60seconds each,types90,tests180,productiontypes/build90each. No DB run. Preserve any failure and use only remaining separate routine allowances when applicable. All earlier consumed limits remain.

Then admit staff selection and exact dated preview/confirmation. Fullfinancial/stage/integrated reviews and final55acceptance remain mandatory. Pause after full55closure;do not56.


## Dated confirmation evidence — 2026-09-16T19:09:21.803379+00:00

Before source-picker/workspace integration, extend only the existing IntentLines evidence renderer to display returned due_attribution parts for both Payment and Credit, proposed or explicitly designated, including historical proposals. Preserve existing line summaries and legacy rendering when no due attribution exists. Show the server-returned basis, original-line/debit source reference, approved due date, exact source timestamp, outstanding at preview/proposal and selected USD. Do not recompute allocations, infer missing dates, rewrite inputs, truncate500part evidence or authorize/post anything. UI-066,BR-PAY-020/036 and the existing dated-source contract require explicit staff confirmation of these facts.

Add14focused rendering cases across Payment/Credit and both bases,live/recorded proposals,legacy absence,exact BIGINT/timestamps,unavailable malformed evidence and full500part display. Run new cases plus the three affected existing FinancialManagement/FinancialWorkspaces/FinancialConfirmation suites because the shared confirmation renderer changes. Keep all existing tests and shared fixtures unchanged. Staticformat/lint60each,types90,tests180,bail1/no fileparallelism,productiontypes/build90each. No DB run. Reuse unrelated source/transport/sequence/loader evidence. Routine correction policy applies without resetting any earlier allowance.

This is a provisional display component; source selection,preview-before-confirmation integration and fullfinancial/stage/integrated independent acceptance remain required before publication. Continue55only,thenpause;no56.


## Dated-source picker scope — 2026-09-16T19:20:56.351620+00:00

# V1-055 dated-source selection design

Current verified milestone: dated-source validator/transport/sequence/loader and exact confirmation rendering. Active financial stage remains uncommitted over cdf1492; source/evidence/Git66pathscope and same follow-up ACTIVE verified by v1055-invoice-due-evidence-cleanup1-handoff-verification.json. All historical and new correction limits remain. No database run is needed for this frontend integration.

Next bounded implementation: one reusable source-picker component and pure explicit-selection adapter, with their focused tests, followed by wiring the existing Payment Allocation and Customer Credit workspaces. Keep shared database/browser fixtures unchanged. Register new parameterized TSX suites in the existing financial traceability inventory as well as the manifest; UI test level is `UI component`. All new component suites require explicit local testing-library cleanup with imported Vitest hooks.

The picker receives captured actor/Property/signal, purpose, source, Invoice and line identifiers plus the existing reference client. It uses loadFinancialDueSources, which has complete genuine-receipt validation,8MiB/32767source sequence budget and1000page ceiling. Only one picker is active in a workspace, preventing simultaneous retained source lists. Load the complete facts before enabling selection. Display source identity/kind,approved due date,exact source timestamp and remaining USD;paginate display50rows without truncating the complete read.

Keep a local amount text draft keyed by source kind and canonical ID. On apply, validate explicit positive amounts against currently loaded source rows,exact integer-cent parsing,positive total and500part bound. Return three-field source_parts (kind,ID,selected cents) and their sum;do not calculate earliest-due allocation or invent dates. Blank/zero input selects nothing. Reject missing,duplicate,stale or excessive selected sources. A clear-selections action is explicit. Source facts are input validation only;the server preview remains authoritative.

Store loaded facts with captured actor/Property/signal/request identity and expose them only while that identity remains current. Check cancellation through useFinancialTask and the verified loader. Use a stable component key for source/Invoice/line/actor/Property/revision. Retain unapplied edits locally. Opening the picker blocks the parent review until explicit Apply or Discard;editing also invalidates any prepared command. Do not silently fall back from an explicit source designation to earliest-due allocation.

Parent workspaces keep applied source_parts by Invoice line,within the existing lineAmounts draft lifecycle. Applying sets the line's total to the exact sum and marks the line draft dirty. Make the line-total field read-only while explicit source parts are selected. Offer an explicit return-to-earliest-due action for that line. Changing source/target/mode follows existing discard confirmation and clears both line amounts and source choices. Include source choices in capture/invalidation/recorded-draft handling. Preserve edits made after a request is captured.

On review,load fresh existing financial action context,validate selected line totals and attach source_parts only for explicitly selected lines. Enforce500selected parts across all lines. For Payment/Credit DESIGNATED Invoice intent,call allocationPreview/creditPreview through the existing validated transport before building the command. Use reply.data.intent unchanged for the separate explicit command confirmation. The transport validates source/Property/actor/request and exact selected amounts/parts;server version/current facts are authoritative. The new FinancialEvidence renderer already shows returned dated facts. Keep PROPOSAL,DIRECT_CHARGE,legacy replay and reversal behavior unchanged.

Verify picker/helper behavior,scope changes,abort/stale/error handling,complete paging,explicit apply/discard,500part bounds,no mutation of supplied selections,no implicit posting,and unchanged proposal/Charge/replay flows. Then run affected workspace/confirmation tests with necessary new synthetic preview responses locally;do not modify accepted historical fixtures. Preserve every failure;routine corrections are max2materiallydifferent per distinct cause,with all earlier consumed limits retained. Full financial stage and final integrated exact-SHA independent reviews remain mandatory.

Authority ends at full V1-055 closure for this continuation. Do not activateV1-056. No new owner decision is pending.


## Current bounded slice

Only the four new picker/selection source and test files are admitted now. Parent workspace integration is a subsequent bounded slice. No existing application/test/shared-fixture edits. Finalize the exact named new case inventory before the first test invocation. Changed-file format/lint60seconds each,frontendtypes90,newtests180,bail1/no fileparallelism,productiontypes/build90each. No database run. Standard traceability/docs/handoff updates follow verified checks; preserve all earlier evidence.


## Workspace integration scope — 2026-09-16T19:53:41.284638+00:00

# V1-055 designated Invoice workspace integration

The Payment/Credit workspaces currently reload complete action context and confirm designated line amounts directly. The verified source picker and preview transport are not yet connected. This slice connects them without changing posting, allocation policy, locks, databases, shared fixtures, replay or recovery.

1. Admit the two workspace files, a pure shared selection adapter with its unit tests, and the existing workspace test file. Preserve exact prior hashes, all consumed limits and prior evidence outside the candidate. Existing whole-version acceptance remains pending.
2. Validate selected source totals and the 500-part global bound without calculating allocation order. Detach explicit parts, reject orphan or inconsistent source choices, and attach source_parts only to explicitly selected Invoice lines.
3. Keep one source editor per workspace. Block parent context/review while it is open. Apply sets exact line total and makes that total read-only; explicit return to earliest due removes source choices while retaining the total. Source/target/mode changes and Receipt handoffs follow existing discard confirmation and reset both choices and amounts. Preserve later edits through the existing draft controller. Scope parents already remount by actor/Property generation; picker keys also bind actor/Property/source/Invoice/line/revision.
4. On designated Invoice review, reload and validate fresh context, then call the validated allocationPreview/creditPreview read and pass its returned intent unchanged to separate staff confirmation. Keep proposals, Charge targets, legacy replay and reversals unchanged.
5. Extend only the local workspace test adapter with clearly synthetic dated source and preview responses. Do not alter historical/shared fixtures. Preserve existing assertions, adding the required preview request to the three affected request-count assertions. Test both parents for apply/discard, explicit earliest-due return, blocked review, dirty/discard behavior, invalid/stale/error preview and no implicit posting; test helper consistency and global bounds.

Before execution, freeze exact case names/counts. Changed-file format/lint each60seconds; frontend types90; focused helper plus affected workspace/confirmation suites240, bail1 and no file parallelism; production types/build90each. No database invocation. Reuse unchanged picker, transport, validator and prior acceptance evidence. Register traceability and update docs/handoff after verification. All failures remain preserved; routine causes allow at most two materially different corrections, with prior allowances unchanged. Required full financial and final integrated independent exact-SHA reviews remain mandatory.

Existing sole coordinator/follow-up remain; no new worker. Publish only after all V1-055 gates pass; then pause the same follow-up. Do not activate V1-056.


## Proved Invoice-wide overdue projection — 2026-09-16T20:42:24.954239+00:00

# V1-055 proved Invoice-wide overdue projection

Standing lifecycle authority covers this fresh financial feature slice. The latest200-case workspace evidence is unchanged. The protected Refund setup decision remains pending and its file/imported helper must not change. No historical diagnostic or fixture allowance is reset.

Admit only the existing unpublished migration62,new backend/tests/test_invoice_due_overdue_migration.py,and mandatory scripts/database-test.sh registration,plus existing records. Add a private STABLE invoker helper invoice_due_overdue_position_at(uuid,timestamptz),called once per Invoice line through MATERIALIZED position rows. Preserve every existing function body and privilege except adding this new helper and its upgrade invocation/revoke. It performs no writes,locks,retries,posting,policy decisions or grants.

Validate a nonnil Invoice identity and finite aware SQL timestamp. Missing/unissued/not-yet-issued Invoice returns NULL. Return Invoice id,original due date,as-of,Asia/Phnom_Penh business date,line count,exact aggregate remaining balance,attribution completeness and unknown-line count. If every line is proved,return the dated source count and exact sum of positive remaining source amounts whose approved due date is strictly before the business date,plus the complementary not-yet-overdue balance. Enforce nonnegative signed-bigint bounds and exact conservation. If any line attribution is unresolved,overdue/not-overdue/source-count values are NULL;never turn unknown into zero. Consumers retain their separate Invoice/Lease/status eligibility and one-final-decision rules. Do not calculate or round a fee in this helper.

Prepare19cases/sixfunctions in declaration order:seven Khmer-midnight/Due-Date boundaries;two Payment/Credit applications explicitly reducing a future-due source without reducing the already-overdue amount;five invalid/nil/nonfinite arguments;two missing/not-yet-issued cases;two owned61-to62legacy unknown-date cases with unchanged histories;one private-function/role/no-write contract. Reuse existing due_connection,legacy_due_connection,funds,adjustment,preview/post and upgrade helpers without edits. All setup is synthetic and disposable.

Before execution require affected Ruff format/lint,mypy,exact19case collection,registered mandatory suite,and all product/helper/fixture hashes. One fresh feature invocation only:180seconds execution,30seconds owned cleanup,210seconds total. Require exact ordered19cases,38phase-specific actual generated database/schema/function observations,two legacy upgrades/removals,57passed phases with no skips,and verified owned container/network/volume/generated-secret cleanup. Stop at any test/required-observation/timeout/cleanup/permission failure;no automatic retry. Routine correction authority applies only within its actual scope;no protected/shared fixture changes or historical recovery reruns.

A passing helper is not financial-stage acceptance. Next connect late-payment review,finalizer,deferred guard and their typed contracts,then source-specific Rent cases/alerts/scheduled reads per the frozen storage design. Complete all affected/final gates and independent fullfinancial/integrated reviews. No publication or V1-056 activation.


## Connected dated late-payment assessment — 2026-09-16T21:02:43.112117+00:00

# V1-055 connected late-payment assessment

Authority: existing V1-055 lifecycle; BR-INV-049/051/052/053 and frozen due-attribution storage design, Connected readers. This is fresh authorized implementation, not historical lock diagnosis or a fixture correction.

Admit only the active unpublished migration62, one new integration module test_invoice_due_late_assessment_migration.py, mandatory database suite registration and already-admitted records. Preserve every existing function AST except upgrade, every earlier migration, all shared/protected fixtures and every prior evidence file.

Replace exactly matched calculation fragments in the installed review, finalizer and deferred decision guard. Each projects proved overdue source amounts at its assessment instant. Preserve original Invoice due date eligibility, Lease/status checks, one final decision/waiver, Invoice-wide10% half-up rounding, replay, actor/capability checks, locks, chronology checks, assertion strength and all history. Unknown attribution blocks a new decision and returns null review amounts with DUE_ATTRIBUTION_UNRESOLVED;never fabricate zero. Add the projection to new review/calculation evidence without rewriting old decisions or receipts. No grants or permissions change.

The client/UI must subsequently support explicitly unavailable amounts and dated evidence before the stage can be accepted. Do not claim that contract integrated in this SQL slice. Source-specific Rent consumers and complete financial/integrated gates remain required.

Focused new database coverage:18 cases/10 test functions in declaration/parameter order. Six mixed-date outcomes/rounding cases;original Invoice eligibility;future-only balance;legacy unknown refusal;two preserved legacy decision/replay cases;wrong aggregate-derived amount refusal;direct deferred guard refusal;two finality/replay cases after another debit;runtime read-only review;two Payment/Credit future-source designations. Exact collection precedes execution. Require36 actual generated database/schema/function entry/exit observations,three real61to62 legacy upgrades/removals,54 passing phases,one runtime-role/read-only observation and verified owned cleanup.

One fresh feature gate:180 seconds execution,30 seconds owned cleanup,210 seconds total,no automatic retry. Stop on failed test,missing observation,timeout,cleanup failure or restriction;preserve exact evidence. Routine correction authority applies only to its expressly allowed causes;no additional application/fixture/historical diagnostic allowance is inferred. Reuse the19 unchanged private-projection cases and prior checks;mandatory final acceptance remains separate.
