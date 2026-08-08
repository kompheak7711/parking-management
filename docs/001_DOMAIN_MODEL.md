# 001 - Domain Model

**Project:** Property Rental Management System
**Document:** Domain Model
**Version:** 1.0
**Status:** Draft
**Audience:** Product Owner, Business Analysts, Software Architects, Developers, QA Engineers

---

# 1. Purpose

This document defines the business domain of the Property Rental Management System.

Its purpose is to establish a common business language and accurately model the real-world operation of a residential rental property before any database schema, APIs, user interfaces, or implementation details are designed.

This document intentionally focuses on **what the business is** rather than **how the software is implemented**.

Implementation details such as SQL tables, REST APIs, user interfaces, permission matrices, and deployment architecture are documented separately.

---

# 2. Scope

The system manages the complete lifecycle of residential rental operations for **one property**.

The domain includes:

- Unit management
- Customer management
- Reservation management
- Lease management
- Occupancy management
- Utility meter management
- Utility readings
- Invoice generation
- Payment processing
- Deposit management
- Move-in
- Move-out
- Final settlement
- Historical auditing

The system does not include:

- Accounting or General Ledger
- Payroll
- Human Resources
- Property construction management
- Building maintenance work orders
- Multi-property portfolio management
- Owner accounting
- Government tax reporting

These domains may be integrated in the future but are outside the scope of this system.

---

# 3. Domain Vision

The Property Rental Management System is designed around one fundamental principle:

> Every significant business event occurring during the lifecycle of a rental unit must be accurately represented, historically preserved, and fully auditable.

The system is intended to become the single source of truth for all operational, financial, and occupancy information related to a single rental property.

The domain model prioritizes:

- Business correctness
- Historical accuracy
- Financial integrity
- Traceability
- Auditability
- Long-term maintainability

---

# 4. Core Business Principles

The following principles govern every part of the domain model.

## 4.1 One Property per Application

Each deployed application manages exactly one property.

The Property entity represents the entire apartment building managed by the application.

Supporting multiple properties within the same application is intentionally outside the current business scope.

---

## 4.2 Business First

The domain model reflects the actual business rather than software implementation.

Business concepts take precedence over database optimization or programming convenience.

---

## 4.3 Historical Data is Never Lost

Business history is permanently preserved.

Instead of deleting records, the system records business transitions over time.

Examples include:

- Previous tenants
- Previous leases
- Historical utility rates
- Historical meter replacements
- Previous invoices
- Previous payments
- Historical deposits
- Historical reservations

Historical information must remain available for reporting and auditing.

---

## 4.4 Financial Integrity

Every financial transaction must be traceable.

Money cannot appear, disappear, or be silently modified.

Every financial adjustment must have a corresponding business event and audit record.

---

## 4.5 One Source of Truth

Every business concept has one authoritative owner.

Examples:

- Unit availability is determined by Reservations and Leases.
- Occupancy is determined by Occupancy records.
- Financial balances are determined from invoices, payments, credits, deposits, and settlements.
- Utility consumption is determined from Utility Readings.

Information should never be duplicated when it can be derived from existing business records.

---

# 5. Ubiquitous Language

The following terminology shall be used consistently throughout the project.

## Property

The apartment building managed by this application.

Each application contains exactly one Property.

---

## Unit

A rentable residential space within the Property.

Each Unit belongs to exactly one Property.

A Unit has:

- Unit Number
- Floor
- Unit Type
- Current Status

Unit Types:

- Studio
- One Bedroom
- Two Bedroom
- Three Bedroom

---

## Customer

A person recorded by the business.

A Customer may participate in multiple business processes over time.

Examples include:

- Reservation customer
- Primary tenant
- Lease signer
- Occupant
- Former tenant
- Payment payer

The system does not classify Customers into permanent customer types.

Customer roles are determined by their relationships with business entities rather than by a fixed customer category.

---

## Reservation

A Reservation temporarily holds a Unit for one Customer before move-in. It may
coexist with a DRAFTED or SIGNED Lease for the same planned tenancy while the
Reservation remains ACTIVE.

A Reservation:

- reserves one Unit
- belongs to one Customer
- requires a Security Deposit
- has an expiration date
- may be cancelled
- may proceed to move-in

Reservation statuses:

- ACTIVE
- CANCELLED
- MOVED_IN

---

## Security Deposit

A mandatory financial liability held by the Property.

The Security Deposit may be paid in multiple installments.

Typically, a Customer pays only part of the required Security Deposit during Reservation and pays the remaining balance before move-in.

The Security Deposit:

- is not rental income
- is not refundable during an active Lease
- is applied only during final settlement
- may be partially or fully refunded after settlement
- must remain fully auditable

---

## Pet Deposit

An additional Deposit liability that applies only when both:

- the pet is approved; and
- the applicable signed Lease terms require a Pet Deposit.

Pet Deposits follow the same financial principles as Security Deposits.

---

## Lease

A legally binding rental agreement between the Property and a Customer.

A Lease:

- applies to one Unit
- has exactly one Primary Tenant
- may have multiple Lease Signers
- may have multiple Occupants
- requires a Security Deposit
- may require a Pet Deposit

Lease statuses:

- DRAFTED
- SIGNED
- CANCELLED
- TERMINATED

---

## Primary Tenant

The principal Customer responsible for managing the Lease.

Every Lease has exactly one Primary Tenant.

A Customer may become the Primary Tenant on multiple Leases over time.

---

## Lease Signer

A Customer who signs the Lease agreement.

All Lease Signers share joint responsibility for the entire Lease balance.

The system does not divide responsibility by percentage.

A Lease Signer is not required to live in the Unit.

---

## Occupant

A Customer who physically lives in the Unit.

Occupancy records represent who resides in the Unit and when.

Occupancy does not determine financial responsibility.

---

## Utility Meter

A physical electricity or water meter assigned to a Unit.

A Unit may have multiple historical Utility Meters due to replacement.

Only one active meter may exist for each utility type.

---

## Utility Reading

A recorded reading taken from a Utility Meter.

Utility Readings determine customer utility usage and utility billing.

Historical readings are never modified or reassigned to different meters.

---

## Invoice

A financial document requesting payment.

Invoice categories include:

- Rent
- Utilities
- Service Charges
- Damage Charges
- Miscellaneous Charges

Invoices represent receivables owed to the Property.

---

## Payment

Money received from a Customer.

Payments may be allocated to one or more invoices by authorized staff.

The system supports:

- Full payment
- Partial payment
- Advance payment
- Overpayment
- Customer credit
- Refund
- Reversal

---

## Final Settlement

The business process performed after Lease termination.

Final Settlement determines:

- Outstanding invoices
- Damage charges
- Utility charges
- Deposit application
- Refunds
- Remaining balances

A Lease is financially complete only after Final Settlement has been finalized.

---

# 6. High-Level Domain Overview

The Property Rental Management System models the complete lifecycle of a residential tenancy.

```text
Property
    │
    ├── Units
    │      │
    │      ├── Reservation
    │      │         │
    │      │         └── Security Deposit
    │      │
    │      ├── Lease
    │      │      ├── Primary Tenant
    │      │      ├── Lease Signers
    │      │      └── Occupants
    │      │
    │      ├── Utility Meters
    │      │
    │      └── Utility Readings
    │
    ├── Customers
    │      └── Invoices
    ├── Payments
    ├── Credits
    └── Final Settlement
```

This domain is intentionally centered around the lifecycle of a Unit—from reservation through lease, occupancy, billing, payment, move-out, and historical archival—while ensuring every business and financial event remains permanently traceable.

---

# 7. Domain Building Blocks

The Property Rental Management System follows Domain-Driven Design (DDD) principles by organizing the business into Aggregates, Entities, Value Objects, and Domain Services.

The purpose of this section is to define the business ownership and lifecycle of each concept.

No database schema or implementation details are included in this document.

---

# 8. Aggregate Overview

The domain consists of the following Aggregate Roots.

| Aggregate        | Purpose                                                       |
| ---------------- | ------------------------------------------------------------- |
| Property         | Represents the apartment building managed by the application. |
| Unit             | Represents a rentable residential unit.                       |
| Customer         | Represents a person recorded by the business.                 |
| Reservation      | Holds a Unit for one Customer before move-in.                 |
| Lease            | Represents the legal rental agreement.                        |
| Utility Meter    | Represents a physical utility meter installed on a Unit.      |
| Utility Reading  | Represents recorded meter readings used for billing.          |
| Invoice          | Represents charges owed by a Customer.                        |
| Payment          | Represents money received from a Customer.                    |
| Deposit          | Represents Security Deposit and Pet Deposit liabilities.      |
| Final Settlement | Represents the financial closing of a Lease.                  |

Although these aggregates interact with one another, each Aggregate is responsible for protecting its own business consistency.

---

# 9. Aggregate Definitions

## 9.1 Property Aggregate

### Purpose

The Property Aggregate represents the apartment building managed by the application.

Exactly one Property exists within each application.

The Property Aggregate owns the overall business environment but does not directly manage operational transactions.

### Responsibilities

- Store property information
- Define the property's identity
- Own all Units
- Provide the root of the business hierarchy

### Owns

- Units

### Referenced By

- All operational aggregates

### Lifecycle

```text
Created
    │
    ▼
Active
```

The Property is expected to remain active for the lifetime of the application.

---

## 9.2 Unit Aggregate

### Purpose

A Unit represents a rentable residential space.

A Unit exists independently of Reservations, Leases, or Customers.

### Responsibilities

- Maintain unit identity
- Track current availability
- Record current operational status
- Associate Utility Meters
- Preserve historical leasing records

### Attributes

- Unit Number
- Floor
- Unit Type
- Status

### Unit Types

- Studio
- One Bedroom
- Two Bedroom
- Three Bedroom

### Unit Statuses

- VACANT
- RESERVED
- OCCUPIED
- UNDER_MAINTENANCE
- CLEANING
- OUT_OF_SERVICE

### Business Invariants

- A Unit belongs to exactly one Property.
- A Unit may have many Reservations over time.
- A Unit may have many historical Leases.
- Signed Leases for the Unit must not have overlapping contractual periods.
- A Unit may have multiple historical Utility Meters.
- A Unit may have only one active Utility Meter for each Utility Type.

---

## 9.3 Customer Aggregate

### Purpose

The Customer Aggregate represents a person known by the business.

A Customer is intentionally role-neutral.

The Customer does not permanently become a Tenant, Occupant, Reservation Customer, or Lease Signer.

Instead, those roles are determined through relationships with other business entities.

### Responsibilities

- Store personal information
- Maintain customer identity
- Preserve customer history

### Customer Roles

A Customer may become:

- Reservation Customer
- Primary Tenant
- Lease Signer
- Occupant
- Former Occupant
- Payment Payer

These are business relationships rather than customer types.

### Business Invariants

- A Customer may reserve many Units over time.
- A Customer may become Primary Tenant on many Leases.
- A Customer may sign many Leases.
- A Customer may occupy many Units over time.
- Customer records are never deleted because historical financial records depend on them.

---

## 9.4 Reservation Aggregate

### Purpose

A Reservation temporarily holds a Unit for one Customer before move-in.

### Responsibilities

- Reserve a Unit
- Record Reservation period
- Record Security Deposit received
- Track expiration
- Link to resulting Lease after move-in

### Reservation Status

- ACTIVE
- CANCELLED
- MOVED_IN

### Business Invariants

- One Reservation belongs to one Unit.
- One Reservation belongs to one Customer.
- One Reservation results in at most one Lease.
- A cancelled Reservation never creates a Lease.
- A moved-in Reservation cannot return to ACTIVE.

Reservation extension history is recorded separately and does not change the Reservation status.

---

## 9.5 Lease Aggregate

### Purpose

The Lease Aggregate represents the legal rental contract.

It controls occupancy, billing, deposits, and the tenancy lifecycle.

### Responsibilities

- Manage contractual agreement
- Assign Primary Tenant
- Record Lease Signers
- Record Occupants
- Manage deposits
- Generate recurring rent obligations
- Support termination

### Lease Status

- DRAFTED
- SIGNED
- CANCELLED
- TERMINATED

### Business Invariants

- A Lease belongs to one Unit.
- A Lease has exactly one Primary Tenant.
- A Lease may have multiple Lease Signers.
- Every Lease Signer is jointly responsible for the full Lease balance.
- A Lease may have many Occupants.
- Signed Leases for the Unit must not have overlapping contractual periods.
- A terminated Lease never becomes signed again.
- A cancelled Lease was never activated.

