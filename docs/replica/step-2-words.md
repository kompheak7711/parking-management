# Step 2: changed words (Parking Rental)

Branch `step-2-wording`. Only words staff see changed. Hidden code names (`unit`, `unit_type`, `#/units`, table and column names, file names, `Unit` class, route docstrings, comments) are unchanged.

## Word rules (owner answers, 2026-10-29)

| Before (English) | After (English) | Before (Khmer) | After (Khmer) |
|---|---|---|---|
| Unit | Parking | បន្ទប់ | ចំណត |
| Units | Parking (same word for one and many; never "Parkings") | បន្ទប់ | ចំណត |
| Unit Type / Unit Types | Parking Type / Parking Types | ប្រភេទបន្ទប់ | ប្រភេទចំណត |
| Unit inventory / Unit features | Parking inventory / Parking features | (no Khmer word for Unit here) | unchanged |
| Unit price (Invoice line) | unchanged | ឯកតា | unchanged |
| Kitchen | unchanged | ផ្ទះបាយ | unchanged |
| Parking Rental (app name) | unchanged | English in both languages | unchanged |

## Reworded sentences (plural verb no longer fits)

| Where | Before | After |
|---|---|---|
| Parking list, empty filter result | No Units match these filters. | No Parking matches these filters. |
| Utilities, readings file help | The Units are already filled in, so staff type only the readings. | The Parking is already filled in, so staff type only the readings. |

Sentences that keep "Parking" for many and still read as English, but may look odd (owner may ask to reword): "{0} Parking at CHETANA Parking", "{0} Parking", "All Parking", "Top 5 Parking", "Parking occupied", "Parking by status", "No Parking yet". "Loading the Parking…" was reworded to "Loading Parking…" on the owner's answer.

## Two places where the code name reached the screen (fixed)

1. History screen: the "what happened" column is built from the server's action code (`unit.status_changed` showed "Unit status changed"). `history/text.ts` `actionText` now shows the code name `unit` as "parking" ("Parking status changed"). Test TEST-FE-958 covers it.
2. Readings file (.xlsx/.csv) header: the downloaded blank file now says "Parking, Electricity, Water". The upload reader accepts both "Parking" and the old "Unit" header (any order, any case).

## Words the database writes or raises (kept as "Unit" in code; one is visible)

PostgreSQL functions created by earlier migrations raise fixed English error texts, and the backend finds the right refusal by that exact text. Those lookup keys keep the "Unit" text (for example "Unit has an open Occupancy", "The Unit has no cleaning rate"); the message staff see for each says "Parking". One database-written text is visible: the move-out cleaning charge Invoice line is described as "Unit cleaning charge" by the database function (migration 81). Changing it needs a new migration; see the report's question.

## Not changed on purpose

- Migration 227 seed list for Unit Types ("1 bedroom" បន្ទប់គេង ១, "2 bedrooms", "3 bedrooms", Studio): migrations are history and the owner enters the Parking Types in Step 3.
- Python docstrings, route docstrings, code comments, CSS comments, test IDs (TEST-FE-nnn, TEST-BE-nnn), SQL test fixture names ("Unit Tester").
- "Unit price" on Invoices (a measure word).

## Every changed English screen string (349 lines, frontend)

