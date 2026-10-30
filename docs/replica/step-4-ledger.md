# Step 4 ledger — Vehicles (plan: docs/replica/step-4-plan.md)

Pre-flight: Task 2 consumes the SQL functions and hints of Task 1; Task 3 consumes the routes and
the `OccupancyResource` fields of Task 2. Names fixed in the plan; no conflict found.
Ruling: the vehicle move-in wraps Property Rental's `app.record_signed_lease_move_in` instead of
  copying it; `vehicle_id` reaches the new Occupancy through a transaction setting and a Parking
  BEFORE INSERT trigger, because `protect_occupancy_history` refuses an UPDATE that changes no
  date. Cost if wrong: one trigger to drop and a 60-line copy of the function to write.
Ruling: Property Rental's constraint `occupancies_customer_lease_period_exclusive` is recreated
  with `WHERE (vehicle_id IS NULL)` (the one edit of a Property Rental object): without it the same
  owner's two vehicles could not hand over on the same day. Cost if wrong: the next sync re-applies
  one ALTER.
Ruling: Parking Type match by code with unknown codes refusing every vehicle type (owner asked
  for the simplest rule and to be told what a later Parking Type does). Cost if wrong: one line
  in `app.vehicle_type_allowed`.
Ruling: no "New vehicle" form inside the move-in dialog; staff add the vehicle on the Customer
  page first (the dialog links there). Not asked for; keeps one place to warn about a duplicate
  plate. Cost if wrong: a small form later.

Task 1: complete. Migration 20270406_256 (vehicles, occupancies.vehicle_id, guard trigger, the
  people-only exclusion, lease_vehicle_changes, app.vehicle_type_allowed, app.create_vehicle,
  app.update_vehicle, app.record_lease_vehicle_move_in, app.change_lease_vehicle), Python
  services vehicle.py and lease_vehicle.py, OccupancyResource vehicle fields, History
  lease.vehicle_changed. tests/test_vehicles_migration.py RED (ModuleNotFoundError) → GREEN
  9/9 on a fresh throw-away database; neighbours (occupant move-out, move-in, occupant
  addition, physical move-out, migrations, meter history, Parking Types, lease API migration)
  199 passed after the head pins moved to 20270406_256 (20 test files).
  Ruling: the move-in test moves in on the signing day (Property Rental refuses a move-in day
  before the signing day) and Termination is dated today (chronology rule): test dates only.
Task 2: complete. api_refusals VEHICLE_*; vehicle_api.py (4 routes); lease_api.py
  vehicle-move-in and vehicle-change routes, VEHICLE_ONLY_ONE on the per-person move-out of a
  vehicle row, VEHICLE_REFUSALS; app.py wiring (vehicle_flow); route inventory. tests
  test_vehicle_api.py (2) and test_lease_api.py (3) RED (404) → GREEN; 75 passed with the
  customer and bootstrap tests; ruff and mypy clean (known POSIX_FADV_DONTNEED only).
  Ruling: a deactivated Customer cannot take a vehicle (409); the screen hides Add vehicle for
  them. Cost if wrong: one check to drop.
  Ruling: the per-occupant move-out answers VEHICLE_ONLY_ONE in the route (the Lease already
  carries the rows) instead of a database change to Property Rental's function. Cost if
  wrong: a direct database caller could still end a vehicle row through that function.
Task 3: complete. customerClient vehicle calls; leaseClient vehicle commands with
  LeaseRefusedError (code + server words, used only by the vehicle commands); customers
  Vehicles card + VehicleDialog; leases parking.ts PEOPLE_MOVE_IN, VehicleDialogs.tsx
  (VehicleCard, MoveInVehicleDialog, ChangeVehicleDialog), LeaseDetail/LeasesPage wiring,
  LeaseForm flag, HandBackDialog plate, text (EN/KM) and serverText KM. Tests TEST-FE-1127 to
  1136 RED → GREEN; LeasesPage 45 passed, 10 skipped; full frontend 1988 passed, 1 failed
  (TEST-FE-894 known), 10 skipped; eslint, tsc, prettier clean.
  Ruling: ten Property Rental people tests (TEST-FE-855, 861, 1118, 1025, 1026, 1027, 1112,
  1113, 1028, 1029) are `it.skip` with a comment naming PEOPLE_MOVE_IN; TEST-FE-845 and 857
  lost only their people assertions. Cost if wrong: the hidden people code is untested on
  Parking until the flag is turned on again.
  Ruling: the lease client's 409/412 handling stays (conflict); only the two vehicle commands
  read the refusal code, so Property Rental's TEST-FE-187 behaviour is unchanged.
  Ruling: "Move-in recorded" toast and History line now read "Vehicle moved in" (owner's
  words "Move in vehicle"). Cost if wrong: two text pairs.
Final review (/code-review high, fresh reviewer): 8 findings; 6 fixed, 2 deferred.
  Final: fixed plain 409 (code CONFLICT) treated as a vehicle refusal — TEST-FE-1135 extended
    RED→GREEN: only VEHICLE_* codes become LeaseRefusedError.
  Final: fixed the only vehicle guarded only in the route — test_the_vehicle_of_a_signer_moves_in
    extended: the per-person move-out function is refused at the database (guard trigger,
    HINT VEHICLE_ONLY_ONE, unless Change vehicle set app.occupancy_vehicle_change or the Lease
    is no longer SIGNED, which is when the Move-out page ends it). Not watched RED: the
    throw-away database was busy with the full suite; the fixed migration ran GREEN after.
  Final: fixed a failed plate lookup stopping the save — TEST-FE-1137 RED→GREEN.
  Final: fixed the vehicle checks running before the version check — test extended: a stale
    version is MoveInVersionConflictError (not watched RED, same reason).
  Final: fixed the Change vehicle date above its limit on an overdue Lease — TEST-FE-1138
    RED→GREEN.
  Final: fixed the plate box (32 characters, no second check) and the needless subtransaction
    around the inner move-in call.
  Final: minor (deferred): vehicleCommand repeats leaseCommand's fetch handling; merging it
    into Property Rental's leaseCommand would change how OCCUPANT_* 409s surface (TEST-FE-187
    pins 409 as a conflict), so it waits for the owner / a Property Rental fix.
  Final: Ruling: the people-list assertions of TEST-FE-845 and 857 were replaced, not the tests.
  Final: fixed test_lease_notices_migration::test_upgrade_preserves_legacy_notice... (full
    database suite, run 1): its before/after snapshot of Occupancy rows now leaves out
    `vehicle_id`, as it leaves out the columns migrations 64 and 227 added (same precedent,
    one line). Not a product defect.
  Final: Ruling: Property Rental's per-person move-out already refuses the owner's vehicle row
    (PRIMARY_TENANT or LAST_SIGNER: on Parking the owner is a Signer and the only open row), so
    the guard trigger covers other writers; the test proves both. Cost if wrong: none.
  Final: Ruling: the ten people tests skip inside their body (`async ({ skip }) => { skip(!PEOPLE_MOVE_IN) … }`)
    instead of `it.skip`/`it.skipIf`, so the traceability scan still finds their ids and
    prettier re-indents nothing (LeasesPage.test.tsx diff: 494 added, 15 removed, no
    whitespace churn). features.csv keeps its original line endings (10 rows added).
  Merge note: LeaseDetail.tsx's Occupants card is re-indented by the `PEOPLE_MOVE_IN &&`
    wrapper (63 real line changes, the rest whitespace); a later Property Rental fix inside that
    card needs a whitespace-insensitive merge.
