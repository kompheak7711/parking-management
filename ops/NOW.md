# V1-020 identity and security hardening — read-batch routing repair

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
- Scheduler: supervisor `658ffdaf-1ac1-45a6-a842-f5f7d7a226eb` is paused before the remaining
  bounded retry; daily reporting and watchdog jobs are unchanged.
- Product status: V1-020 implementation has not started and no product path has changed.
- Owner action: none.
- Exact next action: verify and publish routing revision v2, archive the no-change ceiling
  checkpoint as recovered, then retry only V1-020 `authentication_core`.

<!-- AUTOMATION_STATUS_BEGIN -->
- Automation candidate state: V1-020 active; no product changes; read-batch routing repair in progress.
- Automation exact next action: Publish routing revision v2, then dispatch authentication_core under standing authorization.
<!-- AUTOMATION_STATUS_END -->
