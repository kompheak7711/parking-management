# V1-027 Configuration persistence — verified, unpublished

- Candidate: `V1-027` — Service, utility, payment-method, and exchange-rate
  configuration persistence.
- Authorization: existing durable V1 roadmap authorization; no renewed routine
  authorization is required.
- Baseline: clean, synchronized `implementation/foundation` at `34755c7`.
- Scheduler: exact supervisor `658ffdaf-1ac1-45a6-a842-f5f7d7a226eb` is disabled
  throughout direct work; no overlapping repository worker was present at takeover.
- Existing partial work: none. The scheduled supervisor did not run after activation and
  did not materialize or modify V1-027.
- Scope: effective-dated Property Service and Utility rates, append-preserved Service
  approval periods, configured Payment Method preservation, and append-only USD/KHR
  exchange-rate evidence.
- Dependency: V1-022 Property configuration persistence and Payment Method identity.
- Excluded: unresolved Utility unit metadata, configuration API/UI, production operations,
  canonical changes, and every V1-028 action.
- Canonical authorities: `BR-SVC-*`, `BR-UTIL-014-017`, `BR-PAY-006-007`, and
  `BR-MONEY-*`; canonical documents remain read-only.
- Token ceiling and automation protections: unchanged.
- Implementation: complete. Added effective-dated Property Service rates and approval
  periods, independent Electricity and Water rates, append-preserved exchange-rate
  evidence, and preservation checks for existing V1-022 Payment Methods.
- Verification: complete profile passed 15/15; backend 564 passed with 189 expected
  environment skips; frontend 160 passed; disposable PostgreSQL 193 passed; automation
  routing 182 passed plus compact-state routing and visibility watchdog.
- Independent review: PASS with zero material findings across the exact eight-path
  candidate. PostgreSQL constraints, privileges, upgrade behavior, concurrency coverage,
  canonical read-only scope, and the V1-028 hold were all confirmed.
- Status: complete and uncommitted; final verification and publication remain.
- Blockers: none.
- Exact next action: run final complete verification on the reviewed candidate, confirm the
  exact diff remains review-clean, then commit, push, require exact-SHA GitHub Actions
  success, and reconcile compact state without activating V1-028 or enabling the supervisor.
