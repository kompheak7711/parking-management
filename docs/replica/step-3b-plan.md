# Step 3b: Sync Property Rental V1-061 into Parking — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parking carries every Property Rental commit from df3ec76 up to cb887b88 (V1-061, 18 commits), with Property Rental's default-Rent version replacing Parking's Step 3 price code, and the Parking-only parts (four Parking Type seeds with Khmer names, Parking words, reason + History on a price change) added on top in a new migration 255.

**Architecture:** New branch `step-3b-sync` from `step-3-parking-price`. First set Parking's Step 3 commit aside with `git revert` (it stays in history), so the 18 cherry-picks meet only Step 1 and Step 2 (names and words), not a second migration `20270401_251`. Then cherry-pick the 18 commits in order with `-x`; resolve each conflict by taking Property Rental's text and applying the Step 2 words to it. Then a rename pass over the new strings, the Step 1 names in the new start script, and the Parking-only parts rebuilt test-first on top of Property Rental's `rent-terms` code. Hidden names stay Property Rental's (`unit`, `rent_terms`, `occupant`, `prm_*` roles).

**Tech Stack:** git cherry-pick, Alembic migration, FastAPI, React/Vitest, pytest, replica-skill parity and sweep.

**Spec:** owner message 2026-10-29 (Step 3b: "Parking keeps Property Rental's default-price version ... then adds the Parking-only parts on top"); owner Step 3 answers (reason + History rule, settings.manage permission, Khmer names); docs/replica/step-3-ledger.md (rulings that still apply).

## Global Constraints

- Never touch `~/Development/property-rental-management`, its database, containers or backups. Parking's database (`pkm`, port 5433, 0 Parking rows, at migration 250) is not reset; migrations are only applied if a step needs them.
- Take all 18 commits in order, none skipped, none split. Keep their messages (`cherry-pick -x`).
- Screen words only: "Unit" → "Parking", "Unit Type" → "Parking Type", plural "Units" → "Parking", Khmer បន្ទប់ → ចំណត, ប្រភេទបន្ទប់ → ប្រភេទចំណត. Never "unit price" (ឯកតា). Bedrooms/Bathrooms keep បន្ទប់គេង/បន្ទប់ទឹក (Step 2 fix). Kitchen ផ្ទះបាយ untouched.
- Hidden names unchanged: identifiers, routes, API paths, table/column/function names, test ids, docstrings, route `description=`.
- Operational names stay Parking's: pkm, ports 8001 / 5174 / 5433, Docker project parking-management.
- Required Services per Unit: copied as it is. No switch-off in this step.
- Money in integer cents. No new packages. No push.
- Parking-only test ids start at TEST-FE-1124 (Property Rental used up to 1123).

## Review Focus

1. A conflicted hunk resolved from Property Rental's side that still says "Unit" on a screen (sweep catches text files; test files assert the words, so the suites catch the rest).
2. Khmer compounds after the mechanical rename: ប្រគល់ចំណត (hand back), ចំណតនេះ, and any new string holding គេង/ទឹក/ផ្ទះបាយ.
3. Migration 255 on a Property that already holds the old seeds (Studio, …): the four Parking Types must be added, nothing deleted, no duplicate codes.
4. Rent and Services dialog saved with no reason: 422, nothing written; with a reason: one audit row whose `reason` is the text and whose previous/resulting state carry the old and new price.
5. `start-test-app.sh` must open Parking's ports and database, never Property Rental's.

---

### Task 1: Branch and set Step 3 aside

**Files:** none edited by hand.

- [x] `git switch -c step-3b-sync step-3-parking-price`
- [x] `git revert --no-edit 31caa4e0` → commit "Revert "Step 3: ..."" (message amended to say why: Property Rental V1-061 brings the same column and migration id).
- [x] Expected: `git diff df3ec76 --stat -- backend/migrations` shows no Parking migration 251; `backend/tests/unit_type_support.py` gone.

### Task 2: Cherry-pick the 18 Property Rental commits in order

**Commits (oldest first):** 97e65fb1 f6bc48f9 7493b68f ca5aba74 eb03cf2d 6b0bf443 8874d60c cb1b01f5 b6ad9ef7 808d4bb8 70b55708 58766a65 0560d4b6 27e2e359 37def08c b573134d ab8d21cb cb887b88.

