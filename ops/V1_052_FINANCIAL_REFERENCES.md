# V1-052 financial references and provisional KHR preview

Bounded stage from accepted8a7fc60. Four narrow reference routes and a separate
exact client support the existing financial commands. No staff UI integration,
new grant, dependency, migration, provider, stored quote policy or canonical change.

## Routes and authority

- GET /api/v1/financial-workspaces returns only existing Property scopes explicitly
  granted one of the16 existing financial capabilities, with property_id, name,
  fixed Asia/Phnom_Penh timezone and17boolean capability flags including the separate
  exchange_rates.manage visibility flag. It infers no role/global/object-only grant.
  Unrelated-only or empty grants return an empty list. Requested Property headers
  are rejected here; this is actor-bound discovery before Property selection.
- GET /api/v1/properties/{property_id}/financial-capabilities returns property_id
  and the same exact capability projection. Authenticated/fresh HUMAN reads may
  receive allfalse financial flags; this projection never authorizes a command.
- GET /api/v1/properties/{property_id}/payment-methods requires payments.record
  in that Property; no configuration-manager or unrelated read grant is required.
  Accepted methods return stable id,property_id,code,display_name. The canonical
  singleton Property owns these configured methods; retired methods are excluded.
- POST /api/v1/properties/{property_id}/payments/khr-preview accepts only exact
  positive usd_amount_cents<=9000000000000000 and optional ManualReferenceInput.
  Requires payments.record, Origin/CSRF and additionally exchange_rates.manage
  before any manual source dispatch. Idempotency-Key is rejected: this calculation
  creates no Payment, Receipt, FX, idempotency, guard or encrypted-intent record.

Workspace/method lists use ascending UUID pages, limit1..100/default50; the optional
canonical lowercase UUID cursor is the last returned identity. SQL applies limit+1
before row materialization. No unbounded Property configuration/method collection
is loaded. Metadata includes the resolved actor on every success and resolved
Property on scoped successes. Duplicate/unknown queries and duplicate/mismatched
actor/Property headers fail before lookup. Responses/errors are private,no-store,
Vary Cookie with safe local request correlation; no upstream body/SQL echo.

## Exact provisional KHR result

Reuse select_khr_reference extracted from accepted confirmation; its _selection
method delegates without changing confirmation/replay semantics. Only the existing
approved injected provider is used; default provider remains unavailable. Explicit
ExchangeRateSourceUnavailable without manual input returns200 with status
source_unavailable, provisionaltrue, echoed Property/USD and a boolean
manual_fallback_allowed requiring both existing grants. Generic/malformed provider
failures return503; they never advertise authorized manual fallback. Manual input
is allowed only when that approved automatic source actually reports unavailable.

Available result returns statusavailable, provisionaltrue, Property/USD, original
source/reference/timestamp/fallback evidence, fixed50basis-point markup, integer
system_rate_khr_per_usd, exact decimal-string unrounded_khr_amount and integer
payable_khr_amount. Compute using integer millionths: ceil(reference*1005/1000)
for the whole-KHR system rate, then ceil(USDcents*systemRate/100) for final payable.
Check timestamp against server time after source selection; future sources and
payable outside1..9000000000000000 fail closed. No ambient Decimal rounding.
Actual confirmation selects/preserves the authoritative rate and channel facts;
preview neither persists an earlier quote nor overwrites channel settlement evidence.

## Read isolation and client safety

Runtime-role SELECT only, REPEATABLE READ READ ONLY,3sconnection/lock and5sstatement
limits. Fresh active HUMAN account and existing Property checked before references
or provider access. No financial database credentials/connection are required.
Existing SELECT privileges suffice; no migrations or grant expansion.

The separate financialReferenceClient captures actor/Property/form before awaits;
finite four-operation paths, no-store/credentialed/redirect-denied transport, exact
JSON,32768byte request and1MiB response limits, fatalUTF8 streaming, one20sdeadline,
abort/late-context handling, safe errors/correlation and strict reply/pagination/
capability/FX-consequence validation. Request cursors normalize in captured data
before both transmission and ordering comparison. Every preview amount is echoed
and checked. Returned provisional values alone are displayed by future UI. This
client never reserves, clears or dispatches any of the12financial commands.

Legacy labels have no universal short database text bound. Preserve whole labels;
the defensive response ceiling can honestly make oversized historical data
unavailable, never truncate financial/reference identities or claim all labels fit.

## Verification and preserved evidence

Focused backend/API/KHR/inventory183PASS; full isolated PostgreSQL933PASS after one
fixture correction. Initial932PASS1FAIL exposed new pagination methods influencing
an existing cash-method fixture. Correction1 retires only105new synthetic methods
in finally and verifies baseline accepted IDs restored; no prior assertion/helper
or runtime alteration, no deletion. Original failure and source are retained.
Client42cases and3actualChromium groups cover all4routes, exact streams, abort and
existing encrypted pending preservation. Cursor TEST-FE-347 produced2FAIL1PASS
before one-line normalization;39unrelatedcases intentionally unselected in that
red run. New37trace mappings preserve all1549prior objects for1586total.
Initial formatting/type diagnostics and their corrections remain retained.
Containing-candidate full exact gates and fresh complete8a-base Astra/max/Standard/
enforced-read-only review with zero HIGH/MEDIUM/LOW remain required before acceptance.

Standing review authorization through53 is external
property-rental-standing-independent-review-authorization.json,
SHA256d509c66234abf96872d9c7d9682adc2a1ed315c97772b5793dbbe9426dd6eeff.
It applies to every successor/integration/release/closure review and approved handoff;
no hash-only approval. Exclude credentials,secrets,customer/production data; respect
automatic enforcement. Preserve rejected5578/989/b7/reports/all regressions. Separate
Workboard private-note hold is unresolved and is not retried. After acceptance,
complete staff UI/full52release/CI/refs/same-card/durable closure before53;
fully closed53pausesSAME native, OpenClawdisabled, no54.


Correction1 after rejected456910f: preserve backend-valid whole legacy labels, internal tabs/newlines and Unicode evidence measured in code points, while matching existing evidence normalization and UTF-8/NUL rules. Keep byte ceilings. Preview validates automatic source before manual conflict; only explicit approved source outage allows fallback, without changing confirmation/replay. Both affected transports own/cancel late response bodies and bodies rejected before reader acquisition; cleanup must not block settlement or alter financial recovery. All three findings and identical inherited cleanup receive red/green tests and fresh complete8a-base review.
