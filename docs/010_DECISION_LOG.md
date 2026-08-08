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
- **Decision:** A valid Reservation is required before move-in. Reservation statuses are only `ACTIVE`, `CANCELLED`, and `MOVED_IN`; an extension is historical activity rather than a status.
- **Provenance:** Embodied in 001/002. The prohibition on an `EXPIRED` status was also explicitly approved by the Owner.
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
- **Decision:** There is no separate Reservation Deposit. The money collected during Reservation is the same Security Deposit that continues into the resulting Lease. Activating a Reservation requires at least 20% of agreed monthly Rent; more may be paid. The remaining required Security Deposit may be paid before or at move-in and must be complete no later than move-in completion.
- **Provenance:** Literal Owner Decisions 3 and 5, consistent with the deposit model embodied in 001.
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
- **Decision:** Voluntary early termination makes the Security Deposit non-refundable but does not automatically make the Pet Deposit non-refundable. Pet Deposit remains separately tracked through Final Settlement, may be applied only to authorized pet-related damage, and is refundable to the extent not validly applied or otherwise validly forfeited under an approved rule.
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
- **Decision:** Rent is billed monthly in advance. Recurring Rent Invoices are generated on the 25th for the upcoming calendar month and are normally due on the 5th. First partial months, and final partial months when an approved rule permits proration, use inclusive actual calendar days with final half-up USD-cent rounding. Every Rent Invoice requires the applicable signed Lease, and contractual Rent comes from that Lease.
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
- **Affected documents/rules:** `001_DOMAIN_MODEL.md` sections 9.8, 15.12, 20, 53, 91, and 101; `BR-INV-001`, `BR-INV-002`, `BR-INV-036` through `BR-INV-042`; `002_BUSINESS_RULES.md` section 30.2.
- **Rationale:** Not recorded as part of the approved amendment.
- **Decision date:** Not recorded in this log.
- **Alternatives:** A mandatory-Lease model existed in earlier material and was superseded; complete chronology is intentionally not asserted here.

## DL-020 — Supported Invoice categories and fixed Service lines

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `APPROVED`
- **Decision:** Supported Invoice/line categories are Rent, Utilities, Service Charges, Damage Charges, and Miscellaneous Charges. Deposits are not Invoice categories. Internet and Trash are fixed recurring Service lines on the Rent Invoice, billed in advance on the Rent cycle; first partial months are prorated, while final or early-termination months are not automatically prorated merely because physical occupancy ends.
- **Provenance:** Literal Owner Decision 10 plus the category model embodied in 001/002.
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
- **Status:** `APPROVED`
- **Decision:** The recovered literal supplementary Owner Decision S2 says that when fewer than three complete historical periods exist, the system must not substitute one or two historical periods or another Unit. It must wait for one complete future month of actual consumption for the same Unit and Utility Type, use that future month as the estimate basis, and keep the affected charge pending until then.
- **Provenance:** Literal supplementary Owner Decision S2.
- **Affected documents/rules:** `BR-UTIL-027`, `BR-UTIL-028`; `BR-MOVEOUT-005`, `BR-MOVEOUT-012`; `BR-SETTLE-011`; `BR-AUDIT-004`.
- **Reconciliation note:** `BR-UTIL-027` and `BR-UTIL-028` were reconciled to the recovered literal Owner decision before downstream publication. Both insufficient-history cases preserve the pending charge until one complete future actual period exists.
- **Rationale:** Not recorded as part of the approved decision.
- **Decision date:** Not recorded in this log.
- **Alternatives:** Presented before approval; not adopted in the recovered literal decision.

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
- **Decision:** Payment Allocation remains manual and is posted only after authorized staff confirmation. The system may calculate a deterministic proposal. Without a Customer designation, the proposal uses oldest Due Date first across applicable obligations, with Invoice issue/generation order and then stable sequence/ID for ties, and no category preference. A valid Customer-designated Invoice may override the default proposal. Third-party Payment follows identified intent and is not spread automatically across unrelated obligations.
- **Provenance:** Literal Owner Decision 13 and supplementary Decision S5, preserving the manual model established in 001.
- **Affected documents/rules:** `BR-PAY-019` through `BR-PAY-029`; `BR-AUTH-007`; `001_DOMAIN_MODEL.md` sections 9.9, 54, 78, 90.9, and 104.
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
- **Status:** `APPROVED`
- **Decision:** Customer Credit is maintained in USD accounting value and is not transferable to another Customer. For KHR-origin value, preserve the original KHR amount and exact receipt rate. Refund KHR excess before Credit recognition in the corresponding original KHR amount. If USD Customer Credit is later refunded in KHR, use the exchange rate applicable to that Refund and preserve both currency values, rate, and source relationship. No separate KHR-denominated Credit balance is approved.
- **Provenance:** Literal supplementary Owner Decision S4 and the same-Customer rules embodied in 002.
- **Affected documents/rules:** `BR-CREDIT-001` through `BR-CREDIT-012`; `BR-REFUND-005`, `BR-REFUND-006`, `BR-REFUND-008`; `BR-MONEY-001`, `BR-MONEY-002`.
- **Rationale:** Not recorded as part of the approved decision.
- **Decision date:** Not recorded in this log.
- **Alternatives:** Presented before approval; not adopted.

