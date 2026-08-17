# Deployment identities and protected secret-source scaffolding

## Scope

This bounded tranche implements local design and configuration contracts for `SEC-045`,
`SEC-047`, `SEC-049`, and `SEC-050`, aligned with `DEPLOY-017` through `DEPLOY-019`,
`DEPLOY-062`, `DEPLOY-065`, and `DEPLOY-066`. It provisions no production value, opens no
remote access, performs no restore, and changes none of the canonical documents 001-010.

## Database identity contract

| Purpose | Role | Standing local intent | Prohibited use |
|---|---|---|---|
| Runtime | `prm_runtime` | Migration-reviewed application grants | Schema ownership, trigger/constraint changes, audit or financial-history deletion |
| Migration | `prm_migrator` | Schema ownership and reviewed forward migrations | Application runtime and ad hoc production DDL |
| Backup | `prm_backup` | Read-only full-database backup access | Application worker execution and writes |
| Restore | `prm_restore` | Connect only until a restore is separately authorized | Standing schema/data mutation and ordinary operation |
| Human administration | `prm_human_admin` | Monitoring and exceptional controlled diagnostics | Standing table mutation and every direct financial-history edit |

The PostgreSQL image bootstrap identity is local initialization machinery, not the human-admin
identity and not an application credential. Restore authority is deliberately absent by default.
A later restore runbook must require explicit authorization, recorded operator identity, target
verification, a protected restore credential source, and temporary least privilege; this tranche
does not guess or implement that procedure.

Direct database administration is exceptional. It must use an approved controlled path and be
logged where practical. Operators diagnose and invoke reviewed application correction,
reversal, or adjustment workflows; they never edit financial history directly.

## Secret-source contract

`config/deployment/identity-secret-contract.json` names the five database identities and two
non-database secret classes. Each development, test, staging, and production profile contains
only absolute protected-file references below `/run/secrets/`; it contains no credential or key.
Every environment and every identity has a distinct source path.

`APP_SECRET_KEY_FILE` is ordinary application secret input.
`BACKUP_ENCRYPTION_KEY_FILE` is a separately named backup-encryption input. Neither may share a
source with any database URL file. Only public, non-secret build/environment values may use a
`VITE_` prefix; these server-side source names must never enter a frontend build.

Run static validation of committed scaffolding with:

```text
python3 scripts/validate-deployment-config.py check-examples
```

Deployment tooling must run `check-profile <profile-path>` before starting a service. That mode
fails closed unless every referenced protected file exists and is nonempty/non-placeholder. It
prints only a validation outcome, never source contents. The production profile is a contract
example, not runnable production configuration, and therefore fails `check-profile` until an
independently approved deployment mechanism mounts real protected sources.

## Local Compose handling

Compose mounts separate local password files for bootstrap, migration, runtime, backup, restore,
and human administration. `.env.example` contains paths only. Actual local files belong below
ignored `.local/secrets/`, must be created outside Git with restrictive host permissions, and
must never be supplied as command arguments. The isolated database gate creates disposable test
files under a private temporary directory, emits no values, and removes them on exit.

PostgreSQL initialization reads role passwords from mounted files into environment variables and
uses `psql`'s `\getenv`; password values are not placed in `psql` arguments. The local backup role
receives PostgreSQL's read-all-data role. Restore remains connect-only. Human administration
receives monitoring access but no table DML. Existing volumes are never reset or rewritten;
identity initialization still runs only for a fresh local data directory.

## Explicitly deferred

Production secret-store selection, actual credential/key creation or rotation, production role
provisioning, backup execution/encryption, restore elevation and drills, controlled remote access,
and production deployment are outside this tranche and require separate authorization and
verification. No business or financial policy is introduced here.
