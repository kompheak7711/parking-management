# Step 4: Vehicles — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Lease of a Parking holds one vehicle at a time. The vehicle, not a person, is what moves in and moves out; the people who sign keep Property Rental's signer rules. A vehicle is a record under a Customer (type, plate as typed in Khmer or Latin). Changing the vehicle keeps the history and the Lease.

**Architecture:** Reuse the Occupancy machinery (hidden names `occupancy`, `occupant` stay). New table `app.vehicles` under `app.customers`. New nullable column `app.occupancies.vehicle_id`: an Occupancy row with a vehicle is "this vehicle is parked here under this Lease"; its `customer_id` is the vehicle's owner. New SQL functions (Parking-only files, Property Rental's functions untouched): `app.record_lease_vehicle_move_in` and `app.change_lease_vehicle`. The Lease page's Occupants card becomes the Vehicle card; Record move-in picks a vehicle; a Change vehicle dialog replaces Move out. The Customer page gets a Vehicles card.

**Tech Stack:** Alembic migration, FastAPI, React/Vitest, pytest on a throw-away PostgreSQL.

**Spec:** owner's first message, Step 4; owner's message of 2026-10-29 (Step 4 planning); the Occupants trace (this session, 2026-10-29).

## Global Constraints

- One Lease = one Parking = one vehicle at a time. A second vehicle is refused while one is moved in. The only vehicle never moves out alone: only when a new vehicle moves in (Change vehicle), or when the Lease is terminated (the Move-out page, as today).
- Changing the vehicle: the old vehicle's row gets its move-out day, the new vehicle's row starts the same day, in one database transaction; both rows stay (history); the Lease goes on, its version moves on, History shows the change.
- Vehicle types: car, motorbike, tuk-tuk, food cart. Plate: as typed, Khmer or Latin, no transliteration, 1–32 characters after trimming. A duplicate plate (same letters and digits, spaces/dashes/dots ignored, case ignored) warns and never merges.
- Hidden names stay: `occupancy`, `occupant`, `reservations.complete`, routes `/leases/{id}/occupancies`, `/occupants`. New hidden names: `vehicle`, `vehicle_id`, `app.vehicles`.
- Property Rental's functions and constraints are not edited, with one exception explained in Task 1: the people-only exclusion constraint gets `WHERE vehicle_id IS NULL` so the same owner's two vehicles may hand over on the same day.
- Screen words: "Vehicle", "Move in vehicle", "Change vehicle", "Move out vehicle" (only on the Move-out page, where the Lease ends). People's signer rules, Signers card, Termination and Move-out unchanged.
- Money: none. No new packages. No push. Tests first.
- Owner answers of 2026-10-30: (Q1) no photos or documents in Step 4, type and plate only; (Q2) each vehicle type parks only in its own kind of place: Car → Covered or Uncovered; Motorbike → Motorbike; Tuk-tuk and food cart → Tuk-Tuk/Food Cart. Matched by the Parking Type **code** (`app.unit_setup_items.code`, which Settings cannot change: `protect_unit_setup_item` keeps it) in one SQL function `app.vehicle_type_allowed(vehicle_type, unit_type_code)`. A Parking Type added later has a code the function does not know: no vehicle type may move into it until its code is added to the function (one line). Checked at move-in and at Change vehicle; refusal `VEHICLE_TYPE` with an English and a Khmer message.
- The three assumptions are confirmed: the vehicle's owner is the Primary Tenant or a Signer; the people lists ("Other occupants", "Add occupant", "Who moves in") are hidden on Parking screens with the code kept behind `PEOPLE_MOVE_IN = false` (`frontend/src/leases/parking.ts`); a vehicle is corrected, never deleted.

## Assumptions (confirmed by the owner, 2026-10-30)

- A vehicle moved in under a Lease must belong to one of the Lease's people (the Primary Tenant or a Signer). Reason: Occupancy rows need a Customer, and the Lease's money and letters name those people.
- Before the move-in, the Lease form's "Other occupants" (people) and the Lease page's "Add occupant" are hidden on Parking screens; code stays. People never move in on Parking.
- A vehicle record is corrected, never deleted; a wrong one stays in the Customer's list (History keeps it). A "Remove" can come later if asked.

## Review Focus

