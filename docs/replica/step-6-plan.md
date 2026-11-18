# Step 6: Sync Property Rental V1.1 and V1.2 into Parking — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parking carries every Property Rental change on `implementation/foundation` from after
cb887b88 up to 02e56aed (17 Nov 2026), in order, with Parking's own three migrations moved after
Property Rental's newest one, Parking words on every new screen, and the parts Parking does not
use hidden behind switches as in Step 5.

**Architecture:** Branch `step-6-sync-v1-2` (made from `step-5-switch-off` at 3030a5dc). First move
Parking's three migrations to new ids after Property Rental's head, then cherry-pick the 80
first-parent commits of `cb887b88..02e56aed` in order with `-x` (the 24 merge commits with `-m 1`,
so each brings its whole branch as Property Rental merged it). Resolve each conflict by taking
Property Rental's text and applying the Parking words. Then rebuild the Parking-only parts on top
(Parking Type seeds, vehicles, cleaning off, price reason), add the new switches, and check that
the result equals Property Rental at 02e56aed except for the Parking differences.

**Tech Stack:** git cherry-pick, Alembic/PostgreSQL, FastAPI/pytest, React/Vitest, replica-skill
parity and sweep.

**Spec:** owner Message 17 (17 Nov 2026); `docs/replica/step-3b-plan.md` and ledger (the sync
pattern); `docs/replica/step-4-plan.md` (vehicles), `docs/replica/step-5-plan.md` (switches);
`docs/replica/parking-differences.md` (every Parking difference and where it lives).

## Facts found while planning (17–18 Nov 2026)

- Range: 144 commits (80 on the first-parent line, 24 merges, 120 non-merge), 967 files,
  +247,828 / −14,398 lines. 02e56aed is fetched from the `property-rental` remote (fetch only).
- Property Rental now has 127 new migrations, numbered 255 to 430 with gaps. **Its head is
  `20270807_424_joint_inspection_copy`**, not 430: `20270806_430` sits before `20270804_422` in the
  chain (filename order is not chain order).
- **The clash is worse than the numbers.** Parking's three migrations use the *same revision ids*
  as Property Rental's: `20270405_255`, `20270406_256`, `20270407_257`. The Parking database pkm
  records `20270407_257` as done. After the sync that id means Property Rental's "Regular
  services", so a plain `alembic upgrade head` on pkm would skip Property Rental's 255, 256 and 257
  and break at 258. pkm needs the special path in Task 8.
- What Property Rental's new migrations touch that Parking also changed:
  - `app.seed_unit_setup_items` — rewritten by Property Rental 255 (Unit features, Feature types,
    Item types). Parking's seed (four Parking Types, no Balcony) must be rebuilt on top of it.
  - `app.record_signed_lease_move_in` — Property Rental 421 edits its body (who holds a Unit);
    its signature is unchanged, so Parking's `app.record_lease_vehicle_move_in`, which calls it,
    still fits.
  - `app.occupancies` — read by Property Rental 282, 361, 421; none changes the table, so
    Parking's `vehicle_id` column and `occupancies_guard_vehicle` trigger stay valid.
  - `app.final_settlement_preview` — **not touched** by any new Property Rental migration, so
    Parking's cleaning-off edit (an exact text replace) still finds its text.
- A one-shot trial merge (`git merge-tree`, nothing written) shows 77 files in conflict: about 30
  backend tests (mostly the pinned migration head), the Parking-worded screens (`units/`,
  `leases/`, `settings/`, `moveout/`, `reports/`, `shell/`), `docs/002_BUSINESS_RULES.md`,
  `ops/traceability.json`, `scripts/local/common.sh`, `scripts/local/start-api.sh`,
  `backend/pyproject.toml`, `backend/uv.lock`.
- New packages from Property Rental: `weasyprint` (PDF; needs system libraries on the Mac) and,
  for tests only, `@playwright/test`, `@axe-core/playwright`, `playwright-core`.
- The pkm container is not running now, so its rows were not counted (Task 8 step 1).

## Global Constraints

- Never touch `~/Development/property-rental-management`, its database, containers or backups.
  `property-rental` remote: fetch only.
- Do not touch `main` or `parking-v1-build`. No push until the owner says.
- Take all 80 first-parent commits in order, none skipped, none split; keep their messages
  (`cherry-pick -x`). Take nothing from other Property Rental branches.
