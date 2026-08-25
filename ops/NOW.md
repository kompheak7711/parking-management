# V1-026 Customer API and management UI — Review 56 passed

- Candidate: `V1-026` — Customer API and management UI.
- Authorization: Owner-approved direct takeover of `V1-024` through `V1-026` under the
  existing durable V1 scope; no renewed routine authorization is required.
- Baseline: synchronized `implementation/foundation` at `461745e`; V1-025 is published and
  CI-green at `bc8d68c` (run `32672174766`).
- Scheduler: exact supervisor `658ffdaf-1ac1-45a6-a842-f5f7d7a226eb` remains paused to prevent
  overlapping edits during direct takeover.
- Scope: authenticated Customer create/read/update, history-safe deactivation, minimized list,
  detailed history, currency-separated financial summary, and accessible management UI.
- Excluded: Customer Account Ledger, exports, later relationship/financial source writes, and
  all V1-027 activation or implementation.
- Canonical specifications: read-only.
- Activation repair: the roadmap's nonexistent `UI-CUST-*` wildcard was replaced with canonical
  `UI-028-030`; regression coverage and CI run `32672684442` pass.
- Complete verification: the fresh 15/15 profile passed after Review 52: 564 backend tests,
  160 frontend tests, 184 PostgreSQL tests, and 181 automation tests. Evidence:
  `/private/tmp/property-rental-v1-026-final-review52.json`.
- Independent review: 205 material findings across 52 fresh exact-diff reviews were corrected
  and regression-tested. Corrections cover migration safety and legacy-data preservation;
  command concurrency, idempotency, retention, replay, and reconciliation; strict API input,
  authorization, privacy, and error contracts; and safe browser draft/capability transitions.
- Review 52: two further defects were corrected. Untouched multiline contact addresses are no
  longer flattened into an unrelated update, and IndexedDB version changes now invalidate the
  cached coordination connection so later commands safely reopen storage. Both focused frontend
  regressions pass (127/127).
- Review 53: fresh external Codex exact-diff review passed with no actionable correctness
  regressions; its focused backend/frontend, lint, type, format, and production-build checks pass.
- Publication attempt: implementation commit `5a468c0` was pushed, but exact-sha GitHub Actions
  run `32813957600` failed only its Node 22 frontend test job. The remaining jobs were not the
  source of the failure.
- CI correction: WebCrypto byte decoding now supplies a standards-compatible typed-array view
  instead of its backing buffer. The exact Node 22.12 runtime now passes all 160 frontend tests.
- Fresh correction verification: all 15/15 complete-profile gates pass, including 564 backend
  tests, 160 frontend tests, 184 PostgreSQL tests, and 181 automation tests. Evidence:
  `/private/tmp/property-rental-v1-026-final-ci-correction.json`.
- Verification applicability: the fresh correction profile applies to the exact current candidate;
  publication remains held only for the corrective commit and exact-sha GitHub Actions.
- Review 54: fresh external Codex review of the exact three-file correction passed with no
  actionable regressions; reviewer session `01a0377e-f320-7893-802e-635e753e27c4` made no edits.
- Second publication attempt: commit `5a19290` fixed the Node 22 BufferSource failure. Exact-sha
  run `32815184996` passed backend, dependency-security, and PostgreSQL jobs, but its loaded runner
  needed 1.159 seconds for TEST-FE-135's async crypto/API/React path and exceeded the test's
  default one-second query deadline.
- Timing correction: TEST-FE-135 now uses a bounded five-second asynchronous query deadline.
  The exact Node 22 test passes ten consecutive stress repetitions and the full 160-test suite.
- Correction verification: the timing-only diff passes all 15/15 complete-profile gates, including
  564 backend, 160 frontend, 184 PostgreSQL, and 181 automation tests. Evidence:
  `/private/tmp/property-rental-v1-026-final-ci-timing-correction.json`. Publication remains held
  for independent review and exact-sha GitHub Actions.
- Review 55: the test timeout correction passed review, but the compact state used a descriptive
  uncommitted status outside the monitoring contract. It now uses canonical `complete_uncommitted`;
  the real classifier reports a known review/publication lifecycle with no Owner action, and all
  181 automation tests plus state routing and visibility-watchdog tests pass.
- Review 56: clean external Codex follow-up review passed with no actionable findings; reviewer
  session `01a0378e-6219-7360-a8b8-125235147941` made no edits.
- Token ceiling: 60,000 unchanged.
- Result: authenticated minimized Customer list, explicit detail/history navigation,
  capability-checked create/update/deactivation, stable identity preservation, and truthful
  financial-source unavailability with Customer credit separate from deposits.
- Blockers: none.
- Exact next action: publish the timing correction,
  require successful GitHub Actions, finalize without activating V1-027, then restore the supervisor.

<!-- AUTOMATION_STATUS_BEGIN -->

- Automation candidate state: V1-026 timing correction passed all gates and clean Review 56.
- Automation exact next action: Publish without activating V1-027
    <!-- AUTOMATION_STATUS_END -->
