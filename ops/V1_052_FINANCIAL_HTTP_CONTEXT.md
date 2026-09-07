# V1-052 financial HTTP Property context

This bounded prerequisite follows accepted financial wire/shared storage4e3d2a1.
The planned26 financial client operations need authoritative Property binding on
every response. Several accepted responses include only Payment/Allocation/Receipt
identifiers; empty collections carry no data from which to check Property.

Add optional `X-Financial-Property-ID` to the existing26 HTTP operations. A single
canonical hyphenated nonzero UUID (case-insensitive hex) expresses the browser's
selected Property. Absence preserves existing callers. Duplicate, empty or malformed
values are400; a well-formed different Property is404. Check only after existing
actor/object/Property authorization, before all mutation service dispatch. This is
an additional context assertion, never authorization or a replacement for grants,
CSRF, X-Billing-Actor-ID, idempotency, source validation or fresh server checks.
Payment detail may perform its existing authorized read to resolve scope before
checking the expectation; no command or financial effect may run on a mismatch.

Successful envelopes add `meta.property_id` from the authorized server scope,
including empty lists and legacy callers without the header. Keep the existing
request correlation ID. Never echo untrusted header values as authoritative scope.
Error envelopes expose no Property identity. Preserve data, pages, locations,
original stored idempotent command replies, money/FX facts and all grants. No
financial service, schema/migration, canonical rule, dependency or UI change.

Tests cover all26 methods: matching/absent expectations, malformed/duplicate/zero
headers, cross-Property mismatch with no mutation dispatch, authorization ordering,
error privacy, empty collections and exact original-data replay. Unit/API coverage
complements fresh full exact backend/isolatedPostgreSQL/frontend/automation/static/
build/import/config/trace/guard/preservation checks and one independent complete-base
Astra/max/Standard/enforced-read-only review with zero findings. Standing authority
is the external property-rental-standing-independent-review-authorization.json,
SHA256d509c66234abf96872d9c7d9682adc2a1ed315c97772b5793dbbe9426dd6eeff.

This prerequisite refines the earlier read-only client plan to close a concrete
scope-verification gap. After acceptance, build26 clients and explicit encrypted
recovery, then permission-aware reference data/UI and all full52 release/closure
gates before53. At fully closed53 pause the same follow-up; no54.
