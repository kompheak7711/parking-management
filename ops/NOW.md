# V1-047 Invoice, adjustment, late-payment, and billing-run API/UI — activation green, managed-worktree permission blocked

- Candidate: `V1-047` — Property-scoped invoice, adjustment, late-payment, and
  billing-run staff API/UI workflows with explicit confirmations; payments excluded.
- Authorization: Owner standing continuous authorization from V1-046 through
  V1-060; this release remains limited to the exact manager-accepted candidate
  and bounded manager operations metadata.
- Baseline: fully closed V1-046 reconciliation
  `57fd5d34f4e91102f4d49cc124d17d6022467ae4`.
- Reviewed implementation: exact candidate
  `47798abdbacf04df917eea6ee7f2b889eee7ac8c`, sole parent
  `0a55db2b445c776a2f91afee308cc0a13d8a93e7`, tree
  `b337076e239acd1b2c3c4711af908675bb6841fe`; four commits, 16 paths,
  +3251/-19, raw diff SHA-256
  `515b130833b37b94d9817f88bd7e259801306cb3a36b6f454b6efd871f4fb539`.
- Independent review: Workboard card
  `7ab561b7-7fee-483c-88ce-759273ceb9f6` is property-manager-accepted DONE as
  PASS with zero findings at exact `47798abd`; the reviewer made no edits.
- Release history: normal non-rewriting merge
  `62ef004ae25f1d9088f714e4acc571b8912c6bcc` preserved exact parents
  `47798abd` and `a945d125`. After the bounded frontend-environment recovery,
  clean ops-only successor `d6ca376c60cf8475406cc79006313350726896ed`
  was incorporated by ordinary release merge
  `48e377e60df41b93a8d5d06975ffe8d7b9272055`, parents `62ef004a` and
  `d6ca376c`, tree `070733bc997d017d43eb70ff9616b046e6ae78c2`.
  Both exact histories remain ancestors; no reviewed product commit was
  recreated, rebased, or rewritten.
- Local release verification at exact `48e377e6`: focused V1-046 18/18;
  backend 729 passed with 444 fully explained database-only skips; frontend
  234/234 across 17/17 files; fresh isolated PostgreSQL 467/467 with zero
  skips; adversarial replay/namespace 2/2; revision-36 upgrade 1/1; automation
  189/189. Format, lint, strict type, build/import, locked dependency,
  deployment, publication, security, secret, JSON, traceability, Alembic,
  diff, cleanup, and clean-state gates all passed. The reviewed 16-path product
  diff remains byte-identical at the accepted SHA-256.
- Implementation publication: `implementation/foundation` fast-forwarded
  normally and was pushed without force. GitHub Actions run `33469533522`
  passed all four jobs for exact release SHA `48e377e6`; local, tracking,
  fetched, live-remote, and retained release refs were equal after CI.
- Closure-metadata recovery: manager-owned correction
  `2eafb153-0693-42a6-8704-dc3bbaae9906` removed only the nonexistent
  `UI-INV-*` roadmap authority in exact commit
  `2bc9816db18aa71abf7e98ff7684351fa56ae898`, parent `48e377e6`.
  V1-047 retains 16 exact canonical API/test authorities; automation passed
  189/189 and GitHub Actions run `33470535203` passed all four jobs.
- Retention recovery: the control plane removed the clean release worktree and
  branch while the terminal attempt was reassigned for manager-only closure.
  Property-manager restored the same branch and managed path non-destructively
  at exact release `48e377e6`, verified it clean, and locked it for retained
  evidence; no unique commit or uncommitted work was lost.
- Closure publication: exact two-file closure
  `57f0a8168fa15df9c4c8bc1ba7ed7f6faab23319`, parent `2bc9816d`, was
  pushed normally; GitHub Actions run `33471210962` passed all four jobs.
- V1-046 terminal proof: reconciliation `57fd5d34`, parent `57f0a816`, passed
  exact-SHA GitHub Actions run `33471654604` with all four jobs green; local,
  tracking, fetched, and live-remote refs match. Release Workboard card
  `3266b3a3-e244-4926-ade8-6cc13eff775f` is property-manager-accepted DONE.
- V1-047 contract: Workboard `0df357b4-61a3-4697-af85-b6dcf2cf0305` is DONE.
  It freezes API-050..056, API-091, TEST-053..058, TEST-123..124, `api_ui`
  acceptance, exact allowed paths, payments exclusion, and financial,
  authorization, CSRF, transaction, concurrency, audit, traceability, build,
  secret, integration, and independent-review gates.
- Activation: exact commit `870472b7dffd28caf2c771e54196a0244c6c1a1e`,
  parent `57fd5d34`, tree `b8e8fa70`, passed automation 189/189 with zero
  failures/skips and exact-SHA GitHub Actions run `33472963195` with all four
  jobs green; local, tracking, fetched, and live-remote refs match.
- Blocker-state reconciliation: exact ops commit
  `11cabf9f8f1003d102573995965537807d2e610c`, parent `870472b7`, tree
  `fbe0bb95`, is clean and synchronized. Its initial CI attempt had one
  deterministic automation failure (188/189) while the other three jobs passed;
  focused local reproduction passed 1/1, and the one bounded failed-job rerun
  completed run `33473549663` with all four jobs green, including automation
  189/189. No product or implementation execution changed.
- Implementation: card `26b14ae0-92b3-433d-bed6-46bd732c569c` is BLOCKED
  before start. Two bounded supported Gateway dispatch paths, including the
  authenticated `gateway.remote.token`, both required `operator.admin` for the
  managed worktree. Zero worker, claim, attempt, branch, or worktree was created.
  Runtime remains GPT-5.6 Sol `xhigh`, Standard, Fast-off, with no fallback.
- Scheduler: enabled singleton `658ffdaf-1ac1-45a6-a842-f5f7d7a226eb` remains
  on its 30-minute interval with GPT-5.6 Sol `xhigh`, Standard/Fast-off. Its
  saved payload and `ops/OPENCLAW_SUPERVISOR_PROMPT.md` are byte-identical at
  11,868 bytes, SHA-256
  `0dfd18557308b22fa17135bf931a69910a196caa9f5c8e5386cf2d9d8bcffd56`.
- Production deployment, production data, credentials, paid services,
  customer data, force push, history rewrite, unrelated cleanup, and worktree
  deletion: none.
- Blocker: external OpenClaw permission — managed-worktree dispatch requires
  `operator.admin` and cannot be safely bypassed.
- Owner action required: yes. Grant `operator.admin` to the dispatching Gateway
  identity or invoke `/workboard dispatch` as the authenticated owner.
- Exact next action: after that permission action, unblock implementation
  `26b14ae0-92b3-433d-bed6-46bd732c569c` and start it exactly once from immutable
  activation `870472b7`; do not retry the unchanged permission failure.

<!-- AUTOMATION_STATUS_BEGIN -->

- Automation candidate state: V1-047 approved and active at exact green
  activation `870472b7`; implementation is blocked before start on operator scope.
- Automation exact next action: wait for `operator.admin` or authenticated-owner
  `/workboard dispatch`, then unblock and start the same card exactly once.

<!-- AUTOMATION_STATUS_END -->
