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
  CreditApplicationRecordEvidence,
  CreditEvidence,
  CreditHistoryEvidence,
  FinancialProposalEvidence,
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
  financialMoney,
  parseFinancialAmount,
  selectedFinancialLineIntent,
  type FinancialCommandRequest,
  type FinancialWorkspaceProps,
} from "./financialUi";

type Mode = "read" | "recognize" | "apply" | "reverse" | "applicationReverse";
type Target = "INVOICE" | "LATE_PAYMENT_CHARGE";
type Basis = "PROPOSAL" | "DESIGNATED" | "DIRECT_CHARGE";
const modes = [
  ["read", "View Customer Credit", "credits.read"],
  ["recognize", "Recognize Customer Credit", "credits.recognize"],
  ["apply", "Apply Customer Credit", "credits.apply"],
  ["reverse", "Reverse Credit recognition", "credits.reverse"],
  [
    "applicationReverse",
    "Reverse Credit application",
    "credits.applications.reverse",
  ],
] as const;
const initial = {
  customer: "",
  source: "",
  target: "",
  amount: "",
  reason: "",
  authorization: "",
  designation: "",
};
function pageCursor(value: unknown): string | null {
  const p = financialObject(value);
  return typeof p.next_cursor === "string" ? p.next_cursor : null;
}
function sourceAvailable(data: FinancialObject): bigint {
  return BigInt(
    financialInteger(
      financialObject(
        financialObject(financialObject(data.context).credit).position,
      ).available_usd_cents,
    ),
  );
}
function activeCredit(data: FinancialObject): void {
  if (
    financialObject(financialObject(data.payment_resource).payment).status !==
    "RECEIVED"
  )
    throw new FinancialInputError(
      "The original source Payment is reversed. Review its current history before continuing.",
    );
}

