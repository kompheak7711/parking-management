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

Current live queue position: V1-049 implementation is frozen for fresh exact-SHA verification and independent Astra max review under ops/V1_049_SCOPE.md. Resolve codex/v1-049-direct, inspect any active reviewer, and finish all gates before normal publication, exact-SHA CI, ref equality, Workboard and durable closure. V1-048 is fully closed at e3ae74f with product561dd06, exactCI33959763928/33960592925, card652e776c DONE and receipt7e3dc8d7. Development checks are not V1-049 release acceptance. Preserve all failed checkpoints/worktrees; do not repeat implementation or activateV1-050 before closure.
The owner now authorizes direct continuous Codex execution through V1-053, with
GPT-6 Astra settings in ops/CODEX_TAKEOVER_V1_048_053.md. Stop before V1-054.
OpenClaw stays disabled; current tracking card62275bf0-2739-448c-ae59-50794190ee72
is blocked only to prevent OpenClaw admission; no claim/attempt/execution. V1-048 card652e776c is done. The V1-047 notes below are history.
V1-046 release `48e377e6`, closure `57f0a816`, and reconciliation `57fd5d34`
are published, exact-SHA CI-green, synchronized, and Workboard-accepted DONE.
V1-047 contract `0df357b4-61a3-4697-af85-b6dcf2cf0305` is frozen and DONE.
Implementation `26b14ae0-92b3-433d-bed6-46bd732c569c` is terminal DONE,
retains all product evidence, and has no active claim, attempt, or worker.
The owner authorized direct native Codex implementation and removed only the
rejected OpenClaw coordination-repair dependency. Do not dispatch an OpenClaw worker.
Use the accepted activation `870472b7` in `codex/v1-047-direct-product`.
Exact product `e7a82f7`, release `32fbef1`, and corrected closure chain through
`34922d6` are independently approved, normally published, exact-SHA CI-green,
and remotely synchronized. Final four-file reconciliation and terminal Workboard
acceptance are complete at exact final reconciliation `b022d83`; Workboard card
`26b14ae0` is terminal DONE. OpenClaw stays disabled. V1-048 is authorized and
dependency-ready but was not activated or dispatched in this closure turn.

### V1-047 operational implementation notes

- The owner's explicit native takeover and removal of only the OpenClaw repair
  prerequisite are recorded above and in STATE.direct_codex_product. The canonical
  decision log remains unchanged because the frozen publication scope excludes
  canonical-document edits. No business or financial policy is changed.
- API-050 invoice list adds meta.billing_capabilities for exact-Property action
  visibility only. Existing command authorization, scope and CSRF remain authoritative.
- Financial requests are sealed in actor-bound browser IndexedDB with a non-extractable
  AES-GCM key before transmission. Atomic reservation prevents competing new commands;
  explicit replay uses the original request and idempotency key after reload. No
  token or plaintext customer/financial intent is persisted. Unknown outcomes remain
  blocked until an exact successful replay; recovery storage failure fails closed.
- UI-051 consequence previews use bounded integer cents and are explicitly estimates;
  no derived amount or status is submitted. Backend transactions remain authoritative.
- One remote-SHA comparison test now mocks its own authorized branch, rather than
  inheriting the operator's worktree branch. No OpenClaw runtime repair is included.

### V1-047 independent-review correction — active

Review195f3a8 failed with 1 HIGH, 7 MEDIUM and 2 LOW findings. The prior
implementation and integration evidence remain historical, not release approval.
One native Sol xhigh Standard worker in codex/v1-047-review-correction addresses
actor-bound transmission, verified terminal rejection recovery, original run
identity replay, draft void, separated visibility capabilities, optional list
metadata, lossless response money, charge consequence previews, keyboard focus,
and bounded accessible validation/correlation feedback. No financial policy or
canonical specification change is authorized. Coordinator owns continuity and
Workboard. Preserve all prior artifacts. Require a new bounded commit, fresh
exact-SHA integration and fresh independent Sol max Standard review before any
reviewed release/publication, exact-SHA CI, reconciliation or closure.

