# V1-052 bounded financial action context

Status: ACTIVE after independent acceptance of c65a7cb240ca3e0e67b6802e1ea25b668ae82e3a.
Accepted base receipt: v1052-payment-reversal-context-accepted-c65a7cb.json SHA256
8257d9b2430d1b41de5f3b6094f63b58f06d3d9a613cec6aa7077658a3330a3c.
Complete431-base review29668 covers29paths/two commits with0HIGH0MEDIUM0LOW;
report SHA256c87c3d0a12785a012f0d66d3940927e529fe2f95ea6b3a632f8ce2296891d8cc.
All exact gates passed and all rejected candidates/reports/regressions remain preserved.
This bounded stage implements necessary reads within frozen V1-052 scope.

Standing review authorization remains outside frozen source at
property-rental-standing-independent-review-authorization.json SHA256
 d509c66234abf96872d9c7d9682adc2a1ed315c97772b5793dbbe9426dd6eeff.
Every successor review through53 uses Astra/max/Standard/enforced-read-only and
excludes secrets, credentials, customer and production data. The separate Workboard
private-note hold remains unresolved; no submission retry is part of this stage.

## Purpose and verified source gaps

SEC022 requires action authority independent of general read authority. UI067/070/
072/106 and frozen52 scope require selected original source and current consequences
before explicit posting, reversal, reprint or verified-return confirmation. Existing
Payment reversal context handles its complete dependency graph separately. General
history/list endpoints retain their current read grants.

Nine finite purpose contexts cover the remaining source gaps:

1. Allocation posting: selected Payment original amount/FX/availability, with optional
   explicitly selected Invoice or separate Charge target and bounded original line facts.
   Capability payments.allocate; do not replace the accepted FIFO proposal.
2. Allocation reversal: exact selected Allocation original header/details/reversal,
   original/current Payment and current linked target. Capability payments.allocations.reverse.
3. Receipt reprint: exact selected immutable Receipt and joined Payment/current context;
   no complete reprint history through the action grant. Capability receipts.reprint.
4. Credit recognition: selected Payment original FX/current available USD and current
   applicable-obligation indicator. Capability credits.recognize; payer authorization
   is still explicit and write-time eligibility authoritative.
5. Credit reversal: selected recognition/source/current Credit financial position and
   its recognition-reversal event. Capability credits.reverse; current applied/refunded
   amounts explain unresolved dependencies without implying automatic child reversals.
6. Credit application: selected Credit/source/current available USD with optional known
   eligible Invoice or separate Charge target. Capability credits.apply; keep accepted
   within-Invoice proposal and manual designation contracts unchanged.
7. Credit application reversal: exact selected application/header/bounded details,
   reversal/source Credit/current target. Capability credits.applications.reverse.
8. Refund verified return: exact selected original Refund/net USD/source facts.
   Capability refunds.correct; no collection right or invented Refund status.
9. Refund correction reversal: exact selected VALUE_CORRECTION bound to its original
   Refund, linked reversal if present, original/net USD/source facts.
   Capability refunds.corrections.reverse; a correction for another Refund fails closed.

Explicit bounded routes, all below `/api/v1/properties/{property_id}`:
`/payments/{payment_id}/allocation-context`,
`/payment-allocations/{allocation_id}/reversal-context`,
`/receipts/{receipt_id}/reprint-context`,
`/payments/{payment_id}/credit-recognition-context`,
`/customer-credits/{credit_id}/reversal-context`,
`/customer-credits/{credit_id}/application-context`,
`/credit-applications/{application_id}/reversal-context`,
`/refunds/{refund_id}/verified-return-context`, and
`/refunds/{refund_id}/corrections/{correction_id}/reversal-context`.
Only posting/application modes accept paired optional target_kind/target_id. The
selected correction route binds both Refund and correction in request provenance.
Reversal modes derive their immutable original target instead of accepting a replacement.
This is a finite selected-resource projection, not an arbitrary data-query endpoint.

Payment confirmation can use optional authorized Customer selection or a known record
reference from its workflow; never imply customers.read from payments.record. Existing
Refund source previews already cover supported Refund creation with proper source
history and USD-only restrictions. Final Settlement remains excluded.

## Transaction and projection constraints

