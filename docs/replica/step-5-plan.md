# Step 5: Switch off what Parking doesn't use — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pet deposit, Parking inventory, Parking features, the home-only Parking form fields and the move-out cleaning charge disappear from every screen, letter, report, Invoice and settlement, while every table, function, route and test stays, so each can come back by flipping one flag.

**Architecture:** One flag per switched-off thing in `frontend/src/leases/parking.ts` (the Step 4 `PEOPLE_MOVE_IN` pattern: `export const X = false as boolean;`, elements rendered behind `X &&`, tests skip with `skip(!X)`). The backend and database stay untouched except for the cleaning charge: the database settlement preview blocks a move-out until a cleaning charge is issued or the Parking's rate is 0, so one forward-only migration (`20270407_257`) edits that one check with the `pg_get_functiondef` + `replace` pattern of migrations 238 and 247. Hidden form inputs are also removed from the Update Parking request body, because the backend clears any field it receives as null and keeps any field left out.

**Tech Stack:** TypeScript/React/Vitest (frontend), Alembic/PostgreSQL/pytest (one migration + tests), docs.

**Spec:** owner message of 2026-10-30 (Step 5 brief), owner answers to the Step 5 questions (recorded below as they arrive), `docs/replica/step-4-plan.md` for the flag pattern.

## Global Constraints

- Keep code and tables. No DROP, no DELETE, no data change. Migration 257 only replaces the body of `app.final_settlement_preview(uuid,uuid,uuid,text[])` (one `IF` condition) and is forward-only.
- Money and settlement stay exact: no amount, total, refund or ledger line changes. A cleaning charge, pet approval or PET deposit that already exists in a database still shows and settles as before (rows stay data-driven; only inputs and always-on text are gated).
- Hidden code names unchanged. Flags are the only new identifiers.
- Change only words staff see; Khmer written by Claude is listed for the owner's check.
- Never remove a key from `unitSetupListKinds` (`frontend/src/unitClient.ts:11`) or from `LEDGER_BUCKETS` (`customerLedgerClient.ts`): the parsers check incoming data against them.
- Tests: update old asserts or skip behind the flag; never delete a test. Every skipped test id is listed in `docs/replica/parking-differences.md`.
- Owner answers pending (Task 4 waits for them): Size, View, Notes, Floor, Required Services.

## Flags (all in `frontend/src/leases/parking.ts`)

| Flag | Switches off | Decided |
| --- | --- | --- |
| `PET_DEPOSIT` | pet approval on the Lease form, Pet Deposit always-on text, pet damage tick at move-out, pet create forms on the old folded screens, report wording | yes (owner) |
| `UNIT_INVENTORY` | Parking inventory panel on the Parking page, New Parking note sentence | yes (owner) |
| `ROOM_FEATURES` | "Parking features": Room features checkboxes, Yes/No facts, Settings "Room features" card | yes (owner) |
| `HOME_FIELDS` | Bedrooms, Bathrooms, Kitchen inputs and facts, Settings "Kitchens" card; plus Size / View / Notes if the owner says hide | partly (owner) |
| `CLEANING_CHARGE` | Settings cleaning rates card, "No cleaning rate" chip, move-out step 4 cleaning section, button and dialog; migration 257 stops the settlement block | yes (owner) |

## Review Focus

1. Update Parking after the switch must not wipe stored Size, View, Kitchen, features or Notes: the body built by `detailsFrom` (`units/UnitDialogs.tsx:48-61`) must leave hidden keys out, not send null or `[]`. Test: an Update with hidden fields sends a body without those keys.
2. A Lease that already has a PET deposit or pet approval still shows its Pet Deposit card, pet rows at move-out and settles the same (data-driven rows untouched). Test: existing TEST-FE-870, 976, 988, 994, 991, 992, 1047 stay green with the flag off.
3. A moved-out Lease with no cleaning rate and no cleaning charge reaches a ready settlement preview (no `CLEANING_CHARGE_MISSING`); a Lease that already has an issued cleaning charge still counts it as a normal obligation. Test in `tests/test_cleaning_off_migration.py`.
4. The Rent and Services card, Default Rent and Parking Type keep working on New Parking, because New Parking's rent-terms save runs after the create and must not depend on hidden inputs.
5. The Settings "Parking setup" tab still shows Floors and Parking Types after hiding Room features (and Kitchens, Views); the route `#/settings/units` stays alive.

---

### Task 1: Flags and the Update Parking body

**Files:** `frontend/src/leases/parking.ts`, `frontend/src/units/UnitDialogs.tsx` (`detailsFrom`, `UpdateUnitDialog`), `frontend/src/units/UnitsPage.test.tsx`.

