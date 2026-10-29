# Step 3: Parking Types and default monthly price — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Parking has a default monthly price in whole USD cents that only rate-changing users may set; a new Lease for that Parking starts with that price; the Settings list of Parking Types starts with the owner's four Parking Types.

**Architecture:** One new migration (251) adds the nullable price column to `app.units`, one database function that sets it with a version check (the API writes the History row, as for every other Parking change), and a new body for the seed function of Unit Types. One new API route `PUT /units/{unit_id}/default-rent`. The Parking page shows the price and a "Change price" dialog for allowed users. The Lease form fills Monthly Rent from the chosen Parking when nothing else (Reservation, previous Lease, staff typing) already set it. Hidden names stay (`units`, `unit_type`, `UnitDetail.tsx`); the new hidden names mirror the Lease column: `default_monthly_rent_usd_cents`, action `unit.default_rent_changed`.

**Tech Stack:** PostgreSQL function + Alembic migration, FastAPI + Pydantic, React + Vitest, pytest (database tests run through `make database-test`).

**Spec:** `docs/replica/step-3-brief.md` (the owner's Step 3 brief) plus the owner's answers of 2026-10-29: Q1 seed the four Parking Types (COVERED, UNCOVERED, MOTORBIKE, TUK_TUK_FOOD_CART; no Balcony seed; no price on types); Q2 the price is changed by the permission that changes cleaning rates and Settings lists (`settings.manage`, "Change the Settings"); Q3 Khmer names Covered ចំណតមានដំបូល, Uncovered ចំណតគ្មានដំបូល, Motorbike ម៉ូតូ, Tuk-Tuk/Food Cart តុកតុក/រទេះលក់ម្ហូប; addition: a price change is a money action, so the Change price dialog asks for a reason (required) and History shows who, when, old price, new price and the reason.

## Global Constraints

- Money: integer USD cents, `bigint`, `CHECK (> 0)`; never float. The screen shows dollars with two decimals (`usdFromCents`).
- Changing a default price never touches any Lease, Invoice or Reservation row (no code does; the tests prove it).
- Permission to set the price: **owner's answer to Q2** (`settings.manage`).
- Seed list: **owner's answer to Q1** (the four Parking Types with the owner's Khmer names).
- Hidden code names unchanged; only screen words say "Parking", "Parking Type", "Default monthly price".
- No new features beyond the brief: no price on the Parking list, no price per Parking Type, no price history screen (History already shows the audit row).

## Review Focus

1. A Reservation's agreed rent must still win over the Parking's default price on the Lease form (Task 5 test).
2. Staff who typed a rent and then change the Parking must not lose what they typed (Task 5 test).
3. A stale page (old `If-Match` version) must be refused, not overwrite a newer price (Task 2 test).
4. A price of 0, a negative, or `45.5` dollars without whole cents must be refused by the database and by the API (Tasks 1 and 2 tests).
5. A user with `property.manage` but without the rate permission sees the price but not the button, and the API answers 403 (Tasks 2 and 4 tests).

---

### Task 1: Migration 251 — price column, set function, Parking Type seeds

