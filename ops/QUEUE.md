# Foundation queue

1. Phase 1F GitHub Actions CI foundation — completed and published.
2. Automation visibility and watchdog guardrails — completed and published.
3. Phase 2A provider-neutral authenticated actor boundary — completed and published.
4. Phase 2B provider-neutral capability authorization boundary — completed and published
   as `a931f0a`; local gates and GitHub Actions run `32002986112` passed.
5. Phase 2C Property-local business-date foundation — completed and published.
6. Phase 2C single-Property identity scope primitive — completed and published.
7. Authentication/account/session plan reconciliation to authoritative docs 003-010 and
   `DL-055` through `DL-059` — completed as a bounded read-only tranche.
8. Phase 2D local human-account persistence foundation — completed and published.
9. Phase 2D password-credential persistence foundation — completed and published at
   `d10c306`. The bounded `DB-AUTH-002`
   migration and focused real-PostgreSQL/traceability tests select no hashing library and
   add no credential mechanics, login/API/UI, or other excluded authentication scope.
10. Deployment-identity and secret-source design/local scaffolding for
   `SEC-045/047/049/050` — owner-authorized implementation is independently verified for
   publication. It includes no production value, provisioning operation, deployment, or
   remote-access operation; those remain outside this tranche.
11. Phase 2E password-hashing and verification service against `DB-AUTH-002` — independently
    verified and published as `bc567ea`; GitHub Actions run `32046660052` passed.
    A compact-state completion-status enforcement repair is included with deterministic coverage.
12. Phase 2F Local Login Security Foundation — approved and ready under the durable
    authorization below. Bound the tranche to normalized username lookup, Phase 2E password
    verification, disabled-account rejection, enumeration-resistant outcomes, account/source
    rate-limiting enforcement, secret-free audit evidence, focused tests, and traceability.
    Exclude public login/API/UI, sessions/cookies, MFA, recovery, bootstrap, production
    credentials/deployment/remote access, canonical changes, and policy invention.
13. Phase 2G MFA Policy Enforcement Foundation — approved and ready under the durable
    authorization below. Bound the tranche to provider-neutral enforcement of the approved
    Owner/Manager-required and Staff-optional MFA policy, enrollment/challenge state boundaries,
    focused policy-matrix tests, and traceability. Exclude MFA mechanism/library selection,
    persistence/migrations, API/UI, sessions, recovery/bootstrap, production operations,
    canonical changes, and role/capability-policy invention.
14. Phase 2H provider-neutral Browser Session Lifetime Foundation — implementation is complete
    and published as `5bf88d1`. The
    bounded tranche contains fixed inactivity/absolute lifetime enforcement, injected time,
    activity and revocation handling, secret-free evidence, focused tests, and traceability only.
15. Phase 2I provider-neutral Administrative Recovery Authorization Foundation — approved and
    ready under the durable authorization below. Bound the tranche to the explicit recovery
    authorization matrix, provider-neutral allow/deny decisions, bounded secret-free audit
    evidence, focused deterministic tests, and traceability. Exclude recovery-code generation or
    storage, credential/MFA mutation, session revocation mechanics, persistence/migrations,
    API/UI, emergency/bootstrap procedures, production operations, canonical changes, and policy
    invention.

The owner has standing continuous authorization for the current live V1-046 stage
through V1-060. Each successor activates automatically only after its predecessor is
fully released, published, verified, reconciled, and closed. Routine transitions need
no additional authorization. Unresolved policy, production deployment or credentials,
paid services, customer data, destructive operations, and exhausted bounded recovery
still require owner review.

The executable finite queue is now `ops/V1_ROADMAP.json`. It contains 60 stable tranches,
explicit dependencies, canonical authorities, scope boundaries, risk classes, acceptance
profiles, authorization status, and deterministic order. This legacy narrative queue remains
historical context only and must not be used to invent successors.

