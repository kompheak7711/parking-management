# V1-018 Account and capability administration API — verified, unpublished

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
- Published automation predecessor: repository-owned dispatch/guard repair and its CI fixture
  correction are synchronized at `9f93cef90bbfa8dcab24b58dae05bd1113e96bbb`; GitHub Actions
  run 32458068234 passed all four jobs. The supervisor remains disabled during V1-018 publication.
- Blockers: none. Owner action: none.
- Exact next action: obtain a fresh independent review of the exact seven V1-018 paths, publish
  only those reviewed paths, require GitHub Actions success, reconcile V1-018 as published, and
  stop without activating V1-019.
