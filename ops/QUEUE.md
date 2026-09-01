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

Current live queue position: V1-046 independent review is manager-accepted FAIL with six
MEDIUM findings. Bounded correction card `dfe221fe-d32d-4baf-acb4-442376616dd5` is running;
fresh integration `87d90c87-8cca-4529-98ab-a22646332e77`, fresh review
`208ac3de-72f2-45a2-9be7-4e096aaf08ca`, release, and V1-047 remain dependency-blocked.
