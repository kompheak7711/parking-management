# V1-051 Pet Refund bounded correction1 checkpoint

## Authority and immutable rejected evidence

Standing direct Codex takeover through53 and frozen ops/V1_051_SCOPE.md apply.
Coordinator/financial implementation Astra xhigh Standard; fresh independent reviewer
Astra max Standard, read-only, no fallback. No publication/full-version acceptance.

Rejected candidate f311a9048d1f27ea9f7e7a47bb5fb565e481dd04, tree
12c556aed4135364bd663bd1d547259d8682a5d2, is retained unchanged. Fresh review found
0 HIGH, 2 MEDIUM, 1 LOW; verbatim v1051-pet-refund-review-f311a90.md SHA256
e64f0ce08f7d0a93fa8eddb79e66981ca0d15966736674b20f7e903ec5cb96c2.
Rejected receipt v1051-pet-refund-rejected-f311a90.md SHA256
ff358c8aaa048988e6d21052ce923ab2e6bd16bd420db96dbeeb42280e719a80.
These evidence files reside in the Codex task evidence directory recorded in STATE.
Previous reviewer01a07448-88ec-7d41-8c9e-e608c43bdb01 completed; it is not reused.
Its actual metadata is Astra/max/read-only/approvalnever; local service_tier default,
provider-side Standard attestation unavailable. This is bounded correction1, recorded
ACTIVE before editing at2026-09-06T01:50:06Z; no new owner authorization required.

## Material corrections and regression evidence

1. MEDIUM receipt eligibility: the existing Deposit ledger now checks each original
   Refund's USD amount against the sum of its signed correction effects. Any unresolved
   Refund blocks receipt reversal; full verified returns remove that block without
   deleting the original Refund. This matches the existing persistence predicate in
   published migration38; inline read SQL uses existing table grants and exposes no
   private helper. Disposition, active application and already-reversed guards remain.
   DB-DEP-007/API-042/API-066 regression exercises runtime ledger plus the production
   can_reverse response helper, full20000Refund, partial5000/full15000returns,
   reversal of the5000correction, final5000return, authorized receipt reversal/replay,
   reader denial, unchanged originals, four retained corrections and zero held value.
2. MEDIUM active Security exclusion: replace the Reservation-only fixture with the
   real signed-Lease/move-in fixture. Assert SECURITY, exact attached Lease, SIGNED,
   exact Property, same primary tenant and50000held. Refund preview and creation
   refuse Security while the Lease stays SIGNED and no Refund is created. Departure
   alone still does not qualify Pet. TEST-126/PR-DEP-012 are genuinely exercised.
3. LOW semantic traceability: remove unsupported SEC-026 financial-calculation mapping
   from the bounded-narrative test. API-064/API-094 map exact source/qualifying-review
   identity, bounded linked response and intact original findings. Source identities
   are now explicitly asserted; no requirement claim rests only on a generic label.

Only Deposit read-side integration and tests/traceability/compact evidence change in
this correction. No migration, canonical rule, dependency, grant or source write path
is modified. Original Pet checkpoint remains historical rejected evidence.

## Verified integration before freeze

- Final product PostgreSQL737passed/zero skips116.74s; log
  v1051-pet-correction1-full-postgresql.log SHA256
  9456f3bab5783544d86e71f84e7713231291a08100e690d3d0a11b292dae60da.
- Backend940passed/714DB-onlyskips separately covered44.07s; format/Ruff/mypy143/
  build/import PASS. Log v1051-pet-correction1-full-backend.log SHA256
  48eed2212d9f0d8c57d50ea728fa42040dcbe5bfcbf3378f678208afdc47feda.
- Frontend19files/369tests6.64s/format/lint/types/build PASS. Log
  v1051-pet-correction1-full-frontend-verified.log SHA256
  4a58f0a8c66b1645fa2bc258ab498f6a2b2c7401f2f75ff5a6a21c5cde8966e6.
- Initial focused29PetPG4.69s/86unit+traceability6.53s PASS. Full gates include the
  subsequent two source-identity assertions. Migration41 format/lint/graphhead PASS.
-189automation69.754s plus routing/state/watchdog/retiredrestoration/syntax/compile/
  deployment PASS; log v1051-pet-correction1-automation-initial.log SHA256
  665f64572c37ae2bd21f8fa285f84450be428aebfdedd9895f2eced2a0a13510.
  Exact committed configuration checks must be rerun and bound in a later receipt.
- Test-development evidence, including the failed missing-frontend-tool attempt and
  offline locked-dependency setup, is v1051-pet-correction1-test-development.md SHA256
  c8c6b8b85072a5e7343df4dd0ebf5d5bdec95bba6bac4d25b4110cf1dda28802.
- TEST-118 zero new identifiers, publication guard and working whitespace PASS.
  Verify staged plus cumulative whitespace before/after commit; never amend history.

## Exact review and dependency-safe continuation

Candidate is the immutable commit containing this checkpoint. Its parent must be
f311a9048d1f27ea9f7e7a47bb5fb565e481dd04; obtain exact SHA/tree from Git and bind in
a subsequent evidence receipt. Fresh independent review must cover the complete Pet
delta from2f45c8ab3a9b824650e34ab0225e6f020d13ee3b, all changed paths including new
files, and all three prior findings. Require zero HIGH/MEDIUM/LOW; do not edit or
duplicate review while valid review is running. Full cumulative whitespace/release
base remains cc3d18e682401cc8a9ade10295572fe1a1344317. No Pet acceptance yet.

Sole worktree codex/v1-051-direct,126retainedworktrees; same cardc5621f97 tracking-only
blocked against OpenClaw admission, claim/attempt/executionnull, no owner blocker.
OpenClaw singleton658ffdaf disabled30minutes/no nextRun/runningtasks0; native10minute
follow-up remains ACTIVE. Mainclean44d93be; tracking/fetched/livecc3d, predecessor
CI33986122538 exactcc3d all4SUCCESS. Preserve accepted Creditc162b07/privateUSD79fe7f8/
USDserviceec77dde. On Pet acceptance continue bounded Credit history and KHR sources
in SAME checkout. Full51OPEN/unpublished until all frozen scope, fresh full gates,
authorized metadata-only audits, cumulative exact independent review, normal reviewed
publication, exactCI/ref equality, same-card acceptance and terminal reconciliation.
No52before51closed; continue through53only, then pause nativefollowup/leaveOCdisabled/
no54. Production/access/credentials/customerdata/paid/destructive/forcepush/history
rewrite/retained-worktree deletion remain unauthorized.
