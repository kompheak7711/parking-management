import { useEffect, useState, type FormEvent } from "react";
import type { FinancialScope } from "./financialClient";
import {
  financialId,
  financialObject,
  type FinancialObject,
} from "./financialContracts";
import { stringifyFinancialJson } from "./financialJson";
import type { FinancialReply } from "./financialResponse";
import { FinancialFacts, PaymentEvidence } from "./FinancialEvidence";
import {
  FinancialInputError,
  originalFinancialReceiptId,
  financialLabel,
  financialLocalInstant,
  financialMoney,
  financialTimestamp,
  parseFinancialAmount,
  parseFinancialRate,
  type FinancialCommandRequest,
  type FinancialWorkspaceProps,
} from "./financialUi";
import {
  FINANCIAL_UI_CONTEXT_BYTES,
  readFinancialRecord,
  useFinancialTask,
  useFinancialDraft,
  useFinancialSnapshot,
} from "./financialUiContext";

const initial = {
  payer: "",
  method: "",
  receivedAt: "",
  evidence: "",
  amount: "",
  usd: "",
  lease: "",
  invoice: "",
  charge: "",
  memo: "",
  channelReference: "",
  channelConfirmedAt: "",
  channelAmount: "",
  channelUsd: "",
  channelRate: "",
  manualRate: "",
  manualSource: "",
  manualAt: "",
  manualReason: "",
};
function cursor(value: unknown): string | undefined {
  const row = financialObject(value);
  return typeof row.next_cursor === "string" ? row.next_cursor : undefined;
}
function KhrPreviewEvidence({ value }: { value: FinancialObject }) {
  return (
    <section aria-label="Provisional KHR preview">
      <h4>Provisional KHR preview</h4>
      {value.status === "source_unavailable" ? (
        <p>
          The approved automatic rate source is unavailable.{" "}
          {value.manual_fallback_allowed === true
            ? "Authorized manual fallback may be supplied with its source evidence."
            : "Manual fallback is not available with current access."}
        </p>
      ) : (
        <FinancialFacts
          rows={[
            ["USD accounting amount", financialMoney(value.usd_amount_cents)],
            [
              "Reference KHR per USD",
              financialLabel(value.reference_rate_khr_per_usd),
            ],
            ["Reference source", financialLabel(value.source_reference)],
            [
              "Reference applicable at",
              financialTimestamp(value.applicable_at),
            ],
            ["Rate source", financialLabel(value.rate_source)],
            ["Fixed markup", "0.5%"],
            [
              "Rounded system KHR per USD",
              typeof value.system_rate_khr_per_usd === "number" ||
              typeof value.system_rate_khr_per_usd === "bigint"
                ? value.system_rate_khr_per_usd.toString()
                : "Unavailable",
            ],
            ["Exact unrounded KHR", financialLabel(value.unrounded_khr_amount)],
            [
              "Provisional payable KHR",
              financialMoney(value.payable_khr_amount, "KHR"),
            ],
            ...(value.fallback_reason === null
              ? []
              : [
                  [
                    "Manual fallback evidence",
                    financialLabel(value.fallback_reason),
                  ] as const,
                ]),
          ]}
        />
      )}
      <p>
        This is a provisional calculation. Payment confirmation selects the
        authoritative rate. Actual channel amounts and conversion evidence
        remain separate original facts.
      </p>
    </section>
  );
}
export function FinancialPaymentWorkspace({
  scope,
  capabilities,
  services,
  commands,
  onDirtyStateChange,
  onOpenReceipt,
}: FinancialWorkspaceProps & { onOpenReceipt?: (receiptId: string) => void }) {
  const canRead = capabilities["payments.read"],
    canRecord = capabilities["payments.record"];
  const [mode, setMode] = useState<"read" | "record">(
    canRead ? "read" : "record",
  );
  type DraftField =
    | keyof typeof initial
    | "currency"
    | "payerScope"
    | "manual"
    | "channel";
  const draft = useFinancialDraft<DraftField>(scope, onDirtyStateChange);
  const [fields, setFields] = useState(initial);
  const [currency, setCurrency] = useState<"USD" | "KHR">("USD");
  const [payerScope, setPayerScope] = useState<
    "NORMAL_CUSTOMER" | "THIRD_PARTY_IDENTIFIED"
  >("NORMAL_CUSTOMER");
  const [channel, setChannel] = useState(false),
    [manual, setManual] = useState(false),
    [manualAllowed, setManualAllowed] = useState(false);
  const [methods, setMethods] = useState<FinancialObject[] | null>(null),
    [preview, setPreview] = useState<FinancialObject | null>(null);
  const [filters, setFilters] = useState({ payer: "", method: "", status: "" }),
    [selected, setSelected] = useState("");
  const [list, setList, listCurrent] = useFinancialSnapshot<FinancialReply>(
      commands.revision,
    ),
    [detail, setDetail, detailCurrent] = useFinancialSnapshot<FinancialReply>(
      commands.revision,
    );
  const task = useFinancialTask(scope, commands.revision),
    { cancel } = task,
    { invalidate, revision } = commands;
  useEffect(() => {
    cancel();
    setPreview(null);
    setManualAllowed(false);
  }, [revision, cancel]);
  function edit(values: Partial<typeof initial>, rateChanged = false) {
    for (const [name, value] of Object.entries(values)) {
      const key = name as keyof typeof initial;
      if (value !== fields[key] && (mode === "record" || draft.hasEdits([key])))
        draft.edited(key);
    }
    cancel();
    invalidate();
    setPreview(null);
    setFields((old) => ({ ...old, ...values }));
    if (rateChanged) {
      setManualAllowed(false);
    }
  }
  function choose(value: "read" | "record") {
    cancel();
    invalidate();
    setMode(value);
    setPreview(null);
    setDetail(null);
    setList(null);
    setManualAllowed(false);
  }
  async function acceptedMethods(s: FinancialScope) {
    const rows: FinancialObject[] = [];
    let next: string | null = null;
    for (let page = 0; page < 1000; page++) {
      const reply = await services.references.read(s, {
        operation: "methods",
        limit: 100,
        ...(next ? { cursor: next } : {}),
      });
      if (s.signal.aborted)
        throw new FinancialInputError("The Payment workspace changed.");
      if (!Array.isArray(reply.data))
        throw new FinancialInputError(
          "Accepted Payment methods are unavailable.",
        );
      rows.push(...reply.data.map(financialObject));
      stringifyFinancialJson(rows, FINANCIAL_UI_CONTEXT_BYTES);
      next = reply.page?.nextCursor ?? null;
      if (next === null) return rows;
    }
    throw new FinancialInputError(
      "The complete accepted-method list is unavailable. Refresh before recording a Payment.",
    );
  }
  function loadMethods() {
    if (!canRecord) return;
    setMethods(null);
    void task.run(acceptedMethods, setMethods);
  }
  function manualReference(): FinancialObject {
    return {
      reference_rate_khr_per_usd: parseFinancialRate(fields.manualRate),
      source_reference: fields.manualSource,
      applicable_at: financialLocalInstant(fields.manualAt),
      fallback_reason: fields.manualReason,
    };
  }
  function previewOrReview(confirmation: boolean) {
    if (!canRecord || (confirmation && !commands.ready)) return;
    const preparation = confirmation ? commands.beginReview() : null;
    if (!confirmation) invalidate();
    setPreview(null);
    void task.run(
      async (s) => {
        const freshMethods = confirmation ? await acceptedMethods(s) : null;
        let selectedPreview: FinancialObject | null = null,
          reference: FinancialObject | null = null;
        if (currency === "KHR") {
          const usd = parseFinancialAmount(fields.usd);
          const automatic = financialObject(
            (
              await services.references.read(s, {
                operation: "khrPreview",
                usd_amount_cents: usd,
              })
            ).data,
          );
          if (manual) {
            if (
              !manualAllowed ||
              !capabilities["exchange_rates.manage"] ||
              automatic.status !== "source_unavailable" ||
              automatic.manual_fallback_allowed !== true
            )
              throw new FinancialInputError(
                "Manual fallback is not supported by the current automatic-source check. Turn it off and reload the provisional preview.",
              );
            reference = manualReference();
            selectedPreview = financialObject(
              (
                await services.references.read(s, {
                  operation: "khrPreview",
                  usd_amount_cents: usd,
                  manual_reference: reference,
                })
              ).data,
            );
          } else selectedPreview = automatic;
        }
        let request: FinancialCommandRequest | null = null;
        if (
          confirmation &&
          (currency === "USD" || selectedPreview?.status === "available")
        ) {
          const method = financialId(fields.method);
          if (!freshMethods?.some((row) => row.id === method))
            throw new FinancialInputError(
              "The selected Payment method is no longer accepted. Reload methods and choose an accepted method.",
            );
          const amount = parseFinancialAmount(fields.amount, currency);
          const body: FinancialObject = {
            payer_customer_id: financialId(fields.payer),
            payment_method_id: method,
            received_at: financialLocalInstant(fields.receivedAt),
            evidence_reference: fields.evidence,
            amount: { currency, minor_units: amount },
            payment_scope_kind: payerScope,
          };
          if (fields.lease) body.lease_id = financialId(fields.lease);
          if (fields.invoice)
            body.identified_invoice_id = financialId(fields.invoice);
          if (fields.charge)
            body.identified_late_payment_charge_id = financialId(fields.charge);
          if (fields.memo) body.payer_intent_memo = fields.memo;
          if (fields.channelReference)
            body.channel_transaction_reference = fields.channelReference;
          if (currency === "KHR") {
            body.usd_accounting_amount = {
              currency: "USD",
              minor_units: parseFinancialAmount(fields.usd),
            };
            if (reference) body.manual_reference = reference;
            if (channel) {
              if (
                !fields.channelReference ||
                (!fields.channelAmount &&
                  !fields.channelUsd &&
                  !fields.channelRate)
              )
                throw new FinancialInputError(
                  "Actual channel evidence needs its transaction reference, confirmation time and at least one original amount or rate fact.",
                );
              const original: FinancialObject = {
                transaction_reference: fields.channelReference,
                confirmed_at: financialLocalInstant(fields.channelConfirmedAt),
              };
              if (fields.channelAmount) {
                const actual = parseFinancialAmount(
                  fields.channelAmount,
                  "KHR",
                );
                if (actual !== amount)
                  throw new FinancialInputError(
                    "The channel's actual KHR amount must match the original received KHR.",
                  );
                original.actual_currency = "KHR";
                original.actual_amount_minor = actual;
              }
              if (fields.channelUsd)
                original.actual_usd_value_cents = parseFinancialAmount(
                  fields.channelUsd,
                );
              if (fields.channelRate)
                original.actual_rate_khr_per_usd = parseFinancialRate(
                  fields.channelRate,
                );
              body.channel_evidence = original;
            }
          }
          request = { operation: "paymentRecord", target: {}, body };
        }
        return { request, selectedPreview, freshMethods };
      },
      ({ request, selectedPreview, freshMethods }) => {
        if (preparation && !preparation.isCurrent()) return;
        setPreview(selectedPreview);
        if (freshMethods) setMethods(freshMethods);
        if (!manual)
          setManualAllowed(
            selectedPreview?.status === "source_unavailable" &&
              selectedPreview.manual_fallback_allowed === true &&
              capabilities["exchange_rates.manage"],
          );
        if (request)
          preparation?.review(request, {
            onRecorded: draft.captureRecorded([
              "payer",
              "method",
              "receivedAt",
              "evidence",
              "amount",
              "currency",
              "payerScope",
              "lease",
              "invoice",
              "charge",
              "memo",
              "channelReference",
              ...(currency === "KHR"
                ? (["usd", "manual", "channel"] as const)
                : []),
              ...(currency === "KHR" && manual
                ? ([
                    "manualRate",
                    "manualSource",
                    "manualAt",
                    "manualReason",
                  ] as const)
                : []),
              ...(currency === "KHR" && channel
                ? ([
                    "channelConfirmedAt",
                    "channelAmount",
                    "channelUsd",
                    "channelRate",
                  ] as const)
                : []),
            ]),
            consequence:
              "Confirm this original incoming Payment and issue its one Receipt. This action does not allocate Payment value, recognize Customer Credit, create a Deposit or settle an Invoice. The server selects and verifies the final exchange rate and any original channel evidence.",
            evidence: (
              <>
                {selectedPreview && (
                  <KhrPreviewEvidence value={selectedPreview} />
                )}
                <p>
                  Accepted method at review:{" "}
                  {financialLabel(
                    freshMethods?.find((row) => row.id === fields.method)
                      ?.display_name,
                  )}
                </p>
              </>
            ),
          });
      },
    );
  }
  function readList(next?: string) {
    if (!canRead) return;
    setList(null);
    setDetail(null);
    void task.run(
      async (s) =>
        await readFinancialRecord(
          s,
          {
            operation: "paymentList",
            target: {},
            query: {
              limit: 50,
              sort: "-payment_date",
              ...(filters.payer
                ? { customer_id: financialId(filters.payer) }
                : {}),
              ...(filters.method
                ? { payment_method_id: financialId(filters.method) }
                : {}),
              ...(filters.status ? { status: filters.status } : {}),
              ...(next ? { cursor: next } : {}),
            },
          },
          services.transport,
        ),
      setList,
    );
  }
  function readDetail(id = selected) {
    if (!canRead) return;
    setDetail(null);
    void task.run(
      async (s) =>
        await readFinancialRecord(
          s,
          { operation: "paymentGet", target: { id: financialId(id) } },
          services.transport,
        ),
      (reply) => {
        setDetail(reply);
        setSelected(id);
      },
    );
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mode === "read") readDetail();
    else previewOrReview(true);
  }
  const receiptId = originalFinancialReceiptId(detail?.data);
  if (!canRead && !canRecord) return null;
  return (
    <section aria-label="Payment workspace">
      <h3>Payments</h3>
      <nav aria-label="Payment actions">
        {canRead && (
          <button
            type="button"
            disabled={commands.busy}
            aria-pressed={mode === "read"}
            onClick={() => {
              choose("read");
            }}
          >
            View Payments
          </button>
        )}
        {canRecord && (
          <button
            type="button"
            disabled={commands.busy}
            aria-pressed={mode === "record"}
            onClick={() => {
              choose("record");
            }}
          >
            Record Payment
          </button>
        )}
      </nav>
      <form onSubmit={submit}>
        <fieldset disabled={commands.busy}>
          <legend>
            {mode === "read"
              ? "Find original Payments"
              : "Record original incoming Payment"}
          </legend>
          {mode === "read" ? (
            <>
              <label>
                Payment payer filter
                <input
                  value={filters.payer}
                  onChange={(e) => {
                    cancel();
                    setList(null);
                    setFilters((old) => ({ ...old, payer: e.target.value }));
                  }}
                />
              </label>
              <label>
                Payment method reference filter
                <input
                  value={filters.method}
                  onChange={(e) => {
                    cancel();
                    setList(null);
                    setFilters((old) => ({ ...old, method: e.target.value }));
                  }}
                />
              </label>
              <label>
                Payment status filter
                <select
                  value={filters.status}
                  onChange={(e) => {
                    cancel();
                    setList(null);
                    const value = e.target.value;
                    setFilters((old) => ({
                      ...old,
                      status:
                        value === "RECEIVED" || value === "REVERSED"
                          ? value
                          : "",
                    }));
                  }}
                >
                  <option value="">All Payment statuses</option>
                  <option value="RECEIVED">Received</option>
                  <option value="REVERSED">Reversed</option>
                </select>
              </label>
              <button
                type="button"
                disabled={task.busy}
                onClick={() => {
                  readList();
                }}
              >
                Load Payment list
              </button>
              <label>
                Payment reference
                <input
                  required
                  value={selected}
                  onChange={(e) => {
                    cancel();
                    setDetail(null);
                    setSelected(e.target.value);
                  }}
                />
              </label>
              <button type="submit" disabled={task.busy}>
                Load Payment record
              </button>
            </>
          ) : (
            <>
              <label>
                Payer Customer reference
                <input
                  required
                  value={fields.payer}
                  onChange={(e) => {
                    edit({ payer: e.target.value });
                  }}
                />
              </label>
              <a href="#customer-management-heading">
                Open Customer management
              </a>
              <button type="button" disabled={task.busy} onClick={loadMethods}>
                Load accepted Payment methods
              </button>
              {methods?.length === 0 && (
                <p>No accepted Payment methods are available.</p>
              )}
              <label>
                Accepted Payment method
                <select
                  required
                  value={fields.method}
                  onChange={(e) => {
                    edit({ method: e.target.value });
                  }}
                >
                  <option value="">Select an accepted method</option>
                  {methods?.map((method) => (
                    <option
                      key={financialId(method.id)}
                      value={financialId(method.id)}
                    >
                      {financialLabel(method.display_name)} ·{" "}
                      {financialLabel(method.code)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Payment received at (Asia/Phnom_Penh, +07:00)
                <input
                  required
                  type="datetime-local"
                  step="0.001"
                  value={fields.receivedAt}
                  onChange={(e) => {
                    edit({ receivedAt: e.target.value });
                  }}
                />
              </label>
              <label>
                Payment evidence reference
                <input
                  required
                  maxLength={500}
                  value={fields.evidence}
                  onChange={(e) => {
                    edit({ evidence: e.target.value });
                  }}
                />
              </label>
              <label>
                Incoming currency
                <select
                  value={currency}
                  onChange={(e) => {
                    const value = e.target.value === "KHR" ? "KHR" : "USD";
                    if (value === currency) return;
                    if (!draft.confirmDiscard(["amount", "usd"])) return;
                    edit({ amount: "", usd: "" }, true);
                    draft.clear(["amount", "usd"]);
                    draft.edited("currency");
                    setCurrency(value);
                  }}
                >
                  <option value="USD">USD</option>
                  <option value="KHR">KHR</option>
                </select>
              </label>
              <label>
                Original received amount ({currency})
                <input
                  required
                  inputMode="decimal"
                  value={fields.amount}
                  onChange={(e) => {
                    edit({ amount: e.target.value });
                  }}
                />
              </label>
              {currency === "KHR" && (
                <>
                  <label>
                    Explicit USD accounting amount
                    <input
                      required
                      inputMode="decimal"
                      value={fields.usd}
                      onChange={(e) => {
                        edit({ usd: e.target.value }, true);
                      }}
                    />
                  </label>
                  <button
                    type="button"
                    disabled={task.busy}
                    onClick={() => {
                      previewOrReview(false);
                    }}
                  >
                    Load provisional KHR preview
                  </button>
                  {(manualAllowed || manual) && (
                    <label>
                      <input
                        type="checkbox"
                        checked={manual}
                        onChange={(e) => {
                          edit({});
                          draft.edited("manual");
                          setManual(e.target.checked);
                        }}
                      />
                      Use authorized manual fallback
                    </label>
                  )}
                  {manual && manualAllowed && (
                    <fieldset>
                      <legend>Approved-source outage evidence</legend>
                      <label>
                        Manual reference KHR per USD
                        <input
                          required
                          inputMode="decimal"
                          value={fields.manualRate}
                          onChange={(e) => {
                            edit({ manualRate: e.target.value });
                          }}
                        />
                      </label>
                      <label>
                        Manual source reference
                        <input
                          required
                          maxLength={500}
                          value={fields.manualSource}
                          onChange={(e) => {
                            edit({ manualSource: e.target.value });
                          }}
                        />
                      </label>
                      <label>
                        Manual reference applicable at (Asia/Phnom_Penh, +07:00)
                        <input
                          required
                          type="datetime-local"
                          step="0.001"
                          value={fields.manualAt}
                          onChange={(e) => {
                            edit({ manualAt: e.target.value });
                          }}
                        />
                      </label>
                      <label>
                        Manual fallback reason
                        <input
                          required
                          maxLength={500}
                          value={fields.manualReason}
                          onChange={(e) => {
                            edit({ manualReason: e.target.value });
                          }}
                        />
                      </label>
                    </fieldset>
                  )}
                  <label>
                    <input
                      type="checkbox"
                      checked={channel}
                      onChange={(e) => {
                        edit({});
                        draft.edited("channel");
                        setChannel(e.target.checked);
                      }}
                    />
                    Include actual channel confirmation evidence
                  </label>
                  {channel && (
                    <fieldset>
                      <legend>Original actual channel evidence</legend>
                      <label>
                        Channel confirmed at (Asia/Phnom_Penh, +07:00)
                        <input
                          required
                          type="datetime-local"
                          step="0.001"
                          value={fields.channelConfirmedAt}
                          onChange={(e) => {
                            edit({ channelConfirmedAt: e.target.value });
                          }}
                        />
                      </label>
                      <label>
                        Actual channel KHR amount
                        <input
                          inputMode="numeric"
                          value={fields.channelAmount}
                          onChange={(e) => {
                            edit({ channelAmount: e.target.value });
                          }}
                        />
                      </label>
                      <label>
                        Actual channel USD value
                        <input
                          inputMode="decimal"
                          value={fields.channelUsd}
                          onChange={(e) => {
                            edit({ channelUsd: e.target.value });
                          }}
                        />
                      </label>
                      <label>
                        Actual channel KHR per USD
                        <input
                          inputMode="decimal"
                          value={fields.channelRate}
                          onChange={(e) => {
                            edit({ channelRate: e.target.value });
                          }}
                        />
                      </label>
                    </fieldset>
                  )}
                </>
              )}
              <label>
                Payment payer scope
                <select
                  value={payerScope}
                  onChange={(e) => {
                    edit({});
                    draft.edited("payerScope");
                    setPayerScope(
                      e.target.value === "THIRD_PARTY_IDENTIFIED"
                        ? "THIRD_PARTY_IDENTIFIED"
                        : "NORMAL_CUSTOMER",
                    );
                  }}
                >
                  <option value="NORMAL_CUSTOMER">Customer Payment</option>
                  <option value="THIRD_PARTY_IDENTIFIED">
                    Identified third-party Payment
                  </option>
                </select>
              </label>
              <label>
                Optional Lease reference
                <input
                  value={fields.lease}
                  onChange={(e) => {
                    edit({ lease: e.target.value });
                  }}
                />
              </label>
              <label>
                Identified Invoice reference
                <input
                  value={fields.invoice}
                  onChange={(e) => {
                    edit({ invoice: e.target.value });
                  }}
                />
              </label>
              <label>
                Identified separate Charge reference
                <input
                  value={fields.charge}
                  onChange={(e) => {
                    edit({ charge: e.target.value });
                  }}
                />
              </label>
              <label>
                Payer intent memo
                <textarea
                  maxLength={2000}
                  value={fields.memo}
                  onChange={(e) => {
                    edit({ memo: e.target.value });
                  }}
                />
              </label>
              <label>
                Channel transaction reference
                <input
                  required={currency === "KHR" && channel}
                  maxLength={500}
                  value={fields.channelReference}
                  onChange={(e) => {
                    edit({ channelReference: e.target.value });
                  }}
                />
              </label>
              <button type="submit" disabled={task.busy || !commands.ready}>
                Review incoming Payment
              </button>
            </>
          )}
        </fieldset>
      </form>
      {task.busy && <p role="status">Loading current Payment facts…</p>}
      {task.error && <p role="alert">{task.error}</p>}
      {(!listCurrent || !detailCurrent) && (
        <p role="status">
          Loaded financial facts are out of date after another action. Original
          facts remain below. Reload the record or history for current balances,
          status and complete history.
        </p>
      )}
      {preview && <KhrPreviewEvidence value={preview} />}
      {list && (
        <section aria-label="Payment list page">
          <h4>Payments · newest Payment date first</h4>
          {Array.isArray(list.data) && list.data.length === 0 ? (
            <p>No Payments match these filters on this page.</p>
          ) : (
            <div className="financial-table-scroll">
              <table>
                <caption>Original Payment list page</caption>
                <thead>
                  <tr>
                    <th>Payment / date</th>
                    <th>Payer / method</th>
                    <th className="financial-money">Original received</th>
                    <th className="financial-money">USD accounting value</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {Array.isArray(list.data) &&
                    list.data.map((value) => {
                      const row = financialObject(
                          financialObject(value).payment,
                        ),
                        id = financialId(row.id);
                      return (
                        <tr key={id}>
                          <td>
                            <button
                              type="button"
                              disabled={task.busy || commands.busy}
                              onClick={() => {
                                readDetail(id);
                              }}
                            >
                              {financialLabel(row.payment_number)}
                            </button>
                            <br />
                            {financialLabel(row.payment_date)}
                          </td>
                          <td>
                            {financialLabel(row.payer_customer_id)}
                            <br />
                            {financialLabel(
                              row.payment_method_name_snapshot ??
                                row.payment_method,
                            )}
                          </td>
                          <td className="financial-money">
                            {financialMoney(
                              row.received_amount_minor,
                              row.received_currency === "KHR" ? "KHR" : "USD",
                            )}
                          </td>
                          <td className="financial-money">
                            {financialMoney(row.usd_accounting_value_cents)}
                          </td>
                          <td>
                            {listCurrent
                              ? financialLabel(row.status)
                              : "Reload for current status"}
                          </td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>
          )}
          {listCurrent && list.page && cursor(list.page) && (
            <button
              type="button"
              disabled={task.busy}
              onClick={() => {
                readList(cursor(list.page));
              }}
            >
              Next Payment list page
            </button>
          )}
        </section>
      )}
      {detail && (
        <section aria-label="Selected Payment record">
          <PaymentEvidence
            resource={detail.data}
            showPosition={detailCurrent}
          />
          {onOpenReceipt &&
            !commands.busy &&
            (capabilities["receipts.read"] ||
              capabilities["receipts.reprint"]) &&
            receiptId !== null && (
              <button
                type="button"
                onClick={() => {
                  onOpenReceipt(receiptId);
                }}
              >
                Open original Receipt
              </button>
            )}
          <p>
            Use the separate Allocation, Credit, Refund, Deposit and Receipt
            workspaces for their authorized actions.
          </p>
          <a href="#deposit-management-heading">Open Deposit management</a>
        </section>
      )}
    </section>
  );
}
