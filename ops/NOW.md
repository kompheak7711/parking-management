# V1-025 Customer identity and history persistence — verified, publication pending

- Candidate: `V1-025` — Customer identity and history persistence.
- Authorization: Owner-approved direct takeover of `V1-024` through `V1-026` under the
  existing durable V1 scope; no renewed routine authorization is required.
- Baseline: synchronized `implementation/foundation` at `f30041c`; V1-024 is published and
  CI-green at `085f149` (run `32671201620`).
- Scheduler: exact supervisor `658ffdaf-1ac1-45a6-a842-f5f7d7a226eb` remains paused to prevent
  overlapping edits during direct takeover.
- Scope: one canonical reusable Customer identity, current contact values, provenance, and
  history-preserving behavior. No fixed Customer type/category and no silent merge or delete.
- Excluded: financial ledger and V1-026 API/UI behavior.
- Canonical specifications: read-only.
- Implementation: canonical Customer domain and least-privilege PostgreSQL storage with stable
  UUID identity, optional normalized contact values, provenance, and version checks.
- Reuse: normalized email/phone values produce bounded candidates only; creation or update
  requires an explicit distinct-person decision and never silently merges records.
- History: protected writes atomically preserve before/after Customer snapshots in immutable
  audit events; delete, truncate, identity replacement, and provenance loss are rejected.
- Verification: 533 backend tests pass with 169 expected environment skips; all 170 disposable
  PostgreSQL migration/runtime tests pass; formatting, lint, strict typing, and traceability pass.
- Blockers: none.
- Exact next action: complete final diff review, publish V1-025, require successful GitHub
  Actions, reconcile it complete, then activate V1-026.

<!-- AUTOMATION_STATUS_BEGIN -->
- Automation candidate state: V1-025 verified and awaiting publication.
- Automation exact next action: Publish V1-025 after final review and successful gates, then activate V1-026.
<!-- AUTOMATION_STATUS_END -->
