# V1-051 USD-only policy reconciliation and cumulative review candidate

## Authority and scope

Owner decision DL-060, 2026-09-06: USD is the main accounting currency; KHR is a
Payment-conversion option only. All financial transactions are recorded in USD;
all Refunds are paid and recorded in USD. KHR Refunds and the former proportional
KHR partial-refund proposal are explicitly rejected. Original transaction/KHR/FX
evidence remains immutable. The earlier question is preserved, explicitly marked
superseded, in ops/V1_051_KHR_POLICY_QUESTION.md.

The owner explicitly requested reconciliation of conflicting requirements, scope,
implementation, tests and saved follow-up. This separately authorizes only the
DL-060 changes in canonical001-007 and010. No unrelated canonical change or new
policy is authorized. DL-031's original entry is preserved and partially superseded.

Old frozen scope SHA25691adbb369a44dc25f04a49bcaa11c1dc8c29694c8805037855c1e52e4396d3b2;
reconciled scope SHA2567424fb52732ce8a48ca45518f19344a524f2a8cb4c57a840eb7dd0781fc40b4f.
Historical question initial SHA25632a8e72e25584f4a0a02f378566ad6de3100cc26f26b2c1411c30ae04960572d;
resolved question SHA256774bde419c51b50f1e1f1faccdee35736a6c23a2a794ae91f506a13bd5b93917.
Decision log SHA256d4455750d705e479364f995eba0369e78aecd8e144dd899ed8b3ada6aabda81e.

## Product change and retained evidence

The existing published Refund table already requires USD and exact equal USD cents.
Remove only the obsolete KHR-source rejection from the unpublished migration41
private validator and service preview; preserve source eligibility, recorded USD
budgets, chronology, actor/Property checks, locks and immutable source evidence.
Restrict the new verified-return currency field to USD. No published migration,
historical transaction, receipt or conversion record is rewritten.

Updated direct and Credit source tests preserve exact fractional source rates.
The synthetic101USDcent/4100KHR source now refunds101USDcents without conversion.
Repeated1+1+99USDcent returns, idempotent replay, exact opposite one-cent reversal,
net/source limits and original outbound/Payment/FX history are verified. There is
no residual KHR partial-return rounding decision or new returned-funds workflow.

Accepted Credit history parent edfea74515d2ddf134cdac67a4b7250594d38d2a and earlier
accepted Credit/USD/Pet slices remain preserved. This candidate also incorporates
their cumulative V1-051 implementation for a fresh complete review from closed
V1-050 terminal cc3d18e682401cc8a9ade10295572fe1a1344317. Old pending markers in
accepted checkpoint documents are historical and discharged by their recorded
acceptance receipts; they do not restart completed work or authorize KHR Refunds.

## Prefreeze verification

Evidence directory: /Users/sokompheak/.codex/.chatgpt-projects/g-p-6a721755d4048191b2550824162f9521.

- Focused PostgreSQL:5 PASS,746 deselected,1.76s; log v1051-usd-policy-focused-development.log,
  SHA256dac78a1b679182fdaf8f33bbbb31786308c22d242251211e013a40dbe5999be9.
- Full PostgreSQL:751 PASS,zero skips,116.95s; log v1051-usd-policy-full-postgresql.log,
  SHA256edb2e732f56f73d59df61b705e9dba1abef6cc17976443ccbd74d17b342b27b8.
- Backend:956 PASS,728 DB-only skips separately covered by PostgreSQL,42.03s.
  Frontend:369 PASS/19 files; both builds/import and all formatting/lint/types PASS.
  Application log v1051-usd-policy-full-application.log,
  SHA256b1665ab68d8282917625e3573cd431aeb5d3db4a91cfa22d0457869f76b86c57.
- Automation:189 PASS,71.049s; routing/state/watchdog/retired-restoration/syntax/compile/
  deployment configuration PASS. Log v1051-usd-policy-full-automation.log,
  SHA25662eead72619dfe8d1201c3a1b74f625b1d55adf2c8095d7f5f72e322d86f96a4.
