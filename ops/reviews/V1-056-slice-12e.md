# V1-056 slice 12e review record: final gates and final review of slice 12

Done 2026-10-25 in the cloud session on branch `wip/slice-12c` (12a to 12d, then 7b48d43 and the
merge of implementation/foundation d1f2657, 9ad02c0). No migration; the head is `20270218_206`.
Decision log DL-094.

## Gates

- Backend unit suite (at 12b, fe3131c): 4,938 passed, 2,587 skipped (database suites), none
  failed. The unit tests 12c to 12e added or touched passed on their own:
  `test_local_run_scripts.py` 12, `test_traceability.py` 28, the prune command test.
- Backend ruff format, ruff check and mypy: clean (480 files).
- Frontend (the slice 12 tree): prettier, eslint, `tsc -b`, vitest 1,654 passed in 40 files,
  build. The first run failed `tsc -b` in `FinancialWorkspaces.test.tsx` (a slice 11g-4 test,
  `shown[0]` and `charges[0]` possibly undefined); fixed in 7b48d43. npm audit: 0
  vulnerabilities (the braces advisory is gone).
- TEST-118 audit: passed against 062805c (17 new material identifiers) and d1f2657 (none).
- Full PostgreSQL run 1 (bc738a4, not yet merged with d1f2657): 2,753 passed, 7 failed. Six
  Utility consumption tests failed because the 12b late Utility suite, listed earlier, leaves
  committed Utility Invoice lines that their rate reset (`DELETE FROM app.utility_rates`)
  refuses; reproduced with the two suites in that order; the late suite now runs after the
  Utility suites (7b48d43). The seventh was the draft list test d1f2657 fixed.
- Full PostgreSQL run 2 (9ad02c0): 2,759 passed, 1 failed:
  `test_financial_draft_api_migration.py::test_drafts_are_listed_confirmed_rejected_and_withdrawn_through_the_shared_routes`
  asserted that no PENDING draft is left in the shared Property, but
  `test_settlement_late_charge_reduction_migration.py` leaves one. Reproduced with those two
  suites in order (1 failed), fixed (the test now checks only its own three drafts), then 7
  passed. Not rerun in full (run rules: reruns only after corrections; the fix is to that one
  assertion).

## Final review (one read-only agent, cross-cutting)

- No blocker in the code. Should-fix taken: S1 the branch did not contain d1f2657 (merged in
  9ad02c0, ops/NOW.md keeps both sides in order); S2 the 12b worker bills every earlier late
  Utility period with no age limit on its first pass after deploy (now in DL-094 and the slice
  12 list for the owner; no live history exists before go-live); S3 the uncommitted frontend
  fix (committed). Nits taken: DL-094 names DL-093 as an approved tightening; the plan marks
  the items 12a to 12c closed. Not taken: the prune command prints events on stdout (a rerun
  is safe); the late candidates function is STABLE while its sibling is VOLATILE (harmless).
- Checked by the reviewer: the chain 202 to 206 has no fork; every downgrade refuses; owner,
  definer flag, search path and grants are kept; the prune takes only username locks in digest
  order; no output prints a database address or secret; no amount rule changes.

## Merge note

- The V1-058 branch also uses migration ids 203 to 206; whichever merges second re-chains.