1. Same owner, two vehicles, change on the same day: the people exclusion must not refuse it; the vehicle exclusion (half-open range) must let the old one end and the new one start on that day.
2. The old per-person move-out route called on a vehicle row: must answer 409 `VEHICLE_ONLY_ONE`, never move the vehicle out.
3. Termination and Move-out page: the hand-back lists the vehicle (plate), ends its Occupancy, the Parking becomes free as today.
4. A plate typed in Khmer digits/letters with spaces: stored as typed; the match key still finds the duplicate typed without spaces.
5. Record move-in with no vehicle on the people, or a vehicle of another Customer: refused with a clear code, not a 422 with no words.

---

### Task 1: Migration 256 — vehicles and vehicle occupancies (TDD)

**Files:** Create `backend/migrations/versions/20270406_256_vehicles.py`; Test `backend/tests/test_vehicles_migration.py`; Modify `scripts/database-test.sh`, head asserts (→ 20270406_256).

**Produces:** `app.vehicles(id, customer_id → customers, vehicle_type CHECK IN ('CAR','MOTORBIKE','TUK_TUK','FOOD_CART'), plate_text text 1–32 trimmed, plate_match_key text GENERATED (upper, spaces/dashes/dots removed), version, created_at/by, updated_at/by)`; no delete (trigger like customers); revisions table append-only; runtime role writes only through `app.create_vehicle`, `app.update_vehicle` (version check, plate/type corrections). `app.occupancies.vehicle_id uuid NULL → vehicles`; partial unique index "one open vehicle per Lease" (`lease_id WHERE move_out_date IS NULL AND vehicle_id IS NOT NULL`) and "a vehicle is parked under one Lease at a time" (`vehicle_id WHERE move_out_date IS NULL`); exclusion `occupancies_vehicle_lease_period_exclusive (lease_id, vehicle_id, daterange(move_in_date, move_out_date, '[)'))`; the people exclusion recreated with `WHERE vehicle_id IS NULL`. `app.record_lease_vehicle_move_in(…)` does the vehicle checks (owner is a Signer of the Lease `VEHICLE_NOT_OF_LEASE`; type allowed in the Parking's type `VEHICLE_TYPE`; vehicle not parked elsewhere `VEHICLE_PARKED`; no open Occupancy on the Parking `VEHICLE_SECOND`) and then **calls Property Rental's `app.record_signed_lease_move_in` as it is** with one occupant (the owner); a new BEFORE INSERT trigger on `app.occupancies` fills `vehicle_id` from the transaction setting `app.occupancy_vehicle_id` (the `set_config` precedent of `app.lease_signer_actor_id`), so the move-in checks, the idempotent replay, `lease_move_ins` and the link row stay Property Rental's. The same trigger refuses a change of `vehicle_id` on UPDATE. `app.change_lease_vehicle(p_lease, p_expected_version, p_new_vehicle, p_day, p_actor, p_reason)` (Lease SIGNED, exactly one open vehicle Occupancy, new vehicle ≠ old, owner rule, day between the old move-in day and today, not after End Date; ends the old row, inserts the new row, Lease version +1, append-only `app.lease_vehicle_changes(old_occupancy_id, new_occupancy_id, reason, …)`). Refusal hints: `VEHICLE_SECOND`, `VEHICLE_NOT_OF_LEASE`, `VEHICLE_TYPE`, `VEHICLE_PARKED`, `VEHICLE_NONE_IN`, `VEHICLE_SAME`, `VEHICLE_DATE`. Vehicle writes are audited in `app.audit_events` (`vehicle.created`, `vehicle.updated`, so they show in the Customer's History); no vehicle revisions table. Forward-only.

