# 002 - Business Rules

**Project:** Property Rental Management System
**Document:** Business Rules
**Version:** 2.0 (short form, DL-226, 2026-11-12)
**Status:** Owner Review
**Depends On:** `001_DOMAIN_MODEL.md`
**Audience:** Product Owner, Business Analysts, Software Architects, Developers, QA Engineers

---

# 1. Purpose

This document holds the business rules of the Property Rental Management System: what users may do, when, how money is worked out, how a status changes, and who must approve.

The rules are the same for every way in: the screens, the API, a scheduled job, or an automatic billing run.

Every business and money rule is the owner's decision. The decision log (`010_DECISION_LOG.md`) holds the history of each decision. This document holds only the rule as it stands today.

# 2. How to Read This Document

Version 2.0 says each rule once. Version 1.0 had 396 rules; many said the same thing for one more kind of record. Nothing was taken out of the business: each short rule names the old rules it replaces.

- The heading of a rule is a rule number that existed in version 1.0. Rule numbers are stable. Use them in requirements, the API, the screens, tests and the decision log.
- **Replaces** lists the other version 1.0 numbers whose text is now in this rule. A test or a note that names one of those numbers points to this rule.
- **Decisions** lists the decision-log entries that changed the rule.
- Appendix A shows where every version 1.0 number went.
- Appendix B lists what the owner has decided but the app does not do yet.

| Prefix       | Meaning                         |
| ------------ | ------------------------------- |
| `BR-PROP`    | General rules                   |
| `BR-UNIT`    | Unit rules                      |
| `BR-CUST`    | Customer rules                  |
| `BR-RES`     | Reservation rules               |
| `BR-LEASE`   | Lease rules                     |
| `BR-OCC`     | Occupancy rules                 |
| `BR-DEP`     | Deposit rules                   |
| `BR-RENT`    | Rent rules                      |
| `BR-UTIL`    | Utilities rules                 |
| `BR-SVC`     | Service rules                   |
| `BR-INV`     | Invoice rules                   |
| `BR-LATE`    | Late-payment charge rules       |
| `BR-PAY`     | Payment and allocation rules    |
| `BR-RECEIPT` | Receipt rules                   |
| `BR-CREDIT`  | Customer Credit rules           |
| `BR-LEDGER`  | Customer account view rules     |
| `BR-REFUND`  | Refund rules                    |
| `BR-MOVEOUT` | Move-out rules                  |
| `BR-SETTLE`  | Final Settlement rules          |
| `BR-MONEY`   | Money and currency rules        |
| `BR-AUDIT`   | History rules                   |
| `BR-AUTH`    | Rights rules                    |

When two rules seem to disagree, this order decides:

1. Correct money and history
2. The state of the Lease
3. A valid Reservation
4. A free Unit
5. Billing rules
6. Convenience

An action that breaks a rule is refused. The app never quietly changes what a user typed to make a wrong action look right. Where a rule allows an exception, the exception is explicit, needs the right, and is kept in the history.

---

# 3. General Rules

## BR-PROP-001 — One Property

One installed application manages exactly one Property. Nobody can make a second Property, switch between Properties, or move a Unit to another Property.

## BR-PROP-002 — No Record Is Deleted

Business and money records are never deleted or rewritten in normal work. A record that is no longer in force gets its status or its own event: Cancelled, Terminated, Void, Reversed, a Meter replacement, a Move-out, a Refund. A mistake is corrected by a new record that names the old one.

This is the one rule for every kind of record in this document: Reservations, Leases, Occupancies, Deposits, Meters and readings, rates, Invoices, Payments, Receipts, allocations, Customer Credit, Refunds, Final Settlements.

## BR-PROP-003 — Real Dates and the Property's Time Zone

A business action uses the date on which the thing really happened. Nobody changes an old date to change a billing period, a balance, a rate, a Reservation's life, a Lease's length or a Deposit's outcome. A permitted correction of a date is kept in the history.

The Property's time zone is `Asia/Phnom_Penh`. Scheduled work and end-of-day work use it. A business date lasts to the end of that local day unless a rule says otherwise.

Replaces: BR-MONEY-013.

---

# 4. Unit Rules

## BR-UNIT-001 — Unit Type and Unit Number

A Unit has one Unit Type from the Settings list (today Studio, One bedroom, Two bedroom, Three bedroom). A Unit Type in use cannot be removed. A commercial Unit is not supported.

The Unit number is unique in the Property and cannot change after the Unit is made.

Replaces: BR-UNIT-003.
Decisions: DL-001, DL-074, DL-075, DL-078.

## BR-UNIT-002 — Unit Status

A Unit shows one status on a day: `VACANT`, `RESERVED`, `OCCUPIED`, `SHORT_STAY`, `CLEANING`, `UNDER_MAINTENANCE` or `OUT_OF_SERVICE`.

The status has two parts:

- **Who holds the Unit** is worked out from the dates of its records on the day asked (BR-UNIT-004). It is never stored and never set by hand. `OCCUPIED` comes from a Signed Lease whose Start Date has come or an open Occupancy. `SHORT_STAY` comes from a booked night or a checked-in guest. `RESERVED` comes from an Active Reservation.
- **The condition** is stored and set by staff: `VACANT`, `CLEANING`, `UNDER_MAINTENANCE` or `OUT_OF_SERVICE`.

When someone holds the Unit, the app shows who holds it and keeps the condition with it. For example, a Unit under maintenance while a Customer lives there shows `OCCUPIED`, and its condition stays Under maintenance. When nobody holds it, the app shows the condition.

A Unit with a Signed Lease that starts later shows its condition (normally `VACANT`) and the Lease Start Date until that day. The Lease still holds the Unit: it cannot be reserved or leased to someone else.

Before a Reservation, a Lease, a move-in or a short-stay booking is accepted, the app checks the real records: Active Reservations, Signed Leases, short-stay bookings, Occupancies and the condition.

Replaces: BR-UNIT-013.
Decisions: DL-150 to DL-159 (the status `SHORT_STAY`), DL-226, DL-241.

## BR-UNIT-004 — Who Holds a Unit

- An Active Reservation holds its Unit. A Unit has at most one Active Reservation. The Unit shows `RESERVED` while the Reservation holds it. The Reservation lets go only when it becomes Cancelled or Completed.
- A Unit has at most one Signed Lease for any day. A second Lease whose period overlaps a Signed Lease of the same Unit is refused. A Signed Lease holds its Unit from the signing: no Reservation and no other new Lease. The Unit shows `OCCUPIED` from the Lease Start Date, even before the move-in.
- A short-stay booking holds its nights, from the check-in day up to but not including the check-out day. A booking wins: a Reservation, a Lease draft or a signing that meets a booked night is refused and says why.

Replaces: BR-UNIT-005, BR-UNIT-006, BR-UNIT-007.
Decisions: DL-223, DL-225, DL-241.

## BR-UNIT-008 — After a Move-out or a Cancelled Reservation

After a move-out the Unit no longer shows `OCCUPIED`. It shows its condition, normally `CLEANING`. It shows `VACANT` only when staff set it ready to rent and no Reservation or Lease holds it.

When a Reservation becomes Cancelled (also by expiry), it lets go of the Unit. The Unit shows its condition again.

When a Lease is ended before any move-in, the Unit is let go without an Occupancy or a move-out. It shows its condition, or `CLEANING` when a user with the Unit right gives a reason.

After a short-stay check-out the condition becomes `CLEANING`.

Replaces: BR-UNIT-010, BR-UNIT-011.
Decisions: DL-241.

## BR-UNIT-009 — Under Maintenance and Out of Service

A Unit whose condition is `UNDER_MAINTENANCE` or `OUT_OF_SERVICE` is not offered for a new Reservation. Staff set only the condition: `VACANT`, `CLEANING`, `UNDER_MAINTENANCE` or `OUT_OF_SERVICE`. `RESERVED`, `OCCUPIED` and `SHORT_STAY` cannot be set by hand. The change is kept in the history and never overrides an Active Reservation, a Signed Lease or a short stay.

Replaces: BR-UNIT-012.
Decisions: DL-241.

## BR-UNIT-014 — Unit Cleaning Rate

Each Unit has a cleaning rate in USD cents. It is the source of the Unit cleaning charge at move-out (BR-MOVEOUT-013). A new rate never changes a charge that was issued.

Decisions: DL-065, DL-068.

Amended for Parking (owner, 2026-10-30, Parking Step 5): there is no cleaning charge when a customer leaves a Parking. The cleaning rates stay in the database and the API, but the Settings card "Move-out cleaning rates" and the "No cleaning rate" chip are hidden (`CLEANING_CHARGE`), so no rate is set on Parking.

## BR-UNIT-015 — Default Rent and Required Services

A Unit may have a default monthly Rent in USD cents and a list of required Services. A new Reservation or Lease draft for the Unit starts at the default Rent. Staff may agree a higher Rent. A Rent below the default needs a Manager or the Owner (`rent.below_default`) and a reason. A Lease draft made from a Reservation may keep the Rent agreed in the Reservation. Every new Lease draft for the Unit holds each required Service, and staff cannot remove one. A change of the default Rent or of the list never changes a Reservation or Lease that already exists.

Decisions: DL-110.

Amended for Parking (owner, 2026-10-29, Parking Step 3): a price change is a money action. Rent and Services asks a reason (1 to 500 characters, required) and the Parking's History shows who changed it, when, the old price, the new price and the reason; a New Parking's first price carries the fixed reason "Set with the new Parking". The permission stays Property Rental's (a Manager or the Owner of the Property).

Amended for Parking (owner, 2026-10-30, Parking Step 5): Required Services stay as in Property Rental and are empty by default; with none chosen, nothing is locked on a New Lease and nothing is refused.

---

# 5. Customer Rules

## BR-CUST-001 — One Customer Record for a Person

Customer is the one person record. There is no separate record for a Tenant, a former Tenant, a person living in a Unit, a Lease Signer or a Reservation Customer. Those are roles a Customer has through a Reservation, a Lease or an Occupancy.

## BR-CUST-002 — Use the Existing Customer

When the same person comes back, staff use the existing Customer record. Every Customer has an "ID number / Passport number". Two ID numbers are the same when they match after spaces and dashes are removed and capital letters are ignored. A Customer with the ID number of another Customer is refused. The same phone number or email address as another Customer shows a warning, and staff may still save.

Decisions: DL-071.

## BR-CUST-003 — Customer Details and History

Customer details are: legal name (required), date of birth, gender (Female or Male), nationality, ID number / Passport number (required and unique), phone, email, address and memo. A change of these details never changes what past Reservations, Leases, Occupancies, Payments and money records say.

Decisions: DL-071, DL-078.

---

# 6. Reservation Rules

## BR-RES-001 — A Reservation Is Optional

A Customer may reserve a Unit before signing its Lease. A Lease may also be signed with no Reservation, for a walk-in Customer. A walk-in Lease follows the same Unit rules (BR-UNIT-004).

A Reservation has exactly one Customer, who will be the Primary Tenant.

Replaces: BR-RES-002.

## BR-RES-003 — Reservation Status

A Reservation is `ACTIVE`, `CANCELLED` or `COMPLETED`. There is no "Expired" status.

- Active: the Reservation holds the Unit. Make Reservation receives the accepted first part of the Security Deposit on a Receipt in the same save step, and the Reservation is Active when that amount is received in full.
- Cancelled: it ended with no Lease. It can never become Active or Completed again.
- Completed: its Lease was signed. It can never expire.

Replaces: BR-RES-004.
Decisions: DL-077, DL-112.

## BR-RES-005 — Expiry Date

Every Active Reservation has an Expiry Date. The first Expiry Date is at most 21 days after the Reservation Date (the number comes from Settings; a new value is used only for new Reservations). A shorter time is allowed. The Reservation is valid to the end of the Expiry Date and is never cancelled earlier on that day.

Replaces: BR-RES-006, BR-RES-015.
Decisions: DL-075.

## BR-RES-007 — One Extension

A Reservation may be extended once, and only when it is Active, not expired, has fewer than 14 days left before its Expiry Date, was never extended, and an authorized user approves.

The extension adds at most 14 days (the number comes from Settings; a new value is used only for new Reservations). The days are counted from the old Expiry Date, not from the approval day. The Reservation stays Active and keeps holding the Unit.

Each extension is a Reservation Extension Notice that keeps the first Expiry Date, the Expiry Date before, the new Expiry Date, the approval time from the database clock, the user, and the reason or memo. The Expiry Date never changes without this Notice. A second extension is always refused.

Replaces: BR-RES-008, BR-RES-009, BR-RES-010, BR-RES-017, BR-RES-018, BR-RES-019.
Decisions: DL-075.

## BR-RES-011 — Automatic End on the Expiry Date

At the end of the Expiry Date, an Active Reservation that is not Completed is cancelled by the app with the reason `RESERVATION_EXPIRED`. The Unit is let go and the history stays. This is one step.

The automatic end never keeps the Security Deposit by itself. The Reservation is listed as waiting for a Deposit decision (BR-RES-021).

Replaces: BR-RES-016.

## BR-RES-012 — Cancelling a Reservation

Only an Active Reservation can be cancelled. Every cancellation records its reason and who caused it: the Customer, the expiry while the Property could give the Unit, or the Property that could not give the Unit as agreed. The cause must be the real one. A Property-side problem is never recorded as the Customer's cancellation or as an expiry.

Replaces: BR-RES-020.

## BR-RES-013 — Completed When the Lease Is Signed

A Reservation becomes Completed when its Lease is signed, in the same step. At that moment the Reservation must be Active and not expired. A Reservation gives at most one Lease: a Completed Reservation names exactly one Lease, a Cancelled Reservation none. The Security Deposit received in the Reservation goes on as the Lease's Security Deposit (BR-DEP-005). The move-in is recorded separately (BR-LEASE-015).

Replaces: BR-RES-014.

## BR-RES-021 — Who Caused the End Decides the Deposit

- The Customer cancels, or lets the Reservation expire while the Property could give the Unit: the Security Deposit received is not refundable. Waiting for the expiry does not avoid this rule. Keeping the Deposit is a draft by Staff and takes effect only when a user with `financial.approve` confirms it (BR-AUTH-010). The Deposit stays held until then.
- The Property cannot give the Unit as agreed: management first talks with the Customer, who may agree to wait or accept another Unit for a time. This creates no extra money rule. If the Customer says no and asks to cancel, the Reservation is cancelled and the Unit is let go at once, and all Security Deposit received is refunded. The Refund is a draft with a Refund method and a reference note, takes effect when a user with `financial.approve` confirms it, and always goes to the Reservation Customer.

Replaces: BR-RES-022, BR-DEP-015, BR-DEP-016, BR-DEP-017, BR-REFUND-004.

---

# 7. Security Deposit at the Reservation and at Signing

## BR-DEP-001 — The First Part of the Security Deposit

A Reservation becomes Active only after the accepted first part of the Security Deposit is received. There is no separate "Reservation Deposit": this money is Security Deposit.

The suggested first part is 20% of the agreed monthly Rent (the percent comes from Settings; a new value is used only for new Reservations). It is not a hard minimum. More than the suggestion needs no reason. Less than the suggestion needs a reason and authorized management. The app keeps the suggested amount, the accepted amount, who allowed it, when and why. The money received must equal the accepted amount.

Replaces: BR-DEP-002, BR-DEP-003.
Decisions: DL-075, DL-099.

## BR-DEP-004 — The Required Security Deposit of a Lease

Every Lease has a required Security Deposit. It is a Lease term, like the monthly Rent. The app shows three amounts: required, received, and still to pay (required minus received).

Every Lease draft that is not a renewal records the required amount with the Lease before any money is received, and the printed draft shows it. A draft made from a Reservation starts at the Reservation's amount. It may be changed with a reason, never below the money already received.

Decisions: DL-101.

## BR-DEP-005 — The Same Deposit Goes On Into the Lease

Security Deposit received in a Reservation is the same Security Deposit when the Lease is signed. It is not refunded and collected again, not made into a second Deposit, not converted, and never counted as rental income. If the draft records another required amount, the signing records one increase or decrease of the same Security Deposit, with the draft's reason.

Money received for a Deposit is linked from the Payment to the Deposit. This link is not an Invoice allocation, and a Deposit has no Invoice.

Decisions: DL-101.

## BR-DEP-006 — The Rest Is Received at Sign Lease

Sign Lease first receives, in full, the Security Deposit still to pay, the Pet Deposit of a pet kept from the start (BR-DEP-010) and the total of the Initial Rent Invoice. Then the Lease is signed. There is no part payment at signing, for a walk-in Lease and for a Lease from a Reservation alike. So all of it is paid before the move-in.

Example: Initial Rent $110 + Security Deposit $300 + Pet Deposit $100 = $510, received in one payment.

Decisions: DL-100, DL-234.

---

# 8. Lease Rules

## BR-LEASE-001 — Lease Status

