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
  walks only non-symlinked session-root components and binds one coherent SQLite read transaction
  to regular database, WAL, and session-path identities. Focused regressions cover ancestor
  symlinks, database replacement, and concurrent WAL checkpoint races.
- Final fresh review: session `278528a25dd788fa99ce6981e15478d1` used 48,421 tokens in one
  zero-tool call and passed with no findings. The reviewed candidate is already clean, pushed, and
  CI-green across cumulative bounded commits, so publication now accepts that state only when the
  exact candidate base-to-HEAD paths, reviewed fingerprint, synchronized SHAs, publication guard,
  and exact-HEAD CI all agree. It never fabricates an empty product commit.
- Final review materialization checkpoint: the exact cumulative diff is 126,152 bytes, 6,152
  bytes above the former 120,000-byte packet cap. No model call or recovery attempt was consumed.
  The bounded complete-diff cap is now 160,000 bytes; the separate 90,000-token complex-review
  reservation and normal 60,000-token ceiling are unchanged.
- Complete-diff review: session `445cf26755eecec282bfe266bd268949` used 56,004 tokens in one
  zero-tool call and found two final review-boundary gaps. Independent review now explicitly
  rejects any stored scope that differs from the exact base-to-HEAD Git path set. Recovered Hermes
  output now uses a coherent SQLite transaction and fails closed if database, WAL, or session-path
  identity changes during the read.
- Exact-snapshot review: session `c9f1cca3f0401e4b84e623dc6f5568f7` used 51,164 tokens in one
  zero-tool call and found one remaining swap-and-restore race: recovery validated an open database
  descriptor but reopened the database by pathname. Recovery now copies the database and WAL only
  through the already-validated descriptors into a private snapshot before SQLite reads it, then
  revalidates every source identity. The exact swap-and-restore regression proves a substituted
  pathname cannot supply the recovered verdict; all 140 automation tests and all 15 complete gates
  pass after the repair.
- Full-window review: session `e0abcf5f8f0ba841a2a11ce3fa14f6bb` used 54,674 tokens in one
  zero-tool call and found that a checkpoint could still occur between the database and WAL copies.
  Recovery now captures both source identities before either copy and revalidates both after all
  copying and again after the private SQLite read. A production-shaped checkpoint in that exact
  inter-snapshot gap now fails closed; all 141 automation tests pass.
- Fresh review: session `21c9d1be4ce3ba727bc227470a2c5ae5` used 59,856 tokens in one
  zero-tool call and passed with no findings. The reviewed snapshot was published as `3ba5e2d` and
  exact-commit GitHub Actions run `32602660541` passed. Post-publication reconciliation then exposed
  one lifecycle-only defect: its mutator still depended on an older compact preflight label even
  though the dispatcher held stronger exact-commit review and CI evidence. Dispatcher-bound
  reconciliation now requires the exact 40-character synchronized base commit and pending
  publication state, while retaining the older standalone gate. A production-shaped regression
  covers the actual active-state publication path.
- Lifecycle-repair review: session `35635c009a609b8e94a4ee4feed93bb5` used 59,429 tokens in one
  zero-tool call. Its verdict was rejected because a 65-character test-symbol location exceeded
  the former 40-character field bound, but safe recovery exposed one concrete medium finding: the
  checkpoint regression fired before, rather than between, the database and WAL snapshots. The
  regression now injects the checkpoint only after the completed database copy. Review locations
  remain bounded but accept up to 200 characters so useful symbol names are no longer discarded.
- Literal-path review: session `cd20b8a9558b03bfe1c7ddd1fae95aa0` used 60,099 tokens in one
  zero-tool call and found that candidate filenames were passed to Git after `--` but without
  disabling pathspec magic. Both untracked detection and exact diff materialization now set
  `GIT_LITERAL_PATHSPECS=1`. Separate tracked and untracked regressions prove a filename such as
  `:(exclude)*` is handled as one literal candidate path and cannot hide review bytes.
