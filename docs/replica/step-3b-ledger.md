# Step 3b ledger — Property Rental V1-061 sync (plan: docs/replica/step-3b-plan.md)

Pre-flight: Task 5 produces migration 20270405_255 and the UnitType codes that Task 6 and the
fixtures consume; Task 6 extends Property Rental's `rent-terms` API (Task 2) instead of the
reverted Parking `default-rent` API. No other shared interfaces.

Task 1: complete. Branch step-3b-sync; revert of 31caa4e0 (e3fc7d56).
Task 2: complete. 18 cherry-picks (3460c2dc..c73a3b1b area); conflicts in 10 files resolved with
  Property Rental's side plus the Step 2 words.
  Ruling: conflict hunks take Property Rental's text and only the Step 2 word rules — never a
  reworded sentence — so the next sync meets the same shape. Cost if wrong: a screen word missed
  (the sweep and the word tests catch it).
Task 3: complete. 12 files renamed by the Step 2 script plus 4 misses the script cannot see
  (3 regex literals, 1 nested template string).
  Ruling: `backend/src/property_rental/lease.py` REQUIRED_SERVICE_MISSING keeps "...of the Unit":
  it must equal the PostgreSQL RAISE text of migration 251 (hidden name); the screen text lives in
  api_refusals.py. Cost if wrong: none on screen.
  Ruling: `access_control.py` capability labels and migration 251 strings keep "Unit", as Step 2
  left their siblings (labels are seeded into the database by migrations). Cost if wrong: a role
  screen shows "Unit" in a capability label; the owner may ask for a rename in Step 5.
  Ruling: backend test data strings (memo, notes) keep "Unit": not screen words.
Task 4: complete, no change needed. `start-test-app.sh` uses only `common.sh` helpers, already
  on pkm / 5433 / 8001 / 5174 since Step 1.
Task 5: complete. Migration 20270405_255 (seed function only); tests RED→GREEN on a fresh
  throw-away database; UnitType members COVERED/UNCOVERED/MOTORBIKE/TUK_TUK_FOOD_CART; fixture
  hunks of 31caa4e0 re-applied three-way, head asserts resolved to 20270405_255 (21 files).
  Ruling: the "existing Property gains the four" test seeds twice instead of deleting items
  (`protect_unit_setup_item` forbids DELETE). Cost if wrong: none; the function is the same.
Task 6: complete. Reason required on PUT /units/{id}/rent-terms (422 when missing, blank or
  over 500), audit reason, timeline actor_name; dialog reason box; History line.
  Ruling: the reason is required on every Rent and Services save (price or Services alike):
  one dialog, one save. Cost if wrong: staff type a reason for a Services-only change.
  Ruling: a New Parking's first price carries the fixed reason "Set with the new Parking"
  (precedent: "Lease drafted from the New Lease form"). Cost if wrong: one History line reads
  generic.
  Ruling: the permission stays Property Rental's `_require_manager` (a Manager or the Owner),
  not Step 3's `settings.manage`; the owner's latest brief lists only seeds, words, reason and
  History as Parking-only parts. Cost if wrong: one line to change.
  Ruling: a Services-only change shows "Rent and Services changed by {who}: {reason}" (new
  Khmer string written by Claude, needs the owner's check); a price change shows the Step 3
  line. Cost if wrong: wording only.
Task 7: complete. Docs 001/002/004/005 amended; features.csv +19 rows; traceability +6, one
  renamed.
  Ruling: Tasks 3, 5, 6 and 7 go in one commit: unit_api.py, units/text.ts and
  UnitsPage.test.tsx carry hunks of all three. Cost if wrong: a coarser cherry-pick later.
Task 8: /code-review medium on fac4fe48..HEAD: 7 findings.
  Final: fixed timeline parser dropped actor_name — TEST-FE-1126 RED→GREEN.
  Final: fixed "Say why the price changes." shown for a Services-only change — TEST-FE-1124
  extended RED→GREEN; the plain "Give the reason for the change." is used when the price is as it
  was (reason still required, see the Task 6 ruling).
  Final: Ruling: New Parking's fixed English reason "Set with the new Parking" stays on the client;
  a backend notion of "first price" is a design change for the owner to ask for. Cost if wrong:
  one History line in English on a Khmer screen.
  Final: Ruling: migration 255 re-seeds existing Properties with actor = property.created_by, as
  Property Rental's own seed migrations do; Parking's database has no Property yet. Cost if wrong:
  four audit rows named after the Property's creator.
  Final: minor (deferred): reason trimming re-implemented instead of a shared StringConstraints
  alias (the file already does the same in UnitPatch).
  Final: minor (deferred): History actor name by correlated subselect instead of a LEFT JOIN.
  Final: minor (deferred): docs keep Property Rental's text plus an "Amended for Parking"
  paragraph (Step 2 and Step 3 practice, so future Property Rental doc changes copy cleanly).
