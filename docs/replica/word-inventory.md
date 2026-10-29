# Word inventory: Property Rental (CHETANA Residence)

Source: `prm-src` branch implementation/foundation, commit df3ec76. Counts are case-insensitive regex hits per file: `property rental`, `chetana residence`, `\bunits?\b` (minus Unit Type hits), `unit[ _-]?types?`, `pet[ _-]?deposits?`. Identifiers (`unitId`, `unit_type`) count too, so a file total is "places to touch", not only screen words. Test files are listed but marked.

## Frontend files (frontend/src)

| file | Property Rental | CHETANA Residence | Unit | Unit Type | Pet deposit | note |
| --- | --- | --- | --- | --- | --- | --- |
| approvals/text.ts |  |  | 1 |  | 1 | screen text (EN+KM) |
| customers/text.ts |  |  | 6 |  | 1 | screen text (EN+KM) |
| financialActionContext.ts |  |  | 1 |  |  | screen text (EN+KM) |
| history/text.ts |  |  | 7 |  |  | screen text (EN+KM) |
| home/text.ts |  |  | 1 |  |  | screen text (EN+KM) |
| invoices/text.ts |  |  | 4 |  |  | screen text (EN+KM) |
| leases/text.ts |  |  | 23 |  | 7 | screen text (EN+KM) |
| letters/text.ts |  |  | 3 |  |  | screen text (EN+KM) |
| moveout/text.ts |  |  | 23 |  | 10 | screen text (EN+KM) |
| payments/text.ts |  |  | 2 |  |  | screen text (EN+KM) |
| reports/text.ts |  |  | 31 | 2 | 2 | screen text (EN+KM) |
| reservations/text.ts |  |  | 20 |  |  | screen text (EN+KM) |
| settings/text.ts |  |  | 16 | 7 |  | screen text (EN+KM) |
| signInText.ts |  | 2 |  |  |  | screen text (EN+KM) |
| units/text.ts |  | 2 | 36 | 1 |  | screen text (EN+KM) |
| utilities/text.ts |  |  | 30 |  |  | screen text (EN+KM) |
| App.test.tsx |  |  | 6 |  |  | test |
| App.tsx |  |  | 7 |  |  | JSX/logic |
| ConfigurationManagement.test.tsx |  |  | 2 |  |  | test |
| ConfigurationManagement.tsx |  |  | 2 |  |  | JSX/logic |
| CustomerAccountLedger.test.tsx |  |  |  |  | 1 | test |
| CustomerLedgerEvidence.tsx |  |  | 4 |  |  | JSX/logic |
| DepositManagement.test.tsx |  |  | 1 |  | 16 | test |
| DepositManagement.tsx |  |  | 1 |  | 12 | JSX/logic |
| FinancialEvidence.tsx |  |  |  |  | 3 | JSX/logic |
| FinancialManagement.tsx |  |  |  |  | 2 | JSX/logic |
| FinancialRefundWorkspace.tsx |  |  |  |  | 8 | JSX/logic |
| FinancialWorkspaces.test.tsx |  |  |  |  | 9 | test |
| LeaseEnforcementManagement.tsx |  |  | 1 |  |  | JSX/logic |
| LeaseManagement.test.tsx |  |  | 17 |  | 4 | test |
| LeaseManagement.tsx |  |  | 28 |  | 7 | JSX/logic |
| ReservationManagement.test.tsx |  |  | 3 |  |  | test |
| ReservationManagement.tsx |  |  | 5 |  |  | JSX/logic |
| UnitInventoryPanel.test.tsx |  |  | 12 |  |  | test |
| UnitInventoryPanel.tsx |  |  | 13 |  |  | JSX/logic |
| UtilityLeaseWorkflows.test.tsx |  |  | 2 |  |  | test |
| UtilityManagement.test.tsx |  |  | 2 |  |  | test |
| UtilityManagement.tsx |  |  | 8 |  |  | JSX/logic |
| approvals/ApprovalsPage.test.tsx |  |  | 10 |  |  | test |
| approvals/ApprovalsPage.tsx |  |  | 1 |  |  | JSX/logic |
| customerLedgerClient.ts |  |  |  |  | 4 | JSX/logic |
| customerLedgerFixtures.ts |  |  |  |  | 4 | JSX/logic |
| customers/CustomerDetail.tsx |  |  | 2 |  | 1 | JSX/logic |
| customers/CustomersList.tsx |  |  | 5 |  |  | JSX/logic |
| customers/CustomersPage.test.tsx |  |  | 10 |  | 4 | test |
| customers/customersData.ts |  |  | 4 |  |  | JSX/logic |
| depositClient.ts |  |  |  |  | 4 | JSX/logic |
| financialContracts.test.ts |  |  |  |  | 2 | test |
| financialContracts.ts |  |  |  |  | 5 | JSX/logic |
| financialResponse.ts |  |  |  |  | 3 | JSX/logic |
| financialUiContext.test.ts |  |  | 1 |  |  | test |
| history/HistoryPage.test.tsx |  |  | 22 |  |  | test |
| history/HistoryPage.tsx |  |  | 22 |  |  | JSX/logic |
| home/HomeScreen.test.tsx |  |  | 5 |  |  | test |
| home/HomeScreen.tsx |  |  | 21 |  |  | JSX/logic |
| invoiceClient.ts |  |  | 8 |  |  | JSX/logic |
| invoices/CreateInvoice.tsx |  |  | 9 |  |  | JSX/logic |
| invoices/InvoiceDetail.tsx |  |  | 10 |  |  | JSX/logic |
| invoices/InvoiceDocument.tsx |  | 1 | 8 |  |  | JSX/logic |
| invoices/InvoicesPage.test.tsx |  |  | 14 |  |  | test |
| invoices/LateChargeCard.tsx |  |  | 1 |  |  | JSX/logic |
| invoices/invoicesData.ts |  |  | 7 |  |  | JSX/logic |
| leaseClient.test.tsx |  |  | 2 |  |  | test |
| leaseClient.ts |  |  | 1 |  | 1 | JSX/logic |
| leases/LeaseDetail.tsx |  |  | 3 |  | 1 | JSX/logic |
| leases/LeaseDraftPrint.tsx |  |  | 1 |  | 1 | JSX/logic |
| leases/LeaseForm.tsx |  |  | 42 |  | 1 | JSX/logic |
| leases/LeasesList.tsx |  |  | 1 |  |  | JSX/logic |
| leases/LeasesPage.test.tsx |  |  | 104 |  | 4 | test |
| leases/LeasesPage.tsx |  |  | 1 |  |  | JSX/logic |
| leases/SignLeaseDialog.tsx |  |  | 4 |  |  | JSX/logic |
| leases/TerminateDialogs.tsx |  |  |  |  | 2 | JSX/logic |
| leases/leasesData.ts |  |  | 1 |  |  | JSX/logic |
| letters/LettersDialogs.tsx |  |  | 4 |  |  | JSX/logic |
| letters/LettersPage.test.tsx |  |  | 27 |  | 1 | test |
| letters/LettersPage.tsx |  |  | 2 |  |  | JSX/logic |
| letters/lettersClient.ts |  |  | 1 |  |  | JSX/logic |
| measurementUnits.ts |  |  | 1 |  |  | JSX/logic |
| moveout/ChargeDialogs.tsx |  |  | 2 |  |  | JSX/logic |
| moveout/FinalReadingsDialog.tsx |  |  | 6 |  |  | JSX/logic |
| moveout/HandBackDialog.tsx |  |  | 6 |  |  | JSX/logic |
| moveout/MoveoutPage.test.tsx |  |  | 32 |  | 12 | test |
| moveout/MoveoutPage.tsx |  |  | 5 |  |  | JSX/logic |
| moveout/PrepareDialog.tsx |  |  |  |  | 2 | JSX/logic |
| moveout/SettlementStep.tsx |  |  | 1 |  | 2 | JSX/logic |
| moveout/charges.ts |  |  | 2 |  |  | JSX/logic |
| moveout/moveoutClient.test.ts |  |  | 2 |  |  | test |
| moveout/moveoutClient.ts |  |  | 2 |  |  | JSX/logic |
| moveout/moveoutData.ts |  |  | 3 |  | 1 | JSX/logic |
| moveout/plan.test.ts |  |  |  |  | 6 | test |
| moveout/plan.ts |  |  |  |  | 8 | JSX/logic |
| moveout/settlement.ts |  |  |  |  | 3 | JSX/logic |
| payments/PaymentsList.test.tsx |  |  | 1 |  |  | test |
| payments/PaymentsList.tsx |  |  | 2 |  |  | JSX/logic |
| payments/PaymentsPage.tsx |  |  | 1 |  |  | JSX/logic |
| payments/ReceiptDocument.tsx |  | 1 | 5 |  | 1 | JSX/logic |
| payments/ReceiptPage.tsx |  |  | 4 |  |  | JSX/logic |
| payments/ReceivePayment.tsx |  |  | 10 |  |  | JSX/logic |
| reports/RegisterView.test.tsx |  |  | 25 | 4 | 2 | test |
| reports/RegisterView.tsx |  |  | 6 | 3 |  | JSX/logic |
| reports/ReportsPage.test.tsx |  |  | 25 |  |  | test |
| reports/ReportsPage.tsx |  |  | 27 | 3 |  | JSX/logic |
| reports/TotalsView.test.tsx |  |  | 31 |  |  | test |
| reports/TotalsView.tsx |  |  | 6 |  |  | JSX/logic |
| reports/charts.test.tsx |  |  | 6 |  |  | test |
| reports/parts.tsx |  |  | 3 |  |  | JSX/logic |
| reports/reportsData.ts |  |  | 6 |  |  | JSX/logic |
| reports/reportsTestData.tsx |  |  | 54 | 3 |  | JSX/logic |
| reportsClient.ts |  |  | 3 | 1 |  | JSX/logic |
| reservationClient.test.ts |  |  | 1 |  |  | test |
| reservations/MakeReservationDialog.test.tsx |  |  | 30 |  |  | test |
| reservations/MakeReservationDialog.tsx |  |  | 25 |  |  | JSX/logic |
| reservations/ReservationDetail.tsx |  |  | 3 |  |  | JSX/logic |
| reservations/ReservationsList.tsx |  |  | 1 |  |  | JSX/logic |
| reservations/ReservationsPage.test.tsx |  |  | 16 |  |  | test |
| reservations/ReservationsPage.tsx |  |  | 3 |  |  | JSX/logic |
| reservations/reservationsData.ts |  |  | 1 |  |  | JSX/logic |
| settings/BusinessTab.test.tsx |  | 4 | 2 |  |  | test |
| settings/BusinessTab.tsx |  |  | 11 |  |  | JSX/logic |
| settings/CleaningRates.test.tsx |  |  | 5 | 9 |  | test |
| settings/CleaningRates.tsx |  |  |  | 19 |  | JSX/logic |
| settings/RatesTab.test.tsx |  |  |  | 1 |  | test |
| settings/RatesTab.tsx |  |  |  | 1 |  | JSX/logic |
| settings/SettingsPage.test.tsx |  | 1 | 2 | 1 |  | test |
| settings/SettingsPage.tsx |  |  | 4 |  |  | JSX/logic |
| settings/UnitSetupTab.test.tsx |  |  | 9 | 16 |  | test |
| settings/UnitSetupTab.tsx |  |  | 16 | 8 |  | JSX/logic |
| settings/serviceSettingsClient.test.ts |  |  |  | 8 |  | test |
| settings/serviceSettingsClient.ts |  |  |  | 14 |  | JSX/logic |
| settlementClient.test.tsx |  |  | 1 |  |  | test |
| settlementClient.ts |  |  | 2 |  |  | JSX/logic |
| settlementForms.ts |  |  |  |  | 2 | JSX/logic |
| shell/AppShell.test.tsx |  |  | 11 |  |  | test |
| shell/AppShell.tsx |  | 2 | 1 |  |  | JSX/logic |
| shell/accessClient.test.tsx |  |  | 1 |  |  | test |
| shell/icons.tsx |  |  | 2 |  |  | JSX/logic |
| shell/navigation.ts |  |  | 15 |  |  | screen text (EN+KM) |
| shell/useHashPage.ts |  |  | 2 |  |  | JSX/logic |
| test/customerLedger.browser.tsx |  |  |  |  | 1 | test |
| test/financialActionContextFixtures.ts |  |  |  |  | 3 | test |
| test/financialWorkflows.browser.ts |  |  |  |  | 2 | test |
| unitClient.test.ts |  |  | 6 | 5 |  | test |
| unitClient.ts |  |  | 15 | 14 |  | JSX/logic |
| units/UnitDetail.tsx |  | 1 | 72 | 1 |  | JSX/logic |
| units/UnitDialogs.tsx |  |  | 53 | 8 |  | JSX/logic |
| units/UnitsList.tsx |  |  | 34 | 6 |  | JSX/logic |
| units/UnitsPage.test.tsx |  | 6 | 89 | 14 | 1 | test |
| units/UnitsPage.tsx |  |  | 18 |  |  | JSX/logic |
| units/unitsData.ts |  |  | 10 | 1 |  | JSX/logic |
| utilities/ImportDialog.tsx |  |  | 30 |  |  | JSX/logic |
| utilities/MetersTab.tsx |  |  | 39 |  |  | JSX/logic |
| utilities/UnitBox.tsx |  |  | 27 |  |  | JSX/logic |
| utilities/UtilitiesPage.test.tsx |  |  | 108 | 1 |  | test |
| utilities/UtilitiesPage.tsx |  |  | 40 |  |  | JSX/logic |
| utilities/utilitiesData.ts |  |  | 41 |  |  | JSX/logic |
| utilityClient.test.tsx |  |  | 9 |  |  | test |
| utilityClient.ts |  |  | 8 |  |  | JSX/logic |
| utilityLeaseClient.test.ts |  |  | 1 |  |  | test |
| **total (158 files, 48 tests)** | **0** | **20** | **1713** | **151** | **167** | |

