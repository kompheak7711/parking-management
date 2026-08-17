# Phase 2B — capability authorization boundary

- Objective: add one provider-neutral, deny-by-default server authorization seam.
- Current task: owner-approved implementation is independently verified for review on
  `implementation/foundation` at unchanged HEAD `56f9274`; no commit or push was made.
- Scope: `AuthenticatedActor` now carries trusted capability grants with Property and
  exact-object scopes. `/api/v1/identity/me` declares `identity.read_self`, requires the
  actor's exact self-object scope, returns 401 without an actor, and returns 403 for an
  authenticated actor without the required grant or scope.
- Verification: focused tests first failed on missing authorization primitives, then all
  8 authorization tests passed. Format, lint, strict types, 53 backend tests, 3 frontend
  tests, backend/frontend builds, and all 6 isolated PostgreSQL migration tests passed.
  The TEST-117 manifest test passed and an independent security review returned PASS.
- Preserved boundaries: docs 001-010, provider implementation, role mapping, accounts,
  sessions, credentials, production config/access, business endpoints, UI, and database
  schema are unchanged.
- Blocker: none.
- Exact next action: publish the bounded seven-file Phase 2B tranche under the owner's
  standing commit/push authorization, then verify GitHub Actions and reconcile state.
