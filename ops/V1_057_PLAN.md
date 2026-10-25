# V1-057 plan and step log: reports, Home, audit search and exports

Started 2026-10-25 (owner: "Start in v1-057 thread"). Rules: DL-072 and DL-079 (docs/010), with
DL-073 item 4 ("Refund due by") and the owner's 2026-10-21 change of the export format to .xlsx
and PDF. Branch `claude/v1-057-reports` from implementation/foundation 141e363. Merging into
foundation needs the owner's yes.

Split agreed with the V1-058 screens thread (2026-10-25): this branch builds the server routes,
the frontend client (`frontend/src/reportsClient.ts`) and their tests; the V1-058 thread builds
the Home, Reports, History and export screens on that client. This branch does not touch
`frontend/src/shell/*`, `frontend/src/App.tsx` or the V1-058 screen folders. Migrations start at
`20270301_220`; the V1-058 branch re-chains after foundation 206 on its own.

Run rules: the faster-run rules of ops/V1_055_RUN_RULES.md (affected PostgreSQL files for each
database step, one full run at the end, one review round per step).

## Steps

1. Rights and Home page read (API-076). New rights `reports.read`, `audit.export`, `data.export`
   for the default Owner and Manager bundles; `GET /api/v1/properties/{id}/home`.
2. Totals by Unit and month: Total Income, Total Payment, Total Electricity, Total Water
   (DL-079 answers 1 to 4).
3. The nine registers and lists (DL-079 answer 5), with the overdue groups (DL-072 answer 2) and
   the Payments report lines (DL-072 answer 10, DL-079 answer 7).
4. Audit search record (DL-072 answer 14) and exports (.xlsx and PDF; small files at once, larger
   ones as a job kept 24 hours; name, Unit and phone only; SHA-256 on the audit export).
5. Client functions and types for every route; full PostgreSQL run; report to the owner.

## Decided by Claude under the owner's 2026-10-23 22:30 rule

- Right names: `reports.read` (money reports and the four totals), `audit.export`, `data.export`.
  The audit search keeps `audit.view` (SEC-032: search and export are separate). Staff reports
  (Unit occupancy, Lease dates, Utility consumption without amounts) need only the read rights
  Staff already hold, so the Staff bundle does not change.
- Home sections follow the read right of their data: Units (`units.read`), Pending payment and
  Overdue (`invoices.read`), Paid for this month (`invoices.read` for the billed part,
  `payments.read` for money received), Lease renewal (`leases.read`), Reservations nearing expiry
  (`reservations.read`), Waiting for approval (`financial.approve`), Deposits waiting for a
  decision (`reservation_deposits.dispose` or `financial.approve`), Meter readings missing
  (`utility.read`), Letters due (`rent_nonpayment.read`), open Final Settlements and "Refund due
  by" (`final_settlements.prepare` or `financial.approve`). These are rights people already use
  to see the same records on their daily screens.
- The eight Home cards are the ones in DESIGN.md (owner 20/10/2026, G9): Units occupied, Pending
  payment, Paid for this month, Overdue, Lease renewal, Waiting for approval, Meter readings
  missing, Letters due. This closes the DL-079 "which eight cards" open point.
- "Paid for this month" bar: Invoices whose Due Date is in this month, paid part of their total.
- Meter readings missing counts working meters with no reading dated on or after this month's
  reading day (the 24th, DESIGN.md; no reading-day setting is stored yet). The to-do item shows
  from six days before the reading day.
- To-do groups: Overdue (before today), Today, This week (the next six days), Later.
- Totals by Unit and month (DL-079 open points): the four tables need `reports.read`. A month's
  Payment money is split as the records are now; the month's total never changes. A Late-payment
  Charge reduction or waiver is a minus in the charge's own month. A kept Deposit (Security or
  Pet) counts as income in the month it is kept. Utility amounts and quantities count in the
  month the reading period ends. Money with no Unit (a Payment not tied to a Lease) counts only
  in the whole-Property table and is shown as its own summary figure. Charts need no package:
  the server sends each month's parts and the top five Units.
- Home extras for the screens thread: reserved and vacant Unit counts; "money out" on Waiting
  for approval is the Refund and Payment return drafts; the line under the to-do list gives the
  last finished billing run, the next Rent billing day (the 25th, the DL-075 default, until a
  billing-day setting is stored) and when the exchange rate was last entered.
