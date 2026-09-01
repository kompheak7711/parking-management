# V1-047 Invoice, adjustment, late-payment, and billing-run API/UI — coordination correction under fresh review

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
- Coordination safety rereview: fresh independent read-only card
  `9d1990ed-d3d5-4b0a-ba90-406372df359c` reviewed exact uninstalled candidate
  `ece9afdaf1c4d5bd79b44b0826a4b14a8637f13e`, parent `3fc58af902c0b58bfe88d45316e11994436063d0`,
  after coordination 75/75 and automation 189/189 passed with zero skips. The
  review nevertheless failed with 3 HIGH, 0 MEDIUM, 0 LOW runtime findings:
  unsupported terminal-state expectations, a quoted sensitive-key persistence
  bypass, and no supported idempotent bootstrap for the exact pre-existing
  V1-047 card. The first two material classes survived the prior correction, so
  the bounded-recovery human-stop threshold is reached. The candidate remains
  uninstalled; no scheduler mutation, publication, or V1 dispatch occurred.
- Owner-authorized correction: Workboard
  `d2d1f66e-de97-4f26-93fc-9806feae82ea` is property-manager-accepted DONE at
  exact candidate `85a3439459286103ce2710b20f767f49fa9a5a00`, sole parent
  `ece9afdaf1c4d5bd79b44b0826a4b14a8637f13e`, tree `21195130984c3be4a0378e64f50512f550139cd9`.
  The complete correction is exactly four authorized paths, +1621/-26, raw
  diff SHA-256 `765f43a1ac8ae715cd7c618ab90f9da01df92fa6e785b0a5e1e85885881106f8`.
  Fresh manager verification and integration card
  `c54f4a90-88d2-4d2b-92db-c66b49298d8a` passed coordination 80/80 and
  automation 189/189 with zero failures/skips, plus roadmap, JSON, Python,
  manifest, traceability, scope, ancestry, secret, diff, and clean-state gates.
- Fresh independent review: card `84c1950f-0dfc-4400-9c4b-a6dab427b4c3`
  is running exactly once on `property-codex-2` at the immutable candidate.
  Attempt `workboard:84c1950f-0dfc-4400-9c4b-a6dab427b4c3:1788273631793`
  has a healthy claim and heartbeat. The reviewer is GPT-5.6 Sol `max`,
  Standard/Fast-off, read-only, and bound to the complete exact diff. The
  correction remains uninstalled and unpublished; live V1-047 bootstrap and
  implementation dispatch have not occurred.
- Owner-decision reconciliation: exact ops-only commit
  `0ce6ac9030174e8039c7367ed26737f676be957b`, parent `1c523409`, tree
  `b4b43b89`, changed only `ops/NOW.md`, `ops/QUEUE.md`, and `ops/STATE.json`.
  Local automation passed 189/189 with zero failures/skips; GitHub Actions run
  `33512759067` passed all four jobs. Backend passed 729 with 444 explained
  database-only skips, PostgreSQL passed 467/467 with zero skips, frontend
  passed 234/234 across 17/17 files, automation passed 189/189, and dependency
  audits found zero vulnerabilities. Local, tracking, fetched, and live-remote
  refs match exactly.
- Scheduler: enabled singleton `658ffdaf-1ac1-45a6-a842-f5f7d7a226eb` remains
  on its 30-minute interval with GPT-5.6 Sol `xhigh`, Standard/Fast-off. Its
  saved payload and `ops/OPENCLAW_SUPERVISOR_PROMPT.md` are byte-identical at
  11,868 bytes, SHA-256
  `0dfd18557308b22fa17135bf931a69910a196caa9f5c8e5386cf2d9d8bcffd56`.
- Production deployment, production data, credentials, paid services,
  customer data, force push, history rewrite, unrelated cleanup, and worktree
  deletion: none.
- Blocker: none for the active independent review. V1-047 implementation
  remains BLOCKED with zero starts; no install, live bootstrap, or implementation
  dispatch is permitted before a zero-finding review and release acceptance.
- Owner action required: no.
- Exact next action: preserve and inspect independent review
  `84c1950f-0dfc-4400-9c4b-a6dab427b4c3` through REVIEW. Property-manager then
  accepts a zero-finding exact-SHA verdict or creates one bounded correction for
  material findings. Do not install, publish, bootstrap the live V1-047 card, or
  dispatch implementation `26b14ae0` yet.

<!-- AUTOMATION_STATUS_BEGIN -->

- Automation candidate state: V1-047 approved and active at exact green
  activation `870472b7`; correction `85a3439` and fresh integration are
  manager-accepted DONE, and one independent max review is running while
  implementation remains blocked and unstarted.
- Automation exact next action: inspect the healthy independent review through
  REVIEW, then manager-accept only an exact zero-finding verdict.

<!-- AUTOMATION_STATUS_END -->