---

## 9.6 Utility Meter Aggregate

### Purpose

Represents a physical utility meter installed on a Unit.

### Responsibilities

- Identify the physical meter
- Record installation history
- Preserve replacement history
- Associate Utility Readings

### Utility Types

- Electricity
- Water

### Business Invariants

- A Utility Meter belongs to one Unit.
- A Utility Meter measures only one Utility Type.
- A Utility Meter cannot belong to multiple Units.
- Historical Utility Meters remain permanently recorded.
- Replacing a Utility Meter never changes historical Utility Readings.

---

## 9.7 Utility Reading Aggregate

### Purpose

Represents an actual meter reading used for billing.

### Responsibilities

- Record reading value
- Record reading date
- Preserve historical consumption

### Business Invariants

- Every Utility Reading belongs to one Utility Meter.
- Utility Readings are permanent historical records.
- Historical readings cannot be reassigned to another meter.
- Utility bills are calculated from Utility Readings.

---

## 9.8 Invoice Aggregate

### Purpose

Represents money owed to the Property.

### Responsibilities

- Record charges
- Maintain invoice balance
- Track payment allocation
- Preserve financial history

### Invoice Categories

- Rent
- Utilities
- Service Charges
- Damage Charges
- Miscellaneous Charges

### Business Invariants

- Every Invoice belongs to exactly one Customer.
- An Invoice may additionally be associated with zero or one Lease.
- When a Lease association exists, the Invoice Customer, Unit, obligation,
  period, and Lease context must be consistent.
- Every Rent Invoice requires the applicable signed Lease.
- An Invoice balance cannot become negative.
- Invoice history is permanent.
- Voiding an Invoice preserves its historical record.

---

## 9.9 Payment Aggregate

### Purpose

Represents money received by the Property.

### Responsibilities

- Record payment received
- Allocate payments
- Maintain customer credits
- Record refunds
- Record reversals

### Business Invariants

- One Payment may pay multiple Invoices.
- One Invoice may receive multiple Payments.
- Payment allocation is performed manually by authorized staff.
- Payments are never physically deleted.

---

## 9.10 Deposit Aggregate

### Purpose

Represents money held as a liability rather than income.

The Deposit Aggregate manages both Security Deposits and Pet Deposits.

### Deposit Types

- Security Deposit
- Pet Deposit

### Responsibilities

- Record required deposit amount
- Record deposit payments
- Maintain outstanding balance
- Track application during Final Settlement
- Track refunds

### Business Invariants

- Deposits are liabilities.
- Security Deposit is mandatory.
- Security Deposit may be paid in installments.
- Security Deposit collected during Reservation remains the same Security Deposit after move-in.
- Pet Deposit exists only when a pet is approved and the applicable signed Lease
  terms require that Deposit.
- Deposits are applied only during Final Settlement.

---

## 9.11 Final Settlement Aggregate

### Purpose

Represents the financial closing process of a terminated Lease.

### Responsibilities

- Calculate outstanding balances
- Apply deposits
- Calculate refunds
- Produce final financial result

### Business Invariants

- Every terminated Lease must complete exactly one Final Settlement.
- Final Settlement belongs to exactly one terminated Lease.
- Final Settlement occurs only after Lease termination.
- Final Settlement permanently closes the Lease financially.
- Final Settlement is fully auditable.

---

# 10. Supporting Entities

Supporting Entities exist inside Aggregates and cannot exist independently.

---

## Lease Signer

Represents a Customer who signed the Lease agreement.

Responsibilities:

- Record legal responsibility
- Record signing information
- Preserve historical contract signers

Business Rules:

- One Lease may contain multiple Lease Signers.
- Every Lease Signer is jointly responsible for the entire Lease balance.
- A Lease Signer is not required to occupy the Unit.

---

## Occupancy

Represents a Customer physically living in the Unit.

Responsibilities:

- Record move-in date
- Record move-out date
- Preserve occupancy history

Business Rules:

- Occupancy does not determine financial responsibility.
- One Lease may have multiple Occupants.
- A Customer may occupy multiple Units over time.
- Occupancy history is never deleted.

---

## Payment Allocation

Represents the allocation of a Payment to one or more Invoices.

Business Rules:

- One Payment may allocate to many Invoices.
- One Invoice may receive many Payment Allocations.
- Allocation history is permanent.

---

## Reservation Extension Notice

Represents an approved extension of a Reservation expiration date.

Responsibilities:

- Preserve original expiration date
- Record new expiration date
- Record approval history

Business Rules:

- Creating an extension does not change Reservation status.
- Multiple extensions may exist if permitted by business rules.
- Extension history is permanent.

---

# 11. Value Objects

The following concepts are immutable Value Objects within the domain.

| Value Object        | Purpose                                   |
| ------------------- | ----------------------------------------- |
| Money               | Monetary amount with currency             |
| Date Range          | Reservation, Lease, and Occupancy periods |
| Unit Number         | Human-readable Unit identifier            |
| Meter Serial Number | Physical meter identifier                 |
| Customer Name       | Customer's legal name                     |
| Address             | Contact address                           |
| Phone Number        | Contact number                            |
| Email Address       | Contact email                             |

Value Objects have no independent identity and exist only as part of an owning Aggregate.

---

# 12. Aggregate Ownership Summary

```text
PROPERTY

UNIT

CUSTOMER

RESERVATION
└── Reservation Extension Notice

LEASE
├── Lease Signers
└── Occupancy

UTILITY METER
└── Utility Reading

INVOICE

DEPOSIT

FINAL SETTLEMENT

PAYMENT
└── Payment Allocation
```

Each item shown at the left margin is an Aggregate Root. Nested items are owned
supporting entities. Relationships among Aggregate Roots, including mandatory
Invoice Customer ownership and optional Lease association, are defined in
sections 14 and 15 rather than by nesting one Aggregate Root inside another.

---

# 13. Domain Relationships

This section defines how the core business concepts relate to one another.

These relationships describe business ownership and cardinality only. They are not database relationships or foreign key definitions.

---

# 14. High-Level Domain Relationship Model

```text
Property
│
└── Unit
      │
      ├── Reservation
      │        │
      │        ├── Customer (Reservation Customer)
      │        ├── Deposit (Security Deposit)
      │        └── Reservation Extension Notice
      │
      ├── Lease
      │      │
      │      ├── Primary Tenant (Customer)
      │      ├── Lease Signers (Customer)
      │      ├── Occupants (Customer)
      │      ├── Deposit
      │      ├── Associated Invoice (optional per Invoice)
      │      └── Final Settlement (exactly one when TERMINATED)
      │
      ├── Utility Meter
      │      └── Utility Reading
      │
      └── Historical Leasing Records

Payment
│
└── Payment Allocation
      │
      └── Invoice

Customer
│
└── Invoice (exactly one Customer per Invoice)

Invoice ─────── optional zero-or-one association ───────► Lease
```

The domain follows the natural business lifecycle of a rental unit.

A Unit progresses through reservation, leasing, occupancy, billing, payment, move-out, and historical archival while preserving every significant business event.

---

# 15. Aggregate Relationships

## 15.1 Property → Unit

Relationship

```
One Property
        │
        └────── Many Units
```

Rules

- One application manages exactly one Property.
- Every Unit belongs to one Property.
- A Unit cannot exist without a Property.

---

## 15.2 Unit → Reservation

Relationship

```
One Unit
      │
      └────── Many Reservations (historically)
```

Rules

- A Unit may have many Reservations over time.
- Only one active Reservation may exist for a Unit.
- A cancelled Reservation releases the Unit.
- A moved-in Reservation is linked to the resulting Lease.

---

## 15.3 Reservation → Customer

Relationship

```
One Reservation
        │
        └────── One Customer
```

Rules

- Reservation always belongs to one Customer.
- Reservation cannot contain multiple Customers.
- The Reservation Customer is expected to become the Primary Tenant if the Reservation proceeds to move-in.

---

## 15.4 Reservation → Security Deposit

Relationship

```
One Reservation
        │
        └────── One Security Deposit
```

Rules

- Security Deposit is mandatory.
- Security Deposit may be partially paid.
- The amount collected during Reservation remains the same Security Deposit after move-in.
- The system never creates a second Security Deposit when the Lease begins.

---

## 15.5 Reservation → Lease

Relationship

```
Reservation
      │
      └────────── Zero or One Lease
```

Rules

- A Reservation may never produce a Lease.
- A moved-in Reservation always references exactly one Lease.
- A Reservation cannot create multiple Leases.

---

## 15.6 Unit → Lease

Relationship

```
One Unit
      │
      └────── Many Leases (historically)
```

Rules

- Signed Leases for the Unit must not have overlapping contractual periods.
- Historical Leases remain permanently recorded.
- A terminated Lease never becomes active again.

---

## 15.7 Lease → Primary Tenant

Relationship

```
One Lease
      │
      └────── One Customer
```

Rules

- Every Lease has exactly one Primary Tenant.
- A Customer may become Primary Tenant on many Leases over time.
- The Primary Tenant manages the Lease relationship with the Property.

---

## 15.8 Lease → Lease Signers

Relationship

```
One Lease
      │
      └────── One or Many Lease Signers
```

Rules

- Every Lease has at least one Lease Signer.
- The Primary Tenant must also be a Lease Signer.
- Additional Lease Signers are optional.
- All Lease Signers are jointly responsible for the full Lease balance.
- Financial responsibility is never divided.

---

## 15.9 Lease → Occupancy

Relationship

```
One Lease
      │
      └────── Many Occupancy Records
```

Rules

- Occupancy records identify who physically lives in the Unit.
- Occupancy does not determine financial responsibility.
- A Lease may contain zero or many Occupants before move-in.
- Historical Occupancy is permanently preserved.

---

## 15.10 Unit → Utility Meter

Relationship

```
One Unit
      │
      └────── Many Utility Meters
```

Rules

- Historical meters remain permanently recorded.
- One active Electricity Meter maximum.
- One active Water Meter maximum.
- Replacing a meter never changes previous Utility Readings.

---

## 15.11 Utility Meter → Utility Reading

Relationship

```
One Utility Meter
         │
         └──────── Many Utility Readings
```

Rules

- Utility Readings belong to exactly one Utility Meter.
- Readings cannot be transferred to another meter.
- Historical readings remain unchanged.

---

## 15.12 Customer → Invoice and Optional Lease Association

Relationship

```
One Customer
      │
      └──────── Zero or Many Invoices

One Lease
      │
      └──────── Zero or Many Associated Invoices

Each Invoice ──────── Exactly One Customer
Each Invoice ──────── Zero or One Lease
```

Rules

- Every Invoice has one explicit Customer owner.
- Lease association is optional at the general Invoice level.
- When a Lease association exists, Customer, Unit, obligation, period, and Lease
  context must be consistent.
- Rent Invoices require the applicable signed Lease.
- Rent invoices are generated automatically.
- Utility invoices are generated from Utility Readings.
- Damage and miscellaneous invoices are manually created.
- Optional Lease association does not authorize arbitrary non-Lease charges or
  additional Invoice categories.
- Invoice history is permanent.

---

## 15.13 Payment → Invoice

Relationship

```
Payment
     │
     └────── Payment Allocation
                  │
                  └────── Invoice
```

This is a many-to-many relationship.

Rules

- One Payment may pay many Invoices.
- One Invoice may receive many Payments.
- Allocation is performed manually.
- Allocation history cannot be deleted.

---

## 15.14 Lease → Deposit

Relationship

```
Lease
    │
    ├────── Security Deposit
    └────── Pet Deposit (optional)
```

Rules

- Security Deposit is mandatory.
- Pet Deposit exists only when a pet is approved and the applicable signed Lease
  terms require that Deposit.
- Deposits remain liabilities throughout the Lease.
- Deposits are resolved during Final Settlement.

---

## 15.15 Lease → Final Settlement

Relationship

```
One Terminated Lease
      │
      └──────── One Final Settlement
```

Rules

- Final Settlement occurs only after Lease termination.
- Every terminated Lease must complete exactly one Final Settlement.
- Final Settlement permanently closes the financial lifecycle of the Lease.

---

# 16. Business Lifecycles

This section describes the lifecycle of major business concepts.

---

## 16.1 Unit Lifecycle

