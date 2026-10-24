# Property Rental Management

Business management application built with React, TypeScript, FastAPI, and PostgreSQL.

## Status

The application foundation is in progress. The backend provides a
packaged FastAPI service, environment-backed settings, minimal liveness and
database-backed readiness endpoints, backend quality gates, a non-root container, and
a bounded PostgreSQL development and migration foundation. It also exposes the bounded
local login, TOTP MFA enrollment/challenge, recovery-code challenge, logout, session
inspection, and reauthentication API over secure browser-cookie and CSRF transport. The
backend also provides atomic recovery-code, authorized Owner-to-Manager/Staff, and controlled
server-side emergency Owner recovery orchestration with recovery-specific rate limiting,
applicable-session revocation, and immutable secret-free audit evidence; it exposes no
unauthenticated Owner-reset endpoint. A
bounded frontend foundation provides a strict React/TypeScript/Vite build and a non-business
bootstrap surface. Business workflow APIs, the runtime authentication-flow adapter, worker,
business screens, and production deployment posture remain future work.

## Main components

- `frontend/` — React, TypeScript, and Vite frontend foundation
- `backend/` — FastAPI application, tests, package configuration, and Dockerfile
- `docs/` — authoritative requirements, architecture, and business documentation
- `ops/` — compact implementation state and next-work queue
- `scripts/` — development and maintenance utilities
- `compose.yaml` — authoritative loopback-only PostgreSQL development service

## Prerequisites

- Git
- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/)
- Docker Desktop or another Docker-compatible builder (for container verification)
- Node.js 22 or newer and npm

## Frontend setup

```text
make frontend-install
make frontend
```

The development UI listens on `http://127.0.0.1:5173` (on HTTPS once the local certificate of
"Local run on the Mac mini" exists). Only public values prefixed
with `VITE_` are exposed by Vite. `VITE_APP_BUILD_ID` accepts a non-secret version or
commit identifier; `VITE_APP_ENVIRONMENT` accepts a public environment label. Neither
variable is required for local development.

## Backend setup

```text
make install
make dev
```

Settings are read from protected process configuration. `.env.example` contains public
settings and secret-file path names only; it contains no credential or key value. The
backend does not implicitly read a local `.env` file or bake one into an image.

The development API listens on `http://127.0.0.1:8000`. Its liveness endpoint is:

```text
GET /api/v1/health/live
{"status":"ok","version":"development"}
```

Readiness uses only the protected runtime `APP_DATABASE_URL` identity and returns no
diagnostics. PostgreSQL checks have bounded connection and execution timeouts:

```text
GET /api/v1/health/ready
{"status":"ok"}
```

Missing configuration or a failed check returns HTTP 503 with only
`{"status":"unavailable"}`. Both outcomes include `X-Request-ID`.

Set `APP_BUILD_VERSION` to a non-secret release version or commit identifier when
building/deploying. The Docker image accepts the same value as a build argument:

```text
docker build --build-arg APP_BUILD_VERSION=<version-or-commit> -t property-rental-backend backend
```

Set `APP_ALLOWED_BROWSER_ORIGIN` to the exact HTTPS browser origin permitted to submit
authentication mutations. It defaults to `https://localhost`. Authentication routes fail
closed with `503 Service Unavailable` until an atomic runtime authentication-flow adapter
is configured; no in-memory or external-identity fallback is used.

`APP_TOTP_KEY_FILE` is the path of the protected TOTP protection key file (a root-owned regular
file without group or other access; never a key value). The API reads it once at start-up and
keys its wrong-try counts with a key derived from it. With `APP_DATABASE_URL` set, the API refuses
to start without it in every `APP_ENVIRONMENT` except `development` and `test`. `APP_ENVIRONMENT`
defaults to `development`, so a real deployment must set it (for example to `production`).
Changing the key starts every wrong-try count and wait again. The API checks sign-in codes with
the same key; without it, sign-in codes cannot be checked, and an API started with
`APP_DATABASE_URL` and no key file logs the warning event `security.protected_key_file_missing` at
start-up. `APP_PASSWORD_BLOCKLIST_FILE` is the
path of the local password blocklist, read from login sub-slice L4 (the password change step).

## Verification

