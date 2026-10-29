# Step 1: Clone, rename, separate ports — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parking Rental runs on this Mac mini next to Property Rental, from a full copy of Property Rental's code and history, with nothing shared and no name clash.

**Architecture:** Same code, same hidden names (`property_rental` package, `unit`, `lease`, `occupant`, database roles `prm_runtime` and friends). Only the business name, the app name, and every *operational* name (ports, database name, Docker project, volume, secrets folder, backup folder, job names) change. Property Rental stays a Git remote so later fixes can be cherry-picked.

**Tech Stack:** Git, Docker Compose (PostgreSQL 17.6), Python 3.11 + uv + FastAPI + Alembic, Node + Vite + Vitest.

**Spec:** the owner's message of 2026-10-29 (Ground rules + Step 1), saved as `docs/superpowers/specs/2026-10-29-parking-app-owner-brief.md` in Task 1.

## Global Constraints

- Never touch `~/Development/property-rental-management`, its Docker containers (`property-rental-management-postgres-1`), its volume, its secrets in `/usr/local/etc/prm`, or its backups.
- Source commit: `df3ec76` on `implementation/foundation` (2026-10-28), unless the owner picks a newer one.
- Change only words staff see. Hidden code names stay: `property_rental` package, table/column/function names, database role names `prm_admin`, `prm_migrator`, `prm_runtime`, `prm_financial`, `prm_backup`, `prm_restore`, `prm_human_admin`, `prm_bootstrap` (they live in 187 migration/source files and run inside Parking's own separate PostgreSQL, so no clash).
- New operational prefix: `pkm` (Parking Management). Everywhere `prm` is an *operational* name (job, folder, project, database name), Parking uses `pkm`.
- Money, business rules, features: no change in Step 1.

## Names and ports (the table to show the owner)

| Thing | Property Rental (today, running) | Parking Rental (new) |
| --- | --- | --- |
| Business name on screens | CHETANA Residence | CHETANA Parking |
| App name on screens | Property Rental | Parking Rental |
| Folder | ~/Development/property-rental-management | ~/Development/parking-management |
| GitHub repo | kompheak7711/property-rental-management | kompheak7711/parking-management |
| Docker Compose project | property-rental-management | parking-management |
| Postgres container | property-rental-management-postgres-1 | parking-management-postgres-1 |
| Postgres volume | property-rental-management_postgres_data | parking-management_postgres_data |
| Postgres port (loopback) | 127.0.0.1:5432 | 127.0.0.1:5433 |
| Database name | prm | pkm |
| Database roles | prm_admin, prm_runtime, ... (hidden names) | same names, inside Parking's own server (no clash) |
| API port | 127.0.0.1:8000 | 127.0.0.1:8001 |
| Screens (Vite) port | https://<mac>.local:5173 | https://<mac>.local:5174 |
| APP_NAME / APP_SERVICE_NAME | property-rental-management / property-rental-backend | parking-management / parking-backend |
| Python package name (pyproject `name`) | property-rental-backend | parking-backend |
| Backend command names (pyproject scripts) | property-rental-backup, -ops-check, -log-retention, -scheduled-billing, -reservation-expiration | parking-backup, parking-ops-check, ... |
| npm package name | property-rental-frontend | parking-frontend |
| Local secrets folder (repo) | .local/secrets (inside its own folder) | .local/secrets (inside Parking's folder) |
| Root-only key + helper (Mac) | /usr/local/etc/prm, /usr/local/libexec/prm | /usr/local/etc/pkm, /usr/local/libexec/pkm (needs sudo; owner runs it) |
| Database test compose project | prm-database-test-<pid> | pkm-database-test-<pid> |
| Backup folder (server config) | /var/lib/prm, /var/log/prm | /var/lib/pkm, /var/log/pkm |
| Scheduled job names (systemd units in config/deployment/host) | prm-backup, prm-offhost-daily, prm-log-retention, prm-ops-check (+ .timer), user prm-ops | pkm-backup, pkm-offhost-daily, pkm-log-retention, pkm-ops-check, user pkm-ops |
| Postgres setting name in migrations | prm.sign_in_prune (hidden name) | unchanged |

## Review Focus

1. Vite proxy must point at 8001, not 8000, or Parking screens would silently talk to Property Rental's API.
2. `scripts/local/common.sh` paths must all move to `pkm`; a missed one would read Property Rental's key file.
3. `database-test.sh` picks a free port (POSTGRES_PORT=0) and its own project name; confirm it never names `property-rental-management`.
4. Tests that assert fixed strings (`test_local_run_scripts.py` expects `/prm`, app title tests, README checks) must be updated with the new names, not deleted.
5. Khmer screen text: Step 1 changes only the English/Khmer business and app name pair; "Unit" words wait for Step 2.

---

### Task 1: Git setup (after owner OK on commit and remote plan)

**Files:** new repo folder `~/Development/parking-management`; `docs/superpowers/specs/2026-10-29-parking-app-owner-brief.md`; this plan copied to `docs/superpowers/plans/`.

- [ ] Clone full history: `git clone --branch implementation/foundation git@github.com:kompheak7711/property-rental-management.git ~/Development/parking-management`
- [ ] `git remote rename origin property-rental`; `git remote add origin git@github.com:kompheak7711/parking-management.git`; `git fetch origin`
- [ ] `git checkout -b step-1-clone-rename df3ec76`
- [ ] Keep Property Rental's README (retitled in Task 2); the one-line Parking README on GitHub main is replaced when main is reset. Record this in the step report.
- [ ] Save the owner brief and this plan under `docs/superpowers/`; commit `docs: owner brief and Step 1 plan` (local only, no push).

### Task 2: Screen words (business and app name only)

**Files:** `frontend/src/**/text.ts`, `frontend/index.html`, `frontend/src/App.tsx` (title), `backend/src/property_rental/app.py` (FastAPI title), letters/PDF text in `backend/src/property_rental/*letter*`, `README.md` title line, `.env.example` APP_NAME.

- [ ] Grep inventory: `grep -rn "CHETANA Residence\|Property Rental" frontend/src backend/src README.md` → list in the step report.
- [ ] Replace `CHETANA Residence` → `CHETANA Parking`, `Property Rental` → `Parking Rental` (screen strings, page titles, letter headers only; NOT in code comments/ops history, NOT the `property_rental` package).
- [ ] Khmer pair for the business/app name: ask owner before changing (Step 2 rule). Step 1 keeps Khmer text as is unless it literally contains "Property Rental".
- [ ] Run `make frontend-test backend-test`; fix string-assert tests.
- [ ] Commit `feat: rename screens to CHETANA Parking / Parking Rental`.

### Task 3: Operational names and ports

**Files:** `compose.yaml`, `.env.example`, `Makefile:78`, `frontend/vite.config.ts` (server.port 5174, proxy target 8001), `frontend/package.json`, `backend/pyproject.toml` (name + script names), `scripts/local/common.sh`, `scripts/local/start-api.sh`, `scripts/local/make-secrets.sh`, `scripts/local/make-certificate.sh`, `scripts/database-test.sh`, `config/deployment/*.json`, `config/deployment/host/*` (rename files prm-* → pkm-*), `backend/tests/test_local_run_scripts.py`, `README.md` (Local run section).

- [ ] Apply the table above. Each value appears in the table; nothing else changes.
- [ ] Verify no clash: `grep -rn "5432\|:8000\|5173\|property-rental-management\|/prm\b" compose.yaml .env.example Makefile frontend/vite.config.ts scripts/local config` → expected: only comments explaining the old name, or none.
- [ ] Run `make backend-test frontend-test`; fix tests that assert the old names.
- [ ] Commit `chore: Parking gets its own ports, database name, project, job and folder names`.

### Task 4: Run Parking next to Property Rental

- [ ] `make install` (uv sync + npm ci).
- [ ] `sh scripts/local/make-secrets.sh` → `.local/secrets` (Parking's own passwords).
- [ ] `sh scripts/local/database.sh` → container `parking-management-postgres-1` on 5433. Check: `docker ps` shows both postgres containers.
- [ ] `make migrate` (all migrations into the empty Parking database).
- [ ] API: run the dev form `uv run uvicorn property_rental.app:app --port 8001` (the sudo helper install in `/usr/local/*/pkm` waits for the owner). Check: `curl -s 127.0.0.1:8001/api/health` and `curl -s 127.0.0.1:8000/api/health` both answer.
- [ ] Screens: `npm run dev -- --port 5174`; open in browser; screenshot of both apps side by side.
- [ ] Evidence into the step report: `docker ps`, `lsof -nP -iTCP -sTCP:LISTEN` lines for 5432/5433/8000/8001/5173/5174.

### Task 5: All tests + checks

- [ ] `make backend-test` → counts.
- [ ] `make database-test` (its own throw-away PostgreSQL on a random port) → counts.
- [ ] `make frontend-test` → counts.
- [ ] `make lint typecheck` → clean.
- [ ] `python3 <replica-skill>/replica-diff/parity.py replica/features.csv` after marking every row `clone=yes` for features confirmed by the passing suites.
- [ ] `python3 <replica-skill>/replica-brand/sweep.py . --avoid "Property Rental,CHETANA Residence"` → expect hits only in `ops/` history and comments; list them.
- [ ] `/code-review` on the branch diff; fix findings.
- [ ] Write the step report (changed, test counts, could-not-do, questions). STOP; no push.