**Expected conflicts (trial run in a scratch worktree):** f6bc48f9 `frontend/src/LeaseManagement.tsx`; eb03cf2d `frontend/src/units/UnitsPage.test.tsx`, `frontend/src/units/text.ts`; 6b0bf443 `frontend/src/leases/LeasesPage.test.tsx`; b6ad9ef7 `frontend/src/reservations/MakeReservationDialog.test.tsx`, `frontend/src/reservations/text.ts`; 37def08c `frontend/src/units/UnitsPage.test.tsx`, `frontend/src/units/text.ts`. Other 12 commits apply clean.

- [x] For each commit: `git cherry-pick -x <c>`. On conflict: open each conflicted file, keep Property Rental's side of the hunk, apply the Step 2 words to that hunk only, `git add`, `git cherry-pick --continue`.
- [x] After all 18: `git log --oneline 31caa4e0..HEAD | wc -l` → 19 (revert + 18).
- [x] Quick checks: `cd frontend && npx tsc --noEmit -p tsconfig.json` and `cd backend && uv run ruff check src tests` → expected clean (word changes do not touch types).

### Task 3: Parking words on the strings the 18 commits brought

**Files:** every `frontend/src/**/*.ts(x)` and `backend/src/**/*.py`, `backend/tests/**/*.py` the 18 commits touched or added (notably `frontend/src/shell/serverText.ts`, `frontend/src/units/RentTerms.tsx`, `frontend/src/units/UtilityPrices.tsx`, `frontend/src/reservations/text.ts`, `frontend/src/units/text.ts`, `frontend/src/leases/text.ts`, `backend/src/property_rental/api_refusals.py`, `scripts/local/start-test-app.sh`).

- [x] `python3 $S/rename_words.py --dry --english --khmer <files>` on the files changed in `df3ec76..HEAD` by the 18 commits; read the list; drop hits in docstrings, route `description=`, comments, identifiers (the script already skips those), and any "unit price".
- [x] Apply (without `--dry`), then hand-check Khmer compounds (គេង, ទឹក, ផ្ទះបាយ, ប្រគល់) and English count forms.
- [x] Backend messages: hand pass over `api_refusals.py` new entries (`RENT_BELOW_UNIT_DEFAULT`, `LEASE_REQUIRED_SERVICE_MISSING`, move-out codes) and any new `reports*`/letter strings.
- [x] Run: `cd frontend && npx vitest run` → expected: only TEST-FE-894 failing. `cd backend && uv run pytest -q -x --ignore=tests/test_*_migration.py` → expected: only the known owner set-up test.
- [x] Commit: `Step 3b: Parking words on the Property Rental V1-061 screens`.

### Task 4: Step 1 names in the new start script

**Files:** `scripts/local/start-test-app.sh`, `Start test app.command`, README lines the commit added.

- [x] Replace Property Rental's ports/names with Parking's where the script names them (8000→8001, 5173→5174, 5432→5433, prm paths→pkm, `property-rental`→`parking`); the helper functions `prm_fail`/`prm_origin` are hidden names: keep.
- [x] Verify: `grep -nE '8000|5173|5432|/prm\b|property-rental' scripts/local/start-test-app.sh "Start test app.command"` → expected: none.
- [x] `backend/tests/test_local_run_scripts.py`: if the commit added checks on the script, they must assert Parking's names.
- [x] Commit: `Step 3b: Start test app opens Parking's ports and database`.

### Task 5: Migration 255 — four Parking Types seeded (TDD)

**Files:** Create `backend/migrations/versions/20270405_255_parking_types.py`; Test `backend/tests/test_parking_types_migration.py` (rebuilt from the seed tests of the reverted `test_unit_default_rent_migration.py`); Modify `backend/src/property_rental/unit.py` (UnitType members → COVERED, UNCOVERED, MOTORBIKE, TUK_TUK_FOOD_CART), `backend/tests/unit_type_support.py` (restore from 31caa4e0), `scripts/database-test.sh` (list the new test), head asserts 20270404_254 → 20270405_255 (19 files), test fixtures with old codes (as in 31caa4e0).