Run the non-mutating quality gates:

```text
make test
make lint
make format-check
make typecheck
make build
```

`make format` intentionally rewrites backend and frontend source files;
`make format-check` does not. `make test` also validates the machine-readable TEST-117 manifest at
`ops/traceability.json`. Unit/API tests skip the real PostgreSQL suite unless its
three connection URLs are supplied.

GitHub Actions runs the same backend and frontend formatting, linting, strict type
checking, test, production-build, and traceability gates on pushes and pull requests.
It also audits the locked runtime/development dependency sets and runs the isolated
PostgreSQL migration gate exclusively through `make database-test`. The TEST-118
audit fails when a newly introduced material `BR-*` or `PR-*` heading has no mapping
in `ops/traceability.json`. Workflow actions and CI tool versions are immutable pins;
project dependencies continue to install only from `backend/uv.lock` and
`frontend/package-lock.json`.

## PostgreSQL and migrations

Alembic is the reviewed, versioned schema tool; psycopg is the PostgreSQL driver used
by migrations and integration tests. These are the only Phase 1C dependencies. Create
eight distinct local-only password files at the ignored `.local/secrets/` paths named by
`.env.example`: `postgres_admin_password`, `postgres_migration_password`,
`postgres_runtime_password`, `postgres_financial_password`, `postgres_backup_password`,
`postgres_restore_password`,
`postgres_human_admin_password`, and `postgres_bootstrap_password`. Use an external protected
input method and restrictive permissions;
never put their values in Git, logs, or command arguments. Export only the corresponding
`*_FILE` path variables, then start the single development service with
`docker compose up -d --wait postgres`. Identity
initialization runs only for a fresh PostgreSQL data directory; this foundation does
not alter an existing volume automatically. If an existing development volume lacks
these identities, stop and handle that data explicitly rather than deleting or
reinitializing it through project automation.

`MIGRATION_DATABASE_URL` uses `prm_migrator`, which owns schema changes.
`APP_DATABASE_URL` uses the non-owning `prm_runtime` identity. The application never
falls back to migration credentials. `FINANCIAL_DATABASE_URL` uses the separately protected
`prm_financial` identity only for capability-authorized Reservation financial orchestration.
`TEST_ADMIN_DATABASE_URL` is test-only and must
name the local `prm_admin` bootstrap identity when tests are run directly.

The eight PostgreSQL identity password sources are `postgres_admin_password`,
`postgres_migration_password`, `postgres_runtime_password`, `postgres_financial_password`,
`postgres_backup_password`,
`postgres_restore_password`, `postgres_human_admin_password`, and
`postgres_bootstrap_password`. The managed identity and protected source contract is defined
in `config/deployment/identity-secret-contract.json`; environment-specific files in the same
directory contain source references only. `prm_backup` is read-only, `prm_restore` has no
standing data access, and exceptional `prm_human_admin` access has monitoring but no table
mutation. `prm_bootstrap` has no table access and receives only the migration-published
one-time initial-Owner functions. It must be dedicated to the target deployment database and
unused in every other database in the PostgreSQL cluster. Before provisioning or migration,
the cluster operator must inventory `pg_database`, connect separately to every connectable
database, and inspect role memberships, ownership dependencies, database/schema/object/default
ACLs, and direct grants for `prm_bootstrap`; any use outside the target database is a stop
condition, not an exception to document after the fact. See
`docs/DEPLOYMENT_IDENTITY_SECRET_SCAFFOLDING.md`.
Validate committed examples
with `make deployment-config-check`. Deployment tooling must additionally run
`python3 scripts/validate-deployment-config.py check-profile <profile>` after mounting every
protected source; production fails closed while any source is absent or placeholder-only.

