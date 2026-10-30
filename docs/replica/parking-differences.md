# Where Parking differs from Property Rental (on purpose)

Parking Rental is a copy of Property Rental. Hidden code names (`unit`, `unit_type`, `lease`,
`occupant`, `occupancy`, the `property_rental` package, table, column, function and file names,
routes, API paths, test ids) are the same in both apps, so a Property Rental fix can be copied
(cherry-picked) into Parking. This file lists every place where Parking differs on purpose, so
that whoever copies a fix knows what to re-check. Keep it updated in every step.

Source of truth for each step: `docs/replica/step-N-plan.md` and `step-N-ledger.md`.

Last updated: Step 4 (2026-10-30), branch `step-4-vehicles`, commit `89b2c8ad`.

## How to use it when copying a Property Rental fix

1. Cherry-pick the Property Rental commit. Resolve conflicts with Property Rental's side.
2. Re-apply the Step 2 word rules to the new strings (script `rename_words.py`; see Step 2 below).
3. Walk this list: every row whose files the commit touched needs a look.
4. Run every test group on this Mac (`make frontend-test backend-test database-test lint typecheck`).
5. If the fix adds a migration, its revision must come after Parking's own migrations (255, 256);
   set `down_revision` to Parking's head, and move the head pins in `backend/tests` (see Step 3b).

## Step 1: operational names and ports (commit 9ecc43b2)

| What differs | Parking value | Where | When copying a fix |
| --- | --- | --- | --- |
| Business and app name on screens | CHETANA Parking / Parking Rental | `frontend/src/**/text.ts`, `index.html`, `app.py` title, letters, PDF author, TOTP issuer | New strings with "CHETANA Residence" or "Property Rental" get the Parking name. |
| Ports | PostgreSQL 127.0.0.1:5433, API 8001, Vite 5174 | `compose.yaml`, `.env.example`, `Makefile`, `frontend/vite.config.ts`, `scripts/local/*` | Any new script or config with 5432 / 8000 / 5173 must use Parking's ports. |
| Database name, Compose project, volume | `pkm`, `parking-management`, `parking-management_postgres_data` | `compose.yaml`, `scripts/local/common.sh`, `scripts/database-test.sh` (project `pkm-database-test-<pid>`) | Same. |
| Package and command names | `parking-backend`, `parking-frontend`, `parking-backup`, `parking-ops-check`, ... | `backend/pyproject.toml`, `frontend/package.json` | Same. |
| Host folders and jobs | `/usr/local/etc/pkm`, `/usr/local/libexec/pkm`, `/var/lib/pkm`, `/var/log/pkm`, systemd units `pkm-*`, user `pkm-ops` | `config/deployment/*`, `config/deployment/host/*` | Same. |
| Tests that assert names | updated, never deleted | `backend/tests/test_local_run_scripts.py`, `test_auth_flow`, `test_deployment_scaffolding` | A Property Rental test that asserts `prm` / 8000 is updated to the Parking value. |
| Kept as in Property Rental | `prm_*` database roles, `/run/secrets/prm_*` secret file names, `prm.sign_in_prune` setting, `settings.py` `service_name` default | migrations, `compose.yaml` | Nothing to do. |

## Step 2: screen words (commits a1af0f2f, c1b81f3b)

Only words staff see. Rules (owner 2026-10-29), full list in `docs/replica/step-2-words.md`:

| English before | English after | Khmer before | Khmer after |
| --- | --- | --- | --- |
| Unit / Units | Parking (one word for one and many) | បន្ទប់ | ចំណត |
| Unit Type(s) | Parking Type(s) | ប្រភេទបន្ទប់ | ប្រភេទចំណត |
| Unit inventory, Unit features | Parking inventory, Parking features | unchanged | unchanged |
| Unit price (Invoice line), Kitchen, Bedrooms, Bathrooms | unchanged | ឯកតា, ផ្ទះបាយ, own words | unchanged |

