# 010 - Decision Log

**Project:** Property Rental Management System
**Document:** Decision Log
**Version:** 1.0
**Status:** Owner Review
**Depends On:** `001_DOMAIN_MODEL.md` through `009_DEPLOYMENT_ARCHITECTURE.md`
**Audience:** Product Owner, Business Analysts, Software Architects, Developers, QA Engineers

---

# 1. Purpose

This document records significant recoverable decisions governing the Property
Rental Management System.

It distinguishes:

- literal Owner-approved business policy recovered from repository/session history;
- business decisions embodied in the authoritative Domain Model and Business Rules;
- implementation requirements derived from those decisions without adding business policy;
- technical design directions already recorded by the repository; and
- material questions that still require an Owner decision.

This log does not establish chronology. Decision dates, rationale, and considered
alternatives are stated as **not recorded** unless an authoritative source states
them explicitly. An entry summarizes its cited source; it does not replace the
full governing rules.

---

# 2. Authority and Use

The governing precedence is:

1. explicit Owner decisions already embodied in authoritative documents and recoverable history;
2. `001_DOMAIN_MODEL.md`;
3. `002_BUSINESS_RULES.md`;
4. derived technical requirements necessary to implement those rules;
5. conservative implementation assumptions that do not change business policy.

Later specifications may refine implementation but must not silently contradict
or reinterpret `001_DOMAIN_MODEL.md` or `002_BUSINESS_RULES.md`. A new material
business policy requires an `OPEN OWNER DECISION`, Owner approval, and updates to
every affected authoritative document.

Older unnumbered placeholder documents are not decision authority.

---

# 3. Classification and Status Vocabulary

## 3.1 Types

| Type | Meaning |
| --- | --- |
| `OWNER BUSINESS DECISION` | A business-policy choice explicitly approved by the Owner or embodied as an established business decision in 001/002. Provenance identifies which applies. |
| `DERIVED REQUIREMENT` | A necessary implementation consequence of authoritative policy that does not introduce new business policy. |
| `TECHNICAL DESIGN DECISION` | A recorded choice about implementation technology, architecture, or engineering practice. |
| `OPEN OWNER DECISION` | A material business-policy question for which no approved answer was recovered. |

## 3.2 Entry Statuses

| Status | Meaning |
| --- | --- |
| `APPROVED` | Literal Owner approval was recovered. |
| `ESTABLISHED` | The decision is embodied in 001/002; a separate literal approval statement was not recovered. |
| `REQUIRED` | The requirement follows from cited authoritative rules. |
| `DIRECTION RECORDED` | The repository records the technical direction, but later design documents must refine it. |
| `OPEN` | Owner approval is still required. |
| `SUPERSEDED` | The entry records a formerly open or formerly stated position that later authoritative reconciliation resolved; the historical ID remains preserved. |
| `RECONCILIATION REQUIRED` | An approved decision and a current cited rule do not express the same policy. |

---

# 4. Scope and Domain Decisions

## DL-001 — Single-property residential scope

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `ESTABLISHED`
- **Decision:** One deployed application manages exactly one residential Property. Multi-property portfolio management and commercial leasing are outside the current scope.
- **Provenance:** Embodied in `001_DOMAIN_MODEL.md`; separate literal Owner rationale was not recovered.
- **Affected documents/rules:** `001_DOMAIN_MODEL.md` sections 2, 4.1, 43, 90.1, 90.2, and 101; `BR-PROP-001`; `BR-UNIT-001`.
- **Rationale:** Not recorded.
- **Decision date:** Not recorded.
- **Alternatives:** Not recorded.

## DL-002 — Canonical person model

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `ESTABLISHED`
- **Decision:** `Customer` is the canonical role-neutral person entity. Reservation Customer, Primary Tenant, Lease Signer, Occupant, former occupant, and payer are relationships or roles, not permanent Customer types.
- **Provenance:** Embodied in `001_DOMAIN_MODEL.md` and `002_BUSINESS_RULES.md`.
- **Affected documents/rules:** `001_DOMAIN_MODEL.md` sections 5, 9.3, 44, 73, 88, 89.1-89.4, and 101; `BR-CUST-001` through `BR-CUST-003`; `BR-OCC-001` through `BR-OCC-006`.
- **Rationale:** Not recorded.
- **Decision date:** Not recorded.
- **Alternatives:** Not recorded.

## DL-003 — Reservation is required and has a fixed status vocabulary

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `ESTABLISHED`
- **Decision:** A valid Reservation is required before move-in. Reservation statuses are only `ACTIVE`, `CANCELLED`, and `COMPLETED`; an extension is historical activity rather than a status. `COMPLETED` means the Reservation successfully proceeded through move-in into its resulting Lease and Occupancy.
- **Provenance:** Embodied in 001/002. The prohibition on an `EXPIRED` status and the reconciled successful-completion lifecycle are authoritative upstream.
- **Affected documents/rules:** `001_DOMAIN_MODEL.md` sections 9.4, 45, 46, 89.6, 89.7, and 101; `BR-RES-001`, `BR-RES-003`, `BR-RES-009`, `BR-RES-013`, `BR-RES-014`.
- **Rationale:** Not recorded.
- **Decision date:** Not recorded.
- **Alternatives:** Alternatives were discussed; their complete record is not reproduced here.

## DL-004 — Reservation expiration

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `APPROVED`
- **Decision:** An `ACTIVE` Reservation remains valid through its Expiration Date in the Property local timezone. At end of date, if it has not moved in and has no valid extension, it automatically becomes `CANCELLED` with reason `RESERVATION_EXPIRED`, releases the Unit, and preserves complete history. No `EXPIRED` status is added.
- **Provenance:** Literal Owner Decision 1 recovered from session history.
- **Affected documents/rules:** `BR-RES-005`, `BR-RES-011`, `BR-RES-015`, `BR-RES-016`; `BR-UNIT-010`; `BR-AUDIT-002`.
- **Rationale:** Not recorded as part of the approved decision.
- **Decision date:** Not recorded in this log.
- **Alternatives:** Presented before approval; not adopted.

## DL-005 — Reservation extension

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `APPROVED`
- **Decision:** An `ACTIVE` Reservation may be extended once, only while unexpired and with fewer than 14 calendar days remaining. The extension adds at most 14 calendar days to the existing Expiration Date and is preserved through a Reservation Extension Notice with complete history.
- **Provenance:** Literal Owner Decision 2 recovered from session history.
- **Affected documents/rules:** `BR-RES-007` through `BR-RES-010`; `BR-RES-017` through `BR-RES-019`; `BR-AUDIT-002`; `BR-AUTH-002`.
- **Rationale:** Not recorded as part of the approved decision.
- **Decision date:** Not recorded in this log.
- **Alternatives:** Presented before approval; not adopted.

## DL-006 — Lease parties, responsibility, and occupancy

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `ESTABLISHED`
- **Decision:** Each Lease has exactly one Primary Tenant, and that Customer must be a Lease Signer. A Lease has one or more signers, each jointly responsible for the full unpaid Lease obligation. Occupancy records physical residence and does not itself create financial responsibility.
- **Provenance:** Embodied in 001/002; separate literal Owner rationale was not recovered.
- **Affected documents/rules:** `001_DOMAIN_MODEL.md` sections 9.5, 15.7-15.9, 19, 47-49, and 101; `BR-LEASE-006` through `BR-LEASE-011`; `BR-OCC-001` through `BR-OCC-009`.
- **Rationale:** Not recorded.
- **Decision date:** Not recorded.
- **Alternatives:** Not recorded.

## DL-007 — Lease status and Unit exclusivity

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `ESTABLISHED`
- **Decision:** Lease statuses are only `DRAFTED`, `SIGNED`, `CANCELLED`, and `TERMINATED`, with transitions `DRAFTED -> SIGNED`, `DRAFTED -> CANCELLED`, and `SIGNED -> TERMINATED`. Signed Leases for one Unit must not have overlapping contractual periods.
- **Provenance:** Embodied in 001/002.
- **Affected documents/rules:** `001_DOMAIN_MODEL.md` sections 9.2, 9.5, 15.6, 16.3, 47, 85, and 101; `BR-UNIT-005`; `BR-LEASE-001` through `BR-LEASE-005`; `BR-LEASE-014`.
- **Rationale:** Not recorded.
- **Decision date:** Not recorded.
- **Alternatives:** Not recorded.

---

# 5. Deposit and Pet Decisions

## DL-008 — Security Deposit identity, minimum, and move-in deadline

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `APPROVED`
- **Decision:** There is no separate Reservation Deposit. The money collected during Reservation is the same Security Deposit that continues into the resulting Lease. The normal/default suggested initial amount is 20% of agreed monthly Rent, but it is not a hard minimum. A Reservation becomes ACTIVE after the explicitly accepted initial partial Security Deposit amount is received; authorized management may accept an amount below or above the 20% suggestion with preserved authorization, reason, actor, and calculation evidence. The remaining required Security Deposit may be paid before or at move-in and must be complete no later than move-in completion.
- **Provenance:** Owner-approved Reservation/Security Deposit policy as reconciled and embodied in 001/002.
- **Affected documents/rules:** `001_DOMAIN_MODEL.md` sections 33, 35, 50, 65, 89.5, and 101; `BR-DEP-001` through `BR-DEP-006`; `BR-LEASE-015`; `BR-RES-013`.
- **Rationale:** Not recorded as part of the approved decisions.
- **Decision date:** Not recorded in this log.
- **Alternatives:** Presented before approval; not adopted.

## DL-009 — Reservation cancellation and Security Deposit disposition

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `APPROVED`
- **Decision:** Security Deposit received is non-refundable for a Customer-caused cancellation or Customer-caused expiration when the Property could provide the Unit. If the Property cannot provide the Unit as agreed, management first coordinates a delay or alternative Unit; if the Customer rejects that and requests cancellation, the received Security Deposit is refunded in full through an explicit Refund event. Responsibility must reflect the actual cause.
- **Provenance:** Literal Owner Decision 4.
- **Affected documents/rules:** `BR-RES-020` through `BR-RES-022`; `BR-DEP-015` through `BR-DEP-017`; `BR-REFUND-004`; `BR-AUDIT-002`, `BR-AUDIT-008`.
- **Rationale:** Not recorded as part of the approved decision.
- **Decision date:** Not recorded in this log.
- **Alternatives:** A custom Owner policy was approved; alternatives are not recorded here.

## DL-010 — Pet Deposit applicability and timing

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `APPROVED`
- **Decision:** Pet Deposit applies only when both the pet is approved and the applicable signed Lease terms require it. A required Pet Deposit for a pet present from initial occupancy is due before or at move-in. A later approved pet requires notice and payment before or when the pet begins staying. No Pet Deposit is required merely because a future pet is possible.
- **Provenance:** Literal Owner Decision 5 and supplementary clarification embodied in 001/002.
- **Affected documents/rules:** `001_DOMAIN_MODEL.md` sections 5, 34, 50, and 101; `BR-DEP-007` through `BR-DEP-010`; `BR-DEP-020`; `BR-LEASE-015`.
- **Rationale:** Not recorded as part of the approved decision.
- **Decision date:** Not recorded in this log.
- **Alternatives:** Not recorded.

## DL-011 — Undisclosed pet handling

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `APPROVED`
- **Decision:** Discovery of an undisclosed or unauthorized pet does not automatically terminate the Lease. Management informs the Customer; a Pet Deposit is required only when the pet is approved and the signed Lease requires it. Refusal or failure to comply may proceed under the signed Lease and the approved warning process. No additional pet penalty is created.
- **Provenance:** Literal Owner Decision 5.
- **Affected documents/rules:** `BR-DEP-021`, `BR-DEP-022`; `BR-LEASE-024`, `BR-LEASE-025`; `BR-AUTH-005`.
- **Rationale:** Not recorded as part of the approved decision.
- **Decision date:** Not recorded in this log.
- **Alternatives:** Not recorded.

## DL-012 — Deposit use and explicit disposition

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `APPROVED`
- **Decision:** Security Deposit and Pet Deposit cannot be used as ordinary Rent or other Invoice payment before Final Settlement. Every approved non-refundable outcome uses an explicit linked forfeiture/disposition event that preserves the original receipt, amount, type, reason, governing event, effective date, authorization, and audit history. It is not fabricated as an ordinary Invoice allocation.
- **Provenance:** Literal Owner Decision 14 and supplementary Decision S7.
- **Affected documents/rules:** `BR-DEP-011` through `BR-DEP-019`; `BR-SETTLE-010`, `BR-SETTLE-014`; `BR-AUDIT-008`; `BR-AUTH-008`.
- **Rationale:** Not recorded as part of the approved decisions.
- **Decision date:** Not recorded in this log.
- **Alternatives:** Presented before approval; not adopted.

## DL-013 — Pet Deposit at voluntary early termination

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `APPROVED`
- **Decision:** Voluntary early termination makes the Security Deposit non-refundable but does not automatically make the Pet Deposit non-refundable. Pet Deposit remains separately tracked through Final Settlement. It is identified first for valid pet-caused property damage or extraordinary/deep-cleaning obligations; after Customer Credit and explicitly selected Security Deposit applications, authorized management may explicitly apply remaining Pet Deposit to another valid remaining Settlement obligation when permitted by the approved Settlement rules. Any remaining refundable balance is returned explicitly.
- **Provenance:** Literal supplementary Owner Decision S8.
- **Affected documents/rules:** `BR-DEP-023`, `BR-DEP-024`; `BR-SETTLE-005`, `BR-SETTLE-008`; `BR-REFUND-007`.
- **Rationale:** Not recorded as part of the approved decision.
- **Decision date:** Not recorded in this log.
- **Alternatives:** Presented before approval; not adopted.

---

# 6. Lease End, Termination, and Move-out Decisions

## DL-014 — Normal Lease end and holdover

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `APPROVED`
- **Decision:** There is no automatic month-to-month tenancy. By the contractual End Date, a Lease should normally have an approved signed renewal or proceed through authorized termination and move-out. Arrival of the End Date does not automatically terminate a Lease while occupancy continues. Continued occupancy requires management action under the signed Lease and creates no automatic holdover Rent, fee, penalty, or new tenancy.
- **Provenance:** Literal supplementary Owner Decision S1.
- **Affected documents/rules:** `BR-LEASE-017` through `BR-LEASE-019`; `BR-MOVEOUT-007` through `BR-MOVEOUT-009`; `BR-RENT-010`.
- **Rationale:** Not recorded as part of the approved decision.
- **Decision date:** Not recorded in this log.
- **Alternatives:** Presented before approval; not adopted.

## DL-015 — Voluntary early termination

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `APPROVED`
- **Decision:** A Customer has no general early-termination right. If management processes voluntary early termination, the Lease terminates on the approved actual termination/move-out date; the final calendar month of Rent is charged in full; valid Utility, fixed Service, and other obligations remain due; Security Deposit is non-refundable; no standard early-termination fee is created; and Rent is not generated for later months through the original End Date.
- **Provenance:** Literal Owner Decision 6.
- **Affected documents/rules:** `BR-LEASE-020`, `BR-LEASE-021`, `BR-LEASE-023`; `BR-RENT-012`, `BR-RENT-024` through `BR-RENT-026`; `BR-MOVEOUT-010`; `BR-DEP-023`.
- **Rationale:** Not recorded as part of the approved decision.
- **Decision date:** Not recorded in this log.
- **Alternatives:** A custom Owner policy was approved; alternatives are not recorded here.

