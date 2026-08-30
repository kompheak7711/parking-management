# V1-043 Utility meter, reading, preview, and billing UI/API — complete

- Candidate: `V1-043` — Utility meter, reading, preview, and billing UI/API.
- Authorization: Owner standing direct-Codex authorization for V1-042 through V1-060;
  this release card is limited to the exact independently reviewed V1-043 SHA.
- Baseline: clean synchronized `implementation/foundation` at V1-042 corrective
  reconciliation commit `a7a7b9d3d63da0d9c24c55c2a4a8e1fa94c81af9`.
- Implementation: exact cumulative commit
  `4bf6c75d2709ddf8e989892364038795df7040b1`, direct parent
  `43091931e2b575c0860899bb539f43a0df8a0d80`; nine commits and 22 reviewed paths
  from the baseline, published by non-force fast-forward.
- Scope: Property-scoped Meter lifecycle and history, validated and pending Reading
  history, replacement and correction evidence, bounded single and bulk Reading entry,
  authoritative preview, Rate history, and accessible authenticated Utility UI/API.
- Authorities: `API-044` through `API-049`, `UI-056` through `UI-062`,
  `TEST-046` through `TEST-052`, `TEST-117`, `TEST-118`, and `TEST-119`.
- Excluded: silent estimation, product corrections during release, canonical changes,
  Invoice issuance, scheduled billing, deployment, production data, and V1-044 work.
- Independent review: Workboard card `4a066693-93ef-4b77-8137-76b27dd7e084`
  returned PASS with zero findings for exact SHA `4bf6c75`; reviewer made no edits and
  property-manager acceptance is recorded.
- Local release verification: focused backend 30/30 and frontend 64/64; complete
  deterministic profile 15/15; disposable real PostgreSQL 432/432 with zero failures
  and zero skips; full format, lint, strict type, build/import, test, dependency,
  traceability, Alembic, deployment, publication, automation, and diff gates passed.
- Implementation publication: GitHub Actions run `33323322907` passed all four jobs for
  exact SHA `4bf6c75d2709ddf8e989892364038795df7040b1`.
- Closure: operational-only commit `81d981a7fd8eb3abb681bd7be94762b4add82f15`;
  exact-SHA GitHub Actions run `33323808705` passed all four jobs.
- Status: complete, published, independently reviewed, and closure-valid.
- V1-044: remains held at `approved_ready`; no activation, implementation, or dispatch
  has occurred.
- Scheduler: no scheduler weakening or activation occurred.
- Blockers: none.
- Exact next action: publish this reconciliation commit, require successful exact-SHA
  GitHub Actions, prove final branch synchronization, and release the V1-043 card only
  to REVIEW; the property manager alone may mark it DONE and activate V1-044.

<!-- AUTOMATION_STATUS_BEGIN -->

- Automation publication state: V1-043 implementation and closure commits are published
  and exact-SHA CI-green; reconciliation and final synchronization are pending.
- Automation exact next action: keep V1-044 held and undispatched while this
  reconciliation commit completes exact-SHA CI and final synchronization.

<!-- AUTOMATION_STATUS_END -->
