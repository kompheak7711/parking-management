# V1-020 identity and security hardening — bounded implementation ready

- Candidate: `V1-020` — Identity and security end-to-end hardening gate.
- Authorization: standing authorization for the remaining approved V1 roadmap; no renewed
  tranche authorization was consumed.
- Activation: published at `cb39e25`; its V1-019-coupled CI test was isolated and the repair
  passed GitHub Actions at `8eaefb9`.
- First Hermes result: session `20260823_003208_38266a` made one API call, changed zero files,
  and correctly reported that the packet prohibited discovery while supplying no readable path.
- First routing repair: commit `21334e2` fixed empty packets and passed GitHub Actions run
  `32588816502`; the exact zero-change failure was archived as recovered.
- Remaining defect: Hermes then requested all eight authentication files as one 82,472-byte
  parallel read. The 36,000-byte tool allowance rejected it atomically; repeated rejection
  context reached the proactive ceiling after four calls and changed zero files.
- Repair: V1-020 is divided into seven security-hardening sessions. Every complete parallel
  readable batch is at most 30,000 bytes, with exact authority excerpts and the unchanged
  60,000-token ceiling.
- Forward routing: repository-backed wildcard authority expansion and a bounded
  traceability/profile fallback prevent later approved candidates from receiving empty packets.
- Verification: all 128 automation tests, routing/state/watchdog suites, shell and Python
  syntax, JSON validation, publication guard, and diff checks pass.
- Publication: routing revision v2 commit `324cb36` passed GitHub Actions run `32589644022`;
  the no-change ceiling checkpoint was archived as recovered.
- Authentication core: Hermes session `5b424640f4c7cc74346b7e687f02f455` successfully read
  the 21,243-byte batch and changed three authorized paths before its final response call reached
  the proactive ceiling. The partial work was preserved; Codex completed traceability and the
  focused authentication/traceability suite passes 44 tests.
- Complete verification: PASS 15/15; backend 347 passed with 105 expected local environment
  skips, disposable PostgreSQL 105 passed, frontend 32 passed, and automation 128 passed.
- Review: the seven-path authentication-core diff was reviewed against TEST-108 and
  SEC-068–070; no material finding remains. Candidate-wide independent review remains at the
  final V1-020 publication gate.
- Scheduler: supervisor `658ffdaf-1ac1-45a6-a842-f5f7d7a226eb` is paused between bounded
  substages; daily reporting and watchdog jobs are unchanged.
- Authentication API: session `aa20ea3470d021ff8aed6b5e5aecaaff` reviewed the complete
  route module and changed zero files. Its attempted broad patch failed atomically; direct review
  retained the existing bounded inputs, origin/CSRF checks, secure cookies, generic errors, and
  centralized rate-limit/unavailable handling. The focused API/error suite passes 47 tests.
- Sensitive data and privileges: session `9e84786468ca446b69359637c3263bd3` reviewed the logging
  allowlist, redaction tests, distinct database identities, protected secret sources, and grants;
  no product change was required and 16 focused checks pass.
- MFA policy: session `3e412c9d1876fdb6b07b2a8d360333df` identified useful TOTP
  hardening mixed with an unnecessary SMS-domain change. The SMS change was rejected because the
  API already excludes and tests SMS. Codex added RFC SHA-256/SHA-512 vectors, non-byte protected
  material rejection, immutable audit evidence, and traceability; 69 focused tests and all 15
  complete-profile gates pass (353 backend, 105 PostgreSQL, 32 frontend, 128 automation).
- Recovery: session `f29c92616ed39c67c304e2bd76c1e2fb` completed a bounded review with
  no product changes. Existing coverage proves secure generation, one-time presentation and use,
  reuse rejection, regeneration invalidation, rate limiting, enumeration-safe outcomes, session
  revocation, controlled administrative/emergency recovery, and secret-free immutable audit;
  all 146 focused recovery, revocation, and traceability tests pass.
- Sessions/integration: session `b07fbe99f1be2a7119e6e88e7841e080` added the missing
  MFA-recovery session-revocation trigger and strengthened logout, authentication-recency, and
  provider-neutral authorization-boundary coverage. All 101 focused tests and all 15
  complete-profile gates pass (357 backend, 105 PostgreSQL, 32 frontend, 128 automation).
- Bootstrap/release: session `3b0aa565a6f4daf69c359800c90065b8` completed a bounded
  review with no product changes. Existing coverage proves the protected one-time Owner ceremony,
  exact recovery-code issuance, atomic rollback and closure, least privilege, no public bootstrap
  or reset path, and immutable secret-free evidence; all 93 focused tests pass.
- Product status: all seven V1-020 implementation substages are complete; final candidate-wide
  verification, review, and publication remain.
- Independent-review routing: session `5c98b1abe28618f6e6d3bc8d5f93889b` used 13,653
  tokens before the guard safely rejected a projected 89,547-token follow-up. No tools ran and no
  repository files changed. The repair now materializes only the exact candidate diff and compact
  verification evidence for a direct JSON verdict; the complex-review ceiling remains 90,000.
  The repaired path passes all 129 automation tests and the complete 15/15 release profile
  (357 backend, 105 PostgreSQL, and 32 frontend tests).
- Verification isolation: the real dispatcher exposed a fixture-only failure because live
  repository, state, process, and Hermes variables leaked into child acceptance tests. No model
  call or product change occurred. The dispatcher now scrubs those controls, and the affected
  activation regression explicitly binds its temporary repository.
- Owner action: none.
- Exact next action: verify and publish the bounded verification-isolation follow-up, then rerun
  candidate-wide verification and independent review and publish V1-020 if every gate passes.

<!-- AUTOMATION_STATUS_BEGIN -->
- Automation candidate state: V1-020 active; all seven bounded substages complete; final gates pending.
- Automation exact next action: Publish the verification-isolation follow-up, then verify, review, and publish V1-020.
<!-- AUTOMATION_STATUS_END -->
