# V1-042 Utility consumption and broken-meter estimation services — complete

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
- Closure: commit `9d7f1a7a03eb75e81877caa61916ec618cf3ce31`; exact-SHA
  GitHub Actions run `33237639691` passed all four jobs.
- Corrective implementation: commit `dde389b724a2bfddb52a945958e34064b14b2e1f`;
  exact-SHA GitHub Actions run `33245835436` passed all four jobs.
- Corrective closure: commit `1a7514a13d65fcffdc876e61f6d0e2f82f2f3983`;
  exact-SHA GitHub Actions run `33246001132` passed all four jobs.
- Status: complete, published, independently reviewed, and corrective closure-valid.
- V1-043: held at `approved_ready`; no activation or implementation occurred.
- Corrective reconciliation: first reconciliation commit
  `d42a7497549152103ab58b0fed682ade216fe230` failed exact-SHA GitHub Actions run
  `33237892730` only because the held V1-043 authority `UI-UTIL-*` matched no canonical
  identifier. Read-only inspection confirmed exact requirements `UI-056` through
  `UI-062`; V1-043 remains unactivated. Subsequent external review found and the
  preserved V1-042 worktree corrected exact broken-Meter responsibility segmentation,
  canonical numeric/whole-cent bounds, deterministic non-finite rejection in Python and
  PostgreSQL, and exact Utility traceability.
- Scheduler: the Property Rental supervisor remains disabled and not running.
- Blockers: none.
- Independent review: thirty fresh external exact-diff rounds found 59 material
  findings (34 high, 25 medium). All are corrected within V1-042. Round 29 made no edits
  and identified that the round-28 source locks could still form a lock-upgrade cycle with
  a revision-32 service writer admitted during validation; its finding is preserved at
  `/private/tmp/property-rental-v1-042-independent-review-29.txt`. The upgrade now drains
  replaced function entry points and takes final-mode locks at supported write front doors
  before any source scan.
  Round 30 made no edits and returned `PASS` with no material findings after checking
  the exact 14-path diff, revision-32 fingerprint, migration front doors, rollback,
  history, traceability, the disabled supervisor, and the held V1-043 successor.
  Evidence: `/private/tmp/property-rental-v1-042-independent-review-30.txt`.
  Complete per-session
  evidence is recorded in `ops/STATE.json`.
- Focused correction verification: PASS; all 417 disposable PostgreSQL tests pass. The
  new production-shaped regression pauses the upgrade inside validation, starts a real
  revision-32 service writer, proves it waits at the command front door without holding
  source locks, and then verifies both transactions complete without deadlock.
- Current complete verification: PASS, 15/15; backend 654 passed with 405 expected
  database-environment skips, frontend 213 passed, disposable PostgreSQL 417 passed, and
  automation routing 186 passed. Evidence:
  `/private/tmp/property-rental-v1-042-round-29-correction-verification.json`.
- Exact next action: keep the Property Rental supervisor disabled and V1-043 held for a
  separate direct-takeover turn; do not activate the successor automatically.

<!-- AUTOMATION_STATUS_BEGIN -->

- Automation publication state: original and corrective V1-042 implementation and
  closure commits are exact-SHA CI-green; V1-043 remains the held approved successor.
- Automation exact next action: keep the supervisor disabled and V1-043 held; do not
  restore autonomous execution or activate the successor automatically.

<!-- AUTOMATION_STATUS_END -->
