# V1-056 login sub-slice L5 — every route needs a signed-in user and a capability — review record

Sub-slice L5 of the login slice (ops/V1_056_PLAN.md section 7.3, L5). No migration.
Base commit: 09b6782 (L4). Built on 2026-10-24 in the cloud session. Decisions: owner answers
(a) to Q-2026-10-21-151 and Q-2026-10-21-160; technical points in Q-2026-10-24-186, decided by
Claude under the owner's 2026-10-23 22:30 rule. The commit hash is in `git log` (this record is
part of that commit).

## Built

- One router-level check (`signed_in_browser_request`) on every router except the health and
  identity router and the sign-in router: 401 without a signed-in user, then for a change the
  configured Origin and the CSRF pair (403), before the body is validated. The signed-in user is
  found once per request (`remembered_actor`). The generated documentation pages are turned off.
- `settings.manage` for the Service rate and Utility Rate changes, the Property update, the
  Property configuration update and the one-time charge due-days setting; `property.read` for
  the Property read; `units.read` for the Unit list, a Unit and its timeline; the configuration
  read accepts `settings.manage` or `property.manage`; Unit create and update need the Origin and
  the CSRF pair. The screen's due-days form follows `settings.manage`.
- Tests: `test_route_authorization_inventory.py` (six tests over every operation),
  `test_settings_access_routes_migration.py` (PostgreSQL, real sessions), new Property and Unit
  tests, TEST-FE-685; changed committed tests in docs/010, "Updated tests (login sub-slice L5)".

## Review round 1 (one independent and security agent, read-only, no files written)

- No blocker.
- Should-fix, all done: (1) the generated documentation pages answered without a session and
  were outside the inventory: turned off, and the inventory now checks that the app serves
  nothing outside its OpenAPI document and that the pages answer 404; (2) the docs said the check
  runs "before the body is read", but FastAPI parses the JSON first (a body that is not JSON
  answers 400): the wording is now "before the body is validated", and the body size before the
  check is a slice 12 item; (3) the Settings functions still write the old capability names in
  their audit evidence: recorded as an exception and a slice 12 item (an additive migration);
  (4) the nil-Invoice test had lost its hidden-404 check: it keeps the 404 with a valid CSRF pair
  and checks the CSRF refusal separately.
- Notes: a holder of `units.read` for one Property can tell from 403 or 404 whether a random
  Unit id exists in another Property (accepted; much stricter than before L5, when any session
  read any Unit); the remembered actor is per request and the sign-in routes never use it; no
  check got weaker; the business configuration form is still shown to a holder of
  `property.manage` alone and its save answers 403 (for the screen rebuild); the open-operations
  test was renamed and now also checks the served routes; the database test now creates the
  Manager's Unit before any Settings access; no secret in the diff.

## Review round 2 (one agent, read-only, no files written)

- No blocker, no should-fix; every round 1 fix checked. Notes: the guard's docstring still said
  "before the route reads its body" (fixed as text); the served-routes check would not see a
  HEAD-only route, a mounted app or a path answered by middleware (none exist; a future static
  mount must be added to it); the check imports a private helper from the bootstrap test module
  (accepted). No round 3: round 2 found nothing to fix but text.

## Runs

- Static checks: ruff, format and mypy (backend); prettier, eslint and tsc (frontend): clean.
- U1 (before the last test edits): 6 failed, 3,936 passed; the 6 were the L5 changes (fixed).
- U2: 3,954 passed (3 log tests could not start because the run had log capture turned off; they passed in U3).
- U3 (every API and app test, the tests changed after the reviews and the three log tests): 1,344 passed.
- P1 (full PostgreSQL): 2,676 passed, 1 failed: the due-days database test's actor held `property.manage` but not `settings.manage`; fixed (docs/010, updated tests); T7 (that module and the new Settings routes module): 8 passed.
