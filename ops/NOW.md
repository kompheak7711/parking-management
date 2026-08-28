# V1-040 Rent proration and fixed-service billing services — complete

- Candidate: `V1-040` — Rent proration and fixed-service billing services.
- Authorization: Owner standing direct-Codex authorization for V1-040 through V1-060;
  this tranche is executed alone and requires no renewed routine approval.
- Baseline: clean synchronized `implementation/foundation` at V1-039 reconciliation
  commit `d1994fb703fd6e34b50e919cfc98898949caa8ca`.
- Preflight: PASS; V1-039 is complete and exact-SHA CI-green, V1-040 is the exact
  `approved_ready` successor, no other repository worker overlaps, and the Property
  Rental supervisor is disabled.
- Scheduler: the Property Rental supervisor remains disabled and not running.
- Scope: initial, recurring, and approved final Rent calculations plus approved,
  configured fixed-Service calculations built on V1-039 Invoice persistence.
- Authorities: `BR-RENT-*`, `BR-SVC-*`, and `TEST-040` through `TEST-045`.
- Dependency: published V1-039 Invoice persistence.
- Excluded: Utility billing, V1-041 and later product work, canonical changes,
  production data/access, and installed Hermes-wrapper repair.
- Canonical specifications: read-only.
- Implementation: complete and published at
  `4651b9f71d9f58f0dbc8abd736e868a6b437c0b9`; exact-SHA GitHub Actions run
  `33160649278` passed all four jobs.
- Verification: eleventh-review correction complete profile PASS 15/15; backend
  641 passed with 339 expected environment skips, disposable PostgreSQL 351/351,
  frontend 213 passed, and automation routing 185/185.
- Independent review: the first exact-diff review found two high and four medium
  issues; the second found one high and one medium issue; the third found two high
  and three medium issues; the fourth found one high and one medium issue; the fifth
  found one high and one low issue; the sixth found one high and one low issue. All
  nineteen are corrected and regression-tested. The seventh found one high issue,
  now corrected with a real concurrent Lease/Occupancy regression. The eighth found
  one high Service-source late-commit issue, now corrected with Property-wide source
  serialization and two concurrency regressions. The ninth found two high issues: a
  cross-source lock inversion and calculation-component chronology that was not bound to
  the durable cutoff. Both are corrected with one Property-first source lock order,
  explicit cutoff timestamps, and real concurrency/chronology regressions. The tenth
  found one high reverse tuple-lock/Property-lock deadlock issue, now corrected by using
  the Property boundary as the stable READ COMMITTED serialization point without
  conflicting Lease/Occupancy tuple locks; the reverse interleaving is regression-tested.
  The eleventh found one high direct-call stale-snapshot issue, now corrected by
  enforcing READ COMMITTED inside the database function and rejecting REPEATABLE READ
  and SERIALIZABLE before any write. The corrected exact diff passed the complete
  verification profile. The twelfth fresh exact-diff review returned PASS with no
  material findings and explicitly judged the diff safe to publish.
- Closure: commit `c4293ea98ff4e4a3d2c5d890b437655e0bad1e10`; exact-SHA
  GitHub Actions run `33160919700` passed all four jobs.
- Status: complete, published, independently reviewed, and closure-valid.
- V1-041: held at `approved_ready`; no activation or implementation occurred.
- Blockers: none.
- Exact next action: keep V1-041 held at `approved_ready` and keep the Property Rental
  supervisor disabled; do not activate the successor automatically.

<!-- AUTOMATION_STATUS_BEGIN -->

- Automation publication state: V1-040 implementation and closure are published and
  exact-SHA CI-green; V1-041 remains the held approved successor.
- Automation exact next action: keep the supervisor disabled and V1-041 held; do not
  restore autonomous execution or activate the successor automatically.

<!-- AUTOMATION_STATUS_END -->