- [x] Add `PET_DEPOSIT`, `UNIT_INVENTORY`, `ROOM_FEATURES`, `HOME_FIELDS`, `CLEANING_CHARGE` (all `false as boolean`) with a comment naming the owner's decision and date.
- [x] Failing test TEST-FE-1139 (UnitsPage.test): Update Parking with the flags off sends a PATCH body without `bedrooms`, `bathrooms`, `kitchen_item_id`, `room_feature_ids` (and without `size_square_metres`, `view_item_id`, `notes` if hidden). Run: `npx vitest run src/units/UnitsPage.test.tsx -t TEST-FE-1139` → FAIL (keys present).
- [x] `detailsFrom` builds the object then deletes the keys of hidden fields (one helper `withoutHidden(details)`); New Parking may keep sending nulls/`[]` (a new row has nothing to wipe). Run → PASS.
- [x] TEST-FE-818 (`:1159`): the payload asserts for hidden fields move behind `if (HOME_FIELDS)` / `if (ROOM_FEATURES)`; the test itself stays.

### Task 2: Pet deposit

**Files:** `leases/LeaseForm.tsx:1029-1053, 392, 681`, `leases/LeaseDetail.tsx:1137`, `leases/TerminateDialogs.tsx:354`, `moveout/InspectionDialog.tsx:404-415`, `moveout/MoveoutPage.tsx:1494`, `LeaseManagement.tsx:995-1032, 1099-1110, 1287`, `DepositManagement.tsx:201, 491, 759-789`, `FinancialRefundWorkspace.tsx:421`, `CustomerLedgerEvidence.tsx:31, 96`, `reports/RegisterView.tsx:868-871`, `reports/text.ts:82`.

- [x] Failing tests first: TEST-FE-1140 (LeasesPage.test): New Lease form shows no pet checkbox and sends `pet_term: null`; Lease page shows no "No pet approved" line. TEST-FE-1141 (MoveoutPage.test): finding dialog has no "Caused by the pet" tick; step 4 shows no "No Pet Deposit on this Lease." TEST-FE-1142 (CustomerAccountLedger.test): "Pet Deposit held" row absent when the amount is 0 and the flag is off. TEST-FE-1143 (RegisterView.test): deposits "By kind" lists PET only when held above 0. Run each → FAIL.
- [x] Gate rule A (inputs and always-on text) on `PET_DEPOSIT` alone; rule B (read-only rows) on `PET_DEPOSIT || amount > 0`. Renew: `PET_DEPOSIT && previous.pet_deposit_required`. `reports/text.ts` `d_deposits`: a second key `d_deposits_security` used when off ("Security Deposits held…", Khmer for owner check). Run → PASS.
- [x] Existing tests: TEST-FE-845 and 857 drop their pet assertions; TEST-FE-974, 979 (pet tick), 191, 202, 210 skip with `skip(!PET_DEPOSIT)`; TEST-FE-563 loses the "Pet Deposit held" label from its expected list. Refund option (TEST-FE-443, 529, 530) is gated too, so those three skip.
- [x] Run: `npx vitest run` → only TEST-FE-894 fails.

### Task 3: Parking inventory and Parking features

**Files:** `units/UnitDetail.tsx:354-357, 633-643, 654-660`, `units/UnitDialogs.tsx:210-227`, `units/text.ts:180-183` (`new_note`), `settings/UnitSetupTab.tsx:481`.

- [x] Failing tests: TEST-FE-1144 (UnitsPage.test): Parking page shows no "Parking inventory" heading and no feature tiles; New/Update dialogs show no "Room features" fieldset. TEST-FE-1145 (UnitSetupTab.test): the tab shows Floors and Parking Types but no "Room features" card. Run → FAIL.
- [x] Gate: panel behind `UNIT_INVENTORY &&` (also stops its two GET calls); features list empty when `!ROOM_FEATURES`; fieldset behind `ROOM_FEATURES &&`; `new_note` gets a second key without the inventory sentence; `unitSetupListKinds.filter(kind => kind !== "ROOM_FEATURE" || ROOM_FEATURES)` before `.map(card)`. Run → PASS.
- [x] Existing tests: TEST-FE-029 (`:618` "BalconyYes") guard that assertion; TEST-FE-940 expects the card count without Room features (and without Kitchens/Views per Task 4); TEST-FE-819, 820, 822 render the panel directly and stay.

### Task 4: Home-only Parking form fields (after the owner's answers)

**Files:** `units/UnitDialogs.tsx:164-209, 228-237`, `units/UnitDetail.tsx:339-341, 607-653`, `settings/UnitSetupTab.tsx:481`, `units/text.ts`.

- [x] Failing test TEST-FE-1146: New and Update dialogs show no Bedrooms, Bathrooms, Kitchen (+ Size/View/Notes per answers); the Parking page shows no such facts; Settings shows no Kitchens card (and no Views card if View is hidden). Run → FAIL.
- [x] Gate inputs, facts, subtitle "36 m²" and Settings cards on `HOME_FIELDS` (Kitchens card: `kind !== "KITCHEN" || HOME_FIELDS`, Views likewise if hidden). Run → PASS.
- [x] Existing tests: TEST-FE-029 (`:602, 619, 620`), 818, 940, 941 adjusted as in Task 3. Floor stays (required by the database, drives filters, reports, Utilities). Default Rent stays (Step 3).

### Task 5: Cleaning charge