```text
VACANT
   │
   ▼
RESERVED
   │
   ▼
OCCUPIED
   │
   ├───────────────┐
   ▼               │
CLEANING           │
   │               │
   ▼               │
VACANT ◄───────────┘

UNDER_MAINTENANCE
        │
        ▼
OUT_OF_SERVICE
        │
        ▼
VACANT
```

Notes

- Reservation changes Unit status to RESERVED.
- Move-in changes Unit status to OCCUPIED.
- Move-out changes Unit to CLEANING before becoming VACANT.
- Maintenance may temporarily remove a Unit from rental.

---

## 16.2 Reservation Lifecycle

```text
Reservation Created
          │
          ▼
       ACTIVE
      /      \
     /        \
Cancelled   Moved In
```

Rules

- Reservation begins in ACTIVE state.
- Expiration extensions do not create a new status.
- A moved-in Reservation is permanently completed.
- Cancelled Reservations never become active again.

---

## 16.3 Lease Lifecycle

```text
Drafted
   │
   ├────────► Cancelled
   │
   ▼
Signed
   │
   ▼
Terminated
```

Rules

- Only Drafted Leases may be Cancelled.
- Only Signed Leases may be Terminated.
- Terminated Leases are permanent historical records.

---

## 16.4 Security Deposit Lifecycle

```text
Required
    │
    ▼
Partially Paid
    │
    ▼
Fully Paid
    │
    ▼
Held During Lease
    │
    ▼
Final Settlement
    │
 ┌──┴───────────────┐
 ▼                  ▼
Applied         Refunded
```

Notes

- Partial payments are permitted.
- The same Security Deposit continues from Reservation into the Lease.
- Deposits remain liabilities throughout their lifecycle.

---

## 16.5 Utility Meter Lifecycle

```text
Installed
     │
     ▼
Active
     │
     ▼
Replaced
```

Rules

- Historical Utility Meters are never deleted.
- Meter replacement preserves all historical readings.

---

## 16.6 Utility Reading Lifecycle

```text
Reading Recorded
        │
        ▼
Billing Generated
        │
        ▼
Historical Record
```

Rules

- Readings remain permanent.
- Corrections are handled through authorized modifications while preserving audit history.

---

## 16.7 Invoice Lifecycle

```text
DRAFT
  │
  ├──────────────► VOID
  │
  ▼
UNPAID
  │
  ├──────────────► VOID
  ├──────────────► PAID
  │
  ▼
PARTIALLY_PAID
  │
  ├──────────────► PAID
  └──────────────► VOID only after required financial reversals
```

Invoice status is determined by the approved issuance, allocation, Credit,
Deposit-application, reversal, and voiding rules in `002_BUSINESS_RULES.md`.
Voiding always preserves history.

---

## 16.8 Payment Lifecycle

```text
RECEIVED ─────────────────────────────► REVERSED
    │
    ├── unallocated          (derived allocation condition)
    ├── partially allocated  (derived allocation condition)
    └── fully allocated      (derived allocation condition)
```

Allocation progress is not a Payment receipt status. Unallocated excess remains
part of the RECEIVED Payment until the payer authorizes an approved Credit or
Refund disposition.

---

## 16.9 Final Settlement Lifecycle

```text
Lease Terminated
        │
        ▼
Settlement Created
        │
        ▼
Charges Calculated
        │
        ▼
Deposits Applied
        │
        ▼
Refund or Balance Due
        │
        ▼
Settlement Closed
```

Once closed, the Settlement becomes a permanent historical record.

---

# 17. Cross-Aggregate Invariants

The following business invariants span multiple Aggregates and must always remain true.

### Unit Availability

- A Unit cannot have more than one active Reservation.
- A Unit cannot have more than one signed Lease.

---

### Reservation Integrity

- Every Reservation belongs to exactly one Unit.
- Every Reservation belongs to exactly one Customer.

---

### Lease Integrity

- Every Lease has exactly one Primary Tenant.
- The Primary Tenant must also be a Lease Signer.
- Every signed Lease belongs to one Unit.

---

### Occupancy Integrity

- Occupancy records determine who lives in the Unit.
- Lease Signers determine contractual responsibility.
- Occupancy and contractual responsibility are intentionally separate concepts.

---

### Utility Integrity

- Historical Utility Readings always remain linked to the Utility Meter that produced them.
- Replacing a Utility Meter never alters historical billing records.

---

### Financial Integrity

- Deposits are liabilities.
- Payments never disappear.
- Invoice balances cannot become negative.
- Every financial adjustment must be auditable.

---

# 18. Financial Domain

The financial domain represents monetary obligations, receipts, liabilities,
credits, adjustments, and settlement activities belonging to Customers. A
financial record may additionally be associated with a Lease when its approved
business context requires that association.

The financial model is designed around the following principles:

- Every financial event must be traceable.
- Historical financial records must be preserved.
- Deposits are liabilities, not income.
- Payments and invoice allocations are separate concepts.
- Partial payment and overpayment are supported.
- Financial corrections must be performed through explicit business actions rather than silent record replacement.
- Historical rates used for billing must remain preserved.

---

# 19. Financial Responsibility

Financial responsibility is determined by Lease Signers.

Every Lease Signer is jointly responsible for the entire outstanding Lease balance.

The system does not divide responsibility between signers.

For example:

```text
Lease Balance: $800

Signer A responsibility: Full $800
Signer B responsibility: Full $800
```

This does not mean that the Property may collect the balance twice.

It means that any Lease Signer may be held responsible for satisfying the full unpaid obligation until that obligation has been settled.

Occupancy alone does not create financial responsibility.

A Customer may therefore:

- live in the Unit without being financially responsible, or
- sign the Lease and be financially responsible without living in the Unit.

---

# 20. Invoice Domain

## 20.1 Purpose

An Invoice represents an amount owed by exactly one Customer. It may additionally
be associated with zero or one Lease when applicable.

An Invoice establishes a receivable but does not itself represent money received.

Invoices may contain one or more charge components.

---

## 20.2 Invoice Categories

The domain supports the following invoice categories:

- Rent
- Utilities
- Service Charges
- Damage Charges
- Miscellaneous Charges

Deposits are not Invoice categories because deposits are liabilities rather than operating income.

---

## 20.3 Invoice Responsibility

Every Invoice belongs to exactly one Customer.

An Invoice may additionally be associated with zero or one Lease. Customer
ownership remains explicit and is not derived exclusively from a Lease.

When an Invoice is associated with a Lease, its Customer must be financially
responsible under that Lease, and its Unit, obligation, billing period, and other
contractual context must agree with the Lease.

Selecting one Invoice Customer does not remove the approved joint responsibility
of other Lease Signers. Rent remains Lease-specific and every Rent Invoice
requires the applicable signed Lease.

An Invoice without a Lease must still have an approved billing source and
identifiable purpose within a supported Invoice category. Optional Lease
association does not authorize arbitrary charges or new Invoice categories.

---

## 20.4 Invoice Amount

An Invoice contains the financial obligation created at the time of billing.

The amount originally billed must remain historically identifiable even if:

- partial payments are later made
- credits are applied
- adjustments occur
- the Invoice is later voided
- a payment is reversed

The system must never rewrite historical billing in a way that makes the original financial event impossible to reconstruct.

---

# 21. Rent Billing

## 21.1 Monthly Rent

Rent is billed monthly in advance.

Recurring monthly rent invoices are generated automatically on the **25th of the current month** for the upcoming rental period.

The normal due date is the **5th**.

Example:

```text
Invoice generation date: 25 July
Rental period: August
Due date: 5 August
```

The exact generation and due-date rules are defined in `002_BUSINESS_RULES.md`.

---

## 21.2 First Partial Month

When a Lease begins partway through a calendar month, rent is calculated using the actual number of calendar days.

Example:

```text
Move-in date: 10 July

First rental period:
10 July through 31 July

Next regular rental period:
1 August through 31 August
```

The first partial month does not redefine the recurring monthly billing cycle.

---

## 21.3 Final Partial Month

When the Lease ends partway through a calendar month and the applicable business rules require prorated rent, the final rental period is calculated using actual calendar days.

The exact termination and proration rules belong to `002_BUSINESS_RULES.md`.

---

## 21.4 Historical Rent Rates

A Lease may experience rent changes over time.

Historical rent rates must always be preserved.

A later rent change must not alter:

- previous rent invoices
- previous proration calculations
- historical reporting

The rent rate applicable to a billing period must be determinable from the historical Lease terms applicable during that period.

---

# 22. Utility Billing

Utility billing includes:

- Electricity
- Water

Utility charges are calculated from individual Utility Meter readings associated with each Unit.

---

## 22.1 Utility Consumption

Consumption is determined from sequential readings belonging to the same Utility Meter.

Conceptually:

```text
Consumption
=
Current Reading
-
Previous Reading
```

A reading from one Utility Meter must never be compared directly with a reading from a replacement meter unless an explicit meter-replacement process establishes the appropriate transition.

---

## 22.2 Meter Replacement

When a Utility Meter is replaced:

- the old meter remains in history
- its previous readings remain attached to it
- the replacement meter receives its own identity
- new readings are recorded against the replacement meter
- historical consumption must remain reconstructable

Meter replacement must never cause historical readings to be reassigned.

---

## 22.3 Utility Rates

Electricity and water rates may change over time.

Historical utility rates must therefore be preserved.

The applicable Utility Rate is the rate effective on the Utility Invoice
generation date. That selected rate applies to the entire consumption period
represented by the Invoice.

Consumption must not be split between old and new rates merely because a rate
changed during the represented consumption period.

Each utility bill must be explainable using:

- the relevant Utility Meter
- the relevant readings
- the consumption quantity
- the Invoice generation date
- the exact Utility Rate selected on that date
- the selected rate's effective-date information

Previously issued Utility Invoices must never be recalculated because of a later
rate change.

---

# 23. Fixed Monthly Service Charges

The system supports fixed recurring service charges.

Current fixed monthly services include:

- Internet
- Trash

These charges are not meter-based.

They are billed according to the service rate applicable to the relevant billing period.

Historical service rates must be preserved.

A current service-rate change must not alter prior invoices.

---

# 24. Damage Charges

Damage Charges represent amounts owed because of damage associated with a tenancy.

Damage Charges are separate from normal Rent, Utilities, and Service Charges.

They may arise during or after move-out inspection.

Damage Charges may participate in Final Settlement and may be satisfied using available deposits when permitted by the applicable business rules.

---

# 25. Miscellaneous Charges

Miscellaneous Charges represent authorized Lease-related charges that do not belong to another predefined Invoice category.

The existence of a Miscellaneous category must not be used to bypass proper domain classification when a specific charge type already exists.

Every Miscellaneous Charge must remain sufficiently described for future review and audit.

---

# 26. Payment Domain

## 26.1 Purpose

A Payment represents actual money received.

A Payment is distinct from an Invoice.

```text
Invoice = money owed
Payment = money received
```

A Payment does not automatically imply that a specific Invoice has been settled.

Payment allocation determines how received money is applied.

---

## 26.2 Payment Methods

The domain supports multiple payment methods.

`002_BUSINESS_RULES.md` establishes that accepted Payment Methods are configured
business data rather than a hard-coded list.

The selected payment method must remain part of the historical Payment record.

---

## 26.3 Payment Allocation

Payments are manually allocated by authorized staff.

A Payment may be:

- fully allocated
- partially allocated
- temporarily unallocated
- applied across multiple Invoices

An Invoice may receive:

- one Payment
- multiple Payments
- partial allocations from several Payments

Conceptually:

```text
Payment $500
   │
   ├── $300 → Rent Invoice
   ├── $100 → Utility Invoice
   └── $100 → remains unallocated until an authorized disposition
```

Payment and allocation are intentionally separate business concepts.

---

# 27. Partial Payments

Partial payment is supported.

When a Payment allocation is less than the outstanding Invoice balance, the Invoice remains partially unpaid.

Example:

```text
Invoice amount:       $500
Allocated payment:    $200
Remaining balance:    $300
```

The original Invoice amount remains unchanged.

---

# 28. Overpayments

An Overpayment occurs when money received exceeds the amount currently allocated to outstanding obligations.

Overpayment must not cause an Invoice balance to become negative.

The excess remains part of the original RECEIVED Payment until the payer chooses
and authorizes an approved disposition. It becomes Customer Credit only after the
required authorization; it may instead be refunded or otherwise resolved under
an approved rule.

Example:

