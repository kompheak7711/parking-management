# V1-019 post-exit CI detection repair — independently reviewed; publication pending

- Objective: repair only the false post-exit CI failure and terminal-notification path under
  existing durable V1 authorization. No renewed Owner authorization was used.
- Baseline: clean synchronized `7c0f67d07092702229329a57176ae0fdc95afd12` on
  `implementation/foundation`; V1-019 product files and canonical specifications are unchanged.
- Root cause: launchd lacks Homebrew in `PATH`; the CI waiter invoked bare `gh` in a pipeline whose
  successful `head` command masked the missing executable and caused a false 30-minute timeout.
- Exact historical truth: restoration-metadata commit `7c0f67d07092702229329a57176ae0fdc95afd12`
  is bound to GitHub Actions run `32511133185`, workflow status `completed`, conclusion `success`.
- Repair: installation supplies and verifies one absolute GitHub executable. The waiter captures
  each GitHub command before parsing, resolves and persists one exact run ID, polls only that run,
  and performs a final authoritative lookup with stdout, stderr, exit status, run ID, URL, workflow
  status, and conclusion before failure or timeout.
- Regression coverage: launchd-minimal `PATH` recognizes delayed success; a missing configured
  executable fails immediately; failure and timeout preserve final evidence; reconciliation is
  exact-run/commit bound.
- Terminal behavior: a separate asynchronous launchd terminalizer unloads the source continuation
  before `complete` notification, so source SIGTERM cannot preempt delivery. The source waits on a
  bounded durable handoff instead of failure-exiting into keepalive restart, and an OS-locked claim
  makes the notification deduplication cross-process safe. No credential or route is persisted.
- Safety boundary: terminal results attempt exact one-shot self-unload. An unload failure converts
  apparent completion to `failed_closed`, disables supervisor
  `658ffdaf-1ac1-45a6-a842-f5f7d7a226eb`, and sends no false completion notification. Installation
  validation, reconciliation, and submit failures follow the same terminal boundary. Overlap
  detection is unchanged.
- Verification: PASS. The complete profile observed all 15 gates, including 104 automation tests,
  backend 333 pass with 105 expected environment skips, disposable PostgreSQL 105 pass, frontend
  3 pass, formatting, lint, strict typing, builds, audits, traceability, JSON, and diff integrity.
  Evidence: `/private/tmp/property-rental-post-exit-ci-detection-repair-async-final.json`.
- Independent review: PASS on the exact seven-path snapshot; five material lifecycle findings over
  the review rounds were corrected, and the final pass found no blocking or material issue.
- Blockers: none. Owner action: none. Token ceilings and V1-020 are unchanged.
- Exact next action: commit, push, require successful GitHub Actions, then reconcile only run
  `32511133185`, install the corrected post-exit continuation, and verify the supervisor remains
  disabled until this repository-bound CLI exits.

## Preserved predecessor

- V1-019 routing repair commit `e0469b6d519c0947662204869a535c7080185638` remains unchanged.
- The false `failed_closed` evidence remains local and unnotified until exact reconciliation.
- V1-019 remains the only active candidate; V1-020 successor activation remains held.

<!-- AUTOMATION_STATUS_BEGIN -->
- Automation candidate state: V1-019 approved and active; implementation has not started.
- Automation exact next action: Complete this post-exit repair, then run one naturally scheduled bounded V1-019 retry.
<!-- AUTOMATION_STATUS_END -->
<!-- POST_EXIT_RESTORATION_BEGIN -->
- Post-exit repair is verified but unpublished; the existing supervisor remains disabled.
- Restoration success requires post-CLI zero overlap and naturally scheduled bounded V1-019 progress.
<!-- POST_EXIT_RESTORATION_END -->