## DL-016 — Violation termination

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `APPROVED`
- **Decision:** At least three documented warning letters are required before Lease termination for a Customer violation. The violation and termination authority must come from the signed Lease. The system must not invent violations, penalties, fees, forfeitures, or termination rights.
- **Provenance:** Literal Owner Decision 6.
- **Affected documents/rules:** `BR-LEASE-024`, `BR-LEASE-025`; `BR-DEP-022`; `BR-AUDIT-003`; `BR-AUTH-005`.
- **Rationale:** Not recorded as part of the approved decision.
- **Decision date:** Not recorded in this log.
- **Alternatives:** Not recorded.

## DL-017 — Move-out and financial closure are separate

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `ESTABLISHED`
- **Decision:** Move-out records the actual end of physical occupancy and collects settlement inputs. It does not itself complete financial closure. Final Settlement may remain pending after move-out until all required valid charges are final.
- **Provenance:** Embodied in 001/002 and aligned during authoritative-document review.
- **Affected documents/rules:** `001_DOMAIN_MODEL.md` sections 37, 49, 80, 92, and the Move-out glossary; `BR-MOVEOUT-001` through `BR-MOVEOUT-012`; `BR-SETTLE-011`.
- **Rationale:** Not recorded.
- **Decision date:** Not recorded.
- **Alternatives:** Not recorded.

---

# 7. Billing and Invoice Decisions

## DL-018 — Rent billing cadence, proration, and source

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `ESTABLISHED`
- **Decision:** Rent is billed monthly in advance. Recurring Rent Invoices are generated on the 25th for the upcoming calendar month and are due on the 5th day of that billed month. The Initial Rent Invoice is due seven calendar days after the actual Move-in Date, including when that date falls in the following month. Initial Rent coverage depends on Move-in Date: day 1–20 covers the Move-in Date through month-end; day 21 or later combines the prorated remainder of that month with the entire following month. First partial months, and final partial months when an approved rule permits proration, use inclusive actual calendar days with final half-up USD-cent rounding. Every Rent Invoice requires the applicable signed Lease, and contractual Rent comes from that Lease.
- **Provenance:** Embodied in 001/002; monetary details were explicitly approved in Owner Decision 7.
- **Affected documents/rules:** `001_DOMAIN_MODEL.md` sections 21 and 101; `BR-RENT-001` through `BR-RENT-028`; `BR-MONEY-012`, `BR-MONEY-013`.
- **Rationale:** Not recorded.
- **Decision date:** Not recorded.
- **Alternatives:** Not recorded.

## DL-019 — Invoice ownership and optional Lease association

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `APPROVED`
- **Decision:** Every Invoice belongs to exactly one Customer. An Invoice may additionally be associated with zero or one Lease. A Lease-associated Invoice must be consistent with its Customer, Unit, obligation, period, and Lease context. Rent Invoices require the applicable signed Lease. Optional Lease association does not authorize arbitrary charges or new Invoice categories.
- **Provenance:** Literal Owner approval recovered in the focused Invoice Ownership amendment; subsequently embodied in 001/002.
- **Affected documents/rules:** `001_DOMAIN_MODEL.md` sections 9.8, 15.12, 20, 53, 91, and 101; `BR-INV-001`, `BR-INV-002`, `BR-INV-036` through `BR-INV-042`; `002_BUSINESS_RULES.md` section 31.2.
- **Rationale:** Not recorded as part of the approved amendment.
- **Decision date:** Not recorded in this log.
- **Alternatives:** A mandatory-Lease model existed in earlier material and was superseded; complete chronology is intentionally not asserted here.

## DL-020 — Supported Invoice categories and fixed Service lines

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `APPROVED`
- **Decision:** Supported Invoice/line categories are Rent, Utilities, Service Charges, Damage Charges, and Miscellaneous Charges. Deposits are not Invoice categories. Trash Collection is the currently approved recurring fixed Service and appears as a separately categorized line on the applicable Rent Invoice, billed in advance using the approved Initial/recurring Rent-period structure. Internet and Monthly Cleaning are not currently approved as active billable Services and must not generate charges merely because a Service identity or rate can be configured. Final or early-termination Service treatment follows the signed Lease and approved termination rules and is not automatically prorated merely because physical occupancy ends.
- **Provenance:** Owner-approved fixed-Service policy as reconciled and embodied in 001/002.
- **Affected documents/rules:** `001_DOMAIN_MODEL.md` sections 20.2, 23, and 53; `BR-SVC-001` through `BR-SVC-015`; `BR-INV-006` through `BR-INV-008`; `BR-INV-039`, `BR-INV-042`.
- **Rationale:** Not recorded as part of the approved decision.
- **Decision date:** Not recorded in this log.
- **Alternatives:** Presented before approval; not adopted.

## DL-021 — Invoice lifecycle

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `APPROVED`
- **Decision:** Invoice statuses are `DRAFT`, `UNPAID`, `PARTIALLY_PAID`, `PAID`, and `VOID`. `DRAFT` is pre-issuance and excluded from receivables and overdue balances. Issuance changes `DRAFT` to `UNPAID`; abandoning a Draft changes it to `VOID` with preserved reason and history. Deterministic scheduled Invoices may be generated and issued without manual approval of every Draft.
- **Provenance:** Literal Owner Decision 11.
- **Affected documents/rules:** `BR-INV-009` through `BR-INV-015`; `BR-INV-043`; `BR-INV-050`; `001_DOMAIN_MODEL.md` section 16.7.
- **Rationale:** Not recorded as part of the approved decision.
- **Decision date:** Not recorded in this log.
- **Alternatives:** Presented before approval; not adopted.

## DL-022 — Invoice source integrity, duplicate prevention, and correction

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `APPROVED`
- **Decision:** Invoice amounts must come from approved source facts. Duplicate Rent, Utility, and recurring Service billing must be prevented. A Draft may be corrected before issuance. An issued Invoice is not silently rewritten; legitimate amount corrections use linked debit/credit Adjustments. `VOID` is exceptional for an Invoice that fundamentally should not exist and requires explicit resolution of active financial dependencies.
- **Provenance:** Literal Owner Decision 12.
- **Affected documents/rules:** `BR-RENT-004`, `BR-RENT-011`, `BR-RENT-022`, `BR-RENT-023`, `BR-RENT-027`; `BR-UTIL-018`, `BR-UTIL-032`; `BR-SVC-014`, `BR-SVC-015`; `BR-INV-019` through `BR-INV-050`.
- **Rationale:** Not recorded as part of the approved decision.
- **Decision date:** Not recorded in this log.
- **Alternatives:** Presented before approval; not adopted.

## DL-023 — Utility billing and generation-date rate selection

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `APPROVED`
- **Decision:** Electricity and Water are billed monthly after an ending Reading is entered and validated, or after an authorized broken-meter estimate is complete. The Invoice is due on the 5th of the following month. The Utility Rate effective on the Invoice generation date applies to the entire represented consumption period; the period is not split merely because a rate changed within it. Customers receive advance notice before a Utility Rate change becomes effective.
- **Provenance:** Literal Owner Decision 9.
- **Affected documents/rules:** `001_DOMAIN_MODEL.md` sections 22.3, 39, and 101; `BR-UTIL-014` through `BR-UTIL-022`; `BR-UTIL-029` through `BR-UTIL-032`.
- **Rationale:** Not recorded as part of the approved decision.
- **Decision date:** Not recorded in this log.
- **Alternatives:** A custom Owner policy was approved; alternatives are not recorded here.

## DL-024 — Missing Reading and confirmed broken Meter

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `APPROVED`
- **Decision:** An ordinary missing or inaccessible Reading does not authorize estimation; billing waits for a valid actual Reading. For a confirmed broken Meter, replace the Meter and permit an explicitly identified estimate for the unmeasured period. With sufficient history, use the three most recent complete actual periods for the same Unit and Utility Type, calculate one weighted daily average from total consumption and total represented days, and preserve the full estimation audit trail.
- **Provenance:** Literal Owner Decision 8; selection of the three most recent periods is embodied in `BR-UTIL-025`.
- **Affected documents/rules:** `BR-UTIL-002`, `BR-UTIL-006`, `BR-UTIL-007`, `BR-UTIL-023` through `BR-UTIL-026`; `BR-AUDIT-004`; `BR-AUTH-004`.
- **Rationale:** Not recorded as part of the approved decision.
- **Decision date:** Not recorded in this log.
- **Alternatives:** A custom Owner policy was approved; alternatives are not recorded here.

## DL-025 — Broken-Meter estimation with fewer than three historical periods

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `ESTABLISHED`
- **Decision:** For a confirmed broken Meter, three or more complete historical actual periods use the three most recent complete periods. If exactly one or two complete historical actual periods exist for the same Unit and Utility Type, all available one or two periods are used as the weighted historical basis; they must not be discarded. Only when zero complete historical actual periods exist does the affected estimate/charge remain pending until one complete future actual period for that same Unit and Utility Type becomes available. Another or comparable Unit and arbitrary estimates are prohibited.
- **Provenance:** The final reconciled broken-Meter hierarchy is embodied authoritatively in 001/002 and propagated through 003–009.
- **Affected documents/rules:** `BR-UTIL-025` through `BR-UTIL-028`; `BR-MOVEOUT-005`, `BR-MOVEOUT-012`; `BR-SETTLE-011`; `BR-AUDIT-004`.
- **Reconciliation note:** Earlier recovered wording treated all fewer-than-three-history cases as pending. The approved authoritative rules supersede that interpretation: one/two-period history is usable immediately; only zero-history waits for a future complete actual period.
- **Rationale:** Preserve same-Unit actual evidence whenever available without inventing a comparable-Unit estimate.
- **Decision date:** Not recorded in this log.
- **Alternatives:** Earlier wording is preserved by this reconciliation note but is not the current governing policy.

## DL-026 — Due Date source for non-recurring obligations

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `APPROVED`
- **Decision:** The Due Date for Damage Charges, Miscellaneous Charges, debit Adjustments, and other non-recurring obligations comes from the signed Lease or approved governing business event/document. Authorized staff may record it, but it must not be arbitrary, automatically set to the monthly 5th, or automatically made immediate unless the governing source requires that result.
- **Provenance:** Literal supplementary Owner Decision S9.
- **Affected documents/rules:** `BR-INV-018`, `BR-INV-049`; `BR-AUDIT-006`; `BR-AUTH-006`.
- **Rationale:** Not recorded as part of the approved decision.
- **Decision date:** Not recorded in this log.
- **Alternatives:** Presented before approval; not adopted.

---

# 8. Payment, Currency, Credit, Refund, and Settlement Decisions

## DL-027 — Currency and exchange-rate policy

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `APPROVED`
- **Decision:** USD is the base/accounting and Invoice currency. Payments may be received in USD or KHR. The preferred reference is the ABA Bank USD/KHR Sell rate; the System Exchange Rate is that reference multiplied by `1.005`, rounded upward to the next whole KHR. The rate is selected when Payment receipt is confirmed. If automatic retrieval fails, an authorized user enters the ABA-equivalent reference Sell rate and the same markup and rounding apply. A fractional final KHR payable amount is also rounded upward. Historical transaction and rate facts remain preserved.
- **Provenance:** Literal Owner Decision 7 and supplementary Decision S3.
- **Affected documents/rules:** `BR-MONEY-001` through `BR-MONEY-011`; `BR-PAY-005` through `BR-PAY-007`; `BR-AUDIT-005`, `BR-AUDIT-007`; `BR-AUTH-003`.
- **Rationale:** Not recorded as part of the approved decisions.
- **Decision date:** Not recorded in this log.
- **Alternatives:** A custom Owner policy was approved; alternatives are not recorded here.

## DL-028 — Payment, allocation, reversal, and Refund are separate events

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `ESTABLISHED`
- **Decision:** A Payment records money received. Payment Allocation records how received value is applied. Allocation progress is derived and does not create Payment receipt statuses. Payment receipt statuses are `RECEIVED` and `REVERSED`. Reversal and Refund are explicit linked events that preserve rather than rewrite the original Payment and allocations.
- **Provenance:** Embodied in 001/002 and preserved by literal Owner instructions.
- **Affected documents/rules:** `001_DOMAIN_MODEL.md` sections 26, 31, 32, 41, 54, 68, 78, and 101; `BR-PAY-003`, `BR-PAY-008` through `BR-PAY-018`; `BR-REFUND-001`, `BR-REFUND-010` through `BR-REFUND-012`.
- **Rationale:** Not recorded.
- **Decision date:** Not recorded.
- **Alternatives:** Not recorded.

## DL-029 — Manual authorized Payment Allocation and FIFO proposal

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `APPROVED`
- **Decision:** Payment Allocation remains manual and is posted only after authorized staff confirmation. The system may calculate a deterministic proposal. Without a Customer designation, the default between-Invoice proposal uses oldest Due Date first across applicable outstanding Invoices, with Invoice issue/generation order and then stable sequence/ID for ties. Within a selected mixed Rent Invoice, the default proposal applies value to Rent first and then recurring-Service lines; authorized staff still confirm the proposal. A valid Customer designation may select an eligible Invoice, line/obligation category, or separate positive Late-payment Charge. Late-payment Charges are separate obligations and are not silently inserted into the default Invoice FIFO. Third-party Payment follows identified intent and is not spread automatically across unrelated obligations.
- **Provenance:** Owner-approved manual Allocation/FIFO policy as subsequently reconciled in 001/002.
- **Affected documents/rules:** `BR-PAY-019` through `BR-PAY-040`; `BR-AUTH-*`; applicable Invoice and Late-payment rules.
- **Rationale:** Not recorded as part of the approved decisions.
- **Decision date:** Not recorded in this log.
- **Alternatives:** Presented before approval; automatic posting was not adopted.

## DL-030 — Overpayment choice and Customer Credit

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `APPROVED`
- **Decision:** A true overpayment exists only after applicable outstanding obligations are handled. Excess remains unallocated value on the original `RECEIVED` Payment and does not automatically become Customer Credit. Management coordinates whether the payer wants Credit or Refund. Only authorized retained value becomes Customer Credit, linked to the original Payment; an early future Invoice is not created merely to absorb advance money.
- **Provenance:** Literal Owner Decision 13.
- **Affected documents/rules:** `BR-PAY-030` through `BR-PAY-035`; `BR-CREDIT-002`, `BR-CREDIT-003`, `BR-CREDIT-005`; `BR-REFUND-002`; `BR-AUTH-008`.
- **Rationale:** Not recorded as part of the approved decision.
- **Decision date:** Not recorded in this log.
- **Alternatives:** A custom Owner policy was approved; alternatives are not recorded here.

