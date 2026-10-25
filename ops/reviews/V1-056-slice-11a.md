# V1-056 slice 11a — move-out cleaning, hand-back month and Lease End Date refusals — review record

Slice 11a (ops/V1_056_PLAN.md, slices 11a to 11e): the Unit cleaning rate read and record, the
move-out cleaning charge, the hand-back month assessment and resolution routes, and a code of its
own for a Lease End Date that is not a month end (API-102). No migration. Built on 2026-10-24 in
the cloud session on the 11b work. Decisions on the findings below: decided by Claude under the
owner's 2026-10-23 22:30 rule. The commit hash is in `git log` (this record is part of that
commit).

## Round 1 (read-only review agent, no files written)

No blocker. All 15 cleaning and hand-back database messages in `REFUSALS_BY_DATABASE_MESSAGE`
match the migration 81 and 82 texts exactly, and none is a bad-input message.

- S1, fixed: a hand-back VOID blocked by an unreversed Adjustment or Late-payment Charge, or an
  unsettled billing run, answered a plain 422. It now answers 409 `HAND_BACK_VOID_BLOCKED`
  (only on the hand-back route; the plain `/void` route is unchanged).
- S2, kept for the slice 12 list: the assessment says `VOID` for an Invoice credit-adjusted to
  zero (migration 82 line 159). The command already refuses that case, so no money is at risk;
  the fix is a forward migration that checks "nothing outstanding" first.
- S3, fixed: a closed Final Settlement answers 409 `FINAL_SETTLEMENT_CLOSED` (BR-SETTLE-012) on
  the cleaning charge and both hand-back actions; the Deposit-application message that can
  follow it is mapped too.
- S4, fixed: the PostgreSQL test asserts exactly `HAND_BACK_ALREADY_RESOLVED`, covers a
  same-key replay (same body and ETag) and checks a cleaning charge replay answers 201 with the
  same data.
- N1, fixed: the cleaning-rate read goes through `_invoke`, so no error escapes as 500.
- N2, fixed: the three "identity was reused" messages answer `IDEMPOTENCY_KEY_REUSED` (API-016).
- N3, fixed: docs/005 API-102 says a replay answers the version stored at the first resolution
  and lists `HAND_BACK_VOID_BLOCKED` and `FINAL_SETTLEMENT_CLOSED`.

Decided by Claude under the owner's 2026-10-23 22:30 rule: the per-Unit cleaning rate is set
under `property.manage` until the DL-075 rate groups exist.

Round 2 was the combined review recorded in V1-056-slice-11b.md: no blocker, the fixes correct.

## Gates

Targeted PostgreSQL run S11-T1: 36 passed, 1 failed (a Refund confirm result path in the new
11b test); fixed, and S11-T2 passed. Unit run: see DL-084.
