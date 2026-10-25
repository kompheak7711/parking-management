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