- Official PyPI runtime/development metadata-only audits: no known vulnerabilities;
  logs v1051-usd-policy-runtime-audit.log and v1051-usd-policy-development-audit.log,
  each SHA25679d30422388543b2563e1dde76bb7e7857d7ef0c6fdf05c8c71598633ca07e1e.
  Official npm audit:0 vulnerabilities; v1051-usd-policy-frontend-audit.log,
  SHA2566d8c5c8f3d7684adb070417bd608d01ae90aa3dc26a65af03ffda4955f38d9a3.
- Traceability/JSON and complete base-to-working-tree whitespace checks PASS.
  The unchanged OpenClaw publication guard returns65 for canonical changes because
  it cannot encode owner authorization. DL-060 and this owner's explicit reconciliation
  request satisfy that separate authorization requirement for the listed paths.
  Its existing secret-pattern scan was separately run over every candidate file and
  passed; no scanner or safety guard was modified or disabled. Independent review must
  verify both the narrow canonical scope and this distinction, not call exit65 a pass.

Development diagnostics preserved: first formatting moved the fixture noqa to the
wrong line, two formatted SQL lines exceeded100columns and a removed negative case
left one unused error import. Corrected locally; format/Ruff/mypy145 PASS. Initial
86 Refund-unit/traceability tests passed. A read-only uv graph probe hit the sandbox
cache restriction; use the installed local Alembic for graph verification. No product
guard or assertion was weakened to fix tooling diagnostics.

Product hashes: migration41 92a01c4514e304a09b9421b5251b96c7272b04e04e7d4cec38e9457f91286d79;
refund.py 0dd9668a9e82f0c530fa5afd7f12f1858d6cca70bba28aa9cebb1a607efbd050;
test_refund_migration.py d0778b52e5e93ad30bbc4caecb6d154494f20813ccf49902d77de13e01b2e0a5;
test_refund_service_migration.py b443f03393ee49ff2fbd22b9ef3c2f8524f70d4124530950c3a897644d9983e2.

## Coordination and exact next action

Existing native follow-up property-rental-v1-047-closure-follow-up remains ACTIVE,
same task01a04961-4270-7802-9418-e08203784a8c,10-minute interval. Updated through the
supported app interface and read back:11574 saved characters, byte-identical to the
submitted prompt after the interface trims its terminal newline;
SHA256ad02e5c32b704b5de4bebdc353b372ff70c61b4e76bf3faf2e39c04ce4ca261a.
It contains USD-only policy, rejected old proposal, active continuation, all model/
safety/lifecycle rules and stop-after53. Exactly one OpenClaw job658ffdaf-1ac1-45a6-a842-f5f7d7a226eb
remains disabled,30-minute schedule retained,no next run,zero running tasks.
Same cardc5621f97-7ad1-4b1c-b04f-c854376c2ad8 retains null claim/attempt/execution;
tracking-only blocked prevents OpenClaw admission, not Codex continuation. Owner
decision comment26b84c0d-87c4-4a52-8c58-e007ceaec6df preserves previous evidence.
All126worktrees retained. Actual coordinator2026-09-06T08:57:46.596Z Astra/xhigh,
localdefault/Standard; provider attestation unavailable, no fallback.

Freeze this candidate as a new immutable child of edfea74; record exact SHA/tree
externally, then run fresh exact-SHA gates and fresh independent Astra max Standard
read-only review of the COMPLETE cc3d-to-candidate diff. Require zero findings and
preserve any rejected candidate. Publish only reviewed commits normally to the
authorized implementation/foundation destination; verify exact CI/ref equality,
same-card acceptance and terminal durable reconciliation before closing V1-051.
Only then V1-052 and V1-053; at53closed pause native follow-up/leave OpenClaw disabled/
no54. All production and safety exclusions remain. No routine owner action required.
