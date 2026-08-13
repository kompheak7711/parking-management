# Foundation queue

1. Add PostgreSQL runtime/migration boundaries and an additive initial migration
   before implementing persistence (DEPLOY-001, DEPLOY-032–034; TEST-010/100–104).
2. Add minimal `/api/v1/health/ready` only when a real database dependency exists;
   expose no
   diagnostics unauthenticated (API-081, DEPLOY-023, SEC-039).
3. Add consistent safe error envelopes before business endpoints (API-013/014,
   TEST-088, SEC-039).
4. Add structured redacted logs and graceful lifecycle hooks (DEPLOY-009/024,
   SEC-043).
5. Add Compose services only with separate runtime/migration identities and no
   committed secrets (DEPLOY-017–019/021, SEC-045/049/050).

Each item requires a fresh scoped plan and approval under `AGENTS.md`.
