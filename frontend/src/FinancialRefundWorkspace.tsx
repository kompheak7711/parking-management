import { PET_DEPOSIT } from "./leases/parking";
import { useEffect, useState, type FormEvent } from "react";
import {
  financialId,
  financialInteger,
  financialObject,
  type FinancialObject,
} from "./financialContracts";
import type { FinancialReply } from "./financialResponse";
import {
  ActionContextEvidence,
  RefundCorrectionEvidence,
  RefundEvidence,
  RefundSourceEvidence,
} from "./FinancialEvidence";
import {
  loadFinancialActionContext,
  readFinancialRecord,
  useFinancialTask,
  useFinancialDraft,
  useFinancialSnapshot,
} from "./financialUiContext";
import {
  FinancialInputError,
  financialLabel,
  financialLocalInstant,
  financialMoney,
  parseFinancialAmount,
  type FinancialCommandRequest,
  type FinancialWorkspaceProps,
} from "./financialUi";

type Mode = "read" | "create" | "return" | "reverse";
type Source = "PAYMENT" | "CREDIT" | "PET_DEPOSIT";
const modes = [
  ["read", "View Refunds", "refunds.read"],
  ["create", "Record USD Refund", "refunds.create"],
  ["return", "Record verified USD return", "refunds.correct"],
  ["reverse", "Reverse return correction", "refunds.corrections.reverse"],
] as const;
const initial = {
  customer: "",
  refund: "",
  correction: "",
  sourceId: "",
  reviewId: "",
  amount: "",
  reason: "",
  returnedAt: "",
  method: "",
  evidence: "",
};
function nextCursor(reply: FinancialReply, history = false): string | null {
  const page = history
    ? financialObject(
        financialObject(financialObject(reply.data).corrections).page,
      )
    : reply.page;
  return typeof page?.next_cursor === "string" ? page.next_cursor : null;
}
function correctable(data: FinancialObject) {
  const context = financialObject(data.context);
  const resource = financialObject(context.refund),
    refund = financialObject(resource.refund);
  if (
    refund.source_lifecycle_event_id !== null ||
    refund.refund_currency !== "USD"
  )
    throw new FinancialInputError(
      "Use the coordinated Reservation outcome workflow for this historical Refund.",
    );
  return { context, resource, refund };
}

