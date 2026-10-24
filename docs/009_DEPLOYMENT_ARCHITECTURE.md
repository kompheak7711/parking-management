# 009 — Deployment Architecture

**Document Status:** Owner Review
**Authority:** Downstream of `001_DOMAIN_MODEL.md` through `008_SECURITY_MODEL.md`
**Scope:** Production-oriented deployment, operation, backup, recovery, and update architecture
**Requirement identifiers:** `DEPLOY-*`

---

# 1. Purpose

This document defines how the Property Rental Management System is built,
deployed, operated, backed up, monitored, and recovered. It preserves the
established technology direction:

- React, TypeScript, and Vite frontend;
- FastAPI and Python backend;
- PostgreSQL database;
- Docker Compose development and single-site deployment packaging;
- REST API; and
- automated frontend and backend tests.

The default deployment is a production-oriented local-network installation. Core
operation must not depend on a newly introduced cloud service.

# 2. Architectural Principles

## DEPLOY-001 — Single Authoritative Database

One PostgreSQL database is the authoritative transactional store for business,
financial, audit, authorization, and scheduling state. Application containers
must not maintain competing writable business stores.

## DEPLOY-002 — Stateless Application Services

Frontend delivery and backend API instances are replaceable. Durable state belongs
in PostgreSQL or an explicitly specified durable file store if a later approved
feature requires one.

## DEPLOY-003 — Server-side Business Enforcement

Business rules, calculations, authorization, idempotency, and transaction
boundaries are enforced by the backend and database. The frontend is not a trusted
business-rule boundary.

## DEPLOY-004 — Local-first Operation

Routine property-management workflows remain available on the configured LAN
without requiring public Internet access, except optional external functions such
as automatic ABA reference-rate retrieval.

## DEPLOY-005 — Recoverability Before Optimization

Deployment changes must preserve database history, migration safety, backup
recoverability, and auditability before considering performance optimization.

# 3. Logical Runtime Topology

## DEPLOY-006 — Components

```text
LAN Browser
    │ HTTPS
    ▼
Reverse Proxy / TLS Entry Point
    ├────────► Static React/Vite Build
    │
    └────────► FastAPI API
                   │
                   ├────────► PostgreSQL
                   │
                   └────────► Scheduled Worker
                                  │
                                  └────────► PostgreSQL

Operations Host
    ├── Backup job ───────────────► Encrypted backup storage
    ├── Monitoring / log collection
    └── Controlled migration and restore tooling
```

## DEPLOY-007 — Reverse Proxy

A reverse proxy terminates TLS, serves or routes the frontend, routes `/api`
requests to FastAPI, applies request-size and timeout limits, and emits access
logs without credentials or sensitive bodies.

## DEPLOY-008 — Frontend

The frontend is a versioned production Vite build served as static assets. Runtime
configuration contains only non-secret public values such as the API base path and
build identifier.

## DEPLOY-009 — Backend

FastAPI runs as a non-root process with explicit worker configuration, health
endpoints, structured logs, database connection pooling, and graceful shutdown.
Backend images contain no development credentials.

## DEPLOY-010 — Scheduled Worker

Scheduled billing, Reservation expiration, Utility generation, and other approved
system actions execute in a separately identifiable worker process using the same
backend business services and database constraints. The worker must not implement
a second version of business logic.

## DEPLOY-011 — PostgreSQL

PostgreSQL runs on durable storage with a fixed supported major version, restricted
network exposure, health checks, configured timezone behavior, and regular
backups. The application connects through a least-privilege runtime identity.

# 4. Network Architecture

## DEPLOY-012 — LAN Entry Point

Ordinary users access one stable HTTPS hostname or address on the Property's LAN.
Only the reverse-proxy port is exposed to user devices.

## DEPLOY-013 — Internal Ports

Backend, PostgreSQL, worker-control, metrics, and administration ports are bound
to a private container or host network and are not exposed broadly to the LAN.

## DEPLOY-014 — TLS

Credentials and sessions must use TLS even on the LAN. A locally trusted
certificate authority, managed device trust, or another reviewed certificate
strategy may be used. Certificate renewal must be documented and monitored.