**Files:** `backend/migrations/versions/20270407_257_cleaning_charge_off.py` (new), `backend/tests/test_cleaning_off_migration.py` (new), `backend/tests/test_final_settlement_preview_migration.py:774`, `scripts/database-test.sh`, 20+ head pins (`20270406_256` → `20270407_257`), `moveout/MoveoutPage.tsx:619-624, 927-929, 1003-1021, 1381-1408, 1628`, `settings/RatesTab.tsx:730`, `settings/UnitSetupTab.tsx:254-299, 414`, `settings/text.ts:136`, `payments/text.ts:300`, `reports/text.ts:361`.

- [x] Failing database test (fresh throw-away database, `dbtest-run.sh`): a signed Lease moved in, terminated and moved out, no cleaning rate, no cleaning charge → `app.final_settlement_preview` has no issue `CLEANING_CHARGE_MISSING`; a Lease with an issued cleaning charge still lists it as an obligation; `app.record_unit_cleaning_charge` still works (code kept). Run → FAIL (`CLEANING_CHARGE_MISSING` present).
- [x] Migration 257: `_patch(PREVIEW, "IF v_moved_in AND v_move_out.id IS NOT NULL AND NOT EXISTS(\n                SELECT 1 FROM app.unit_cleaning_charges cleaning", "IF false AND v_moved_in AND v_move_out.id IS NOT NULL AND NOT EXISTS(\n                SELECT 1 FROM app.unit_cleaning_charges cleaning")` (count must be 1; the migration refuses otherwise). Docstring: "Parking Step 5: no cleaning charge at move-out (owner 2026-10-30)". Downgrade raises (forward-only). Run → PASS.
- [x] Update `test_a_moved_out_lease_waits_for_final_utility_cleaning_and_billed_periods` (`:774`): the cleaning expectation moves out of its asserts (the other two waits stay). Move the head pins. Add the file to `scripts/database-test.sh`.
- [x] Failing frontend tests: TEST-FE-1147 (MoveoutPage.test): step 4 shows no cleaning section or button and counts as done with no charge; TEST-FE-1148 (RatesTab.test / UnitSetupTab.test): no cleaning rates card, no "No cleaning rate" chip. Run → FAIL.
- [x] Gate on `CLEANING_CHARGE`: the rate read, `cleaningSettled` true when off, button, section, dialog, Settings card, chip; copy keys `cf_type_note`, `c_MOVEOUT_s`, `reports/text.ts:361` get an "off" variant. Run → PASS.
- [x] Existing tests: TEST-FE-978 skip; TEST-FE-976 cleaning asserts behind `if (CLEANING_CHARGE)`; TEST-FE-1006 skip; TEST-FE-1005, 1007 stay (they render the card directly); 979, 982, 995, 955, 957, 1001, 1008 stay.
- [x] Not done (owner may ask later): a guard on `app.record_unit_cleaning_charge` so a direct API call cannot still record a charge; the route stays usable with the button hidden.

### Task 6: Docs, features, traceability, differences

- [x] `docs/002_BUSINESS_RULES.md`: "Amended for Parking (owner, 2026-10-30)" paragraphs under §11 Pet Deposit, BR-SETTLE-005, BR-UNIT-001 (features), BR-UNIT-014 and BR-MOVEOUT-013 (cleaning), BR-UNIT-015 (Required Services, per the owner's answer).
- [x] `docs/004_DATABASE_MODEL.md` (migration 257, the one edited check), `docs/005_API_SPECIFICATION.md` (routes stay; screens hidden), `docs/replica/features.csv` (switched-off rows marked), `ops/traceability.json` (+ new TEST-FE ids, + database test), `docs/replica/parking-differences.md` (Step 5 section: five flags, migration 257, every skipped test id).
- [x] `docs/replica/step-5-ledger.md` with rulings.

### Task 7: Checks and report

- [x] `make frontend-test`, `make backend-test`, `make database-test` (fresh throw-away database), `make lint typecheck`, `make frontend-build` → same known failures, no new failures.
- [x] `parity.py docs/replica/features.csv` → 100; `sweep.py . --avoid "Unit Type,Unit,Property Rental,CHETANA Residence"` → no staff-visible hits.
- [x] `/code-review`; fix findings; report (what changed, test results per group, could not do, questions); STOP, no commit, no push.

## Owner answers (2026-10-30, after the plan)

- Size (m²): hide. View: hide, with its Settings "Views" card. Notes: keep. Floor: keep (owner adds Floors in Settings before the first Parking). Required Services: keep, empty by default.
- So `HOME_FIELDS` covers Size, Bedrooms, Bathrooms, View, Kitchen (inputs, facts, subtitle, Settings "Views" and "Kitchens" cards). Notes stays.
- Cleaning charge: migration 257 approved (turns off only the cleaning-charge check in the settlement preview). Database test: a move-out with no cleaning charge closes; an old cleaning charge still counts as a normal debt.
- Pet deposit: a test confirms a full move-out and settlement with no pet deposit is exact to the cent.
- Khmer vehicle words (Step 4): approved. `parking-differences.md`: commit with Step 5.
