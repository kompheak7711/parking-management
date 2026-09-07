# V1-052 financial clients and explicit recovery

Bounded stage from accepted226c353. Implement14 GET and12 POST operations across
Payment, Allocation, Receipt, Credit and USD Refund with finite validated paths,
exact money/FX JSON and server-authorized Property metadata. Server remains the
authority for grants, availability, FIFO, eligibility, FX and financial effects.
No service/migration/grant/dependency/canonical policy or staff UI change.

Capture plain validated command data before awaiting. POST bodies are at most
262144 UTF8 bytes; opaque integer-only allocation intents are at most250000 bytes
and500 details. Strict nonzero UUIDs and finite queries prevent stored URL dispatch.
Transport uses credentials include, no-store, redirect error, existing CSRF and
actor binding, one overall deadline and bounded fatal-UTF8 exact JSON reads.
Require actual route status and matching Property/resource/source identity; malformed
or unsafe successful replies keep commands unresolved. No sensitive error echo.
Read budgets are defensive client availability limits, never financial truncation:
oversized server history must produce an explicit unavailable result. Record exact
chosen budgets and rationale before verification; no claim all historic text bounded.

Persist only a versioned financial envelope in the existing shared encrypted
actor-keyed store: actor, Property, finite operation/target IDs, request key and exact
original wire body. Never credentials, URLs or plaintext browser storage. Atomic
begin precedes first transmission. Foreign billing/unknown/corrupt records block new
commands without clearing or dispatch. Restore validates inner/outer identity/key.
Only explicit submission/retry sends; reload/login/reconnect never replay. Replay
uses original bytes/key and rechecks current actor/Property context. Unknown outcomes
remain pending through later validation/auth/conflict errors. Clear only the exact
stored key after validated success, or a freshly submitted definitive rejection.
Storage failure fails closed; late work from invalidated contexts never updates UI.

Verify all26 mappings, strict exact schemas and response identity; transport bounds,
immutable capture, abort/deadline and late events; shared admission, foreign/corrupt
records and storage failures; explicit original replay and real-browser concurrency.
Preserve existing billing and accepted codec/store tests. Add assertion traceability.
Freeze normal candidate, exact applicable full checks and one fresh complete226-base
Astra/max/Standard/enforced-read-only review with zero findings before acceptance.

Standing OpenAI review authority through53 is external
property-rental-standing-independent-review-authorization.json,
SHA256d509c66234abf96872d9c7d9682adc2a1ed315c97772b5793dbbe9426dd6eeff.
Include it in all future review requests/handoffs; respect automatic enforcement and
exclude credentials/secrets/customer/production data. Preserve rejected5578/report
and all regression evidence. No completed tests repeat solely due to pending approval.
After acceptance: capability/reference boundaries and staff UI, full52 release/CI/
refs/same-card/durable closure, then53. Closed53 pauses SAME follow-up; no54.

All successful replies use a defensive4MiB decoded UTF8 budget. This exceeds the
existing1MiB inner Allocation history/Refund audit budgets plus envelopes; it is
an explicit client availability ceiling because some historical text is unbounded.
Oversized evidence remains unavailable and an affected command remains unresolved.
The overall20-second deadline spans fetch and streamed body reads, including a
noncooperating transport. No dependency inputs or accepted runtime files change.

Correction1 after rejected989d934: initial/replay financial attempts require a
shared actor-scoped exclusive Web Lock with ifAvailable (no queued automatic send).
Hold through outcome retirement; unavailable coordination blocks commands. The
encrypted store format stays unchanged. Actual Payment confirmation has no position;
Refund correction replies must prove the newest returned/reversed event. Align
internal envelope budgets without raising wire limits and retain safe correlation
on invalid replies. Five findings require regression proof and fresh full-base review.
