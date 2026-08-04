# Database Design

## Conventions

- Use UUIDs or another explicitly approved identifier strategy.
- Store money as integer minor units.
- Store timestamps with time-zone awareness.
- Include created and updated timestamps where appropriate.
- Do not hard-delete financial records.
- Use foreign keys and database constraints.
- Use migrations for every schema change.

## Entities

Entities will be defined during domain design.

## Relationships

To be defined.

## Important invariants

To be defined.

## Retention and deletion

To be defined.

## Migration policy

- Every schema change requires a migration.
- Migrations must be reviewed before execution.
- Destructive migrations require explicit approval and a backup.
