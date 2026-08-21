# V1-018 Account and capability administration API — published and reconciled

- Objective: implement the approved bounded V1-018 Account and capability administration API.
- Current task: independently review and publish the verified API-079/080 routes,
  SEC-019-023 enforcement, and PR-AUTH capability checks on `implementation/foundation`.
- Implemented: all nine approved account, session-revocation, capability-catalog,
  configurable role-bundle, and role-assignment operations under `/api/v1`.
- Authorization is deny-by-default, capability-based, and Property-scoped. Identifier-only
  mutations resolve authoritative resource scope before mutation. Client role/capability/
  Property headers remain inert, and role names are configuration data only.
- Strict request/response models exclude credentials and reject unknown fields, empty
  updates, malformed capabilities, and cross-Property assignments. The application remains
  fail-closed without an injected audited administration adapter.
- Focused API contract/security coverage and traceability were added. The existing complete
  runtime route-inventory test now includes the approved V1-018 routes while preserving the
  no-web-bootstrap assertion.
- Verification: focused V1-018 tests passed 47; the complete 15-gate foundation profile passed,
  including backend 333 passed with 105 expected environment skips, disposable PostgreSQL 105,
  frontend 3, automation 88, formatting, lint, strict typing, builds, dependency audit,
  deployment configuration, traceability, JSON, publication guards, and diff integrity.
- Verification and first-review fixes remained inside the preserved candidate: exact object and
  Property authorization, browser-origin/CSRF protection, version preconditions, bounded stable
  pagination, creation Locations, lifecycle allowlisting, relationship authorization, and
  fail-closed result binding now cover the complete administration surface. Exact-object denial
  precedes existence resolution; disablement and capability reduction bind immutable audit and
  applicable-session revocation atomically; cursor-aware tests traverse every collection to
  termination without duplicates or skips. OpenAPI safety checks inspect recursively exposed
  field names instead of safety prose.
- Independent review: PASS with no findings for the exact seven-path fingerprint
  `0241af6b4a96cccffdc87ae6be53446fc4344b8c8ca32cbe6b2063ba8b6b390d`;
  the reviewer made no edits. Product commit `98ee724e98d2442fd0254bd825256707108f71c8`
  is pushed and synchronized; GitHub Actions run 32461040956 passed all four jobs.
- Published automation predecessor: repository-owned dispatch/guard repair and its CI fixture
  correction are synchronized at `9f93cef90bbfa8dcab24b58dae05bd1113e96bbb`; GitHub Actions
  run 32458068234 passed all four jobs. The supervisor remains disabled during V1-018 publication.
- Blockers: none. Owner action: none.
- Reconciliation commit `5a580c33be98cc29f30caf195000c712fd62998c` is pushed and
  synchronized; GitHub Actions run 32461385184 passed all four jobs. The supervisor restoration
  metadata is ready for its final CI gate before the external schedule is re-enabled.
- Exact next action: require successful CI for the scheduler-restoration metadata, then re-enable
  the existing supervisor without manually activating V1-019 in this session.

<!-- AUTOMATION_STATUS_BEGIN -->
- Automation publication state: V1-018 published on `implementation/foundation` at
  `98ee724e98d2442fd0254bd825256707108f71c8`.
- Automation exact next action: After scheduler-restoration metadata CI and SHA equality, enable
  the existing supervisor; do not manually activate V1-019 in this session.
<!-- AUTOMATION_STATUS_END -->