## DL-031 — Customer Credit and KHR-origin Refund accounting

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `PARTIALLY SUPERSEDED BY DL-060` — the historical KHR-refund clauses below are no longer operative. USD Credit, same-Customer scope and original KHR source-evidence preservation remain approved.
- **Decision:** Customer Credit is maintained in USD accounting value and is not transferable to another Customer. For KHR-origin value, preserve the original KHR amount and exact receipt rate. Refund KHR excess before Credit recognition in the corresponding original KHR amount. If USD Customer Credit is later refunded in KHR, use the exchange rate applicable to that Refund and preserve both currency values, rate, and source relationship. No separate KHR-denominated Credit balance is approved.
- **Provenance:** Literal supplementary Owner Decision S4 and the same-Customer rules embodied in 002.
- **Affected documents/rules:** `BR-CREDIT-001` through `BR-CREDIT-012`; `BR-REFUND-005`, `BR-REFUND-006`, `BR-REFUND-008`; `BR-MONEY-001`, `BR-MONEY-002`.
- **Rationale:** Not recorded as part of the approved decision.
- **Decision date:** Not recorded in this log.
- **Alternatives:** Presented before approval; not adopted.

## DL-032 — Final Settlement order

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `APPROVED`
- **Decision:** For each terminated Lease, finalize every valid Settlement obligation; apply authorized Customer Credit first; identify Pet Deposit first for valid pet-caused property damage or extraordinary/deep-cleaning obligations; explicitly select and confirm any Security Deposit applications to valid remaining Settlement obligations; if a valid Settlement balance still remains and the Customer has not paid or will not pay it, authorized management may explicitly select remaining Pet Deposit for another valid remaining Settlement obligation; record any remaining Customer balance; and explicitly refund remaining refundable Deposit balances. No general Payment FIFO or inferred Deposit-type FIFO/oldest-due order controls Deposit application. Every input, application, disposition, Refund, correction, and result remains separately traceable.
- **Provenance:** Final Settlement policy as reconciled and embodied in the authoritative 001/002 baseline.
- **Affected documents/rules:** `BR-SETTLE-001` through `BR-SETTLE-015`; `BR-REFUND-007`; `BR-AUDIT-009`; `BR-AUTH-009`; `001_DOMAIN_MODEL.md` sections 37 and 57.
- **Rationale:** Not recorded as part of the approved decision.
- **Decision date:** Not recorded in this log.
- **Alternatives:** Presented before approval; not adopted.

---

# 9. Derived Implementation Requirements

The entries in this section are implementation consequences. They do not approve
new business policy.

## DL-033 — Stable identities and rule identifiers

- **Type:** `DERIVED REQUIREMENT`
- **Status:** `REQUIRED`
- **Decision:** Entities and Aggregate Roots require stable identities independent of mutable human-readable values. Downstream specifications must use the unique `BR-*` identifiers as stable policy references.
- **Derived from:** `001_DOMAIN_MODEL.md` section 97; `002_BUSINESS_RULES.md` section 31.4.
- **Affected documents/rules:** 004-008; all `BR-*` references.
- **Rationale:** Not separately recorded; this is the cited authoritative requirement.
- **Decision date:** Not recorded.
- **Alternatives:** Not recorded.

## DL-034 — Enforce immediate invariants atomically

- **Type:** `DERIVED REQUIREMENT`
- **Status:** `REQUIRED`
- **Decision:** Storage and command boundaries must atomically prevent a second active Reservation for one Unit, overlapping Signed Lease coverage, duplicate billing, negative Invoice balances, allocation beyond available value, Deposit application before Final Settlement, and more than one active Meter per Unit and Utility Type.
- **Derived from:** `001_DOMAIN_MODEL.md` sections 85 and 100; corresponding rules in 002.
- **Affected documents/rules:** 004 Database Model, 005 API Specification, 007 Testing Strategy; `BR-UNIT-004`, `BR-UNIT-005`, `BR-RENT-011`, `BR-UTIL-005`, `BR-UTIL-018`, `BR-INV-026` through `BR-INV-029`, `BR-PAY-027`, `BR-PAY-028`, `BR-SETTLE-010`.
- **Rationale:** Not separately recorded.
- **Decision date:** Not recorded.
- **Alternatives:** Database/API transaction boundaries are deferred to 004/005.

## DL-035 — Preserve source records and use linked corrections

- **Type:** `DERIVED REQUIREMENT`
- **Status:** `REQUIRED`
- **Decision:** Implement immutable or reconstructable source history. Corrections use explicit linked Adjustment, Reversal, Allocation Reversal, Credit application/reversal, Deposit application/disposition, Refund, VOID, or post-settlement correction records rather than deletion or silent overwrite.
- **Derived from:** `001_DOMAIN_MODEL.md` sections 3-4, 31-32, 40-41, 58, 94, and 96; 002 financial-integrity rules.
- **Affected documents/rules:** 004, 005, 007, 008; `BR-PROP-002`; `BR-INV-019` through `BR-INV-025`; `BR-PAY-012` through `BR-PAY-018`; `BR-PAY-029`; `BR-CREDIT-009`, `BR-CREDIT-012`; `BR-REFUND-010` through `BR-REFUND-012`; `BR-SETTLE-012` through `BR-SETTLE-015`; `BR-AUDIT-010`.
- **Rationale:** Not separately recorded.
- **Decision date:** Not recorded.
- **Alternatives:** Not recorded.

## DL-036 — Derived balances must reconcile to authoritative facts

- **Type:** `DERIVED REQUIREMENT`
- **Status:** `REQUIRED`
- **Decision:** Unit availability, Invoice outstanding balance, separate Late-payment Charge remaining balance, Payment allocation progress, Customer Credit balance, Deposit outstanding/refundable balance, Utility consumption, Lease/Customer financial position, and Settlement results must be derived from or fully reconcilable to authoritative records and must not become competing sources of truth. The Customer Account Ledger is a read-only reconstructable view over those sources, not a second financial ledger or mutable accounting source.
- **Derived from:** `001_DOMAIN_MODEL.md`; `BR-UNIT-013`; `BR-LATE-*`; `BR-PAY-*`; `BR-CREDIT-*`; `BR-LEDGER-*`; Deposit and Settlement rules.
- **Affected documents/rules:** 003-009; applicable balance, Ledger, authorization, recovery, and audit requirements.
- **Rationale:** Not separately recorded.
- **Decision date:** Not recorded.
- **Alternatives:** Not recorded.

## DL-037 — Deterministic and idempotent scheduled processing

- **Type:** `DERIVED REQUIREMENT`
- **Status:** `REQUIRED`
- **Decision:** Scheduled Reservation expiration, recurring billing, overdue/Late-payment eligibility evaluation, and Rent Nonpayment milestone evaluation must be safely retryable. Stable business keys, uniqueness controls, Property-local business dates, and deterministic ordering must prevent duplicate effects and support recovery of missed runs. Scheduled evaluation must not cross the approved human-authorization boundaries: it may present Late-payment eligibility but cannot finalize a Late-payment Decision/Charge automatically, and Rent Nonpayment evaluation cannot automatically terminate a Lease.
- **Derived from:** Reservation end-of-date policy, duplicate-billing policy, Late-payment rules, Rent Nonpayment rules, deterministic Allocation proposal policy, and approved deployment/security boundaries.
- **Affected documents/rules:** 004, 005, 007, 008, 009; `BR-RES-*`; `BR-RENT-*`; `BR-INV-050` through `BR-INV-055`; `BR-LATE-*`; `BR-LEASE-026` through `BR-LEASE-030`; applicable `BR-PAY-*`.
- **Rationale:** Not separately recorded.
- **Decision date:** Not recorded.
- **Alternatives:** Execution mechanism is deferred to later specifications.

## DL-038 — Exact monetary arithmetic and explicit time semantics

- **Type:** `DERIVED REQUIREMENT`
- **Status:** `REQUIRED`
- **Decision:** Authoritative money calculations must use integer minor units or exact-decimal arithmetic, never binary floating point. Implement all approved half-up and upward-rounding rules exactly. Persist business dates, instants, and the Property timezone sufficiently to reproduce scheduled and financial results.
- **Derived from:** Owner currency/proration decisions; `AGENTS.md` financial rules; `BR-MONEY-001` through `BR-MONEY-013`.
- **Affected documents/rules:** 004, 005, 006, 007, 009; all monetary and scheduled-action rules.
- **Rationale:** Not separately recorded.
- **Decision date:** Not recorded.
- **Alternatives:** Storage types and precision details are deferred to 004.

## DL-039 — Audit records and authorization boundaries

- **Type:** `DERIVED REQUIREMENT`
- **Status:** `REQUIRED`
- **Decision:** Every action described as authorized requires an authenticated actor with permission for that exact action and object scope. Audit data must preserve actor, action, date/time, reason, previous and resulting state/value, affected record, and required source links. High-value capabilities remain separable: generic Invoice authority does not imply Late-payment final-Decision authority; Late-payment Charge correction/reversal is separate from the original Decision; Receipt reprint does not create another Payment/Receipt identity; active-Lease Pet Deposit Refund qualification is separate from ordinary Deposit/Refund execution; Lease-warning authority does not imply Rent Nonpayment Serious Default authority; and read-only Customer Account Ledger access does not imply mutation authority over source financial records.
- **Derived from:** `001_DOMAIN_MODEL.md`; `BR-AUDIT-*`; `BR-AUTH-*`; `008_SECURITY_MODEL.md`, especially `SEC-020`, `SEC-022`, and `SEC-070`.
- **Affected documents/rules:** 004-009 and every protected high-value workflow.
- **Rationale:** Preserve approved business authorization boundaries independently of configurable staff role bundles.
- **Decision date:** Not recorded.
- **Alternatives:** Named staff role-to-capability mapping remains an operational/security configuration choice.

---

# 10. Recorded Technical Design Direction

## DL-040 — Expected application stack

- **Type:** `TECHNICAL DESIGN DECISION`
- **Status:** `DIRECTION RECORDED`
- **Decision:** The expected stack is React, TypeScript, and Vite for the frontend; FastAPI and Python for the backend; PostgreSQL for the database; Docker Compose for development; REST for the API style; and automated frontend and backend tests. A different framework, database, or major dependency requires explicit approval.
- **Provenance:** `AGENTS.md` technology direction. This is not a business-policy decision from 001/002.
- **Affected documents/rules:** 003-009.
- **Rationale:** Not recorded.
- **Decision date:** Not recorded.
- **Alternatives:** Not recorded.

## DL-041 — Logical domain boundaries are not deployable-service boundaries

- **Type:** `TECHNICAL DESIGN DECISION`
- **Status:** `DIRECTION RECORDED`
- **Decision:** Bounded Contexts define logical business responsibilities and do not require separate deployable services. The application may remain a modular monolith while preserving those boundaries. Final application topology remains deferred to the later architecture specifications.
- **Provenance:** `001_DOMAIN_MODEL.md` sections 71-83.
- **Affected documents/rules:** 003, 004, 005, 008, 009.
- **Rationale:** Not recorded.
- **Decision date:** Not recorded.
- **Alternatives:** Not assessed in this drafting task.

---

# 11. Open Owner Decisions

No unresolved Owner **business-policy** decision remains in the approved 001–009
baseline. The entry below is retained under its stable ID because it was formerly
open and was later resolved during authoritative reconciliation.

## DL-042 — Initial Rent Invoice Due Date after move-in — superseded open question

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `SUPERSEDED`
- **Historical question:** What Due Date applies when the Initial Rent Invoice is issued after the 5th day of the billed month?
- **Resolution:** `BR-RENT-009` now establishes the Initial Rent Invoice Due Date as exactly seven calendar days after the actual Move-in Date, including when the result falls in the following month. Examples include 10 July → 17 July, 20 July → 27 July, 21 July → 28 July, and 27 July → 3 August. Recurring Rent Invoices remain due on the 5th day of the billed month, and the Lease does not define an alternative recurring Due Date.
- **Affected documents/rules:** `BR-RENT-005`, `BR-RENT-009`; corresponding PR, API, UI, testing, and billing requirements in 003–009.
- **Reconciliation note:** Earlier `OOD-BR-001`/downstream propagation represented this as unresolved. Those references were superseded when the seven-calendar-day Initial Rent Due Date became authoritative.
- **Rationale:** Current authoritative rule controls; no new decision is needed.
- **Decision date:** Not recorded.
- **Alternatives:** Earlier alternatives are historical and no longer open.

## 11.1 Open Implementation and Operational Decisions

The following nonblocking choices do not change approved business rights or
financial policy. Their source specifications preserve conservative behavior until
the Owner or authorized deployment decision-maker resolves them.

| Source identifier | Open choice | Current conservative treatment |
|---|---|---|
| `OOD-DB-001` | Customer legal-name/contact validation and duplicate matching | Preserve approved value objects; impose no unapproved identity rule. |
| `OOD-DB-002` | Refund delivery method and pre-completion lifecycle | Persist only the completed Refund event; invent no pending/failed Refund status. |
| `OOD-DB-003` | Invoice, Payment, and Refund number format/sequence | Require unique immutable values without prescribing format. |
| `OOD-DB-004` | Meter serial-number uniqueness scope | Preserve serial text without claiming global or per-type uniqueness. |
| `OOD-DB-005` | Electricity/Water measurement-unit metadata | Preserve exact numeric quantities/rates without naming an unsupported unit; block production Utility configuration and definitive fixtures until resolved. |
| `OOD-API-001` | Production authentication provider | **RESOLVED by DL-055:** application-managed local username/password; API business authorization remains credential-library-neutral. |
| `OOD-UI-001` | Brand and visual design tokens | Use accessible neutral tokens pending brand direction. |
| `OOD-UI-002`, `OOD-TEST-001` | Certified browser/device matrix | Use standards-compliant responsive behavior and generic cross-browser coverage. |
| `OOD-SEC-001` | Named staff role-to-capability mapping | Keep capabilities and role bundles configurable; grant no role-name authority. |
| `OOD-SEC-002` | Mandatory MFA scope | **RESOLVED by DL-056:** Owner and Manager required; Staff optional; stricter remote-access controls preserved. |
| `OOD-DEPLOY-001`, `OOD-TEST-002` | Production RPO/RTO | Keep backup/recovery parameters configurable; promise no unapproved objective. |
| `OOD-DEPLOY-002` | Production host, address, and certificate trust | Specify required properties without selecting infrastructure identifiers. |
| `OOD-DEPLOY-003` | Remote-access enablement/gateway | Keep remote access disabled by default. |

These implementation/operational choices do not reopen the superseded Initial
Rent Due Date question in `DL-042` and do not authorize new business policy.

---

# 12. Technical Decisions from Specifications 003-009

## DL-043 — Exhaustive one-to-one Product Requirement traceability

- **Type:** `DERIVED REQUIREMENT`
- **Status:** `REQUIRED`
- **Decision:** Every authoritative `BR-*` rule has one same-suffix detailed `PR-*` requirement preserving its normative body. Capabilities, workflows, and quality requirements supplement rather than replace that bijection. The Decision Log must not hard-code a stale rule count when authoritative rule families are extended through controlled reconciliation.
- **Provenance:** `003_PRODUCT_REQUIREMENTS.md` authority/traceability model and the approved 001/002 rule set.
- **Affected documents/rules:** 003-009; every `BR-*` and detailed same-suffix `PR-*`.
- **Rationale:** Prevent loss of conditions, exceptions, calculations, and prohibitions during downstream translation.
- **Decision date:** Not recorded.
- **Alternatives:** Not recorded.

