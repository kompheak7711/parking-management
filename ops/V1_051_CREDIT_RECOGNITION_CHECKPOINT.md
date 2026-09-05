# V1-051 Credit recognition checkpoint — partial, unpublished

Updated 2026-09-05T20:42:21Z. Sole implementation checkout:
`/Users/sokompheak/Development/property-rental-management-v1-051`,
branch `codex/v1-051-direct`, coordinator task
`01a04961-4270-7802-9418-e08203784a8c`.
This is a recoverable implementation checkpoint, NOT a release candidate,
independent product acceptance or V1-051 closure.

## Authority and dependency state

V1-050 remains fully closed at cc3d18e682401cc8a9ade10295572fe1a1344317;
exact CI33986122538 attempt1/all4jobs success and remote still cc3d verified.
Accepted activation44d93be5bb557bc221f392c52ad1d8a8604142e4 precedes this work.
Do not repeat activation, scope freeze, predecessor closure or activation review.
Cumulative future product review base remains cc3d, including all activation/checkpoint changes.
Frozen scope ops/V1_051_SCOPE.md; complete authority ops/CODEX_TAKEOVER_V1_048_053.md.
Direct continuous authorization through53, normal reviewed non-force publication and
official registry metadata-only audits remain effective. All existing safety exclusions remain.
Actual coordinator turn_context2026-09-05T20:27:36.075Z is gpt-6-astra/xhigh;
local service_tier=default. Provider-side tier attestation is unavailable.

## Implemented slice

- Forward unpublished migration41 adds append-only payer-authorized USD Credit recognition,
  recognition reversals, exact transactional command receipts and atomic audit.
- Original Payment, Receipt and KHR/FX source facts stay unchanged. Active recognized
  value reduces Payment availability; reversal releases it once without erasing history.
- Current and chronological Payment budgets, Payment reversal and proposal-dependency
  timestamps include Credit recognition/reversal alongside existing Allocation/Deposit events.
- New Python Credit service separately authorizes read, recognition and reversal for
  exact Property; fresh human lifecycle checks; immutable bounded scalar intent;
  exact idempotent replay and safe unresolved-outcome error handling.
- True excess requires all applicable Invoice AND separate Charge obligations settled.
  Preserve payer and third-party identified intent; no automatic Credit or future Invoice.
- Excess classification uses READ COMMITTED and short SHARE locks on ten existing
  obligation producer tables. NOWAIT after the Payment source lock prevents lock-order
  waiting cycles; active competing writers reject with an unresolved retryable outcome.
  Snapshot-isolation recognition fails closed. This conservative throughput tradeoff is
  technical concurrency protection, not a new financial rule.
- Tests registered in the isolated database harness and traceability manifest.
  Nineteen existing latest-head expectations move40to41; historical upgrades remain unchanged.

## Verification of this working-tree slice

- Focused Credit unit31PASS; focused PostgreSQL35PASS.
- Complete PostgreSQL619PASS, zero skips,100.85seconds. Includes all previous Payment,
  Allocation, Receipt, migration/race/history regressions plus new Credit tests.
- Complete backend857PASS/596database-only skips,38.84seconds. Those596 cases are
  separately covered by the complete isolated PostgreSQL suite; not waived.
- Backend formatting137files, Ruff, mypy137files, sdist/wheel build and app import PASS.
  Migration formatting and Ruff independently PASS.
- Automation189PASS,74.920seconds; state routing, watchdog, retired restoration,
  shell syntax, Python compilation, deployment configuration, traceability and
  publication/secret guard, and whitespace diff checks PASS.
- Frontend gates and dependency audits have NOT been rerun for this partial slice.
  Full future exact-SHA product gates, audits and independent Astra max Standard
  read-only zero-finding cumulative review remain mandatory before publication.
- First backend run failed only because eight new unit-test manifest entries were
  missing (856passed/596skipped/1failed). Exact mappings added; full rerun above passed.
- Initial PostgreSQL run failed on a test comparing selected Receipt Payment fields
  with the entire source row. Corrected to exact selected Payment and financial-position
  objects while retaining raw Payment/Receipt equality assertions; no product rule weakened.
- Early lint findings were new-test line lengths/fixture annotations; corrected and verified.
  Existing Starlette httpx deprecation warning remains non-failing.

## Remaining V1-051 work — do this next

1. Continue this SAME checkout. Do not recreate migration41 or another worker/worktree.
2. Add Credit application headers/details/reversals, bounded per-target proposal and
   explicit designation, same-Customer/Property/source-target validation, authoritative
   line attribution and current/historical Credit budget. Integrate target locks and
   Invoice/Charge balances, statuses, adjustment/void/correction chronology.
3. Extend excess-classification locks to new Credit application/reversal producers.
   Replace the explicitly partial credit_available_value with all Credit consumers,
   and strengthen recognition reversal with application/Refund resolution and chronology.
4. Extend EXISTING Refund/correction history for Payment excess, Credit, qualified
   active-Lease Pet Deposit and preserved Reservation full-refund paths. Integrate exact
   original-KHR versus later Credit-refund FX, source budgets and verified-return corrections.
   No fabricated Final Settlement source, unsupported statuses or new collection rights.
5. Add bounded Credit history/read models and all remaining actual scope regressions.
   Freeze full immutable product, run fresh complete exact-SHA gates/audits and fresh
   independent Astra max Standard read-only zero-finding cumulative review.
6. Only then reviewed normal publication, exact GitHub Actions/ref equality, same-card
   acceptance and separately reconciled terminal closure; then52and53 dependency-ordered.
   At53closed pause native follow-up, leave OpenClaw disabled and do not activate54.

## Coordination

Singleton OpenClaw supervisor658ffdaf-1ac1-45a6-a842-f5f7d7a226eb disabled,
retained30minute schedule/no next run; running OpenClawtasks0.
Tracking-only cardc5621f97-7ad1-4b1c-b04f-c854376c2ad8 remains blocked solely
against OpenClaw admission, with no claim/attempt/execution and no owner blocker.
All126worktrees retained; main coordinator stays44d93 and points to this sole checkout.
Existing native10minute follow-up remains ACTIVE; update its checkpoint in place only.
Preserve all failed checkpoints/reviews/evidence. No V1-051 publication or closure yet.