**Interfaces:** Produces: `app.seed_unit_setup_items(property_id)` seeding codes COVERED, UNCOVERED, MOTORBIKE, TUK_TUK_FOOD_CART with English/Khmer names (Covered ចំណតមានដំបូល, Uncovered ចំណតគ្មានដំបូល, Motorbike ម៉ូតូ, Tuk-Tuk/Food Cart តុកតុក/រទេះលក់ម្ហូប), no Balcony feature; existing Properties get the four (ON CONFLICT DO NOTHING); forward-only.

- [x] Write tests: new Property seeds exactly the four with Khmer names; an existing Property with old seeds gains the four and keeps the old; downgrade raises; head is 20270405_255.
- [x] Run via `$S/dbtest-run.sh tests/test_parking_types_migration.py` → expected FAIL (revision missing).
- [x] Write the migration (seed function body from the reverted 251, down_revision 20270404_254).
- [x] Run again → PASS. Then the fixture changes (codes, `seeded_unit_type` helper, 19 head asserts) and `uv run pytest -q tests/test_unit.py tests/test_unit_api.py` → PASS.
- [x] Commit: `Step 3b: migration 255 seeds the four Parking Types`.

### Task 6: Reason and History on a price change (TDD)

**Files:** Modify `backend/src/property_rental/unit_api.py` (`UnitRentTermsSource.reason: str` required 1–500 trimmed; `set_rent_terms(..., reason)` passes it to `_audit`; timeline rows carry `actor_name` via subselect on `app.user_accounts`; `UnitTimelineEvent.actor_name`), `frontend/src/unitClient.ts` (`UnitRentTermsSource.reason`, `UnitTimelineEvent.actor_name`), `frontend/src/units/RentTerms.tsx` (reason box, required), `frontend/src/units/UnitDetail.tsx` (History line for `unit.rent_terms_changed`: "Default monthly price {old} → {new} by {who}: {reason}" when the price changed, else the existing line), `frontend/src/units/text.ts` (keys from the reverted Step 3: `price_reason_req`, `h_price`; Khmer as approved).
Tests: `backend/tests/test_unit_api.py` (missing/blank reason → 422 and no audit row; with reason → audit row reason + states), `frontend/src/units/UnitsPage.test.tsx` TEST-FE-1124 (reason required in the dialog), TEST-FE-1125 (History line who/old/new/reason).

- [x] Write the backend tests → run → FAIL. Implement → PASS.
- [x] Write the frontend tests → run → FAIL. Implement → PASS.
- [x] Ruling to record: the reason is required on every Rent and Services save (price or Services), because the dialog is one save; owner may narrow it.
- [x] Commit: `Step 3b: a price change asks a reason and History shows who, old, new and why`.

### Task 7: Docs, feature list, traceability

**Files:** `docs/002_BUSINESS_RULES.md` (BR-UNIT-015 Parking wording on top of Property Rental's DL-110 rule), `docs/001_DOMAIN_MODEL.md`, `docs/004_DATABASE_MODEL.md` (migration 255), `docs/005_API_SPECIFICATION.md` (reason field), `docs/replica/features.csv` (rows for V1-061 features original=yes clone=yes; Parking-only rows), `ops/traceability.json` (new tests), `docs/replica/step-3b-ledger.md` (rulings).

- [x] Edit; `python3 <replica-skill>/replica-diff/parity.py docs/replica/features.csv` → 100.
- [x] Commit: `Step 3b: docs and feature list for the V1-061 sync`.

### Task 8: Full verification, review, report

- [x] `make frontend-test` → expected: only TEST-FE-894.
- [x] `make backend-test` → expected: only the owner set-up test.
- [x] `make database-test` (own throw-away PostgreSQL) → expected: 0 failed (timing test may need a note).
- [x] `make lint typecheck format-check` → expected: only the known mypy `backup_job.py` error.
- [x] Sweep: `sweep.py . --avoid "Unit Type,Unit,Property Rental,CHETANA Residence"` → 0 hits in text files.
- [x] `/code-review` on `step-3-parking-price..HEAD`; fix Critical/Important with tests first.
- [x] Report: changes, test counts per group, where Required Services shows, risks, questions. STOP. No push.