```text
Outstanding Invoice: $400
Payment received:     $500

Allocated:            $400
Unallocated excess:   $100
```

---

# 29. Advance Payments

An Advance Payment is money received before the related future Invoice or obligation exists.

Advance Payments remain part of the Customer's available financial balance until:

- allocated to a later Invoice
- refunded
- otherwise resolved through an authorized financial process

Advance Payments must not create artificial historical Invoices solely to absorb the money.

---

# 30. Customer Credit

Customer Credit represents money belonging to or available for a Customer that has not yet been consumed by a valid charge.

Customer Credit may arise from:

- overpayment
- advance payment
- reversed allocation
- authorized financial adjustment
- other valid credit-producing events

Customer Credit is distinct from a Deposit.

```text
Customer Credit
    =
Money available for future allocation

Deposit
    =
Money held under a deposit obligation
```

These concepts must not be merged.

---

# 31. Reversals

A Reversal corrects or negates a previous financial event while preserving the original event in history.

Examples include:

- reversing an incorrect Payment
- reversing an incorrect Payment Allocation
- correcting an erroneous financial transaction

A reversal must never be implemented as silent deletion of the original financial record.

Conceptually:

```text
Original Financial Event
          │
          ▼
       Reversal
          │
          ▼
Correct Financial Position
```

Both the original event and the reversal remain auditable.

---

# 32. Refunds

A Refund represents money returned to a Customer.

Refunds may arise from:

- Customer Credit
- Security Deposit
- Pet Deposit
- other authorized refundable balances

A Refund is itself a financial event and must remain permanently recorded.

The refund must identify the financial balance from which the refunded amount originated.

---

# 33. Deposit Domain

## 33.1 Deposit Types

The system recognizes exactly two deposit types:

- Security Deposit
- Pet Deposit

No separate Reservation Deposit exists.

---

## 33.2 Security Deposit

Security Deposit is mandatory.

It begins during Reservation and continues into the resulting Lease.

The same Security Deposit obligation remains throughout the complete tenancy lifecycle.

---

## 33.3 Partial Security Deposit

The Security Deposit may be paid in installments.

A common Reservation scenario is:

```text
Monthly Rent:                       $500
Required Security Deposit:          $500

Initial Security Deposit payment:   $100
Remaining Security Deposit:         $400
```

The initial $100 is already a Security Deposit.

It is not renamed, converted, or reclassified when the Customer later moves in.

The Customer must complete the required Security Deposit before move-in according to the applicable business rules.

---

## 33.4 Required and Held Amounts

The financial model distinguishes between:

```text
Required Deposit Amount
         │
         ├── Amount Received
         │
         └── Outstanding Amount
```

Example:

```text
Required:       $500
Received:       $100
Outstanding:    $400
```

Later:

```text
Required:       $500
Received:       $500
Outstanding:      $0
```

Deposit installments must remain individually traceable through the financial transaction history.

---

## 33.5 Security Deposit During Reservation

An active Reservation requires a Security Deposit according to the Reservation business rules.

The Reservation may therefore exist while the Security Deposit is only partially paid.

The required minimum initial amount and Reservation-expiration consequences are defined in `002_BUSINESS_RULES.md`.

---

## 33.6 Security Deposit During Lease

When the Reservation proceeds to move-in:

- the existing Security Deposit remains in place
- the Deposit is associated with the resulting Lease
- money previously received is not received again
- the remaining required amount must be satisfied before move-in

There is no financial “conversion transaction.”

---

## 33.7 Security Deposit Refundability

The Security Deposit is not refundable while the Lease remains active.

It is held until the Lease has ended and Final Settlement is performed.

A Security Deposit may then be:

- applied against authorized outstanding amounts
- partially refunded
- fully refunded
- fully consumed by settlement obligations

The exact refund and forfeiture conditions belong to `002_BUSINESS_RULES.md`.

---

# 34. Pet Deposit

A Pet Deposit applies only when a pet is approved and the applicable signed Lease
terms require that Deposit.

A Pet Deposit:

- is a liability
- is separate from the Security Deposit
- remains traceable independently
- may be used only under authorized settlement rules
- is resolved through Final Settlement

If no pet is being kept, a Pet Deposit must not be required merely because the
Customer may keep a pet later.

If an approved pet is introduced later and the applicable signed Lease terms
require a Pet Deposit, that Deposit must be paid before or when the pet begins
staying in the Unit.

---

# 35. Deposits Versus Payments

Receiving money for a Deposit is still a financial receipt, but the purpose of that money is different from normal revenue.

Conceptually:

```text
Money Received
      │
      ├── Payment toward Invoice
      │        └── Reduces receivable
      │
      └── Deposit Receipt
               └── Increases deposit liability
```

The financial model must preserve this distinction.

A Deposit receipt must never be treated as rent income merely because money was received.

---

# 36. Deposit Application

Deposits are not applied against ordinary monthly balances during an active Lease.

Deposit application occurs only during Final Settlement.

Possible settlement uses include authorized:

- unpaid Rent
- unpaid Utilities
- unpaid Service Charges
- Damage Charges
- Miscellaneous Charges
- other valid settlement obligations

Deposit application must be explicitly recorded.

A Deposit balance must never silently decrease.

---

# 37. Final Settlement

## 37.1 Purpose

Final Settlement determines the complete financial position of a terminated Lease.

It reconciles all remaining obligations and liabilities before the tenancy is financially closed.

---

## 37.2 Settlement Inputs

Final Settlement may include:

- Outstanding Rent
- Final prorated Rent
- Final Electricity charges
- Final Water charges
- Outstanding Service Charges
- Damage Charges
- Miscellaneous Charges
- Customer Credit
- Security Deposit
- Pet Deposit
- Payments received during settlement

---

## 37.3 Settlement Calculation

Conceptually:

```text
Outstanding Charges
        ↓
Less Available Customer Credit
        ↓
Less Authorized Deposit Application
        ↓
Final Financial Position
```

The final result may be:

```text
$0 Balance
```

or:

```text
Amount Due from Customer
```

or:

```text
Amount Refundable to Customer
```

---

## 37.4 Deposit Application During Settlement

Deposit application is explicit and traceable.

Example:

```text
Security Deposit Held:       $500

Outstanding Rent:            $150
Utility Charges:              $80
Damage Charges:              $70

Total Settlement Charges:    $300
Deposit Applied:              $300
Deposit Refundable:           $200
```

The system must preserve:

- the original Deposit amount
- each Deposit receipt
- each amount applied
- the reason for each application
- the remaining amount
- any resulting Refund

---

# 38. Financial Balances

The domain distinguishes between several different balances.

## Invoice Balance

Amount still owed on a specific Invoice.

---

## Lease Outstanding Balance

Total remaining receivables associated with the Lease.

---

## Customer Credit Balance

Available Customer money not currently allocated to receivables.

---

## Deposit Balance

Amount currently held as a Deposit liability.

---

## Settlement Balance

The net financial position calculated during Final Settlement.

These balances must not be treated as interchangeable.

---

# 39. Historical Financial Rates

Historical billing must be reproducible.

The system must preserve the exact rate selected under the applicable source and
effective-date rule when a charge was generated.

This includes:

- Rent rates
- Electricity rates
- Water rates
- Internet charges
- Trash charges
- Other recurring service rates

A Utility Rate change affects Utility Invoices generated on or after its effective
date. Rent and fixed Service rates follow their applicable contractual period
rules.

Historical invoices must not change because a current rate changes.

---

# 40. Financial Auditability

Every financial change must be fully auditable.

This includes:

- Invoice creation
- Invoice modification
- Invoice voiding
- Payment receipt
- Payment allocation
- Allocation change
- Payment reversal
- Customer Credit creation
- Customer Credit application
- Deposit receipt
- Deposit application
- Refund
- Final Settlement
- Rate changes
- Utility Reading modifications that affect billing

The audit model must make it possible to determine:

```text
What changed?
Who changed it?
When was it changed?
What was the previous state?
What became the new state?
Why was the change made?
```

Technical audit storage and authorization rules are defined in later architecture documents.

---

# 41. Core Financial Invariants

The following financial invariants must always hold.

### Invoice Integrity

- An Invoice represents a real financial obligation.
- Historical Invoice amounts remain reconstructable.
- An Invoice cannot have a negative outstanding balance.

### Payment Integrity

- Payments cannot silently disappear.
- Payment Allocation is separate from Payment receipt.
- One Payment may be allocated across multiple Invoices.
- Partial allocation is supported.

### Credit Integrity

- Overpayment does not produce a negative Invoice balance.
- Excess money remains part of the RECEIVED Payment until an authorized Credit,
  Refund, or other approved disposition is recorded.
- Customer Credit and Deposit balances are different concepts.

### Deposit Integrity

- Security Deposit is mandatory.
- Security Deposit may be partially paid.
- The Deposit collected during Reservation remains the same Deposit during the Lease.
- Deposits are liabilities.
- Deposits cannot be used for ordinary monthly payment allocation while the Lease remains active.
- Deposit application occurs only during Final Settlement.
- A Property-caused Reservation cancellation may require a Security Deposit Refund
  before a Lease exists.
- For a Deposit associated with a Lease, Refund occurs only after the Lease has
  ended and settlement rules permit it.

### Rate Integrity

- Historical rates must remain preserved.
- Current rate changes never rewrite historical charges.

### Audit Integrity

- Financial corrections use explicit reversal, adjustment, void, allocation, application, or refund actions.
- Financial history must never be silently rewritten or deleted.

---

# 42. Domain Invariants

Domain Invariants are rules that must remain true regardless of which application workflow, user interface, API, or technical implementation performs the operation.

These invariants protect the integrity of the business model.

They are stricter than ordinary validation rules because violating them would place the system into an invalid business state.

---

# 43. Property Invariants

The following rules apply to the Property domain:

- One application manages exactly one Property.
- Every Unit belongs to the Property managed by the application.
- Operational records may not reference a Unit outside that Property.
- Historical records remain associated with the same Property for their entire lifetime.

---

# 44. Unit Invariants

A Unit is the central rentable asset in the system.

The following rules must always remain true:

- Every Unit has exactly one Unit Number.
- Every Unit has one Floor attribute.
- Every Unit has one Unit Type.
- Every Unit has one current operational Status.
- A Unit may have many historical Reservations.
- A Unit may have many historical Leases.
- A Unit may have no more than one active Reservation at a time.
- A Unit may have no more than one Signed Lease covering any point in time.
- A Unit may not be simultaneously available for conflicting tenancy commitments.

Unit status must reflect the actual operational condition of the Unit.

Unit statuses are:

- VACANT
- RESERVED
- OCCUPIED
- UNDER_MAINTENANCE
- CLEANING
- OUT_OF_SERVICE

Unit availability must not be inferred only from the status value when authoritative Reservation or Lease records indicate otherwise.

---

# 45. Reservation Invariants

A Reservation represents a temporary commitment to hold one Unit for one Customer.

The following rules apply:

- Every Reservation belongs to exactly one Unit.
- Every Reservation belongs to exactly one Customer.
- A Reservation may result in at most one Lease.
- An ACTIVE Reservation holds the Unit.
- A CANCELLED Reservation no longer holds the Unit.
- A MOVED_IN Reservation has completed its reservation lifecycle.
- A MOVED_IN Reservation cannot return to ACTIVE.
- A CANCELLED Reservation cannot return to ACTIVE.
- Reservation expiration changes must preserve historical extension records.
- Extending the expiration date does not create a new Reservation status.
- Security Deposit received during Reservation remains associated with the same tenancy process.

Reservation statuses are limited to:

```text
ACTIVE
CANCELLED
MOVED_IN
```

---

# 46. Reservation Expiration Invariants

The Reservation has an original expiration commitment and a current effective expiration date.

When an authorized extension occurs:

- the original history must remain reconstructable
- the previous expiration date must remain known
- the new expiration date must be recorded
- the person authorizing the extension must be auditable
- the reason or memo associated with the extension must be preserved when required

The detailed maximum Reservation duration and extension conditions are defined in `002_BUSINESS_RULES.md`.

---

# 47. Lease Invariants

The Lease represents the contractual tenancy.

The following rules must always hold:

