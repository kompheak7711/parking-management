# V1-054 enforcement integration operations

This implementation note supplements the read-only canonical requirements in
`docs/005_API_SPECIFICATION.md`, `docs/008_SECURITY_MODEL.md` and
`docs/009_DEPLOYMENT_ARCHITECTURE.md`. It changes no business policy.

## Staff workflows and permissions

The signed-in application provides **Lease warnings and Rent nonpayment** with
its own authorized Property selector. General Lease warning history requires
`leases.read`; recording a warning requires `leases.warn`. Rent case and event
history and current alerts require `rent_nonpayment.read`. Opening a case
requires `rent_nonpayment.case_manage`; posting an event requires
`rent_nonpayment.event_post`. A command-only account receives a minimal source or
action context, without the history permissions. Billing authority does not
grant these capabilities. Every API call checks fresh account state and the
specific Property and resource before reading or executing a command.

General warnings preserve the supplied sequence, calendar dates, violation,
Lease provision and communication. Their sequence is unique per Lease. The
suggested next sequence is a convenience and is revalidated at command time.
Existing warning history remains intact, including text written before the new
command field limits.

Rent alerts evaluate issued, non-VOID Rent lines with a positive remaining
balance and at least 20 Property-local calendar days overdue, including lines
without a manually opened case. Each case retains its exact Invoice/Rent line,
Lease, financially responsible Customer and original Due Date. Current
eligibility and the common line balance are read from the server. The staff
workflow records only an explicit Warning Notice, Serious Default, Cure or
authorized follow-up. It never ends a Lease, closes Occupancy, changes Unit
status or creates a fee. Authorized follow-up remains available on a historical
VOID case with current remaining Rent zero; a new milestone or Cure is not
eligible on that source.

## Original commands and current evidence

The three enforcement commands use the existing actor-keyed sealed browser
recovery store and cross-tab attempt lock. Confirmation captures exact source
references and original input before any asynchronous work. A pending command
blocks a new financial/enforcement command and must be explicitly reviewed and
retried. Its same command key and exact wire body are retained across reloads,
Property changes, lost replies and later eligibility changes. The original
response uses its original request metadata, so these three browser operations
use the command key as their stable `X-Request-ID`. Other financial operations
retain their existing behavior. A retry never re-labels the original response as
a fresh assessment, and it cannot bypass fresh actor or scope authorization.

The confirmed original action is shown as historical evidence. Current case
reads refresh separately when the account has the corresponding read or action
capability. A failed read is not represented as zero or as complete history.
List pages are bounded; controls explicitly request another page. Lease warning
forms and Rent case/event forms have independent permission boundaries. Property
and session changes invalidate pending UI work; voluntary navigation/sign-out
protects unsaved drafts, while session expiry clears actor-specific views.

Refreshing records or recovery preserves form drafts and selected sources.
Forms cannot submit while their fresh authorized context is unavailable. A
rejected, blocked or unresolved attempt retains its inputs and the unsaved-change
guard. Successful recording clears only that form; simultaneous opening/event
drafts remain independent. Exact replay may clear a retained matching draft only
after confirmed success, using the original actor, Property, operation, target
and wire body to bind it. Confirming a different action saved by another tab does
not clear this form. No draft is automatically submitted.

## Read-only evaluation entry point

`property_rental.nonpayment_evaluation.ScheduledRentNonpaymentEvaluator` evaluates
one bounded page. The module command accepts `--property-id`, `--actor-id`,
`--limit` (1 through 100) and an optional Rent-line UUID `--cursor`. It requires a
dedicated connection in `APP_NONPAYMENT_EVALUATION_DATABASE_URL` and never falls
back to runtime, financial, migrator or bootstrap connection settings.

Migration51 also revokes the historical PUBLIC execution grant on the existing
Customer email match-key trigger function. The existing trigger and published
migration16 remain unchanged. This prevents a newly provisioned evaluator login
with temporary-table access from attaching that privileged function to another
relation. Connected tests verify denial of that attachment and preservation of
normal runtime Customer create/update/email matching, including removing email.

No live evaluator login, worker or schedule is provisioned or enabled by this
version. Future authorized operations must first provision a dedicated login
for one Property and SERVICE actor, with only database CONNECT, app schema USAGE
and EXECUTE on
`app.scheduled_rent_nonpayment_evaluation(uuid,uuid,integer,uuid)`. Register that
exact login/Property/actor in `app.rent_nonpayment_evaluation_principals` using
the authorized migration/administration boundary and a fresh active human
`created_by` reference. Registration inserts a distinct SERVICE actor identity.
Do not reuse a standard application role or grant role memberships, application
table/column/sequence access, schema creation or another privileged application
function. The registration and each evaluation reject privileged role flags,
membership (including non-inherited elevation), those excess grants, a disabled
principal, wrong actor/Property/login, or a transaction that is not read-only.
The checks include effective column SELECT, INSERT, UPDATE and REFERENCES, also
when inherited from PUBLIC, and every PostgreSQL 17 application-table privilege,
including REFERENCES, TRIGGER and MAINTAIN. Removing an excess grant permits
the otherwise valid registered principal to evaluate again.

The evaluator sets the transaction read-only before its query, a 3 second
connection timeout, a 5 second statement limit and a 3 second lock limit. One call
returns at most the requested number of current alert rows and a next cursor.
An authorized scheduler or operations wrapper must process subsequent pages
using that cursor until it is null, and begin each new evaluation sweep without
a cursor. Pages are independently current observations, not an immutable export
snapshot. The evaluator does not persist an alert, case, event, command receipt,
financial change or tenancy change. Staff alert presentation reads the same
projection under human authorization.

The command emits only evaluated status, count, next cursor and Property
business date. It omits connection strings and source/customer content from
logs. A handled failure emits only a failure status and exception type with a
nonzero exit status; the future authorized operations wrapper must record that
failure and raise its operational alert. Retrying a read-only evaluation cannot
duplicate a business event. Disable an evaluation principal with its disabled
timestamp and fresh human actor; retain its principal and identity history.
Production provisioning, live scheduling and production deployment remain
outside the current authorization.

## Acceptance evidence

The new source is validated by focused HTTP/PostgreSQL, evaluator boundary,
frontend transport/recovery/session, and real synthetic browser tests, followed
by all mandatory stage and integrated acceptance gates. Exact-SHA independent
reviews and terminal publication/CI/ref/Workboard evidence are recorded in the
version's durable state and immutable external evidence. This implementation
note alone is not a claim that those gates or version closure have completed.