## DL-032 — Final Settlement order

- **Type:** `OWNER BUSINESS DECISION`
- **Status:** `APPROVED`
- **Decision:** For each terminated Lease, finalize valid charges; apply authorized Customer Credit; apply Pet Deposit only to authorized pet-related damage; apply Security Deposit to remaining authorized obligations using oldest-due ordering where applicable; record any remaining Customer balance; and explicitly refund remaining refundable Deposit balances. Every input, application, disposition, Refund, and result remains separately traceable.
- **Provenance:** Literal supplementary Owner Decision S6, refining Owner Decision 14.
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
- **Derived from:** `001_DOMAIN_MODEL.md` section 97; `002_BUSINESS_RULES.md` section 30.4.
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
- **Decision:** Unit availability, Invoice outstanding balance, Payment allocation progress, Customer Credit balance, Deposit outstanding/refundable balance, Utility consumption, Lease balance, and Settlement net balance must be derived from or fully reconcilable to authoritative records and must not become competing sources of truth.
- **Derived from:** `001_DOMAIN_MODEL.md` sections 4.5, 38, 95; `BR-UNIT-013`; Payment, Credit, Deposit, and Settlement rules.
- **Affected documents/rules:** 003-007; `BR-UNIT-013`; `BR-PAY-008` through `BR-PAY-014`; `BR-CREDIT-012`; `BR-SETTLE-009`, `BR-SETTLE-012`.
- **Rationale:** Not separately recorded.
- **Decision date:** Not recorded.
- **Alternatives:** Not recorded.

## DL-037 — Deterministic and idempotent scheduled processing

- **Type:** `DERIVED REQUIREMENT`
- **Status:** `REQUIRED`
- **Decision:** Scheduled Reservation expiration and recurring billing must be safely retryable. Stable business keys and deterministic ordering must prevent duplicate effects and support recovery of missed runs.
- **Derived from:** Reservation end-of-date policy, duplicate-billing policy, and deterministic FIFO policy.
- **Affected documents/rules:** 004, 005, 007, 009; `BR-RES-011`, `BR-RES-016`; `BR-RENT-011`, `BR-RENT-027`; `BR-INV-026` through `BR-INV-029`; `BR-PAY-021` through `BR-PAY-023`.
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
- **Decision:** Every action described as authorized requires an authenticated actor with permission for that action. Audit data must preserve actor, action, date/time, reason, previous and resulting state/value, affected record, and required source links. The later Security Model may refine roles but must not weaken these requirements.
- **Derived from:** `001_DOMAIN_MODEL.md` sections 40, 58, and 81; `BR-AUDIT-001` through `BR-AUDIT-010`; `BR-AUTH-001` through `BR-AUTH-009`.
- **Affected documents/rules:** 004, 005, 006, 007, 008, 009.
- **Rationale:** Not separately recorded.
- **Decision date:** Not recorded.
- **Alternatives:** Complete role and permission matrix is deferred to 008.

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

## DL-042 — Due Date for a first partial-month Rent Invoice issued after the 5th

- **Type:** `OPEN OWNER DECISION`
- **Status:** `OPEN`
- **Question:** What Due Date applies when the first partial-month Rent Invoice is issued after the 5th day of the billed month?
- **Current authoritative context:** `BR-RENT-005` permits a first partial-month Invoice after mid-month move-in. `BR-RENT-009` defines the normal recurring Due Date as the 5th day of the billed month unless the Lease specifies another date. Recovered session history explicitly identified the after-the-5th case as unresolved, and no later literal Owner answer was recovered.
- **Affected documents/rules:** `BR-RENT-005`, `BR-RENT-009`, `BR-INV-018`; 003, 005, 006, and 007 workflows/tests.
- **Rationale:** The approved rationale is not recorded.
- **Decision date:** Not applicable; open.
- **Alternatives:** Alternatives were presented in session history, but none was approved; this log does not select one.

