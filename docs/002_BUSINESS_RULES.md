# 002 - Business Rules

**Project:** Property Rental Management System
**Document:** Business Rules
**Version:** 1.0
**Status:** Owner Review
**Depends On:** `001_DOMAIN_MODEL.md`
**Audience:** Product Owner, Business Analysts, Software Architects, Developers, QA Engineers

---

# 1. Purpose

This document defines the operational business rules governing the Property Rental Management System.

Where `001_DOMAIN_MODEL.md` defines the business concepts and their relationships, this document defines:

- what users are allowed to do
- when business actions are allowed
- how monetary values are calculated
- how statuses change
- what conditions must be satisfied
- what exceptions are permitted
- which actions require authorization
- how historical financial correctness is preserved

These rules are business requirements and must be enforced consistently regardless of whether an operation is initiated through:

- User Interface
- API
- scheduled process
- administrative workflow
- automated billing process

---

# 2. Rule Classification

Business Rules in this document are classified using the following prefixes.

| Prefix       | Meaning                |
| ------------ | ---------------------- |
| `BR-PROP`    | Property rules         |
| `BR-UNIT`    | Unit rules             |
| `BR-CUST`    | Customer rules         |
| `BR-RES`     | Reservation rules      |
| `BR-LEASE`   | Lease rules            |
| `BR-OCC`     | Occupancy rules        |
| `BR-DEP`     | Deposit rules          |
| `BR-RENT`    | Rent billing rules     |
| `BR-UTIL`    | Utility rules          |
| `BR-SVC`     | Service charge rules   |
| `BR-INV`     | Invoice rules          |
| `BR-PAY`     | Payment rules          |
| `BR-CREDIT`  | Customer Credit rules  |
| `BR-REFUND`  | Refund rules           |
| `BR-MOVEOUT` | Move-out rules         |
| `BR-SETTLE`  | Final Settlement rules |
| `BR-MONEY`   | Money and currency rules |
| `BR-AUDIT`   | Audit rules            |
| `BR-AUTH`    | Authorization rules    |

Rule identifiers are stable references and should be reused in:

- Product Requirements
- API Specification
- UI Specification
- Testing Strategy
- Decision Log

---

# 3. General Business Rules

## BR-PROP-001 — Single Property

One deployed application manages exactly one Property.

The application must not allow users to:

- create a second Property
- switch between Properties
- assign a Unit to another Property

---

## BR-PROP-002 — Historical Records

Historical operational and financial records must not be physically deleted as part of normal business workflows.

Where a record is no longer active, the system must use its approved status or an
explicit historical event, such as:

- CANCELLED
- TERMINATED
- VOID
- REVERSED
- Meter replacement
- Move-out
- Refund

when such a status or event applies.

---

## BR-PROP-003 — Business Date Integrity

Business actions must use the date on which the underlying business event actually occurred.

Users must not alter historical dates merely to change:

- billing periods
- balances
- rates
- Reservation validity
- Lease duration
- Deposit eligibility

Any permitted correction to a historical date must be audited.

The Property's authoritative business timezone is `Asia/Phnom_Penh`. Scheduled
business actions and end-of-date processing must use that timezone. A business date
remains in effect through the end of that local calendar date unless a rule explicitly
states otherwise.

---

# 4. Unit Rules

## BR-UNIT-001 — Supported Unit Types

A Unit may use only one of the following Unit Types:

- STUDIO
- ONE_BEDROOM
- TWO_BEDROOM
- THREE_BEDROOM

Commercial Unit is not supported.

Amended by DL-075 (owner, 2026-10-20): Unit Types are a Settings list (the Owner or a user with Settings access, DL-074), no longer the four fixed types above, which are today's values. A Unit Type used by a Unit cannot be removed. Commercial Unit stays unsupported (DL-001).

---

## BR-UNIT-002 — Supported Unit Statuses

A Unit may have only one current status:

- VACANT
- RESERVED
- OCCUPIED
- UNDER_MAINTENANCE
- CLEANING
- OUT_OF_SERVICE

---

## BR-UNIT-003 — Unit Number Uniqueness

Each Unit Number must be unique within the Property.

Amended by DL-078 (owner, 2026-10-20): the Unit number cannot change after the Unit is created.

---

## BR-UNIT-004 — Reservation Availability

A new Reservation may be created only when the Unit is legally available to be reserved.

A Unit must not receive a second active Reservation while another Reservation is ACTIVE.

An ACTIVE Reservation always holds its Unit. A Reservation releases its Unit only
when it becomes CANCELLED or COMPLETED through an approved business transition.

---

## BR-UNIT-005 — Lease Exclusivity

A Unit may have only one SIGNED Lease covering any point in time.

The system must reject an attempt to sign a second Lease when another SIGNED Lease
for the same Unit has an overlapping contractual period.

---

## BR-UNIT-006 — Reserved Status

When an ACTIVE Reservation successfully holds a Unit, the Unit status becomes:

```text
RESERVED
```

The Unit remains unavailable to another Reservation while that ACTIVE
Reservation holds it.

---

## BR-UNIT-007 — Occupied Status

When the Lease becomes SIGNED, the Unit status becomes:

```text
OCCUPIED
```

The Unit is OCCUPIED from signing, even before physical move-in.

---

## BR-UNIT-008 — Cleaning After Move-out

After move-out, a Unit may be placed into:

```text
CLEANING
```

until it is ready for rental again.

Once cleaning is completed and no other blocking condition exists, the Unit may return to:

```text
VACANT
```

Move-out does not require the Unit to become VACANT immediately. Its status must
reflect its actual physical and operational condition.

---

## BR-UNIT-009 — Maintenance Availability

A Unit in either:

```text
UNDER_MAINTENANCE
OUT_OF_SERVICE
```

must not be offered for a new Reservation unless an authorized user explicitly restores it to an available operational state.

Restoration must reflect the Unit's actual condition and must be audited. A
status change must not override an ACTIVE Reservation or SIGNED Lease.

---

## BR-UNIT-010 — Release After Reservation Cancellation

When a Reservation becomes CANCELLED, including automatic cancellation caused by
expiration, that Reservation releases the Unit.

If no other Lease, maintenance, cleaning, or out-of-service condition blocks
availability, the Unit becomes VACANT.

When a Lease is terminated before any move-in under BR-LEASE-005, the Unit is released
without an Occupancy or physical move-out. It returns to VACANT, or to CLEANING when a
user holding the Unit management capability records a reason.

---

## BR-UNIT-011 — Unit Status After Move-out

When physical move-out is completed, the Unit must leave OCCUPIED status and
enter the status that reflects its actual condition, normally CLEANING.

The Unit may become VACANT only after it is ready for rental and no authoritative
Reservation or Lease record blocks availability.

---

## BR-UNIT-012 — Restoration From Unavailable Operational States

A Unit may leave UNDER_MAINTENANCE or OUT_OF_SERVICE only through an authorized
restoration action confirming that the blocking condition has been resolved.

The resulting status must be determined from the Unit's actual readiness and its
authoritative Reservation and Lease records.

---

## BR-UNIT-013 — Authoritative Availability

Unit status is an operational summary and must not become a competing source of
truth.

Legal availability must be validated from the Unit's ACTIVE Reservations,
SIGNED Leases, actual occupancy, and blocking operational conditions. A status
value alone must never authorize a conflicting Reservation, Lease, or move-in.

---

## BR-UNIT-014 — Unit Cleaning Rate

Each Unit has a configured cleaning rate in USD cents. It is the source of the Unit cleaning charge at move-out (BR-MOVEOUT-013). Changing the rate never changes an issued charge (DL-065, DL-068).

## BR-UNIT-015 — Default Rent and Required Services

A Unit may have a default monthly Rent in USD cents and a list of required Services (DL-110, owner 2026-10-29). A new Reservation or Lease draft for the Unit starts at the default Rent. Staff may agree a higher Rent; a Rent below the default needs a Manager or the Owner (`rent.below_default`) and the reason of the command. A Lease draft from a Booking may keep the Booking's agreed Rent. Every new Lease draft for the Unit holds each required Service, and staff cannot remove one. Changing either never changes a Reservation or Lease that already exists.

---

# 5. Customer Rules

## BR-CUST-001 — Single Customer Entity

The system must use Customer as the canonical person record.

The system must not create separate permanent person entities for:

- Tenant
- Former Tenant
- Occupant
- Lease Signer
- Reservation Customer

These roles are established through relationships.

---

## BR-CUST-002 — Customer Reuse

An existing Customer record should be reused when the same person enters a new Reservation, Lease, Occupancy, Payment, or other business relationship.

The system should avoid unnecessary duplicate Customer records.

Amended by DL-071 (owner, 2026-10-20; answer 11): a Customer has an "ID number / Passport number" field. A Customer with the same ID number as another Customer is refused; staff must use the existing Customer. The same phone number or the same email address as another Customer shows a warning, and staff may still save. The ID number is required for every Customer, and two ID numbers are the same when they match after removing spaces and dashes and ignoring capital letters (owner, 2026-10-21). Not built yet.

---

## BR-CUST-003 — Customer History

Changing current Customer contact information must not alter the historical meaning of previous:

- Reservations
- Leases
- Payments
- Occupancies
- financial records

Amended by DL-078 (owner, 2026-10-20): Customer details are legal name (required), date of birth, gender (Female or Male), nationality, ID number / Passport number (required and unique, DL-071), phone, email, address and memo; changing them never changes past records.

---

# 6. Reservation Rules

## BR-RES-001 — Reservation Is Optional

A Customer may reserve a Unit before signing its Lease. A Lease may also be signed
without a Reservation for a walk-in Customer; then no Reservation is completed and the
Unit still becomes OCCUPIED at signing under BR-UNIT-007.

A walk-in Lease is subject to the same Unit exclusivity as any other Lease under
BR-UNIT-005 and BR-UNIT-006.

Amended by DL-100 (owner, 2026-10-27): a walk-in draft keeps a planned Security Deposit; Sign Lease first receives the full Security Deposit and the Initial Rent Invoice total, then signs.

---

## BR-RES-002 — One Customer per Reservation

A Reservation contains exactly one Customer.

The Reservation Customer is the prospective Primary Tenant.

---

## BR-RES-003 — Reservation Statuses

Reservation status may be only:

```text
ACTIVE
CANCELLED
COMPLETED
```

The system must not introduce an EXPIRED Reservation status.

ACTIVE means the Reservation currently holds the Unit. CANCELLED means it ended
without successfully proceeding to tenancy. COMPLETED means it successfully
proceeded to its resulting signed Lease; physical move-in may follow later. CANCELLED and
COMPLETED are terminal.

---

## BR-RES-004 — Initial Reservation Status

A newly accepted Reservation begins in ACTIVE status only after all Reservation
activation conditions, including receipt of the explicitly accepted initial Security
Deposit amount, are met.

Amended by DL-077 (owner, 2026-10-20): Make Reservation receives the accepted initial Security Deposit on a Receipt in the same save step, and the Reservation becomes active when that amount is received in full.

---

## BR-RES-005 — Reservation Expiration Required

Every ACTIVE Reservation must have a Reservation Expiration Date.

The Reservation remains valid through the entire Expiration Date in the
Property's configured local timezone.

---

## BR-RES-006 — Maximum Initial Reservation Period

The initial Reservation Expiration Date must not be more than 21 calendar days
from the Reservation Date. A shorter initial period is permitted.

Amended by DL-075 (owner, 2026-10-20): the 21 days are the Settings default for the longest first expiry. A new value applies only to new Reservations.

---

## BR-RES-007 — Reservation Extension Eligibility

A Reservation may be extended only when:

- the Reservation is ACTIVE;
- it has not expired;
- fewer than 14 calendar days remain before its current Expiration Date;
- it has not previously been extended; and
- the extension is authorized.

---

## BR-RES-008 — Maximum Extension

The single approved extension may add no more than 14 calendar days to the
existing Expiration Date.

The extension is calculated from the existing Expiration Date, not from the date
on which the extension is approved.

Amended by DL-075 (owner, 2026-10-20): the 14 days are the Settings default for the one extension. A new value applies only to new Reservations. The extension window of BR-RES-007 stays fixed.

---

## BR-RES-009 — Extension Is Not a Status

An extension does not change Reservation status. The Reservation remains ACTIVE
and continues holding its Unit.

The extension must be represented by a Reservation Extension Notice.

---

## BR-RES-010 — Extension History

Every extension must preserve:

- original Expiration Date;
- immediately previous Expiration Date;
- new Expiration Date;
- extension approval date and time (the database's own time when the authorized user
  records the extension; owner answer (a) to Q-2026-10-14-112 point 1);
- authorized user; and
- reason or memo when provided.

The effective Expiration Date must not be changed without this Notice history.

---

## BR-RES-011 — Reservation Expiration

At the end of the effective Expiration Date in the Property's configured local
timezone, an ACTIVE Reservation that has not become COMPLETED and has no valid
approved extension automatically becomes CANCELLED.

The cancellation reason must be `RESERVATION_EXPIRED`. The Reservation history
must remain permanent, and the Unit must be released from that Reservation.

---

## BR-RES-012 — Reservation Cancellation

Only an ACTIVE Reservation may be cancelled. Every cancellation must record its
reason and whether it is customer-caused, caused by expiration while the Property
could provide the Unit, or caused by the Property's inability to provide the
Unit as agreed.

A CANCELLED Reservation cannot later become ACTIVE or COMPLETED.

---

## BR-RES-013 — Reservation Completion at Lease Signing

A Reservation becomes COMPLETED when its resulting Lease becomes SIGNED, in the same
coordinated transition. At that moment the Reservation must be ACTIVE and not expired.
A COMPLETED Reservation cannot expire.

The COMPLETED Reservation must reference exactly one resulting Lease. COMPLETED is
terminal. The holding deposit received during the Reservation continues as the Security
Deposit under BR-DEP-005. Physical move-in, when it occurs, is recorded separately under
BR-LEASE-016.

---

## BR-RES-014 — Reservation to Lease Relationship

A Reservation may result in zero or one Lease.

The system must not create multiple resulting Leases from one Reservation.
A COMPLETED Reservation references exactly one resulting Lease. A CANCELLED
Reservation produces no resulting Lease.

---

## BR-RES-015 — Expiration Date Boundary

Expiration is end-of-date processing. The Reservation remains valid through the
entire effective Expiration Date and must not be cancelled earlier that day.

---

## BR-RES-016 — Automatic Expiration Cancellation

Automatic expiration performs the approved ACTIVE to CANCELLED transition,
records `RESERVATION_EXPIRED`, preserves history, and releases the Unit as one
coordinated business action.

Amended by the owner answers of 2026-10-04 to Q-2026-10-03-2 (docs/010, V1-056 slice 3b): automatic expiration still cancels and releases the Unit, but never forfeits the Security Deposit; the forfeiture is a Staff draft confirmed by a `financial.approve` holder (BR-AUTH-010). Until then the Reservation is listed as waiting for a Deposit decision.

---

## BR-RES-017 — Single Extension Limit

An ACTIVE Reservation may be extended no more than once.

---

## BR-RES-018 — Extension Date Calculation

An extension adds its approved number of calendar days to the existing
Expiration Date. It does not replace the original Reservation history.

---

## BR-RES-019 — No Second Extension

After one Reservation Extension Notice has been approved, every attempt to grant
another extension must be rejected.

If move-in does not occur by the extended Expiration Date, the automatic
expiration rule applies.

---

## BR-RES-020 — Cancellation Responsibility Classification

Cancellation responsibility must be based on the actual reason the Reservation
did not proceed. A Property-side inability to provide the Unit must not be
misclassified as customer-caused cancellation or expiration.

---

## BR-RES-021 — Customer-caused Cancellation or Expiration

When the Customer voluntarily cancels for a Customer-attributable reason, or
allows the Reservation to expire while the Property remained capable of
providing the Unit as agreed, the Security Deposit received is non-refundable.

Waiting for expiration must not bypass the customer-caused cancellation policy.

Amended by the owner answers of 2026-10-04 to Q-2026-10-03-2 (docs/010, V1-056 slice 3b): the non-refundable outcome is recorded as a forfeiture draft and takes effect only when a `financial.approve` holder confirms it (BR-AUTH-010); the Security Deposit stays held until then. Corrections of the outcome are drafts too.

---

## BR-RES-022 — Property-caused Cancellation

When the Property cannot provide the reserved Unit as agreed, Property Management
must first coordinate with the Customer. The Customer may agree to wait or may
accept temporary accommodation in another Unit.

This rule creates no additional temporary-accommodation financial policy.

If the Customer rejects the delay or alternative and requests cancellation, the
Reservation must be cancelled and all Security Deposit received for that
Reservation must be refunded through an explicit Refund event.

Amended by the owner answers of 2026-10-04 to Q-2026-10-03-2 (docs/010, V1-056 slice 3b): the cancellation and Unit release happen at once; the Refund is a draft with a Refund method and reference note (BR-REFUND-014) and takes effect only when a `financial.approve` holder confirms it (BR-AUTH-010). A Reservation Refund always goes to the Reservation Customer.

---

# 7. Security Deposit Rules During Reservation

## BR-DEP-001 — Security Deposit Required for Reservation

A Reservation may become ACTIVE only after the explicitly accepted initial partial
Security Deposit amount has been received. Authorized management may accept an
amount below or above the normal 20% suggestion.

The business does not use a separate Reservation Deposit.

---

## BR-DEP-002 — Initial Security Deposit May Be Partial

The initial payment may be less than the total required Security Deposit, but it
must equal the initial amount explicitly accepted for that Reservation. The accepted
amount and authorization must be audited.

Every receipt remains part of the same Security Deposit obligation.

Amended by DL-100 (owner, 2026-10-27): at Sign Lease the rest of the Security Deposit is received in full, together with the Initial Rent Invoice; there is no part payment at signing.

---

## BR-DEP-003 — Suggested Initial Security Deposit

The normal/default suggested amount when reserving a Unit is 20% of the agreed
monthly Rent. It is not a hard minimum.

```text
Suggested Initial Security Deposit
=
Agreed Monthly Rent × 20%
```

The final monetary result uses the approved monetary rounding rule.

Example:

```text
Agreed Monthly Rent:                  $500
Suggested Initial Security Deposit:   $100
```

Authorized management may accept another explicit amount, including an amount below
or above 20%, based on the actual Reservation arrangement. The system must preserve
the suggested amount, accepted required amount, override authorization, actor,
timestamp, and reason. It must not reject a Reservation merely because the collected
Security Deposit is below 20%. A lower accepted amount may legitimately hold the Unit
for a short Reservation period when authorized management accepts that arrangement.
This amount is Security Deposit, not a fee or separate Deposit type.

Amended by DL-075 (owner, 2026-10-20): the 20 percent is the Settings default for the suggested deposit. A new value applies only to new Reservations.

Amended by DL-099 (owner, 2026-10-27): more than the suggestion needs no typed reason and no override; only an amount below it needs a reason and authorized management.

---

## BR-DEP-004 — Required Security Deposit Amount

Every Lease has a required total Security Deposit amount.

The exact required total is determined by the agreed Lease terms.

The system must distinguish:

```text
Required Security Deposit
Security Deposit Received
Security Deposit Outstanding
```

where:

```text
Outstanding
=
Required
-
Received
```

Amended by DL-101 (owner, 2026-10-27): the required Security Deposit is a Lease term like the monthly Rent. Every draft Lease that is not a renewal records it with the Lease (not in the payment tables) before any money is received, and the printed draft shows it. A draft from a Reservation starts at the Reservation's amount and may be changed with a reason, never below the money already received; the Reservation's Security Deposit takes the new amount only when the Lease is signed.

---

## BR-DEP-005 — Security Deposit Continues Into Lease

Any Security Deposit received during Reservation remains the same Security Deposit when the resulting Lease is signed.

Money received for a Deposit must be linked explicitly from the Payment to the
applicable Deposit liability and Deposit balance. This Payment-to-Deposit link is
not an Invoice Payment Allocation and does not require a Deposit Invoice.

The system must not:

- refund it and recollect it
- create a second deposit
- record a conversion transaction
- recognize it as rental income

Amended by DL-101 (owner, 2026-10-27): when the draft from a Reservation records another Security Deposit amount, signing records one increase or decrease of the required amount of the same Security Deposit, with the draft's reason; it stays the same Security Deposit.

---

## BR-DEP-006 — Remaining Deposit Within Five Days After the Lease Start Date

The Security Deposit balance remaining after the holding deposit is due within five
calendar days after the Lease Start Date, together with the Initial Rent Invoice.

Move-in is always recorded when it happens and is never blocked by an unpaid Security
Deposit or Initial Rent. If the Security Deposit balance or the Initial Rent is unpaid
after that period, the owner may terminate under the standard Lease clause in
BR-LEASE-025.

Amended by DL-100 (owner, 2026-10-27): the app now receives the Security Deposit balance and the Initial Rent Invoice in full when the Lease is signed, so both are paid before move-in; this rule still covers a Lease signed before DL-100 and the Initial Rent Invoice Due Date.

---

# 8. Lease Rules

## BR-LEASE-001 — Lease Statuses

Lease status may be only:

```text
DRAFTED
SIGNED
CANCELLED
TERMINATED
```

---

## BR-LEASE-002 — New Lease Status

A newly created Lease begins as:

```text
DRAFTED
```

---

## BR-LEASE-003 — Valid Lease Status Transitions

Only the following transitions are permitted:

```text
DRAFTED -> SIGNED
DRAFTED -> CANCELLED
SIGNED  -> TERMINATED
```

Reaching the contractual Lease End Date does not by itself perform the SIGNED to
TERMINATED transition. That transition occurs through the applicable authorized
termination and move-out process.

---

## BR-LEASE-004 — Drafted Lease Cancellation

Only a DRAFTED Lease may be CANCELLED.

A SIGNED Lease must not be cancelled.

If a SIGNED Lease ends, it must be TERMINATED.

---

## BR-LEASE-005 — Signed Lease Termination

Only a SIGNED Lease may be TERMINATED.

A DRAFTED Lease cannot be terminated.

Termination must record the approved actual termination date and its governing
signed-Lease or business event. A Termination Notice alone does not change Lease
status.

When a Lease is terminated because the Initial Rent Invoice is unpaid:

- If the tenant never moved in, any Security Deposit paid is forfeited. If nothing was
  paid on the Initial Rent Invoice, it is VOIDed with a mandatory reason under
  BR-INV-046. If it was partly paid, the Property keeps the paid amount without Refund
  and the unpaid remainder is removed by a linked credit Adjustment with a mandatory
  reason, so the Customer owes nothing more. No Utility charge applies to the Customer.
  The Unit returns to VACANT under BR-UNIT-010 without an Occupancy or physical
  move-out.
- If the tenant moved in, the Initial Rent Invoice is kept and is never VOIDed. Rent is
  owed only through the termination date; the remaining days are removed by a linked
  credit Adjustment calculated with BR-RENT-007 proration. Utility through the actual
  Move-out Date and any Damage charges are charged, and the move-out process applies.
  Final Settlement remains governed by its own rules.