- Every Lease belongs to exactly one Unit.
- Every Lease has exactly one Primary Tenant.
- The Primary Tenant is a Customer.
- The Primary Tenant must be one of the Lease Signers.
- A Lease may have additional Lease Signers.
- Every Lease Signer is a Customer.
- Every Lease Signer is jointly responsible for the full Lease obligation.
- Responsibility is never divided into individual percentages or partial legal balances.
- A Lease may contain multiple Occupants.
- Occupancy and contractual responsibility remain separate concepts.
- Signed Leases for the same Unit must not have overlapping contractual periods.

Lease statuses are:

```text
DRAFTED
SIGNED
CANCELLED
TERMINATED
```

Allowed lifecycle transitions are:

```text
DRAFTED -> SIGNED
DRAFTED -> CANCELLED
SIGNED  -> TERMINATED
```

No other status transitions are valid.

---

# 48. Lease Signer Invariants

Lease Signers establish contractual financial responsibility.

The following rules apply:

- Every Lease has at least one Lease Signer before it becomes SIGNED.
- The Primary Tenant must be included among the Lease Signers.
- A Lease Signer may also be an Occupant.
- A Lease Signer is not required to be an Occupant.
- Removing a historical signer from a previously signed agreement must not erase the historical contract record.
- All signers are jointly responsible for the full unpaid Lease balance while their contractual responsibility applies.

---

# 49. Occupancy Invariants

Occupancy represents actual residence rather than contractual responsibility.

The following rules apply:

- Every Occupancy record belongs to one Lease.
- Every Occupancy record identifies one Customer.
- Occupancy records contain a Move-in Date.
- Occupancy records may contain a Move-out Date.
- An Occupancy record with no Move-out Date represents current occupancy.
- An Occupant does not become financially responsible merely because they live in the Unit.
- Historical Occupancy records must remain permanently available.

Occupancy must answer the business question:

> Who physically lived in this Unit, and during what period?

It must not be used as a substitute for Lease Signer responsibility.

---

# 50. Deposit Invariants

Deposits represent money held as liabilities.

The following rules apply:

- Every tenancy requires a Security Deposit.
- Security Deposit may be paid partially.
- Security Deposit may be received in multiple financial receipts.
- Money received during Reservation is already Security Deposit.
- The system must not create a separate Reservation Deposit concept.
- The same Security Deposit continues into the resulting Lease.
- The required amount and the amount actually received are separate business facts.
- The remaining Security Deposit balance may be outstanding before move-in.
- Required move-in deposit conditions must be satisfied before possession is granted.
- Security Deposit is not refundable during an active Lease.
- Pet Deposit applies only when a pet is approved and the applicable signed Lease
  terms require that Deposit.
- If no pet is being kept, Pet Deposit is not required merely because a Customer
  may keep a pet later.
- If an approved pet is introduced later and the signed Lease terms require Pet
  Deposit, it must be paid before or when the pet begins staying in the Unit.
- Security Deposit and Pet Deposit remain separate liabilities.
- Deposits may only be applied as part of Final Settlement.
- Deposit application must never occur silently.
- Every application, refund, or financial correction must remain auditable.

---

# 51. Utility Meter Invariants

Utility Meters represent physical measurement devices.

Each Utility Meter records:

- Meter ID
- Serial Number
- Utility Type
- Description
- Status
- Installed Date
- Replaced Date
- Memo

The following rules apply:

- Every Utility Meter belongs to exactly one Unit.
- Every Utility Meter measures exactly one Utility Type.
- Supported Utility Types are Electricity and Water.
- A Unit may have multiple historical meters.
- A Unit may have no more than one active Electricity Meter.
- A Unit may have no more than one active Water Meter.
- A replacement meter receives its own identity.
- Historical Utility Readings remain attached to the meter that produced them.
- Replacing a meter never rewrites historical consumption.

---

# 52. Utility Reading Invariants

Each Utility Reading records:

- Reading ID
- Meter ID
- Reading Date
- Reading Value
- Modified Date

The following rules apply:

- Every Utility Reading belongs to exactly one Utility Meter.
- A Utility Reading cannot be transferred to another meter.
- Reading history must remain reconstructable.
- Changes to readings that influence financial billing must be audited.
- Meter replacement boundaries must be respected when calculating consumption.

The system does not currently require a separate Reading Type or Reading Source concept.

---

# 53. Invoice Invariants

Invoices represent financial receivables.

The following rules apply:

- Every Invoice belongs to exactly one Customer.
- An Invoice may additionally be associated with zero or one Lease.
- When a Lease association exists, the Invoice Customer, Unit, obligation,
  period, and Lease context must be consistent.
- Rent Invoices require the applicable signed Lease.
- Optional Lease association does not authorize arbitrary non-Lease charges or
  new Invoice categories.
- Every Invoice has an identifiable billing purpose.
- Every Invoice belongs to one supported Invoice category.
- The original billed amount must remain historically identifiable.
- Invoice outstanding balance cannot become negative.
- Payments do not directly rewrite Invoice amounts.
- Payment Allocations reduce outstanding balances.
- Voiding an Invoice preserves the original Invoice history.
- Historical Invoices remain reproducible using the applicable historical rates and billing data.

Supported Invoice categories are:

- Rent
- Utilities
- Service Charges
- Damage Charges
- Miscellaneous Charges

Deposits are not Invoice categories.

---

# 54. Payment Invariants

A Payment represents money actually received.

The following rules apply:

- Every Payment represents a real financial receipt.
- Payment receipt and Payment Allocation are separate events.
- One Payment may be allocated to multiple Invoices.
- One Invoice may receive allocations from multiple Payments.
- A Payment may remain partially or fully unallocated.
- Allocation is performed manually by authorized staff.
- Payment history cannot be erased.
- Reversing a Payment must preserve both the original Payment and the reversal event.

---

# 55. Customer Credit Invariants

Customer Credit represents money available to the Customer that is not currently consumed by a receivable.

The following rules apply:

- Customer Credit is not a Deposit.
- Customer Credit may arise from overpayment or advance payment.
- An Invoice may not become negative in order to represent credit.
- Unused Payment value may remain available as Customer Credit.
- Applying Customer Credit must be auditable.
- Refunding Customer Credit must be auditable.

---

# 56. Historical Rate Invariants

The financial domain depends on historical rates.

The following rates may vary over time:

- Rent
- Electricity
- Water
- Internet
- Trash
- Other recurring service charges

The following invariants apply:

- A rate change must never rewrite a previously issued historical charge.
- Historical billing must remain reproducible.
- The applicable rate must be determinable for any historical charge.
- Current rates and historical rates must be distinguishable.
- Historical invoices retain the economic meaning they had when created.

---

# 57. Final Settlement Invariants

Final Settlement closes the financial lifecycle of a Lease.

The following rules apply:

- Every terminated Lease must complete exactly one Final Settlement.
- Final Settlement belongs to exactly one terminated Lease.
- Final Settlement occurs only after the Lease is TERMINATED.
- Outstanding obligations must be identified before settlement is finalized.
- Available Customer Credit must be recognized.
- Security Deposit and Pet Deposit remain identifiable separately.
- Deposit applications must identify the amount and purpose.
- Refunds must identify their financial source.
- Any remaining amount due from the Customer must remain identifiable.
- Final Settlement history must remain permanent.
- Closing settlement must not erase any underlying Invoice, Payment, Deposit, Credit, or Adjustment history.

---

# 58. Audit Invariants

Auditability is a domain-wide requirement.

Every significant financial change must answer:

```text
What changed?
Who performed the change?
When did it occur?
What was the previous value or state?
What is the resulting value or state?
Why was the change made?
```

At minimum, full audit history is required for:

- Lease status changes
- Reservation changes
- Reservation expiration extensions
- Security Deposit changes
- Pet Deposit changes
- Utility Reading modifications
- Utility rate changes
- Service rate changes
- Rent changes
- Invoice changes
- Payment changes
- Payment Allocations
- Credits
- Reversals
- Refunds
- Final Settlement actions

Technical audit implementation is defined later in the architecture documentation.

---

# 59. Domain Events

Domain Events represent significant business facts that have occurred.

They are expressed in past tense because they describe completed business events.

Domain Events are not API messages, database triggers, or implementation mechanisms.

Their purpose is to define meaningful business transitions.

---

# 60. Property and Unit Events

Representative events include:

```text
PropertyCreated
UnitCreated
UnitStatusChanged
UnitReserved
UnitOccupied
UnitEnteredCleaning
UnitEnteredMaintenance
UnitMarkedOutOfService
UnitReturnedToVacant
```

These events describe significant changes to Unit availability or operational state.

---

# 61. Reservation Events

Representative Reservation events include:

```text
ReservationCreated
ReservationExpirationExtended
ReservationCancelled
ReservationMovedIn
```

`ReservationExpirationExtended` records an extension while the Reservation remains ACTIVE.

`ReservationMovedIn` represents completion of the Reservation lifecycle and links the Reservation to the resulting Lease.

---

# 62. Customer Events

Representative Customer events include:

```text
CustomerCreated
CustomerDetailsUpdated
```

Changes to identity or contact information must not destroy the historical relationships between the Customer and previous business records.

---

# 63. Lease Events

Representative Lease events include:

```text
LeaseDrafted
PrimaryTenantAssigned
LeaseSignerAdded
LeaseSignerRemovedBeforeSigning
LeaseSigned
LeaseCancelled
LeaseTerminationNoticeRecorded
LeaseTerminated
```

A termination notice does not itself terminate the Lease.

The Lease remains SIGNED until the business process reaches actual termination.

---

# 64. Occupancy Events

Representative Occupancy events include:

```text
OccupantAdded
OccupantMovedIn
OccupantMovedOut
```

These events preserve physical residence history independently from contractual responsibility.

---

# 65. Deposit Events

Representative Deposit events include:

```text
SecurityDepositRequired
SecurityDepositReceived
SecurityDepositFullyPaid
PetDepositRequired
PetDepositReceived
DepositAppliedToSettlement
DepositRefunded
```

A Security Deposit received during Reservation remains a Security Deposit throughout the tenancy.

No `ReservationDepositConverted` event exists because no such conversion occurs in the business domain.

---

# 66. Utility Events

Representative Utility Meter events include:

```text
UtilityMeterInstalled
UtilityMeterMarkedBroken
UtilityMeterReplaced
UtilityMeterRemoved
```

Representative Utility Reading events include:

```text
UtilityReadingRecorded
UtilityReadingCorrected
```

Corrections that affect billing require full audit history.

---

# 67. Billing Events

Representative Invoice events include:

```text
RentInvoiceGenerated
UtilityInvoiceGenerated
ServiceChargeInvoiceGenerated
DamageChargeInvoiceCreated
MiscellaneousChargeInvoiceCreated
InvoiceAdjusted
InvoiceVoided
```

The exact conditions for invoice creation and adjustment are defined in `002_BUSINESS_RULES.md`.

---

# 68. Payment Events

Representative Payment events include:

```text
PaymentReceived
PaymentAllocated
PaymentAllocationReversed
PaymentReversed
AdvancePaymentReceived
CustomerCreditCreated
CustomerCreditApplied
CustomerCreditRefunded
RefundIssued
```

These events preserve the distinction between money received, money allocated, and money returned.

---

# 69. Settlement Events

Representative Final Settlement events include:

```text
FinalSettlementStarted
FinalChargesAdded
DepositApplied
CustomerCreditAppliedToSettlement
SettlementBalanceCalculated
SettlementRefundIssued
SettlementBalancePaid
FinalSettlementClosed
```

Closing Final Settlement marks financial completion of the tenancy but does not remove any historical source records.

---

# 70. Domain Event Principles

All Domain Events follow these principles:

- An event describes something that already happened.
- An event represents a meaningful business fact.
- Events must use domain terminology.
- Events must not expose technical implementation details.
- Events must not replace the authoritative business entities.
- Historical events must remain traceable when required for audit.

---

# 71. Bounded Contexts

The Property Rental Management System is one application but contains several distinct business areas.

These areas are modeled as Bounded Contexts to prevent concepts from becoming overloaded or tightly coupled.

The initial domain is divided into the following contexts:

1. Property and Unit Management
2. Customer Management
3. Reservation Management
4. Lease and Occupancy Management
5. Utility Management
6. Billing Management
7. Payment and Credit Management
8. Deposit Management
9. Move-out and Final Settlement
10. Audit and History

These boundaries describe business responsibilities rather than deployable services.

The application may remain a modular monolith while maintaining these logical domain boundaries.

---

# 72. Property and Unit Management Context

## Responsibility

This context owns the physical rental inventory.

It manages:

- Property
- Unit
- Unit Number
- Floor
- Unit Type
- Unit operational status

