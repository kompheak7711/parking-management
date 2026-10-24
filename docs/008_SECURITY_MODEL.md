# 008 — Security Model

**Document Status:** Owner Review
**Authority:** Downstream of `001_DOMAIN_MODEL.md`, `002_BUSINESS_RULES.md`, and the applicable requirements and technical specifications in `003`–`007`
**Scope:** Security architecture and controls for the Property Rental Management System
**Rule identifiers:** `SEC-*`

---

# 1. Purpose

This document defines the security properties required to protect customer data,
financial records, credentials, operational availability, and audit history. It
does not assign business authority that has not been approved by the Owner.

Security controls must preserve the domain and financial invariants in
`001_DOMAIN_MODEL.md` and `002_BUSINESS_RULES.md`. A security mechanism must not
provide a bypass around a business action, status transition, calculation,
authorization, or audit requirement.

# 2. Security Principles

## SEC-001 — Least Privilege

Every authenticated actor, service, scheduled job, and database connection must
receive only the capabilities required for its approved function.

## SEC-002 — Deny by Default

Access is denied unless an authenticated actor has an explicitly configured
capability for the requested action and its Property scope.

## SEC-003 — Capability-based Authorization

Authorization is defined by granular capabilities. Role names are configurable
bundles of capabilities rather than sources of hard-coded business authority.
Exact staff-to-role assignments remain configurable because the Owner has not
approved a fixed organizational role map.

## SEC-004 — Defense in Depth

UI visibility, API authorization, service-layer validation, database constraints,
and audit controls must reinforce one another. Hiding a UI control is not an
authorization control.

## SEC-005 — Historical Integrity

Security controls must prevent silent deletion or mutation of audit-sensitive and
financial history, consistent with `BR-AUDIT-001` through `BR-AUDIT-010`.

## SEC-006 — Minimize Sensitive Data

The system must collect, display, export, log, and retain only data necessary for
the approved property-management workflows.

# 3. Protected Assets

## SEC-007 — Asset Classes

Protected assets include:

- Customer identity and contact information;
- Reservation, Lease, signer, Occupant, Lease-violation warning, Rent Nonpayment
  case/event, pet-departure, and Pet Deposit refund-review records;
- Deposit, Invoice, Adjustment, Late-payment Decision, Late-payment Charge and
  correction, Payment, Allocation, Customer Credit, Refund, Reversal, Receipt,
  Receipt reprint, Customer Account Ledger, and Final Settlement records;
- Utility Meter, Reading, Rate, and calculated billing information;
- exchange-rate source and calculation evidence;
- authorization and audit records;
- user identities, credentials, sessions, and capability assignments;
- application configuration, secrets, backups, and migration history; and
- service availability and recovery materials.

## SEC-008 — Security Classification

At minimum, data is classified as:

- **Restricted:** credentials, secret keys, session material, backup encryption
  keys;
- **Confidential:** Customer data, Lease documents, financial details, audit actor
  data;
- **Internal:** operational configuration, monitoring, non-public reports; or
- **Public:** content deliberately designated for public disclosure.

Restricted and Confidential data must not appear in unauthenticated responses or
ordinary application logs.

# 4. Authentication

## SEC-009 — Unique User Identity

Every human user must authenticate with a unique account. Shared staff accounts
are prohibited because they prevent reliable attribution.

## SEC-010 — Authentication Provider Properties

Production uses application-managed local username and password authentication and must
not depend on Google, Microsoft, Auth0, or another external identity provider for normal
operation. The mechanism must provide:

- secure credential verification;
- account disablement;
- credential reset or recovery under an auditable administrative process;
- protection against automated guessing;
- session revocation; and
- stable actor identity for audit events.

Library and protocol implementation details remain technical choices and must not change
business authorization semantics.

## SEC-011 — Password Storage

Only salted, adaptive password hashes using a
currently accepted password-hashing algorithm may be stored. Plaintext,
reversible encryption, unsalted hashing, and security-question recovery are
prohibited.

## SEC-012 — Authentication Rate Limiting

Login and recovery endpoints must be rate-limited by account and source while
avoiding account-enumeration disclosures.