Amended by DL-081 (login sub-slice L7c; Q-2026-10-24-189): until the server deployment, the app runs on the Mac mini (README, "Local run on the Mac mini"). The LAN entry point (DEPLOY-012) is the HTTPS screen server on port 5173 (`npm run dev:local`, which refuses to start without the certificate), which forwards `/api` to the API; the screen server adds X-Forwarded-For, which the API's server trusts from 127.0.0.1 only, so sign-in waits and audit sources see each device; the API listens on 127.0.0.1:8000 only and PostgreSQL on 127.0.0.1 only (DEPLOY-013). TLS uses a local certificate authority made on the Mac (10 years; the script warns 60 days before it ends) that the owner trusts once on the Mac and on the iPad, and a server certificate for the Mac's `.local` name, `localhost` and 127.0.0.1 (365 days), renewed yearly by running `scripts/local/make-certificate.sh` again. Local secrets (DEPLOY-019) are files in the ignored `.local/secrets` folder (0700; the database password files 0444 so the database container can read them; the address files 0600); the TOTP protection key is the root-only file of SEC-073.

## DEPLOY-015 — Optional Remote Access

Remote access is disabled by default. If enabled, it uses a controlled encrypted
gateway such as a managed VPN or equivalent access layer with authenticated users,
MFA capability, and audit logging. PostgreSQL and internal service ports are never
published directly to the Internet.

Amended by DL-071 (owner, 2026-10-05): remote access is off in V1; the system is reached only on the office network (resolves `OOD-DEPLOY-003` for V1).

Built in V1-059 part A (2026-10-24): `config/deployment/production-operations.json` says `remote_access.enabled: false`, and `scripts/validate-deployment-config.py check-examples` refuses any other value. Runbook: `docs/V1_059_OPERATIONS_RUNBOOK.md`.

## DEPLOY-016 — External Egress

Outbound access is restricted to explicitly configured dependencies. Failure of
automatic ABA reference-rate retrieval must activate the authorized manual
reference-rate fallback without bypassing markup, rounding, or audit rules.

Amended by DL-071 (owner, 2026-10-05): the allowed list also has one outbound connection to Telegram, used only for the critical alert messages of DEPLOY-051. The Telegram bot token is a secret: a placeholder in V1-059, never in the repository or in a log.

Built in V1-059 part A (2026-10-24): the outbound allowed list in `config/deployment/production-operations.json` is exactly `api.telegram.org` (no automatic exchange-rate host exists yet; it is added when that function is built); the validator refuses another host, a secret value in the file, and anything shaped like a Telegram bot token under `config/deployment/`. The bot token and the Owner and Manager chat ids are files under `/run/secrets/`; the repository holds placeholders only.

# 5. Environment Model

## DEPLOY-017 — Environments

Development, test, staging where used, and production have separate databases,
credentials, secrets, and configuration. Production data must not be copied to a
less protected environment without explicit authorization and appropriate
sanitization.

## DEPLOY-018 — Configuration

Environment-specific configuration includes:

- deployment environment name;
- public base URL and API origin;
- Property timezone;
- database connection details;
- session/authentication settings;
- trusted proxy and origin settings;
- worker schedule and lock settings;
- automatic exchange-rate source settings;
- log level and destination;
- backup destination and encryption configuration;
- monitoring thresholds; and
- optional remote-access integration.

Business configuration such as accepted Payment Methods, rates, capability
bundles, and Property data remains controlled application data rather than image
configuration.

## DEPLOY-019 — Secret Injection

Secrets are injected at deployment from protected host configuration or an
approved secret store. `.env` files containing production secrets, database dumps,
and backup keys must not be committed.

## DEPLOY-020 — Immutable Build Identity

Every deployed frontend and backend artifact records a version or Git commit. The
UI and operational health output make the deployed build identity available to
authorized support staff without exposing secrets.

# 6. Container and Process Layout

## DEPLOY-021 — Compose Services

The production-oriented Compose topology contains separately managed services for:

- reverse proxy/frontend;
- backend API;
- scheduled worker;
- PostgreSQL; and
- optional monitoring/logging components.

Development tooling may add hot reload or exposed ports but must not define the
production security posture.

## DEPLOY-022 — Non-root Runtime

Application and proxy containers run as non-root users wherever supported.
Writable mounts are limited to explicitly required runtime paths.