A Lease is `DRAFTED`, `SIGNED`, `CANCELLED` or `TERMINATED`. A new Lease starts as Drafted. Only these changes are allowed:

```text
DRAFTED -> SIGNED
DRAFTED -> CANCELLED
SIGNED  -> TERMINATED
```

Only a Drafted Lease can be cancelled. A Signed Lease is never cancelled; when it ends, it is Terminated. A Drafted Lease cannot be terminated. A termination records the real termination date and the reason from the signed Lease or the business event. A Termination Notice alone does not change the status. Reaching the Lease End Date does not end the Lease by itself (BR-LEASE-017).

Replaces: BR-LEASE-002, BR-LEASE-003, BR-LEASE-004, BR-LEASE-005.

Old Leases only: a Lease signed before 27 October 2026 could have an unpaid Initial Rent Invoice and could be ended for it under Article 2.5. The app no longer has this step (DL-240): Sign Lease receives the Initial Rent and the Security Deposit first (DL-100), so no Lease can reach this case. A Lease that was ended this way before keeps its records as they are, and its Final Settlement follows its own rules.

## BR-LEASE-006 — One Primary Tenant, Who Signs

A Lease has exactly one Primary Tenant before it can be signed. The Primary Tenant is one of the Lease Signers, and the Lease cannot be signed until the Primary Tenant has signed. So a signed Lease always has at least one Signer.

Replaces: BR-LEASE-007, BR-LEASE-008.

## BR-LEASE-009 — Several Signers, One Whole Debt

A Lease may have several Signers. Each Signer is responsible for the whole unpaid amount of the Lease. The app never splits the debt between Signers: a Lease with two Signers that owes $800 owes $800, not $400 each. A Customer may sign a Lease without living in the Unit.

Replaces: BR-LEASE-010, BR-LEASE-011.

## BR-LEASE-012 — Lease Dates

A Lease has a Start Date and an End Date before it can be signed. The End Date is later than the Start Date and is the last day of a calendar month (example: Start Date 10 April 2026, End Date 31 May 2027). Any other End Date is refused. A Lease ends in the middle of a month only by early termination. The dates stay readable in the history after a renewal, a termination or a move-out.

The End Date is a limit of the contract. It is not an automatic month-by-month renewal and not an automatic end while people still live there. No Rent Invoice is made for a month after the End Date.

Replaces: BR-LEASE-013, BR-LEASE-031.
Decisions: DL-068, DL-069.

## BR-LEASE-014 — No Two Signed Leases at the Same Time

Before a Lease is signed, the app confirms that no other Signed Lease of the same Unit covers any of its days. A signed renewal follows the same rule (BR-UNIT-004).

---

# 9. Occupancy Rules

An Occupancy is the record of one person living in a Unit.

## BR-OCC-001 — Living There Is Not Signing

An Occupancy says who really lives in the Unit. A Lease Signer is who is responsible for the money. They are not the same. A person who lives in the Unit and did not sign owes nothing because of living there.

Replaces: BR-OCC-006.

## BR-OCC-002 — One Customer, One Lease, Real Dates

Every Occupancy names one Customer and belongs to one Lease. It starts when the real Move-in Date is recorded. The Move-out Date stays empty while the person lives there, is recorded when the person leaves, and is never before the Move-in Date. A correction of a date keeps the old value in the history.

A person may be added to a Lease draft or to a running Lease. Before the move-in the person is planned and moves in with the Lease. After it, the person's own Occupancy starts on their own real move-in date: not before the Lease's move-in date, not after the End Date, and not after today.

Replaces: BR-OCC-003, BR-OCC-004, BR-OCC-005, BR-OCC-007.
Decisions: DL-102.

## BR-OCC-009 — Closing an Occupancy

An Occupancy closes only when the person has really left and the real Move-out Date is recorded by the move-out step. The move-out of the whole Unit is done together with the Lease termination, the Unit status, the final Utilities and the Final Settlement. If people stay after the Lease End Date with no signed renewal, the Occupancy stays open and nothing is made up: no move-out, no month-by-month Lease, no extra Rent, no penalty (BR-LEASE-017).

One person may move out alone while the Lease runs, on their own real day:

- The Primary Tenant never moves out alone. They leave with the Lease.
- A person who signed nothing needs only the day and a reason.
- A Joint Signer needs every other Signer to agree. They stay a Signer and keep the responsibility until the Lease ends.
- The only Signer still living there cannot move out until the Lease's termination is complete.
- The day is on or after their Move-in Date, never after today, and never after the End Date.

Replaces: BR-OCC-008, BR-OCC-010.
Decisions: DL-111.

Amended for Parking (owner, 2026-10-30, Parking Step 4): on Parking the vehicle, not a person, takes the Occupancy (BR-VEH-001). The people rules above stay in the code behind the screen flag `PEOPLE_MOVE_IN` and are not used on Parking screens.

## BR-VEH-001 — One Vehicle at a Time (Parking)

Parking Step 4 (owner, 2026-10-30). A Lease of a Parking holds one vehicle at a time; the vehicle takes the Occupancy slot (hidden names stay `occupancy`, `occupant`).

- A vehicle is a record under a Customer: a type (car, motorbike, tuk-tuk, food cart) and a plate as typed, Khmer or Latin, 1 to 32 characters, never transliterated. A vehicle is corrected, never deleted. Photos and documents are not part of Step 4.
- A plate is matched without spaces, dashes, dots and case. Two vehicles may share a plate: the screen warns with the other owner's name ("Another vehicle has this plate"), and staff may still save. Nothing is merged.
- The vehicle that moves in belongs to the Primary Tenant or a Signer of the Lease (`VEHICLE_NOT_OF_LEASE`). It moves in through the Lease's move-in (same checks as the people move-in) and only when nothing is moved in on that Parking (`VEHICLE_SECOND`). A vehicle is parked under one Lease at a time (`VEHICLE_PARKED`).
- Each vehicle type parks only in its own kind of place, matched by the Parking Type code (Settings cannot change a code): Car → COVERED or UNCOVERED; Motorbike → MOTORBIKE; Tuk-tuk and food cart → TUK_TUK_FOOD_CART (`VEHICLE_TYPE`, checked at move-in and at Change vehicle). A Parking Type added later has a code the rule does not know: no vehicle type may move into it until the code is added to `app.vehicle_type_allowed`.
- Change vehicle ends the old vehicle's row and starts the new one on the change day, in one transaction; both rows stay (history); the Lease goes on and its version moves on; the History shows "Vehicle changed: {old plate} → {new plate}: {reason}". The new vehicle must differ from the old (`VEHICLE_SAME`); the day is on or after the old vehicle's move-in day, not after today and not after the End Date (`VEHICLE_DATE`); it needs a vehicle moved in on a running Lease (`VEHICLE_NONE_IN`).
- The only vehicle never moves out alone (`VEHICLE_ONLY_ONE` on the per-person move-out route): it leaves with a new vehicle (Change vehicle) or with the Lease (Termination and the Move-out page, which lists it by plate).

---

# 10. Signing and Move-in

## BR-LEASE-015 — Signing and Move-in

When a Lease is signed, in one step: its Reservation, if it has one, becomes Completed; the Lease holds the Unit, which shows `OCCUPIED` from the Lease Start Date; the Security Deposit stays with the Lease.

The move-in is recorded later, when it really happens. It needs: a Signed Lease; its Reservation, if any, Completed with this Lease; a Unit that is not `UNDER_MAINTENANCE` or `OUT_OF_SERVICE`; and a valid move-in date. The Occupancy then starts on the real Move-in Date (BR-OCC-002). The move-in does not change the Reservation or the Unit status. An unpaid Pet Deposit of a pet that came later never stops a move-in (BR-DEP-010).

Replaces: BR-LEASE-016.
Decisions: DL-100.

---

# 11. Pet Deposit Rules

## BR-DEP-007 — Only for an Approved Pet

A Pet Deposit is required only when a pet is approved under the signed Lease and the Lease terms ask for the Deposit. It is never required because the Customer might keep a pet one day.

Replaces: BR-DEP-008.

## BR-DEP-009 — Held Money for Pet Damage, Not a Limit

A Pet Deposit is money held for the Customer. It is not Rent, Service or Damage income. It is there first for damage a pet caused and for deep cleaning beyond the normal cleaning between tenants. It does not limit what the Customer owes: with a Pet Deposit of $200 and a valid pet cost of $500, the Customer still owes $300.

While the Lease runs, the Customer pays a valid pet charge directly. The Pet Deposit is not used up automatically and stays held, unless BR-DEP-011 allows its Refund.

## BR-DEP-010 — When the Pet Deposit Is Due

- A pet kept from the start: the draft Lease records the pet and its Pet Deposit amount, typed for each Lease. The Pet Deposit is received at Sign Lease, with the Security Deposit and the Initial Rent (BR-DEP-006). A draft with an approved pet and no Pet Deposit amount is not signed until the amount is recorded.
- A renewal takes no Pet Deposit at signing. A pet on a renewal follows the next point.
- A pet that comes later: the Customer must tell Property Management. If the pet is approved and the Lease asks for a Pet Deposit, it is paid before or when the pet starts to stay in the Unit. An unpaid Pet Deposit of this kind never stops the move-in.

Replaces: BR-DEP-020. Decisions: DL-234.

---

# 12. Deposits During the Lease

## BR-DEP-011 — Held During the Lease

The Security Deposit and the Pet Deposit are held while the Lease is Signed. They are two separate amounts, each with its own balance.

The Security Deposit is never refunded while the Lease is Signed.

The Pet Deposit stays held while an approved pet is kept. If the tenant stops keeping the pet for good during the Lease, the app records it and any valid pet damage or deep-cleaning cost is worked out. The Customer owes the full valid cost. When that is settled, what is left of the Pet Deposit may be refunded by a Refund with full history. The Lease does not have to end for this Refund.

Replaces: BR-DEP-012, BR-REFUND-013.

## BR-DEP-013 — A Deposit Never Pays an Ordinary Invoice

While the Lease runs, a Deposit cannot pay Rent, Utilities, Services or any other ordinary Invoice. The Customer cannot ask for it, and staff cannot do it. A Deposit pays Invoices and late-payment charges only in the Final Settlement, after the Lease has ended.

Keeping a Deposit under an approved non-refundable rule is its own record. It is not an Invoice allocation and is separate from the Final Settlement. This creates no new reason to keep a Deposit.

Replaces: BR-DEP-014, BR-SETTLE-010.

---

# 13. Rent Rules

### BR-RENT-015 — Monthly Rent From the Signed Lease, Billed in Advance

Rent is charged by the month. The monthly Rent is the amount in the signed Lease. Rent is billed in advance: each monthly Rent Invoice is for the coming calendar month, from its first day to its last day (the Invoice of 25 July is for 1 to 31 August).

Every Rent Invoice needs a Signed Lease that covers its period, with a Customer and a Unit that are valid for that Lease. The Rent line is worked out from the Rent in the Lease. Staff and automatic work never type another amount. A change after issue uses an Adjustment; it does not rewrite the Rent of the Lease.

The Rent changes only for future periods, by a new or renewed signed Lease with a start date for the new Rent. Periods before that date keep the old Rent. An issued Rent Invoice keeps its Rent, period, calculation, amount and date for ever.

Replaces: BR-RENT-001, BR-RENT-002, BR-RENT-003, BR-RENT-016, BR-RENT-017, BR-RENT-018, BR-RENT-021, BR-RENT-022, BR-RENT-023.

### BR-RENT-004 — One Rent Invoice for a Lease and a Month

A Lease has at most one Rent Invoice for a rental period. Periods of the same Lease never overlap: each billed day belongs to exactly one Rent Invoice. The Lease and the period are the key of the billing run. A missed run can be done later and a repeated run finds the Invoice that exists; it never makes a second one.

Replaces: BR-RENT-011, BR-RENT-019, BR-RENT-027.

### BR-RENT-005 — The Initial Rent Invoice

The Initial Rent Invoice is worked out from the Lease Start Date in the signed Lease, not from the real Move-in Date.

- Start Date on day 1 to 20: it covers the Start Date to the last day of that month.
- Start Date on day 21 or later: it covers the rest of the start month and the whole next month.

Only the part month is worked out by days (BR-RENT-006). Examples: Start Date 10 July covers 10 to 31 July. Start Date 27 July covers 27 July to 31 August, and the monthly billing goes on from 25 August for September. Start Date 20 September with a Rent of $300: $300 × 11/30 = $110.00, even if the tenant arrives on 25 September. The first and the monthly Rent periods never overlap.

### BR-RENT-006 — Part Months Use the Real Days

A part month is always worked out with the real number of days of that month (28, 29, 30 or 31). No fixed 30-day month, no average, no rounded daily rate:

```text
Monthly Rent × billed days (first and last day counted)
--------------------------------------------------------
real days in the month
```

Only the final result is rounded, to the nearest USD cent, half up. The same formula is used for every Customer and for the first and the last month. Every Rent line keeps the Lease, the monthly Rent, the period, the billed days, the days in the month, the calculation, the rounding and the final USD amount.

Replaces: BR-RENT-007, BR-RENT-013, BR-RENT-020, BR-RENT-028.

### BR-RENT-008 — Issue Day and Who Gets an Invoice

Monthly Rent Invoices are made by the app on the issue day of the month before, in the Property's time zone. The issue day comes from Settings (default the 25th; day 1 to 28, after the reading day). A new issue day starts with the next billing month.

A monthly Rent Invoice is made only for a Signed Lease that covers the billed period and is not terminated before the period starts. Never for a Drafted, Cancelled or Terminated Lease. Never for a period that the Initial Rent Invoice covers. Never for a period after the Lease End Date, unless a signed renewal covers it: people staying on does not create Rent or a new Lease by itself.

This does not stop an authorized user from billing a valid period before the termination date that was not billed yet.

Replaces: BR-RENT-010.
Decisions: DL-069, DL-075.

### BR-RENT-009 — Rent Due Dates

A monthly Rent Invoice is due on the Due Date day of the billed month. The day comes from Settings (default the 5th; day 1 to 28) and is the same for the monthly Utilities Invoice. A new day starts with the next billing month. The Due Date of an issued Invoice never changes.

The Initial Rent Invoice names the signed Lease. Its Due Date is the Lease Start Date plus five days. An authorized user may set another Due Date before issue, with a reason. It is received in full at Sign Lease (BR-DEP-006).

Decisions: DL-075, DL-100.

### BR-RENT-012 — The Last Month When the Tenant Leaves Early

When a Customer leaves before the Lease End Date and Property Management processes the early termination:

- The Rent of the calendar month of the real hand-back date is charged in full. It is not worked out by days.
- No Rent is made for a month after the real termination date.
- A hand-back before the 5th of a month is the one exception (the real hand-back date counts, not the notice date). The Customer pays only the days used, the same whether that month's Rent Invoice was paid or not:
  - the days used are the days from the 1st to the hand-back day. The hand-back day is a day used;
  - each line of that month's Rent Invoice, the Rent and its fixed Service lines, goes down to the days used, with the formula of BR-RENT-006. An authorized user does this in one step with a reason, and the app makes a credit Adjustment for each line;
  - what the Customer paid above the days used becomes Customer Credit. No Payment is changed;
  - what is not yet paid of the days used stays owed.
  - Example: Rent 800.00 USD, hand-back on 3 August (31 days). To pay: 800.00 × 3 ÷ 31 = 77.42 USD.
- When the hand-back is between the issue day and the end of a month, the next month's Rent Invoice that was already made has no day used. Unpaid: an authorized user makes the whole Invoice Void with a reason, with its fixed Service lines. Paid in full or in part: credit Adjustments take it down to zero, and what was paid becomes Customer Credit.

When another approved rule or the signed Lease asks for a last month by days, the period is from the first day of the month to the real termination date, with the formula of BR-RENT-006.

An Invoice made in advance for a period that is no longer valid is never edited or deleted. It is made Void or gets a credit Adjustment (BR-INV-021, BR-INV-046). The last Rent is worked out apart from the Deposits, Damage, Utilities and the Final Settlement.

Replaces: BR-RENT-014, BR-RENT-024, BR-RENT-025, BR-RENT-026, BR-RENT-030.
Decisions: DL-068, DL-069, DL-229.

---

# 14. Utilities Rules

### BR-UTIL-001 — Electricity and Water, From the Unit's Own Meter

The app bills two Utilities: Electricity and Water. Each is billed by itself, from its own Meter, its own readings and its own rate. A change to one never changes the bill of the other.

A Utility charge is the real use measured by the Meter of that Unit:

```text
Utility charge = use (from valid readings, or an approved broken-Meter estimate) × the rate
```

The final USD amount is rounded by the money rule (BR-MONEY-012). Staff never type another amount. Use may be estimated only for a Meter confirmed broken (BR-UTIL-023).