Use explicit selected Property paths and finite action/source identifiers. Before
projection require the exact existing Property action capability, validate actor and
source identifiers and recheck a fresh active HUMAN in the same REPEATABLE READ READ
ONLY snapshot. Keep3second connect/lock and5second statement limits/UTC, safe errors,
actor/Property/request binding, private/no-store and no Idempotency-Key/CSRF/write.

Existing receipt_resource/credit_resource/credit_application_resource execute FOR
SHARE (migrations40/41). Do not call them from the new READ ONLY transaction or weaken
that setting. Existing credit_read_summary is STABLE and already supplies original
Credit/position/FX, but is definer-private; a narrow new projection can invoke it after
fresh exact source scope. Existing refund_resource reads a coherent bounded page
without row locks; no unbounded history gathering or first-page filtering may substitute
for exact selected correction context.

New forward-only migration47 adds only necessary STABLE security-definer selected
projections with fixed pg_catalog search_path/UTC, strict finite arguments, exact
Property/source verification, PUBLIC/bootstrap/financial revokes and runtime execute
only. Reuse safe accepted arithmetic helpers and facts; no original migration/table/
trigger/serialization/command change. Source reads never call serialize/lock/assert
write helpers. Default read resource budgets below1MiB leave envelope headroom.

Verified schema decision: paginate selected Allocation and Credit-application details,
and selected Invoice target lines. Migration39 permits positive smallint Allocation
detail sequences without a 500-row constraint and places no byte bound on each
calculation trace. Migration41 constrains Credit-application sequences to 1..500 but
allows 200,000 bytes per detail, so its aggregate can exceed the response budget.
Command input bounds cannot establish a bound on all retained financial-writer rows.
Use limit+1 keysets and a response byte budget; never materialize an entire detail
collection to decide whether it fits. An individual oversized selected fact must fail
unavailable explicitly, without truncation or a false complete-sequence claim. These
findings match DB-PAY detail rules and DB-CREDIT-005; no original schema change is needed.

Current target projection uses authoritative Invoice DRAFT/VOID zero/current statuses
and separate Charge adjusted/remaining arithmetic. Invoice/Charge identity and source
Customer/Property/Lease/designation checks happen before exposing target facts. Normal
Payment targets belong to the payer; third-party Payment follows confirmed Lease/
Invoice/Charge designation and never makes the payer the responsible Customer. Credit
application stays within the Credit Customer and Property. Charge value never changes
the source Invoice. Accepted final commands remain authoritative for chronology and
current availability under concurrency.

Credit recognition cannot call assert_payment_excess_eligible in a read-only snapshot:
that helper explicitly requires READ COMMITTED and SHARE NOWAIT table locks. If the UI
needs an obligation indicator, project the same applicable Invoice/Charge existence
facts in the read snapshot without acquiring write guards and label it as current
context; do not make a read token a grant or waive transactional revalidation. Include
Credit applications in current balances through accepted primitives. Do not claim
positive unallocated amount alone is eligible true excess.

## Client and interface contract

Dedicated finite requests and typed domain replies reuse the accepted bounded exact
financial transport ownership/deadline/actor invalidation rules. Read-only source
requests never reserve, retire or replace financial intent. Capture every input before
awaiting; use immutable request-owned evidence if continuation is introduced. No raw
JSON form or generic recursive result renderer. Staff forms later show actual source,
amount/current consequence, required reason/evidence, explicit confirmation and safe
unknown-outcome recovery with original key/bytes.

## Required proof before acceptance

- Each purpose with its sole action grant succeeds; all unrelated/global/object-only/
  absent/wrongProperty grants fail before projection; disabled/service actors and
  missing/crossProperty/source-target mismatches fail closed.
- Original KHR/FX, Credit USD and Refund USD identities/amounts are preserved exactly;
  current balances agree with accepted resources/positions, including reversals,
  partial/full verified returns, correction reversals and VOID targets.
- Receipt identity stays stable; no reprint event during a context read. Selected
  correction cannot be substituted from another Refund or hidden beyond a first page.
- Real PostgreSQL privileges and read-only/no-app-table/guard/audit-write proof; coherent
  snapshot under concurrent mutation; bounded arguments/bytes/detail cardinality and
  actual timeout behavior; no broad list/Customer contact data exposure.
- Client exact integers, finite strict schemas, input capture, body cancellation,
  actor/Property invalidation and preservation of existing encrypted intent; actual
  Chromium synthetic coverage with all financial network calls blocked.