Correction170407f is frozen with fresh737 backend/335 frontend/467 PostgreSQL/189
automation gates passed, plus static/build/config/traceability/backend audits.
Official frontend audit recovered on immutable170407f in the10:36 cycle: exit0,
zero vulnerabilities. One fresh independent cumulative Sol max Standard review
is running; inspect it without duplicate dispatch. No publication or closure yet.
Runtime decisions: X-Billing-Actor-ID binds opted-in billing commands at the
authenticated boundary; legacy callers retain their existing contract. Scoped
billing-capabilities GET provides visibility without invoice-read coupling.
Its exact API inventory expectation is maintained, not weakened. No canonical
policy changes. Browser-discovered focus restoration and its regression are fixed;
all intermediate commits/evidence remain preserved. No publication or closure yet.

### Current superseding checkpoint — e3e605b

The170407f independent review finished FAIL with1MEDIUM terminal decision conflict
and1LOW operation feedback issue. b69c602 corrects both; e3e605b fixes one new test
fixture type. Current clean exact e3e605b gates PASS737backend/351frontend/467real
PostgreSQL/189automation, static/build/config/traceability/backend audits and real
browser encrypted recovery/focus. Official npm audit timed out; fresh verdict is
pending. No workers running. Next: one bounded audit retry per later wake, then
fresh independent Sol max Standard cumulative review and all release gates.
No publication/closure yet; preserve every earlier artifact; OpenClaw disabled.

11:50 wake supersedes audit-pending status: official npm audit PASS, zero
vulnerabilities. One fresh independent cumulative Sol max Standard reviewer
01a06c44-cd4b-7791-904e-e9a52dd345ac is running on clean e3e605b. Inspect existing
review; no duplicate or repeated audit. Publication and closure remain held.

### Current superseding checkpoint — acd7f74

Third bounded product correction complete locally: terminal charge-conflict recovery
and capability-read feedback/retry. Exact gates PASS737backend/365frontend/467DB/189
automation plus static/build/config/traceability/backend audits and real browser.
Fresh npm audit rejected before execution by automatic approval. Owner must explicitly
authorize public dependency name/version metadata to official npm advisory endpoint.
Native follow-up PAUSED;no worker;OpenClaw disabled;V1-048 held. After permission,
normal audit and fresh exact-SHA independent review, reviewed publication/CI/closure.


### Current superseding checkpoint — owner permission resolved, acd7f74 review running

Owner explicitly authorized dependency names/versions to official npm registry for required V1-047 audits. Normal exact acd7f74 audit PASS exit0 zero vulnerabilities; all required integration gates passed. Existing native10-minute follow-up ACTIVE. Sole fresh independent cumulative Sol max Standard read-only reviewer01a06cb3-f351-7133-b188-efd4fe1b1413 (exec52928) is running. Inspect it, never duplicate or repeat completed gates. Require zero actionable findings then separately reviewed integration/release/closure, normal publication, exact-SHA CI and ref equality, Workboard/durable reconciliation. No owner action required;OpenClaw disabled;V1-048 held;all histories/evidence preserved. Earlier permission-pending and old-review-running paragraphs are historical, superseded by this checkpoint.


### Current superseding checkpoint — fourth bounded correction

acd7f74 independent cumulative review finished FAIL1MEDIUM pre-receipt conflict ambiguity and1LOW run-retry feedback reset. These are new scenarios, not the same finding surviving3attempts. One Sol xhigh Standard worker01a06cd1-824c-7233-867a-a8cc56f60624/exec92446 is correcting only those cases in the existing correction worktree. Inspect it without duplicate dispatch;then verify new commit, fresh full exact-SHA integration and independent max review. All prior evidence remains;no release until zero findings and subsequent publication/CI/ref/Workboard closure gates. Native10minute follow-up active;OpenClaw disabled;V1-048 held;no owner action.