Kept with the "Unit" text on purpose (not screen words, or the database writes or raises them):

- Backend lookup keys that must equal a PostgreSQL `RAISE` text or a seeded row (22 texts in 14
  files, for example `invoice_api.py` cleaning-charge refusals, `lease_signing_api.py`,
  `draft_record_api.py`, `lease.py` REQUIRED_SERVICE_MISSING). The staff-facing
  `Refusal.message` in `api_refusals.py` says "Parking".
- Capability labels and descriptions in `access_control.py` (seeded by migrations 176 and 220).
- Docstrings, route docstrings, comments, test ids, SQL fixture names, test data strings.
- The Invoice line "Unit cleaning charge" written by the database function of migration 81
  (visible; Step 5 switches the charge off).
- `history/text.ts` `actionText` shows the action code `unit` as "parking" (one helper, Parking only).
- `utility_sheet.py`: the downloaded readings file header says "Parking"; upload accepts "Parking"
  and "Unit".
- `unit_api.py` default audit reason says "Parking source data changed through the authorized
  Parking API".

When copying a fix: run `rename_words.py` on the new string literals, then hand-check regex
literals and nested template strings (the script cannot see them), and never rename a string
that a migration raises or seeds.

## Step 3b: Parking Types, price reason, sync with Property Rental V1-061 (commits 2724112a..565fd7bd)

| What differs | Where | When copying a fix |
| --- | --- | --- |
| Migration `20270405_255`: the seed function `app.seed_unit_setup_items` seeds four Parking Types (codes COVERED, UNCOVERED, MOTORBIKE, TUK_TUK_FOOD_CART) instead of the four Unit Types of BR-UNIT-001, and no Balcony Room feature. | `backend/migrations/versions/20270405_255_parking_types.py` | A Property Rental change to the seed list is not copied; Parking keeps its own. |
| Head pins: backend tests assert Alembic head and UnitType members. | `backend/tests/unit_type_support.py`, `test_parking_types_migration.py`, 20+ `test_*_migration.py` files pin the head (now `20270406_256`) | A new Property Rental migration lands after Parking's; move the pins. |
| Reason required on "Rent and Services" (PUT `/units/{id}/rent-terms`): 422 when missing, blank or over 500; kept in the audit row; History shows "Default monthly price {old} → {new} by {who}: {reason}" or "Rent and Services changed by {who}: {reason}"; timeline rows carry `actor_name`. A new Parking's first price carries the fixed reason "Set with the new Parking". | `backend/src/property_rental/unit_api.py` (`reason` field, `actor_name`), `frontend/src/units/RentTerms.tsx`, `units/UnitDialogs.tsx`, `units/text.ts` (`h_rent_terms_by`, `h_price`, `rt_reason_req`, `reason`) | A Property Rental change to rent-terms must keep the reason parameter. |
| Step 3 (`31caa4e0`, a separate `default-rent` API) was reverted; Property Rental's `rent-terms` is the base. | branch `step-3-parking-price` (superseded) | Nothing to do. |
| Khmer strings written by Claude for the reason and History lines (owner check pending). | `units/text.ts` | Nothing to do. |

## Step 4: vehicles (commit 89b2c8ad)