Outside frontend/src: `frontend/index.html` has "Property Rental Management" twice (title + meta description); `backend/pyproject.toml` has "Property Rental" once (package description). The sign-in screen calls the app "Residence Management" (`signInText.ts` au_app) and the shell header says "CHETANA Residence" (`shell/AppShell.tsx` line 24).

## Khmer words used for Unit, Unit Type, Property Rental

| Khmer | used for | rows | files | example (file · key · EN → KM) |
| --- | --- | --- | --- | --- |
| បន្ទប់ | Unit (room) | 164 | approvals/text.ts, customers/text.ts, history/text.ts, home/text.ts, invoices/text.ts, leases/text.ts, letters/text.ts, moveout/text.ts, payments/text.ts, reports/text.ts, reservations/text.ts, settings/text.ts, shell/navigation.ts, units/text.ts, utilities/text.ts | customers/text.ts · search · Search by name, phone, Unit or ID number → ស្វែងរកតាមឈ្មោះ ទូរស័ព្ទ បន្ទប់ ឬលេខអត្ត |
| ប្រភេទបន្ទប់ | Unit Type | 6 | reports/text.ts, settings/text.ts, units/text.ts | settings/text.ts · cf_UNIT_TYPE · Unit Types → ប្រភេទបន្ទប់ |
| ឯកតា | "unit" in "unit price" only (not the room) | 3 | invoices/text.ts | invoices/text.ts · ni_price · Unit price → តម្លៃឯកតា |
| ផ្ទះ | (house) — not used for Unit | 0 | — | — |
| យូនីត | (transliteration) — not used | 0 | — | — |