- Preserve all accepted/rejected candidates, reports and regression traces; register
  assertion-level trace mappings. Full exact gates and one fresh complete-base Astra
  max Standard read-only zero review. No hash-only human approval request.

After bounded acceptance, implement staff workflows in the existing authorized shell,
then full52 cumulative release review/publication/exactCI/ref equality/SAME-card/durable
closure. Only fully closed52 permits53; fully closed53 pauses SAME native follow-up,
keeps OpenClaw disabled and never activates54.


Pagination revision contract:
original detail rows use stable sequence/UUID keysets with limit+1. Any repeated current
source/target context must stay bound to an opaque revision across pages. Source Payment
availability includes Deposit receipts whose reversal may advance only a Deposit guard;
root Payment revision alone is insufficient. Reuse the same proven read-only vector as
Payment reversal context: root status/guard and all historical associated Deposit guard
count/sum, plus selected Invoice/Charge target financial guard. Include exact Property,
action, source, optional target and view in the hash. Never call serialize functions.
New clients must consume their own immutable captured request provenance, as corrected
in c65, and never let an optional caller cursor establish a complete sequence.

## Implemented draft and verification

Nine read-only contexts, forward-only47, action-authorized service/API and exact client are implemented. The client owns actual request provenance in a private WeakMap; the sequence owns runtime-private frozen actor/Property/source/purpose/target/Refund scope. Only actual ordered initial/continuation replies with matching immutable source/current facts and complete detail totals establish completeness; copies, mutations and scope bridges fail. Returned snapshots are detached, and no read creates or retires an encrypted command. Invoice debit increases retain original and adjusted values separately. Payment position and Credit source snapshots must agree.

Focused checks:215backend/API/inventory,225client,28isolatedPG then5additional boundary cases(33covered),25trace,12actualChromium groups, backend6type checks and frontend project types/lint/format passed.28captured synthetic database examples exercise all nine purposes, original/reversed events, Charge/VOID targets and Payment/Credit/Deposit Refunds. Byte-budget proof uses an actual oversized UTF-8 Invoice line and runtime READ ONLY SQL54000, mapped unavailable without writes. Direct malformed SQL and historical unsupported Deposit application probes pass. Real-browser IndexedDB/WebCrypto tests preserve the pending key/bytes and exact9007199254740993 target values.56additive mappings preserve1644accepted mappings=1700.

Retain all failed draft attempts: initial private-header/empty-kind defects, debit ceiling and source-coherence reds, lint/type diagnostics, test-loader path collision, test-runner registration quoting and browser marker mismatch. Corrections preserve existing financial write guards, canonical specifications, dependencies and historical trace mappings. One existing Starlette/httpx deprecation warning is retained. Full exact candidate checks and fresh completec65-base Astra/max/Standard/enforced-read-only zero review are still required; this is not V1-052 closure.

Exact candidate dc24920 failed only the initial backend formatting gate: four new route inventory mappings required formatter line wrapping. Backend later steps did not run. Its completed986PostgreSQL/832frontend/189automation/migration results remain preserved. PostgreSQL reported the Starlette/httpx deprecation and a Pydantic cursor-alias warning in an existing competing-credit-refunds test; cause is not established. Correction1 formats the inventory and proves the entire Python AST unchanged; no runtime, schema or frontend behavior changed. Preserve dc24920 as the parent of a normal successor; require fresh successor exact gates and completec65-base independent review.

Candidate99d0b55 preserved: formatting passed187files, then lint found one106character Refund-correction route key. Correction2 uses adjacent string literals with identical fullPythonAST; preview uses the actual repository filename/cwd and passes format/lint without ignores. All backend checks must pass before the next commit. Its986PostgreSQL/189automation/migration gates passed; first frontend attempt timed out in unchanged existingTEST-FE079 with831otherPASS. Isolated same-source probe and full frontend recovery passed; cause is not established, and no assertion/timeout/source was changed. Full checks are scheduled to avoid competing frontend/database/automation runs. Both failed candidates and all raw results are retained; no independent review was submitted for either.

Correction2 full prefreeze backend verification passes:2547tests,963explicit database-only skips,187formatted/linted/typed files,build/import. The route inventory module AST is identical to99d0b55. Preserve both failed gate candidates and original timeout evidence; frontend isolated recovery passed832tests with unchanged assertions/timeouts/source. The next immutable successor still requires its applicable full exact gates and one completec65-base independent review.

## Independent review correction1 after 06aa8ed