- Home to-do: drafts waiting, Deposits waiting for a decision and open Final Settlements are
  dated by when the wait began, so they stay under Today while they wait (the screen shows how
  long ago), as the mock-up does.
- Register rights: the five money registers need `reports.read`; Utility consumption needs
  `utility.read` and shows amounts and Rates only with `reports.read`; Unit occupancy needs
  `units.read`, `leases.read` and `reservations.read`; Lease dates needs `leases.read`; Audit
  activity needs `audit.view`, the audit search right (SEC-032).
- Register periods: Invoice register by Invoice date, Payments by the day the money came in (a
  reversal line by its own day), Utility consumption by the day the reading period ends, Credit
  ledger by the day the Credit was recorded, Final Settlements by the day they were started,
  Lease dates by the End Date (the actual termination date for a Lease ended early), Audit
  activity by the event's business day. Unit occupancy and Deposit liability show today, so the
  period does not apply. The floor filter keeps the rows of that floor's Units.
- Invoice register: VOID Invoices are listed but not added up. "Paid" is the part paid by
  Payments, the same records as the Payments report's Paid to Invoices; the rest settled
  another way (Customer Credit or a Deposit) is its own column. The Final Settlement register
  shows the Deposits and Credit used, the Deposits kept, the refunds and the balance due when it
  closed; it has no separate "charges" column, because the charges are those amounts together.
- A Refund that came back counts at its net value (`app.refund_net_value_at`) in the Payments
  lines, the Deposit register and the Final Settlement register.

Register summaries (fields over every row of the filter):

- invoice_register: issued, paid_to_invoices, other_settled, owed (USD cents), invoice_count,
  void_count, overdue_groups (days_1_19, days_20_29, days_30_plus: count and owed), by_status;
  chart months with paid, other_settled, owed.
- payments: received, lines (INVOICES, LATE_PAYMENT_CHARGES, DEPOSITS, CREDIT, REFUNDED,
  NOT_ALLOCATED, REVERSED_LATER), paid_to_invoices_by_category, reversals (minus), net,
  payment_count, received_other_currency_minor (KHR, information only); chart months
  (paid_to_invoices, deposits, other) and month_lines.
- utility_consumption: electricity_kwh, water_m3, estimate_count, period_count, and with
  `reports.read` electricity_usd_cents and water_usd_cents; chart months with kWh and m³.
- credit_ledger, deposits, final_settlements: the money columns added up, with bars; deposits
  add held_by_type, final_settlements open_count and closed_count.
- unit_occupancy: occupied, reserved, vacant, not_available, unit_count.
- lease_dates: current_count, ending_60_days_count, ending_without_renewal_count,
  terminated_count; chart months of End Dates.
- audit_activity: event_count, by_actor, by_kind; rows are days with their counts.

## Step log

- Step 1 (2026-10-25): migration `20270301_220` (three rights, new Owner and Manager bundle
  versions with an audit event each, `app.report_actor_property`, `app.home_page`); route
  `GET /api/v1/properties/{property_id}/home`; client `reportsApi.home`. The access-control test
  now lists the four `sign_in_prune.*` log event names as non-capability labels: that test
  failed on foundation 141e363 since slice 12c added them.
- Step 2 (2026-10-25): migration `20270302_221` (`app.report_income_facts`,
  `app.report_payment_facts`, `app.report_utility_facts`); `report_totals.py` builds the tables;
  route `GET /api/v1/properties/{property_id}/reports/totals/{report}` with `unit_id`, `floor`,
  `from`, `to`; client `reportsApi.totals`. Migration `20270303_222` adds the Home extras and
  finds an Invoice's Property with `app.invoice_property_id`. The head checks in seven older
  test files now name `20270303_222`.
- Step 3 (2026-10-25): migration `20270304_223` (`app.report_payment_parts`, internal, and
  `app.report_payment_facts` rebuilt on it; the register reads); `report_registers.py`; route
  `GET /api/v1/properties/{property_id}/reports/{name}` with `floor`, `from`, `to`, `offset`,
  `limit`; client `reportsApi.register`.
