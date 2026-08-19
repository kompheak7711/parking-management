# V1-013 Standards-based TOTP MFA Cryptographic and Persistence Foundation — verified

- Objective: implement the approved bounded RFC 6238 TOTP enrollment-verifier mechanics and
  protected persistence foundation without adding public API/UI, SMS, or production secrets.
- Current result: RFC 6238 generation matches published SHA-1 vectors; exact-counter verification
  fails closed for wrong, stale, or malformed codes; enrollment seeds use 160 bits of OS entropy.
- Secret protection: AES-256-GCM authenticates and encrypts seeds with random 96-bit nonces,
  explicit key identifiers, and actor/enrollment-bound associated data. Secret wrappers and
  protected material do not expose plaintext through representations, logs, or output.
- Persistence: forward-only migration `20260819_06` stores only ciphertext, nonce, key identifier,
  bounded TOTP parameters, lifecycle state, and provenance separately from role/capability data.
  One pending/active enrollment is allowed per actor; disabled history is retained.
- Database controls: immutable verifier material, forward-only pending/active/disabled transitions,
  actor/provenance requirements, existing-account foreign keys, constraints, and column-bounded
  runtime privileges were verified on isolated real PostgreSQL.
- Dependency: locked `cryptography==50.0.0` supplies reviewed AES-GCM rather than custom encryption;
  no production key or secret is configured or committed. GitHub Actions dependency audit rejected
  the initially locked 46.0.7 release; repair attempt 2 upgraded to the first release fixing all
  reported advisories, and the exact CI audit command then passed locally.
- Test-first evidence: crypto tests first failed on the absent module; PostgreSQL tests first failed
  on the absent table; traceability first failed on absent entries; key-identifier hardening first
  failed when application validation was weaker than persistence.
- Verification: backend 232 passed with 69 expected dedicated-database skips; frontend 3 passed;
  isolated PostgreSQL 69 passed; formatting, lint, strict typecheck, builds/import, deployment,
  roadmap, automation, lock consistency, and frontend dependency audit passed.
- Initial independent review found two persistence defects: enrollment history remained removable
  through owner-level DELETE/TRUNCATE, and AES-GCM nonce uniqueness was not enforced per key.
  Repair attempt 1 added destructive-operation rejection triggers, per-key nonce uniqueness, and
  real-PostgreSQL regressions. Independent re-review passed with no material findings. Repair
  attempt 2 corrected the vulnerable dependency bound identified by the publication CI gate.
- Scope preserved: no API/UI, SMS, session/recovery orchestration, production key, role/capability
  policy, deployment operation, canonical specification change, or unrelated implementation.
- Publication: feature commit `c4d14d5` is pushed; CI run `32221669512` passed backend,
  frontend, and PostgreSQL gates but failed the runtime dependency audit. The verified
  cryptography 50.0.0 corrective update remains uncommitted pending focused publication.
- Blockers: none. Owner action: none.
- Roadmap remains 12/60 published complete until V1-013 is independently published.
- Exact next action: independently verify and publish the completed bounded V1-013 tranche under
  standing authorization, then reconcile the roadmap and dispatch its approved successor.
