# V1-015 Login, MFA, Logout, Reauthentication, and Session API — active

- Objective: implement the exact structured V1-015 Identity candidate under durable v1
  authorization.
- Scope: local authentication endpoints, secure browser transport, and CSRF protection where
  applicable.
- Authorities: API-008 through API-010, API-096 through API-097, TEST-108, TEST-128, and
  TEST-131 through TEST-132.
- Excluded: external identity providers, canonical policy changes, production credentials,
  remote access, destructive data operations, and unapproved scope expansion.
- Published predecessor: V1-014 persistent browser-session and revocation persistence is complete.
  Its implementation, real PostgreSQL checks, application gates, automation repairs, and dependency
  checks passed locally and in GitHub Actions.
- Publication repair: candidate CI now precedes any publication-state mutation; failed or missing CI
  leaves state and Git unchanged; successful reconciliation records the completed publication
  lifecycle; a stale current-tranche candidate can no longer block structured successor selection.
- Publication evidence: corrective runs 32234182703, 32234417192, 32234591248, and 32234847489
  passed. V1-015 selection run 32235008614 passed.
- Roadmap: V1-001 through V1-014 are complete; V1-015 is active and V1-016 remains the next
  dependency-ready approved candidate.
- Blockers: none. Owner action: none.
- Exact next action: implement the approved bounded V1-015 candidate and run its api_ui acceptance
  profile plus all publication gates before independent review.
