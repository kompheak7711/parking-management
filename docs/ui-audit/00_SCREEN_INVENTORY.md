# 00 Screen inventory (UI v81, Part B1)

Date: 07/11/2026. Branch `ui-v81`. Source: `frontend/src/shell/navigation.ts` (menu, tabs, rights) and the page folders under `frontend/src/`.

How to read this list:

- **Address** is the hash route. A record page is `#/<page>/<detail>`.
- **Back** is where the "Back to X" link goes when the record was opened directly. When the person came from another page, Back returns to that page instead (shared helper `shell/backNav.tsx`).
- **Sub-tabs (v81)**: owner decision 07/11 07:55: record pages stay on one page with no sub-tabs. Sub-tabs are only for Settings and for pages that hold more than one table. A page with one table and no number cards gets no sub-tab row.
- **Batch** is the Part B batch that changes the screen.

## Menu

| Group | Menu item | Tabs (in order) | Right needed to see it |
|---|---|---|---|
| (none) | Home | – | everyone |
| Operations | Payments | – | payments.read, payments.record, receipts.read, credits.read or refunds.read |
| Operations | Invoices | Invoices, Quotations | invoices.read; quotations.read |
| Operations | Utilities | (own tabs inside the page) | utility.read |
| Operations | Approvals | – (one view; the Short-stay approvals tab of round 4 went with DL-222) | financial.approve |
| Leasing | Bookings | Reservations, Viewing requests | reservations.read; visit_requests.read |
| Leasing | Short stays | (own tabs inside the page, underlined in v81) | short_stays.read |
| Leasing | Leases | Leases, Notices, Move-outs | leases.read; rent_nonpayment.read or leases.warn; deposits.read, final_settlements.prepare or leases.move_out |
| Leasing | Customers | – | customers.read |
| Property | Units | – | units.read |
| Property | Products | Products, Stock movements, Storage locations | products.read |
| Property | Problem reports | – (v81: Monthly report becomes a tab) | problem_reports.read |
| Property | Inspections (v81, new) | Joint Inspection, Unit Check | to be set from existing rights (open question if none fits) |
| Administration | Ledger | Expense requests, Expenses, Supplier bills, Journal entries, Needs check, Chart of accounts, Financial statements, Budget, Fixed assets, Bank and cash, Month-end close | expenses.request; the rest ledger.read |
| Administration | Employees and payroll | Employees, Salary loans, Payroll, Attendance | hr.employees.read; hr.salaries.read; hr.attendance.read |
| Administration | Telegram | Linked tenants, Contact office, FAQ, Telegram health | telegram.read; telegram.contact; telegram.faq |
| Administration | Reports | – | reports.read, utility.read, leases.read or audit.view |
| Administration | Audit log | – | audit.view |
| Administration | Users and access (v81, moved out of Settings) | Users, Roles, Sign-in and security, History | identity.manage_access |
| Administration | Settings | General, Utility rates, Monthly services, Units setup, System health | settings.manage, identity.manage_access or operations.status.read |
| (top bar) | My account | – | everyone |

## Pages and record pages

| Page | Address | Record pages (detail) | Back (direct open) | Sub-tabs (v81) | Batch |
|---|---|---|---|---|---|
| Home | `#/home` | – | – | none; adds the Financial summary box (was Owner money) and the Short stays, Low stock and Attendance cards (round 7) | 3 |
| Top-bar search | (all pages) | opens the record found | – | – | 3 |
| Payments | `#/payments` | `receive`, `receive:<invoice>`, `receipt:<id>` | Payments | none; cards by Invoice type and parts on the Receipt page (round 9) | 4 |
| Invoices | `#/invoices` | `inv:<id>`, `new`, edit | Invoices | none (record on one page) | 4 |
| Quotations | `#/quotations` | `qt:<id>`, `new`, `new:<from>` | Quotations | none | 4 |
| Utilities | `#/utilities` | `meters`, `meter:<id>` | Utilities › Meters | page tabs stay | 4 |
| Approvals | `#/approvals` | – | – | one view (design tabs by kind not used: DL-222 needs no short-stay approval) | 4 |
| Reservations | `#/reservations` | `<id>`, `new:<unit>` | Bookings | none | 4 |
| Viewing requests | `#/visitreqs` | – | – | none | 4 |
| Short stays | `#/shortstays` | `st:<id>`, `new`, week report | Short stays | tabs underlined; early check-out warning | 4 |
| Leases | `#/leases` | `<id>`, `new`, `new:<unit>`, `renew:<id>` | Leases | none; History card latest 5 + History page | 4 |
| Notices | `#/letters` | `warnings` | Leases › Notices | none | 4 |
| Move-outs | `#/moveout` | `<lease>` | Move-outs | none | 4 |
| Customers | `#/customers` | `<id>` | Customers | none; Latest Receipts 5 + All Receipts page; Balance due + Full statement page; History card + History page | 4 |
| Units | `#/units` | `<id>` | Units | none; History card latest 5 + History page | 4 |
| Products | `#/products` | – | – | page tabs stay | 4 |
| Stock movements | `#/stock` | – | – | – | 4 |
| Storage locations | `#/locations` | – | – | – | 4 |
| Problem reports | `#/problems` | `pr:<id>`, `new`, `month`, `finding:<id>` | Problem reports | Monthly report becomes a tab | 4 |
| Inspections (new) | `#/inspections` (planned) | Joint Inspection, Unit Check | Inspections | tabs | 4 |
| Ledger tabs | `#/exreqs` … `#/lclose` | `exreqs/<id>`, `journal/<no>`, `chart/<line>` | the tab | Bank and cash: USD bank, Riel bank, Cash sub-tabs | 4 |
| Employees and payroll tabs | `#/employees` … `#/attendance` | employee record | Employees | none on the record | 4 |
| Telegram tabs | `#/tglinks` … `#/tghealth` | – | – | – | 4 |
| Reports | `#/reports` | `<report key>` | Reports | none; titles in normal case | 4 |
| Audit log | `#/history` | – | – | Export choice | 4 |
| Users and access (new menu item) | `#/access` (planned) | user | Users and access | Users, Roles, Sign-in and security, History | 2 |
| Settings | `#/settings/<tab>` | – | – | General first, then Utility rates, Monthly services, Units setup, System health; "Earlier forms" removed after each action is found elsewhere | 2 |
| My account | `#/account` | – | – | none | 2 |

## Shared parts used by every page (batch 1, done)

| Part | File | What it does |
|---|---|---|
| BackLink, goBack, useRemembered | `shell/backNav.tsx` | "Back to X"; the browser's own Back; parent list on a direct open; list filters kept for the browser tab |
| SubTabs, SubTabPanel | `shell/ui.tsx` | tablist with count badges, `?tab=` in the address without a history step, arrow keys |
| PanelHeader | `shell/ui.tsx` | title, one-line description, "+ Add" |
| Dialog as drawer | `shell/ui.tsx` | Add/Edit forms open on the right (full sheet ≤640px); phone Back closes it first; `confirmDiscard` asks before losing typed changes (money windows keep their own close rules) |
| DataTable, FilterBar, ColumnToggle | `shell/ui.tsx` | one table frame with filters and column choice |
| EmptyState, StatusBadge, Skeleton | `shell/ui.tsx` | empty, status and loading states |
