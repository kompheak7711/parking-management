# Phase 2C — single-Property application foundation

- Objective: implement canonically bounded single-Property application primitives.
- Complete unpublished task: Property-local business-date conversion uses the standard
  library `Asia/Phnom_Penh` timezone and rejects timezone-naive instants.
- Canonical basis: `PR-PROP-003` and `DL-038` only; docs 001-010 remain read-only and
  unchanged.
- Fresh verification: RED confirmed the missing module; 3 focused business-time tests
  then passed. Format, lint, strict types, 56 backend tests plus 3 frontend tests,
  backend/frontend builds, 6 isolated PostgreSQL migration tests, and traceability passed.
- Independent review: PASS with no policy, logic, security, or bounded-scope findings.
- Preserved boundaries: database schema/data, API behavior, UI, authentication provider,
  role mapping, credentials, production configuration/access, and financial behavior are
  unchanged.
- Repository state: branch `implementation/foundation`, base HEAD/upstream `0187f265`,
  expected uncommitted tranche only; no commit, push, deploy, or remote access performed.
- Blocker: none.
- Exact next action: publish this independently verified tranche, confirm GitHub Actions
  and SHA/file-list integrity, then dispatch the approved high-risk single-Property
  identity scope primitive that rejects objects assigned to a different Property ID.