It answers questions such as:

- What Units exist?
- Where is each Unit located?
- What type of Unit is it?
- Is the Unit operationally available?

It does not own:

- Customer identity
- Lease contracts
- Invoice balances
- Payment allocations

---

# 73. Customer Management Context

## Responsibility

This context owns Customer identity and contact information.

It manages:

- Customer identity
- Customer personal details
- Contact information

It intentionally does not maintain permanent customer classifications such as:

- Tenant
- Former Tenant
- Occupant
- Reservation Customer

Those roles are derived from relationships in other contexts.

---

# 74. Reservation Management Context

## Responsibility

This context owns the process of holding a Unit before move-in.

It manages:

- Reservation
- Reservation status
- Reservation expiration
- Reservation extension history
- Reservation Customer
- Reservation-to-Lease transition

It collaborates with:

- Property and Unit Management
- Customer Management
- Deposit Management
- Lease Management

---

# 75. Lease and Occupancy Management Context

## Responsibility

This context owns contractual tenancy and physical occupancy.

It manages:

- Lease
- Lease status
- Primary Tenant
- Lease Signers
- Occupancy
- Lease dates
- Lease termination lifecycle

It answers separate questions:

```text
Who is contractually responsible?
```

and:

```text
Who physically lives in the Unit?
```

These concepts must remain distinct.

---

# 76. Utility Management Context

## Responsibility

This context owns utility measurement history.

It manages:

- Utility Meter
- Meter installation
- Meter replacement
- Meter status
- Utility Reading

It provides authoritative consumption data to Billing Management.

It does not own utility invoices or payment status.

---

# 77. Billing Management Context

## Responsibility

This context owns receivables.

It manages:

- Rent billing
- Utility billing
- Service Charges
- Damage Charges
- Miscellaneous Charges
- Invoice lifecycle
- Historical billing rates

It consumes information from:

- Lease Management
- Utility Management
- historical rate information

It does not own money received.

---

# 78. Payment and Credit Management Context

## Responsibility

This context owns financial receipts and allocation.

It manages:

- Payment
- Payment method
- Payment Allocation
- Advance Payment
- Overpayment
- Customer Credit
- Payment reversal
- Credit refund

It collaborates closely with Billing Management but remains conceptually separate.

This distinction preserves the rule:

```text
Invoice = Amount owed
Payment = Money received
Allocation = How received money is applied
```

---

# 79. Deposit Management Context

## Responsibility

This context owns deposit liabilities.

It manages:

- Security Deposit
- Pet Deposit
- Required amount
- Amount received
- Outstanding amount
- Deposit application
- Deposit refund

It collaborates with:

- Reservation Management
- Lease Management
- Final Settlement

Deposits must remain separate from normal Customer Credit and Invoice payment balances.

---

# 80. Move-out and Final Settlement Context

## Responsibility

This context owns completion of the tenancy lifecycle.

It coordinates:

- termination notice
- move-out
- inspection
- final charges
- final utility billing
- outstanding balances
- Customer Credit
- Security Deposit
- Pet Deposit
- deposit application
- refund
- remaining amount due
- final closure

It consumes information from several other contexts but owns the final settlement result.

---

# 81. Audit and History Context

## Responsibility

This context ensures that significant business and financial activity remains traceable.

It records sufficient history to reconstruct important changes across the system.

Audit concerns include:

- Actor
- Action
- Timestamp
- Previous state
- Resulting state
- Reason or memo
- Related business entity

Audit and History is a cross-cutting domain capability.

It must not become the authoritative source of current balances or operational state.

The authoritative state remains within the relevant business Aggregate.

---

# 82. Context Interaction Overview

```text
Property & Unit Management
          │
          ▼
Reservation Management
          │
          ├──────────────► Deposit Management
          │
          ▼
Lease & Occupancy Management
          │
          ├──────────────► Billing Management
          │                      ▲
          │                      │
          │               Utility Management
          │
          ├──────────────► Payment & Credit Management
          │
          ▼
Move-out & Final Settlement
          ▲
          │
     Deposit Management
          ▲
          │
Payment & Credit Management

Audit & History
      │
      └──── Cross-cutting across all contexts
```

---

# 83. Context Boundary Principles

The following principles govern communication between Bounded Contexts:

- Each business fact has one authoritative owner.
- One context may reference information owned by another context but must not silently redefine it.
- Financial responsibilities must remain separate from physical occupancy.
- Billing must remain separate from Payment receipt.
- Deposits must remain separate from Customer Credit.
- Utility measurement must remain separate from Utility billing.
- Historical audit records must not replace authoritative domain state.
- Context boundaries must not be bypassed merely for implementation convenience.

---

# 84. Aggregate Coordination

Some operations require multiple Aggregates to participate in one business workflow.

Examples include:

### Reservation Creation

Coordinates:

```text
Customer
+
Unit
+
Reservation
+
Security Deposit
```

### Move-in

Coordinates:

```text
Reservation
+
Lease
+
Security Deposit
+
Occupancy
+
Unit
```

### Utility Billing

Coordinates:

```text
Customer
+
Unit
+
Applicable Lease (when the Invoice is Lease-associated)
+
Utility Meter
+
Utility Reading
+
Generation-date Utility Rate
+
Invoice
```

### Payment Processing

Coordinates:

```text
Customer
+
Payment
+
Payment Allocation
+
Invoice
+
Customer Credit
```

### Move-out

Coordinates:

```text
Lease
+
Occupancy
+
Unit
+
Utility Readings
+
Inspection
+
Final Charges
+
Final Settlement
+
Deposits
+
Customer Credit
+
Refund
```

These workflows do not imply that all involved concepts belong to one Aggregate.

Business coordination across Aggregate boundaries must preserve each Aggregate's invariants.

---

# 85. Domain Consistency Principles

The system distinguishes between business operations requiring immediate consistency and those that may be coordinated across multiple business steps.

Immediate domain consistency is required for rules such as:

- preventing a second active Reservation for the same Unit
- preventing overlapping Signed Lease coverage for the same Unit
- preventing invalid Lease status transitions
- preventing negative Invoice balances
- preventing allocation beyond available Payment value
- preventing Deposit application before Final Settlement
- preventing two active meters of the same Utility Type for one Unit

Longer workflows such as move-in and Final Settlement may coordinate several domain operations while preserving the integrity of every participating Aggregate.

Technical transaction boundaries are defined later in the Database Model and API Specification.

---

# 86. Domain Model Independence

The concepts in this document must remain independent from implementation technology.

Nothing in the domain requires a specific:

- programming language
- web framework
- database engine
- API protocol
- frontend framework
- cloud provider
- deployment architecture

The implementation must adapt to the domain model.

The domain model must not be distorted merely to simplify a particular technology choice.

---

# 87. Domain Model as the Foundation

This Domain Model establishes the vocabulary and conceptual structure used by all subsequent architecture documents.

The following documents must remain consistent with the concepts defined here:

```text
001_DOMAIN_MODEL.md
        │
        ▼
002_BUSINESS_RULES.md
        │
        ▼
003_PRODUCT_REQUIREMENTS.md
        │
        ▼
004_DATABASE_MODEL.md
        │
        ▼
005_API_SPECIFICATION.md
        │
        ▼
006_UI_SPECIFICATION.md
        │
        ▼
007_TESTING_STRATEGY.md
        │
        ▼
008_SECURITY_MODEL.md
        │
        ▼
009_DEPLOYMENT_ARCHITECTURE.md
        │
        ▼
010_DECISION_LOG.md
```

Later documents may add implementation detail, but they must not silently redefine the business concepts established in the Domain Model.

Any deliberate change to these concepts must be documented through the appropriate architectural decision process.

---

# 88. Domain Glossary

This glossary defines the official business terminology used throughout the Property Rental Management System.

All later documentation, code, APIs, database objects, user-interface labels, and tests should use these terms consistently unless a later architectural decision explicitly changes them.

---

## Property

The single apartment property managed by one deployed application.

The current system does not support multiple properties in one application.

---

## Unit

A rentable residential space within the Property.

A Unit has:

- Unit Number
- Floor
- Unit Type
- Operational Status

Supported Unit Types:

- Studio
- One Bedroom
- Two Bedroom
- Three Bedroom

Supported Unit Statuses:

- VACANT
- RESERVED
- OCCUPIED
- UNDER_MAINTENANCE
- CLEANING
- OUT_OF_SERVICE

---

## Unit Number

The human-readable identifier used by the business to identify a Unit.

Examples:

```text id="8pjl2n"
101
302
A-05
```

The exact format is an implementation and business configuration concern.

---

## Floor

The floor on which the Unit is located.

Floor is an attribute of Unit and is not modeled as a separate domain entity.

---

## Unit Type

The classification of a Unit by residential layout.

Supported types are:

```text id="c173aw"
STUDIO
ONE_BEDROOM
TWO_BEDROOM
THREE_BEDROOM
```

---

## Unit Status

The current operational state of a Unit.

Unit Status describes availability or physical readiness, not Lease termination notice state.

A termination notice does not automatically change Unit Status.

---

## Customer

A person known by the Property Rental Management System.

Customer is role-neutral.

A Customer may participate in different business relationships over time, including:

- Reservation Customer
- Primary Tenant
- Lease Signer
- Occupant
- Former Occupant
- Payer

The system does not maintain permanent Customer Types.

---

## Reservation

A temporary business commitment that holds one Unit for one Customer before move-in.

A Reservation has:

- one Customer
- one Unit
- an expiration date
- a status
- related Security Deposit activity

Reservation Statuses:

```text id="k31j8f"
ACTIVE
CANCELLED
MOVED_IN
```

---

## Reservation Customer

The Customer for whom the Unit is reserved.

A Reservation contains exactly one Reservation Customer.

If the Reservation proceeds to a Lease, that Customer is expected to become the Primary Tenant.

---

## Reservation Expiration Date

The current date until which the Reservation remains valid.

The original expiration history must remain reconstructable if extensions occur.

---

## Reservation Extension Notice

A historical record of an approved change to the Reservation expiration date.

An extension does not create a new Reservation status.

---

## Security Deposit

A mandatory financial liability held in connection with a Reservation and resulting Lease.

A Security Deposit:

- may be paid partially
- may be paid in multiple installments
- begins during Reservation
- remains the same Deposit through the Lease
- is not rent income
- is not refundable while the Lease remains active
- is resolved during Final Settlement

There is no separate Reservation Deposit concept.

---

## Required Security Deposit

The total Security Deposit amount required by the tenancy agreement.

This is distinct from the amount already received.

---

## Security Deposit Received

The cumulative amount of Security Deposit money actually received.

---

## Security Deposit Outstanding

The remaining required Security Deposit amount not yet received.

Conceptually:

```text id="ivks21"
Outstanding Security Deposit
=
Required Security Deposit
-
Security Deposit Received
```

---

## Pet Deposit

A Deposit liability that applies only when a pet is approved and the applicable
signed Lease terms require that Deposit.

Pet Deposit is separate from Security Deposit.

---

## Lease

The contractual rental agreement for one Unit.

A Lease contains:

- exactly one Unit
- exactly one Primary Tenant
- one or more Lease Signers
- zero or more Occupants
- Lease terms
- associated financial obligations
- deposits

Lease Statuses:

```text id="f7y147"
DRAFTED
SIGNED
CANCELLED
TERMINATED
```

---

## Primary Tenant

The principal Customer associated with the Lease.

Every Lease has exactly one Primary Tenant.

The Primary Tenant must also be a Lease Signer.

A Customer may be the Primary Tenant on multiple Leases over time.

---

## Lease Signer

A Customer who has signed the Lease agreement and accepted contractual responsibility.

Every Lease Signer is jointly responsible for the full outstanding Lease balance.

Responsibility is not divided among Lease Signers.

A Lease Signer may or may not live in the Unit.

---

## Joint Responsibility

The rule that each Lease Signer is responsible for satisfying the full unpaid Lease obligation while that obligation remains outstanding.

Joint responsibility does not create duplicate debt.

---

## Occupant

A Customer who physically resides in the Unit.

Being an Occupant does not automatically make the Customer financially responsible.

---

## Occupancy

The historical record describing when a Customer lives in a Unit under a Lease.

Occupancy includes:

- Customer
- Lease
- Move-in Date
- Move-out Date

---

## Move-in Date

The date on which an Occupant begins residing in the Unit.

