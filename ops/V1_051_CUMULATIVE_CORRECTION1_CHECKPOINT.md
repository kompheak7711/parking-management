# V1-051 cumulative correction1 — bounded FX evidence and policy mappings

Rejected parent bdf45389946af3aa4fd67d273dc6c8cf9f00daa0 is retained unchanged.
Full cumulative review base remains cc3d18e682401cc8a9ade10295572fe1a1344317.
This checkpoint is not acceptance: freeze a new child, then fresh exact gates and
independent Astra max Standard read-only cumulative review are required.

## Findings and bounded approach

Prior complete47path review finished2026-09-06T09:39:43.327Z,0HIGH2MEDIUM0LOW.
Actual child01a07605-1156-7a90-9737-7e3844bb9013 (launcher01a07605-108a), execution36965
exit0, observedAstra/max/read-only/approvalnever/localdefault; no provider attestation.
Report v1051-cumulative-review-bdf4538.md SHA256
0fbdda12fe1d8de331946644fa37c3c01191da4ca55e91709fbf8ad5e994c2b6 matches JSONLfinal.
Do not poll that completed reviewer as running or repeat its failed checkpoint.

M1: Credit and Refund resources embedded unbounded FX source_reference and
calculation_trace in responses and every persisted command receipt. A regression
on unchanged bdf4538 product reproduced1682199characters where fewer than10000
were required. Retain the complete original record; use a private STABLE,
security-definer typed FX summary and immutable record ID in Credit/Refund resources.
Explicitly revoke PUBLIC/runtime/financial/bootstrap access to the new helper.
Original source evidence, exact decimal rates, USD balances, locks, authorizations
and command replay semantics are preserved. No historical receipt is rewritten.

Expanded large-evidence regression covers Credit recognition/get/replay/reversal,
list/ledger, Refund creation/one-cent return/correction reversal/full return/limit-one
page/replay, bounded persisted receipts and private helper ACLs. Fractional source
tests now check bounded exact scalar summaries and nested original trace decimals
in unchanged linked storage; the independent nested JSON decoder test remains.

M2: exact TEST-118 failed BR-CREDIT-011,BR-REFUND-006,PR-CREDIT-011,PR-REFUND-005,
PR-REFUND-006. Map them to the existing parametrized KHR-origin Payment/Credit USD
Refund assertions; do not weaken the audit or simply rename the headings back.
The new exact candidate must run the complete-base audit after freezing; prefreeze
old-HEAD checks did not cover then-uncommitted changed headings and are not proof.

Correction1 of at most2 materially different corrections for these findings.
No owner decision required: DL-060 USD-only policy and routine correction authority
remain explicit. KHR-refund proposal rejected, original KHR/FX audit evidence retained.

## Prefreeze verification and evidence

Evidence directory: /Users/sokompheak/.codex/.chatgpt-projects/g-p-6a721755d4048191b2550824162f9521.
- Reproduction log v1051-correction1-fx-size-reproduction.log SHA256
  864f492926b6ddcc88a47bf6c5c07ae215405557391a3d2e098e16e3bf48b2dd:
  expected failing size assertion on old product,1FAIL/750deselected,1.52s.
- Corrected focused PostgreSQL10PASS/741deselected,2.31s; log
  v1051-correction1-focused-postgresql.log SHA256
  2faca408d1ca486ab099563722829043a523c0666ef6541a283c57642ff3f5f8.
- Full PostgreSQL751PASS,zero skips,118.20s; v1051-correction1-full-postgresql.log
  SHA2563f1ea827a65f30699ffdd5f77c8bbfa821742234e2c938efc59a37754ea9a6bd.
- Backend956PASS/728DB-onlyskips separately covered,43.20s; frontend369PASS/19files;
  formatting/lint/mypy145/build/importPASS. v1051-correction1-full-application.log
  SHA25669071fa77e1b637ec9d00ad16afd73bcdfc63c0c5aa1cb98764bd7f298a8ca8e.
- Automation189PASS70.661s; routing/state/watchdog/retired restoration/syntax/compile/
  deployment configPASS. v1051-correction1-full-automation.log
  SHA2562490aa7c18cdd6af57a1874eb6ababa43aaad9d41b3acef694f80e938c33959d.
- Publication worktree secret/JSON/whitespace guardPASS; five mappings confirmed
  present. Exact committed TEST-118 and full cumulative whitespace still required.
  No canonical document is changed by this correction; the parent DL-060 canonical
  edits remain separately owner-authorized. No safety guard altered.
- Existing official PyPI runtime/development and npm audits were clean; lockfiles
  unchanged. All hashes in the preserved USD-only checkpoint.

Development diagnostic: the new Refund limit-one test initially passed its page as
positional actor, caught by mypy; corrected to the existing page keyword. Static
checks and focused/full PostgreSQL then passed; no product guard/assertion weakened.

Product hashes: migration41 da25459e1f4d9cf29449e24b4cc7297fd78a42aade146bac8bd64d4bf752a4eb;
Credit history tests c6d26780b6afb3870fa84f75e2a1305112810a5dd46f254af9daa0705cfe0e38;
Credit migration tests3521156fae74b15414bf477c6bac3efede85b2400e2dd141de921546ea746a83;
traceability83ffc96019dd862beec76b9652c94ad04fe06dbe2249c3cbf1ef50360d62d192.

## Durable coordination and next action

Native follow-up property-rental-v1-047-closure-follow-up remains ACTIVE10minutes,
same coordinator task01a04961-4270-7802-9418-e08203784a8c. Its complete saved policy
is now phase-independent, preserving all authority/model/safety/lifecycle sections
and DL-060;11248characters byte-verified after supported update, SHA256
49baafc52ee102a222a36890c93eb4c877282f3ff4d75e7ebd21e353ba1955b2.
It reads the current stage from property-rental-codex-takeover-live.md in the evidence
directory, instead of retaining old running/pending instructions. Later exact-SHA
results update that live index without editing a frozen reviewed checkout. Historical
prompt hashes and prior handoffs remain evidence, not current dispatch instructions.

Same cardc5621f97 tracking-onlyblocked againstOpenClawadmission/nullclaim-attempt-execution;
completed-review/correction comment05e72b0c-3ce2-4f09-bdbe-580f3211c3ff. All126worktrees
retained. OpenClaw singleton658ffdaf disabled30minutes/no next run/no workers.
Full V1-051 OPEN/unpublished. Freeze new child, fresh exact gates and independent
zero-finding cumulative review, normal reviewed publication, exactCI/all4jobs/refequality,
same-card acceptance and terminal durable closure before52. Continue through53;
then pause native follow-up/leave OpenClaw disabled/no54. All production/access/
credentials/customerdata/paid/destructive/forcepush/historyrewrite/worktree deletion
exclusions remain. Do not request routine authorization or restore KHR policy wait.
