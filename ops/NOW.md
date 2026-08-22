# V1-020 identity and security hardening — context-routing repair

- Candidate: `V1-020` — Identity and security end-to-end hardening gate.
- Authorization: standing authorization for the remaining approved V1 roadmap; no renewed
  tranche authorization was consumed.
- Activation: published at `cb39e25`; its V1-019-coupled CI test was isolated and the repair
  passed GitHub Actions at `8eaefb9`.
- First Hermes result: session `20260823_003208_38266a` made one API call, changed zero files,
  and correctly reported that the packet prohibited discovery while supplying no readable path.
- Repair: V1-020 is divided into authentication-abuse, MFA-policy, recovery,
  sessions/integration, and bootstrap/release sessions. Each receives no more than eight exact
  source/test paths, exact authority excerpts, and the unchanged 60,000-token ceiling.
- Forward routing: repository-backed wildcard authority expansion and a bounded
  traceability/profile fallback prevent later approved candidates from receiving empty packets.
- Verification: all 128 automation tests, routing/state/watchdog suites, shell and Python
  syntax, JSON validation, publication guard, and diff checks pass.
- Scheduler: supervisor `658ffdaf-1ac1-45a6-a842-f5f7d7a226eb` is paused during repair
  publication; daily reporting and watchdog jobs are unchanged.
- Product status: V1-020 implementation has not started and no product path has changed.
- Owner action: none.
- Exact next action: verify and publish the routing repair, rebase the failed no-change attempt,
  re-enable the supervisor, and retry only V1-020 `authentication_abuse`.

<!-- AUTOMATION_STATUS_BEGIN -->
- Automation candidate state: V1-020 active; no product changes; context-routing repair in progress.
- Automation exact next action: Publish the bounded context-routing repair, then retry authentication_abuse under standing authorization.
<!-- AUTOMATION_STATUS_END -->