| What differs | Where | When copying a fix |
| --- | --- | --- |
| Migration `20270406_256`: table `app.vehicles`, column `app.occupancies.vehicle_id`, table `app.lease_vehicle_changes`, functions `app.vehicle_type_allowed`, `app.check_lease_vehicle`, `app.create_vehicle`, `app.update_vehicle`, `app.record_lease_vehicle_move_in`, `app.change_lease_vehicle`, trigger `occupancies_guard_vehicle`. Forward-only. | `backend/migrations/versions/20270406_256_vehicles.py` | A Property Rental migration that changes `app.occupancies` or `app.record_signed_lease_move_in` must be checked against the trigger and the wrapper function. |
| **The one edited Property Rental object:** constraint `occupancies_customer_lease_period_exclusive` is dropped and re-created with `WHERE (vehicle_id IS NULL)` (people rows only), so the same owner's two vehicles can hand over on the same day. | same migration | A Property Rental migration that re-creates this constraint must keep the `WHERE`. |
| Vehicle type rule BR-VEH-001: match by Parking Type code (COVERED/UNCOVERED → CAR, MOTORBIKE → MOTORBIKE, TUK_TUK_FOOD_CART → TUK_TUK or FOOD_CART). A Parking Type added later allows no vehicle until its code is added to `app.vehicle_type_allowed` (one line, new migration). | same migration; `docs/002_BUSINESS_RULES.md` | Nothing to do. |
| New backend modules and routes: `vehicle.py`, `vehicle_api.py`, `lease_vehicle.py`; routes under `/customers/{id}/vehicles`, `/vehicles/{id}`, `/properties/{id}/vehicles?plate=`, `/leases/{id}/vehicle-move-in`, `/leases/{id}/vehicle-change`; refusals VEHICLE_* in `api_refusals.py`; `lease_api.py` OccupancyResource gains `vehicle_id`, `vehicle_type`, `plate_text`, timeline event `lease.vehicle_changed`, per-occupant move-out refuses a vehicle row. Route inventory test updated. | `backend/src/property_rental/{vehicle,vehicle_api,lease_vehicle,lease_api,app,api_refusals}.py`, `backend/tests/test_initial_owner_bootstrap_cli.py` | A Property Rental change to `lease_api.py` occupancy queries or move-out must keep the vehicle columns and the VEHICLE_ONLY_ONE path. |
| Business snapshot test excludes `vehicle_id` (precedent: migrations 64 and 227). | `backend/tests/test_lease_notices_migration.py` | Keep the exclusion. |
| `PEOPLE_MOVE_IN = false` hides the people lists (Other occupants, Add occupant, Who moves in, per-person Move out). Code kept. Ten Property Rental tests skip when the flag is off: TEST-FE-855, 861, 1118, 1025, 1026, 1027, 1028, 1029, 1112, 1113. TEST-FE-845 and 857 lost only their people assertions. | `frontend/src/leases/parking.ts`, `leases/LeaseDetail.tsx` (the old Occupants card is re-indented behind the flag: expect a conflict there), `leases/LeaseForm.tsx`, `leases/LeasesPage.test.tsx` | A Property Rental fix to the Occupants card merges into the gated block; a new people test gets the same `skip(!PEOPLE_MOVE_IN)`. |
| New screens: Vehicles card and dialog on the Customer page; Vehicle card, move-in pick and Change vehicle dialog on the Lease page; hand-back lists the vehicle by plate; History "Vehicle moved in" / "Vehicle changed". Toast and History line for move-in read "Vehicle moved in". | `frontend/src/customers/{CustomerDetail,CustomerDialogs}.tsx`, `customers/text.ts`, `leases/VehicleDialogs.tsx`, `leases/LeaseDetail.tsx`, `leases/text.ts` (`moved_in_toast`, `e_lease.move_in`), `moveout/HandBackDialog.tsx`, `customerClient.ts`, `leaseClient.ts` (`vehicleCommand`, `LeaseRefusedError`), `shell/serverText.ts` | Property Rental's `leaseCommand` 409/412 handling is unchanged; only the two vehicle commands use `vehicleCommand`. |
| Khmer strings for vehicles written by Claude (owner check pending). | `customers/text.ts`, `leases/text.ts`, `shell/serverText.ts` | Nothing to do. |
| Docs amended: 001 (Occupant), 002 (BR-OCC-010, BR-VEH-001), 004 (DB-LEASE-003, DB-VEH-001), 005 (Parking Step 4 paragraph); `features.csv` +10 rows; `ops/traceability.json` +26. | `docs/` | Docs keep Property Rental's text plus an "Amended for Parking" paragraph, so Property Rental doc changes copy cleanly. |