Amended by DL-080 (owner, 2026-10-20): after 5 wrong tries the person waits 15 minutes, with the same message whether or not the account exists. A one-time password given by the Owner after a reset works for 24 hours and must be changed at the first sign-in.

Amended by DL-081 (owner's wait rule, recorded 2026-10-23 with login sub-slice L3b; replaces the "5 wrong tries, 15 minutes" values above): after 3 wrong tries in a row for one username the person waits 5 minutes; after 2 more wrong tries (5 in a row) 15 minutes; after that every 2 more wrong tries mean another 15-minute wait, until a correct sign-in clears the count. Unknown usernames are counted the same way; tries during a wait are refused without checking the password and add no time; wrong sign-in codes and recovery codes count; a source address with 20 wrong tries in 15 minutes waits 15 minutes; the counts are kept in the database (DB-AUTH-011).

## SEC-013 — Multi-factor Authentication

The authentication architecture must use an appropriate standards-based MFA mechanism.
MFA is mandatory for Owner and Manager and optional for Staff. A newly created Owner or
Manager must not receive normal privileged application access until enrollment is
complete. Staff without MFA may operate only within granted capabilities; Staff with MFA
enabled must complete it. SMS-based MFA or recovery is prohibited without separate Owner
approval. Existing stricter remote-access controls remain authoritative.

Amended by DL-081 (owner rule of 2026-10-21; login sub-slice L1e): an account that holds Settings access must use the sign-in code at every sign-in. A Staff account gets Settings access only after it has set up its sign-in code (MFA required and an active enrollment), and its Settings access works only while that holds (docs/004 DB-AUTH-008).

## SEC-014 — Account Lifecycle

Account creation, disablement, capability changes, credential resets, and session
revocation require an authorized actor and an immutable audit event.

Amended by DL-081 (login sub-slice L2a): in the database only the active Owner account class
creates, changes and disables accounts, revokes their sessions, creates and changes role bundles,
assigns and removes them and gives and removes Settings access; each action writes one audit event
without secrets in the same transaction (docs/004 DB-AUTH-010). The acting Owner is passed by the
application from the signed-in session (sub-slice L3a), so this database check is a second line
behind the session and capability checks of the routes.

# 5. Session Security

## SEC-015 — Session Tokens

Session identifiers or access tokens must be unpredictable, time-bounded, scoped,
and transmitted only over protected channels. Tokens must not be stored in
application logs or URLs.

## SEC-016 — Browser Session Protection

Cookie-based browser sessions must use `Secure`, `HttpOnly`, and an appropriate
`SameSite` policy. State-changing browser requests require CSRF protection when
the authentication design is susceptible to CSRF.

## SEC-017 — Session Expiration and Revocation

Production browser sessions expire after 30 minutes of inactivity and after an absolute
24 hours regardless of activity. Password or MFA reset/recovery, account disablement, or
a material privilege reduction must support prompt applicable-session revocation.

## SEC-018 — Reauthentication

Deployments must be able to require recent authentication or an additional factor
for high-risk administration. Reauthentication does not replace the business
authorization and confirmation requirements for financial actions.

Amended by DL-081 (login sub-slice L3d-2, owner answer (a) to Q-2026-10-21-157,
Q-2026-10-24-184): the actions that change who may do what (creating or disabling an account,
turning its MFA on or off, creating or changing a role bundle, giving or removing one, giving or
removing Settings access, and the Owner's reset of an account) need a reauthentication with the
password and the sign-in code of the same browser session in the last 15 minutes, shown by the
separate reauthentication cookie; a copied session cookie alone, a password-only
reauthentication or a recovery code never passes. A sign-in with the sign-in code counts as one.
The capability check still applies.

# 6. Authorization Model

## SEC-019 — Property Scope

Every business authorization check must include the applicable Property scope.
The initial domain contains one Property, but the security boundary must not rely
solely on client-supplied identifiers.

## SEC-020 — Capability Families

The configurable capability catalog must distinguish at least:

- read and manage Property configuration;
- read and manage Units and Customers;
- create, extend, cancel, and complete Reservations;
- draft, sign, renew, terminate, and inspect Leases;
- manage Lease Signers and Occupants;
- record move-in, Lease-violation warnings, and move-out evidence;
- open/view Rent Nonpayment cases and post authorized Rent Nonpayment events;
- record approved pet departure and perform the active-Lease Pet Deposit qualifying
  refund review;
- manage Meters, Readings, Utility Rates, and Service Rates;
- generate, issue, adjust, and exceptionally void Invoices;
- review Late-payment eligibility/proposals;
- finalize Late-payment Decisions independently of generic Invoice editing;
- correct or reverse Late-payment Charges through their approved process;
- confirm and reverse Payments;
- view Receipts and perform authorized Receipt reprints;
- post and reverse Payment Allocations;
- recognize, apply, and reverse Customer Credit;
- create and correct Refunds;
- record Deposit receipts, applications, dispositions, and Refunds;
- prepare and close Final Settlements;
- manage exchange-rate fallback entries;
- view the Customer Account Ledger;
- view and export reports;
- view audit history;
- manage user accounts, role bundles, and capabilities; and
- operate migrations, backups, restore, and deployment administration.

## SEC-021 — Configurable Role Bundles

A deployment may group capabilities into named roles, but role names and their
capability mappings are configured data. Specifications and code must authorize
capabilities, not assume that a role title inherently grants a financial right.

Amended by DL-074 (owner, 2026-10-04 and 2026-10-20): the default bundles are Owner, Manager and Staff (OOD-SEC-001), still configurable data. Settings access is its own per-user capability that only the Owner account class gives or removes and always has, as the Owner-only resets of DL-058 are tied to the account class, not to a role name.

Amended by DL-081 (login sub-slice L1b-1): capabilities are configured data too, in the append-only catalog of docs/004 DB-AUTH-006 (75 capabilities, among them the approved `settings.manage`, `operations.status.read`, `property.read` and `units.read`); each capability has one grant path: a bundle may hold only `bundle` capabilities (enforced from L1b-2), never `settings.manage` (per user), `identity.manage_access` (Owner account class only, Q-2026-10-21-162 (b)) or `rent_nonpayment.evaluate` (service principal); `billing.generate` is a bundle capability (Q-2026-10-21-161 (a)).

Amended by DL-081 (login sub-slices L1b-2 and L1d): role bundles and their assignments are append-only data of docs/004 DB-AUTH-007, and a bundle can hold only `bundle` capabilities; the effective grants of an active, classified account are read fresh on every read (`actor_capability_grants`), so a removed capability, assignment or Settings access stops at the next read. `identity.manage_access` comes only from the Owner account class; `settings.manage` comes from the Owner account class and from a per-user grant that only the Owner gives or removes (docs/004 DB-AUTH-008).

Amended by DL-081 (login sub-slice L1c): the default Owner, Manager and Staff bundles are seeded once per Property as editable data (docs/004 DB-AUTH-009); the Owner and Manager bundles hold the same bundle capabilities, and the Staff bundle holds no approval, administration, audit, export or money-at-once capability. The bundle names give no power by themselves; only their capabilities do.

Amended by DL-081 (login sub-slice L1e): a Staff account's per-user `settings.manage` is given and read only while its sign-in code is set up (SEC-013).

## SEC-022 — Separation of Capabilities

Capabilities for entering source data, authorizing a financial action, reversing
or correcting that action, viewing audit history, and administering permissions must
remain separable. A deployment may assign multiple capabilities to one person, but
the system must not require that combination.

Generic Invoice management must not imply authority to finalize, reduce, or waive a
Late-payment Decision. Generic Deposit or Refund management must not imply authority
to perform the active-Lease Pet Deposit qualifying review. Generic Lease-warning
authority must not imply authority to post a Rent Nonpayment Serious Default.

## SEC-023 — Server-side Enforcement

Every API action and scheduled operation must enforce authorization on the
server. Client-provided status, owner, Property, Customer, Lease, amount, rate,
balance, or authorization assertions are untrusted.

# 7. Financial-operation Security

## SEC-024 — Explicit Financial Actions

Financial and business-significant changes must use explicit operations rather than
unrestricted record mutation. This includes issuance, Adjustment, voiding,
Late-payment final Decision, Late-payment Charge correction/reversal, Payment
confirmation, Receipt reprint, Allocation, Customer Credit recognition/application/
reversal, Refund, Reversal, Deposit receipt/application/disposition, active-Lease Pet
Deposit qualifying refund review, Rent Nonpayment milestone/follow-up posting, and
Settlement closure.

## SEC-025 — Required Financial Authorization

The API/service layer must enforce the authorization requirements in
`BR-AUTH-001` through `BR-AUTH-009`. Possession of database or generic edit access
must not imply authority for a financial action.

## SEC-026 — Trusted Calculations

Invoice balances, separate Late-payment Charge balances and default calculations,
allocation availability, Customer Credit balances, Deposit balances, Settlement
results, Utility consumption, proration, and KHR conversion must be calculated or
verified by trusted server-side logic. Callers must not set derived balances,
statuses, default percentages, or financial availability directly.

## SEC-027 — Exchange-rate Fallback

Manual entry of an ABA-equivalent reference Sell rate is permitted only when the
automatic source is unavailable and the actor has the configured capability. The
server must still apply the mandatory `1.005` multiplier and both upward-rounding
rules from `BR-MONEY-004` through `BR-MONEY-010`.

## SEC-028 — Idempotency and Replay Protection

Financial and scheduled commands that may be retried must use idempotency and
uniqueness controls. Replayed requests must return the prior result or a conflict
without duplicating an Invoice, Late-payment Decision/Charge, Payment, Receipt,
Receipt reprint event, Allocation, Customer Credit event, Refund, Deposit event,
Rent Nonpayment event, or Reversal.

## SEC-029 — Concurrency Protection

Concurrent financial actions must lock or version the affected aggregate and
revalidate limits inside one database transaction. Authorization checked before
a stale read must be checked again when required at execution time.

# 8. Audit and Tamper Resistance

## SEC-030 — Audit Event Minimum

Every security-sensitive or business-significant action must preserve:

- actor identity or system job identity;
- Property scope;
- action and target type/identifier;
- timestamp in UTC and relevant Property-local business date;
- previous and resulting state or linked source event;
- reason and authorization evidence where required;
- correlation/request identifier; and
- outcome, including rejected high-risk attempts where safe to record.

## SEC-031 — Append-only Audit Storage

Ordinary application roles must not update or delete audit events. Audit storage
must use append-only application permissions and database controls. Corrections
create new linked events.

## SEC-032 — Audit Access

Audit viewing and export require separate capabilities. Audit data must be
filtered to authorized Property scope and must not expose secrets.

Amended by DL-072 (owner, 2026-10-04): by default the Owner and the Manager get all reports, audit search, audit export and data export; Staff get only the operational reports, with no money totals, no audit search, no audit export and no data export. The capabilities and default role bundles stay configurable (OOD-SEC-001); the capability names are proposed at V1-057 planning. Every export and every audit search writes an audit event; ordinary report views do not.

## SEC-033 — Clock Integrity

Application, worker, and database hosts must use reliable time synchronization.
Audit timestamps are recorded in UTC; Property-local dates retain the configured
timezone context.

## SEC-034 — Audit Monitoring

Monitoring should support alerting or high-value review for repeated authentication
failures, permission changes, financial reversals, exceptional Invoice voids,
Late-payment final Decisions and Charge corrections/reversals, active-Lease Pet Deposit
qualifying Refund activity, Rent Nonpayment Serious Default events, manual
exchange-rate fallback, unusual Receipt reprint activity where operationally useful,
backup failures, restore attempts, and audit-write failures.

Not every business event must generate a real-time alert; deployment policy may choose
which audited high-value events become operational alerts.

# 9. API and Input Security

## SEC-035 — Transport Security

All browser and API traffic must use TLS, including LAN deployments unless an
explicitly isolated terminating reverse proxy provides the protected channel.
Plain HTTP must not carry credentials or session tokens.

## SEC-036 — Input Validation

The API must validate type, length, format, allowed values, date ranges, money
units, identifiers, file metadata, and cross-resource relationships before use.
Validation must occur before business processing and again at database boundaries
through constraints where appropriate.

## SEC-037 — Injection Prevention

Database access must use parameterized queries. Templates and UI rendering must
escape untrusted data by context. Shell commands must not interpolate untrusted
values. Unsafe deserialization and dynamic code execution are prohibited.

## SEC-038 — Object-level Authorization

Every request referencing a Customer, Unit, Reservation, Lease, Invoice, Payment,
or other record must verify the actor may access that exact object and its
Property. Sequential or guessed identifiers must not bypass authorization.

## SEC-039 — Error Responses

External errors must be consistent and must not disclose stack traces, SQL,
credentials, configuration paths, or unauthorized record existence. Detailed
diagnostics belong in protected logs correlated by an error identifier.

## SEC-040 — Pagination and Resource Limits

List, search, export, and upload operations require bounded pagination, size
limits, timeouts, and rate controls to prevent accidental or malicious resource
exhaustion.

# 10. Customer Data Protection

## SEC-041 — Field-level Minimization

Customer lists and search results should expose only fields needed for the current
workflow. More sensitive details require explicit navigation and authorization.

Amended by DL-071 (owner, 2026-10-20): the owner approves a new Customer field "ID number / Passport number" (DB-CUST-001). It is a sensitive detail: it never appears in exports or in the top bar search (UI-010).

Amended by DL-072 (owner, 2026-10-04): an export shows a Customer only with name, Unit and phone number: no ID number, no address and no ID document.

Amended by DL-078 (owner, 2026-10-20): the owner approves date of birth, gender and nationality as Customer fields (SEC-006). The Customers page search may find a Customer by ID number without listing it; exports still hold only name, Unit and phone.

## SEC-042 — Export Protection

Customer and financial exports require an export capability, an audit event, and
bounded scope. Export files must be protected in transit and removed from temporary
storage according to a configured retention policy.

Amended by DL-072 (owner, 2026-10-04): exports are CSV only. A small export downloads at once and is not stored on the server; an export job file is kept 24 hours and then deleted. An audit export's SHA-256 fingerprint is saved in its own audit event.

## SEC-043 — Logging Redaction

Logs must redact credentials, tokens, full request bodies containing Customer or
financial data, and secrets. Identifiers may be logged only where needed for
operability and audit correlation.

## SEC-044 — Browser Data Handling

Sensitive data must not be persisted in browser local storage unless a reviewed
security design requires it. Logout and session expiration must remove accessible
session material.

# 11. Database Security

## SEC-045 — Separate Database Identities

Application runtime, migrations, backup, restore, and human administration must
use separate database identities with least-privilege grants.

## SEC-046 — Application Database Privilege

The runtime identity must not own the schema, disable triggers, alter constraints,
or delete append-only audit/financial records through ordinary operations.

## SEC-047 — Administrative Access

Direct production database access is exceptional, restricted, logged where
practical, and performed through controlled administration paths. Direct edits to
financial history are prohibited.

## SEC-048 — Constraint Integrity

Database constraints and transactions form part of the security boundary against
malformed or concurrent writes. Application authorization does not justify
removing integrity constraints.

# 12. Secrets and Credentials

## SEC-049 — Secret Sources

Secrets must come from protected deployment configuration or a secret-management
mechanism. They must never be committed to Git, embedded in images, printed in
logs, or included in client bundles.

## SEC-050 — Secret Separation

Development, test, staging, and production use distinct secrets. Backup encryption
keys and database credentials must be separate from ordinary application secrets.

## SEC-051 — Rotation

Deployments must support rotation of signing keys, database credentials, external
service credentials, and backup keys without rewriting historical business data.

# 13. Backups and Recovery Security

## SEC-052 — Encrypted Backups

Backups containing Confidential or Restricted data must be encrypted at rest and
in transit. Access to backup data and keys must be separately controlled.

## SEC-053 — Backup Integrity

Backups must include integrity verification and enough metadata to identify
application version, schema migration version, creation time, and scope.

## SEC-054 — Restore Authorization

Restore is a privileged operational action requiring explicit authorization,
recorded operator identity, target environment verification, and a documented
procedure that prevents accidental overwrite of the wrong database.

## SEC-055 — Restore Testing

Backups are not considered reliable until periodic restoration tests verify that
schema, business data, financial history, and audit records can be recovered.
Test restores must protect or sanitize Customer data.

# 14. LAN and Remote Access

## SEC-056 — LAN Deployment Boundary

LAN hosting reduces public exposure but is not a trust substitute. Authentication,
authorization, TLS, patching, audit, and backup controls remain mandatory.

## SEC-057 — Network Exposure

Only the reverse proxy or approved application entry point should be reachable by
ordinary clients. PostgreSQL, internal backend ports, worker controls, and
administration interfaces must not be broadly exposed.

## SEC-058 — Controlled Remote Access

Remote administration or user access is optional and disabled unless deliberately
configured. When enabled, it must use an authenticated encrypted access layer such
as a managed VPN or equivalent controlled gateway, with MFA support, source
restrictions where practical, and audit logging.

Amended by DL-071 (owner, 2026-10-05): remote access is off in V1; the system is reached only on the office network.

## SEC-059 — No Required Cloud Dependency

Core local operation must not require a new cloud service. Optional external
identity, exchange-rate retrieval, monitoring, or remote-access services must fail
safely and must not weaken local business integrity.

Amended by DL-071 (owner, 2026-10-05): the critical alerts are also sent by Telegram message (DEPLOY-051). Telegram is such an optional service: the alerts carry no Customer data, the bot token is a secret kept out of the repository and the logs, and when a message cannot be sent the system keeps working and the health page shows the warning. No cloud storage service is used for backups.

# 15. Application and Dependency Security

## SEC-060 — Supported Components

Frontend, backend, database, reverse proxy, base images, and dependencies must be
maintained at supported security patch levels under a controlled update process.

## SEC-061 — Dependency Review

Dependency changes require review of provenance, licensing, maintenance, known
vulnerabilities, and necessity. Lockfiles and reproducible builds must be used
where supported.

## SEC-062 — Secure Build and Delivery

Build artifacts must be produced from reviewed source, exclude development
secrets, and be identifiable by version or commit. Deployment must not execute
unreviewed scripts from writable runtime data directories.

## SEC-063 — File Handling

If later requirements permit document or evidence uploads, allowed type, size,
name, storage path, and malware controls must be specified before enabling them.
This document does not itself authorize a new upload feature.

Amended by DL-077 (owner, 2026-10-20): the owner approves one upload: an optional photo or PDF proof of payment (at most 5 MB) on a Payment, kept and never deleted, opened only by users who may see that Payment. It is built in its own later file storage step after V1-056, with the file name, storage path and malware controls specified first; `python-multipart` needs the owner's yes then. Nothing is enabled before that step.

# 16. Logging, Monitoring, and Incident Response

## SEC-064 — Operational Logging

Services must emit structured logs with timestamp, severity, service, environment,
correlation identifier, and safe diagnostic context. Audit events remain distinct
from ordinary diagnostic logs.

## SEC-065 — Log Protection

Logs must be access-controlled, protected from casual alteration, rotated, and
retained according to configured operational policy without retaining secrets.

## SEC-066 — Security Alerts

Deployments must support alerts for authentication abuse, privilege changes,
critical service failure, database unavailability, migration failure, scheduled
billing failure, audit-write failure, low backup freshness, and low disk capacity.

## SEC-067 — Incident Procedure

A documented incident procedure must cover containment, credential/session
revocation, evidence preservation, recovery, validation of financial history, and
post-incident review.

# 17. Security Verification

## SEC-068 — Required Security Tests

The testing strategy must cover:

- authentication success, failure, lockout/rate limiting, and revocation;
- capability and object-level authorization for every protected action;
- financial/business-action bypass attempts, including Late-payment Decision/Charge,
  Receipt reprint, active-Lease Pet Deposit refund review, and Rent Nonpayment events;
- CSRF, injection, XSS, unsafe file/path, and sensitive-error controls;
- concurrency and idempotency for financial operations and business-significant
  append-only commands;
- append-only audit behavior;
- secret and log redaction;
- backup integrity and restore authorization; and
- remote-access-disabled defaults.

## SEC-069 — Security Review Gate

Changes to authentication, authorization, financial endpoints, audit storage,
secret handling, backup/restore, or network exposure require focused security
review before deployment.

## SEC-070 — High-value Workflow Authorization Boundaries

The security model must preserve the separate authorization boundaries already
defined by the authoritative API/UI:

- a Late-payment final Decision is distinct from generic Invoice edit/issue authority;
- a Late-payment Charge correction/reversal is distinct from the original Decision;
- Receipt reprint is an audited financial-document action and must not create or
  imply another Payment or Receipt identity;
- active-Lease Pet Deposit Refund qualification is distinct from ordinary Deposit
  management and from Refund execution;
- Lease-violation warnings are distinct from Rent Nonpayment case/event authority; and
- Customer Account Ledger access is read-only and must not imply authority to mutate
  its source financial records.

Server-side authorization must enforce these boundaries even when one deployment
assigns several capabilities to the same person.

## SEC-071 — Recovery Codes

Recovery codes must be securely generated, presented only through a protected one-time
flow, independently consumable, and non-reusable. If verification material is retained
server-side, usable codes must not be stored in plaintext. Generation, regeneration,
use, rejection, and related session revocation are auditable. Recovery endpoints retain
rate limiting and account-enumeration protection.

Amended by DL-081 (login sub-slice L7a, Q-2026-10-24-188): each recovery code holds 60 random bits from the operating system's secure source, written as 12 symbols of Crockford's Base32 so it can be copied by hand; it is stored only as an Argon2id verifier of its canonical form (capitals, no dashes or spaces, I and L as 1, O as 0), and wrong codes count toward the sign-in wait.

## SEC-072 — Controlled Administrative Recovery

Recovery never bypasses authorization. Owner may administratively reset/recover Manager
and Staff accounts. Staff ordinary authority cannot reset/recover Owner or Manager, and
Manager recovery of Staff is not granted unless separately and explicitly approved.
Owner recovery uses Owner recovery codes or a deliberate controlled server-side
emergency procedure; there is no ordinary unauthenticated web “reset Owner” function.
All security-sensitive recovery actions create immutable audit evidence without secrets.

## SEC-073 — Initial Owner Bootstrap

The initial Owner is created through a protected command-line procedure on the
production server, only while no account or bootstrap closure exists. Password input is
interactive and first validated as 15–128 Unicode code points. It is then NFC-normalized,
revalidated as nonempty and 15–128 code points, locally blocklisted as the complete normalized
value, and hashed and verified in full without truncation. Spaces, paste, and password managers are permitted;
character-composition and periodic-rotation rules are prohibited. A locally controlled
blocklist rejects compromised, common, expected, and project-context passwords without
exposing candidates externally. Password material never appears in arguments, shell
history, process listings, ordinary environment variables, logs, source control, or compact
state.

Bootstrap generates exactly 10 cryptographically random independently single-use recovery
codes, presents them exactly once through the controlling TTY, persists only protected
verifiers, and requires explicit acknowledgement before commit. One absolute monotonic
ceremony deadline starts before TOTP confirmation and covers TOTP input, recovery presentation
and complete persistence writes, acknowledgement input, and commit preparation. Writes,
partial input, retries, and trickled input never reset or extend it. Presentation,
confirmation, TTY, acknowledgement, or deadline failure rolls back completely. Required
Owner TOTP enrollment is confirmed and its protected material is persisted within the same
atomic operation. Its protection key is supplied only through an already-open
root-controlled descriptor or equivalent protected secret file, never arguments, logs,
repository or compact state, or ordinary environment variables. A dedicated least-privilege
one-time database identity is restricted to this atomic boundary.

Amended by DL-081 (login sub-slice L7b): the initial Owner's username is stored in the sign-in form (NFC, lower case), the same form account creation stores and sign-in looks up; a username with U+200B or any other character that is not printable, or one that tidying would change, is refused, and the stored username and the display and audit names follow the account name rule of account creation (1 to 128 characters, NFC, no two spaces in a row, none of the hidden characters); the bootstrap may refuse a few names account creation would tidy and accept, such as one with U+200B.

Amended by DL-081 (login sub-slice L7c; Q-2026-10-24-189): on the Mac mini the protection key is a root-owned file with mode 0600 at `/usr/local/etc/prm/totp_protection_key` (64 hex characters from `openssl rand -hex 32`, made by root with umask 077). A small root-owned helper installed at `/usr/local/libexec/prm/with-protected-key.py` is the only part run with sudo: it refuses to run except as root under sudo from a person's own account, opens the key without following a symbolic link, with the bootstrap's checks (a regular root-owned file that neither the group nor others can read) plus one link, and only a file named `totp_protection_key` in a root-owned folder that neither the group nor others can write, places it on descriptor 4, closes every other descriptor from 3 up, drops to that person's user, group and groups for good (and checks that root cannot be taken back), and runs the Owner set-up or the API as that person. The set-up reads the bootstrap database address and the blocklist from descriptors 3 and 5, and gets 900 seconds from showing the TOTP key to the acknowledgement. The API runs with `APP_ENVIRONMENT=production` and `APP_TOTP_KEY_FILE=/dev/fd/4`; the key reader copies an inherited `/dev/fd/<n>` descriptor instead of opening the path again, which Linux refuses for a root-only file once the helper has dropped to the person's user. No password, key or database address is a command argument or printed.

## SEC-074 — Bootstrap Closure

After the initial Owner is established, bootstrap cannot create another Owner or remain
as a credential/recovery backdoor. Subsequent account creation follows normal authorized
account-management controls. Bootstrap, password, MFA, and recovery-code secrets are
never committed to Git. Successful atomic closure permanently revokes bootstrap mutation
capability. Every later attempt fails closed and creates immutable secret-free rejection
evidence; recovery and emergency procedures cannot reactivate or bypass closure.

## SEC-075 — Recovery and Authentication Audit

Account creation/disablement, password changes/recovery, MFA enrollment/challenge reset
or disablement, recovery-code lifecycle, administrative/emergency recovery, session
creation/revocation, material privilege changes, and initial Owner bootstrap preserve
actor or controlled-procedure identity, target, timestamp, reason, outcome, correlation,
and applicable previous/resulting non-secret state in immutable audit evidence.

# 18. RESOLVED AND OPEN OWNER DECISIONS

## OOD-SEC-001 — Staff Role Mapping

**Question:** Which named staff roles receive each capability bundle in the live
business?

**Current treatment:** Capability definitions and role bundles are configurable.
No role name is granted an irreversible financial authority by this specification.

**RESOLVED by DL-074 (owner, 2026-10-04):** default bundles Owner (every capability), Manager (all daily work, approvals, reports, audit history, exports and the health page; no user or role administration) and Staff (daily data entry only; no approvals, administration, audit or export). The bundles stay configurable.

**Blocking:** No. Database, API, UI, and testing designs can enforce capabilities
without fixing the Owner's organizational mapping.

## OOD-SEC-002 — Mandatory MFA Scope

**Resolved question:** Which users or access paths must use MFA in production?

**Resolution:** Owner and Manager require MFA; Staff MFA is optional. Stricter
remote-access controls remain authoritative. See `DL-056`.

**Status:** Resolved by final Owner approval.

# 19. Traceability Summary

| Security area | Upstream authority |
|---|---|
| Financial authorization | `BR-AUTH-*` |
| Audit reconstruction | `BR-AUDIT-*` |
| Invoice lifecycle and correction | `BR-INV-001` through `BR-INV-050` |
| Late-payment Decision/Charge | `BR-INV-051` through `BR-INV-055`, `BR-LATE-*` |
| Payment and Allocation integrity | `BR-PAY-*` |
| Receipt and reprint integrity | `BR-RECEIPT-*` |
| Customer Credit and Refund integrity | `BR-CREDIT-*`, `BR-REFUND-*` |
| Customer Account Ledger access/integrity | `BR-LEDGER-*` |
| Deposit and active-Lease Pet Refund controls | `BR-DEP-*`, applicable `BR-REFUND-*` |
| Rent Nonpayment authorization boundary | `BR-LEASE-026` through `BR-LEASE-030`, applicable `BR-PAY-*` |
| Settlement controls | `BR-SETTLE-*` |
| Currency and exchange integrity | `BR-MONEY-*` |
| Property-local time and history | `BR-PROP-*`, `BR-AUDIT-*` |

# 20. Completion Criteria

This Security Model is complete for Owner Review when:

- every protected business action is capability-gated server-side;
- authentication and session properties are specified without inventing staff
  authority;
- financial records and audit history cannot be silently mutated;
- Customer data, secrets, backups, database access, and logs have explicit
  protections;
- LAN and optional remote-access assumptions are explicit;
- security verification requirements and the high-value workflow authorization
  boundaries are traceable; and
- only the named role-to-capability bundle mapping remains an open operational choice;
  the production MFA mapping is resolved.
