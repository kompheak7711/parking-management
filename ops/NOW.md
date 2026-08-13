# Phase 1D application-level safe error envelopes

- Objective: implement only API-013, API-014, TEST-088, and SEC-039 error-envelope
  infrastructure before business endpoints.
- Current task: implementation complete and verified on `implementation/foundation`;
  changes remain uncommitted and unstaged as owner required.
- Contract: malformed JSON returns the canonical safe 400 envelope; other FastAPI
  request/schema validation remains 422 with safe field locations. HTTP failures
  (including route-not-found) and unexpected exceptions use the same envelope shape.
- Statuses: canonical 400/401/403/404/409/412/422/429/500/503 mappings use stable,
  safe codes and messages; other HTTP statuses use a generic safe fallback.
- Validation safety: malformed JSON is classified only from framework error type and
  location. Validation responses omit rejected values and diagnostics; 422 responses
  expose only sorted, deduplicated, bounded field locations.
- Security: exception details, stack traces, SQL, credentials, configuration paths, and
  unauthorized object existence are never copied into unauthenticated responses.
- Correlation: the existing request-ID middleware is reused and `X-Request-ID` matches
  `meta.request_id` for every handled outcome, including unexpected failures.
- Preserved behavior: liveness/readiness success and readiness-unavailable bodies remain
  unchanged; no business endpoint, auth policy, logging, lifecycle, dependency, schema,
  migration, database, Compose, Makefile, environment, or product-policy change was made.
- Verification: the API-014 regression was observed failing at 422 before the fix; focused
  malformed/422 tests passed 2 and contract/health/traceability tests passed 39. Ruff
  format/lint, strict mypy, diff check, and canonical-doc integrity checks passed. The
  normal suite passed 41 with its 6 dedicated real-database tests skipped.
- Blocker: none.
- Exact next action: owner reviews this bounded uncommitted tranche; do not stage, commit,
  push, deploy, or start structured logging/lifecycle work without fresh approval.