A Unit with no Meter of a kind gets no Utilities Invoice for that kind. A Unit with no Meter at all on the hand-back day needs no final reading and no final Utilities Invoice. A Lease has no separate Utilities tick. A Meter added later is billed from its first reading.

Replaces: BR-UTIL-002, BR-UTIL-003, BR-UTIL-004, BR-UTIL-032.
Decisions: DL-098.

### BR-UTIL-005 — Meters

A Unit has at most one working Meter for each Utility. A Meter serial number is unique among all Meters of the Property, whatever the Utility. Staff type the serial printed on the Meter, or a unique Property code (for example `EL-U101`) when none is printed. A replaced Meter keeps its serial in the history, and the serial is never used again.

A Meter found broken is recorded as broken, with the day it was found and what is wrong. From that day its readings are refused. It cannot be made working again: it must be replaced. The failed Meter, the new Meter, the failure date and the replacement date stay linked.

A replaced Meter and its readings stay in the history. Readings before the replacement belong to the old Meter, readings after it to the new Meter. Use is never worked out from the readings of two different Meters. A reading always stays with the Meter that gave it.

Replaces: BR-UTIL-006, BR-UTIL-007, BR-UTIL-008, BR-UTIL-013.
Decisions: DL-071, DL-104.

### BR-UTIL-009 — Readings

Readings of one Meter are in date order: a new reading has a later date than the last valid one. Before billing, readings are checked: dates in order, valid values, no negative use, no impossible use. A reading that fails the check is not used for billing.

Use is the difference between two readings, one after the other, of the same Meter. The period of use keeps its start and end dates and never overlaps another billed period of the same Unit and Utility.

A wrong reading may be corrected by an authorized user, before and after the Invoice is issued, whatever the Invoice's payment status. The correction keeps the old value, the new value, who, when and why. Before issue, the corrected reading is used for billing. After issue, the Invoice is not rewritten: the difference in money is posted as an Invoice Adjustment (BR-INV-021).

Replaces: BR-UTIL-010, BR-UTIL-011, BR-UTIL-012.

### BR-UTIL-014 — Rates

Electricity and Water each have their own rate. Every rate has a start date, and a new rate (the first one too) starts on a reading day after today. Until a rate of a kind is in force, no Utilities Invoice of that kind can be made.

A new rate is used only for use from its start date. The rate is chosen by the first day of the period of use (the day after the reading that starts it): the latest rate that had started on or before that day is used for the whole period, whatever day the Invoice is made. A period is never split because the rate changed inside it. For a broken-Meter estimate the first day is the first day of the estimated time.

A period that started before the first rate ever set of its kind has no older price. It uses that first rate, and its Invoice can be made only once that rate has started.

Customers are told about a new rate before its start date. The start date, not the telling date, decides which rate the app uses.

A new rate never changes an issued Utilities Invoice, charge, use or a finished period. Every Utilities line keeps the exact rate and the rate's start date that were used.

Replaces: BR-UTIL-015, BR-UTIL-016, BR-UTIL-017, BR-UTIL-029, BR-UTIL-030, BR-UTIL-031.
Decisions: DL-075, DL-105, DL-230.

### BR-UTIL-018 — No Double Billing, One Customer for a Period

The same Unit, Utility and period of use is billed once only. A period never mixes the use of two different responsible Customers. A move-in, a move-out or a change of who is responsible needs a valid reading (or an approved broken-Meter estimate) as the border.

Before the Lease Start Date, after cleaning and repair, staff record a valid reading of each Meter of the Unit with a proof reference, and turn Electricity and Water off. That reading is where the Customer's responsibility starts, whether the tenant arrives on the Start Date or later. If staff turn the Utilities on again before the hand-over, they record a new start reading. The Property pays for all use between the last tenant's final reading and the new Customer's start reading, and for any use when the tenant never moved in.

Replaces: BR-UTIL-019.

### BR-UTIL-020 — Monthly Billing and the Final Invoice

Electricity and Water are billed every month. Staff read every Meter every month, also in Vacant Units with Electricity and Water off. Each period keeps the dates of its start and end readings. The billing month is the calendar month of the end reading.

A Utilities Invoice is made only after its end reading is typed and valid, or an approved broken-Meter estimate is complete. A monthly Utilities Invoice is due on the Due Date day of the month after the billing month. The day comes from Settings (default the 5th; day 1 to 28), and a new day starts with the next billing month.

At move-out the final Utilities Invoice is made at once from the final readings or the approved estimate. It is due 7 days after issue (Lease Article 14.3). It never bills a period that the monthly run billed.

Replaces: BR-UTIL-021, BR-UTIL-022.
Decisions: DL-075.

### BR-UTIL-023 — Broken Meter Estimate

Use is estimated only when a Meter is confirmed broken and the real use of that time cannot be found. The estimate is marked as an estimate caused by a Meter failure. If staff simply could not read a Meter that is not confirmed broken, the Utility is not billed yet: the app waits for a real reading.

```text
Daily average  = total real use of the basis periods / total days of those periods
Estimated use  = daily average × days that could not be measured (first and last day counted)
```

- The basis is the last three whole periods of real use before the failure, for the same Unit and Utility. With only one or two whole periods, all of them are used.
- With no whole period at all, the app waits for one whole future period of real use of the same Unit and Utility, and uses that. Until then the estimate and its charge stay open, and the reason for the wait is kept.
- The unmeasured time starts when use could no longer be measured and ends on the last day before the new Meter gives valid readings. No day is counted both in the estimate and in the new Meter's real use.
- The average is always one division over all basis periods. Averages of separately rounded periods are never averaged. Another Unit is never used as the basis, and no number is made up.

Replaces: BR-UTIL-024, BR-UTIL-025, BR-UTIL-026, BR-UTIL-027, BR-UTIL-028.

---

# 15. Service Rules

A Service is a fixed monthly charge set by management, such as Trash Collection. It is not measured like a Utility.

### BR-SVC-001 — Services Come From Settings and the Lease

Services are added in Settings by the Owner or a user with Settings access. Each has an English and a Khmer name, a Service type and a monthly rate. A Service type is "Only one per Lease" or "One or more per Lease". A type cannot be changed to "Only one per Lease" while a Lease holds two Services of that type, and a type that has Services cannot be removed. Trash Collection is ticked by default on a new Lease.

Only a Service that is set up in Settings, ticked on the Lease, active and really given for the billed period is billed. Nobody makes a Service or a Service charge by typing it on an Invoice. The amount is the Service's fixed monthly rate. Staff never type another amount; a correction after issue uses an Adjustment. The amount does not depend on Utilities use, on the number of people, or on the number of days in a full month. Service charges are separate from Rent, Utilities and Deposits.

The one-time Unit cleaning charge at move-out (BR-MOVEOUT-013) is not a Service.

Replaces: BR-SVC-002, BR-SVC-004, BR-SVC-014, BR-SVC-015.
Decisions: DL-074, DL-075, DL-097.

### BR-SVC-003 — Billed in Advance on the Rent Invoice

Each Service of a Lease is billed monthly in advance, as its own line on the Rent Invoice. It adds to the Invoice total and is never counted as Rent. There is normally no separate Service Invoice. A Service follows Rent for its periods, its issue day and its Due Date (BR-RENT-008, BR-RENT-009).

The first Service period is like the first Rent period (BR-RENT-005): for a Lease Start Date on day 1 to 20, the Start Date to the end of that month; for day 21 or later, the rest of the start month by days plus the whole next month. It is a line on the Initial Rent Invoice. Monthly billing goes on with the first whole month after it, and no period is billed twice.

A month is billed when the Lease and the Service's approval cover the whole month, at the rate in force on the first billed day. A Service that covers only part of a month, or has no rate, stops that Rent Invoice until it is corrected.

Each Service line keeps the Service, its category, its rate, its period, the calculation when by days, and the final amount. A line for a start on day 21 or later keeps both parts readable.

Replaces: BR-SVC-009, BR-SVC-010, BR-SVC-011, BR-SVC-012.
Decisions: DL-075, DL-097.

### BR-SVC-005 — A New Service Rate

A new Service rate starts on the first day of a later month and is used only for periods that start on or after that day. Issued Invoices keep the old rate, and a new Service name shows only on new Invoices. The history of each Service stays readable: what it is, its approval, when it was active, and its rates.

Replaces: BR-SVC-006, BR-SVC-007, BR-SVC-008.
Decisions: DL-075.

### BR-SVC-013 — The Last Month

A Service is not worked out by days just because the people leave during a month. The last Service charge follows the Lease and the Rent rule for the last month (BR-RENT-012): at a hand-back before the 5th, the fixed Service lines of that month's Rent Invoice go down to the days used with the Rent line; when next month's unpaid Rent Invoice is made Void, its Service lines go with it.

---

# 16. Invoice Rules

### BR-INV-002 — Every Amount Owed Is an Invoice, With One Customer

Every amount a Customer owes for something the Property gave or charged is an Invoice. The late-payment charge is an Invoice too (BR-LATE-001); only a charge made before 14 November 2026 is still a debt of its own (BR-LATE-004). A Security Deposit or a Pet Deposit is money held for the Customer. It is never an Invoice and never an Invoice type.

Every Invoice belongs to exactly one Customer, from the day it is made and for ever. A Customer may have many Invoices.

An Invoice names a Lease only when what is owed comes from that Lease. Then the Invoice Customer must be a Customer responsible under that Lease, and the Unit, period, Rent and Services must agree with the Lease. Naming one Invoice Customer does not take away the responsibility of the other Signers. An Invoice with no Lease still needs an approved business event. A Lease is never added or removed to get around a check for the source, double billing, payment split or settlement. The same debt is never billed once with a Lease and once without.

Replaces: BR-INV-001, BR-INV-007, BR-INV-036, BR-INV-037, BR-INV-038.

### BR-INV-017 — Number, Date, Period and Amount

Each Invoice has its own number (INV, the 2-digit year, a running number: `INV260001`), given when it is issued and never used again. It has an Invoice Date. It has a billing period where that fits (Rent, Electricity, Water, Services); a one-time charge such as Damage may have none. The Invoice amount is the total of its charges when it is issued. These values are part of the history from the issue on.

Replaces: BR-INV-003, BR-INV-004, BR-INV-005.
Decisions: DL-071, DL-118.

### BR-INV-016 — Invoice Type, Line Category and Source

Every Invoice has one main category and every line has one category: Rent, Utilities, Service Charges, Damage Charges or Miscellaneous Charges. An Invoice holds lines of another category only where a rule says so: the Service lines on a Rent Invoice. Each line keeps its own category, source, rate, calculation and amount, and a Service line is never counted as Rent. The category of an Invoice or a line never changes after issue.

Every Invoice keeps one Invoice type. The type is set when the Invoice is made and never changes. It is the type shown to people and used by Settings › Invoice types. There are seven types: Rent (Rent and its Services), Utilities, Short stay, Products (an Invoice from a signed Quotation), Damage (short-stay damage too), Late-payment, and Other charges (the Unit cleaning charge at move-out, an extra charge after move-out, money to pay back after a wrong Refund). Only the app makes an Invoice of the type Late-payment, for a late-payment charge (BR-LATE-001); no person can. Settings lists the type with late payment No, and that cannot be changed.

Every Invoice comes from a real business event:

- Rent and its Service lines: the signed Lease (BR-RENT-015, BR-SVC-001).
- Utilities: valid readings or an approved estimate, times the rate (BR-UTIL-001).
- Products: a signed Quotation. Each item is a line with a whole quantity and a unit price in US cents, and its amount is exactly quantity times unit price, with no rounding. An Invoice made with the old Create Invoice step holds 1 to 20 items, with one reason and one approval for all.
- Damage: a recorded finding of the Move-out inspection, or a Repair Quotation the Customer agreed (BR-MOVEOUT-006).
- Other charges: their own rule (BR-MOVEOUT-013 and the correction rules).

Replaces: BR-INV-006, BR-INV-008, BR-INV-039, BR-INV-040, BR-INV-041, BR-INV-042.
Decisions: DL-020, DL-103, DL-123, DL-221, DL-231.

### BR-INV-015 — Invoice Status

An Invoice is `DRAFT`, `UNPAID`, `PARTIALLY_PAID`, `PAID` or `VOID`. Only these changes are allowed:

```text
DRAFT           -> UNPAID, VOID
UNPAID          -> PARTIALLY_PAID, PAID, VOID
PARTIALLY_PAID  -> PAID, UNPAID, VOID
PAID            -> PARTIALLY_PAID, UNPAID
VOID            -> (the end)
```

- Draft: not yet owed. It is not counted in any balance and cannot be late. It may be changed before issue with no reason asked. A Draft made by a person that is not wanted may be deleted, with no reason, because nobody ever owed it; one record in the audit log says who deleted it and when. A Draft that another record uses, or that the app made by itself, is not deleted: it becomes Void with a reason. The history of an Invoice starts when it is issued (DL-239). Example: a Draft for a key copy, 2 × $15.00, is changed to 3 × $15.00 and saved; or it is deleted and leaves the list.
- Unpaid: issued. From then on it is an official document. Scheduled billing (Rent with its Services, Utilities) may make and issue an Invoice in one step. A charge made by a person may stay a Draft for review.
- Partly paid and Paid are worked out, never typed: from the active payment allocations, Customer Credit uses and Final Settlement Deposit uses, line by line. An Invoice is Paid only when every line is at zero. Example: $300 on the Rent line of a $500 Rent plus $10 Service Invoice leaves $210, Partly paid. A late-payment charge never changes the status of its Invoice.
- A status goes back (Paid to Partly paid or Unpaid, Partly paid to Unpaid) only as the result of an authorized reversal or correction. Never by hand, and never to show a Refund.

Replaces: BR-INV-009, BR-INV-010, BR-INV-011, BR-INV-012, BR-INV-013, BR-INV-043, BR-INV-050.

### BR-INV-018 — Due Date

Every issued Invoice has exactly one Due Date. A Draft may have none. Lines have no Due Date of their own, and a debit Adjustment uses the Due Date of its Invoice. The Due Date is fixed once the Invoice is issued.

- Monthly Rent and monthly Utilities: BR-RENT-009, BR-UTIL-020. Initial Rent: BR-RENT-009.
- A one-time Damage or Other charge made by authorized staff: the issue date plus the Settings "days after issue" (1 to 90, default 7). A new value is used at once for Invoices issued after the change.
- The Unit cleaning charge at move-out, Damage charges at move-out and the final Utilities Invoice: 7 days after issue (Lease Article 14.3), whatever the setting says.
- An authorized user may set another Due Date before issue, with a reason; who and when are kept.

Replaces: BR-INV-049.
Decisions: DL-075.

### BR-INV-020 — Never Changed After Issue

After issue, the amount, date, period, category, number, Due Date, Customer and Lease of an Invoice are never changed, deleted, reused or made again under the same number. A later change of Rent, a rate, a Service, a Customer, a Lease or a Meter never changes an issued Invoice: it shows the facts of its issue day.

A correction needs the right, a reason, who and when. It keeps the old values and is linked to what it corrects. Allocations, Credit uses, Refunds and Adjustments that hang on an Invoice are undone only by their own steps; nothing is deleted, cut loose or moved to make a correction possible. Every Invoice event is kept in the history: made, adjusted, made Void, status change, Due Date change, allocation change. A Void Invoice stays in the records.

Replaces: BR-INV-019, BR-INV-023, BR-INV-025, BR-INV-030, BR-INV-031, BR-INV-032, BR-INV-033, BR-INV-034, BR-INV-035, BR-INV-047, BR-INV-048.

### BR-INV-021 — Adjustment

A correction of the amount of an issued Invoice is a debit or credit Adjustment, linked to the Invoice. The first amount and the Lease terms stay as they were. An Adjustment is recorded on one line and keeps the Invoice, the source, the amount, the reason, the approval, who and when. It follows the Customer and the Lease (or no Lease) of what it corrects.

- A debit Adjustment is allowed only while its line still has an amount unpaid. On a fully paid line it is refused; an amount that was missed there is billed on a new one-time Invoice. If a reversal brings the line back above zero, a debit Adjustment is allowed again.
- The new Invoice for a missed amount keeps the Invoice type of the Invoice where the amount was missed: missed Rent is billed as Rent, missed Utilities as Utilities. It names that Invoice. It is for the same Customer and the same Lease (or no Lease). It is a one-time charge with its own Due Date (BR-INV-018), and the late-payment switch of its type is the one it follows. The income report and the General Ledger count it as what was missed, in the month of the new Invoice.
- A credit Adjustment is allowed on any line of an issued Invoice that is not Void. Credit above what the line still owes becomes Customer Credit of the Invoice Customer (BR-CREDIT-002).

Decisions: DL-232.

Replaces: BR-INV-044, BR-INV-045.

### BR-INV-046 — Void

Void is only for an Invoice that should not exist at all. It is not the way to correct an amount. Only an authorized user can make an Invoice Void, with a reason. Void ends the Invoice for good and keeps its record.

