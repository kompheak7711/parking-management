# V1-056 slice 4 — Unit cleaning rate and move-out cleaning charge: reviews

Slice: 4 (BR-UNIT-014, BR-MOVEOUT-013, BR-INV-018, BR-MOVEOUT-006, BR-SVC-001; owner answers to plan Q13 and Q14). Base: 0dd169f. Status: owner answered Q-2026-10-04-7 (Option B, keep `MISCELLANEOUS_CHARGES` with the link table); committed after review round 3 (no should-fix). Commit: the slice 4 checkpoint commit that adds this file (hash recorded in ops/NOW.md).

## Built

Migration `20261016_81`: append-only `app.unit_cleaning_rates` (chain per Unit, `property.manage`, runtime role) with `app.set_unit_cleaning_rate` and `app.unit_cleaning_rate_current`; `app.record_unit_cleaning_charge` (financial role, `invoices.create`) records the Unit's current rate as a Miscellaneous one-time charge source through `app.record_one_time_charge` and writes append-only `app.unit_cleaning_charges` (one per Lease, rate snapshot, move-out event). Refused without move-in, without a recorded move-out, without a rate, for a zero rate and for a stale expected rate. Service methods in `invoice.py`. No HTTP route (slice 11a).

## Test runs

Backend unit suite: 3346 passed, 1557 skipped (before round 1).

PostgreSQL (full suite):

1. 1 failed, 1706 passed (ops/reviews/V1-056-slice-04-full-test-run.txt). Cause: the cross-Property rate test assumed the fixture's Lease was in a separate Property; the suite has one Property. Correction 1 for this cause (a second Property row) was also wrong: V1 allows one Property per database (singleton key), found by review round 1 before any run. Correction 2: Unit and Lease scope tested with ids outside the Property and an unknown Property id; the cross-Unit check uses a second Unit of the same Property.
2. 1708 passed, 0 failed (ops/reviews/V1-056-slice-04-full-test-run-2.txt). Cause of the run: verify correction 2 and the round-1 test additions.

## Round 1 (independent; no security review required for slice 4)

BLOCKER: (1) second Property insert violates the singleton Property; (2) no green full run. Both addressed by correction 2 and run 2.
SHOULD-FIX: (3) category `MISCELLANEOUS_CHARGES` differs from the approved plan's `UNIT_CLEANING` — owner decision (Q-2026-10-04-7); (4) "outside the Property" case never reached the Lease scope branch — added a Lease-outside-scope case (P0002, nothing recorded); (5) no inactive-actor test — added `test_cleaning_functions_refuse_an_inactive_actor` for all three functions (P4506).
NOTES: (6) identity reuse with another one-time charge id — test added; (7) no concurrency test; the per-Lease lock and UNIQUE(lease_id) carry the invariant — answered, no change; (8) the charge audit is the generic one-time charge event with the rate id in the evidence reference and the move-out event in the link row — answered, no change; (9) issue day read from the clock — now read from the Invoice `issued_at`; (10) TRUNCATE untested — added; (11) `_runtime_execute` duplication — accepted; (12) BR-SVC-001 not traced — added to the first test.

## Owner answer (Q-2026-10-04-7, 2026-10-04)

Option B: keep the cleaning charge on `MISCELLANEOUS_CHARGES` with the link table, as built; recorded in docs/010 as an owner-approved change to the plan; ops/V1_056_PLAN.md no longer names `UNIT_CLEANING`. Owner rule from now on: ask before building anything differently from the approved plan.

## Round 2 (independent)

No blocker. 1 SHOULD-FIX: the identity-reuse test could not fail if the guard were removed (the one-per-Lease check also raised a conflict) — now a raw call asserting 23505 "identity was reused". NOTES: (2) reduction refusal untested for this Invoice — added: a user without `invoices.adjust` is refused and a blank reason is rejected before the authorized credit Adjustment; (3) a draft correction or VOID takes the charge off an Invoice — added as a slice 8 requirement note in the plan; (4) rates-table TRUNCATE trigger not proven alone — accepted (the foreign key blocks truncating rates alone); (5) inactive-actor test traced to SEC-014; (6) traceability wording now says "unknown Lease/Unit id"; (7) ops/NOW.md updated; (8) gates recorded below.

Gates after the round-2 fixes: backend format, lint and type check clean (266 files). Backend unit suite: 3346 passed, 1558 skipped (ops/reviews/V1-056-slice-04-round3-unit-test-run.txt).

PostgreSQL run 3 (standing round-3 rule, after the round-2 test fixes): 1708 passed, 0 failed (ops/reviews/V1-056-slice-04-round3-full-test-run.txt).

## Round 3 (standing rule; last round)

Independent: 0 BLOCKER, 0 SHOULD-FIX, 6 NOTE. All round 1 and 2 fixes confirmed real. Notes: (1) the charge reads the rate under the Lease lock, not the rate lock; the named rate is kept and both rows are immutable — accepted; (2) the blank-reason check is command-level — traceability wording updated; (3) the three trigger functions' revokes are not asserted — accepted; (4) slice 8 must not flag a missing charge for a never-moved-in Customer or a zero rate — added to the slice 8 plan note; (5) BR-SVC-001 shown indirectly — accepted; (6) status lines — updated. docs/004 for the two new tables stays in slice 12 (plan). No code or test changed after the round-3 runs.
