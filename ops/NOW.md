# Operations — risk-based model routing

- Objective: reduce Codex usage without weakening publication or sensitive-domain
  review gates.
- Current task: verified and published on `implementation/foundation` as `ea721af`;
  no implementation cycle is active.
- Routing: explicit low-risk mechanical tranches use fresh Ollama sessions; unknown,
  mislabeled, security, identity, permission, financial, business-policy, migration,
  architecture, production, credential, and canonical work fail closed to Codex.
- Recovery: local failure or unchanged compact state receives at most one fresh Codex
  escalation. Each wake-up remains bounded to six authorized tranches.
- Local limits: 40 Hermes iterations, hard stops for repeated/no-progress tools,
  30,000-token supervisor ceiling, 16,000-token compaction reserve, mid-turn pressure
  checks, and compacted transcript rotation.
- Verification: real named-provider Ollama smoke test returned `OLLAMA_PROVIDER_READY`;
  six model-free routing cases passed; format, lint, strict types, 49 backend tests,
  3 frontend tests, builds, npm and locked Python audits, TEST-118 traceability, and all
  6 isolated PostgreSQL migration tests passed. GitHub Actions run 32000171078 passed.
- Preserved boundaries: canonical docs 001-010, application behavior, database schema,
  credentials, production access, and Phase 2B authorization state are unchanged.
- Blocker: none.
- Exact next action: obtain owner approval before beginning the high-risk Phase 2B
  provider-neutral capability authorization boundary.