An Invoice that has received money is not made Void directly: its allocations, Credit uses, Refunds, Adjustments and other links are first undone by their own steps.

Replaces: BR-INV-014, BR-INV-022, BR-INV-024.

### BR-INV-026 — No Double Billing

The app refuses an Invoice that bills the same thing twice:

- Rent: the same Lease and rental period (BR-RENT-004).
- Utilities: the same Unit, Utility and period of use (BR-UTIL-018).
- Services: the same Lease and Service, for the same or an overlapping time; the monthly run skips what the Initial Rent Invoice covered.

The source facts decide what "the same" is. Changing the Customer or the Lease on the Invoice does not get around this rule.

Replaces: BR-INV-027, BR-INV-028, BR-INV-029.

---

# 17. Late Payment

### BR-INV-051 — When an Invoice Is Late

The Due Date is the last day to pay on time. Money received on the Due Date is on time. In the Property's time zone, an amount still unpaid is late from the next day. There are no extra days of grace.

Whether an Invoice can get a late-payment charge is set by its Invoice type in Settings › Invoice types (late payment Yes or No). Switching a type needs a reason and keeps history. A type set to No gets no charge.

Decisions: DL-118, DL-221.

### BR-LATE-001 — One Automatic Late-payment Charge

At 00:00 Property time on the first day after the Due Date, the app adds the late-payment charge by itself. No person decides.

```text
Late-payment charge = amount of the Invoice still unpaid at that moment × the Settings rate
```

- The rate is a whole percent from 0 to 10, set in Settings (default 10%). Settings refuse more than 10% and refuse a part of a percent such as 7.5%: the signed Lease allows at most 10% (Article 2.3). A new rate starts with the next billing month and is used for charges added after the change.
- The charge is worked out once, on the whole Invoice, not line by line. Money already paid is not charged. The result is rounded half up to the cent. A charge that rounds to zero is not written.
- One charge for an Invoice, for ever. It never repeats, never grows, and money paid later does not change it. A Late-payment Invoice never gets a late-payment charge.
- No charge for: an Invoice that was already late on the day the automatic charge first ran; an Invoice issued after its charge moment; an Invoice of a Lease whose Final Settlement is closed. A missed day is caught up by the next run with the amount unpaid at that day's 00:00.
- An Adjustment recorded before the charge is counted in it. A debit Adjustment after the charge is allowed and not counted. A credit Adjustment never changes the charge.

The charge is an Invoice of the type Late-payment. The app makes and issues it in the same step. It has one line, "Late-payment charge of Invoice" with the number of the Invoice that was late, and it names that Invoice. It is for the same Customer and the same Lease. Its Due Date is the day it is made: it is owed at once. A tenant with a Tenant-bot link gets it by Telegram, like every issued Invoice. It is part of what the Customer owes, and it never changes the amount, the lines, the balance or the status of the Invoice that was late.

Example: Rent of $800.00 is unpaid after 5 November. At 00:00 on 6 November the app makes a Late-payment Invoice of $80.00 with the Due Date 6 November.

The Invoice that was late cannot be made Void while its Late-payment Invoice stands: first the Late-payment Invoice is made Void (BR-INV-046).

Replaces: BR-INV-052, BR-INV-053, BR-INV-054, BR-INV-055, BR-LATE-002, BR-LATE-003, BR-LATE-006, BR-RENT-029.
Decisions: DL-075, DL-076, DL-085, DL-118, DL-226, DL-233.

### BR-LATE-004 — Balance and Correction of a Late-payment Charge

A Late-payment Invoice is paid and settled like every Invoice: by a Payment, by Customer Credit, or by a Deposit in the Final Settlement. With no name from the payer, it is paid in the order of its own Due Date (BR-PAY-021).

It is corrected like every Invoice, by the people who may adjust an Invoice or make it Void (the right "Approve financial records": by default the Owner and a Manager), only after the Customer complains that it is wrong because of a staff mistake, with a reason:

- Lower it: a credit Adjustment (BR-INV-021). Money paid above the new amount becomes Customer Credit at once (BR-CREDIT-002).
- Cancel it: Void when it has received no money and has no Adjustment (BR-INV-046). If money was received, a credit Adjustment takes it down to zero and what was paid becomes Customer Credit.
- The amount only goes down. A debit Adjustment on a Late-payment Invoice is refused.

The first amount and every change stay in the history. A cancelled Late-payment Invoice is not made again: there is one charge for an Invoice, for ever (BR-LATE-001).

Charges made before 14 November 2026 are not Invoices. Each stays as it was made, a debt of its own that is owed at once with no Due Date. What is still owed is its first amount minus valid payment allocations and Customer Credit uses. The Owner or a Manager (`late_payment.charge_correction`) may lower or cancel such a charge after a staff mistake, with one of three reasons ("Staff recorded the payment on the wrong Invoice", "Paid on time but recorded late", "Other staff mistake") and a "What happened" text. Money paid above the new amount becomes Customer Credit at once, and Credit that was used returns to its Credit. A charge that a Deposit paid cannot be corrected this way. After the Lease's Final Settlement is closed, a charge is corrected only by a correction after settlement (BR-SETTLE-012).

Replaces: BR-LATE-005.
Decisions: DL-076, DL-086, DL-087, DL-233.

---

# 18. Payment and Receipt Rules

### BR-PAY-001 — One Payer, and a Lease When It Helps

Every Payment names exactly one payer Customer. A Customer may make many Payments. A Payment may name a Lease, as background only: the Lease does not decide what the Payment pays. A Payment before the move-in or after the Lease ended may have no Lease.

Another person who pays for a tenant does not become responsible under the Lease by paying. When that person names a Lease or an Invoice, it is kept as what the payer wanted; it does not make the debt theirs.

Replaces: BR-PAY-002.

### BR-PAY-003 — A Payment Is Money Received

A Payment records that the Property received money. By itself it pays no Invoice. An Invoice is paid only by a payment allocation, a Customer Credit use or a Deposit use in the Final Settlement.

Payment, Receipt, allocation, Payment Reversal, Customer Credit and Refund are separate records. Giving money back is a Refund, linked to its source. A Refund never changes the amount of the Payment, never wipes its allocations, is never a negative Payment, and there is no "Refunded" Payment status.

Replaces: BR-PAY-013, BR-RECEIPT-006.

### BR-PAY-004 — Number and Date

A Payment has one Receipt, and the Payment Number is that Receipt's number: `RCP`, the 2-digit year of the confirmation date in the Property's time, and a 4-digit running number that starts again at 0001 each year (`RCP260001`). After 9999 it grows to 5 digits. It is never used again and never changed.

The Payment Date is the day the Property received the money. For a riel Payment, the moment the receipt is confirmed is also the moment the rate is chosen and kept (BR-MONEY-007).

Replaces: BR-PAY-005, BR-RECEIPT-002.
Decisions: DL-071.

### BR-PAY-006 — Payment Methods and Currency

Payment Methods are added, edited and turned off in Settings. Each method says whether it needs a reference. A method used on a Receipt is never deleted, only turned off. At least one method stays on, and only a method that is on can be chosen. A Payment is in USD or in riel (BR-MONEY-001).

The method, the currency and, for riel, every rate value recorded on a Payment stay as they were, also when a method is renamed or turned off later.

Replaces: BR-PAY-007.
Decisions: DL-075.

### BR-PAY-008 — Payment Status

A Payment is `RECEIVED` or `REVERSED`. A new Payment is Received. The only change is Received to Reversed, and Reversed is the end.

"Partly used" and "fully used" are not statuses. They are worked out from the active allocations against the Payment's USD value, and the Payment stays Received.

Replaces: BR-PAY-009, BR-PAY-010, BR-PAY-011, BR-PAY-014.

### BR-PAY-012 — Reversing a Payment

A Payment becomes Reversed only by an authorized Payment Reversal linked to it. Before that, every active allocation and any Customer Credit that came from the Payment is reversed by its own step. A completed Refund from the Payment stops the reversal, unless an authorized correction first solves that Refund without rewriting history. The reversal works out again the balance and status of every Invoice it touched. The reversed Payment stays in the records.

### BR-PAY-017 — What a Payment Keeps

A Payment is never deleted and its amount is never changed. It keeps for ever: its number, the Customer, the Lease if any, the Payment Date, the method, the currency and amount received, the USD value, the riel amount and exact rate facts when in riel, its status, and what the payer wanted when they said so.

Every Payment event is kept in the history: received, status change, Receipt issued or printed again, allocation change, reversal, Refund.

Replaces: BR-PAY-015, BR-PAY-016, BR-PAY-018.

### BR-RECEIPT-001 — The Receipt

A Receipt is the numbered paper for the Customer that says money was received under one Payment. It does not replace the Payment, make a Payment, or pay anything by itself.

A Receipt may show its number, the Payment, the Customer, the Payment Date, the method, the currency and amount received, the USD value, the riel details, what was paid (Invoice lines, a late-payment charge, a Deposit), who issued it and when. Every amount on it comes from the Payment and its linked records.

Printing a Receipt again keeps the same number, Payment and Customer. It is not new money and makes no second Payment. Who printed it again and when is kept. A correction of a Payment or an allocation uses its own step and never rewrites the Receipt's history.

Replaces: BR-RECEIPT-003, BR-RECEIPT-004, BR-RECEIPT-005.

---

# 19. Payment Allocation Rules

A payment allocation says which part of a Payment pays which debt.

## BR-PAY-019 — An Allocation Is Its Own Record

An allocation links part of the USD value of one Received Payment to one debt of the Customer: a line of an issued Invoice, or a late-payment charge. It rewrites no other record.

Money received for a Deposit is the Payment-to-Deposit link of BR-DEP-005. It is not an allocation. Customer Credit, Payment money not yet used, Refunds and Deposits are separate balances.

## BR-PAY-020 — The App Proposes, Staff Confirm

The app works out a proposal and ticks it when the amount is typed. Pressing Receive payment is the staff confirmation. One command saves the Payment and its allocations together. There is no "match later" while the Customer owes anything.

Decisions: DL-029, DL-077.

## BR-PAY-021 — The Order of the Proposal

When the payer names nothing, the proposal for the payer's own Payment is:

1. Invoices by oldest Due Date first, until the Payment is used up or everything is paid.
2. Invoices with the same Due Date: by issue order, then by a stable Invoice number order.
3. A Late-payment Invoice has its own Due Date, the day it was made, and takes its place by it like every Invoice. A late-payment charge made before 14 November 2026 (BR-LATE-004) comes right after its own Invoice, before newer Invoices; the charge of an Invoice that is already paid keeps the place of that Invoice's Due Date.
4. Inside one Rent Invoice: the Rent line first, then its Service lines. On an Invoice of typed items: from the top down.

The order inside an Invoice never changes the order between Invoices. Example: on $500 Rent plus $10 Trash Collection, $300 goes to Rent; $505 pays Rent in full and $5 of the Service; $510 pays both.

A Payment that names an Invoice or a charge, and another person's Payment, get no automatic ticks for other debts.

Replaces: BR-PAY-022, BR-PAY-023, BR-PAY-036, BR-PAY-038, BR-PAY-040.
Decisions: DL-076, DL-088, DL-103.

## BR-PAY-024 — The Customer May Name What to Pay

When the Customer names a valid Invoice, a line of an Invoice or a late-payment charge, staff may change the ticks to that and confirm. What the Customer named, what was paid, the amount, who and when are kept. An amount named for a late-payment charge pays no more than the charge still owes; the rest follows the Customer's other wish or the normal proposal.

Replaces: BR-PAY-037.

## BR-PAY-025 — Whose Invoices a Payment May Pay

A Customer's own Payment may pay that Customer's open Invoices, across their Leases, and their Invoices with no Lease.

Another person's Payment pays only the Invoice or Lease that person named. It is never spread over other debts of the payer or of anyone else. The payer does not become the Invoice Customer or a Signer. A Signer who is not the Invoice Customer pays this way too; this does not change the Signer's responsibility.

The one exception is the confirmed move of a Payment from the wrong Unit's Invoice (BR-PAY-042).

Replaces: BR-PAY-026.

## BR-PAY-027 — Limits of an Allocation

An allocation is above zero. It is not more than the Payment still has free, and not more than the debt still owes. No line, Invoice or late-payment charge ever goes below zero. Money above what is owed becomes Customer Credit or waits on the Payment (BR-PAY-030).

Replaces: BR-PAY-028.

## BR-PAY-029 — History and Reversal of an Allocation

Every allocation keeps its Payment, its target, the amount, what the Customer named if anything, the proposal, the time and the user who confirmed. A correction is an Allocation Reversal linked to it. The reversal works out again the balances and statuses of the line, the Invoice and the Customer. An allocation is never deleted or overwritten.

## BR-PAY-030 — Money Above Everything Owed

Extra money exists only when everything the Customer owes is paid and part of the Payment is still free, or when nothing is owed.

At Receive payment the extra money becomes the payer's Customer Credit at once, in the same step, with no question to the payer. Example: the Customer owes $300.00 and pays $350.00; $300.00 pays the Invoices and $50.00 becomes Customer Credit. The Credit names the Payment and the amount. The Customer may ask for a Refund of that Credit any day (BR-CREDIT-011). Credit pays a later Invoice only when staff use it (BR-CREDIT-005).

If the app cannot check at that moment that nothing else is owed (for example, another person is changing Invoices), the Payment is still saved and the extra money waits on the Receipt. Money that waits on a Receipt, including Receipts made before 15 November 2026, stays as it was: Property Management asks the payer to keep it as Customer Credit or get it back. The choice, the amount, the time and the user are kept.

- Credit: only the amount the payer agrees to keep becomes Customer Credit, linked to the Payment and owned by the payer.
- Refund: the Refund is linked to the Payment and its extra money.

Either way that amount can no longer be allocated from the Payment, so it cannot be used twice. The amount of the Payment and its allocations never change.

Free Payment money or Customer Credit never causes a future Rent Invoice to be made before its issue day.

Replaces: BR-PAY-031, BR-PAY-032, BR-PAY-033, BR-PAY-034, BR-PAY-035.
Decisions: DL-077, DL-235.

## BR-PAY-039 — Unpaid Rent Means the Rent Line

Allocations lower the line they name, and the lines add up to what the Invoice owes (BR-INV-015). For the unpaid-Rent rules (BR-LEASE-026) only the Rent line counts, after valid allocations and Credit uses. An unpaid Service alone is never treated as unpaid Rent.

## BR-PAY-042 — A Payment on the Wrong Unit's Invoice

When a Payment was put by mistake on another Unit's Invoice (meant for Unit 201, paid on Unit 203), the money is not refunded to the payer. Staff record a draft that says in words that both Customers confirmed, who confirmed, the date and how. When a user with `financial.approve` confirms it, the wrong allocation is reversed and the same Payment is allocated to the right Invoice.

The first Invoice is unpaid again, and the late-payment and unpaid-Rent rules apply to it from then on; earlier records do not change. If the wrong allocation already became Customer Credit or a Refund, those are reversed first, or the move is stopped. The Payment (amount, date, Receipt) never changes, and no Customer Credit moves between Customers.

After the Lease's Final Settlement is closed, an allocation the settlement relied on is moved only by a correction of that settlement (BR-SETTLE-012). The details of that correction are in the decision log.

Decisions: DL-031, DL-068, DL-069.

---

# 20. Customer Credit Rules

## BR-CREDIT-001 — Credit Is Kept in USD, Apart From Deposits

Customer Credit is a USD amount. There is no riel Credit balance. When Credit comes from a riel Payment, the riel amount, the exact rate of the Payment's confirmation and the USD value stay with the source; the Credit itself is in USD.

Customer Credit is not a Security Deposit and not a Pet Deposit. It is never shown as one, pooled with one or quietly turned into one. It is money the Property holds for a Customer, not a supplier bill.

Replaces: BR-CREDIT-004, BR-CREDIT-010, BR-CREDIT-013.

## BR-CREDIT-002 — How Credit Starts

- From extra money at Receive payment: at once, with no question to the payer (BR-PAY-030). The Credit names the Payment, the amount kept and the payer.
- From extra money that waits on a Receipt: only after the payer agrees that the Property keeps the named amount (BR-PAY-030). The Credit names the Payment, the amount kept, the payer and the agreement.
- From a credit Adjustment: paid value that a credit Adjustment gives back becomes Credit at once, with no question to the payer. It belongs to the Customer named on the Lease and the Invoice, even when another person paid, and a Refund of it goes to that Customer. The Credit names the Adjustment and the allocation or Credit use that was given back. The same holds for value given back when a paid late-payment charge is corrected.

Replaces: BR-CREDIT-003, BR-CREDIT-014.
Decisions: DL-064, DL-068, DL-069, DL-235.

## BR-CREDIT-005 — Using Credit

