# Step 6 ledger — Property Rental V1.1 and V1.2 sync (plan: docs/replica/step-6-plan.md)

Branch `step-6-sync-v1-2` from `step-5-switch-off` (3030a5dc). Owner go-ahead 17 Nov 2026 21:26 UTC;
owner choice A (22:10 UTC): the 80 copy commits are local commits; Parking's own changes stay
uncommitted for review. Nothing pushed. Real pkm untouched.

Order changed from the plan: the copy (Task 2) ran before the migration move (Task 1), because
the move is a Parking change and stays uncommitted. Cost if wrong: none; the chain is only
checked at the end.

Task 2: complete. 80 cherry-picks (`-x`, merges `-m 1`), 3030a5dc..HEAD = 80 commits.
  Conflicts resolved by a script where one side equals the base after undoing the Parking words
  (Property Rental's side taken; words re-applied in Task 3); by hand otherwise.
  Ruling: a conflict hunk whose Parking side was only a Step 4/5 switch wrapper took Property
  Rental's side and the switch was put back in Task 6 on the final screen, because V1.1 and UI v81
  redrew those screens. Cost if wrong: a switch missed; `tsc` flagged every unused flag import and
  each was re-wrapped.
  Ruling: `frontend/src/leases/LeaseDetail.tsx` was rebuilt from Property Rental's 02e56aed file
  plus the Step 4/5 hunks, because the UI v81 merge left interleaved hunks that did not parse.
  Ruling: `backend/uv.lock` takes Property Rental's file with the package name `parking-backend`.
Task 1 (after Task 2): complete, uncommitted. Migrations renamed to 431/432/433 with ids ending
  `_parking`, chained after `20270807_424`.
Task 3: complete. Parking words by a script on string literals of the files the 80 commits
  touched (frontend and backend src), skipping strings a migration raises (quoted match); test
  regexes by a second pass.
  Ruling: `lease.py` and `reservation.py` short-stay booking texts stay "Unit": code matches the
  database's exact words (split strings the quoted check missed). Cost if wrong: none on screen.
  Ruling: `shell/plural.ts` drops "Parking" from the singular list ("1 Parkin" otherwise).
  Ruling: `CHETANA Residence` in `home/text.ts` and the Quotation page → "CHETANA Parking"
  (Step 1 name); the database seed name is not changed.
Task 4: complete. 431 = Property Rental 255 seed with the Parking Types, no Balcony. 432/433
  skip themselves when already applied. Head pins → `20270810_433_parking`. New tests:
  `test_a_new_property_gets_property_rentals_v1_1_lists_without_balcony`,
  `test_parking_migrations_run_again_change_nothing`.
  Ruling: the rerun test lives in `test_parking_types_migration.py` (plan named a new file);
  fewer files. Cost if wrong: none.
Task 5: complete. Tests written after reading the code (not red first: the behaviour comes from
  Property Rental): `test_a_vehicle_holds_its_parking_under_the_holder_rule`,
  `test_a_joint_inspection_works_on_a_vehicle_agreement`. No code change needed.
Task 6: complete. Eight switches; Step 5 switches re-applied on V1.1 screens; tests
  TEST-FE-3155..3157. Parking test ids 1124..1154 → 3124..3154 (Property Rental took 1124..1154).
  Ruling: hidden pages are refused by `pageAllowed`, so a typed address shows "not allowed"
  instead of the page. Cost if wrong: one line (the plan said the route stays alive).
  Ruling: Settings › Monthly services is hidden as approved; it also holds the V1-061 Services and
  their rates used by Rent and Services (Step 3b). Question for the owner in the report.
Task 7: complete. 002 (Step 3/5 amendments restored on the new 002, Step 6 amendments), 004,
  005, `parking-differences.md` Step 6, `features.csv` (+21 rows, parity 100),
  `ops/traceability.json` (Parking entries restored, new ones added).
  Telegram job files renamed to Parking names (Step 1 rule).
Task 8 (trial only, owner limit): pkm backed up (`.local/backups/pkm-before-step6-20261117.dump`,
  202 tables), restored into `pkm_step6_trial`, stamped to `20270404_254`, upgraded to
  `20270810_433_parking` with no error. Before → after: Properties 1 → 1, Parking 0 → 0,
  Customers 0, Vehicles 0, Leases 0, Invoices 0, Payments 0, users 1 → 1, setup items 5 → 29,
  audit rows 7 → 68. Preview keeps `IF false AND`; vehicles and joint inspections tables exist.
  Finding: Property Rental 255 seeds its home Unit Types (Studio, 1/2/3 bedroom) and Balcony into a
  Property that already exists, so pkm's Parking Type list would show them. Not removed (no
  delete; the owner decides). The app was not started against the copy (start-api needs the Mac
  password).
Task 9: complete.
  Frontend: 2,360 passed, 33 skipped, 20 failed = the 20 that fail on Property Rental 02e56aed on
  this Mac (19 AppShell localStorage on Node 26, TEST-FE-894). tsc, eslint, prettier clean.
  Backend (no database): 5,237 passed; failures = the 5 that fail on Property Rental 02e56aed
  (weasyprint libraries, owner set-up); the 12 Parking ones were fixed. ruff, format clean; mypy
  only the known backup_job.py error.
  Database tests (own throw-away PostgreSQL): run 1 had 36 failed / 120 errors, nearly all test
  data with home Unit Types; fixed. Run 2: 3,340 passed, 10 failed; 7 fixed after (2 skipped as
  short stays), 3 = the same 3 that fail on Property Rental 02e56aed today.
  /code-review medium on the uncommitted Parking changes: 9 findings.
  Final: fixed ABA QR hidden field still blocking a save (BusinessTab).
  Final: fixed Invoice and Joint Inspection PDFs printing "Unit" (f-strings the word script did not
  read).
  Final: fixed Joint Inspection PDF and screen Khmer "room" words turned into ចំណត (also short
  stays).
  Final: fixed Joint Inspection problem-report link to the hidden page.
  Final: fixed Telegram timer descriptions (CHETANA Parking).
  Final: Ruling: the pkm id clash (findings 1-2) is handled by the Task 8 path (stamp to 254 then
  upgrade), rehearsed on pkm_step6_trial; no code can tell an old Parking 257 from Property
  Rental's 257. Cost if wrong: a plain `alembic upgrade head` on pkm breaks; the report says so.
  Final: minor (deferred): Home repeats the switch checks instead of calling pageAllowed.

Owner answers after the report (17-18 Nov 2026):
- Question 1 (18 Nov, 04:23 UTC): (a) staff remove the home Unit Types (Studio, 1, 2, 3 bedroom)
  and Balcony in Settings › Parking setup after the pkm upgrade; no code change.
- Question 2 (18 Nov, 04:30 UTC): hide the Services settings page too (Settings › Monthly
  services stays hidden with MONTHLY_SERVICES, including the V1-061 Services and their rates).
- Question 3 (18 Nov, 04:37 UTC): yes, upgrade pkm. Done the tested way: backup
  `.local/backups/pkm-before-step6-upgrade-20261118.dump` (202 table data parts, opens), marker
  set from `20270407_257` to `20270404_254`, `alembic upgrade head` → `20270810_433_parking`, no
  error. 201 tables before, 377 after; no table lost a row. Only additions: Property Rental's
  seeded rows (rights, roles, business rules, ledger chart and 2027 year, invoice types, problem
  types, staff checklists and others) and 24 setup items (the home Unit Types and Balcony for staff
  to remove, plus hidden feature and item lists). Settlement preview keeps `IF false AND`.
