# V1-056 slice 11b — shared financial draft routes — review record

Slice 11b (ops/V1_056_PLAN.md, slices 11a to 11e): the draft list, draft detail, confirm,
reject and withdraw routes shared by every draft kind (API-101). Migration `20270208_196`
(the shared draft reads leave out a confirmed draft's `transaction_id`). Base commit 133a8ef.
Built on 2026-10-24 in the cloud session. Decisions on the findings below: decided by Claude
under the owner's 2026-10-23 22:30 rule (no money, no who-may-do-what over money). The commit
hash is in `git log` (this record is part of that commit).

## Round 1 (read-only review agent, no files written)

No blocker.

- Should-fix 1, fixed: Reservation Deposit drafts were listed, read and decided without
  `reservations.read`, which their own routes need. The shared routes now hide a
  `RESERVATION_*` draft from a person without `reservations.read` (decided by Claude under the
  owner's 2026-10-23 22:30 rule). Test
  `test_financial_draft_api.py::test_reservation_deposit_drafts_need_reservations_read`.
- Should-fix 2, fixed: the cross-Property cursor test reached the capability check, not the
  cursor's Property binding. The test now uses a person who holds the capability on both
  Properties and gets 400.
- Should-fix 3, fixed: route tests added for a withdraw by a preparer who no longer holds the
  prepare capability, a withdraw of a draft the caller cannot see, a flow answer of another
  Property or id (503), a refused reject authorization (403) and refusals without database text.
- Note 5, fixed: only the database's "not the preparer" refusal answers
  `DRAFT_WITHDRAW_PREPARER_ONLY`; an inactive or unassigned actor gets the plain 403.
- Note 7, fixed: the `RefusedRequest` handler sets `Vary: Cookie` with `private, no-store`.
- Note 8, fixed: withdraw checks the id of the draft it read first.
- Notes 4, 6, 9, 10 and 11: no change. Migration 196 is correct; 403 for a refused read or
  reject leaks nothing because the database checks the actor first; query validation before
  the capability check matches the other query routes.

## Round 2 (with the slice 11a round 1 review)

No blocker. The round 1 fixes are correct. Further changes made in this round:

- A rejected or withdrawn draft, or a draft another approver confirmed, answers
  `DRAFT_ALREADY_DECIDED`; only the approver who confirmed a draft gets its result again
  (BR-AUTH-010). A draft decided while a confirm runs also answers `DRAFT_ALREADY_DECIDED`.
- A signed-in actor id that is not a UUID is refused with 403, not a server error.
- N4, fixed: the confirm test's stand-in services check the real constructor's and method's
  argument counts.
- Note, kept for the slice 12 list: a concurrent double-confirm by the same approver answers
  `DRAFT_ALREADY_DECIDED` instead of the stored result. Nothing is recorded twice.

Round 3 was not needed: round 2 found no blocker and no should-fix in 11b.

## Gates

Targeted PostgreSQL run of the slice 11 database tests (S11-T2) passed. Unit run: see DL-084.