Run `make migrate` to apply forward migrations. It never resets or recreates a
database and downgrade functions deliberately refuse destructive rollback. For an existing
PostgreSQL cluster created before V1-017, a cluster administrator must first provision the
`prm_bootstrap` login with `NOINHERIT`, `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE`,
`NOREPLICATION`, `NOBYPASSRLS`, a connection limit of one, no role memberships or owned
objects, and only `CONNECT` to the target deployment database. The operator must attest that
the role is unused in every other database after performing the per-database inventory above.
Its distinct credential comes from the
protected `BOOTSTRAP_DATABASE_URL_FILE` source. The migration fails before schema changes
when the cluster-global attributes or target-database role membership, ACL, ownership, or
authority checks fail; it intentionally performs no runtime cross-database introspection.
Never reset an existing volume to obtain it.
Fresh data directories create the same bounded identity through `scripts/postgres-init.sh`.
That initialization also removes `PUBLIC` database authority from the stock `postgres` and
`template1` databases while preserving explicit `prm_admin` maintenance access, so the new
bootstrap identity has no effective cross-database `CONNECT` or `TEMP` authority.

For an existing cluster created before V1-031, a cluster administrator must also provision
`prm_financial` before running `make migrate`. It must be a dedicated `LOGIN` with
`NOINHERIT`, `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE`, `NOREPLICATION`, and
`NOBYPASSRLS`; it must have no role memberships, owned objects, default ACLs, large-object
authority, or direct schema/object grants, and only `CONNECT` (never `CREATE` or `TEMP`) on
the target deployment database. It must also inherit no application relation, callable
function, schema-creation, default-ACL, or large-object authority through `PUBLIC`;
PostgreSQL system catalogs, extension-owned support objects, and trigger-only functions that
the role cannot attach or invoke are not application authority. Its distinct credential
must come from the protected `FINANCIAL_DATABASE_URL_FILE` source and must never appear in a
command argument or log. The operator must inventory every other connectable database and
stop if this identity has any authority outside the target. Migration 21 validates the
cluster-global attributes and complete target-database state, then fails before creating any V1-031 schema
when the role is absent or unsafe. It intentionally does not create or repair a cluster role
and does not claim cross-database inspection; never reset an existing volume to obtain it.

After the migration succeeds and before any account exists, run the packaged protected
command from `backend/` with the database URL, root-owned TOTP key, and local password
blocklist opened as inherited descriptors rather than values in arguments or environment:

    uv run --extra dev python -m property_rental.bootstrap_cli \
      --username initial-owner --display-name "Initial Owner" --audit-name initial-owner \
      --totp-key-identifier bootstrap-v1 \
      3</run/secrets/bootstrap_database_url \
      4</run/secrets/bootstrap_totp_key \
      5</run/secrets/bootstrap_password_blocklist

Run it from a controlling terminal under the protected server procedure. The three example
paths are source references only; deployments must substitute their mounted protected paths.
The UTF-8 password blocklist contains one exact password per newline-delimited record. Leading
and trailing spaces are significant, and there is no comment syntax that can make a permitted
password value unrepresentable.
The command refuses any database identity other than `prm_bootstrap`, never writes secrets to
stdout or stderr, and permanently loses mutation capability after a successful acknowledged
commit.

Run `make database-test` to create one isolated PostgreSQL Compose project with freshly
generated credentials and an automatically assigned loopback port. The wrapper
discovers that actual port, runs the real migration gate, and removes its container
and volume on exit. Credentials are generated inside the wrapper and are neither
printed nor persisted. Direct test invocation still refuses non-loopback hosts,
unexpected database/role names, missing passwords, or reused identity passwords.

## Local run on the Mac mini

Login sub-slice L7c (owner answers (a) to Q-2026-10-21-155 and Q-2026-10-21-159; technical
points Q-2026-10-24-189). This is how the owner runs the app on the Mac mini, makes the first
Owner account once, and opens the screens on the Mac and on an iPad on the same Wi-Fi. Every
step is typed in Terminal from the repository folder. No password, key or database address is
ever typed as a command argument or shown on screen, except the Owner set-up's own one-time
screen.

0. **Before you start** (once): the Prerequisites above, Docker Desktop running, then
   `make install`. It and the first database start (which gets
   the `postgres:17.6` image) download what the project's lock files name; nothing else does.
   `/usr/bin/python3 --version` must answer (the first time, macOS asks to install the command
   line tools; say yes).
1. **Make the local secrets** (once): `sh scripts/local/make-secrets.sh`. It makes the eight
   database password files and four database address files in `.local/secrets` (ignored by Git;
   only your account can open the folder). A file that is already there is kept.
