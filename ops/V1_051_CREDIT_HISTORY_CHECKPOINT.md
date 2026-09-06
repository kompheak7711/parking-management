# V1-051 Credit list/history service checkpoint

## Authority and accepted dependency

Standing direct Codex takeover through53 and frozen ops/V1_051_SCOPE.md apply.
Same sole codex/v1-051-direct checkout; no new worker/worktree. Financial/migration/
concurrency implementation Astra xhigh Standard; fresh independent exact-SHA reviewer
Astra max Standard, read-only. Actual coordinator02:54:36Z Astra/xhigh; local
service_tierdefault; provider-side Standard attestation unavailable. No fallback.

This candidate is a new immutable child of accepted Pet correction1
3c4015c6412803503126be3516311926c087afba, treefab7d12bf30e4fa8b56ee3c372621ace7d0881dd.
Fresh independent Pet review0HIGH0MEDIUM0LOW/all11paths/all3priorfindingsresolved:
v1051-pet-correction1-review-3c4015c.md
SHA256273848190f4728444ab10b7080cd6f4beab4c84cc5ab66b1d744e624975d914a.
Acceptance v1051-pet-refund-accepted-3c4015c.md
SHA256808c18b45ca2bbdaab2972176515c1d7174ea7443178c58e53b3b75c6e68975e
discharges immutable pending fields. Completed reviewer01a0747c-5cfe is not reused.
Preserve rejectedf311a90 and all earlier accepted Credit/Refund checkpoints.

## Bounded implementation and contracts

- API-061 Customer Credit list and Credit-only ledger services. CreditPage validates
  limit1..100 and complete aware UTC time/UUID; CreditLedgerPage adds a required known
  event family. Revalidate envelopes at transmission. Fresh exact-Property credits.read
  capability plus active HUMAN/property checks; no role bundle or mutation authority.
- New private position view derives recognized, active applied, net refunded, explicitly
  reversed and available integer USD cents using existing authoritative consumers.
  Credit Refunds do not debit the original Payment a second time.
- Private summaries/events are not executable by runtime/financial/bootstrap/PUBLIC;
  the position view is not selectable by those roles. Only two bounded public read
  facades are granted. SECURITY DEFINER fixes pg_catalog search path; times are UTC.
- Both public facades and source functions are STABLE: actor, Credit identity, current
  positions and history share the calling query's snapshot. Read-specific actor checks
  do not take command locks or write serialization guards; accepted write guards stay
  intact. Repeatable Read READ ONLY callers retain a coherent older snapshot while a
  fresh service request sees a concurrently committed Refund.
- History includes recognition/reversal, application/reversal, Refund, verified value
  correction and correction reversal. Exact source/reversal identity, actor, authorization,
  amount/currency, signed USD effect and retained reason are linked. History orders by
  (occurred_at,event_kind COLLATE C,event_id) descending; cursor retains all three fields,
  so equal UUIDs from different event tables cannot be lost. Timestamp-group cumulative
  balance is the as-of value including all events at that instant, not fabricated order
  among simultaneous events. Each page has at most100events; current positions are
  recomputed per request, so separate pages are not a multi-request frozen snapshot.
- Typed Payment/FX summaries preserve exact original currency/minor units/USD basis/
  rate identity/precise decimal strings. Original unbounded rate reference/calculation
  trace stays linked in its immutable source; no floating conversion or source rewrite.
  Long historical reasons are explicitly source-linked, not silently truncated.
  Application detail/proposal and unrelated Customer/unified history are not embedded.
- Existing Credit get/mutations/replay and Refund commands remain unchanged. Only the
  unpublished forward migration41 is extended; published migrations and canonical
  requirements are untouched. KHR Refund-specific schema/services remain a later51slice.

## Verification before freeze

All12new test functions have assertion-specific mappings in ops/traceability.json.
New PostgreSQL module is registered in the existing disposable synthetic harness.
-16unit PASS0.20s;38unit+traceabilityPASS6.73s;11focusedPGPASS2.43s.
-748fullPGPASS/zero skips113.79s; v1051-credit-history-full-postgresql.log
  SHA256f0d6fe201ef3e9441433d52d448630b19d2899dd03860250870b5a8b1c5cc376.
-956backendPASS/725DB-onlyskips separately covered41.09s; format/Ruff/mypy145/build/import;
  v1051-credit-history-full-backend.log
  SHA2561c0c2323ea33b9f462d023dbd2b5ff4332a04f6f23b7d7f75c49067377e3cf82.
-369frontendPASS19files6.58s/format/lint/types/build; v1051-credit-history-full-frontend.log
  SHA2561578420f1da6ad08da5bf8b8ac377767f439f259a88db12101e6646805bdf947.
-189automationPASS68.980s/routing/state/watchdog/retiredrestoration/syntax/compile/
  deployment configuration; v1051-credit-history-automation-initial.log
  SHA2565aeabd4f06dd153c3cdc57f2d0686a845895c696c79640aa93e8b66dd3a822ac.
- Development failures/resolutions preserved in v1051-credit-history-test-development.md
  SHA25681dfd24caebef7680b8b35c25b9442f75940855528608e8e92a18a18a48bc3aa.
  Evidence directory is /Users/sokompheak/.codex/.chatgpt-projects/g-p-6a721755d4048191b2550824162f9521.
- TEST-118zero new identifiers/working whitespacePASS. Check staged and cumulative
  whitespace before/after commit; bind exact SHA/tree and fresh exact committed gates
  in a subsequent receipt. No new dependency or network audit performed in this slice.

## Exact review and dependency-safe continuation

Candidate is the immutable commit containing this checkpoint, parent3c4015c. Require
fresh exact integration and independent Astra max read-only review of ALL changed paths
from3c4015c, including ops/evidence/mappings; zero HIGH/MEDIUM/LOW before local acceptance.
Do not edit or duplicate while a valid review runs. Full cumulative release basecc3d18e.
No Credit-history acceptance or V1-051 release yet.

Reconciled03:03Z: mainclean44d93be; tracking/fetched/livecc3d18e682401cc8a9ade10295572fe1a1344317;
predecessorCI33986122538 exactcc3d/all4SUCCESS;126retainedworktrees. Same tracking-only
cardc5621f97 blocked solely against OpenClaw admission, no claim/attempt/execution/owner
blocker. OpenClaw singleton658ffdaf disabled30minutes/no nextRun/runningtasks0. Native
same-task10minute follow-up ACTIVE, updated through supported interface with Pet accepted/
Credit reads active; saved prompt byte-verified SHA256
ae076b071b5079f1d2c0de72e7ee0166ec8a76cac3b0bf8af2e0fd800ea4b2af.
A later phase-specific follow-up update supersedes this recorded snapshot, not the policy.

After accepted Credit reads, implement original-KHR Payment excess and later Credit-to-KHR
Refunds within frozen51scope. Full51 remains OPEN/unpublished until allscope/freshgates/
authorized metadata-only audits/cumulative independent review/normal reviewed publication/
exactCI/refequality/same-card acceptance/durableclosure. No52until51closed; through53only,
then pause nativefollowup/leaveOpenClawdisabled/no54. Production/access/credentials/customer
data/paid/destructive/forcepush/historyrewrite/retained-worktree deletion stay unauthorized.