- pkm (port 5433): never reset, never delete data, never drop. No change to pkm until the owner
  approves Task 8 after seeing the trial result.
- Screen words as Step 2 and 3b: "Unit" → "Parking", "Unit Type" → "Parking Type", Khmer បន្ទប់ →
  ចំណត, ប្រភេទបន្ទប់ → ប្រភេទចំណត; Vehicle words from Step 4. Never "unit price" (ឯកតា). Bedrooms
  and Bathrooms keep បន្ទប់គេង / បន្ទប់ទឹក. New Khmer written by Claude goes on the owner's check list.
- Hidden names unchanged: identifiers, routes, API paths, table, column and function names, test
  ids, docstrings, `prm_*` roles and helpers.
- Operational names stay Parking's: pkm, ports 8001 / 5174 / 5433, Docker project
  parking-management.
- Parking rule kept: a price change needs a reason (`PUT /units/{id}/rent-terms`, 422 without one)
  and History shows who, old, new and why.
- Step 5 switches stay off: `PET_DEPOSIT`, `UNIT_INVENTORY`, `ROOM_FEATURES`, `HOME_FIELDS`,
  `CLEANING_CHARGE`, and `PEOPLE_MOVE_IN` from Step 4.
- Hide with a switch, never delete: tables, functions, routes and tests stay. Every skipped test
  id is listed in `docs/replica/parking-differences.md`.
- Money in integer cents. Parking-only test ids continue after the highest id Property Rental uses
  at 02e56aed.

## Review Focus

1. pkm after the upgrade: same Customers, Vehicles, Agreements, Invoices, Payments and audit rows
   as before; four Parking Types; settlement preview still has Parking's `IF false AND`. Test:
   Task 8 trial compares row counts and checks before and after.
2. A vehicle moved in holds its Parking under the new "who holds a Unit" rule (DL-241), and a
   vehicle change (old occupancy ends, new one starts the same day) never shows the Parking as
   free. Test in Task 5.
3. A Joint Inspection at move-in and move-out works on an Agreement whose occupancy is a vehicle,
   and a Done move-out inspection still leads to a ready final settlement with no cleaning charge.
   Test in Task 5.
4. A hidden part does not leak: no menu item, Home card, Settings tab or link to General Ledger,
   HR, Telegram, short stays, Products/Quotations, Problem reports or Monthly services when their
   switch is off. Test in Task 6.
5. A price change still refuses an empty reason after Property Rental's V1.1 changes to the Rent
   and Services dialog. Test: existing Parking tests TEST-FE-1124..1126 and the backend 422 test
   stay green.

---

### Task 1: Move Parking's three migrations after Property Rental's head

**Files:** rename `backend/migrations/versions/20270405_255_parking_types.py` →
`20270808_431_parking_types.py`, `20270406_256_vehicles.py` → `20270809_432_vehicles.py`,
`20270407_257_cleaning_charge_off.py` → `20270810_433_cleaning_charge_off.py`.

**Interfaces:** Produces revision ids `20270808_431_parking` (down `20270807_424`),
`20270809_432_parking` (down `20270808_431_parking`), `20270810_433_parking` (down
`20270809_432_parking`). The `_parking` ending keeps them apart from any future Property Rental
431–433. Parking head = `20270810_433_parking`.

- [ ] `git mv` the three files; set `revision` / `down_revision` as above. During Task 2 the chain
      is broken (424 does not exist yet); tests are not run between cherry-picks.
- [ ] Commit: `Step 6: move Parking's three migrations after Property Rental's head`.

### Task 2: Cherry-pick the 80 Property Rental commits in order

- [ ] List: `git rev-list --reverse --first-parent cb887b88..02e56aed` (80 ids, saved in the ledger).
- [ ] For each: merge commit → `git cherry-pick -x -m 1 <c>`; other → `git cherry-pick -x <c>`. On
      conflict: keep Property Rental's side of each hunk, apply only the Parking word rules to that
      hunk, keep Parking's lines that exist only in Parking (vehicle code, flags, price reason),
      `git add`, `git cherry-pick --continue`. Pinned head `20270407_257` in tests: take Property
      Rental's value (fixed once in Task 4).