Credit pays only a valid open debt of the same Customer: an issued Invoice or a late-payment charge, across that Customer's Leases. It never moves to another Customer. No Invoice is made, or made early, only to use up Credit.

A Credit use is its own record, confirmed by staff. It names the Credit, the target and its line, the amount, what the Customer named if anything, the proposal, who and when. On a Rent Invoice with nothing named, the proposal is Rent first, then Services (BR-PAY-021). On issue day, "One tap" fills in the use of the Customer's Credit for the new Invoice, and staff confirm it.

A Credit use is above zero, not more than the Credit has, and not more than the debt owes. No line, Invoice, charge or Credit goes below zero.

When a correction puts Credit back on the line it came from, it goes back on that same line, labelled "put back by a correction". Staff cannot pick that label for an ordinary Credit use. The details are in the decision log.

Replaces: BR-CREDIT-006, BR-CREDIT-007, BR-CREDIT-008.
Decisions: DL-077.

## BR-CREDIT-009 — Credit History and Reversal

The first Credit and every use stay for ever. A correction is a reversal linked to what it corrects, and it works out the balances and statuses again. How a Credit started, was used, reversed and refunded, what is left, and its source values can always be read back.

Replaces: BR-CREDIT-012.

## BR-CREDIT-011 — Refund of Credit

Credit is refunded only in USD, in exact cents (BR-REFUND-005). Its source link stays, with any riel Payment and its rate.

Money that a correction of a closed Final Settlement brought back into a Credit leaves only through a correction of that Final Settlement, so that the Customer's open debt on the Lease is paid first. The ordinary Credit Refund refuses that money. Other money in the Credit stays refundable the ordinary way.

Decisions: DL-032, DL-060.

---

# 21. Customer Account View

## BR-LEDGER-001 — One Account View for Each Customer

Each Customer has one account view: the full money history in time order and where the Customer stands today. It is built from the real records and can always be built again from them. It never replaces, merges or rewrites Invoices, Payments, allocations, Credit, Adjustments, Refunds, Deposits, late-payment charges, reversals or Final Settlements, and it is never a second set of numbers.

It shows, for one Customer: what was charged and why; Payments and what they paid; Credit made, free, used, reversed, refunded; Refunds and Adjustments; Security Deposit and Pet Deposit received, held, used, kept, refunded; late-payment charges and what they still owe; what is unpaid and of what it is made; the total owed today; and the free Credit.

The total owed is the open Invoices plus the open late-payment charges. Credit, free Payment money and Deposits are shown apart and never lower a debt without an authorized use. Each event keeps its time, source, Customer, amount and effect. Corrections and reversals are shown as their own events.

The view uses plain words: Amount charged, Payment received, Credit, Refund, Outstanding balance. It needs no bookkeeping words. The General Ledger is a separate part of the app and is not this view.

Replaces: BR-LEDGER-002, BR-LEDGER-003, BR-LEDGER-004, BR-LEDGER-005, BR-LEDGER-006, BR-LEDGER-007.
Decisions: DL-116, DL-117.

---

# 22. Refund Rules

## BR-REFUND-001 — A Refund Is Its Own Record With One Source

A Refund is money going out. It names one source and the amount that source still has: extra money of a Payment, Customer Credit, or a refundable Deposit. The Refund is above zero and not more than its source still has.

A Refund never rewrites, deletes or lowers its source: not the amount of the Payment, not the first amount of the Credit, not the Deposit received. The whole chain from the money received through allocation, Credit, Deposit use and Refund can always be read back.

Replaces: BR-REFUND-002, BR-REFUND-003, BR-REFUND-010, BR-REFUND-012.

## BR-REFUND-005 — Every Refund Is in USD

Every Refund is paid and recorded in USD, in exact cents. Riel is a way to pay in, never a way to refund. Extra money from a riel Payment is refunded from the USD value that is left; it is never worked out again from riel or with a new rate. The riel amount and the rate of the source stay for the history. Money that comes back from a Refund is counted in exact USD cents too.

Replaces: BR-REFUND-006, BR-REFUND-008.
Decisions: DL-060.

## BR-REFUND-009 — Approval, Reason and Refund Method

Every Refund needs the right approval and keeps its reason, who, when, who receives it and its source. A Refund is a draft and takes effect when an approver confirms it (BR-AUTH-010).

Every Refund records a Refund method and a reference note. Refund methods are their own Settings list, not the Payment Methods list, starting with Cash and Bank transfer. For cash, the note says who took the money. Only the Owner and users with Settings access (`settings.manage`) add a method or turn one off or on. At least one stays on. A method turned off is kept for old Refunds and cannot be used for a new one. Each change is kept in the history.