The complete31-path, three-commit candidate06aa8ed was independently REJECTED with
zero HIGH, four MEDIUM and zero LOW findings. Report SHA256
9e092a38c4f4b8cd02b720c4fe9371a1c9fddae65ca4e3f6bc5023adc1c8c3a7;
rejection receipt SHA256
05aafab9a4024d72ab7c44e41d56e797d403b9b01690454d1d9e1ab450add787.
The candidate, report, all prior exact/focused failures and every regression remain
preserved. This is correction1 for each new FAC-06-M1–M4 finding, independent of
the two completed route-inventory formatting corrections. No finding is waived.

- FAC-06-M1-SOURCE-FACTS: validate finite original Payment, position, Receipt link,
  Credit recognition/position and FX schemas before client provenance registration.
  Match original currency/FX record identities and repeated rate/channel fields;
  enforce existing USD/no-FX and KHR/required-FX semantics. Credit reversal is whole
  recognition or zero, must agree with an included reversal, and active recognized
  value must fit the source Payment's recognized-Credit disposition. Validate
  source receipt and immutable reversal references consistently. Preserve actual
  channel-value precedence, exact rates and accepted original legacy shapes.
- FAC-06-M2-INVOICE-COMPLETENESS: add a revision-bound total item_count for every
  context and authoritative Invoice line_count, original_total_usd_cents and
  adjusted_total_usd_cents. Derive these from the exact selected source/target in
  the same read-only snapshot. The complete client sequence must match cardinality
  and original/adjusted/current totals, including paid, adjusted-to-zero, DRAFT
  and VOID lines. Original/adjusted totals follow existing bigint schema limits;
  adjusted may exceed original because legitimate DEBIT adjustments are supported.
- FAC-06-M3-DRAFT-REVISION: include selected Invoice version plus scoped draft
  revision-event count and maximum identity in read-only revision evidence.
  Existing draft writes record append-only history and advance header version;
  new line insertions also affect cardinality. Cover changes outside the requested
  page and reverted facts without hashing unbounded history payloads. Keep all
  existing write policies/triggers and migrations through46 unchanged. Prove real
  PostgreSQL stale-page409 after a permitted draft correction, not only a mock.
- FAC-06-M4-SEQUENCE-BUDGET: allow at most8MiB of accumulated exact UTF8 context
  snapshot and item serialization, including structural overhead. This is an
  explicit availability ceiling, not a claim that all historic evidence fits.
  Check prospective bytes before retaining new items; on any failure clear retained
  buffers, poison completeness and return no data. Detached completed-data copies
  remain bounded by the same limit. Never truncate evidence or raise wire limits.

Use the existing unpublished migration47 and bounded service/client modules only.
All nine action grants, request routes, keyset-before-payload ordering, existing
per-response ceilings, financial commands and encrypted recovery remain intact.
Update synthetic fixtures to actual corrected database projections and add unit,
API, real PostgreSQL, actual-client and Chromium regressions for all four findings.
Preserve red results before correcting runtime code and register assertion-level
trace entries without replacing any of the1700 prior mappings.

Freeze a normal successor of06aa8ed. Run all applicable exact gates, scheduling
the frontend suite without competing full suites, and one fresh completec65-base
31-path/four-commit Astra/max/Standard/enforced-read-only independent review under
the existing non-hash-limited through53 authorization. Source corrections require
new exact verification; no tests repeat merely because approval was pending.
Staff UI planning remains outside the checkout and unactivated until this stage
receives independent zero-finding acceptance. Full52closure precedes53; fully
closed53pauseSAME native, OpenClawdisabled/no54. The separate Workboard private-note
restriction remains unresolved and must not be retried.

Correction1 implementation verified: finite original Payment/Credit/FX schemas and repeated source facts; whole recognition reversal consistent with disposition; revision-bound item_count and Invoice line_count/original_total_usd_cents/adjusted_total_usd_cents; Invoice version plus append-only draft history count/max; cumulative8388608UTF8bytes checked before retention and failure clears items/snapshot/cursor. Existing legitimate channel field precedence and legacy Payment/reversal references remain valid.45realPG,278client,14Chromium,26trace tests and full2555backend975DB-onlyskips/187static/build/import pass.1700prior mappings preserved plus17new. Original red evidence and test-helper/static failures remain retained; first Receipt mismatch premise is explicitly qualified. Fresh exact candidate gates and complete-base independent zero review are still required.
