# V1-052 exact financial wire and encrypted recovery foundation

This bounded stage follows accepted Credit/USDRefund HTTP9b5a339. It implements
shared browser infrastructure for the required staff financial clients; it does
not complete those clients, UI, full-version browser workflows or release.
The existing takeover/scope and canonical financial/security rules remain authority.
No backend runtime, financial service, migration, dependency manifest or canonical policy
change is included. Implementation uses Astra/xhigh/Standard because it concerns
financial precision, encryption and concurrent admission.

## Exact JSON

`financialJson.ts` parses and serializes financial JSON without converting decimal
tokens to JavaScript numbers. Safe integers use numbers and larger integers use
bigint. Decimal/exponent tokens and negative zero use immutable ExactJsonNumber,
retaining their original literal. Ordinary strings remain strings. Native fractional,
nonfinite or unsafe numbers cannot be serialized; callers must provide an exact
literal or integer before rounding can occur. Native JSON.stringify on a tagged
exact number deliberately fails rather than silently changing its JSON type.

Both directions are iterative, allowing deeply nested valid data without recursive
stack overflow. Parsing rejects duplicate decoded keys, invalid JSON, malformed
Unicode and extra trailing data. Object keys remain own data, including __proto__.
Serialization rejects cycles, sparse arrays, undefined/functions/symbols, exotic
objects and enumerable getters. It does not call getters or custom toJSON hooks.
Shared noncyclic references may be repeated as ordinary JSON values.

The caller selects a positive safe-integer UTF8 byte limit; default262144 matches
the current financial POST envelope. No numeric rounding, cursor rewriting,
eligibility calculation, FIFO calculation or currency conversion occurs here.
Future resource readers must select limits appropriate to their complete server
projection rather than reusing a command limit that truncates valid history.

## Preserved encrypted storage

`sealedIntentStore.ts` extracts the existing billing journal's actor-keyed IndexedDB
reservation. Database property-rental.billing-intent.v1 stays version1, with the
same pending store and four fields: key, iv, ciphertext, requestKey. Existing
nonextractable256bit AES-GCM keys,12byte IVs and actor additional authenticated data
remain readable. No database rename, reset, destructive migration, record rewrite
or key replacement occurs. New keys remain nonextractable. Only synthetic test
fixtures are inserted, corrupted or removed by browser verification.

Read returns decrypted text and the stored request key only in memory. Owning
adapters validate the payload and its key before use. The primitive does not know
financial routes, perform fetch, retry commands or make authorization decisions.
Invalid metadata, malformed UTF8, decryption or storage failures fail closed.
The browser authority remains the authenticated actor and each server endpoint.

Begin captures immutable strings before its first await, encrypts before storing,
and atomically reads then inserts in one actor-keyed readwrite transaction. Any
existing value, including a corrupt/foreign record, blocks another reservation.
Each tab uses the same physical store; stale visible readiness cannot bypass this
final atomic guard. Clear checks the exact requestKey inside its transaction and
never deletes a different pending command. A failed write/clear remains blocked.
Open connections close on completion or versionchange; a blocked open that later
succeeds closes its unused connection.

The plaintext storage limit is1048576UTF8bytes, sufficient for a262144byte command
wire string plus JSON escaping and its bounded context envelope. Its sealed
ciphertext adds the16byte GCM tag. Identity strings are nonempty, bounded and valid
Unicode so different malformed strings cannot collapse to the same UTF8 actor
binding. This is input validation, not a change to domain identifiers or grants.

## Existing billing integration

`invoiceClient.ts` retains its public BillingJournal API and existing action
allowlist, Property presence and inner-key-versus-stored-key checks. It delegates
physical storage to the shared primitive and uses exact JSON in its in-memory
sealing/loading adapter. Existing legacy JSON records remain readable; bigint
amounts can now be serialized exactly. Unknown/foreign commands remain blocked and
are never cast into another operation or dispatched. Existing Invoice UI behavior,
transport, permissions, request keys, recovery gates and server services remain.

Later Payment/Allocation/Receipt/Credit/Refund adapters must use this same store,
validate their finite operation namespace, IDs and exact original wire payload,
and expose owning-workspace recovery. Separate stores that admit simultaneous
unknown financial commands are excluded. Explicit reviewed replay, actor/Property
invalidation and safe result matching remain later client/UI requirements; this
primitive performs no automatic financial replay.

## Verification and remaining scope

Unit regressions cover exact bigint/decimal wire round trips, malformed/duplicate
JSON, encoded-key safety, Unicode/byte limits,8000level nesting, unsupported values,
native serialization mistakes, preserved legacy billing records and fail-closed
adapter behavior. Existing Invoice client and component regressions must pass.

Real Chromium checks use synthetic data and the production modules to prove the
original ciphertext layout, nonextractable keys, actor-bound decryption, exact
payload capture, corruption refusal, request-key-specific clear, byte limits,
storage write/clear failure, reload without replay and competing browser-tab
reservations. Logs and failures remain outside the checkout. Browser test source
is frontend/src/test/financialRecovery.browser.ts; it is not a production page.

Acceptance requires all applicable exact frontend/backend/database/static/build/
automation/configuration/traceability/preservation gates and one fresh independent
Astra/max/Standard/enforced-read-only review of the complete9b-to-candidate diff,
with zero findings. Accepted9b evidence and every failed checkpoint stay preserved.
Then implement the26financial operation clients, their recovery workflows and staff
UI, perform full52cumulative review/release/CI/refs/same-card closure, and only then53.
At fully53closed pause the same native follow-up; keep OpenClaw disabled; no54.

The backend traceability test inventory additionally registers the three new financial
TypeScript unit suites (including parameterized cases) and the browser harness
success identifiers. Original Python/component inventory and all1469prior mappings
remain intact;27new assertion mappings are added. No unexecuted browser success is
claimed by static inventory: actual browser logs and exact-source hashes are required.