## 11.1 Open Implementation and Operational Decisions

The following nonblocking choices do not change approved business rights or
financial policy. Their source specifications preserve conservative behavior until
the Owner or authorized deployment decision-maker resolves them.

| Source identifier | Open choice | Current conservative treatment |
|---|---|---|
| `OD-004-001` | Customer legal-name/contact validation and duplicate matching | Preserve approved value objects; impose no unapproved identity rule. |
| `OD-004-002` | Refund delivery method and pre-completion lifecycle | Persist only the completed Refund event; invent no pending/failed Refund status. |
| `OD-004-003` | Invoice, Payment, and Refund number format/sequence | Require unique immutable values without prescribing format. |
| `OD-004-004` | Meter serial-number uniqueness scope | Preserve serial text without claiming global or per-type uniqueness. |
| `OD-004-005` | Electricity/Water measurement-unit metadata | Preserve exact numeric quantities/rates without naming an unsupported unit. |
| `OOD-API-001` | Production authentication provider | Keep API authentication-provider-neutral. |
| `OOD-UI-001` | Brand and visual design tokens | Use accessible neutral tokens pending brand direction. |
| `OOD-UI-002`, `OOD-TEST-001` | Certified browser/device matrix | Use standards-compliant responsive behavior and generic cross-browser coverage. |
| `OOD-SEC-001` | Named staff role-to-capability mapping | Keep capabilities and role bundles configurable; grant no role-name authority. |
| `OOD-SEC-002` | Mandatory MFA scope | Support MFA without inventing the final mandatory mapping. |
| `OOD-DEPLOY-001`, `OOD-TEST-002` | Production RPO/RTO | Keep backup/recovery parameters configurable; promise no unapproved objective. |
| `OOD-DEPLOY-002` | Production host, address, and certificate trust | Specify required properties without selecting infrastructure identifiers. |
| `OOD-DEPLOY-003` | Remote-access enablement/gateway | Keep remote access disabled by default. |

The repeated partial-month Due Date references `OOD-PR-001`, `OOD-API-002`,
`OOD-UI-003`, and `OOD-TEST-003` all propagate the single business-policy question
in `OOD-BR-001` and `DL-042`; they are not separate decisions.

---

# 12. Technical Decisions from Specifications 003-009

## DL-043 — Exhaustive one-to-one Product Requirement traceability

- **Type:** `DERIVED REQUIREMENT`
- **Status:** `REQUIRED`
- **Decision:** Each of the 343 `BR-*` rules has one same-suffix detailed `PR-*` requirement preserving its normative body. Capabilities, workflows, and quality requirements supplement rather than replace that bijection.
- **Provenance:** `003_PRODUCT_REQUIREMENTS.md` sections 2 and 5-9.
- **Affected documents/rules:** 003-007; every `BR-*` and detailed `PR-*`.
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
- **Decision:** Authentication uses unique actor identities; server-side authorization is deny-by-default and capability-based; configurable role bundles do not themselves create business authority. Financial actions, audit access, secrets, Customer data, database privileges, and backups receive defense-in-depth controls.
- **Provenance:** `008_SECURITY_MODEL.md` sections 2-17.
- **Affected documents/rules:** 005-009; `BR-AUTH-001` through `BR-AUTH-009`; `BR-AUDIT-001` through `BR-AUDIT-010`.
- **Rationale:** Enforce least privilege without inventing the Owner's organizational role map.
- **Decision date:** Not recorded.
- **Alternatives:** Not recorded.

## DL-049 — Local-first modular deployment topology

- **Type:** `TECHNICAL DESIGN DECISION`
- **Status:** `DIRECTION RECORDED`
- **Decision:** The production-oriented topology uses a TLS reverse proxy and static React build, FastAPI API, separate scheduled worker, and one PostgreSQL database, packaged for local-network operation. Durable job state, safe migrations, encrypted verified backups, monitored recovery, and no mandatory new cloud dependency are required.
- **Provenance:** `009_DEPLOYMENT_ARCHITECTURE.md` sections 2-15.
- **Affected documents/rules:** 004-009; scheduled, financial-history, security, and recovery requirements.
- **Rationale:** Support maintainable single-site operation and reliable recovery without premature distributed services.
- **Decision date:** Not recorded.
- **Alternatives:** Not recorded.

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