## DL-044 — PostgreSQL relational integrity and append-only financial events

- **Type:** `TECHNICAL DESIGN DECISION`
- **Status:** `DIRECTION RECORDED`
- **Decision:** PostgreSQL stores normalized aggregate data with declarative constraints where possible and transactional or trigger enforcement for cross-row invariants. Financial corrections, applications, dispositions, Reversals, Refunds, and audit facts use linked append-only events rather than destructive mutation.
- **Provenance:** `004_DATABASE_MODEL.md` sections 2-18.
- **Affected documents/rules:** 004, 005, 007-009; financial and audit rules.
- **Rationale:** Preserve concurrency-safe integrity and historical reconstruction.
- **Decision date:** Not recorded.
- **Alternatives:** Not recorded.

## DL-045 — Explicit REST command resources and idempotency

- **Type:** `TECHNICAL DESIGN DECISION`
- **Status:** `DIRECTION RECORDED`
- **Decision:** The `/api/v1` REST API separates queries from explicit business-action endpoints, rejects generic status mutation for controlled lifecycles, and requires idempotency plus transactional revalidation for retryable financial and scheduled commands.
- **Provenance:** `005_API_SPECIFICATION.md` sections 3-26.
- **Affected documents/rules:** 005-009; lifecycle, financial, authorization, and audit rules.
- **Rationale:** Keep all clients on one authoritative command and validation boundary.
- **Decision date:** Not recorded.
- **Alternatives:** Not recorded.

## DL-046 — Staff-facing workflow UI with server-owned calculations

- **Type:** `TECHNICAL DESIGN DECISION`
- **Status:** `DIRECTION RECORDED`
- **Decision:** The React UI is an authenticated staff workspace organized around approved lifecycle tasks. It displays authoritative server results, requires explicit confirmation for consequential actions, and does not duplicate financial calculations or use hidden controls as authorization.
- **Provenance:** `006_UI_SPECIFICATION.md` sections 2-24.
- **Affected documents/rules:** 006-008; all user-initiated workflows.
- **Rationale:** Provide simple workflows without creating a competing policy engine.
- **Decision date:** Not recorded.
- **Alternatives:** Not recorded.

## DL-047 — Layered, traceable verification gates

- **Type:** `TECHNICAL DESIGN DECISION`
- **Status:** `DIRECTION RECORDED`
- **Decision:** Verification spans domain/service, database, API, UI, security, migration, and deployment layers, with negative, boundary, concurrency, authorization, financial-reconciliation, rounding, and end-to-end tests traced to stable identifiers.
- **Provenance:** `007_TESTING_STRATEGY.md` sections 2-23.
- **Affected documents/rules:** 003-009; all `BR-*`.
- **Rationale:** A passing happy path alone cannot prove financial or lifecycle integrity.
- **Decision date:** Not recorded.
- **Alternatives:** Not recorded.

## DL-048 — Capability-based deny-by-default security

- **Type:** `TECHNICAL DESIGN DECISION`
- **Status:** `DIRECTION RECORDED`
- **Decision:** Authentication uses unique actor identities; server-side authorization is deny-by-default and capability-based; configurable role bundles do not themselves create business authority. Financial actions, audit access, secrets, Customer data, database privileges, and backups receive defense-in-depth controls. High-value workflow boundaries remain independently enforceable for Late-payment Decisions/Charge corrections, Receipt reprints, active-Lease Pet Deposit Refund qualification, Rent Nonpayment case/events, and read-only Customer Account Ledger access.
- **Provenance:** `008_SECURITY_MODEL.md` sections 2-17, including `SEC-070`.
- **Affected documents/rules:** 005-009; `BR-AUTH-001` through `BR-AUTH-009`; `BR-AUDIT-001` through `BR-AUDIT-010`.
- **Rationale:** Enforce least privilege without inventing the Owner's organizational role map.
- **Decision date:** Not recorded.
- **Alternatives:** Not recorded.

## DL-049 — Local-first modular deployment topology

- **Type:** `TECHNICAL DESIGN DECISION`
- **Status:** `DIRECTION RECORDED`
- **Decision:** The production-oriented topology uses a TLS reverse proxy and static React build, FastAPI API, separate scheduled worker, and one PostgreSQL database, packaged for local-network operation. Durable job state, safe migrations, encrypted verified backups, monitored recovery, and no mandatory new cloud dependency are required. Deployment recovery and monitoring preserve the later Late-payment, Receipt/reprint, Customer Account Ledger, active-Lease Pet Deposit Refund, and Rent Nonpayment authorization/history boundaries.
- **Provenance:** `009_DEPLOYMENT_ARCHITECTURE.md` sections 2-18.
- **Affected documents/rules:** 004-009; scheduled, financial-history, security, monitoring, authorization, and recovery requirements.
- **Rationale:** Support maintainable single-site operation and reliable recovery without premature distributed services or weakening high-value workflow boundaries.
- **Decision date:** Not recorded.
- **Alternatives:** Not recorded.

## DL-050 — Late-payment Decision and separate Charge

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `ESTABLISHED`
- **Decision:** After an applicable issued Invoice passes its Due Date with a positive remaining overdue balance, the system may calculate and present a default Late-payment proposal equal to 10% of that remaining overdue source-Invoice balance. Eligibility does not automatically post a Charge. Authorized management makes exactly one final Decision for that source Invoice: confirm the default, approve a positive reduced amount below the default, or waive it to zero. A positive final Decision creates exactly one separate Late-payment Charge obligation; it does not change the source Invoice principal, lines, balance, or status and cannot itself generate another Late-payment Charge. Later correction/reversal is explicit, authorized, linked, and append-only.
- **Provenance:** Embodied authoritatively in 001/002 and propagated through approved 003–009.
- **Affected documents/rules:** `BR-INV-051` through `BR-INV-055`; `BR-LATE-*`; applicable Payment, Credit, audit, authorization, API, UI, testing, security, and deployment requirements.
- **Rationale:** Preserve the late-payment policy as a separately authorized non-compounding obligation rather than rewriting the source Invoice.
- **Decision date:** Not recorded.
- **Alternatives:** No automatic or recurring/compounding Charge is approved.

## DL-051 — Receipt identity and reprint

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `ESTABLISHED`
- **Decision:** A confirmed Payment normally produces one numbered immutable Receipt acknowledging money received. Receipt does not itself allocate value or create another financial obligation. A Receipt reprint preserves the same Receipt identity and Receipt Number and records a separate auditable reprint event; it must never create a second Payment, Receipt identity, or money-received event. Refund remains a separate outbound financial event.
- **Provenance:** Embodied authoritatively in 001/002 and propagated through approved 003–009.
- **Affected documents/rules:** `BR-PAY-018`; `BR-RECEIPT-*`; applicable API, UI, testing, security, recovery, and audit requirements.
- **Rationale:** Customer-facing proof of receipt must remain reconstructable without duplicating financial value.
- **Decision date:** Not recorded.
- **Alternatives:** No separate Refund-receipt document is created by this decision.

## DL-052 — Unified Customer Account Ledger

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `ESTABLISHED`
- **Decision:** Each Customer has one unified chronological Customer Account Ledger view showing amounts charged, Payments and applications, Customer Credit, Refunds, Deposits as separately identifiable liabilities, Late-payment Charges, outstanding composition, total current amount owed, and available Customer Credit. The Ledger is reconstructed from authoritative underlying financial records and is read-only; it is not a General Ledger, Chart of Accounts, journal-entry system, vendor Accounts Payable system, or competing financial source of truth.
- **Provenance:** Embodied authoritatively in 001/002 and propagated through approved 003–009.
- **Affected documents/rules:** `BR-LEDGER-*`; applicable `BR-PAY-*`, `BR-CREDIT-*`, `BR-REFUND-*`, `BR-DEP-*`, `BR-LATE-*`; API-093 and downstream UI/testing/security/deployment requirements.
- **Rationale:** Provide one understandable Customer financial view while retaining authoritative specialized records underneath.
- **Decision date:** Not recorded.
- **Alternatives:** Formal debit/credit bookkeeping and general accounting are outside current scope.

## DL-053 — Active-Lease Pet Deposit Refund exception

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `ESTABLISHED`
- **Decision:** Security Deposit is not refunded while a Lease remains SIGNED. If an approved pet permanently leaves during an active Lease, that departure is recorded and applicable pet-caused damage or extraordinary/deep-cleaning obligations are determined and resolved. Any remaining refundable Pet Deposit may then be returned through an explicit Refund without terminating the Lease or creating Final Settlement. Qualification/review for this exception is separate from Refund execution and preserves complete source and authorization history.
- **Provenance:** Embodied authoritatively in 001/002 and propagated through approved 003–009.
- **Affected documents/rules:** `BR-DEP-011` through `BR-DEP-014`; `BR-REFUND-013`; applicable API-094/API-065, UI, testing, security, audit, and recovery requirements.
- **Rationale:** Pet Deposit remains tied to the pet-related exposure it secures and need not remain held after that exposure permanently ends and valid obligations are resolved.
- **Decision date:** Not recorded.
- **Alternatives:** This exception does not create an active-Lease Security Deposit Refund right.

## DL-054 — Rent Nonpayment milestones remain separate from termination

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `ESTABLISHED`
- **Decision:** Rent Nonpayment uses the remaining Rent obligation—not an unpaid recurring-Service-only balance. Calendar days overdue begin after the Rent Due Date. At 20 days overdue with positive Rent remaining, the system alerts authorized staff and supports/records the formal Nonpayment Warning Notice. At 30 days overdue with positive Rent remaining, it records the Serious Nonpayment Default condition. Cure before the 30-day threshold stops that current trigger while preserving history. Payment after Serious Default does not erase history or automatically decide an already initiated termination process. Neither the 20-day Warning nor 30-day Serious Default automatically terminates the Lease, ends Occupancy, changes Unit status, creates Move-out, or creates Final Settlement; termination remains a separately authorized signed-Lease action and the general warning requirements are not silently bypassed.
- **Provenance:** Embodied authoritatively in 001/002 and propagated through approved 003–009.
- **Affected documents/rules:** `BR-LEASE-024` through `BR-LEASE-030`; `BR-PAY-036` through `BR-PAY-039`; applicable API-095, UI, testing, security, scheduling, monitoring, and audit requirements.
- **Rationale:** Preserve exact Rent-default evidence while preventing an automated financial milestone from becoming an unauthorized tenancy termination.
- **Decision date:** Not recorded.
- **Alternatives:** No automatic termination is approved.

## DL-055 — Local username/password production authentication

- **Type:** `OWNER SECURITY DECISION`
- **Status:** `APPROVED`
- **Decision:** Production authenticates every human through a unique application-managed local username and password. Shared accounts, security questions, plaintext/reversibly encrypted passwords, and dependence on Google, Microsoft, Auth0, or another external identity provider for normal operation are prohibited. Passwords use secure salted adaptive hashing; login/recovery retain guessing, rate-limit, enumeration, disablement, revocation, and audit controls. Credential mechanics do not replace capability-based deny-by-default server authorization.
- **Provenance:** Final Owner Authentication Decision `AUTH-01`, approved 2026-08-17.
- **Affected documents/rules:** 003-009; `PR-CAP-009`, `DB-AUTH-001`–`DB-AUTH-005`, `API-008`, `API-096`–`API-100`, `SEC-009`–`SEC-012`, `DEPLOY-068`; resolves `OOD-API-001`.
- **Rationale:** Preserve local-first operation, unique audit attribution, and independence from external identity availability.
- **Decision date:** 2026-08-17.
- **Alternatives:** External-provider normal authentication is not approved.

## DL-056 — Production MFA policy by account class

- **Type:** `OWNER SECURITY DECISION`
- **Status:** `APPROVED`
- **Decision:** Standards-based MFA is required for Owner and Manager and optional for Staff. A new Owner or Manager receives no normal privileged access until enrollment is complete. Staff without MFA remains limited by its capabilities; Staff with MFA enabled must complete it. SMS MFA/recovery is not approved. Stricter remote-access controls remain authoritative, and role labels never replace capability checks.
- **Provenance:** Final Owner Authentication Decision `AUTH-02`, approved 2026-08-17.
- **Affected documents/rules:** 003-009; `PR-CAP-009`, `API-096`, `UI-110`, `TEST-128`, `SEC-013`, `DEPLOY-068`; resolves `OOD-SEC-002`.
- **Rationale:** Require stronger authentication for privileged administration without inventing business authority or weakening remote access.
- **Decision date:** 2026-08-17.
- **Alternatives:** Mandatory Staff MFA and SMS MFA/recovery are not approved.

## DL-057 — Production browser-session lifetime

- **Type:** `OWNER SECURITY DECISION`
- **Status:** `APPROVED`
- **Decision:** Production browser sessions expire after 30 minutes of inactivity and after an absolute 24 hours regardless of activity. Existing unpredictable/time-bounded token, TLS, cookie, CSRF, revocation, and high-risk reauthentication controls remain required. Password/MFA recovery, account disablement, and material privilege reduction revoke applicable sessions promptly.
- **Provenance:** Final Owner Authentication Decision `AUTH-03`, approved 2026-08-17.
- **Affected documents/rules:** 003-009; `DB-AUTH-004`, `API-097`, `UI-111`, `TEST-131`–`TEST-132`, `SEC-015`–`SEC-018`, `DEPLOY-069`.
- **Rationale:** Replace deployment TBDs with bounded, testable production session policy.
- **Decision date:** 2026-08-17.
- **Alternatives:** Configurable weaker production values are not approved.

## DL-058 — Recovery codes and controlled server-side recovery

- **Type:** `OWNER SECURITY DECISION`
- **Status:** `APPROVED`
- **Decision:** Account/MFA recovery supports securely generated single-use recovery codes and controlled auditable server-side administrative recovery. Owner may recover Manager and Staff accounts; Staff cannot recover Owner or Manager; Manager recovery of Staff is not granted. Owner recovery uses Owner recovery codes or a deliberate emergency server procedure, never an ordinary unauthenticated web reset. Recovery preserves rate limiting, enumeration resistance, authorization, session revocation where appropriate, protected verifier storage, and immutable secret-free audit evidence.
- **Provenance:** Final Owner Authentication Decision `AUTH-04`, approved 2026-08-17.
- **Affected documents/rules:** 003-009; `DB-AUTH-003`–`DB-AUTH-005`, `API-098`–`API-099`, `UI-112`, `TEST-129`–`TEST-130`, `SEC-071`–`SEC-072`, `SEC-075`, `DEPLOY-071`–`DEPLOY-072`.
- **Rationale:** Provide recoverability without security questions, reusable codes, authorization bypass, or a persistent Owner-reset backdoor.
- **Decision date:** 2026-08-17.
- **Alternatives:** Security questions, SMS recovery, Staff recovery of privileged accounts, and invented Manager recovery authority are not approved.