For the Primary Tenant, this generally corresponds to possession of the Unit.

---

## Move-out Date

The date on which an Occupant ceases residing in the Unit.

---

## Termination Notice

A formal record that a Lease is intended to end.

Termination Notice does not itself terminate the Lease.

A Lease remains SIGNED until the actual termination business action occurs.

---

## Move-in

The business process through which an active Reservation becomes an occupied tenancy.

Move-in coordinates:

- Reservation
- Lease
- Security Deposit
- Occupancy
- Unit Status

---

## Move-out

The business process through which occupancy ends physically and the inputs for
later financial closure are collected. Financial closure occurs through Final
Settlement, which may remain pending after move-out.

Move-out may include:

- termination notice
- final occupancy date
- inspection
- final utility readings
- final charges
- Final Settlement
- Deposit application
- Refund
- archive

---

## Utility Meter

A physical meter assigned to one Unit.

Supported Utility Types:

```text id="mlmbvm"
ELECTRICITY
WATER
```

A Unit may have multiple historical meters but no more than one active meter for each Utility Type.

---

## Meter ID

The system identity of a Utility Meter.

---

## Serial Number

The physical serial number assigned to the Utility Meter.

---

## Utility Type

The type of utility measured by the meter.

Supported values:

- Electricity
- Water

---

## Installed Date

The date a Utility Meter became installed or active for the Unit.

---

## Replaced Date

The date a Utility Meter was replaced by another meter.

---

## Utility Reading

A recorded numeric reading from one Utility Meter on a specific date.

A Utility Reading contains:

- Reading ID
- Meter ID
- Reading Date
- Reading Value
- Modified Date

---

## Reading Date

The date on which the meter value was observed or recorded for business use.

---

## Reading Value

The cumulative meter value recorded at a point in time.

---

## Utility Consumption

The measurable amount of utility consumed between applicable readings.

Utility Consumption is derived from Utility Reading history and is not itself the authoritative raw measurement.

---

## Historical Rate

A rate selected for a historical charge under its applicable source and
effective-date rule.

Historical Rates must remain preserved so previous billing can always be reconstructed.

For a Utility Invoice, this is the Utility Rate effective on the Invoice
generation date and applied to the entire represented consumption period.

Examples include:

- Rent Rate
- Electricity Rate
- Water Rate
- Internet Charge
- Trash Charge

---

## Invoice

A financial receivable belonging to exactly one Customer and optionally
associated with zero or one Lease.

When a Lease association exists, Customer, Unit, obligation, period, and Lease
context must be consistent. Rent Invoices require the applicable signed Lease.
Optional Lease association does not authorize arbitrary non-Lease charges or new
Invoice categories.

Supported Invoice Categories:

- Rent
- Utilities
- Service Charges
- Damage Charges
- Miscellaneous Charges

---

## Rent Invoice

An Invoice representing rental charges for a defined rental period.

Rent is normally billed monthly in advance. Every Rent Invoice requires the
applicable signed Lease.

---

## Utility Invoice

An Invoice representing Electricity and/or Water usage derived from Utility
Readings and the Utility Rate effective on the Invoice generation date. The
selected rate applies to the entire represented consumption period.

---

## Service Charge

A fixed recurring service-related charge.

Current recurring services include:

- Internet
- Trash Collection

---

## Damage Charge

A charge created for damage associated with the tenancy.

Damage Charges commonly arise during move-out inspection or settlement.

---

## Miscellaneous Charge

An authorized Lease-related charge that does not belong to another defined Invoice category.

Miscellaneous Charges must remain sufficiently described for audit purposes.

---

## Payment

Money actually received.

Payment is distinct from Invoice.

```text id="q8lv5y"
Invoice = Money owed
Payment = Money received
```

---

## Payment Allocation

The explicit application of Payment value to one or more Invoices.

Allocation is performed manually by authorized staff.

---

## Partial Payment

A Payment or Payment Allocation that satisfies only part of an outstanding Invoice.

---

## Overpayment

A Payment amount greater than the obligations to which it is allocated.

Unused value remains part of the RECEIVED Payment until the payer authorizes an
approved Customer Credit, Refund, or other disposition.

---

## Advance Payment

Money received before the corresponding future receivable exists.

Advance Payment remains available until later allocated, refunded, or otherwise resolved.

---

## Customer Credit

Money available for use by a Customer that is not currently allocated to an Invoice and is not classified as a Deposit.

Customer Credit may arise from:

- Overpayment
- Advance Payment
- Reversed allocation
- Authorized financial adjustment

---

## Reversal

A financial action that negates a previous financial event while preserving both the original event and the reversal in history.

---

## Refund

Money returned to a Customer.

A Refund must identify the balance from which the money originated.

Possible sources include:

- Customer Credit
- Security Deposit
- Pet Deposit

---

## Final Settlement

The financial closing process for a terminated Lease.

Final Settlement reconciles:

- outstanding Invoices
- final Rent
- final Utilities
- Service Charges
- Damage Charges
- Miscellaneous Charges
- Customer Credit
- Security Deposit
- Pet Deposit
- Refunds
- remaining Customer balance

---

## Settlement Balance

The final net financial result after all settlement inputs are considered.

Possible results include:

- zero balance
- amount due from Customer
- amount refundable to Customer

---

## Deposit Application

The explicit use of held Deposit value against authorized obligations during Final Settlement.

Deposit Application must always remain auditable.

---

## Audit Record

Historical information describing a significant change in the system.

An Audit Record must be able to identify:

- what changed
- who changed it
- when it changed
- previous state
- resulting state
- reason or memo when applicable

---

# 89. Terminology Rules

The following terminology rules apply throughout the project.

## 89.1 Use Customer, Not Tenant, as the Person Entity

The canonical person entity is:

```text id="p21a31"
Customer
```

Do not create a permanent `Tenant` entity solely because a Customer currently has a Lease.

`Tenant` describes a role within a Lease relationship.

---

## 89.2 Use Primary Tenant for the Lease Role

Every Lease has one Primary Tenant.

This is a relationship between Customer and Lease, not a Customer Type.

---

## 89.3 Use Lease Signer for Contractual Responsibility

Financial responsibility is established through Lease Signer.

Do not use Occupant to determine Lease responsibility.

---

## 89.4 Use Occupancy for Residence History

The canonical concept for recording who lives in a Unit is:

```text id="jqq97g"
Occupancy
```

Do not infer occupancy exclusively from the Primary Tenant or Lease Signer records.

---

## 89.5 Do Not Use Reservation Deposit

The business term is:

```text id="ysx60g"
Security Deposit
```

Money collected during Reservation is already Security Deposit.

The following term must not be introduced:

```text id="6srd33"
Reservation Deposit
```

---

## 89.6 Do Not Use Converted for Reservation Completion

The approved Reservation completion status is:

```text id="1v67f2"
MOVED_IN
```

Do not describe the Reservation as financially converted into a Lease or the Deposit as converted into another Deposit.

---

## 89.7 Extended Is Not a Reservation Status

Reservation extension is represented by a Reservation Extension Notice.

The Reservation remains ACTIVE while valid.

Approved Reservation statuses remain:

```text id="kwdy1p"
ACTIVE
CANCELLED
MOVED_IN
```

---

## 89.8 Floor Is Not an Entity

Floor remains an attribute of Unit.

Do not create a Floor aggregate or entity unless a later documented requirement introduces floor-specific business behavior.

---

## 89.9 Commercial Unit Is Not a Supported Unit Type

The current domain does not contain Commercial Units.

Do not introduce commercial-specific concepts without a future approved domain change.

---

## 89.10 Utility Meter Is the Correct Term

Use:

```text id="sc8p8d"
Utility Meter
```

rather than:

```text id="99kzzu"
Utility Reading Meter
```

A Utility Meter exists independently from the readings recorded against it.

---

## 89.11 Reading Type and Reading Source Are Not Current Domain Concepts

The current Utility Reading model does not require Reading Type or Reading Source.

Do not add them without a future business requirement.

---

# 90. Domain Exclusions

The following concepts are intentionally excluded from the current Domain Model.

Their absence is deliberate and must not be interpreted as missing documentation.

---

## 90.1 Multi-Property Management

The application manages exactly one Property.

The following are excluded:

- Property switching
- Property portfolios
- Cross-property Customers
- Consolidated portfolio reporting

---

## 90.2 Commercial Leasing

The current application models residential Units only.

Commercial-specific concepts are excluded.

---

## 90.3 General Accounting

The application manages operational rental finances but is not a General Ledger.

Excluded concepts include:

- Chart of Accounts
- Journal Entries
- Trial Balance
- Profit and Loss
- Balance Sheet
- Formal accrual accounting

Financial data may later integrate with a separate accounting system.

---

## 90.4 Payroll and Human Resources

Employee payroll, employment records, leave, and HR administration are outside scope.

---

## 90.5 Maintenance Work Order Management

The current domain may mark a Unit as:

- UNDER_MAINTENANCE
- OUT_OF_SERVICE

However, detailed maintenance management is outside scope.

Excluded concepts include:

- Work Orders
- Technician Scheduling
- Maintenance Inventory
- Repair Cost Tracking
- Vendor Dispatch

A dedicated maintenance domain may be introduced later.

---

## 90.6 Procurement and Inventory

Purchasing, stock control, furniture inventory, and consumable inventory are outside the current domain.

---

## 90.7 Tax Accounting

Government tax calculation and tax filing are outside the current Domain Model.

---

## 90.8 Banking Integration

Automatic bank synchronization and payment-provider integration are outside the current domain definition.

The system records Payments but does not currently depend on external banking systems.

---

## 90.9 Automated Payment Allocation

Payment Allocation is intentionally manual.

Automatic allocation algorithms are not part of the current business model.

---

## 90.10 Smart Meter Integration

Utility Readings are currently represented as business records independent of how they are physically collected.

Automatic smart-meter ingestion is outside the current scope.

---

# 91. Conceptual Domain Model

The following model summarizes the major business relationships.

```text id="ic0p8p"
PROPERTY
│
└── UNIT
    │
    ├── RESERVATION
    │   │
    │   ├── Reservation Customer ───────────► CUSTOMER
    │   │
    │   ├── Reservation Extension Notice
    │   │
    │   ├── SECURITY DEPOSIT
    │   │
    │   └──────────────► resulting LEASE
    │
    ├── LEASE
    │   │
    │   ├── Primary Tenant ─────────────────► CUSTOMER
    │   │
    │   ├── Lease Signers ──────────────────► CUSTOMER
    │   │
    │   ├── Occupancy ──────────────────────► CUSTOMER
    │   │
    │   ├── SECURITY DEPOSIT
    │   │
    │   ├── PET DEPOSIT (conditional)
    │   │
    │   ├── optionally associated INVOICES
    │   │
    │   └── FINAL SETTLEMENT (exactly one when TERMINATED)
    │
    └── UTILITY METERS
        │
        └── UTILITY READINGS


CUSTOMER
│
├── INVOICES
│
└── PAYMENT
    │
    └── PAYMENT ALLOCATION ─────────────────► INVOICE

INVOICE ──────── optional zero-or-one association ────────► LEASE


CUSTOMER CREDIT
        │
        └────────────► future allocation / refund / settlement


FINAL SETTLEMENT
│
├── outstanding INVOICES
├── CUSTOMER CREDIT
├── SECURITY DEPOSIT
├── PET DEPOSIT
├── final charges
└── REFUND or remaining balance due
```

---

# 92. Core Tenancy Lifecycle

The complete tenancy lifecycle is conceptually:

```text id="e030zp"
UNIT VACANT
    │
    ▼
RESERVATION CREATED
    │
    ├── Security Deposit partially received
    │
    ├── Reservation may be extended
    │
    ├──────────────► CANCELLED
    │
    ▼
LEASE DRAFTED
    │
    ▼
LEASE SIGNED
    │
    ├── Remaining Security Deposit completed
    │
    ▼
MOVE-IN
    │
    ├── Reservation becomes MOVED_IN
    ├── Unit becomes OCCUPIED
    └── Occupancy begins
    │
    ▼
ACTIVE TENANCY
    │
    ├── Rent Billing
    ├── Utility Billing
    ├── Service Charges
    ├── Payments
    ├── Payment Allocations
    └── Customer Credit
    │
    ▼
AUTHORIZED TERMINATION AND MOVE-OUT PROCESS
    │
    ├── Lease becomes TERMINATED through the approved business action
    ├── Occupancy ends on the actual Move-out Date
    ├── Final readings
    ├── Inspection
    └── Final charges
    │
    ▼
FINAL SETTLEMENT
    │
    ├── Credits applied
    ├── Deposits applied
    ├── Refund issued if required
    └── Remaining balance collected if required
    │
    ▼
SETTLEMENT CLOSED
    │
    ▼
UNIT CLEANING / MAINTENANCE
    │
    ▼
UNIT VACANT
```

