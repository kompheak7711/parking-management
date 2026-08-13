# Foundation queue

1. Review and publish only the verified Phase 1C PostgreSQL runtime/migration tranche;
   do not broaden it into business schema or production deployment posture.
2. Add minimal `/api/v1/health/ready` against the real runtime database dependency;
   expose no diagnostics unauthenticated (API-081, DEPLOY-023, SEC-039).
3. Add consistent safe error envelopes before business endpoints (API-013/014,
   TEST-088, SEC-039).
4. Add structured redacted logs and graceful lifecycle hooks (DEPLOY-009/024,
   SEC-043).
5. Design backup/restore/human administration database identities and production
   secret provisioning only in a separately authorized deployment tranche
   (SEC-045/047/049/050).

Each implementation item requires fresh scoped approval under `AGENTS.md`.
