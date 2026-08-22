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
- Review contract follow-up: Hermes session `6436d586904295897c2a55d15490f2c2` used 37,061
  tokens in one zero-tool call and identified that untracked files are absent from a Git diff, but
  returned its finding as a string instead of the required object. The strict parser correctly
  rejected the verdict. Review now fails closed before sending any untracked candidate content,
  publishes the exact finding-object schema, and treats invalid delivery as bounded recoverable
  routing rather than immediate Owner work. All 130 automation tests and all 15 release gates pass.
- Review transport and findings: Hermes session `161b6941ab6d1df2f595c95147060189` used
  37,921 tokens in one zero-tool call and saved a valid exact verdict, but the wrapper returned an
  empty command response. The preserved verdict identified two non-probative browser-session
  tests. They are replaced by production authentication/administration authorization checks and
  exact capability, Property, object, and SEC-070 boundary checks. The dispatcher now recovers
  only a completed final assistant message from the exact regular non-symlinked session database
  and revalidates it through the unchanged strict review contract; it never makes a replacement
  model call for transport loss.
- Fresh review: session `2cc185b461d1e12be101193344bb7994` proved the repaired transport
  path by recovering and validating one 43,974-token zero-tool verdict without a replacement
  model call. It found two further hardening gaps. Recovery now requires the globally newest
  active session message itself to be the completed assistant verdict, and candidate-diff
  materialization disables both external diff helpers and text conversion. Focused regressions
  cover the incomplete-session, external-diff, and text-conversion boundaries. Concrete in-scope
  review and test findings now remain automatic repair work; Owner action is reserved for the
  protected decision categories or actual bounded-repair exhaustion.
- Second fresh review: session `a8359284d26732844114341dd015d30e` used 48,764 tokens in one
  zero-tool call and found one remaining recovery boundary: canonicalizing a symlinked Hermes
  session root and reopening `state.db` left ancestor-symlink and replacement races. Recovery now
  walks only non-symlinked session-root components, reads regular database and WAL evidence through
  bound descriptors with stable identity checks, and queries a private snapshot. Focused
  regressions cover both the ancestor symlink and database replacement race.
- Owner action: none.
- Exact next action: run the complete release profile, publish the stable-session-snapshot hardening, then
  repeat candidate-wide independent review and publish V1-020 if every gate passes.

<!-- AUTOMATION_STATUS_BEGIN -->
- Automation candidate state: V1-020 active; all seven bounded substages complete; final gates pending.
- Automation exact next action: Verify and publish the stable-session-snapshot hardening, then review and publish V1-020.
<!-- AUTOMATION_STATUS_END -->
