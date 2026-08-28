# V1-041 Utility meter, replacement, reading, and correction persistence — complete

- Candidate: `V1-041` — Utility meter, replacement, reading, and correction persistence.
- Authorization: Owner standing direct-Codex authorization for V1-041 through V1-060;
  this tranche is executed alone and requires no renewed routine approval.
- Baseline: clean synchronized `implementation/foundation` at V1-040 reconciliation
  commit `770e615d24e8f0167d12106657e5db416e0596bd`.
- Preflight: PASS; V1-040 is complete and exact-SHA CI-green, V1-041 is the exact
  `approved_ready` successor, no other repository worker overlaps, and the Property
  Rental supervisor is disabled.
- Scheduler: the Property Rental supervisor remains disabled and not running.
- Partial-work recovery: no uncommitted V1-041 work exists; nothing requires preservation.
- Scope: forward-only PostgreSQL persistence for Utility Meters, replacement history,
  validated Utility Readings, append-only Reading corrections, and effective-dated
  Utility Rates, building on published V1-023 and V1-027 persistence.
- Authorities: `BR-UTIL-001` through `BR-UTIL-017`, `API-044` through `API-047`,
  and `TEST-046` through `TEST-049`.
- Excluded: consumption/estimation services, utility billing generation, API/UI delivery,
  V1-042 and later work, canonical changes,
  production data/access, and installed Hermes-wrapper repair.
- Canonical specifications: read-only.
- Required invariants: Electricity/Water only; one active Meter per Unit/Utility Type;
  stable Meter/Reading identity; permanent replacement and correction history;
  chronological nonnegative validated Readings; exact Meter ownership; effective-dated
  immutable Rate history; authorization/audit provenance; real PostgreSQL concurrency.
- Implementation: the forward-only `20260828_31` migration now preserves Meter,
  replacement, validated Reading, correction, and Utility Rate unit-consistency history;
  focused disposable PostgreSQL verification passes 360/360, including concurrent
  active-Meter creation and current-evidence correction races.
- Complete verification: PASS, 15/15; backend 641 passed with 348 expected
  database-environment skips, frontend 213 passed, disposable PostgreSQL 360 passed,
  and automation routing 185 passed. Evidence:
  `/private/tmp/property-rental-v1-041-pre-review-verification.json`.
- Independent review: the first fresh external Codex review found two high and one
  medium finding. All three were corrected with a strict equal-timestamp correction
  order, post-failure Reading boundary, and deterministic observed-lock concurrency
  regressions. The canonical approved failure-to-replacement gap remains supported.
- Second independent review: one high reverse-history finding and one medium
  replacement-cycle finding were corrected by rejecting failure dates behind existing
  Readings and enforcing deferred recursive acyclic replacement history.
- Third independent review: one low operational-state finding was corrected by aligning
  the durable next action with the current final-review/publication step; no product or
  database behavior changed.
- Final independent review: PASS with no material findings and no reviewer edits.
  Evidence: `/private/tmp/property-rental-v1-041-independent-review-fourth.txt`.
- Corrected verification: PASS, 15/15; backend 641 passed with 352 expected
  database-environment skips, frontend 213 passed, disposable PostgreSQL 364 passed,
  and automation routing 185 passed. Evidence:
  `/private/tmp/property-rental-v1-041-second-review-corrections-verification.json`.
- Closure: commit `d6c05690d06ea06a9ce904c2ed7d976bf816fb6c`; exact-SHA
  GitHub Actions run `33173041349` passed all four jobs.
- Status: complete, published, independently reviewed, and closure-valid.
- V1-042: held at `approved_ready`; no activation or implementation occurred.
- Blockers: none.
- Exact next action: keep V1-042 held at `approved_ready` and keep the Property Rental
  supervisor disabled until this V1-041 reconciliation commit is exact-SHA CI-green;
  do not activate the successor automatically.

<!-- AUTOMATION_STATUS_BEGIN -->

- Automation publication state: V1-041 implementation and closure are published and
  exact-SHA CI-green; V1-042 remains the held approved successor.
- Automation exact next action: keep the supervisor disabled and V1-042 held; do not
  restore autonomous execution or activate the successor automatically.

<!-- AUTOMATION_STATUS_END -->
