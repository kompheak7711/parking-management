# Recon map: Property Rental — "CHETANA Residence" (web, staff app)

Scope: the whole V1 staff application: sign-in, Home, daily work (Payments, Invoices, Utilities, Approvals), tenants (Reservations, Leases, Letters, Move-out, Customers), building (Units), office (Reports, History, Settings).
For: the owner's own business (one Property, one Owner, Managers, Staff), to be re-skinned and re-scoped (Unit → new concept, Pet deposit removed) in the clone.
Date: 2026-10-29
Source: read-only clone at `scratchpad/prm-src`, branch `implementation/foundation`, commit `df3ec76`. Recon is from the code itself (we own it), not from public pages; trademark/terms steps of the skill do not apply and no screenshots were taken.

## Sources

| # | source | path | notes |
| --- | --- | --- | --- |
| 1 | menu, routes, tabs | `frontend/src/shell/navigation.ts`, `shell/useHashPage.ts`, `App.tsx` (lines 1580-2400) | hash routes `#/<page>[/<id>]`, menu groups, capability gating per page |
| 2 | screen text EN+KM | `frontend/src/*/text.ts`, `signInText.ts`, `shell/pages.tsx` (2 732 string pairs) | every label, button, error, toast, empty state |
| 3 | page components | `frontend/src/{home,payments,invoices,utilities,approvals,units,customers,reservations,leases,letters,moveout,reports,history,settings}/*.tsx` | new design pages and dialogs |
| 4 | folded "earlier forms" (English only) | `frontend/src/*Management.tsx`, `Financial*Workspace.tsx`, `CustomerAccountLedger.tsx`, `UtilityLeaseWorkflows.tsx`, `ConfigurationManagement.tsx` | legacy panels still mounted under `<details class="ui-records">` on most pages |
| 5 | backend HTTP routes | `backend/src/property_rental/*_api.py` (34 files, 251 routes) + `auth_api.py` (`/api/v1/auth/...`) | FastAPI |
| 6 | schema | `backend/migrations/versions/*.py` (236 Alembic files, raw SQL, 235 tables in schema `app`) | the real schema, confidence high |

## Core loop

Staff record what happened in the building — a Reservation, a signed Lease, meter readings, money received — and the app turns it into Invoices, Receipts, deposits, letters and a Final Settlement, with every money-moving decision going through a Manager's approval and every action written to History.

## Business rules that shape the screens (from the text)