## Step 5: switch off what Parking doesn't use

| What differs | Where | When copying a fix |
| --- | --- | --- |
| Five screen flags, all `false`: `PET_DEPOSIT`, `UNIT_INVENTORY`, `ROOM_FEATURES`, `HOME_FIELDS` (Size, Bedrooms, Bathrooms, View, Kitchen), `CLEANING_CHARGE`. Inputs and always-on texts render behind `FLAG &&`; rows that show existing data stay data-driven (an existing Pet Deposit or cleaning charge still shows and settles). | `frontend/src/leases/parking.ts` | A Property Rental fix inside a gated block merges into the block; a new input for one of these things gets the same flag. |
| **The second edited Property Rental object:** migration `20270407_257` rewrites `app.final_settlement_preview(uuid,uuid,uuid,text[])` with `pg_get_functiondef` + replace so the cleaning check reads `IF false AND v_moved_in AND v_move_out.id IS NOT NULL AND NOT EXISTS(...)`. Exactly one match or the migration refuses. Forward-only. Nothing else in the function changes; no table, rate or charge function changes. | `backend/migrations/versions/20270407_257_cleaning_charge_off.py` | A Property Rental migration that rewrites `app.final_settlement_preview` (as 169, 174, 206, 238, 247 did) puts the check back. Add a new Parking migration after it that applies the same `_patch`, or Parking move-outs block again with `CLEANING_CHARGE_MISSING`. `test_the_preview_source_has_the_cleaning_check_switched_off` catches it. |
| Head pins moved `20270406_256` → `20270407_257` (22 test files; `test_vehicles_migration.py` keeps `get_revision("20270406_256")`). | `backend/tests/` | A new Property Rental migration: its `down_revision` follows Parking's head; move the pins. |
| `test_a_moved_out_lease_waits_for_final_utility_cleaning_and_billed_periods`: the cleaning expectations are `[]` (Property Rental expects `[("NO_RATE", None)]` then `[("NOT_ISSUED", 2_500)]`); the rate and charge steps still run. | `backend/tests/test_final_settlement_preview_migration.py` | Expect a conflict on those four asserts; keep `[]`. |
| New database test file (in `scripts/database-test.sh` after the preview test): no-rate/no-charge move-out is ready; an existing cleaning charge is a normal debt; a full settlement with no Pet Deposit is exact to the cent; head pin; function source check. | `backend/tests/test_cleaning_off_migration.py` | Nothing to do. |
| Update Parking omits hidden fields from the PATCH body (`detailsFrom` returns `Partial<UnitDetails>`), because `unit_api.py` clears a field it receives as null and keeps one left out. New Parking omits them too (`UnitCreate` has defaults). | `frontend/src/units/UnitDialogs.tsx` | A Property Rental change to `detailsFrom` or to the Unit create/update body merges here; keep the omission. |
| Settings "Parking setup" tab filters its cards (`shownOnParking`): Views and Kitchens behind `HOME_FIELDS`, Room features behind `ROOM_FEATURES`; `unitSetupListKinds` itself is unchanged (the parser checks it). The Parking Type note has no cleaning-rate sentence (`cf_type_note_parking`); the "No cleaning rate" read is skipped. | `frontend/src/settings/UnitSetupTab.tsx`, `settings/text.ts` | Keep the filter around `unitSetupListKinds.map(card)`. |
| Text variants with an "off" key: `units/text.ts` `new_note_parking` (no inventory sentence), `settings/text.ts` `cf_type_note_parking`, `reports/text.ts` `d_deposits_security` (picked by `descriptionKey` in `ReportsPage.tsx`), `payments/text.ts` `c_MOVEOUT_s_parking` (picked in `PaymentsList.tsx`). Khmer written by Claude (owner check pending). | those files | A Property Rental change to the original key does not reach the `_parking` variant: copy it by hand. |
| Pet gating: `LeaseForm.tsx` (tick and field; a renewal of a Lease that has a pet keeps it and shows the tick, data-driven), `LeaseDetail.tsx` (`no_pet` line), `TerminateDialogs.tsx` (the VIOLATION sub-text), `moveout/InspectionDialog.tsx` (pet tick), `moveout/MoveoutPage.tsx` (`dep_none`), old screens `LeaseManagement.tsx` (pet fieldset; the Conditional Pet Deposit block shows only when a pet is on record) and `DepositManagement.tsx` (Create Pet Deposit form), `FinancialRefundWorkspace.tsx` (PET_DEPOSIT source), `CustomerLedgerEvidence.tsx` (Pet Deposit held row while 0), `reports/RegisterView.tsx` (PET kind while 0). Five words-only sentences on the old folded screens (`LeaseManagement.tsx`: move-in checklist line, follow-up notice, Approved Deposit terms paragraph; `DepositManagement.tsx`: help paragraph, loading notice) pick a no-pet wording behind `PET_DEPOSIT` (owner 2026-10-30; TEST-FE-1153, 1154). | listed | Merge into the gated blocks. |
| Cleaning gating: `MoveoutPage.tsx` (`mayRate` false so the rate is never read; `cleaningSettled` true; the Cleaning charge section shows only for a charge that exists), `settings/RatesTab.tsx` (no Cleaning rates card). **Open note (owner 2026-10-30):** `app.record_unit_cleaning_charge` and its API route are not guarded; a direct API call can still record a cleaning charge on Parking, and such a charge then shows and settles as a normal debt. The screen button is hidden. Guard it only if the owner asks. | listed | Merge into the gated blocks. |
| Property Rental tests that skip when a flag is off: TEST-FE-978, 1006 (`CLEANING_CHARGE`); 202, 210, 529, 530 and the PET_DEPOSIT case of 443 (`PET_DEPOSIT`); `ops/traceability.json` keeps their entries unchanged (its early entries are hash-checked by `test_traceability.py`); the skip is recorded here and in the TEST-FE-1152 entry. Tests that run with only their pet or home-field step behind a flag: TEST-FE-029, 818, 940, 941 (Add/Remove use Parking Types instead of Views/Kitchens), 845, 857, 563, 974, 979, 191; 976 unchanged. New Parking tests: TEST-FE-1139 to 1152. | `frontend/src/**/*.test.tsx` | A new Property Rental test for one of these things gets the same `skip(!FLAG)`. |
| Docs amended: 002 (BR-UNIT-001, BR-UNIT-014, BR-UNIT-015, §11 Pet Deposit, BR-MOVEOUT-013, BR-SETTLE-005), 004 (preview paragraph), 005 (Step 5 paragraph); `features.csv` rows marked `skip` with "Step 5: switched off on Parking"; `ops/traceability.json` +19. | `docs/`, `ops/` | As Step 4. |

## Test and tooling differences

| What differs | Where |
| --- | --- |
| `scripts/database-test.sh` lists every `tests/test_*_migration.py`, including Parking's `test_parking_types_migration.py`, `test_vehicles_migration.py` and `test_cleaning_off_migration.py`. | `scripts/database-test.sh` |
| Known failures on this Mac (not fixed in Parking; fix belongs in Property Rental first): TEST-FE-894 (`blob.text`), `test_the_owner_set_up_says_whether_the_owner_was_made`, mypy `backup_job.py` POSIX_FADV_DONTNEED; one timing test (`assert 299 == 300`) can fail on a busy Mac. | `docs/replica/known-failures.md` |
| Git: remote `property-rental` is read-only for Parking (never push to it); `origin` is `kompheak7711/parking-management`. | `.git/config` |

## Not yet applied to the running Parking database

Migrations 251 to 257 are not yet applied to `parking-management-postgres-1` (database `pkm`,
at `20270331_250`). Run `make migrate` when the owner says so.
