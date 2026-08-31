# V1-045 Invoice lifecycle, issuance, adjustments, and void services — closure pending

- Candidate: `V1-045` — Invoice lifecycle, issuance, adjustments, and void services.
- Authorization: Owner standing direct-Codex authorization for V1-042 through V1-060;
  this release card is limited to the exact independently reviewed V1-045 SHA.
- Baseline: clean synchronized `implementation/foundation` at V1-044 reconciliation
  commit `5ad58a520ba9595b9b9ea9fc0ac6ed7d3c98769f`.
- Implementation: exact cumulative commit
  `df8096c1eb1e04aa7ec6c3c782a95fd3b549f1af`, direct parent
  `2c1c8532b7fb9b86c550457487b65e45ad06676d`; exactly 11 linear commits and
  15 reviewed paths from the baseline, published by non-force fast-forward. The
  final correction changed only `backend/tests/test_billing_run_migration.py`
  (+55/-13).
- Scope: authorized-source Invoice creation; DRAFT correction and issuance;
  immutable exact adjustments and exceptional VOID history; typed line sources;
  bounded list/detail APIs; financial, transaction, authorization, idempotency,
  replay, concurrency, audit, and migration invariants.
- Authorities: `BR-INV-*`, `API-050` through `API-053`, `TEST-053` through
  `TEST-058`, `TEST-117` through `TEST-119`, and the bounded `DB-INV-*` contracts.
- Excluded: physical deletion, product corrections during release, production
  deployment, production data or credentials, late-payment policy, and V1-046 work.
- Independent review: Workboard card
  `5e6e6369-6e13-4fb9-884c-6cf9e4ba57d8` returned an explicit zero-finding PASS
  for exact SHA `df8096c1`; reviewer made no edits and property-manager acceptance
  is recorded.
- Local release verification: focused Invoice 32/32; focused typed-source and
  cumulative retry/VOID PostgreSQL 2/2; focused billing-run 11/11; structural
  traceability 22/22 plus semantic TEST-119/API-050/API-051/API-053/DB-INV-002;
  complete deterministic profile 15/15; backend 711 passed with 433 expected
  database-only skips covered by real PostgreSQL 456/456; frontend 234/234;
  automation 186/186. Format, lint, strict type, build/import, locked dependency,
  Alembic one-head/36-linear-revision fresh and populated upgrade, deployment,
  publication, security, secret, JSON, traceability, and diff gates passed.
- Implementation publication: GitHub Actions run `33402789651` passed all four jobs
  for exact SHA `df8096c1eb1e04aa7ec6c3c782a95fd3b549f1af`.
- Status: V1-045 is functionally complete and the exact reviewed implementation is
  published and exact-SHA CI-green; this ops-only closure and final reconciliation
  remain pending.
- V1-046: remains held at `approved_ready`; no activation, implementation, or
  dispatch has occurred.
- Scheduler: no production deployment, scheduler activation, or scheduler weakening
  occurred.
- Blockers: none.
- Exact next action: publish this ops-only closure commit, require successful
  exact-SHA GitHub Actions, then create only one bounded ops-only reconciliation
  commit, require its exact-SHA CI, prove final source/local/upstream/live-remote
  synchronization, and release only to REVIEW.

<!-- AUTOMATION_STATUS_BEGIN -->

- Automation publication state: exact V1-045 target `df8096c1` is published and
  exact-SHA CI-green; closure and final reconciliation are pending.
- Automation exact next action: keep V1-046 held and undispatched while V1-045
  closure, reconciliation CI, and final synchronization complete.

<!-- AUTOMATION_STATUS_END -->