- [ ] Tests first (watch each fail): a vehicle is made under a Customer with type and plate as typed; type outside the four is refused; the match key ignores spaces, dashes, dots and case; two vehicles may share a plate (warning is the API's job); a vehicle is never deleted and only the functions write it; move-in with a vehicle writes one Occupancy with the vehicle; a second vehicle while one is in is refused; a vehicle of a Customer not on the Lease is refused; change vehicle on the same day keeps both rows and the Lease, moves the version on, writes the change row; change with none moved in is refused; the old per-person function on a vehicle row is not what the API calls (API test in Task 2); Termination's `physical_move_out_record` ends the vehicle row; head and forward-only.
- [ ] Migration; GREEN on the throw-away database; `scripts/database-test.sh` lists the file.

### Task 2: API (TDD)

**Files:** Create `backend/src/property_rental/vehicle_api.py` (+ `vehicle.py` domain); Modify `lease_api.py` (move-in body takes `vehicle_id`; new route `POST /leases/{id}/vehicle-change`; per-occupant move-out answers 409 for a vehicle row; occupancy rows carry `vehicle` {id, type, plate}), `api_refusals.py`, `access_control.py` labels (none new), `test_initial_owner_bootstrap_cli.py` route inventory, `ops/traceability.json`.

**Produces:** new file `vehicle_api.py` (+ `vehicle.py`): `GET /customers/{id}/vehicles`, `POST /customers/{id}/vehicles` (`vehicle_id`, `vehicle_type`, `plate_text`; 201), `PATCH /vehicles/{id}` (If-Match), `GET /properties/{id}/vehicles?plate=` (the duplicate check before saving: every vehicle with the same match key). The move-in picker reads each Signer's vehicles with `GET /customers/{id}/vehicles`. `lease_api.py`: `POST /leases/{id}/vehicle-move-in` and `POST /leases/{id}/vehicle-change` (new routes, Property Rental's `/move-in` untouched); `OccupancyResource` gains `vehicle_id`, `vehicle_type`, `plate_text` (null for a person); the per-occupant move-out of a vehicle row answers 409 `VEHICLE_ONLY_ONE` before the database is asked; History gains `lease.vehicle_changed` with "{old plate} → {new plate}: {reason}". Commands and the service live in the new `lease_vehicle.py`. Capabilities: read `customers.read`; vehicle write `customers.manage`; move-in/change `reservations.complete`. Refusals (api_refusals.py, rule BR-VEH-001…): `VEHICLE_SECOND` 409, `VEHICLE_NOT_OF_LEASE` 409, `VEHICLE_TYPE` 409, `VEHICLE_PARKED` 409, `VEHICLE_NONE_IN` 409, `VEHICLE_SAME` 422, `VEHICLE_DATE` 422, `VEHICLE_ONLY_ONE` 409. History text `e_lease.move_in` becomes "Vehicle moved in".

- [ ] Tests first: each route's capability, browser checks, If-Match, 422 shapes (type, plate length, blank, over 32), `same_plate` present for a duplicate and empty otherwise, move-in needs exactly one vehicle, the refusal codes, move-out of a vehicle row 409.
- [ ] Implement; GREEN; full backend suite.

### Task 3: Screens (TDD)

**Files:** `customerClient.ts` (vehicle types and the four calls on `CustomerApi`; no new client file), `customers/CustomerDetail.tsx` (Vehicles card: type, plate, Add vehicle / Edit), `customers/CustomerDialogs.tsx` (`VehicleDialog`: type, plate; before saving it looks the plate up and shows "Another vehicle has this plate: {owner}" with the button "Save anyway"), `leases/parking.ts` (`PEOPLE_MOVE_IN = false`), `leases/LeaseDetail.tsx` (Vehicle card replaces the Occupants card: "No vehicle moved in yet"; plate, type, owner, "Moved in {day}"; past vehicles "moved out {day}"; "Change vehicle"; no Add occupant, no per-vehicle Move out), new `leases/VehicleDialogs.tsx` (`MoveInVehicleDialog`: day, the Signers' vehicles, note, and a link to the Customer page when none; `ChangeVehicleDialog`: new vehicle, day, reason), `LeaseForm.tsx` ("Other occupants" behind the flag), `moveout/HandBackDialog.tsx` (plate from the Lease's Occupancy), `leases/text.ts`, `customers/text.ts`, `shell/serverText.ts` (Khmer for the new codes); tests in `LeasesPage.test.tsx`, `CustomersPage.test.tsx`, `leaseClient.test.ts`, `customerClient.test.ts` (TEST-FE-1127 onward). Property Rental's people tests that need the hidden lists are switched off with `it.skip` and a comment naming the flag.

- [ ] Tests first: Vehicles card lists and adds a vehicle; duplicate warning shows the owner and still saves on a second press; Lease page states; Record move-in with a vehicle; Change vehicle sends the new vehicle and the day, History says "Vehicle changed: {old plate} → {new plate}"; no Move out button on the vehicle; Termination hand-back shows the plate.
- [ ] Implement; GREEN; full frontend suite.

### Task 4 (Q1): none — the owner chose (a), no photos or documents in Step 4.

### Task 5 (Q2): in Task 1 (`app.vehicle_type_allowed`) and Task 2 (`VEHICLE_TYPE`).

### Task 6: Docs, feature list, checks, review, report

- [ ] docs/002 BR-VEH-001… (new rules), BR-OCC-010 amended for Parking; docs/001, 004, 005; features.csv; traceability; ledger.
- [ ] `make frontend-test backend-test database-test lint typecheck format-check`; parity; sweep; `/code-review`; report; STOP; no push.