## DEPLOY-023 — Health Checks

At minimum:

- **liveness** confirms a process is running;
- **readiness** confirms the API can safely serve requests and reach the database;
- **worker health** reports last heartbeat and last successful scheduled-job run;
- **database health** confirms PostgreSQL accepts authenticated checks; and
- **proxy health** confirms routing is available.

Readiness must not expose sensitive diagnostics to unauthenticated clients.

## DEPLOY-024 — Graceful Lifecycle

API and worker processes stop accepting new work, complete or roll back active
transactions, and close connections during shutdown. Container restart must not
leave a financial operation partially committed.

## DEPLOY-025 — Restart Policy

Long-running services restart after unexpected failure with bounded backoff.
Repeated failure must trigger an alert rather than an uncontrolled tight loop.

# 7. Scheduled Operations

## DEPLOY-026 — Database-backed Scheduling State

Every scheduled business operation preserves its logical business date, start and
completion time, outcome, correlation identifier, and idempotency key in durable
state.

## DEPLOY-027 — Singleton Execution

A database advisory lock, unique job-run constraint, or equivalent transactionally
safe mechanism ensures only one active execution of each singleton scheduled task
for the same Property and logical period.

## DEPLOY-028 — Idempotent Jobs

Retries must not duplicate Reservation cancellation, Rent Invoice, Utility
Invoice, Service line, Rent Nonpayment milestone/event, or another scheduled
business or financial event. Duplicate-prevention keys and business constraints
are rechecked inside the transaction.

Interactive high-value commands that may be retried—including Late-payment final
Decision/Charge creation, Receipt reprint, active-Lease Pet Deposit refund review,
Payment/Allocation/Customer Credit/Refund actions, and their corrections or
reversals—use the idempotency and uniqueness protections defined by
`005_API_SPECIFICATION.md` and `008_SECURITY_MODEL.md`. Deployment retries must
never bypass those controls.

## DEPLOY-029 — Property-local Scheduling

Schedules use the configured Property timezone for business-day behavior and
preserve UTC execution timestamps. Host or container timezone must not silently
change the business date.

## DEPLOY-030 — Job Failure

A failed job records the error safely, rolls back incomplete transactions, remains
retryable, and generates an operational alert. Operators may retry through an
explicit authorized action; they must not manually insert missing financial rows.

## DEPLOY-031 — Expected Scheduled Tasks

The worker supports only tasks derived from approved rules, including:

- Property-local Reservation expiration cancellation;
- recurring Rent Invoice and fixed Service line generation on the 25th;
- Utility Invoice generation after validated monthly Reading inputs or a completed
  approved broken-Meter estimate;
- overdue-Invoice evaluation needed to detect and present an eligible Late-payment
  proposal, without automatically finalizing a Decision or creating a Charge;
- Rent Nonpayment day-count and milestone evaluation needed for the 20-day alert
  and 30-day Serious Nonpayment Default record, while Notice issuance, authorized
  follow-up, and Lease termination remain separate actions under their approved
  authorization boundaries; and
- health/alert evaluation.

This list does not authorize a new charge, penalty, status, automatic Allocation,
automatic Customer Credit recognition, automatic Late-payment final Decision, or
automatic Lease termination.

Backup execution and verification run as a separately privileged Operations Host
job under the backup identity, not through the application scheduled worker or its
database role.

# 8. Database Migrations

## DEPLOY-032 — Migration Tooling

Every schema change uses a versioned migration committed with the application.
Production schema changes must never be performed by ad hoc manual DDL as the
normal deployment path.

## DEPLOY-033 — Forward-safe Design

Migrations use expand-and-contract sequencing where a direct change could break a
running version. New nullable structures, backfills, constraint validation, and
code cutover are separated when necessary.

## DEPLOY-034 — Financial Preservation

A migration must not overwrite, collapse, or discard historical financial events,
rates, source links, audit actors, original amounts, or statuses. Data conversion
must be deterministic, reviewable, and tested on a representative restored copy.

## DEPLOY-035 — Pre-migration Gate

Before production migration:

1. verify a recent successful backup;
2. verify available disk capacity;
3. confirm application and database versions;
4. review migration locks and expected duration;
5. run migration tests and integrity checks;
6. announce the maintenance impact where applicable; and
7. confirm the recovery procedure.