- One Property, Phnom Penh time, amounts in USD; riel payments converted at "ABA Sell rate + markup", rounded up, recorded at the USD value of the day.
- Billing calendar: meters read on the 24th, Rent+Utility Invoices issued on the 25th, due on the 5th; one-time Invoices due N days after issue (1-90, default 7); late-payment charge = X% of unpaid, added by the app the day after the Due Date.
- Reservation: expires at most 21 days after the Reservation Date, one extension only (Manager), suggested deposit 20% of agreed Rent; less than suggested needs Owner/Manager.
- Lease: a draft first; signed when every Signer signed the paper; Unit becomes Occupied at signing; Initial Rent = prorated + (whole next month if start ≥ day 21), due Start+5 days; Security Deposit = one month's Rent; optional Pet approval + Pet Deposit; services billed on the Rent Invoice; at most 20 services; renewal starts the day after the old End Date.
- Rent letters: day-20 warning, day-30 default notice, then termination notice (30 days); Lease rule warnings: 3 written warnings before a violation termination.
- Termination grounds: early (customer), violation (3 warnings), rent unpaid (day-30 notice), Initial Rent unpaid (after 5 days). Security Deposit kept in full on termination.
- Move-out order: hand-back → final readings → inspection and charges (damage, cleaning at the Unit Type's rate) → Final Settlement draft (staff) → Manager confirms → closed; corrections after closure are drafts.
- Every money-out or deposit decision is a draft in "Waiting for approval"; preparer may not confirm their own draft unless they hold approval rights.
- Sign-in: username+password; Owner/Managers/settings-users need TOTP MFA + 10 recovery codes; 30 min idle / 24 h max session; 3 wrong → 5 min wait; one-time password for resets; nothing is ever deleted.
- Every save has three outcomes shown to the user: saved / refused (server rule) / unknown (no answer, "Try again" resends the same idempotent command) plus "conflict" (someone changed it first; list re-read).

## Screens

Routes are hash routes. Pages hidden by capability show `NoAccess`; pages that need the Property show `PropertyNeeded` until Settings loads it. Every list page has the same states: loading, failed (+Retry), no property, not allowed, empty, filled, filtered ("Showing: … / Show all").

| ID | screen | route / how to reach | purpose | key components | states seen |
| --- | --- | --- | --- | --- | --- |
| S01 | Sign in | `/` signed out | username + password, language toggle, app facts | SignInScreens, Field, show/hide password, "Forgot your password?" link | empty, wrong credentials, too many tries (wait n min), offline, signed-out notice |
| S02 | Two-step code | after S01 for MFA users | 6-digit TOTP; switch to recovery code | code input, toggle "Use a recovery code" | bad code, bad/used recovery code, step timed out, recovery code used warning |
| S03 | Forgot password | link on S01 | explains reset (Owner gives one-time password; Owner uses server procedure) | static text, back link | — |
| S04 | Choose a new password | after one-time password sign-in | set own password (15-128 chars, not common, match) | two inputs, live rule checklist | invalid, unknown outcome |
| S05 | Set up two-step sign-in | first sign-in of MFA users | QR + key, enter first code | QR image, key text, code input | loading QR, bad code |
| S06 | Recovery codes | after S05 | show 10 codes once, copy, tick "I wrote them down" | code list, Copy, checkbox, Finish | codes not made |
| S07 | Signed out | idle 30 min / 24 h | tell why, "Sign in again" | notice | idle, day limit |
| S08 | App shell | every signed-in page | menu (Home · Daily work: Payments, Invoices, Utilities, Waiting for approval · Tenants: Bookings, Leases[Leases/Letters/Move-out], Customers · Building: Units · Office: Reports, History, Settings), top bar: page title, clock (Phnom Penh), language EN/KM, signed-in name, Sign out | AppShell, Icon set, hash router, NoAccess, PropertyNeeded, ComingSoon | menu filtered by capabilities; tabs under one item |
| S09 | Home | `#/home` | today's numbers and to-do | 4 KPI cards (Units occupied, Pending payment, Paid for month, Overdue), 4 notice cards (Lease renewal, Waiting for approval, Meter readings missing, Letters due), "What to do" list grouped Overdue/Today/This week/Later with Show more, jobs line (last billing run, ABA rate, next Invoices), quick actions Receive payment / Enter meter readings | loading, failed, not allowed, nothing overdue, "Nothing here" |
| S10 | Payments list | `#/payments` | money received by period | period chips (Today/This month/Last month/Pick dates/All), 7 category cards + "not matched yet", table (Receipt, Received on, Customer, Amount, Paid for, Status), status chips Matched/Part/Not matched/Reversed, add-up note, newest-500 note | empty period, filtered by card, riel basis note |
| S11 | Receive payment | button on S10/S09/Invoice/Customer | record a payment and what it pays | form (Customer picker w/ Unit+Phone+Unpaid, Currency USD/KHR, Amount, Method, Received on dd/mm/yyyy hh:mm, Reference, Payer note), riel→USD at app rate, "What this money pays for" tick list oldest-due-first incl. late charges, left-over notice (Credit or refund), confirm dialog, done card with Receipt number, "Receive another payment" | validation summary "Fix n thing(s)", nothing unpaid, >100 items, rate unavailable, future date, unknown/refused/changed |
| S12 | Receipt | `#/payments/<payment id>` | one Receipt per payment, print, reprint | ReceiptDocument (print CSS), Print, Reprint dialog (reason: lost/copy/other + detail), reprints list, refunded/reversed banners | not matched yet, reversed, missing, names failed |
| S13 | Invoices list | `#/invoices` | all Invoices by month and type | month chips + Pick a month, type filter (Rent/Utilities/Services/Misc/Damage), 4 cards (Total, Unpaid, Overdue, Paid), table (No., Customer, Type, Due, Amount, Balance, Status, Unit), customer filter banner, Create Invoice, Receive payment | drafts/void notes, filtered, none found |
| S14 | Invoice detail | `#/invoices/<id>` | one Invoice with status, lines, late charge, history | status card (billed/received/overdue/balance/days), lines with adjustments, Customer card, Late-payment charge section, History, actions Receive payment / Print / Issue / Adjust / Void / Edit items / Open Lease / All Invoices for Unit | draft, issued, overdue (auto or by-person banner), paid, void, not found |
| S15 | Create Invoice | button on S13 | one-time charge draft (up to 20 items) | kind of charge, Customer (signed Lease only), items (desc, qty 1-9999, unit price), reason, "what approves it", what-happens-next card, confirm dialog, done card (Open Draft) | no customer with Lease, validation |
| S16 | Issue Invoice dialog | S14 Draft | give number and Due Date (rule or chosen with reason) | dialog | date in past, reason missing |
| S17 | Adjust dialog | S14 issued | lower/raise one line with source | dialog, live "goes from X to Y" | line paid in full cannot be raised |
| S18 | Void dialog | S14 issued | void with reason | dialog | money already paid → cannot void |
| S19 | Edit items | S14 Draft from Create Invoice | change items with reason | items editor, confirm, done | not editable (not a created draft) |
| S20 | Late-payment charge reduce/waive | S14 (Manager) | reduce to ≥ paid or waive, reason code + detail | dialog | waive impossible when part paid, deposit paid part |
| S21 | Earlier Invoice forms | folded on S13 | billing runs (rent/utilities), Initial Rent Due Date, one-time charge due days, late-payment review, open invoice by ID, reconcile command | InvoiceManagement, BillingRunDiagnostics (English) | — |
| S22 | Utilities · Meter readings | `#/utilities` tab | type this month's readings | filters (Unit, floor, month, meter kind, Only not read), progress "x of y read", next-invoice note, UnitBox rows (last, new, used, result), per-row Save/Save anyway, readings grid by month | before reading day, all done, vacant/reserved notes, lower than last, much higher/lower warning, broken meter, conflict, not allowed to save |
| S23 | Utilities · Meters | tab | meters inventory | cards (Electricity, Water, Broken), filter All/Working/Broken/Replaced, table (Unit·Meter, Type, Status, Put in on, Last reading), Add meter (Manager) | none, filtered |
| S24 | Meter detail | row on S23 | one meter, readings, replace/report | facts, readings list, Report broken dialog, Replace meter dialog (serial, first reading, dates, reason) | broken since, replaced by/replaced, no reading yet |
| S25 | Import readings | button on S22 | xlsx/csv import for reading day, blank file download | ImportDialog: file pick, Check, result table (Prev, Current, Check), summary ready/fix, Confirm readings | wrong type/>2 MB/columns/rows/empty, >100 readings, changed meanwhile, per-row conflict/refused/failed |
| S26 | Earlier Utility forms | folded on S22 | install meter, bounded bulk entry, correct a reading, rate history, calculation detail, Lease utility baseline, unbilled periods, catch-up invoice, final utility inputs/invoice | UtilityManagement, UtilityLeaseWorkflows (English) | — |
| S27 | Waiting for approval | `#/approvals` | decide drafts | cards (Waiting, Money out, Deposits kept, Decided today), table (Draft, For, Prepared by, Amount, Status), draft detail "What happens when you confirm", Confirm / Reject (reason) / Withdraw (reason), decided-today list | nothing waiting, >200 oldest, view-only lock, unknown answer |
| S28 | Units list | `#/units` | all Units by status | 4 cards (Occupied, Reserved, Vacant, Not available), floor + Unit Type filters, table (Unit, Status, Monthly Rent, Until), New Unit | none match, lists failed, tenants hidden |
| S29 | Unit detail | `#/units/<unit id>` | one Unit | details (type, size m², beds, baths, view, kitchen, room features, notes, photo placeholder), Current Lease / Reservation / Availability card, Lease history, Meters, Invoices for this Unit, History; actions Make Reservation, New Lease, New Lease from Reservation, Open Lease/draft/Reservation, Change status, Update Unit | per status text, unknown access, not found |
| S30 | New Unit dialog | S28 | number, floor, type, view, kitchen, features, size, beds, baths, notes | dialog | number used, lists empty |
| S31 | Update Unit dialog | S29 | same fields, number fixed | dialog | conflict |
| S32 | Change status dialog | S29 | Vacant/Cleaning/Under maintenance/Out of service + reason | dialog | blocked by Lease / Reservation, same status |
| S33 | Unit inventory | panel (UnitInventoryPanel) | items by group with quantity, record number | panel | — |
| S34 | Customers list | `#/customers` | people with a Lease, Reservation or history | search (name, phone, Unit, ID), 4 cards (Current tenants, Signers and occupants, Reservations, Former), table (Legal name, Phone, Unit, Relationship), kind chips, Add Customer | search failed (local filter), none, tenants hidden, "Not saved" badge |
| S35 | Customer detail | `#/customers/<id>` | one person | Contact and identity, Leases and Reservations (roles), Money (Unpaid, Customer Credit, Security Deposit, Pet Deposit), Account Ledger link, Unpaid Invoices, Latest Receipts, History; Edit contact, Deactivate | deactivated, money unknown, missing |
| S36 | Add Customer | page | one person one record; duplicate check | fields (legal name, phone, email, address, DOB, gender, nationality, ID/passport, memo), "maybe same" list, "This is a different person" tick | ID taken (open existing), blocked by pending save, unknown/refused |
| S37 | Edit contact dialog | S35 | change contact fields with note that past docs do not change | dialog | nothing changed, conflict |
| S38 | Deactivate dialog | S35 | reason | dialog | — |
| S39 | Earlier Customer forms | folded on S34 (auto-opens while a save waits) | Account Ledger (filters, position summary, history, evidence), Create Customer, possible duplicates, reconcile pending save | CustomerAccountLedger, CustomerManagement (English) | coordination unavailable |
| S40 | Reservations list | `#/reservations` (menu "Bookings") | Units held | cards (Active, Ending within 7 days, Completed, Cancelled), table (Unit, Customer, Reserved on, Expires, Deposit received, Status, Result), Make Reservation | none |
| S41 | Reservation detail | `#/reservations/<id>` | one Reservation | facts, Extension card, Cancellation card, Security Deposit card (suggested/accepted/received, money outcome text), History; New Lease from Reservation, Open the Lease, Extend, Cancel | ending warning, extended once, expired, deposit keep/refund waiting |
| S42 | Make Reservation dialog | S40 / S29 | Unit (vacant), Customer (+New Customer), dates (≤21 days), agreed Rent, full deposit, received now, reason if below 20% | dialog | no vacant Unit, override needs Manager, rights unreadable, conflict |
| S43 | Extend dialog | S41 (Manager) | new expiration, memo | dialog | already extended |
| S44 | Cancel Reservation dialog | S41 | reason, responsibility Customer/Property, what was offered | dialog | — |
| S45 | Leases list | `#/leases` (tab 1 of Leases/Letters/Move-out) | every Lease | cards (Current, Ending soon, Drafts, Ended), table (Unit, Primary Tenant, Period, Rent, Deposit, Status, +n Signers), New Lease | none |
| S46 | Lease detail | `#/leases/<id>` | one Lease | banners (draft/ending/no move-in/renewed), Lease card, Signers (signed/to sign), Occupants, Rent and services (Initial Rent math, recurring rule), Deposits (Security/Pet required-received-outstanding), Termination card, History; actions Sign Lease, Edit draft, Cancel draft, Print draft, Receive Security Deposit, Record move-in, Add occupant, Renew, Terminate, Record termination notice, Open move-out | per status |
| S47 | New / Renew Lease form | S45, S29, S41 | draft terms | Unit, Primary Tenant (+Add a Customer / New Customer), other Signers, other occupants, Start/End (1 year, month end), Rent, Security Deposit (+reason when from Booking), pet approved + which pet, Services by type (only one / one or more) with rates, "What will be billed" preview, confirm dialog | services loading/failed/closed, no meters note, limit 20, booking not active, renewal start rule, partial save (deposit) |
| S48 | Edit draft dialog | S46 | dates, Rent, deposit, why changed | dialog | partial save |
| S49 | Cancel draft dialog | S46 | memo | dialog | — |
| S50 | Sign Lease dialog | S46 draft | tick every Signer; "Money to receive before signing" (deposit rest, Initial Rent, services, total), Receive X and sign | SignDialog | no terms, due passed, deposit below received, no rights, unknown |
| S51 | Receive Security Deposit dialog | S46 | required, outstanding, received now → Receipt | ReceiveDepositDialog | — |
| S52 | Record move-in dialog | S46 signed | date, who moves in (planned/others), note | MoveInDialog | date range errors |
| S53 | Add occupant dialog | S46 | Customer, move-in date | dialog | nobody to add |
| S54 | Terminate dialog | S46 | ground (early/violation/rent/unpaid initial), date, warnings ≥3, notice, evidence, reason, pet-rule keep, consequences list | TerminateDialog | waits per ground |
| S55 | Record termination notice dialog | S46 / S55 | date given, ends on, letter number, text, how given, details | RecordNoticeDialog | — |
| S56 | Print draft Lease | S46 draft | sheet for the customer to check | LeaseDraftPrint | amounts unreadable |
| S57 | Earlier Lease forms | folded on S45 | create draft, successor renewal, edit drafted terms, signers, occupants, move-in checklist, pre-signing summary, deposit/pet/service terms, terminate for unpaid Initial obligation, permanent timeline | LeaseManagement (English) | — |
| S58 | Letters · Rent letters | `#/letters` tab | unpaid Rent after day 20 | cards (Letters due, Day-20 given, Day-30 given), table (Unit and Customer, Rent month, Day-20, Day-30, Next step, Letters), Record letter, Termination notice (Manager) | none due, letters failed |
| S59 | Letters · Lease rule warnings | tab | warnings 1-3 of 3 per Lease | table (Lease, Warnings, Last warning, Breach), Record warning | none |
| S60 | Record Rent letter dialog | S58 | which (day-20/day-30), date, how given (hand/door/email/Telegram/WhatsApp/other), details, letter number | dialog | already recorded |
| S61 | Record Lease rule warning dialog | S59 | Lease, breach date, warning date, what happened, article | dialog | no Lease moved in |
| S62 | Earlier letter forms | folded on S58 | Rent nonpayment cases, current Rent alerts, unpaid Initial Rent alerts, Lease warning review | LeaseEnforcementManagement, RentNonpaymentWorkspace, LeaseWarningWorkspace (English) | — |
| S63 | Move-out list | `#/moveout` tab | Leases ending / handed back / settlements | cards (Leaving soon, Handed back, Waiting for a Manager, Closed), table (Unit, Customer, Lease ends, Handed back, Step, Deposits held) | settlements failed |
| S64 | Move-out detail | `#/moveout/<lease id>` | 6 steps: Lease ends, Hand back, Final readings, Inspection and charges, Final Settlement (statement), After closure; Deposits card; History | Step list (Done/To do/Now/Not needed/If needed) | never moved in, renewed, not within 60 days |
| S65 | Record hand-back dialog | S64 step 2 | date, keys returned, who moved out, Unit after (Cleaning/Maintenance/Out of service), note; rent rule before/after 5th | HandBackDialog | Manager-only when it ends the Lease |
| S66 | Final readings dialog | S64 step 3 | readings per meter, Save and issue final Utility Invoice / Save only | FinalReadingsDialog | no meters, unchecked reading, utility refusal codes |
| S67 | Inspection dialog | S64 step 4 | date, findings (desc, charge, evidence, pet-caused), notes; correct inspection with reason | InspectionDialog | locked when charged |
| S68 | Damage charge dialog | finding | make Draft Invoice | ChargeDialogs | charged before |
| S69 | Cleaning charge dialog | S64 step 4 | Unit's cleaning rate → Draft Invoice | ChargeDialogs | rate missing/zero/changed |
| S70 | Prepare Final Settlement dialog | S64 step 5 | statement (open items, Credit, Pet Deposit for pet damage, Security Deposit, kept deposits, remaining Pet Deposit choice), refund method + reference, reason | PrepareDialog, SettlementStep | blocked list (fi_*), waiting, closed |
| S71 | Keep deposit dialog | S64 (Manager) | record kept Security/Pet Deposit as a draft | KeepDepositDialog | refusal codes |
| S72 | After closure charge dialog | S64 step 6 | add a charge as a draft (damage/misc) | AfterClosureStep | refund later |
| S73 | Earlier Deposit forms | folded on S63 | deposit management, conditional Pet Deposit liability | DepositManagement (English) | — |
| S74 | Reports index | `#/reports` | 13 reports in 2 groups (Totals by Unit and month; Registers and lists) | report cards with Owner/Manager tag, Open report | none allowed, staff note |
| S75 | Totals report | S74 → Total Income / Total Payment / Total Electricity / Total Water | Unit × month matrix | scope (whole/floor/Unit), period, chart (stacked bars), facts (highest month/Unit, top 5), table, Export | none, failed |
| S76 | Register report | S74 → Invoice register, Payments, Utility consumption, Credit ledger, Deposits, Final Settlements, Unit occupancy, Lease dates, Audit activity | summary + by-kind chart + table | show more, as-of-today reports |
| S77 | Export dialog | S75/S76/S78 | xlsx or PDF, rows, sensitivity note, logged to History | dialog | refused (too many rows), not allowed, gone |
| S78 | History | `#/history` | audit log | filters (When: today/7/30/all, Who, Action kind, Unit, Search), table (When, Who, What happened, Record), Show more, Export audit | none, not allowed |
| S79 | Settings · Business | `#/settings` tab | Property, billing calendar, late charge, Reservations rules, Payment Methods, riel rate, document numbers | cards, Edit (days after issue), Add/Edit method dialog | read-only for non-owners |
| S80 | Settings · Rates and services | tab | Utility Rates (effective-dated, tenants told), Services + rate history, Service types, Move-out cleaning rates by Unit Type | ServiceDialog, TypeDialog, CleaningRates | refusal codes |
| S81 | Settings · Unit setup | tab | lists: Floors, Unit Types, Views, Kitchens, Room features (EN+KM names) | add/edit/remove with in-use guard | — |
| S82 | Settings · Users and sign-in | tab (Owner) | users table (Name, Role, MFA, Can change settings, State, Sign-in help), Add user, Reset sign-in (password / two-step), Disable, Settings access, End all sessions, role capability matrix, sign-in rules; re-auth dialog (password + code) | UsersTab | OTP shown once |
| S83 | Settings · System health | tab | version, DB, migration, backup, offsite, restore test, Telegram alerts, last billing run, last expiry check | read-only card | healthy / needs attention |
| S84 | Earlier settings forms | folded on S79-S82 | ConfigurationManagement (exchange-rate confirm, role bundles, access changes) | English | — |
| S85 | My account | `#/account` (top bar) | signed-in name, sign out | AppShell | — |
| S86 | Earlier Payments forms | folded on S10 | payment list/matching, KHR preview, Customer Credit list, Refunds and verified returns, allocations/receipts/payment reversals, action context evidence | FinancialManagement + 4 workspaces (English) | — |

## Flows

```
F01 Staff signs in
    S01 -> (S02 code) -> S09
    happy path clicks: 3 (username, password, Sign in) + 2 with MFA
    edge: wrong password x3 -> wait 5 min; lost phone -> recovery code; idle 30 min -> S07

F02 New user's first sign-in
    S01 (one-time password) -> S04 new password -> S05 QR + code -> S06 recovery codes -> S09
    edge: OTP expired (Owner resets again); codes not made

F03 Walk-in customer reserves a Unit
    S28/S29 or S40 -> S42 Make Reservation (+New Customer) -> S41
    then S41 Extend (once, Manager) or Cancel; expiry worker cancels at the date
    edge: deposit below 20% needs Manager; Unit changed meanwhile

F04 Reservation becomes a signed Lease and a move-in
    S41 New Lease from Reservation -> S47 draft (services, preview) -> S46 -> S50 Sign (receive rest of deposit + Initial Rent) -> Unit Occupied -> S52 Record move-in
    happy path clicks: ~12
    edge: Booking expired; Initial Rent Due Date passed; deposit below received; partial save of deposit

F05 Monthly billing cycle
    day 24: S22 readings (or S25 import) -> 25th: billing run (server) makes Rent+Utility Invoices -> S13 -> due 5th -> late charge auto (S14 banner) -> S58 day-20 / day-30 letters
    edge: meter broken (S24 replace), reading much higher than usual, earlier month not billed

F06 Money arrives
    S09/S10 -> S11 Receive payment (allocation oldest-due-first) -> S12 Receipt -> (left over -> Credit or Refund draft -> S27)
    happy path clicks: 7
    edge: riel not on the dollar grid; nothing unpaid (money waits on Receipt); unknown answer -> Try again resends the same command

F07 Unpaid Rent to termination
    S58 Record day-20 letter -> day-30 letter -> S55 termination notice (Manager) -> S54 Terminate (ground Rent) -> S64 move-out
    edge: notice period not ended; letter number missing

F08 Move-out to Final Settlement
    S64 -> S65 hand-back -> S66 final readings + final Utility Invoice -> S67 inspection (+S68/S69 charges -> S16 issue drafts) -> (S71 kept deposit draft -> S27) -> S70 prepare settlement -> S27 Manager confirms -> closed; S72 later charge
    happy path clicks: ~20 across two roles
    edge: blockers list (final utility not issued, cleaning charge missing, late decision missing, drafts pending); never moved in

F09 Manager decides a draft
    S09 notice -> S27 -> draft -> Confirm / Reject(reason) / Withdraw(reason)
    edge: preparer cannot confirm own draft; >200 waiting

F10 One-time charge
    S13 Create Invoice -> S15 items -> Draft -> Manager S16 Issue (rule or chosen Due Date) -> S14
    edge: Adjust (S17) / Void (S18) after issue; Edit items (S19) while draft

F11 Add a Customer without duplicates
    S34 Add Customer -> S36 (maybe-same list) -> tick "different person" or open existing -> S35
    edge: ID number taken; a save still waiting to be checked blocks new saves

F12 Broken meter
    S22 cannot read -> S24 Report broken -> Replace meter (serial, first reading, dates) -> S22 reads new meter
    edge: new meter date before failure; serial already used

F13 Owner changes rates and lists
    S80 schedule Utility Rate (24th, tenants told) / add Service + New rate (1st of month) / Service types / cleaning rates per Unit Type; S81 floors, Unit Types, views, kitchens, room features
    edge: item in use cannot be removed; Unit Type with Units needs a cleaning rate

F14 Owner manages users
    S82 Add user -> one-time password shown once -> F02; Reset sign-in; Disable; Settings access (re-auth with password + code); End all sessions
    edge: Staff gets settings access only after MFA set up

F15 Report and export
    S74 -> S75/S76 (scope, period) -> S77 Export xlsx/pdf -> file + History entry
    edge: >5 000 rows for PDF; Khmer names only in xlsx

F16 Unit lifecycle
    S30 New Unit (Vacant) -> S29 -> S32 Change status (Cleaning/Maintenance/Out of service) ; Occupied/Reserved set by the app
    edge: blocked by signed Lease or active Reservation

F17 Lease rule violation
    S59 Record warning x3 -> S54 Terminate (ground Violation, tick 3 warnings, optional keep Pet Deposit)

F18 Lease renewal
    S46 ending banner -> Renew -> S47 (starts day after End Date, linked) -> S50 sign
    edge: old deposit does not move by itself
```

## Components

| component | variants | states | used on |
| --- | --- | --- | --- |
| Button | primary, secondary, ghost, danger, "Manager"-badged (MANAGER tag) | default, hover, focus, disabled, busy "Saving…" | all |
| Dialog (`shell/ui.tsx`) | form dialog, confirm dialog, done card | open, busy, problem notice, outcome notice (saved/refused/unknown/conflict) | every action |
| CountCard | KPI card, filter card (click filters list) | selected, zero, hidden by capability | S09, S10, S13, S23, S27, S28, S34, S40, S45, S58, S63 |
| Chip | status (Unit, Lease, Reservation, Payment, Invoice, Move-out, Customer kind) | per status colour | lists and details |
| Table | list table with sortable-ish columns, "Showing: …/Show all", "Show more" paging | empty, filtered, capped (200/500) | all lists |
| Filter bar | period chips (Today/This month/Last month/Pick dates/All), month picker, select (floor, type, Unit, kind), search box | applied, invalid dates | lists, reports, history |
| DateInput (`shell/DateInput.tsx`) | dd/mm/yyyy, with time variant (24 h) | invalid, future, range | forms |
| Money fields | USD cents, KHR whole riel with app-rate conversion | riel not on grid, rate missing | S11, S42, S47, S51 |
| Customer picker | select with Unit · Phone · Unpaid; "+ New Customer" inline | none, loading, failed | S11, S42, S47, S53 |
| Unit picker | vacant Units / Units without meter | none free | S42, S47, S23 |
| Tick list "What this money pays for" | oldest-due-first auto ticks, manual override, late-charge rows | left over, all used, errors per row | S11 |
| Step list (Move-out) | Done / To do / Now / Not needed / If needed | — | S64 |
| Notice banners (`shell-notice`) | info, warn (NoAccess, PropertyNeeded, ComingSoon, draft/overdue/void banners) | — | all |
| Toast / outcome notice | saved, refused, unknown ("Try again" resends), conflict ("read again") | — | all saves |
| History list | per-record events with "Show earlier events" | none, incomplete | S29, S35, S41, S46, S64, S14 |
| Print documents | InvoiceDocument, ReceiptDocument, LeaseDraftPrint (print CSS) | REPRINT mark | S12, S14, S56 |
| Charts (`reports/charts.tsx`) | StackedBars, BarList | empty | S75, S76 |
| Language toggle | EN / KM; every string is an [en, km] pair; `lang` attribute per block | — | S01, S08 |
| Icon set (`shell/icons.tsx`) | home, payments, invoice, meter, check, units, customers, calendar, lease, list, moveout, reports, history, settings, info | — | menu |
| Folded "Earlier forms" `<details class="ui-records">` | English legacy panels | auto-open when a save waits | most pages |

## Inferred data model (from migrations, confidence high)

235 tables in schema `app`; most are append-only command/event/evidence tables (`*_commands`, `*_events`, `*_reversals`, `*_serialization_guards`) that implement idempotent commands and audit. The business entities:

```
Property (properties, 1 row)   id, singleton_key, timezone_name, one_time_charge_due_days, version; business configuration
                                (name, address, billing days, late %, reservation rules, document prefixes) in property_business_configuration
Unit (units)                   id, property_id, unit_number, floor, floor_item_id, unit_type, status (VACANT|RESERVED|OCCUPIED|CLEANING|
                                UNDER_MAINTENANCE|OUT_OF_SERVICE), version, created/updated by; details (size, beds, baths, view, kitchen,
                                notes) in unit_management; unit_room_features (unit_id, item_id)
UnitSetupItem (unit_setup_items) id, list_kind (FLOOR|UNIT_TYPE|VIEW|KITCHEN|ROOM_FEATURE), code, name_en, name_km, sort_order, removed_at
UnitInventory (unit_inventory_records/_lines) record_number, recorded_at; lines: item_group, item_name, quantity
Customer (customers)           id, legal_name, phone_number, email_address, contact_address, memo, id_document_number, date_of_birth,
                                (gender, nationality in later cols), deactivated_at, deactivation_reason, version; customer_email_match_keys
Reservation (reservations)     id, unit_id, customer_id, reservation_date, agreed_monthly_rent_usd_cents, original_expiration_date,
                                effective_expiration_date, status (ACTIVE|COMPLETED|CANCELLED), resulting_lease_id, cancellation_reason_code,
                                cancellation_responsibility (CUSTOMER|PROPERTY), cancelled_at, completed_at; reservation_extension_notices,
                                reservation_deposit_acceptances, reservation_lifecycle_events, reservation_expiration_runs
Lease (leases)                 id, unit_id, primary_tenant_id, status (DRAFTED|SIGNED|TERMINATED|ENDED|CANCELLED), start_date, end_date,
                                monthly_rent_usd_cents, predecessor_lease_id, signed_at, terminated_at, actual_termination_date,
                                termination_reason, version; lease_revisions (draft edits), lease_planned_security_deposits
LeaseSigner (lease_signers)    id, lease_id, customer_id, signed_at, added_at; lease_signer_history
Occupancy (occupancies)        id, lease_id, customer_id, move_in_date, move_out_date; lease_move_ins, lease_occupant_additions,
                                move_in_occupancy_links
LeasePetApproval (lease_pet_approvals) id, lease_id, approved_date, pet_description, deposit_required_by_signed_terms; lease_pet_departures;
                                pet_deposit_refund_reviews; settlement_pet_classifications   <- all removed in the clone
LeaseServiceTerm (lease_service_terms) id, lease_id, property_service_id, applicable_from, applicable_through, service_approval_period_id
Deposit (deposits)             id, deposit_type (SECURITY|PET), customer_id, reservation_id, lease_id, pet_approval_id, required_usd_cents,
                                required_effective_date; deposit_receipts (payment_id, amount), deposit_applications (final_settlement_id,
                                target invoice/line/late charge, stage, amount), deposit_dispositions (forfeiture: amount, effective_date,
                                reason), deposit_required_amount_adjustments, *_reversals
Invoice (invoices)             id, invoice_number, customer_id, lease_id, source_occupancy_id, primary_category (RENT|UTILITIES|SERVICE_CHARGES|
                                MISCELLANEOUS_CHARGES|DAMAGE_CHARGES), status (DRAFT|ISSUED|VOID…), invoice_date, due_date, billing_period_start/end,
                                rent_billing_kind, original_total_usd_cents, due_date_rule, due_date_source, due_date_override_reason, issued_at/by,
                                originating_billing_run_attempt_id, draft_reference
InvoiceLine (invoice_lines)    id, invoice_id, line_sequence, category, description, quantity, unit_price, amount (+ calculation components)
InvoiceAdjustment (invoice_adjustments) id, invoice_id, invoice_line_id, adjustment_type (CREDIT|DEBIT), amount_usd_cents, source_reference;
                                invoice_void_events, invoice_draft_revision_events, authorized_nonrecurring_obligations (one-time charges)
LatePaymentCharge (late_payment_charges) id, customer_id, source_invoice_id, late_payment_decision_id, original_amount_usd_cents, payable_at;
                                late_payment_charge_runs, _reductions, _corrections, late_payment_decisions
Payment (payments)             id, payment_number, property_id, payer_customer_id, lease_id, payment_scope_kind, identified_invoice_id,
                                identified_late_payment_charge_id, payment_date, payment_method_id (+code/name snapshot), received_currency (USD|KHR),
                                received_amount_minor, usd_accounting_value_cents, exchange_rate_record_id, channel_transaction_reference,
                                payer_intent_memo, status, confirmed_at/by; payment_reversals, payment_returns, payment_moves
PaymentAllocation (payment_allocations) id, payment_id, target_customer_id, target_kind (INVOICE|LATE_CHARGE), invoice_id, late_payment_charge_id,
                                amount_usd_cents, between/within_invoice_basis, selected_invoice_due_date, proposal_trace, posted_at/by
Receipt (receipts)             id, receipt_number, payment_id, payer_customer_id, issued_at/by, identity_snapshot; receipt_reprints (reason)
CustomerCredit (customer_credits) id, customer_id, source_payment_id, recognized_usd_cents, recognized_at/by, reason;
                                customer_credit_applications (+details, reversals)
Refund (refunds)               id, refund_number, recipient_customer_id, source_deposit_id, source_lifecycle_event_id, usd_accounting_value_cents,
                                refund_currency, refund_amount_minor, reason, processed_at/by; refund_methods (code, display_name, active),
                                refund_corrections, refund_recipient_agreements, refund_draft_details
PaymentMethod (payment_methods) id, code, display_name, accepted
ExchangeRateRecord (exchange_rate_records) reference_rate_khr_per_usd, markup_basis_points, system_rate_khr_per_usd, rate_source, applicable_at,
                                entered_by, channel_actual_* (confirmed real rate)
DocumentNumberSeries (document_number_series/_counters) document_type (INVOICE|RECEIPT|REFUND), letters, year, running number
UtilityMeter (utility_meters)  id, unit_id, serial_number, utility_type (ELECTRICITY|WATER), measurement_unit_code (kWh|m3), description,
                                installed_date, failure_date, deactivated_date, memo; utility_meter_replacements, utility_meter_failure_reports
UtilityReading (utility_readings) id, meter_id, reading_date, reading_value, validated_at/by, source_kind (typed|import|move-in|move-out);
                                utility_reading_corrections (previous_value, corrected_value, reason), utility_baseline_* (lease start readings)
UtilityRate (utility_rates)    id, utility_type, measurement_unit_code, rate_usd_per_unit, effective_date, notice_at, notice_evidence
UtilityConsumptionPeriod (utility_consumption_periods) meter, period start/end, consumption, billed invoice; broken_meter_estimates (+basis periods)
ServiceType (service_types)    id, name_en, name_km, one_per_lease, removed_at
PropertyService (property_services) id, service_code, display_name, display_name_km, (service_type); service_rates (monthly_rate_usd_cents,
                                effective_date); property_service_approval_periods
CleaningRate (cleaning_rates)  id, name_en, name_km, rate_usd_cents, removed_at; cleaning_rate_unit_types (rate_id, unit_type);
                                unit_cleaning_charges (obligation_id, lease_id, unit_id, rate)
BillingRun (billing_runs)      id, run_kind (RENT|UTILITIES), logical_run_key, request_digest; billing_run_attempts, _items, _eligible_sources
PhysicalMoveOut (physical_move_out_events) lease_id, unit_id, actual_move_out_date, unit_condition, previous/resulting_unit_status, reason,
                                supersedes_event_id; physical_move_out_occupancies; hand_back_rent_resolutions
MoveOutInspection (move_out_inspections) lease_id, inspection_date, result_text, completed_at/by, evidence_reference, supersedes_inspection_id;
                                inspection_damage_findings (ordinal, description, pet_related, amount); move_out_final_input_* (final readings)
FinalSettlement (final_settlements) id, lease_id, started_at/by, actual_termination_date_snapshot, move_out_date_snapshot, closed_at/by,
                                source_snapshot, closing_balance_due_usd_cents; settlement_invoice_items, _line_items, _late_payment_charge_items,
                                final_settlement_refund_details, settlement_corrections (+effects, refund details)
RentNonpaymentCase (rent_nonpayment_cases) lease_id, customer_id, invoice_id, rent_invoice_line_id, due_date_snapshot, opened_at;
                                rent_nonpayment_events (day-20 / day-30 letters: date, how given, letter number, details)
TerminationNotice (termination_notices) lease_id, notice_date, intended_termination_date, notice_text, (letter number, how given)
LeaseViolationWarning (lease_violation_warnings) lease_id, warning_sequence (1-3), violation_date, warning_date, violation_description, (article)
FinancialDraft (financial_drafts) id, kind (REFUND|DEPOSIT_FORFEITURE|PAYMENT_MOVE|FINAL_SETTLEMENT|SETTLEMENT_CORRECTION|…), prepare_capability,
                                payload, source_revision, reason, prepared_at/by; financial_draft_decisions (decision CONFIRM|REJECT|WITHDRAW,
                                reason, decided_at/by, result)
UserAccount (user_accounts)    actor_id, normalized_username, display_name, lifecycle_state (ACTIVE|DISABLED), mfa_policy_class, provenance;
                                password_credentials, one_time_passwords, totp_mfa_enrollments, recovery_code_sets/_codes, browser_sessions,
                                sign_in_waits/_wrong_tries, user_account_changes
Access (role_bundles, role_bundle_capabilities, user_role_assignments, user_capability_grants, capabilities, default_role_bundles)
                                roles Owner/Manager/Staff; capability strings such as payments.record, invoices.read, financial.approve,
                                settings.manage, identity.manage_access, audit.view, operations.status.read
AuditEvent (audit_events)      id, occurred_at, business_date, actor_id, action, entity_type, entity_id, reason, authorization_reference,
                                previous_state, resulting_state, correlation_id, source, outcome, customer_id, unit_id, lease_id
ReportExportFile (report_export_files) report, file_type (xlsx|pdf), file_name, content, sha256, row_count, expires_at
OperationsStatus (no table; read from backup_job, billing_runs, reservation_expiration_runs)
```

Relationships: Property 1-n Unit; Unit 1-n Meter; Unit 1-n Reservation; Unit 1-n Lease; Customer 1-n Reservation; Lease n-1 Customer (primary) and n-n Customer via LeaseSigner and Occupancy; Lease 0-1 PetApproval; Lease 1-n LeaseServiceTerm n-1 PropertyService; Reservation/Lease 1-n Deposit (SECURITY, PET); Lease 1-n Invoice 1-n InvoiceLine; Invoice 1-n LatePaymentCharge; Customer 1-n Payment 1-n PaymentAllocation → Invoice|LatePaymentCharge; Payment 1-1 Receipt; Payment 0-1 CustomerCredit; Deposit 1-n DepositReceipt (→ Payment), DepositApplication (→ FinalSettlement), DepositDisposition; Lease 0-1 PhysicalMoveOut, 0-n MoveOutInspection, 0-1 FinalSettlement; Lease 0-n RentNonpaymentCase, TerminationNotice, LeaseViolationWarning; FinancialDraft 0-1 decision; every command → AuditEvent.

## Feature matrix

See `features.csv`: 305 rows across 23 areas. Must: 194, should: 81, could: 30, skip: 0. Pet deposit rows (12, area "Pet deposit") are tagged `REMOVE in clone` in notes; brand/name rows (3) are tagged `rename in clone`.

## Out of scope (cannot or should not be cloned)

- Nothing licensed or external is owned by the app. Two external dependencies to re-decide, not clone: the ABA bank exchange-rate feed (`job_rate`) and Telegram alerts for System health. Both are optional in the clone.
- The folded "Earlier forms" (English legacy panels, S21/S26/S39/S57/S62/S73/S84/S86) are transitional UI the source itself is replacing; clone the capabilities they still hold (billing runs, Initial Rent Due Date, reading corrections, catch-up Utility Invoice, Customer Account Ledger, Credit/Refund lists, payment reversal, role bundles, exchange-rate confirm) as proper screens, not the panels.
- Pet deposit (approval, Pet Deposit, pet damage first, keep Pet Deposit, pet departures, refund reviews) will be removed per the clone's scope; listed in features.csv so the removal is explicit.

## Size

Screens 86 (14 pages, 9 tabs, ~50 dialogs, 8 legacy panels), flows 18, entities ~45 business (235 tables). Hard parts: (1) money engine — allocation oldest-due-first with late charges, KHR conversion, Credit, refunds, reversals, all idempotent with unknown-outcome recovery; (2) draft/approval workflow and the capability model; (3) Final Settlement rules and blockers; (4) full EN/KM bilingual text (2 732 pairs); (5) auth: TOTP MFA, recovery codes, one-time passwords, session rules, re-auth; (6) scheduled jobs (billing run, late charges, reservation expiry, backups) and audit of everything incl. report exports. Size: XL as a whole — rescope to the core loop (Units, Customers, Reservations, Leases, Invoices, Payments, Utilities, Approvals, basic Settings/Users) for an L first cut.