No Khmer rendering of "Property Rental" exists: the app name is left in English in both languages (`au_app: ["Residence Management", "Residence Management"]`). "CHETANA Residence" is also kept in Latin script inside Khmer strings (e.g. units/text.ts `sub`: "បន្ទប់ {0} នៅ CHETANA Residence").

Pet Deposit in Khmer: see rows with key `pet`, `dep_pet`, `dep_PET`, `fs_pet_*`, `kd_btn_PET`, `tg_petrule`, `dk_PET_FORFEIT` in customers/leases/moveout/approvals/reports text files (counted in the Pet deposit column above).

## Backend files with these English words in string literals (backend/src/property_rental)

Counted per string literal (any quoted string containing the word), so these include refusal messages, audit reasons, report column headers, PDF/letter text and some enum/code names. The user-facing ones to touch first are marked.

| file | Property Rental | CHETANA Residence | Unit | Unit Type | Pet deposit | likely user-facing |
| --- | --- | --- | --- | --- | --- | --- |
| unit_api.py |  |  | 44 |  |  | yes — refusals |
| unit.py |  |  | 21 |  |  | check (reasons/codes) |
| final_settlement_api.py |  |  |  |  | 9 | check (reasons/codes) |
| api_refusals.py |  |  | 4 |  | 4 | yes — refusal messages shown in the UI |
| deposit_api.py |  |  |  |  | 6 | check (reasons/codes) |
| invoice_api.py |  |  | 6 |  |  | check (reasons/codes) |
| final_settlement.py |  |  |  |  | 5 | check (reasons/codes) |
| invoice.py |  |  | 5 |  |  | check (reasons/codes) |
| lease_signing_api.py |  |  | 4 |  |  | check (reasons/codes) |
| draft_record_api.py |  |  | 3 |  | 1 | check (reasons/codes) |
| settlement_correction.py |  |  |  |  | 4 | check (reasons/codes) |
| access_control.py |  |  | 3 |  | 1 | check (reasons/codes) |
| credit_refund_api.py |  |  |  |  | 3 | check (reasons/codes) |
| unit_inventory_api.py |  |  | 3 |  |  | yes |
| deposit.py |  |  |  |  | 3 | check (reasons/codes) |
| payment_move.py |  |  | 3 |  |  | check (reasons/codes) |
| report_exports.py |  |  | 3 |  |  | check (reasons/codes) |
| report_files.py |  | 1 | 2 |  |  | check (reasons/codes) |
| utility_sheet.py |  |  | 3 |  |  | check (reasons/codes) |
| reservation.py |  |  | 2 |  |  | check (reasons/codes) |
| audit_api.py |  |  | 2 |  |  | check (reasons/codes) |
| move_in.py |  |  | 2 |  |  | check (reasons/codes) |
| customer_ledger_query.py |  |  |  |  | 2 | check (reasons/codes) |
| app.py |  |  |  |  | 2 | check (reasons/codes) |
| lease.py |  |  | 1 |  | 1 | check (reasons/codes) |
| refund.py |  |  | 1 |  | 1 | check (reasons/codes) |
| auth_flow.py |  | 1 |  |  |  | check (reasons/codes) |
| customer_ledger.py |  |  |  |  | 1 | check (reasons/codes) |
| move_out_api.py |  |  | 1 |  |  | check (reasons/codes) |
| unpaid_initial_termination.py |  |  | 1 |  |  | check (reasons/codes) |
| settlement_correction_api.py |  |  | 1 |  |  | check (reasons/codes) |
| report_registers.py |  |  | 1 |  |  | check (reasons/codes) |
| lease_api.py |  |  | 1 |  |  | check (reasons/codes) |
| utility_baseline.py |  |  | 1 |  |  | check (reasons/codes) |
| __init__.py | 1 |  |  |  |  | check (reasons/codes) |
| reports_api.py |  |  | 1 |  |  | yes — report titles/column headers |
| financial_draft_api.py |  |  | 1 |  |  | check (reasons/codes) |
| report_totals.py |  |  | 1 |  |  | check (reasons/codes) |
| reports.py |  |  | 1 |  |  | check (reasons/codes) |
| operations_check.py |  | 1 |  |  |  | check (reasons/codes) |
| physical_move_out.py |  |  | 1 |  |  | check (reasons/codes) |
| **total (41 files)** | **1** | **3** | **123** | **0** | **43** | |
