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
- **V1-056 slice 1, Lease End Date month end (DL-069, owner approval 2026-10-03, migration `20261011_76`):** `app.create_lease_draft`, `app.create_lease_draft_with_terms`, `app.update_lease_draft` and `app.sign_lease` refuse an End Date that is not the last day of its calendar month (SQLSTATE 22023). The check runs after the idempotent replay, so an earlier recorded command still replays. There is no table constraint and no existing Lease row is read or changed; an earlier draft with a mid-month End Date must be updated before it can be signed.
- **Updated test inputs (V1-056 slice 1):** fixtures that create or sign a Lease through these functions now use month-end End Dates: `test_lease_lifecycle_migration.py` (two tests: the idempotency test, and the occupied Lease, successor and renewal in the open-Occupancy test, whose successor and renewal now start on the day after that month end), `test_lease_signing_reservation_migration.py` (`signed`), `test_unpaid_initial_termination_migration.py` (`signed_with_initial`) and `test_lease_api_migration.py` (2028-01-09 became 2028-01-31). No assertion changed. The head-revision assertions in the migration and service suites now expect `20261011_76`; only the expected revision changed.
- **V1-056 slice 2, financial drafts (DL-069, owner answers 2026-10-03, migration `20261012_77`):** new capabilities `financial.approve` and `final_settlements.prepare`. Tables `app.financial_drafts` and `app.financial_draft_decisions` are append-only; each draft has at most one decision (CONFIRMED, REJECTED or WITHDRAWN). Only a `financial.approve` holder confirms or rejects; the preparer withdraws with the draft's own prepare capability. A person may prepare and confirm the same draft only when holding `financial.approve`; both are recorded. Capabilities are checked by the application; the database checks the active human actor, the Property and the recorded authorization reference. Draft kinds (Refund, deposit forfeiture, Payment move, Final Settlement, post-settlement correction) get their record and confirm commands in later slices; until then nothing can create a draft through the runtime or financial roles.
- **Updated test expectation (V1-056 slice 2):** the head-revision assertions now expect `20261012_77`; only the expected revision changed.
- **Slice 2 scope as built (V1-056, review answers 2026-10-03):** each draft kind is tied to its prepare capabilities by a table constraint (Refund: `refunds.create` or `reservation_deposits.refund`; deposit forfeiture: `deposits.dispose` or `reservation_deposits.dispose`; Payment move: `payments.allocations.reverse`; Final Settlement and post-settlement correction: `final_settlements.prepare`). A reader without `financial.approve` sees only the kinds it may prepare. The internal confirm record also requires the `financial.approve` reference. Deliberately left to the kind slices: the confirm commands and their "Staff cannot confirm" tests, the stale-draft check against `source_revision`, idempotent confirm, and the "no financial effect before confirmation" tests (slices 3, 6, 7, 9 and 10). Names differ from the plan text: the decision table is `app.financial_draft_decisions` (one decision per draft) and the shared functions are `insert_financial_draft`, `confirm_financial_draft_record`, `reject_financial_draft` and `withdraw_financial_draft`; reject and withdraw run under the financial role and reads under the runtime role, as the existing Credit and Refund functions do.
- **Slice 2 round 3 (owner-approved extra review round, 2026-10-03):** the shared confirm record also requires the matching draft kind. Pet Deposit use at Final Settlement belongs to the FINAL_SETTLEMENT draft; if a later slice needs a separate deposit-use draft kind, it widens the kind and kind/capability constraints and the read functions' kinds bound in a relaxing migration.
- **Owner answers to Q-2026-10-03-2 (2026-10-04), Reservation Deposit drafts:** Staff cancellation cancels the Reservation at once and releases the Unit; the Security Deposit stays held until a `financial.approve` holder confirms the Refund or forfeiture draft. The relaxing migration of the outcome-complete trigger is approved. The expiry worker still expires the Reservation and releases the Unit automatically but never forfeits; the forfeiture waits for a Staff draft and an approver. Reservation outcome corrections are drafts too. Refund corrections (verified returns and their reversal) stay as they are, without a draft. Slice 3 is split into 3a (Refund methods, Refund drafts for Credit, Payment and Pet Deposit Refunds, joint-Signer recipient) and 3b (Reservation Refunds and forfeitures as drafts). 3b must add a bounded per-Property read list "Reservations waiting for a Deposit decision" and a test that an expired Reservation stays on it until its draft is confirmed.
- **V1-056 slice 3a-1, Refund methods and Refund drafts (migration `20261013_78`):** `app.refund_methods` is one configured list seeded with Cash and Bank transfer (ABA or another bank); `property.manage` adds or deactivates a method; a method's code and name never change and none is deleted. A Credit, Payment or Pet Deposit Refund is recorded as a `REFUND` draft by a `refunds.create` holder, with a method and a reference note, and takes effect only when a `financial.approve` holder confirms it; confirmation runs the existing Refund functions, so every earlier Refund rule still applies, and stores the method and note in append-only `app.refund_draft_details`. A draft whose amount is no longer available is refused at confirmation and stays pending. Refund command keys keep their earlier scope: the draft id is derived from the Property, the preparer, the Refund kind and the key, and a confirmation is refused when that id is already another Refund command key of the approver. The financial role no longer executes `app.create_usd_refund` or `app.create_pet_usd_refund` directly (owner answer to plan Q6), and `POST /refunds` now answers 409 `REFUND_DRAFT_REQUIRED` and records nothing; the draft screens come in slice 11c (the two draft routes were brought forward into this slice, see the scope-change note below). The joint-Signer recipient rule (BR-REFUND-015) follows in slice 3a-2.
- **Updated tests (V1-056 slice 3a-1):** tests that created a Refund in one call now use `tests/refund_test_support.py`, which records the draft and confirms it as the same person holding `financial.approve`; the returned Refund resource and every assertion are unchanged (`test_refund_service_migration.py`, `test_pet_refund_migration.py`, `test_credit_history_migration.py`, `test_credit_refund_api_migration.py`, `test_credit_refund_read_migration.py`, `test_customer_ledger_migration.py`, `test_customer_ledger_read_migration.py`, `test_deposit_disposition_migration.py`, `test_deposit_financial_revision_migration.py`, `test_financial_action_context_migration.py`, `test_payment_read_migration.py`, `test_payment_reversal_context_migration.py`). Narrowed expectations, test names kept: in `test_credit_refund_api.py`, `test_credit_refund_http_exact_service_dispatch_and_private_response[12]` and `test_credit_refund_http_pet_creation_uses_only_qualified_existing_service` expect 409 `REFUND_DRAFT_REQUIRED` with no service call, and `test_credit_refund_http_service_failures_keep_safe_unknown_outcome_and_key_reuse` uses the verified-return route for the Refund error mapping; in `test_refund.py` the capability, transmission and failure-mapping tests use `record_usd_draft`, `record_pet_draft` and `confirm_draft` and their SQL; `test_lock_retry.py` replays `confirm_draft`; `test_pet_refund_migration.py` expects the financial role to lack direct EXECUTE on `app.create_pet_usd_refund`. The head-revision assertions now expect `20261013_78`.
- **Slice 3a-1 scope change (2026-10-04):** the two Refund draft routes (`POST /refund-drafts` and `POST /properties/{property_id}/refund-drafts/{draft_id}/confirm`, docs/005 API-065) are built in slice 3a-1 instead of slice 11c, so that the real HTTP Refund tests keep testing Refund creation over HTTP; the screens stay in slice 11c. In `test_credit_refund_api_migration.py` the eight tests that created a Refund with `POST /refunds` now record the draft and confirm it over HTTP; their assertions are unchanged, and the client actor also holds `financial.approve`. In `test_refund_service_migration.py`, `test_refund_command_receipts_are_immutable_and_private` looks up the stored command by the derived draft id, and `test_refund_service_facade_database_roles_are_separated` expects the financial role to lack EXECUTE on `app.create_usd_refund`. A confirmation replay returns the original stored Refund response, as the one-call create did.
- **More updated tests (V1-056 slice 3a-1):** `test_initial_owner_bootstrap_cli.py` lists the two new Refund draft routes in the expected API inventory. In `test_financial_context.py` the boundary case for the Refund create route (index 23) now uses `POST /refund-drafts`, the route that creates a Refund draft, with the same status, meta, cache and Location checks.
- **Refund audit fields after drafts (V1-056 slice 3a-1):** a confirmed Refund row keeps the earlier shape: `processed_by` is the approver who confirmed and `authorization_reference` stays `refunds.create`, as the earlier Refund trigger requires. The preparer, the `financial.approve` decision, the method and the reference note are in `app.financial_drafts`, `app.financial_draft_decisions` and `app.refund_draft_details`, linked by the draft id.
- **Owner answers to Q-2026-10-04-4 (2026-10-04), Deposit Refund to another Signer:** a Deposit Refund paid to another Signer (BR-REFUND-015) is shown on the Deposit owner's (Primary Tenant's) Customer Ledger, naming the Signer who was paid; the receiving Signer's ledger shows no balance change. Deposit Refunds are booked on the owner's ledger in a new projection version; earlier records and earlier projection results stay unchanged. The written agreement is free text recorded with the draft (who agreed, the date and how); the chosen person must be a Signer of that Lease; no file upload. The rule applies to Pet Deposit Refunds now (slice 3a-2) and to Final Settlement Deposit Refunds in slice 9; Reservation Refunds always go to the Reservation Customer.
- **Run rule update (owner, 2026-10-04):** default one full PostgreSQL run per sub-slice; a rerun only after a real correction (at most 2 per distinct cause); every run listed in the slice report; a targeted run only when it provably covers every affected test (ops/V1_056_TAKEOVER.md section 5).
- **V1-056 slice 3a-2, Deposit Refund to another Signer (BR-REFUND-015, migration `20261014_79`):** a Pet Deposit Refund draft may name another Lease Signer with the written agreement of all Signers (free text, 1 to 2,000 characters). The named person must be a signed Signer of that Lease and not the Primary Tenant; a Payment or Credit Refund cannot name one. At confirmation the agreement is written first to append-only `app.refund_recipient_agreements` and the Refund row names that Signer; the Pet Refund source check accepts another recipient only with that recorded agreement. The ledger view `app.customer_ledger_effects` is rebuilt from the revision 48 builders with one change: a Deposit Refund and its corrections are booked on the Deposit owner's ledger, and `source_audit.paid_to_customer_id` names the Signer when it differs; every earlier Deposit Refund was paid to the Deposit owner, so earlier results are unchanged. The head-revision assertions now expect `20261014_79`.
- **V1-056 slice 3b, Reservation Deposit drafts (BR-AUTH-010, BR-RES-016, BR-RES-021, BR-RES-022; owner answers to Q-2026-10-03-2; migration `20261015_80`):** the outcome-complete check (`app.assert_reservation_financial_outcome_complete`) also accepts a cancelled Reservation whose Deposit has no outcome record at all; once any disposition or Refund exists for that Deposit the earlier complete-outcome rule applies unchanged. `app.cancel_reservation_v3` and `app.expire_reservation_v3` record the lifecycle event and release the Unit only; the Deposit state reads `AWAITING_DECISION`. A Staff draft (`app.record_reservation_deposit_draft`) records the decision: the kind follows the cancellation responsibility (Customer-caused or expired: `DEPOSIT_FORFEITURE` under `reservation_deposits.dispose`; Property-caused: `REFUND` under `reservation_deposits.refund` with Refund number, method and reference note); it covers the whole received Deposit; only one draft per Reservation may be pending. A correction draft (`app.record_reservation_deposit_correction_draft`) needs `reservation_deposits.correct` as well and replaces the confirmed outcome with one of the same kind. `app.confirm_reservation_deposit_draft` (only with the `financial.approve` reference) runs the existing outcome functions (`app.complete_reservation_deposit_outcome`, `app.correct_reservation_deposit_outcome`) with the approver as actor, so every earlier outcome rule applies; a Refund also gets its method and note in `app.refund_draft_details`, and the Refund goes to the Reservation Customer as the earlier source check requires. A draft whose Reservation version or received Deposit changed is refused with 422 and stays pending (a defensive check, see below). `app.list_reservations_awaiting_deposit_decision` (runtime role, `reservations.read`) is the bounded per-Property list "Reservations waiting for a Deposit decision". The financial role no longer executes `app.cancel_reservation_v2`, `app.expire_reservation_v2`, `app.correct_reservation_deposit_outcome` or `app.correct_reservation_deposit_disposition_v2` (owner answer to plan Q6); those functions are unchanged. `POST /reservations/{id}/security-deposit-dispositions`, and `POST /deposit-dispositions/{id}/reverse` for a Reservation disposition, answer 409 `RESERVATION_DEPOSIT_DRAFT_REQUIRED` and record nothing. The draft routes and the list route are built in this slice (as in slice 3a-1) so that the real HTTP Reservation tests keep testing outcomes over HTTP; their screens stay in slice 11c. The Reservation screen's cancel form no longer sends `outcome_id` or `refund_number` and always uses the cancel route.
- **Slice 3b details (review round 1, 2026-10-04):** `app.validate_deposit_receipt_reversal` (the revision 38 body plus one check) refuses a receipt reversal only while a Reservation Deposit draft is pending (owner answer to Q-2026-10-04-5); with no draft pending the reversal works as before, and the Reservation then holds nothing and leaves the waiting list. Receipts of a Reservation Deposit are recorded only at Reservation creation and a cancelled Reservation's version does not change, so the stale-draft comparison at confirmation is defensive and not expected to fire. A Refund number is checked against recorded Refunds only; two pending drafts of different Reservations may carry the same number, and the second confirmation is then refused with 409 and its draft stays pending (as in slice 3a). The confirm route's `Idempotency-Key` is required but not stored; the draft id is the idempotency identity, as for the slice 3a Refund confirm route (API-065). A client that retries a cancel sent before this slice with the earlier body (`outcome_id`, `refund_number`) gets 422 instead of a replay. A partial expression index on `app.financial_drafts ((payload->>'reservation_id'))` serves the one-pending-draft check and the waiting list. The preparer may also confirm when holding `financial.approve` (owner answer to plan Q4); both are recorded.
- **Updated tests (V1-056 slice 3b):** `tests/reservation_deposit_test_support.py` records and confirms the Deposit draft as the same person in the caller's transaction and returns the fourteen columns the earlier one-call functions returned. `test_reservation_lifecycle_migration.cancel` now cancels with `app.cancel_reservation_v3` and confirms the draft (its default outcome id is derived from the command key, so a repeat replays); every test that uses it keeps its assertions (`test_reservation_outcome_migration.py`, `test_customer_ledger_migration.py`, `test_financial_action_context_migration.py`, `test_deposit_api_migration.py`). Direct calls of `app.correct_reservation_deposit_outcome` in `test_reservation_outcome_migration.py` (two tests), `test_customer_ledger_migration.py`, `test_financial_action_context_migration.py` and `test_deposit_api_migration.py` (`test_ledger_includes_refund_and_refund_correction_history`) now record and confirm a correction draft; assertions unchanged. `app.validate_deposit_receipt_reversal` also refuses a receipt reversal while a Reservation Deposit draft for that Reservation is pending (Q-2026-10-04-5), tested by `test_receipt_reversal_is_refused_only_while_a_draft_is_pending`; no earlier test reverses such a receipt. Narrowed expectations, test names kept: `test_postgres_service_creates_extends_and_cancels_one_stable_reservation` expects `AWAITING_DECISION`; `test_expiration_uses_end_of_date_is_bounded_and_preserves_classification` calls `app.expire_reservation_v3`; `test_financial_history_is_append_only_and_runtime_is_least_privilege` expects the financial role to lack EXECUTE on the three one-call functions it checks, three of the four retired functions (the fourth, `app.correct_reservation_deposit_disposition_v2`, is checked in `test_reservation_deposit_draft_roles_and_retired_one_call_paths` in the new test file `tests/test_reservation_deposit_draft_migration.py`); `test_failure_concurrent_retry_and_replay_produce_one_logical_execution` expects no disposition after expiry; `test_http_detail_reads_real_postgres_receipt_lifecycle_and_outcome_evidence` expires its own Reservation and confirms the forfeiture draft before reading; `test_http_mutations_reach_real_postgres_with_security_replay_and_rollback` cancels through the cancel route, records and confirms the forfeiture draft and the correction draft over HTTP, expects only the `reservation.cancel` command for the cancel key, and checks that the cancel replay after the correction keeps the cancellation identity and version; `test_reservation_disposition_correction_is_atomic_replay_safe_and_reconstructable` records and confirms the correction draft twice at once and once more (one result) and expects 409 `RESERVATION_DEPOSIT_DRAFT_REQUIRED` from the reverse route. Unit tests: `test_reservation.py` (cancel and expire commands without outcome fields; the correction digest test checks the draft id scope; the capability test uses an actor without `reservations.cancel`), `test_reservation_api.py` (cancel answers `AWAITING_DECISION`; the earlier atomic route answers 409 also without `If-Match`; the time-bound test checks the draft record call), `test_deposit_api.py` (409 for a Reservation disposition correction), `test_initial_owner_bootstrap_cli.py` (four new routes). Frontend: `TEST-FE-181` and `TEST-FE-211` (`reservationClient.test.ts`) expect the cancel route, `TEST-FE-184` the new notice text. The head-revision assertions now expect `20261015_80`.
- **Owner answers to Q-2026-10-04-5 (2026-10-04), slice 3b round 2:** fix all four findings (Option A). `AWAITING_DECISION` is shown only when a Deposit is really held and no outcome record exists; a cancelled Reservation whose earlier outcome is done, or which holds nothing (for example its receipt was reversed), shows `PENDING_V1_031` as before and is not on the waiting list (`app.cancel_reservation_v3`, `app.expire_reservation_v3` and the Reservation read use the same test, through `app.reservation_deposit_held_cents`). Receipt reversal is refused only while a Reservation Deposit draft is pending. Round 3 is allowed once for this slice as an exception to the standing rule.
- **Reject and withdraw brought forward from slice 11b (V1-056 slice 3b, owner answer to Q-2026-10-04-5):** for Reservation Deposit drafts only, `POST /reservations/{reservation_id}/deposit-drafts/{draft_id}/reject` (a `financial.approve` holder, with a reason) and `.../withdraw` (the preparer only, with the draft's prepare capability and a reason), following plan Q5 and the slice 2 decision rules. The route, the service and the database (`app.reject_reservation_deposit_draft`, `app.withdraw_reservation_deposit_draft`, which check the Reservation, the Reservation variants and the prepare capability, then call the slice 2 decision functions) all check. They record a decision only and never move money.
- **Owner-approved tightening exception (migration `20261015_80_reservation_deposit_drafts`, 2026-10-04):** the financial role loses EXECUTE on `app.cancel_reservation_v2`, `app.expire_reservation_v2`, `app.correct_reservation_deposit_outcome` and `app.correct_reservation_deposit_disposition_v2`, approved as an exception like the `app.sign_lease` revoke in `20261009_74`. No application code path, worker or test calls them through the financial or runtime role; `app.confirm_reservation_deposit_draft` calls `app.correct_reservation_deposit_outcome` internally as the function owner, and tests only assert the missing privileges.
- **V1-056 slice 4, Unit cleaning rate and move-out cleaning charge (BR-UNIT-014, BR-MOVEOUT-013; owner answers to plan Q13 and Q14; migration `20261016_81`):** `app.unit_cleaning_rates` is an append-only chain per Unit: `app.set_unit_cleaning_rate` (runtime role, `property.manage`) records a rate in USD cents (0 or more) with a reason, superseding exactly the current rate the caller names, and `app.unit_cleaning_rate_current` reads it (`invoices.create` or `property.manage`). Staff record the cleaning charge themselves with `app.record_unit_cleaning_charge` (financial role, `invoices.create`), naming the rate they expect. It needs a recorded physical move-out and is refused when the Customer never moved in, when the Unit has no rate, when the rate is zero (no charge line, owner answer to Q14) or when the named rate is no longer current. It records the Unit's current rate as a Miscellaneous one-time charge source for the Primary Tenant through the existing `app.record_one_time_charge`, so its own Invoice is drafted and issued as any one-time charge: the Due Date is the issue date plus the Property's configured days, with the existing authorized override, and a reduction is a linked credit Adjustment with a reason. Append-only `app.unit_cleaning_charges` links the charge to the Lease (at most one per Lease), the Unit, the rate snapshot and the move-out event. A later rate change never changes a recorded charge. Owner-approved change to the plan (answer to Q-2026-10-04-7, Option B, 2026-10-04): the plan named a new one-time charge category `UNIT_CLEANING`; the owner approved keeping the cleaning charge on the existing `MISCELLANEOUS_CHARGES` category with the link table, as built. Invoice lists and the ledger show it as Miscellaneous with the description "Unit cleaning charge"; the link table identifies every cleaning charge, and the Settlement check (slice 8) reads it. The HTTP routes and screens stay in slice 11a. The head-revision assertions now expect `20261016_81`; only the expected revision changed.
- **Owner answers to Q-2026-10-04-8 (2026-10-04), hand-back month (BR-RENT-030, slice 5):** BR-RENT-030 applies to voluntary early leaving only (a verified BR-LEASE-021 termination with basis `VOLUNTARY_EARLY`); for terminations for a violation, the 30-day Rent nonpayment default, pet noncompliance, or unpaid Initial Rent or Security Deposit, staff use the existing VOID and Adjustment commands. The next month's Rent Invoice when the hand-back is between the 25th and the month end is treated like the hand-back month: unpaid, VOID with a reason; fully paid, the Property keeps it with no Refund and no credit, and the Customer may stay until that month ends; partly paid, the paid part is kept and a linked credit Adjustment with a reason removes the unpaid rest. Only the monthly Rent Invoices generated on the 25th are covered; the Initial Rent Invoice keeps its existing rules. Approved defaults: the date that counts is the actual move-out date of the current physical move-out record; Payments and Customer Credit applied both count as paid; the credit Adjustment removes each line's outstanding amount (Rent and fixed Service lines); one explicit staff command per Invoice, under `invoices.void` or `invoices.adjust`, with a reason; nothing runs automatically.
- **Owner answer to Q-2026-10-04-9 (2026-10-04), BR-RENT-026 amendment:** Option A. BR-RENT-026 (docs/002) and PR-RENT-026 (docs/003) gain the sentence: "Under BR-RENT-030, a fully paid Rent Invoice for the hand-back month, or for the next month when the hand-back is between the 25th and the month end, is kept as issued with no VOID, Refund or credit Adjustment (DL-068, Q-2026-10-04-8)." The unpaid (VOID) and partly paid (linked credit Adjustment) cases already follow BR-RENT-026.
- **V1-056 slice 5, hand-back month Rent Invoices (BR-RENT-030, BR-RENT-026, BR-LEASE-021; owner answers to Q-2026-10-04-8 and Q-2026-10-04-9; migration `20261017_82`):** `app.hand_back_rent_invoice_assessment` (runtime role, `invoices.read` and `leases.read` after review round 2) shows, for one monthly Rent Invoice generated on the 25th, whether the rule covers it and which action applies; it changes nothing. The rule covers only a Lease whose termination reads `VOLUNTARY_EARLY_VERIFIED` (through `app.lease_termination_invoice_readiness`) and has a current physical move-out record: a move-out before the 5th covers that month's Invoice, a move-out on or after the 25th covers the next month's Invoice; other dates, the Initial Rent Invoice and DRAFT or VOID Invoices are refused. Payments and Customer Credit applied count as paid: nothing applied gives `VOID`, nothing outstanding gives `KEEP` (kept as issued, the command records nothing), otherwise `CREDIT_ADJUSTMENT`. `app.resolve_hand_back_rent_invoice` (financial role) is one explicit staff command per Invoice with a reason, the expected action and the Invoice version; the application checks `invoices.void` for `VOID` and `invoices.adjust` for `CREDIT_ADJUSTMENT`. It re-assesses under the Invoice lock, refuses a changed action, then runs the existing `app.void_invoice` (whole Invoice, Rent and fixed Service lines) or one `app.adjust_invoice` credit Adjustment per line for that line's outstanding amount, so every earlier VOID and Adjustment rule still applies. Append-only `app.hand_back_rent_resolutions` records one resolution per Invoice with the move-out record, the hand-back date, the coverage, the action, the reason, the Adjustment ids and the stored response; a replay of the same key returns it and a different request with the same key is refused. Nothing runs automatically. The HTTP route and screen stay in slice 11a. The head-revision assertions now expect `20261017_82`; only the expected revision changed.
- **Slice 5 details (review round 1, 2026-10-04):** the assessment shown to an `invoices.read` holder carries no Lease, Customer, move-out or hand-back date identities (those stay in the internal `app.hand_back_rent_invoice_basis` and in the resolution record); review round 2 then also required `leases.read` for the assessment (see below). The command also takes the expected outstanding amount and refuses when it differs; it takes a per-key advisory lock so a concurrent repeat replays, locks the Lease row `FOR SHARE NOWAIT` so a move-out correction cannot change the basis while it runs, refuses an ambiguous current move-out record, derives the VOID and Adjustment keys and digests from the hand-back request so they cannot replay an unrelated command, checks that its own VOID event or Adjustments were recorded, stores the VOID event id and writes its own `invoice.hand_back_rent.resolved` audit event. A later move-out correction after a resolution is not blocked (that would change the physical move-out rules); the resolution keeps the record it used. Accepted: when nothing is applied the assessment shows `VOID` even if `app.void_invoice` will refuse (an active earlier Adjustment or Late-payment Charge); the command then reports the Invoice as invalid and staff use the existing commands.
- **Slice 5 details (review round 2, 2026-10-04):** the assessment answer still reveals whether the Lease has a verified voluntary early termination and which move-out window applies, so the assessment needs `leases.read` as well as `invoices.read`, as the existing termination Invoice readiness read does; the command keeps `invoices.void` or `invoices.adjust` as approved. Each credit Adjustment's source reference is `hand-back-rent-resolution:<resolution id>`, so the move-out record id is not shown to Invoice readers. A test shows that a notice date pointing at another month is ignored.
- **Owner answers to Q-2026-10-04-11 (2026-10-04), Deposit forfeiture (slice 6):** (1) the record that pays an Invoice from a Deposit is built once, in the Final Settlement slices, and the BR-DEP-027 Pet Deposit outcome (valid pet damage first, the rest refunded) moves there, including the Pet Deposit at unpaid-Initial-Rent and violation terminations. (2) The 30-day Rent nonpayment default is a forfeiture ground only when the termination cites `BR-LEASE-028` and a `THIRTY_DAY_SERIOUS_DEFAULT` event exists for that Lease on or before the termination date; otherwise the forfeiture is refused. (3) The direct Lease Deposit disposition route answers 409 like the Reservation route; the unpaid-Initial-Rent termination command stops forfeiting the Security Deposit and staff record a forfeiture draft that a `financial.approve` holder confirms. This change to the migration 70 function is approved as a relaxing change, made in a new migration; the migration 70 file is not edited.
- **Owner answers to Q-2026-10-04-10 (2026-10-04):** (a) the migration 70 command that may fail when two Invoice lines need a credit Adjustment is treated as a bug: first a test shows the failure, then the fix in the same new migration as the Q-2026-10-04-11 change, then the test passes; if the test shows no failure, nothing changes. (b) A physical move-out correction is refused, with an error that names the resolution, once a hand-back resolution relies on that move-out record; past decisions are never changed silently. A way for staff to correct such a case later is an open item for slice 12.
- **V1-056 slice 6, Lease Deposit forfeiture drafts (BR-DEP-018, 019, 022, 023, 026; BR-AUTH-010; owner answers to Q-2026-10-04-10 and Q-2026-10-04-11; migration `20261018_83`):** `app.record_lease_deposit_forfeiture_draft` (financial role, `deposits.dispose`) records a `DEPOSIT_FORFEITURE` draft of the whole held Lease Deposit; `app.confirm_lease_deposit_forfeiture_draft` (only with the `financial.approve` reference) runs the existing `app.record_lease_deposit_disposition_with_context` with the approver as actor, so every earlier Deposit rule applies; a draft whose Deposit state, held amount, ground or termination changed is refused as stale and stays pending; only one forfeiture draft per Deposit may be pending. The ground is worked out by `app.lease_deposit_forfeiture_source` from the termination record: `BR-LEASE-021` (Security, `BR-DEP-023`), `BR-DEP-022` with basis `CUSTOMER_VIOLATION` (Security and Pet), `BR-LEASE-005` with basis `UNPAID_INITIAL_OBLIGATION` (Security, now also when the Customer moved in, BR-DEP-026), `BR-LEASE-025` with basis `CUSTOMER_VIOLATION` (Security) and `BR-LEASE-028` with a `THIRTY_DAY_SERIOUS_DEFAULT` event on or before the termination date (Security); anything else is refused, and a Pet Deposit outside BR-DEP-022 is refused because its outcome is decided at Final Settlement (BR-DEP-027, slice 9). No HTTP route recorded Lease Deposit dispositions before this slice, but the service method `record_disposition` and the financial role's EXECUTE grants on the one-call disposition functions were a direct path; this slice closes them (owner answers to Q-2026-10-04-12 and Q-2026-10-04-13, below). The draft routes come with the draft screens (slice 11c). The unpaid-Initial never-moved-in resolution no longer forfeits the Security Deposit (approved relaxing change of the migration 70 function, made in this migration) and defers the constraints again before each credit Adjustment, so a two-line Initial Invoice can be credited: the new test failed without the fix (slice 6 run 2; run 1 is not valid evidence because files changed during it). `app.physical_move_out_record` refuses a correction (SQLSTATE P5N06, `PhysicalMoveOutResolutionReliance`) when a hand-back resolution relies on the record it would supersede, naming the resolution. Narrowed expectation, test name kept: `test_never_moved_in_with_nothing_paid_forfeits_voids_and_releases_the_unit` now expects no disposition from the resolution and the held Security Deposit amount unchanged by it. The head-revision assertions now expect `20261018_83`; only the expected revision changed.
- **Owner answers to Q-2026-10-04-12 and Q-2026-10-04-13 (2026-10-04), approved tightening exceptions in migration `20261018_83` (V1-056 slice 6):** like the slice 3b revoke, the financial role loses EXECUTE on `app.record_lease_deposit_disposition(uuid,uuid,uuid,text,uuid,uuid,uuid,bigint,date,text,text)` (migrations 27 and 56), `app.record_lease_deposit_disposition_with_context(uuid,uuid,uuid,text,uuid,uuid,uuid,bigint,date,text,text,uuid,text,bigint)` (migration 58) and `app.reverse_deposit_disposition_v2(uuid,uuid,uuid,text,uuid,uuid,text,text,text)` (migration 28). The functions are unchanged; the forfeiture draft confirm still runs the disposition function as its owner. `PostgresDepositService.record_disposition` and `reverse_disposition` check the capability and then refuse with `LeaseDepositDraftRequired` ("Lease Deposit forfeiture draft required", "Lease Deposit forfeiture reversal draft required") before any database call. For a Lease disposition, `POST /deposit-dispositions/{id}/reverse` checks `deposits.correct` and the browser mutation rules and answers 409 `LEASE_DEPOSIT_DRAFT_REQUIRED`; the Deposit ledger no longer offers `can_reverse` for any disposition. The forfeiture reversal draft (Staff prepare it, a `financial.approve` holder confirms it) is built in sub-slice 6b right after slice 6 is committed. The Deposit receipt reversal stays as it is, without a draft, like a Payment reversal. A move-out correction is not blocked because a Unit cleaning charge recorded the move-out event it relied on (owner agreed with the Q-2026-10-04-12 note). The refusal of a move-out correction that a hand-back resolution relies on (P5N06, owner answer to Q-2026-10-04-10 b) is also an owner-approved tightening in this migration. The read-only search of the backend (Q-2026-10-04-13) found no other grant or service method that keeps or moves Security, Pet or Reservation Deposit money without a draft and an approver: Reservation outcome and correction functions were revoked in migration 80, the one-call Refund functions in migration 78, the Signer Refund function is internal (migration 79), the moved-in unpaid-Initial resolution only records credit Adjustments, and Refund corrections stay without a draft by the answer to Q-2026-10-03-2.
- **Updated tests (V1-056 slice 6, owner answer to Q-2026-10-04-12):** `tests/lease_deposit_forfeiture_test_support.py` gives `forfeit_through_draft` (the real path: the person records the forfeiture draft under `deposits.dispose` and, holding `financial.approve`, confirms it; a repeat with the same key and disposition id replays both steps) and `record_disposition_as_owner` / `reverse_disposition_as_owner` (the one-call database functions with the same parameters and error mapping the service used, signed in as the migration owner). Tests whose subject is the forfeiture now use the real path; because a forfeiture is always the whole held amount (BR-DEP-026), the held amount they expect after it changes, and no other assertion changes: `test_deposit_disposition_migration.py::test_voluntary_security_context_links_exact_original_event_command_and_audit` expects 0 held (was 38000 after a 12000 one-call disposition) and the drafted disposition id; `test_deposit_disposition_migration.py::test_explicit_pet_noncompliance_source_supports_each_applicable_deposit` expects 0 held (was 49000 or 4000 after a 1000 one-call disposition) and also checks the context row (termination event, `BR-DEP-022`, the whole amount); `test_deposit_migration.py::test_lease_disposition_and_reversal_are_bounded_idempotent_and_auditable` expects 0 held (was 8000 after 12000), replays through the same key, and its reversal still restores 20000; `test_termination_deposit_migration.py::test_disposition_and_reversal_change_current_readiness_without_completing_finances` forfeits the same 50000 through the draft with unchanged assertions. Reversals in these tests run as the owner until slice 6b builds the reversal draft; 6b moves the tests whose subject is the reversal to that draft. The owner helper is used, with every assertion unchanged, where the disposition is setup for another subject: `test_customer_ledger_migration.py::test_ledger_pet_receipt_requirement_disposition_and_reversals_remain_separate`, `test_payment_reversal_context_migration.py::test_payment_reversal_context_database_shared_deposit_descendants_deduplicated_and_guarded`, `test_deposit_migration.py::test_same_key_replays_are_concurrency_safe_for_exposed_deposit_commands`, `test_deposit_migration.py::test_storage_triggers_reject_negative_required_amount_and_dependent_receipt_reversal`, `test_deposit_disposition_migration.py::test_context_is_append_only_and_only_financial_role_has_the_narrow_wrapper` and `test_deposit_financial_revision_migration.py::test_disposition_reversal_and_exact_replay_keep_separate_observation_and_saved_result`; in tests of earlier migration revisions: `test_deposit_disposition_migration.py::test_forward58_preserves_all57_history_function_identity_and_legacy_replay`, `test_lease_deposit_command_guards_migration.py::test_forward56_preserves_all55_history_and_original_successful_replay` and `test_deposit_financial_revision_migration.py::test_forward57_preserves_all56_rows_other_functions_and_historical_command_replay`; and in tests of the guards of the migration 58 database function that the draft confirm runs, which the draft path cannot reach with their inputs (a partial amount, a chosen or stale context, a raw replay with changed fields, two commands on one observation): in `test_deposit_disposition_migration.py` `test_unsupported_source_rule_or_relationship_rejects_without_financial_effects`, `test_old_fresh_entry_and_direct_storage_require_context_without_changing_history`, `test_net_zero_history_invalidates_fresh_posting_even_when_balance_is_restored`, `test_refund_history_participates_in_posting_observation`, `test_two_fresh_commands_cannot_both_consume_one_financial_observation`, and `test_repeatable_read_cannot_post_against_an_observation_before_concurrent_commit`, `test_raw_replay_rejects_changed_fields_even_with_the_old_digest` and `test_immediate_constraints_and_transaction_rollback_preserve_atomic_history`, whose raw connections now sign in as the owner; `test_deposit_migration.py::test_concurrent_lease_dispositions_cannot_exceed_one_held_balance`; and in `test_lease_deposit_command_guards_migration.py` `test_concurrent_lease_disposition_identity_is_serialized_and_atomic`, `test_disabled_lease_disposition_actor_is_rechecked_before_write_and_replay`, `test_lease_disposition_property_and_balance_failures_leave_no_effects` and `test_lease_disposition_audit_conflict_rolls_back_financial_and_command_rows`. Narrowed expectations, test names kept: `test_deposit_disposition_migration.py::test_context_is_append_only_and_only_financial_role_has_the_narrow_wrapper` expects the financial role to lack EXECUTE on the wrapper as well; `test_deposit_disposition.py::test_service_preserves_legacy_route_and_sends_complete_explicit_context` expects `record_disposition` to refuse with `LeaseDepositDraftRequired` and make no database call, with or without the context (its capability refusal is unchanged).
- **V1-056 slice 6 round-1 fixes (before review round 2):** new tests confirm a `BR-LEASE-025` draft, a `BR-LEASE-028` draft after a recorded `THIRTY_DAY_SERIOUS_DEFAULT` event, and a `BR-LEASE-005` draft after move-in; a refusal test covers key reuse, disposition-id reuse, an unknown Property, a confirm naming another Deposit, an unknown Deposit and a stale draft; the least-privilege test also checks the three revoked functions for the financial, runtime and bootstrap roles and PUBLIC; `tests/test_lease_deposit_forfeiture.py` shows that both services refuse a missing capability or bad input before any connection and checks the forfeiture service's error mapping; `LeaseDepositForfeitureService` maps P5801 and 23P01 to a conflict; the guarded `if amount > 0` in `test_unpaid_initial_resolution_no_longer_forfeits_and_the_draft_does` is an assertion. docs/005 API-042 records the 409 of the Lease reverse route.
- **V1-056 slice 6 review round 2 (independent and security, 2026-10-04):** no blocker; one should-fix (independent): the wrong-Property case uses an unknown Property id, so the Deposit and draft Property checks are not reached. Answer: the schema holds one Property (`properties_singleton_key_unique`), so any other Property id is unknown and refused first (P4501), as in the slice 3b isolation tests; the Deposit and draft Property checks stay as defence and the test says so. Notes taken before round 3: the draft refuses a reason that the confirmation would refuse (`app.lease_notice_text_valid`, same check as the disposition function); a disposition id held by any `DEPOSIT_FORFEITURE` draft is refused for a new draft (P5205); the Pet Deposit refusal names BR-DEP-024 and BR-DEP-027; tests for a Serious Default event of another Lease, two drafts recorded at once for one Deposit (one waits, one conflict), the reserved disposition id, the newline reason and the 403 without CSRF on the Lease reverse route; the unpaid-Initial narrowed test asserts the held amount unchanged; docs/005 says only the receipt reversal records anything on the reverse routes. Notes left for later, no change in slice 6: the BR-LEASE-028 date boundary (an event after the termination date) has no test, because the event date is always the recording day; the database trusts the passed `financial.approve` text as every draft kind does; the disposition audit names `deposits.dispose` with the approver as actor (the draft decision records `financial.approve`), to revisit in slice 6b; one person holding both capabilities may prepare and confirm (allowed by the owner answer to plan Q4).
- **Owner answer to Q-2026-10-04-14 (2026-10-04), slice 6 round 3:** Option A, text and docs only. The never-moved-in follow-up form and its confirmation (`frontend/src/LeaseManagement.tsx`) and docs/004 (unpaid-Initial resolutions), docs/006 (UI-042 follow-up forms, UI-076) and docs/007 now say that the resolution VOIDs or credits the Initial Rent Invoice and releases the Unit, while the Security Deposit stays held until a forfeiture draft is confirmed by a `financial.approve` holder; resolutions recorded before migration `20261018_83` keep the forfeiture they recorded. New frontend test TEST-FE-671 checks the form text and the confirmation. Backend runs 7 and 8 stand because no backend file changed. The use of the owner helper for tests of the migration 58 function's own checks is accepted. Moved to sub-slice 6b (ops/V1_056_PLAN.md): the disposition id held by a pending Reservation draft (`outcome_id`), a test for a disposition id used only by a recorded disposition, the stale status lines, and the draft-read filter by preparing capability.
- **V1-056 sub-slice 6b, Lease Deposit forfeiture reversal drafts (BR-AUTH-010, BR-DEP-019; owner answers to Q-2026-10-04-13 and Q-2026-10-04-14; migration `20261019_84`):** `app.record_lease_deposit_reversal_draft` (financial role) records a `DEPOSIT_FORFEITURE` draft with variant `LEASE_FORFEITURE_REVERSAL`, prepared under `deposits.correct` (Option A of Q-2026-10-04-13: "record under `deposits.correct`"; the draft table's two capability checks and the decision table's withdrawal check are relaxed to allow that capability, so the preparer withdraws such a draft with it, owner answer to Q-2026-10-05-15), for one confirmed Lease forfeiture, with a reason and an evidence reference (1 to 500 characters each, the reversal limits, checked with `app.lease_notice_text_valid`). `app.confirm_lease_deposit_reversal_draft` (only with the `financial.approve` reference) locks the Deposit row, refuses a draft whose Deposit changed since it was recorded (stale, stays pending), and runs the existing `app.reverse_deposit_disposition_v2` as its owner with the approver as actor, so every earlier reversal rule applies. The reversal row and its audit event name the approver with `deposits.correct` (the earlier reversal function sets that reference); the draft records the preparer, the draft decision records the approver with `financial.approve`, and the audit event's correlation id is the draft id, so the whole chain is traceable; whether those records should name `financial.approve` instead stays an owner item (ops/V1_056_PLAN.md slice 12), because it would change the earlier functions. Only one reversal draft per forfeiture may wait; a forfeiture already reversed is refused; a reversal id is refused when a recorded reversal or an audit event already uses it or any draft holds it as a reversal, correction, disposition or outcome id; the forfeiture and reversal confirms cannot confirm each other's drafts. The one-call reversal stays closed (slice 6); its HTTP route still answers 409 and the draft routes come with the draft screens (slice 11c). Moved here from slice 6 round 3 (owner answer to Q-2026-10-04-14): a new Lease forfeiture draft also refuses a disposition id that any `DEPOSIT_FORFEITURE` draft, in any state, holds as its `outcome_id` (a Reservation draft's outcome id becomes its disposition id; the one existing function changed in place, refusing only that identity, the same any-state rule slice 6 uses for `disposition_id`); a test for a disposition id used only by a recorded disposition; draft reads by the preparing capability (`app.financial_draft_resource_by_capability`, `app.list_financial_drafts_by_capability`, runtime role only; `FinancialDraftService` passes the prepare capabilities the reader holds, or all of them for a `financial.approve` holder), so a holder of only `reservation_deposits.dispose` cannot read Lease forfeiture drafts and the reverse. The earlier kind-based read functions stay unchanged and granted but no application module uses them (a test checks this); revoking them would be a tightening and is left to the owner. Stale status lines corrected (review record "Known gap", the four ops/NOW.md slice 6 stop lines).
- **Updated tests (V1-056 sub-slice 6b):** `tests/lease_deposit_forfeiture_test_support.py` adds `reverse_through_draft` (records the reversal draft and confirms it as the same person holding `financial.approve`). Tests whose subject is the reversal now use it, every assertion unchanged: `test_deposit_migration.py::test_lease_disposition_and_reversal_are_bounded_idempotent_and_auditable`, `test_termination_deposit_migration.py::test_disposition_and_reversal_change_current_readiness_without_completing_finances` and the reversal step of `test_deposit_financial_revision_migration.py::test_disposition_reversal_and_exact_replay_keep_separate_observation_and_saved_result` (its partial disposition stays on the owner helper). Reversals that are setup for another subject, tests of earlier migration revisions and the concurrent same-key replay of the one-call reversal function keep the owner helper (docs/010 slice 6 note). The head-revision assertions now expect `20261019_84`; only the expected revision changed.
- **Owner answer to Q-2026-10-05-15 (2026-10-05), sub-slice 6b round 2:** yes to the recommendation: migration `20261019_84` also relaxes `financial_draft_decision_shape` (a WITHDRAWN decision may carry `deposits.correct`), and tests cover withdraw by the preparer, refusal of another `deposits.correct` holder and of a wrong capability (permission error), reject by an approver, a new reversal draft after either, confirmation of a decided draft (conflict), both cross-flow directions, readers with only `deposits.correct` or only `deposits.dispose`, and two reversal drafts recorded at once. A database refusal by a rule reaches the user clearly: `FinancialDraftService` reports SQLSTATE 23514 and 23505 as `FinancialDraftConflictError` ("Financial draft decision conflicts with the draft's rules"), not as unavailable storage; 42501 stays a permission error (test `test_a_refused_withdrawal_is_a_conflict_not_unavailable_storage`). The round 3 reviewers list every capability check for preparing, withdrawing, rejecting and confirming a reversal draft. The approver naming in the disposition and reversal records is an owner item in slice 12; the plan's later migration numbers read "next free number".
- **Owner answers to Q-2026-10-05-16 (2026-10-05), wrong-Unit Payment move (BR-PAY-042, slice 7):** yes to all six recommendations. (1) The new allocation made by a confirmed move draft has its own allocation basis `WRONG_UNIT_MOVE`, exempt from the payer check (BR-PAY-025, including a normal Payment's identified Invoice) and the third-party intent check (BR-PAY-026); only that move, or a credit Adjustment's re-post of such an allocation on the same Invoice, creates it; BR-PAY-025 and BR-PAY-026 (docs/002) and PR-PAY-025 and PR-PAY-026 (docs/003) gain one sentence each pointing to BR-PAY-042. The Payment record, its payer and its Receipt never change; if the correct Invoice owes less than the moved allocation, the rest stays unallocated on the recorded payer under the normal Credit and Refund rules. (2) The one-Customer two-step path (one-call allocation reversal under `payments.allocations.reverse`, then one-call allocation under `payments.allocate` to the same Customer's Invoice on another Unit) stays an ordinary allocation correction under BR-PAY-029; no value moves between Customers; the move draft may still be used for one Customer. (3) Late-payment and Rent nonpayment rules are unchanged: after a move the first Invoice is simply unpaid again, the days count as before (Due Date for a Late-payment Decision, `app.rent_nonpayment_day_zero` for the milestones), the move records nothing about late payment, and nothing runs automatically; if the Customer whose Payment was misplaced got a Late-payment Decision only because of the mistake, staff may waive it. (4) The move is blocked while the Payment has any Customer Credit that is not reversed or any Refund that is not fully returned. (5) A draft may name a wrong allocation that was already reversed by the one-call reversal, when the Payment's unallocated value still covers the amount to move; confirmation then only posts the new allocation. (6) Only an allocation on an Invoice moves, and only to an Invoice; on the correct Invoice the amount is spread over its lines in the existing within-Invoice default order (BR-PAY-036: Rent, then Service charges, then other lines), worked out when the draft is recorded and stored in it; confirmation refuses the draft as stale if anything it relied on changed. A Payment reversal followed by a new Payment for the other Customer is not a move (new Payment and new Receipt).
- **Owner answer to Q-2026-10-05-17 (2026-10-05), a moved allocation and the one-call reversal (slice 7):** option 1. A confirmed move leaves the recorded payer on the Payment, so the one-call allocation reversal (`payments.allocations.reverse`) refuses an allocation with basis `WRONG_UNIT_MOVE`; otherwise the value could return to the payer's own Invoice through two one-call commands without a draft or an approver. A moved allocation changes only through another move draft confirmed by `financial.approve`, or through a credit Adjustment on its Invoice (the released value becomes that Invoice Customer's Credit, BR-CREDIT-014). While a moved allocation is active the Payment cannot be reversed (BR-PAY-012); a Payment that bounces after a move is an open item for slice 12.
- **V1-056 slice 7, wrong-Unit Payment move drafts (BR-PAY-042, BR-AUTH-010; owner answers to Q-2026-10-05-16 and Q-2026-10-05-17; migration `20261020_85`):** `app.record_payment_move_draft` (financial role, `payments.allocations.reverse`) records a `PAYMENT_MOVE` draft naming one Invoice allocation, the correct Invoice on another Unit (both Invoices must belong to Leases of different Units in the same Property), a reason (1 to 1,000 characters) and the two acknowledgements (1 to 2,000 characters each). The internal `app.payment_move_source` works out the move at recording and again at confirmation: the amount (the whole allocation, or what the correct Invoice still owes if less), its split over the correct Invoice's lines in the BR-PAY-036 order, and the correct Invoice's version and latest financial event; it refuses a Late-payment Charge allocation, a reversed Payment, an allocation already moved or released by a credit Adjustment, a correct Invoice with nothing outstanding, a Payment with Customer Credit not reversed or a Refund not fully returned, and an allocation already reversed by the one-call reversal when the Payment no longer holds its value. Only one draft per allocation may wait. `app.confirm_payment_move_draft` (only with the `financial.approve` reference) locks the Payment and both Invoices in the allocation commands' order, refuses a stale draft (it stays pending), reverses the wrong allocation with the approver as actor (unless already reversed), posts a `WRONG_UNIT_MOVE` allocation with the approver as `posted_by`, inserts the `app.payment_moves` link and records the decision, in one transaction; an exact repeat replays the stored result. The reversal and allocation rows keep their earlier authorization references (`payments.allocations.reverse`, `payments.allocate`), as the 6b reversal rows do; the draft records the preparer, the decision records the approver with `financial.approve`, and the allocation audit names the move. The allocation source guard (migration 39) is patched in place to exempt that basis from the payer and intent checks; deferred constraint triggers prove that every `WRONG_UNIT_MOVE` allocation has a confirmed move (or is a credit Adjustment's re-post of one) and that a moved allocation is reversed only by a move or a credit Adjustment (SQLSTATE P4904, reported by the allocation service as a conflict). Business-state refusals use SQLSTATE 55000 and reach the user as `PaymentMoveConflictError` (owner answer for slice 11c). The frontend allocation reversal context accepts the new basis, so the reversal context of a one-Customer move loads (TEST-FE-672); for a move to another Customer's Invoice the backend context function (migration 47) already refuses the target as outside the payer scope, which is acceptable because that reversal is always refused. No HTTP route or screen before slice 11d.
- **Updated test expectations (V1-056 slice 7):** the head-revision assertions in `test_migrations.py`, `test_billing_service_migration.py`, `test_credit_refund_read_migration.py`, `test_customer_ledger_migration.py`, `test_customer_ledger_read_migration.py`, `test_financial_action_context_migration.py`, `test_invoice_migration.py`, `test_late_payment_migration.py`, `test_lease_api_migration.py`, `test_lease_enforcement_api_migration.py`, `test_payment_reversal_context_migration.py`, `test_utility_api_migration.py`, `test_utility_consumption_migration.py` and `test_utility_meter_migration.py` now expect `20261020_85`; only the expected revision changed.
- **V1-056 slice 7 review round 1 (independent and security, 2026-10-05):** no blocker. Should-fix, all fixed before round 2: (security) a test that an unknown Property is not found for record and confirm and moves nothing (V1 holds one Property, `properties_singleton_key_unique`, so any other id is refused first with P4501, now mapped to `PaymentMoveNotFoundError`; the Payment, Invoice and draft Property checks stay as defence); (independent) the frontend payer-scope skip could never run because the backend context function refuses such a target, so it was removed and TEST-FE-672 now proves only the reachable case (the basis is accepted); a test of the BR-PAY-036 split (Rent in full, then the Service line, other lines untouched); tests that Credit recognized or a Refund made after the draft blocks confirmation (the draft stays pending); the credit-Adjustment test renamed to what it proves. Notes taken: the reversal and the new allocation share one instant (later than every event of both Invoices); one `payment_move.confirmed` audit event per move with the draft id as correlation id, the approver, `financial.approve` and the preparer; the record function takes the per-allocation lock only after the Property check; the constraint name is quoted; "too many lines" is a conflict (55000); the stored draft limit of 16,000 bytes (payload with both acknowledgements and the line split) is named in its refusal; concurrency tests for two drafts and two confirms at once; the Payment reversal test no longer pins the existing allocation service's "unresolved" mapping for that refusal. Answered in writing, no change: the database trusts the actor id and the `financial.approve` reference passed by the backend, as for every draft kind (DL-069 design: the database checks the active actor and Property, the application checks capabilities); the confirm locks the Payment before the Invoices like the existing allocation commands, while a credit Adjustment locks the Invoice first, so a rare deadlock surfaces as a conflict (40P01) with nothing written; the reversal context of a moved allocation is not offered by any screen until slice 11d, which must show the reversal as unavailable and point to a move draft.
- **Owner answer to Q-2026-10-05-18 (2026-10-05), slice 7 round 2:** finding 1 option (a): the one-call Credit reversal (`credits.reverse`, `app.reverse_customer_credit`) refuses a Customer Credit that a credit Adjustment released from a moved (`WRONG_UNIT_MOVE`) allocation when that Credit belongs to a Customer other than the Payment's payer (new BEFORE INSERT trigger `customer_credit_reversals_moved_payment` in migration `20261020_85`, SQLSTATE P4904, which `CustomerCreditService` reports as `CreditConflictError`); such Credits could not exist before this slice. The Credit stays with its Customer: applied to that Customer's Invoices or refunded through a Refund draft confirmed by `financial.approve`. A one-Customer move is not affected. Round 3 allowed with the three fixes and the notes; both round 3 reviewers search once more for any other path from a moved allocation to a different Customer without a draft and an approver and list what they checked.
- **V1-056 slice 7 review round 2 fixes (before round 3):** the confirmation forces the correct Invoice's refresh (`app.refresh_allocated_invoice(...,true)`), so its version advances even when the status stays the same and a command prepared before the move is stale (tested); a test proves the exemption for a normal Payment's identified Invoice (an ordinary allocation to the other Unit is refused for the same Customer, the confirmed move posts it); tests for the Credit reversal refusal (two Customers) and its absence for a one-Customer move; the audit key is `prepared_by_actor_id` (the audit reader accepts only classified keys); the credit-Adjustment guard is proven on its own (the released allocation stays refused after its Credit is reversed, while its replacement may be drafted); a Refund verified as fully returned no longer blocks the move; the draft-size refusal names both causes. Answered in writing: a proof of the BR-PAY-036 ranking with lines stored out of category order would need Service-source rows that no producer creates (every V1 Invoice producer numbers Rent first, and the order mirrors `app.payment_allocation_proposal`), so the split test proves Rent then Service on a generated Initial Rent Invoice.
- **Owner answers to Q-2026-10-05-19 (2026-10-05), slice 7 round 3 (correcting the Q-2026-10-05-18 entry above):** my option (a) of Q-2026-10-05-18 said a Credit released from a moved allocation to another Customer could be refunded through a Refund draft; that was wrong, because the existing Refund rules (migration 41) pay a Credit Refund only to a recipient who is both the Credit's Customer and the Payment's payer. Answer: keep the refusal; such a Credit can only be applied to its Customer's Invoices; the Refund of such a Credit to the Invoice Customer who is not the payer is required by BR-CREDIT-014 and is planned in slice 9 (Final Settlement needs it) as a Refund draft confirmed by `financial.approve` (it is missing today for third-party Payments too, since migration 67); the lasting block it causes (answer 4 counts any Credit that is not reversed, so no other allocation of that Payment can move and the Payment cannot be reversed) is a slice 12 item. The third-party gap found by both reviewers is fixed: the Credit reversal refusal now applies unless the Payment is a normal Customer Payment and the Credit belongs to its payer, because a third-party Payment's unallocated value can only go to its identified Lease or Invoice of another Customer (test of that chain). A test shows that a Credit Refund of another Customer's moved-value Credit is refused and records no Refund. One more fresh review of these changes, with the same path search, before the commit.
- **V1-056 slice 7 extra review (owner-approved, after round 3; independent and security, 2026-10-05):** no blocker and no should-fix; both reviewers listed every path checked (allocation reversal and post, another move draft, credit and debit Adjustments with the hand-back, unpaid-Initial and forfeiture callers, adjustment reversal, VOID, Payment reversal, Credit recognition, application, application reversal, reversal, Refund drafts, corrections, verified returns, correction reversals, Deposit receipts and dispositions, Pet Refund to a Signer, Late-payment Charges, Final Settlement, direct writes and grants) and found no path that moves value from a moved allocation to a different Customer without a draft and a `financial.approve` holder. Notes taken as wording only: a Credit of a Customer other than the payer can only be applied (to Invoices or Late-payment Charges), while a third-party payer's own Credit can still be refunded to the payer through a Refund draft; the earlier rationale "a third-party Payment's value can only go to its identified Lease or Invoice" is imprecise (once that Lease owes nothing, the value may also become the payer's Credit or a Refund to the payer), the conclusion is unchanged. Notes moved to the plan: slice 11d shows the Credit reversal as unavailable when it would be refused; slice 9 maps the Credit Refund recipient refusal (23514, today reported as unresolved) to a conflict; slice 12 tightens two tests (two-step Refund refusal with its exact cause; grants test also for `prm_bootstrap` and security definer).
- **Owner answers to Q-2026-10-05-20 (2026-10-05), Final Settlement (V1-056 slice 8):** (1) A Deposit may pay a Late-payment Charge of the Settlement, like any other debt; docs/004 DB-DEP-005, DB-DER-007 and DB-DER-009 are amended to match. (2) The Security Deposit is kept only where the termination record gives a forfeiture ground (`app.lease_deposit_forfeiture_source`, slice 6) and its forfeiture draft is confirmed; every other termination, on the Lease End Date or not, follows DL-032. (3) Strict order: Customer Credit before Deposits, pet damage before any Pet Deposit Refund, and where DL-032 applies the Security Deposit pays open debt before any Security Deposit Refund; no Refund is made while this Lease still has open debt that a Deposit could pay. (4) At unpaid-Initial, non-pet violation and 30-day default terminations the remaining Pet Deposit pays other debt only when the Customer chooses it; the Customer's agreement is recorded as text (who, the date, how), like the slice 7 acknowledgements, together with the staff reason. (5) Changed from the recommendation: the Settlement includes the Invoices of every Signer of the Lease, and the Deposits may pay all open debt of the Lease, whoever is named on the Invoice, in the DL-032 order, because the Deposit protects the whole Lease; debt left after that stays on the ledger of the person named on the Invoice. The owner asked to stop if this conflicts with a written rule or the ledger design: it fits the ledger design, but it conflicts with the text of BR-SETTLE-016 and the DL-069 "Joint Signers" line (settlement debt on the Primary Tenant's ledger), so the work stopped again before any code (Q-2026-10-05-21, which also asks about the BR-DEP-014 wording and one case left open by answers 3 and 4). (6) Every Late-payment Decision that the existing late-payment review allows for a Settlement Invoice must be recorded before closure; the preview shows a missing one as a blocking issue. (7) Approved tightening: after a Settlement closes, one-call changes to its obligations are refused (VOID, Adjustments including the hand-back and unpaid-Initial resolutions, Late-payment Decisions and Charge corrections, and new charges on the Lease) until the slice 10 correction drafts exist; Payments, allocations, Credit applications and their ordinary reversals stay open, so the Customer can still pay the debt.
- **Owner answers to Q-2026-10-05-21 (2026-10-05), Final Settlement (V1-056 slice 8):** yes to all three recommendations. (1) BR-SETTLE-016 (docs/002) gains: debt left on an Invoice issued to another Signer of the Lease stays on that Signer's Customer Ledger, because an Invoice's Customer never changes; at Final Settlement the Lease's Deposits may pay it in the DL-032 order. The DL-069 "Joint Signers" line is unchanged; this entry links it. (2) BR-DEP-014 (docs/002) and PR-DEP-014 (docs/003) now say that Deposits may be applied to Invoice obligations and Late-payment Charges only as part of the Final Settlement process after Lease termination. (3) BR-DEP-027 (docs/002) gains: at unpaid-Initial, non-pet violation and 30-day default terminations the remaining Pet Deposit pays other debt only when the Customer chooses it, recorded as text (who, the date, how) with the staff reason; otherwise the rest is refunded, and the debt stays. Without the Customer's choice that Pet Deposit is not a Deposit that could pay the debt, so answer 3 of Q-2026-10-05-20 does not hold back its Refund. The DL-013 staff step stays at a normal Lease end and at voluntary early leaving: authorized staff may apply the remaining Pet Deposit with a reason when the Customer will not pay, so there the rest pays open debt before any Pet Deposit Refund.
- **V1-056 sub-slice 8a-1, Final Settlement record and Deposit application record (BR-SETTLE-001, BR-SETTLE-009, BR-SETTLE-010, BR-SETTLE-012, BR-DEP-014, BR-DEP-026, BR-DEP-027; owner answers to Q-2026-10-05-20 and Q-2026-10-05-21; migration `20261021_86`):** `app.final_settlements` holds one Final Settlement per TERMINATED Lease (DB-SETTLE-001, plus the Property). `app.start_final_settlement` (financial role; the application checks `final_settlements.prepare`) opens it with the actual termination date and the current physical move-out date as snapshots, writes a `final_settlement.started` audit event and has no financial effect; for a Lease that already has one it returns the existing Settlement unchanged, and for a Lease that is not TERMINATED it refuses as a conflict (55000). A guard allows exactly one change, the closure that the confirm (sub-slice 8e) will write; a closed Settlement is never changed again and no Settlement is ever deleted. `app.deposit_applications` (DB-DEP-005 with a target kind: an Invoice line or a Late-payment Charge of the Settlement Lease, whoever is named on the Invoice) records a Deposit application in the stages `PET_RELATED_FIRST`, `SECURITY_EXPLICIT` and `PET_REMAINDER_EXPLICIT`. No role may write it; the internal `app.post_deposit_application` (no grant) is the only writer and records the `financial.approve` reference and a `deposit_application.recorded` audit event; the Settlement confirm (8e) will call it. Checks: the Settlement is open and its Lease TERMINATED; the Deposit belongs to that Lease and its type matches the stage; a kept Deposit is never applied (the termination record gives a forfeiture ground through the slice 6 rule, now the shared `app.lease_deposit_forfeiture_rule`, or the Deposit has an active disposition); the first Pet stage pays only a Damage charge line whose inspection finding is pet-related on the current inspection; the stages keep the DL-032 order and the order number only grows; the amount stays within the held Deposit and the open obligation, also at every past moment of the Deposit's history; the application is later than every earlier event of the target and of the Deposit. A Deposit application counts as paid wherever balances are derived: `app.invoice_line_application_value_at` (Invoice line outstanding, Invoice status, the Invoice resource and `app.adjust_invoice`), `app.late_payment_charge_application_summary` (the Late-payment Charge balance; a new `deposit_total_usd_cents` key and `DEPOSIT_APPLICATION` items), `app.allocation_target_latest_at`, `app.deposit_balance_events` and `app.deposit_snapshot` (the held amount), the termination Invoice readiness (new line field `deposit_applied_usd_cents`, also checked by the Python reader) and the hand-back basis (applied value through the shared function). The Invoice version advances with each application. VOID and Adjustments (55000) and Late-payment Charge corrections (P4603, the Late-payment conflict code) refuse an obligation a Deposit application paid, and the Deposit receipt reversal trigger also refuses while the Deposit has an application; these concern a record that did not exist before, so no earlier input is refused. The Payment reversal and financial action contexts (migrations 46 and 47) already report a Payment whose Deposit has an application as unsupported; a test now proves it with a real application. Deposit application reversals are not built (plan Q15). The Customer Ledger projection of Deposit applications and the Deposit's own history event (the Deposit ledger read) follow in sub-slice 8a-2; until then no application can exist outside tests, because no role can write one. The Late-payment Charge resource still shows `payment_total` and `credit_total` only; its `deposit_total` is shown with the Settlement screens (slice 11e). The head-revision assertions now expect `20261021_86`; only the expected revision changed.
- **Updated tests (V1-056 sub-slice 8a-1):** earlier tests that assumed `app.final_settlements` and `app.deposit_applications` do not exist, test names kept: `test_deposit_api_migration.py::test_split_departure_and_review_are_idempotent_and_create_no_refund`, `test_deposit_migration.py::test_pet_refund_qualification_keeps_signed_lease_and_creates_no_refund_or_application`, `test_pet_refund_migration.py::test_pet_refund_reuses_review_preserves_lease_and_exact_replay_audit` and `test_customer_ledger_migration.py::test_ledger_security_refund_coordinated_correction_keeps_liability_distinct` now expect no Final Settlement and no Deposit application for their Lease, Deposit or Customer instead of no table. The three contract tests that simulated the future table (`test_deposit_api_migration.py::test_future_deposit_application_dependency_is_fail_closed_and_reversal_aware`, `test_payment_reversal_context_migration.py::test_payment_reversal_context_database_unsupported_future_application_is_explicit` and `test_financial_action_context_migration.py::test_financial_action_context_database_future_deposit_application_is_explicit`) run unchanged on a database migrated only to `20261020_85` (`tests/pre_settlement_test_support.py`); the head behavior is tested in `test_final_settlement_migration.py`. `test_termination_invoice_migration.py::test_forward59_preserves_every58_table_function_and_genuine_legacy_source` reads the revision 59 readiness through its database function as the runtime role, because the current reader needs the migration 86 field; the asserted facts are unchanged. `test_termination_invoice.py` fixtures carry `deposit_applied_usd_cents: 0`.
- **V1-056 sub-slice 8a-1 review round 2 (independent and security, 2026-10-05):** no blocker; security no should-fix; independent two should-fix, both fixed: the closure test now also sends a full closure that changes `started_at`, the termination date snapshot or the move-out snapshot and expects the refusal (BR-SETTLE-012); the Deposit's own history reader (the Deposit ledger read) is named in sub-slice 8a-2. Notes taken: the human-approver check is also in the Deposit application trigger, so every future writer inherits it, with a test using a real billing service identity; docs/004 says the Customer's choice and the staff reason for the remaining Pet Deposit are checked by the draft and the confirm (8c, 8e); two traceability wordings corrected (BR-SETTLE-017 removed from a test that does not check the Customer's choice). The human-approver refusal uses 42501, the same code a missing grant gives; both are refusals and the service reports them as a permission error, so a missing grant fails closed. Other notes moved to ops/V1_056_PLAN.md (slice 8 notes).
- **Owner answers to Q-2026-10-05-22 (2026-10-05), Deposit receipt reversal (V1-056 sub-slices 8a-1 and 8r):** (a) Option (a): a Deposit receipt reversal becomes a draft. Staff with `deposits.correct` prepare it and a `financial.approve` holder confirms it, like the Lease forfeiture reversal (sub-slice 6b). This approved tightening replaces the earlier answer to Q-2026-10-04-13 that the Deposit receipt reversal stays as it is, without a draft; that earlier answer no longer applies. Reason (security review of 8a-1, round 1): a one-call receipt reversal returns the receipt's value to its Payment, which stays RECEIVED, and a one-call allocation or Credit recognition then lets Deposit money pay debt without a draft or an approver, also during an active Lease and while a Lease forfeiture draft is pending. (b) It is built as sub-slice 8r, right after 8a-1 is committed. (c) Sub-slice 8r also checks the Reservation Deposit receipt reversal from slice 3b and closes it in 8r if it can free money the same way, or the 8r report says why it cannot. (d) 8a-1 continues with the five independent round-1 should-fix items and the cheap notes, one backend unit run and one full PostgreSQL run, then review round 2 under the standing round-3 rule; the security finding S1 counts as answered by 8r.
- **V1-056 sub-slice 8a-1 review round 1 fixes (migration `20261021_86`, before commit):** the Payment reversal context (migration 46, result view) and the financial action context (migration 47) now subtract the Late-payment Charge's active applications from `app.late_payment_charge_financial_position`, so a Deposit application counts in their remaining balance (both functions changed in place, the correction formula unchanged; identical for every record without a Deposit application). The refusal of a Late-payment Charge correction after a Deposit application uses P4603, which the Late-payment service already reports as a conflict; the only writer inserts after its replay lookup, so the code cannot hide a successful earlier request. `app.post_deposit_application` refuses an unknown target (P0002), an unknown target kind (22023) and an approver who is not a person (42501). docs/004 DB-DEP-005 now says the trigger checks the stage against the Deposit type and the stage order, and that the draft and the confirm (8c, 8e) check the prior-stage prerequisites. New tests: the BR-LEASE-025, BR-LEASE-028 and BR-LEASE-005 grounds keep the Security Deposit through the shared rule while the Pet Deposit stays applicable; a Deposit pays an Invoice of another signed Signer and the Invoice keeps its Customer; both Payment contexts count a Deposit application on a Late-payment Charge; a Charge correction after an application is a service conflict; the Invoice resource and the target chronology with an application; least privilege also for TRUNCATE, REFERENCES, TRIGGER and PUBLIC; the closed-Settlement refusal now uses a real Deposit and line. Not tested: the active-disposition branch of the kept-Deposit check, because no current writer can give a Deposit without a forfeiture ground an active disposition (the slice 6 draft refuses it); the branch stays as a defensive check for dispositions recorded by the earlier one-call functions.
- **V1-056 sub-slice 8r, Deposit receipt reversal drafts (BR-AUTH-010; owner answer to Q-2026-10-05-22; migration `20261022_87`):** `app.record_deposit_receipt_reversal_draft` (financial role, `deposits.correct`) records a `DEPOSIT_FORFEITURE` draft with variant `DEPOSIT_RECEIPT_REVERSAL` for one receipt of a Lease or Reservation Deposit, with a reason (1 to 500 characters); it has no financial effect. `app.confirm_deposit_receipt_reversal_draft` (only with the `financial.approve` reference) locks the Deposit row, refuses a draft whose Deposit changed since it was recorded (stale, stays pending), records the draft decision and then runs the existing `app.reverse_deposit_receipt_v2` as its owner with the approver as actor, so every earlier receipt reversal rule applies; an exact repeat replays the stored result. The reversal row and its audit event name the approver with `deposits.correct`, as in sub-slice 6b; the draft decision names `financial.approve`. The financial role loses EXECUTE on `app.reverse_deposit_receipt_v2` (the approved tightening); `PostgresDepositService.reverse_receipt` checks the capability and refuses with `DepositReceiptReversalDraftRequired`; `POST /deposit-receipts/{id}/reverse` checks `deposits.correct` and the browser mutation rules and answers 409 `DEPOSIT_RECEIPT_REVERSAL_DRAFT_REQUIRED`; the Deposit resource and ledger no longer offer a one-call receipt reversal. A new receipt reversal draft is refused while a `REFUND` or `DEPOSIT_FORFEITURE` draft for the Deposit or its Reservation is pending, and the receipt reversal guard (the migration 80 body, same two kinds) now also matches a pending draft's `deposit_id`, so a confirmation is refused while another such draft for that Deposit waits; the Final Settlement drafts (8c, 8e) must extend both checks (plan); a reversal id is used once (recorded reversals, audit events, every draft's reversal, correction, disposition and outcome ids). The other draft confirms refuse this variant (they check their own variant and capability). Owner answer (c): the slice 3b Reservation Deposit receipt reversal could free money the same way, because a Reservation Deposit receipt is funded by a Payment of the Reservation's Customer (`NORMAL_CUSTOMER`) whose freed value a one-call allocation or Credit recognition could use; it is closed by the same draft. The draft routes come with the draft screens (slice 11c).
- **Updated tests (V1-056 sub-slice 8r):** `tests/deposit_receipt_reversal_test_support.py` gives `reverse_receipt_through_draft` (the real path) and `reverse_receipt_as_owner` (the earlier one-call function with the same parameters and error mapping the service used, signed in as the migration owner). These tests used the one-call reversal as setup or test the earlier function's own rules, which the draft confirmation runs unchanged, and now call it as the owner with no other change: `test_customer_ledger_migration.py::test_ledger_pet_receipt_requirement_disposition_and_reversals_remain_separate`, `test_customer_ledger_read_migration.py::test_ledger_runtime_deposit_receipt_reversal_keeps_held_liability_and_payment_separate`, `test_deposit_disposition_migration.py::test_net_zero_history_invalidates_fresh_posting_even_when_balance_is_restored`, `test_payment_reversal_context_migration.py::test_payment_reversal_context_database_shared_deposit_descendants_deduplicated_and_guarded` and `::test_payment_reversal_context_database_unsupported_future_application_is_explicit`, `test_financial_action_context_migration.py::test_financial_action_context_database_shared_deposit_guard_changes_source_context` and `::test_financial_action_context_database_future_deposit_application_is_explicit`, `test_termination_deposit_migration.py::test_unreceived_liability_then_later_receipt_and_reversal_are_separate_observations`, `test_deposit_migration.py::test_adjustments_and_receipt_reversals_preserve_history` and `::test_same_key_replays_are_concurrency_safe_for_exposed_deposit_commands`, `test_deposit_financial_revision_migration.py::test_required_corrections_and_receipt_reversal_advance_even_at_original_net_value`, and `test_pet_refund_migration.py::test_pet_verified_returns_reconcile_receipt_ledger_eligibility_and_reversal` (which also expects the ledger's `can_reverse` to be false for the deposits.correct holder). The `reverse_receipt` helper of `test_reservation_deposit_draft_migration.py` runs the one-call function as the owner, so its pending-draft guard is still tested there. `test_deposit_api_migration.py::test_real_http_reads_history_and_splits_departure_from_review` expects the route's 409 `DEPOSIT_RECEIPT_REVERSAL_DRAFT_REQUIRED`, reverses the receipt through the draft and reads the Deposit; its replay and idempotency-key checks of the route's reversal are removed because the route no longer records a reversal. `test_deposit_api.py::test_linked_reversals_and_split_pet_refund_qualification_preserve_sources` expects the route's 409 and no command sent to the flow; `test_deposit_api.py::test_reservation_disposition_correction_requires_replacement_and_exact_capabilities` expects `can_reverse_receipt` to be false. The head-revision assertions now expect `20261022_87`; only the expected revision changed.
- **V1-056 sub-slice 8r review round 1 (independent and security, 2026-10-05):** no blocker; three should-fix, all fixed: docs/004 and this log name the two draft kinds the pending-draft checks see, and the plan makes 8c and 8e extend them; a test reverses the Payment of a returned transfer after the receipt reversal draft is confirmed (refused while the draft is only pending, and a rejected draft changes nothing); the least-privilege test also covers the earlier function `app.reverse_deposit_receipt`, the patched guard (owner kept) and INSERT, UPDATE, DELETE and TRUNCATE on `app.deposit_receipt_reversals`. Notes taken: this confirm refuses a Reservation draft id; the draft-kind comment in `financial_draft.py`. The adjustment date in the stale test comes from the database clock in Asia/Phnom_Penh, as in the 8a-1 tests. Other notes moved to the plan (11c screens, slice 12).
- **V1-056 sub-slice 8r review round 2 (independent and security, 2026-10-05):** no blocker; security no should-fix; independent one should-fix, fixed: the main test now has another person confirm, so the reversal row, its audit event and the draft decision name the approver while the draft names the preparer, and it shows the database refuses the record function with `financial.approve` and the confirm function with `deposits.correct` (42501). Notes taken: the migration text names the two draft kinds the pending-draft checks see; the HTTP test replays the draft confirmation after later Deposit activity (the replay the earlier route test checked); a unit test shows the receipt reverse route answers 404 without `deposits.correct`, 403 without the browser mutation proof and only then 409. Other notes moved to the plan (11c routes and docs/006 UI-073; slice 12 exact grantee sets).
- **V1-056 sub-slice 8r review round 3 (independent and security, 2026-10-05):** no blocker and no should-fix, so 8r is committed under the standing round-3 rule; the notes are in the review record and the plan (slice 12 and 11c).
- **Owner answers to the four points of the V1-056 sub-slice 8r report (Q-2026-10-05-23, 2026-10-05):** (1) Accepted: until slice 11c a Deposit receipt reversal works only through the service (`DepositReceiptReversalService`), and the screen hides the action; there are no real users yet. (2) Approved tightening: while a Deposit receipt reversal draft is pending, the confirmation of a Refund draft or a forfeiture draft for the same Deposit is refused; recording those drafts stays allowed. It is built in sub-slice 8a-2 with a test, because it stops money going out that may never have been received. (3) A Security Deposit whose forfeiture was reversed is held again, as if that forfeiture never happened. At Final Settlement it follows DL-032 (it pays open debt and the rest is refunded), unless a new forfeiture draft is confirmed. It must never be stuck with no way to apply or refund it. If this conflicts with a written rule, the work stops and asks the owner before sub-slice 8c (the check is in Q-2026-10-05-24). (4) Agreed: sub-slices 8c and 8e extend the receipt reversal pending-draft checks to the Final Settlement drafts.
- **V1-056 sub-slice 8a-2, Deposit applications in the Customer Ledger and the Deposit history (BR-SETTLE-009, BR-SETTLE-016, BR-LEDGER-003, BR-LEDGER-006; owner answer 2 to Q-2026-10-05-23; migration `20261023_88`):** a new Customer Ledger projection version adds the event `DEPOSIT_APPLIED` (event order 75) for each Final Settlement Deposit application. Its Deposit-owner component reduces the Security or Pet Deposit held; its obligation component, on the Customer named on the Invoice or Late-payment Charge, reduces that Invoice line or Charge. Both carry the same evidence (application, Settlement, stage, order, Deposit type, Deposit owner, target kind, target Customer, reason), so one Customer gets one header with both components, and a Deposit that pays another Signer's debt shows on both ledgers, each with its own component (owner answers to Q-2026-10-05-20 and Q-2026-10-05-21). Every earlier component is unchanged. `app.customer_ledger_page` accepts the new kind as a history filter; the Python reader and the frontend client know it ("Deposit applied"). The Deposit's own history (`GET /deposits/{id}/ledger`) lists each application as `APPLICATION_INVOICE_LINE` or `APPLICATION_LATE_PAYMENT_CHARGE`, governed by the Final Settlement, through the bounded `app.deposit_application_history(property, deposit)`; the runtime role executes that function only and still has no privilege on `app.deposit_applications`. Owner answer 2 to Q-2026-10-05-23 (approved tightening): a trigger on `app.financial_draft_decisions` refuses (55000) the confirmation of a `REFUND` or `DEPOSIT_FORFEITURE` draft whose payload names a Deposit (or its Reservation) while a receipt reversal draft for that Deposit is pending; recording stays allowed and the refused draft stays pending. The Lease forfeiture reversal draft (6b) and the receipt reversal draft are not Refund or forfeiture drafts and are not affected. The Refund service reports this refusal as a conflict (it reported any other 55000 as "outcome unresolved"); the Reservation and Lease forfeiture services already report 55000 as a conflict. Decision on the two 8a-1 notes about Deposit identifiers visible to readers (`app.late_payment_charge_application_summary` items and `app.deposit_has_active_application`, both granted to the runtime role without a Property check): no change in 8a-2; they move to slice 11e with the Late-payment Charge `deposit_total` and the Settlement screens.
- **Updated tests (V1-056 sub-slice 8a-2):** the head-revision assertions now expect `20261023_88`; only the expected revision changed. `test_customer_ledger.py::test_ledger_equal_time_order_and_filter_are_deterministic_across_timezones` expects 24 kinds instead of 23, and `CustomerAccountLedger.test.tsx` TEST-FE-564 expects 25 history rows (24 events plus the header) instead of 24; test names kept. `test_migrations.py::test_v1_038_upgrade_projects_legacy_pet_departure_authorization` reads the legacy departure's authorization with the same derivation the Deposit ledger read uses, on its database at revision `20260831_37`, because the current ledger read also needs migration 88's function; the asserted fact is unchanged. The ledger read's legacy branch (a departure that only a combined `deposit.pet_refund.qualify` command recorded) is now tested at head through the production read by `test_pet_refund_migration.py::test_the_deposit_history_reads_a_legacy_combined_qualification_departure` (review round 2). The setup of `test_final_settlement_migration.py::test_a_deposit_pays_an_invoice_of_another_signer` moved into the helper `another_signer_invoice`, unchanged, so the new ledger test reuses it. The new Pet Refund wait test is in `test_pet_refund_migration.py`, which runs after `test_lease_migration.py`, because `test_nonbilling_lease_event_term_and_pet_stores_are_append_only` counts every Pet Refund review of the shared test database (run P1 failed on that count while the new test sat in an earlier module).
- **V1-056 sub-slice 8a-2 review round 1 (independent and security, 2026-10-05):** no blocker. Should-fix, all fixed: (both reviewers) a race: the receipt reversal draft recorder held only its advisory lock, while the Pet Refund and Reservation Deposit confirms lock only the Deposit row, so a Refund draft recorded after the recorder's pending-draft check could be confirmed before the receipt reversal draft committed; migration 88 now also patches `app.record_deposit_receipt_reversal_draft` to lock the Deposit row after its advisory lock (the same order as the receipt reversal confirm), and a two-connection test shows the Pet Refund waits and is then refused. (Independent) boundary tests: a withdrawal and a rejection of a waiting forfeiture draft pass while the receipt reversal draft is pending, and a Lease forfeiture reversal (6b) is confirmed while it is pending. (Independent) the `test_v1_038_upgrade_projects_legacy_pet_departure_authorization` change replaces a production read by the same derivation in SQL; answered in writing in round 1 (the database is held at revision 37 by design, so no production read can use an object of migration 88 there); round 2 found that answer inadequate because no head test reached the legacy branch, so a head test now reads such a departure through the production read (see the updated-tests note). Notes taken: the trigger compares uuids so it can use the Deposit indexes; the both-pending case is described in docs/004; the another-Signer test asserts the exact header count; static check outputs are saved with the runs. Notes moved to the plan (slice 12): the Refund service recognises this refusal by its message text; test-order coupling on the global Pet Refund review count in `test_nonbilling_lease_event_term_and_pet_stores_are_append_only`. Not changed: the Late-payment Charge component has no category or description, like the Payment allocation components; the bounded history read has no actor parameter (the Deposit read checks the capability for the Deposit's Property first, and the existing Deposit history read uses direct table grants).
- **V1-056 sub-slice 8a-2 review round 2 (independent and security, 2026-10-05):** no blocker; security no should-fix; independent one should-fix, fixed: the legacy combined-qualification branch of the Deposit ledger read lost its only production-code test when `test_v1_038...` changed; a head test now covers it (above). Notes taken: the migration text and docs/004 state the exact guarantee (no Refund or forfeiture confirmation commits while a receipt reversal draft for the Deposit is pending or still being recorded) and that it relies on READ COMMITTED, the isolation every confirmation uses; the race test now checks that the Pet Refund waits for the recorder's own process (`pg_blocking_pids`). Note moved to the plan (slice 12): no concurrent test for the Reservation Deposit confirmation, which relies on the same Deposit row lock.
- **V1-056 sub-slice 8a-2 review round 3 (independent and security, 2026-10-05):** no blocker and no should-fix, so 8a-2 is committed under the standing round-3 rule; the notes (isolation hardening of the receipt reversal wait, one docstring wording, extra least-privilege and concurrency tests) are in the review record and the plan (slice 12).
- **Owner answer to Q-2026-10-05-24 (2026-10-05), a reversed forfeiture at Final Settlement (V1-056 sub-slices 8b, 8c and 8e):** yes to the three recommendations. (1) BR-DEP-026 (docs/002) gains one sentence: when a confirmed forfeiture of the Security Deposit is reversed, the Deposit is held again; at Final Settlement it follows DL-032 (it pays open debt and the rest is refunded) unless a new forfeiture draft is confirmed (owner answer 3 to Q-2026-10-05-23). BR-DEP-023 (docs/002) points to it, and the BR-DEP-026 note under PR-DEP-023 (docs/003) says the same. (2) The Settlement preview (8b) and the confirm (8e) handle three cases for a Deposit whose termination record gives a forfeiture ground: no confirmed forfeiture yet is a blocking issue; a confirmed, active forfeiture keeps the Deposit, which is never applied; a forfeiture that was confirmed and then reversed, with no active forfeiture, follows DL-032, and a pending new forfeiture draft for that Deposit is a blocking issue. This needs a relaxing change of the 8a-1 kept-Deposit check (`app.post_deposit_application` refuses every Deposit with a ground today). (3) The same rule applies to a Pet Deposit kept for pet noncompliance (BR-DEP-022) whose forfeiture was reversed: it is held again and follows the Pet Deposit steps of DL-032 unless a new forfeiture draft is confirmed. BR-DEP-022 text is unchanged; this entry records the rule.
- **Owner acceptance of three sub-slice 8a-2 choices (2026-10-05):** (1) the receipt reversal wait does not hold back the confirmation of a Lease forfeiture reversal draft (6b), because it is not a Refund or forfeiture draft; (2) the bounded Deposit application history read has no actor parameter: the Deposit ledger route checks the capability for the Deposit's Property first; (3) the Deposit identifiers visible to Late-payment readers and the Late-payment Charge `deposit_total` stay with slice 11e.
- **V1-056 sub-slice 8b, Final Settlement preview (BR-SETTLE-002, BR-SETTLE-003, BR-SETTLE-011, DL-032; owner answers to Q-2026-10-05-20, Q-2026-10-05-21, Q-2026-10-05-23 and Q-2026-10-05-24; migration `20261024_89`):** `app.final_settlement_preview` (runtime role, STABLE; `FinalSettlementReadService.preview` checks `final_settlements.prepare` or `financial.approve`; the database checks an active person and the Property) reads one Final Settlement and writes nothing: the open obligations per Customer named on the Lease's issued, non-VOID Invoices (the Primary Tenant first), each Customer's available Credit with what it may pay of that Customer's obligations, both Deposits with held amount, ground, forfeiture state and path, the seven DL-032 steps in order with upper bounds only (nothing is proposed or inferred between Deposit types), and the blocking issues listed in docs/004 DB-SETTLE-001. The Deposit path follows the owner answer to Q-2026-10-05-24: `KEPT` (an active forfeiture), `FORFEITURE_REQUIRED` (a ground and no forfeiture ever confirmed; a blocking issue) or `DL_032` (no ground, or every forfeiture reversed; a pending new forfeiture draft is a blocking issue through the pending-draft check). The 8a-1 Deposit application guard now uses the same path and refuses everything except `DL_032` (a relaxing change approved in the answer to Q-2026-10-05-23), so a reversed-forfeiture Security Deposit and a Pet Deposit kept for pet noncompliance whose forfeiture was reversed may be applied; the termination record lookup is the shared `app.lease_termination_forfeiture_rule`, and `app.lease_deposit_kept_rule` keeps its result and errors. Choice within the plan: the final Utility issue applies when the Primary Tenant moved in (as the final Utility command requires) and does not wait for an Invoice when nothing is billable (a final Reading equal to the meter's last validated Reading and no period with consumption on no Invoice), because the command refuses to create an empty Invoice. After review round 1 and the owner answers to Q-2026-10-05-25: the cleaning check uses the Unit's current rate; step 5 allows the staff step everywhere except the three BR-DEP-027 terminations; `UTILITY_PERIOD_NOT_BILLED` and `ONE_TIME_CHARGE_NOT_INVOICED` are blocking issues; a Deposit with a ground and nothing held has the path `NOTHING_HELD` and raises no issue (the forfeiture draft refuses a Deposit that holds nothing; the plan says "still held"); the Late-payment check reads UNPAID and PARTIALLY_PAID Invoices, as the review allows (migration 39); a pending draft's id, kind and variant are shown only to a `financial.approve` holder or a holder of its prepare capability (the slice 2 and 6b read rule), while the issue itself blocks for every reader; the service reads in a read-only transaction. The route is built in slice 11e.
- **Updated tests (V1-056 sub-slice 8b):** the head-revision assertions now expect `20261024_89`; only the expected revision changed. The new PostgreSQL module `test_final_settlement_preview_migration.py` runs after the Utility modules in `scripts/database-test.sh`, because `test_utility_consumption_migration.py` deletes every Utility rate inside a transaction and a final Utility Invoice line created earlier would reference a rate.
- **Owner answers to Q-2026-10-05-25 (2026-10-05), Final Settlement preview (V1-056 sub-slice 8b):** yes to all four recommendations. (1) The "cleaning charge missing" issue uses the Unit's current cleaning rate, the same rate the slice 4 command charges: it shows while the Customer moved in and out, no cleaning charge sits on an issued, non-VOID Invoice, and the current rate is above zero or not set; a rate change after the move-out (audited, with a reason, under `property.manage`) decides. This replaces the plan note's "rate in force at the move-out". (2) DL-032 step 5: authorized staff may apply the remaining Pet Deposit with a reason when the Customer will not pay at every termination except the three BR-DEP-027 terminations (unpaid Initial Rent or Security Deposit, non-pet violation, 30-day Rent nonpayment default), where only the Customer's choice applies; this includes a Pet Deposit kept for pet noncompliance whose forfeiture was reversed and a termination with no forfeiture ground. (3) New blocking issue `UTILITY_PERIOD_NOT_BILLED` for every Utility consumption period the Lease is responsible for with consumption and no Invoice line, whether or not the final Utility Invoice exists (BR-SETTLE-011; such a period is billed through the catch-up command). (4) New blocking issue `ONE_TIME_CHARGE_NOT_INVOICED` for a one-time charge source of the Lease (Damage, Miscellaneous or the cleaning charge) that is on no DRAFT or issued, non-VOID Invoice (BR-SETTLE-003, BR-SETTLE-011).
- **Intermittent lock failure in V1-056 sub-slice 8b run P3 (2026-10-05; owner answer to Q-2026-10-05-26):** `test_refund_migration.py::test_usd_refund_khr_origin_uses_recorded_usd_without_repricing` failed once with `LockNotAvailable` on `app.payment_allocations` from `LOCK TABLE ... IN SHARE MODE NOWAIT` in `app.assert_payment_excess_eligible` (through `app.validate_general_refund_source`). It passed in runs P1 and P2; its module runs before the 8b module, and 8b changes nothing on that path. It is the same intermittent failure recorded on 2026-10-02 (2 of 4 full runs, in `test_financial_action_context_migration` and `test_refund_migration`) and 2026-10-03 (9f-3: likely autovacuum, not proven). Owner answer: one more full PostgreSQL run (P4); stop if the same test fails again; slice 12 makes this test robust against `LockNotAvailable` without weakening it.
- **Owner answer to Q-2026-10-05-27 (2026-10-05), withdrawn one-time charges at Final Settlement (V1-056 sub-slice 8b):** option (b) with one addition. `ONE_TIME_CHARGE_NOT_INVOICED` flags only a one-time charge source still waiting to be billed. A charge whose last Invoice was VOIDed (the VOID has a reason) and a charge that a draft correction replaced (recorded in `app.invoice_draft_revision_events` with a reason) are left out; the replacement charge is checked like any other charge. Reason: BR-SETTLE-003 lets only valid obligations into the Settlement, and a charge source can never be cancelled, so without this a withdrawn charge could be cleared only by billing it again and crediting it away. Addition: the preview lists each VOIDed charge that was not billed again under `information` (`VOIDED_CHARGE_NOT_BILLED_AGAIN`, with its amount), not as a blocking issue, so the person who confirms the Settlement sees it; this was a small additive change (one more key). Also taken from the round-2 review notes (tests and defensive changes, no rule change): a reversed forfeiture counts only through a disposition of the Deposit's own Lease (any active disposition still keeps the Deposit); commands keep the server's default transaction mode (`read_only=None`).
- **Owner answer to the sub-slice 8b round-3 owner item (Q-2026-10-05-28, 2026-10-05), replaced one-time charges at Final Settlement (V1-056 sub-slice 8c):** yes. The Settlement preview also lists, under `information` and not as a blocking issue, each one-time charge that a draft correction replaced, whether its replacement is on this Lease, on another Lease or on no Lease, and names the charge that replaced it. Built in sub-slice 8c as a small additive change with a test.
- **V1-056 sub-slice 8c, Final Settlement draft (BR-AUTH-010, BR-SETTLE-004 to BR-SETTLE-008, BR-SETTLE-017, BR-DEP-027, DL-032; owner answers to Q-2026-10-05-20, Q-2026-10-05-21, Q-2026-10-05-23, Q-2026-10-05-25 and Q-2026-10-05-28; migration `20261025_90`):** `app.record_final_settlement_draft` (financial role; `FinalSettlementService.record_draft` checks `final_settlements.prepare`) records a `FINAL_SETTLEMENT` draft with the DL-032 steps in order and amounts in cents: Customer Credit, Pet Deposit to pet damage, Security Deposit, remaining Pet Deposit with the Customer's choice as text (who, the date, how) and the staff reason or, outside the BR-DEP-027 terminations, the staff reason alone, and Deposit Refunds with an active Refund method, a reference note and the recipient (the Primary Tenant, or another signed Signer with the written agreement of all Signers). The draft has no financial effect; only a `financial.approve` holder will confirm it (sub-slice 8e); withdraw and reject use the shared draft functions; one draft waits per Settlement. It is refused while the preview shows a blocking issue, and when the plan breaks the strict order of owner answer 3 to Q-2026-10-05-20, checked by `app.final_settlement_plan_result`, which the confirm calls again: each Customer's Credit pays that Customer's own open debt, up to what it can pay, before any Deposit pays (owner answer 2 to Q-2026-10-05-29, below); the Pet Deposit pays open pet damage before any other use or Refund; no Deposit is refunded while the Lease still has open debt that the Deposit could pay. Choices within the plan: (1) every Deposit on the DL-032 path must end with nothing held, applied or refunded (BR-SETTLE-008: every remaining refundable balance is refunded explicitly); (2) replaced by the owner answer 2 to Q-2026-10-05-29 below (each Customer's Credit is always used against that Customer's own open debt); (3) at a BR-DEP-027 termination a Pet Deposit Refund does not wait for other debt, also when the Customer chose to use part of the rest (Q-2026-10-05-21: without the Customer's choice the Pet Deposit is not a Deposit that could pay that debt; the amount the Customer chose is recorded); (4) the expected closing balance is computed by the database and stored in total and per Customer, not entered by staff; (4a), rejected by the owner on 2026-10-05 (Q-2026-10-05-30, below): the choice was that, at a termination where the staff step is allowed, staff could use the remaining Pet Deposit for debt the Security Deposit could also pay and then refund the Security Deposit, because the Refund check looks at the debt left after all chosen applications (DL-032 "any Security Deposit applications", BR-SETTLE-006: no inferred order between Deposit types; review round 3 note, listed for the owner); (5) the source revision is the digest of every Settlement source's state (`app.final_settlement_source_state`) rather than one revision per source, because the draft payload is limited to 16,000 bytes; it is computed in the same call as the plan check (one snapshot, review round 1 fix; the preview's earlier VOLATILE Late-payment review reads its own snapshot, which fails safe because a Charge it sees changes the digest, review round 2); the confirm (8e) recomputes it. Owner answer 4 to Q-2026-10-05-23: the receipt reversal recorder, the receipt reversal guard and the decision trigger now also see a pending `FINAL_SETTLEMENT` draft that applies or refunds the Deposit (`deposit_ids`); a pending receipt reversal draft blocks the Settlement draft through the preview. Owner answer to Q-2026-10-05-28: the preview lists replaced one-time charges under `information` (`CHARGE_REPLACED_BY_DRAFT_CORRECTION`, with the replacing charge and its Lease or none). No HTTP route yet (slice 11e).
- **Updated test expectations (V1-056 sub-slice 8c):** the head-revision assertions now expect `20261025_90`; only the expected revision changed. `test_final_settlement_preview_migration.py::test_withdrawn_one_time_charges_do_not_block_and_voided_ones_are_listed` (test name kept): its two `information` assertions now also expect the replaced charge, with the charge that replaced it, because of the owner answer to Q-2026-10-05-28; nothing else in the test changed. The new PostgreSQL module `test_final_settlement_draft_migration.py` runs right after the preview module.
- **Owner answers to Q-2026-10-05-29 (2026-10-05), Customer Credit in the Final Settlement draft (V1-056 sub-slice 8c):** (1) option (a): the draft follows the existing Credit rule BR-CREDIT-006. On an Invoice with Rent or Service lines a Credit step follows the Rent-first, then recurring-Service proposal order (the first line of that Invoice in that order that still owes), unless the step records the Customer's designation as text (who, the date, how; 1 to 500 characters, the limit of the existing Credit application's designation reference). Other Invoices and Late-payment Charges keep the free choice. No Settlement-only exception; docs/002 is unchanged. (2) option (a): each Customer's Credit is always used against that Customer's own open debt in the Settlement, up to what it can pay (the lower of the Credit available and that Customer's open debt), before any Deposit pays; it is never used for another Customer's debt; a Settlement draft never leaves open debt and unused Credit on the same Customer. This replaces "choice (2)" of the sub-slice 8c entry above, which required Credit only before a Deposit paid that Customer.
- **Owner answer to choice (4a) of the V1-056 sub-slice 8c entry (2026-10-05):** rejected. The remaining Pet Deposit (DL-032 step 5) may pay only the debt that is still open after the Security Deposit has been used. This follows the owner's words "the rest is refunded; the Customer may choose to use the rest for any remaining balance" and the step order the draft already uses (Security Deposit, step 4, before the remaining Pet Deposit, step 5). The same applies when the Customer chooses it. So a Final Settlement plan in which the remaining Pet Deposit pays debt while a Security Deposit on the DL-032 path still holds money is refused, at draft time and in the plan check that the confirm (8e) runs again; staff can no longer use the remaining Pet Deposit for debt the Security Deposit could pay and then refund the Security Deposit. Choices (1) to (4) of the 8c entry stand. Built in sub-slice 8d (migration `20261026_91`).
- **V1-056 sub-slice 8d, Final Settlement Deposit Refund source (BR-DEP-025, BR-REFUND-007, BR-REFUND-014, BR-REFUND-015, BR-SETTLE-008, BR-AUTH-010, DL-032; owner answer 3 to Q-2026-10-05-20 and the owner answer to choice (4a); migration `20261026_91`):** `app.final_settlement_refund_details` links a Refund of a Lease Security or Pet Deposit to its Final Settlement and records its method, reference note, the Signers' agreement and the `FINAL_SETTLEMENT` draft, one Refund per Deposit per Settlement; the Refund source-context check is relaxed so a Deposit Refund may have neither a Reservation event nor a Pet Refund review, and the Refund source trigger then requires that link; every earlier row keeps its context. The only writer, `app.post_final_settlement_deposit_refund`, is internal (no grant); the confirm (8e) calls it. The Refund source trigger checks every writer (docs/004): open Settlement of a terminated Lease, a `DL_032` Deposit of that Lease owned by the Primary Tenant, recipient and agreement (BR-REFUND-015), active method, exactly a Refund step of a pending draft of that Settlement or one confirmed by the same approver, amount within the held Deposit, and no open debt of the Lease that a Deposit could pay. Choices within the plan: (1) the Refund row records `authorization_reference = 'financial.approve'` and the approver as `processed_by`, like the Deposit applications (8a), because only the Settlement confirm writes it; (2) the Settlement link, method, note and agreement are kept in their own table, not in a new `refunds.final_settlement_id` column as docs/004 first described, because every Refund reader returns the whole Refund row and the frontend's financial action context checks its keys exactly, so a new column would break the response of every existing Refund; and not in `refund_draft_details` and `refund_recipient_agreements`, because those allow one Refund per draft and a Settlement draft may hold two; (3) the open-debt check reads the debt as the preview does and also refuses any Deposit Refund while a `DL_032` Security Deposit of the Lease still holds money and debt is open ("a Deposit could pay"); (4) a Settlement Refund is not corrected by the one-call Refund correction (it already failed there with an unclear 23514; now the correction path says so) until the post-settlement corrections (slice 10); (5) a Deposit application of a Settlement is refused once the Settlement has a Refund (BR-SETTLE-008: every application is recorded before the remaining balance is refunded); this and (4) refuse only records no writer could create before. The general Refund audit books a Settlement Refund on the Deposit's Property and Lease; the Customer Ledger already books Deposit Refunds on the Deposit owner (slice 3a-2). The owner answer to choice (4a) is built in the plan check `app.final_settlement_plan_result`, which the draft recorder and the confirm share. After review round 1: a deferred check (`app.assert_final_settlement_refund_confirmed`) lets a Settlement Refund commit only when its draft is CONFIRMED under `financial.approve` by the Refund's approver, so the database itself proves that no Deposit money leaves on a pending draft or on another approver's confirmation (a rejected or withdrawn draft is refused earlier, when the Refund row is written) (this refuses only records no writer could create before); the writer locks the Settlement and then the Deposit before writing, the lock order of the Deposit applications. No HTTP route (slice 11e).
- **Updated test expectations (V1-056 sub-slice 8d):** the head-revision assertions now expect `20261026_91`; only the expected revision changed. `test_final_settlement_draft_migration.py::test_a_security_refund_follows_once_no_debt_is_left` (test name kept): its plan uses the remaining Pet Deposit for debt the Security Deposit could still pay and then refunds the Security Deposit, so its one expectation changed from "recorded" to the refusal "The remaining Pet Deposit pays only debt still open after the Security Deposit has been used" (owner answer to choice (4a)); its traceability note now says so. The accepted Security Refund once no debt is left is shown by the new `test_the_remaining_pet_deposit_pays_only_debt_left_after_the_security_deposit`. The new PostgreSQL module `test_final_settlement_refund_migration.py` runs last, after `test_refund_signer_recipient_migration.py`, because `test_refund_signer_recipient_migration.py::test_refunds_of_the_earlier_shape_project_exactly_as_before` reads every Deposit Refund of the shared test database that has no `refund_recipient_agreements` row and expects it paid to the Deposit owner; a Settlement Refund paid to another Signer keeps its agreement in `final_settlement_refund_details`.
- **Owner answers to Q-2026-10-05-31 (2026-10-05), sub-slice 8d after review round 2:** (1) yes, as an owner exception to the standing round-3 rule: make the three should-fix fixes and the listed notes, run backend unit and full PostgreSQL once each, then one round 3 that must have no blocker and no should-fix. For fix 1, a Settlement Refund is refused while a Deposit receipt reversal draft or a forfeiture draft is pending for the same Deposit, even when that draft was recorded after the Settlement draft was confirmed (the owner's 8r rule), with tests for both orders. (2) yes: BR-SETTLE-005 and BR-SETTLE-017 (docs/002) gain the line "Amended by the owner answer to Q-2026-10-05-30". (3) The table `app.final_settlement_refund_details` is accepted instead of a `refunds.final_settlement_id` column; docs/004 matches it. Owner rule for later work: when a design differs from docs/004 or the plan, ask the owner first.
- **V1-056 sub-slice 8d review round 2 fixes (migration `20261026_91`, before commit):** the Refund source check takes the per-Deposit draft lock (`lease-deposit-forfeiture:<deposit>`, the lock of the forfeiture, forfeiture reversal and receipt reversal draft recorders) before the Deposit row and refuses (55000) while any pending `DEPOSIT_FORFEITURE` draft (forfeiture, forfeiture reversal or receipt reversal) names the Deposit; the writer takes the same locks in the same order (the Settlement row, the draft lock, the Deposit row) and sets its two deferred checks (the details row's Refund key and the confirmation check) back to DEFERRED before writing, because `app.post_credit_application` leaves `SET CONSTRAINTS ALL IMMEDIATE` in force for the rest of the transaction; this only moves those checks to commit. Tests: both orders for a receipt reversal draft and a forfeiture draft, the confirmation in the Refund's own transaction (same approver commits, another approver writes nothing), a kept Deposit, a Deposit of another Lease, details naming another Deposit, the writer's input refusals.
- **Owner answers to Q-2026-10-06-32 (2026-10-06), the Settlement's Credit applications and closure snapshots (V1-056 sub-slices 8e-2 and 8e-3):** (1) the Settlement's Credit steps are written by a new internal writer, not through `app.post_credit_application`: it follows the same Credit rules (BR-CREDIT-006 and the owner answers to Q-2026-10-05-29), records the Settlement link (`customer_credit_applications.final_settlement_id`, docs/004 DB-CREDIT-002) and has no grant to any role, like the 8d Refund writer; (2) these Credit applications record the Settlement's `financial.approve` confirmation as their authorization; (3) a Credit application made by the Settlement is never reversed with one call after closure; a correction waits for the slice 10 correction drafts (owner answer 7 to Q-2026-10-05-20); (4) the line-level closure records (DB-SETTLE-006) refer to an `id` column added to `settlement_invoice_items` (DB-SETTLE-002 keeps its primary key), a technical choice. The recommendations of Q-2026-10-06-32 are these answers, so 8e-2 proceeds without a further stop.
- **Owner answers to Q-2026-10-06-33 (2026-10-06), sub-slice 8e-1 after review round 1:** (1) a scheduled Rent or Utility run skips a Lease whose Final Settlement is closed with the diagnostic `FINAL_SETTLEMENT_CLOSED`, so the run succeeds and a VOID of an open Lease's Invoice from that run is never refused because another Lease in the run is closed (with a test); (2) closure is blocked while a Rent month of the Lease is still unbilled (a full month inside the Lease's coverage with no active Rent Invoice); this is a new preview blocking issue built in 8e-3 with the confirm's re-check, and it refuses Settlement drafts that 8c accepts today (owner-approved tightening); (3) a VOID of a draft Invoice of a closed Lease stays refused, and closure is blocked while the Lease has any draft Invoice: the preview's `INVOICE_DRAFT_NOT_ISSUED` (8b) already blocks every DRAFT with the Lease, whoever is named on it, the confirm (8e-3) checks it again under its locks, and the 8e-1 guard keeps a draft from gaining the Lease after closure. The round-1 notes are in the plan.
- **V1-056 sub-slice 8e-1, refusals after a Final Settlement closes (owner answer 7 to Q-2026-10-05-20, approved tightening; owner answers to Q-2026-10-06-33; BR-SETTLE-012, BR-SETTLE-013; migration `20261027_92`):** 8e is split into 8e-1 (these refusals), 8e-2 (the Settlement Credit application writer) and 8e-3 (confirm and close); ops/V1_056_PLAN.md, "8e pre-code review", has the 8e notes and the read-only path search. `app.refuse_closed_final_settlement_change` (SECURITY DEFINER, no grant) runs as the first BEFORE INSERT trigger on `invoice_void_events`, `invoice_adjustments`, `invoice_adjustment_reversals`, `late_payment_decisions`, `late_payment_charges`, `late_payment_charge_corrections`, `invoices` and `authorized_nonrecurring_obligations`, and as the first BEFORE UPDATE OF `lease_id`, `status` trigger on `invoices` when a row gets a Lease or a DRAFT with a Lease is issued (review round 1, blocker B1: `app.correct_invoice_draft` moves a draft onto another charge by UPDATE and `app.issue_invoice` issues it by UPDATE). Every writer of those rows inherits it: VOID, Adjustments (also through the hand-back and unpaid-Initial resolutions), the Adjustment reversal (no writer yet), Late-payment Decisions, Charges and Charge corrections, and every new Invoice or charge with the Lease (Rent and Utility runs, final and catch-up Utility Invoices, Invoice drafts naming any Signer, a draft corrected onto a Lease charge or issued with the Lease, one-time, Damage and cleaning charges). For a Lease with a Final Settlement it locks the target Invoice and then the Settlement row `FOR SHARE` and refuses with SQLSTATE `P5S01` when the Settlement is closed; a Lease without a Settlement takes no lock. A change thus waits for a running closure and is then refused, and a closure waits for a running change; the confirm (8e-3) will lock the Lease's Invoices before the Settlement row. A DRAFT may still become VOID by UPDATE, but its VOID event is refused like every other VOID (owner answer 3); a one-time-charge draft has no Due Date until it is issued, so the earlier rule `invoices_due_date_issued` (migration 64) already refuses its VOID, open or closed (found in run P2). The Invoice, Late-payment, final Utility Invoice, Rent billing and unpaid-Initial services map `P5S01` to their conflict errors (owner answer: business state reaches the user as a conflict). Owner answer 1: the scheduled Rent and Utility run items lock the Lease's Settlement row `FOR SHARE` before they bill and record a Lease whose Settlement is closed as `SKIPPED` with `FINAL_SETTLEMENT_CLOSED`; the run item's allowed codes and `app.billing_run_has_missing_eligible_sources` accept the code (relaxing changes), so the run succeeds and the VOID of its other Invoices is not held back. Payments, allocations, Payment reversals, Credit applications and their reversals are not guarded (owner answer 7). Choices within the plan: the refusal sits on the tables, so every INSERT writer and every guarded UPDATE inherits it; its triggers run before the 8a-1 Deposit-application refusal, so a closed Settlement is the reason given; the new run code needs no screen change (the diagnostics screen shows an unknown code as "Diagnostic code FINAL_SETTLEMENT_CLOSED."; 11e may add a label). No closed Settlement can exist before 8e-3 (only the confirm writes the closure), so nothing changes for existing data; the tests close a Settlement through an owner test helper, which the 8a-1 closure guard allows once. docs/004 (DB-SETTLE-001) and docs/005 (API-072) record the behavior.
- **Updated tests (V1-056 sub-slice 8e-1):** the head-revision assertions now expect `20261027_92` (26 assertions in 14 modules); only the expected revision changed. The new PostgreSQL module `test_final_settlement_closed_refusal_migration.py` runs last.