## DEPLOY-036 — Migration Execution

Only the migration identity may alter the schema. The application is placed in a
compatible mode or maintenance window when required. Migration output is retained
without secrets.

## DEPLOY-037 — Post-migration Verification

Verify schema version, constraints, row-count/integrity checks, API readiness,
worker readiness, representative read paths, and absence of unexpected errors
before declaring the deployment successful.

## DEPLOY-038 — No Destructive Automatic Rollback

A failed migration does not trigger an unreviewed destructive database rollback.
Recovery uses the migration's reviewed forward fix or an explicitly authorized
restore procedure.

# 9. Backup Architecture

## DEPLOY-039 — Backup Scope

Backups include PostgreSQL business and audit data, schema/migration metadata, and
required deployment configuration. Secrets and encryption keys are backed up
through a separately protected process.

## DEPLOY-040 — Backup Types

The deployment supports:

- frequent automated database backups suitable for point-in-time or bounded-loss
  recovery where configured;
- periodic full logical or physical backups;
- a pre-migration backup; and
- protected copies separated from the primary host or storage failure domain.

## DEPLOY-041 — Encryption and Access

Backup data is encrypted in transit and at rest. Backup credentials and encryption
keys are not available to ordinary application users or embedded in client code.

## DEPLOY-042 — Backup Verification

Each run records start/end time, source database identity, schema version, size,
checksum or integrity result, destination, retention class, and outcome. Empty,
truncated, or stale backups fail the job.

## DEPLOY-043 — Retention

Backup retention and off-host-copy frequency are deployment configuration pending
Owner confirmation of recovery objectives. Retention automation must never delete
the final known good backup.

Amended by DL-071 (owner, 2026-10-05): hourly copies are kept 2 days, daily copies 30 days and monthly copies 12 months; the last good copy is never deleted. A daily encrypted copy goes to an external drive or a second computer in the office, and a weekly encrypted copy is kept outside the building. No cloud storage service is used.

