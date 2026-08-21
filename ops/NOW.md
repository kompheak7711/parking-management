# V1-019 openai-codex invocation-contract follow-up — verified; publication pending

- Objective: repair only the published V1-019 automation route after Hermes session
  `6baf17e6e77d7582e72b2e19a40ab806` failed before model execution.
- Baseline: clean synchronized `d877cf3b6648083f97e54d661933e3d188999dae` on
  `implementation/foundation`; V1-019 product files and canonical specifications remain unchanged.
- Exact failure: the installed direct `openai-codex` endpoint rejected injected
  `max_output_tokens` with HTTP 400. One API call started, zero completed, zero tokens were
  counted, and no model or Owner-authorized implementation attempt was consumed.
- Classification: `unsupported_invocation_configuration`, recoverable without Owner action.
  The exact failed routing fingerprint is
  `ab2d0cb1c2d3de9e287d595effddd4e4f9de5bdafc361deea003cbde10dcfdc2`.
- Repair: keep the 60,000 cumulative ceiling; reserve predicted context plus completion/checkpoint
  allowance locally; omit unsupported provider parameters; preserve exact zero-usage provider
  diagnostics and attempt accounting; publish routing revision
  `v1-019-invocation-contract-repair-v2` with one bounded eligible retry.
- Restoration: `failed_closed` and `complete` are terminal. Both unload the exact submitted
  one-shot label; restart re-entry never resets terminal evidence to `pending_post_exit`.
- Safety boundary: supervisor `658ffdaf-1ac1-45a6-a842-f5f7d7a226eb` is disabled with no next
  run. Malfunctioning label `com.property-rental.post-exit-restoration.ca4143c8deb3` is unloaded.
  No other cron job was modified.
- Verification: PASS. The complete profile observed all 15 gates, including 97 automation tests,
  backend 333 pass with 105 expected environment skips, disposable PostgreSQL 105 pass, frontend
  3 pass, formatting, lint, strict typing, builds, audits, traceability, JSON, and diff integrity.
  Evidence: `/private/tmp/property-rental-v1-019-invocation-contract-follow-up.json`.
- Independent review: PASS with no blocking findings across the exact nine-path snapshot;
  repository fingerprint `13494038c776a3d7c03bf36e1372745ad7a3c9a836f679813d8460ffd532fccb`
  and compact-state fingerprint `a16d7db426cb8bee697b20e24d7971e3e75cb47b1f9db35340e5cd00222c791a`.
- Blockers: none. Owner action: none. Durable V1 authorization remains valid.
- Exact next action: publish and require successful GitHub Actions, then install the corrected
  fail-closed post-exit continuation. This repository-bound CLI must not enable the supervisor.

## Preserved predecessor

- V1-018 product commit `98ee724e98d2442fd0254bd825256707108f71c8` and GitHub Actions
  run `32461040956` remain published and verified.
- Prior V1-019 routing repair `ca4143c8deb348fddf3c44414022de1fef54831e` and restoration
  metadata `d877cf3b6648083f97e54d661933e3d188999dae` remain preserved.

<!-- AUTOMATION_STATUS_BEGIN -->
- Automation candidate state: V1-019 approved and active; implementation has not started.
- Automation exact next action: Publish the corrected routing revision, then run one naturally scheduled bounded V1-019 retry.
<!-- AUTOMATION_STATUS_END -->
<!-- POST_EXIT_RESTORATION_BEGIN -->
- Post-exit restoration metadata is published; the existing supervisor remains disabled until the continuation enables it.
- V1-019 remains the only active candidate; V1-020 successor activation is held.
<!-- POST_EXIT_RESTORATION_END -->
