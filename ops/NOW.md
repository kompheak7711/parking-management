# Phase 1F CI foundation

- Objective: add only the bounded GitHub Actions foundation required by
  TEST-113/117/118, without deployment, credentials, or application features.
- Current task: implemented, independently verified, and authorized for publication;
  uncommitted on
  `implementation/foundation` at base `f2611057169c0d05570b898625d47dee26076d81`.
- Workflow: immutable action/tool pins and locked project installs gate backend and
  frontend formatting, linting, strict types, tests, builds, traceability, dependency
  security, and isolated PostgreSQL migrations.
- PostgreSQL boundary: the workflow invokes only `make database-test`; it contains no
  database credential or connection configuration.
- Traceability: existing tests enforce TEST-117 manifest/executable coverage; the new
  deterministic TEST-118 audit rejects newly introduced material BR/PR headings that
  lack manifest mappings.
- Last verified result: locked installs passed; backend/frontend quality, strict types,
  45 backend tests plus 3 frontend tests, builds/import, two Python audits, npm audit,
  and 6 isolated PostgreSQL migration tests passed. Workflow YAML/pins/format/scope,
  canonical-doc integrity, compact JSON, diff, and empty staged-set checks passed.
- Changed paths: `.github/workflows/ci.yml`, `README.md`, `scripts/traceability-audit.py`,
  `ops/NOW.md`, and `ops/STATE.json`.
- Preserved scope: canonical docs 001-010, application code, dependencies/lockfiles,
  database tooling/data, Git index, commits, and remote state are unchanged.
- Blocker: none before authorized publication.
- Exact next action: stage only the five reviewed Phase 1F paths, commit and push,
  verify the remote SHA and GitHub-hosted CI result, then reconcile compact state.
