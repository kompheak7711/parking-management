# Phase 2C — single-Property application foundation

- Objective: begin the canonically bounded single-Property application foundation after
  successful Phase 2B publication.
- Current task: approved and ready for high-risk Codex supervisor dispatch on
  `implementation/foundation` from synchronized checkpoint `d3dd0a3`.
- Scope: `AuthenticatedActor` carries provider-established capability grants with
  Property and exact-object scopes. `/api/v1/identity/me` requires
  `identity.read_self` for the actor's exact self-object scope, returning 401 without an
  actor and 403 without the required trusted grant.
- Fresh verification: all 8 focused authorization tests passed; format, lint, strict
  types, 53 backend tests, 3 frontend tests, and backend/frontend builds passed. The
  seven-path commit contains no canonical document change.
- Preserved boundaries: docs 001-010, provider implementation, role mapping, accounts,
  sessions, credentials, production config/access, business endpoints, UI, and database
  schema are unchanged.
- Remote verification: GitHub Actions run `32002986112` completed successfully on its
  first attempt for exact commit `a931f0a`.
- Blocker: none.
- Exact next action: implement and independently verify one bounded Phase 2C
  single-Property application foundation tranche, then commit and push only if every
  applicable publication gate passes.