For this ground, an increase of the required Security Deposit total counts only from the
later of Lease Start plus five days and five days after the increase was recorded
(Asia/Phnom_Penh business dates, as the ground's own date rule), so the Customer always
gets five days to pay an increase. A decrease counts from the moment it is recorded (owner
answer (b) to Q-2026-10-19-138, V1-056 sub-slice 10i-2). The first amount of a Security
Deposit created after the Lease was signed (every walk-in Security Deposit) counts only on a
termination business date after its creation date plus five days; a Reservation's Deposit,
created before signing, counts at once (owner answer (a) to Q-2026-10-20-148, V1-056
sub-slice 10i-4a).

---

## BR-LEASE-006 — Primary Tenant Required

Every Lease must have exactly one Primary Tenant before the Lease may become SIGNED.

---

## BR-LEASE-007 — Primary Tenant Must Sign

The Primary Tenant must be included among the Lease Signers.

A Lease cannot become SIGNED if the Primary Tenant has not signed.

---

## BR-LEASE-008 — Lease Signer Minimum

A Lease must have at least one Lease Signer before it may become SIGNED.

Because the Primary Tenant must sign, this minimum is always satisfied by the Primary Tenant when the Lease is validly signed.

---

## BR-LEASE-009 — Multiple Signers

A Lease may contain multiple Lease Signers.

Every Lease Signer is jointly responsible for the full unpaid Lease obligation.

---

## BR-LEASE-010 — No Split Financial Responsibility

The system must not assign individual debt percentages to Lease Signers.

For example, a Lease with two signers and an $800 balance must not be represented as:

```text
Signer A owes $400
Signer B owes $400
```

Instead, the Lease owes:

```text
$800 total
```

and each signer is jointly responsible for satisfying that balance.

---

## BR-LEASE-011 — Lease Signer May Be Non-Occupant

A Customer may sign the Lease without living in the Unit.

Signing responsibility and physical occupancy are separate.

---

## BR-LEASE-012 — Lease Dates Required

A Lease must define its contractual period before becoming SIGNED.

The Lease must have:

- Lease Start Date
- Lease End Date

These contractual dates remain historically identifiable after renewal,
termination, or move-out.

---

## BR-LEASE-013 — Lease End Date

The Lease End Date must be later than the Lease Start Date.

The End Date is a contractual boundary, not an automatic month-to-month renewal
and not an automatic TERMINATED transition while occupancy continues.

Amended by DL-068 and DL-069 (2026-10-03): the End Date must also be the last day of a calendar month (BR-LEASE-031).

---

## BR-LEASE-014 — Non-overlapping Signed Lease Coverage

Before a Lease becomes SIGNED, the system must confirm that no other SIGNED Lease
has overlapping contractual coverage for the same Unit.

An approved signed renewal must not create overlapping contractual coverage that
violates this invariant.

---

## BR-LEASE-031 — Lease End Date Is a Month End

A Lease End Date must be the last day of a calendar month. Example: Start Date 10 April 2026, End Date 31 May 2027. Any other End Date is rejected. A Lease ends mid-month only through early termination. No Rent Invoice is generated for a month after the End Date (DL-069).

---

# 9. Occupancy Rules

## BR-OCC-001 — Occupancy Is Separate From Lease Signer

Occupancy identifies who physically lives in a Unit.

Lease Signer identifies who accepts contractual financial responsibility.

The system must not treat these as equivalent.

---

## BR-OCC-002 — Occupancy Customer

Every Occupancy record must identify one Customer.

---

## BR-OCC-003 — Occupancy Lease

Every Occupancy record must belong to one Lease.

---

## BR-OCC-004 — Move-in Date Required

An Occupancy record becomes active when the actual Move-in Date is recorded as
part of the coordinated move-in transition.

Amended by DL-102 (owner, 2026-10-28): a person may be added to a draft or a running Lease. Before the move-in they are planned and move in with the Lease; after it their own Occupancy starts on their own actual move-in date, not before the Lease's move-in date, not after the End Date and not after today.

---

## BR-OCC-005 — Move-out Date

The Move-out Date remains empty while the Customer currently occupies the Unit.

When occupancy ends, the Move-out Date must be recorded.

The Move-out Date is the actual date physical occupancy ended and must not precede
the Move-in Date.

---

## BR-OCC-006 — Occupancy Does Not Create Debt

An Occupant who is not a Lease Signer does not become financially responsible merely by residing in the Unit.

---

## BR-OCC-007 — Occupancy Date Ordering

For a completed occupancy period:

```text
Move-in Date <= Move-out Date
```

Both endpoints are actual business dates. Corrections must preserve the previous
values and audit history.

---

## BR-OCC-008 — Occupancy After Lease End Date

If a Customer remains in the Unit after the contractual Lease End Date without an
approved signed renewal, Occupancy remains open and the Lease situation remains
represented accurately until Property Management takes authorized action under
the signed Lease.

The system must not fabricate move-out, automatic month-to-month tenancy,
automatic holdover Rent, penalties, fees, or a new tenancy.

---

## BR-OCC-009 — Coordinated Occupancy Closure

Occupancy closes only when physical occupancy has actually ended and an actual
Move-out Date is recorded through the move-out process.

Closing Occupancy must be coordinated with Lease termination, Unit status, final
Utility handling, and Final Settlement. Occupancy history must never be deleted.

Amended by DL-111 (owner, 2026-10-29): one person may move out while the Lease runs (BR-OCC-010). The whole-Unit move-out above still closes the last Occupancies with the Lease.

---

## BR-OCC-010 — Move Out One Occupant

While a signed Lease runs, one person may move out on their own actual day (DL-111, owner 2026-10-29):

- The Primary Tenant never moves out alone; they leave with the Lease (Termination and Move-out).
- A person who signs nothing needs only the day and a reason.
- A Joint Signer needs every other Signer of the Lease to agree. They stay a Signer of the Lease and keep its responsibility until it ends.
- The only Signer still living there cannot move out until the Lease's termination is complete.
- The day is on or after their Move-in Date, never after today and never after the End Date.

---

# 10. Move-in Rules

## BR-LEASE-015 — Required Conditions Before Move-in

Move-in may occur only when all required conditions are satisfied.

At minimum:

- Lease is SIGNED
- any Reservation for this Lease is COMPLETED with this Lease as its resulting Lease
- Unit is not UNDER_MAINTENANCE
- Unit is not OUT_OF_SERVICE
- move-in date is valid

An unpaid Security Deposit, Pet Deposit or Initial Rent never blocks move-in under
BR-DEP-006 and BR-DEP-010.

---

## BR-LEASE-016 — Move-in Completion

When the Lease becomes SIGNED:

- any Reservation for this Lease becomes COMPLETED; a walk-in Lease has none
- Unit becomes OCCUPIED
- Security Deposit remains associated with the Lease

These actions represent one coordinated business transition.

When physical move-in is completed later, the Occupancy begins with the actual Move-in
Date under BR-OCC-004. Move-in does not change the Reservation or Unit status. The
move-in transition must not complete until all conditions in BR-LEASE-015 are true.

---

# 11. Pet Deposit Rules

## BR-DEP-007 — Pet Deposit Conditional

Pet Deposit is required only when a pet is approved under the signed Lease and
the applicable Lease terms require that Deposit.

---

## BR-DEP-008 — No Pet Deposit Without Approved Pet

If no pet is being kept, a Pet Deposit must not be required merely because the
Customer might keep a pet in the future.

---

## BR-DEP-009 — Pet Deposit Is Liability

Pet Deposit must be recorded as a liability and not as:

- rent income
- service income
- damage income

Pet Deposit primarily secures demonstrable pet-caused property damage or
extraordinary/deep cleaning beyond normal turnover cleaning. It does not cap the
Customer's liability for the full valid repair or deep-cleaning cost.

Examples include pet damage to furniture, doors, walls, or flooring; cleaning beyond
normal turnover cleaning; and other demonstrable pet-caused property damage or
deep-cleaning cost.

```text
Pet Deposit:                    $200
Valid Pet-caused Cost:          $500
Remaining Customer Liability:  $300
```

If a valid pet-caused damage or deep-cleaning obligation becomes payable while the
Lease remains active, the Customer must pay that valid charge directly. The Pet
Deposit must not be consumed automatically and remains held unless BR-DEP-012 later
permits its Refund.

```text
Active-Lease Pet-caused Charge: $500
Customer Owes Directly:         $500
Pet Deposit Remains Held:       unchanged
```

---

## BR-DEP-010 — Pet Deposit Timing

When a Customer will keep an approved pet from the beginning of occupancy, the
Pet Deposit required by the applicable signed Lease terms is due within five calendar
days after the Lease Start Date. An unpaid Pet Deposit never blocks move-in.

When a Customer introduces or acquires a pet later, the Customer must notify
Property Management. If the pet is approved and the applicable signed Lease terms
require a Pet Deposit, that Deposit must be paid before or when the pet begins
staying in the Unit.

---

# 12. Deposit Refundability During Lease

## BR-DEP-011 — Deposit Held During Active Lease

Security Deposit and Pet Deposit are held during the active Lease, except that the
remaining refundable Pet Deposit may be returned under BR-DEP-012 after the pet
permanently leaves and applicable pet-related obligations are resolved.

They remain distinct liabilities with separately traceable balances.

---

## BR-DEP-012 — No Normal Deposit Refund During Active Lease

Security Deposit must not be refunded while the Lease remains SIGNED.

Pet Deposit remains held while an approved pet is kept at the Unit. If the tenant
permanently stops keeping the pet during an active Lease, the system must record that
fact and determine any valid pet-caused property damage or extraordinary/deep-cleaning
obligation. The Customer remains responsible for the full valid cost. Once applicable
pet-related obligations are resolved, any remaining refundable Pet Deposit may be
returned through an explicit Refund event with complete history. Lease termination is
not required for this Refund.

This rule does not prevent an explicit disposition required by an approved
non-refundable policy or an explicit Property-caused Reservation Refund before a
Lease begins.

---

## BR-DEP-013 — Deposits Are Not Monthly Payment Funds

A Customer must not use Security Deposit or Pet Deposit to pay ordinary monthly:

- Rent
- Utilities
- recurring Service Charges
- other ordinary current Invoice obligations

while the Lease remains active.

The Customer cannot direct staff to treat a Deposit as an ordinary Payment, and
staff cannot allocate it to an ordinary Invoice before Final Settlement.

---

## BR-DEP-014 — Deposit Application During Final Settlement Only

Deposits may be applied to Invoice obligations and Late-payment Charges only as part
of the Final Settlement process after Lease termination. An active-Lease Pet Deposit Refund under BR-DEP-012
is a separate Refund process, not Deposit application to an Invoice.

An explicit forfeiture/disposition event under an approved non-refundable policy
is not an Invoice allocation and must remain separate from Final Settlement
application. This distinction does not create any new reason for forfeiture.

Amended by the owner answers to Q-2026-10-05-20 and Q-2026-10-05-21 (2026-10-05): a Deposit may pay a Late-payment Charge like any other debt; the first sentence now names Late-payment Charges.

---

# 13. Business Rule Precedence

Where two operational rules appear to conflict, the following order applies:

1. Financial integrity and audit requirements
2. Lease contractual state
3. Reservation validity
4. Unit availability
5. Billing rules
6. operational convenience

For example, the system must not change a historical Invoice merely because doing so would simplify a current Payment allocation.

---

# 14. Rule Enforcement Principle

A business action that violates a rule in this document must be rejected.

The application must not silently alter user input to make an invalid action appear valid.

Examples:

```text
Invalid:
Signing a Lease whose contractual period overlaps another SIGNED Lease for the Unit

Invalid:
Moving in before the Lease is SIGNED

Invalid:
Cancelling a Signed Lease

Invalid:
Applying Security Deposit to an ordinary monthly Rent Invoice

Invalid:
Overwriting a historical Reservation expiration extension

Invalid:
Creating a second active electricity meter for the same Unit
```

Where an authorized exception is permitted by business policy, the exception must be explicit and fully audited.

---

# 15. Rent Billing Rules

## 15.1 Purpose

This section defines the business rules governing rent calculation, rent billing, recurring invoice generation, proration, rent revisions, and historical rent preservation.

These rules ensure that rent is billed consistently, accurately, and transparently while preserving historical financial records.

---

## 15.2 Standard Rent Billing

### BR-RENT-001 — Monthly Rent

Rent shall be charged on a monthly basis.

The agreed monthly Rent is defined in the applicable signed Lease agreement. A
different contractual Rent requires an applicable new or renewed signed agreement
for the future period; it must not be created by editing an Invoice.

---

### BR-RENT-002 — Rent is Billed in Advance

Rent shall always be billed in advance.

Each recurring Rent Invoice represents the upcoming rental period rather than the period already occupied.

Example:

| Invoice Date | Rental Period              |
| ------------ | -------------------------- |
| 25 July      | 1 August – 31 August       |
| 25 August    | 1 September – 30 September |

---

### BR-RENT-003 — Standard Rental Period

For active Leases, the normal rental period shall follow the calendar month.

A standard monthly Rent Invoice covers:

- the first calendar day of the month, through
- the final calendar day of the same month.

---

### BR-RENT-004 — One Rent Invoice Per Rental Period

Only one Rent Invoice may exist for the same Lease and rental period.

The business shall reject duplicate rent billing for an already billed rental period.

Example:

**Valid**

- Lease A
- Rent Invoice
- 1 August – 31 August

**Invalid**

- Lease A
- Second Rent Invoice
- 1 August – 31 August

---

## 15.3 Initial Rent Invoice

### BR-RENT-005 — Initial Rent Invoice Period

The Initial Rent Invoice is calculated from the Lease Start Date in the signed Lease,
not the actual Move-in Date. For a Lease Start Date on day 1 through day 20 inclusive,
it covers the Lease Start Date through the last calendar day of that month. Only the
portion after a Lease Start Date later than day 1 is prorated. For a Lease Start Date on
day 21 or later, it combines the prorated remainder of the start month and the entire
following calendar month. BR-RENT-007 proration applies.

Examples: a 10 July Lease Start Date covers 10–31 July; a 27 July Lease Start Date
covers 27 July–31 August, and recurring billing resumes on 25 August for the 1–30
September period. A Lease Start Date of 20 September with a $300 monthly Rent is
charged from 20 September even if the tenant arrives on 25 September:
$300 × 11/30 = $110.00. The actual Move-in Date does not change Initial Rent coverage.
Initial and recurring Rent periods must not duplicate or overlap.

---

### BR-RENT-006 — Actual Calendar Day Proration

Prorated rent shall always be calculated using the actual number of calendar days in the affected month.

The business shall never use:

- fixed 30-day months,
- fixed 31-day months,
- average monthly day calculations,
- simplified daily-rate assumptions.

Examples:

| Month                  | Days Used |
| ---------------------- | --------- |
| January                | 31        |
| February (Normal Year) | 28        |
| February (Leap Year)   | 29        |
| April                  | 30        |

---

### BR-RENT-007 — Proration Basis

Prorated Rent is calculated directly as:

```text
Monthly Rent × Inclusive Billable Calendar Days
------------------------------------------------
Actual Calendar Days in the Billing Month
```

The intermediate daily rate must not be rounded. Only the final monetary result
is rounded to the nearest USD cent using half-up rounding.

---

## 15.4 Recurring Monthly Billing

### BR-RENT-008 — Automatic Invoice Generation

Recurring Rent Invoices shall be generated automatically on the 25th day of the
current calendar month in the Property's configured local timezone.

The generated invoice represents the upcoming month's rental period.
The recurring process must not generate a period that BR-RENT-005 reserves for the
Initial Rent Invoice, even if the Lease was signed before that 25th. Recurring billing
resumes with the first complete calendar month after the Initial Rent period.

Example:

| Generation Date | Rental Period |
| --------------- | ------------- |
| 25 July         | August        |
| 25 August       | September     |
| 25 September    | October       |

Amended by DL-075 (owner, 2026-10-20): the 25th is the Settings default issue day (day 1 to 28, after the reading day). A change starts with the next billing month.

---

### BR-RENT-009 — Rent Invoice Due Dates

Recurring Rent Invoices have a Due Date of the **5th day of the billed month**. This
Due Date is established by the application/business rule; the Lease Agreement does
not define an alternative recurring Invoice Due Date.

The system proposes an Initial Rent Invoice Due Date of the Lease Start Date plus five
calendar days, including when that date falls in the following month. An authorized user
may set a different Due Date before issuance with a mandatory reason; the actor and
timestamp are recorded. The Due Date is fixed once the Invoice is issued. The Initial
Rent Invoice references the signed Lease, not a recorded Occupancy, and may be issued
before the Lease Start Date.

Example:

| Rental Month | Invoice Generated | Due Date    |
| ------------ | ----------------- | ----------- |
| August       | 25 July           | 5 August    |
| September    | 25 August         | 5 September |

Examples: issued 1 July or 10 July for a 10 July Lease Start Date, proposed Due Date
15 July; a 27 July Lease Start Date, proposed Due Date 1 August.

The Initial Rent Invoice never opens a Rent nonpayment case and has no late-payment
charge. If it remains unpaid after its Due Date, the system alerts authorized management
on the following calendar day in `Asia/Phnom_Penh`. Any response, including termination
under BR-LEASE-005 and BR-LEASE-025, is a separate manual authorized action; nothing is
automatic. The actual Move-in Date is recorded when move-in occurs, whether or not the
Invoice is paid.

Amended by DL-075 (owner, 2026-10-20): the 5th is the Settings default Due Date day for recurring Rent and monthly Utility Invoices (day 1 to 28). A change starts with the next billing month; an issued Due Date never changes. The Initial Rent Due Date of the Lease Start Date plus five calendar days stays fixed.

---

### BR-RENT-010 — Invoice Generation Eligibility

Recurring Rent Invoices shall only be generated for Leases that are:

- Signed,
- contractually applicable to the billed rental period, and
- Not terminated before the beginning of that rental period.

The period must also fall wholly after the Initial Rent period defined by
BR-RENT-005. No recurring generation may duplicate or overlap Initial Rent coverage.

The business shall not generate Rent Invoices for:

- Drafted Leases,
- Cancelled Leases,
- Terminated Leases.

This restriction governs recurring future-period generation. It does not prevent
authorized finalization of a valid unbilled rental period that occurred before
the approved termination date, subject to duplicate prevention and the applicable
final-month rule.

No Rent Invoice may be generated for a period after the contractual Lease End
Date unless an approved signed renewal covers that period. Continued occupancy
alone must not create automatic holdover Rent or a new tenancy.

---

### BR-RENT-011 — No Duplicate Monthly Billing

The business shall prevent duplicate recurring Rent Invoices.

A Lease shall never receive multiple Rent Invoices covering the same rental period.

Scheduled generation must be idempotent. A retry or recovery run must find the
existing Invoice rather than create another one.

---

## 15.5 Final Month

### BR-RENT-012 — Final Rental Period

When an approved termination rule requires a prorated final rental period, that
period begins on the first calendar day of the month and ends on the approved
actual termination date.

Voluntary early termination processed under BR-LEASE-021 is not prorated. Its
final month is charged in full.

---

### BR-RENT-013 — Applicable Final Month Proration

When final-month proration is required by an approved rule or the signed Lease,
it uses the same inclusive actual-calendar-day calculation and final rounding as
the prorated portion of the Initial Rent Invoice.

This rule must not override the full-month voluntary early-termination rule.

---

### BR-RENT-014 — Final Billing Independence

Final rent calculation is independent of:

- Security Deposit,
- Pet Deposit,
- Damage Charges,
- Utility Charges,
- Final Settlement.

Those financial obligations are handled separately under their respective business rules.

---

## 15.6 Rent Revisions

### BR-RENT-015 — Future Rent Changes

Monthly Rent may be revised only for future rental periods through the applicable
new or renewed signed Lease agreement.

An approved rent revision shall never retroactively modify completed rental periods.

---

### BR-RENT-016 — Effective Date

Every contractual Rent change shall have an effective date in that applicable
signed agreement.

The revised monthly rent applies only to rental periods beginning on or after that effective date.

Rental periods before the effective date continue using the previous rent.

---

### BR-RENT-017 — Historical Rent Preservation

Historical rent values shall remain permanently preserved.

The business shall never overwrite:

- historical monthly rent,
- prorated calculations,
- historical invoices,
- completed billing periods.

---

### BR-RENT-018 — Historical Invoice Integrity

Previously issued Rent Invoices shall permanently retain:

- the monthly rent used,
- the billing period,
- the calculation performed,
- the invoice amount,
- the invoice date.

Later rent revisions shall never alter existing Rent Invoices.

---

## 15.7 Billing Integrity

### BR-RENT-019 — Billing Period Consistency

Rental periods for the same Lease shall never overlap.

Every billable day shall belong to one—and only one—Rent Invoice.

The business shall reject any billing period that overlaps a previously billed rental period.

---

### BR-RENT-020 — Rent Calculation Consistency

The business shall use a single, consistent rent calculation methodology throughout the application.

Rent shall never be calculated using different formulas for different Customers.

---

### BR-RENT-021 — Historical Auditability

Every completed rent billing event forms part of the permanent financial history of the Property.

Historical rent records shall remain auditable and shall not be silently modified, deleted, recalculated, or replaced.

---

### BR-RENT-022 — Signed Lease Source of Truth

Every Rent Invoice requires a valid applicable signed Lease covering its rental
period. The Invoice Customer and Unit must be valid in that Lease context.

---

### BR-RENT-023 — No Manual Contractual Rent Override

The Rent line amount must be calculated from the contractual Rent in the
applicable signed Lease. Staff and automated processes must not replace it with an
arbitrary amount.

Legitimate financial changes after issuance use the approved Adjustment rules;
they do not rewrite contractual Rent.

---

### BR-RENT-024 — Voluntary Early-Termination Final Month

When a Customer voluntarily leaves before the Lease End Date and Property
Management processes the early termination, Rent for the calendar month
containing the approved actual termination/move-out date is charged in full.

Amended by DL-068 and DL-069 (2026-10-03): the calendar month is the month of the actual hand-back date. The exception for a hand-back before the 5th is BR-RENT-030.

---

### BR-RENT-025 — No Future Rent After Processed Early Termination

After voluntary early termination is processed, Rent must not be generated for
months after the approved actual termination date even though the original Lease
End Date was later.

---

### BR-RENT-026 — Advance-generated Invoice After Termination

If advance billing created a Rent Invoice for a period that is no longer valid
after an approved termination, the original Invoice must not be silently edited
or deleted. It must follow the controlled VOID or linked Adjustment process,
including resolution of active financial dependencies.

Amended by DL-068 and DL-069 (2026-10-03): when the hand-back month's Rent Invoice is VOIDed under BR-RENT-030, the whole Invoice is VOIDed, including Trash Collection and other fixed Service lines, because they are billed in advance on the same Invoice.

Amended by the owner's answer to Q-2026-10-04-9 (2026-10-04): Under BR-RENT-030, a fully paid Rent Invoice for the hand-back month, or for the next month when the hand-back is between the 25th and the month end, is kept as issued with no VOID, Refund or credit Adjustment (DL-068, Q-2026-10-04-8).

---

### BR-RENT-027 — Scheduled Billing Idempotency

Each generation attempt uses the applicable Lease and rental period as its stable
business key. Missed runs may be recovered, and repeated runs may be retried,
without creating duplicate Rent Invoices.

---

### BR-RENT-028 — Rent Calculation Traceability

Every Rent line must preserve the applicable Lease, contractual monthly Rent,
rental period, billable days when prorated, calendar days in the month,
calculation, rounding rule, and final USD amount.

---

### BR-RENT-029 — Contractual Late-payment Policy

The signed Lease policy is substantially that Rent or any other amount payable under
the Lease must be paid by the Due Date on the applicable Invoice or Bill. When a
balance remains unpaid after that Due Date, the normal/default late-payment charge is
10% of the remaining unpaid overdue amount of that Invoice. Authorized management may
reduce or waive the charge but must not increase it above 10%.

BR-INV-051 through BR-INV-055 govern the Invoice-wide calculation and one final
management decision. BR-LEASE-026 through BR-LEASE-030 govern the separate 20-day
Rent nonpayment warning, 30-day Serious Nonpayment Default, cure history, and explicit
termination boundary.

The Initial Rent Invoice is not an applicable source Invoice for a late-payment charge.

Amended by DL-075 (owner, 2026-10-20): the 10% is the Settings default late-payment rate, a whole percent from 0 to 10 (Lease Article 2.3 allows up to 10%). A new rate starts with the next billing month and applies to charges added after the change, for every Lease, never above 10%.

Amended by DL-076 (owner, 2026-10-20): the charge is added automatically under DL-076; the Owner or a Manager may reduce or waive it only after a Customer complaint of a staff mistake, never above the Settings rate (at most 10%).

---

### BR-RENT-030 — Hand-back Before the 5th

When a Customer leaving before the Lease End Date hands back the Unit before the 5th of a month (the date that counts is the actual hand-back date, not the notice date):

- that month's Rent Invoice unpaid: an authorized user VOIDs the whole Invoice with a reason, including its fixed Service lines; this also covers the next month's Rent Invoice generated on the 25th when the hand-back is between the 25th and the end of the month;
- that month's Rent fully paid: the Property keeps it, with no Refund and no credit Adjustment, and the Customer may stay until the last day of that month;
- that month's Rent partly paid: the Property keeps the paid part and a linked credit Adjustment with a reason removes the unpaid rest.

A hand-back on or after the 5th follows BR-RENT-024: that month's Rent is charged in full (DL-068, DL-069).

---

# 16. Utility Billing Rules

## 16.1 Purpose

This section defines the business rules governing utility billing, utility meter usage, meter replacement, utility readings, consumption calculation, utility rate changes, and historical preservation.

The objective is to ensure that utility charges accurately reflect actual consumption while preserving complete historical records for auditing and dispute resolution.

---

## 16.2 General Utility Billing

### BR-UTIL-001 — Supported Utility Types

The Property Rental Management System currently supports the following utility types:

- Electricity
- Water

No additional Utility Type is approved by this document.

---

### BR-UTIL-002 — Utility Billing Principle

Utility charges shall be based on actual metered consumption.

Consumption shall be determined from validated Utility Readings recorded for the applicable billing period.

Estimated consumption may be used only for a confirmed broken Meter under
BR-UTIL-023 through BR-UTIL-028. An inaccessible or missing ordinary reading does
not authorize estimation.

---

### BR-UTIL-003 — Utility Consumption Ownership

Utility consumption belongs to the Unit served by the Utility Meter.

Utility charges shall always be calculated using readings recorded from the meter assigned to that Unit.

Amended by DL-098 (owner, 2026-10-26): a Unit with no Meter of a kind (for example a store room with no electricity or water) gets no Utility Invoice for that kind; a Unit with no Meter at all on the hand-back day needs no final reading or final Utility Invoice at move-out. A Lease has no separate Utility tick; a Meter added later is billed from its first reading.

---

### BR-UTIL-004 — Utility Billing Independence

Electricity and Water shall be billed independently.

Each utility shall be calculated using:

- its own Utility Meter,
- its own Utility Readings,
- its own historical utility rate.

Changes affecting one utility shall never modify the billing of another utility.

---

## 16.3 Utility Meter Rules

### BR-UTIL-005 — One Active Meter Per Utility Type

A Unit may have only one active Utility Meter for each Utility Type.

Examples:

**Valid**

- Unit 301
    - Electricity Meter A
    - Water Meter B

**Invalid**

- Unit 301
    - Electricity Meter A
    - Electricity Meter C (both active)

---

### BR-UTIL-006 — Meter Replacement

A Utility Meter may be replaced when necessary.

Replacement does not remove the historical meter from the Property records.

Historical Utility Meters shall remain permanently preserved.

When a Meter is confirmed broken, it must be replaced. Failure and replacement
dates, the failed Meter, and the replacement Meter must remain linked.

Amended by DL-071 (owner, 2026-10-05; answer 12): a Meter serial number is unique across all Meters of the Property, whatever the Utility Type. Staff enter the serial printed on the Meter, or a unique Property code (for example `EL-U101`) when none is printed. A replaced Meter keeps its serial in history, and that serial cannot be used again. Not built yet.

Built by DL-104 (V1-060 B6, 2026-10-28): a Meter found broken may be recorded broken before it is replaced ("Report broken", with the day it was found broken and what is wrong). From that day it is broken: its Readings after that day are refused until it is replaced, and the replacement keeps the same failure date. It cannot be made working again; it must be replaced.

---

### BR-UTIL-007 — Meter Replacement Boundary

When a Utility Meter is replaced:

- all Utility Readings before the replacement belong to the previous meter,
- all Utility Readings recorded after installation belong to the replacement meter.

Actual consumption shall never be calculated by subtracting readings from two
different physical Meters. The first valid measurement day of the replacement
Meter must not also be counted in an approved estimate for the failed Meter.

---

### BR-UTIL-008 — Historical Meter Preservation

Historical Utility Meters shall never be deleted solely because a replacement meter has been installed.

Historical meter information remains part of the permanent operational history of the Property.

---

## 16.4 Utility Reading Rules

### BR-UTIL-009 — Reading Sequence

Utility Readings for the same Utility Meter shall follow chronological order.

Each new reading shall represent a later reading date than the previous validated reading.

---

### BR-UTIL-010 — Reading Validation

Before utility billing is performed, Utility Readings shall be validated.

At a minimum, validation shall ensure:

- chronological reading dates,
- valid reading values,
- no negative consumption,
- no impossible consumption resulting from incorrect readings.

Utility Readings that fail validation shall not be used for billing.

---

### BR-UTIL-011 — Reading Corrections

Incorrect Utility Readings may be corrected through an authorized business process
both before and after Utility Invoice issuance. The system must not use Invoice
payment status as the correction boundary.

Every correction preserves original Reading value, corrected Reading value, actor,
date/time, reason, and complete audit history. Historical Utility Readings shall
never be silently overwritten, deleted, or reassigned.

Before issuance, the corrected Reading becomes the valid billing input. After
issuance, correction remains permitted whether the Invoice is UNPAID,
PARTIALLY_PAID, or PAID, but the issued Invoice must not be silently rewritten. If
the correction changes the amount that should have been billed, the system preserves
the original Invoice, calculates the difference, and posts that financial difference
through the approved linked Invoice Adjustment process. The original Reading,
corrected Reading, original Invoice, and complete Adjustment chain remain
reconstructable.

---

### BR-UTIL-012 — Consumption Calculation

Utility consumption shall be calculated as the difference between two consecutive validated Utility Readings recorded for the same Utility Meter.

Consumption shall never be calculated using readings from different Utility Meters.

Start and end dates of the represented consumption period must be preserved and
must not overlap another billed period for the same Unit and Utility Type.

---

### BR-UTIL-013 — Historical Reading Integrity

Every Utility Reading shall remain permanently associated with the exact Utility Meter that produced it.

Replacing a Utility Meter shall never reassign, delete, or silently overwrite a
historical Utility Reading. An authorized correction under BR-UTIL-011 preserves the
original and corrected values and does not change Meter ownership.

---

## 16.5 Utility Rate Rules

### BR-UTIL-014 — Utility Rates

Each Utility Type shall have its own billing rate.

Electricity and Water rates are maintained independently.

---

### BR-UTIL-015 — Rate Effective Date

Every Utility Rate shall have an effective date.

The applicable rate is the Utility Rate effective on the date the Utility Invoice
is generated.

That one rate applies to the entire consumption period represented by the
Invoice.

Amended by DL-075 (owner, 2026-10-20): a new Utility Rate starts on a reading day (UI-091). The Rate effective on the Invoice generation date still applies.

Note (V1-060 B6, DL-105; owner, 2026-10-28): the owner kept this rule for the first Rate too: a new Rate, the first included, starts on a reading day after today. Until a Rate of a kind is in effect, no Utility Invoice for that kind can be made, and the final and catch-up Utility Invoice routes say so with `UTILITY_RATE_NOT_IN_EFFECT`.

---

### BR-UTIL-016 — Historical Rate Preservation

Changes to Utility Rates shall never modify:

- historical Utility Invoices,
- historical Utility Charges,
- historical Utility Consumption,
- completed billing periods.

Historical Utility Rates shall remain permanently preserved.

Every issued Utility line must preserve the exact rate and rate effective date
actually used.

---

### BR-UTIL-017 — Future Rate Changes

A revised Utility Rate becomes selectable on its approved effective date. The
Invoice generation date determines whether the old or revised rate applies.

A consumption period must not be split solely because the rate changed during
that period. Previously issued Invoices retain their historical rate.

---

## 16.6 Utility Billing Integrity

### BR-UTIL-018 — No Duplicate Utility Billing

The business shall prevent duplicate utility billing.

The same Unit, Utility Type, and consumption period shall never be billed more
once. Applicable Customer and Lease association must also be consistent.

A Utility billing period must not combine consumption assigned to different
financially responsible Customers. A move-in, move-out, or responsibility change
requires a validated Reading boundary or an approved broken-Meter estimation
boundary so each Customer is billed only for the applicable period.

Before the Lease Start Date, after cleaning and repair, staff record a validated Reading
for each Utility Meter of the Unit with an evidence reference and turn Electricity and
Water off. That Reading is the Customer's starting responsibility boundary, whether the
tenant arrives on the Lease Start Date or later. If staff switch the Utilities on again
before handover, they record a new baseline Reading. The Property bears all consumption
between the previous tenant's final Reading and the new Customer's baseline Reading,
including cleaning and repair, and any consumption when the tenant never moved in.

---

### BR-UTIL-019 — Historical Utility Integrity

Historical Utility Charges shall remain permanent financial records.

Historical Utility Billing shall never be silently:

- deleted,
- overwritten,
- recalculated,
- reassigned to another Utility Meter.

Corrections must preserve both the original operational source and every linked
financial correction.

---

### BR-UTIL-020 — Monthly Utility Billing

Electricity and Water are billed monthly.

Each monthly period preserves its starting and ending Reading dates. For due-date
purposes, the billing month is the Property-local calendar month containing the
period's ending Reading date.

Staff record every Utility Meter every month, including Meters of VACANT Units with
Electricity and Water off.

---

### BR-UTIL-021 — Utility Invoice Generation

A Utility Invoice may be generated only after its ending Meter Reading has been
entered and validated, or after an authorized broken-Meter estimate is complete.

At move-out, the final Utility Invoice is created off-cycle immediately from the final
validated Readings or approved estimate. Its Due Date follows BR-INV-018. It must not
duplicate a consumption period billed by the monthly run under BR-UTIL-018 and
BR-INV-027.

Amended by DL-075 (owner, 2026-10-20): the final Utility Invoice is due 7 days after issue (Lease Article 14.3), whatever the "days after issue" setting says.

---

### BR-UTIL-022 — Utility Due Date

A monthly Utility Invoice is due on the 5th day of the following month in the
Property's configured local timezone, where “following month” is relative to the
billing month defined in BR-UTIL-020.

The final Utility Invoice created at move-out follows BR-INV-018 instead.

Amended by DL-075 (owner, 2026-10-20): the 5th is the Settings default Due Date day (day 1 to 28). A change starts with the next billing month.

---

### BR-UTIL-023 — Confirmed Broken-Meter Estimation

Estimation is permitted only when a Meter is confirmed broken and valid actual
consumption for the unmeasured period cannot be obtained. The Meter must be
replaced, and the estimate must be explicitly identified as estimated
consumption caused by Meter failure.

---

### BR-UTIL-024 — Ordinary Missing Reading

If staff cannot obtain a reading but the Meter is not confirmed broken, the
Utility must not be billed yet. The system must wait for a valid actual reading
and must not estimate merely because the Meter was inaccessible or the reading
was missed.

---

### BR-UTIL-025 — Three-complete-period Historical Basis

When three or more complete historical actual periods exist for the same Unit and
Utility Type, use the three most recent complete historical actual periods before
the affected broken-Meter period as the historical basis.

```text
Weighted Historical Daily Average
=
Total Actual Consumption Across the Three Complete Periods
-----------------------------------------------------------
Total Calendar Days Represented by Those Periods
```

The system must not average three separately rounded period averages.

---

### BR-UTIL-026 — Basis Daily Average and Estimate Boundaries

Every historical basis under BR-UTIL-025 or BR-UTIL-027 and every complete
future-period basis under BR-UTIL-028 uses one weighted daily average:

```text
Basis Daily Average
=
Total Actual Consumption Across All Periods in the Basis
--------------------------------------------------------
Total Calendar Days Represented by All Periods in the Basis
```

The system must not average separately rounded period averages.

```text
Estimated Consumption
=
Basis Daily Average × Inclusive Unmeasured Calendar Days
```

The period begins when consumption became unmeasurable and ends on the last day
before the replacement Meter begins providing valid readings. A day must not be
counted in both the estimate and the replacement-Meter actual period.

---

### BR-UTIL-027 — One-or-two-period Historical Basis

If fewer than three, but at least one, complete historical actual period exists
before the affected broken-Meter period for the same Unit and Utility Type, use all
one or two available complete historical actual periods for that same Unit and
Utility Type as the basis.

```text
Weighted Historical Daily Average
=
Total Actual Consumption Across All Available Complete Historical Periods
--------------------------------------------------------------------------
Total Calendar Days Represented by Those Periods
```

Estimated Consumption is that weighted daily average multiplied by the applicable
unmeasured calendar days under BR-UTIL-026. The system must not discard the one or
two available periods and must not average separately rounded period averages.

---

### BR-UTIL-028 — Zero-history Future-period Fallback

If zero complete historical actual periods exist for the same Unit and Utility
Type, there is no usable historical basis. The system must wait until one complete
future month or period of actual consumption becomes available for that same Unit
and Utility Type and use that complete future actual period as the daily-average
basis under BR-UTIL-026.

Until that future complete actual period exists, the broken-Meter estimate and
affected charge remain pending and unfinalized. The reason for delay and the
future actual data eventually used must be preserved.

The system must never substitute another or comparable Unit, invent arbitrary
consumption, or average separately rounded period averages.

---

### BR-UTIL-029 — Generation-date Rate Selection

The Invoice generation date selects the effective Utility Rate. Selection uses
the Property's configured local timezone and is preserved on the Invoice.

---

### BR-UTIL-030 — Whole-period Rate Application

The selected Utility Rate applies to the entire represented consumption period.
The system must not allocate consumption across old and new rates solely because
a rate effective date occurred within that period.

---

### BR-UTIL-031 — Advance Rate-change Notice

Customers must be informed of a Utility Rate change before its effective date.
The effective date, not the notice date, controls automated rate selection.

---

### BR-UTIL-032 — Utility Charge Source of Truth

```text
Utility Charge
=
Validated Actual Consumption or Authorized Broken-Meter Estimate
×
Applicable Generation-date Utility Rate
```

The final USD amount uses the approved monetary rounding rule. Staff must not
replace the calculated charge with an arbitrary amount.

---

# 17. Service Charge Rules

## 17.1 Purpose

This section defines the business rules governing recurring fixed service charges that are billed independently of utility consumption.

Unlike utilities, service charges are fixed amounts determined by management.

---

## 17.2 Supported Service Charges

### BR-SVC-001 — Fixed Monthly Services

The Property currently approves and provides this recurring fixed monthly Service:

- Trash Collection

Trash Collection is billed as a fixed monthly charge rather than a
consumption-based charge.

Internet and Monthly Cleaning are not currently provided and must not generate
charges. They are examples of Services the Property could approve and configure in
the future. This document approves no other Service type. Any different Service
requires a separate Owner-approved rule and explicit configuration before billing;
staff must not create an arbitrary Service through a generic or miscellaneous field.

Amended by DL-097 (owner, 2026-10-26): every Service a Lease holds (added in Settings with a monthly rate and ticked on the Lease, DL-075) is billed on the Rent Invoice with the Trash Collection rules: a month is billed when the Lease's term and the Service's approval cover the whole month, at the rate in force on the first billed day, by days in the move-in month and in full for a following month, each Service on its own line. A Service that covers only part of a month, or has no rate, stops that Rent Invoice until it is corrected.

Amended by DL-068 and DL-069 (2026-10-03): the one-time Unit cleaning charge at move-out (BR-MOVEOUT-013) is not a recurring Service and does not approve a Monthly Cleaning Service.

Amended by DL-075 (owner, 2026-10-20): widened. Services are added in Settings by the Owner or a user with Settings access (DL-074), each with an English and a Khmer name, a Service type and a monthly rate. A Service type is "Only one per Lease" or "One or more per Lease"; changing a type to "Only one per Lease" is refused while a Lease holds two Services of that type, and a type that has Services cannot be removed. Trash Collection is chosen by default on a new Lease.

---

### BR-SVC-002 — Service Charge Independence

Service charges are independent of:

- Rent,
- Electricity,
- Water,
- Security Deposit,
- Pet Deposit.

Changes to one category shall not automatically affect another.

---

## 17.3 Service Billing

### BR-SVC-003 — Monthly Billing

Each active, approved, and applicable configured recurring Service is billed monthly
in advance as a separate line item on the applicable Rent Invoice. Trash Collection
is the current such Service.

For the Initial Service period under BR-SVC-012, that separate line appears on the
Initial Rent Invoice. Later normal recurring Service lines appear on the applicable
recurring Rent Invoice.

Separate Service Charge Invoices are not normally generated for these fixed
recurring monthly Services.

---

### BR-SVC-004 — Fixed Charges

An approved configured recurring Service uses its configured fixed monthly charge.

Their billing amount is not affected by:

- utility consumption,
- number of occupants,
- number of days within a normal full month.

The prorated move-in-month component of the Initial Service period uses actual
calendar days. Final and early-termination-month treatment follows the signed Lease
and approved termination rules and is not automatically prorated merely because the
Customer physically leaves during the month.

---

## 17.4 Service Rate Changes

### BR-SVC-005 — Service Rate Effective Date

Every service charge revision shall have an effective date.

The revised amount applies only to billing periods beginning on or after that effective date.

The applicable configured Service terms remain the source of truth.

Amended by DL-075 (owner, 2026-10-20): a new Service rate starts on the first day of a later month. Issued Invoices keep the old rate, and a new Service name shows only on new Invoices.

---

### BR-SVC-006 — Historical Service Rate Preservation

Historical service rates shall remain permanently preserved.

Changes to configured Service charges shall never modify historical Invoices.
The Service identity, Owner approval, configuration, active/inactive effective
periods, and rate history must remain reconstructable.

---

### BR-SVC-007 — Future Service Rate Changes

Revised service charges shall only affect future billing periods.

Completed billing periods shall always retain the original service charge used during billing.

---

## 17.5 Service Charge Integrity

### BR-SVC-008 — Historical Financial Integrity

Historical configured Service charges are permanent financial records.

They shall never be silently:

- deleted,
- recalculated,
- overwritten,
- replaced.

All revisions shall preserve complete historical traceability.

---

### BR-SVC-009 — Rent Invoice Line Items

Each fixed recurring Service is a separate categorized line item on the
applicable Rent Invoice. Its amount contributes to the Invoice total without
being reclassified as Rent.

The initial line is placed on the Initial Rent Invoice and covers the complete Initial
Service period under BR-SVC-012, including both components for a day-21-or-later
move-in.

---

### BR-SVC-010 — Line-level History

Each Service line preserves its Service identity, category, configured rate,
billing period, calculation when prorated, and final amount. A day-21-or-later Initial
Service line preserves both the prorated move-in-month component and the full following
month component without collapsing or obscuring either period.

---

### BR-SVC-011 — Advance Billing Schedule

Initial recurring-Service lines follow BR-SVC-012 and are issued on the Initial Rent
Invoice and share its Due Date under BR-RENT-009. After that initial coverage, fixed
recurring Services use the normal Rent billing cycle: generation on the 25th in the
Property's authoritative `Asia/Phnom_Penh` timezone for the upcoming uncovered month
and the same applicable Due Date as the recurring Rent Invoice.

Normal recurring generation resumes with the first complete calendar month after the
Initial Service period under BR-SVC-012. A scheduled run must not generate a Service
period already covered by that Initial Service period.

Amended by DL-075 (owner, 2026-10-20): the 25th is the Settings default issue day. A change starts with the next billing month.

---

### BR-SVC-012 — Initial Recurring-Service Period

Each explicitly approved, configured, active, and applicable recurring Service
follows the same Initial Invoice period structure as Rent.

For a Lease Start Date on day 1 through day 20 inclusive, its Initial Service
period covers the Lease Start Date through the last calendar day of the start month.

For a Lease Start Date on day 21 or later, its Initial Service period combines:

1. the prorated remainder of the start month; and
2. the entire following calendar month.

Each component uses the applicable approved configured Service rate for its period.
The prorated component uses the inclusive actual-calendar-day formula and final
half-up USD-cent rounding under BR-MONEY-012. The Service appears as a separate line
on the Initial Rent Invoice and therefore shares the Initial Rent Invoice Due Date under BR-RENT-009.

Example:

```text
Lease Start Date:           27 July
Initial Service coverage:  27–31 July, prorated
                           plus 1–31 August, full month
Initial Invoice Due Date:  1 August (proposed)
Normal generation resumes: 25 August for 1–30 September
Normal Due Date:            5 September
```

Initial and recurring Service periods must not overlap or duplicate one another.

---

### BR-SVC-013 — Final and Early-termination Month

Fixed recurring Services are not automatically prorated because physical
occupancy ends during a month. The applicable signed Lease and approved
termination rules control the valid final charge.

---

### BR-SVC-014 — Configured Services Only

Only a configured Property Service that applies under the governing terms may be
billed. The Service must also be active and actually provided for the billed period.
The system must not create a Service or charge from free-form Invoice entry.

---

### BR-SVC-015 — Configured Rate Source of Truth

Each fixed recurring Service line is calculated from its applicable configured
Service terms and rate. Staff must not replace that amount with an arbitrary
value. Issued corrections use the linked Adjustment rules.

---

# 18. Invoice Business Rules

## 18.1 Purpose

This section defines the business rules governing Invoice creation, Invoice lifecycle, billing categories, adjustments, voiding, duplicate billing prevention, and historical invoice preservation.

Invoices are the official financial documents representing amounts owed by Customers. Every Invoice forms part of the permanent financial history of the Property and shall remain fully auditable throughout its lifecycle.

---

## 18.2 General Invoice Principles

### BR-INV-001 — Invoice as the Official Financial Record

Every billable financial obligation owed by a Customer shall be represented by an Invoice.

Invoices serve as the official record of amounts due for services or charges provided by the Property.

Every Invoice has mandatory Customer ownership whether or not a Lease association
applies.

---

### BR-INV-002 — Invoice Ownership

Every Invoice shall belong to exactly one Customer.

An Invoice may additionally be associated with zero or one Lease when the billed
obligation arises from that Lease.

When a Lease association exists, the Invoice Customer must not contradict the
Customer responsibility under that Lease, and all applicable Unit, contractual,
and billing facts must be consistent with it. The explicit Invoice Customer is
not replaced by the Lease association.

An Invoice without a Lease still requires an approved governing business event.
Optional Lease association does not approve a new Invoice Category or charge.

A Customer may have multiple Invoices.

---

### BR-INV-003 — Invoice Identification

Each Invoice shall have a unique business identifier.

Once issued, the Invoice identity shall never be reused or reassigned.

---

### BR-INV-004 — Invoice Date

Every Invoice shall record the official Invoice Date representing when the financial obligation was created.

The Invoice Date forms part of the permanent financial record.

---

### BR-INV-005 — Billing Period

Where applicable, an Invoice shall record the billing period it represents.

Examples include:

- Monthly Rent
- Electricity
- Water
- each applicable approved and configured recurring Service

Invoices that do not represent a recurring billing period (such as Damage Charges) may omit a billing period where appropriate.

When the Invoice is associated with a Lease, its billing period must not
contradict that Lease. A billing period does not by itself make Lease association
mandatory.

---

## 18.3 Invoice Categories

### BR-INV-006 — Supported Invoice and Line Categories

Every Invoice shall have exactly one primary supported Invoice Category, and
every Invoice line shall have exactly one supported line category:

- Rent
- Utilities
- Service Charges
- Damage Charges
- Miscellaneous Charges

An Invoice may contain more than one line category only where an approved rule
requires combined billing, such as fixed recurring Service lines on a primary
Rent Invoice. No additional category is approved by this rule.

---

### BR-INV-007 — Deposit Exclusion

Security Deposits and Pet Deposits are liabilities held by the Property.

Deposits are **not** Invoice Categories and shall never be billed as ordinary Invoices.

Deposit collection and application are governed by their own business rules.

---

### BR-INV-008 — Category Integrity

The primary Invoice Category and each line's category determine their applicable
source-of-truth rules. Every line must preserve its category and source
independently.

Changing the primary Invoice Category or a line category after issuance is not
permitted.

---

## 18.4 Invoice Status Lifecycle

### BR-INV-009 — Standard Invoice Statuses

An Invoice shall exist in one of the following statuses:

- DRAFT
- UNPAID
- PARTIALLY_PAID
- PAID
- VOID

---

### BR-INV-010 — Draft Invoice

A newly created Invoice shall initially have the status:

- DRAFT

A DRAFT Invoice may be reviewed and corrected before issuance. If it is abandoned
or invalidated, it becomes VOID with a reason; it is not deleted or described as
cancelled.

A DRAFT Invoice is not a Customer receivable, does not increase Accounts
Receivable, is excluded from outstanding balances, and cannot make a Customer
overdue.

---

### BR-INV-011 — Invoice Issuance

When a Draft Invoice is officially issued to the Customer, its status shall become:

- UNPAID

Once issued, the Invoice becomes an official financial document.

The original Invoice Date, Invoice Number, Invoice Amount, and Billing Period become part of the permanent financial history.

Approved deterministic scheduled billing may generate and issue an Invoice
without manual approval of an intermediate DRAFT. Manual or exceptional charges
may remain DRAFT for review.

---

### BR-INV-012 — Partial Payment

When active Payment Allocations, Customer Credit applications, or authorized
Final Settlement Deposit applications reduce an issued Invoice but leave a
positive outstanding balance, its status shall become:

- PARTIALLY_PAID

For an Invoice with multiple lines or obligation categories, confirmed applications
reduce the identified underlying balances and roll up to the Invoice outstanding
balance. For example, applying $300 to the Rent line of a $500 Rent plus $10 recurring
Service Invoice leaves $200 Rent and $10 Service, so the Invoice outstanding balance is
$210 and the status is PARTIALLY_PAID.

---

### BR-INV-013 — Fully Paid

When active Payment Allocations, Customer Credit applications, or authorized
Final Settlement Deposit applications reduce the outstanding balance to exactly
zero, the Invoice status shall become:

- PAID

The Invoice may become PAID only when all of its underlying line or obligation balances
roll up to zero. A separate Late-payment Charge balance does not affect the source
Invoice's status.

---

### BR-INV-014 — Void

An Invoice may become:

- VOID

only through an authorized business process.

Voiding an Invoice permanently ends its billing lifecycle while preserving its historical record.

VOID is a controlled exceptional mechanism for an Invoice that fundamentally
should not exist. It is not the normal method for correcting an amount.

---

### BR-INV-015 — Allowed Invoice Status Transitions

Invoices shall transition only through the business-approved lifecycle shown below.

```text
DRAFT
 ├──► UNPAID
 └──► VOID

UNPAID
 ├──► PARTIALLY_PAID
 ├──► PAID
 └──► VOID

PARTIALLY_PAID
 ├──► UNPAID (after authorized allocation/application reversal)
 ├──► PAID
 └──► VOID (only after all active financial applications and dependencies have been
           resolved through their explicit approved processes under BR-INV-024)

PAID
 ├──► PARTIALLY_PAID (after authorized allocation/application reversal)
 └──► UNPAID (after authorized allocation/application reversal)

VOID
 └──► (Terminal state)
```

Any transition not shown above shall be rejected. UNPAID, PARTIALLY_PAID, and
PAID are determined by the current adjusted obligation and active financial
applications; they must be recomputed after an authorized reversal or
Adjustment.

The regressions `PARTIALLY_PAID → UNPAID`, `PAID → PARTIALLY_PAID`, and
`PAID → UNPAID` are permitted only as derived consequences of authorized financial
reversals or corrections that change valid remaining applications/allocations. They
must never represent manual status editing, partial Invoice voiding, partial Refund
semantics, arbitrary reopening, or a Refund represented merely by changing status.
VOID remains a separate action under BR-INV-014.

An Invoice that has received one or more Payments shall not be VOID until all associated Payment allocations have been properly reversed in accordance with the Payment business rules.

Financial corrections shall be performed through approved adjustment, reversal, or correction procedures while preserving the complete audit history.

---

## 18.5 Invoice Creation Rules

### BR-INV-016 — Invoice Creation

Invoices may be created through approved business events, including:

- recurring Rent billing,
- Utility billing,
- recurring Service Charges,
- Damage Charges,
- Miscellaneous Charges.

Every Invoice shall originate from a legitimate business event.

It must identify exactly one Customer. It identifies a Lease only when the
governing obligation is associated with that Lease.

Amended by DL-103 (owner, 2026-10-28): one Miscellaneous Invoice made with Create Invoice may hold 1 to 20 items. Each item is its own approved one-time charge with a whole quantity and a unit price in US cents, and its amount is exactly the quantity times the unit price, with no rounding. All items share one reason and one approval. While the Invoice is a Draft its items may be changed with a reason for the change; it gets one Invoice number and one Due Date when it is issued.

---

### BR-INV-017 — Invoice Amount

The Invoice Amount shall equal the total charges represented by that Invoice at the time it is issued.

Once issued, the original Invoice Amount forms part of the permanent financial history.

---

### BR-INV-018 — Due Date

Every issued Invoice has exactly one Due Date; a DRAFT may have none. Recurring Due
Dates follow their approved billing rules, and the Initial Rent Invoice follows
BR-RENT-009. For a one-time Damage or Miscellaneous charge created manually by
authorized staff, and for the final Utility Invoice under BR-UTIL-021, the system
proposes a Due Date of the issue date plus the Property's configured number of calendar
days, seven by default. An authorized user may set a different Due Date with a mandatory
reason; the actor and timestamp are recorded. The Due Date is fixed once issued. Debit
Adjustments use their Invoice's Due Date under BR-INV-044.

Amended by DL-075 (owner, 2026-10-20): the configured number of days is the Settings "days after issue" (1 to 90, default 7), which applies at once to Invoices issued after the change. The move-out cleaning charge, move-out Damage Charges and the final Utility Invoice are due 7 days after issue (Lease Article 14.3), whatever the setting says; the authorized override with a mandatory reason stays.

---

## 18.6 Invoice Adjustments

### BR-INV-019 — Adjustment Principle

If an issued Invoice contains an error, the correction shall preserve the complete financial history.

Historical financial records shall never be silently modified.

---

### BR-INV-020 — No Silent Modification

After issuance, the following shall never be silently changed:

- Invoice Amount
- Invoice Date
- Billing Period
- Invoice Category

Any correction shall remain fully auditable.

---

### BR-INV-021 — Linked Adjustment Method

A legitimate correction to the financial amount of an issued Invoice must use an
explicit linked debit or credit Adjustment.

The Adjustment changes the current financial obligation without replacing the
original Invoice amount or contractual source. It must identify the original
Invoice, reason, amount, authorization, actor, and time.

---

## 18.7 Invoice Voiding

### BR-INV-022 — Authorized Voiding

Only authorized personnel may void an Invoice.

The reason for voiding shall be recorded.

VOID is permitted only when the Invoice fundamentally should not exist. Amount
corrections normally use BR-INV-021.

---

### BR-INV-023 — No Physical Deletion

Voiding an Invoice shall never physically remove it from the financial history.

The original Invoice shall remain permanently available for audit purposes.

---

### BR-INV-024 — Restrictions on Voiding Paid Invoices

An Invoice that has received one or more Payments shall not be voided directly.

Active Allocations, Customer Credit applications, Refunds, Adjustments, and other
financial dependencies must first be resolved through their explicit approved
processes before VOID may proceed.

---

### BR-INV-025 — Historical Preservation

Voided Invoices remain part of the permanent financial records of the Property.

---

## 18.8 Duplicate Billing Prevention

### BR-INV-026 — Duplicate Rent Billing

The business shall prevent multiple Rent Invoices covering the same Lease and the same rental period.

---

### BR-INV-027 — Duplicate Utility Billing

The business shall prevent utility consumption from being billed more than once.

The same Unit, Utility Type, and consumption period shall not produce duplicate
Utility billing. Applicable Customer and optional Lease association must be
consistent and must not be varied to bypass this rule.

---

### BR-INV-028 — Duplicate Service Charge Billing

The business shall prevent any approved and configured recurring Service Charge from
being billed multiple times or for overlapping coverage for the same Lease and
Service. Normal generation must skip every period already included in the Initial
Service period under BR-SVC-012.

---

### BR-INV-029 — Duplicate Invoice Prevention Principle

The application shall reject any Invoice that would create duplicate billing for the same financial obligation.

Examples include:

- duplicate Rent for the same billing period,
- duplicate Electricity billing for the same consumption period,
- duplicate Water billing for the same consumption period,
- duplicate or overlapping configured Service coverage for the same Lease and Service.

The governing source facts define duplicate identity. An obligation must not be
billed once with a Lease association and again without one.

---

## 18.9 Historical Invoice Integrity

### BR-INV-030 — Permanent Financial Record

Every issued Invoice forms part of the permanent accounting history of the Property.

---

### BR-INV-031 — Historical Preservation

Issued Invoices shall never be silently:

- deleted,
- overwritten,
- reused,
- recreated with the same identity.

---

### BR-INV-032 — Historical Accuracy

Historical Invoices shall permanently preserve:

- Invoice Number,
- Invoice Date,
- Invoice Category,
- Billing Period,
- Original Charges,
- Due Date,
- Payment History,
- Final Status.

The Invoice must also preserve its Customer owner and the exact Lease association
or absence of Lease association that applied when issued.

These values represent the official historical financial record.

---

### BR-INV-033 — Independence from Future Changes

Future changes to:

- Rent,
- Utility Rates,
- Service Charges,
- Customer Information,
- Lease Information,
- Utility Meters,

shall never modify previously issued Invoices.

Historical Invoices shall always reflect the business facts that existed at the time they were issued.

Future changes must not retroactively add, remove, or replace an Invoice's Lease
association or Customer ownership.

---

## 18.10 Business Rule Enforcement

### BR-INV-034 — Financial Integrity

Every Invoice-related business action shall preserve:

- financial accuracy,
- auditability,
- traceability,
- historical integrity.

The application shall reject any action that compromises the integrity of the Property's financial records.

---

### BR-INV-035 — Audit Requirement

Every significant Invoice event shall be fully auditable, including but not limited to:

- Invoice creation,
- Invoice adjustment,
- Invoice voiding,
- status changes,
- due date revisions (where permitted),
- payment allocation changes.

Historical audit information shall remain permanently available and shall never be silently removed.

---

### BR-INV-036 — Mandatory Customer Ownership

Every Invoice has exactly one explicit Customer owner from creation through
historical preservation. Customer ownership is required independently of whether
a Lease association exists.

---

### BR-INV-037 — Optional Lease Association

An Invoice may be associated with zero or one Lease. A Lease is recorded only
when applicable to the governing obligation and never substitutes for mandatory
Customer ownership.

---

### BR-INV-038 — Lease Association Consistency

When a Lease is associated, the Invoice Customer must be a Customer financially
responsible under that Lease. Applicable Unit, period, Rent, Service, and other
contractual facts must not contradict the Lease.

Choosing one Invoice Customer does not remove the joint Lease responsibility of
other Lease Signers. Lease association must not be added or removed to evade
source, duplicate, allocation, or settlement validation.

---

### BR-INV-039 — Mixed Line-item Integrity

A Rent Invoice may include separately categorized fixed recurring Service lines.
Each line preserves its category, source, rate, calculation, and amount. Combined
billing must not reclassify a Service line as Rent.

---

### BR-INV-040 — Rent Invoice Source of Truth

A Rent Invoice requires a valid applicable signed Lease covering the rental
period. The Invoice Customer and Unit must be valid in that Lease context, and
contractual Rent must come from the Lease.

This Rent-specific requirement does not make Lease association mandatory for all
Invoices.

---

### BR-INV-041 — Utility Invoice Source of Truth

Utility charges come only from validated actual Meter Readings or the authorized
broken-Meter estimate, multiplied by the generation-date Utility Rate. Customer,
Unit, Meter, consumption period, and optional Lease association must be mutually
consistent.

Staff must not enter an arbitrary replacement Utility amount.

---

### BR-INV-042 — Fixed Service Source of Truth

Fixed recurring Service lines come from configured Service terms and rates. When
included with Rent, they use the same applicable Customer and Lease context as
the Rent Invoice.

---

### BR-INV-043 — DRAFT Correction

Before issuance, source data and calculations on a DRAFT Invoice may be corrected
subject to audit. DRAFT correction must not create Accounts Receivable or erase
the record.

---

### BR-INV-044 — Linked Debit and Credit Adjustments

Issued amount corrections use explicit linked debit or credit Adjustments.
Original Invoice values and contractual terms remain unchanged.

An Adjustment is recorded against one line of an issued Invoice and uses that Invoice's
single Due Date. Invoice lines have no Due Dates of their own.

A debit Adjustment is allowed only while its line has a positive remaining balance. It
is rejected once the line is fully paid; a missed amount on a fully paid line is billed
as a normal one-time Miscellaneous or Damage Charge. A Payment or Credit reversal that
restores a positive balance on the line allows debit Adjustments again.

A credit Adjustment is allowed on any issued, non-VOID Invoice line. Any credit beyond
that line's remaining balance becomes Customer Credit for the Invoice Customer.

---

### BR-INV-045 — Adjustment Source and Linkage

Every Adjustment preserves its original Invoice, source obligation, amount,
reason, authorization, actor, and time. It follows the corrected obligation's
actual Customer and optional Lease context and must not manufacture a Lease
association for a non-Lease Invoice.

---

### BR-INV-046 — Exceptional VOID

VOID is available only when an Invoice fundamentally should not exist. It is not
the ordinary amount-correction method, and it never removes the original record.

When a Lease is terminated and the tenant never moved in under BR-LEASE-005, an Initial
Rent Invoice with nothing paid is VOIDed with a mandatory reason. A partly paid one is
not VOIDed; its unpaid remainder is removed by a linked credit Adjustment.

---

### BR-INV-047 — Financial Dependency Preservation

Active Allocations, Customer Credit applications, Refunds, Adjustments, and other
linked financial events must be resolved through explicit processes. Nothing may
be silently deleted, detached, or reassigned to permit VOID or correction.

---

### BR-INV-048 — Correction Authorization and Reason

An issued-Invoice correction requires appropriate authorization, a mandatory
reason, timestamp, user identity, preserved original values, and linkage between
the source and correction.

---

### BR-INV-049 — Non-recurring Due Date Source

The Due Date of a one-time Damage or Miscellaneous charge follows BR-INV-018. It no
longer has to come from a governing Lease provision, event or document. A debit
Adjustment has no Due Date of its own and uses its Invoice's Due Date under BR-INV-044.

---

### BR-INV-050 — Deterministic Scheduled Issuance

Approved scheduled billing may generate and issue Invoices automatically from
deterministic source rules. Rent and its fixed recurring Service lines require an
applicable signed Lease. Other Invoices follow their approved source rules.

---

### BR-INV-051 — Due Date and Overdue Boundary

An applicable source Invoice is an issued Invoice for Rent or another amount payable
under the signed Lease under BR-RENT-029. Its stated Due Date is the last calendar day
on which payment is timely. Payment received on that Due Date is not late.

In the Property's authoritative business timezone, `Asia/Phnom_Penh`, any positive
remaining unpaid balance becomes overdue on the next calendar day after the Due Date.
There is no additional ten-day grace period.

Example:

```text
Due Date:                     5 August
Payment received 5 August:   On time
Remaining balance 6 August:  Overdue and eligible for proposal
```

Eligibility does not automatically post a charge.

The Initial Rent Invoice is not an applicable source Invoice for a late-payment charge.

Amended by DL-076 (owner, 2026-10-20): "Eligibility does not automatically post a charge" is replaced: at 00:00 Property time on the first day after the Due Date, the app adds the late-payment charge by itself, at the Settings rate (DL-075, default 10%) of the amount unpaid at that moment, rounded half-up; no management decision is needed.

---

### BR-INV-052 — Invoice-wide Late-payment Calculation

At assessment, the default late-payment charge is calculated once against the total
remaining unpaid overdue balance of the applicable source Invoice as a whole:

```text
Default Late-payment Charge
=
Remaining Unpaid Overdue Source-Invoice Balance at Assessment
×
10%
```

The balance reflects valid financial applications and allocations in effect at
assessment. Amounts already validly paid or otherwise validly applied must not be
charged again. The system must not calculate separate late-payment percentages for
individual lines of the same applicable overdue Invoice. The final USD result uses
the general half-up cent rounding rule in BR-MONEY-012.

Example:

```text
Rent:                                      $500
Trash Collection:                          $10
Electricity:                               $80
Water:                                     $20
Original source-Invoice total:             $610

If remaining unpaid overdue balance:       $610
Default late-payment charge at 10%:         $61

If valid Payments already applied:         $300
Remaining unpaid overdue balance:          $310
Default late-payment charge at 10%:         $31
```

Amended by DL-076 (owner, 2026-10-20): the rate is the Settings rate (DL-075, default 10%), and the calculation is made once by the app at 00:00 on the first day after the Due Date.

---

### BR-INV-053 — Authorized Late-payment Decision

The system detects the overdue source Invoice, calculates and presents the proposed
default charge, and flags it for authorized management. It must not post the charge
automatically merely because the Due Date has passed.

Authorized management makes one final decision for the source Invoice:

- confirm the default 10% charge;
- approve a reduced charge below the 10% default; or
- waive the charge, equivalent to 0% and $0.

Management must not increase the contractual percentage or approved amount above the
10% default calculation. Ordinary staff must not arbitrarily change the percentage
or amount.

The decision preserves at minimum the source Customer, source Invoice, source Invoice
Due Date, remaining overdue balance at assessment, default percentage, actual approved
percentage, calculated default amount, actual approved amount, decision outcome,
authorized management actor, reason, assessment timestamp, and confirmation or waiver
timestamp.

Replaced by DL-076 (owner, 2026-10-20): no management decision. At 00:00 Property time on the first day after the Due Date, the app adds the late-payment charge by itself, at the Settings rate (DL-075, default 10%) of the amount unpaid at that moment, rounded half-up; no management decision is needed. The Owner or a Manager may only reduce or waive it after the Customer complains that it is wrong because of a staff mistake, with one of three fixed reasons ("Staff recorded the payment on the wrong Invoice", "Paid on time but recorded late", "Other staff mistake") and a required "What happened" text. The amount only goes down.

Built in V1-056 slice 11g-1 (DL-085): the billing worker runs the charge pass after its billing runs, under the same lock, as the Property's billing service principal. Owner answer of 2026-10-25 ("No charge"): an Invoice already overdue on the day the pass first runs gets no charge. Readings recorded: an Invoice issued after its charge moment gets no charge; a missed day is caught up by the next pass with the amount unpaid at that day's 00:00; an Invoice of a Lease whose Final Settlement is closed gets no charge (BR-SETTLE-012); a charge that rounds to zero writes nothing. The database itself refuses a charge for a day before the pass's first day. The pass starts 10 seconds after 00:00; the amount is the one unpaid at 00:00, because a payment allocation dated before an earlier charge decision is refused.

---

### BR-INV-054 — One Final Non-compounding Decision per Invoice

Each applicable source Invoice may have only one final late-payment decision. A
confirmed default charge, reduced charge, or waiver is final for that source Invoice.

The late-payment charge must not repeat daily, weekly, monthly, or on any other
cadence. It must not compound, generate another late-payment charge, or create a
recursive penalty. Continued nonpayment of the source principal does not reopen the
decision. A reduced charge must not later be supplemented with the difference, and a
waiver must not later be replaced by a charge. Payment received after the final
decision does not recalculate or replace that decision.

The Invoice is locked while an Adjustment or the final late-payment decision is
recorded, so the two are strictly ordered. An Adjustment recorded before the final
decision is included in that decision's balance. A debit Adjustment recorded after the
final decision is allowed but is not counted in that decision, and a credit Adjustment
never changes a final decision.

Example: if the default is $31 and management approves $15, the remaining $16 must
never be imposed as a second late-payment charge for that source Invoice.

Amended by DL-076 (owner, 2026-10-20): one automatic charge per Invoice replaces the one final decision; money paid later does not change it. A reduction or waiver never raises it.

---

### BR-INV-055 — Explicit Linked Late-payment Financial Record

A final late-payment decision is a permanent auditable business event linked to its
source Invoice. A positive approved amount must remain an explicit linked auditable
financial charge and must not be hidden in an undifferentiated entry.

The source Invoice's original principal, lines, and issued amount must not be silently
altered to incorporate the charge. A confirmed positive amount creates the separate
Late-payment Charge obligation defined by BR-LATE-001. It does not create another
Invoice, Invoice Category, Miscellaneous Charge, or historical source-Invoice line. A
waiver records the final decision and audit history without creating a receivable.

Amended by DL-076 (owner, 2026-10-20): the linked record is the automatic charge and its reductions and waivers; history keeps every change.

---

### BR-LATE-001 — Positive Late-payment Charge Obligation

Authorized management confirmation of a positive default or reduced amount creates
exactly one separate Late-payment Charge obligation. It belongs to exactly one Customer
and links to exactly one source overdue Invoice and its final late-payment decision.
The obligation Customer must be the source Invoice Customer.

The obligation is part of the Customer's overall outstanding balance but is not an
Invoice and does not affect the source Invoice's principal, lines, outstanding balance,
or derived status.

Amended by DL-076 (owner, 2026-10-20): the app creates the charge by itself (DL-076); no management confirmation.

---

### BR-LATE-002 — Immediate Payability

A positive Late-payment Charge becomes payable immediately at its management
confirmation timestamp. It requires no new Invoice and no Invoice Due Date. Its
confirmation timestamp is the date and time the obligation becomes payable.

Amended by DL-076 (owner, 2026-10-20): the charge is payable at once from the moment the app adds it (00:00 on the first day after the Due Date).

---

### BR-LATE-003 — Waived and Reduced Decisions

A WAIVED or equivalent final outcome preserves the proposal and waiver decision and
creates no positive receivable. A REDUCED or equivalent final outcome creates only the
approved reduced Late-payment Charge amount. The waived or reduced difference must
never be added later for that source Invoice.

Amended by DL-076 (owner, 2026-10-20): a reduction or waiver is made after the charge exists, by the Owner or a Manager after a Customer complaint of a staff mistake; a paid charge may still be reduced or waived, and paid money above the new amount goes to Customer Credit under BR-CREDIT-014.

---

### BR-LATE-004 — Remaining Balance and Satisfaction

The original confirmed Late-payment Charge amount remains historically unchanged. Its
remaining outstanding balance equals that original amount less valid Payment
Allocations and Customer Credit applications, adjusted only by explicit authorized
reversals or corrections. The remaining balance cannot become negative.

A zero remaining balance means the obligation is fully satisfied. No additional manual
status lifecycle is required, and no Late-payment Charge balance affects the source
Invoice's balance or status.

---

### BR-LATE-005 — Explicit Correction and Reversal

If a confirmed Late-payment Charge later requires correction or reversal, the original
decision and obligation remain permanent. An authorized linked correction or reversal
records the reason, actor, date/time, previous amount or balance, resulting amount or
balance, and all affected applications. Silent deletion or rewriting is prohibited.
Correction must obey the approved maximum and final-decision rules and must not be used
to supplement a reduced charge or replace a waived decision.

Amended by the owner's answer to Q-2026-10-07-38 (2026-10-07): after the Lease's Final Settlement is closed, a Late-payment Charge correction is made only as a post-settlement correction (BR-SETTLE-013). When the corrected Charge was paid, the released value follows BR-CREDIT-014.

Built in V1-056 slice 11g-2 (DL-086; DL-076 answer 4): before the Final Settlement is closed, the Owner or a Manager (`late_payment.charge_correction`) reduces or waives a charge with one of three fixed reasons and a "What happened" text; the amount only goes down. Paid value above the new amount is released at once: the paying Payment allocations and Credit applications are reversed whole, newest first, their unreleased rest is posted again to the charge, released Payment value becomes Customer Credit of the charge's Customer (BR-CREDIT-014) and released Credit value returns to its Credit. A charge a Deposit application paid is refused; after closure this command is refused and the post-settlement corrections apply.

Built in V1-056 slice 11g-3 (DL-087; DL-076 answers 1 and 4): from the Property's first finished automatic pass on, a person's late-payment decision is refused and the charge changes only by a reduction or waiver with a fixed reason (BR-LATE-005 as built in 11g-2); a free reduction, a free waiver and a reduction reversal (which would raise the amount) are refused. Decisions and corrections recorded before stay as history.

---

### BR-LATE-006 — No Recursive Charge

A proposed, confirmed, reduced, waived, partially satisfied, fully satisfied, corrected,
or reversed Late-payment Charge must never itself be assessed for another late-payment
charge.

# 19. Payment Rules

## 19.1 Purpose

This section defines the business rules governing Payments received from Customers, including payment creation, payment methods, payment statuses, payment allocation, and historical preservation.

A Payment represents money received by the Property from a Customer. A Payment does not automatically settle an Invoice until it has been allocated according to the approved business process.

---

## 19.2 General Payment Principles

### BR-PAY-001 — Payment Ownership

Every Payment shall identify exactly one payer Customer.

A Customer may have multiple Payments throughout their business relationship with the Property.

A third-party payer does not become a financially responsible Customer under a
Lease merely by making the Payment.

---

### BR-PAY-002 — Lease Association

A Payment may optionally be associated with a Lease.

Lease association provides business context but does not determine how the Payment is allocated.

Payments received before Move-in or after Lease termination may not have an associated Lease.

For a third-party Payment, an optional Lease or Invoice designation records the
payer's identified intent and must not be treated as ownership of that obligation.

---

### BR-PAY-003 — Payment Represents Money Received

A Payment records the receipt of funds from a Customer.

A Payment itself does not determine which Invoice has been paid.

An Invoice balance may be settled through authorized Payment Allocations, Customer
Credit applications, or Final Settlement Deposit applications under the applicable
rules. Recording a Payment settles no Invoice until value from that Payment is
explicitly allocated.

Payment, Receipt, Payment Allocation, Payment Reversal, Customer Credit, and
Refund are separate financial concepts and events.

---

### BR-PAY-004 — Unique Payment Identification

Every Payment shall have a unique business identifier.

Once assigned, the Payment identifier shall never be reused or modified.

---

### BR-PAY-005 — Payment Date

Every Payment shall record the official Payment Date representing the date the Property received the funds.

The Payment Date forms part of the permanent financial history.

For a KHR Payment, confirmation of receipt is also the event at which the
applicable exchange rate is selected and preserved.

---

## 19.3 Supported Payment Methods

### BR-PAY-006 — Configurable Payment Methods and Currencies

Accepted Payment Methods are configured business data and are not hard-coded by
this document. Only a currently accepted configured method may be used.

Supported Payment currencies are USD and KHR under BR-MONEY-002.

Amended by DL-075 (owner, 2026-10-20): Payment Methods are added, edited and turned off in Settings. Each method says whether it needs a reference. A method used on a Receipt is never deleted, only turned off. At least one method stays on, and only methods that are on can be chosen.

---

### BR-PAY-007 — Payment Method Preservation

The Payment Method recorded when the Payment is received shall remain permanently preserved.

Historical Payments shall never be modified solely because a Payment Method is renamed or retired.

The Payment currency and, for KHR, all exchange and source values must likewise
remain permanent.

---

## 19.4 Payment Status

### BR-PAY-008 — Payment Record Statuses

Payment record status may be only:

- RECEIVED
- REVERSED

Allocation progress is derived from active Allocation records. Refund is a
separate financial event and is not a Payment status.

---

### BR-PAY-009 — Initial Status

A newly received Payment shall initially have the status:

- RECEIVED

---

### BR-PAY-010 — Partially Allocated

When active Allocations use part, but not all, of a RECEIVED Payment's available
USD accounting value, the Payment is partially allocated as a derived condition.
Its Payment record status remains RECEIVED.

---

### BR-PAY-011 — Fully Allocated

When active Allocations use the Payment's entire available USD accounting value,
the Payment is fully allocated as a derived condition. Its Payment record status remains
RECEIVED.

No remaining unallocated balance shall exist.

---

### BR-PAY-012 — Reversed

A Payment becomes REVERSED only through an authorized explicit Payment Reversal
event linked to the original Payment.

A reversed Payment shall remain permanently preserved for audit purposes.

All active Allocations and any Customer Credit recognition sourced from the
Payment must first be reversed through their explicit linked processes. A
completed Refund sourced from the Payment prevents reversal unless an authorized
linked correction first resolves that Refund without rewriting history.

A Payment Reversal recomputes every affected Invoice balance and status.

---

### BR-PAY-013 — Refund Is Separate From Payment

Returning money uses a separate linked Refund event. A Refund does not change the
original Payment amount, erase its Allocations, or create a REFUNDED Payment
status.

---

## 19.5 Allowed Payment Status Transitions

### BR-PAY-014 — Payment Lifecycle and Allocation Condition

The permitted Payment lifecycle is:

```text
RECEIVED -> REVERSED
REVERSED -> terminal
```

Posting or reversing Allocations changes the derived allocated and unallocated
amounts without changing RECEIVED status. A Refund follows its source-specific
rules and does not require falsifying the original Payment lifecycle.

---

## 19.6 Payment Integrity

### BR-PAY-015 — Payment Amount

The original Payment Amount represents the amount of money received from the
payer in its received currency.

Once recorded, the original Payment Amount shall never be silently modified.

---

### BR-PAY-016 — No Physical Deletion

Payments form part of the permanent financial history.

Payments shall never be physically deleted.

---

### BR-PAY-017 — Historical Preservation

Historical Payments shall permanently preserve:

- Payment Number
- Customer
- Lease (if applicable)
- Payment Date
- Payment Method
- Received Currency and Original Amount
- USD accounting value
- KHR amount and exact exchange information when applicable
- Current Status
- payer intent or designation when applicable

These values constitute the official financial record.

Amended by DL-071 (owner, 2026-10-20; answer 10b): a Payment has one Receipt, and the Payment Number is that Receipt's number, for example `RCP260001` (type code, 2-digit year of the confirmation date, 4-digit running number). This replaces the separate Payment Number. Not built yet.

---

### BR-PAY-018 — Audit Requirement

Every significant Payment event shall be fully auditable, including:

- Payment creation
- Payment record-status changes
- Receipt issuance and reprint
- Allocation changes
- Reversal
- Refund

Historical audit information shall never be silently removed.

---

## 19.7 Receipt Rules

### BR-RECEIPT-001 — Receipt Acknowledges Payment

A Receipt is the numbered customer-facing acknowledgment that money was received under
one existing Payment. Receipt does not replace Payment, create Payment, settle an
obligation independently, or serve as the authoritative receipt-of-money event.

---

### BR-RECEIPT-002 — Receipt Identity and Source

Every Receipt has a unique Receipt Number and identifies exactly one source Payment and
that Payment's payer Customer. One Payment normally produces one business Receipt.
Persistence of safely derived display fields is decided by `004_DATABASE_MODEL.md`.

Amended by DL-071 (owner, 2026-10-20; answer 10): the Receipt Number is `RCP`, the 2-digit year of the confirmation date in the Property's local time and a 4-digit running number that restarts at 0001 each year, with no dashes or spaces (for example `RCP260001`); it grows to 5 digits after 9999 and is never reused. It is also the Payment Number. Not built yet.

---

### BR-RECEIPT-003 — Customer-facing Content

A Receipt may present, as applicable, its Receipt Number, Payment, Customer, Payment
Date, Payment Method, received currency and amount, USD accounting value, KHR conversion
details, confirmed Invoice-line or other obligation applications, Late-payment Charge
amount paid, Deposit purpose, allocation/application breakdown, issuer, and issue time.

Every presented amount and application must be traceable to the immutable Payment and
linked authoritative Allocation, Credit-application, Deposit, or obligation records.

---

### BR-RECEIPT-004 — Reprint Is Not New Money

Reprinting a Receipt preserves the same original Receipt Number, source Payment,
Customer, and business identity. A reprint must not create a second Payment, duplicate
the received amount, or represent another receipt of money. The reprint event, actor,
and date/time remain auditable.

---

### BR-RECEIPT-005 — Receipt History

Receipt issuance and reprint history must remain reconstructable. Correction of a
Payment or Allocation uses the applicable explicit correction or reversal process and
must not silently rewrite or delete the original Receipt history.

---

### BR-RECEIPT-006 — Refund Remains Separate

A Receipt acknowledges inbound money. A Refund remains a distinct outbound financial
event under BR-REFUND-001 and must not be represented as a negative Payment or as
deletion or rewriting of the original Payment or Receipt. This rule creates no separate
Refund-receipt document.

---

# 20. Payment Allocation Rules

## BR-PAY-019 — Allocation Is a Separate Financial Event

A Payment Allocation links part of one RECEIVED Payment's USD accounting value to one
or more identified obligations belonging to the applicable Customer. A target may be
an issued Customer Invoice with sufficient Invoice-line or obligation-category detail,
or a separate confirmed Late-payment Charge. It does not rewrite any source record.

A Deposit receipt remains the separate Payment-to-Deposit link in BR-DEP-005 and is not
silently converted into an ordinary Payment Allocation. Customer Credit, unallocated
Payment, Refund, and Deposit balances likewise remain distinct.

---

## BR-PAY-020 — Manual Authorized Posting

Payment Allocation is manual and performed by authorized staff. The system may
calculate and present a proposal, but it must not post that proposal without
authorized staff confirmation.

Amended by DL-077 (owner, 2026-10-20): pressing Receive payment is the staff confirmation. The app ticks the proposal when the amount is entered, and one command saves the Payment and its Allocations in one database transaction. There is no "match later" while the Customer owes anything.

---

## BR-PAY-021 — Deterministic Default Proposal

When the payer has not designated a specific Invoice, the system proposes
allocation across the applicable outstanding Invoices using the approved FIFO
rules.

---

## BR-PAY-022 — Oldest-due Ordering

The default proposal applies value to the oldest Due Date first and continues
through applicable outstanding Invoices until the Payment is exhausted or all
applicable outstanding Invoices are satisfied.

No line-category preference may reorder the selected Invoices. After an Invoice is
selected, the within-Invoice rules in BR-PAY-036 apply.

---

## BR-PAY-023 — Deterministic Ties

Invoices with the same Due Date are ordered by Invoice issue or generation order
and then by a stable Invoice sequence or identifier.

---

## BR-PAY-024 — Customer-designated Allocation

When the Customer explicitly identifies a valid Invoice, Invoice line or obligation
category, or separate Late-payment Charge, authorized staff may post the Payment to
that valid designated target instead of the applicable default proposal. The Customer
designation and posted Allocation must be preserved.

---

## BR-PAY-025 — Normal Customer Scope

For a normal Customer Payment, the default proposal includes applicable
outstanding Invoices belonging to the financially responsible Customer,
including across that Customer's applicable Lease relationships where permitted
by the approved rules.

An Invoice without a Lease remains eligible when it belongs to that Customer and
is otherwise a valid applicable obligation.

Amended by the owner's answer to Q-2026-10-05-16 (2026-10-05): under BR-PAY-042, a confirmed wrong-Unit Payment move may allocate a normal Customer Payment to an Invoice of another Customer or outside the Payment's identified Invoice; only that move, or a credit Adjustment's re-post of such an allocation on the same Invoice, does so.

---

## BR-PAY-026 — Third-party Payment Scope

A third-party Payment follows the payer's identified Invoice or Lease intent. It
must not be automatically spread across unrelated obligations of either the payer
or another Customer.

The third-party payer does not become the Invoice Customer or a Lease Signer by
making the Payment.

For allocation purposes, a jointly responsible Lease Signer who is not the
Invoice Customer uses this designated-payment path. That treatment does not
remove or change the Signer's approved joint Lease responsibility.

Amended by the owner's answer to Q-2026-10-05-16 (2026-10-05): under BR-PAY-042, a confirmed wrong-Unit Payment move may allocate a third-party Payment outside its identified Invoice or Lease intent; only that move, or a credit Adjustment's re-post of such an allocation on the same Invoice, does so.

---

## BR-PAY-027 — Allocation Amount Limits

An Allocation must be positive and must not exceed either:

- the Payment's remaining unallocated USD accounting value; or
- the identified target obligation's current outstanding balance.

---

## BR-PAY-028 — No Negative Obligation Balance

Posting an Allocation must never cause an Invoice-line, Invoice, Late-payment Charge,
or other target obligation balance to become negative. Payment value beyond applicable
outstanding balances remains unallocated excess.

---

## BR-PAY-029 — Allocation History and Reversal

Every posted Allocation permanently preserves its Payment, target Invoice or other
obligation, Invoice-line or obligation category where applicable, allocated amount,
Customer designation if any, proposed default if any, posting time, and authorized
user confirmation. A correction uses an explicit linked Allocation Reversal and
recomputes affected line, obligation, Invoice, and Customer balances and derived
statuses; it never deletes or overwrites the original Allocation.

---

## BR-PAY-030 — True Overpayment

An overpayment exists only after all applicable outstanding obligations have been
handled and a positive amount remains unallocated from the Payment.

---

## BR-PAY-031 — Unallocated Excess

Unallocated excess remains part of the original RECEIVED Payment until the payer
chooses an approved disposition. It does not automatically become Customer
Credit.

Once excess is recognized as Customer Credit or committed to a Refund, that
disposed amount is excluded from the Payment's allocatable available value. The
original received Payment amount remains unchanged.

Amended by DL-077 (owner, 2026-10-20): money waits on the Receipt only when it is more than everything owed, or when nothing is owed; it is never called Credit before the Customer chooses Credit or a refund.

---

## BR-PAY-032 — Customer Coordination

When overpayment is identified, Property Management must coordinate with the
payer and ask whether the excess should be retained as Customer Credit or
refunded. The decision, amount, date and time, and user recording it must be
audited.

---

## BR-PAY-033 — Credit Choice

Only the amount the payer authorizes for retention may be recognized as Customer
Credit. The resulting Credit remains linked to the original Payment and belongs
to the recorded payer Customer.

Recognition of the Credit consumes that excess from the Payment's allocatable
available value without reducing or rewriting the original Payment amount.

Amended by DL-068 and DL-069 (2026-10-03): Customer Credit created from value released by a credit Adjustment belongs to the Customer named on the Lease and Invoice, even when a third party paid (BR-CREDIT-014).

---

## BR-PAY-034 — Refund Choice

When the payer requests return of the excess, the Refund workflow must link the
Refund to that original Payment and excess. The original Payment amount and every
Allocation remain unchanged.

The amount committed to the Refund is excluded from the Payment's allocatable
available value so that the same excess cannot be reused.

---

## BR-PAY-035 — No Early Future Invoice for Advance Money

An unallocated Payment or Customer Credit must not cause a future Rent Invoice to
be generated before its approved billing schedule merely to absorb advance
money.

---

## BR-PAY-036 — Within-Invoice Default Proposal

After the applicable Invoice is selected under BR-PAY-021 through BR-PAY-025, if that
Invoice contains Rent and recurring-Service lines and the Customer did not designate
the within-Invoice target, the system proposes value in this order:

1. Rent line or obligation;
2. then recurring-Service lines on that same Invoice.

This is a proposal only. Authorized staff must confirm it before posting under
BR-PAY-020. The system must not silently post the proposal.

Example: for $500 Rent plus $10 Trash Collection, an unspecified $300 Payment produces
a proposal of $300 to Rent, leaving $200 Rent and $10 Trash Collection. An unspecified
$505 Payment proposes $500 to Rent and $5 to Trash Collection, leaving Rent fully paid
and $5 Service outstanding. A $510 Payment proposes full satisfaction of both lines.

Amended by DL-103 (owner, 2026-10-28): on an Invoice of typed items (DL-103) the proposal pays the items from the top down, in the order they are listed on the Invoice. It is still a proposal that staff confirm.

---

## BR-PAY-037 — Customer-designated Within-Invoice Allocation

When the Customer clearly identifies a valid line or obligation category within a
mixed Invoice, authorized staff may confirm that designation instead of the default
within-Invoice proposal. The designation, confirmed target, amount, actor, and date/time
must be preserved.

---

## BR-PAY-038 — Between-Invoice FIFO Remains First

When the Customer has not designated an Invoice, the system first proposes applicable
Invoices by oldest Due Date and the existing deterministic tie-breakers in BR-PAY-022
and BR-PAY-023. BR-PAY-036 then orders lines only within each selected mixed Invoice.
Rent-first within one Invoice must not reorder multiple Invoices.

---

## BR-PAY-039 — Invoice Rollup and Rent Determination

Confirmed Payment Allocations reduce their identified Invoice-line or obligation
balances. Those remaining balances roll up exactly to the Invoice outstanding balance
and its derived status under BR-INV-012 and BR-INV-013.

The remaining Rent obligation after valid confirmed Payment Allocations and Customer
Credit applications—not the total mixed-Invoice balance—determines Rent nonpayment
under BR-LEASE-027 through BR-LEASE-030. An unpaid Service-only balance must not be
misclassified as unpaid Rent.

---

## BR-PAY-040 — Late-payment Charge Allocation

Authorized staff may allocate Payment value directly to a positive confirmed
Late-payment Charge. The Allocation reduces only that separate obligation's remaining
balance and does not rewrite or increase its original amount or the source Invoice.

If a Customer designates an amount for the Late-payment Charge, apply no more than its
remaining balance. Any remaining Payment value follows the Customer's other valid
designation or the normal confirmed Allocation rules and remains unallocated until
posted or otherwise disposed under an approved rule.

Example: if the source Invoice remains $310 outstanding and its separate Late-payment
Charge is $31, a Customer-designated $100 Payment to the Late-payment Charge applies $31
there and leaves $69 for another valid confirmed Allocation or disposition. The source
Invoice remains $310 outstanding until value is separately allocated to it. A Receipt
may show both the $100 Payment and the confirmed $31 application.

Replaced by DL-076 (owner, 2026-10-20): the proposal pays oldest Due Date first, and a late-payment charge right after its own Invoice, before newer Invoices. Staff change the ticks only when the Customer names what to pay (BR-PAY-024) and confirm with Receive payment (DL-029). A third-party payer's money gets no automatic ticks.

Built in V1-056 slice 11g-4 (DL-088; DL-076 answer 5): the payment proposal of a payer's own Payment that names nothing pays oldest Due Date first and each open late-payment charge of the payer right after its own Invoice, before newer Invoices; the charge of an Invoice already paid keeps its Due Date place. A Payment that names an Invoice or a charge, and a third-party Payment, are proposed as before (no charge targets). The charge part is posted as a direct charge allocation.

---

## BR-PAY-042 — Payment Allocated to the Wrong Unit's Invoice

When a Payment was allocated by mistake to another Unit's Invoice (example: meant for Unit 201, paid on Unit 203), the Payment is not refunded to the payer. Staff record a draft that states as text that both Customers confirmed, who confirmed, the date and how. After a `financial.approve` holder confirms it, the wrong Payment Allocation is reversed and the same Payment is allocated to the correct Invoice.

The first Invoice becomes unpaid again, and the normal late-payment and Rent nonpayment rules apply to it from then on; earlier records are not changed. If the wrong allocation already became Customer Credit or a Refund, those must be reversed first; otherwise the move is blocked. The Payment record (amount, date, Receipt) never changes, and no Customer Credit moves between Customers (DL-031, DL-068, DL-069). BR-PAY-041 is withdrawn and is not reused.

After the Lease's Final Settlement is closed, a wrong allocation that the Settlement relied on is moved only through a correction of that Settlement (BR-SETTLE-013; V1-056 sub-slice 10g); from V1-056 sub-slice 10h the ordinary move draft is refused for it.

Amended by the owner's answer (a) to Q-2026-10-17-121 (2026-10-17; V1-056 sub-slice 10g-2): inside that correction only, the Payment's other Customer Credit or Refunds do not block the move, because the wrong allocation is still active and its value never became Credit or a Refund; that Credit, those Refunds and the Settlement's use of them stay as they are. The move stays blocked while such Credit or Refunds exist and a credit Adjustment released any part of an allocation of that Payment on the wrong Invoice (that Credit came from the wrong money). The ordinary move draft keeps the rule above.

Amended by the owner's answers to Q-2026-10-06-36 (answers 3 and 4) and Q-2026-10-17-120 (point 2) (built in V1-056 sub-slice 10h-1): the ordinary move draft refuses an allocation that a closed Final Settlement relied on (made at or before the closure on an obligation of its Lease, or written by a correction of that Settlement, such as the new allocation of a Payment move correction on another Lease); staff move it through a correction of that Settlement. A draft recorded before the closure is refused at its confirmation and stays pending. An allocation reversed before the closure was not relied on by that Settlement and keeps the ordinary move draft.

---

# 21. Customer Credit Rules

## BR-CREDIT-001 — USD Accounting Balance

Customer Credit is maintained as a USD accounting value. No separate
KHR-denominated Customer Credit balance is approved.

---

## BR-CREDIT-002 — Authorized Creation

Unallocated excess becomes Customer Credit only after the payer authorizes
Property Management to retain the identified amount. Recognition must not be
automatic.

Amended by DL-068 and DL-069 (2026-10-03): value released by a credit Adjustment becomes Customer Credit at once without payer authorization (DL-064 option (a); BR-CREDIT-014).

---

## BR-CREDIT-003 — Payment Source Linkage

Every Customer Credit created from overpayment identifies the original Payment,
the retained excess amount, the payer Customer, and the authorization event.

Amended by DL-068 and DL-069 (2026-10-03): Customer Credit created from a credit Adjustment identifies the Adjustment, the released Payment Allocation or Credit application and the Invoice Customer (BR-CREDIT-014).

---

## BR-CREDIT-004 — Separate From Deposit

Customer Credit is distinct from Security Deposit and Pet Deposit. It must not be
represented as, pooled with, or converted silently into either Deposit type.

---

## BR-CREDIT-005 — Valid Obligation Application

Authorized Customer Credit may be applied only to a valid outstanding obligation,
including an issued Invoice or a positive confirmed Late-payment Charge belonging to
the same Customer. It must not create or accelerate an Invoice solely to consume the
Credit.

---

## BR-CREDIT-006 — Authorized Application

A Customer Credit application is a separate authorized financial event.
It identifies the Credit source, target Invoice or other obligation, sufficient
Invoice-line or obligation-category detail where applicable, amount, Customer
designation if any, proposed default if any, actor confirmation, and time.

For a selected mixed Rent Invoice without Customer designation, the application follows
the Rent-first then recurring-Service proposal and authorized confirmation requirements
in BR-PAY-036 through BR-PAY-039.

Exception (owner answers (b) to Q-2026-10-13-104 and (a) to Q-2026-10-13-106, V1-056): when
a post-settlement correction reverses a mistaken return and puts back the part of a Credit
application that was not the mistaken money, that put-back goes back on its own Invoice line,
even where the Rent-first proposal would choose another line; it restores what was there
before the mistake and is not a new application choice. It is labelled "put back by a
correction", only for a put-back linked to that correction, on the same line, and never more
than the amount reversed there. Staff cannot choose this label for an ordinary Credit
application.

Exception (owner answer (a) to Q-2026-10-16-118 point 1, V1-056): when a confirmed Adjustment
reversal (the `ADJUSTMENT_REVERSAL` draft of a mistaken credit Adjustment, confirmed under
`financial.approve`) puts the released Credit back, that put-back always goes back on the
Adjustment's own Invoice line, even where an earlier line still owes and the Rent-first
proposal would choose it; it restores what was there before the mistake and is not a new
application choice. It carries the same label "put back by a correction", only for a put-back
of that reversal, on the Adjustment's line, and never more than the release or the line's
unpaid rest. The same holds after the Lease's Final Settlement is closed for the Adjustment
reversal correction of that Settlement (V1-056 sub-slice 10f-2), whose put-back is also linked to
the correction.

Amended by DL-077 (owner, 2026-10-20): on issue day, "One tap" fills in the use of the Customer's Credit for the new Invoice, and staff confirm it.

---

## BR-CREDIT-007 — Application Limits

A Credit application must be positive and cannot exceed either the available
Customer Credit balance or the target obligation's outstanding balance. It must not
produce a negative Invoice-line, Invoice, Late-payment Charge, or Credit balance.

---

## BR-CREDIT-008 — Same-Customer Scope

Customer Credit may be applied only to obligations belonging to that same
Customer, including valid Invoices across that Customer's applicable Lease
relationships. It cannot be transferred to another Customer.

---

## BR-CREDIT-009 — Application History and Reversal

The original Credit and every application remain permanent. A correction uses an
explicit linked reversal and recomputes affected balances and statuses.

---

## BR-CREDIT-010 — KHR-origin Source Preservation

When Credit originates from a KHR Payment, preserve the original KHR amount,
exact Payment-confirmation exchange rate, USD accounting value, and source
relationship. The Credit balance itself remains USD.

---

## BR-CREDIT-011 — USD-only Credit Refund

Refund Customer Credit only in USD, paid and recorded in exact USD cents. Preserve
its USD value and original source linkage, including any KHR Payment and immutable
conversion-rate evidence. Do not convert Credit into a KHR Refund (DL-060).

Amended by V1-056 sub-slice 10h-1b (owner answers (b) to Q-2026-10-19-141 and (a) to
Q-2026-10-19-144): money that a post-settlement correction brought back into a Customer Credit (a
Refund from that Credit whose return a correction of a closed Final Settlement recorded) leaves
only through a correction of that Final Settlement, so the Customer's open debt on the Lease is
paid first (DL-032). The ordinary Credit Refund draft refuses that money at record and at
confirmation, and the one-call Credit reversal, which would move it back to its Payment, is
refused while that money is in the Credit unless a correction of that Settlement links the
reversal; money the Credit holds for other reasons stays refundable through the ordinary draft
(BR-SETTLE-013). Other value a correction puts back into a Credit (for example a correction's
reversal of a Credit application) is not counted as money brought back.

---

## BR-CREDIT-012 — Permanent Credit History

Creation, application, reversal, Refund, remaining balance, and source values of
Customer Credit must remain permanently reconstructable and auditable.

---

## BR-CREDIT-013 — Not Vendor Accounts Payable

Customer Credit retained for a Customer remains a distinct customer-related liability
concept. It must not be called or modeled as ordinary vendor Accounts Payable. General
supplier and vendor Accounts Payable is outside this application's scope.

---

## BR-CREDIT-014 — Credit From a Credit Adjustment

Customer Credit created from value released by a credit Adjustment belongs to the Customer named on the Lease and Invoice, even when a third party paid. It is recognized at once, without payer authorization, and any Refund of it goes to that Customer (DL-064, DL-068).

Amended by the owner's answer to Q-2026-10-07-38 (2026-10-07): the same applies to value released when a paid Late-payment Charge is corrected after the Lease's Final Settlement is closed. Credit released to a Customer who did not make the Payment is refunded to that Customer.

---

## BR-LEDGER-001 — One Unified Customer View

Each Customer must have a unified Customer Account Ledger view that presents the
Customer's complete chronological financial history and current financial position.
It must be reconstructable from the Customer's authoritative underlying records.

---

## BR-LEDGER-002 — Underlying Records Remain Authoritative

The Customer Account Ledger does not replace, merge, or rewrite Invoice lines,
Invoices, Payments, Payment Allocations, Customer Credit, Credit applications,
Adjustments, Refunds, Security Deposits, Pet Deposits, Deposit applications or
dispositions, Late-payment Charges, Payment or Allocation Reversals, or Final
Settlement records.

Whether `004_DATABASE_MODEL.md` derives the view directly or uses a reconciled
materialized structure is an implementation choice. A Ledger representation must never
become a second conflicting source of financial truth.

---

## BR-LEDGER-003 — Complete Financial Position

The Ledger must make it possible to determine, for one Customer:

- amounts charged and their source obligations;
- Payments received and confirmed applications;
- Customer Credit created, available, applied, reversed, or refunded;
- Refunds and Adjustments;
- Security Deposit and Pet Deposit amounts received, held, applied, disposed, or refunded;
- Late-payment Charges and their remaining balances;
- obligations that remain unpaid and their composition;
- total current amount the Customer owes; and
- available Customer Credit.

Deposits remain separately identifiable liabilities and must not be pooled into ordinary
Customer Credit or netted away by the Ledger view.

---

## BR-LEDGER-004 — Business-facing Language

Customer-facing and staff-facing Ledger presentation uses operational terms such as
Amount charged, Payment received, Credit, Refund, Outstanding balance, and Customer
Credit. It must not require formal debit/credit bookkeeping terminology and must not
introduce a Chart of Accounts, journal-entry posting, General Ledger, or vendor Accounts
Payable workflow.

---

## BR-LEDGER-005 — Chronology and Reconstruction

Every displayed event must retain or derive its event date/time, source record,
Customer, amount, direction or business effect, and resulting position. Corrections and
reversals remain separate events so the historical and current positions can be
reconstructed without silent deletion or rewriting.

---

## BR-LEDGER-006 — Balance Composition

The Customer's total outstanding amount includes valid Invoice outstanding balances and
separate positive Late-payment Charge outstanding balances. Customer Credit,
unallocated Payment, Security Deposit, and Pet Deposit remain distinct balances and
must not be silently treated as reductions of an obligation without an authorized
application.

---

## BR-LEDGER-007 — Illustrative Ledger

For an Invoice with $500 Rent and $10 Trash Collection, an authorized $300 Rent
Allocation leaves $200 Rent and $10 Service outstanding. If authorized management then
confirms a $21 Late-payment Charge, the Customer's total outstanding amount is $231
while the Invoice remains $210 outstanding. A later $231 Payment may be allocated as
$200 Rent, $10 Trash Collection, and $21 Late-payment Charge, resulting in zero total
outstanding without changing the original Invoice or Late-payment Charge amounts.

This example does not require physical duplication of every amount in a Ledger table.

---

# 22. Refund Rules

## BR-REFUND-001 — Refund Is a Separate Event

A Refund is an explicit outbound financial event. It does not rewrite, delete,
or replace the Payment, Customer Credit, or Deposit from which it originates.

---

## BR-REFUND-002 — Required Financial Source

Every Refund must identify one valid source and the amount available from that
source. The source may be unallocated Payment excess, Customer Credit, or a
refundable Deposit balance under an approved rule.

---

## BR-REFUND-003 — Refund Amount Limit

A Refund amount must be positive and must not exceed the refundable amount
remaining at its identified source.

---

## BR-REFUND-004 — Property-caused Reservation Refund

When a Reservation is cancelled because the Property cannot provide the Unit as
agreed and the Customer rejects the coordinated delay or alternative, all
Security Deposit received for that Reservation must be refunded in full through
an explicit Refund.

---

## BR-REFUND-005 — USD Refund of KHR-origin Excess

Refund eligible unallocated excess from a KHR Payment only in USD, using the
remaining recorded USD accounting value after authorized dispositions. Preserve
the original KHR Payment amount and Payment-confirmation exchange evidence for
audit. Do not recalculate the Refund from a KHR remainder or a new rate (DL-060).

---

## BR-REFUND-006 — USD-only Credit Refund Currency

All Customer Credit Refunds must be paid and recorded in USD. KHR is a Payment
conversion option only, not a Refund currency. No Refund-date exchange rate or
KHR Refund rounding is used; retain original KHR source evidence (DL-060).

---

## BR-REFUND-007 — Final Settlement Deposit Refund

Remaining refundable Security Deposit and Pet Deposit balances after Final
Settlement are refunded through separate explicit Refund events so each Deposit
type remains traceable.

---

## BR-REFUND-008 — Currency and Value Preservation

Every Refund is paid and recorded in USD, with its amount in cents equal to its
USD accounting value. Preserve source relationships and any original KHR amounts,
exchange rates, timestamps and calculation evidence for audit. Historical records
must not be rewritten. Partial verified returns of USD Refunds use exact USD cents,
not KHR conversion or proportional KHR rounding (DL-060).

---

## BR-REFUND-009 — Authorization and Reason

Every Refund requires appropriate authorization and a recorded reason, actor,
date and time, recipient, and source.

---

## BR-REFUND-010 — No Original-record Rewrite

A later Refund must never reduce the recorded original Payment amount, original
Customer Credit creation amount, or original Deposit receipt.

---

## BR-REFUND-011 — Refund History

Every Refund and any authorized linked correction must preserve complete history.
A Refund must never be physically deleted or rewritten. This rule does not create
additional Refund statuses or a new Refund right.

---

## BR-REFUND-012 — Reconstructable Source Chain

The full chain from original receipt through Allocation, Credit recognition,
Deposit disposition or application, and Refund must be reconstructable without
relying on rewritten historical values.

---

## BR-REFUND-013 — Active-Lease Pet Deposit Refund

When the approved pet permanently leaves during an active Lease, BR-DEP-012 may make
the remaining Pet Deposit refundable after all applicable pet-related obligations are
resolved. Its return uses an explicit Refund event linked to that Pet Deposit, the
recorded permanent pet departure, the obligation review, authorization, reason,
actor, and date/time. The Lease need not terminate, and full history is preserved.

---

## BR-REFUND-014 — Refund Methods

Refund methods are a configured list, like Payment Methods, starting with Cash and Bank transfer (ABA or another bank). Every Refund records its method and a reference note. All Refunds are in USD (DL-060). The system sets no Refund deadline (DL-068, DL-069).

Amended by DL-073 (owner, 2026-10-20): there is still no Refund deadline or block in the system. While a Deposit Refund is not made, a to-do reminder shows "Refund due by" with the date 7 days after the later of the final inspection and the final Utility Invoice (the Lease's 7-day promise). Not built yet.

Amended by DL-080 (owner, 2026-10-20): for a cash Refund, the reference note says who took the money. Refund methods stay their own list, not the Payment Methods list.

Amended by DL-089 (owner, 2026-10-25): Refund methods are managed with Settings access. Only the Owner and people ticked for Settings access (`settings.manage`) may add a Refund method or turn one off or on again, and at least one Refund method always stays on. A method turned off is kept (old Refunds still name it) and can be turned on again; a new Refund cannot use it. Each change is recorded in the audit history with who made it.

---

## BR-REFUND-015 — Deposit Refund Recipient for Joint Signers

A Deposit Refund goes to the Primary Tenant unless all Lease Signers agree in writing that another Signer receives it. The agreement is recorded as text (DL-069).

---

# 23. Lease Termination Rules

## BR-LEASE-017 — No Automatic Month-to-month Tenancy

The Lease does not automatically continue as a month-to-month tenancy at its
contractual End Date. No new tenancy, holdover Rent, fee, penalty, or other charge
is created automatically.

---

## BR-LEASE-018 — No Automatic Termination at End Date

Arrival of the contractual Lease End Date does not automatically change a SIGNED
Lease to TERMINATED while the Customer still occupies the Unit.

By that date, the Lease should normally have an approved signed renewal or
proceed through the applicable termination and move-out process.

---

## BR-LEASE-019 — Continued Occupancy Requires Management Action

If the Customer remains after the Lease End Date without an approved signed
renewal, Property Management must take authorized action according to the signed
Lease. Until then, the actual Lease and Occupancy situation must remain recorded
accurately.

---

## BR-LEASE-020 — No General Early-termination Right

A Customer does not have a general right to terminate a Lease before its
contractual End Date. Early termination is not normally permitted.

---

## BR-LEASE-021 — Processed Voluntary Early Termination

If a Customer voluntarily leaves before the Lease End Date and Property
Management processes the early termination:

- the Lease terminates on the approved actual termination/move-out date;
- Rent for that calendar month is charged in full;
- applicable Utility, fixed Service, and other valid outstanding obligations
  remain due;
- the Security Deposit is non-refundable;
- no separate standard early-termination fee is created; and
- Rent is not generated for later months through the original End Date.

Amended by DL-068 and DL-069 (2026-10-03): "that calendar month" is the month of the actual hand-back (move-out) date, not a notice date. A hand-back before the 5th follows BR-RENT-030 for that month's Rent. The leaving Customer also owes every issued Invoice (paid or unpaid), outstanding Late-payment Charges and the move-out charges, including the Unit cleaning charge (BR-MOVEOUT-013). The whole Security Deposit is forfeited and is never applied to what the Customer owes (BR-DEP-026).

---

## BR-LEASE-022 — Termination Notice

Where a Termination Notice applies, its content and notice period come from the
signed Lease. Recording a Notice does not itself change Lease status or fabricate
an actual Move-out Date.

---

## BR-LEASE-023 — Actual Termination Date

A SIGNED Lease becomes TERMINATED only through the authorized process on the
approved actual termination date. That date and the governing event must remain
historically identifiable.

---

## BR-LEASE-024 — General Violation Warning Minimum

Property Management must issue at least three documented warning letters before
terminating a Lease for a Customer violation.

Each warning must identify the violation, date, Lease provision, communication,
and history. The undisclosed-pet process follows this rule if noncompliance
proceeds toward termination.

The specific 20-day Rent Nonpayment Warning Notice under BR-LEASE-027 does not
automatically replace or satisfy this broader three-warning-letter requirement.
Nothing in the 30-day Serious Nonpayment Default rule bypasses any warning requirement
that applies to the eventual termination process. Counting one record toward another
procedure requires an expressly approved basis rather than an implementation
assumption.

Amended by DL-070 (owner, 2026-10-15; the new standard Lease agreement): a serious breach by the Customer, meaning a crime or danger to people or the building, may end the Lease at once, without the three warning letters. The authority still comes from the signed Lease (BR-LEASE-025), and the termination is still an explicit action by an authorized user with its grounds recorded; nothing is automatic. Every other Customer violation still needs the three warning letters. Not built yet.

Amended by DL-073 (owner, 2026-10-20): for a Rent nonpayment termination the day-20 Nonpayment Warning Notice (BR-LEASE-027) is letter 1, the day-30 default notice (BR-LEASE-028) is letter 2 and the termination notice (BR-LEASE-022) is letter 3; such a termination needs no other warning letters (the owner's explicit approval under this rule). Not built yet.

---

## BR-LEASE-025 — Signed-Lease Termination Authority

A violation and the authority to terminate for it must come from the signed
Lease. The system must not invent a violation, penalty, fee, forfeiture, or
termination right.

The standard Lease used for all Customers contains a clause giving a termination right
if either the Security Deposit or the Initial Rent Invoice is not fully paid within five
calendar days after the Lease Start Date. That clause is the governing signed-Lease ground for
termination. BR-LEASE-024's three warning letters do not apply to this ground. The
termination records the Lease clause reference.

Amended by DL-068 and DL-069 (2026-10-03): DL-064, DL-068 and DL-069 approve the Security Deposit forfeiture for this termination ground, whether or not the Customer moved in (BR-DEP-026), and the Pet Deposit outcome in BR-DEP-027.

Amended by DL-070 (owner, 2026-10-15; the new standard Lease agreement): this clause is Article 2.5 of the standard Lease agreement, and a termination on this ground records "Article 2.5" as its clause reference. Not built yet: staff still enter the clause reference as text.

---

## BR-LEASE-026 — Rent Nonpayment Day Count

Rent nonpayment days are counted in `Asia/Phnom_Penh` calendar days from a fixed day
one, independent of the Invoice Due Date.

The Rent nonpayment process under BR-LEASE-026 through BR-LEASE-030 applies only to
recurring monthly Rent Invoices. Day one is the first calendar day of the billed month.
The Initial Rent Invoice never opens a Rent nonpayment case; BR-RENT-009 governs its
follow-up.

Day N is day one plus N − 1 calendar days. Day 20 is therefore the 20th and day 30 is
the 1st plus 29 days; in a normal-year February, day 30 is 2 March.

The Invoice Due Date under BR-RENT-009 and the overdue boundary under BR-INV-051
continue to govern the late-payment decision. They do not change the nonpayment day
count.

When one Invoice contains both Rent and recurring-Service lines, the nonpayment
process uses the remaining Rent line balance after valid confirmed Payment
Allocations, Customer Credit applications and Adjustments. The whole mixed-Invoice
balance is not a substitute for the remaining Rent balance.

A case recorded under an earlier count keeps its recorded values; the count applies to
cases opened after this rule took effect.

Example:

```text
Recurring Rent for August:                 day 1 = 1 August,   day 20 = 20 August,   day 30 = 30 August
Recurring Rent for February:               day 1 = 1 February, day 20 = 20 February, day 30 = 2 March (normal year)
```

---

## BR-LEASE-027 — Twenty-day Rent Nonpayment Warning Notice

If a positive balance of the applicable Rent obligation remains unpaid on day 20 under
BR-LEASE-026, the system must alert authorized staff or management and
require or support issuance and recording of a formal Nonpayment Warning Notice to the
Customer. The Notice states that continued nonpayment through 30 days overdue may
result in authorized management initiating the approved Lease termination or
surrender process.

When a case is opened after day 20 has passed, the system alerts authorized staff at
once.

The Notice is a permanent auditable business record, not an ephemeral UI warning. It
preserves at minimum, where applicable:

- Customer;
- Lease;
- applicable overdue Rent Invoice or obligation;
- Due Date;
- remaining Rent amount at Notice time;
- Notice issue date/time;
- issuer;
- Notice type;
- delivery or communication information when recorded;
- document or reference to the actual Notice; and
- subsequent status and history.

---

## BR-LEASE-028 — Thirty-day Serious Nonpayment Default

If a positive balance of the applicable Rent obligation remains unpaid on day 30 under
BR-LEASE-026, the system records a Serious Nonpayment Default condition.
Authorized management may then initiate the approved Lease termination or surrender
process. When a case is opened after day 30 has passed, the system alerts authorized
staff at once.

The condition must not automatically:

- change the Lease to TERMINATED;
- mark the Unit VACANT;
- end Occupancy;
- create Move-out;
- create Final Settlement;
- surrender the Unit; or
- delete or end the Customer's legal or operational tenancy record.

Actual Lease termination remains a separate explicit authorized business action under
BR-LEASE-005, BR-LEASE-023, BR-LEASE-024, and BR-LEASE-025. Until termination and
physical Move-out actually occur, the Lease remains in its appropriate existing
status, normally SIGNED, and the Unit remains OCCUPIED while the Customer still
physically occupies it.

A remaining recurring-Service balance alone does not satisfy the Rent-balance condition
for this rule.

Amended by DL-073 (owner, 2026-10-20): the day-30 default notice is a letter the system records, like the day-20 Notice of BR-LEASE-027, and it counts as letter 2 of a Rent nonpayment termination (BR-LEASE-024). The condition itself and its no-automatic-action list are unchanged. Not built yet.

---

## BR-LEASE-029 — Cure After Warning and Before Thirty Days

If the Customer fully cures the applicable Rent nonpayment after its 20-day Warning
Notice but before day 30 under BR-LEASE-026, the current 30-day trigger for that cured
obligation stops. The system must not initiate termination at day 30 merely because
the obligation was previously late.

The Invoice's overdue history, Warning Notice, cure Payment and Allocation history,
and all related dates remain permanent and auditable.

---

## BR-LEASE-030 — Payment After Serious Nonpayment Default

Payment after a Serious Nonpayment Default does not erase that historical condition,
its Warning Notice, or any already initiated authorized termination process.

The system must not automatically decide whether an initiated termination process
continues or stops solely because later Payment occurs. Authorized management retains
control under the existing approved termination rules, and the Payment, Allocations,
default history, management actions, and resulting outcome remain auditable.

---

# 24. Move-out Rules

## BR-MOVEOUT-001 — Actual Move-out Date

Move-out records the actual date physical occupancy ends. It must not be inferred
solely from the contractual Lease End Date or a Notice date.

---

## BR-MOVEOUT-002 — Lease Coordination

Move-out must be coordinated with the applicable authorized Lease termination.
The Lease termination date and actual Move-out Date must represent the approved
business event accurately.

---

## BR-MOVEOUT-003 — Occupancy Closure

Every open Occupancy that physically ends must receive its actual Move-out Date.
Occupancy history remains permanent.

---

## BR-MOVEOUT-004 — Unit Operational Transition

After physical move-out, the Unit leaves OCCUPIED and enters the status matching
its actual condition, normally CLEANING. It must not become available merely
because the Lease was terminated.

---

## BR-MOVEOUT-005 — Final Utility Handling

Final actual Utility Readings must be obtained and validated where possible. If
a Meter is confirmed broken, only the approved estimation process may be used.

An ordinary missing reading delays the charge. A zero-history broken-Meter estimate
remains pending until the approved complete future-period basis exists. One or two
complete historical actual periods are usable immediately under BR-UTIL-027.

When final validated Readings or an approved estimate are recorded at move-out, the
system creates the final Utility Invoice off-cycle under BR-UTIL-021. When the tenant
never moved in, no Utility or Damage charge applies to the Customer; the Property bears
any Utility consumption.

---

## BR-MOVEOUT-006 — Inspection and Final Charges

Authorized inspection results and all valid Rent, Utility, fixed Service, Damage,
Miscellaneous, and Adjustment obligations that properly belong in Final
Settlement must be finalized from their approved sources.

This rule does not create a new charge, fee, or damage policy.

A Damage charge is created only from a recorded inspection damage finding, by an
authorized manager or staff member holding the Damage-charge capability, who enters the
amount with a mandatory reason and evidence reference (a note or document reference).
Each finding is billed at most once. The charge must match the finding's Customer,
Lease and Unit. Inspection alone creates no charge; there is no standard damage fee and
no automatic Pet Deposit forfeiture. Its Due Date follows BR-INV-018.

Amended by DL-068 and DL-069 (2026-10-03): the Unit cleaning charge in BR-MOVEOUT-013 is an approved move-out charge and is not an invented fee.

Amended by the owner's answer to the V1-056 sub-slice 10b report (2026-10-07): after the Final Settlement is closed, a Damage charge is billed only as a post-settlement correction (BR-SETTLE-013). Staff prepare it under the Final Settlement preparer capability, and a holder of `financial.approve` confirms and authorizes it, like every correction; the Damage-charge capability is not used for it. The other rules of this section still apply: a recorded inspection damage finding, billed at most once, matching the finding's Customer, Lease and Unit, with the amount, a reason and an evidence reference.

Amended by the owner's answers to Q-2026-10-07-44 (answer 2) and Q-2026-10-08-49 (2026-10-08; V1-056 sub-slice 10c-2a-4): once a Lease's Final Settlement is closed, no move-out inspection on that Lease may be superseded; the attempt is refused as a conflict and nothing is recorded. The inspection the closed Settlement relied on never changes. Damage found after closure is recorded as a new, separate inspection that supersedes nothing, and its finding is billed only as a post-settlement correction. A wrong finding on the inspection the Settlement relied on is fixed only with a post-settlement correction. Known limit: a mistake in an inspection recorded after closure cannot be fixed by a supersede either; the wrong finding is simply not billed, because billing it needs a correction confirmed by a holder of `financial.approve`.

---

## BR-MOVEOUT-007 — Normal Lease End

By the Lease End Date, an approved signed renewal should be in place or the
applicable termination and move-out process should proceed. The system must not
assume either outcome without the corresponding authorized records.

---

## BR-MOVEOUT-008 — Continued Occupancy After End Date

If physical occupancy continues, the Move-out Date remains empty and the Lease
must not be automatically marked TERMINATED. Property Management action under
the signed Lease is required.

---

## BR-MOVEOUT-009 — No Invented Holdover Terms

Continued occupancy after the End Date must not automatically create
month-to-month tenancy, holdover Rent, penalties, fees, or a new tenancy.

---

## BR-MOVEOUT-010 — Voluntary Early Move-out

Voluntary early move-out follows BR-LEASE-021, including the full final calendar
month of Rent, applicable final obligations, Security Deposit disposition, and no
future Rent after the processed termination.

Amended by DL-068 and DL-069 (2026-10-03): the full final month follows BR-RENT-024 and BR-RENT-030, and the Security Deposit follows BR-DEP-026.

---

## BR-MOVEOUT-011 — Move-out History

The Lease, Occupancy, Unit status, readings, inspection, notices, authorization,
actual dates, and corrections associated with move-out must remain permanently
auditable.

---

## BR-MOVEOUT-012 — Final Settlement Sequence

Move-out and Lease termination provide inputs to Final Settlement. Final
Settlement must not close until all required valid charges are final, including
any approved pending broken-Meter estimate.

---

## BR-MOVEOUT-013 — Unit Cleaning Charge

At every move-out, for any reason of leaving, the Customer is charged the Unit's configured cleaning rate (BR-UNIT-014) as a one-time charge on the move-out Invoice. Its Due Date is the issue date plus the Property's configured days (7 by default), with the existing authorized override (BR-INV-018). An authorized user may reduce it with a linked credit Adjustment and a reason. There is no cleaning charge when the Customer never moved in (DL-065, DL-068, DL-069).

---

# 25. Deposit Disposition Rules

## BR-DEP-015 — Customer-caused Reservation Cancellation

When a Customer voluntarily cancels an ACTIVE Reservation for a
Customer-attributable reason, Security Deposit received is non-refundable. The
Unit is released, and the original Deposit and cancellation history are
preserved.

---

## BR-DEP-016 — Customer-caused Reservation Expiration

When the Property could provide the Unit as agreed but the Customer does not move
in and the Reservation expires without a valid extension, Security Deposit
received is non-refundable.

---

## BR-DEP-017 — Property-caused Reservation Refund

When the Property cannot provide the reserved Unit as agreed and the Customer
rejects the coordinated delay or alternative and requests cancellation, all
Security Deposit received must be refunded in full through explicit Refund
events. The original Deposit receipt remains unchanged.

---

## BR-DEP-018 — Explicit Forfeiture or Disposition Event

Every approved non-refundable Deposit outcome uses an explicit linked Deposit
forfeiture or disposition event. The event reduces the refundable Deposit balance
without deleting, rewriting, or silently reclassifying the original receipt.

Amended by DL-068 and DL-069 (2026-10-03): a forfeited Security Deposit is forfeited in full and is never applied to what the Customer owes (BR-DEP-026).

---

## BR-DEP-019 — Disposition Audit

Each Deposit disposition records:

- amount;
- Deposit type;
- reason;
- governing Reservation, Lease, or business event;
- effective date;
- authorization; and
- complete audit history.

It must not be allocated to an ordinary monthly Invoice merely to make an
accounting balance work. This rule authorizes no new forfeiture circumstance.

Amended by DL-068 and DL-069 (2026-10-03): DL-064, DL-068 and DL-069 approve the forfeiture circumstances listed in BR-DEP-026 and the Pet Deposit outcome in BR-DEP-027. BR-DEP-022 stays as written.

---

## BR-DEP-020 — Pet Introduced After Move-in

A Customer who later wants to introduce or acquire a pet must notify Property
Management. If the pet is approved and the applicable signed Lease terms require
a Pet Deposit, that Deposit must be paid before or when the pet begins staying in
the Unit.

---

## BR-DEP-021 — Undisclosed or Unauthorized Pet

When an undisclosed or unauthorized pet is found, Property Management informs the
Customer of the violation. A Pet Deposit is required only if the pet is approved
and the applicable signed Lease terms require that Deposit. The Lease must not be
terminated immediately and automatically merely because the pet was discovered.

No additional pet penalty is created by this rule.

---

## BR-DEP-022 — Pet Noncompliance and Violation Termination

If the Customer refuses or fails to pay the required Pet Deposit, termination may
proceed only under the signed Lease and the three-warning-letter rule.

If the Lease is terminated for that violation, the applicable Security Deposit
and Pet Deposit are non-refundable according to the signed Lease and must be
resolved through explicit disposition events.

---

## BR-DEP-023 — Voluntary Early-termination Security Deposit

When voluntary early termination is processed under BR-LEASE-021, the Security
Deposit is non-refundable and is resolved through an explicit disposition event.

Amended by DL-068 and DL-069 (2026-10-03): the whole Security Deposit is forfeited and is never applied to what the Customer owes; unpaid charges stay as debt (BR-DEP-026).

Amended by the owner answer to Q-2026-10-05-24 (2026-10-05): when a confirmed forfeiture of this Security Deposit is reversed, BR-DEP-026 applies.

---

## BR-DEP-024 — Pet Deposit During Voluntary Early Termination

Voluntary early termination does not automatically make the Pet Deposit
non-refundable. It remains separately tracked through Final Settlement, may be
applied under BR-SETTLE-005 and BR-SETTLE-006, and is refundable to the extent not
validly applied or otherwise validly forfeited under an explicitly approved rule.

---

## BR-DEP-025 — Remaining Refundable Deposit

Every remaining refundable Security Deposit or Pet Deposit balance after Final
Settlement must be returned through an explicit Refund event. Each Deposit type
and Refund remains separately traceable.

---

## BR-DEP-026 — Forfeited Security Deposit Is Never Applied

When the Security Deposit is kept, the whole deposit is forfeited through an explicit disposition event and is never used to pay what the Customer owes. Unpaid charges stay as debt on the Customer Ledger. This applies to voluntary early leaving, termination for unpaid Initial Rent or Security Deposit (whether or not the Customer moved in), termination for a violation (pet or non-pet) and termination after the 30-day Rent nonpayment default. At a normal Lease end DL-032 is unchanged (DL-064, DL-068, DL-069).

Amended by DL-073 (owner, 2026-10-20; item 3c replaced 2026-10-21): a serious-breach termination (DL-070) is a violation termination: the Security Deposit is kept. The Security Deposit is kept, and Rent already paid for the hand-back month is not refunded, when the Customer chooses to leave before the End Date or the Lease is terminated on a ground of this list. When the Property ends the Lease with notice (Article 15.4) or both sides agree to end it early, DL-032 applies: the Security Deposit pays the open debt and the rest is refunded. Not built yet.

Amended by the owner answer to Q-2026-10-05-24 (2026-10-05): when a confirmed forfeiture of the Security Deposit is reversed, the Deposit is held again; at Final Settlement it follows DL-032 (it pays open debt and the rest is refunded) unless a new forfeiture draft is confirmed (owner answer to Q-2026-10-05-23).

---

## BR-DEP-027 — Pet Deposit at Other Terminations

At termination for unpaid Initial Rent or Security Deposit, for a non-pet violation, or after the 30-day Rent nonpayment default, the Pet Deposit pays valid pet damage first and the rest is refunded, as in DL-013. Termination for pet noncompliance follows BR-DEP-022: both deposits are kept (DL-068, DL-069).

Amended by DL-073 (owner, 2026-10-20): a serious-breach termination (DL-070) is treated as a non-pet violation termination: the Pet Deposit pays pet damage first and the rest is refunded; a pet-rule breach keeps both Deposits. Not built yet.

Amended by the owner answer to Q-2026-10-05-21 (2026-10-05): at these terminations the remaining Pet Deposit pays other debt only when the Customer chooses it, recorded as text (who, the date, how) with the staff reason; otherwise the rest is refunded (owner answer to Q-2026-10-05-20). At a normal Lease end and at voluntary early leaving the DL-013 staff step stays: authorized staff may apply the remaining Pet Deposit with a reason when the Customer will not pay (BR-SETTLE-017).

---

# 26. Final Settlement Rules

The general sequence is:

```text
Finalize all valid Settlement charges
        ↓
Apply authorized Customer Credit
        ↓
Authorized management explicitly selects/confirms Deposit applications
        ↓
Determine remaining Customer balance or refundable Deposit balance
        ↓
Refund remaining refundable Deposit
```

Deposit applications are always explicit and auditable.

## BR-SETTLE-001 — One Settlement per Terminated Lease

Every TERMINATED Lease must complete exactly one Final Settlement. The Settlement
belongs to exactly one TERMINATED Lease and may remain pending until all
finalization prerequisites are satisfied.

---

## BR-SETTLE-002 — Settlement Inputs

Final Settlement must identify the Lease, responsible Customers, actual
termination and Move-out dates, outstanding Invoices, applicable outstanding
Late-payment Charges, Customer Credit, Security Deposit, Pet Deposit, final Utility
handling, Adjustments, and other valid linked financial events applicable to that Lease.

Amended by the owner's answer (a) to Q-2026-10-17-120 point 3 (built in V1-056 sub-slice 10h-3): a Final Settlement is not recorded or confirmed while a draft that could change its inputs waits. Besides a waiting Refund, forfeiture or wrong-Unit Payment move draft on the Lease's sources, this includes another Lease's waiting Payment move correction whose correct Invoice is on this Lease, a waiting returned-Payment draft, or another Settlement's waiting returned-Payment correction, of a Payment that paid this Lease's obligations, funded a Credit of one of its Customers or funded one of its Deposits, and a waiting Adjustment reversal draft of an Adjustment on one of its Invoices. The draft is first confirmed by an approver, rejected or withdrawn. After closure the same waiting drafts hold the Settlement's post-settlement corrections until they are confirmed, rejected or withdrawn. Amended by the owner's answer 2 of 2026-10-20 to the 10h-3 report (built in V1-056 sub-slice 10h-4a): this also includes another Settlement's waiting held-value Refund correction that would pay out money held in a Credit of one of this Lease's Customers. Amended by the owner's answer (a) to Q-2026-10-20-146 (built in V1-056 sub-slice 10i-4c): this also includes another Settlement's waiting post-settlement correction whose plan lets a Credit of one of this Lease's Customers pay, or whose Refund correction gives value back into such a Credit; no amount rule changes, only the order.

---

## BR-SETTLE-003 — Finalize Valid Outstanding Charges

Before applying Credit or Deposits, finalize every valid outstanding obligation
that properly belongs in the Settlement from its approved source. No new fee,
penalty, category, or obligation may be invented for Settlement.

Amended by DL-068 and DL-069 (2026-10-03): the Unit cleaning charge (BR-MOVEOUT-013) and outstanding Late-payment Charges are valid Settlement obligations.

---

## BR-SETTLE-004 — Apply Authorized Customer Credit First

After valid charges are finalized, apply authorized Customer Credit to applicable
Settlement obligations through separate auditable Credit-application events.

---

## BR-SETTLE-005 — Pet Deposit Identification and Application

Pet Deposit remains separately identifiable first for valid pet-caused property
damage or extraordinary/deep-cleaning obligations where applicable. Pet Deposit does
not cap the Customer's full liability for those valid costs.

After Customer Credit and explicitly selected Security Deposit applications, if a
valid Settlement balance remains unpaid and the Customer has not paid or will not
pay it, authorized management may explicitly select remaining Pet Deposit for that
valid Settlement balance. This later application is not limited to pet-related
obligations.

Amended by DL-068 and DL-069 (2026-10-03): the Customer may also choose to use the remaining Pet Deposit for any remaining balance (BR-SETTLE-017).

Amended by the owner answer to Q-2026-10-05-30 (2026-10-05): the remaining Pet Deposit pays only debt still open after the Security Deposit has been used, also when the Customer chooses it.

---

## BR-SETTLE-006 — Explicit Deposit Selection

After authorized Customer Credit, authorized management must explicitly select and
confirm every Security Deposit or Pet Deposit application to a valid Final Settlement
obligation. Security Deposit may be applied to valid remaining Settlement
obligations. Each application records its Deposit source, target obligation, amount,
actor, timestamp, reason, and authorization.

The system must not infer an additional FIFO ordering between Deposit types beyond
BR-SETTLE-005 and must not apply either Deposit automatically merely because a
Settlement balance exists.

Amended by DL-068 and DL-069 (2026-10-03): a Security Deposit forfeited under BR-DEP-026 is not available for application. At a normal Lease end DL-032 is unchanged: the Security Deposit may pay remaining charges and the rest is refunded.

---

## BR-SETTLE-007 — Remaining Customer Balance

After all authorized applications, any unpaid amount remains a Customer balance.
Settlement must record it without changing the original obligations.

Amended by DL-068 and DL-069 (2026-10-03): an unpaid balance after Final Settlement stays open as debt on the Primary Tenant's Customer Ledger (BR-SETTLE-016). There is no write-off in V1.

---

## BR-SETTLE-008 — Refund Remaining Deposit Balances

Every remaining refundable Security Deposit and Pet Deposit balance must be
refunded explicitly and separately under the Refund rules.

The Customer must not receive refundable Deposit money while leaving a valid
Settlement balance unpaid when that available Deposit has been authorized for
application. Every such application must be recorded before the remaining refundable
balance is determined.

---

## BR-SETTLE-009 — Separate Traceability

Every Customer Credit application, Pet Deposit application, Security Deposit
application, forfeiture/disposition, remaining balance, and Refund must remain a
separate linked financial event and be independently auditable.

---

## BR-SETTLE-010 — No Deposit Use Before Settlement

Security Deposit and Pet Deposit must not be used for ordinary unpaid Invoices
before Final Settlement. A Customer instruction cannot override this rule.

An approved non-refundable Deposit disposition remains separate from Invoice
application and does not create a new forfeiture circumstance.

---

## BR-SETTLE-011 — Finalization Prerequisites

Final Settlement begins as a pending process and must not close until the Lease is
TERMINATED and every required
valid final charge is determined. An ordinary missing Utility Reading or a
pending zero-history broken-Meter estimate keeps the affected charge and Settlement
unfinalized as necessary. One or two complete historical actual periods use
BR-UTIL-027 and do not wait for future data.

---

## BR-SETTLE-012 — Permanent Closure

Final Settlement may close only once. Once closed, its identity, source balances,
application order, calculations, dispositions, Refunds, and resulting balance are
permanent. Source records must never be erased.

---

## BR-SETTLE-013 — Post-closure Correction

A legitimate correction after closure uses explicit linked Adjustment,
application reversal, disposition correction, or other applicable authorized
linked financial correction. The closed Settlement and original financial events
are not reopened or rewritten.

Amended by DL-068 and DL-069 (2026-10-03): a finalized Final Settlement is never reopened. A later fix is a new linked post-settlement correction (extra charge or Refund) with a reason. There is no time limit for post-settlement corrections.

Amended by the owner's answers to Q-2026-10-06-36 and Q-2026-10-06-37 (2026-10-06 and 2026-10-07): the post-settlement correction kinds are the extra charge, the charge reduction (a credit Adjustment that removes a wrong charge that is still unpaid), the Refund, the returned Payment, the Adjustment reversal, the forfeiture reversal and the Payment move. Each needs a reason; Staff prepare it, and only a holder of `financial.approve` confirms it.

Amended by the owner's answer to Q-2026-10-07-38 (2026-10-07): a wrong Late-payment Charge after closure is fixed by a Late-payment Charge correction linked to the Settlement, prepared under the Final Settlement preparer capability and confirmed only by a holder of `financial.approve`. When the Charge was paid, the value released by the correction follows BR-CREDIT-014, as for a credit Adjustment of an Invoice line.

Amended by the owner's answer to Q-2026-10-07-45 (2026-10-07; built in V1-056 sub-slice 10c-2a-5): a Damage line whose pet classification is wrong after closure, in either direction, is fixed by a pet classification correction, prepared under the Final Settlement preparer capability and confirmed only by a holder of `financial.approve`. The charge amount stays the same and the closed inspection record is not changed; the correction records the corrected classification, its evidence and the reason. Where the corrected classification changes which Deposit should pay the line, the line's Deposit applications from the Deposit that no longer should pay are reversed and the released Deposit value follows DL-032 again, with every Final Settlement rule and, at a BR-DEP-027 termination, a Customer choice given for this correction. A Deposit refunded at closure is not taken back, so the line may stay open debt on the Customer's ledger. A line billed from an inspection that was superseded before closure is not corrected this way until the owner decides whether a superseding inspection may carry a finding forward (the open point of Q-2026-10-07-45).

Amended by the owner's answers to Q-2026-10-16-118 and Q-2026-10-16-119 (2026-10-16; built in V1-056 sub-slice 10f-2): after closure, the Adjustment reversal correction reverses a mistaken credit Adjustment on an Invoice of the Settlement's Lease that was recorded before the closure, or the credit Adjustment that a charge reduction correction of that Settlement wrote; reversing a charge reduction's Adjustment restores exactly the debt the reduction removed. The Adjustments of every other correction kind and of a hand-back or unpaid-Initial resolution are not reversed this way. The part of each released value whose Credit is still available goes back on the Adjustment's own line; the rest stays as debt on the Invoice Customer's ledger.

Amended by the owner's answers to Q-2026-10-06-36 (answer 4) and Q-2026-10-06-37 (answers 1 and 5) (built in V1-056 sub-slice 10g, 2026-10-16): after closure, a Payment allocation that the Settlement relied on and that was made on the wrong Unit's Invoice is moved only through a Payment move correction of that Settlement (BR-PAY-042: the reason and the confirmation text of both Customers; prepared by the Settlement preparer and confirmed only by a `financial.approve` holder). The debt comes back on the Settlement's obligation and stays on its Customer's ledger; the correct Invoice may belong to another Lease, also one whose Final Settlement is closed (it pays that Lease's remaining debt); what it does not take stays unallocated on the Payment. An allocation made after the closure is moved by the ordinary move draft. An allocation that a correction of another Lease's Final Settlement wrote is not moved by this correction (open: Q-2026-10-17-120). Since V1-056 sub-slice 10g-2 (owner answer (a) to Q-2026-10-17-121), the Payment's other Customer Credit or Refunds block this correction only as the BR-PAY-042 amendment of 10g-2 says.

Amended by the owner's answers to Q-2026-10-06-36 (answers 3 and 4), Q-2026-10-06-37 (answer 5), Q-2026-10-07-39 and Q-2026-10-17-120 (point 2), and the owner note of 2026-10-16 on the 10f-2 report (built in V1-056 sub-slice 10h-1): after closure, a Payment allocation or Customer Credit application that the Settlement relied on is never reversed outside a correction of that Settlement. The Settlement relied on an allocation or Credit application on an obligation of its Lease made at or before the closure (also the re-posted rest of one), on its own Credit applications, and on every record one of its corrections wrote (for example a put-back of an Adjustment reversal correction, or the new allocation of a Payment move correction on another Lease). The one-call allocation reversal, the one-call Credit application reversal, an ordinary credit Adjustment or another Lease's correction that would release such a record, and the ordinary move draft are refused as a conflict; the debt the Settlement saw paid stays paid, so a charge reduction can never remove it. A record that two closed Final Settlements relied on is reversed by neither (a known limit, Q-2026-10-17-120 point 1). Allocations and Credit applications made after the closure and not written by a correction stay reversible with one call, so the Customer can still pay and correct the remaining debt.

Amended by the owner's answers (b) to Q-2026-10-19-141 and (a) to Q-2026-10-19-144 (built in V1-056 sub-slice 10h-1b): money that a post-settlement correction brought back into a Customer Credit (a Refund from that Credit, for example a Settlement Refund, whose return from the bank a correction of the closed Settlement recorded) leaves only through a correction of that Settlement, the held-value Refund correction naming the return, which pays the Customer's own open debt on the Lease first and refunds only the rest (DL-032). The ordinary Credit Refund draft is refused for that money at record and at confirmation (a conflict; the draft stays pending), and so is the one-call Credit reversal, which would move that money back to its Payment, from where a Payment Refund or a new Credit could pay it out while the Customer still owes on the closed Lease; a correction of that Settlement that links the Credit reversal (the returned-Payment correction) still reverses it. Money the Credit holds for other reasons stays refundable through the ordinary draft. Other value a correction puts back into a Credit (for example a correction's reversal of a Credit application) is not counted as money brought back.

Amended by the owner's answers 4 to Q-2026-10-06-36 and 6 to Q-2026-10-10-69 (built in V1-056 sub-slice 10h-2): once the Final Settlement of a kept Deposit's Lease is closed, the forfeiture is reversed only through a correction of that Settlement that links the reversal: the forfeiture reversal correction, which follows DL-032 (the Deposit pays this Lease's open debt first and only the rest is refunded), or the returned-Payment and receipt corrections that reverse it as part of their own work. The ordinary forfeiture reversal draft is refused at record and at confirmation (a conflict; the draft stays pending), and no other writer reverses such a forfeiture outside that correction. Owner answer (a) to Q-2026-10-19-143: a Payment allocation or Customer Credit application reversal is recorded only at the database's default isolation (READ COMMITTED), so the refusals of what a closed Settlement relied on cannot be bypassed through an older snapshot.

---

## BR-SETTLE-014 — Forfeiture Is Separate

A Deposit already resolved through an approved forfeiture/disposition event is
shown as such and is not fabricated as an ordinary Invoice Payment or pooled with
an available Deposit balance.

Amended by DL-068 and DL-069 (2026-10-03): a forfeited Security Deposit is never used to pay what the Customer owes (BR-DEP-026).

---

## BR-SETTLE-015 — Settlement Audit

Settlement must preserve every input, ordering decision, calculation, application,
disposition, Refund, authorization, actor, date and time, source link, and final
result necessary to reconstruct it.

---

## BR-SETTLE-016 — Settlement Debt and Joint Signers

A balance the Customer does not pay after Final Settlement stays open as debt on the Primary Tenant's Customer Ledger. There is no write-off in V1 (DL-068, DL-069).

Amended by the owner answer to Q-2026-10-05-21 (2026-10-05): debt left on an Invoice issued to another Signer of the Lease stays on that Signer's Customer Ledger, because an Invoice's Customer never changes; at Final Settlement the Lease's Deposits may pay it in the DL-032 order (owner answer to Q-2026-10-05-20).

---

## BR-SETTLE-017 — Customer-chosen Pet Deposit Use

At move-out the Customer may choose to use the remaining Pet Deposit to pay any remaining balance. Authorized staff may also do this with a reason when the Customer will not pay (DL-032 step 5). The application is confirmed by a `financial.approve` holder (DL-068).

Amended by the owner answer to Q-2026-10-05-30 (2026-10-05): the remaining Pet Deposit pays only debt still open after the Security Deposit has been used, also when the Customer chooses it.

---

# 27. Money, Currency, Exchange Rate, Dates, and Timezone Rules

## BR-MONEY-001 — Base and Accounting Currency

USD is the Property's base and accounting currency.

All financial transactions are recorded in USD. Every Refund must be paid and
recorded in USD; KHR is only a Payment-conversion option. Original KHR and
conversion-rate facts remain audit evidence and are never rewritten (DL-060).

All Invoices and Customer Credit balances are denominated and displayed in USD.
Receiving a Payment in KHR must not turn an Invoice into a dual-currency Invoice.

---

## BR-MONEY-002 — Supported Payment Currencies

Payments may be received in USD or KHR only.

When KHR is selected, the Payment interface may display the KHR equivalent of the
USD obligation using the applicable System Exchange Rate.

---

## BR-MONEY-003 — Safe Monetary Arithmetic

Authoritative monetary calculation must use integer minor units or exact-decimal
arithmetic. Binary floating-point must not be used as the authoritative
representation of money.

---

## BR-MONEY-004 — Preferred Exchange-rate Source

The preferred external reference for USD/KHR conversion is the ABA Bank USD/KHR
Sell rate. No different external exchange-rate provider is approved by this
document.

---

## BR-MONEY-005 — System Exchange Rate

The System Exchange Rate is calculated as:

```text
ABA-equivalent USD/KHR Sell Reference Rate × 1.005
```

The 1.005 multiplier represents the approved 0.5% markup.

---

## BR-MONEY-006 — Exchange-rate Rounding

If the marked-up KHR-per-USD System Exchange Rate has a fractional result, it is
rounded upward to the next whole KHR.

Example:

```text
4,062 × 1.005 = 4,082.31
System Exchange Rate = 4,083 KHR/USD
```

---

## BR-MONEY-007 — Rate Selection at Payment Confirmation

The applicable System Exchange Rate is selected and preserved when receipt of the
Payment is actually confirmed. A later rate change must never recalculate that
historical Payment.

---

## BR-MONEY-008 — Manual Reference-rate Fallback

If the automatic ABA reference cannot be obtained, an authorized user may enter
the ABA-equivalent reference Sell rate manually.

The system must then apply the same 0.5% markup and upward whole-KHR
exchange-rate rounding. Manual entry must not bypass the standard formula.

---

## BR-MONEY-009 — Final KHR Payable-amount Rounding

The KHR equivalent is calculated using the rounded System Exchange Rate. If the
resulting payable KHR amount is fractional, the final payable amount is rounded
upward to the next whole KHR, not half-up.

---

## BR-MONEY-010 — Exchange-rate Audit History

Every KHR Payment must preserve:

- reference rate;
- approved 0.5% markup;
- resulting System Exchange Rate;
- applicable date and time;
- automatic source or manual-entry information;
- USD accounting value; and
- KHR amount.

---

## BR-MONEY-011 — Authoritative Payment-channel Settlement

When KHQR or another accepted bank Payment channel provides an authoritative
actual conversion, settlement amount, or settlement rate, the actual transaction
information must be preserved. It must not later be rewritten using a different
rate.

---

## BR-MONEY-012 — General Proration and Monetary Rounding

Where proration is approved:

```text
Prorated Amount
=
Monthly Amount × Inclusive Billable Calendar Days
-------------------------------------------------
Actual Calendar Days in That Month
```

The intermediate daily result is not rounded. The final USD monetary result is
rounded to the nearest cent using half-up rounding unless a specific approved
rule requires different rounding.

---

## BR-MONEY-013 — Business Dates and Timezone

Start and end dates are inclusive where the applicable rule defines an inclusive
date range. Scheduled business actions and end-of-date processing use the Property's
authoritative `Asia/Phnom_Penh` timezone under BR-PROP-003.

---

# 28. Audit Rules

## BR-AUDIT-001 — Minimum Audit Content

Every auditable event must identify the actor, action, date and time, reason,
previous state or value, resulting state or value, and affected business record.

---

## BR-AUDIT-002 — Reservation Audit

Reservation activation, extension, expiration, cancellation classification,
Unit release, and move-in transition must preserve their source, authorization,
dates, reasons, and prior values.

---

## BR-AUDIT-003 — Lease and Occupancy Audit

Signing, renewal records, Notices, warning letters, termination, Move-in,
Move-out, Occupancy corrections, and Unit transitions must remain historically
traceable.

A Signer's signature time and the Lease signing time are the database's own time
at the moment of the command. No browser or device clock sets them, so a device
clock cannot refuse a signing or make a signature look earlier (owner answer to
Q-2026-10-14-110).

The Lease termination time is also the database's own time at the moment of the
termination command; the actual termination date stays a staff-entered date (owner
answer (a) to Q-2026-10-14-112 point 1, V1-056 sub-slice 10i-1).

Nonpayment Warning Notices and Serious Nonpayment Default conditions must preserve
their source Rent obligation, elapsed-day boundary, amount snapshot, issue or event
time, actor, communication or document linkage where recorded, cure history, and
subsequent management action.

---

## BR-AUDIT-004 — Meter and Estimation Audit

Reading corrections, Meter failure and replacement, estimation authorization,
period boundaries, historical or future actual data used, calculations, and
resulting consumption must remain reconstructable.

---

## BR-AUDIT-005 — Rate Audit

Rent, Utility, Service, and exchange-rate history must preserve source, effective
date and time, selected historical value, calculation, and authorization where
applicable.

---

## BR-AUDIT-006 — Invoice, Adjustment, and Late-payment Audit

Invoice creation, DRAFT correction, issuance, line sources, status changes,
Adjustments, Due Date source, and VOID events must preserve original and resulting
financial facts and all linkages.

Late-payment proposals and final decisions must preserve the source Invoice and its
Due Date, assessment balance, default and actual percentages, default and actual
amounts, management actor, reason, assessment timestamp, confirmation or waiver
timestamp, final confirmed, reduced, or waived outcome, and any resulting positive
Late-payment Charge obligation.

The obligation's original amount, remaining balance, Payment and Customer Credit
application history, satisfaction, correction, and reversal history must remain linked
to the decision, Customer, and source Invoice.

---

## BR-AUDIT-007 — Payment and Allocation Audit

Payment confirmation, payer intent, currency conversion, Allocation proposal and
posting, target obligation and line/category breakdown, Customer designation,
authorized confirmation, Allocation Reversal, Payment Reversal, Customer Credit
recognition and application, Receipt issuance and reprint, and Refund must remain
separately traceable.

---

## BR-AUDIT-008 — Deposit Audit

Every Deposit receipt, suggested amount, accepted required amount, authorized
Reservation-stage override, actor, timestamp, reason, balance, application,
forfeiture/disposition, governing event, and Refund must remain linked and
reconstructable by Deposit type.

---

## BR-AUDIT-009 — Final Settlement Audit

Final Settlement must preserve every input, ordering step, calculation,
application, disposition, Refund, remaining balance, authorization, and
post-closure correction.

---

## BR-AUDIT-010 — Permanent Audit History

Audit history is permanent. It must not be physically deleted, silently
rewritten, or replaced by only the latest value.

---

## BR-AUDIT-011 — Customer Account Ledger Reconciliation

The Customer Account Ledger must be reconstructable and reconcilable to its underlying
authoritative financial events. Every displayed charge, Payment, Credit, Refund,
Adjustment, Deposit event, Late-payment Charge, application, reversal, and balance must
retain or derive its source linkage. A derived or materialized Ledger representation
must not conceal disagreement with the authoritative records.

---

# 29. Authorization Rules

## BR-AUTH-001 — Explicit Authorization

Every action described as authorized in this document requires an authenticated
user with permission for that action. The complete role and permission matrix is
defined in the later Security Model and must not weaken these requirements.

---

## BR-AUTH-002 — Reservation Authorization

Reservation extension, exceptional cancellation classification, and correction
of Reservation dates or reasons require authorization and audit.

Amended by DL-080 (owner, 2026-10-20): extending a Reservation needs a Manager: the capability is in the default Owner and Manager bundles, not in the Staff bundle (DL-074).

---

## BR-AUTH-003 — Exchange-rate Authorization

Manual entry of the ABA-equivalent reference Sell rate is permitted only when the
automatic source cannot be obtained and requires authorization and audit.

---

## BR-AUTH-004 — Utility Estimate Authorization

Confirmed broken-Meter estimation, its inputs, and any correction require
authorization. Ordinary missing readings cannot be authorized into estimates.

---

## BR-AUTH-005 — Lease and Move-out Authorization

Lease signing, renewal records, Termination Notices, violation warning letters,
termination, and correction of actual Move-in or Move-out facts require their
applicable authorization.

Issuance of a formal Rent Nonpayment Warning Notice, recording and acting on a
Serious Nonpayment Default, and every resulting termination decision require their
applicable authorization. Elapsed time alone grants no termination authority.

Amended by DL-080 (owner, 2026-10-20): signing and terminating a Lease need a Manager: the capabilities are in the default Owner and Manager bundles, not in the Staff bundle (DL-074).

---

## BR-AUTH-006 — Invoice and Late-payment Authorization

Manual or exceptional Invoice issuance, issued-Invoice Adjustment, Due Date
recording for a non-recurring obligation, dependency correction, and VOID require
authorization and reason as applicable.

Confirming, reducing, or waiving a proposed late-payment charge is restricted to
authorized management. A positive approved charge requires the linked explicit
Late-payment Charge obligation in BR-INV-055 and BR-LATE-001; ordinary staff cannot
post, vary, correct, or reverse it arbitrarily.

Amended by DL-076 (owner, 2026-10-20): the late-payment charge is added by the app at 00:00 on the first day after the Due Date, with no confirmation. Only the Owner or a Manager may reduce or waive it, after a Customer complaint of a staff mistake, with one of three fixed reasons and a required "What happened" text; the amount only goes down.

---

## BR-AUTH-007 — Payment and Allocation Authorization

Payment confirmation or correction, manual Allocation posting, Allocation
Reversal, and Payment Reversal require authorization and audit. A deterministic
proposal is not authorization to post. This includes confirmation of Customer-
designated targets, between-Invoice FIFO proposals, within-Invoice Rent-first proposals,
Invoice-line or obligation detail, and Late-payment Charge applications.

---

## BR-AUTH-008 — Credit, Refund, and Deposit Authorization

Customer Credit recognition and application, Refund, and Deposit
forfeiture/disposition require authorization, source linkage, reason, and audit.
Customer authorization required by the Credit-versus-Refund decision must also be
preserved.

An override of the suggested Reservation Security Deposit amount requires authorized
management and preservation of the accepted amount, actor, timestamp, and reason.

Amended by DL-068 and DL-069 (2026-10-03): Refunds, deposit use, deposit forfeiture and wrong-Invoice Payment moves are confirmed only by a holder of `financial.approve` (BR-AUTH-010).

---

## BR-AUTH-009 — Final Settlement Authorization

Final Settlement application, finalization, closure, and post-closure correction
require authorization and complete audit history.

Amended by DL-068 and DL-069 (2026-10-03): Final Settlement and post-settlement corrections are confirmed only by a holder of `financial.approve` (BR-AUTH-010).

---

## BR-AUTH-010 — Financial Approval Drafts

Final Settlement, deposit use, deposit forfeiture, Refunds, wrong-Invoice Payment moves and post-settlement corrections are recorded first as drafts. Staff may record a draft; only a holder of the capability `financial.approve` (the Owner, a Manager or another user given it) confirms it. A draft has no financial effect until it is confirmed (DL-068, DL-069).

---

# 30. Owner Decision Status

## Resolved: OOD-BR-001 — Initial Rent Invoice Due Date

The Owner resolved this item: the Initial Rent Invoice Due Date is proposed as the
Lease Start Date plus five calendar days under BR-RENT-009, with an authorized override. The recurring Due Date remains the
5th of the billed month and is not overridden by the Lease.

## Resolved: OOD-BR-002 — Late-payment Calculation Base

The Owner resolved this item under BR-INV-052: calculate the default 10% once against
the total remaining unpaid overdue balance of the applicable source Invoice at
assessment, excluding amounts already validly paid or applied and without separate
line-by-line percentages.

## Resolved: OOD-BR-003 — Overdue Trigger and Management Posting

The Owner resolved this item under BR-INV-051 and BR-INV-053: the Due Date is the last
timely calendar day in Asia/Phnom_Penh, overdue begins the next calendar day, the old
ten-day grace concept is removed, and management must confirm, reduce, or waive the
proposed charge rather than the system posting it automatically.

Replaced by DL-076 (owner, 2026-10-20): the system now adds the charge by itself the day after the Due Date; management no longer confirms it. Reduce or waive only after a Customer complaint of a staff mistake.

## Resolved: OOD-BR-004 — One Final Decision per Invoice

The Owner resolved this item under BR-INV-054: one final late-payment decision is
permitted for each applicable source Invoice. It never repeats, compounds, recurses,
or reopens after a confirmed, reduced, or waived decision.

## Resolved: OOD-BR-005 — Rent Nonpayment Warning and Serious Default

The Owner resolved this item under BR-LEASE-026 through BR-LEASE-030: calendar days
are counted after the Rent Due Date; a formal Notice applies at 20 days when still
unpaid; a Serious Nonpayment Default is recorded at 30 days when still unpaid; and
actual termination remains a separate authorized process subject to applicable
warning and signed-Lease rules.

## Resolved: OOD-BR-006 — Initial Recurring-Service Period

The Owner resolved this item under BR-SVC-012: applicable configured recurring
Services follow the same day-1-through-20/day-21-or-later Initial Invoice period as
Rent, share the Initial Rent Invoice Due Date, and resume normal billing without
duplicate or overlapping periods.

## Resolved: OOD-BR-007 — Positive Late-payment Charge Representation

The Owner resolved this item under BR-INV-055 and BR-LATE-001 through BR-LATE-006. A
confirmed positive amount creates a separate immediately payable Late-payment Charge
obligation linked to exactly one Customer and one source overdue Invoice. It is payable
at management confirmation without another Invoice or Due Date and is not an Invoice,
Invoice Category, Miscellaneous Charge, source-Invoice line, or source-principal
modification. A waiver creates no receivable, and a reduction creates only the approved
reduced obligation.

## Resolved: OOD-BR-008 — Mixed Rent-Invoice Partial-value Attribution

The Owner resolved this item under BR-PAY-019 through BR-PAY-040 and BR-CREDIT-005
through BR-CREDIT-007. Payment Allocations and Customer Credit applications preserve
sufficient line or obligation detail. A valid Customer designation may control the
application. Without designation, the system first retains the existing FIFO proposal
between applicable Invoices and then proposes Rent first followed by recurring-Service
lines within each selected mixed Invoice. Authorized staff must confirm before posting.
Remaining Rent after confirmed applications controls the 20-day and 30-day Rent
nonpayment procedures.

There are currently no unresolved Owner decisions in `001_DOMAIN_MODEL.md` or this
document.

---

# 31. Completion and Cross-rule Consistency

## 31.1 Authoritative Scope

This document defines the approved business-policy matters delegated to Business
Rules by `001_DOMAIN_MODEL.md`. Section 30 preserves the resolved decision identifiers
and confirms that there are currently no unresolved Owner decisions in these two
authoritative documents. Implementations must not reinterpret these rules to create new
statuses, charges, fees, penalties, currencies, exchange providers, estimation
methods, termination rights, Refund rights, or authorization policies.

## 31.2 Consistent Invoice Ownership and Association

`001_DOMAIN_MODEL.md` and this document use the same approved Invoice model:

- every Invoice belongs to exactly one Customer;
- an Invoice may additionally be associated with zero or one Lease;
- a Lease-associated Invoice must remain consistent with its Customer, Unit,
  obligation, period, and Lease context;
- every Rent Invoice requires the applicable signed Lease; and
- optional Lease association does not authorize arbitrary non-Lease charges or
  new Invoice categories.

## 31.3 Consistent Utility Rate and Pet Deposit Policies

`001_DOMAIN_MODEL.md` and this document also use the same approved policies for:

- Utility Rate selection on the Utility Invoice generation date, whole-period
  application of that selected rate, and permanent preservation of issued
  Utility Invoice history; and
- Pet Deposit requirement only when a pet is approved and the applicable signed
  Lease terms require that Deposit, including the approved timing for a pet
  introduced after move-in, and the separate application/refund rules in sections
  25 and 26.

The two authoritative documents are mutually consistent on these policies.

## 31.4 Stable Rule Identifiers

Every `BR-*` identifier in this document is unique and is the stable reference
for downstream specifications. A rule must not be reinterpreted through an older
placeholder document.

## 31.5 Financial Integrity

Original financial records remain permanent. Corrections use explicit linked
Adjustment, Reversal, application, disposition, Credit, Refund, or other approved
events so that every balance and historical fact can be reconstructed.

## 31.6 Downstream Conformance

Database, API, UI, testing, security, and deployment specifications must conform
to this document and `001_DOMAIN_MODEL.md`. Any new material policy requires
controlled Owner approval rather than an implementation assumption.

## 31.7 Consistent Customer Financial Model

`001_DOMAIN_MODEL.md` and this document use the same financial distinctions:

- Invoice and Invoice lines are issued receivables whose balances and status remain
  derived from valid detailed applications;
- a Late-payment Charge is a separate non-Invoice obligation linked to one source
  Invoice and one Customer;
- Payment is the authoritative fact that money was received;
- Receipt is the customer-facing acknowledgment of that Payment;
- Payment Allocation and Customer Credit application preserve target obligation and
  sufficient Invoice-line detail;
- Customer Credit, unallocated Payment, Deposits, Invoice balances, and Late-payment
  Charge balances remain distinct;
- Refund is an outbound event rather than a negative Payment; and
- Customer Account Ledger is a reconstructable unified view, not a General Ledger or a
  second financial source of truth.

General vendor Accounts Payable and full General Ledger accounting remain outside scope.
