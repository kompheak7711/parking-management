# Phase 1F CI foundation

- Objective: add the bounded Phase 1F continuous-integration foundation without
  deployment, production credentials, or application feature work.
- Current task: explicitly approved and ready for one OpenClaw/Hermes implementation
  and independent-verification cycle.
- Base: Phase 1E is published on `implementation/foundation` through metadata
  commit `d1aee643fdff2ed27f254e7fdb0e583798de5083`.
- Checks passed: clean npm lock install, frontend audit/format/lint/strict typecheck/
  3 tests/Vite 7.3.6 build and public metadata assertions; backend locked install,
  format/lint/strict mypy/45 tests with 6 expected database skips/build/import;
  runtime and development dependency audits; backend container build/import/non-root;
  traceability, JSON, exact changed-path scope, diff, secret scan, and canonical docs
  001-010 integrity.
- Publication verification: implementation commit local/upstream/remote SHA and exact
  22-file committed allowlist checks passed.
- Preserved scope: no canonical docs 001-010, dependency versions, database tooling,
  Phase 1F work, staging, commits, or pushes.
- Token policy: the 30-minute schedule uses a deterministic preflight and invokes
  no model when state is unchanged, blocked, or has no approved next action.
- Blocker: none.
- Exact next action: implement and independently verify the bounded GitHub Actions
  CI foundation covering existing backend and frontend quality, test, and build
  gates; commit and push only after every required check passes.
