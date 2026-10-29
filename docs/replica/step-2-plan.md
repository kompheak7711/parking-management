# Step 2: Wording (screen words only) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every word staff see says "Parking" / "Parking Type" / "Parking Rental" where Property Rental said "Unit" / "Unit Type" / "Property Rental". Nothing else changes.

**Architecture:** Screen text lives in the bilingual text files (`frontend/src/**/text.ts`, `signInText.ts`, `shell/navigation.ts`) as `[English, Khmer]` pairs, plus a few literal strings in `.tsx` files and in backend messages staff read (refusal messages, report and export headers, letters, the readings sheet). Hidden names (`unit`, `unit_type`, `UnitsPage`, routes `#/units`, table and column names, API paths) stay.

**Tech Stack:** TypeScript text files, Vitest, pytest, replica-brand sweep.

**Spec:** owner brief 2026-10-29, Step 2; owner answers of 2026-10-29 (Step 1 report).

## Global Constraints

- "Unit Type" → "Parking Type"; "Unit" → "Parking". Plural "Units": owner chooses the form (Question 2). "Lease" and "Customer" unchanged. "Property Rental" already "Parking Rental" (Step 1).
- Khmer: no Khmer word changes until the owner approves the list (Question 1).
- Hidden code names unchanged: identifiers, file names, routes, API paths, table/column names, test IDs (TEST-FE-nnn), comments, route docstrings.
- "unit price" (invoice line, Khmer ឯកតា) is a measure word, not a Unit: unchanged.
- "Unit inventory" (the checklist of items inside a Unit: kitchen, beds...): Question 3.

## Inventory (where the words are)

| Place | Count | Treatment |
| --- | --- | --- |
| English strings with Unit/Units/Unit Type in 15 text files | 169 (24 of them "Unit Type") | replace |
| Khmer strings with បន្ទប់ (7 of them ប្រភេទបន្ទប់) | 178 | replace after owner OK |
| Literal strings in .tsx (tables `<th>Unit</th>`, dialogs, Unit inventory panel, invoice PDF "Unit {n}", hand-back reason) | 25 | replace the staff-visible ones; comments untouched |
| Backend staff-facing messages (api_refusals.py, reports, report_files.py, report_exports.py, utility_sheet.py, letters, lease.py and reservation.py refusals) | subset of 76 strings in 23 files | replace only messages and headers; route docstrings untouched |
| Frontend tests asserting the words | 31 files | update expected text |
| Backend tests asserting the words | 41 files | update expected text |

## Review Focus

1. Khmer sentences that embed the business name ("បន្ទប់ {0} នៅ CHETANA Parking") must read naturally after the swap.
2. Count forms ("1 Unit", "{0} Units", "All Units", "No Units match") get the owner's chosen plural form, not a mechanical "Parkings".
3. Exported .xlsx headers: the readings sheet column "Unit" may be matched by name on upload. Check `utility_sheet.py` reads columns by position or by name before renaming the header.
4. Refusal messages are matched exactly by tests and by the front end (`api_refusals.py` keys): rename the English text, not the key.
5. Sweep must find 0 "Unit"/"Unit Type" in text files; hits in comments, identifiers, `ops/` and `docs/` are expected and listed.

---

### Task 1: English text files

**Files:** `frontend/src/{units,settings,reports,moveout,leases,utilities,reservations,customers,history,letters,invoices,payments,home,approvals}/text.ts`, `frontend/src/shell/navigation.ts`.

- [x] Script: in the English (first) element of each pair only, replace `Unit Types` → `Parking Types`, `Unit Type` → `Parking Type`, `Units` → owner's plural form, `Unit` → `Parking`. Word-boundary, case-sensitive (never `unit_id`, `unitId`, `#/units`).
- [x] Hand-check the 15 diffs for wrong hits and sentences that need rewording.
- [x] Run: `cd frontend && npx vitest run` → expected: failures only in tests asserting old words (Task 4) plus TEST-FE-894 (known).

### Task 2: Literal strings in .tsx and backend messages

**Files:** `ReservationManagement.tsx`, `LeaseManagement.tsx`, `UnitInventoryPanel.tsx`, `UtilityManagement.tsx`, `invoices/InvoiceDocument.tsx`, `moveout/HandBackDialog.tsx`; backend `api_refusals.py`, `lease.py`, `reservation.py`, `unit_api.py`, `unit.py`, `move_in.py`, `physical_move_out.py`, `reports.py`, `reports_api.py`, `report_exports.py`, `report_files.py`, `report_totals.py`, `utility_sheet.py`, `utility_baseline.py`, `service_settings_api.py`, `unit_inventory_api.py`, `invoice_api.py`, `invoice.py`, `lease_signing_api.py`, `draft_record_api.py`, `audit_api.py`, `unpaid_initial_termination.py`, `access_control.py`.

- [x] Per file: change only strings staff read (messages, headers, labels, PDF text). Leave docstrings, route `description=`, comments.
- [x] Run: `cd backend && uv run pytest -q` → expected: failures only in tests asserting old words (Task 4) plus the known owner set-up test.

### Task 3: Khmer text (only after owner OK on Question 1)

**Files:** same text files as Task 1.

- [x] Replace `ប្រភេទបន្ទប់` → approved Parking Type word, then `បន្ទប់` → approved Parking word, in the Khmer (second) element only. `ផ្ទះបាយ` (Kitchen) and `ឯកតា` (unit price) untouched.
- [x] Hand-check compounds ("គ្មានបន្ទប់" = no Unit, number and floor phrases) read naturally.

### Task 4: Tests

- [x] Update the 31 frontend and 41 backend test files' expected strings (same replacements; test IDs untouched).
- [x] Run all: `make backend-test`, `make database-test`, `make frontend-test`, `make lint typecheck` → expected: same 3 known failures, no new failures.

### Task 5: Checks and report

- [x] Sweep: `sweep.py . --avoid "Unit Type,Unit,Property Rental,CHETANA Residence"` → 0 hits in text files; list the rest (identifiers, comments, ops/, docs/).
- [x] Parity: `parity.py docs/replica/features.csv` → 100.
- [x] Changed-words list for the owner (English pairs and Khmer pairs).
- [x] `/code-review`; fix findings; report; stop. No commit.