export function FinancialCreditWorkspace({
  scope,
  capabilities,
  services,
  commands,
  onDirtyStateChange,
}: FinancialWorkspaceProps) {
  const allowed = modes.filter(([, , grant]) => capabilities[grant]);
  const [mode, setMode] = useState<Mode>(allowed[0]?.[0] ?? "read");
  const [readKind, setReadKind] = useState<"credit" | "application">("credit");
  const [targetKind, setTargetKind] = useState<Target>("INVOICE");
  const [basis, setBasis] = useState<Basis>("PROPOSAL");
  type DraftField =
    | keyof typeof initial
    | "basis"
    | "targetKind"
    | "lineAmounts";
  const draft = useFinancialDraft<DraftField>(scope, onDirtyStateChange);
  const [fields, setFields] = useState(initial);
  const [lineAmounts, setLineAmounts] = useState<Record<string, string>>({});
  const [linePage, setLinePage] = useState(0);
  const [context, setContext] = useState<FinancialObject | null>(null);
  const [proposal, setProposal] = useState<FinancialObject | null>(null);
  const [list, setList, listCurrent] = useFinancialSnapshot<FinancialReply>(
    commands.revision,
  );
  const [detail, setDetail, detailCurrent] =
    useFinancialSnapshot<FinancialReply>(commands.revision);
  const task = useFinancialTask(scope, commands.revision),
    { cancel } = task;
  const { revision, invalidate } = commands;
  useEffect(() => {
    cancel();
    setContext(null);
    setProposal(null);
  }, [revision, cancel]);
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
      if (value !== fields[key] && (mode !== "read" || draft.hasEdits([key])))
        draft.edited(key);
    }
    draft.clear(cleared);
    for (const key of selections)
      if (mode !== "read" || draft.hasEdits([key])) draft.edited(key);
    cancel();
    invalidate();
    setProposal(null);
    setFields((old) => ({ ...old, ...values }));
    if (sourceChanged) {
      setContext(null);
      setDetail(null);
      setList(null);
      setLineAmounts({});
      setLinePage(0);
    }
    return true;
  }
  function choose(value: Mode) {
    if (!edit({}, true)) return;
    setMode(value);
  }
  function chooseTarget(value: Target) {
    if (value === targetKind) return;
    if (!edit({ target: "" }, true, ["target"], ["targetKind", "basis"]))
      return;
    setTargetKind(value);
    setBasis(value === "INVOICE" ? "PROPOSAL" : "DIRECT_CHARGE");
  }
  function readList(cursor?: string) {
    if (!capabilities["credits.read"]) return;
    setList(null);
    setDetail(null);
    void task.run(
      async (s) =>
        await readFinancialRecord(
          s,
          {
            operation: "creditList",
            target: { id: financialId(fields.customer) },
            query: { limit: 50, ...(cursor ? { cursor } : {}) },
          },
          services.transport,
        ),
      setList,
    );
  }
  function readDetail(
    id = fields.source,
    history = false,
    cursor?: string,
    kind = readKind,
  ) {
    if (!capabilities["credits.read"]) return;
    if (id !== fields.source && !draft.confirmDiscard(["source"])) return;
    setDetail(null);
    void task.run(
      async (s) =>
        await readFinancialRecord(
          s,
          kind === "application"
            ? {
                operation: "creditApplication",
                target: { id: financialId(id) },
              }
            : history
              ? {
                  operation: "creditLedger",
                  target: { id: financialId(id) },
                  query: { limit: 50, ...(cursor ? { cursor } : {}) },
                }
              : { operation: "creditGet", target: { id: financialId(id) } },
          services.transport,
        ),
      (reply) => {
        setReadKind(kind);
        setDetail(reply);
        if (id !== fields.source) draft.clear(["source"]);
        setFields((old) => ({ ...old, source: id }));
      },
    );
  }
  function load(confirmation: boolean, withProposal = false) {
    const grant = modes.find(([value]) => value === mode)?.[2];
    if (
      !grant ||
      !capabilities[grant] ||
      mode === "read" ||
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
        const purpose =
          mode === "recognize"
            ? "credit_recognition"
            : mode === "reverse"
              ? "credit_reversal"
              : mode === "applicationReverse"
                ? "credit_application_reversal"
                : "credit_application";
        const data = await loadFinancialActionContext(
          s,
          {
            operation: "financialActionContext",
            purpose,
            source_id: id,
            ...(mode === "apply"
              ? {
                  target_kind: targetKind,
                  target_id: financialId(fields.target),
                }
              : {}),
          },
          services.references,
        );
        let request: FinancialCommandRequest | null = null,
          selectedProposal: FinancialObject | null = null;
        const c = financialObject(data.context);
        if (mode === "apply" && (confirmation || withProposal)) {
          activeCredit(data);
          const target = financialObject(data.target),
            maximum = BigInt(
              financialInteger(
                targetKind === "INVOICE"
                  ? target.outstanding_usd_cents
                  : target.remaining_balance_usd_cents,
              ),
            );
          let amount: bigint;
          let intent: FinancialObject;
          if (targetKind === "INVOICE" && basis === "DESIGNATED") {
            const selected = selectedFinancialLineIntent(data, lineAmounts);
            amount = selected.total;
            intent = {
              mode: "DESIGNATED",
              invoice_id: financialId(fields.target),
              amount_usd_cents: amount,
              details: selected.details,
              designation_reference: fields.designation,
            };
          } else {
            amount = parseFinancialAmount(fields.amount);
            intent = {
              mode: basis,
              late_payment_charge_id: financialId(fields.target),
              amount_usd_cents: amount,
              ...(basis === "DESIGNATED"
                ? { designation_reference: fields.designation }
                : {}),
            };
          }
          if (
            amount > sourceAvailable(data) ||
            amount > maximum ||
            (targetKind === "INVOICE" &&
              !["UNPAID", "PARTIALLY_PAID"].includes(
                financialLabel(target.status),
              )) ||
            (targetKind === "LATE_PAYMENT_CHARGE" && target.reversed !== false)
          )
            throw new FinancialInputError(
              "The selected Credit or target no longer supports this USD amount. Reload its current facts.",
            );
          if (targetKind === "INVOICE" && basis === "PROPOSAL") {
            const reply = await readFinancialRecord(
              s,
              {
                operation: "creditProposal",
                target: { id },
                query: {
                  invoice_id: financialId(fields.target),
                  amount_usd_cents: amount,
                },
              },
              services.transport,
            );
            selectedProposal = financialObject(reply.data);
            // The original requested amount can exceed this returned bounded batch.
            intent = { mode: "PROPOSAL", proposal: selectedProposal };
          }
          if (confirmation)
            request = {
              operation: "creditApply",
              target: { id },
              body: { currency: "USD", intent },
            };
        } else if (confirmation) {
          if (mode === "recognize") {
            activeCredit(data);
            const available = BigInt(
                financialInteger(
                  financialObject(
                    financialObject(data.payment_resource).position,
                  ).available_usd_cents,
                ),
              ),
              amount = parseFinancialAmount(fields.amount);
            if (c.applicable_obligations !== false || amount > available)
              throw new FinancialInputError(
                "Credit recognition requires eligible excess Payment value with no applicable outstanding obligations.",
              );
            request = {
              operation: "creditRecognize",
              target: { id },
              body: {
                currency: "USD",
                amount_usd_cents: amount,
                payer_authorization_reference: fields.authorization,
                reason: fields.reason,
              },
            };
          } else if (mode === "reverse") {
            activeCredit(data);
            const original = financialObject(financialObject(c.credit).credit);
            if (
              c.reversal !== null ||
              sourceAvailable(data) !==
                BigInt(financialInteger(original.recognized_usd_cents))
            )
              throw new FinancialInputError(
                "Resolve active Credit applications and net Refunds before reversing this original recognition.",
              );
            request = {
              operation: "creditReverse",
              target: { id },
              body: { reason: fields.reason },
            };
          } else {
            if (c.reversal !== null)
              throw new FinancialInputError(
                "This original Credit application already has a linked reversal.",
              );
            request = {
              operation: "creditApplicationReverse",
              target: { id },
              body: { reason: fields.reason },
            };
          }
        }
        return { data, request, selectedProposal };
      },
      ({ data, request, selectedProposal }) => {
        if (preparation && !preparation.isCurrent()) return;
        setContext(data);
        setProposal(selectedProposal);
        if (request)
          preparation?.review(request, {
            onRecorded: draft.captureRecorded(
              mode === "recognize"
                ? ["source", "amount", "authorization", "reason"]
                : mode === "apply"
                  ? [
                      "source",
                      "target",
                      "targetKind",
                      "basis",
                      ...(targetKind === "INVOICE" && basis === "DESIGNATED"
                        ? (["lineAmounts"] as const)
                        : (["amount"] as const)),
                      ...(basis === "DESIGNATED"
                        ? (["designation"] as const)
                        : []),
                    ]
                  : ["source", "reason"],
            ),
            consequence:
              mode === "recognize"
                ? "Recognize explicitly authorized Customer Credit in USD from the eligible excess Payment. This is separate from Payment Allocation and Deposit value."
                : mode === "apply"
                  ? "Post only the displayed Credit application and its exact returned batch or designated lines. A separate Charge application reduces that Charge only. Further eligible amounts need a new explicit proposal and confirmation."
                  : mode === "reverse"
                    ? "Reverse this original Credit recognition permanently, preserving its history and restoring its eligible source Payment value."
                    : "Reverse this exact original Credit application, restoring eligible Credit and target balances while preserving the application and attribution history.",
            evidence: <ActionContextEvidence value={data} />,
          });
      },
    );
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mode === "read") readDetail();
    else load(true);
  }
  const detailData = detail ? financialObject(detail.data) : null,
    history = detailData?.history ? financialObject(detailData.history) : null;
  const lines =
    context && Array.isArray(context.items)
      ? context.items
          .map(financialObject)
          .filter((item) => item.kind === "INVOICE_LINE")
      : [];
  const page = Math.min(
    linePage,
    Math.max(0, Math.ceil(lines.length / 50) - 1),
  );
  if (!allowed.length) return null;
  return (
    <section
      id="financial-credit-workspace"
      aria-label="Customer Credit workspace"
    >
      <h3>Customer Credit</h3>
      <p>
        Credit is a separate USD balance. Original incoming KHR and
        exchange-rate evidence remain attached to its Payment.
      </p>
      <nav aria-label="Credit actions">
        {allowed.map(([value, label]) => (
          <button
            key={value}
            type="button"
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
          {mode === "read" && (
            <>
              <label>
                Customer reference for Credit list
                <input
                  value={fields.customer}
                  onChange={(e) => {
                    edit({ customer: e.target.value }, true);
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
                Load Customer Credit list
              </button>
              <a href="#customer-management-heading">
                Open Customer management
              </a>
              <label>
                Credit record type
                <select
                  value={readKind}
                  onChange={(e) => {
                    if (!edit({ source: "" }, true, ["source"])) return;
                    setReadKind(
                      e.target.value === "application"
                        ? "application"
                        : "credit",
                    );
                  }}
                >
                  <option value="credit">Credit recognition</option>
                  <option value="application">
                    Original Credit application
                  </option>
                </select>
              </label>
            </>
          )}
          <label>
            {mode === "recognize"
              ? "Source Payment reference"
              : mode === "applicationReverse" ||
                  (mode === "read" && readKind === "application")
                ? "Original Credit application reference"
                : "Credit reference"}
            <input
              required
              value={fields.source}
              onChange={(e) => {
                edit({ source: e.target.value }, true);
              }}
            />
          </label>
          {mode === "apply" && (
            <>
              <label>
                Credit target
                <select
                  value={targetKind}
                  onChange={(e) => {
                    chooseTarget(
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
              <label>
                Target reference
                <input
                  required
                  value={fields.target}
                  onChange={(e) => {
                    edit({ target: e.target.value }, true);
                  }}
                />
              </label>
              <label>
                Credit attribution
                <select
                  value={basis}
                  onChange={(e) => {
                    const value = e.target.value;
                    if (value === basis) return;
                    if (!edit({}, true, [], ["basis"])) return;
                    if (
                      value === "PROPOSAL" ||
                      value === "DESIGNATED" ||
                      value === "DIRECT_CHARGE"
                    )
                      setBasis(value);
                  }}
                >
                  {targetKind === "INVOICE" ? (
                    <option value="PROPOSAL">
                      Server within-Invoice proposal
                    </option>
                  ) : (
                    <option value="DIRECT_CHARGE">
                      Direct separate Charge
                    </option>
                  )}
                  <option value="DESIGNATED">
                    Explicit Customer designation
                  </option>
                </select>
              </label>
              {basis === "DESIGNATED" && (
                <label>
                  Customer designation reference
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
          {(mode === "recognize" ||
            (mode === "apply" &&
              !(basis === "DESIGNATED" && targetKind === "INVOICE"))) && (
            <label>
              Credit amount (USD)
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
          {mode === "recognize" && (
            <label>
              Payer authorization reference
              <input
                required
                maxLength={500}
                value={fields.authorization}
                onChange={(e) => {
                  edit({ authorization: e.target.value });
                }}
              />
            </label>
          )}
          {mode !== "read" && (
            <button
              type="button"
              disabled={task.busy}
              onClick={() => {
                load(false);
              }}
            >
              Load current Credit context
            </button>
          )}
          {mode === "apply" && basis === "PROPOSAL" && (
            <button
              type="button"
              disabled={task.busy}
              onClick={() => {
                load(false, true);
              }}
            >
              Load Credit proposal
            </button>
          )}
          {mode === "apply" &&
            basis === "DESIGNATED" &&
            targetKind === "INVOICE" && (
              <>
                {context ? (
                  <>
                    <div className="financial-table-scroll">
                      <table>
                        <caption>
                          Designated Invoice lines · {lines.length} loaded ·
                          page {page + 1}
                        </caption>
                        <thead>
                          <tr>
                            <th>Line / description</th>
                            <th className="financial-money">
                              Current outstanding USD
                            </th>
                            <th className="financial-money">Designated USD</th>
                          </tr>
                        </thead>
                        <tbody>
                          {lines
                            .slice(page * 50, page * 50 + 50)
                            .map((line) => {
                              const data = financialObject(line.data),
                                id = financialId(line.id);
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
                                      Designated USD for line {id}
                                      <input
                                        inputMode="decimal"
                                        value={lineAmounts[id] ?? ""}
                                        onChange={(e) => {
                                          cancel();
                                          invalidate();
                                          setProposal(null);
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
                          Previous designation lines
                        </button>
                        <button
                          type="button"
                          disabled={(page + 1) * 50 >= lines.length}
                          onClick={() => {
                            setLinePage(page + 1);
                          }}
                        >
                          Next designation lines
                        </button>
                      </div>
                    )}
                  </>
                ) : (
                  <p>
                    Load the complete target context before designating its line
                    amounts.
                  </p>
                )}
              </>
            )}
          {mode !== "read" && mode !== "apply" && (
            <label>
              Credit reason
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
          <button
            type="submit"
            disabled={task.busy || (mode !== "read" && !commands.ready)}
          >
            {mode === "read" ? "Load Credit record" : "Review Credit action"}
          </button>
        </fieldset>
      </form>
      {task.busy && <p role="status">Loading complete Credit facts…</p>}
      {task.error && <p role="alert">{task.error}</p>}
      {(!listCurrent || !detailCurrent) && (
        <p role="status">
          Loaded financial facts are out of date after another action. Original
          facts remain below. Reload the record or history for current balances,
          status and complete history.
        </p>
      )}
      {context && <ActionContextEvidence value={context} />}
      {proposal && <FinancialProposalEvidence value={proposal} />}
      {list && (
        <section aria-label="Customer Credit list page">
          <h4>Customer Credit list page</h4>
          {Array.isArray(list.data) && list.data.length === 0 ? (
            <p>No Customer Credit on this page.</p>
          ) : (
            <ul>
              {Array.isArray(list.data) &&
                list.data.map((row) => {
                  const credit = financialObject(financialObject(row).credit),
                    id = financialId(credit.id);
                  return (
                    <li key={id}>
                      <button
                        type="button"
                        disabled={task.busy || commands.busy}
                        onClick={() => {
                          readDetail(id, false, undefined, "credit");
                        }}
                      >
                        {id} · originally{" "}
                        {financialMoney(credit.recognized_usd_cents)}
                      </button>
                    </li>
                  );
                })}
            </ul>
          )}
          {listCurrent && list.page && pageCursor(list.page) && (
            <button
              type="button"
              disabled={task.busy}
              onClick={() => {
                readList(pageCursor(list.page) ?? undefined);
              }}
            >
              Next Credit list page
            </button>
          )}
        </section>
      )}
      {detailData && (
        <section aria-label="Selected Credit record">
          {readKind === "application" ? (
            <CreditApplicationRecordEvidence
              resource={detailData}
              showPosition={detailCurrent}
            />
          ) : (
            <>
              <CreditEvidence
                resource={detailData}
                showPosition={detailCurrent}
              />
              <button
                type="button"
                disabled={task.busy}
                onClick={() => {
                  readDetail(fields.source, true);
                }}
              >
                Load Credit event history
              </button>
              {detailCurrent && history && (
                <>
                  <CreditHistoryEvidence items={history.items} />
                  {pageCursor(history.page) && (
                    <button
                      type="button"
                      disabled={task.busy}
                      onClick={() => {
                        readDetail(
                          fields.source,
                          true,
                          pageCursor(history.page) ?? undefined,
                        );
                      }}
                    >
                      Next Credit event page
                    </button>
                  )}
                </>
              )}
            </>
          )}
        </section>
      )}
    </section>
  );
}
