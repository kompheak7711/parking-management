# Phase 2A provider-neutral authenticated actor boundary

- Objective: retain only the smallest authentication-provider-neutral server-side actor
  boundary while leaving the concrete production authentication mechanism unresolved.
- Current task: independently verified and published on `implementation/foundation`
  as `89f30ba`; no implementation cycle is active.
- Implemented: opaque `AuthenticatedActor` identity; injected request-to-actor resolver;
  default denial when no provider establishes an actor; protected
  `/api/v1/identity/me` returning only `data.actor_id` plus correlated API-011 `meta`.
- Rejected work removed: Argon2 dependency/lock changes, local username/password account
  behavior, password hashing, login/rate-limit logic, and in-process bearer-session
  issue/resolve/revoke behavior and tests/traceability.
- Security boundary: the API core does not parse or mint credentials, passwords,
  cookies, sessions, or bearer tokens. Client actor and authorization headers cannot
  establish identity without an injected trusted provider.
- Preserved boundaries: health remains public/minimal; canonical docs, database,
  frontend, financial logic, role/capability mappings, MFA policy, production provider
  choice, credentials, remote access, and deployment behavior are unchanged.
- Authority: API-001, API-003, API-007 through API-011, PR-AUTH-001, SEC-002,
  SEC-009, SEC-010, SEC-023, SEC-039, SEC-068, OOD-API-001, and DL-048. This tranche
  implements only the neutral actor-boundary portions; provider properties and
  business capability enforcement remain outside this bounded correction.
- Verification: format, lint, strict types, 49 backend tests plus 3 frontend tests,
  backend/frontend builds, TEST-118 traceability, locked runtime/development Python
  audits, npm audit, locked dependency checks, and all 6 isolated PostgreSQL migration
  tests via `make database-test` passed independently. Local, upstream, and remote
  publication SHAs matched `89f30ba23818d7d8ffb6edb30d8f311aeffa259a`.
- Blocker: none.
- Exact next action: obtain owner approval before beginning a bounded Phase 2B
  provider-neutral capability authorization boundary.
