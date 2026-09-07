# V1-052 Credit and USD Refund HTTP contract

Base: accepted Allocation/Receipt HTTP `5f4bd4160eb37f01bb9fc155076e5223b56f2802`.
Authority remains CODEX_TAKEOVER_V1_048_053 and the frozen V1_052_SCOPE.
This is the next bounded API-061–066 adapter slice. Implementation and acceptance
are pending; no whole-version release or new financial policy is claimed.

## Planned public operations

Paths have the `/api/v1` prefix. Resource identity placeholders below use descriptive
names in implementation. Linked read/reversal adapters expose already accepted
service operations required by the frozen scope.

| Method and path | Capability | Behavior |
| --- | --- | --- |
| GET `/customers/{customer_id}/credits` | credits.read | bounded recognized Credit list |
| GET `/customer-credits/{credit_id}` | credits.read | original Credit/source and current position |
| GET `/customer-credits/{credit_id}/ledger` | credits.read | complete paginated ledger with event-family cursor |
| POST `/payments/{payment_id}/credit-recognitions` | credits.recognize | explicit payer-authorized recognition, 201 |
| POST `/customer-credits/{credit_id}/reverse` | credits.reverse | approved linked recognition reversal, 200 |
| GET `/customer-credits/{credit_id}/application-proposal` | credits.apply | read-only selected Invoice/amount proposal |
| POST `/customer-credits/{credit_id}/applications` | credits.apply | explicit accepted application intent, 201 |
| GET `/credit-applications/{application_id}` | credits.read | complete original application/details and current target |
| POST `/credit-applications/{application_id}/reverse` | credits.applications.reverse | approved linked application reversal, 200 |
| GET `/properties/{property_id}/refunds` | refunds.read | bounded completed Refund list, optional Customer filter |
| GET `/refunds/{refund_id}` | refunds.read | original source/payout with paginated verified-return/correction history |
| GET `/refund-sources/{source_type}/{source_id}` | refunds.create | authoritative eligibility and original source audit |
| POST `/refunds` | refunds.create | explicit supported USD Refund, 201 |
| POST `/refunds/{refund_id}/verified-returns` | refunds.correct | exact verified returned USD value, 200 |
| POST `/refunds/{refund_id}/verified-returns/{correction_id}/reverse` | refunds.corrections.reverse | existing linked correction reversal, 200 |

Recognition requires USD currency, exact amount_usd_cents, payer authorization
reference and reason. Application requires USD currency plus the unchanged accepted
intent. All Refund creates/verified returns require explicit USD currency; reject
KHR, caller FX calculations, invented pending/failed status and payout method.
Source types for generic Refund create are PAYMENT/CREDIT/PET_DEPOSIT; Pet requires
the matching qualifying pet_refund_review_id. Unsupported Final Settlement and active
Security Deposit sources fail closed.

The Property-caused Reservation full Refund remains the existing atomic Reservation
cancellation lifecycle command with its existing separate capability and original
Refund identity. Show/link that existing path; never create a second generic payout.
Existing lifecycle Refund corrections retain their specialized original path;
the general Refund service rejects unsupported lifecycle corrections. Pet departure
and qualification remain the existing API-094 workflow, followed by explicit payout.

List/history pages default50, max100. Opaque cursors bind route/resource/Property,
Customer filter where applicable, timestamp/id, and ledger event kind where needed.
No invented empty-page acceptance for malformed cursors, duplicate or unknown query
fields, coerced amounts or unnormalized timestamps. Full source evidence remains
unchanged; links can avoid repeating large historical narratives.

## Narrow read boundary

Credit tables intentionally deny direct runtime SELECT. New forward-only migration45
adds only a read-only security-definer scope function returning one Property UUID and
a bounded original Payment/Credit audit projection for Refund eligibility. Both check
a fresh persisted active HUMAN before financial lookup, use fixed resource allowlists
and search paths, and expose no private command keys or responses. Runtime receives
EXECUTE only; table grants and all historical migrations remain unchanged.

The Python reader passes only the current actor's grants for the exact endpoint
capability and checks returned scope. These reads use bounded repeatable-read,
read-only transactions. Accepted Credit/Refund services retain their existing normal
transactions and SHARE locks. Commands require separate financial credentials, never
runtime fallback. No financial command or audit event is produced by the new reads.

HTTP reuses the accepted strict UTF8/duplicate-JSON/262144-byte streaming boundary;
canonical Credit intent250000bytes/500details remains. Preserve exact integer cents,
decimal-string FX evidence, exact actor/key/reason replay, CSRF/Origin protection,
safe error/correlation envelopes and private/no-store for every new route family.

## Verification

Cover fresh/disabled/nonhuman actors, exact capabilities and scope, no permission
escalation through source reads, unchanged private command/table privileges,
malformed currencies/amounts/evidence/timestamps, competing source consumption,
proposal/post/replay/reversal, complete tied-event pagination, source KHR audit,
Pet/Reservation restrictions and unknown outcomes. Register migration45 and retain
all prior migration history assertions; update only current-head expectations.
Add actual assertion-level traceability and exact API inventory when wiring routes.
Full exact checks and independent complete-base Astra/max/Standard/read-only zero
review precede bounded acceptance; full V1-052 UI/recovery/release gates still remain.

## HTTP representation detail

A Credit/Refund request guard rejects duplicate and unknown raw query fields with
400 before framework value validation, regardless of duplicate-value order. A
single invalid typed query value still returns422; unsupported methods retain405.
The inherited strict POST streaming boundary and accepted financial behavior are
unchanged. This is correction1 for retained candidatec4d6ad5's independent LOW finding.

Recognition uses `currency`, `amount_usd_cents`, `payer_authorization_reference`
and `reason`. Application uses `currency` and the unchanged `intent`. Refund
creation uses `currency`, `source_type`, `source_id`, `amount_usd_cents`, `reason`
and, for PET_DEPOSIT only, `pet_refund_review_id`. A verified return uses
`currency`, `returned_amount_minor`, `returned_at`, `return_method_reference`,
`evidence_reference` and `reason`. Correction reversal uses `evidence_reference`
and `reason`. All monetary command currencies must explicitly equal USD.

Customer Credit and Refund lists return `data` items plus a top-level `page`.
Credit ledger `history` and Refund `corrections` retain nested `items` plus a
nested `page` with `limit` and opaque `next_cursor`. This also applies to original
Refund command replies; pagination adapts the stored reply without a new read or
recalculation. Cursors bind collection, Property, resource and Customer filter,
plus the original timestamp/id and Credit ledger event kind where applicable.
Proposal queries require exact positive `amount_usd_cents` and `invoice_id`.
Pet source queries require `pet_refund_review_id`; other source types reject it.

The first adapter implementation is in progress. None of this HTTP slice is
accepted or published until focused/full checks and its fresh independent
complete-base review pass. The previously verified read foundation is recorded
separately with its retained failure evidence.
