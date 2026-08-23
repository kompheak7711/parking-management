# V1-024 Unit API and management UI — verified, publication pending

- Candidate: `V1-024` — Unit API and management UI.
- Authorization: Owner-approved direct takeover of `V1-024` through `V1-026` under the
  existing durable V1 scope; no renewed routine authorization is required.
- Baseline: synchronized `implementation/foundation` at `757c04d`.
- Scheduler: exact supervisor `658ffdaf-1ac1-45a6-a842-f5f7d7a226eb` is paused to prevent
  overlapping edits during direct takeover.
- Cause recovered: two Hermes sessions read seven complete files in one batch; the projected
  second request exceeded the unchanged 60,000-token ceiling before any edit. Historical
  attempt and usage records remain preserved outside the repository.
- Implementation: authenticated Unit list/detail, bounded filters and keyset pagination,
  Property-scoped `property.manage` create/update, ETag preconditions, immutable audit-backed
  timeline, operational alerts, and explicit absence of a generic deletion route.
- UI: dedicated typed Unit client and accessible list/detail/history management view with
  loading, empty, authorization, conflict, and successful-action states. Mutation controls
  appear only when the server confirms scoped capability.
- Persistence: forward-only migration `20260824_14` adds the least-privilege version-checked
  Unit update function; create/update and audit evidence commit atomically.
- Verification: formatting, lint, backend/frontend typing, builds, imports, 520 backend tests,
  47 frontend tests, and 158 disposable-PostgreSQL tests pass.
- Canonical specifications: unchanged.
- Blockers: none.
- Exact next action: complete final diff review, publish V1-024, require successful GitHub
  Actions, reconcile it complete, then activate V1-025 without starting V1-026 early.

<!-- AUTOMATION_STATUS_BEGIN -->
- Automation candidate state: V1-024 implementation verified; publication pending.
- Automation exact next action: Review and publish V1-024, then activate V1-025.
<!-- AUTOMATION_STATUS_END -->
