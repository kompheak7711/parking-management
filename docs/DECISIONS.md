# Architecture Decisions

## ADR-001: Separate applications

**Status:** Accepted

**Decision:** Property rental management and parking management will be
maintained as separate repositories.

**Reason:** They have different domains, billing rules and potential deployment
lifecycles.

**Consequences:**

- Each application can evolve independently.
- Common functionality may initially be duplicated.
- Shared packages should be introduced only after genuine repeated needs appear.
