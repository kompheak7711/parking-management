# Phase 1F CI foundation

- Objective: add only the bounded GitHub Actions foundation required by
  TEST-113/117/118, without deployment, credentials, or application features.
- Current task: complete and published on `implementation/foundation` as
  `d1eb61b6e897842a13782c227170f30f323fe248`; no implementation cycle is active.
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
- Hosted verification: GitHub Actions CI run `31863438115` completed successfully
  on the first attempt for the Phase 1F implementation commit.
- Preserved scope: canonical docs 001-010, application code, dependencies/lockfiles,
  database tooling/data, and production configuration remain unchanged.
- Blocker: none.
- Exact next action: obtain owner approval for the first bounded Phase 2 identity
  and security tranche.
