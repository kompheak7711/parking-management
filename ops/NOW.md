# V1-046 Late-payment decision, charge, and correction API — implementation verified for review

- Predecessor: `V1-045` is complete, published, and reconciled. Implementation
  `df8096c1eb1e04aa7ec6c3c782a95fd3b549f1af`, closure
  `fe00f286759695f53001e77937b107d343fb6947`, and final reconciliation
  `39c38e74b7b55f877f74081c94dcd9b971aa1348` are published, synchronized,
  independently reviewed, and exact-SHA CI-green.
- Active candidate: `V1-046` — Late-payment decision, charge, correction, and
  allocation boundaries. The implemented scope remains backend API-091 only;
  V1-047 UI and V1-049 allocation implementation remain excluded.
- Frozen contract: Workboard card `0bdb979f-dce4-4ea8-8036-d08bfc810270` is DONE.
- Implementation: Workboard card `90ffb0d9-ea08-4a87-916f-af461387692b` is
  restored to REVIEW at exact commit
  `7a5097c9f055fd7d7d91e44376f4e215dc2fa790`, sole parent
  `39c38e74b7b55f877f74081c94dcd9b971aa1348`. The retained managed worktree is
  clean; the authorized diff is exactly 16 files, +2282/-19.
- Verification evidence: focused unit/API/traceability 65/65 (independently
  rerun during recovery); real PostgreSQL 464/464 with zero skips; backend
  727/727; frontend 234/234; automation 186/186. Format, lint, strict types,
  builds, dependency audits, deployment checks, publication/secret guards,
  diff checks, and sole linear Alembic head `20260831_37` passed before the
  worker transport failure.
- Recovery classification: two native task records ended through CLI transcript
  compaction after the commit and proof were already durable. The later packet
  was a stale duplicate dispatch; it created no new implementation, commit,
  claim, worker, or worktree. Historical task failures remain preserved as
  transport evidence and do not invalidate the verified commit.
- Remaining gates: integration card `bfee8d82-83e6-4000-ac63-6835b1220201`,
  independent-review card `8548ab20-00b1-4ccf-8275-1472b704ee03`, and release
  card `3266b3a3-e244-4926-ade8-6cc13eff775f` remain dependency-ordered and
  unclaimed. Release and publication are not complete.
- Supervisor recovery: existing job `658ffdaf-1ac1-45a6-a842-f5f7d7a226eb`
  (`Property Rental 24/7 Supervisor`) was reused, moved in place from its retired
  Hermes-era command payload to the `property-manager` native-Codex/Workboard
  agent turn, and enabled on its 30-minute interval with no model fallback. Its
  immediate read-only recovery run
  `cron:658ffdaf-1ac1-45a6-a842-f5f7d7a226eb:1788195703494` completed `ok`
  with an explicit PASS in 597337 ms. It found zero active claims, READY/RUNNING
  cards, queued tasks, duplicate workers, or duplicate worktrees; the next run
  is scheduled for `2026-09-01 00:31:43 +07`.
- Recovery-state publication: ops-only commit
  `3d4ba8538ed838dfb0ed96f995d4a4623a6bbce8` is clean, synchronized, and
  exact-SHA CI-green in run `33417142442` across dependency, frontend,
  backend/traceability, and PostgreSQL migration jobs.
- Separate operational issue: repeated `Native hook relay unavailable` errors
  are recorded for follow-up. Current gateway process health and all five hook
  eligibility checks pass; no gateway restart or mutation is justified.
- V1-047: held and untouched.
- Blockers: none for continuity reconciliation. V1-046 still requires its
  existing integration, fresh independent review, and release gates.
- Exact next action: manager-verify the REVIEW implementation card, advance only
  the existing dependency-ready V1-046 integration path, and keep V1-047 held.

<!-- AUTOMATION_STATUS_BEGIN -->

- Automation state: V1-045 complete; V1-046 exact implementation SHA `7a5097c9`
  verified and restored to REVIEW after transport-only task failures. The sole
  30-minute supervisor is enabled and its immediate native recovery cycle passed.
- Automation exact next action: continue the existing V1-046 Workboard DAG from
  manager review through integration and fresh independent review; do not
  reimplement, duplicate a worker, release early, or activate V1-047.

<!-- AUTOMATION_STATUS_END -->
