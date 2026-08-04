# AGENTS.md

## Project purpose

This repository contains a production-oriented business management application.

The application must prioritize:

- Correct financial calculations
- Data integrity
- Clear audit history
- Safe database migrations
- Maintainable architecture
- Simple user workflows
- Reliable reporting
- Protection of customer and business data

## Technology direction

Expected stack:

- Frontend: React, TypeScript and Vite
- Backend: FastAPI and Python
- Database: PostgreSQL
- Development environment: Docker Compose
- API style: REST
- Testing: automated frontend and backend tests

Do not introduce a different framework, database or major dependency without
explicit approval.

## Required workflow

For any substantial task:

1. Inspect the relevant repository files.
2. Explain the current implementation.
3. Identify affected files and business rules.
4. Prepare a step-by-step implementation plan.
5. Wait for approval before editing.
6. Implement only the approved scope.
7. Run relevant tests, type checks and builds.
8. Review the final diff for regressions.
9. Report changed files and verification results.

Small corrections such as spelling or formatting do not require a long plan.

## Safety rules

- Never delete production or development data without explicit approval.
- Never reset, recreate or overwrite a database automatically.
- Never run destructive database migrations without explicit approval.
- Never alter financial records silently.
- Never expose passwords, secrets, tokens or personal data.
- Never commit `.env` files or database backups.
- Never change unrelated files.
- Never discard existing uncommitted work.
- Never force-push.
- Never commit or push unless explicitly requested.
- Never add packages without explaining why they are necessary.
- Never replace working code merely to use a different coding style.

## Financial rules

- Store monetary amounts as integer minor units, such as cents.
- Do not use floating-point numbers for money.
- Preserve transaction and payment history.
- Corrections should use void, reversal or adjustment records where appropriate.
- Financial operations must be auditable.
- Calculations must be deterministic and tested.
- Dates, billing periods and time zones must be handled explicitly.

## Backend standards

- Use clear service, repository and API boundaries.
- Validate all external input.
- Return consistent error responses.
- Keep business logic outside route handlers.
- Use database transactions for multi-step financial operations.
- Add database constraints for important invariants.
- Use migrations for schema changes.
- Add tests for business rules and edge cases.

## Frontend standards

- Use TypeScript strict mode.
- Avoid `any` unless justified.
- Keep API access in a dedicated client layer.
- Provide loading, empty, success and error states.
- Validate forms before submission.
- Maintain accessible labels and keyboard navigation.
- Follow the existing design system.
- Do not duplicate business logic that belongs on the backend.

## Verification

Before reporting completion, run all applicable commands documented in the
repository.

At minimum, verify:

- Frontend formatting
- Frontend linting
- Frontend type checking
- Frontend tests
- Frontend production build
- Backend formatting
- Backend linting
- Backend type checking
- Backend tests
- Database migration status

If a command cannot be run, explain why.

## Documentation

Update documentation when changing:

- Business rules
- Database schema
- API behavior
- Environment variables
- Setup instructions
- Deployment procedures
- Significant architectural decisions