Current live queue position: V1-047 fresh independent max review `67d4ab70` is
manager-accepted DONE as FAIL with 4 HIGH, 1 MEDIUM, 0 LOW at immutable
`a3a1cff`; bounded correction `b1614ef8` is RUNNING exactly once on
`property-codex-1` before fresh cumulative integration and fresh independent
review.
V1-046 release `48e377e6`, closure `57f0a816`, and reconciliation `57fd5d34`
are published, exact-SHA CI-green, synchronized, and Workboard-accepted DONE.
V1-047 contract `0df357b4-61a3-4697-af85-b6dcf2cf0305` is frozen and DONE;
activation `870472b7` is published, synchronized, and exact-SHA CI-green in run
`33472963195`. Implementation `26b14ae0-92b3-433d-bed6-46bd732c569c` remains
BLOCKED before start with zero starts. Coordination correction, fresh integration,
and accepted zero-finding independent review remain hard dependencies. A fresh independent
exact-SHA rereview of the uninstalled coordination
candidate `ece9afd` then failed with 3 HIGH findings, including two surviving
material classes and one missing bootstrap for this exact pre-existing card. The
owner explicitly cleared that exhausted-recovery stop for one materially different
H1-H3 correction. Correction `d2d1f66e-de97-4f26-93fc-9806feae82ea` is now
property-manager-accepted DONE at exact `85a3439`, parent `ece9afd`; its complete
four-path +1621/-26 diff and fresh manager integration card `c54f4a90` passed
coordination 80/80 and automation 189/189 with zero failures/skips. Fresh read-only
independent review `84c1950f-0dfc-4400-9c4b-a6dab427b4c3` is manager-accepted
DONE for review work with a FAIL verdict of 1 HIGH, 1 MEDIUM, 0 LOW. Bounded
correction `555bf742-61a0-47fd-b508-8ed2db72cce3` concluded at exact `8b1046be`;
coordination 83/83 and automation 189/189 passed, but manager verification
rejected it with 1 HIGH, 0 MEDIUM, 0 LOW after a direct blocked-owner probe
returned `BLOCKED_OWNER_ACCEPTED`. Narrow changed-fingerprint correction
`dd728972-8d05-4e0f-bbfd-9626adae9527` is property-manager-accepted DONE at
exact `85e18b8`, parent `8b1046be`, after worker and manager coordination 84/84
and automation 189/189 passed with zero failures/skips and manager inspection
found 0 HIGH, 0 MEDIUM, 0 LOW. Fresh cumulative read-only integration
`a440be0b-71ba-4522-82c4-af6a24d0fd96` is property-manager-accepted DONE at
immutable `85e18b8`; worker and manager coordination 84/84 and automation
189/189 passed with zero failures/skips. Fresh independent max review
`79120fbe-cd09-4bf1-baed-cac17b40ba48` is property-manager-accepted DONE at
immutable `85e18b8` with FAIL verdict 2 HIGH, 0 MEDIUM, 0 LOW. Manager reproduced
the unbound dispatcher cwd and exact `UNSAFE_ACCEPT pass failed blocked` late-state
path, reran coordination 84/84 and automation 189/189 with zero failures/skips,
and kept the candidate uninstalled and unpublished. Bounded changed-fingerprint
correction `0167afb8-24e8-4391-b4d0-9ec4896cdf37` is property-manager-accepted
DONE at exact `3a912c3`, parent `85e18b8`; worker and manager focused 2/2,
coordination 86/86, and automation 189/189 passed with zero failures/skips and
0 HIGH, 0 MEDIUM, 0 LOW findings. Fresh cumulative read-only integration
`c108b139-47b3-4481-b233-583eea7c3b72` is property-manager-accepted DONE at
exact `3a912c3`; worker and manager focused 11/11, coordination 86/86, and
automation coordination 86/86 plus routing/evidence 189/189 passed with zero
failures/skips and zero findings. Fresh independent max review
`28daaec5-167b-4fb2-b606-11a7f54b0a86` is property-manager-accepted DONE at
immutable `3a912c3` with FAIL verdict 5 HIGH, 0 MEDIUM, 0 LOW. Reviewer and
manager each passed coordination 86/86 and routing/evidence 189/189 with zero
failures/skips, but independently confirmed five secret-handling, runtime-replay,
logical-duplicate, worktree-drift, and late-failure-consumption defects. Exact
bounded correction `c3536723-13f6-446a-a973-8a67963c51d4` was created once at
base `3a912c3` for GPT-5.6 Sol `xhigh`, Standard/Fast-off, with four allowed
paths. Its first supported Gateway start failed before claim, attempt, worker,
branch, or worktree creation on missing `operator.admin`. The supported RPC now
succeeds: the exact preserved card was moved BLOCKED -> TODO -> READY and
dispatched once with zero start failures. It concluded on `property-codex-1`
as attempt `workboard:c3536723-13f6-446a-a973-8a67963c51d4:1788291263209`
in clean managed branch/worktree
`openclaw/wb-c3536723-13f6-446a-a973-8a67963c51d4` /
`wb-c3536723-13f6-446a-a973-8a67963c51d4` at exact `587768eb`, parent
`3a912c3`, tree `814cdcee`, as a clean four-path +895/-71 diff with binary
SHA-256 `f229ff0a`. Worker and manager coordination 91/91 and automation 189/189
passed with zero failures/skips; manager auxiliary adversarial probes passed
13/13 and found 0 HIGH, 0 MEDIUM, 0 LOW. Card `c3536723` is manager-accepted
DONE. Fresh integration card `82257d37-d17b-42f3-8909-b855dfac5eac` was
created once with stable key `v1-047-ops-cumulative-integration-587768e-v1`.
Its first start failed before any claim/attempt/worker/worktree because the
local route lacked `operator.admin`; a materially different configured-token
route also mismatched the running Gateway. The supported token-free operator
route then recovered, and the exact preserved card moved BLOCKED -> TODO ->
READY and started exactly once with zero start failures on `property-codex-3`
as attempt `workboard:82257d37-d17b-42f3-8909-b855dfac5eac:1788296690469`
in clean managed branch/worktree
`openclaw/wb-82257d37-d17b-42f3-8909-b855dfac5eac` /
`wb-82257d37-d17b-42f3-8909-b855dfac5eac` at exact `587768eb`, parent
`3a912c3`, tree `814cdcee`. Worker and manager independently passed focused 5/5,
coordination 91/91, automation 189/189, and every exact scope/integrity gate
with zero candidate failures/skips and 0 HIGH, 0 MEDIUM, 0 LOW; complete
five-commit/four-path diff is +3440/-84 with binary SHA-256 `fe60b379`. The
worker released to REVIEW and property-manager accepted card `82257d37` DONE
after reconciling only its stale execution presentation. Fresh independent max
review `94f964ff-8a8a-4f54-a018-aa0d76aaa2b7` is property-manager-accepted DONE
at immutable `587768eb` with FAIL verdict 3 HIGH, 0 MEDIUM, 0 LOW after reviewer
and manager coordination 91/91 and automation 189/189 passed with zero failures/
skips. Manager independently reproduced all three fail-closed bypasses. One
bounded correction `dafb7f51-a40a-4a3d-a459-79ead8040e3f` was created with
stable key `v1-047-ops-correction-three-high-587768e-v1`. Its first Gateway
start failed before worker/session/worktree creation because the ledger lacked
an absolute source checkout; the same card was rebound to the exact clean review
worktree and started once with zero start failures on `property-codex-1` as
attempt `workboard:dafb7f51-a40a-4a3d-a459-79ead8040e3f:1788300750975`. Its
managed branch/worktree concluded clean at exact `a3a1cff`, parent `587768eb`,
tree `7a83808c`, as one zero-merge four-path +592/-187 commit with binary SHA-256
`59c300f5`. Worker and manager focused 3/3, coordination 93/93, automation
189/189, and every integrity gate passed with zero failures/skips and zero
findings; card `dafb7f51` is manager-accepted DONE. Fresh cumulative integration
`8ccec368-0586-42a9-8cc9-98da32d4b0ed` was created once with stable key
`v1-047-ops-cumulative-integration-a3a1cff-v1` and started exactly once with
zero start failures on `property-codex-3` as attempt
`workboard:8ccec368-0586-42a9-8cc9-98da32d4b0ed:1788304194732` in managed
branch/worktree `openclaw/wb-8ccec368-0586-42a9-8cc9-98da32d4b0ed` /
`wb-8ccec368-0586-42a9-8cc9-98da32d4b0ed` at immutable `a3a1cff`. Worker and
manager each passed focused 7/7, coordination 93/93, automation 189/189, and all
integrity gates with zero failures/skips/findings; card `8ccec368` is manager-
accepted DONE. Fresh independent max review
`67d4ab70-d53c-4bd3-b7db-32ae3aa8a4c3` was created once with stable key
`v1-047-ops-independent-review-a3a1cff-v1` and started exactly once with zero
start failures on `property-codex-2` as attempt
`workboard:67d4ab70-d53c-4bd3-b7db-32ae3aa8a4c3:1788305930790` in managed
branch/worktree `openclaw/wb-67d4ab70-d53c-4bd3-b7db-32ae3aa8a4c3` /
`wb-67d4ab70-d53c-4bd3-b7db-32ae3aa8a4c3` at immutable `a3a1cff`. Reviewer and
manager gates passed focused 7/7, coordination 93/93, and automation 189/189;
property-manager accepted the review DONE as FAIL with 4 HIGH, 1 MEDIUM, 0 LOW
after reproducing every material class and correcting the live Gateway schema
description. Bounded correction `b1614ef8-368e-4fd9-bfe6-01604711e930` was
created once with stable key
`v1-047-ops-correction-a3a1cff-runtime-late-failure-v1` and started exactly once
with zero start failures on `property-codex-1` as attempt
`workboard:b1614ef8-368e-4fd9-bfe6-01604711e930:1788309806773` in clean managed
branch/worktree `openclaw/wb-b1614ef8-368e-4fd9-bfe6-01604711e930` /
`wb-b1614ef8-368e-4fd9-bfe6-01604711e930` at exact base `a3a1cff`. It concluded
at exact `86c61f3`, parent `a3a1cff`, tree `cfb19a32`, as one clean four-path
+755/-57 commit with binary diff SHA-256 `51b613a1`. Worker and manager focused
5/5, coordination 97/97, automation 189/189, and all auxiliary gates passed
with zero failures/skips/findings; property-manager stopped only the stale
execution presentation and accepted `b1614ef8` DONE. Fresh cumulative
integration `71288e13-5065-4ee8-8fda-1cd1693df39c` was created once with stable
key `v1-047-ops-cumulative-integration-86c61f3-v1`. One generic CLI pre-start
failed on missing `operator.admin` without creating a claim, attempt, worker,
branch, or worktree; the supported `workboard.cards.dispatch` Gateway operator
RPC then started exactly one `property-codex-3` attempt with zero failures:
`workboard:71288e13-5065-4ee8-8fda-1cd1693df39c:1788313446435`. Its clean
managed branch/worktree are `openclaw/wb-71288e13-5065-4ee8-8fda-1cd1693df39c`
/ `wb-71288e13-5065-4ee8-8fda-1cd1693df39c` at immutable `86c61f3`.
Preserve and inspect this healthy GPT-5.6 Sol `xhigh`, Standard/Fast-off
integration. Do not install, bootstrap the live card, publish, or dispatch
implementation `26b14ae0` before manager acceptance and a fresh zero-finding
independent max review.
The owner-decision reconciliation is published at exact `0ce6ac9`, parent
`1c523409`; local automation passed 189/189, exact-SHA CI run `33512759067`
passed all four jobs, and local/tracking/fetched/live-remote refs match.
V1-048 remains dependency-held.

The latest exact ops-state publication `4854408`, parent `05a70f5`, is pushed,
remote-synchronized, and exact-SHA CI-green in run `33545659366` with all four
jobs passed; local automation passed 189/189 with zero failures/skips.
