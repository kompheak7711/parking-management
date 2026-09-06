# V1-051 qualified Pet Deposit Refund checkpoint

## Authority and scope

Standing direct Codex takeover through V1-053: ops/CODEX_TAKEOVER_V1_048_053.md.
Frozen scope: ops/V1_051_SCOPE.md. This bounded successor to accepted USD service
ec77dde87cdd5f957b78afbdc736766ff43bb5fe starts from continuation marker
2f45c8ab3a9b824650e34ab0225e6f020d13ee3b. Full eventual V1-051 cumulative review
base remains cc3d18e682401cc8a9ade10295572fe1a1344317.

Coordinator and financial/concurrency/migration implementation: Astra xhigh Standard.
Fresh independent exact-SHA reviewer: Astra max Standard, read-only, no fallback.
No publication or full V1-051 acceptance is claimed by this partial checkpoint.

## Implementation and canonical traceability

- BR-DEP-011..014, PR-DEP-012, DB-LEASE-010/011, API-094/API-065, TEST-126,
  DL-053: Refunds reuse the existing append-only qualifying review and permanent
  departure. Review, Pet approval, Deposit, Customer, Property and SIGNED Lease
  must match. A shared Lease lock preserves status until Refund commit. Obligations
  were resolved in the separate qualifying review; execution never mints a review.
- Refund execution uses independently grantable refunds.create, never an implied
  deposits.refund.qualify grant. Source preview and create revalidate actor and exact
  Property; recipient and available integer USD cents are server-derived. Command
  replay retains Property/actor/action/key and complete exact immutable intent/response.
- Extend existing Refund source context with pet_refund_review_id, exclusive of
  Reservation lifecycle context. Existing Reservation full-outcome/correction paths
  stay unchanged. There is no active Security Refund, Invoice Deposit application,
  Lease termination, Final Settlement, liability cap or new business policy.
- API-066/DB-REFUND-002: USD verified returns and exact linked correction reversals
  work against Pet Deposit sources. History, original payout and audit remain immutable;
  a reversal cannot reuse value consumed by a later Refund or receipt reversal.
- Every current Deposit held-balance writer (receipt/reversal, disposition/reversal,
  Refund/correction) shares the Deposit root lock and a real MVCC guard revision.
  READ COMMITTED refreshes after serialization; stale Repeatable Read/Serializable
  consumers fail with SQLSTATE40001. No mutation is exposed on guard rows or helpers.
- Deferred Deposit conservation checks all historical timestamp groups, not only a
  zero-clamped current balance. Reversals cannot predate their source. Explicit
  Refund/correction chronology continues the latest source event. The new guard
  coexists with existing Payment source and Reservation outcome protections.
- Refund resources capture matching review/departure identities and typed facts with
  the correction page in one bounded snapshot. Full retained review/departure narratives
  stay in their existing source resources; they are neither copied into every Refund
  response nor truncated/replaced in storage. Audit includes exact Deposit/review identity,
  Property-local business date, Customer and Lease. Generic PATCH/DELETE remain absent.

Only the unpublished forward migration41 is extended; published migrations and
canonical specifications are untouched. No new dependency, external provider or
production data is used. The PostgreSQL harness uses disposable synthetic data only.

## Verification checkpoint

- PASS 64 Refund unit cases, 86 Refund-unit plus traceability cases (6.19s).
- PASS 28 focused real PostgreSQL Pet Refund cases (3.89s); 708 other cases
  deselected for this focused run and covered by the final full run below.
- PASS formatting, Ruff and mypy (143 source files).
- PASS final full PostgreSQL:736 cases,zero skips,110.82s. Verified log SHA256
  e336682cf75776db868c8c8c7dafaee69b05b1437f853464b5afa84cebf0f2b0.
- PASS final full backend:940 cases,713 database-only skips covered separately by
  real PostgreSQL,40.61s; build/import passed. Verified log SHA256
  cca2187dcddd553e6d2c1df748bbec531201ad0adac5d3e7f3053d9590017865.
- PASS 189 automation tests73.300s and routing/state-routing/watchdog/retired
  restoration/syntax/deployment checks. Traceability/publication/diff guards pass.
  Automation/configuration guards will also be run on the frozen exact SHA.
- These full gates cover the final bounded-summary refinement and corrected
  normalized synthetic fixture; earlier failed and superseded logs remain preserved.
  Fresh exact-SHA readback and independent review remain required for acceptance.
- Fresh independent exact-SHA zero-finding review is pending, not acceptance.
- Preserved development diagnostics: v1051-pet-refund-test-development.md in the
  Codex evidence directory. No financial guard was weakened to obtain a pass.

## Remaining lifecycle

After accepted Pet checkpoint, continue original-KHR Payment excess, Credit-to-KHR
Refunds and bounded Credit history in the same sole V1-051 checkout. Then all frozen
scope, full integration/audits, cumulative independent review, normal authorized
publication, exact CI/ref equality, existing-card acceptance and terminal reconciliation
remain required. V1-052 is not activated while V1-051 is open.

OpenClaw supervisor658ffdaf-1ac1-45a6-a842-f5f7d7a226eb remains disabled;
existing native 10-minute follow-up remains active. No new worker, card or worktree.
No production/access/credentials/customer data/paid/destructive/force-push/history
rewrite or retained-worktree deletion authority is introduced.
