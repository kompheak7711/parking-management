# Step 2 ledger — plan: docs/replica/step-2-plan.md

Branch `step-2-wording` from `step-1-clone-rename` (9ecc43b). Owner answers 2026-10-29: Khmer OK (ចំណត, ប្រភេទចំណត), plural = "Parking" for one and many, "Unit inventory/features" → "Parking inventory/features".

Pre-flight: no shared interfaces between tasks (all tasks edit words only).

- Task 1: complete. English words in string literals of every `frontend/src` file (text files, screen files, tests) by script `rename_words.py` (string literals only; comments and identifiers untouched); JSX text and test regexes fixed by line. Ruling: "Unit price" kept (measure word) — cost if wrong: one label.
- Task 2: complete. Backend: every non-docstring string literal in `backend/src` and `backend/tests`. Ruling: internal error texts (for example "Parking persistence is unavailable") renamed too, docstrings not — one consistent rule beats a hand-picked list; cost if wrong: a larger diff when copying Property Rental fixes.
  - Ruling: `utility_sheet.py` `COLUMNS` "unit" → "parking" so the downloaded readings file (header "Parking") uploads again — cost if wrong: a readings file with an old "Unit" header is refused.
  - Ruling: `reports_api.py` `summary=` (OpenAPI only) renamed with the rest — harmless.
  - Ruling: migration 227 Khmer "បន្ទប់គេង" = bedroom (seed Unit Types) untouched; migrations are history, Step 3 replaces the list.
  - Ruling: f-strings (Python 3.14 tokenizes them apart) fixed by sed in `report_exports.py`, `unit.py`.
- Task 3: complete. Khmer ប្រភេទបន្ទប់ → ប្រភេទចំណត, then បន្ទប់ → ចំណត in all frontend string literals (20 files). ផ្ទះបាយ and ឯកតា untouched.
- Task 4: tests. First frontend run: 4 failed (known TEST-FE-894 + 3 new: "UnitU301" and "Still in the Unit5 days ago" had no word boundary; History showed "Unit status changed" from the action code). Fixed: two test strings; `history/text.ts` `actionText` shows code name `unit` as "parking". Ruling: fix in the one helper that turns codes into words, not in the test — cost if wrong: none found; no other helper exposes "unit" (checked `event_kind`, `condition`, `governing_source_kind`, evidence keys).
- Rewordings (owner asked for the list): "No Units match these filters." → "No Parking matches these filters."; "The Units are already filled in" → "The Parking is already filled in".
- Formatting: `ruff format` reformatted 40 backend files after the token rewrite; two long lines in `lease_signing_api.py` re-split. `make lint`: clean. `make typecheck`: known mypy failure only. `tsc`, `eslint`, `prettier`: clean.

## Code review (medium) and fix pass

Findings 1–3, 5, 6, 8 (confirmed, Important): backend dictionaries keyed on the exact error text that PostgreSQL functions raise (`invoice_api.py` cleaning-charge refusals, `draft_record_api.py` payment-move refusal, `lease_signing_api.py` signing refusals) had their keys renamed, so the refusal lookups would never match; tests mocking those texts were renamed with them and hid it. The Invoice line description "Unit cleaning charge" and the audit note "Unit cleaning charge at move-out (BR-MOVEOUT-013)" are written by the database function in migration 81; `frontend/src/moveout/charges.ts` matches the description. Fix: every string whose original text appears inside a migration as SQL (RAISE EXCEPTION, INSERT, function body) or as a seeded catalog row was put back to the "Unit" text: 22 texts in 14 files (`db-text-restored.txt` in the scratchpad lists them). Staff-facing `Refusal.message` values keep "Parking". Also restored: capability descriptions in `access_control.py` (seeded by migrations 176 and 220; not shown on any screen), test assertions of database messages ("Unit transition disagrees", "Reservation expired while the Property could provide the Unit", "Wrong-Unit Payment move confirmed (BR-PAY-042)", forward-only migration errors).
Finding 4 (Important): readings-sheet upload refused the old "Unit" header. Fix: `utility_sheet.py` reads "unit" as "parking"; `test_utility_sheet.py` 15 passed.
Finding 7 (Important): `ruff format .` had reformatted 34 migration files and `env.py`. Restored from HEAD; `make format-check` passes (it formats `src tests` only).
Finding 9 (Minor): default audit reason in `unit_api.py` now says "Parking source data changed through the authorized Parking API". Ruling: keep; Parking's database has no earlier rows, and the reason is shown in History — cost if wrong: one reason text differs from Property Rental's.
Ruling: the Invoice line description "Unit cleaning charge" stays on screen because the database writes it; changing it needs a new migration that re-creates the function (owner question) — cost if wrong: one visible "Unit" word on move-out Invoices.
Verification after the fix pass: `make lint format-check` exit 0; targeted `pytest` 100 passed; `vitest` moveout + LeaseManagement 61 passed; full suites re-run (see report).

## Full test runs (after the fix pass)

Frontend: 1 failed, 1966 passed (76 files) — only known TEST-FE-894.
Backend: 2 failed, 5103 passed, 2717 skipped (17m24s). One is the known owner set-up test. The other, `test_every_local_script_parses_and_reads_secrets_only_from_files`, still asserted `--port 8000`: a Step 1 miss (the port moved to 8001 in Step 1, the test was not updated). Ruling: assertion changed to 8001 (same rule as the Step 1 test updates: update old-name asserts, never delete) — cost if wrong: none, 8001 is Parking's owner-approved port. Re-run of the file: 1 failed (known), 9 passed.
Database: first run 1 failed, 2896 passed — `test_a_start_during_a_wait_answers_429_and_writes_nothing` got 299 instead of 300: migration 185 rounds up the seconds left of the 300 s wait, so 299 means more than one second passed between the wrong try and the next call on the loaded Mac; the test file has no Step 2 change. Re-run: 2897 passed (34m57s). Ruling: timing, not a regression; no code change — cost if wrong: an unrelated flaky test stays unfixed.
Result: same 3 known failures, no new failures.

## Fix after the owner's Step 2 answers (2026-10-29)

"Loading the Parking…" → "Loading Parking…" (owner). Found while planning Step 3: the Khmer rename had turned the compound words បន្ទប់គេង (Bedrooms) and បន្ទប់ទឹក (Bathrooms) into ចំណតគេង / ចំណតទឹក (`frontend/src/units/text.ts`). Put back. A scan of every Khmer string that has ចំណត glued to a following letter found no other compound (Khmer writes words without spaces, so the rest are separate words such as ចំណតទំនេរ = vacant Parking).
