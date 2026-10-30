# Step 5 ledger — plan: docs/replica/step-5-plan.md

Pre-flight: Task 1 produces the five flags in `frontend/src/leases/parking.ts`; Tasks 2–5 consume them by name. `detailsFrom` (Task 1) is consumed by both dialogs in Task 4. No other shared interfaces.

Ruling: `detailsFrom` leaves hidden keys out for New Parking too (not only Update), because `UnitCreate` in `unit_api.py` gives every detail a default; one function, one rule. Cost if wrong: a 422 on New Parking, caught by TEST-FE-818.

Ruling: pet gating on the two old folded screens (`LeaseManagement.tsx`, `DepositManagement.tsx`) hides the inputs (pet fieldset, Create Pet Deposit form) and the Conditional Pet Deposit block when no pet is on record; the three generic help sentences that mention Pet Deposits stay — no input, no amount, old engineering screens. Cost if wrong: a staff member reads the word "Pet" on an old screen.

Ruling: the Refund workspace's "Qualified Pet Deposit" source is hidden (`PET_DEPOSIT`); TEST-FE-443 runs its PAYMENT and CREDIT cases only, TEST-FE-529 and 530 skip. Cost if wrong: a pet deposit refund from the old workspace needs the flag on.

Ruling: the TerminateDialogs VIOLATION ground loses only its sub-text ("Includes pet-rule violations"); the pet tick itself was already data-driven (`lease.pet_deposit_required`). Cost if wrong: none; the tick still shows for a Lease with a pet.

Ruling: `TEST-FE-941` (Settings Add/Edit/Remove) uses the Parking Types list for Add and Remove when Views and Kitchens are hidden; the behaviour under test (dup check, Khmer name, re-read) is the same. Cost if wrong: a Views-only bug is not caught on Parking (the list is hidden anyway).

Ruling: the exact-to-the-cent no-pet settlement test uses a signed Lease that never moved in (`signed_with_initial`) with a 7,525 charge and a 10,000 Security Deposit, closed through `record_draft` + `confirm` by a second approver; the moved-out path is covered by the no-rate/no-charge test reaching `ready`. Cost if wrong: the moved-out close is proven only to `ready`, not through `confirm`.

Ruling: `app.record_unit_cleaning_charge` keeps no guard (plan Task 5 "not done"): the button is hidden, the route stays usable by a direct API call. Cost if wrong: a direct API call could still record a cleaning charge; it would then show and settle as a normal debt.

Task 1: complete (flags; `detailsFrom` omits hidden keys; TEST-FE-1139 RED→GREEN; TEST-FE-818 adjusted)
Task 3: complete (inventory and features gated; TEST-FE-1144, 1145 RED→GREEN; 029, 940, 941 adjusted)
Task 4: complete (Size, Bedrooms, Bathrooms, View, Kitchen gated; Views and Kitchens cards hidden; TEST-FE-1146 RED→GREEN)
Task 2: complete (pet gated in 11 files; TEST-FE-1140, 1141, 1142, 1143, 1149, 1150, 1151 RED→GREEN; 845, 857, 563 adjusted; 974, 979, 191, 202, 210, 529, 530 skip; 443 PET case off)
Task 5: complete (migration 20270407_257; tests/test_cleaning_off_migration.py 5 tests RED→GREEN on a fresh database; preview test cleaning asserts `[]`; 22 head pins; database-test.sh; TEST-FE-1147, 1148, 1152 RED→GREEN; 978, 1006 skip)
Task 6: complete (docs 002/004/005, features.csv, traceability +19, parking-differences Step 5, this ledger)

Final review (code-review skill, 8 findings):
Final: fixed TEST-FE-974, 979, 191 skipped although the pet was one step, not the subject — they run again with the pet step behind `PET_DEPOSIT` (974 expects `pet_related` = flag; 191 expects `pet_term` null when off). 529/530 stay skipped: their subject is the PET_DEPOSIT Refund source flow.
Final: fixed features.csv line endings — the file keeps CRLF; only the 15 content edits remain.
Final: fixed `CustomerLedgerEvidence.tsx` — the pet row test goes through `ledgerMoney` (the existing normalizer), not a raw `BigInt(...)`.
Final: fixed `LeaseForm.tsx` — a renewal of a Lease with a pet keeps `pet_deposit_required` and shows the tick (data-driven, rule B); `pet_term` is sent as before. Cost if wrong: none on Parking (no pet rows).
Final: fixed `UnitDialogs.tsx` — the `size` read sits inside the `HOME_FIELDS` block.
Final: Ruling: traceability entries of the tests that skip on Parking stay byte-for-byte as Property Rental wrote them: `test_traceability.py` hashes the early entries (editing a note made six of its tests fail), and `status` allows only implemented / planned / blocked. The skip list lives in `parking-differences.md` and in the TEST-FE-1152 note. Cost if wrong: a reader must open the differences file.
Final: minor (deferred): `MoveoutPage.tsx` checks `CLEANING_CHARGE` in three places (`mayRate`, `cleaningSettled`, the section guard); one derived value would be tidier but "hidden" also means "no permission" in Property Rental, so the three stay apart.
Final: minor (deferred): `test_a_moved_out_lease_waits_for_final_utility_cleaning_and_billed_periods` keeps Property Rental's name and body with `[]` cleaning asserts, so a Property Rental fix to that test copies with one predictable conflict; the Parking behaviour is proven in `test_cleaning_off_migration.py`.

Task 7: complete (frontend 1997 passed / 1 failed TEST-FE-894 known / 16 skipped; eslint, tsc, prettier, build clean; backend 5122 passed / 1 failed known owner set-up / 2748 skipped; database 2933 passed on a throw-away PostgreSQL in 45 min; mypy only the known backup_job error; parity 100; sweep: only "Unit price" and one comment. Same known failures, no new failures. Not committed, not pushed.)

Owner 2026-10-30 (after report): the five words-only Pet Deposit sentences on the old folded screens now pick a no-pet wording behind `PET_DEPOSIT` (grep had found three; two more were split across lines or were a notice). TEST-FE-1153, 1154 RED then GREEN. The follow-up notice string has no test of its own (reaching it needs a termination follow-up; words only, covered by tsc and lint). Cleaning-charge API left unguarded by owner decision; recorded as an open note in parking-differences.md.