2. **Make the protected key and install the helper** (once; sudo asks for your Mac password).
   First `ls -ld /usr/local /usr/local/etc /usr/local/libexec` (the ones that exist): each must
   show `root` as its owner. If one shows your own name (an Intel Mac with Homebrew), stop and
   ask, because then a program running as you could swap the helper that sudo runs. Then:

       sudo install -d -o root -g wheel -m 0755 /usr/local/etc/prm /usr/local/libexec/prm
       sudo sh -c 'umask 077; set -C; openssl rand -hex 32 > /usr/local/etc/prm/totp_protection_key'
       sudo chown root:wheel /usr/local/etc/prm/totp_protection_key
       sudo install -o root -g wheel -m 0755 scripts/local/with-protected-key.py \
           /usr/local/libexec/prm/with-protected-key.py

   The key protects every sign-in code: never copy it anywhere else, and keep it in the Mac's
   backup. `set -C` makes the command refuse to replace a key that is already there: a new key
   would lock every account out of its sign-in codes. The helper is the only part that runs as
   root: it opens the key and then runs the API or the Owner set-up as you. After a `git pull`,
   if `cmp scripts/local/with-protected-key.py /usr/local/libexec/prm/with-protected-key.py`
   reports a difference, run the last install line again.
3. **Start the database**: `sh scripts/local/database.sh` (Docker Desktop must be running). The
   first start makes the database identities. If an older `property-rental-management` volume
   exists without them, stop and ask; never delete the volume. If the first start stops with
   an error, stop and ask too: the database keeps its half-made first state. Stop it later with
   `sh scripts/local/database.sh stop`.
4. **Apply the migrations**: `sh scripts/local/migrate.sh`.
5. **Make the first Owner account** (once, before anyone else):

       sh scripts/local/bootstrap-owner.sh --username owner \
           --display-name "CHETANA Owner" --audit-name chetana-owner

   Choose your own username and names (a display name in Khmer is fine; type it without the
   invisible space some Khmer keyboards add, or the set-up refuses it). Type the Owner password
   twice (15 to 128 characters; nothing shows while you type). The set-up shows a key of
   letters and digits: in Google Authenticator tap +, then "Enter a setup key", type the key,
   choose "Time based", and type the 6-digit code it shows. Write the 10 recovery codes on paper,
   and type the acknowledgement it asks for. You have 15 minutes from the key to the
   acknowledgement; if time runs out, nothing is saved and you start again. The
   set-up can run only once; after it, the Owner makes every other account in the app.
6. **Make the HTTPS certificate** (once a year): `sh scripts/local/make-certificate.sh`. It covers
   `https://NAME.local:5173` (NAME is the Mac's local network name, System Settings, General,
   Sharing, shown in lower case) and `https://localhost:5173`. Trust its authority once (it
   lasts 10 years; the script warns 60 days before it ends):
   - on the Mac: `sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain .local/https/local-ca.pem`;
   - on the iPad: `open -R .local/https/local-ca.pem` shows the file in Finder (`.local` is
     hidden); AirDrop it to the iPad, install it in Settings,
     General, VPN & Device Management, then turn it on in Settings, General, About, Certificate
     Trust Settings.
7. **Start the API** in one Terminal window: `sh scripts/local/start-api.sh` (sudo asks for your
   Mac password). It listens on 127.0.0.1:8000 only, with `APP_ENVIRONMENT=production`.
8. **Start the screens** in a second Terminal window: `cd frontend && npm run dev:local`. If
   macOS asks whether "node" may accept incoming network connections, choose Allow (the iPad
   needs it).
9. **Open** `https://NAME.local:5173` on the Mac or the iPad and sign in. Use this address on
   the Mac too: the API accepts sign-ins only from this one address.

Stop with Control-C in both windows. The passwords never leave `.local/secrets`; the password
blocklist is `config/password-blocklist.txt` (not a secret; add lines to it, one password each).

Every day after that (or after the Mac restarts): open Docker Desktop, then steps 3, 7 and 8,
then step 9. Each year: step 6 again, then restart step 8. If the Mac's local network name
changes (macOS may add "-2" after a name clash on the Wi-Fi), do step 6 again and restart steps 7
and 8. Use Safari or Chrome; Firefox does not use the Mac's trusted certificates.