- [ ] `scripts/local/common.sh`, `start-api.sh` and the new Telegram scripts: keep Parking's ports,
      pkm and Docker project names.
- [ ] Check: `git log --oneline 3030a5dc..HEAD | wc -l` → 81 (Task 1 + 80).
- [ ] Check: `git diff 02e56aed HEAD --stat` shows only Parking-difference files (words, vehicles,
      flags, seeds, migrations 431–433, docs/replica). Anything else is a lost hunk: fix it.

### Task 3: Parking words on the new screens

**Files:** every `frontend/src/**` and `backend/src/**` file the 80 commits added or changed; new
folders `joint/`, `inspections/`, `ledger/`, `shortstays/`, `hr/`, `telegram/`, `products/`,
`quotations/`, `problems/`, `access/`.

- [ ] Run the Step 2 rename script (`rename_words.py --dry --english --khmer`, as in Step 3b) on
      those files; drop hits in comments, docstrings, identifiers and "unit price"; apply.
- [ ] Hand pass: `api_refusals.py` new codes, letter and PDF text (`weasyprint` templates, Joint
      Inspection PDF), Telegram message text, Khmer compounds.
- [ ] Hidden parts (Task 6) get the same words, so they are ready if switched on later.
- [ ] Run `cd frontend && npx vitest run` and `cd backend && uv run pytest -q -x
      --ignore=tests/test_*_migration.py` → only the known failures in `known-failures.md`.
- [ ] Commit: `Step 6: Parking words on the V1.1 and V1.2 screens`.

### Task 4: Parking migrations rebuilt on Property Rental's new database (TDD)

**Files:** the three migrations of Task 1; `backend/tests/test_parking_types_migration.py`,
the Step 4 vehicles migration test, `test_cleaning_off_migration.py`; new
`backend/tests/test_parking_migrations_rerun.py`; `scripts/database-test.sh`; every pinned head
(`20270807_424` → `20270810_433_parking`).

**Interfaces:** Each of 431–433 does nothing when its change is already in the database
(431: `CREATE OR REPLACE` + `ON CONFLICT DO NOTHING` is already safe to repeat; 432: skip when
`app.vehicles` exists; 433: skip when the preview already contains `IF false AND v_moved_in`).
This is what lets pkm run them again (Task 8).

- [ ] Failing tests: new Property seeds the four Parking Types with Khmer names **plus** Property
      Rental 255's Feature types, Unit features and Item types except Balcony; head is
      `20270810_433_parking`; rerun test: upgrade to head, stamp back to `20270807_424`, upgrade
      again → no error, no new rows, same function bodies.
- [ ] 431: seed function = Property Rental 255's body with the Unit Types swapped for the four
      Parking Types and no Balcony feature. 432: Step 4 body unchanged plus the skip guard.
      433: unchanged plus the skip guard.
- [ ] Run with the own throw-away PostgreSQL (`make database-test` or the targeted script) → PASS.
- [ ] Commit: `Step 6: Parking migrations 431-433 on top of Property Rental 424`.

### Task 5: Vehicles still work with DL-241 and the Joint Inspection (TDD)

**Files:** tests in `backend/tests/` next to the Step 4 vehicle tests; `frontend/src/joint/*` and
`frontend/src/moveout/*` tests.

- [ ] Test: after `app.record_lease_vehicle_move_in`, `app.unit_held_by(parking, today)` =
      `OCCUPIED`; after `app.change_lease_vehicle` on the same day it is still `OCCUPIED`; after
      move-out it is NULL.
- [ ] Test: a second vehicle is still refused (`VEHICLE_SECOND`) and a wrong vehicle type still
      refused, after 421 changed the holder checks.
- [ ] Test: Joint Inspection MOVE_IN and MOVE_OUT on a vehicle Agreement: start, sign, Done; the
      form lists the Parking with no features (switches off) and does not crash on an empty
      features list; a Broken line at move-out makes one damage finding; final settlement preview
      is ready with no `CLEANING_CHARGE_MISSING`.
- [ ] Test: the late-payment pass on a Parking Agreement makes one 10% Late-payment Invoice per
      overdue Invoice, with no confirmation step (owner decision 2: automatic, as Property Rental).