## DL-059 — Protected initial Owner command-line bootstrap

- **Type:** `OWNER SECURITY DECISION`
- **Status:** `APPROVED`
- **Decision:** The first Owner is created only through a protected production-server command-line bootstrap while no account or bootstrap closure exists. It validates the supplied password as 15–128 Unicode code points, NFC-normalizes it, revalidates the normalized result as nonempty and 15–128 code points, applies the local compromised/common/expected/project-context blocklist to the complete normalized value without external disclosure, and hashes and verifies that complete value without truncation. It permits spaces, paste, and password managers and uses no composition or periodic-rotation rule. It generates exactly 10 random independently single-use recovery codes, presents them exactly once only on the controlling TTY, and persists only protected verifiers. One ceremony-wide absolute monotonic deadline starts before TOTP confirmation and covers TOTP input, recovery presentation and complete persistence writes, acknowledgement input, and commit preparation; writes, partial input, retries, and trickled input never reset or extend it. Presentation, acknowledgement, or deadline failure rolls back completely. A dedicated least-privilege one-time database identity atomically persists initial Owner identity, password verifier, confirmed protected TOTP enrollment, recovery verifiers, immutable audit, and permanent closure. The TOTP protection key enters only through an already-open root-controlled descriptor or equivalent protected secret file, never arguments, logs, repository/compact state, or ordinary environment variables. Successful closure permanently revokes bootstrap mutation capability; repeats fail closed and audit without secrets. Password, MFA, and recovery secrets never enter arguments, redirectable stdout, logs, durable state, audit, or Git. Later accounts use normal authorized management, and recovery cannot reactivate bootstrap.
- **Provenance:** Final Owner Authentication Decision `AUTH-05`, approved 2026-08-17.
- **Affected documents/rules:** 003-009; `DB-AUTH-005`, `API-100`, `UI-113`, `TEST-133`–`TEST-134`, `SEC-073`–`SEC-075`, `DEPLOY-070`–`DEPLOY-072`.
- **Rationale:** Establish the trust root without exposing a public first-owner route, leaking secrets, or retaining a bootstrap backdoor.
- **Decision date:** 2026-08-17.
- **Alternatives:** Public web bootstrap and reusable bootstrap credentials are prohibited.

---

## DL-060 — USD accounting and USD-only Refunds

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `APPROVED`
- **Decision (literal owner clarification):** USD is the main accounting currency. Customers may pay in KHR, but KHR is only a payment-conversion option. Financial transactions are recorded in USD. All refunds must be paid and recorded in USD. Do not implement KHR refunds.
- **Supersession:** The owner explicitly rejected, not approved, the proposed V1-051 KHR partial-refund rounding policy. This decision supersedes the conflicting KHR-refund clauses of DL-031 and downstream requirements. The original decision entry and rejected proposal remain historical evidence.
- **History:** Preserve existing transaction evidence and original KHR amounts or conversion-rate metadata required for audit; never rewrite historical records. Payment conversion, immutable source facts and USD Credit accounting remain intact.
- **Derived implementation consequences:** Refunds from eligible KHR-origin Payment excess and Credit use recorded available USD cents, not converted KHR remainders or a Refund-date rate. Partial verified returns of USD Refunds restore their exact positive USD cents, bounded by the original/net Refund; reversals have exact opposite effects and remain source-budget constrained. No KHR partial-return rounding, zero-cent correction, collection right, new Refund status or rewritten historical fact is introduced.
- **Provenance:** Explicit owner message in the existing Codex takeover task on 2026-09-06, titled “Owner financial-policy clarification for V1-051”. Earlier generic confirmations are not approval of the rejected proposal.
- **Affected documents/rules:** 001-007; BR-MONEY-001/002, BR-CREDIT-010/011, BR-REFUND-003/005/006/008/010/011/012, corresponding product requirements, DB-PAY-002/003, DB-REFUND-001/002, API-065/066, UI-071/072, TEST-074; V1-051 scope and native Codex follow-up.
- **Decision date:** 2026-09-06.
- **Continuation:** Resume the existing direct Codex takeover from its latest verified stage, complete V1-051 then V1-052 and V1-053 under unchanged models, exact-SHA gates, independent review, normal publication and closure requirements. Keep OpenClaw disabled. At V1-053 closure pause the Codex follow-up and do not activate V1-054. Existing production and safety exclusions remain unchanged.
- **Alternatives:** KHR Refunds and the proposed proportional KHR partial-refund/remainder policy are explicitly not approved.

---

## DL-061 — Deposit financial observation revision

- **Type:** `TECHNICAL DESIGN DECISION`
- **Status:** `ACCEPTED at dc230345e79e82dd5b56fcf5ffed1027d2a01d37; exact gates and independent zero-finding review preserved externally`
- **Decision:** Preserve existing Deposit metadata versions and original command results. Derive a separate `disposition_state_version` from that metadata version plus immutable required-adjustment and balance-event counts. Count originals and corrections separately, so a net-zero financial history still changes the observation. Keep the existing mutable serialization guard separate.
- **Authority:** Routine implementation authority for V1-055 under the owner's standing V1-054 through V1-060 authorization. This technical entry creates no business or security policy and does not activate version V1-061.
- **Derived from:** DB-DEP-001 through DB-DEP-004, DB-DEP-007/008, DB-TXN-003/004, API-042 and SEC-028/029: preserve history and revalidate financial state in the posting transaction.
- **Boundary:** The protected read returns the revision from the same snapshot as balances. Expected-version command enforcement and exact governing-rule/source validation remain separate pending work. Future Deposit applications/reversals must participate before acceptance. No Refund, forfeiture or termination right is added.
- **Rationale:** Metadata version alone does not follow financial events. A net-balance token misses events followed by reversals. The MVCC guard can change for coordination without a new financial event; it remains the concurrency mechanism, not financial truth.
- **Decision date:** 2026-09-14.

---

## DL-062 — Exact-source Deposit disposition command context

- **Type:** `TECHNICAL DESIGN DECISION`
- **Status:** `ACCEPTED at 5ad5d9744f4e301773e387bb065ae10d9ac403b6; all22 gates and independent zero-finding full-stage review preserved externally`
- **Decision:** Bind a fresh disposition to an exact approved original termination event, existing supported rule and expected financial revision. Preserve immutable context and command intent, require it at the shared fresh boundary/storage, and keep absent-context historical replay unchanged.
- **Authority:** Existing V1-055 implementation authorization; BR-DEP-022/023/024, BR-LEASE-021/024/025, DB-TXN-003/004, API-042 and SEC-028/029. No new forfeiture circumstance, termination right or Pet consequence is introduced.
- **Source:** BR-DEP-023 uses original voluntary-early Security authority. BR-DEP-022 requires the original explicit rule and signed Customer-violation decision with real general warning sources; generic violation or free text is insufficient.
- **Concurrency:** Reuse the accepted financial revision and existing Deposit MVCC guard. Required-amount adjustments also participate; a root row lock alone cannot validate an observation retained by a repeatable-read transaction.
- **History:** Forward58 adds append-only context with atomic command/source/audit linkage. Original snapshot shape, digests, successful results and all historic rows remain. Exact replay precedes current financial observation checks; new contextual retries also compare every original field.
- **Boundary:** No HTTP/frontend, Invoice reconciliation, physical workflow or Settlement completion. Future applications/reversals must extend financial observation and balance invalidation before acceptance. This technical ID does not activate V1-062 or expand the V1-060 authorization boundary.
- **Decision date:** 2026-09-14.

---

## DL-063 — Original Invoice coverage and current termination observation

- **Type:** `TECHNICAL DESIGN DECISION`
- **Status:** `IMPLEMENTED; VERIFICATION AND INDEPENDENT ACCEPTANCE PENDING`
- **Decision:** Show original Invoice/component coverage alongside separately derived current Adjustment, Payment and Credit positions in a bounded scoped read-only observation. Classify original Rent coverage relative to a verified final calendar month without proposing a financial amount or authorizing a correction.
- **Authority:** Standing V1-055 implementation authority; BR-RENT-023 through BR-RENT-026, BR-INV-024/025, DB-INV-006, DB-TXN-003/004 and UI-076. This changes no financial or security policy and does not activate version V1-063.
- **Source:** Bind to the original approved termination command and any present signed context; preserve genuine legacy evidence. Non-Rent obligations and VOID history remain separate. An original period can remain visible after a valid financial correction.
- **Financial boundary:** Current balances reuse the established append-only financial functions. Invoice metadata versions are not a complete financial observation token. Controlled correction commands must revalidate current source, amounts and every connected financial dependency; this read grants no posting authority.
- **Pagination:** Each bounded UUID-keyset page is a separate repeatable-read observation; no aggregate completion or cross-page snapshot guarantee. Nested component overflow is explicit. Full financial-dependency assessment and financial completion remain false.
- **Acceptance boundary:** Forward59 is additive. Required regression, full applicable gates and independent exact-SHA complete-stage review precede local acceptance. Controlled Invoice correction, physical/staff workflows and full V1-055 integrated acceptance remain pending; no publication or V1-056 activation.
- **Review correction IR-1/2/3:** Initial `a244b79` full review rejected three read-contract findings. Preserve each actual signed Invoice Customer separately from `primary_tenant_id`; require compatible original issued components; reject line-provable PAID/UNPAID contradictions while retaining valid mixed/zero obligations. The unpublished revision59 successor changes no accepted migration or financial writer. Original candidate, report, failed checks and all correction limits remain preserved; correction regressions, expanded focused review and fresh complete-stage review remain required.
- **Decision date:** 2026-09-14.