| File | English before | English after |
|---|---|---|
| App.test.tsx | Home / Customers / Units | Home / Customers / Parking |
| App.test.tsx | main / Units | main / Parking |
| LeaseManagement.test.tsx | Unit version | Parking version |
| LeaseManagement.test.tsx | Unit identifier | Parking identifier |
| LeaseManagement.test.tsx | Create Lease Unit input is absent | Create Lease Parking input is absent |
| LeaseManagement.test.tsx | Unit after release | Parking after release |
| LeaseManagement.test.tsx | Unit status reason (required for CLEANING) | Parking status reason (required for CLEANING) |
| LeaseManagement.test.tsx | Unit CLEANING | Parking CLEANING |
| LeaseManagement.tsx | Revalidating parties, terms, and non-overlapping Unit periods… | Revalidating parties, terms, and non-overlapping Parking periods… |
| LeaseManagement.tsx | Lease terminated for an unpaid Initial obligation. Resolve the Security Deposit, Invoice and Unit explicitly below; nothing was changed automatically. | Lease terminated for an unpaid Initial obligation. Resolve the Security Deposit, Invoice and Parking explicitly below; nothing was changed automatically. |
| LeaseManagement.tsx | Enter the termination event, the reason and, for CLEANING, the Unit reason. | Enter the termination event, the reason and, for CLEANING, the Parking reason. |
| LeaseManagement.tsx | VOID or credit the Initial Rent Invoice and release the Unit? The Security Deposit stays held until a forfeiture draft is confirmed. This cannot be edited afterwards. | VOID or credit the Initial Rent Invoice and release the Parking? The Security Deposit stays held until a forfeiture draft is confirmed. This cannot be edited afterwards. |
| LeaseManagement.tsx | Complete the coordinated Reservation, Lease, Unit, and Occupancy transition? | Complete the coordinated Reservation, Lease, Parking, and Occupancy transition? |
| LeaseManagement.tsx | `Move-in completed atomically. Reservation version ${String(result.reservation_version)}, Unit version ${String(result.unit_version)}, and Deposit ${result.deposit_id} remain linked.`, | `Move-in completed atomically. Reservation version ${String(result.reservation_version)}, Parking version ${String(result.unit_version)}, and Deposit ${result.deposit_id} remain linked.`, |
| LeaseManagement.tsx | Unit identifier | Parking identifier |
| LeaseManagement.tsx | <th>Unit</th> | <th>Parking</th> |
| LeaseManagement.tsx | <dt>Unit</dt> | <dt>Parking</dt> |
| LeaseManagement.tsx | {selected.signers.length} Signer(s); Unit {selected.unit_number} |   |
| LeaseManagement.tsx |   | {selected.unit_number}; {selected.start_date}– |
| LeaseManagement.tsx | {money(selected.monthly_rent_usd_cents)} monthly. The server |   |
| LeaseManagement.tsx | rechecks required parties, source terms, and non-overlap. | monthly. The server rechecks required parties, source terms, and |
| LeaseManagement.tsx | Reservation and Unit identities and versions will be | Reservation and Parking identities and versions will be |
| LeaseManagement.tsx | Unit version | Parking version |
| LeaseManagement.tsx | credits its unpaid lines, and releases the Unit. The Security | credits its unpaid lines, and releases the Parking. The |
| LeaseManagement.tsx | Deposit stays held until a forfeiture draft under BR-LEASE-005 | Security Deposit stays held until a forfeiture draft under |
| LeaseManagement.tsx | is confirmed by a financial.approve holder. | BR-LEASE-005 is confirmed by a financial.approve holder. |
| LeaseManagement.tsx | Unit after release | Parking after release |
| LeaseManagement.tsx | Unit status reason (required for CLEANING) | Parking status reason (required for CLEANING) |
| LeaseManagement.tsx | `; Unit ${followUp.resulting_unit_status}`} | `; Parking ${followUp.resulting_unit_status}`} |
| ReservationManagement.test.tsx | Available Unit identifier / unit-1 | Available Parking identifier / unit-1 |
| ReservationManagement.tsx | <th>Unit</th> | <th>Parking</th> |
| ReservationManagement.tsx | Available Unit identifier | Available Parking identifier |
| ReservationManagement.tsx | Cancellation releases the Unit at once. No free-form forfeiture | Cancellation releases the Parking at once. No free-form |
| ReservationManagement.tsx | is offered: the {money(selected.deposit_received_usd_cents)} |   |
| UnitInventoryPanel.test.tsx | Unit inventory | Parking inventory |
| UnitInventoryPanel.test.tsx | Unit inventory saved. The earlier list stays in History. | Parking inventory saved. The earlier list stays in History. |
| UnitInventoryPanel.test.tsx | No inventory has been recorded for this Unit yet. | No inventory has been recorded for this Parking yet. |
| UnitInventoryPanel.test.tsx | TEST-FE-822 adds an Another item that is already listed to that item and loads the new Unit after a switch | TEST-FE-822 adds an Another item that is already listed to that item and loads the new Parking after a switch |
| UnitInventoryPanel.tsx | Unit inventory is unavailable for this session. | Parking inventory is unavailable for this session. |
| UnitInventoryPanel.tsx | The Unit inventory request was not completed. Retry when the service is available. | The Parking inventory request was not completed. Retry when the service is available. |
| UnitInventoryPanel.tsx | Saving the Unit inventory… | Saving the Parking inventory… |
| UnitInventoryPanel.tsx | Unit inventory saved. The earlier list stays in History. | Parking inventory saved. The earlier list stays in History. |
| UnitInventoryPanel.tsx | Enter how many of each item are in the Unit. 0 takes an item out. | Enter how many of each item are in the Parking. 0 takes an item out. |
| UnitInventoryPanel.tsx | No inventory has been recorded for this Unit yet. | No inventory has been recorded for this Parking yet. |
| UtilityManagement.test.tsx | Unit identifier | Parking identifier |
| UtilityManagement.tsx | <p>No Meters are recorded for this Unit.</p> | <p>No Meters are recorded for this Parking.</p> |
| UtilityManagement.tsx | Unit and Utility Type is available. No comparable Unit or | Parking and Utility Type is available. No comparable Parking |
| UtilityManagement.tsx | arbitrary estimate is allowed. | or arbitrary estimate is allowed. |
| approvals/ApprovalsPage.test.tsx | TEST-FE-932 shows the four cards, the waiting drafts oldest first with their names, Unit, Customer, preparer and amount, the cards filter the list, and what was decided today | TEST-FE-932 shows the four cards, the waiting drafts oldest first with their names, Parking, Customer, preparer and amount, the cards filter the list, and what was decided today |
| approvals/ApprovalsPage.test.tsx | Move payment to the right Unit | Move payment to the right Parking |
| approvals/ApprovalsPage.test.tsx | Open: Move payment to the right Unit | Open: Move payment to the right Parking |
| approvals/ApprovalsPage.test.tsx | Move payment to the right Unit withdrawn. No money moved. | Move payment to the right Parking withdrawn. No money moved. |
| approvals/text.ts | Move payment to the right Unit | Move payment to the right Parking |
| customers/CustomersPage.test.tsx | TEST-FE-826 shows each Customer with the phone, the Unit and the relationship from the Leases and Reservations | TEST-FE-826 shows each Customer with the phone, the Parking and the relationship from the Leases and Reservations |
| customers/CustomersPage.test.tsx | Legal name / Phone / Unit / Relationship | Legal name / Phone / Parking / Relationship |
| customers/CustomersPage.test.tsx | TEST-FE-827 filters by count card and by name, phone or Unit, and Search asks the server for a whole ID number | TEST-FE-827 filters by count card and by name, phone or Parking, and Search asks the server for a whole ID number |
| customers/CustomersPage.test.tsx | Search by name, phone, Unit or ID number | Search by name, phone, Parking or ID number |
| customers/CustomersPage.test.tsx | Your account cannot read Leases or Reservations, so Unit and Relationship show “—”. | Your account cannot read Leases or Reservations, so Parking and Relationship show “—”. |
| customers/text.ts | Search by name, phone, Unit or ID number | Search by name, phone, Parking or ID number |
| customers/text.ts | The search could not run. The list still filters by name, phone and Unit. | The search could not run. The list still filters by name, phone and Parking. |
| customers/text.ts | Your account cannot read Leases or Reservations, so Unit and Relationship show “—”. | Your account cannot read Leases or Reservations, so Parking and Relationship show “—”. |
| customers/text.ts | Holding a Unit, Lease not signed yet | Holding a Parking, Lease not signed yet |
| history/HistoryPage.test.tsx | Unit | Parking |
| history/HistoryPage.test.tsx | Unit status changedReason: Repair done | Parking status changedReason: Repair done |
| history/HistoryPage.test.tsx | link / Unit U203 / href | link / Parking U203 / href |
| history/HistoryPage.test.tsx | TEST-FE-959 Search sends the period, the person and the Unit; Export audit sends the same filters and saves the file; a refused export says why; no audit.export hides it | TEST-FE-959 Search sends the period, the person and the Parking; Export audit sends the same filters and saves the file; a refused export says why; no audit.export hides it |
| history/HistoryPage.test.tsx | Unit / option | Parking / option |
| history/text.ts | .toLowerCase(); | .toLowerCase() |
| home/HomeScreen.test.tsx | Units occupied | Parking occupied |
| home/HomeScreen.test.tsx | expect(card(/Units occupied/).textContent).toContain( | expect(card(/Parking occupied/).textContent).toContain( |
| invoices/InvoicesPage.test.tsx | TEST-FE-896 The list shows the four cards with their amounts, the add-up line and every Invoice with the Draft first, its Customer and Unit, Due Date, amount, balance and status | TEST-FE-896 The list shows the four cards with their amounts, the add-up line and every Invoice with the Draft first, its Customer and Parking, Due Date, amount, balance and status |
| invoices/InvoicesPage.test.tsx | Unit U101 | Parking U101 |
| leaseClient.test.tsx | TEST-FE-185 sends bounded status, Unit, Customer, date, and period filters | TEST-FE-185 sends bounded status, Parking, Customer, date, and period filters |
| leaseClient.ts | The Lease changed or conflicts with current Unit availability. Reload before retrying. | The Lease changed or conflicts with current Parking availability. Reload before retrying. |
| leases/LeasesPage.test.tsx | Unit | Parking |
| leases/LeasesPage.test.tsx | await screen.findByText(/This Lease or its Unit changed meanwhile/), | await screen.findByText(/This Lease or its Parking changed meanwhile/), |
| leases/LeasesPage.test.tsx | TEST-FE-853 a draft whose Customer has an active Booking of the Unit takes only the rest of its deposit; a refusal saves nothing and shows why, and changed values are a new request | TEST-FE-853 a draft whose Customer has an active Booking of the Parking takes only the rest of its deposit; a refusal saves nothing and shows why, and changed values are a new request |
| leases/LeasesPage.test.tsx | An active Reservation of this Customer for this Unit is completed in the same step | An active Reservation of this Customer for this Parking is completed in the same step |
| leases/LeasesPage.test.tsx | UnitU301 | ParkingU301 |
| leases/LeasesPage.test.tsx |  Customer chose another Unit  |  Customer chose another Parking  |
| leases/LeasesPage.test.tsx | Customer chose another Unit | Customer chose another Parking |
| leases/LeasesPage.test.tsx | TEST-FE-857 New Lease offers open Units, fills a one-year End Date, previews the bill, asks before saving and keeps the Lease id on Try again | TEST-FE-857 New Lease offers open Parking, fills a one-year End Date, previews the bill, asks before saving and keeps the Lease id on Try again |
| leases/LeasesPage.test.tsx | Choose a Unit / U401 / U402 | Choose a Parking / U401 / U402 |
| leases/LeasesPage.test.tsx | Unit / unit-U402 | Parking / unit-U402 |
| leases/LeasesPage.test.tsx | TEST-FE-1010 New Lease says when the chosen Unit has no electricity or water meter on the Start Date (nothing of that kind is billed); a meter put in later counts from its day; a failed meter read shows nothing | TEST-FE-1010 New Lease says when the chosen Parking has no electricity or water meter on the Start Date (nothing of that kind is billed); a meter put in later counts from its day; a failed meter read shows nothing |
| leases/LeasesPage.test.tsx | This Unit has no electricity or water meter, so no Utilities are billed. Add the meters in Utilities when they are put in. | This Parking has no electricity or water meter, so no Utilities are billed. Add the meters in Utilities when they are put in. |
| leases/LeasesPage.test.tsx | This Unit has no electricity meter, so no electricity is billed. Add the meter in Utilities when it is put in. | This Parking has no electricity meter, so no electricity is billed. Add the meter in Utilities when it is put in. |
| leases/LeasesPage.test.tsx | TEST-FE-1075 New Lease from a Unit page opens with that Unit chosen and still lets it change; a Unit a walk-in Lease may not use is not chosen | TEST-FE-1075 New Lease from a Parking page opens with that Parking chosen and still lets it change; a Parking a walk-in Lease may not use is not chosen |
| leases/LeasesPage.test.tsx | Unit /  | Parking /  |
| leases/LeasesPage.test.tsx | TEST-FE-858 a Lease from a Booking takes its Unit, Customer, Rent and Security Deposit | TEST-FE-858 a Lease from a Booking takes its Parking, Customer, Rent and Security Deposit |
| leases/LeasesPage.test.tsx | Unit / U403 | Parking / U403 |
| leases/LeasesPage.test.tsx | TEST-FE-859 Renew starts the day after the old End Date with the same Unit, tenant and other Signers, linked to the old Lease | TEST-FE-859 Renew starts the day after the old End Date with the same Parking, tenant and other Signers, linked to the old Lease |
| leases/LeasesPage.test.tsx | Unit / U101 | Parking / U101 |
| leases/LeasesPage.test.tsx | The Unit stays Occupied until the hand-back is recorded. | The Parking stays Occupied until the hand-back is recorded. |
| leases/text.ts | Signed, Unit is Occupied. Record the move-in when the Customer receives the keys (Start Date {0}). | Signed, Parking is Occupied. Record the move-in when the Customer receives the keys (Start Date {0}). |
| leases/text.ts | Every Signer is responsible for the whole balance, not a share. A Signer need not live in the Unit. | Every Signer is responsible for the whole balance, not a share. A Signer need not live in the Parking. |
| leases/text.ts | An active Reservation of this Customer for this Unit is completed in the same step; its deposit continues as the Security Deposit. | An active Reservation of this Customer for this Parking is completed in the same step; its deposit continues as the Security Deposit. |
| leases/text.ts | The Reservations could not be read. If this Unit is Reserved, the signing will be refused; ask someone who can see Reservations. | The Reservations could not be read. If this Parking is Reserved, the signing will be refused; ask someone who can see Reservations. |
| leases/text.ts | This Lease or its Unit changed meanwhile, so nothing more was saved. It was read again: check it and try again. | This Lease or its Parking changed meanwhile, so nothing more was saved. It was read again: check it and try again. |
| leases/text.ts | Only a draft is cancelled; a signed Lease never is. The Unit and any Booking stay as they are. | Only a draft is cancelled; a signed Lease never is. The Parking and any Booking stay as they are. |
| leases/text.ts | From the Booking of {0}: the Unit, the Customer, the agreed Rent and the deposit come from it. | From the Booking of {0}: the Parking, the Customer, the agreed Rent and the deposit come from it. |
| leases/text.ts | The new Lease for {0} starts the day after the old End Date and is linked to it. The Unit stays Occupied. | The new Lease for {0} starts the day after the old End Date and is linked to it. The Parking stays Occupied. |
| leases/text.ts | The Units and Customers could not be read just now. Check the connection and your access, and try again. | The Parking and Customers could not be read just now. Check the connection and your access, and try again. |
| leases/text.ts | Vacant, cleaning or maintenance Units. A Reserved Unit gets its Lease from its Booking. | Vacant, cleaning or maintenance Parking. A Reserved Parking gets its Lease from its Booking. |
| leases/text.ts | This Unit has no electricity meter, so no electricity is billed. Add the meter in Utilities when it is put in. | This Parking has no electricity meter, so no electricity is billed. Add the meter in Utilities when it is put in. |
| leases/text.ts | This Unit has no water meter, so no water is billed. Add the meter in Utilities when it is put in. | This Parking has no water meter, so no water is billed. Add the meter in Utilities when it is put in. |
| leases/text.ts | This Unit has no electricity or water meter, so no Utilities are billed. Add the meters in Utilities when they are put in. | This Parking has no electricity or water meter, so no Utilities are billed. Add the meters in Utilities when they are put in. |
| leases/text.ts | The server refused the draft. Another Lease may already cover this Unit for these dates, or the details do not fit the rules. Nothing more was saved. | The server refused the draft. Another Lease may already cover this Parking for these dates, or the details do not fit the rules. Nothing more was saved. |
| leases/text.ts | The Unit stays Occupied until the hand-back is recorded. | The Parking stays Occupied until the hand-back is recorded. |
| leases/text.ts | Never moved in: release the Unit and settle the Initial Rent Invoice in the next step. | Never moved in: release the Parking and settle the Initial Rent Invoice in the next step. |
| letters/LettersPage.test.tsx | Left at the Unit with a witness: Sok Dara | Left at the Parking with a witness: Sok Dara |
| letters/LettersPage.test.tsx | Left at the Unit with a witness | Left at the Parking with a witness |
| letters/LettersPage.test.tsx | Left at the Unit with a witness: Witness Sok Dara | Left at the Parking with a witness: Witness Sok Dara |
| letters/text.ts | A letter never ends the Lease, adds a fee or changes the Unit by itself. The Owner or a Manager decides each next step. | A letter never ends the Lease, adds a fee or changes the Parking by itself. The Owner or a Manager decides each next step. |
| moveout/HandBackDialog.tsx | The Lease reached its End Date and the Unit was handed back | The Lease reached its End Date and the Parking was handed back |
| moveout/HandBackDialog.tsx | Unit handed back | Parking handed back |
| moveout/MoveoutPage.test.tsx | Unit handed back | Parking handed back |
| moveout/MoveoutPage.test.tsx | Unit cleaning charge | Parking cleaning charge |
| moveout/MoveoutPage.test.tsx | Still in the Unit5 days agoRecord the hand-back | Still in the Parking5 days agoRecord the hand-back |
| moveout/MoveoutPage.test.tsx | TEST-FE-963 a Lease past its End Date: Record hand-back ends it on the End Date as signed, then records the move-out with the new Lease version, the Unit version and every open Occupancy; Try again after no answer sends the same request | TEST-FE-963 a Lease past its End Date: Record hand-back ends it on the End Date as signed, then records the move-out with the new Lease version, the Parking version and every open Occupancy; Try again after no answer sends the same request |
| moveout/MoveoutPage.test.tsx | fireEvent.change(within(dialog).getByLabelText(/The Unit after/), { | fireEvent.change(within(dialog).getByLabelText(/The Parking after/), { |
| moveout/MoveoutPage.test.tsx | Handed back on 12/10/2026. Unit set to Cleaning. | Handed back on 12/10/2026. Parking set to Cleaning. |
| moveout/MoveoutPage.test.tsx | TEST-FE-966 ending the Lease answers nothing: Try again ends it with the same request; a Unit read failure after that is not called a refusal; closing reads the page again; a Lease with a signed renewal shows no hand-back | TEST-FE-966 ending the Lease answers nothing: Try again ends it with the same request; a Parking read failure after that is not called a refusal; closing reads the page again; a Lease with a signed renewal shows no hand-back |
| moveout/MoveoutPage.test.tsx | TEST-FE-1009 a Unit with no meter on the hand-back day (a store room with no electricity or water) has no final readings or Utility Invoice: the step is done and offers no button; a failed meter read keeps the usual step | TEST-FE-1009 a Parking with no meter on the hand-back day (a store room with no electricity or water) has no final readings or Utility Invoice: the step is done and offers no button; a failed meter read keeps the usual step |
| moveout/MoveoutPage.test.tsx | /This Unit has no meter on .*, so there are no final readings and no final Utility Invoice\./, | /This Parking has no meter on .*, so there are no final readings and no final Utility Invoice\./, |
| moveout/MoveoutPage.test.tsx | Unit cleaning charge$35.00 INV-lease-U105 | Parking cleaning charge$35.00 INV-lease-U105 |
| moveout/MoveoutPage.test.tsx | TEST-FE-978 Add cleaning charge records the Unit's rate with the Lease's id and makes its Draft, also when that id was recorded before; a refusal names why, a server failure offers Try again; no rate, a zero rate or a hidden rate say so | TEST-FE-978 Add cleaning charge records the Parking's rate with the Lease's id and makes its Draft, also when that id was recorded before; a refusal names why, a server failure offers Try again; no rate, a zero rate or a hidden rate say so |
| moveout/MoveoutPage.test.tsx | This Unit's cleaning rate: $35.00. | This Parking's cleaning rate: $35.00. |
| moveout/MoveoutPage.test.tsx | This Unit has no cleaning rate yet. Set it in Settings, then add the charge. | This Parking has no cleaning rate yet. Set it in Settings, then add the charge. |
| moveout/MoveoutPage.test.tsx | This Unit's cleaning rate is zero: no cleaning charge. | This Parking's cleaning rate is zero: no cleaning charge. |
| moveout/MoveoutPage.test.tsx | TEST-FE-987 the step waits until the Unit is handed back; a person who may only approve sees it but cannot start it; a person with neither right is told so; a refused start says why and no answer offers Try again with the same key | TEST-FE-987 the step waits until the Parking is handed back; a person who may only approve sees it but cannot start it; a person with neither right is told so; a refused start says why and no answer offers Try again with the same key |
| moveout/MoveoutPage.test.tsx | After the Lease ends and the Unit is handed back. | After the Lease ends and the Parking is handed back. |
| moveout/charges.ts | Unit cleaning charge | Parking cleaning charge |
| moveout/moveoutClient.test.ts | Unit handed back | Parking handed back |
| moveout/text.ts | Leases ending, Units handed back and Final Settlements | Leases ending, Parking handed back and Final Settlements |
| moveout/text.ts | Handed back on {0}. Unit set to {1}. | Handed back on {0}. Parking set to {1}. |
| moveout/text.ts | The Customer is still in the Unit. Record the real hand-back date when the keys come back. | The Customer is still in the Parking. Record the real hand-back date when the keys come back. |
| moveout/text.ts | The Unit leaves Occupied. Rent for the month of hand-back follows the rule shown. | The Parking leaves Occupied. Rent for the month of hand-back follows the rule shown. |
| moveout/text.ts | The meters of this Unit could not be read just now. Close and try again. | The meters of this Parking could not be read just now. Close and try again. |
| moveout/text.ts | This Unit has no meter on {0}. Add the meters in Utilities first. | This Parking has no meter on {0}. Add the meters in Utilities first. |
| moveout/text.ts | This Unit has no meter on {0}, so there are no final readings and no final Utility Invoice. | This Parking has no meter on {0}, so there are no final readings and no final Utility Invoice. |
| moveout/text.ts | Inspect the Unit after the hand-back. Each damage charge needs an amount, a reason and evidence; it is recorded once per finding. | Inspect the Parking after the hand-back. Each damage charge needs an amount, a reason and evidence; it is recorded once per finding. |
| moveout/text.ts | This Unit's cleaning rate: {0}. | This Parking's cleaning rate: {0}. |
| moveout/text.ts | This Unit has no cleaning rate yet. Set it in Settings, then add the charge. | This Parking has no cleaning rate yet. Set it in Settings, then add the charge. |
| moveout/text.ts | This Unit's cleaning rate is zero: no cleaning charge. | This Parking's cleaning rate is zero: no cleaning charge. |
| moveout/text.ts | This Unit has no cleaning rate. Set the rate first. | This Parking has no cleaning rate. Set the rate first. |
| moveout/text.ts | This Unit's cleaning rate is zero, so there is no cleaning charge. | This Parking's cleaning rate is zero, so there is no cleaning charge. |
| moveout/text.ts | After the Lease ends and the Unit is handed back. | After the Lease ends and the Parking is handed back. |
| moveout/text.ts | Handed back on {0}; Unit set to {1}. | Handed back on {0}; Parking set to {1}. |
| moveout/text.ts | Hand-back corrected: {0}; Unit {1}. | Hand-back corrected: {0}; Parking {1}. |
| moveout/text.ts | The Lease or the Unit changed meanwhile. The page was read again; check it and record again. | The Lease or the Parking changed meanwhile. The page was read again; check it and record again. |
| payments/PaymentsList.test.tsx | Unit U204 | Parking U204 |
| reports/RegisterView.test.tsx | TEST-FE-1043 Invoice register: the Summary gives issued, paid, settled another way and still owed with the void count, the overdue groups 1 to 19, 20 to 29 and 30 days or more, and the chart by issue month; every Invoice, Customer and Unit links to its page and the footer adds up the amounts | TEST-FE-1043 Invoice register: the Summary gives issued, paid, settled another way and still owed with the void count, the overdue groups 1 to 19, 20 to 29 and 30 days or more, and the chart by issue month; every Invoice, Customer and Parking links to its page and the footer adds up the amounts |
| reports/RegisterView.test.tsx | Unit | Parking |
| reports/RegisterView.test.tsx | TEST-FE-1046 Utility consumption: one line for each Unit and reading period with kWh and m³ side by side, estimates and amounts not billed yet marked; the Summary splits by kind with the Utility Rates; without the money right there are no amounts and no Rates | TEST-FE-1046 Utility consumption: one line for each Parking and reading period with kWh and m³ side by side, estimates and amounts not billed yet marked; the Summary splits by kind with the Utility Rates; without the money right there are no amounts and no Rates |
| reports/RegisterView.test.tsx | Unit / Period / kWh / m³ | Parking / Period / kWh / m³ |
| reports/RegisterView.test.tsx | TEST-FE-1048 Unit occupancy lists every Unit with its Unit Type, status, Customer, Lease or Reservation, Monthly Rent and Until, counts the Units by status, and has no Monthly Rent without the money right | TEST-FE-1048 Parking occupancy lists every Parking with its Parking Type, status, Customer, Lease or Reservation, Monthly Rent and Until, counts the Parking by status, and has no Monthly Rent without the money right |
| reports/RegisterView.test.tsx | table / Unit occupancy | table |
| reports/RegisterView.test.tsx | Unit Type | Parking Type |
| reports/RegisterView.test.tsx | Total / 4 Units /  /  /  /  /  | Total / 4 Parking /  /  /  /  /  |
| reports/RegisterView.test.tsx | Units / 4 | Parking / 4 |
| reports/RegisterView.test.tsx | Units by status | Parking by status |
| reports/RegisterView.test.tsx | Total / 4 Units /  /  /  /  | Total / 4 Parking /  /  /  /  |
| reports/RegisterView.test.tsx | TEST-FE-1049 Lease dates: each Lease is named by its Unit and opens the Lease; a Lease ending within 60 days shows the days left, an early end and a drafted renewal are shown; the Summary counts current, ending, no renewal and terminated | TEST-FE-1049 Lease dates: each Lease is named by its Parking and opens the Lease; a Lease ending within 60 days shows the days left, an early end and a drafted renewal are shown; the Summary counts current, ending, no renewal and terminated |
| reports/RegisterView.test.tsx | Unit / 7 | Parking / 7 |
| reports/RegisterView.test.tsx | TEST-FE-1051 the Customer Credit ledger links each Credit to its Customer, Unit and Receipt and adds up Credit, used, refunded, reversed and left; the Final Settlement register names each by its Unit, opens the Final Settlement and shows open and closed | TEST-FE-1051 the Customer Credit ledger links each Credit to its Customer, Parking and Receipt and adds up Credit, used, refunded, reversed and left; the Final Settlement register names each by its Parking, opens the Final Settlement and shows open and closed |
| reports/ReportsPage.test.tsx | Totals by Unit and month | Totals by Parking and month |
| reports/ReportsPage.test.tsx | Unit occupancy | Parking occupancy |
| reports/ReportsPage.test.tsx | Invoiced amounts for each Unit, month by month | Invoiced amounts for each Parking, month by month |
| reports/ReportsPage.test.tsx | link | within( |
| reports/ReportsPage.test.tsx | Owner and Manager | link |
| reports/ReportsPage.test.tsx | ), | Owner and Manager |
| reports/ReportsPage.test.tsx | TEST-FE-1031 shows only the reports the account may read: Staff see Utility consumption, Unit occupancy and Lease dates; History adds Audit activity; the money right adds the Totals tables and the money registers | TEST-FE-1031 shows only the reports the account may read: Staff see Utility consumption, Parking occupancy and Lease dates; History adds Audit activity; the money right adds the Totals tables and the money registers |
| reports/ReportsPage.test.tsx | region / Totals by Unit and month | region / Totals by Parking and month |
| reports/ReportsPage.test.tsx | This file has personal data (names, Units, phone numbers). Keep it inside the business and delete it when done. | This file has personal data (names, Parking, phone numbers). Keep it inside the business and delete it when done. |
| reports/ReportsPage.test.tsx | TEST-FE-1053 a Totals export sends the Unit and the period, has no Rows line, and fetches a big file from its export job | TEST-FE-1053 a Totals export sends the Parking and the period, has no Rows line, and fetches a big file from its export job |
| reports/ReportsPage.test.tsx | combobox / Unit | combobox / Parking |
| reports/ReportsPage.test.tsx | All Units / U101 / U203 / U204 | All Parking / U101 / U203 / U204 |
| reports/ReportsPage.test.tsx | table / Unit occupancy | table / Parking occupancy |
| reports/TotalsView.test.tsx | Totals by Unit and month | Totals by Parking and month |
| reports/TotalsView.test.tsx | TEST-FE-1038 Total Income: years newest first with January to December and a Total, — for a month with no record; the Summary gives the total, the highest month and Unit and the money not tied to a Unit; the chart stacks the parts by month beside the Top 5 Units | TEST-FE-1038 Total Income: years newest first with January to December and a Total, — for a month with no record; the Summary gives the total, the highest month and Parking and the money not tied to a Parking; the chart stacks the parts by month beside the Top 5 Parking |
| reports/TotalsView.test.tsx | All Units / span | All Parking / span |
| reports/TotalsView.test.tsx | Highest Unit / U203 · $2,500.00 | Highest Parking / U203 · $2,500.00 |
| reports/TotalsView.test.tsx | Not tied to a Unit / $50.00 | Not tied to a Parking / $50.00 |
| reports/TotalsView.test.tsx | Top 5 Units | Top 5 Parking |
| reports/TotalsView.test.tsx | TEST-FE-1039 the Unit filter asks for one Unit's table and All Units for every Unit added together; the scope shows over the table and stays for the other Totals tables | TEST-FE-1039 the Parking filter asks for one Parking's table and All Parking for every Parking added together; the scope shows over the table and stays for the other Totals tables |
| reports/TotalsView.test.tsx | combobox / Unit | combobox / Parking |
| reports/TotalsView.test.tsx | All Units / U101 / U203 / U204 | All Parking / U101 / U203 / U204 |
| reports/TotalsView.test.tsx | Highest Unit / U101 · $200.00 | Highest Parking / U101 · $200.00 |
| reports/TotalsView.test.tsx | Water billed for each Unit, reading period by period | screen.getByText( |
| reports/charts.test.tsx | No Unit | No Parking |
| reports/charts.test.tsx | Top 5 Units | Top 5 Parking |
| reports/charts.test.tsx | No Unit / -$1.00 | No Parking / -$1.00 |
| reports/text.ts | Invoiced amounts for each Unit, month by month | Invoiced amounts for each Parking, month by month |
| reports/text.ts | Money received from each Unit, month by month | Money received from each Parking, month by month |
| reports/text.ts | Electricity billed for each Unit, reading period by period | Electricity billed for each Parking, reading period by period |
| reports/text.ts | Water billed for each Unit, reading period by period | Water billed for each Parking, reading period by period |
| reports/text.ts | kWh and m³ per Unit and reading period, with the amounts billed | kWh and m³ per Parking and reading period, with the amounts billed |
| reports/text.ts | Every Unit: status, Customer, Lease or Reservation end | Every Parking: status, Customer, Lease or Reservation end |
| reports/text.ts | Each Invoice counts in the month it is for: Rent in its Rent month, Utilities in the month their reading period ends. Deposits held are not income; a kept Deposit counts in the month it is kept. With All Units, every Unit is added together. | Each Invoice counts in the month it is for: Rent in its Rent month, Utilities in the month their reading period ends. Deposits held are not income; a kept Deposit counts in the month it is kept. With All Parking, every Parking is added together. |
| reports/text.ts | Every Receipt counts on the day the money came in, deposits included; a reversed Payment comes off in the month it is reversed. For the same whole months this total matches the Payments report: Received less reversals, or Money received when there are none. With All Units, every Unit is added together. | Every Receipt counts on the day the money came in, deposits included; a reversed Payment comes off in the month it is reversed. For the same whole months this total matches the Payments report: Received less reversals, or Money received when there are none. With All Parking, every Parking is added together. |
| reports/text.ts | Each month holds the reading period that ends on the 24th of that month (October = 25/09 – 24/10), at the Rate of that period. With All Units, every Unit is added together. | Each month holds the reading period that ends on the 24th of that month (October = 25/09 – 24/10), at the Rate of that period. With All Parking, every Parking is added together. |
| reports/text.ts | This file has personal data (names, Units, phone numbers). Keep it inside the business and delete it when done. | This file has personal data (names, Parking, phone numbers). Keep it inside the business and delete it when done. |
| reservations/MakeReservationDialog.test.tsx | Unit | Parking |
| reservations/MakeReservationDialog.test.tsx | Unit / unit-2 | Parking |
| reservations/MakeReservationDialog.test.tsx | /The Reservation was not saved: the Unit or the Customer changed meanwhile/, | /The Reservation was not saved: the Parking or the Customer changed meanwhile/, |
| reservations/MakeReservationDialog.test.tsx | TEST-FE-1092 a Unit from the address that is not free is not kept; less than the suggestion waits while the rights are not known; after a lost answer every box stays fixed; a refusal after a lost Reservation answer finds that Reservation saved | TEST-FE-1092 a Parking from the address that is not free is not kept; less than the suggestion waits while the rights are not known; after a lost answer every box stays fixed; a refusal after a lost Reservation answer finds that Reservation saved |
| reservations/MakeReservationDialog.test.tsx | Unit /  | Parking /  |
| reservations/MakeReservationDialog.test.tsx | TEST-FE-1100 a Unit from the address that is not vacant never reaches the money step | TEST-FE-1100 a Parking from the address that is not vacant never reaches the money step |
| reservations/MakeReservationDialog.test.tsx | Choose a Unit. | Choose a Parking. |
| reservations/MakeReservationDialog.test.tsx | TEST-FE-1101 the money saved but the Reservation refused as changed does not ask to change the Unit or the Customer, which are fixed with the money | TEST-FE-1101 the money saved but the Reservation refused as changed does not ask to change the Parking or the Customer, which are fixed with the money |
| reservations/MakeReservationDialog.test.tsx | The Reservation was not saved: the Unit or the Customer changed meanwhile (for example, someone else reserved this Unit first). | The Reservation was not saved: the Parking or the Customer changed meanwhile (for example, someone else reserved this Parking first). |
| reservations/ReservationsPage.test.tsx | await screen.findByText(/^5 Reservations · a Unit held/), | await screen.findByText(/^5 Reservations · a Parking held/), |
| reservations/ReservationsPage.test.tsx | Unit | Parking |
| reservations/ReservationsPage.test.tsx | CancelledCustomer no longer wants the Unit | CancelledCustomer no longer wants the Parking |
| reservations/ReservationsPage.test.tsx | Customer no longer wants the Unit | Customer no longer wants the Parking |
| reservations/ReservationsPage.test.tsx | Unit / unit-2 | Parking |
| reservations/text.ts | {0} Reservations · a Unit held for a Customer until the Lease is signed | {0} Reservations · a Parking held for a Customer until the Lease is signed |
| reservations/text.ts | Property could not provide the Unit | Property could not provide the Parking |
| reservations/text.ts | The Customer no longer wants the Unit. Under the rules the Security Deposit is kept. | The Customer no longer wants the Parking. Under the rules the Security Deposit is kept. |
| reservations/text.ts | The Property cannot provide the Unit, and the Customer declined a later date or another Unit. Under the rules the Security Deposit is refunded. | The Property cannot provide the Parking, and the Customer declined a later date or another Parking. Under the rules the Security Deposit is refunded. |
| reservations/text.ts | The Unit goes back to Vacant at once. No money moves now: the deposit decision is recorded as a draft, and the Owner or a Manager confirms it. | The Parking goes back to Vacant at once. No money moves now: the deposit decision is recorded as a draft, and the Owner or a Manager confirms it. |
| reservations/text.ts | The Reservation was not saved: the Unit or the Customer changed meanwhile (for example, someone else reserved this Unit first). Check them, then try again. | The Reservation was not saved: the Parking or the Customer changed meanwhile (for example, someone else reserved this Parking first). Check them, then try again. |
| reservations/text.ts | The Reservation was not saved: the Unit or the Customer changed meanwhile (for example, someone else reserved this Unit first). | The Reservation was not saved: the Parking or the Customer changed meanwhile (for example, someone else reserved this Parking first). |
| reservations/text.ts | Reading the Units and Customers… | Reading the Parking and Customers… |
| settings/BusinessTab.test.tsx | Units: 0 | Parking: 0 |
| settings/CleaningRates.test.tsx | TEST-FE-1005 lists each rate with its Unit Types and warns of a type with no rate; Add sends its own id and the ticked types (a type of another rate moves); Edit sends the version; untick and Remove of a type with Units are refused with its name | TEST-FE-1005 lists each rate with its Parking Types and warns of a type with no rate; Add sends its own id and the ticked types (a type of another rate moves); Edit sends the version; untick and Remove of a type with Parking are refused with its name |
| settings/CleaningRates.test.tsx | Studio has Units and needs a cleaning rate. Put it in another rate first. | Studio has Parking and needs a cleaning rate. Put it in another rate first. |
| settings/CleaningRates.test.tsx | Two Bedroom has Units and needs a cleaning rate. Put it in another rate first. | Two Bedroom has Parking and needs a cleaning rate. Put it in another rate first. |
| settings/SettingsPage.test.tsx | Unit setup / #/settings/units | Parking setup / #/settings/units |
| settings/UnitSetupTab.test.tsx | Settings: Unit setup | Settings: Parking setup |
| settings/UnitSetupTab.test.tsx | TEST-FE-940 shows the five lists with how many Units use each item; an item in use offers no Remove; Floors have no Edit | TEST-FE-940 shows the five lists with how many Parking use each item; an item in use offers no Remove; Floors have no Edit |
| settings/UnitSetupTab.test.tsx | Floors / Unit Types / Views / Kitchens / Room features | Floors / Parking Types / Views / Kitchens / Room features |
| settings/UnitSetupTab.test.tsx | Floors / Unit Types / Views / Kitchens / Room features | ).toEqual([ |
| settings/UnitSetupTab.test.tsx | Floor 12 Units | Floor 12 Parking |
| settings/UnitSetupTab.test.tsx | No Units yet | No Parking yet |
| settings/UnitSetupTab.test.tsx | Room features / Balcony1 Unit | Room features / Balcony1 Parking |
| settings/UnitSetupTab.test.tsx | Unit Types / button / Edit: Studio | Parking Types / button |
| settings/UnitSetupTab.test.tsx | Unit Types | Parking Types |
| settings/UnitSetupTab.test.tsx | Rename keeps every Unit of this type. | Rename keeps every Parking of this type. |
| settings/UnitSetupTab.test.tsx | dialog / Edit · Unit Type | dialog / Edit · Parking Type |
| settings/UnitSetupTab.test.tsx | Someone changed this list, or a Unit now uses the item. The lists were read again; check and try again. | Someone changed this list, or a Parking now uses the item. The lists were read again; check and try again. |
| settings/UnitSetupTab.test.tsx | TEST-FE-943 Khmer shows the Khmer list names and the mock-up words; without the Units list an item shows only that a Unit uses it | TEST-FE-943 Khmer shows the Khmer list names and the mock-up words; without the Parking list an item shows only that a Parking uses it |
| settings/UnitSetupTab.test.tsx | TEST-FE-1006 a Unit Type with no move-out cleaning rate shows a No cleaning rate chip; when the rates cannot be read no chip shows | TEST-FE-1006 a Parking Type with no move-out cleaning rate shows a No cleaning rate chip; when the rates cannot be read no chip shows |
| settings/UnitSetupTab.test.tsx | region / Unit Types | region / Parking Types |
| settings/text.ts | These lists fill the choices on New Unit and Update Unit. An item used by a Unit cannot be removed; rename it instead. | These lists fill the choices on New Parking and Update Parking. An item used by a Parking cannot be removed; rename it instead. |
| settings/text.ts | Rename keeps every Unit of this type. Add the new type to a move-out cleaning rate on the Rates and services tab. | Rename keeps every Parking of this type. Add the new type to a move-out cleaning rate on the Rates and services tab. |
| settings/text.ts | Room features show as Yes or No on each Unit page. | Room features show as Yes or No on each Parking page. |
| settings/text.ts | Someone changed this list, or a Unit now uses the item. The lists were read again; check and try again. | Someone changed this list, or a Parking now uses the item. The lists were read again; check and try again. |
| settings/text.ts | Daily work: Payments, Invoices, readings, Units, Customers, Reservations, Leases, move-out steps | Daily work: Payments, Invoices, readings, Parking, Customers, Reservations, Leases, move-out steps |
| settings/text.ts | {0} has Units and needs a cleaning rate. Put it in another rate first. | {0} has Parking and needs a cleaning rate. Put it in another rate first. |
| settings/text.ts | A move-out has a cleaning charge at the rate of the Unit's type. A new amount applies to every Unit of its types from now on; charges already made keep theirs. | A move-out has a cleaning charge at the rate of the Parking's type. A new amount applies to every Parking of its types from now on; charges already made keep theirs. |
| settings/text.ts | A Unit Type that has Units needs a cleaning rate. Put it in another rate first. The list was read again. | A Parking Type that has Parking needs a cleaning rate. Put it in another rate first. The list was read again. |
| settlementClient.test.tsx | Move-out cleaning rate for this Unit | Move-out cleaning rate for this Parking |
| shell/AppShell.test.tsx | Units | Parking |
| shell/AppShell.test.tsx | link / Units | link / Parking |
| shell/AppShell.test.tsx | main / Units | main / Parking |
| shell/AppShell.test.tsx | Units / #/units | Parking / #/units |
| unitClient.test.ts | Unit API client | Parking API client |
| unitClient.test.ts | TEST-FE-817 reads Unit details and setup lists, never sends a Unit number on update, and names a refused pick | TEST-FE-817 reads Parking details and setup lists, never sends a Parking number on update, and names a refused pick |
| unitClient.test.ts | TEST-FE-821 reads the Unit inventory and saves it against the record number it showed | TEST-FE-821 reads the Parking inventory and saves it against the record number it showed |
| unitClient.ts | Unit management is unavailable for this session. | Parking management is unavailable for this session. |
| unitClient.ts | The Unit changed. Reload it before retrying. | The Parking changed. Reload it before retrying. |
| unitClient.ts | The Unit request was not completed. | The Parking request was not completed. |
| unitClient.ts | Check the Unit details. The Unit number may already be used, or a list item may have been removed. | Check the Parking details. The Parking number may already be used, or a list item may have been removed. |
| units/UnitsPage.test.tsx | Units list | Parking list |
| units/UnitsPage.test.tsx | TEST-FE-027 shows the Units table with status chips, Until from the Lease or Reservation, and New Unit for a manager | TEST-FE-027 shows the Parking table with status chips, Until from the Lease or Reservation, and New Parking for a manager |
| units/UnitsPage.test.tsx | 4 Units at CHETANA Parking | 4 Parking at CHETANA Parking |
| units/UnitsPage.test.tsx | Unit / Floor / Unit Type / Status / Until | Parking / Floor / Parking Type / Status / Until |
| units/UnitsPage.test.tsx | 4 Units | 4 Parking |
| units/UnitsPage.test.tsx | button / New Unit | button / New Parking |
| units/UnitsPage.test.tsx | TEST-FE-028 hides New Unit, Change status and Update Unit without the server's permission | TEST-FE-028 hides New Parking, Change status and Update Parking without the server's permission |
| units/UnitsPage.test.tsx | button / Update Unit | button / Update Parking |
| units/UnitsPage.test.tsx | TEST-FE-823 filters by floor, Unit Type and the four count cards | TEST-FE-823 filters by floor, Parking Type and the four count cards |
| units/UnitsPage.test.tsx | 2 Units | 2 Parking |
| units/UnitsPage.test.tsx | Unit Type | Parking Type |
| units/UnitsPage.test.tsx | 1 Unit | 1 Parking |
| units/UnitsPage.test.tsx | TEST-FE-825 opens a Unit by its address and shows “—” when Leases cannot be read | TEST-FE-825 opens a Parking by its address and shows “—” when Leases cannot be read |
| units/UnitsPage.test.tsx | The Units could not be read. Retry when the service is available. | The Parking could not be read. Retry when the service is available. |
| units/UnitsPage.test.tsx | button / Update Unit | fireEvent.click( |
| units/UnitsPage.test.tsx | await screen.findByText(/Someone else changed this Unit first\./), | await screen.findByText(/Someone else changed this Parking first\./), |
| units/UnitsPage.test.tsx | Unit page | Parking page |
| units/UnitsPage.test.tsx | TEST-FE-029 keeps the Unit details, Lease, Meters, Invoices and History apart and lists the History | TEST-FE-029 keeps the Parking details, Lease, Meters, Invoices and History apart and lists the History |
| units/UnitsPage.test.tsx | Unit details | Parking details |
| units/UnitsPage.test.tsx | Invoices for this Unit | Invoices for this Parking |
| units/UnitsPage.test.tsx | heading / Unit details | heading / Parking details |
| units/UnitsPage.test.tsx | Unit created. | Parking created. |
| units/UnitsPage.test.tsx | TEST-FE-1074 each button opens its own place: New Lease opens the form with the Unit chosen or the draft from its Reservation, and Open Lease, Open draft Lease and Open Reservation open that record | TEST-FE-1074 each button opens its own place: New Lease opens the form with the Parking chosen or the draft from its Reservation, and Open Lease, Open draft Lease and Open Reservation open that record |
| units/UnitsPage.test.tsx | TEST-FE-824 changes the status only with a reason and not while a Lease holds the Unit | TEST-FE-824 changes the status only with a reason and not while a Lease holds the Parking |
| units/UnitsPage.test.tsx | This Unit has a signed Lease. Its status changes only through Move-out. | This Parking has a signed Lease. Its status changes only through Move-out. |
| units/UnitsPage.test.tsx | TEST-FE-818 adds a Unit with the Floor and Unit Type from the Settings lists, and Update Unit never sends the Unit number | TEST-FE-818 adds a Parking with the Floor and Parking Type from the Settings lists, and Update Parking never sends the Parking number |
| units/UnitsPage.test.tsx | Enter the Unit number. | Enter the Parking number. |
| units/UnitsPage.test.tsx | fireEvent.change(within(dialog).getByLabelText(/^Unit number/), { | fireEvent.change(within(dialog).getByLabelText(/^Parking number/), { |
| units/UnitsPage.test.tsx | Update Unit · U201 | Update Parking · U201 |
| units/UnitsPage.test.tsx | expect(within(edit).queryByLabelText(/^Unit number/)).toBeNull(); | expect(within(edit).queryByLabelText(/^Parking number/)).toBeNull(); |
| units/UnitsPage.test.tsx | Corner Unit | Corner Parking |
| units/UnitsPage.test.tsx | Unit U201 updated. | expect( |
| units/text.ts | The Units could not be read. Retry when the service is available. | The Parking could not be read. Retry when the service is available. |
| units/text.ts | The Property is not known yet, so the Units cannot be shown. | The Property is not known yet, so the Parking cannot be shown. |
| units/text.ts | The Settings lists could not be read, so Units cannot be added or changed now. | The Settings lists could not be read, so Parking cannot be added or changed now. |
| units/text.ts | An active Reservation holds the Unit | An active Reservation holds the Parking |
| units/text.ts | This Unit was not found. Go back to the Units list. | This Parking was not found. Go back to the Parking list. |
| units/text.ts | This Unit is vacant. It can be reserved, or a Lease can be drafted for a walk-in Customer. | This Parking is vacant. It can be reserved, or a Lease can be drafted for a walk-in Customer. |
| units/text.ts | Your account cannot read Leases or Reservations for this Unit. | Your account cannot read Leases or Reservations for this Parking. |
| units/text.ts | Unpaid Invoices for this Unit show here when Invoices are rebuilt (step R5). | Unpaid Invoices for this Parking show here when Invoices are rebuilt (step R5). |
| units/text.ts | Unit inventory updated. / បានធ្វើបច្ចុប្បន្នភាពសម្ភារៈ។ | Parking inventory updated. / បានធ្វើបច្ចុប្បន្នភាពសម្ភារៈ។ |
| units/text.ts | A new Unit starts as Vacant with an empty inventory; add its items on the Unit page. | A new Parking starts as Vacant with an empty inventory; add its items on the Parking page. |
| units/text.ts | Changes are dated and kept in History. The Unit number cannot change. | Changes are dated and kept in History. The Parking number cannot change. |
| units/text.ts | Check the Unit details. The Unit number may already be used, or a list item may have been removed. | Check the Parking details. The Parking number may already be used, or a list item may have been removed. |
| units/text.ts | Someone else changed this Unit first. Its latest details are shown now; try again if needed. | Someone else changed this Parking first. Its latest details are shown now; try again if needed. |
| units/text.ts | This Unit has a signed Lease. Its status changes only through Move-out. | This Parking has a signed Lease. Its status changes only through Move-out. |
| units/text.ts | This Unit has an active Reservation. Cancel the Reservation first. | This Parking has an active Reservation. Cancel the Reservation first. |
| utilities/UtilitiesPage.test.tsx | TEST-FE-1062 Much less than usual in an Occupied Unit asks to check the meter first; an empty Unit is not checked | TEST-FE-1062 Much less than usual in an Occupied Parking asks to check the meter first; an empty Parking is not checked |
| utilities/UtilitiesPage.test.tsx | Unit | Parking |
| utilities/UtilitiesPage.test.tsx | Unit / September 2026 / August 2026 | Parking / September 2026 / August 2026 |
| utilities/UtilitiesPage.test.tsx | TEST-FE-879 The Unit box takes U201, u201 or 201, shows that Unit's readings with the meter on each line, and names a Unit that does not exist | TEST-FE-879 The Parking box takes U201, u201 or 201, shows that Parking's readings with the meter on each line, and names a Parking that does not exist |
| utilities/UtilitiesPage.test.tsx | button / All Units | button / All Parking |
| utilities/UtilitiesPage.test.tsx | expect(screen.queryByText(/No Unit/)).toBeNull(); | expect(screen.queryByText(/No Parking/)).toBeNull(); |
| utilities/UtilitiesPage.test.tsx | columnheader / Unit | columnheader / Parking |
| utilities/UtilitiesPage.test.tsx | TEST-FE-882 A Unit whose readings cannot be read is named and the list is never called done without it; the Unit box waits while U10 may still become U101 | TEST-FE-882 A Parking whose readings cannot be read is named and the list is never called done without it; the Parking box waits while U10 may still become U101 |
| utilities/UtilitiesPage.test.tsx | TEST-FE-883 The Meters list counts the meters in use, shows replaced meters last, and filters by card, status and Unit | TEST-FE-883 The Meters list counts the meters in use, shows replaced meters last, and filters by card, status and Parking |
| utilities/UtilitiesPage.test.tsx | Electricity meters: 3. In use, one per Unit · All working | Electricity meters: 3. In use, one per Parking · All working |
| utilities/UtilitiesPage.test.tsx | TEST-FE-884 Add meter does not offer a Unit that has a working meter of the kind, sends the meter with its first reading on the day it is put in, and names a serial already used | TEST-FE-884 Add meter does not offer a Parking that has a working meter of the kind, sends the meter with its first reading on the day it is put in, and names a serial already used |
| utilities/UtilitiesPage.test.tsx | option | ...within(dialog) |
| utilities/UtilitiesPage.test.tsx | Choose a Unit / U301 | Choose a Parking / U301 |
| utilities/UtilitiesPage.test.tsx | fireEvent.change(within(dialog).getByLabelText(/^Unit/), { | fireEvent.change(within(dialog).getByLabelText(/^Parking/), { |
| utilities/UtilitiesPage.test.tsx | TEST-FE-1061 Add meter offers only Units without a current meter of the chosen kind, clears a Unit that has the newly chosen kind, and says to use Replace meter when no Unit is left | TEST-FE-1061 Add meter offers only Parking without a current meter of the chosen kind, clears a Parking that has the newly chosen kind, and says to use Replace meter when no Parking is left |
| utilities/UtilitiesPage.test.tsx | const unitBox = within(dialog).getByLabelText<HTMLSelectElement>(/^Unit/); | const unitBox = |
| utilities/UtilitiesPage.test.tsx | Choose a Unit | Choose a Parking |
| utilities/UtilitiesPage.test.tsx | Every Unit already has a water meter. To change a broken meter, open it and choose Replace meter. | Every Parking already has a water meter. To change a broken meter, open it and choose Replace meter. |
| utilities/UtilitiesPage.test.tsx | const unitBox = within(dialog).getByLabelText(/^Unit/); | const unitBox = within(dialog).getByLabelText(/^Parking/); |
| utilities/UtilitiesPage.test.tsx | TEST-FE-890 Import opens from the reading list, downloads the blank file with every Unit, asks for a file, and sends the chosen file to be read | TEST-FE-890 Import opens from the reading list, downloads the blank file with every Parking, asks for a file, and sends the chosen file to be read |
| utilities/UtilitiesPage.test.tsx | Unit,Meter\n / readings.csv | Parking,Meter\n / readings.csv |
| utilities/UtilitiesPage.test.tsx | The first row needs the three column names Unit, Electricity and Water. | The first row needs the three column names Parking, Electricity and Water. |
| utilities/UtilitiesPage.test.tsx | Unit,Meter\n | Parking,Meter\n |
| utilities/UtilitiesPage.test.tsx | There is no Unit U999. | There is no Parking U999. |
| utilities/UtilitiesPage.test.tsx | This Unit has no electricity meter. A Manager adds it on the Meters tab. | This Parking has no electricity meter. A Manager adds it on the Meters tab. |
| utilities/UtilitiesPage.test.tsx | TEST-FE-1063 Import marks a reading much less than usual in an Occupied Unit as ready with a check note | TEST-FE-1063 Import marks a reading much less than usual in an Occupied Parking as ready with a check note |
| utilities/text.ts | For a Unit that has no meter of this kind, such as a new Unit. A Unit has one electricity meter and one water meter. To change a broken meter, open it and choose Replace meter. | For a Parking that has no meter of this kind, such as a new Parking. A Parking has one electricity meter and one water meter. To change a broken meter, open it and choose Replace meter. |
| utilities/text.ts | Every Unit already has a {0} meter. To change a broken meter, open it and choose Replace meter. | Every Parking already has a {0} meter. To change a broken meter, open it and choose Replace meter. |
| utilities/text.ts | {0} already has a working {1} meter ({2}). A Unit can have only one. | {0} already has a working {1} meter ({2}). A Parking can have only one. |
| utilities/text.ts | One row for each Unit, with three columns: Unit, Electricity, Water. The Units are already filled in, so staff type only the readings. No meter numbers. | One row for each Parking, with three columns: Parking, Electricity, Water. The Parking is already filled in, so staff type only the readings. No meter numbers. |
| utilities/text.ts | Every Unit is filled in. Print it or fill it in on the tablet. | Every Parking is filled in. Print it or fill it in on the tablet. |
| utilities/text.ts | The file is bigger than 2 MB. It needs only one row for each Unit. | The file is bigger than 2 MB. It needs only one row for each Parking. |
| utilities/text.ts | The first row needs the three column names Unit, Electricity and Water. | The first row needs the three column names Parking, Electricity and Water. |
| utilities/text.ts | ជួរទីមួយត្រូវមានឈ្មោះជួរឈរបី៖ Unit, Electricity និង Water។ | ជួរទីមួយត្រូវមានឈ្មោះជួរឈរបី៖ Parking, Electricity និង Water។ |
| utilities/text.ts | The file has too many rows. It needs one row for each Unit. | The file has too many rows. It needs one row for each Parking. |
| utilities/text.ts | This Unit has no {0} meter. A Manager adds it on the Meters tab. | This Parking has no {0} meter. A Manager adds it on the Meters tab. |
| utilities/text.ts | No meter photos are needed. Report a meter problem on a Unit Check. | No meter photos are needed. Report a meter problem on a Parking Check. |

## Every changed Khmer screen string (179 lines)

| File | Khmer before | Khmer after |
|---|---|---|
| approvals/text.ts | ផ្ទេរការបង់ទៅបន្ទប់ត្រឹមត្រូវ | ផ្ទេរការបង់ទៅចំណតត្រឹមត្រូវ |
| customers/text.ts | ស្វែងរកតាមឈ្មោះ ទូរស័ព្ទ បន្ទប់ ឬលេខអត្តសញ្ញាណ | ស្វែងរកតាមឈ្មោះ ទូរស័ព្ទ ចំណត ឬលេខអត្តសញ្ញាណ |
| customers/text.ts | មិនអាចស្វែងរកបានទេ។ បញ្ជីនៅតែត្រងតាមឈ្មោះ ទូរស័ព្ទ និងបន្ទប់។ | មិនអាចស្វែងរកបានទេ។ បញ្ជីនៅតែត្រងតាមឈ្មោះ ទូរស័ព្ទ និងចំណត។ |
| customers/text.ts | គណនីរបស់អ្នកមិនអាចអានកិច្ចសន្យា ឬការកក់បានទេ ដូច្នេះបន្ទប់ និងទំនាក់ទំនង បង្ហាញ “—”។ | គណនីរបស់អ្នកមិនអាចអានកិច្ចសន្យា ឬការកក់បានទេ ដូច្នេះចំណត និងទំនាក់ទំនង បង្ហាញ “—”។ |
| customers/text.ts | កំពុងកក់បន្ទប់ មិនទាន់ចុះហត្ថលេខាកិច្ចសន្យា | កំពុងកក់ចំណត មិនទាន់ចុះហត្ថលេខាកិច្ចសន្យា |
| customers/text.ts | Unit / បន្ទប់ | Parking / ចំណត |
| history/text.ts | Unit / បន្ទប់ | Parking / ចំណត |
| history/text.ts | All Units / គ្រប់បន្ទប់ | All Parking / គ្រប់ចំណត |
| home/HomeScreen.test.tsx | បន្ទប់មានអ្នកជួល | ចំណតមានអ្នកជួល |
| home/text.ts | Units occupied / បន្ទប់មានអ្នកជួល | Parking occupied / ចំណតមានអ្នកជួល |
| invoices/text.ts | Unit / បន្ទប់ | Parking / ចំណត |
| leases/text.ts | Unit / បន្ទប់ | Parking / ចំណត |
| leases/text.ts | បានចុះហត្ថលេខា បន្ទប់មានអ្នកជួល។ កត់ត្រាការចូលស្នាក់នៅពេលអតិថិជនទទួលកូនសោ (ថ្ងៃចាប់ផ្តើម {0})។ | បានចុះហត្ថលេខា ចំណតមានអ្នកជួល។ កត់ត្រាការចូលស្នាក់នៅពេលអតិថិជនទទួលកូនសោ (ថ្ងៃចាប់ផ្តើម {0})។ |
| leases/text.ts | អ្នកចុះហត្ថលេខាម្នាក់ៗទទួលខុសត្រូវលើសមតុល្យទាំងមូល មិនមែនចំណែកទេ។ អ្នកចុះហត្ថលេខាមិនចាំបាច់រស់នៅក្នុងបន្ទប់ទេ។ | អ្នកចុះហត្ថលេខាម្នាក់ៗទទួលខុសត្រូវលើសមតុល្យទាំងមូល មិនមែនចំណែកទេ។ អ្នកចុះហត្ថលេខាមិនចាំបាច់រស់នៅក្នុងចំណតទេ។ |
| leases/text.ts | បានបន្ថែម {0} ជាអ្នករស់នៅបន្ទប់ {1}។ | បានបន្ថែម {0} ជាអ្នករស់នៅចំណត {1}។ |
| leases/text.ts | Still in the Unit / នៅក្នុងបន្ទប់ | Still in the Parking / នៅក្នុងចំណត |
| leases/text.ts | ការកក់កំពុងដំណើរការរបស់អតិថិជននេះសម្រាប់បន្ទប់នេះ បានបញ្ចប់ក្នុងជំហានតែមួយ។ ប្រាក់កក់របស់វាបន្តជាប្រាក់កក់សុវត្ថិភាព។ | ការកក់កំពុងដំណើរការរបស់អតិថិជននេះសម្រាប់ចំណតនេះ បានបញ្ចប់ក្នុងជំហានតែមួយ។ ប្រាក់កក់របស់វាបន្តជាប្រាក់កក់សុវត្ថិភាព។ |
| leases/text.ts | មិនអាចអានការកក់បានទេ។ បើបន្ទប់នេះត្រូវបានកក់ ការចុះហត្ថលេខានឹងត្រូវបដិសេធ។ សូមសួរអ្នកដែលអាចមើលការកក់។ | មិនអាចអានការកក់បានទេ។ បើចំណតនេះត្រូវបានកក់ ការចុះហត្ថលេខានឹងត្រូវបដិសេធ។ សូមសួរអ្នកដែលអាចមើលការកក់។ |
| leases/text.ts | កិច្ចសន្យានេះ ឬបន្ទប់របស់វាបានប្តូរក្នុងពេលនេះ ដូច្នេះគ្មានអ្វីបន្ថែមត្រូវបានរក្សាទុកទេ។ វាត្រូវបានអានម្តងទៀត៖ សូមពិនិត្យ ហើយព្យាយាមម្តងទៀត។ | កិច្ចសន្យានេះ ឬចំណតរបស់វាបានប្តូរក្នុងពេលនេះ ដូច្នេះគ្មានអ្វីបន្ថែមត្រូវបានរក្សាទុកទេ។ វាត្រូវបានអានម្តងទៀត៖ សូមពិនិត្យ ហើយព្យាយាមម្តងទៀត។ |
| leases/text.ts | មានតែសេចក្តីព្រាងប៉ុណ្ណោះដែលត្រូវលុប កិច្ចសន្យាដែលបានចុះហត្ថលេខាមិនដែលលុបទេ។ បន្ទប់ និងការកក់ណាមួយ នៅដដែល។ | មានតែសេចក្តីព្រាងប៉ុណ្ណោះដែលត្រូវលុប កិច្ចសន្យាដែលបានចុះហត្ថលេខាមិនដែលលុបទេ។ ចំណត និងការកក់ណាមួយ នៅដដែល។ |
| leases/text.ts | ពីការកក់របស់ {0}៖ បន្ទប់ អតិថិជន ថ្លៃឈ្នួលដែលបានព្រមព្រៀង និងប្រាក់កក់ មកពីវា។ | ពីការកក់របស់ {0}៖ ចំណត អតិថិជន ថ្លៃឈ្នួលដែលបានព្រមព្រៀង និងប្រាក់កក់ មកពីវា។ |
| leases/text.ts | កិច្ចសន្យាថ្មីសម្រាប់ {0} ចាប់ផ្តើមថ្ងៃបន្ទាប់ពីថ្ងៃបញ្ចប់ចាស់ ហើយភ្ជាប់ទៅវា។ បន្ទប់នៅតែមានអ្នកជួល។ | កិច្ចសន្យាថ្មីសម្រាប់ {0} ចាប់ផ្តើមថ្ងៃបន្ទាប់ពីថ្ងៃបញ្ចប់ចាស់ ហើយភ្ជាប់ទៅវា។ ចំណតនៅតែមានអ្នកជួល។ |
| leases/text.ts | មិនអាចអានបន្ទប់ និងអតិថិជនបានទេឥឡូវនេះ។ សូមពិនិត្យការតភ្ជាប់ និងសិទ្ធិរបស់អ្នក ហើយព្យាយាមម្តងទៀត។ | មិនអាចអានចំណត និងអតិថិជនបានទេឥឡូវនេះ។ សូមពិនិត្យការតភ្ជាប់ និងសិទ្ធិរបស់អ្នក ហើយព្យាយាមម្តងទៀត។ |
| leases/text.ts | Choose a Unit / ជ្រើសបន្ទប់ | Choose a Parking / ជ្រើសចំណត |
| leases/text.ts | បន្ទប់ទំនេរ កំពុងសម្អាត ឬកំពុងជួសជុល។ បន្ទប់ដែលបានកក់ ទទួលកិច្ចសន្យាពីការកក់របស់វា។ | ចំណតទំនេរ កំពុងសម្អាត ឬកំពុងជួសជុល។ ចំណតដែលបានកក់ ទទួលកិច្ចសន្យាពីការកក់របស់វា។ |
| leases/text.ts | Choose the Unit. / សូមជ្រើសបន្ទប់។ | Choose the Parking. / សូមជ្រើសចំណត។ |
| leases/text.ts | បន្ទប់នេះគ្មាននាឡិកាស្ទង់អគ្គិសនីទេ ដូច្នេះមិនគិតថ្លៃអគ្គិសនីទេ។ សូមបន្ថែមនាឡិកាស្ទង់ក្នុងទឹកភ្លើង ពេលដំឡើងរួច។ | ចំណតនេះគ្មាននាឡិកាស្ទង់អគ្គិសនីទេ ដូច្នេះមិនគិតថ្លៃអគ្គិសនីទេ។ សូមបន្ថែមនាឡិកាស្ទង់ក្នុងទឹកភ្លើង ពេលដំឡើងរួច។ |
| leases/text.ts | បន្ទប់នេះគ្មាននាឡិកាស្ទង់ទឹកទេ ដូច្នេះមិនគិតថ្លៃទឹកទេ។ សូមបន្ថែមនាឡិកាស្ទង់ក្នុងទឹកភ្លើង ពេលដំឡើងរួច។ | ចំណតនេះគ្មាននាឡិកាស្ទង់ទឹកទេ ដូច្នេះមិនគិតថ្លៃទឹកទេ។ សូមបន្ថែមនាឡិកាស្ទង់ក្នុងទឹកភ្លើង ពេលដំឡើងរួច។ |
| leases/text.ts | បន្ទប់នេះគ្មាននាឡិកាស្ទង់អគ្គិសនី ឬទឹកទេ ដូច្នេះមិនគិតថ្លៃទឹកភ្លើងទេ។ សូមបន្ថែមនាឡិកាស្ទង់ក្នុងទឹកភ្លើង ពេលដំឡើងរួច។ | ចំណតនេះគ្មាននាឡិកាស្ទង់អគ្គិសនី ឬទឹកទេ ដូច្នេះមិនគិតថ្លៃទឹកភ្លើងទេ។ សូមបន្ថែមនាឡិកាស្ទង់ក្នុងទឹកភ្លើង ពេលដំឡើងរួច។ |
| leases/text.ts | ម៉ាស៊ីនមេបានបដិសេធសេចក្តីព្រាង។ កិច្ចសន្យាផ្សេងប្រហែលគ្របដណ្តប់បន្ទប់នេះសម្រាប់ថ្ងៃទាំងនេះរួចហើយ ឬព័ត៌មានមិនត្រូវតាមច្បាប់។ គ្មានអ្វីបន្ថែមត្រូវបានរក្សាទុកទេ។ | ម៉ាស៊ីនមេបានបដិសេធសេចក្តីព្រាង។ កិច្ចសន្យាផ្សេងប្រហែលគ្របដណ្តប់ចំណតនេះសម្រាប់ថ្ងៃទាំងនេះរួចហើយ ឬព័ត៌មានមិនត្រូវតាមច្បាប់។ គ្មានអ្វីបន្ថែមត្រូវបានរក្សាទុកទេ។ |
| leases/text.ts | បន្ទប់នៅមានអ្នកជួល រហូតដល់កត់ត្រាការប្រគល់។ | ចំណតនៅមានអ្នកជួល រហូតដល់កត់ត្រាការប្រគល់។ |
| leases/text.ts | មិនដែលចូលស្នាក់នៅ៖ ដោះលែងបន្ទប់ និងដោះស្រាយវិក្កយបត្រថ្លៃឈ្នួលដំបូង នៅជំហានបន្ទាប់។ | មិនដែលចូលស្នាក់នៅ៖ ដោះលែងចំណត និងដោះស្រាយវិក្កយបត្រថ្លៃឈ្នួលដំបូង នៅជំហានបន្ទាប់។ |
| letters/text.ts | Unit and Customer / បន្ទប់ និងអតិថិជន | Parking and Customer / ចំណត និងអតិថិជន |
| letters/text.ts | លិខិតមិនបញ្ចប់កិច្ចសន្យា បន្ថែមថ្លៃ ឬប្តូរបន្ទប់ដោយខ្លួនឯងទេ។ ម្ចាស់ ឬអ្នកគ្រប់គ្រងសម្រេចជំហានបន្ទាប់នីមួយៗ។ | លិខិតមិនបញ្ចប់កិច្ចសន្យា បន្ថែមថ្លៃ ឬប្តូរចំណតដោយខ្លួនឯងទេ។ ម្ចាស់ ឬអ្នកគ្រប់គ្រងសម្រេចជំហានបន្ទាប់នីមួយៗ។ |
| letters/text.ts | Left at the Unit with a witness / ទុកនៅបន្ទប់ ដោយមានសាក្សី | Left at the Parking with a witness / ទុកនៅចំណត ដោយមានសាក្សី |
| moveout/text.ts | កិច្ចសន្យាជិតបញ្ចប់ បន្ទប់បានប្រគល់ និងការទូទាត់ចុងក្រោយ | កិច្ចសន្យាជិតបញ្ចប់ ចំណតបានប្រគល់ និងការទូទាត់ចុងក្រោយ |
| moveout/text.ts | Handed back / បានប្រគល់បន្ទប់ | Handed back / បានប្រគល់ចំណត |
| moveout/text.ts | Unit / បន្ទប់ | Parking / ចំណត |
| moveout/text.ts | Record the hand-back / កត់ត្រាការប្រគល់បន្ទប់ | Record the hand-back / កត់ត្រាការប្រគល់ចំណត |
| moveout/text.ts | លំដាប់ការងារ៖ ប្រគល់បន្ទប់ អំណានចុងក្រោយ ត្រួតពិនិត្យ និងថ្លៃ ការទូទាត់ចុងក្រោយ។ ការទូទាត់ចុងក្រោយតែមួយក្នុងមួយកិច្ចសន្យា; ការកែបន្ទាប់ពីបិទ ជាកំណត់ត្រាដាច់ដោយឡែក។ | លំដាប់ការងារ៖ ប្រគល់ចំណត អំណានចុងក្រោយ ត្រួតពិនិត្យ និងថ្លៃ ការទូទាត់ចុងក្រោយ។ ការទូទាត់ចុងក្រោយតែមួយក្នុងមួយកិច្ចសន្យា; ការកែបន្ទាប់ពីបិទ ជាកំណត់ត្រាដាច់ដោយឡែក។ |
| moveout/text.ts | Still in the Unit / នៅក្នុងបន្ទប់ | Still in the Parking / នៅក្នុងចំណត |
| moveout/text.ts | Hand back the Unit / ប្រគល់បន្ទប់ | Hand back the Parking / ប្រគល់ចំណត |
| moveout/text.ts | បានប្រគល់នៅ {0}។ បន្ទប់ត្រូវបានកំណត់ជា {1}។ | បានប្រគល់នៅ {0}។ ចំណតត្រូវបានកំណត់ជា {1}។ |
| moveout/text.ts | អតិថិជននៅក្នុងបន្ទប់។ កត់ត្រាថ្ងៃប្រគល់ពិតប្រាកដ ពេលទទួលកូនសោ។ | អតិថិជននៅក្នុងចំណត។ កត់ត្រាថ្ងៃប្រគល់ពិតប្រាកដ ពេលទទួលកូនសោ។ |
| moveout/text.ts | Hand-back date / ថ្ងៃប្រគល់បន្ទប់ | Hand-back date / ថ្ងៃប្រគល់ចំណត |
| moveout/text.ts | The Unit after the hand-back / បន្ទប់បន្ទាប់ពីប្រគល់ | The Parking after the hand-back / ចំណតបន្ទាប់ពីប្រគល់ |
| moveout/text.ts | បន្ទប់លែងមានអ្នកស្នាក់នៅ។ ថ្លៃឈ្នួលខែប្រគល់ តាមច្បាប់បង្ហាញ។ | ចំណតលែងមានអ្នកស្នាក់នៅ។ ថ្លៃឈ្នួលខែប្រគល់ តាមច្បាប់បង្ហាញ។ |
| moveout/text.ts | After the hand-back. / បន្ទាប់ពីប្រគល់បន្ទប់។ | After the hand-back. / បន្ទាប់ពីប្រគល់ចំណត។ |
| moveout/text.ts | មិនអាចអាននាឡិកាស្ទង់នៃបន្ទប់នេះបានទេឥឡូវនេះ។ សូមបិទ ហើយព្យាយាមម្តងទៀត។ | មិនអាចអាននាឡិកាស្ទង់នៃចំណតនេះបានទេឥឡូវនេះ។ សូមបិទ ហើយព្យាយាមម្តងទៀត។ |
| moveout/text.ts | បន្ទប់នេះគ្មាននាឡិកាស្ទង់នៅ {0} ទេ។ សូមបន្ថែមនាឡិកាស្ទង់ក្នុងទឹកភ្លើងជាមុនសិន។ | ចំណតនេះគ្មាននាឡិកាស្ទង់នៅ {0} ទេ។ សូមបន្ថែមនាឡិកាស្ទង់ក្នុងទឹកភ្លើងជាមុនសិន។ |
| moveout/text.ts | បន្ទប់នេះគ្មាននាឡិកាស្ទង់នៅ {0} ទេ ដូច្នេះគ្មានអំណានចុងក្រោយ និងគ្មានវិក្កយបត្រទឹកភ្លើងចុងក្រោយទេ។ | ចំណតនេះគ្មាននាឡិកាស្ទង់នៅ {0} ទេ ដូច្នេះគ្មានអំណានចុងក្រោយ និងគ្មានវិក្កយបត្រទឹកភ្លើងចុងក្រោយទេ។ |
| moveout/text.ts | វិក្កយបត្រទឹកភ្លើងចុងក្រោយពេលចាកចេញ៖ អំណានពីអំណានវដ្តចុងក្រោយ ដល់ថ្ងៃប្រគល់បន្ទប់។ | វិក្កយបត្រទឹកភ្លើងចុងក្រោយពេលចាកចេញ៖ អំណានពីអំណានវដ្តចុងក្រោយ ដល់ថ្ងៃប្រគល់ចំណត។ |
| moveout/text.ts | ត្រួតពិនិត្យបន្ទប់បន្ទាប់ពីប្រគល់។ ថ្លៃខូចខាតនីមួយៗត្រូវមានចំនួន មូលហេតុ និងភស្តុតាង; កត់ត្រាម្តងក្នុងមួយការរកឃើញ។ | ត្រួតពិនិត្យចំណតបន្ទាប់ពីប្រគល់។ ថ្លៃខូចខាតនីមួយៗត្រូវមានចំនួន មូលហេតុ និងភស្តុតាង; កត់ត្រាម្តងក្នុងមួយការរកឃើញ។ |
| moveout/text.ts | អត្រាសម្អាតរបស់បន្ទប់នេះ៖ {0}។ | អត្រាសម្អាតរបស់ចំណតនេះ៖ {0}។ |
| moveout/text.ts | បន្ទប់នេះមិនទាន់មានអត្រាសម្អាតទេ។ កំណត់វាក្នុងការកំណត់ ហើយបន្ថែមថ្លៃ។ | ចំណតនេះមិនទាន់មានអត្រាសម្អាតទេ។ កំណត់វាក្នុងការកំណត់ ហើយបន្ថែមថ្លៃ។ |
| moveout/text.ts | អត្រាសម្អាតរបស់បន្ទប់នេះគឺសូន្យ៖ គ្មានថ្លៃសម្អាត។ | អត្រាសម្អាតរបស់ចំណតនេះគឺសូន្យ៖ គ្មានថ្លៃសម្អាត។ |
| moveout/text.ts | បន្ទប់នេះគ្មានអត្រាសម្អាតទេ។ កំណត់អត្រាជាមុនសិន។ | ចំណតនេះគ្មានអត្រាសម្អាតទេ។ កំណត់អត្រាជាមុនសិន។ |
| moveout/text.ts | អត្រាសម្អាតរបស់បន្ទប់នេះគឺសូន្យ ដូច្នេះគ្មានថ្លៃសម្អាត។ | អត្រាសម្អាតរបស់ចំណតនេះគឺសូន្យ ដូច្នេះគ្មានថ្លៃសម្អាត។ |
| moveout/text.ts | បន្ទាប់ពីកិច្ចសន្យាបញ្ចប់ និងប្រគល់បន្ទប់។ | បន្ទាប់ពីកិច្ចសន្យាបញ្ចប់ និងប្រគល់ចំណត។ |
| moveout/text.ts | បានប្រគល់នៅ {0}; បន្ទប់ត្រូវបានកំណត់ជា {1}។ | បានប្រគល់នៅ {0}; ចំណតត្រូវបានកំណត់ជា {1}។ |
| moveout/text.ts | ការប្រគល់ត្រូវបានកែ៖ {0}; បន្ទប់ {1}។ | ការប្រគល់ត្រូវបានកែ៖ {0}; ចំណត {1}។ |
| moveout/text.ts | Open Unit / បើកបន្ទប់ | Open Parking / បើកចំណត |
| moveout/text.ts | កិច្ចសន្យា ឬបន្ទប់បានផ្លាស់ប្តូរ។ ទំព័រត្រូវបានអានម្តងទៀត; សូមពិនិត្យ ហើយកត់ត្រាម្តងទៀត។ | កិច្ចសន្យា ឬចំណតបានផ្លាស់ប្តូរ។ ទំព័រត្រូវបានអានម្តងទៀត; សូមពិនិត្យ ហើយកត់ត្រាម្តងទៀត។ |
| payments/text.ts | Unit / បន្ទប់ | Parking / ចំណត |
| reports/ReportsPage.test.tsx | region / សរុបតាមបន្ទប់ និងខែ | region / សរុបតាមចំណត និងខែ |
| reports/ReportsPage.test.tsx | សរុបតាមបន្ទប់ និងខែ / ចំណូលសរុប | សរុបតាមចំណត និងខែ / ចំណូលសរុប |
| reports/text.ts | Totals by Unit and month / សរុបតាមបន្ទប់ និងខែ | Totals by Parking and month / សរុបតាមចំណត និងខែ |
| reports/text.ts | ចំនួនក្នុងវិក្កយបត្រ សម្រាប់បន្ទប់នីមួយៗ តាមខែ | ចំនួនក្នុងវិក្កយបត្រ សម្រាប់ចំណតនីមួយៗ តាមខែ |
| reports/text.ts | ប្រាក់បានទទួលពីបន្ទប់នីមួយៗ តាមខែ | ប្រាក់បានទទួលពីចំណតនីមួយៗ តាមខែ |
| reports/text.ts | អគ្គិសនីគិតថ្លៃ សម្រាប់បន្ទប់នីមួយៗ តាមរយៈពេលអាន | អគ្គិសនីគិតថ្លៃ សម្រាប់ចំណតនីមួយៗ តាមរយៈពេលអាន |
| reports/text.ts | ទឹកគិតថ្លៃ សម្រាប់បន្ទប់នីមួយៗ តាមរយៈពេលអាន | ទឹកគិតថ្លៃ សម្រាប់ចំណតនីមួយៗ តាមរយៈពេលអាន |
| reports/text.ts | kWh និង m³ តាមបន្ទប់ និងរយៈពេលអាន ជាមួយចំនួនគិតថ្លៃ | kWh និង m³ តាមចំណត និងរយៈពេលអាន ជាមួយចំនួនគិតថ្លៃ |
| reports/text.ts | Unit occupancy / ការកាន់កាប់បន្ទប់ | Parking occupancy / ការកាន់កាប់ចំណត |
| reports/text.ts | បន្ទប់នីមួយៗ៖ ស្ថានភាព អតិថិជន ចុងកិច្ចសន្យា ឬការកក់ | ចំណតនីមួយៗ៖ ស្ថានភាព អតិថិជន ចុងកិច្ចសន្យា ឬការកក់ |
| reports/text.ts | Unit / បន្ទប់ | Parking / ចំណត |
| reports/text.ts | All Units / គ្រប់បន្ទប់ | All Parking / គ្រប់ចំណត |
| reports/text.ts | Highest Unit / បន្ទប់ខ្ពស់បំផុត | Highest Parking / ចំណតខ្ពស់បំផុត |
| reports/text.ts | Not tied to a Unit / មិនភ្ជាប់នឹងបន្ទប់ | Not tied to a Parking / មិនភ្ជាប់នឹងចំណត |
| reports/text.ts | Top 5 Units / បន្ទប់ 5 ខ្ពស់បំផុត | Top 5 Parking / ចំណត 5 ខ្ពស់បំផុត |
| reports/text.ts | វិក្កយបត្រនីមួយៗរាប់ក្នុងខែដែលវាសម្រាប់៖ ថ្លៃឈ្នួលក្នុងខែឈ្នួល ទឹកភ្លើងក្នុងខែដែលរយៈពេលអានបញ្ចប់។ ប្រាក់កក់ដែលកាន់កាប់មិនមែនចំណូលទេ; ប្រាក់កក់ដែលរក្សាទុក រាប់ក្នុងខែដែលវាត្រូវបានរក្សាទុក។ ពេលជ្រើសគ្រប់បន្ទប់ បន្ទប់ទាំងអស់ត្រូវបូកបញ្ចូលគ្នា។ | វិក្កយបត្រនីមួយៗរាប់ក្នុងខែដែលវាសម្រាប់៖ ថ្លៃឈ្នួលក្នុងខែឈ្នួល ទឹកភ្លើងក្នុងខែដែលរយៈពេលអានបញ្ចប់។ ប្រាក់កក់ដែលកាន់កាប់មិនមែនចំណូលទេ; ប្រាក់កក់ដែលរក្សាទុក រាប់ក្នុងខែដែលវាត្រូវបានរក្សាទុក។ ពេលជ្រើសគ្រប់ចំណត ចំណតទាំងអស់ត្រូវបូកបញ្ចូលគ្នា។ |
| reports/text.ts | បង្កាន់ដៃនីមួយៗរាប់នៅថ្ងៃដែលលុយចូល រួមទាំងប្រាក់កក់; ការបង់ប្រាក់ដែលត្រូវបានត្រឡប់វិញ ត្រូវដកចេញក្នុងខែដែលវាត្រូវបានត្រឡប់។ សម្រាប់ខែពេញដូចគ្នា សរុបនេះដូចរបាយការណ៍ការបង់ប្រាក់៖ «ប្រាក់ទទួល ដកការត្រឡប់វិញ» ឬ «ប្រាក់បានទទួល» ពេលគ្មានការត្រឡប់វិញ។ ពេលជ្រើសគ្រប់បន្ទប់ បន្ទប់ទាំងអស់ត្រូវបូកបញ្ចូលគ្នា។ | បង្កាន់ដៃនីមួយៗរាប់នៅថ្ងៃដែលលុយចូល រួមទាំងប្រាក់កក់; ការបង់ប្រាក់ដែលត្រូវបានត្រឡប់វិញ ត្រូវដកចេញក្នុងខែដែលវាត្រូវបានត្រឡប់។ សម្រាប់ខែពេញដូចគ្នា សរុបនេះដូចរបាយការណ៍ការបង់ប្រាក់៖ «ប្រាក់ទទួល ដកការត្រឡប់វិញ» ឬ «ប្រាក់បានទទួល» ពេលគ្មានការត្រឡប់វិញ។ ពេលជ្រើសគ្រប់ចំណត ចំណតទាំងអស់ត្រូវបូកបញ្ចូលគ្នា។ |
| reports/text.ts | ខែនីមួយៗ មានរយៈពេលអានដែលបញ្ចប់នៅថ្ងៃទី 24 នៃខែនោះ (តុលា = 25/09 – 24/10) តាមអត្រានៃរយៈពេលនោះ។ ពេលជ្រើសគ្រប់បន្ទប់ បន្ទប់ទាំងអស់ត្រូវបូកបញ្ចូលគ្នា។ | ខែនីមួយៗ មានរយៈពេលអានដែលបញ្ចប់នៅថ្ងៃទី 24 នៃខែនោះ (តុលា = 25/09 – 24/10) តាមអត្រានៃរយៈពេលនោះ។ ពេលជ្រើសគ្រប់ចំណត ចំណតទាំងអស់ត្រូវបូកបញ្ចូលគ្នា។ |
| reports/text.ts | Unit Type / ប្រភេទបន្ទប់ | Parking Type / ប្រភេទចំណត |
| reports/text.ts | Units / បន្ទប់ | Parking / ចំណត |
| reports/text.ts | 1 Unit / បន្ទប់ 1 | 1 Parking / ចំណត 1 |
| reports/text.ts | {0} Units / បន្ទប់ {0} | {0} Parking / ចំណត {0} |
| reports/text.ts | Units by status / បន្ទប់តាមស្ថានភាព | Parking by status / ចំណតតាមស្ថានភាព |
| reports/text.ts | ឯកសារនេះមានទិន្នន័យផ្ទាល់ខ្លួន (ឈ្មោះ បន្ទប់ លេខទូរស័ព្ទ)។ រក្សាក្នុងអាជីវកម្ម និងលុបពេលរួចរាល់។ | ឯកសារនេះមានទិន្នន័យផ្ទាល់ខ្លួន (ឈ្មោះ ចំណត លេខទូរស័ព្ទ)។ រក្សាក្នុងអាជីវកម្ម និងលុបពេលរួចរាល់។ |
| reservations/text.ts | ការកក់ {0} · បន្ទប់ដែលរក្សាទុកសម្រាប់អតិថិជន រហូតដល់ចុះហត្ថលេខាកិច្ចសន្យា | ការកក់ {0} · ចំណតដែលរក្សាទុកសម្រាប់អតិថិជន រហូតដល់ចុះហត្ថលេខាកិច្ចសន្យា |
| reservations/text.ts | Holding a Unit now / កំពុងរក្សាបន្ទប់ឥឡូវនេះ | Holding a Parking now / កំពុងរក្សាចំណតឥឡូវនេះ |
| reservations/text.ts | Unit / បន្ទប់ | Parking / ចំណត |
| reservations/text.ts | Customer no longer wants the Unit / អតិថិជនលែងចង់បានបន្ទប់ | Customer no longer wants the Parking / អតិថិជនលែងចង់បានចំណត |
| reservations/text.ts | អគារមិនអាចផ្តល់បន្ទប់បាន | អគារមិនអាចផ្តល់ចំណតបាន |
| reservations/text.ts | អតិថិជនលែងចង់បានបន្ទប់។ តាមវិធាន ប្រាក់កក់សុវត្ថិភាពត្រូវរក្សាទុក។ | អតិថិជនលែងចង់បានចំណត។ តាមវិធាន ប្រាក់កក់សុវត្ថិភាពត្រូវរក្សាទុក។ |
| reservations/text.ts | អគារមិនអាចផ្តល់បន្ទប់បាន ហើយអតិថិជនបដិសេធកាលបរិច្ឆេទក្រោយ ឬបន្ទប់ផ្សេង។ តាមវិធាន ប្រាក់កក់សុវត្ថិភាពត្រូវសងវិញ។ | អគារមិនអាចផ្តល់ចំណតបាន ហើយអតិថិជនបដិសេធកាលបរិច្ឆេទក្រោយ ឬចំណតផ្សេង។ តាមវិធាន ប្រាក់កក់សុវត្ថិភាពត្រូវសងវិញ។ |
| reservations/text.ts | បន្ទប់ត្រឡប់ទៅទំនេរភ្លាមៗ។ គ្មានប្រាក់ផ្លាស់ទីឥឡូវទេ៖ ការសម្រេចលើប្រាក់កក់ត្រូវកត់ត្រាជាសេចក្តីព្រាង ហើយម្ចាស់ ឬអ្នកគ្រប់គ្រងបញ្ជាក់វា។ | ចំណតត្រឡប់ទៅទំនេរភ្លាមៗ។ គ្មានប្រាក់ផ្លាស់ទីឥឡូវទេ៖ ការសម្រេចលើប្រាក់កក់ត្រូវកត់ត្រាជាសេចក្តីព្រាង ហើយម្ចាស់ ឬអ្នកគ្រប់គ្រងបញ្ជាក់វា។ |
| reservations/text.ts | Choose a vacant Unit / ជ្រើសរើសបន្ទប់ទំនេរ | Choose a vacant Parking / ជ្រើសរើសចំណតទំនេរ |
| reservations/text.ts | No Unit is vacant now. / ឥឡូវនេះមិនមានបន្ទប់ទំនេរទេ។ | No Parking is vacant now. / ឥឡូវនេះមិនមានចំណតទំនេរទេ។ |
| reservations/text.ts | Choose a Unit. / សូមជ្រើសរើសបន្ទប់។ | Choose a Parking. / សូមជ្រើសរើសចំណត។ |
| reservations/text.ts | ការកក់មិនត្រូវបានរក្សាទុកទេ៖ បន្ទប់ ឬអតិថិជនបានផ្លាស់ប្តូរក្នុងពេលនេះ (ឧទាហរណ៍ មានអ្នកផ្សេងបានកក់បន្ទប់នេះមុន)។ សូមពិនិត្យពួកវា រួចព្យាយាមម្តងទៀត។ | ការកក់មិនត្រូវបានរក្សាទុកទេ៖ ចំណត ឬអតិថិជនបានផ្លាស់ប្តូរក្នុងពេលនេះ (ឧទាហរណ៍ មានអ្នកផ្សេងបានកក់ចំណតនេះមុន)។ សូមពិនិត្យពួកវា រួចព្យាយាមម្តងទៀត។ |
| reservations/text.ts | ការកក់មិនត្រូវបានរក្សាទុកទេ៖ បន្ទប់ ឬអតិថិជនបានផ្លាស់ប្តូរក្នុងពេលនេះ (ឧទាហរណ៍ មានអ្នកផ្សេងបានកក់បន្ទប់នេះមុន)។ | ការកក់មិនត្រូវបានរក្សាទុកទេ៖ ចំណត ឬអតិថិជនបានផ្លាស់ប្តូរក្នុងពេលនេះ (ឧទាហរណ៍ មានអ្នកផ្សេងបានកក់ចំណតនេះមុន)។ |
| reservations/text.ts | កំពុងអានបន្ទប់ និងអតិថិជន… | កំពុងអានចំណត និងអតិថិជន… |
| settings/CleaningRates.test.tsx | បន្ទប់តូច | ចំណតតូច |
| settings/UnitSetupTab.test.tsx | បន្ទប់កំពុងប្រើ | ចំណតកំពុងប្រើ |
| settings/UnitSetupTab.test.tsx | មិនទាន់មានបន្ទប់ | មិនទាន់មានចំណត |
| settings/text.ts | Unit setup / ការរៀបចំបន្ទប់ | Parking setup / ការរៀបចំចំណត |
| settings/text.ts | បញ្ជីទាំងនេះបំពេញជម្រើសនៅលើបន្ទប់ថ្មី និងកែបន្ទប់។ ធាតុដែលបន្ទប់កំពុងប្រើ មិនអាចដកចេញបានទេ សូមប្តូរឈ្មោះវិញ។ | បញ្ជីទាំងនេះបំពេញជម្រើសនៅលើចំណតថ្មី និងកែចំណត។ ធាតុដែលចំណតកំពុងប្រើ មិនអាចដកចេញបានទេ សូមប្តូរឈ្មោះវិញ។ |
| settings/text.ts | Unit Types / ប្រភេទបន្ទប់ | Parking Types / ប្រភេទចំណត |
| settings/text.ts | Room features / លក្ខណៈបន្ទប់ | Room features / លក្ខណៈចំណត |
| settings/text.ts | Unit Type / ប្រភេទបន្ទប់ | Parking Type / ប្រភេទចំណត |
| settings/text.ts | Room feature / លក្ខណៈបន្ទប់ | Room feature / លក្ខណៈចំណត |
| settings/text.ts | ការប្តូរឈ្មោះរក្សាបន្ទប់ទាំងអស់នៃប្រភេទនេះ។ សូមបន្ថែមប្រភេទថ្មីទៅអត្រាសម្អាតពេលចាកចេញ នៅផ្ទាំងអត្រា និងសេវា។ | ការប្តូរឈ្មោះរក្សាចំណតទាំងអស់នៃប្រភេទនេះ។ សូមបន្ថែមប្រភេទថ្មីទៅអត្រាសម្អាតពេលចាកចេញ នៅផ្ទាំងអត្រា និងសេវា។ |
| settings/text.ts | លក្ខណៈបន្ទប់បង្ហាញជា មាន ឬ គ្មាន នៅលើទំព័របន្ទប់នីមួយៗ។ | លក្ខណៈចំណតបង្ហាញជា មាន ឬ គ្មាន នៅលើទំព័រចំណតនីមួយៗ។ |
| settings/text.ts | 1 Unit / 1 បន្ទប់ | 1 Parking / 1 ចំណត |
| settings/text.ts | {0} Units / {0} បន្ទប់ | {0} Parking / {0} ចំណត |
| settings/text.ts | No Units yet / មិនទាន់មានបន្ទប់ | No Parking yet / មិនទាន់មានចំណត |
| settings/text.ts | Used by a Unit / បន្ទប់កំពុងប្រើ | Used by a Parking / ចំណតកំពុងប្រើ |
| settings/text.ts | មាននរណាម្នាក់បានប្តូរបញ្ជីនេះ ឬបន្ទប់មួយកំពុងប្រើធាតុនេះ។ បញ្ជីត្រូវបានអានម្តងទៀត សូមពិនិត្យ ហើយព្យាយាមម្តងទៀត។ | មាននរណាម្នាក់បានប្តូរបញ្ជីនេះ ឬចំណតមួយកំពុងប្រើធាតុនេះ។ បញ្ជីត្រូវបានអានម្តងទៀត សូមពិនិត្យ ហើយព្យាយាមម្តងទៀត។ |
| settings/text.ts | ការងារប្រចាំថ្ងៃ៖ ការបង់ប្រាក់ វិក្កយបត្រ អំណាន បន្ទប់ អតិថិជន ការកក់ កិច្ចសន្យា ជំហានចាកចេញ | ការងារប្រចាំថ្ងៃ៖ ការបង់ប្រាក់ វិក្កយបត្រ អំណាន ចំណត អតិថិជន ការកក់ កិច្ចសន្យា ជំហានចាកចេញ |
| settings/text.ts | Units / បន្ទប់ | Parking / ចំណត |
| settings/text.ts | {0} មានបន្ទប់ ហើយត្រូវការអត្រាសម្អាត។ សូមដាក់វាក្នុងអត្រាផ្សេងជាមុនសិន។ | {0} មានចំណត ហើយត្រូវការអត្រាសម្អាត។ សូមដាក់វាក្នុងអត្រាផ្សេងជាមុនសិន។ |
| settings/text.ts | ការចាកចេញមានថ្លៃសម្អាត តាមអត្រានៃប្រភេទបន្ទប់។ ចំនួនថ្មីអនុវត្តចំពោះបន្ទប់ទាំងអស់នៃប្រភេទរបស់វា ចាប់ពីពេលនេះតទៅ ថ្លៃដែលបានធ្វើរួចរក្សាចំនួនដើម។ | ការចាកចេញមានថ្លៃសម្អាត តាមអត្រានៃប្រភេទចំណត។ ចំនួនថ្មីអនុវត្តចំពោះចំណតទាំងអស់នៃប្រភេទរបស់វា ចាប់ពីពេលនេះតទៅ ថ្លៃដែលបានធ្វើរួចរក្សាចំនួនដើម។ |
| settings/text.ts | ប្រភេទបន្ទប់ដែលមានបន្ទប់ ត្រូវការអត្រាសម្អាត។ សូមដាក់វាក្នុងអត្រាផ្សេងជាមុនសិន។ បញ្ជីត្រូវបានអានម្តងទៀត។ | ប្រភេទចំណតដែលមានចំណត ត្រូវការអត្រាសម្អាត។ សូមដាក់វាក្នុងអត្រាផ្សេងជាមុនសិន។ បញ្ជីត្រូវបានអានម្តងទៀត។ |
| shell/AppShell.test.tsx | link / បន្ទប់ | link / ចំណត |
| shell/navigation.ts | Units / បន្ទប់ | Parking / ចំណត |
| units/text.ts | {0} Units at CHETANA Parking / បន្ទប់ {0} នៅ CHETANA Parking | {0} Parking at CHETANA Parking / ចំណត {0} នៅ CHETANA Parking |
| units/text.ts | Loading the Units… / កំពុងផ្ទុកបន្ទប់… | Loading Parking… / កំពុងផ្ទុកចំណត… |
| units/text.ts | មិនអាចអានបន្ទប់បានទេ។ សូមព្យាយាមម្តងទៀតពេលសេវាអាចប្រើបាន។ | មិនអាចអានចំណតបានទេ។ សូមព្យាយាមម្តងទៀតពេលសេវាអាចប្រើបាន។ |
| units/text.ts | មិនទាន់ស្គាល់អគារ ដូច្នេះមិនអាចបង្ហាញបន្ទប់បានទេ។ | មិនទាន់ស្គាល់អគារ ដូច្នេះមិនអាចបង្ហាញចំណតបានទេ។ |
| units/text.ts | មិនអាចអានបញ្ជីការកំណត់បានទេ ដូច្នេះមិនអាចបន្ថែម ឬកែបន្ទប់បានឥឡូវនេះ។ | មិនអាចអានបញ្ជីការកំណត់បានទេ ដូច្នេះមិនអាចបន្ថែម ឬកែចំណតបានឥឡូវនេះ។ |
| units/text.ts | New Unit / បន្ទប់ថ្មី | New Parking / ចំណតថ្មី |
| units/text.ts | Unit Type / ប្រភេទបន្ទប់ | Parking Type / ប្រភេទចំណត |
| units/text.ts | ការកក់កំពុងរក្សាបន្ទប់ | ការកក់កំពុងរក្សាចំណត |
| units/text.ts | Unit / បន្ទប់ | Parking / ចំណត |
| units/text.ts | 1 Unit / បន្ទប់ 1 | 1 Parking / ចំណត 1 |
| units/text.ts | {0} Units / បន្ទប់ {0} | {0} Parking / ចំណត {0} |
| units/text.ts | No Units match these filters. / គ្មានបន្ទប់ត្រូវនឹងតម្រងនេះទេ។ | No Parking matches these filters. / គ្មានចំណតត្រូវនឹងតម្រងនេះទេ។ |
| units/text.ts | រកមិនឃើញបន្ទប់នេះទេ។ ត្រឡប់ទៅបញ្ជីបន្ទប់។ | រកមិនឃើញចំណតនេះទេ។ ត្រឡប់ទៅបញ្ជីចំណត។ |
| units/text.ts | Update Unit / ធ្វើបច្ចុប្បន្នភាពបន្ទប់ | Update Parking / ធ្វើបច្ចុប្បន្នភាពចំណត |
| units/text.ts | Unit details / ព័ត៌មានលម្អិតបន្ទប់ | Parking details / ព័ត៌មានលម្អិតចំណត |
| units/text.ts | No photo of this Unit yet. / មិនទាន់មានរូបថតបន្ទប់នេះទេ។ | No photo of this Parking yet. / មិនទាន់មានរូបថតចំណតនេះទេ។ |
| units/text.ts | Bedrooms / បន្ទប់គេង | Bedrooms / បន្ទប់គេង (unchanged: bedroom is its own word) |
| units/text.ts | Bathrooms / បន្ទប់ទឹក | Bathrooms / បន្ទប់ទឹក (unchanged: bathroom is its own word) |
| units/text.ts | Room features / លក្ខណៈបន្ទប់ | Room features / លក្ខណៈចំណត |
| units/text.ts | បន្ទប់នេះទំនេរ។ អាចកក់ ឬព្រាងកិច្ចសន្យាសម្រាប់អតិថិជនដែលមកផ្ទាល់។ | ចំណតនេះទំនេរ។ អាចកក់ ឬព្រាងកិច្ចសន្យាសម្រាប់អតិថិជនដែលមកផ្ទាល់។ |
| units/text.ts | គណនីរបស់អ្នកមិនអាចអានកិច្ចសន្យា ឬការកក់សម្រាប់បន្ទប់នេះបានទេ។ | គណនីរបស់អ្នកមិនអាចអានកិច្ចសន្យា ឬការកក់សម្រាប់ចំណតនេះបានទេ។ |
| units/text.ts | Invoices for this Unit / វិក្កយបត្រសម្រាប់បន្ទប់នេះ | Invoices for this Parking / វិក្កយបត្រសម្រាប់ចំណតនេះ |
| units/text.ts | វិក្កយបត្រមិនទាន់បង់សម្រាប់បន្ទប់នេះនឹងបង្ហាញនៅទីនេះ ពេលរៀបចំវិក្កយបត្រឡើងវិញ (ជំហាន R5)។ | វិក្កយបត្រមិនទាន់បង់សម្រាប់ចំណតនេះនឹងបង្ហាញនៅទីនេះ ពេលរៀបចំវិក្កយបត្រឡើងវិញ (ជំហាន R5)។ |
| units/text.ts | Unit created. / បានបង្កើតបន្ទប់។ | Parking created. / បានបង្កើតចំណត។ |
| units/text.ts | Unit details updated. / បានធ្វើបច្ចុប្បន្នភាពព័ត៌មានបន្ទប់។ | Parking details updated. / បានធ្វើបច្ចុប្បន្នភាពព័ត៌មានចំណត។ |
| units/text.ts | Unit number / លេខបន្ទប់ | Parking number / លេខចំណត |
| units/text.ts | Enter the Unit number. / សូមបញ្ចូលលេខបន្ទប់។ | Enter the Parking number. / សូមបញ្ចូលលេខចំណត។ |
| units/text.ts | មិនទាន់មានលក្ខណៈបន្ទប់ក្នុងការកំណត់ទេ។ | មិនទាន់មានលក្ខណៈចំណតក្នុងការកំណត់ទេ។ |
| units/text.ts | បន្ទប់ថ្មីចាប់ផ្តើមជាទំនេរ ជាមួយបញ្ជីសម្ភារៈទទេ; បន្ថែមសម្ភារៈនៅទំព័របន្ទប់។ | ចំណតថ្មីចាប់ផ្តើមជាទំនេរ ជាមួយបញ្ជីសម្ភារៈទទេ; បន្ថែមសម្ភារៈនៅទំព័រចំណត។ |
| units/text.ts | ការផ្លាស់ប្តូរមានកាលបរិច្ឆេទ និងរក្សាទុកក្នុងប្រវត្តិ។ លេខបន្ទប់មិនអាចប្តូរបានទេ។ | ការផ្លាស់ប្តូរមានកាលបរិច្ឆេទ និងរក្សាទុកក្នុងប្រវត្តិ។ លេខចំណតមិនអាចប្តូរបានទេ។ |
| units/text.ts | Unit {0} added as Vacant. / បានបន្ថែមបន្ទប់ {0} ជាទំនេរ។ | Parking {0} added as Vacant. / បានបន្ថែមចំណត {0} ជាទំនេរ។ |
| units/text.ts | Unit {0} updated. / បានធ្វើបច្ចុប្បន្នភាពបន្ទប់ {0}។ | Parking {0} updated. / បានធ្វើបច្ចុប្បន្នភាពចំណត {0}។ |
| units/text.ts | សូមពិនិត្យព័ត៌មានបន្ទប់។ លេខបន្ទប់អាចត្រូវបានប្រើរួច ឬធាតុក្នុងបញ្ជីអាចត្រូវបានដកចេញ។ | សូមពិនិត្យព័ត៌មានចំណត។ លេខចំណតអាចត្រូវបានប្រើរួច ឬធាតុក្នុងបញ្ជីអាចត្រូវបានដកចេញ។ |
| units/text.ts | មាននរណាម្នាក់បានកែបន្ទប់នេះមុន។ ព័ត៌មានចុងក្រោយត្រូវបានបង្ហាញឥឡូវ; សូមព្យាយាមម្តងទៀតបើចាំបាច់។ | មាននរណាម្នាក់បានកែចំណតនេះមុន។ ព័ត៌មានចុងក្រោយត្រូវបានបង្ហាញឥឡូវ; សូមព្យាយាមម្តងទៀតបើចាំបាច់។ |
| units/text.ts | បន្ទប់នេះមានកិច្ចសន្យាបានចុះហត្ថលេខា។ ស្ថានភាពប្តូរបានតែតាមរយៈការចាកចេញប៉ុណ្ណោះ។ | ចំណតនេះមានកិច្ចសន្យាបានចុះហត្ថលេខា។ ស្ថានភាពប្តូរបានតែតាមរយៈការចាកចេញប៉ុណ្ណោះ។ |
| units/text.ts | បន្ទប់នេះមានការកក់កំពុងដំណើរការ។ សូមលុបចោលការកក់ជាមុន។ | ចំណតនេះមានការកក់កំពុងដំណើរការ។ សូមលុបចោលការកក់ជាមុន។ |
| utilities/text.ts | Unit / បន្ទប់ | Parking / ចំណត |
| utilities/text.ts | All Units / គ្រប់បន្ទប់ | All Parking / គ្រប់ចំណត |
| utilities/text.ts | អានគ្រប់នាឡិកាស្ទង់ រួមទាំងបន្ទប់ទំនេរ។ វិក្កយបត្រនឹងចេញថ្ងៃ {0} ពីអំណានទាំងនេះ។ | អានគ្រប់នាឡិកាស្ទង់ រួមទាំងចំណតទំនេរ។ វិក្កយបត្រនឹងចេញថ្ងៃ {0} ពីអំណានទាំងនេះ។ |
| utilities/text.ts | Unit · Meter / បន្ទប់ · នាឡិកាស្ទង់ | Parking · Meter / ចំណត · នាឡិកាស្ទង់ |
| utilities/text.ts | In use, one per Unit / កំពុងប្រើ មួយក្នុងមួយបន្ទប់ | In use, one per Parking / កំពុងប្រើ មួយក្នុងមួយចំណត |
| utilities/text.ts | សម្រាប់បន្ទប់ដែលគ្មាននាឡិកាស្ទង់ប្រភេទនេះ ដូចជាបន្ទប់ថ្មី។ បន្ទប់មួយមាននាឡិកាស្ទង់អគ្គិសនីមួយ និងទឹកមួយ។ ដើម្បីប្តូរនាឡិកាស្ទង់ខូច សូមបើកវា ហើយជ្រើស ប្តូរនាឡិកាស្ទង់។ | សម្រាប់ចំណតដែលគ្មាននាឡិកាស្ទង់ប្រភេទនេះ ដូចជាចំណតថ្មី។ ចំណតមួយមាននាឡិកាស្ទង់អគ្គិសនីមួយ និងទឹកមួយ។ ដើម្បីប្តូរនាឡិកាស្ទង់ខូច សូមបើកវា ហើយជ្រើស ប្តូរនាឡិកាស្ទង់។ |
| utilities/text.ts | Choose a Unit. / សូមជ្រើសបន្ទប់។ | Choose a Parking. / សូមជ្រើសចំណត។ |
| utilities/text.ts | Choose a Unit / ជ្រើសបន្ទប់ | Choose a Parking / ជ្រើសចំណត |
| utilities/text.ts | បន្ទប់ទាំងអស់មាននាឡិកាស្ទង់{0}រួចហើយ។ ដើម្បីប្តូរនាឡិកាស្ទង់ខូច សូមបើកវា ហើយជ្រើស ប្តូរនាឡិកាស្ទង់។ | ចំណតទាំងអស់មាននាឡិកាស្ទង់{0}រួចហើយ។ ដើម្បីប្តូរនាឡិកាស្ទង់ខូច សូមបើកវា ហើយជ្រើស ប្តូរនាឡិកាស្ទង់។ |
| utilities/text.ts | {0} មាននាឡិកាស្ទង់{1}កំពុងប្រើរួចហើយ ({2})។ បន្ទប់មួយអាចមានតែមួយ។ | {0} មាននាឡិកាស្ទង់{1}កំពុងប្រើរួចហើយ ({2})។ ចំណតមួយអាចមានតែមួយ។ |
| utilities/text.ts | មួយជួរសម្រាប់បន្ទប់នីមួយៗ មានបីជួរឈរ៖ បន្ទប់ អគ្គិសនី ទឹក។ បន្ទប់បានបំពេញរួចហើយ ដូច្នេះបុគ្គលិកវាយតែអំណានប៉ុណ្ណោះ។ គ្មានលេខនាឡិកាស្ទង់ទេ។ | មួយជួរសម្រាប់ចំណតនីមួយៗ មានបីជួរឈរ៖ ចំណត អគ្គិសនី ទឹក។ ចំណតបានបំពេញរួចហើយ ដូច្នេះបុគ្គលិកវាយតែអំណានប៉ុណ្ណោះ។ គ្មានលេខនាឡិកាស្ទង់ទេ។ |
| utilities/text.ts | បន្ទប់ទាំងអស់បានបំពេញរួច។ បោះពុម្ព ឬបំពេញលើថេប្លេត។ | ចំណតទាំងអស់បានបំពេញរួច។ បោះពុម្ព ឬបំពេញលើថេប្លេត។ |
| utilities/text.ts | ឯកសារធំជាង 2 MB។ វាត្រូវការតែមួយជួរសម្រាប់បន្ទប់នីមួយៗ។ | ឯកសារធំជាង 2 MB។ វាត្រូវការតែមួយជួរសម្រាប់ចំណតនីមួយៗ។ |
| utilities/text.ts | ឯកសារមានជួរច្រើនពេក។ វាត្រូវការមួយជួរសម្រាប់បន្ទប់នីមួយៗ។ | ឯកសារមានជួរច្រើនពេក។ វាត្រូវការមួយជួរសម្រាប់ចំណតនីមួយៗ។ |
| utilities/text.ts | There is no Unit {0}. / គ្មានបន្ទប់ {0} ទេ។ | There is no Parking {0}. / គ្មានចំណត {0} ទេ។ |
| utilities/text.ts | Row {0} has no Unit. / ជួរទី {0} គ្មានបន្ទប់។ | Row {0} has no Parking. / ជួរទី {0} គ្មានចំណត។ |
| utilities/text.ts | បន្ទប់នេះគ្មាននាឡិកាស្ទង់{0}ទេ។ អ្នកគ្រប់គ្រងបន្ថែមវានៅផ្ទាំងនាឡិកាស្ទង់។ | ចំណតនេះគ្មាននាឡិកាស្ទង់{0}ទេ។ អ្នកគ្រប់គ្រងបន្ថែមវានៅផ្ទាំងនាឡិកាស្ទង់។ |
| utilities/text.ts | មិនត្រូវការរូបថតនាឡិកាស្ទង់ទេ។ រាយការណ៍បញ្ហានាឡិកាស្ទង់លើការពិនិត្យបន្ទប់។ | មិនត្រូវការរូបថតនាឡិកាស្ទង់ទេ។ រាយការណ៍បញ្ហានាឡិកាស្ទង់លើការពិនិត្យចំណត។ |

## Backend messages staff can see or that reach logs (45 lines)

The 14 backend texts that the database raises or seeds (cleaning-charge and signing refusal keys, the payment-move key, the three capability descriptions) were put back to "Unit" after the code review; see "Words the database writes or raises" above. They are not in this table.

| File | Message before | Message after |
|---|---|---|
| backend: api_refusals.py | This Unit has no cleaning rate. Set the rate first. | This Parking has no cleaning rate. Set the rate first. |
| backend: api_refusals.py | This Unit's cleaning rate is zero, so there is no cleaning charge. | This Parking's cleaning rate is zero, so there is no cleaning charge. |
| backend: api_refusals.py | Choose an Invoice of a Lease on another Unit as the correct Invoice. | Choose an Invoice of a Lease on another Parking as the correct Invoice. |
| backend: api_refusals.py | This allocation was moved to another Unit's Invoice. Correct it with another move draft or  | This allocation was moved to another Parking's Invoice. Correct it with another move draft or  |
| backend: audit_api.py | stored Unit floor is not a canonical text label | stored Parking floor is not a canonical text label |
| backend: invoice.py | Unit cleaning rate read returned no result | Parking cleaning rate read returned no result |
| backend: lease_signing_api.py | Someone still lives in this Unit (an open Occupancy). Nothing was saved. | Someone still lives in this Parking (an open Occupancy). Nothing was saved. |
| backend: lease_signing_api.py | This Unit cannot be signed now: it is Reserved for someone else, Out of Service or  | This Parking cannot be signed now: it is Reserved for someone else, Out of Service or  |
| backend: lease_signing_api.py | The Customer's Reservation of this Unit has ended or changed, so this draft cannot take  | The Customer's Reservation of this Parking has ended or changed, so this draft cannot  |
| backend: lease_signing_api.py | its Security Deposit. Nothing was saved. Ask the Owner or a Manager. | take its Security Deposit. Nothing was saved. Ask the Owner or a Manager. |
| backend: lease_signing_api.py | The Customer's Reservation of this Unit has no Security Deposit. Nothing was saved. | The Customer's Reservation of this Parking has no Security Deposit. Nothing was saved. |
| backend: lease_signing_api.py | Another signed Lease of this Unit covers these dates. Nothing was saved. Check the dates  | Another signed Lease of this Parking covers these dates. Nothing was saved. Check the dates  |
| backend: lease_signing_api.py | Check the Lease, its Unit and its Customer, or ask the Owner. | Check the Lease, its Parking and its Customer, or ask the Owner. |
| backend: physical_move_out.py | An explicit nonavailable Unit condition is required | raise PhysicalMoveOutInvalidError( |
| backend: report_exports.py | unit_occupancy / Unit occupancy | unit_occupancy / Parking occupancy |
| backend: report_exports.py | Unit {unit_number} / Floor {floor} / Whole Property | Parking {unit_number} |
| backend: report_exports.py | A register is filtered by floor, not by Unit | A register is filtered by floor, not by Parking |
| backend: report_files.py | unit_number / Unit | unit_number / Parking |
| backend: reports.py | Unknown Unit | Unknown Parking |
| backend: reports_api.py | A Totals by Unit and month report | A Totals by Parking and month report |
| backend: service_settings_api.py | A Unit Type that has Units needs a cleaning rate. Put it in another rate first. | A Parking Type that has Parking needs a cleaning rate. Put it in another rate first. |
| backend: unit.py | Unit number {unit.unit_number!r} already exists in this Property | Parking number {unit.unit_number!r} already exists in this Property |
| backend: unit.py | Unit identity {unit.unit_id} already exists | Parking identity {unit.unit_id} already exists |
| backend: unit.py | Unit creation returned an invalid result | Parking creation returned an invalid result |
| backend: unit.py | Unit is assigned to a different Property ID | Parking is assigned to a different Property ID |
| backend: unit.py | Unit number {normalized_number!r} already exists in this Property | Parking number {normalized_number!r} already exists in this Property |
| backend: unit_api.py | the Unit version precondition was not met | the Parking version precondition was not met |
| backend: unit_api.py | Unit persistence is unavailable | Parking persistence is unavailable |
| backend: unit_api.py | Unit was not found | Parking was not found |
| backend: unit_api.py | Unit source data changed through the authorized Unit API | Parking source data changed through the authorized Parking API |
| backend: unit_api.py | Unit creation returned no result | Parking creation returned no result |
| backend: unit_api.py | Unit source fields are invalid | Parking source fields are invalid |
| backend: unit_api.py | Unit identity or number already exists | Parking identity or number already exists |
| backend: unit_api.py | Unit setup lists are unavailable | Parking setup lists are unavailable |
| backend: unit_api.py | Unit setup item was not found | Parking setup item was not found |
| backend: unit_api.py | A Unit uses this item | A Parking uses this item |
| backend: unit_api.py | Unit setup item fields are invalid | Parking setup item fields are invalid |
| backend: unit_api.py | Unit setup item creation returned no result | Parking setup item creation returned no result |
| backend: unit_api.py | unit_type must be a code of the Unit Types list | unit_type must be a code of the Parking Types list |
| backend: unit_inventory_api.py | Unit persistence is unavailable | Parking persistence is unavailable |
| backend: unit_inventory_api.py | Unit inventory lines are unreadable | Parking inventory lines are unreadable |
| backend: unit_inventory_api.py | Unit was not found | Parking was not found |
| backend: unit_inventory_api.py | Unit inventory is invalid | Parking inventory is invalid |
| backend: utility_sheet.py | unit / electricity / water | parking / electricity / water |
| backend: utility_sheet.py | Unit / Electricity / Water | Parking / Electricity / Water |