**Files:**
- Create: `backend/migrations/versions/20270401_251_parking_default_rent.py` (down_revision `20270331_250`)
- Test: `backend/tests/test_unit_default_rent_migration.py` (database test, same fixtures as `test_unit_setup_lists_migration.py`)
- Modify: `backend/tests/test_unit_setup_lists_migration.py` (seeded names), `docs/002_BUSINESS_RULES.md` (BR-UNIT-001 list; new rule BR-UNIT-0xx "Default monthly price" with the owner's words)

**Interfaces:**
- Produces: column `app.units.default_monthly_rent_usd_cents bigint NULL CHECK (> 0)`; function `app.set_unit_default_rent(p_id uuid, p_cents bigint, p_expected_version integer, p_actor_id uuid)` that updates the price, bumps `version` and `updated_by`, and returns the row, or nothing when the version is stale (same shape as `app.update_unit`; the History row is written by the API with `PostgresUnitResourceFlow._audit`, action `unit.default_rent_changed`, like `unit.updated`); `app.unit_with_details` replaced so it also returns the new column; new body of `app.seed_unit_setup_items` with `('UNIT_TYPE','COVERED','Covered','ចំណតមានដំបូល',10)`, `('UNIT_TYPE','UNCOVERED','Uncovered','ចំណតគ្មានដំបូល',20)`, `('UNIT_TYPE','MOTORBIKE','Motorbike','ម៉ូតូ',30)`, `('UNIT_TYPE','TUK_TUK_FOOD_CART','Tuk-Tuk/Food Cart','តុកតុក/រទេះលក់ម្ហូប',40)` ( `ROOM_FEATURE BALCONY` seed removed for Parking). Existing Properties get the four new types through the same `ON CONFLICT DO NOTHING` insert.

- [x] **Step 1: Write the failing tests**

```python
def test_a_default_rent_is_set(code_database): ...  # set 4500 → row.default_monthly_rent_usd_cents == 4500, version 2, unit_with_details returns 4500
def test_a_stale_version_sets_nothing(code_database): ...  # expected_version 1 after a set → no row returned, price and version unchanged
def test_zero_and_negative_prices_are_refused(code_database): ...  # 0 and -1 → CHECK violation, no audit row
def test_a_price_change_leaves_leases_untouched(code_database): ...  # signed Lease at 5000; set 4500 → Lease monthly_rent_usd_cents still 5000
def test_a_new_property_gets_the_four_parking_types(code_database): ...  # names == ['Covered','Uncovered','Motorbike','Tuk-Tuk/Food Cart'], no 'Balcony'
```

- [x] **Step 2: Run them to see them fail**

Run: `sh scripts/database-test.sh tests/test_unit_default_rent_migration.py` — Expected: FAIL (column does not exist / function does not exist). Note: the script runs the whole database suite (about 35 minutes); run the file alone with a throw-away database only if the script accepts a path, otherwise accept the full run.

- [x] **Step 3: Write migration 251** (column, CHECK, function with REVOKE/GRANT like 227, `CREATE OR REPLACE FUNCTION app.seed_unit_setup_items`, then `SELECT app.seed_unit_setup_items(id, created_by) FROM app.properties`). Forward-only downgrade like 227.
- [x] **Step 4: Run the tests to see them pass** — Expected: PASS; `test_unit_setup_lists_migration.py` updated for the new names also PASS.
- [x] **Step 5: Commit** `Step 3a: Parking default price column and Parking Type seeds (migration 251)`

### Task 2: API — read the price, set the price

**Files:**
- Modify: `backend/src/property_rental/unit.py` (`Unit.default_monthly_rent_usd_cents: int | None = None`), `backend/src/property_rental/unit_api.py` (row mapping, `_body`, `can_change_rent`, new route), `backend/src/property_rental/api_refusals.py` if a refusal text is needed
- Test: `backend/tests/test_unit_api.py`, `backend/tests/test_unit.py`

**Interfaces:**
- Produces: every Unit body has `default_monthly_rent_usd_cents: int | null` and `can_change_rent: bool`; `PUT /units/{unit_id}/default-rent` body `{"default_monthly_rent_usd_cents": 4500, "reason": "New price list"}` (reason required, 1–500 chars) with header `If-Match: "<version>"`, answers 200 with the Unit body and new `ETag`; 403 without the rate permission; 412 on a stale version; 422 for 0, negative, non-integer or missing; 404 unknown Parking.
- Consumes: Task 1 function.

- [x] **Step 1: Write the failing tests** (`test_unit_api.py`: `test_the_default_rent_is_in_the_unit_body`, `test_a_rate_user_sets_the_default_rent`, `test_a_manager_without_the_rate_permission_gets_403`, `test_a_stale_if_match_gets_412`, `test_the_change_is_in_the_history` (one audit row, action `unit.default_rent_changed`, actor, reason, previous and resulting price), `test_a_missing_reason_gets_422`, `test_bad_prices_get_422` with 0, -1, 45.5, "45"; `test_unit.py`: `Unit` accepts `None` and a positive int, refuses 0).
- [x] **Step 2: Run** `cd backend && uv run pytest -q tests/test_unit_api.py tests/test_unit.py` — Expected: FAIL (unknown field / 404 route).
- [x] **Step 3: Implement** `UnitDefaultRentSource(BaseModel)` with `default_monthly_rent_usd_cents: Annotated[int, Field(gt=0, strict=True)]`; `PostgresUnitResourceFlow.set_default_rent(unit_id, cents, expected_version, actor_id, reason) -> Unit` (audit row carries the reason, like Change status) calling the Task 1 function; route uses `_expected_version(if_match, current.version)` and `AuthorizationRequirement(capability=<Q2 permission>, property_id=...)`.
- [x] **Step 4: Run the tests** — Expected: PASS. `make lint typecheck` clean except the known mypy failure.
- [x] **Step 5: Commit** `Step 3b: API reads and sets a Parking's default monthly price`

### Task 3: Settings words — Parking Types seeds on screen

**Files:**
- Modify: `frontend/src/units/UnitsPage.test.tsx`, `frontend/src/settings/UnitSetupTab.test.tsx` (fixture names only where a test asserts a seeded name)

- [x] **Step 1:** No screen code changes: the Settings tab already edits the list. Change the fixtures that assert "1 bedroom" / "Studio" to the Parking names where the test is about seeded names; leave other fixtures.
- [x] **Step 2: Run** `cd frontend && npx vitest run src/settings src/units` — Expected: PASS.
- [x] **Step 3: Commit** `Step 3c: Settings tests use the Parking Type names`

### Task 4: Parking page — show the price, Change price dialog

**Files:**
- Modify: `frontend/src/unitClient.ts` (`UnitResource.default_monthly_rent_usd_cents`, `can_change_rent`, `setDefaultRent(unitId, cents, version)`), `frontend/src/units/UnitDetail.tsx` (price row + button), `frontend/src/units/UnitDialogs.tsx` (`RentDialog`), `frontend/src/units/text.ts` (new pairs: `price` ["Default monthly price", KM], `price_unset` ["Not set", KM], `change_price` ["Change price", KM], `price_help` ["Fills the Monthly Rent of a new Lease for this Parking. Existing Leases and Invoices do not change.", KM], `price_invalid` ["Enter a price above zero, in dollars and cents.", KM], `price_reason` ["Reason", KM], `price_reason_required` ["Say why the price changes.", KM], `price_conflict` [...]). History on the Parking page shows the row as who, when, "Default monthly price $35.00 → $45.00" and the reason (`UnitDetail.tsx` timeline).
- Test: `frontend/src/units/UnitsPage.test.tsx`

- [x] **Step 1: Write the failing tests** (`TEST-FE-xxx`: the page shows "Default monthly price" "$45.00"; "Not set" when null; the button is absent when `can_change_rent` is false; the dialog sends `{default_monthly_rent_usd_cents: 4500, reason: "New price list"}` with `If-Match: "3"` and the page shows the new price; an empty reason shows the reason message and sends nothing; the History list shows who, when, old and new price and the reason; "45.555" shows the invalid message and sends nothing; a 412 reloads and shows the conflict message).
- [x] **Step 2: Run** `npx vitest run src/units` — Expected: FAIL.
- [x] **Step 3: Implement** the client call, the row and the dialog (same dialog shape as the Change status dialog; cents = `Math.round(Number(value) * 100)` after a `/^\d+(\.\d{1,2})?$/` check; reason textarea required).
- [x] **Step 4: Run** — Expected: PASS; `npm run lint`, `tsc`, `prettier --check` clean.
- [x] **Step 5: Commit** `Step 3d: Parking page shows and changes the default monthly price`

### Task 5: Lease form — Monthly Rent starts from the Parking's price

**Files:**
- Modify: `frontend/src/leases/LeaseForm.tsx` (`rentTyped` state like `depositTyped`; on Unit choice and on first load of a walk-in draft, when `!rentTyped` and no Reservation and no previous Lease, `setRent` from the chosen Unit's `default_monthly_rent_usd_cents`; a Parking with no price leaves the field empty), `frontend/src/leases/text.ts` only if a help line is wanted (none planned).
- Test: `frontend/src/leases/LeasesPage.test.tsx`

- [x] **Step 1: Write the failing tests** (choosing Parking U101 with 4500 fills Monthly Rent "45.00"; choosing a Parking with null leaves ""; staff typed "50.00" then changed Parking → still "50.00"; a Reservation draft keeps the agreed rent; a renewal keeps the previous Lease rent; New Lease from the Parking page fills "45.00").
- [x] **Step 2: Run** `npx vitest run src/leases` — Expected: FAIL.
- [x] **Step 3: Implement** in the Unit `<select>` `onChange` and in the load effect.
- [x] **Step 4: Run** — Expected: PASS.
- [x] **Step 5: Commit** `Step 3e: a new Lease starts with the Parking's default monthly price`

### Task 6: All tests, checks, report

- [x] `make backend-test`, `make database-test`, `make frontend-test`, `make lint typecheck format-check` — Expected: same 3 known failures (+ the timing test if the Mac is busy), no new failures.
- [x] replica parity (`parity.py docs/replica/features.csv`, add the three new rows: default price, change price, Lease prefill) and sweep (`--avoid "Unit Type,Unit"`) — 0 screen words.
- [x] `/code-review`; fix findings; write `docs/replica/step-3-ledger.md`; report; stop. No push.