- Step 4 (2026-10-25): migration `20270305_224` (`app.report_export_files`,
  `app.record_report_activity`, `app.store_report_export`, `app.take_report_export`);
  `report_files.py` (.xlsx with openpyxl, PDF with reportlab) and `report_exports.py`; routes
  `POST /api/v1/properties/{property_id}/exports`, `POST .../audit-exports` and
  `GET .../exports/{export_id}`; a new audit search (first page only) writes `audit.searched`;
  client `reportsApi.exportFile`, `exportAudit` and `download`. The head checks in seven older
  test files now name `20270305_224`. Step 4 choices, decided by Claude under the owner's
  2026-10-23 22:30 rule:
  - An export of up to 1,000 rows downloads at once and is not stored. A larger one (up to
    50,000 rows) is an export job: its file is kept 24 hours for the person who made it only,
    then deleted. The audit event of every export stays.
  - The download path is Property-scoped, `/properties/{property_id}/exports/{export_id}`, in
    place of API-078's `/exports/{export_id}`, so the same Property check as every report applies.
  - Every report export writes `report.exported` and every audit export `audit.exported` with
    the file's SHA-256 fingerprint in `file_sha256` (DL-072 answer 12). The History page accepts
    an exact 64-letter hex value only in a `*_sha256` key; the floor filter is stored as
    `floor_label`.
  - A file shows a Customer by name with the Unit only: no ID number, address or document.
  - The PDF uses the built-in Helvetica font, which has no Khmer letters; Khmer text is
    readable in the .xlsx file. A Khmer PDF font is a later item.
  - Packages: openpyxl and reportlab (approved), with their typing stubs types-openpyxl and
    types-reportlab for the type check; reportlab brings pillow (MIT-CMU) and
    charset-normalizer (MIT).
- Review round 1 (2026-10-25), three blockers and five should-fix items, all fixed:
  - History must read every stored event: capability lists (`added_capability_ids`,
    `capability_ids`, of migrations 181 and 220) now pass the audit value rules; a search or
    export filter the rules refuse (free text, a control character) is left out of the event and
    counted in `filters_not_recorded_count`; an export's details are checked before they are kept.
  - A spreadsheet keeps every text as text (a name starting with "=" is never a formula) and
    drops the control characters a spreadsheet cannot hold.
  - The definer functions now get the Properties of the person's grants, not only the asked one.
  - An audit file filtered by Unit holds the events about the Unit itself, as History does.
  - Lease dates "current" counts only a signed Lease running today.
  - Rent in Unit occupancy and Lease dates shows only with `reports.read` (to confirm with the
    owner: DL-072 answer 5 says Staff see no money).
  - A PDF holds at most 5,000 rows and a file at most 25 MiB; more is refused with 422.
- Review round 2 (2026-10-25): no blocker, two should-fix items, fixed: History also reads
  older stored id lists (`*_ids`, such as `created_period_ids` of migration 72) and the `also`
  capability of migration 72's authorization evidence; the client types mark Rent as present
  only for people with `reports.read`. Nits fixed: the audit search uses `report_actor` for its
  Property list, a details fault answers 503, the file heading says "Property local time".
- Review round 3 (2026-10-25): no blocker; one should-fix fixed: a grant with a wrong Property
  id is refused (403) before the audit search reads, with a test. Nit left as is: the `also`
  key is accepted in any audit field (only migration 72 writes it).
- Step 5 (2026-10-25): full PostgreSQL run on de420c7: 2,761 passed, 15 failed. Fixed: ten older
  tests still named head `20270218_206` (now `20270306_225`); four move-out tests counted the
  new `audit.searched` events of their own History searches as changes (they now leave them
  out); the month facts failed when a Property's amounts added up past the bigint range, so
  migration `20270306_225` returns `app.report_income_facts` and `app.report_payment_facts` as
  one row per part and the application adds them up (same totals). Rerun of the 29 failed or
  changed suites on a fresh database: all pass (706 + 43). Frontend: 1,663 tests pass, build ok.
- Owner 2026-10-25 13:30 "all recommended": merge V1-057 into implementation/foundation; keep
  each Unit's Rent hidden from people without `reports.read` in Unit occupancy and Lease dates
  (screens and files).