## DL-064 — Initial Rent, Rent nonpayment, one-time charges and Adjustments

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `APPROVED; CANONICAL AMENDMENT APPLIED; IMPLEMENTATION PENDING`
- **Rent nonpayment:** The process under BR-LEASE-026 to 030 applies only to recurring monthly Rent, with day one the 1st of the billed month. Recurring Rent is generated on the 25th and due on the 5th, unchanged.
- **Initial Rent:** Calculated from the Lease Start Date, not the actual move-in (Lease Start 20 September, arrival 25 September: $300 × 11/30 = $110.00). It references the signed Lease, not an Occupancy, and may be issued before the Lease Start Date. The proposed Due Date is the Lease Start Date plus five calendar days; an authorized user may set another with a mandatory reason, actor and timestamp; it is fixed once issued. It opens no Rent nonpayment case and has no late-payment charge. Management is alerted the day after it becomes overdue; any termination is manual. Move-in is recorded when it happens, paid or not.
- **Unpaid-Initial termination:** Always "terminate", never "cancel". The governing ground is a signed-Lease clause (under legal review) in the standard Lease for all Customers giving a termination right when either the Security Deposit or the Initial Rent is unpaid within five days after the Lease Start Date; BR-LEASE-024 does not apply; the termination records the clause reference. Never moved in: Security Deposit forfeited; Invoice VOIDed with reason if nothing was paid, otherwise the Property keeps the paid amount and a linked credit Adjustment removes the unpaid remainder; no Utility charge; Unit returns to VACANT. Moved in: Invoice kept, a prorated credit Adjustment removes the days after termination, Utility and Damage are charged, move-out applies.
- **One-time charges and final Utility:** Damage and Miscellaneous charges are created manually; one-time charges and the final Utility Invoice propose the issue date plus a Property-configured number of days, seven by default, with an authorized override. The final Utility Invoice is created off-cycle at move-out from the final Readings and must not duplicate a monthly-run period. Damage amounts are entered per finding by a capability holder with reason and evidence reference; evidence is text only.
- **Utility baseline:** Before the Lease Start Date staff record a validated Reading with evidence and turn Electricity and Water off; that Reading is the Customer's starting boundary, and switching on again requires a new baseline. Staff record every Meter monthly, including VACANT Units. The Property bears consumption between tenants and when a tenant never moved in.
- **Reservation and Unit at signing:** A Reservation becomes COMPLETED and the Unit OCCUPIED when the Lease is SIGNED, before physical move-in; a COMPLETED Reservation cannot expire; the holding deposit continues as the Security Deposit. Physical move-in only begins the Occupancy. This changes BR-RES-003, BR-RES-013, BR-UNIT-007, BR-LEASE-015, BR-LEASE-016 and BR-DEP-005 for new signings; historical records are unchanged.
- **Adjustments:** An Invoice has one Due Date and its lines have none. A debit Adjustment is blocked on a fully paid line and allowed again after a reversal. A credit Adjustment is allowed on any issued line; over-applied Payment value becomes Customer Credit from that Payment. The Invoice lock orders Adjustments against the final late-payment decision; a debit after the decision is allowed but not counted; a credit never changes it. `invoices.due_date` may be null only while DRAFT.
- **Supersedes:** DL-042's seven-day resolution for new Initial Rent Invoices; the 2026-09-15 within-line due-date allocation decision.
- **Unchanged:** BR-RENT-007, BR-LEASE-030, BR-INV-052–055, BR-LATE-001–003, the Lease Start Date.
- **Affected:** BR-RENT-005/009/029, BR-LEASE-005/025/026–029, BR-SVC-011/012, BR-INV-018/044/046/049/051/054, BR-UNIT-010, BR-UTIL-018/021/022, BR-MOVEOUT-005/006, OOD-BR-001; matching PR, DB-INV-001/003, DB-LEASE-008/009, DB-MOVEOUT-002, API-052/069/095, UI-051/076/078/108, TEST-043/057/078/123/127.
- **Transition:** Recorded Invoices, cases and events are never rewritten; new rules apply to new records.
- **Implementation (one-time charges, migration `20261002_65`):** Owner answers of 2026-10-01: service only, no new HTTP route (a creation route may join API-052 in the HTTP and UI slice); Damage requires the new capability `damage_charges.bill`, Miscellaneous reuses `invoices.create`; an authorized Due Date is recorded at issue with a mandatory reason, actor and timestamp and is fixed once issued. `properties.one_time_charge_due_days` (default 7, 1 to 90) follows the versioned Property update pattern with `property.manage`; the existing pattern had no audit event, so this setter adds one. Historical governing-source obligations keep their recorded Due Dates. A finding of a superseded inspection is not billable. Inspection never creates a charge and Pet Deposit is never forfeited automatically.
- **Implementation (debit block, migration `20261003_66`):** A debit Adjustment is rejected while its line balance is zero, whether paid by Payment or by applied Customer Credit; a Payment or Credit reversal reopens the line. A late-fee decision counts an Adjustment only when the Adjustment came first under the Invoice lock; a later debit is accepted and not counted.
- **Implementation (credit excess, migration `20261003_67`):** Owner answers of 2026-10-03: the excess is Customer Credit of the Invoice Customer even when a third party paid (Adjustment-sourced Credit only); option (a) overrides the open-Invoice rule for Adjustment excess, so the released value becomes Customer Credit at once; the newest Payment allocation or Credit application is released first. Reversal and re-post carry the reason "Invoice adjustment credit excess" and rewrite no history. Open for the V1-056 review: Refunds of such Credit when a third party paid.
- **Traceability note (credit excess):** BR-INV-044 replaced the older behavior "a credit beyond the already applied value is rejected". The frozen manifest entry for `test_allocation_adjustments_cannot_credit_already_applied_value` was intentionally left unchanged; that test now asserts only what remains true (a credit beyond the line's adjusted obligation is rejected), and the new manifest entries for `test_credit_adjustment_excess_migration.py` describe the current behavior.
- **Implementation (Rent nonpayment and Initial Rent follow-up, migration `20261004_68`):** Owner answers of 2026-10-04: an open recurring Rent case uses the count from the 1st for any milestone not yet recorded; recorded cases and events never change. No production data exists, so this affects only test data. An earlier case on Initial Rent stays readable and accepts only CURE and AUTHORIZED_FOLLOW_UP. Every Initial Rent Invoice without a final decision is excluded from late fees (`INITIAL_RENT_NO_LATE_PAYMENT`); existing decisions and Charges are untouched. The unpaid Initial Rent alert is a computed read at service level until the HTTP and UI slice. Nothing is automatic at any milestone.
- **Superseded test expectations (DL-064):** `test_ledger_canonical_rent_service_charge_example_and_original_source_preservation` no longer finalizes a late charge on the canonical Initial Rent Invoice; `test_mixed_service_balance_cannot_trigger_rent_default_after_rent_cure` and `test_cure_after_day_twenty_warning_stops_day_thirty_trigger_and_preserves_notice` now assert that a case cannot be opened on Initial Rent. Their frozen manifest entries were intentionally left unchanged; the mixed and cure behaviors on recurring Rent are covered by the new manifest entries for `test_rent_nonpayment_recurring_only_migration.py`.
- **Superseded whole-row comparison (DL-064):** `test_upgrade_preserves_legacy_notice_and_allows_append_only_correction` compared whole Invoice rows before and after the upgrade; since migration 64 an upgrade adds the three Due Date override columns as null, so its `business_snapshot` helper now leaves `due_date_override_reason`, `due_date_set_by` and `due_date_set_at` out of the Invoice comparison. The test name and its frozen manifest entry are unchanged.
- **Decision date:** 2026-09-30.

## DL-065 — Voluntary leaving and cleaning charge — pending V1-056

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `RECORDED; NOT IMPLEMENTED; PENDING V1-056`
- **Decision:** Voluntary leaving before the month's Rent Due Date (the 5th): no Rent for that month; the Customer pays final Utilities, Damage and cleaning; the Security Deposit is not refunded. Voluntary leaving after the Due Date: the Customer pays the unpaid Invoice, final Utilities, Damage and cleaning; the Security Deposit is not refunded. There is no discount rule; only an authorized user may reduce an unpaid Invoice after negotiation, by a linked credit Adjustment with a mandatory reason. Each Unit has a configured cleaning rate, charged at move-out.
- **Boundary:** BR-LEASE-021 (voluntary early termination) is unchanged in V1-055. Termination for an unpaid Initial Rent Invoice after move-in is not voluntary and uses proration through the termination date under DL-064.
- **Decision date:** 2026-10-01.

## DL-066 — Walk-in Leases and deposit timing without a move-in payment gate

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `APPROVED; CANONICAL AMENDMENT APPLIED; IMPLEMENTATION PENDING`
- **Walk-in Lease:** A Lease may be signed with no Reservation. If a Reservation exists, it becomes COMPLETED at signing; if none exists, nothing is completed and the Unit still becomes OCCUPIED.
- **Deposit timing:** The Security Deposit balance after the holding deposit and the Initial Rent are due within five calendar days after the Lease Start Date. A Pet Deposit for a pet kept from the beginning of occupancy has the same five-day timing. Move-in is always recorded and has no payment gate. If the Security Deposit balance or the Initial Rent is unpaid after that period, the owner may terminate under the standard Lease clause (BR-LEASE-025).
- **Affected:** BR-RES-001, BR-DEP-006, BR-DEP-010, BR-LEASE-015, BR-LEASE-016; matching PR, DB-RES-001, TEST-034.
- **Implementation:** The Reservation, Unit and move-in code changes remain in their later slice; historical records are unchanged.
- **Implementation (migration `20261005_69`):** Signing through `app.sign_lease_with_reservation` completes an ACTIVE Reservation for the same Unit and Primary Tenant, links its holding deposit as the Security Deposit and makes the Unit OCCUPIED; a walk-in signing occupies a VACANT, CLEANING or UNDER_MAINTENANCE Unit, and a renewal keeps an OCCUPIED Unit. Physical move-in for such Leases only begins Occupancy and has no payment gate. Leases signed before this migration keep the Reservation move-in path. The older `app.sign_lease` stays granted for compatibility; the service always uses the new function.
- **Implementation (unpaid Initial termination, migration `20261005_70`):** Owner answers of 2026-10-05: the ground is verified at termination time and the clause reference is recorded; CLEANING instead of VACANT needs a reason and the Unit management capability; the cleaning charge stays out (DL-065 pending for V1-056). The Pet Deposit is not touched by this termination; its refund or forfeiture is for the V1-056 review. Only Leases signed through the new signing path are resolved by the never-moved-in command.
- **Superseded test expectation (DL-066):** `test_commands_are_idempotent_versioned_audited_and_preserve_signer_rules` now expects the Unit to stay OCCUPIED after terminating a moved-in Lease, because signing occupies the Unit and termination alone does not release an open Occupancy. Its frozen manifest entry is unchanged.
- **Decision date:** 2026-10-01.

---

# 13. Governance

1. Decision IDs are stable and must not be reused.
2. A correction preserves the old entry and marks it superseded; it does not silently rewrite historical meaning.
3. An `OWNER BUSINESS DECISION` may be changed only through explicit Owner approval.
4. A `DERIVED REQUIREMENT` must identify the authoritative rules from which it follows and must not add policy.
5. A `TECHNICAL DESIGN DECISION` must not override 001 or 002.
6. An `OPEN OWNER DECISION` must remain open until a literal approval is recorded.
7. A source conflict must be recorded and reconciled through controlled edits; this log must not invent the controlling answer.
8. Updates to 001 or 002 that materially change a logged decision require corresponding updates here and in affected downstream specifications.

---


### V1-055 Invoice correction command boundary checkpoint

BR-RENT-023–026 and PR-INV-044–048 continue to use explicit existing linked
Adjustments and exceptional VOID. Original Invoice values, calculation components,
Service obligations and signed Lease evidence remain unchanged. Direct Adjustment
commands now require actual integer USD cents, matching the strict HTTP money
boundary; no floating-point, boolean or other coercion enters a command digest.
Valid integer limits, SQL writers, authorization, replay and schema are unchanged.

Connected integration coverage includes a genuine initial Invoice spanning the
processed final month and a later month, an approved linked credit correction,
concurrent exact retries, active Payment/Credit reversal prerequisites, source funds
remaining available, and rejected commands preserving all application-table history.
An Invoice with zero outstanding after an Adjustment is not thereby VOID or a
financially closed tenancy. These are tests of explicit approved processes, not
automatic proposed amounts or new permission/termination rules.

This bounded checkpoint does not accept debit Adjustment due-date behavior.
PR-INV-049 requires a governing-source due date; the current generic Adjustment
input has no explicit due-date field. Its connected persistence and consumers
remain a required separate verification/remediation before V1-055 acceptance.
Physical move-out, inspection/readings, HTTP/staff and final integrated acceptance
also remain incomplete; no V1-055 publication or V1-056 activation is permitted.


### V1-055 operational inspection evidence checkpoint

DB-MOVEOUT-001/002, BR-MOVEOUT-006/011/012 and DL-017 are implemented as
append-preserved operational inspection and typed finding evidence. Recording
requires the exact scoped inspection capability and current signed-Lease source
evidence. An inspection correction keeps the original rows and audit history;
original idempotent command responses remain stable. It creates no charge, changes
no actual occupancy date and makes no financial-completion claim.

The accepted Invoice correction boundary at79314cc remains preserved through its
focused and fresh complete-stage zero-finding reviews and22 recorded gates. ICB-1
resolved at the retained final2of2 documentation correction; no attempt limit resets.

The separate owner question about applications between original and debit amounts
on one Invoice line with different approved due dates remains pending. The approved
governing-date and between-Invoice/within-Invoice ordering rules are unchanged;
this operational stage does not implement or infer the missing attribution policy.

Physical departure must later reconcile existing Unit, Lease and Utility boundaries.
Inspection data alone does not remove the deferred DAMAGE_CHARGES source restriction.
Current migration60, regression and mandatory gates and fresh independent full-stage
review remain pending at this implementation checkpoint. Whole V1-055 remains
incomplete and unpublished; no V1-056 activation or Settlement closure is authorized.


### V1-055 inspection MI-1/MI-2 correction checkpoint

The initial complete-stage review of retained8f8f496 rejected two MEDIUM findings:
raw inspection snapshots were incompatible with the existing typed audit reader,
and immediate completion constraints ran before linked command evidence existed.
All original22 passing gates and the rejected report remain preserved.

The bounded correction keeps full inspection narratives and original responses in
their immutable source records and writes a private typed projection to audit
states. It changes no shared audit policy or read authorization. Completion binds
that projection, prior source and typed authorization linkage to the source rows.
Only the three new completeness constraints are deferred during construction and
checked before return; unrelated constraints retain their mode. Successful new
commands leave those three constraints immediate, and exact replay does not alter
the caller's mode. Original and correcting commands remain atomic.

MI-1 and MI-2 each consume correction1of2; prior layout2of2, audit fixture1of2 and
every older correction limit remain unchanged. New actual audit-consumer and
transaction-mode regressions, mandatory gates, expanded focused exact-SHA review
and fresh complete-stage review are pending. No inspection-stage acceptance,
whole V1-055 publication or financial-policy decision is implied by this change.


### V1-055 physical departure foundation checkpoint

BR-MOVEOUT-001/002/003/004/011/012, BR-OCC-005/007/009 and BR-UNIT-011/012/013
are implemented as explicit actual ended-member evidence coordinated with an
existing authorized termination. Additive migration61 preserves old storage and
functions; the new command alone applies bounded Occupancy date and Unit condition
changes. Historical corrections and original command recovery remain permanent.

The existing Utility boundary guard remains authoritative. A crossing historical
period or estimation case prevents this command atomically; it is an unresolved
connected reconciliation requirement, not a successful final Utility handling
result. Missing readings and pending approved estimates remain visible as pending.
No financial completion, charge, availability restoration or holdover policy is
inferred. Final Utility source linking, Damage admission, HTTP/staff integration,
final integrated review and every version acceptance gate remain required.

Accepted inspection c701a85 retains its focused and fresh complete-stage zero
reviews and22 gates; MI-1 and MI-2 are resolved1of2 each. All earlier correction
limits, original failed checkpoints, rejected candidates and regression evidence
remain preserved. The same-line original/debit due-date attribution question is
still pending; this physical foundation does not supply a policy answer.

At this initial implementation checkpoint, fresh physical regression and mandatory
gates and independent full-stage review remain pending. Whole V1-055 is incomplete
and unpublished; V1-056 is not activated.


### V1-055 owner-approved within-line due-date allocation — 2026-09-15

The owner approved earliest-due-first allocation for undesignated Payments and Customer Credits across amounts on the same Invoice line with different approved due dates. Existing between-Invoice ordering, Rent-before-Service ordering, customer designations and staff confirmation requirements remain authoritative. This decision supersedes the earlier pending same-line attribution question; the earlier checkpoint text remains historical.

The approval and exact owner text are preserved outside this candidate in v1055-earliest-due-first-owner-policy-20260915.json and v1055-owner-decisions-and-task-settings-20260915.json. The physical-departure stage records this decision only. Its financial persistence, calculations, connected consumers, regressions and independent acceptance remain a separate required bounded stage before V1-055 publication. No historical transaction rewrite, automatic confirmation or completed financial implementation is implied.


### V1-055 physical PD-1/PD-2 correction checkpoint

The initial full-stage review of retained7c86322 rejected two MEDIUM findings:
evidence-only successors could overwrite later Unit readiness, and physical audits
omitted their Unit relationship. The original22 passed gates,1498-case successful
database diagnostic, prior failed runs and immutable candidate/report remain evidence.

The correction preserves live Unit status/version when date, members and confirmed
condition are unchanged. Such an event may observe current VACANT or RESERVED
without making an availability transition; substantive corrections keep existing
transition rules. Completeness binds these distinctions and the explicit audit
Unit relationship. Actual Unit readers, readiness, Reservation and Lease callers
are covered by connected regressions without changing shared policies or locks.

PD-1 and PD-2 each consume correction1of2. The earlier trigger record-shape2of2
and both exhausted diagnostic/recovery allowances remain unchanged. Fresh affected
checks, expanded focused review and fresh full-stage review are required; this is
not stage or version acceptance. Approved earliest-due-first financial implementation,
Utility reconciliation/final sources, Damage, HTTP/staff and integrated V1-055
acceptance remain pending before publication or V1-056 activation.


### V1-055 connected Unit audit PD-3 and fixture chronology checkpoint

The first correction gate passed1516 cases and failed5. Four new synthetic
Lease fixtures overlapped the prior inclusive termination period; the existing
exclusion constraint correctly rejected them before the physical correction.
Fixture chronology correction1of2 uses an existing historical move-in source,
yesterday's termination and a later Lease beginning today. No source constraint,
clock rule or assertion is relaxed.

The fifth failure exposed PD-3: an existing Unit update stores its public floor
label under `floor`, which the general audit reader cannot classify. A narrow
Unit-event read adapter validates that canonical top-level text through existing
public-label and secret checks at both decoding and serialization. It retains
the original key/value and immutable rows. Other fields, nested data, other entity
types, the shared write classifier and role/Property permissions are unchanged.

PD-3 correction1of2 expands connected review across the shared read boundary.
PD-1/PD-2 each remain1of2, import layout1of2, trigger shape2of2 and all exhausted
diagnostic/recovery allowances remain preserved. Full fresh affected gates,
expanded focused and complete-stage independent reviews remain mandatory.
Nothing here accepts or publishes V1-055 or activates V1-056.


### V1-055 approved refund fixture isolation recovery — 2026-09-16

The owner approved one bounded fixture correction after the preserved intermittent
shared Credit setup lock failure. The real competing-Refund test now uses a fresh
owned database through existing disposable helpers; all original application
locks, timeouts, service behavior, outcome assertions and replay checks remain.
An added regression retains an unrelated shared-database invoices writer while
the unchanged workflow succeeds in the distinct database, then checks fixture
restoration and writer retention. The old module10functions/13cases becomes
11functions/14cases; full collection1521 becomes1522 in the preserved order.

The original focused12 run passed ten lock-contract cases and the Refund body,
but failed required teardown observation because its external observer emitted
recognize_* while requiring recognition_*. That failed run and observer remain
unchanged evidence. The owner separately approved phase mapping only and one
two-case verification90s+30s cleanup, reusing the ten unchanged passes. Both
cases and all required observations passed, enabling the previously approved
full1522 gate once480s+30s. All1522cases and required observations passed.
Total execution and cleanup including the failed observer run was356.967621s
within660s. Every owned cleanup passed. No automatic retry, further fixture
correction, allowance reset or application behavior change occurred.

Historical lock-holder identity remains unknown. This evidence supports the
isolated fixture remedy but does not independently accept it. Expanded fresh
PD-1/PD-2/PD-3, chronology and fixture correction review and then fresh complete
stage review remain mandatory. All prior limits, candidates, findings, failed
checkpoints and regression evidence remain preserved. Whole V1-055 is incomplete
and unpublished, with financial allocation, Utility/final sources, Damage,
HTTP/staff workflows and final integrated acceptance still required.


### V1-055 REC-1 current coordination-record correction — 2026-09-16

The expanded independent review of82c620f reported no remaining product defect
in PD-1/PD-2/PD-3 or the isolated Refund fixture, but rejected one LOW finding:
current takeover records still required owner action, and a never-authorized
old connected diagnostic request still said its owner question was pending.
These contradicted the separately approved and completed recovery and preflight.

REC-1 correction1of2 clears only the current owner-action flag and marks that
obsolete proposal historical/superseded. Its authorization_received=false and
executed=false remain accurate; no retroactive approval or extra run is implied.
Original proposal contents and previous state roots remain archived unchanged.
No application, fixture, test, migration, runner or traceability mapping changes.
Completed database evidence and every consumed allowance remain preserved.

Fresh affected records verification, exact-SHA REC-1 correction review and a
fresh complete-stage review with zero unresolved findings remain mandatory.
This does not accept the stage/version or authorize publication or V1-056.


### V1-055 physical acceptance and financial implementation boundary — 2026-09-16

The complete corrected physical stage atcdf1492 is independently approved with zero findings. The fixture isolation remedy is accepted based on preserved source, controlled writer observations and completed gates; the historical lock holder remains unknown. All rejected candidates, original failures and consumed allowances remain preserved.

No financial completion or whole-version acceptance is claimed.


### Owner authority:V1-055 closure and separate routine corrections — 2026-09-16T18:49:21.206433+00:00

I authorize autonomous continuation through full V1-055 closure while I am away, including the currently prepared two-expression test correction and its checks.
I grant a separate allowance for routine formatting, lint, typing, test-code and external-helper corrections that preserve application behavior, assertions, scope and acceptance requirements. For these corrections only, this supersedes previous “no further correction” and “stop on any failure” instructions. Allow at most two materially different corrections per distinct cause, verify affected behavior, and preserve every failure and correction. Do not repeatedly retry an unchanged approach or rename the same cause to obtain another allowance.
Preserve all previously consumed allowances. This does not grant additional historical database diagnostics, fixture corrections, changes to financial or authorization policy, or relaxation of locks, timeouts, assertions or acceptance gates.
Continue already-authorized implementation, required tests, independent reviews, normal publication and closure when their requirements pass. Reuse valid evidence for unchanged code. Resume the existing follow-up when a permitted path is verified.
For an actual permission/safety restriction, exhausted applicable recovery allowance or unresolved business decision, stop the affected action, preserve a concrete question in the main task and send one redacted Telegram alert. Continue unaffected authorized work; do not repeatedly poll an unchanged hold or treat silence as approval.
Once V1-055 is fully closed, pause the existing follow-up and report verified results. Do not activate V1-056 under this instruction. All other restrictions and model requirements remain unchanged.

Durable exact authority: /Users/sokompheak/.codex/.chatgpt-projects/g-p-6a721755d4048191b2550824162f9521/property-rental-v1055-routine-correction-authority-20260917.json. Previous authority snapshots and all consumed limits remain preserved.


### V1-055 final Utility input evidence — 2026-09-29

Owner decisions of 2026-09-29: move-out references final Readings that already exist through API-045 and never creates Readings; the new evidence lives in a separate forward migration63 while migration62 stays frozen; Damage-source work is held; HTTP work is limited to the routes defined by API-068/069. API-069 says the command "records … final Readings" and BR-MOVEOUT-005 says final actual Utility Readings "must be obtained and validated where possible"; neither states that move-out creates a Reading, so the reference model applies.

Migration63 and its service record one item per applicable Meter as a validated Reading dated on the actual Move-out Date, an approved broken-Meter estimate bounding that date, or an explicit unresolved reason checked against current Utility evidence. Original physical events are unchanged and later completion appends a successor. One fresh PostgreSQL invocation ran 18 cases, all passing, without retry. The approved-estimate item is covered by negative cases only; a positive case is not yet verified. The Meter applicability window and the Reading date rule are implementation choices awaiting owner confirmation. Existing tests that assert the migration head as `20260916_62` must be updated for migration63 before the full PostgreSQL run. No HTTP route, staff workflow, Damage source or Final Settlement behavior is delivered, and whole V1-055 remains incomplete.


### V1-055 owner rule changes and withdrawal of within-line due-date attribution — 2026-09-30

Owner decisions of 2026-09-30 withdraw the 2026-09-15 decision "V1-055 owner-approved within-line due-date allocation". That entry remains as history and no longer governs. The owner decided:

- An Invoice has exactly one Due Date. Invoice lines have no Due Dates.
- Adjustments remain linked debit or credit records on the original Invoice and use its Due Date. A debit Adjustment is blocked on an Invoice line that is fully paid; a missed amount on such a line is billed as a normal one-time Miscellaneous or Damage charge. A Payment reversal that reopens the line allows debit Adjustments again. Credit Adjustments are allowed on any issued Invoice; a credit beyond the remaining balance becomes Customer Credit. The Invoice is locked so that an Adjustment and the final late-payment decision are strictly ordered: an Adjustment recorded before the final decision is included in that decision's balance, and a credit Adjustment never changes a final decision. BR-INV-049 continues to govern Damage and Miscellaneous charges.
- Recurring Rent nonpayment days are counted from the 1st of the billed month, which is day one, so day 20 is the 20th and day 30 is the 1st plus 29 calendar days. For the Initial Rent Invoice, day one is its issue date, and a day-21-or-later combined Initial Invoice has one day one and one count. A case opened late carries its real day count and alerts staff at once if day 20 or day 30 has passed. Recorded cases and events are never rewritten; the new count applies to new cases.
- The Initial Rent Invoice is due five calendar days after it is issued, fixed at issuance from the Asia/Phnom_Penh business date. BR-RENT-005 and BR-RENT-007 are unchanged, billing starts at the actual Move-in Date, and the Lease Start Date is unchanged.
- The late-payment charge is not an Invoice and continues to follow the Invoice Due Date. BR-INV-052 to BR-INV-055, BR-LATE-001 to BR-LATE-003 and BR-LEASE-030 are unchanged.

The unpublished due-attribution implementation is removed by a forward commit: migration 20260916_62, the dated-source services, the preview and due-source routes, the dated-source user interface, BR-PAY-041/PR-PAY-041 and their tests and traceability. Migration 62 was never applied to any persistent database, and migration 20260917_63 now follows 20260915_61. The canonical amendments for these decisions await owner approval; until then BR-LEASE-026 to BR-LEASE-029, BR-RENT-009, BR-SVC-011, BR-SVC-012 and BR-INV-049 remain as written and the code for them is unchanged.

## DL-067 — Utility baseline, final Utility Invoice and catch-up billing; known same-dates billing gap

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `APPROVED; IMPLEMENTATION IN PROGRESS (V1-055 Slices 7 and 8)`
- **Baseline:** A baseline Reading may be dated on or before the Lease Start Date, never after it. It is the Customer's responsibility boundary; a new baseline after switching on again supersedes the earlier one.
- **Skipped period:** A monthly Utility period of a Lease that has no Occupancy yet is skipped with the diagnostic NOT_MOVED_IN. It is billed later by an explicit audited staff command, once the Lease has an Occupancy, as one off-cycle Utility Invoice. The Due Date follows BR-INV-018 (issue date plus the Property's configured days, authorized override with mandatory reason), capability `invoices.issue`. A Lease that never moves in leaves the period unbilled; the Property bears it.
- **Final Invoice:** The final Utility Invoice also bills every period the Customer is responsible for that has no active Invoice line, so nothing is left unbilled at move-out. It waits until every Meter is resolved.
- **Known gap (slice 7b, not fixed in Slices 7 or 8):** the Utility worker creates one run per distinct period dates. A period finalized after a SUCCEEDED run for the same dates is never billed by the worker. To be fixed before Slice 9 and certainly before V1-060.
- **Implementation (Slice 8, migration `20261006_71`):** one baseline event per Lease records one validated Reading per applicable Meter, all dated the baseline date, as a service with no HTTP route. The baseline must precede handover (SIGNED Lease, no Occupancy) and must not split a finalized period. The responsibility functions `utility_responsibility_window_is_stable` and `guard_utility_responsibility_change` use `baseline_date + 1` instead of the Lease Start Date and the move-in date for a Lease with a baseline. The monthly Utility run skips NOT_MOVED_IN and PROPERTY_BORNE_CONSUMPTION periods instead of failing; a Lease without a baseline keeps its exact results. The Utility run creates one run per distinct period dates, so the first partial period after a baseline is billed by its own run with those exact dates.
- **Design difference (accepted 2026-10-02):** the baseline is one event per Lease with one item per Meter, all on one baseline date, instead of one row per Meter; the Customer's boundary is therefore one date per Lease.
- **Implementation (Slice 7, migration `20261007_72`):** `app.utility_final_invoice_create` and `app.utility_catch_up_invoice_create` (service only, no HTTP route) create one off-cycle Utility Invoice, issued through the existing issue command with the issue-plus-configured-days Due Date or an authorized override. The final Invoice creates the missing ACTUAL periods from the final-input Readings and also bills every responsible period without an Invoice line; it waits for every Meter and exists once per final-input event. The catch-up bills a NOT_MOVED_IN period only after an Occupancy exists. Final needs `invoices.issue` and `utility.calculate` (it creates periods); the catch-up needs `invoices.issue`. The start Reading of a Meter with no earlier period and no baseline is its first Reading when it was installed during the Customer's responsibility.
- **Slice 7b (migration `20261008_73`):** `billing_runs_period_no_overlap` is limited to Rent runs because the Utility run is exact-dates and the Invoice line is unique per period; the earlier plan that a partial period gets its own run needed this. `app.utility_unbilled_periods` lists periods no run will pick up and the catch-up command bills them; late periods are billed only by explicit staff action, never by an automatic supplemental run.
- **Superseded test expectation (DL-067, slice 9b):** the OpenAPI inventory in `test_fastapi_openapi_inventory_has_no_bootstrap_or_unauthenticated_owner_reset_route` now also lists the two new Invoice routes `POST /properties/{id}/one-time-charges` and `POST /properties/{id}/one-time-charge-due-days`; no bootstrap or reset route was added.
- **Superseded test expectation (DL-067, slice 9c):** the OpenAPI inventory in `test_fastapi_openapi_inventory_has_no_bootstrap_or_unauthenticated_owner_reset_route` now also lists the read route `GET /properties/{id}/initial-rent-unpaid-alerts`; no bootstrap or reset route was added.
- **Superseded test expectation (DL-067, slice 9c):** the same OpenAPI inventory test now also lists the two follow-up routes `POST /properties/{id}/lease-terminations/{termination_event_id}/unpaid-initial-never-moved-in` and `.../unpaid-initial-moved-in-credit`; no bootstrap or reset route was added. The `private, no-store` header rule now also covers the 9b routes `one-time-charges` and `one-time-charge-due-days`, which it had missed.
- **Superseded test expectation (DL-067, slice 9d):** the same OpenAPI inventory test now also lists the Utility routes `GET` and `POST /properties/{id}/leases/{lease_id}/utility-baseline`, `GET` and `POST .../move-out-final-utility-inputs`, `POST .../final-utility-invoice`, `POST .../utility-catch-up-invoice` and `GET /properties/{id}/unbilled-utility-periods`; no bootstrap or reset route was added.
- **Superseded test expectation (DL-067, slice 9e):** migration `20261009_74` retires the runtime role's direct EXECUTE on `app.sign_lease`; signing runs through the SECURITY DEFINER `app.sign_lease_with_reservation`. Two expectations changed only in the `app.sign_lease` privilege value: the first element of the pair in `test_v1_034_upgrade_preserves_v1_033_lease_and_replaces_unbounded_runtime_helpers` and the third element in `test_runtime_role_uses_only_bounded_functions_and_command_history_is_permanent`. The head-revision assertions now expect `20261009_74`.
- **Audit capability of the Initial Rent Due Date override (DL-067, slice 9e, owner-approved 2026-10-02):** migration `20261009_74` adds an overload of `app.set_initial_rent_due_date` that takes the capability the caller was authorized under (`billing.generate` or `invoices.issue`) and records it in the audit event. The invoice route passes `invoices.issue`; the six-argument function and its earlier audit records are unchanged. No test expectation had to be narrowed for this part; the invoice service test gained an expectation for the stored capability.
- **Superseded test fixture (DL-067, slice 9e, owner-approved 2026-10-02):** `test_v1_045_typed_sources_keep_category_and_controlling_id_together` now uses a WATER Meter, Rate and consumption period instead of ELECTRICITY. Its Rate is committed to the shared test database with the date 2027-04-01 and the Invoice line check needs the Rate to be effective at the period start, so a far-future date was not possible; from April 2027 the old ELECTRICITY fixture would have become the current ELECTRICITY Rate for `test_json_snapshots_preserve_maximum_consumption_and_rate_precision`. No expectation changed.
- **Frontend type check (DL-067, slice 9e):** `npm run typecheck` now runs `tsc -b`. The root `tsconfig.json` lists no files, so `tsc --noEmit` checked nothing; `tsc -b` checks the application and Node projects exactly as the production build does.
- **Frontend test timing (DL-067, slice 9e):** `TEST-FE-488` now waits for the second page of reversal records to commit before it clicks Next again. Under heavy parallel load the second click could reach the button before the first page change had finished, and the handler never ran; the assertions are unchanged. `TEST-FE-087` failed once in a full run and could not be reproduced under load; it stays recorded as an intermittent timing failure.
- **Owner exception for the app.sign_lease revoke (DL-067, owner decision 2026-10-02):** the owner approved the REVOKE of the runtime role's direct EXECUTE on `app.sign_lease` in migration `20261009_74` as an exception to the additive-or-relaxing migration rule, because it removes an old, unused privilege. Signing runs through the SECURITY DEFINER `app.sign_lease_with_reservation`, which still calls `app.sign_lease`.
- **Lease timeline visibility (DL-067, owner decision 2026-10-02):** Rent-nonpayment events and Initial Rent Due Date overrides will be shown in the Lease timeline, but only to users who already have the permission to see those records today. A user without that permission sees the timeline exactly as before, with no hint that hidden events exist. The runtime role gets no direct table access; a bounded read function, like the existing pattern, supplies the rows. Not built yet.
- **Superseded test expectation (DL-067):** the head-revision assertions in the migration and service suites now expect `20261008_73`; only the expected revision changed.
- **Termination context (DL-067, slice 9c):** `POST /leases/{id}/terminate` accepts an optional `context` object that carries the termination basis (including the unpaid Initial Rent basis), the signed Lease provision, the grounds, the authorization and evidence references, the notice data and the warning identifiers. The database still refuses a fresh termination without it. Documented in docs/005.
- **Superseded by slice 9e (DL-067):** the DL-066 sentence that `app.sign_lease` stays granted for compatibility, and the DL-067 line that names head revision `20261008_73`, are superseded by slice 9e (migration `20261009_74`, which retires that grant and is the later head).
- **Owner answer 1 (DL-067, 2026-10-02):** apply the `npm audit` fix now, only if it changes `package-lock.json` alone.
- **Owner answer 2 (DL-067, 2026-10-02):** fix the intermittent test lock failures now, before the Lease timeline work and before V1-056.
- **Owner answer 3 (DL-067, 2026-10-02):** Initial Rent Due Date overrides in the Lease timeline need `invoices.read`; Rent-nonpayment events need `rent_nonpayment.read`.
- **Frontend test timing (DL-067, slice 9f-2, owner decision 2026-10-03):** `TEST-FE-128` ("retains an authoritatively absent command identity for its explicit retry", `frontend/src/CustomerManagement.test.tsx`) failed once in a full frontend run at the `#customer-legal-name` lookup near line 2755 and passed on the next full run (1585 of 1585). It is recorded as a third intermittent timing failure next to `TEST-FE-087` and `TEST-FE-488`. The cause is not yet known; the failing output was not saved, and the test is unmodified.
- **Lock failures in the full PostgreSQL suite (DL-067, slice 9f-3, 2026-10-03):** a read-only search of all backend tests and fixtures found no test that leaves a connection or transaction open into another test. The likely cause is PostgreSQL autovacuum: autovacuum and ANALYZE hold SHARE UPDATE EXCLUSIVE on a table while they work on it, which conflicts with the `LOCK TABLE ... IN SHARE MODE NOWAIT` in `app.assert_payment_excess_eligible`, and a NOWAIT request never waits for autovacuum to step aside. The mechanism is proven by `test_credit_obligation_set_lock_rejects_autovacuum_lock_without_waiting`; that the past suite failures were caused by autovacuum is not proven. A diagnostic full run with a lock watcher passed 1640 of 1640 and gave no evidence, because the watcher read the catalog of the wrong database. Autovacuum stays enabled in tests.
- **Bounded lock retry (DL-067, slice 9f-4, owner decision 2026-10-03):** the Credit and Refund services (`CustomerCreditService` and `RefundService`, the services whose commands reach `app.assert_payment_excess_eligible`) replay the same command after SQLSTATE 55P03 only, at most three times, with pauses of 0.25, 0.5 and 1 second (`property_rental/lock_retry.py`). NOWAIT stays. Each attempt is its own connection and transaction, and the refused attempt is rolled back and closed before the pause, so no lock, and never the Payment source lock, is held while waiting. Every attempt sends the identical command with the same idempotency key, so a replay cannot write a duplicate row. After the last attempt the services raise the same `CreditUnavailableError` or `RefundUnavailableError` as before. The Invoice adjustment path that reaches the same check through `app.validate_invoice_credit_excess_release` is unchanged and still answers a conflict.
- **Correction to the slice 9f-4 line (DL-067, slice 9f-4b, 2026-10-03):** the Invoice adjustment credit-excess path does not reach `app.assert_payment_excess_eligible`. Migration `20261003_67` changed `app.validate_credit_recognition()` so that a Credit created by an adjustment release (`app.invoice_credit_excess_releases`, source PAYMENT_ALLOCATION) skips that check; only other Credit recognitions call it. `app.validate_invoice_credit_excess_release` only validates the release row and takes no NOWAIT lock. That path therefore cannot fail on the NOWAIT obligation-set lock, so no retry was added to `app.adjust_invoice` or the Invoice service. The 9f-4 sentence saying the adjustment path reaches the same check is wrong and is superseded by this line.
- **Lease timeline restricted events (DL-067, slice 9f-5, owner decision 2026-10-03, migration `20261010_75`):** the Lease detail and timeline reads show Initial Rent Due Date overrides to actors with `invoices.read` and Rent-nonpayment events to actors with `rent_nonpayment.read` for the Lease's Property, merged into the existing order and cursor. They come from the bounded STABLE SECURITY DEFINER function `app.lease_timeline_restricted`, which the runtime role may only EXECUTE; it gets no table privilege. As in the existing bounded functions (for example `app.lease_enforcement_workspaces`), the database checks that the actor is an active human account and keeps only rows whose Lease Property is in the matching Property list; the application checks the capabilities and builds those lists from the actor's grants. Capability grants are not stored in the database, so the database cannot check them itself. With no such grants the application does not call the function, and a `leases.read`-only actor sees exactly the earlier timeline. Command responses that embed a Lease (for example after signing) still carry the earlier timeline without the restricted events; the next detail or timeline read shows them.
- **Superseded test expectation (DL-067, slice 9f-5):** the head-revision assertions in the migration and service suites now expect `20261010_75`; only the expected revision changed. The in-memory Lease flow in `test_lease_api.py` accepts and records the new optional `visibility` argument; no expectation changed.
- **Accepted dev-only risk (DL-067, owner decision 2026-10-03, to fix in V1-059):** advisory GHSA-vfj7-8cjw-p6xm (`braces`, high, stack exhaustion through deeply nested patterns) was published after slice 9f-2. All 9 high `npm audit` findings come from that one advisory through one dev-only chain: `typescript-eslint` 8.44.1 → `@typescript-eslint/*` → `fast-glob` → `micromatch` → `braces`. The fix is `typescript-eslint` 8.71.0, which the owner approved. It removed the chain and gave 0 vulnerabilities, but its newer rules reported 35 lint errors in existing code (`no-unnecessary-type-assertion` 19, `prefer-optional-chain` 9, `unbound-method` 4, `no-meaningless-void-operator` 3). As instructed, no code, rule or configuration was changed and the update was undone; `package.json` and `package-lock.json` keep 8.44.1. The vulnerable code runs only in the lint toolchain on developer and CI machines, not in the shipped application. Until V1-059, `make frontend-audit` fails on this advisory.
- **Development database migration deferred (DL-067, owner decision 2026-10-03):** no local development database existed on 2026-10-03, so no `pg_dump` backup was taken and `make migrate` was not run. The full PostgreSQL suite (1648 passed) applies every migration through `20261010_75` on fresh databases. The first `make migrate` against a real database, with a backup taken first, moves to V1-059.
- **Browser check deferred; login slice planned (DL-067, owner decision 2026-10-03):** the application has no working login yet. `property_rental.app:app` is built with `deny_unauthenticated_actor` and `UnavailableAuthenticationFlow`, so `/api/v1/auth/login` answers 503 and no business screen can be reached in a browser. The owner declined a temporary launcher that would bypass authentication. The V1-055 screens were therefore not checked in a browser. A new slice builds the real login: the runtime authentication adapter with sessions and MFA, plus tests. It is planned after V1-056 and before V1-057, and the first browser check waits for it.
- **Decision date:** 2026-10-02.


## DL-068 — Leaving early, deposits, refunds, approval and correction history for V1-056

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `APPROVED; CANONICAL AMENDMENT PENDING; IMPLEMENTATION PENDING V1-056`
- **Clarifies:** DL-065. DL-015's "the final calendar month of Rent is charged in full" means the calendar month of the actual hand-back (move-out) date, with the before-the-5th exception below. The text of DL-015 and DL-065 is unchanged.
- **Leaving early, hand-back on or after the 5th:** the Customer pays that month's Rent in full, every issued Invoice (paid or unpaid) and the move-out charges (final Utility, Damage, cleaning and other services).
- **Leaving early, hand-back before the 5th, that month's Rent unpaid:** the same, except that month's Rent Invoice, which an authorized user VOIDs with a reason. This also covers the next month's Rent Invoice generated on the 25th when the Customer leaves between the 25th and the end of the month.
- **That month's Rent fully paid:** the Property keeps it; no Refund and no credit Adjustment. Because the Customer paid, the Customer may stay until the last day of that month.
- **That month's Rent partly paid:** the Property keeps the paid part, and a linked credit Adjustment with a reason removes the unpaid rest (the DL-064 pattern for a Lease that never moved in).
- **Date that counts:** the actual hand-back (move-out) date, not the notice date. The one-month notice is not a system rule.
- **Kept Security Deposit:** a kept (forfeited) Security Deposit does not reduce what the Customer owes. Authorized staff may still apply the deposit to charges with a reason, as DL-032 allows.
- **Cleaning charge:** a Unit cleaning charge, from the Unit's configured rate, is charged at every move-out, for any reason of leaving, on the move-out Invoice. An authorized user may reduce it with a reason.
- **Unpaid balance after Final Settlement:** stays open as debt on the Customer Ledger. No write-off in V1.
- **Pet Deposit at termination for unpaid Initial Rent and at violation termination:** it pays pet damage first and the rest is refunded, as in DL-013.
- **Security Deposit when the Customer moved in and is then terminated for unpaid Initial Rent:** kept, as for a Customer who never moved in.
- **Remaining Pet Deposit at move-out:** the Customer may choose to use it to pay any remaining balance. DL-032 step 5 also lets authorized staff do this with a reason when the Customer will not pay.
- **Credit from a credit Adjustment:** belongs to the Customer named on the Lease and Invoice, even when a third party paid. Any Refund of it goes to that Customer.
- **Payment allocated to the wrong Unit's Invoice by mistake** (example: meant for Unit 201, paid on Unit 203): not refunded to the payer. The wrong Payment Allocation on the Unit 203 Invoice is reversed and the same Payment is allocated to the Unit 201 Invoice. No Customer Credit moves between Customers (DL-031 stays true). Before this, staff record as text that both Customers confirmed: who, the date and how they confirmed. An authorized user approves.
- **Refund method:** cash or bank transfer (ABA or another bank), with a reference note. All Refunds are in USD (DL-060). No Refund deadline in the system.
- **Approval:** Final Settlement, deposit use, kept deposits, Refunds, wrong-Invoice Payment moves and post-settlement corrections are approved by the Owner, a Manager or another user given the approval capability. Staff can prepare but cannot approve. A new capability needs a proposed name and an owner answer before it is used.
- **Correction history:** a finalized Final Settlement is never reopened. A later fix is a new linked post-settlement correction (extra charge or Refund) with a reason; the original Settlement stays unchanged. No time limit for post-settlement corrections.
- **Canonical amendment pending:** 001 and 002 are not changed by this entry. The rules it changes or adds (among them BR-LEASE-021, BR-RENT-024, BR-MOVEOUT-010, BR-DEP-022, BR-DEP-019, BR-PAY-033, BR-CREDIT-002/003, BR-SETTLE-003/005/014, BR-AUTH-008/009 and the Trash-only Service rule) need owner-approved amendments before or with V1-056.
- **Decision date:** 2026-10-03.

## DL-069 — Answers to the DL-068 conflicts and gaps for V1-056

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `APPROVED; IMPLEMENTATION PENDING V1-056`
- **Supersedes:** the DL-068 clause "Authorized staff may still apply the deposit to charges with a reason, as DL-032 allows." DL-068 text is unchanged; the link is only in this entry.
- **Canonical amendment:** 001 and 002 are amended to match DL-068 and this entry for every conflict in the DL-068 review.
- **Kept Security Deposit:** a kept (forfeited) Security Deposit is never used to pay what the Customer owes. The whole deposit is forfeited and unpaid charges stay as debt on the Customer Ledger. This applies to every case where the Security Deposit is kept: voluntary early leaving, termination for unpaid Initial Rent or Security Deposit, and violation termination.
- **Normal Lease end:** DL-032 is unchanged. The Security Deposit may pay remaining charges and the rest is refunded.
- **Pet noncompliance termination:** both deposits are kept; BR-DEP-022 stays as written. **Non-pet violation termination, or termination after the 30-day Rent nonpayment default:** the Security Deposit is kept; the Pet Deposit pays pet damage first and the rest is refunded.
- **Approval capability:** new capability `financial.approve`. It approves Final Settlement, deposit use, deposit forfeiture, Refunds, wrong-Invoice Payment moves and post-settlement corrections.
- **Drafts:** Staff record a draft of each of these actions; only a `financial.approve` holder confirms it. A draft has no financial effect until it is confirmed.
- **Late-payment Charges:** they are part of what a leaving Customer owes.
- **VOID of the hand-back month:** when the hand-back month's Rent Invoice is VOIDed (unpaid, hand-back before the 5th), the whole Invoice is VOIDed, including Trash Collection and other fixed Service lines, because they are billed in advance on the same Invoice. A read-only check on 2026-10-03 confirmed that the monthly Rent Invoice generated on the 25th and the Initial Rent Invoice both carry the Trash Collection line, prorated by days on the first part-month like the Initial Rent.
- **Lease End Date:** a Lease End Date must always be the last day of a calendar month (example: Start Date 10 April 2026, End Date 31 May 2027). Any other End Date is rejected. A Lease ends mid-month only through early termination. V1-056 adds the validation and a test, and a test that no Rent Invoice is generated for a month after the End Date.
- **Cleaning charge:** no cleaning charge when the Customer never moved in. The Unit cleaning charge is a one-time charge on the move-out Invoice; its Due Date is the issue date plus the Property's configured days (7 by default), with the existing authorized override. A reduction is a linked credit Adjustment with a reason.
- **Wrong-Unit Payment move:** reverse the wrong allocation and allocate the same Payment to the correct Invoice. The first Invoice becomes unpaid again and the normal late-payment and Rent nonpayment rules apply from then on; earlier records are not changed. If the wrong allocation already became Customer Credit or a Refund, those must be reversed first; otherwise the move is blocked. The Payment record (amount, date, Receipt) never changes.
- **Joint Signers:** settlement debt shows on the Primary Tenant's Customer Ledger. Deposit Refunds go to the Primary Tenant unless all Signers agree in writing to another Signer, recorded as text.
- **Refund methods:** a configured list, like Payment Methods, starting with Cash and Bank transfer.
- **Rules changed or added:** BR-LEASE-013, BR-LEASE-021, BR-LEASE-025, BR-RENT-024, BR-RENT-026, BR-MOVEOUT-006, BR-MOVEOUT-010, BR-SVC-001, BR-PAY-033, BR-CREDIT-002, BR-CREDIT-003, BR-DEP-018, BR-DEP-019, BR-DEP-023, BR-SETTLE-003, BR-SETTLE-005, BR-SETTLE-006, BR-SETTLE-007, BR-SETTLE-013, BR-SETTLE-014, BR-AUTH-008, BR-AUTH-009; new BR-UNIT-014, BR-LEASE-031, BR-RENT-030, BR-PAY-042 (BR-PAY-041 stays withdrawn), BR-CREDIT-014, BR-REFUND-014, BR-REFUND-015, BR-MOVEOUT-013, BR-DEP-026, BR-DEP-027, BR-SETTLE-016, BR-SETTLE-017, BR-AUTH-010.
- **Decision date:** 2026-10-03.