- [ ] Frontend: Joint Inspection screens say Parking / Vehicle; tenant wording follows Step 2.
- [ ] Fix only what the tests show broken. Commit: `Step 6: vehicles with the new holder rule and Joint Inspection`.

### Task 6: Switches for the new parts Parking hides

**Files:** `frontend/src/leases/parking.ts` (new flags, `false as boolean`, owner's date),
`frontend/src/shell/navigation.ts` (filter menu items and sub-tabs by flag), Home cards,
Settings tabs, links inside Lease, Customer, Invoice and Payment pages; tests next to each.

**Flags:** `GENERAL_LEDGER`, `HR`, `TELEGRAM`, `SHORT_STAYS` (also Housekeeping and Booking sites),
`PRODUCTS` (also Quotations), `PROBLEM_REPORTS`, `MONTHLY_SERVICES`, `ABA_QR` — final (owner
approved the show/hide table on 17 Nov 2026, 19:57 UTC).

- [ ] Failing test per flag: menu, Home and Settings show nothing of it; its route stays alive.
- [ ] Gate; existing Property Rental tests of a hidden part skip with `skip(!FLAG)`, listed in
      `parking-differences.md`.
- [ ] Step 5 switches on V1.1 screens: `ROOM_FEATURES` and `HOME_FIELDS` now gate the **Unit
      features** panel, its dialog fields and the Settings cards Feature types, Unit features,
      Item types (Bedrooms/Bathrooms/Kitchen/Room features inputs no longer exist on screen);
      `UNIT_INVENTORY` gates the new inventory by Item type and place; `PET_DEPOSIT` also gates
      the new Pet Deposit step at Sign Lease (DL-234); `CLEANING_CHARGE` also gates any new
      cleaning text V1.1 added. Re-run TEST-FE-1139..1146 and update their selectors.
- [ ] Commit: `Step 6: switch off the V1.1 and V1.2 parts Parking does not use`.

### Task 7: Docs, feature list, traceability

**Files:** `docs/001`–`005` (Property Rental text plus "Amended for Parking" paragraphs),
`docs/replica/features.csv`, `docs/replica/parking-differences.md` (new rows: migration ids, rerun
guards, flags, skipped tests), `ops/traceability.json`, `docs/replica/step-6-ledger.md`.

- [ ] Rules text: unpaid rent notices on day 10, 20, 25 and the day-30 letter (owner decision 1,
      17 Nov 2026); remove any Parking wording that still says day 20 / day 30 only. Late charge
      automatic, lowered or cancelled by the Owner or a Manager only after a customer complaint
      (owner decision 2, 17 Nov 2026). A hand-back before the 5th pays only the days used, from
      the 1st to the hand-back day (owner decision 3, 17 Nov 2026). A Draft Invoice may be
      changed or deleted with no reason; issued Invoices only by adjustments (owner decision 4,
      17 Nov 2026).
- [ ] `parity.py docs/replica/features.csv` → 100. Commit: `Step 6: docs and feature list`.

### Task 8: pkm to the new head — only after the owner's OK

Proposal (nothing here runs before the owner says yes):

1. Read only: start the Parking database container, record `alembic_version` and row counts of
   the main tables (properties, units, customers, vehicles, leases, occupancies, invoices,
   payments, audit).
2. Backup: `pg_dump -Fc pkm` into Parking's backup folder; check the file opens
   (`pg_restore --list`).
3. Trial on a copy: restore that backup into a new throw-away database `pkm_step6_trial` (pkm
   untouched). On the copy: set the recorded version back to `20270404_254` (the last id both apps
   share; this edits only the one-row bookkeeping table) and run `alembic upgrade head`. Property
   Rental's 255–424 run, then 431–433 skip what is already there.
4. Check the copy: head `20270810_433_parking`; row counts as in step 1 plus only the additions
   listed below; four Parking Types; vehicles and agreements intact; preview has Parking's
   `IF false AND`; the app starts on 8001/5174 against the copy.
5. Report to the owner. With the owner's OK, run steps 2–4 on pkm itself (fresh backup first).
   The throw-away copy is kept until the owner says it can go.

What Property Rental's migrations add or change in pkm's data (owner to accept):
- Each Property gets default Feature types, Unit features, Item types (hidden), the General Ledger
  starter chart and 2027 fiscal year (hidden), 15 starter FAQ (hidden), new number rules and
  rights.
- 255 copies any Bedrooms/Bathrooms/Kitchen/Room features of a Parking into Unit features
  (Parking spaces normally have none).
- 421: a Parking stored as Reserved or Occupied is stored as Ready; who holds it is then read from
  its Reservation, Agreement or vehicle occupancy, so the screens show the same.
- No row is deleted; the old columns stay.

### Task 9: Full checks, review, report

- [ ] `make frontend-test`, `make backend-test`, `make database-test`, `make lint typecheck
      format-check` → only the known failures.
- [ ] Sweep: `sweep.py . --avoid "Unit Type,Unit,Property Rental,CHETANA Residence"` → 0 hits in
      screen text.
- [ ] `/code-review` on `3030a5dc..HEAD`; fix Critical and Important test-first.
- [ ] Report to the owner. Stop. No push.

---

## New parts in Property Rental V1.1 / V1.2 and the recommendation for Parking

Show = visible in Parking. Hide = code, tables and routes kept, switched off like Step 5.

**Owner decision (17 Nov 2026, 19:57 UTC): approved exactly as recommended below ("Yes, as
recommended").** Task 6 flags are therefore final: `GENERAL_LEDGER`, `HR`, `TELEGRAM`,
`SHORT_STAYS`, `PRODUCTS`, `PROBLEM_REPORTS`, `MONTHLY_SERVICES`, `ABA_QR`.

| Part | What it does (one line) | Recommend |
| --- | --- | --- |
| General Ledger | Full books: accounts, journal, auto-posting from payments, expenses, bills, assets, month and year close, statements | Hide |
| HR and payroll | Employees, salary loans, payroll, attendance with QR check-in, overtime | Hide |
| Telegram bots | Tenant, Customer and Staff bots: link a tenant, send Invoices, Receipts, notices, warnings, problem reports | Hide (needs bots and a Cloudflare relay; not in v1) |
| Short stays | Daily and weekly rent: calendar, bookings, check-in/out, booking-site calendars, quotes | Hide |
| Housekeeping | Cleaning tasks for short stays, given to cleaners automatically | Hide (part of short stays) |
| Products and Quotations | Products, prices, stock; quotations that become a Products Invoice | Hide |
| Problem reports | Report a problem, track the repair and its cost, monthly report | Hide (owner may want it for building damage) |
| Monthly services (V1.1 Regular services) | Recurring services on a Unit and a Services Invoice | Hide (project rules remove recurring services) |
| Unit features / Feature types / Item types | Replace Room features and Kitchens with counted features and places | Hide (Step 5 `ROOM_FEATURES`, `HOME_FIELDS`) |
| Inventory by Item type and place | Inventory list grouped by type and place | Hide (Step 5 `UNIT_INVENTORY`) |
| Pet Deposit at signing (DL-234) | Pet Deposit received at Sign Lease | Hide (Step 5 `PET_DEPOSIT`) |
| Joint Inspection (DL-243) | Move-in and move-out inspection signed by customer and staff on a tablet, with photos and a PDF | Show (project rule: move-in/move-out with inspection as Property Rental) — needs owner check of the form for a parking space |
| Inspections page | One list of all inspections of the Property | Show |
| ABA QR on Invoices | ABA payment QR printed on every Invoice; method chosen in Settings | Hide until the owner asks (not in v1 list) |
| Lease number | Every Agreement gets a number | Show |
| Late-payment Invoice (DL-233) | The 10% late charge becomes its own Invoice | Show (it is how the late charge now works) |
| Day 10 / 20 / 25 notices and day-30 letter (DL-237) | Three unpaid-rent notices, then a termination letter a Manager issues | Show — but differs from Parking's rule, see below |
| Simpler Invoice types, stored on the Invoice (DL-221, DL-231) | Rent, Utilities, Short stay, Products, Damage, Other charges | Show |
| Hand-back before the 5th pays days used (DL-229) | Customer pays only the days to the hand-back day | Show — rule change, see below |
| Extra money becomes Customer Credit at once (DL-235) | Overpayment goes to Credit at Receive payment | Show |
| Draft Invoice change and delete (DL-239) | A Draft (never issued) Invoice can be edited or deleted | Show — see below |
| Riel rate no mark-up (DL-228), late cap 10% (DL-226) | KHR rate without mark-up; Settings refuse a late charge above 10% | Show |
| Who holds a Unit from its records (DL-241) | Reserved/Occupied worked out from dates, not a stored word | Show (core) |
| Settings > Business rules | Due day, late %, reservation rules in Settings | Show |
| Roles and permissions V1.1, Users and access | New roles screen and rights | Show (Telegram tab hidden) |
| For rent Yes/No on a Unit | A space can be marked not for rent | Show (small; owner may hide) |
| Home cards "Paid on time", "Birthdays" | Two Home cards; Paid on time on a Customer | Show |
| System health page | Health of backups and jobs | Show |
| UI v81 redesign | New menu groups and screen layout | Show |

## Property Rental rule changes that differ from Parking's rules (owner to decide)

1. **Unpaid rent notices.** Parking: warning on day 20, serious default on day 30. Property Rental
   now: notices on day 10, 20 and 25 (sent by Telegram, else on paper by staff) and the day-30
   letter **needs all three notices first**. With Telegram hidden, staff must record two extra
   paper notices each month per late Customer.
   **Owner decision (17 Nov 2026, 19:59 UTC): A — take Property Rental's rule** (notices on day 10,
   20 and 25, then the day-30 termination letter issued by a Manager or the Owner after the three
   notices). No Parking difference. Task 7 updates Parking's rules text (`docs/002_BUSINESS_RULES.md`
   "Amended for Parking" paragraph and any Parking wording that still says "warning on day 20,
   serious default on day 30") to say days 10 / 20 / 25 / 30.
2. **Late charge.** Parking's project rules: a Manager confirms, reduces or waives the one 10%
   charge. Code already in Parking (DL-076, 20 Oct 2026): the charge is automatic with no
   confirmation; the Owner or a Manager lowers or cancels it only after a customer complaint of a
   staff mistake. V1.2 (DL-233) only turns that charge into a Late-payment Invoice.
   **Owner decision (17 Nov 2026, 20:01 UTC): keep it automatic, same as Property Rental** — the
   Owner or a Manager lowers or cancels it only after a customer complaint. No Parking difference.
   Task 7 changes Parking's rules text from "a manager confirms, reduces or waives" to this.
3. **Hand-back before the 5th (DL-229).** New rule: the Customer pays the days used of that month.
   Not in Parking's rules.
   **Owner decision (17 Nov 2026, 20:21 UTC): yes, pay only the days used, same as Property
   Rental.** No Parking difference. Task 7 adds it to Parking's rules text.
4. **Draft Invoice delete (DL-239).** Parking: history never edited, only corrected. A Draft has
   never been issued, so this may fit, but the owner should confirm.
   **Owner decision (17 Nov 2026, 20:55 UTC): yes, drafts only, same as Property Rental** — a
   Draft Invoice may be changed or deleted with no reason; an issued Invoice is only corrected by
   adjustments. No Parking difference. Task 7 adds it to Parking's rules text.
5. **Pet Deposit at signing, Regular services, Unit features** — rules Parking removed; they stay
   hidden.

## Risks

- pkm ids clash (above): the wrong command on pkm skips three Property Rental migrations. Only the
  Task 8 path is safe; it is rehearsed on a copy first.
- 421 rewrites stored Parking status words; 255 and 262 add rows. All are additions or
  re-statements, no deletes, but they are data changes on pkm the owner should accept.
- Hidden parts still run in the database: General Ledger auto-posting writes ledger rows for every
  payment, and the notice job exists. Harmless and invisible, but the database grows.
- Joint Inspection lists places from Unit features; with features hidden a parking space has no
  place lines, only keys and meters (which a parking space may not have). The form may look empty.
- `weasyprint` needs Mac system libraries (pango); install on the Mac mini before go-live.
- 80 cherry-picks with ~77 conflicting files: a hunk resolved the wrong way. Task 2's
  `git diff 02e56aed HEAD` check catches lost Property Rental changes.
- Future syncs: every new Property Rental migration will again follow 424 directly, so Parking's
  431–433 will need re-chaining each sync; the rerun guards of Task 4 make that safe to repeat.
- Telegram setup scripts create bots and a Cloudflare relay with Property Rental's names; they
  must not be run for Parking until renamed.