## Development workflow

1. Create or select a Git branch.
2. Review the relevant requirements and business rules.
3. Prepare an implementation plan.
4. Implement a focused change.
5. Run tests, type checks, formatting checks, lint, and builds.
6. Review the diff.
7. Commit only verified work.

## Autonomous supervision

OpenClaw checks compact state every 30 minutes without invoking a model when no
approved work is actionable. The supervisor is a deterministic stage router: it reconciles
state, selects the exact structured roadmap successor, monitors locks/processes, classifies
failures, persists evidence, and schedules work. It never carries out model-heavy product
implementation or injects its full prompt/history into a worker.

Attempt identity is explicitly scoped by roadmap tranche ID. Structured successor
selection activates the successor lifecycle and initializes a repair object bearing that
same tranche ID; preflight ignores repair counters, failures, and protection flags whose
recorded tranche ID does not match the dispatched tranche. Published predecessor repair
exhaustion therefore cannot consume a successor's independent bounded attempts.

The 30-minute interval is only an idle wake-up cadence. Candidate work is persisted as
separate reconciliation/dispatch, implementation, deterministic verification, independent
review, publication, post-publication reconciliation, and next-candidate activation stages.
Immediate chaining is capped at six stage transitions per wake-up.

Each model stage receives a compact deterministic task packet and a fresh one-shot session.
`scripts/openclaw_dispatch.py` is the only model-invocation authority. It creates a
single-use manifest binding candidate, stage, branch, HEAD, repository/worktree and
preserved-candidate fingerprints, task hash, unique usage path, and token policy. The
supervisor and the Hermes wrapper reject direct or unmanifested model calls. The
manifest is also bound to the live dispatcher process and exact candidate-stage record;
each implementation receives an explicit product-path write allowlist, while repair is
limited to the already-persisted candidate paths and review has no write paths.
repository-owned Hermes wrapper uses `openai-codex`/`gpt-5.6-sol` with requested
reasoning `high` for implementation and `xhigh` for an independent review. The ordinary
ceiling remains exactly 60,000 tokens. A review preclassified as complex uses 90,000;
120,000 is allowed only with a reason, repository fingerprint, and scope recorded before
invocation. Implementation cannot promote itself to a review ceiling, and an unsupported
configuration stops without consuming an attempt.

The repository-local Hermes guard enforces the ceiling cumulatively across provider API
calls. Counted usage is `input_tokens + output_tokens`; cache-read tokens are recorded
separately and are not added again. Once observed counted usage reaches the boundary, no
later API call starts. Any unavoidable overshoot from the already-started call is recorded.
Implementation and ordinary repair each receive a fresh 60,000-token session; review gets
90,000 unless the persisted exceptional-review classification authorizes 120,000.

Hermes implementation sessions have repository-scoped file access, read-only `git status`
and `git diff`, and one allowlisted repository-owned `make` verification target per terminal
call, always from the repository root. Patch operations validate every source and
destination, including move operations. `make database-test` is the only database verification route. Git mutation, direct
database commands, scheduler control, background processes, unrestricted browsing,
delegation, secrets, and writes to canonical documents are denied. Review, publication,
GitHub mutation, and scheduler control remain separate dispatcher/operator stages.
Provider authentication is withheld from the isolated session until the guard registers
inside the actual chat process, so a plugin-load failure cannot silently run a model
without the repository guard.

One verification-only continuation may be atomically consumed for an exact unchanged
fingerprint when implementation is complete and the exclusive stop reason is a tool,
session, or token ceiling. It is forbidden after a failed check, while a relevant worker
remains, or for product edits, policy/scope changes, secrets, protected operations, or
destructive work. It cannot recurse. Ordinary model, implementation, verification, review,
repair, gateway/fallback, and ceiling usage remain separate durable records.

The repeated-call guard keys normalized command identity/arguments with repository,
compact-state, process-state, and prior-result fingerprints. It suppresses an unchanged
failed call while preserving the safe underlying exit/category evidence and exact next
eligible action. Lock recovery verifies PID/process identity rather than age alone.