### Current superseding checkpoint — e7a82f7 independent review

Fourth correction complete;396be6a plus test/traceability-only030d91b/e7a82f7 preserve every earlier candidate. All exact e7a82f7 integration gates PASS769backend/369frontend/469realPostgreSQL zero skips/189automation/static/build/config/traceability/audits/realbrowser. One fresh independent cumulative23path Sol max Standard read-only reviewer01a06ce7-eb89-7603-b1e8-2e974fa65532,exec76718 is active. Inspect it without duplication;zero findings then separately reviewed integration/release/closure,normal push,exact-SHA CI/ref/Workboard closure. Native10minute follow-up active;OpenClaw disabled;V1-048 held;no owner action. Earlier worker-running paragraphs are historical.


### Current release preparation checkpoint

Product e7a82f7 full exact-SHA integration and independent review PASS zero findings. Normal two-parent merge preserves published foundation4e9c00ca and producte7a82f7. Reconcile only ops/NOW,STATE,QUEUE; runtime identical to reviewed product. Freeze exact release candidate, run fresh gates and independent release review before publication/CI/ref reconciliation and separate closure. V1-047 not yet closed;V1-048 held. OpenClaw disabled;native follow-up active;no owner action. Earlier failed review/repair or active-worker paragraphs are historical only.

### Current superseding checkpoint — final V1-047 reconciliation

Release32fbef1 is published and exact-SHA CI-green. Immutable failed closure
checkpoint549ace3 remains preserved. Correctione4a4ce0 and scheduler-inspection
fix34922d6 each passed fresh189 automation tests and independent Sol max Standard
review with zero findings. The linear closure chain is normally published; exact-SHA
GitHub Actions run33945359575 passed all four jobs and every remote/local ref equals
34922d6. Freeze this bounded four-file final reconciliation, test and independently
review it, publish normally, require exact-SHA CI/ref equality, then complete preserved
Workboard card26b14ae0 and record terminal V1-047 closure. Do not activate or dispatch
V1-048 in this closure turn. OpenClaw remains disabled; no owner action required.

### Current superseding checkpoint — final-reconciliation correction

Immutable final-reconciliation checkpoint030577b failed independent Sol max Standard
review with one MEDIUM unrecognized-status routing finding and one LOW stale-worker
finding. The normal successor restores the executable `verified_unpublished` route and
clears stale worker/branch/worktree identity while preserving the Workboard card and all
evidence. Freeze and test the cumulative four-file successor, require fresh independent
Sol max Standard review, then publish normally, require exact-SHA CI/ref equality,
complete Workboard card26b14ae0 and record terminal V1-047 closure. OpenClaw remains
disabled; V1-048 must not activate or dispatch in this closure turn; no owner action.

### Current superseding checkpoint — final next-action correction

Checkpointcfbce3a fixed both030577b findings and passed189 automation tests, but a
fresh independent Sol max Standard review found one LOW stale-next-action inconsistency.
The normal successor changes only current durable instructions and preserves both failed
checkpoints plus all evidence. Freeze and test the cumulative four-file reconciliation,
require fresh independent Sol max Standard review, publish normally, require exact-SHA
CI/ref equality, then complete Workboard card26b14ae0 and record terminal V1-047 closure.
OpenClaw remains disabled; V1-048 must not activate or dispatch; no owner action.

### Current superseding checkpoint — V1-047 terminal closure

Final cumulative reconciliationb022d83 passed exact local automation189/189 and
fresh independent Sol max Standard review with zero findings. It is normally published;
GitHub Actions run33947895715 passed all four jobs and local/tracking/fetched/live-remote
refs are equal. Existing Workboard card26b14ae0 is terminal DONE through the supported
gateway with all history and failed checkpoints preserved. V1-047 is fully released,
published, verified, reconciled and closed. End this native closure turn without
activating or dispatching V1-048. OpenClaw remains disabled. On a later authorized
cycle, reconcile first and activate only exact V1-048 under standing V1-060 policy.