export function FinancialRefundWorkspace({
  scope,
  capabilities,
  services,
  commands,
  onDirtyStateChange,
}: FinancialWorkspaceProps) {
  const allowed = modes.filter(([, , capability]) => capabilities[capability]);
  const [mode, setMode] = useState<Mode>(allowed[0]?.[0] ?? "read");
  const [source, setSource] = useState<Source>("PAYMENT");
  type DraftField = keyof typeof initial | "sourceKind";
  const draft = useFinancialDraft<DraftField>(scope, onDirtyStateChange);
  const [fields, setFields] = useState(initial);
  const [context, setContext] = useState<FinancialObject | null>(null);
  const [list, setList, listCurrent] = useFinancialSnapshot<FinancialReply>(
    commands.revision,
  );
  const [detail, setDetail, detailCurrent] =
    useFinancialSnapshot<FinancialReply>(commands.revision);
  const task = useFinancialTask(scope, commands.revision);
  const { cancel } = task;
  const { revision, invalidate } = commands;
  useEffect(() => {
    cancel();
    setContext(null);
  }, [revision, cancel]);
  function edit(values: Partial<typeof initial>) {
    for (const [name, value] of Object.entries(values)) {
      const key = name as keyof typeof initial;
      if (value !== fields[key] && (mode !== "read" || draft.hasEdits([key])))
        draft.edited(key);
    }
    cancel();
    invalidate();
    setContext(null);
    setList(null);
    setDetail(null);
    setFields((old) => ({ ...old, ...values }));
  }
  function choose(value: Mode) {
    cancel();
    invalidate();
    setContext(null);
    setList(null);
    setDetail(null);
    setMode(value);
  }
  function readList(cursor?: string) {
    if (!capabilities["refunds.read"]) return;
    setList(null);
    setDetail(null);
    void task.run(
      async (s) =>
        await readFinancialRecord(
          s,
          {
            operation: "refundList",
            target: {},
            query: {
              limit: 50,
              ...(fields.customer
                ? { customer_id: financialId(fields.customer) }
                : {}),
              ...(cursor ? { cursor } : {}),
            },
          },
          services.transport,
        ),
      setList,
    );
  }
  function readDetail(id = fields.refund, cursor?: string) {
    if (!capabilities["refunds.read"]) return;
    if (id !== fields.refund && !draft.confirmDiscard(["refund"])) return;
    setDetail(null);
    void task.run(
      async (s) =>
        await readFinancialRecord(
          s,
          {
            operation: "refundGet",
            target: { id: financialId(id) },
            query: { limit: 50, ...(cursor ? { cursor } : {}) },
          },
          services.transport,
        ),
      (reply) => {
        setDetail(reply);
        if (id !== fields.refund) draft.clear(["refund"]);
        setFields((old) => ({ ...old, refund: id }));
      },
    );
  }
  function load(confirmation: boolean) {
    const capability = modes.find(([key]) => key === mode)?.[2];
    if (
      !capability ||
      !capabilities[capability] ||
      mode === "read" ||
      (confirmation && !commands.ready)
    )
      return;
    const preparation = confirmation ? commands.beginReview() : null;
    if (!confirmation) invalidate();
    setContext(null);
    void task.run(
      async (s) => {
        let data: FinancialObject;
        if (mode === "create") {
          const reply = await readFinancialRecord(
            s,
            {
              operation: "refundSource",
              target: { sourceType: source, id: financialId(fields.sourceId) },
              ...(source === "PET_DEPOSIT"
                ? {
                    query: {
                      pet_refund_review_id: financialId(fields.reviewId),
                    },
                  }
                : {}),
            },
            services.transport,
          );
          data = financialObject(reply.data);
        } else {
          data = await loadFinancialActionContext(
            s,
            {
              operation: "financialActionContext",
              purpose:
                mode === "return"
                  ? "refund_return"
                  : "refund_correction_reversal",
              source_id: financialId(
                mode === "return" ? fields.refund : fields.correction,
              ),
              ...(mode === "reverse"
                ? { refund_id: financialId(fields.refund) }
                : {}),
            },
            services.references,
          );
        }
        let request: FinancialCommandRequest | null = null;
        if (confirmation) {
          if (mode === "create") {
            const amount = parseFinancialAmount(fields.amount);
            if (
              data.eligible !== true ||
              amount > BigInt(financialInteger(data.available_usd_cents))
            )
              throw new FinancialInputError(
                "The requested Refund exceeds the currently eligible USD source amount.",
              );
            request = {
              operation: "refundCreate",
              target: {},
              body: {
                currency: "USD",
                source_type: source,
                source_id: financialId(fields.sourceId),
                amount_usd_cents: amount,
                reason: fields.reason,
                ...(source === "PET_DEPOSIT"
                  ? { pet_refund_review_id: financialId(fields.reviewId) }
                  : {}),
              },
            };
          } else {
            const selected = correctable(data);
            if (mode === "return") {
              const amount = parseFinancialAmount(fields.amount);
              if (
                amount >
                BigInt(financialInteger(selected.resource.net_refund_usd_cents))
              )
                throw new FinancialInputError(
                  "The demonstrated return exceeds the current net USD payout.",
                );
              request = {
                operation: "refundReturn",
                target: { id: financialId(fields.refund) },
                body: {
                  currency: "USD",
                  returned_amount_minor: amount,
                  returned_at: financialLocalInstant(fields.returnedAt),
                  return_method_reference: fields.method,
                  evidence_reference: fields.evidence,
                  reason: fields.reason,
                },
              };
            } else {
              const correction = financialObject(selected.context.correction);
              if (
                selected.context.reversal !== null ||
                correction.correction_kind !== "VALUE_CORRECTION" ||
                correction.verified_return_currency !== "USD"
              )
                throw new FinancialInputError(
                  "This selected return correction is already reversed or is not a demonstrated USD return.",
                );
              request = {
                operation: "refundReturnReverse",
                target: {
                  id: financialId(fields.refund),
                  correctionId: financialId(fields.correction),
                },
                body: {
                  evidence_reference: fields.evidence,
                  reason: fields.reason,
                },
              };
            }
          }
        }
        return { data, request };
      },
      ({ data, request }) => {
        if (preparation && !preparation.isCurrent()) return;
        setContext(data);
        if (request)
          preparation?.review(request, {
            onRecorded: draft.captureRecorded(
              mode === "create"
                ? [
                    "sourceKind",
                    "sourceId",
                    "amount",
                    "reason",
                    ...(source === "PET_DEPOSIT" ? ["reviewId" as const] : []),
                  ]
                : mode === "return"
                  ? [
                      "refund",
                      "amount",
                      "returnedAt",
                      "method",
                      "evidence",
                      "reason",
                    ]
                  : ["refund", "correction", "evidence", "reason"],
            ),
            consequence:
              mode === "create"
                ? "Record a completed USD payout from this exact source. The original payout and its audit history are permanent."
                : mode === "return"
                  ? "Record only the demonstrated USD money return and restore its supported source balance. This does not establish a collection right or erase the original payout."
                  : "Reverse this exact verified-return correction and remove its source-balance restoration. The original Refund and correction remain in the audit history.",
            evidence:
              mode === "create" ? (
                <RefundSourceEvidence value={data} />
              ) : (
                <ActionContextEvidence value={data} />
              ),
          });
      },
    );
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mode === "read") readDetail();
    else load(true);
  }
  const detailData = detail ? financialObject(detail.data) : null;
  const history = detailData ? financialObject(detailData.corrections) : null;
  const corrections =
    history && Array.isArray(history.items) ? history.items : [];
  const legacy =
    context && mode !== "create" && mode !== "read"
      ? financialObject(
          financialObject(financialObject(context.context).refund).refund,
        ).source_lifecycle_event_id !== null
      : false;
  if (!allowed.length) return null;
  return (
    <section id="financial-refund-workspace" aria-label="Refund workspace">
      <h3>Refunds and verified returns</h3>
      <p>
        Refund payouts and verified returns are USD. Original incoming KHR
        evidence stays attached to its source.
      </p>
      <nav aria-label="Refund actions">
        {allowed.map(([key, label]) => (
          <button
            key={key}
            type="button"
            aria-pressed={mode === key}
            disabled={commands.busy}
            onClick={() => {
              choose(key);
            }}
          >
            {label}
          </button>
        ))}
      </nav>
      <form onSubmit={submit}>
        <fieldset disabled={commands.busy}>
          <legend>{modes.find(([key]) => key === mode)?.[1]}</legend>
          {mode === "read" ? (
            <>
              <label>
                Customer reference filter (optional)
                <input
                  value={fields.customer}
                  onChange={(e) => {
                    edit({ customer: e.target.value });
                  }}
                />
              </label>
              <button
                type="button"
                disabled={task.busy}
                onClick={() => {
                  readList();
                }}
              >
                Load Refund list
              </button>
            </>
          ) : null}
          {mode === "create" ? (
            <>
              <label>
                Refund source
                <select
                  value={source}
                  onChange={(e) => {
                    const value = e.target.value;
                    if (
                      value === "PAYMENT" ||
                      value === "CREDIT" ||
                      value === "PET_DEPOSIT"
                    ) {
                      if (value === source) return;
                      if (!draft.confirmDiscard(["sourceId", "reviewId"]))
                        return;
                      edit({ sourceId: "", reviewId: "" });
                      draft.clear(["sourceId", "reviewId"]);
                      draft.edited("sourceKind");
                      setSource(value);
                    }
                  }}
                >
                  <option value="PAYMENT">Unallocated Payment</option>
                  <option value="CREDIT">Recognized Customer Credit</option>
                  {/* Parking Step 5: no pet on Parking (PET_DEPOSIT). */}
                  {PET_DEPOSIT && (
                    <option value="PET_DEPOSIT">Qualified Pet Deposit</option>
                  )}
                </select>
              </label>
              <label>
                Source reference
                <input
                  required
                  value={fields.sourceId}
                  onChange={(e) => {
                    edit({ sourceId: e.target.value });
                  }}
                />
              </label>
              {source === "PET_DEPOSIT" && (
                <>
                  <label>
                    Qualifying Pet review reference
                    <input
                      required
                      value={fields.reviewId}
                      onChange={(e) => {
                        edit({ reviewId: e.target.value });
                      }}
                    />
                  </label>
                  <a href="#deposit-management-heading">
                    Open Deposit management for Pet qualification
                  </a>
                </>
              )}
            </>
          ) : (
            <label>
              Refund reference
              <input
                required
                value={fields.refund}
                onChange={(e) => {
                  edit({ refund: e.target.value });
                }}
              />
            </label>
          )}
          {mode === "reverse" && (
            <label>
              Original return correction reference
              <input
                required
                value={fields.correction}
                onChange={(e) => {
                  edit({ correction: e.target.value });
                }}
              />
            </label>
          )}
          {mode !== "read" && (
            <>
              <button
                type="button"
                disabled={task.busy}
                onClick={() => {
                  load(false);
                }}
              >
                Load current source facts
              </button>
              {(mode === "create" || mode === "return") && (
                <label>
                  {mode === "create"
                    ? "Refund amount (USD)"
                    : "Demonstrated returned amount (USD)"}
                  <input
                    required
                    inputMode="decimal"
                    value={fields.amount}
                    onChange={(e) => {
                      edit({ amount: e.target.value });
                    }}
                  />
                </label>
              )}
              {mode === "return" && (
                <>
                  <label>
                    Verified return time (Asia/Phnom_Penh, +07:00)
                    <input
                      required
                      type="datetime-local"
                      step="0.001"
                      value={fields.returnedAt}
                      onChange={(e) => {
                        edit({ returnedAt: e.target.value });
                      }}
                    />
                  </label>
                  <label>
                    Actual return method reference
                    <input
                      required
                      maxLength={500}
                      value={fields.method}
                      onChange={(e) => {
                        edit({ method: e.target.value });
                      }}
                    />
                  </label>
                </>
              )}
              {(mode === "return" || mode === "reverse") && (
                <label>
                  Evidence reference
                  <input
                    required
                    maxLength={500}
                    value={fields.evidence}
                    onChange={(e) => {
                      edit({ evidence: e.target.value });
                    }}
                  />
                </label>
              )}
              <label>
                Reason
                <textarea
                  required
                  maxLength={1000}
                  value={fields.reason}
                  onChange={(e) => {
                    edit({ reason: e.target.value });
                  }}
                />
              </label>
            </>
          )}
          <button
            type="submit"
            disabled={
              task.busy || (mode !== "read" && (!commands.ready || legacy))
            }
          >
            {mode === "read" ? "Load original Refund" : "Review Refund action"}
          </button>
        </fieldset>
      </form>
      {task.busy && <p role="status">Loading complete financial facts…</p>}
      {task.error && <p role="alert">{task.error}</p>}
      {(!listCurrent || !detailCurrent) && (
        <p role="status">
          Loaded financial facts are out of date after another action. Original
          facts remain below. Reload the record or history for current balances,
          status and complete history.
        </p>
      )}
      {legacy && (
        <p>
          This historical Refund uses the{" "}
          <a href="#reservation-management-heading">
            coordinated Reservation outcome workflow
          </a>
          .
        </p>
      )}
      {context &&
        (mode === "create" ? (
          <RefundSourceEvidence value={context} />
        ) : (
          <ActionContextEvidence value={context} />
        ))}
      {list && (
        <section aria-label="Refund list page">
          <h4>Refund list page</h4>
          {Array.isArray(list.data) && list.data.length === 0 ? (
            <p>No Refunds match this Property and filter.</p>
          ) : (
            <ul>
              {Array.isArray(list.data) &&
                list.data.map((item) => {
                  const resource = financialObject(item),
                    refund = financialObject(resource.refund),
                    id = financialId(refund.id);
                  return (
                    <li key={id}>
                      <button
                        type="button"
                        disabled={task.busy || commands.busy}
                        onClick={() => {
                          readDetail(id);
                        }}
                      >
                        {financialLabel(refund.refund_number)} ·{" "}
                        {financialMoney(refund.refund_amount_minor)} · {id}
                      </button>
                    </li>
                  );
                })}
            </ul>
          )}
          <p>
            This is one loaded page of original payouts. Reload after another
            action for a current list.
          </p>
          {listCurrent && nextCursor(list) && (
            <button
              type="button"
              disabled={task.busy}
              onClick={() => {
                readList(nextCursor(list) ?? undefined);
              }}
            >
              Next Refund page
            </button>
          )}
        </section>
      )}
      {detailData && (
        <section aria-label="Selected Refund result or record">
          <RefundEvidence resource={detailData} showPosition={detailCurrent} />
          {detailCurrent && (
            <>
              <h4>Refund correction history page</h4>
              {corrections.length === 0 ? (
                <p>No corrections on this page.</p>
              ) : (
                corrections.map((item) => (
                  <RefundCorrectionEvidence
                    key={financialId(financialObject(item).id)}
                    value={item}
                  />
                ))
              )}
              {detail && nextCursor(detail, true) && (
                <p>
                  More correction history exists.
                  {capabilities["refunds.read"] && (
                    <button
                      type="button"
                      disabled={task.busy}
                      onClick={() => {
                        readDetail(
                          financialId(financialObject(detailData.refund).id),
                          nextCursor(detail, true) ?? undefined,
                        );
                      }}
                    >
                      Next correction page
                    </button>
                  )}
                </p>
              )}
            </>
          )}
        </section>
      )}
    </section>
  );
}