Built in V1-059 part A (2026-10-24): `property-rental-backup run` (hourly timer) makes a `pg_dump` custom-format backup with the read-only backup identity on one exported snapshot, with the row count of every table of that snapshot; checks it with `pg_restore --list`; seals it with AES-256-GCM (`cryptography`) and opens it again to compare SHA-256; stores it with a DEPLOY-042 manifest; links the first good backup of a Phnom Penh day and month into the daily and monthly classes; and deletes expired copies, never a copy of the newest good backup (`backup_retention.py`). `offhost-copy --kind daily|weekly` copies the newest good backup, still encrypted, and checks the copy by SHA-256; off-host daily copies are kept 30 days and weekly copies about 12 months, never the newest (decided by Claude under the owner's 2026-10-23 22:30 rule). Runbook: `docs/V1_059_OPERATIONS_RUNBOOK.md`.

# 10. Restore and Disaster Recovery

## DEPLOY-044 — Restore Procedure

A documented restore procedure must:

1. identify the incident and target recovery point;
2. authorize the restore and record the operator;
3. preserve the failed system for investigation when practical;
4. verify target host, database, and environment;
5. restore into an isolated validation target first where practical;
6. apply required migrations only after restore compatibility is known;
7. run structural and financial integrity checks;
8. switch clients only after acceptance; and
9. record the final recovery outcome.

## DEPLOY-045 — Restore Tests

Periodic restore tests must demonstrate recovery of Customers, Leases, Rent
Nonpayment cases/events, Invoices, Late-payment Decisions/Charges and linked
corrections, Payments, Receipts and Receipt reprint history, Allocations, Customer
Credit and its events, Refunds, Deposits, pet-departure and Pet Deposit refund-review
records, Settlements, rates, and audit history.

Restore validation must also demonstrate that the read-only Customer Account Ledger
can be reconstructed from the restored authoritative financial sources; the Ledger
must not become a competing source of financial truth.

A successful backup command without a restore test is insufficient.

Amended by DL-071 (owner, 2026-10-05): a full restore test runs every 3 months and before every release.

Built in V1-059 part A (2026-10-24): `property-rental-backup restore-test` restores the newest good backup, in one transaction with owners and grants, into an empty throwaway database whose name starts with `prm_restore_test`, and compares the schema revision and the row count of every table with the backup's manifest; the health page warns when the last test failed or is more than 92 days old. The Customer Account Ledger reconstruction is a person check in the runbook until V1-060 automates it. `scripts/backup-restore-check.sh` runs the whole path on a throwaway PostgreSQL 17.6. Runbook: `docs/V1_059_OPERATIONS_RUNBOOK.md`.

## DEPLOY-046 — Recovery Validation

Validation includes:

- database constraints and migration version;
- financial source-chain reconstruction;
- Invoice, separate Late-payment Charge, Payment, Customer Credit, Deposit, Refund,
  and Settlement balance/effect recomputation;
- Receipt identity and Receipt reprint-history continuity without duplicate
  Payment or Receipt identities;
- reconstructability of the read-only Customer Account Ledger from authoritative
  source records;
- Rent Nonpayment case/event and active-Lease Pet Deposit refund-review continuity;
- latest scheduled-job and idempotency state;
- user authentication and authorization configuration;
- audit-event continuity; and
- application/worker health.

## DEPLOY-047 — Recovery Objectives

Exact Recovery Point Objective and Recovery Time Objective values are an
`OPEN OWNER DECISION`. The architecture keeps backup frequency, retention, and
recovery procedures configurable so those values can be adopted without changing
business records.

Amended by DL-071 (owner, 2026-10-05): the Recovery Point Objective is at most 1 hour of data loss, with a backup every hour; the Recovery Time Objective is 1 working day.

# 11. Logging and Monitoring

## DEPLOY-048 — Structured Logs

Proxy, API, worker, migration, backup, and database operational logs use structured
timestamps, environment/service identity, severity, and correlation identifiers.
They exclude credentials, tokens, secrets, and unnecessary Customer/financial
payloads.

## DEPLOY-049 — Audit Separation

Business audit events are durable application records and must not rely on
short-retention container stdout logs. Operational log loss must not erase business
history.

## DEPLOY-050 — Metrics

Monitor at minimum:

- service and endpoint availability;
- request rate, latency, and error rate;
- database connections, locks, transaction failures, storage, and backup age;
- worker heartbeat, job duration, failure, and retry count;
- scheduled billing and other scheduled-business-event duplicate conflicts;
- audit-write failures;
- authentication-failure and permission-change signals;
- high-value audited-event signals sufficient for configured review of exceptional
  Invoice voids, financial reversals, Late-payment final Decisions and Charge
  corrections/reversals, active-Lease Pet Deposit qualifying Refund activity, Rent
  Nonpayment Serious Default events, manual exchange-rate fallback, unusual Receipt
  reprint activity, and restore attempts;
- CPU, memory, disk, and container restart count; and
- certificate and secret-expiration warnings where observable.

## DEPLOY-051 — Alerts

Alerts must be actionable and routed to configured operators. Critical alerts
include database unavailable, backup/restore failure, audit persistence failure,
repeated scheduled-job failure, low disk space, migration failure, and TLS
certificate expiry.

Consistent with `SEC-034`, monitoring must also support configurable high-value
security review or alerting for repeated authentication failures, permission
changes, financial reversals, exceptional Invoice voids, Late-payment final
Decisions and Charge corrections/reversals, active-Lease Pet Deposit qualifying
Refund activity, Rent Nonpayment Serious Default events, manual exchange-rate
fallback, unusual Receipt reprint activity where operationally useful, and restore
attempts. Deployment policy determines which audited high-value events require
real-time alerts; this architecture does not require every business event to alert
in real time.

Amended by DL-071 (owner, 2026-10-05): critical alerts go by Telegram message to the Owner and the Manager, and the health page shows a warning. An alert carries no Customer data. When a message cannot be sent, the system keeps working and the health page warning stays (SEC-059).

Built in V1-059 part A (2026-10-24): `property-rental-ops-check run` (every 5 minutes) checks the database, the readiness page, the backup, off-host copy, restore test and migration records, repeated scheduled-job failures, free disk and the TLS certificate; the same rules (`operations_status.evaluate_warnings`) feed `GET /api/v1/operations/status` and the Telegram messages. A critical warning is sent when it starts, every 12 hours while it lasts and once when it ends; a message holds only fixed warning texts. A failed or impossible delivery is retried on the next check and shown on the health page. The audit-write failure alert waits until the application records such failures (V1-059 part B or V1-060).

## DEPLOY-052 — Log Retention

Operational log retention is configurable and bounded. Audit and financial
retention follows authoritative history requirements and is not reduced to match
operational log retention.

Amended by DL-071 (owner, 2026-10-05): technical (operational) logs are kept 90 days; audit and money history are kept forever.

Built in V1-059 part A (2026-10-24): `property-rental-log-retention` (daily) deletes operational log files older than 90 days in the configured log folder only (`.log`, `.jsonl` and their `.gz`; no sub-folders, no links); the example journal setting keeps the system journal 90 days and sends the containers' logs there. The database's audit and money history are out of its reach.

# 12. Deployment and Update Procedure

## DEPLOY-053 — Pre-deployment Checks

Before release:

- authoritative specification and migration changes are reviewed;
- frontend/backend formatting, linting, type checking, tests, and production build
  pass;
- container images build reproducibly;
- dependency/security scans meet the release policy;
- migration forward and recovery paths are tested;
- backup freshness is confirmed; and
- release notes identify schema, configuration, and operational changes.

## DEPLOY-054 — Controlled Release

A release uses versioned images/artifacts and an explicit sequence:

1. capture current versions and health;
2. create/verify the pre-release backup;
3. stop or quiesce incompatible workers;
4. apply migrations through the migration identity;
5. deploy backend and worker versions;
6. deploy frontend/proxy artifacts;
7. run health and smoke checks;
8. resume scheduling; and
9. monitor for regression.

## DEPLOY-055 — Application Rollback

When schema compatibility permits, application artifacts may be rolled back to the
last known good version. Database rollback is never assumed; migration compatibility
and forward correction are preferred to destructive history reversal.

## DEPLOY-056 — Failed Release

A failed release stops further rollout, preserves logs and current data, and uses
the reviewed recovery decision. Operators must not reset or recreate the database
to obtain a clean deployment.

# 13. Failure Modes

## DEPLOY-057 — Database Unavailable

The API becomes not ready and rejects writes safely. Workers stop acquiring new
jobs. The system must not queue unverified financial writes in browser storage for
later blind replay.

## DEPLOY-058 — Worker Unavailable

Interactive workflows may continue when safe, but scheduled work is visibly late
and alerts fire. On restart, durable job state and idempotency allow safe catch-up.

## DEPLOY-059 — External Rate Source Unavailable

The automatic reference-rate step fails visibly. Authorized staff may use the
approved manual ABA-equivalent reference Sell-rate fallback; the application still
applies mandatory markup and upward rounding.

## DEPLOY-060 — Storage Exhaustion

Low-space alerts occur before writes fail. If durability cannot be guaranteed,
services reject new writes rather than reporting false success.

## DEPLOY-061 — Host Failure

Services are restored on a prepared replacement host from versioned configuration,
versioned application artifacts, and verified backups. Business continuity does
not depend on undocumented state inside a failed container.

# 14. Development and Test Deployment

## DEPLOY-062 — Developer Compose

Docker Compose provides reproducible local frontend, backend, PostgreSQL, and
worker services. Development defaults use non-production secrets and isolated
data volumes.

## DEPLOY-063 — Test Isolation

Automated tests use disposable databases or isolated schemas and must never point
to production. Migration tests start from supported prior schema versions and
verify upgrade integrity.

## DEPLOY-064 — Seed Data

Development/test seed data is synthetic and contains no real Customer credentials
or business records. Seed operations are unavailable or strongly guarded in
production.

# 15. Security Alignment

## DEPLOY-065 — Security Model Conformance

Deployment must conform to `008_SECURITY_MODEL.md`, including least privilege,
secret handling, TLS, restricted database exposure, capability enforcement, audit
protection, controlled remote access, and the high-value workflow authorization
boundaries in `SEC-070`.

Deployment identities, retries, workers, monitoring tools, and administrative
paths must not collapse the separate authority for Late-payment final Decisions,
Late-payment Charge corrections/reversals, Receipt reprints, active-Lease Pet
Deposit qualifying refund review, Rent Nonpayment cases/events, or read-only
Customer Account Ledger access.

## DEPLOY-066 — Runtime Identities

Reverse proxy, API, worker, migration, backup, and database processes use separate
identities where their privileges differ.

## DEPLOY-067 — Host Security

Production hosts require supported OS patches, restricted administrator access,
firewall rules, time synchronization, protected storage, and documented ownership.

## DEPLOY-068 — Local Authentication Runtime

Production packages the application-managed local username/password authentication,
MFA, session, recovery, and audit components required by `008_SECURITY_MODEL.md`.
Routine login and recovery-code verification remain functional in the local-first
installation without Google, Microsoft, Auth0, or another external identity provider.

## DEPLOY-069 — Production Session Policy

Production configuration fixes browser-session inactivity expiry at 30 minutes and
absolute expiry at 24 hours. Operators may not weaken these values through an
undocumented environment override. TLS, Secure/HttpOnly/SameSite cookies where
applicable, CSRF controls, revocation, and high-risk reauthentication remain enabled.

## DEPLOY-070 — Initial Owner Bootstrap Operation

Deployment documentation provides a protected server-side command-line bootstrap that
is available only before any account or bootstrap closure exists. It accepts passwords only
through the controlling TTY, validates the supplied value at 15–128 code points, NFC-normalizes
it, revalidates the result as nonempty and 15–128 code points, and applies the local blocklist
and hash/verification to the complete normalized value without composition, rotation, external disclosure, or truncation. It permits paste
and password managers. It generates exactly 10 random single-use recovery codes, writes
them exactly once directly to the controlling TTY rather than stdout, persists only
protected verifiers, and requires explicit acknowledgement before commit. One ceremony-wide
absolute monotonic deadline starts before TOTP confirmation and covers TOTP input, recovery
presentation and complete persistence writes, acknowledgement input, and commit preparation;
writes, partial input, retries, and trickled input never reset or extend it. Any presentation,
TTY, TOTP-confirmation, deadline, or acknowledgement failure rolls back all effects.

The operation uses a dedicated least-privilege one-time PostgreSQL identity confined to the
atomic Owner/account, password, confirmed MFA, recovery, audit, and closure operation. The
cluster administrator provisions that identity and its protected credential before applying
the bootstrap migration; the non-role-creating migration validates this prerequisite and
fails without partial schema changes when it is absent. Fresh installations use the
reviewed database-identity initialization path, while existing clusters add the identity
through their controlled cluster-administration procedure without resetting data. The
identity has `NOINHERIT`, `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE`, `NOREPLICATION`,
`NOBYPASSRLS`, a connection limit of one, no memberships or ownership, and only target-database
`CONNECT` before migration. Provisioning must attest that this dedicated role is unused in
every other database. The operator verifies that attestation by inventorying `pg_database`,
connecting separately to every connectable database, and inspecting memberships, ownership
dependencies, database/schema/object/default ACLs, and direct grants. Runtime does not perform
cross-database introspection. The target-database migration fails closed and publishes no
V1-017 functions when any role attribute, membership, ACL, ownership, or authority check fails.
The
TOTP protection key is read from an already-open root-controlled descriptor or equivalent
protected secret file and never from arguments, ordinary environment variables, logs,
runbook/repository content, or compact state. Successful closure permanently revokes
bootstrap mutation capability; repeats fail closed and audit without secrets. Password,
TOTP, and recovery material never enters arguments, redirectable stdout, logs, state, or
audit. No public first-Owner web route is deployed.

## DEPLOY-071 — Controlled Recovery Operation

Runbooks document recovery-code handling, Owner administrative recovery of Manager and
Staff, and deliberate emergency Owner recovery. Emergency recovery requires controlled
server access, operator authentication/authorization, reason and correlation evidence,
session revocation, post-recovery validation, and immutable secret-free audit. It is not
an ordinary unauthenticated web reset and does not grant Manager-to-Staff recovery.

## DEPLOY-072 — Authentication Secrets and Disaster Recovery

Password verifiers, MFA verifier/secret material, protected recovery-code verification
material, session revocation state, bootstrap-closure state, and security audit evidence
are included in encrypted backup/restore validation with least-privilege access.
Bootstrap credentials, MFA secrets, usable recovery codes, and actual recovery secrets
must never be committed to Git or included in ordinary logs/runbooks. Usable recovery codes
and bootstrap input secrets are never durable state or backup content. TOTP-key delivery
must not be converted into arguments, ordinary environment variables, runbook/repository
content, compact state, or logging.

# 16. Traceability

| Deployment concern | Authoritative source |
|---|---|
| Technology direction | `AGENTS.md` |
| Property-local business time | `BR-PROP-*` |
| Scheduled Reservation/Rent/Utility actions | `BR-RES-*`, `BR-RENT-*`, `BR-UTIL-*`, `BR-INV-050` |
| Late-payment eligibility and Decision/Charge boundary | `BR-INV-051` through `BR-INV-055`, `BR-LATE-*` |
| Rent Nonpayment milestone evaluation | `BR-LEASE-026` through `BR-LEASE-030`, applicable `BR-PAY-*` |
| Duplicate prevention/idempotency | applicable `BR-RES-*`, `BR-RENT-*`, `BR-UTIL-*`, `BR-INV-*`, `BR-PAY-*` |
| Invoice and Late-payment financial history | `BR-INV-*`, `BR-LATE-*` |
| Payment, Allocation, Receipt, and reprint history | `BR-PAY-*`, `BR-RECEIPT-*` |
| Customer Credit and Refund history | `BR-CREDIT-*`, `BR-REFUND-*` |
| Customer Account Ledger reconstruction | `BR-LEDGER-*` |
| Deposit and active-Lease Pet Deposit Refund history | `BR-DEP-*`, applicable `BR-REFUND-*` |
| Final Settlement history | `BR-SETTLE-*` |
| Exchange-rate source/fallback | `BR-MONEY-*` |
| Audit | `BR-AUDIT-*` |
| Authorization/security | `BR-AUTH-*`, `008_SECURITY_MODEL.md` |
| Authentication, MFA, sessions, recovery, and bootstrap | `PR-CAP-009`, `SEC-009` through `SEC-018`, `SEC-071` through `SEC-075`, `DL-055` through `DL-059` |

# 17. OPEN OWNER DECISION

## OOD-DEPLOY-001 — Recovery Objectives

**Question:** What maximum data-loss interval and restoration time are acceptable
for the production installation?

**Current treatment:** Backup frequency, retention, and restore automation remain
configurable; no data-loss guarantee is invented.

**RESOLVED by DL-071 (owner, 2026-10-05):** at most 1 hour of data loss (backups every hour); working again within 1 working day; retention and restore tests as in DEPLOY-043 and DEPLOY-045.

**Blocking:** No.

## OOD-DEPLOY-002 — Production Host and LAN Address

**Question:** Which physical/virtual host, stable hostname, certificate trust
method, and LAN address will be used?

**Current treatment:** The architecture defines required properties without
selecting hardware or network identifiers.

**PARTLY RESOLVED by DL-071 (owner, 2026-10-05):** production runs on a separate small computer in the office, used only for this system, not the development Mac mini. The computer name, its address and the certificate method are chosen later; they do not block V1-059.

**Blocking:** No.

## OOD-DEPLOY-003 — Remote Access Enablement

**Question:** Will production enable remote user or administrator access, and
through which approved controlled gateway?

**Current treatment:** Disabled by default; optional architecture is specified.

**RESOLVED for V1 by DL-071 (owner, 2026-10-05):** remote access is off in V1; office network only.

**Blocking:** No.

# 18. Completion Criteria

This Deployment Architecture is complete for Owner Review when:

- runtime topology and network boundaries are explicit;
- environment, secrets, health, restart, and scheduling behavior are defined;
- migrations cannot silently destroy financial history;
- backups are encrypted, verifiable, and restorable;
- update and failure-recovery procedures are controlled;
- Property-local scheduling and external-rate-source failure are handled safely;
- recovery, monitoring, and deployment controls preserve Late-payment,
  Receipt/reprint, Customer Account Ledger, active-Lease Pet Deposit Refund, and
  Rent Nonpayment authorization/history boundaries;
- no mandatory cloud dependency has been introduced; and
- deployment-specific recovery, host, and remote-access choices remain explicit
  OPEN OWNER DECISION items.
