# V1-051 KHR partial-value policy question — rejected and superseded by DL-060

## Resolution — 2026-09-06

The owner explicitly rejected the proposal below. USD is the main accounting
currency; KHR is only a Payment-conversion option. Financial transactions and all
Refunds are recorded in USD, and all Refunds are paid in USD. Do not implement KHR
Refunds. Preserve original transaction/KHR/conversion evidence without historical
rewrites. See DL-060 and the reconciled V1-051 scope.

This resolves the obsolete KHR-refund blocker. Partial USD returns are exact USD
cents; the former KHR rounding/remainder question is not an outstanding decision.
Resume the same Codex takeover through V1-053 with all existing gates and exclusions.
OpenClaw remains disabled; pause the native follow-up at V1-053 closure, no V1-054.

The original question had SHA256
32a8e72e25584f4a0a02f378566ad6de3100cc26f26b2c1411c30ae04960572d.
Its contents below are preserved as historical evidence only. Their proposed policy,
pause instructions and approval request are superseded, not current instructions.

## Historical question (not operative)

## Accepted boundary

Credit list/history exactedfea74515d2ddf134cdac67a4b7250594d38d2a is independently
accepted0HIGH0MEDIUM0LOW; acceptance receipt SHA256
265383fc5578d6e537ea4387727aac973e4a580fe56df9b755512e2abc5568f9.
FullV1-051 remains OPEN/unpublished. No KHR product code has been changed.
The standing implementation/publication authority remains valid; this is a financial
policy question, not a request for routine reauthorization.

## Evidence and ambiguity

Read canonical BR-PAY-030..034, BR-CREDIT-010/011, BR-REFUND-003/005/006/008/011,
BR-MONEY-003..012, PR-REFUND-005/006/008, UI-069/071/072, DB-PAY-002/003,
DB-REFUND-001/002, API-061/065/066/085, TEST-071..074 and DL-030/031.
These establish original KHR and original USD basis preservation, a new applicable
rate for later Credit-to-KHR, upward System Rate/final-KHR rounding, immutable
history and currency-effect reconciliation. They do not specify which partial
disposition receives the original transaction's rounding remainder, nor a cumulative
partial-return USD restoration rule.

The existing published Payment validator explicitly accepts authoritative channel
KHR and USD amounts as controlling facts when both are present; it does not replace
them with a System Rate conversion. This is tested by test_payment_migration.py.
For example, its valid channel case records USD101cents and KHR4100 while preserving
System Rate4101KHR/USD. Thus converting every partial balance at the System Rate
cannot reconstruct the authoritative original amount.

Synthetic arithmetic illustration, not customer data:
- Original confirmed pair USD101cents/KHR4100;100cents applied,1cent excess.
- Proportional1cent is4100/101KHR, approximately40.594KHR.
- Rounding that isolated partial amount upward yields41KHR.
- Rounding the100cent consumed portion upward first yields4060KHR, leaving40KHR.
Both retain the original exchange record, but assign its one-riel remainder to
different portions. No KHR attribution was stored on the USD-only allocation.
Selecting one changes the actual customer refund; the missing choice is not a
new rate provider or a generic authorization question.

Partial verified returns have a related cumulative-cent issue: per-return rounding
can over-restore or strand part of the original USD basis. DB-REFUND-002 requires
nonzero USD effects, so a sub-cent KHR return cannot silently become a zero-value
correction or an invented pending-return workflow.

## Decision requested, not approved

Proposed direction for owner confirmation: apportion partial original-source KHR
Refunds and verified returns using the original confirmed USD/KHR pair, carry rounding
remainders cumulatively and reconcile the final portion exactly to original totals.
Retain original rates/amounts, never restore more USD or KHR than the original,
and keep unrepresentable zero-cent corrections fail-closed under DB-REFUND-002.
Later Credit-to-KHR creation still uses its applicable Refund rate/upward rounding;
its later partial corrections must reconcile the immutable resulting USD/KHR pair.

This is a proposal, not an implemented or approved business rule. Ask whether the
owner approves that direction or requires another remainder-allocation rule. After
the answer, record the actual authorized rule in010_DECISION_LOG and applicable
canonical sources before implementing; obtain fresh tests/exact-SHA independent
review. Do not infer consent from earlier blanket implementation authorization.

## Safe pause and continuation

Preserve SAME51checkout and all126worktrees/failed checkpoints. Only ops acceptance/
this policy question are currently being updated; no accepted product change.
OpenClaw658ffdaf stays disabled; same tracking-onlycardc5621f97 retains evidence and
no claim/attempt/execution. Native same-task10minute follow-up may reconcile owner
responses but must stay quiet while this decision is unchanged and not dispatch
any worker or invent the missing rule. No repeated routine authorization request.
No52before51closed; through53only, then pausefollowup/leaveOCdisabled/no54.
Production/customerdata/paid/destructive/forcepush/historyrewrite/worktree deletion
remain unauthorized.