The shell preflight is a thin consumer of the dispatcher's authoritative Python lifecycle
classifier. Lifecycle and blocker categories—not free-form blocker prose—control routing.
A preserved capability-only continuation requires the exact candidate, branch, HEAD,
preserved-worktree fingerprint, approved scope, no failed check, no overlapping worker,
and `owner_action: none`; it routes directly to deterministic verification and never reruns
implementation. Genuine Owner-policy, secrets, protected-operation, scope, and exhausted-
attempt categories remain blocked. The model-free classifier also enforces durable handoff invariants learned from prior
recovery incidents. An approved candidate with a missing `next_action` is dispatched
from its already-approved task instead of silently idling. A verified
`verified_unpublished`, `complete_uncommitted`, or `complete_unpublished` tranche covered by standing
authorization is routed to independent publication verification and cannot demand a
redundant owner commit/push instruction. These cases are regression-tested by
`make automation-test` and any future repair must add or extend a deterministic test.
The executable rule primarily uses structured approval lifecycle fields—not an open-ended
list of worker-written status labels—so any future label with implementation complete,
publication incomplete, approved scope, and no blockers follows the same publication path.
Any other unrecognized status under durable authorization enters a bounded state-contract
repair instead of silent idle; a state that cannot be safely normalized produces one
deduplicated Telegram alert.
Implementers must record an uncommitted completed tranche as `complete_uncommitted`.
For recovery from the previously emitted `verified_unpublished` and
`implemented_awaiting_supervisor_review` aliases,
preflight routes the same mandatory publication action instead of silently idling.
Published state with an explicitly approved next candidate is also actionable: preflight
routes that candidate immediately and the task packet takes its phase and risk metadata,
so publication does not create an unnecessary approval or scheduler wait.
If Hermes instead emits the exact unselected/not-approved placeholder while the queue
still grants durable bounded-v1 authorization, or omits the candidate using any other wording,
preflight ignores the prose and reads `ops/V1_ROADMAP.json`. One unique safe successor
is materialized, committed, pushed, CI-checked, and dispatched without a model. No unique safe
successor produces one deduplicated `HANDOFF_MISSING` alert. Concrete protected or
policy-dependent candidates remain non-actionable and still require the Owner.
If a clean upstream-synchronized HEAD has advanced beyond the commit recorded by a
pre-publication state, the dispatcher performs compact-state reconciliation, commit,
push, and GitHub Actions polling deterministically without invoking a model. A
`not_approved` candidate cannot be dispatched through stale publication state.

Automation repairs follow a permanent prevention protocol:

1. Identify and record the root cause; do not stop at retrying the failed cycle.
2. Repair the executable enforcement path that permitted the failure.
3. Add or extend a deterministic regression test that fails without the repair.
4. Update the supervisor prompt when agent behavior or authorization semantics change.
5. Update the watchdog and daily report when compact-state interpretation or
   owner-visible reporting changes.
6. Run `make automation-test`, then commit the focused repair so its rationale remains
   recoverable from Git history.

Only legitimately affected files are changed. A repair does not mechanically rewrite
all automation files; the regression test is the mandatory proof that the same defect
cannot silently recur.

Ordinary technical failures within an already approved tranche carry durable standing
repair authority. OpenClaw may automatically diagnose, repair, add regression coverage,
reverify, commit, push, and recheck GitHub Actions for at most two attempts. Successful
repair activity is silent. Owner attention is required only after the attempt limit or
when a correction crosses canonical/architecture policy, business or financial policy,
destructive data operations, actual production secrets or credentials, production
deployment, remote access, history rewriting, suspected secret exposure, or the original
approved scope.

A separate model-free watchdog sends Telegram after every newly published roadmap tranche,
including the verified commit, roadmap progress, and exact next action. It also reports an
approval request, a stalled approved tranche, an intentionally disabled or unhealthy
scheduler, stage progress, or recovery. Identical notification types at an unchanged material
state fingerprint are deduplicated. The daily 08:00 Asia/Phnom_Penh report includes automation
health, last check and state update, repository synchronization, 24-hour counted model usage
and separately reported cache-read usage,
the reason for being idle, blockers, commits, and the exact next owner action.

## Security

`.env` is local-only. Do not commit passwords, API keys, database credentials,
customer information, production database backups, or other secrets. The liveness
response deliberately exposes only process status and a non-secret build identity.
