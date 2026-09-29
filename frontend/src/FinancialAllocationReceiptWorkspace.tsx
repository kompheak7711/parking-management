import { useEffect, useState, useRef, type FormEvent } from "react";
import {
  financialId,
  financialInteger,
  financialObject,
  type FinancialObject,
} from "./financialContracts";
import type { FinancialReply } from "./financialResponse";
import { FinancialDueSourcePicker } from "./FinancialDueSourcePicker";
import {
  dueAmountText,
  type FinancialDueSelection,
} from "./financialDueSelection";
import {
  replaceDueLineSelection,
  selectedDueLineIntent,
  type FinancialDueLineSelections,
} from "./financialDueWorkspace";
import {
  ActionContextEvidence,
  AllocationRecordEvidence,
  FinancialProposalEvidence,
  PaymentReversalEvidence,
  ReceiptEvidence,
  ReceiptHistoryEvidence,
} from "./FinancialEvidence";
import {
  loadFinancialActionContext,
  loadPaymentReversalContext,
  readFinancialRecord,
  useFinancialTask,
  useFinancialDraft,
  useFinancialSnapshot,
} from "./financialUiContext";
import {
  FinancialInputError,
  financialLabel,
  financialMoney,
  parseFinancialAmount,
  type FinancialCommandRequest,
  type FinancialWorkspaceProps,
  type FinancialReceiptHandoff,
} from "./financialUi";
const modes = [
  ["allocationRead", "View Payment Allocations", "payments.read"],
  ["allocate", "Allocate Payment", "payments.allocate"],
  [
    "allocationReverse",
    "Reverse original Allocation",
    "payments.allocations.reverse",
  ],
  ["paymentReverse", "Reverse original Payment", "payments.reverse"],
  ["receiptRead", "View original Receipt", "receipts.read"],
  ["reprint", "Record Receipt reprint", "receipts.reprint"],
] as const;
type Mode = (typeof modes)[number][0];
type Basis = "PROPOSAL" | "DESIGNATED" | "DIRECT_CHARGE";
const initial = {
  source: "",
  target: "",
  selectedAllocation: "",
  amount: "",
  designation: "",
  reason: "",
  delivery: "",
};
function nextCursor(value: unknown): string | undefined {
  const p = financialObject(value);
  return typeof p.next_cursor === "string" ? p.next_cursor : undefined;
}
export function FinancialAllocationReceiptWorkspace({
  scope,
  capabilities,
  services,
  commands,
  onDirtyStateChange,
  receiptHandoff,
}: FinancialWorkspaceProps & {
  receiptHandoff?: FinancialReceiptHandoff | null;
}) {
  const allowed = modes.filter(([, , grant]) => capabilities[grant]);
  const [mode, setMode] = useState<Mode>(allowed[0]?.[0] ?? "allocationRead");
  const [basis, setBasis] = useState<Basis>("PROPOSAL"),
    [targetKind, setTargetKind] = useState<"INVOICE" | "LATE_PAYMENT_CHARGE">(
      "INVOICE",
    ),
    [receiptByPayment, setReceiptByPayment] = useState(false);
  type DraftField =
    | keyof typeof initial
    | "basis"
    | "targetKind"
    | "receiptByPayment"
    | "lineAmounts";
  const draft = useFinancialDraft<DraftField>(scope, onDirtyStateChange);
  const [fields, setFields] = useState(initial),
    [lineAmounts, setLineAmounts] = useState<Record<string, string>>({}),
    [linePage, setLinePage] = useState(0);
  const [dueSelections, setDueSelections] =
    useState<FinancialDueLineSelections>({});
  const [dueEditor, setDueEditor] = useState<string | null>(null);
  const [context, setContext] = useState<FinancialObject | null>(null),
    [proposal, setProposal] = useState<FinancialObject | null>(null),
    [record, setRecord, recordCurrent] = useFinancialSnapshot<FinancialReply>(
      commands.revision,
    );
  const task = useFinancialTask(scope, commands.revision),
    { cancel } = task,
    { invalidate, revision } = commands;
  useEffect(() => {
    cancel();
    setContext(null);
    setProposal(null);
    setDueEditor(null);
  }, [revision, cancel]);
  const receiptRegion = useRef<HTMLElement>(null);
  const consumedHandoff = useRef<FinancialReceiptHandoff | null>(null);
  const readReceipt = capabilities["receipts.read"],
    reprintReceipt = capabilities["receipts.reprint"];
  const { run } = task;
  useEffect(() => {
    if (!receiptHandoff || consumedHandoff.current === receiptHandoff) return;
    consumedHandoff.current = receiptHandoff;
    const origin = receiptHandoff.scope;
    if (
      origin.actorId !== scope.actorId ||
      origin.propertyId !== scope.propertyId ||
      origin.signal !== scope.signal ||
      origin.signal.aborted ||
      (!readReceipt && !reprintReceipt)
    )
      return;
    if (!draft.confirmDiscard()) return;
    draft.clear();
    cancel();
    invalidate();
    setContext(null);
    setProposal(null);
    setRecord(null);
    setLineAmounts({});
    setDueSelections({});
    setDueEditor(null);
    setLinePage(0);
    setReceiptByPayment(false);
    setMode(readReceipt ? "receiptRead" : "reprint");
    setFields({ ...initial, source: receiptHandoff.receiptId });
    receiptRegion.current?.focus();
    // This explicit handoff reads only through the independently granted Receipt route.
    // Reprinting still requires a separate review and confirmation.
    if (readReceipt)
      void run(
        async (s) =>
          await readFinancialRecord(
            s,
            {
              operation: "receiptGet",
              target: { id: financialId(receiptHandoff.receiptId) },
              query: { limit: 50 },
            },
            services.transport,
          ),
        setRecord,
      );
    else
      void run(
        async (s) =>
          await loadFinancialActionContext(
            s,
            {
              operation: "financialActionContext",
              purpose: "receipt_reprint",
              source_id: financialId(receiptHandoff.receiptId),
            },
            services.references,
          ),
        setContext,
      );
  }, [
    receiptHandoff,
    draft,
    scope,
    readReceipt,
    reprintReceipt,
    cancel,
    invalidate,
    run,
    services,
    setRecord,
  ]);
  function edit(
    values: Partial<typeof initial>,
    sourceChanged = false,
    discarded: DraftField[] = [],
    selections: DraftField[] = [],
  ) {
    const cleared: DraftField[] = [
      ...discarded,
      ...(sourceChanged ? ["lineAmounts" as const] : []),
    ];
    if (!draft.confirmDiscard(cleared)) return false;
    for (const [name, value] of Object.entries(values)) {
      const key = name as keyof typeof initial;
      if (value !== fields[key] && (!readMode || draft.hasEdits([key])))
        draft.edited(key);
    }
    draft.clear(cleared);
    for (const key of selections)
      if (!readMode || draft.hasEdits([key])) draft.edited(key);
    cancel();
    invalidate();
    setProposal(null);
    setFields((old) => ({ ...old, ...values }));
    if (sourceChanged) {
      setContext(null);
      setRecord(null);
      setLineAmounts({});
      setDueSelections({});
      setDueEditor(null);
      setLinePage(0);
    }
    return true;
  }
  function dirtyDueSelection() {
    cancel();
    invalidate();
    setProposal(null);
    draft.edited("lineAmounts");
  }
  function applyDueSelection(line: string, selection: FinancialDueSelection) {
    const next = replaceDueLineSelection(dueSelections, line, selection);
    dirtyDueSelection();
    setDueSelections(next);
    setLineAmounts((old) => ({
      ...old,
      [line]: dueAmountText(selection.amount),
    }));
    setDueEditor(null);
  }
  function choose(value: Mode) {
    if (!edit({}, true)) return;
    setMode(value);
  }
  const readMode = mode === "allocationRead" || mode === "receiptRead";
  function readPage(cursor?: string, allocation = fields.selectedAllocation) {
    if (
      (mode === "allocationRead" && !capabilities["payments.read"]) ||
      (mode === "receiptRead" && !capabilities["receipts.read"]) ||
      !readMode
    )
      return;
    setRecord(null);
    void task.run(
      async (s) =>
        await readFinancialRecord(
          s,
          mode === "allocationRead"
            ? {
                operation: "allocationList",
                target: { id: financialId(fields.source) },
                query: {
                  limit: 50,
                  ...(allocation
                    ? { allocation_id: financialId(allocation) }
                    : {}),
                  ...(cursor ? { cursor } : {}),
                },
              }
            : {
                operation: receiptByPayment ? "paymentReceipt" : "receiptGet",
                target: { id: financialId(fields.source) },
                query: { limit: 50, ...(cursor ? { cursor } : {}) },
              },
          services.transport,
        ),
      (reply) => {
        setRecord(reply);
        if (mode === "allocationRead")
          setFields((old) => ({ ...old, selectedAllocation: allocation }));
      },
    );
  }
  function load(confirmation: boolean, withProposal = false, result = false) {
    const grant = modes.find(([value]) => value === mode)?.[2];
    if (
      dueEditor !== null ||
      !grant ||
      !capabilities[grant] ||
      readMode ||
      (confirmation && !commands.ready)
    )
      return;
    const preparation = confirmation ? commands.beginReview() : null;
    if (!confirmation) invalidate();
    setContext(null);
    setProposal(null);
    void task.run(
      async (s) => {
        const id = financialId(fields.source);
        const data =
          mode === "paymentReverse"
            ? await loadPaymentReversalContext(
                s,
                id,
                result ? "result" : "impact",
                services.references,
              )
            : await loadFinancialActionContext(
                s,
                {
                  operation: "financialActionContext",
                  purpose:
                    mode === "allocate"
                      ? "allocation"
                      : mode === "allocationReverse"
                        ? "allocation_reversal"
                        : "receipt_reprint",
                  source_id: id,
                  ...(mode === "allocate" && basis !== "PROPOSAL"
                    ? {
                        target_kind: targetKind,
                        target_id: financialId(fields.target),
                      }
                    : {}),
                },
                services.references,
              );
        let request: FinancialCommandRequest | null = null,
          returned: FinancialObject | null = null;
        if (mode === "allocate" && (confirmation || withProposal)) {
          const payment = financialObject(
              financialObject(data.payment_resource).payment,
            ),
            available = BigInt(
              financialInteger(
                financialObject(financialObject(data.payment_resource).position)
                  .available_usd_cents,
              ),
            );
          if (payment.status !== "RECEIVED" || available <= 0n)
            throw new FinancialInputError(
              "This Payment has no currently available value for a new Allocation.",
            );
          let intent: FinancialObject;
          if (basis === "PROPOSAL") {
            returned = financialObject(
              (
                await readFinancialRecord(
                  s,
                  { operation: "allocationProposal", target: { id } },
                  services.transport,
                )
              ).data,
            );
            const targets = Array.isArray(returned.targets)
              ? returned.targets.map(financialObject)
              : [];
            const total = targets.reduce(
              (sum, target) =>
                sum +
                BigInt(
                  financialInteger(
                    target.amount_usd_cents,
                    1n,
                    9_000_000_000_000_000n,
                  ),
                ),
              0n,
            );
            if (!targets.length || total <= 0n || total > available) {
              if (confirmation)
                throw new FinancialInputError(
                  "No supported positive batch is available from the current Payment proposal. Reload its original and current facts.",
                );
            }
            intent = { mode: "PROPOSAL", proposal: returned };
          } else {
            const target = financialObject(data.target);
            let amount: bigint, selected: FinancialObject;
            if (targetKind === "INVOICE") {
              const chosen = selectedDueLineIntent(
                data,
                lineAmounts,
                dueSelections,
              );
              amount = chosen.total;
              if (
                !["UNPAID", "PARTIALLY_PAID"].includes(
                  financialLabel(target.status),
                )
              )
                throw new FinancialInputError(
                  "The selected Invoice is no longer payable.",
                );
              selected = {
                invoice_id: financialId(fields.target),
                amount_usd_cents: amount,
                details: chosen.details,
              };
            } else {
              amount = parseFinancialAmount(fields.amount);
              if (
                target.reversed !== false ||
                amount >
                  BigInt(financialInteger(target.remaining_balance_usd_cents))
              )
                throw new FinancialInputError(
                  "The separate Charge no longer supports this amount.",
                );
              selected = {
                late_payment_charge_id: financialId(fields.target),
                amount_usd_cents: amount,
              };
            }
            if (amount > available)
              throw new FinancialInputError(
                "The selected Allocation exceeds the Payment's current available USD.",
              );
            intent =
              basis === "DIRECT_CHARGE"
                ? { mode: basis, ...selected }
                : {
                    mode: "DESIGNATED",
                    targets: [selected],
                    designation_reference: fields.designation,
                  };
          }
          if (targetKind === "INVOICE" && basis === "DESIGNATED") {
            const preview = await readFinancialRecord(
              s,
              {
                operation: "allocationPreview",
                target: { id },
                body: { intent },
              },
              services.transport,
            );
            intent = financialObject(financialObject(preview.data).intent);
          }
          if (confirmation)
            request = {
              operation: "allocationPost",
              target: { id },
              body: { intent },
            };
        } else if (confirmation) {
          if (mode === "allocationReverse") {
            if (financialObject(data.context).reversal !== null)
              throw new FinancialInputError(
                "This original Allocation already has a linked reversal.",
              );
            request = {
              operation: "allocationReverse",
              target: { id },
              body: { reason: fields.reason },
            };
          } else if (mode === "paymentReverse") {
            const payment = financialObject(
              financialObject(data.payment_resource).payment,
            );
            if (payment.status !== "RECEIVED")
              throw new FinancialInputError(
                "This Payment is already reversed; its original and related result history remain available.",
              );
            if (!Array.isArray(data.items) || data.items.length !== 0)
              throw new FinancialInputError(
                "Resolve the active linked Allocations, Credit, Refunds and Deposit actions in their own authorized workflows, then reload the complete impact. Nothing is reversed automatically.",
              );
            request = {
              operation: "paymentReverse",
              target: { id },
              body: { reason: fields.reason, expected_status: "RECEIVED" },
            };
          } else
            request = {
              operation: "receiptReprint",
              target: { id },
              body: {
                reason: fields.reason,
                ...(fields.delivery
                  ? { delivery_reference: fields.delivery }
                  : {}),
              },
            };
        }
        return { data, request, returned };
      },
      ({ data, request, returned }) => {
        if (preparation && !preparation.isCurrent()) return;
        setContext(data);
        setProposal(returned);
        if (request)
          preparation?.review(request, {
            onRecorded: draft.captureRecorded(
              mode === "allocate"
                ? [
                    "source",
                    "basis",
                    ...(basis !== "PROPOSAL"
                      ? ([
                          "targetKind",
                          "target",
                          ...(targetKind === "INVOICE"
                            ? (["lineAmounts"] as const)
                            : (["amount"] as const)),
                        ] as const)
                      : []),
                    ...(basis === "DESIGNATED"
                      ? (["designation"] as const)
                      : []),
                  ]
                : mode === "reprint"
                  ? ["source", "receiptByPayment", "reason", "delivery"]
                  : ["source", "reason"],
            ),
            consequence:
              mode === "allocate"
                ? "Post only the exact displayed Payment Allocation batch or designated target and lines. Payment value, Customer Credit and Deposit value remain separate. Any further eligible batch needs a new explicit proposal and confirmation."
                : mode === "allocationReverse"
                  ? "Reverse this exact original Allocation while preserving its original lines and attribution. The server recomputes current Payment and target balances."
                  : mode === "paymentReverse"
                    ? "Reverse this original Payment only after all downstream dependencies have been explicitly resolved. Preserve its original Receipt and audit history; no related action is reversed automatically."
                    : "Record this reasoned reprint of the same original Receipt identity. This does not create another financial receipt or move money. The printable copy is available after the reprint is confirmed and its original identity is loaded.",
            evidence:
              mode === "paymentReverse" ? (
                <PaymentReversalEvidence value={data} />
              ) : (
                <ActionContextEvidence value={data} />
              ),
          });
      },
    );
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (readMode) readPage();
    else load(true);
  }
  const lines =
      context && Array.isArray(context.items)
        ? context.items
            .map(financialObject)
            .filter((row) => row.kind === "INVOICE_LINE")
        : [],
    page = Math.min(linePage, Math.max(0, Math.ceil(lines.length / 50) - 1));
  const recordData =
    record && !Array.isArray(record.data) ? financialObject(record.data) : null;
  const reprints = recordData?.reprints
    ? financialObject(recordData.reprints)
    : null;
  if (!allowed.length) return null;
  return (
    <section
      id="financial-allocation-receipt-workspace"
      ref={receiptRegion}
      tabIndex={-1}
      aria-label="Allocation, Receipt and Payment reversal workspace"
    >
      <h3>Allocations, Receipts and Payment reversals</h3>
      <nav aria-label="Allocation and Receipt actions">
        {allowed.map(([value, label]) => (
          <button
            type="button"
            key={value}
            disabled={commands.busy}
            aria-pressed={mode === value}
            onClick={() => {
              choose(value);
            }}
          >
            {label}
          </button>
        ))}
      </nav>
      <form onSubmit={submit}>
        <fieldset disabled={commands.busy}>
          <legend>{modes.find(([value]) => value === mode)?.[1]}</legend>
          {mode === "receiptRead" && (
            <label>
              Receipt lookup basis
              <select
                value={receiptByPayment ? "payment" : "receipt"}
                onChange={(e) => {
                  if (
                    !edit(
                      { source: "" },
                      true,
                      ["source"],
                      ["receiptByPayment"],
                    )
                  )
                    return;
                  setReceiptByPayment(e.target.value === "payment");
                }}
              >
                <option value="receipt">Original Receipt reference</option>
                <option value="payment">Original Payment reference</option>
              </select>
            </label>
          )}
          <label>
            {mode === "reprint" || (mode === "receiptRead" && !receiptByPayment)
              ? "Original Receipt reference"
              : mode === "allocationReverse"
                ? "Original Allocation reference"
                : "Source Payment reference"}
            <input
              required
              value={fields.source}
              onChange={(e) => {
                edit({ source: e.target.value }, true);
              }}
            />
          </label>
          {mode === "allocationRead" && (
            <label>
              Optional selected Allocation reference
              <input
                value={fields.selectedAllocation}
                onChange={(e) => {
                  edit({ selectedAllocation: e.target.value }, true);
                }}
              />
            </label>
          )}
          {mode === "allocate" && (
            <>
              <label>
                Allocation attribution
                <select
                  value={basis}
                  onChange={(e) => {
                    const value = e.target.value;
                    if (value === basis) return;
                    if (
                      !edit(
                        {},
                        true,
                        [],
                        [
                          "basis",
                          ...(value === "DIRECT_CHARGE" &&
                          targetKind !== "LATE_PAYMENT_CHARGE"
                            ? (["targetKind"] as const)
                            : []),
                        ],
                      )
                    )
                      return;
                    setBasis(
                      value === "PROPOSAL"
                        ? "PROPOSAL"
                        : value === "DIRECT_CHARGE"
                          ? "DIRECT_CHARGE"
                          : "DESIGNATED",
                    );
                    if (value === "DIRECT_CHARGE")
                      setTargetKind("LATE_PAYMENT_CHARGE");
                  }}
                >
                  <option value="PROPOSAL">Server Payment FIFO proposal</option>
                  <option value="DESIGNATED">
                    Explicit Customer designation
                  </option>
                  <option value="DIRECT_CHARGE">Direct separate Charge</option>
                </select>
              </label>
              {basis !== "PROPOSAL" && (
                <>
                  {basis === "DESIGNATED" && (
                    <label>
                      Designated Allocation target
                      <select
                        value={targetKind}
                        onChange={(e) => {
                          if (
                            !edit(
                              { target: "" },
                              true,
                              ["target"],
                              ["targetKind"],
                            )
                          )
                            return;
                          setTargetKind(
                            e.target.value === "INVOICE"
                              ? "INVOICE"
                              : "LATE_PAYMENT_CHARGE",
                          );
                        }}
                      >
                        <option value="INVOICE">Invoice</option>
                        <option value="LATE_PAYMENT_CHARGE">
                          Separate Late-payment Charge
                        </option>
                      </select>
                    </label>
                  )}
                  <label>
                    Allocation target reference
                    <input
                      required
                      value={fields.target}
                      onChange={(e) => {
                        edit({ target: e.target.value }, true);
                      }}
                    />
                  </label>
                  {targetKind === "LATE_PAYMENT_CHARGE" && (
                    <label>
                      Separate Charge Allocation amount (USD)
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
                  {basis === "DESIGNATED" && (
                    <label>
                      Allocation designation reference
                      <input
                        required
                        maxLength={500}
                        value={fields.designation}
                        onChange={(e) => {
                          edit({ designation: e.target.value });
                        }}
                      />
                    </label>
                  )}
                </>
              )}
              {basis === "PROPOSAL" && (
                <button
                  type="button"
                  disabled={task.busy}
                  onClick={() => {
                    load(false, true);
                  }}
                >
                  Load Payment Allocation proposal
                </button>
              )}
            </>
          )}
          {!readMode && (
            <button
              type="button"
              disabled={task.busy || dueEditor !== null}
              onClick={() => {
                load(false);
              }}
            >
              Load complete original and current context
            </button>
          )}
          {mode === "allocate" &&
            basis === "DESIGNATED" &&
            targetKind === "INVOICE" &&
            (context ? (
              <>
                <div className="financial-table-scroll">
                  <table>
                    <caption>
                      Allocation designated lines · {lines.length} loaded · page{" "}
                      {page + 1}
                    </caption>
                    <thead>
                      <tr>
                        <th>Original line / description</th>
                        <th className="financial-money">Current outstanding</th>
                        <th className="financial-money">Designated USD</th>
                      </tr>
                    </thead>
                    <tbody>
                      {lines.slice(page * 50, page * 50 + 50).map((line) => {
                        const id = financialId(line.id),
                          data = financialObject(line.data);
                        return (
                          <tr key={id}>
                            <td>
                              {financialLabel(data.description)}
                              <br />
                              {id}
                            </td>
                            <td className="financial-money">
                              {financialMoney(data.outstanding_usd_cents)}
                            </td>
                            <td className="financial-money">
                              <label>
                                Allocation USD for line {id}
                                <input
                                  inputMode="decimal"
                                  readOnly={dueSelections[id] !== undefined}
                                  value={lineAmounts[id] ?? ""}
                                  onChange={(e) => {
                                    if (dueSelections[id]) return;
                                    cancel();
                                    invalidate();
                                    const value = e.target.value;
                                    if (value !== (lineAmounts[id] ?? ""))
                                      draft.edited("lineAmounts");
                                    setLineAmounts((old) => ({
                                      ...old,
                                      [id]: value,
                                    }));
                                  }}
                                />
                              </label>
                              <button
                                type="button"
                                disabled={task.busy || dueEditor !== null}
                                onClick={() => {
                                  cancel();
                                  invalidate();
                                  setProposal(null);
                                  setDueEditor(id);
                                }}
                              >
                                Choose dated sources for line {id}
                              </button>
                              {dueSelections[id] && (
                                <>
                                  <p>
                                    {dueSelections[id].parts.length} explicitly
                                    selected dated sources
                                  </p>
                                  <button
                                    type="button"
                                    disabled={task.busy || dueEditor !== null}
                                    onClick={() => {
                                      dirtyDueSelection();
                                      setDueSelections((old) => {
                                        return Object.fromEntries(
                                          Object.entries(old).filter(
                                            ([line]) => line !== id,
                                          ),
                                        );
                                      });
                                    }}
                                  >
                                    Use earliest due order for line {id}
                                  </button>
                                </>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                {lines.length > 50 && (
                  <div className="button-row">
                    <button
                      type="button"
                      disabled={page === 0}
                      onClick={() => {
                        setLinePage(page - 1);
                      }}
                    >
                      Previous Allocation lines
                    </button>
                    <button
                      type="button"
                      disabled={(page + 1) * 50 >= lines.length}
                      onClick={() => {
                        setLinePage(page + 1);
                      }}
                    >
                      Next Allocation lines
                    </button>
                  </div>
                )}
                {dueEditor !== null && (
                  <FinancialDueSourcePicker
                    key={`${scope.actorId}:${scope.propertyId}:${fields.source}:${fields.target}:${dueEditor}:${revision.toString()}`}
                    scope={scope}
                    input={{
                      operation: "financialDueSources",
                      purpose: "allocation",
                      source_id: fields.source,
                      invoice_id: fields.target,
                      invoice_line_id: dueEditor,
                      limit: 50,
                    }}
                    initial={dueSelections[dueEditor]}
                    references={services.references}
                    onDirty={dirtyDueSelection}
                    onApply={(selection) => {
                      applyDueSelection(dueEditor, selection);
                    }}
                    onDiscard={() => {
                      setDueEditor(null);
                    }}
                  />
                )}
              </>
            ) : (
              <p>
                Load complete Invoice lines before entering the explicit
                designation.
              </p>
            ))}
          {!readMode && mode !== "allocate" && (
            <label>
              Allocation, reversal or reprint reason
              <textarea
                required
                maxLength={1000}
                value={fields.reason}
                onChange={(e) => {
                  edit({ reason: e.target.value });
                }}
              />
            </label>
          )}
          {mode === "reprint" && (
            <label>
              Optional Receipt delivery reference
              <input
                maxLength={500}
                value={fields.delivery}
                onChange={(e) => {
                  edit({ delivery: e.target.value });
                }}
              />
            </label>
          )}
          <button
            type="submit"
            disabled={
              task.busy || dueEditor !== null || (!readMode && !commands.ready)
            }
          >
            {readMode
              ? "Load original history page"
              : "Review selected financial action"}
          </button>
        </fieldset>
      </form>
      {task.busy && <p role="status">Loading complete financial context…</p>}
      {task.error && <p role="alert">{task.error}</p>}
      {!recordCurrent && (
        <p role="status">
          Loaded financial facts are out of date after another action. Original
          facts remain below. Reload the record or history for current balances,
          status and complete history.
        </p>
      )}
      {context &&
        (mode === "paymentReverse" ? (
          <>
            <PaymentReversalEvidence value={context} />
            <div className="button-row">
              <a href="#financial-allocation-receipt-workspace">
                Allocation actions
              </a>
              <a href="#financial-credit-workspace">Customer Credit actions</a>
              <a href="#financial-refund-workspace">Refund actions</a>
              <a href="#deposit-management-heading">Deposit actions</a>
              <button
                type="button"
                disabled={task.busy}
                onClick={() => {
                  load(false, false, true);
                }}
              >
                Load complete reversal result
              </button>
            </div>
          </>
        ) : (
          <ActionContextEvidence value={context} />
        ))}
      {proposal && <FinancialProposalEvidence value={proposal} />}
      {record && mode === "allocationRead" && (
        <section aria-label="Original Allocation history page">
          <h4>Original Allocation history page</h4>
          {Array.isArray(record.data) ? (
            record.data.length === 0 ? (
              <p>No Allocations on this page.</p>
            ) : (
              <ul>
                {record.data.map((value) => {
                  const row = financialObject(value),
                    id = financialId(row.id);
                  return (
                    <li key={id}>
                      <button
                        type="button"
                        disabled={task.busy || commands.busy}
                        onClick={() => {
                          readPage(undefined, id);
                        }}
                      >
                        {id} · {financialMoney(row.amount_usd_cents)} ·{" "}
                        {financialLabel(row.target_kind)}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )
          ) : (
            <AllocationRecordEvidence
              resource={record.data}
              showPosition={recordCurrent}
            />
          )}
          {recordCurrent && record.page && nextCursor(record.page) && (
            <button
              type="button"
              disabled={task.busy}
              onClick={() => {
                readPage(nextCursor(record.page));
              }}
            >
              Next Allocation history page
            </button>
          )}
        </section>
      )}
      {recordData && mode === "receiptRead" && (
        <section aria-label="Original Receipt record">
          <ReceiptEvidence resource={recordData} showPosition={recordCurrent} />
          {recordCurrent && reprints && (
            <>
              <ReceiptHistoryEvidence items={reprints.items} />
              {nextCursor(reprints.page) && (
                <button
                  type="button"
                  disabled={task.busy}
                  onClick={() => {
                    readPage(nextCursor(reprints.page));
                  }}
                >
                  Next Receipt reprint page
                </button>
              )}
            </>
          )}
        </section>
      )}
    </section>
  );
}