---

# 93. Core Financial Model Summary

The financial model intentionally separates five concepts.

```text id="lf713m"
RECEIVABLES
    │
    └── Invoice

CASH RECEIVED
    │
    └── Payment

APPLICATION OF CASH
    │
    └── Payment Allocation

CUSTOMER MONEY AVAILABLE
    │
    └── Customer Credit

MONEY HELD AS LIABILITY
    │
    └── Deposit
```

These concepts must remain distinct throughout the system.

A single monetary receipt must always have a clearly identifiable business purpose and history.

---

# 94. Historical Integrity Model

Historical integrity is a first-class domain concern.

The following information must remain historically reconstructable:

- Customer relationships
- Reservations
- Reservation extensions
- Leases
- Lease Signers
- Occupancy periods
- Rent rates
- Utility rates
- Service rates
- Utility Meters
- Utility Readings
- Invoices
- Payments
- Payment Allocations
- Credits
- Deposits
- Reversals
- Refunds
- Final Settlements

Current information must never overwrite historical business truth.

---

# 95. Derived Versus Authoritative Information

The system distinguishes authoritative facts from derived information.

## Authoritative Facts

Examples include:

- Lease Status
- Reservation Status
- Utility Reading
- Payment received
- Invoice issued
- Deposit received
- Occupancy Move-in Date
- Occupancy Move-out Date

These facts are explicitly recorded.

---

## Derived Information

Examples include:

- Current Customer Credit balance
- Invoice Outstanding Balance
- Total Lease Outstanding Balance
- Current Security Deposit Outstanding
- Utility Consumption
- Unit availability
- Settlement net balance

Derived information must be calculated from authoritative records or maintained in a way that remains fully reconcilable with them.

Derived values must never become an independent competing source of truth.

---

# 96. Data Retention Principles

The domain assumes long-term retention of business history.

Records should not be physically deleted merely because they are no longer active.

Examples:

```text id="flqqzw"
Cancelled Reservation
        ≠ deleted Reservation

Terminated Lease
        ≠ deleted Lease

Replaced Utility Meter
        ≠ deleted Utility Meter

Voided Invoice
        ≠ deleted Invoice

Reversed Payment
        ≠ deleted Payment

Moved-out Occupancy
        ≠ deleted Occupancy
```

Deletion policy and regulatory retention details are defined in later security and operational documentation.

---

# 97. Identity Principles

Every Entity and Aggregate Root has a stable identity.

Identity remains unchanged throughout the lifetime of the business record.

Examples include:

- Customer ID
- Unit ID
- Reservation ID
- Lease ID
- Deposit ID
- Meter ID
- Reading ID
- Invoice ID
- Payment ID
- Settlement ID

Human-readable identifiers such as Unit Number or Meter Serial Number must not be assumed to replace stable system identity.

Database key implementation is deferred to `004_DATABASE_MODEL.md`.

---

# 98. Date and Time Principles

Business dates are significant throughout the domain.

Examples include:

- Reservation Date
- Reservation Expiration Date
- Lease Start Date
- Lease End Date
- Move-in Date
- Move-out Date
- Meter Installed Date
- Meter Replaced Date
- Reading Date
- Invoice Date
- Due Date
- Payment Date
- Refund Date
- Settlement Date

This Domain Model defines their business meaning.

Technical storage format, time zone handling, precision, and database representation are defined in later architecture documents.

---

# 99. Monetary Principles

All monetary values represent an amount together with a Currency.

Conceptually:

```text id="p7m4fb"
Money
├── Amount
└── Currency
```

The Domain Model does not assume floating-point arithmetic.

Technical monetary precision and database representation are defined in `004_DATABASE_MODEL.md`.

---

# 100. Domain Error Principles

An operation that violates a Domain Invariant must be rejected rather than silently corrected.

Examples include attempts to:

- create a second active Reservation for the same Unit
- create overlapping Signed Lease coverage for the same Unit
- terminate a Drafted Lease
- cancel a Signed Lease
- move in without satisfying required move-in conditions
- create two active Electricity Meters for one Unit
- allocate more Payment value than is available
- reduce an Invoice balance below zero
- apply a Deposit during an active Lease
- overwrite historical rates
- delete an audited financial event

The exact error representation belongs to the API and UI specifications.

---

# 101. Domain Decisions Established by This Document

The following architectural domain decisions are considered established by this document:

1. One application manages exactly one Property.
2. Floor is an attribute of Unit.
3. The system currently manages residential Units only.
4. Customer is the single canonical person entity.
5. Customer has no permanent Customer Type.
6. Reservation contains exactly one Customer.
7. Reservation is mandatory before move-in.
8. Reservation statuses are ACTIVE, CANCELLED, and MOVED_IN.
9. Reservation extension is historical activity, not a Reservation status.
10. Security Deposit exists from the Reservation stage onward.
11. There is no separate Reservation Deposit.
12. Security Deposit may be partially paid.
13. Remaining required Security Deposit must be satisfied according to move-in rules.
14. Security Deposit is not refundable while the Lease remains active.
15. Security Deposit and Pet Deposit are liabilities.
16. Pet Deposit applies only when a pet is approved and the applicable signed
Lease terms require it.
17. Every Lease has exactly one Primary Tenant.
18. Primary Tenant must be a Lease Signer.
19. A Lease may have multiple Lease Signers.
20. Every Lease Signer is jointly responsible for the full balance.
21. Occupancy is separate from contractual responsibility.
22. Signed Leases for one Unit must not have overlapping contractual periods.
23. Rent is billed monthly in advance.
24. First and final partial months use actual calendar days when applicable.
25. Recurring monthly Rent Invoices are generated on the 25th and due on the 5th.
26. Electricity and Water use individual Utility Meters.
27. One Unit may have only one active meter per Utility Type.
28. Historical Utility Meters and Utility Readings are preserved.
29. Internet and Trash are fixed recurring service charges.
30. Historical rates must remain preserved; a Utility Invoice selects the Utility
Rate effective on its generation date and applies it to the entire represented
consumption period.
31. Payments and Payment Allocations are separate concepts.
32. Payment allocation is manual.
33. Partial payments are supported.
34. Overpayments and Advance Payments may create Customer Credit.
35. Customer Credit is separate from Deposit.
36. Reversals and Refunds preserve financial history.
37. Deposits may only be applied during Final Settlement.
38. Every Invoice belongs to exactly one Customer and may additionally be
associated with zero or one Lease.
39. Rent Invoices require the applicable signed Lease, and any Lease-associated
Invoice must remain consistent with its Lease context.
40. Every terminated Lease completes exactly one Final Settlement, which closes
its financial lifecycle.
41. Every significant financial change must be audited.
42. Historical records must not be silently deleted or rewritten.

---

# 102. Specification Responsibilities

This Domain Model defines the core concepts and invariants. The completed
`002_BUSINESS_RULES.md` defines approved operational policy. Implementation and
product details remain assigned to the later numbered specifications.

## `002_BUSINESS_RULES.md`

Defines rules such as:

- maximum Reservation duration
- exact Reservation extension eligibility
- maximum extension duration
- Reservation expiration behavior
- minimum Security Deposit amount at Reservation
- move-in deposit requirements
- cancellation and refund authorization
- Rent proration formulas
- invoice generation rules
- due-date rules
- utility calculation rules
- rate-effective-date rules
- final settlement rules
- deposit deduction priority
- refund rules
- Lease termination rules

---

## `003_PRODUCT_REQUIREMENTS.md`

Will define:

- system capabilities
- user workflows
- functional requirements
- non-functional product requirements
- acceptance expectations

---

## `004_DATABASE_MODEL.md`

Will define:

- tables
- columns
- keys
- constraints
- indexes
- historical data representation
- monetary storage
- date/time storage
- audit persistence

---

## `005_API_SPECIFICATION.md`

Will define:

- application operations
- API resources
- commands
- queries
- request/response structures
- error contracts

---

## `006_UI_SPECIFICATION.md`

Will define:

- screens
- forms
- navigation
- dashboards
- workflows
- field presentation
- user interaction behavior

---

## `007_TESTING_STRATEGY.md`

Will define:

- domain tests
- business-rule tests
- integration tests
- financial reconciliation tests
- regression testing
- acceptance testing

---

## `008_SECURITY_MODEL.md`

Will define:

- roles
- permissions
- authorization
- sensitive data protection
- financial action restrictions
- audit access

---

## `009_DEPLOYMENT_ARCHITECTURE.md`

Will define:

- application topology
- infrastructure
- environments
- database hosting
- backup
- recovery
- networking
- deployment procedures

---

## `010_DECISION_LOG.md`

Will record significant architectural decisions and future changes to the model.

---

# 103. Change Governance

This document is the authoritative definition of the business domain.

Future implementation work must conform to it.

If a later requirement conflicts with this document, the conflict must not be silently resolved in code.

The process is:

```text id="zwxp9m"
New Business Requirement
        │
        ▼
Evaluate Domain Impact
        │
        ├── No Domain Change
        │       └── Update relevant later specification
        │
        └── Domain Change Required
                │
                ▼
        Record Architectural Decision
                │
                ▼
        Update 001_DOMAIN_MODEL.md
                │
                ▼
        Update dependent specifications
```

This prevents the implementation and documentation from gradually diverging.

---

# 104. Document Dependency Rule

Later documents depend on this Domain Model.

Therefore:

> A lower-level document may refine a domain concept, but it must not contradict or redefine it without first updating the Domain Model and recording the decision.

For example:

- The Database Model may choose how to persist `LeaseSigner`.
- It may not redefine Lease Signer as an Occupant.
- The API Specification may expose Reservation commands.
- It may not introduce `EXTENDED` as a Reservation status.
- The UI may display Security Deposit payments made during Reservation.
- It may not label them as a separate Reservation Deposit.
- The Payment API may support allocation.
- It may not automatically allocate payments if manual allocation remains the approved business model.

---

# 105. Domain Model Completion Criteria

This Domain Model is considered complete for the initial architecture phase when it provides a stable answer to the following questions:

- What are the principal business concepts?
- Which concepts have independent identity?
- What relationships exist between them?
- Which states and lifecycles are valid?
- Who is contractually responsible?
- Who physically occupies a Unit?
- How does Reservation relate to Lease?
- How does Security Deposit behave before and during the Lease?
- How are Utility Meters and Utility Readings historically preserved?
- What constitutes an Invoice?
- What constitutes a Payment?
- How is Customer Credit different from Deposit?
- How is a Lease financially closed?
- Which historical information must remain auditable?
- Which areas of the business own which concepts?
- Which implementation concerns are intentionally deferred?

Detailed operational formulas and authorization conditions are defined in
`002_BUSINESS_RULES.md`. Product and implementation concerns remain assigned to
the applicable later numbered specifications.

---

# 106. Final Domain Summary

The Property Rental Management System manages the full residential tenancy lifecycle for one Property.

At its center is the Unit.

A Unit may be reserved by one Customer and later leased under one active Lease.

The Lease has exactly one Primary Tenant and may have multiple Lease Signers and Occupants.

Lease Signers establish contractual financial responsibility.

Occupancy establishes physical residence.

These concepts remain separate.

Security Deposit begins during Reservation and may initially be only partially paid. It remains the same Security Deposit throughout the tenancy and is held as a liability until Final Settlement.

Utility consumption is based on historically preserved Electricity and Water meters and their readings.

Billing creates receivables.

Payments represent money received.

Payment Allocations determine how that money is applied.

Overpayments and Advance Payments may create Customer Credit.

Deposits and Customer Credit are distinct financial concepts.

Move-out ends physical occupancy, while Lease termination ends the contractual lifecycle.

Final Settlement closes the financial lifecycle by reconciling charges, Credits, Deposits, Refunds, and remaining balances.

Throughout the entire lifecycle, historical truth must remain preserved.

No significant financial event may be silently deleted, overwritten, or made impossible to reconstruct.

This Domain Model establishes the business foundation upon which all remaining system specifications are built.

---
