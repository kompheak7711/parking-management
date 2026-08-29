# V1-042 Utility consumption and broken-meter estimation services — active

- Candidate: `V1-042` — Utility consumption and broken-meter estimation services.
- Authorization: Owner standing direct-Codex authorization for V1-042 through V1-060;
  this tranche is executed alone and requires no renewed routine approval.
- Baseline: clean synchronized `implementation/foundation` at V1-041 reconciliation
  commit `f8fe2547a6996c538fef0c3218cc52ac31c72979`.
- Preflight: PASS; V1-041 is complete and all three exact-SHA CI runs are green,
  V1-042 is the exact `approved_ready` successor, no other repository worker overlaps,
  and the Property Rental supervisor is disabled and not running.
- Partial-work recovery: no uncommitted V1-042 work exists; nothing requires preservation.
- Scope: actual Utility Consumption finalization, confirmed broken-Meter cases, exact
  historical/future basis selection, zero-history pending behavior, generation-date
  Utility Rate selection, and non-persisted calculation-preview services.
- Authorities: `BR-UTIL-018` through `BR-UTIL-032`, `API-048`, `API-049`,
  `TEST-048` through `TEST-052`, and `TEST-122`.
- Dependencies: published V1-041 Meter, Reading, correction, replacement, and Rate
  persistence.
- Excluded: Invoice issuance and scheduled billing, HTTP/UI delivery, invented units,
  substitute/comparable-Unit or arbitrary fallback policy, V1-043 and later work,
  canonical changes, production data/access, and installed Hermes-wrapper repair.
- Canonical specifications: read-only.
- Required invariants: same-Meter validated actual consumption; immutable non-overlapping
  source periods; confirmed failure and replacement only; latest-three or all one/two
  historical periods; first future period only for zero history; one weighted daily
  average; inclusive unmeasured days; no double-counted replacement day; Property-local
  generation-date Rate selection; whole-period Rate application; permanent evidence;
  authorization, idempotency, and real PostgreSQL concurrency.
- V1-043 and later: held; no activation or implementation is permitted.
- Scheduler: the Property Rental supervisor remains disabled and not running.
- Blockers: none.
- Independent review: twenty-one fresh external exact-diff rounds found 45 material findings
  (25 high, 20 medium); all are corrected within V1-042 with deterministic and real
  PostgreSQL regression coverage; round 21 reviewed the resulting exact diff and returned
  PASS with no actionable correctness defects and no reviewer edits. Complete per-session
  evidence is in `ops/STATE.json`; the clean verdict is preserved at
  `/private/tmp/property-rental-v1-042-independent-review-pass-21.txt`.
- Focused correction verification: PASS; all five pure Utility tests and the traceability
  guard pass. The initial complete-profile attempt truthfully stopped on the renamed test's
  stale traceability ID; that metadata reference was corrected before the full profile was
  restarted from gate one.
- Current complete verification: PASS, 15/15; backend 646 passed with 400 expected
  database-environment skips, frontend 213 passed, disposable PostgreSQL 412 passed,
  and automation routing 185 passed. Evidence:
  `/private/tmp/property-rental-v1-042-twentieth-review-correction-verification.json`.
- Status: implementation commit `5938d5d9142b3c4be6fcda1566736efd7a50396d`
  is published and exact-SHA GitHub Actions run `33237449033` passed all four jobs;
  the separate V1-042 closure commit and its own CI result remain pending.
- Exact next action: create and push only the V1-042 closure commit, require successful
  exact-SHA GitHub Actions, then reconcile closure-valid compact state while V1-043
  remains held.

<!-- AUTOMATION_STATUS_BEGIN -->

- Automation publication state: V1-042's implementation is published and exact-SHA
  CI-green but its closure remains pending; V1-043 and later remain held.
- Automation exact next action: keep the supervisor disabled and V1-043 held until
  V1-042 completes closure publication and reconciliation.

<!-- AUTOMATION_STATUS_END -->