The app sets no Refund deadline and blocks nothing. While a Deposit Refund is not made, a reminder shows "Refund due by": 7 days after the later of the final inspection and the final Utilities Invoice (the Lease's 7-day promise).

Replaces: BR-REFUND-014.
Decisions: DL-068, DL-069, DL-073, DL-080, DL-089.

## BR-REFUND-011 — Refund History

A Refund and any correction linked to it keep their full history. A Refund is never deleted or rewritten. This adds no Refund status and no new right to a Refund.

## BR-REFUND-015 — Who Receives a Deposit Refund

A Deposit Refund goes to the Primary Tenant, unless all Lease Signers agree in writing that another Signer receives it. The agreement is recorded as text.

Decisions: DL-069.

---

# 23. Lease End and Termination Rules

## BR-LEASE-017 — Nothing Is Automatic at the Lease End Date

At the Lease End Date the Lease does not go on month by month. No new Lease, extra Rent, fee, penalty or other charge is made automatically. The Lease also does not become Terminated by itself while the Customer still lives in the Unit.

By that date the Lease should have a signed renewal, or go through termination and move-out. If the Customer stays with no signed renewal, Property Management must act as the signed Lease says. Until then the Lease and the Occupancies stay recorded as they really are.

Replaces: BR-LEASE-018, BR-LEASE-019, BR-MOVEOUT-007, BR-MOVEOUT-008, BR-MOVEOUT-009.

## BR-LEASE-020 — Leaving Early

A Customer has no general right to end a Lease before its End Date. If a Customer leaves early and Property Management processes the early termination:

- the Lease ends on the real hand-back (move-out) date, not on a notice date;
- the Rent of that calendar month is charged in full; a hand-back before the 5th follows BR-RENT-012;
- every issued Invoice, paid or unpaid, open late-payment charges, Utilities, Services and the move-out charges with the Unit cleaning charge stay owed;
- the whole Security Deposit is kept and is never used for what the Customer owes (BR-DEP-023);
- there is no separate early-termination fee;
- no Rent is made for later months.

Replaces: BR-LEASE-021, BR-MOVEOUT-010.
Decisions: DL-068, DL-069.

## BR-LEASE-022 — Notice and the Real Termination Date

Where a Termination Notice is needed, its content and its notice time come from the signed Lease. Recording a Notice does not change the Lease status and does not make up a Move-out Date. A Signed Lease becomes Terminated only by the authorized step, on the real termination date. That date and its reason stay readable in the history.

Replaces: BR-LEASE-023.

## BR-LEASE-024 — Ending a Lease for a Violation

A violation, and the right to end the Lease for it, must come from the signed Lease. The app never makes up a violation, a penalty, a fee, a reason to keep a Deposit or a right to end a Lease. Ending a Lease is always a step by an authorized user with its reason recorded. Nothing is automatic.

- Property Management sends at least three written warning letters before ending a Lease for a violation. Each letter names the violation, the date, the Lease article and how it was sent. A hidden pet follows this rule too.
- A serious breach, meaning a crime or a danger to people or the building, may end the Lease at once, with no warning letters.
- For unpaid Rent the letters are the three notices of day 10, day 20 and day 25, then the termination letter of day 30 (BR-LEASE-026). No other letters are needed.
- Article 2.5 of the standard Lease (Security Deposit or Initial Rent not fully paid within five days after the Lease Start Date): the app has no step for it, because Sign Lease receives this money first (BR-LEASE-001, DL-240).

Replaces: BR-LEASE-025.
Decisions: DL-064, DL-070, DL-073, DL-237.

## BR-LEASE-026 — Unpaid Rent: Notices on Day 10, 20 and 25, Termination Letter on Day 30

This rule is only for monthly Rent Invoices. The Initial Rent Invoice never starts it.

- Days are counted in the Property's time zone from a fixed day 1: the first day of the billed month. Day N is day 1 plus N − 1 days. For August Rent, day 10 is 10 August, day 20 is 20 August, day 25 is 25 August and day 30 is 30 August. For February Rent in a normal year, day 30 is 2 March.
- No notice comes before the Due Date has passed. The Due Date in Settings may be day 1 to 28. With a Due Date on the 15th, the day-10 notice waits for the 16th. The late-payment charge follows its own rule and does not change this count.
- Only the Rent line counts, after valid allocations, Credit uses and Adjustments. An unpaid Service alone does not count.
- There are four steps while the Rent is still unpaid:

| Step | Day | Who sends it |
| --- | --- | --- |
| Notice 1 | Day 10 | The app, by itself |
| Notice 2 | Day 20 | The app, by itself |
| Notice 3 (the last notice) | Day 25 | The app, by itself |
| Termination letter | Day 30 | A Manager or the Owner |

- The three notices. For a tenant with a live Tenant-bot link, the app records the notice and sends it by Telegram by itself, from 09:00 in the Property's time zone, only when the Rent is still unpaid at that moment. It sends them in order and at most one a day, so after a gap it catches up one notice each day. For this tenant the Telegram message is the notice; staff give a paper copy when the tenant asks.
- A tenant with no Tenant-bot link gets nothing by itself. The app alerts staff the same day, on Home and on the Letters screen. Staff print the letter, give it, and record it with how it was given and its number. The paper letter is the official copy.
- Paying the Rent in full stops the next notices. A part payment does not stop them. The history of the late Invoice, the notices and the Payment stays.
- The termination letter is never sent by the app by itself. On day 30, when the Rent is still unpaid and the three notices are given, the app has it ready and alerts. A user with the right to end a Lease (a Manager or the Owner) sends it. The app records it as the Serious Nonpayment Default of that Rent, together with the Termination Notice and its end date. A linked tenant also gets it by Telegram. The paper letter is the official copy.
- The termination letter waits for the three notices. When day 30 has passed and a notice is missing, staff give the missing notices first.
- The termination letter itself changes nothing: the Lease stays Signed, the Unit stays Occupied, no Occupancy ends, and no move-out or Final Settlement is made. Ending the Lease is a separate step by a Manager or the Owner, on or after the end date written in the letter (BR-LEASE-024).
- Each notice and the termination letter is a kept record: Customer, Lease, the Rent Invoice, Due Date, Rent unpaid at that time, the time, who (or the app by itself), the type, how it was sent, the document number, and what followed.
- Paying after the termination letter does not erase it or an ending that management already started. The app does not decide whether that ending goes on. Management decides, and everything is kept in the history.
- A case recorded under an older way of counting keeps its values. A case that holds only the day-20 notice from before this rule needs notices 1 and 3 before its termination letter.

Replaces: BR-LEASE-027, BR-LEASE-028, BR-LEASE-029, BR-LEASE-030.
Decisions: DL-073, DL-217, DL-237.

---

# 24. Move-out Rules

## BR-MOVEOUT-001 — The Move-out

A move-out records the real day the people left. It is never taken from the Lease End Date or from a notice date alone. It is done together with the authorized Lease termination, and both dates must be the real ones. Every open Occupancy that ends gets its real Move-out Date.

After the move-out the Unit no longer shows `OCCUPIED`. It shows its condition, normally `CLEANING`. It is not free just because the Lease ended (BR-UNIT-008).

Replaces: BR-MOVEOUT-002, BR-MOVEOUT-003, BR-MOVEOUT-004.

## BR-MOVEOUT-005 — Final Readings and the Final Utilities Invoice

Final readings are taken and checked where possible. A broken Meter uses only the approved estimate (BR-UTIL-023). A reading that is simply missing delays the charge. When the final readings or the estimate are recorded, the app makes the final Utilities Invoice at once (BR-UTIL-020).

When the tenant never moved in, the Customer gets no Utilities charge and no Damage charge. The Property pays for any use.

## BR-MOVEOUT-006 — Inspection and Damage Charges

The inspection results and every valid Rent, Utilities, Service, Damage, Other charge and Adjustment that belongs in the Final Settlement are made final from their own sources. This rule makes no new charge or fee.

A Damage charge is made only from a recorded damage finding: of the Move-out inspection, of the Check report of a Repair Check, or of a Joint Inspection. A manager or staff member with the Damage-charge right types the amount with a reason and a proof reference. Each finding is billed once at most. The charge must match the finding's Customer, Lease and Unit. An inspection alone makes no charge. There is no standard damage fee, and a Pet Deposit is never kept automatically. The Due Date follows BR-INV-018.

During a Lease, a repair the Customer caused first gets a Repair Quotation (valid 7 days). The Customer's agreement is recorded with its date and how. The Damage charge is exactly the agreed price; a higher cost needs a new agreed Quotation; a refusal makes no charge. A repair marked "Urgent: repair now" with a reason by the Owner or a Manager starts without agreement, and its Damage charge is the real cost with proof.

After the Final Settlement is closed, no Move-out inspection of that Lease is replaced. Damage found later is a new, separate inspection, and it is billed only by a correction after settlement (BR-SETTLE-012).

Decisions: DL-115.

## BR-MOVEOUT-013 — Unit Cleaning Charge

At every move-out, whatever the reason for leaving, the Customer is charged the Unit's cleaning rate (BR-UNIT-014) as a one-time charge. It is due 7 days after issue (BR-INV-018). An authorized user may lower it with a credit Adjustment and a reason. There is no cleaning charge when the Customer never moved in.

Decisions: DL-065, DL-068, DL-069.

## BR-MOVEOUT-011 — Move-out History and the Final Settlement

The Lease, the Occupancies, the Unit status, the readings, the inspection, the notices, the approvals, the real dates and any corrections of a move-out are kept in the history.

The move-out and the termination feed the Final Settlement. The Final Settlement does not close until every valid charge is final, with any broken-Meter estimate that is still waiting.

Replaces: BR-MOVEOUT-012.

Amended for Parking (owner, 2026-10-30, Parking Step 5): no cleaning charge at move-out on Parking. Migration `20270407_257` turns off the one settlement check `CLEANING_CHARGE_MISSING` in `app.final_settlement_preview` (it became `IF false AND ...`), so a move-out with no cleaning rate and no cleaning charge can close. The move-out step 4 shows no cleaning section or "Add cleaning charge" button (`CLEANING_CHARGE`). `app.record_unit_cleaning_charge`, the rates and the Invoice line stay; a cleaning charge that already exists counts as a normal debt of the Settlement.

---

# 25. Keeping and Returning Deposits

## BR-DEP-018 — Keeping a Deposit Is Its Own Record

Every time a Deposit is kept (not refundable), there is a record linked to the Deposit. It lowers the refundable balance and never deletes, rewrites or renames the money received. It keeps the amount, the Deposit kind, the reason, the Reservation, Lease or event behind it, the date, the approval and the history. It is a draft by Staff and takes effect when an approver confirms it (BR-AUTH-010).

A kept Deposit is never put on an ordinary Invoice to make the numbers fit, and it is shown as kept, never as a Payment or as part of a Deposit that is still held. Only the cases in these rules allow keeping a Deposit.

Replaces: BR-DEP-019, BR-SETTLE-014.

## BR-DEP-021 — A Pet That Was Not Told

When a pet is found that was not told or not allowed, Property Management tells the Customer of the violation. A Pet Deposit is required only if the pet is approved and the Lease asks for it. The Lease is not ended at once or automatically because the pet was found, and no extra pet penalty exists.

If the Customer refuses or fails to pay the required Pet Deposit, the Lease may be ended only under the signed Lease and after the three warning letters (BR-LEASE-024). If it is ended for that, the Security Deposit and the Pet Deposit are both kept.

Replaces: BR-DEP-022.

## BR-DEP-023 — A Kept Security Deposit Is Kept Whole

When the Security Deposit is kept, the whole Deposit is kept, and it is never used to pay what the Customer owes. Unpaid charges stay as the Customer's debt. Rent already paid for the hand-back month is not refunded.

The Security Deposit is kept when:

- the Customer chooses to leave before the End Date (BR-LEASE-020);
- the Lease is ended for a violation, a pet rule or another rule, or for a serious breach;
- the Lease is ended after the day-30 unpaid-Rent default;
- an old Lease was ended under Article 2.5 before the app took out that step (BR-LEASE-001, DL-240), whether or not the Customer moved in.

It is not kept, and pays the open debt with the rest refunded (BR-SETTLE-004), at a normal Lease end, when the Property ends the Lease with notice (Article 15.4), and when both sides agree to end it early.

When a confirmed keeping is reversed, the Deposit is held again. At the Final Settlement it then pays the open debt and the rest is refunded, unless a new keeping draft is confirmed.

Replaces: BR-DEP-026.
Decisions: DL-032, DL-064, DL-068, DL-069, DL-070, DL-073.

## BR-DEP-024 — The Pet Deposit When a Lease Ends

Leaving early does not make the Pet Deposit non-refundable by itself. It is followed apart through the Final Settlement.

- Ended for a pet-rule violation: both Deposits are kept (BR-DEP-021).
- Ended under Article 2.5, for another violation or a serious breach, or after the day-30 default: the Pet Deposit pays valid pet damage first and the rest is refunded. It pays other debt only when the Customer chooses it, recorded as text (who, the date, how) with the staff reason.
- A normal Lease end and leaving early: the Pet Deposit pays pet damage first. For other debt see BR-SETTLE-004.

Replaces: BR-DEP-027.
Decisions: DL-013, DL-068, DL-069, DL-073.

## BR-DEP-025 — What Is Left Is Refunded

After the Final Settlement, whatever is left of the Security Deposit and of the Pet Deposit is refunded. Each Deposit kind has its own Refund, so each can be followed.

Replaces: BR-REFUND-007.

---

# 26. Final Settlement Rules

```text
Make every valid charge final
        ↓
Use Customer Credit
        ↓
Management chooses and confirms each Deposit use
        ↓
Work out what the Customer still owes, or what Deposit is left
        ↓
Refund the Deposit that is left
```

## BR-SETTLE-001 — One Final Settlement for Each Ended Lease

Every Terminated Lease gets exactly one Final Settlement. It names the Lease, the responsible Customers, the real termination and Move-out dates, the open Invoices, the open late-payment charges, the Customer Credit, the Security Deposit, the Pet Deposit, the final Utilities, the Adjustments and the other linked money events of that Lease.

Before any Credit or Deposit is used, every valid debt that belongs in the settlement is made final from its own source. The Unit cleaning charge and open late-payment charges are part of it. No new fee, penalty or kind of charge is made up for a settlement.

The settlement starts as waiting. It does not close until the Lease is Terminated and every valid final charge is known. A missing reading, or a broken-Meter estimate that waits for a future period, keeps it open. It is also not recorded or confirmed while a draft that could change its numbers waits (a Refund, a keeping of a Deposit, a Payment move, a returned Payment, an Adjustment reversal, or a correction of another settlement that touches the same money). That draft is first confirmed, rejected or taken back.

Replaces: BR-SETTLE-002, BR-SETTLE-003, BR-SETTLE-011.
Decisions: DL-068, DL-069.

## BR-SETTLE-004 — The Order: Credit, Security Deposit, Pet Deposit

1. Customer Credit is used first, by Credit uses of their own.
2. Then authorized management chooses and confirms each Deposit use on a valid settlement debt. The Security Deposit may pay any valid debt of the settlement that is left. A Security Deposit that was kept (BR-DEP-023) is not there to be used.
3. The Pet Deposit is first for valid pet damage and deep cleaning. It does not limit what the Customer owes for them. For other debt, it pays only what is still open after the Security Deposit has been used: when the Customer chooses it, or by authorized staff with a reason when the Customer will not pay. A user with `financial.approve` confirms it. When the Lease was ended under Article 2.5, for a violation other than a pet rule, for a serious breach or after the day-30 default, only the Customer's choice allows it (BR-DEP-024).

Every Deposit use keeps its Deposit, the debt it pays, the amount, who, when, why and the approval. The app never uses a Deposit automatically because a balance exists, and it sets no other order between the two Deposits.

Replaces: BR-SETTLE-005, BR-SETTLE-006, BR-SETTLE-017.
Decisions: DL-013, DL-032, DL-068.

## BR-SETTLE-007 — What Is Left After the Settlement

An amount still unpaid stays as debt on the Primary Tenant's account. The debts themselves do not change. Debt on an Invoice issued to another Signer stays on that Signer's account, because the Customer of an Invoice never changes; the Lease's Deposits may pay it in the order above.

After the Final Settlement is closed, the Owner may write off an unpaid Invoice line or late-payment charge, with a reason.

What is left of each Deposit is refunded, each by its own Refund (BR-DEP-025). The Customer does not get Deposit money back while a valid settlement debt is unpaid and that Deposit was approved to pay it: every such use is recorded first.

Replaces: BR-SETTLE-008, BR-SETTLE-016.
Decisions: DL-068, DL-069, DL-117.

## BR-SETTLE-012 — Closed Once; Later Fixes Are Corrections

A Final Settlement closes once. After that its numbers, order, calculations, Deposit outcomes, Refunds and result are fixed for ever, and it is never opened again.

A later fix is a new correction linked to the settlement, with a reason. There is no time limit. Staff prepare it (the Final Settlement preparer right) and only a user with `financial.approve` confirms it. The kinds are: an extra charge, a charge reduction, a Refund, a returned Payment, an Adjustment reversal, a reversal of a kept Deposit, a Payment move, a late-payment charge correction, a pet classification correction of a Damage line, and a Refund of money a correction brought back. Each kind has its own detailed rules in the decision log.

After the closure, an allocation, a Credit use or a kept Deposit that the settlement relied on is never reversed outside a correction of that settlement. The debt the settlement saw as paid stays paid. Allocations and Credit uses made after the closure are reversed the ordinary way, so the Customer can still pay what is left. No late-payment charge is added to an Invoice of a Lease whose Final Settlement is closed.

Replaces: BR-SETTLE-013.
Decisions: DL-068, DL-069.

## BR-SETTLE-009 — Settlement History

Every Credit use, Pet Deposit use, Security Deposit use, kept Deposit, amount left and Refund is its own linked record. The settlement keeps every input, order choice, calculation, approval, who, when, source link and result, so it can always be worked out again.

Replaces: BR-SETTLE-015.

---

# 27. Money and Currency Rules

## BR-MONEY-001 — USD Is the Base; Payments in USD or Riel

USD is the Property's currency. Every money record is in USD. Invoices and Customer Credit are in USD and shown in USD. A Payment may be received in USD or in riel (KHR) only. A riel Payment does not make its Invoice a two-currency Invoice. When riel is chosen, the screen may show the riel amount for the USD debt at the app's rate. Every Refund is in USD (BR-REFUND-005).

Replaces: BR-MONEY-002.
Decisions: DL-060.

## BR-MONEY-003 — Money Is Counted Exactly

Money is worked out in whole cents (or exact decimals), never with floating-point numbers.

## BR-MONEY-004 — The Riel Rate

The outside rate is the ABA Bank USD/KHR Sell rate. No other source is approved.

```text
App rate = ABA Sell rate, rounded up to the next whole riel
Example:   ABA sells 1 USD for 4,076.25 riel, so the app rate is 4,077 riel for 1 USD
```

There is no mark-up (DL-228, owner 13 Nov 2026: "Always 0%, no setting"). It is not a Settings value. If the ABA rate cannot be read automatically, an authorized user may type the ABA Sell rate by hand. The app then uses the same rounding. Typing by hand never skips the formula.

Riel Payments saved before 13 Nov 2026 used ABA Sell rate × 1.005 (a 0.5% mark-up). They keep that rate; it is never worked out again.

Replaces: BR-MONEY-005, BR-MONEY-006, BR-MONEY-008.

## BR-MONEY-007 — The Rate of a Payment Is Kept

The app rate is chosen and kept at the moment the receipt of the Payment is confirmed. A later rate never changes that Payment. The riel amount is worked out with the rounded app rate and rounded up to the next whole riel (not half up).

Every riel Payment keeps: the ABA rate, its mark-up (0, or 0.5% for Payments saved before DL-228), the app rate, the date and time, whether the rate was read automatically or typed, the USD value and the riel amount. When KHQR or another bank channel gives its own real conversion, amount or rate, that real information is kept and never rewritten with another rate.

Replaces: BR-MONEY-009, BR-MONEY-010, BR-MONEY-011.

## BR-MONEY-012 — Part Months and Rounding

Where a rule asks for a part month:

```text
Monthly amount × billed days (first and last day counted)
----------------------------------------------------------
real days in that month
```

The daily result is not rounded. The final USD amount is rounded to the nearest cent, half up, unless a rule says otherwise.

---

# 28. History Rules

## BR-AUDIT-006 — Every Change Is Kept, for Ever

Every change that matters keeps: who did it, what was done, the date and time, the reason, the state or value before, the state or value after, and the record it touched.

This holds for every kind of record in this document: Reservations (start, extension, expiry, cancellation and who caused it, Unit let go); Leases and Occupancies (signing, renewal, Notices, warning letters, termination, move-in, move-out, corrections, Unit changes); Meters, readings, failures, replacements and estimates with the data and calculation used; Rent, Utilities, Service and riel rates with their start dates; Invoices, Adjustments, Void and late-payment charges with their corrections; Payments, what the payer wanted, allocations, reversals, Credit, Receipts and Refunds; Deposits by kind, with the suggested and accepted amounts; Final Settlements and their corrections; and the Customer account view, which must always agree with the real records.

History is for ever. It is never deleted, quietly rewritten, or replaced by the latest value only.

Replaces: BR-AUDIT-001, BR-AUDIT-002, BR-AUDIT-004, BR-AUDIT-005, BR-AUDIT-007, BR-AUDIT-008, BR-AUDIT-009, BR-AUDIT-010, BR-AUDIT-011.

## BR-AUDIT-003 — Times Come From the Database Clock

A Signer's signature time, the Lease signing time and the Lease termination time are the database's own time at the moment of the step. No browser or device clock sets them, so a device clock cannot refuse a signing or make a signature look earlier. The real termination date stays a date typed by staff.

Each unpaid-Rent notice and the termination letter (the Serious Nonpayment Default) keep their Rent Invoice, the day count, the amount at that time, the time, who, the letter, any later payment, and what management did next.

---

# 29. Rights Rules

## BR-AUTH-001 — Every Action Needs a Signed-in User With the Right

Every action that this document calls "authorized" needs a signed-in user who has the right for that action. Rights are given by role (Owner, Manager, Staff) and can be ticked for a user in Settings. The Security Model (`008_SECURITY_MODEL.md`) holds the full list and must not weaken these rules.

Decisions: DL-074.

## BR-AUTH-002 — Actions That Need More Than Staff

| Action | Who, by default |
| --- | --- |
| Extend a Reservation; correct Reservation dates or reasons; class a cancellation | Manager or Owner |
| Accept a first Security Deposit below the suggestion | Authorized management, with a reason |
| Sign a Lease; terminate a Lease; Termination Notices and warning letters; correct a move-in or move-out date | Manager or Owner |
| Record an unpaid-Rent notice (day 10, 20, 25) by hand | Authorized user. For a tenant with a Tenant-bot link the app records and sends it by itself (BR-LEASE-026) |
| Send the day-30 termination letter and act on it | A user with the right to end a Lease. Time passing alone gives no right to end a Lease |
| Type the ABA rate by hand | Authorized user, only when the rate cannot be read automatically |
| Estimate use for a broken Meter, and correct it | Authorized user. A reading that is only missing can never be made into an estimate |
| Issue a charge by hand, adjust an issued Invoice, set a Due Date by hand, make an Invoice Void | Authorized user, with a reason |
| Change or delete a Draft Invoice made by a person | A user who may make Invoices, with no reason. An issued Invoice is never deleted (BR-INV-015) |
| Lower or cancel a Late-payment Invoice, or a late-payment charge made before 14 November 2026 | Owner or Manager by default (BR-LATE-004) |
| Receive a Payment, confirm its allocations, reverse an allocation or a Payment | Authorized user. A proposal by the app is never the confirmation |
| Make Credit from extra money that waits on a Receipt, use Credit | Authorized user; the payer's choice is kept. Extra money at Receive payment becomes Credit at once (BR-PAY-030) |
| Refunds, Deposit use, keeping a Deposit, a Payment move, the Final Settlement and its corrections | Draft by Staff, confirmed by `financial.approve` (BR-AUTH-010) |

Every one of these is kept in the history with its reason.

Replaces: BR-AUTH-003, BR-AUTH-004, BR-AUTH-005, BR-AUTH-006, BR-AUTH-007, BR-AUTH-008, BR-AUTH-009.
Decisions: DL-068, DL-069, DL-076, DL-080.

## BR-AUTH-010 — Money Drafts and the Approver

The Final Settlement, Deposit use, keeping a Deposit, Refunds, the move of a Payment from the wrong Invoice and corrections after settlement are first recorded as drafts. Staff may record a draft. Only a user with `financial.approve` (the Owner, a Manager, or another user given it) confirms it. A draft changes no money until it is confirmed.

Decisions: DL-068, DL-069.

---

# 30. Scope and Conformance

- This document and `001_DOMAIN_MODEL.md` are the source for business rules. The database, API, screen, test, security and deployment documents follow them. Nobody reads a rule in a way that makes a new status, charge, fee, penalty, currency, rate source, way to estimate, right to end a Lease, right to a Refund or right of a user. A new rule needs the owner's decision.
- Every `BR-` number is unique and stable.
- The original money records stay for ever. Corrections are linked Adjustments, reversals, uses, Deposit outcomes, Credit or Refunds, so every balance and every past fact can be worked out again.
- The General Ledger, Supplier bills, Expenses and short stays (Daily and Weekly rent) are parts of the app with their own decisions in the decision log (DL-116, DL-117, DL-150 to DL-159, DL-190 to DL-199, DL-223 to DL-225). They are not repeated here.

---

# Appendix A. Where Every Version 1.0 Rule Number Went

A number in bold is still a rule heading. Every other number now lives in the rule named beside it.

| Version 1.0 number | Now in |
| --- | --- |
| **BR-PROP-001** | BR-PROP-001 — One Property |
| **BR-PROP-002** | BR-PROP-002 — No Record Is Deleted |
| **BR-PROP-003** | BR-PROP-003 — Real Dates and the Property's Time Zone |
| **BR-UNIT-001** | BR-UNIT-001 — Unit Type and Unit Number |
| **BR-UNIT-002** | BR-UNIT-002 — Unit Status |
| BR-UNIT-003 | BR-UNIT-001 — Unit Type and Unit Number |
| **BR-UNIT-004** | BR-UNIT-004 — Who Holds a Unit |
| BR-UNIT-005 | BR-UNIT-004 — Who Holds a Unit |
| BR-UNIT-006 | BR-UNIT-004 — Who Holds a Unit |
| BR-UNIT-007 | BR-UNIT-004 — Who Holds a Unit |
| **BR-UNIT-008** | BR-UNIT-008 — After a Move-out or a Cancelled Reservation |
| **BR-UNIT-009** | BR-UNIT-009 — Under Maintenance and Out of Service |
| BR-UNIT-010 | BR-UNIT-008 — After a Move-out or a Cancelled Reservation |
| BR-UNIT-011 | BR-UNIT-008 — After a Move-out or a Cancelled Reservation |
| BR-UNIT-012 | BR-UNIT-009 — Under Maintenance and Out of Service |
| BR-UNIT-013 | BR-UNIT-002 — Unit Status |
| **BR-UNIT-014** | BR-UNIT-014 — Unit Cleaning Rate |
| **BR-UNIT-015** | BR-UNIT-015 — Default Rent and Required Services |
| **BR-CUST-001** | BR-CUST-001 — One Customer Record for a Person |
| **BR-CUST-002** | BR-CUST-002 — Use the Existing Customer |
| **BR-CUST-003** | BR-CUST-003 — Customer Details and History |
| **BR-RES-001** | BR-RES-001 — A Reservation Is Optional |
| BR-RES-002 | BR-RES-001 — A Reservation Is Optional |
| **BR-RES-003** | BR-RES-003 — Reservation Status |
| BR-RES-004 | BR-RES-003 — Reservation Status |
| **BR-RES-005** | BR-RES-005 — Expiry Date |
| BR-RES-006 | BR-RES-005 — Expiry Date |
| **BR-RES-007** | BR-RES-007 — One Extension |
| BR-RES-008 | BR-RES-007 — One Extension |
| BR-RES-009 | BR-RES-007 — One Extension |
| BR-RES-010 | BR-RES-007 — One Extension |
| **BR-RES-011** | BR-RES-011 — Automatic End on the Expiry Date |
| **BR-RES-012** | BR-RES-012 — Cancelling a Reservation |
| **BR-RES-013** | BR-RES-013 — Completed When the Lease Is Signed |
| BR-RES-014 | BR-RES-013 — Completed When the Lease Is Signed |
| BR-RES-015 | BR-RES-005 — Expiry Date |
| BR-RES-016 | BR-RES-011 — Automatic End on the Expiry Date |
| BR-RES-017 | BR-RES-007 — One Extension |
| BR-RES-018 | BR-RES-007 — One Extension |
| BR-RES-019 | BR-RES-007 — One Extension |
| BR-RES-020 | BR-RES-012 — Cancelling a Reservation |
| **BR-RES-021** | BR-RES-021 — Who Caused the End Decides the Deposit |
| BR-RES-022 | BR-RES-021 — Who Caused the End Decides the Deposit |
| **BR-DEP-001** | BR-DEP-001 — The First Part of the Security Deposit |
| BR-DEP-002 | BR-DEP-001 — The First Part of the Security Deposit |
| BR-DEP-003 | BR-DEP-001 — The First Part of the Security Deposit |
| **BR-DEP-004** | BR-DEP-004 — The Required Security Deposit of a Lease |
| **BR-DEP-005** | BR-DEP-005 — The Same Deposit Goes On Into the Lease |
| **BR-DEP-006** | BR-DEP-006 — The Rest Is Received at Sign Lease |
| **BR-LEASE-001** | BR-LEASE-001 — Lease Status |
| BR-LEASE-002 | BR-LEASE-001 — Lease Status |
| BR-LEASE-003 | BR-LEASE-001 — Lease Status |
| BR-LEASE-004 | BR-LEASE-001 — Lease Status |
| BR-LEASE-005 | BR-LEASE-001 — Lease Status |
| **BR-LEASE-006** | BR-LEASE-006 — One Primary Tenant, Who Signs |
| BR-LEASE-007 | BR-LEASE-006 — One Primary Tenant, Who Signs |
| BR-LEASE-008 | BR-LEASE-006 — One Primary Tenant, Who Signs |
| **BR-LEASE-009** | BR-LEASE-009 — Several Signers, One Whole Debt |
| BR-LEASE-010 | BR-LEASE-009 — Several Signers, One Whole Debt |
| BR-LEASE-011 | BR-LEASE-009 — Several Signers, One Whole Debt |
| **BR-LEASE-012** | BR-LEASE-012 — Lease Dates |
| BR-LEASE-013 | BR-LEASE-012 — Lease Dates |
| **BR-LEASE-014** | BR-LEASE-014 — No Two Signed Leases at the Same Time |
| BR-LEASE-031 | BR-LEASE-012 — Lease Dates |
| **BR-OCC-001** | BR-OCC-001 — Living There Is Not Signing |
| **BR-OCC-002** | BR-OCC-002 — One Customer, One Lease, Real Dates |
| BR-OCC-003 | BR-OCC-002 — One Customer, One Lease, Real Dates |
| BR-OCC-004 | BR-OCC-002 — One Customer, One Lease, Real Dates |
| BR-OCC-005 | BR-OCC-002 — One Customer, One Lease, Real Dates |
| BR-OCC-006 | BR-OCC-001 — Living There Is Not Signing |
| BR-OCC-007 | BR-OCC-002 — One Customer, One Lease, Real Dates |
| BR-OCC-008 | BR-OCC-009 — Closing an Occupancy |
| **BR-OCC-009** | BR-OCC-009 — Closing an Occupancy |
| BR-OCC-010 | BR-OCC-009 — Closing an Occupancy |
| **BR-LEASE-015** | BR-LEASE-015 — Signing and Move-in |
| BR-LEASE-016 | BR-LEASE-015 — Signing and Move-in |
| **BR-DEP-007** | BR-DEP-007 — Only for an Approved Pet |
| BR-DEP-008 | BR-DEP-007 — Only for an Approved Pet |
| **BR-DEP-009** | BR-DEP-009 — Held Money for Pet Damage, Not a Limit |
| **BR-DEP-010** | BR-DEP-010 — When the Pet Deposit Is Due |
| **BR-DEP-011** | BR-DEP-011 — Held During the Lease |
| BR-DEP-012 | BR-DEP-011 — Held During the Lease |
| **BR-DEP-013** | BR-DEP-013 — A Deposit Never Pays an Ordinary Invoice |
| BR-DEP-014 | BR-DEP-013 — A Deposit Never Pays an Ordinary Invoice |
| BR-RENT-001 | BR-RENT-015 — Monthly Rent From the Signed Lease, Billed in Advance |
| BR-RENT-002 | BR-RENT-015 — Monthly Rent From the Signed Lease, Billed in Advance |
| BR-RENT-003 | BR-RENT-015 — Monthly Rent From the Signed Lease, Billed in Advance |
| **BR-RENT-004** | BR-RENT-004 — One Rent Invoice for a Lease and a Month |
| **BR-RENT-005** | BR-RENT-005 — The Initial Rent Invoice |
| **BR-RENT-006** | BR-RENT-006 — Part Months Use the Real Days |
| BR-RENT-007 | BR-RENT-006 — Part Months Use the Real Days |
| **BR-RENT-008** | BR-RENT-008 — Issue Day and Who Gets an Invoice |
| **BR-RENT-009** | BR-RENT-009 — Rent Due Dates |
| BR-RENT-010 | BR-RENT-008 — Issue Day and Who Gets an Invoice |
| BR-RENT-011 | BR-RENT-004 — One Rent Invoice for a Lease and a Month |
| **BR-RENT-012** | BR-RENT-012 — The Last Month When the Tenant Leaves Early |
| BR-RENT-013 | BR-RENT-006 — Part Months Use the Real Days |
| BR-RENT-014 | BR-RENT-012 — The Last Month When the Tenant Leaves Early |
| **BR-RENT-015** | BR-RENT-015 — Monthly Rent From the Signed Lease, Billed in Advance |
| BR-RENT-016 | BR-RENT-015 — Monthly Rent From the Signed Lease, Billed in Advance |
| BR-RENT-017 | BR-RENT-015 — Monthly Rent From the Signed Lease, Billed in Advance |
| BR-RENT-018 | BR-RENT-015 — Monthly Rent From the Signed Lease, Billed in Advance |
| BR-RENT-019 | BR-RENT-004 — One Rent Invoice for a Lease and a Month |
| BR-RENT-020 | BR-RENT-006 — Part Months Use the Real Days |
| BR-RENT-021 | BR-RENT-015 — Monthly Rent From the Signed Lease, Billed in Advance |
| BR-RENT-022 | BR-RENT-015 — Monthly Rent From the Signed Lease, Billed in Advance |
| BR-RENT-023 | BR-RENT-015 — Monthly Rent From the Signed Lease, Billed in Advance |
| BR-RENT-024 | BR-RENT-012 — The Last Month When the Tenant Leaves Early |
| BR-RENT-025 | BR-RENT-012 — The Last Month When the Tenant Leaves Early |
| BR-RENT-026 | BR-RENT-012 — The Last Month When the Tenant Leaves Early |
| BR-RENT-027 | BR-RENT-004 — One Rent Invoice for a Lease and a Month |
| BR-RENT-028 | BR-RENT-006 — Part Months Use the Real Days |
| BR-RENT-029 | BR-LATE-001 — One Automatic Late-payment Charge |
| BR-RENT-030 | BR-RENT-012 — The Last Month When the Tenant Leaves Early |
| **BR-UTIL-001** | BR-UTIL-001 — Electricity and Water, From the Unit's Own Meter |
| BR-UTIL-002 | BR-UTIL-001 — Electricity and Water, From the Unit's Own Meter |
| BR-UTIL-003 | BR-UTIL-001 — Electricity and Water, From the Unit's Own Meter |
| BR-UTIL-004 | BR-UTIL-001 — Electricity and Water, From the Unit's Own Meter |
| **BR-UTIL-005** | BR-UTIL-005 — Meters |
| BR-UTIL-006 | BR-UTIL-005 — Meters |
| BR-UTIL-007 | BR-UTIL-005 — Meters |
| BR-UTIL-008 | BR-UTIL-005 — Meters |
| **BR-UTIL-009** | BR-UTIL-009 — Readings |
| BR-UTIL-010 | BR-UTIL-009 — Readings |
| BR-UTIL-011 | BR-UTIL-009 — Readings |
| BR-UTIL-012 | BR-UTIL-009 — Readings |
| BR-UTIL-013 | BR-UTIL-005 — Meters |
| **BR-UTIL-014** | BR-UTIL-014 — Rates |
| BR-UTIL-015 | BR-UTIL-014 — Rates |
| BR-UTIL-016 | BR-UTIL-014 — Rates |
| BR-UTIL-017 | BR-UTIL-014 — Rates |
| **BR-UTIL-018** | BR-UTIL-018 — No Double Billing, One Customer for a Period |
| BR-UTIL-019 | BR-UTIL-018 — No Double Billing, One Customer for a Period |
| **BR-UTIL-020** | BR-UTIL-020 — Monthly Billing and the Final Invoice |
| BR-UTIL-021 | BR-UTIL-020 — Monthly Billing and the Final Invoice |
| BR-UTIL-022 | BR-UTIL-020 — Monthly Billing and the Final Invoice |
| **BR-UTIL-023** | BR-UTIL-023 — Broken Meter Estimate |
| BR-UTIL-024 | BR-UTIL-023 — Broken Meter Estimate |
| BR-UTIL-025 | BR-UTIL-023 — Broken Meter Estimate |
| BR-UTIL-026 | BR-UTIL-023 — Broken Meter Estimate |
| BR-UTIL-027 | BR-UTIL-023 — Broken Meter Estimate |
| BR-UTIL-028 | BR-UTIL-023 — Broken Meter Estimate |
| BR-UTIL-029 | BR-UTIL-014 — Rates |
| BR-UTIL-030 | BR-UTIL-014 — Rates |
| BR-UTIL-031 | BR-UTIL-014 — Rates |
| BR-UTIL-032 | BR-UTIL-001 — Electricity and Water, From the Unit's Own Meter |
| **BR-SVC-001** | BR-SVC-001 — Services Come From Settings and the Lease |
| BR-SVC-002 | BR-SVC-001 — Services Come From Settings and the Lease |
| **BR-SVC-003** | BR-SVC-003 — Billed in Advance on the Rent Invoice |
| BR-SVC-004 | BR-SVC-001 — Services Come From Settings and the Lease |
| **BR-SVC-005** | BR-SVC-005 — A New Service Rate |
| BR-SVC-006 | BR-SVC-005 — A New Service Rate |
| BR-SVC-007 | BR-SVC-005 — A New Service Rate |
| BR-SVC-008 | BR-SVC-005 — A New Service Rate |
| BR-SVC-009 | BR-SVC-003 — Billed in Advance on the Rent Invoice |
| BR-SVC-010 | BR-SVC-003 — Billed in Advance on the Rent Invoice |
| BR-SVC-011 | BR-SVC-003 — Billed in Advance on the Rent Invoice |
| BR-SVC-012 | BR-SVC-003 — Billed in Advance on the Rent Invoice |
| **BR-SVC-013** | BR-SVC-013 — The Last Month |
| BR-SVC-014 | BR-SVC-001 — Services Come From Settings and the Lease |
| BR-SVC-015 | BR-SVC-001 — Services Come From Settings and the Lease |
| BR-INV-001 | BR-INV-002 — Every Amount Owed Is an Invoice, With One Customer |
| **BR-INV-002** | BR-INV-002 — Every Amount Owed Is an Invoice, With One Customer |
| BR-INV-003 | BR-INV-017 — Number, Date, Period and Amount |
| BR-INV-004 | BR-INV-017 — Number, Date, Period and Amount |
| BR-INV-005 | BR-INV-017 — Number, Date, Period and Amount |
| BR-INV-006 | BR-INV-016 — Invoice Type, Line Category and Source |
| BR-INV-007 | BR-INV-002 — Every Amount Owed Is an Invoice, With One Customer |
| BR-INV-008 | BR-INV-016 — Invoice Type, Line Category and Source |
| BR-INV-009 | BR-INV-015 — Invoice Status |
| BR-INV-010 | BR-INV-015 — Invoice Status |
| BR-INV-011 | BR-INV-015 — Invoice Status |
| BR-INV-012 | BR-INV-015 — Invoice Status |
| BR-INV-013 | BR-INV-015 — Invoice Status |
| BR-INV-014 | BR-INV-046 — Void |
| **BR-INV-015** | BR-INV-015 — Invoice Status |
| **BR-INV-016** | BR-INV-016 — Invoice Type, Line Category and Source |
| **BR-INV-017** | BR-INV-017 — Number, Date, Period and Amount |
| **BR-INV-018** | BR-INV-018 — Due Date |
| BR-INV-019 | BR-INV-020 — Never Changed After Issue |
| **BR-INV-020** | BR-INV-020 — Never Changed After Issue |
| **BR-INV-021** | BR-INV-021 — Adjustment |
| BR-INV-022 | BR-INV-046 — Void |
| BR-INV-023 | BR-INV-020 — Never Changed After Issue |
| BR-INV-024 | BR-INV-046 — Void |
| BR-INV-025 | BR-INV-020 — Never Changed After Issue |
| **BR-INV-026** | BR-INV-026 — No Double Billing |
| BR-INV-027 | BR-INV-026 — No Double Billing |
| BR-INV-028 | BR-INV-026 — No Double Billing |
| BR-INV-029 | BR-INV-026 — No Double Billing |
| BR-INV-030 | BR-INV-020 — Never Changed After Issue |
| BR-INV-031 | BR-INV-020 — Never Changed After Issue |
| BR-INV-032 | BR-INV-020 — Never Changed After Issue |
| BR-INV-033 | BR-INV-020 — Never Changed After Issue |
| BR-INV-034 | BR-INV-020 — Never Changed After Issue |
| BR-INV-035 | BR-INV-020 — Never Changed After Issue |
| BR-INV-036 | BR-INV-002 — Every Amount Owed Is an Invoice, With One Customer |
| BR-INV-037 | BR-INV-002 — Every Amount Owed Is an Invoice, With One Customer |
| BR-INV-038 | BR-INV-002 — Every Amount Owed Is an Invoice, With One Customer |
| BR-INV-039 | BR-INV-016 — Invoice Type, Line Category and Source |
| BR-INV-040 | BR-INV-016 — Invoice Type, Line Category and Source |
| BR-INV-041 | BR-INV-016 — Invoice Type, Line Category and Source |
| BR-INV-042 | BR-INV-016 — Invoice Type, Line Category and Source |
| BR-INV-043 | BR-INV-015 — Invoice Status |
| BR-INV-044 | BR-INV-021 — Adjustment |
| BR-INV-045 | BR-INV-021 — Adjustment |
| **BR-INV-046** | BR-INV-046 — Void |
| BR-INV-047 | BR-INV-020 — Never Changed After Issue |
| BR-INV-048 | BR-INV-020 — Never Changed After Issue |
| BR-INV-049 | BR-INV-018 — Due Date |
| BR-INV-050 | BR-INV-015 — Invoice Status |
| **BR-INV-051** | BR-INV-051 — When an Invoice Is Late |
| BR-INV-052 | BR-LATE-001 — One Automatic Late-payment Charge |
| BR-INV-053 | BR-LATE-001 — One Automatic Late-payment Charge |
| BR-INV-054 | BR-LATE-001 — One Automatic Late-payment Charge |
| BR-INV-055 | BR-LATE-001 — One Automatic Late-payment Charge |
| **BR-LATE-001** | BR-LATE-001 — One Automatic Late-payment Charge |
| BR-LATE-002 | BR-LATE-001 — One Automatic Late-payment Charge |
| BR-LATE-003 | BR-LATE-001 — One Automatic Late-payment Charge |
| **BR-LATE-004** | BR-LATE-004 — Balance and Correction of a Late-payment Charge |
| BR-LATE-005 | BR-LATE-004 — Balance and Correction of a Late-payment Charge |
| BR-LATE-006 | BR-LATE-001 — One Automatic Late-payment Charge |
| **BR-PAY-001** | BR-PAY-001 — One Payer, and a Lease When It Helps |
| BR-PAY-002 | BR-PAY-001 — One Payer, and a Lease When It Helps |
| **BR-PAY-003** | BR-PAY-003 — A Payment Is Money Received |
| **BR-PAY-004** | BR-PAY-004 — Number and Date |
| BR-PAY-005 | BR-PAY-004 — Number and Date |
| **BR-PAY-006** | BR-PAY-006 — Payment Methods and Currency |
| BR-PAY-007 | BR-PAY-006 — Payment Methods and Currency |
| **BR-PAY-008** | BR-PAY-008 — Payment Status |
| BR-PAY-009 | BR-PAY-008 — Payment Status |
| BR-PAY-010 | BR-PAY-008 — Payment Status |
| BR-PAY-011 | BR-PAY-008 — Payment Status |
| **BR-PAY-012** | BR-PAY-012 — Reversing a Payment |
| BR-PAY-013 | BR-PAY-003 — A Payment Is Money Received |
| BR-PAY-014 | BR-PAY-008 — Payment Status |
| BR-PAY-015 | BR-PAY-017 — What a Payment Keeps |
| BR-PAY-016 | BR-PAY-017 — What a Payment Keeps |
| **BR-PAY-017** | BR-PAY-017 — What a Payment Keeps |
| BR-PAY-018 | BR-PAY-017 — What a Payment Keeps |
| **BR-RECEIPT-001** | BR-RECEIPT-001 — The Receipt |
| BR-RECEIPT-002 | BR-PAY-004 — Number and Date |
| BR-RECEIPT-003 | BR-RECEIPT-001 — The Receipt |
| BR-RECEIPT-004 | BR-RECEIPT-001 — The Receipt |
| BR-RECEIPT-005 | BR-RECEIPT-001 — The Receipt |
| BR-RECEIPT-006 | BR-PAY-003 — A Payment Is Money Received |
| **BR-PAY-019** | BR-PAY-019 — An Allocation Is Its Own Record |
| **BR-PAY-020** | BR-PAY-020 — The App Proposes, Staff Confirm |
| **BR-PAY-021** | BR-PAY-021 — The Order of the Proposal |
| BR-PAY-022 | BR-PAY-021 — The Order of the Proposal |
| BR-PAY-023 | BR-PAY-021 — The Order of the Proposal |
| **BR-PAY-024** | BR-PAY-024 — The Customer May Name What to Pay |
| **BR-PAY-025** | BR-PAY-025 — Whose Invoices a Payment May Pay |
| BR-PAY-026 | BR-PAY-025 — Whose Invoices a Payment May Pay |
| **BR-PAY-027** | BR-PAY-027 — Limits of an Allocation |
| BR-PAY-028 | BR-PAY-027 — Limits of an Allocation |
| **BR-PAY-029** | BR-PAY-029 — History and Reversal of an Allocation |
| **BR-PAY-030** | BR-PAY-030 — Money Above Everything Owed |
| BR-PAY-031 | BR-PAY-030 — Money Above Everything Owed |
| BR-PAY-032 | BR-PAY-030 — Money Above Everything Owed |
| BR-PAY-033 | BR-PAY-030 — Money Above Everything Owed |
| BR-PAY-034 | BR-PAY-030 — Money Above Everything Owed |
| BR-PAY-035 | BR-PAY-030 — Money Above Everything Owed |
| BR-PAY-036 | BR-PAY-021 — The Order of the Proposal |
| BR-PAY-037 | BR-PAY-024 — The Customer May Name What to Pay |
| BR-PAY-038 | BR-PAY-021 — The Order of the Proposal |
| **BR-PAY-039** | BR-PAY-039 — Unpaid Rent Means the Rent Line |
| BR-PAY-040 | BR-PAY-021 — The Order of the Proposal |
| **BR-PAY-042** | BR-PAY-042 — A Payment on the Wrong Unit's Invoice |
| **BR-CREDIT-001** | BR-CREDIT-001 — Credit Is Kept in USD, Apart From Deposits |
| **BR-CREDIT-002** | BR-CREDIT-002 — How Credit Starts |
| BR-CREDIT-003 | BR-CREDIT-002 — How Credit Starts |
| BR-CREDIT-004 | BR-CREDIT-001 — Credit Is Kept in USD, Apart From Deposits |
| **BR-CREDIT-005** | BR-CREDIT-005 — Using Credit |
| BR-CREDIT-006 | BR-CREDIT-005 — Using Credit |
| BR-CREDIT-007 | BR-CREDIT-005 — Using Credit |
| BR-CREDIT-008 | BR-CREDIT-005 — Using Credit |
| **BR-CREDIT-009** | BR-CREDIT-009 — Credit History and Reversal |
| BR-CREDIT-010 | BR-CREDIT-001 — Credit Is Kept in USD, Apart From Deposits |
| **BR-CREDIT-011** | BR-CREDIT-011 — Refund of Credit |
| BR-CREDIT-012 | BR-CREDIT-009 — Credit History and Reversal |
| BR-CREDIT-013 | BR-CREDIT-001 — Credit Is Kept in USD, Apart From Deposits |
| BR-CREDIT-014 | BR-CREDIT-002 — How Credit Starts |
| **BR-LEDGER-001** | BR-LEDGER-001 — One Account View for Each Customer |
| BR-LEDGER-002 | BR-LEDGER-001 — One Account View for Each Customer |
| BR-LEDGER-003 | BR-LEDGER-001 — One Account View for Each Customer |
| BR-LEDGER-004 | BR-LEDGER-001 — One Account View for Each Customer |
| BR-LEDGER-005 | BR-LEDGER-001 — One Account View for Each Customer |
| BR-LEDGER-006 | BR-LEDGER-001 — One Account View for Each Customer |
| BR-LEDGER-007 | BR-LEDGER-001 — One Account View for Each Customer |
| **BR-REFUND-001** | BR-REFUND-001 — A Refund Is Its Own Record With One Source |
| BR-REFUND-002 | BR-REFUND-001 — A Refund Is Its Own Record With One Source |
| BR-REFUND-003 | BR-REFUND-001 — A Refund Is Its Own Record With One Source |
| BR-REFUND-004 | BR-RES-021 — Who Caused the End Decides the Deposit |
| **BR-REFUND-005** | BR-REFUND-005 — Every Refund Is in USD |
| BR-REFUND-006 | BR-REFUND-005 — Every Refund Is in USD |
| BR-REFUND-007 | BR-DEP-025 — What Is Left Is Refunded |
| BR-REFUND-008 | BR-REFUND-005 — Every Refund Is in USD |
| **BR-REFUND-009** | BR-REFUND-009 — Approval, Reason and Refund Method |
| BR-REFUND-010 | BR-REFUND-001 — A Refund Is Its Own Record With One Source |
| **BR-REFUND-011** | BR-REFUND-011 — Refund History |
| BR-REFUND-012 | BR-REFUND-001 — A Refund Is Its Own Record With One Source |
| BR-REFUND-013 | BR-DEP-011 — Held During the Lease |
| BR-REFUND-014 | BR-REFUND-009 — Approval, Reason and Refund Method |
| **BR-REFUND-015** | BR-REFUND-015 — Who Receives a Deposit Refund |
| **BR-LEASE-017** | BR-LEASE-017 — Nothing Is Automatic at the Lease End Date |
| BR-LEASE-018 | BR-LEASE-017 — Nothing Is Automatic at the Lease End Date |
| BR-LEASE-019 | BR-LEASE-017 — Nothing Is Automatic at the Lease End Date |
| **BR-LEASE-020** | BR-LEASE-020 — Leaving Early |
| BR-LEASE-021 | BR-LEASE-020 — Leaving Early |
| **BR-LEASE-022** | BR-LEASE-022 — Notice and the Real Termination Date |
| BR-LEASE-023 | BR-LEASE-022 — Notice and the Real Termination Date |
| **BR-LEASE-024** | BR-LEASE-024 — Ending a Lease for a Violation |
| BR-LEASE-025 | BR-LEASE-024 — Ending a Lease for a Violation |
| **BR-LEASE-026** | BR-LEASE-026 — Unpaid Rent: Notices on Day 10, 20 and 25, Termination Letter on Day 30 |
| BR-LEASE-027 | BR-LEASE-026 — Unpaid Rent: Notices on Day 10, 20 and 25, Termination Letter on Day 30 |
| BR-LEASE-028 | BR-LEASE-026 — Unpaid Rent: Notices on Day 10, 20 and 25, Termination Letter on Day 30 |
| BR-LEASE-029 | BR-LEASE-026 — Unpaid Rent: Notices on Day 10, 20 and 25, Termination Letter on Day 30 |
| BR-LEASE-030 | BR-LEASE-026 — Unpaid Rent: Notices on Day 10, 20 and 25, Termination Letter on Day 30 |
| **BR-MOVEOUT-001** | BR-MOVEOUT-001 — The Move-out |
| BR-MOVEOUT-002 | BR-MOVEOUT-001 — The Move-out |
| BR-MOVEOUT-003 | BR-MOVEOUT-001 — The Move-out |
| BR-MOVEOUT-004 | BR-MOVEOUT-001 — The Move-out |
| **BR-MOVEOUT-005** | BR-MOVEOUT-005 — Final Readings and the Final Utilities Invoice |
| **BR-MOVEOUT-006** | BR-MOVEOUT-006 — Inspection and Damage Charges |
| BR-MOVEOUT-007 | BR-LEASE-017 — Nothing Is Automatic at the Lease End Date |
| BR-MOVEOUT-008 | BR-LEASE-017 — Nothing Is Automatic at the Lease End Date |
| BR-MOVEOUT-009 | BR-LEASE-017 — Nothing Is Automatic at the Lease End Date |
| BR-MOVEOUT-010 | BR-LEASE-020 — Leaving Early |
| **BR-MOVEOUT-011** | BR-MOVEOUT-011 — Move-out History and the Final Settlement |
| BR-MOVEOUT-012 | BR-MOVEOUT-011 — Move-out History and the Final Settlement |
| **BR-MOVEOUT-013** | BR-MOVEOUT-013 — Unit Cleaning Charge |
| BR-DEP-015 | BR-RES-021 — Who Caused the End Decides the Deposit |
| BR-DEP-016 | BR-RES-021 — Who Caused the End Decides the Deposit |
| BR-DEP-017 | BR-RES-021 — Who Caused the End Decides the Deposit |
| **BR-DEP-018** | BR-DEP-018 — Keeping a Deposit Is Its Own Record |
| BR-DEP-019 | BR-DEP-018 — Keeping a Deposit Is Its Own Record |
| BR-DEP-020 | BR-DEP-010 — When the Pet Deposit Is Due |
| **BR-DEP-021** | BR-DEP-021 — A Pet That Was Not Told |
| BR-DEP-022 | BR-DEP-021 — A Pet That Was Not Told |
| **BR-DEP-023** | BR-DEP-023 — A Kept Security Deposit Is Kept Whole |
| **BR-DEP-024** | BR-DEP-024 — The Pet Deposit When a Lease Ends |
| **BR-DEP-025** | BR-DEP-025 — What Is Left Is Refunded |
| BR-DEP-026 | BR-DEP-023 — A Kept Security Deposit Is Kept Whole |
| BR-DEP-027 | BR-DEP-024 — The Pet Deposit When a Lease Ends |
| **BR-SETTLE-001** | BR-SETTLE-001 — One Final Settlement for Each Ended Lease |
| BR-SETTLE-002 | BR-SETTLE-001 — One Final Settlement for Each Ended Lease |
| BR-SETTLE-003 | BR-SETTLE-001 — One Final Settlement for Each Ended Lease |
| **BR-SETTLE-004** | BR-SETTLE-004 — The Order: Credit, Security Deposit, Pet Deposit |
| BR-SETTLE-005 | BR-SETTLE-004 — The Order: Credit, Security Deposit, Pet Deposit |
| BR-SETTLE-006 | BR-SETTLE-004 — The Order: Credit, Security Deposit, Pet Deposit |
| **BR-SETTLE-007** | BR-SETTLE-007 — What Is Left After the Settlement |
| BR-SETTLE-008 | BR-SETTLE-007 — What Is Left After the Settlement |
| **BR-SETTLE-009** | BR-SETTLE-009 — Settlement History |
| BR-SETTLE-010 | BR-DEP-013 — A Deposit Never Pays an Ordinary Invoice |
| BR-SETTLE-011 | BR-SETTLE-001 — One Final Settlement for Each Ended Lease |
| **BR-SETTLE-012** | BR-SETTLE-012 — Closed Once; Later Fixes Are Corrections |
| BR-SETTLE-013 | BR-SETTLE-012 — Closed Once; Later Fixes Are Corrections |
| BR-SETTLE-014 | BR-DEP-018 — Keeping a Deposit Is Its Own Record |
| BR-SETTLE-015 | BR-SETTLE-009 — Settlement History |
| BR-SETTLE-016 | BR-SETTLE-007 — What Is Left After the Settlement |
| BR-SETTLE-017 | BR-SETTLE-004 — The Order: Credit, Security Deposit, Pet Deposit |
| **BR-MONEY-001** | BR-MONEY-001 — USD Is the Base; Payments in USD or Riel |
| BR-MONEY-002 | BR-MONEY-001 — USD Is the Base; Payments in USD or Riel |
| **BR-MONEY-003** | BR-MONEY-003 — Money Is Counted Exactly |
| **BR-MONEY-004** | BR-MONEY-004 — The Riel Rate |
| BR-MONEY-005 | BR-MONEY-004 — The Riel Rate |
| BR-MONEY-006 | BR-MONEY-004 — The Riel Rate |
| **BR-MONEY-007** | BR-MONEY-007 — The Rate of a Payment Is Kept |
| BR-MONEY-008 | BR-MONEY-004 — The Riel Rate |
| BR-MONEY-009 | BR-MONEY-007 — The Rate of a Payment Is Kept |
| BR-MONEY-010 | BR-MONEY-007 — The Rate of a Payment Is Kept |
| BR-MONEY-011 | BR-MONEY-007 — The Rate of a Payment Is Kept |
| **BR-MONEY-012** | BR-MONEY-012 — Part Months and Rounding |
| BR-MONEY-013 | BR-PROP-003 — Real Dates and the Property's Time Zone |
| BR-AUDIT-001 | BR-AUDIT-006 — Every Change Is Kept, for Ever |
| BR-AUDIT-002 | BR-AUDIT-006 — Every Change Is Kept, for Ever |
| **BR-AUDIT-003** | BR-AUDIT-003 — Times Come From the Database Clock |
| BR-AUDIT-004 | BR-AUDIT-006 — Every Change Is Kept, for Ever |
| BR-AUDIT-005 | BR-AUDIT-006 — Every Change Is Kept, for Ever |
| **BR-AUDIT-006** | BR-AUDIT-006 — Every Change Is Kept, for Ever |
| BR-AUDIT-007 | BR-AUDIT-006 — Every Change Is Kept, for Ever |
| BR-AUDIT-008 | BR-AUDIT-006 — Every Change Is Kept, for Ever |
| BR-AUDIT-009 | BR-AUDIT-006 — Every Change Is Kept, for Ever |
| BR-AUDIT-010 | BR-AUDIT-006 — Every Change Is Kept, for Ever |
| BR-AUDIT-011 | BR-AUDIT-006 — Every Change Is Kept, for Ever |
| **BR-AUTH-001** | BR-AUTH-001 — Every Action Needs a Signed-in User With the Right |
| **BR-AUTH-002** | BR-AUTH-002 — Actions That Need More Than Staff |
| BR-AUTH-003 | BR-AUTH-002 — Actions That Need More Than Staff |
| BR-AUTH-004 | BR-AUTH-002 — Actions That Need More Than Staff |
| BR-AUTH-005 | BR-AUTH-002 — Actions That Need More Than Staff |
| BR-AUTH-006 | BR-AUTH-002 — Actions That Need More Than Staff |
| BR-AUTH-007 | BR-AUTH-002 — Actions That Need More Than Staff |
| BR-AUTH-008 | BR-AUTH-002 — Actions That Need More Than Staff |
| BR-AUTH-009 | BR-AUTH-002 — Actions That Need More Than Staff |
| **BR-AUTH-010** | BR-AUTH-010 — Money Drafts and the Approver |

---

# Appendix B. Decided by the Owner, Not Built Yet

The owner decided these on 12 November 2026 (DL-226). The app does not do them yet, so the rules above still say what the app does today. Each one changes its rule in this document in the same change that builds it.

Nothing is left in this list.

Built already: D2, the late-payment rate in Settings is at most 10% (BR-LATE-001). D1, a hand-back before the 5th pays only the days used (BR-RENT-012, DL-229). Q3, the Utilities rate is chosen by the first day of the period of use (BR-UTIL-014, DL-230). T1, the seven Invoice types are kept on the Invoice (BR-INV-016, DL-231). D3, an amount missed on a fully paid line keeps the type of what was missed (BR-INV-021, DL-232). L1, the late-payment charge is an Invoice of the type Late-payment (BR-LATE-001, BR-LATE-004, DL-233). D4, the Pet Deposit for a pet kept from the start is received at Sign Lease (BR-DEP-010, BR-DEP-006, DL-234). D5, extra money at Receive payment becomes Customer Credit at once (BR-PAY-030, BR-CREDIT-002, DL-235). D6, a Draft Invoice is changed with no reason and a Draft made by a person may be deleted (BR-INV-015, DL-239). C1, the ending of an old Lease for unpaid Initial Rent or Security Deposit is taken out of the app (BR-LEASE-001, BR-LEASE-024, BR-DEP-023, DL-240). C2, who holds a Unit is worked out from the dates of its records and staff set only its condition (BR-UNIT-002, BR-UNIT-004, BR-UNIT-008, BR-UNIT-009, DL-241).

Kept as they are, by the owner's decision of the same day: two monthly Invoices (Rent with Services, and Utilities); nothing automatic after the Lease End Date (BR-LEASE-017); the broken Meter estimate (BR-UTIL-023); the corrections after a closed Final Settlement (BR-SETTLE-012), with no new kinds, to be looked at again after six months of real use.

Open for the owner's lawyer: BR-DEP-023 keeps the whole Security Deposit and the Customer's debt stays owed. Is this in the Lease text, and is it allowed?