- Review materialization checkpoint: the exact 19-path cumulative diff is 164,229 bytes, 4,229
  bytes above the prior 160,000-byte transport cap. No model call or attempt was consumed. The
  complete-diff byte cap is now 180,000; the ordinary 60,000-token ceiling and separate 90,000-token
  complex-review reservation are unchanged.
- Lossless-transport review: session `e96e6f2e5771ddd7f886023689354907` used 62,037 tokens in one
  zero-tool call and found two materialization gaps. Review diffs now stream at most 180,001 bytes
  from Git, kill and fail closed immediately above the 180,000-byte cap, and require strict UTF-8
  instead of replacing distinct source bytes with the same character. Focused non-UTF-8 and
  oversized-diff regressions prove both failures occur before any model call.
- Private-snapshot review: session `db3ab5c7650583fd384bdee1d29ecb3f` used 72,723 tokens in one
  zero-tool call and found two strict-boundary gaps. Recovery now retains and revalidates private
  snapshot directory, database, and WAL descriptors inside the active read transaction before
  legitimate close-time WAL cleanup. A private-path swap regression fails closed, while the exact
  completed live WAL-backed review still recovers successfully. Review `line` values are no longer
  coerced: missing, null, numeric, boolean, array, and object locations all fail the declared string
  contract.
- Final materialization checkpoint: the added private-snapshot evidence brings the exact cumulative
  diff to 180,483 bytes, 483 bytes above the 180,000-byte cap. No model call was made. The bounded
  diff transport cap is now 220,000 bytes; the ordinary 60,000-token ceiling and separate
  90,000-token review ceiling remain unchanged and the proactive reservation guard still decides
  whether a provider request is safe.
- Closed-WAL review: session `8e323f42104fc6a70e9d19815437d9eb` used 72,884 tokens in one
  zero-tool call and found the missing normal case where a WAL-mode database has no live sidecars.
  The private snapshot now always precreates WAL and SHM entries and opens SQLite in read-only mode,
  retaining the existing identity checks inside the transaction. Focused regressions now cover
  DELETE mode, live WAL, checkpoint races, private-path swaps, and closed WAL with no sidecars.
- Private-SHM review: session `79386215cbfd15abe4659d2831268a48` used 65,302 tokens in one
  zero-tool call and found that the precreated private SHM pathname lacked its own retained identity.
  Recovery now holds the SHM descriptor and revalidates its inode, type, link count, and pathname
  inside the active transaction. A pre-connect SHM symlink-substitution regression fails closed,
  while clean-WAL and exact live-WAL recovery remain successful.
- Exceptional-review checkpoint: the 199,770-byte exact diff was safely stopped before any model
  call because its predicted request did not fit beneath 90,000 tokens. The already-approved
  exceptional-review policy now deterministically selects 120,000 tokens only when the complete
  diff exceeds 180,000 bytes, persists the exact classification/fingerprint/scope in the manifest,
  and leaves implementation at 60,000 and ordinary complex reviews at 90,000.
- Final exceptional review: session `48c4cad06b0a32829c89b162ccc64e49` used 75,376 tokens in one
  zero-tool call and passed all 19 paths with no findings. Commit `d8ca9e4` was published, but exact
  GitHub Actions run `32606766929` failed only because a test temporary bare repository was still
  creating `objects/pack` during cleanup; PostgreSQL, frontend, dependency security, backend tests,
  and every preceding routing test passed. Test repositories now disable Git auto-GC and background
  maintenance through process-scoped configuration, with a deterministic fixture regression.
- Owner action: none.
- Exact next action: verify, review, and publish the bounded reconciliation lifecycle repair, then
  reconcile V1-020 complete from its exact successful publication commit.

<!-- AUTOMATION_STATUS_BEGIN -->
- Automation candidate state: V1-021 independent-review findings are repaired. Read/write key normalization now matches, classified camelCase facts round-trip, unknown-field secrets fail closed, and audit rows never establish resource ownership. Review bounds are unchanged; fresh gates remain pending.
- Automation exact next action: Rerun complete deterministic verification and a fresh independent review, then publish and reconcile V1-021 only on PASS.
<!-- AUTOMATION_STATUS_END -->
