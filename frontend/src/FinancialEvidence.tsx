import { Fragment, useEffect, useState, type ReactNode } from "react";
import { ExactJsonNumber } from "./financialJson";
import {
  financialObject,
  type FinancialObject,
  type FinancialCommandOperation,
} from "./financialContracts";
import type { FinancialReply } from "./financialResponse";
import {
  financialLabel,
  financialMoney,
  financialTimestamp,
} from "./financialUi";

function record(value: unknown): FinancialObject {
  try {
    return financialObject(value);
  } catch {
    return {};
  }
}
function optional(value: unknown): string {
  return value === null ? "Not recorded" : financialLabel(value);
}
function exact(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "bigint") return value.toString();
  if (typeof value === "number" && Number.isSafeInteger(value))
    return value.toString();
  if (value instanceof ExactJsonNumber) return value.literal;
  return value === null ? "Not recorded" : "Unavailable";
}
function bool(value: unknown): string {
  return value === true ? "Yes" : value === false ? "No" : "Unavailable";
}
function money(value: unknown): string {
  return value === null ? "Not recorded" : financialMoney(value);
}
function originalMoney(value: unknown, currency: unknown): string {
  return currency === "USD" || currency === "KHR"
    ? financialMoney(value, currency)
    : "Unavailable";
}

export function FinancialFacts({
  rows,
}: {
  rows: readonly (readonly [string, ReactNode])[];
}) {
  return (
    <dl className="financial-facts">
      {rows.map(([label, value]) => (
        <Fragment key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </Fragment>
      ))}
    </dl>
  );
}

export function ExchangeRateEvidence({ value }: { value: unknown }) {
  if (value === null || value === undefined) return null;
  const row = record(value);
  return (
    <section aria-label="Original exchange-rate evidence">
      <h4>Original exchange-rate evidence</h4>
      <FinancialFacts
        rows={[
          ["Rate record reference", optional(row.id ?? row.record_id)],
          ...(row.rate_source === undefined
            ? []
            : [["Original rate source", optional(row.rate_source)] as const]),
          ...(row.reference_rate_khr_per_usd === undefined
            ? []
            : [
                [
                  "Reference KHR per USD",
                  exact(row.reference_rate_khr_per_usd),
                ] as const,
              ]),
          ["System KHR per USD", exact(row.system_rate_khr_per_usd)],
          ...(row.markup_basis_points === undefined
            ? []
            : [
                [
                  "Fixed markup",
                  row.markup_basis_points === 50 ? "0.5%" : "Unavailable",
                ] as const,
              ]),
          ...(row.applicable_at === undefined
            ? []
            : [
                [
                  "Original rate applicable at",
                  financialTimestamp(row.applicable_at),
                ] as const,
              ]),
          ...(row.source_reference === undefined
            ? []
            : [
                [
                  "Original rate source reference",
                  optional(row.source_reference),
                ] as const,
              ]),
          ...(row.fallback_reason === undefined
            ? []
            : [
                [
                  "Original fallback evidence",
                  optional(row.fallback_reason),
                ] as const,
              ]),
          [
            "Actual channel KHR amount",
            row.channel_actual_amount_minor === null
              ? "Not recorded"
              : financialMoney(row.channel_actual_amount_minor, "KHR"),
          ],
          [
            "Actual channel USD value",
            money(row.channel_actual_usd_value_cents),
          ],
          [
            "Actual channel KHR per USD",
            exact(row.channel_actual_rate_khr_per_usd),
          ],
          ...(row.channel_confirmed_at === undefined
            ? []
            : [
                [
                  "Channel confirmation time",
                  row.channel_confirmed_at === null
                    ? "Not recorded"
                    : financialTimestamp(row.channel_confirmed_at),
                ] as const,
              ]),
        ]}
      />
      <p>
        These are original incoming Payment facts. They do not select a rate for
        a Refund.
      </p>
    </section>
  );
}

export function PaymentEvidence({
  resource,
  showPosition = true,
}: {
  resource: unknown;
  showPosition?: boolean;
}) {
  const row = record(resource),
    payment = record(row.payment),
    position = record(row.position),
    dispositions = record(position.dispositions),
    reversal = record(row.reversal);
  return (
    <>
      <section aria-label="Original payment facts">
        <h4>Original payment facts</h4>
        <FinancialFacts
          rows={[
            ["Payment number", financialLabel(payment.payment_number)],
            ["Payment reference", financialLabel(payment.id)],
            [
              "Payer Customer reference",
              financialLabel(payment.payer_customer_id),
            ],
            [
              "Original method",
              financialLabel(
                payment.payment_method_name_snapshot ?? payment.payment_method,
              ),
            ],
            [
              "Original received amount",
              originalMoney(
                payment.received_amount_minor,
                payment.received_currency,
              ),
            ],
            [
              "Original USD accounting value",
              money(payment.usd_accounting_value_cents),
            ],
            ["Payment date", financialLabel(payment.payment_date)],
            ...(payment.confirmed_at === undefined
              ? []
              : [
                  [
                    "Original confirmation time",
                    financialTimestamp(payment.confirmed_at),
                  ] as const,
                ]),
            ...(payment.confirmed_by === undefined
              ? []
              : [
                  [
                    "Original confirming actor",
                    financialLabel(payment.confirmed_by),
                  ] as const,
                ]),
            ...(payment.payment_scope_kind === undefined
              ? []
              : [
                  [
                    "Original payer scope",
                    financialLabel(payment.payment_scope_kind),
                  ] as const,
                ]),
            ...(payment.lease_id === undefined
              ? []
              : [
                  [
                    "Linked Lease reference",
                    optional(payment.lease_id),
                  ] as const,
                ]),
            ...(payment.identified_invoice_id === undefined
              ? []
              : [
                  [
                    "Identified Invoice reference",
                    optional(payment.identified_invoice_id),
                  ] as const,
                ]),
            ...(payment.identified_late_payment_charge_id === undefined
              ? []
              : [
                  [
                    "Identified separate Charge reference",
                    optional(payment.identified_late_payment_charge_id),
                  ] as const,
                ]),
            ...(payment.payer_intent_memo === undefined
              ? []
              : [
                  [
                    "Original payer intent",
                    optional(payment.payer_intent_memo),
                  ] as const,
                ]),
            ...(payment.channel_transaction_reference === undefined
              ? []
              : [
                  [
                    "Original channel reference",
                    optional(payment.channel_transaction_reference),
                  ] as const,
                ]),
          ]}
        />
      </section>
      <ExchangeRateEvidence
        value={row.exchange_rate ?? row.exchange_rate_record ?? row.fx}
      />
      {showPosition && (
        <section aria-label="Current payment position">
          <h4>Current payment position</h4>
          <FinancialFacts
            rows={[
              ["Current Payment status", financialLabel(payment.status)],
              ["Allocated USD", money(dispositions.allocation_usd_cents)],
              ["Directed to Deposits", money(dispositions.deposit_usd_cents)],
              ["Recognized as Credit", money(dispositions.credit_usd_cents)],
              ["Refunded USD", money(dispositions.refund_usd_cents)],
              [
                "Available unallocated USD",
                money(position.available_usd_cents),
              ],
            ]}
          />
          <p>
            Unallocated Payment value is separate from recognized Customer
            Credit.
          </p>
        </section>
      )}
      {row.reversal !== null && row.reversal !== undefined && (
        <section aria-label="Recorded Payment reversal">
          <h4>Recorded Payment reversal</h4>
          <FinancialFacts
            rows={[
              ["Reversal reference", financialLabel(reversal.id)],
              ["Reversal time", financialTimestamp(reversal.occurred_at)],
              ["Reversal reason", financialLabel(reversal.reason)],
              ["Reversing actor", financialLabel(reversal.actor_id)],
            ]}
          />
        </section>
      )}
    </>
  );
}

export function ReceiptIdentityEvidence({ value }: { value: unknown }) {
  const receipt = record(value),
    identity = record(receipt.identity_snapshot);
  return (
    <section aria-label="Original Receipt identity">
      <h4>Original Receipt identity</h4>
      <FinancialFacts
        rows={[
          ["Original Receipt number", financialLabel(receipt.receipt_number)],
          ["Original Receipt reference", financialLabel(receipt.id)],
          ["Original payer name", financialLabel(identity.payer_legal_name)],
          [
            "Original payer Customer reference",
            financialLabel(receipt.payer_customer_id),
          ],
          ["Original Payment reference", financialLabel(receipt.payment_id)],
          ["Original issue time", financialTimestamp(receipt.issued_at)],
          ["Original issuer", financialLabel(receipt.issued_by)],
        ]}
      />
      <p>Reprinting preserves this identity and its historical payer name.</p>
    </section>
  );
}

export function ReceiptEvidence({ resource }: { resource: unknown }) {
  const row = record(resource),
    position = record(row.financial_position);
  return (
    <>
      <ReceiptIdentityEvidence value={row.receipt} />
      <PaymentEvidence resource={row} showPosition={false} />
      <section aria-label="Current Receipt-linked Payment context">
        <h4>Current Receipt-linked Payment context</h4>
        <FinancialFacts
          rows={[
            [
              "Current Payment status",
              financialLabel(position.status ?? record(row.payment).status),
            ],
            ["Allocated USD", money(position.allocated_usd_cents)],
            [
              "Directed to Deposits",
              money(position.deposit_directed_usd_cents),
            ],
            ["Available unallocated USD", money(position.available_usd_cents)],
          ]}
        />
        <p>
          Current balances are separate from the original Receipt. This view
          does not claim a complete breakdown of other dispositions.
        </p>
      </section>
    </>
  );
}

export function CreditEvidence({ resource }: { resource: unknown }) {
  const row = record(resource),
    credit = record(row.credit),
    position = record(row.position),
    source = record(row.source_payment);
  return (
    <>
      <section aria-label="Original Credit recognition">
        <h4>Original Credit recognition</h4>
        <FinancialFacts
          rows={[
            ["Credit reference", financialLabel(credit.id)],
            ["Customer reference", financialLabel(credit.customer_id)],
            [
              "Source Payment reference",
              financialLabel(credit.source_payment_id),
            ],
            ["Original recognized USD", money(credit.recognized_usd_cents)],
            [
              "Payer authorization evidence",
              financialLabel(credit.customer_authorization_reference),
            ],
            ["Recognition time", financialTimestamp(credit.recognized_at)],
            ["Recognizing actor", financialLabel(credit.recognized_by)],
            ["Recognition reason", financialLabel(credit.reason)],
            [
              "Original source received amount",
              originalMoney(
                source.received_amount_minor,
                source.received_currency,
              ),
            ],
          ]}
        />
      </section>
      <ExchangeRateEvidence value={row.exchange_rate} />
      <section aria-label="Current Credit position">
        <h4>Current Credit position</h4>
        <FinancialFacts
          rows={[
            [
              "Recognized USD",
              money(
                position.recognized_usd_cents ?? credit.recognized_usd_cents,
              ),
            ],
            ...(row.position === undefined
              ? []
              : [
                  ["Applied USD", money(position.applied_usd_cents)] as const,
                  ["Refunded USD", money(position.refunded_usd_cents)] as const,
                  [
                    "Reversed recognition USD",
                    money(position.reversed_usd_cents),
                  ] as const,
                ]),
            [
              "Available Credit USD",
              money(position.available_usd_cents ?? row.available_usd_cents),
            ],
          ]}
        />
        <p>
          Credit applications are separate from Payment Allocations and Deposit
          receipts.
        </p>
      </section>
    </>
  );
}

export function RefundEvidence({ resource }: { resource: unknown }) {
  const row = record(resource),
    refund = record(row.refund),
    source = record(row.source);
  const legacy = typeof refund.source_lifecycle_event_id === "string";
  return (
    <>
      <section aria-label="Original completed Refund">
        <h4>Original completed Refund</h4>
        <FinancialFacts
          rows={[
            ["Refund number", financialLabel(refund.refund_number)],
            ["Refund reference", financialLabel(refund.id)],
            [
              "Recipient Customer reference",
              financialLabel(refund.recipient_customer_id),
            ],
            ["Original paid USD", money(refund.refund_amount_minor)],
            ["Refund currency", financialLabel(refund.refund_currency)],
            ["Source kind", financialLabel(source.type)],
            ["Source reference", financialLabel(source.id)],
            ["Processing time", financialTimestamp(refund.processed_at)],
            ["Processing actor", financialLabel(refund.processed_by)],
            ["Original Refund reason", financialLabel(refund.reason)],
            [
              "Original authorization",
              financialLabel(refund.authorization_reference),
            ],
          ]}
        />
      </section>
      <section aria-label="Current Refund value">
        <h4>Current Refund value</h4>
        <FinancialFacts
          rows={[["Current net Refund USD", money(row.net_refund_usd_cents)]]}
        />
        <p>
          The original payout remains recorded when later verified returns
          change its net value.
        </p>
        {legacy && (
          <p>
            This retained Reservation Refund uses its coordinated Reservation
            outcome workflow. Null historical correction fields are not proof of
            a returned payment.
          </p>
        )}
      </section>
      {row.source_payment !== undefined && row.source_payment !== null && (
        <PaymentEvidence
          resource={{
            payment: row.source_payment,
            exchange_rate: row.source_exchange_rate ?? null,
          }}
          showPosition={false}
        />
      )}
      {row.pet_refund_review !== undefined &&
        row.pet_refund_review !== null && (
          <FinancialFacts
            rows={[
              [
                "Original Pet review reference",
                financialLabel(record(row.pet_refund_review).id),
              ],
              [
                "Original Pet Deposit reference",
                financialLabel(record(row.pet_refund_review).pet_deposit_id),
              ],
              [
                "Pet obligations resolved at review",
                bool(
                  record(row.pet_refund_review).all_pet_obligations_resolved,
                ),
              ],
              [
                "Pet obligations reviewed USD",
                money(
                  record(row.pet_refund_review).obligations_reviewed_usd_cents,
                ),
              ],
              [
                "Pet review time",
                financialTimestamp(record(row.pet_refund_review).reviewed_at),
              ],
            ]}
          />
        )}
    </>
  );
}

export function RefundCorrectionEvidence({
  value,
  title = "Original Refund correction",
}: {
  value: unknown;
  title?: string;
}) {
  const row = record(value);
  if (value === null || value === undefined) return null;
  const legacy =
    row.verified_return_currency === null &&
    row.source_balance_effect_original_minor === null;
  return (
    <section aria-label={title}>
      <h4>{title}</h4>
      <FinancialFacts
        rows={[
          ["Correction reference", financialLabel(row.id)],
          ["Correction kind", financialLabel(row.correction_kind)],
          ["Original Refund reference", financialLabel(row.refund_id)],
          ["Recorded correction time", financialTimestamp(row.occurred_at)],
          ["Correcting actor", financialLabel(row.actor_id)],
          ["Correction reason", financialLabel(row.reason)],
          ["Correction evidence", financialLabel(row.evidence_reference)],
          ["Previous net Refund USD", money(row.previous_net_refund_usd_cents)],
          [
            "Resulting net Refund USD",
            money(row.resulting_net_refund_usd_cents),
          ],
          [
            "Source balance effect USD",
            money(row.source_balance_effect_usd_cents),
          ],
          [
            "Verified returned USD",
            row.verified_return_currency === "USD"
              ? money(row.verified_return_amount_minor)
              : "Not recorded",
          ],
          [
            "Verified return time",
            row.verified_returned_at === null
              ? "Not recorded"
              : financialTimestamp(row.verified_returned_at),
          ],
          ["Return method reference", optional(row.return_method_reference)],
          [
            "Linked original correction reference",
            optional(row.reverses_correction_id),
          ],
          [
            "Recorded authorization",
            financialLabel(row.authorization_reference),
          ],
        ]}
      />
      {legacy && (
        <p>
          Retained lifecycle correction: no independent return amount, time or
          method is inferred.
        </p>
      )}
    </section>
  );
}

export function TargetEvidence({
  target: value,
  items = [],
}: {
  target: unknown;
  items?: unknown;
}) {
  const target = record(value);
  const rows = Array.isArray(items) ? items.map(record) : [];
  const [page, setPage] = useState(0);
  useEffect(() => {
    setPage(0);
  }, [target.id]);
  const currentPage = Math.min(
    page,
    Math.max(0, Math.ceil(rows.length / 50) - 1),
  );
  const start = currentPage * 50;
  if (value === null || value === undefined) return null;
  if (target.kind !== "INVOICE" && target.kind !== "LATE_PAYMENT_CHARGE")
    return <p>Selected target evidence is unavailable.</p>;
  const invoice = target.kind === "INVOICE";
  return (
    <section
      aria-label={
        invoice ? "Selected Invoice facts" : "Selected separate Charge facts"
      }
    >
      <h4>
        {invoice ? "Selected Invoice facts" : "Selected separate Charge facts"}
      </h4>
      <FinancialFacts
        rows={
          invoice
            ? [
                ["Invoice reference", financialLabel(target.id)],
                ["Invoice number", financialLabel(target.invoice_number)],
                ["Current Invoice status", financialLabel(target.status)],
                [
                  "Target Customer reference",
                  financialLabel(target.customer_id),
                ],
                [
                  "Original Invoice total",
                  money(target.original_total_usd_cents),
                ],
                [
                  "Adjusted Invoice obligation",
                  money(target.adjusted_total_usd_cents),
                ],
                [
                  "Current Invoice outstanding",
                  money(target.outstanding_usd_cents),
                ],
                ["Complete original line count", exact(target.line_count)],
                ["Due date", financialLabel(target.due_date)],
                [
                  "Original issue time",
                  target.issued_at === null
                    ? "Not issued"
                    : financialTimestamp(target.issued_at),
                ],
              ]
            : [
                ["Charge reference", financialLabel(target.id)],
                [
                  "Source Invoice reference",
                  financialLabel(target.source_invoice_id),
                ],
                ["Original Charge USD", money(target.original_usd_cents)],
                [
                  "Adjusted Charge obligation",
                  money(target.adjusted_obligation_usd_cents),
                ],
                [
                  "Current Charge balance",
                  money(target.remaining_balance_usd_cents),
                ],
                ["Original Charge reversed", bool(target.reversed)],
              ]
        }
      />
      {!invoice && (
        <p>
          This Charge is a separate obligation. Its payment does not settle the
          source Invoice.
        </p>
      )}
      {rows.length > 0 && (
        <>
          <div className="financial-table-scroll">
            <table>
              <caption>
                Selected line evidence: {rows.length} lines loaded; showing{" "}
                {start + 1}–{Math.min(start + 50, rows.length)}
              </caption>
              <thead>
                <tr>
                  <th>Line reference</th>
                  <th>Category / description</th>
                  <th>Original amount</th>
                  <th>Adjusted amount</th>
                  <th>Current outstanding</th>
                  <th>Original attribution / proposal</th>
                </tr>
              </thead>
              <tbody>
                {rows.slice(start, start + 50).map((item) => {
                  const data = record(item.data),
                    isLine = item.kind === "INVOICE_LINE";
                  return (
                    <tr
                      key={`${financialLabel(item.kind)}:${financialLabel(item.id)}`}
                    >
                      <td>
                        Sequence {exact(item.sequence)}
                        <br />
                        {financialLabel(item.id)}
                        {!isLine && (
                          <>
                            <br />
                            Target: {financialLabel(data.target_id)}
                          </>
                        )}
                      </td>
                      <td>
                        {data.category === null &&
                        data.target_kind === "LATE_PAYMENT_CHARGE"
                          ? "Separate Charge"
                          : financialLabel(data.category)}
                        {isLine && (
                          <>
                            <br />
                            {financialLabel(data.description)}
                          </>
                        )}
                      </td>
                      <td>
                        {money(
                          isLine
                            ? data.original_amount_usd_cents
                            : item.kind === "ALLOCATION_LINE"
                              ? data.posted_amount_usd_cents
                              : data.applied_amount_usd_cents,
                        )}
                      </td>
                      <td>
                        {isLine
                          ? money(data.adjusted_amount_usd_cents)
                          : "Original selected event"}
                      </td>
                      <td>
                        {money(
                          isLine
                            ? data.outstanding_usd_cents
                            : data.current_outstanding_usd_cents,
                        )}
                      </td>
                      <td>
                        {isLine ? (
                          "Current Invoice line"
                        ) : (
                          <>
                            {financialLabel(data.attribution_basis)}
                            <br />
                            Proposed: {money(data.proposed_amount_usd_cents)}
                          </>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {rows.length > 50 && (
            <div className="button-row">
              <button
                type="button"
                disabled={currentPage === 0}
                onClick={() => {
                  setPage(currentPage - 1);
                }}
              >
                Previous evidence lines
              </button>
              <button
                type="button"
                disabled={start + 50 >= rows.length}
                onClick={() => {
                  setPage(currentPage + 1);
                }}
              >
                Next evidence lines
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}

export function OriginalApplicationEvidence({
  value,
  allocation,
}: {
  value: unknown;
  allocation: boolean;
}) {
  const row = record(value);
  return (
    <section
      aria-label={
        allocation ? "Original Allocation" : "Original Credit application"
      }
    >
      <h4>
        {allocation ? "Original Allocation" : "Original Credit application"}
      </h4>
      <FinancialFacts
        rows={[
          ["Original event reference", financialLabel(row.id)],
          ["Original selected amount", money(row.amount_usd_cents)],
          [
            "Original source reference",
            financialLabel(
              allocation ? row.payment_id : row.customer_credit_id,
            ),
          ],
          ["Original target kind", financialLabel(row.target_kind)],
          ["Original target reference", financialLabel(row.target_id)],
          [
            "Original event time",
            financialTimestamp(allocation ? row.posted_at : row.occurred_at),
          ],
          [
            "Original actor",
            financialLabel(allocation ? row.posted_by : row.actor_id),
          ],
          [
            "Original authorization",
            financialLabel(row.authorization_reference),
          ],
          [
            "Original within-target attribution",
            financialLabel(row.within_invoice_basis),
          ],
          [
            "Original designation evidence",
            optional(row.customer_designation_reference),
          ],
          [
            "Original proposal time",
            row.proposal_generated_at === null
              ? "Not recorded"
              : financialTimestamp(row.proposal_generated_at),
          ],
          ...(allocation
            ? [
                [
                  "Original between-Invoice attribution",
                  financialLabel(row.between_invoice_basis),
                ] as const,
                [
                  "Original FIFO sequence",
                  exact(row.between_invoice_sequence),
                ] as const,
                [
                  "Selected Invoice number at posting",
                  optional(row.selected_invoice_number_snapshot),
                ] as const,
              ]
            : []),
          ...(allocation
            ? [
                [
                  "Selected due date at posting",
                  optional(row.selected_invoice_due_date),
                ] as const,
                [
                  "Selected issue time at posting",
                  row.selected_invoice_issued_at === null
                    ? "Not recorded"
                    : financialTimestamp(row.selected_invoice_issued_at),
                ] as const,
                [
                  "Original proposal batch reference",
                  optional(row.proposal_batch_id),
                ] as const,
              ]
            : []),
        ]}
      />
      <p>
        This selected original is distinct from current aggregate balances,
        which may include other events.
      </p>
    </section>
  );
}

export function LinkedReversalEvidence({ value }: { value: unknown }) {
  if (value === null || value === undefined)
    return <p>No linked reversal is recorded for this selected original.</p>;
  const row = record(value);
  return (
    <section aria-label="Linked reversal">
      <h4>Linked reversal</h4>
      <FinancialFacts
        rows={[
          ["Linked reversal reference", financialLabel(row.id)],
          ["Recorded reversal time", financialTimestamp(row.occurred_at)],
          ["Reversal reason", financialLabel(row.reason)],
          ["Reversing actor", financialLabel(row.actor_id)],
        ]}
      />
    </section>
  );
}

export function ActionContextEvidence({ value }: { value: unknown }) {
  const row = record(value),
    context = record(row.context),
    deposit = record(context.deposit_source);
  return (
    <>
      {row.payment_resource !== null && row.payment_resource !== undefined && (
        <PaymentEvidence resource={row.payment_resource} />
      )}
      {context.receipt !== undefined && (
        <ReceiptIdentityEvidence value={context.receipt} />
      )}
      {context.credit !== undefined && (
        <CreditEvidence resource={context.credit} />
      )}
      {context.refund !== undefined && (
        <RefundEvidence resource={context.refund} />
      )}
      {context.deposit_source !== null &&
        context.deposit_source !== undefined && (
          <section aria-label="Original Deposit source">
            <h4>Original Deposit source</h4>
            <FinancialFacts
              rows={[
                ["Deposit reference", financialLabel(deposit.id)],
                ["Deposit type", financialLabel(deposit.deposit_type)],
                ["Current held USD", money(deposit.held_usd_cents)],
              ]}
            />
          </section>
        )}
      {context.allocation !== undefined && (
        <OriginalApplicationEvidence value={context.allocation} allocation />
      )}
      {context.application !== undefined && (
        <OriginalApplicationEvidence
          value={context.application}
          allocation={false}
        />
      )}
      {context.correction !== undefined && (
        <RefundCorrectionEvidence value={context.correction} />
      )}
      {context.reversal !== undefined &&
        (row.purpose === "refund_correction_reversal" ? (
          <RefundCorrectionEvidence
            value={context.reversal}
            title="Linked correction reversal"
          />
        ) : (
          <LinkedReversalEvidence value={context.reversal} />
        ))}
      {row.purpose === "credit_recognition" && (
        <FinancialFacts
          rows={[
            [
              "Applicable outstanding obligations",
              bool(context.applicable_obligations),
            ],
          ]}
        />
      )}
      <TargetEvidence target={row.target} items={row.items} />
    </>
  );
}

export function RefundSourceEvidence({ value }: { value: unknown }) {
  const source = record(value),
    evidence = record(source.receipt_evidence);
  return (
    <section aria-label="Selected Refund source">
      <h4>Selected Refund source</h4>
      <FinancialFacts
        rows={[
          ["Source type", financialLabel(source.source_type)],
          ["Source reference", financialLabel(source.source_id)],
          [
            "Recipient Customer reference",
            financialLabel(source.recipient_customer_id),
          ],
          ["Refund currency", financialLabel(source.refund_currency)],
          ["Server eligible", bool(source.eligible)],
          ["Current maximum refundable USD", money(source.available_usd_cents)],
        ]}
      />
      {source.source_type === "PET_DEPOSIT" ? (
        <>
          <FinancialFacts
            rows={[
              [
                "Qualifying Pet review reference",
                financialLabel(source.pet_refund_review_id),
              ],
              [
                "Pet departure reference",
                financialLabel(source.pet_departure_id),
              ],
              [
                "Pet approval reference",
                financialLabel(source.pet_approval_id),
              ],
              ["Lease reference", financialLabel(source.lease_id)],
              ["Qualified at", financialTimestamp(source.qualified_at)],
            ]}
          />
          <a href="#deposit-management-heading">
            Open Deposit management for Pet qualification
          </a>
        </>
      ) : (
        <>
          <PaymentEvidence
            resource={{
              payment: source.source_payment ?? null,
              exchange_rate: source.source_exchange_rate ?? null,
            }}
            showPosition={false}
          />
          <FinancialFacts
            rows={[
              [
                "Original receipt evidence",
                optional(evidence.evidence_reference),
              ],
              [
                "Original received time",
                evidence.received_at === null
                  ? "Not recorded"
                  : financialTimestamp(evidence.received_at),
              ],
            ]}
          />
        </>
      )}
      <p>
        Eligibility and the final amount are rechecked by the server. Incoming
        KHR and exchange-rate facts remain audit evidence; this payout is USD.
      </p>
    </section>
  );
}

interface DisplayCommand {
  operation: FinancialCommandOperation;
  target: Readonly<Record<string, string>>;
  body: FinancialObject;
}
function IntentLines({ value }: { value: unknown }) {
  const rows = Array.isArray(value) ? value.map(record) : [];
  return rows.length ? (
    <div className="financial-table-scroll">
      <table>
        <caption>Exact selected line amounts</caption>
        <thead>
          <tr>
            <th>Invoice line reference</th>
            <th>Category / basis</th>
            <th>Current outstanding</th>
            <th>Selected USD</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((line, index) => (
            <tr
              key={`${financialLabel(line.invoice_line_id)}:${index.toString()}`}
            >
              <td>{financialLabel(line.invoice_line_id)}</td>
              <td>
                {line.category === undefined
                  ? "Explicit designation"
                  : financialLabel(line.category)}
                {line.attribution_basis !== undefined && (
                  <> · {financialLabel(line.attribution_basis)}</>
                )}
              </td>
              <td>
                {line.outstanding_usd_cents === undefined
                  ? "See complete source context"
                  : money(line.outstanding_usd_cents)}
              </td>
              <td>{money(line.amount_usd_cents)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ) : null;
}
export function FinancialProposalEvidence({ value }: { value: unknown }) {
  const proposal = record(value),
    credit = proposal.credit_id !== undefined;
  const targets = Array.isArray(proposal.targets)
    ? proposal.targets.map(record)
    : [];
  return (
    <section
      aria-label={
        credit ? "Credit application proposal" : "Payment Allocation proposal"
      }
    >
      <h4>
        {credit ? "Credit application proposal" : "Payment Allocation proposal"}
      </h4>
      <FinancialFacts
        rows={[
          [
            credit ? "Credit reference" : "Payment reference",
            financialLabel(credit ? proposal.credit_id : proposal.payment_id),
          ],
          ["Generated at", financialTimestamp(proposal.generated_at)],
          [
            "Available source USD at proposal",
            money(proposal.available_usd_cents),
          ],
          ["Server ordering policy", financialLabel(proposal.policy)],
          [
            "Continuation",
            proposal.continuation_status === "MORE_ELIGIBLE"
              ? "Another explicit batch may remain"
              : proposal.continuation_status === "COMPLETE"
                ? "This proposal is complete"
                : "Unavailable",
          ],
          ...(credit
            ? [
                [
                  "Selected Invoice reference",
                  financialLabel(proposal.invoice_id),
                ] as const,
                [
                  "Requested USD",
                  money(proposal.requested_amount_usd_cents),
                ] as const,
                ["This batch USD", money(proposal.amount_usd_cents)] as const,
                [
                  "Remaining requested USD",
                  money(proposal.remaining_requested_usd_cents),
                ] as const,
                [
                  "Invoice version at proposal",
                  exact(proposal.invoice_version),
                ] as const,
              ]
            : [
                [
                  "Proposal batch reference",
                  financialLabel(proposal.proposal_batch_id),
                ] as const,
                [
                  "Payment scope at proposal",
                  financialLabel(proposal.payment_scope),
                ] as const,
                [
                  "Original designation reference",
                  optional(proposal.designation_reference),
                ] as const,
                [
                  "Unallocated after this batch",
                  money(proposal.unallocated_after_usd_cents),
                ] as const,
              ]),
        ]}
      />
      {credit ? (
        <IntentLines value={proposal.details} />
      ) : targets.length ? (
        targets.map((target) => (
          <section
            key={financialLabel(target.invoice_id)}
            aria-label={`Proposed Invoice ${financialLabel(target.invoice_number)}`}
          >
            <h5>{financialLabel(target.invoice_number)}</h5>
            <FinancialFacts
              rows={[
                ["Invoice reference", financialLabel(target.invoice_id)],
                [
                  "Target Customer reference",
                  financialLabel(target.target_customer_id),
                ],
                ["FIFO sequence", exact(target.sequence)],
                ["Due date", financialLabel(target.due_date)],
                ["Original issue time", financialTimestamp(target.issued_at)],
                ["Invoice version at proposal", exact(target.version)],
                [
                  "Target Customer reference",
                  financialLabel(target.target_customer_id),
                ],
                ["This target USD", money(target.amount_usd_cents)],
              ]}
            />
            <IntentLines value={target.details} />
          </section>
        ))
      ) : (
        <p>No eligible targets were returned.</p>
      )}
      <p>
        Confirmation posts only the displayed batch. Any remaining eligible
        amount requires a fresh proposal and a separate explicit confirmation.
      </p>
    </section>
  );
}
function IntentEvidence({
  value,
  credit,
}: {
  value: unknown;
  credit: boolean;
}) {
  const intent = record(value);
  if (intent.mode === "PROPOSAL")
    return <FinancialProposalEvidence value={intent.proposal} />;
  if (intent.mode === "DIRECT_CHARGE")
    return (
      <FinancialFacts
        rows={[
          ["Attribution", "Direct payment of a separate Charge"],
          [
            "Separate Charge reference",
            financialLabel(intent.late_payment_charge_id),
          ],
          ["Selected Charge USD", money(intent.amount_usd_cents)],
        ]}
      />
    );
  const targets = credit
    ? [intent]
    : Array.isArray(intent.targets)
      ? intent.targets.map(record)
      : [];
  return (
    <section aria-label="Explicit Customer designation">
      <h4>Explicit Customer designation</h4>
      <FinancialFacts
        rows={[
          [
            "Designation evidence",
            financialLabel(intent.designation_reference),
          ],
        ]}
      />
      {targets.map((target, index) => (
        <div key={index}>
          <FinancialFacts
            rows={[
              [
                target.invoice_id
                  ? "Designated Invoice reference"
                  : "Designated separate Charge reference",
                financialLabel(
                  target.invoice_id ?? target.late_payment_charge_id,
                ),
              ],
              ["Designated USD", money(target.amount_usd_cents)],
            ]}
          />
          <IntentLines value={target.details} />
        </div>
      ))}
    </section>
  );
}

export function FinancialCommandEvidence({
  request,
}: {
  request: DisplayCommand;
}) {
  const { operation, target, body } = request;
  const facts: (readonly [string, ReactNode])[] = [];
  switch (operation) {
    case "paymentRecord": {
      const amount = record(body.amount),
        usd = record(body.usd_accounting_amount),
        manual = record(body.manual_reference),
        channel = record(body.channel_evidence);
      facts.push(
        ["Payer Customer reference", financialLabel(body.payer_customer_id)],
        ["Selected method reference", financialLabel(body.payment_method_id)],
        ["Received amount", originalMoney(amount.minor_units, amount.currency)],
        [
          "USD accounting amount",
          money(
            amount.currency === "USD" ? amount.minor_units : usd.minor_units,
          ),
        ],
        ["Received at", financialTimestamp(body.received_at)],
        ["Receipt evidence reference", financialLabel(body.evidence_reference)],
      );
      if (body.payment_scope_kind !== undefined)
        facts.push(["Payer scope", financialLabel(body.payment_scope_kind)]);
      for (const [key, label] of [
        ["lease_id", "Lease reference"],
        ["identified_invoice_id", "Identified Invoice reference"],
        [
          "identified_late_payment_charge_id",
          "Identified separate Charge reference",
        ],
        ["payer_intent_memo", "Payer intent"],
        ["channel_transaction_reference", "Channel transaction reference"],
      ] as const)
        if (body[key] !== undefined && body[key] !== null)
          facts.push([label, financialLabel(body[key])]);
      if (body.manual_reference)
        facts.push(
          [
            "Manual reference KHR per USD",
            exact(manual.reference_rate_khr_per_usd),
          ],
          [
            "Manual rate source reference",
            financialLabel(manual.source_reference),
          ],
          [
            "Manual rate applicable at",
            financialTimestamp(manual.applicable_at),
          ],
          ["Manual fallback reason", financialLabel(manual.fallback_reason)],
        );
      if (body.channel_evidence) {
        facts.push(
          [
            "Actual channel reference",
            financialLabel(channel.transaction_reference),
          ],
          [
            "Actual channel confirmation time",
            financialTimestamp(channel.confirmed_at),
          ],
        );
        if (channel.actual_amount_minor != null)
          facts.push([
            "Actual channel KHR",
            originalMoney(channel.actual_amount_minor, "KHR"),
          ]);
        if (channel.actual_usd_value_cents != null)
          facts.push([
            "Actual channel USD",
            money(channel.actual_usd_value_cents),
          ]);
        if (channel.actual_rate_khr_per_usd != null)
          facts.push([
            "Actual channel KHR per USD",
            exact(channel.actual_rate_khr_per_usd),
          ]);
      }
      break;
    }
    case "allocationPost":
    case "creditApply":
      facts.push([
        operation === "allocationPost"
          ? "Source Payment reference"
          : "Source Credit reference",
        financialLabel(target.id),
      ]);
      break;
    case "allocationReverse":
      facts.push(["Original Allocation reference", financialLabel(target.id)]);
      break;
    case "paymentReverse":
      facts.push(
        ["Original Payment reference", financialLabel(target.id)],
        ["Expected original status", financialLabel(body.expected_status)],
      );
      break;
    case "receiptReprint":
      facts.push(["Original Receipt reference", financialLabel(target.id)]);
      if (body.delivery_reference != null)
        facts.push([
          "Delivery reference",
          financialLabel(body.delivery_reference),
        ]);
      break;
    case "creditRecognize":
      facts.push(
        ["Source Payment reference", financialLabel(target.id)],
        ["Credit to recognize (USD)", money(body.amount_usd_cents)],
        [
          "Payer authorization reference",
          financialLabel(body.payer_authorization_reference),
        ],
      );
      break;
    case "creditReverse":
      facts.push(["Original Credit reference", financialLabel(target.id)]);
      break;
    case "creditApplicationReverse":
      facts.push([
        "Original Credit application reference",
        financialLabel(target.id),
      ]);
      break;
    case "refundCreate":
      facts.push(
        ["Refund source type", financialLabel(body.source_type)],
        ["Refund source reference", financialLabel(body.source_id)],
        ["Completed payout (USD)", money(body.amount_usd_cents)],
      );
      if (body.pet_refund_review_id)
        facts.push([
          "Qualifying Pet review reference",
          financialLabel(body.pet_refund_review_id),
        ]);
      break;
    case "refundReturn":
      facts.push(
        ["Original Refund reference", financialLabel(target.id)],
        ["Demonstrated returned USD", money(body.returned_amount_minor)],
        ["Verified return time", financialTimestamp(body.returned_at)],
        [
          "Actual return method reference",
          financialLabel(body.return_method_reference),
        ],
      );
      break;
    case "refundReturnReverse":
      facts.push(
        ["Original Refund reference", financialLabel(target.id)],
        [
          "Exact return correction to reverse",
          financialLabel(target.correctionId),
        ],
      );
      break;
  }
  if (body.evidence_reference !== undefined && operation !== "paymentRecord")
    facts.push(["Evidence reference", financialLabel(body.evidence_reference)]);
  if (body.reason !== undefined)
    facts.push(["Reason", financialLabel(body.reason)]);
  return (
    <section aria-label="Exact action to confirm">
      <h4>Exact action to confirm</h4>
      <FinancialFacts rows={facts} />
      {(operation === "allocationPost" || operation === "creditApply") && (
        <IntentEvidence
          value={body.intent}
          credit={operation === "creditApply"}
        />
      )}
    </section>
  );
}

export function FinancialOutcomeEvidence({
  operation,
  reply,
}: {
  operation: FinancialCommandOperation;
  reply: FinancialReply;
}) {
  const row = record(reply.data),
    receipt = record(row.receipt);
  const corrections = record(row.corrections);
  return (
    <section aria-label="Confirmed financial result">
      <h4>Confirmed financial result</h4>
      <FinancialFacts rows={[["Confirmation reference", reply.requestId]]} />
      {operation === "paymentRecord" && (
        <>
          <PaymentEvidence
            resource={row}
            showPosition={row.position !== undefined}
          />
          <FinancialFacts
            rows={[
              ["Original Receipt reference", financialLabel(receipt.id)],
              [
                "Original Receipt number",
                financialLabel(receipt.receipt_number),
              ],
              ["Receipt issued at", financialTimestamp(receipt.issued_at)],
            ]}
          />
        </>
      )}
      {(operation === "allocationPost" ||
        operation === "allocationReverse" ||
        operation === "paymentReverse") && (
        <>
          <FinancialFacts
            rows={[
              ["Original Payment reference", financialLabel(row.payment_id)],
              ...(row.available_usd_cents === undefined
                ? []
                : [
                    [
                      "Available Payment USD at confirmation",
                      money(row.available_usd_cents),
                    ] as const,
                  ]),
              ...(row.allocation_id === undefined
                ? []
                : [
                    [
                      "Original Allocation reference",
                      financialLabel(row.allocation_id),
                    ] as const,
                  ]),
              ...(row.reversal_id === undefined
                ? []
                : [
                    [
                      "Recorded reversal reference",
                      financialLabel(row.reversal_id),
                    ] as const,
                  ]),
              ...(row.status === undefined
                ? []
                : [
                    [
                      "Recorded Payment status",
                      financialLabel(row.status),
                    ] as const,
                  ]),
            ]}
          />
          {Array.isArray(row.allocation_ids) && (
            <ul aria-label="Recorded Allocations">
              {row.allocation_ids.map((id) => (
                <li key={financialLabel(id)}>{financialLabel(id)}</li>
              ))}
            </ul>
          )}
        </>
      )}
      {operation === "receiptReprint" && (
        <FinancialFacts
          rows={[
            ["Original Receipt reference", financialLabel(row.receipt_id)],
            ["Original Receipt number", financialLabel(row.receipt_number)],
            [
              "Recorded reprint reference",
              financialLabel(record(row.reprint).id),
            ],
            [
              "Reprint recorded at",
              financialTimestamp(record(row.reprint).reprinted_at),
            ],
            ["Reprint reason", financialLabel(record(row.reprint).reason)],
          ]}
        />
      )}
      {(operation === "creditRecognize" || operation === "creditReverse") && (
        <>
          <CreditEvidence resource={row} />
          <LinkedReversalEvidence value={row.recognition_reversal} />
        </>
      )}
      {(operation === "creditApply" ||
        operation === "creditApplicationReverse") && (
        <CreditApplicationRecordEvidence resource={row} atConfirmation />
      )}
      {(operation === "refundCreate" ||
        operation === "refundReturn" ||
        operation === "refundReturnReverse") && (
        <>
          <RefundEvidence resource={row} />
          {Array.isArray(corrections.items) &&
            corrections.items.map((value) => (
              <RefundCorrectionEvidence
                key={financialLabel(record(value).id)}
                value={value}
              />
            ))}
          {record(corrections.page).next_cursor !== null &&
            record(corrections.page).next_cursor !== undefined && (
              <p>
                This response contains one correction page; further history
                remains available through its authorized record view.
              </p>
            )}
        </>
      )}
      <p>
        This is the server-confirmed result. Later record reads may show newer
        balances.
      </p>
    </section>
  );
}

export function CreditApplicationRecordEvidence({
  resource,
  atConfirmation = false,
}: {
  resource: unknown;
  atConfirmation?: boolean;
}) {
  const row = record(resource),
    application = record(row.application);
  const details = Array.isArray(row.details) ? row.details.map(record) : [];
  return (
    <>
      <OriginalApplicationEvidence
        allocation={false}
        value={{
          ...application,
          target_id:
            application.invoice_id ??
            application.late_payment_charge_id ??
            null,
        }}
      />
      <FinancialFacts
        rows={[
          [
            atConfirmation
              ? "Selected target balance at confirmation"
              : "Current selected target balance",
            money(row.target_balance_usd_cents),
          ],
          [
            atConfirmation
              ? "Selected target status at confirmation"
              : "Current target Invoice status",
            row.target_invoice_status === null
              ? "Separate Charge"
              : financialLabel(row.target_invoice_status),
          ],
        ]}
      />
      <CreditEvidence resource={row.credit_position} />
      <LinkedReversalEvidence value={row.reversal} />
      {details.length > 0 && (
        <div className="financial-table-scroll">
          <table>
            <caption>Original Credit application details</caption>
            <thead>
              <tr>
                <th>Sequence / reference</th>
                <th>Original target</th>
                <th>Original proposed USD</th>
                <th>Original applied USD</th>
                <th>Attribution</th>
              </tr>
            </thead>
            <tbody>
              {details.map((line) => (
                <tr key={financialLabel(line.id)}>
                  <td>
                    {exact(line.detail_sequence)} · {financialLabel(line.id)}
                  </td>
                  <td>
                    {financialLabel(
                      line.invoice_line_id ?? line.late_payment_charge_id,
                    )}
                  </td>
                  <td>{money(line.proposed_amount_usd_cents)}</td>
                  <td>{money(line.applied_amount_usd_cents)}</td>
                  <td>{financialLabel(line.attribution_basis)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
export function CreditHistoryEvidence({ items }: { items: unknown }) {
  const rows = Array.isArray(items) ? items.map(record) : [];
  if (!rows.length) return <p>No Credit events on this page.</p>;
  return (
    <div className="financial-table-scroll">
      <table>
        <caption>Credit event history page</caption>
        <thead>
          <tr>
            <th>Event / reference</th>
            <th>Recorded time</th>
            <th>Effect / available after USD</th>
            <th>Original source / links</th>
            <th>Reason / actor</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((event) => {
            const detail = event;
            return (
              <tr
                key={`${financialLabel(event.event_kind)}:${financialLabel(event.event_id)}`}
              >
                <td>
                  {financialLabel(event.event_kind)}
                  <br />
                  {financialLabel(event.event_id)}
                </td>
                <td>{financialTimestamp(event.occurred_at)}</td>
                <td>
                  {money(event.balance_effect_usd_cents)}
                  <br />
                  {money(event.available_after_usd_cents)}
                </td>
                <td>
                  {financialLabel(detail.source_kind)} ·{" "}
                  {financialLabel(detail.source_id)}
                  {detail.reverses_event_id != null && (
                    <>
                      <br />
                      Reverses: {financialLabel(detail.reverses_event_id)}
                    </>
                  )}
                  {detail.target_id != null && (
                    <>
                      <br />
                      Target: {financialLabel(detail.target_kind)} ·{" "}
                      {financialLabel(detail.target_id)}
                    </>
                  )}
                </td>
                <td>
                  {event.reason_in_source === true
                    ? "Full reason retained in linked source record"
                    : optional(event.reason)}
                  <br />
                  {financialLabel(detail.actor_id)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function PaymentReversalEvidence({ value }: { value: unknown }) {
  const row = record(value),
    items = Array.isArray(row.items) ? row.items.map(record) : [];
  const [page, setPage] = useState(0);
  const identity = `${financialLabel(record(record(row.payment_resource).payment).id)}:${financialLabel(row.view)}:${financialLabel(row.revision)}`;
  useEffect(() => {
    setPage(0);
  }, [identity]);
  const current = Math.min(page, Math.max(0, Math.ceil(items.length / 50) - 1)),
    visible = items.slice(current * 50, current * 50 + 50),
    result = row.view === "result";
  return (
    <section
      aria-label={
        result
          ? "Complete Payment reversal result"
          : "Complete Payment reversal impact"
      }
    >
      <h4>
        {result
          ? "Complete Payment reversal result"
          : "Complete Payment reversal impact"}
      </h4>
      <PaymentEvidence resource={row.payment_resource} />
      <p>
        {items.length} related{" "}
        {result ? "balance records" : "dependency records"} loaded from all
        sequential context pages.{" "}
        {result
          ? "Each category is a separate current server balance."
          : "Parent and line records describe relationships; their amounts overlap and must not be added together. Resolve linked actions explicitly, then reload impact before reversal."}
      </p>
      {!items.length ? (
        <p>
          {result
            ? "No related balance records are present."
            : "No active downstream dependencies are present in this complete impact."}
        </p>
      ) : (
        <>
          <div className="financial-table-scroll">
            <table>
              <caption>
                {result
                  ? "Related balances after reversal"
                  : "Active reversal dependencies"}{" "}
                · showing {current * 50 + 1}–
                {Math.min(current * 50 + 50, items.length)} of {items.length}
              </caption>
              <thead>
                <tr>
                  <th>Record kind / reference</th>
                  <th>
                    {result
                      ? "Current related facts"
                      : "Source and target relationship"}
                  </th>
                  <th>
                    {result
                      ? "Original values / status"
                      : "Original amount / recorded time"}
                  </th>
                </tr>
              </thead>
              <tbody>
                {visible.map((item) => {
                  const data = record(item.data),
                    kind = financialLabel(item.kind);
                  return (
                    <tr key={`${kind}:${financialLabel(item.id)}`}>
                      <td>
                        {kind}
                        <br />
                        {financialLabel(item.id)}
                      </td>
                      {result ? (
                        <>
                          <td>
                            {kind === "INVOICE" ? (
                              <FinancialFacts
                                rows={[
                                  [
                                    "Current outstanding USD",
                                    money(data.outstanding_usd_cents),
                                  ],
                                ]}
                              />
                            ) : kind === "LATE_PAYMENT_CHARGE" ? (
                              <FinancialFacts
                                rows={[
                                  [
                                    "Adjusted Charge USD",
                                    money(data.adjusted_obligation_usd_cents),
                                  ],
                                  [
                                    "Remaining Charge USD",
                                    money(data.remaining_balance_usd_cents),
                                  ],
                                  [
                                    "Source Invoice",
                                    financialLabel(data.source_invoice_id),
                                  ],
                                ]}
                              />
                            ) : kind === "CREDIT" ? (
                              <FinancialFacts
                                rows={[
                                  [
                                    "Applied Credit USD",
                                    money(data.applied_usd_cents),
                                  ],
                                  [
                                    "Net refunded Credit USD",
                                    money(data.refunded_usd_cents),
                                  ],
                                  [
                                    "Reversed Credit USD",
                                    money(data.reversed_usd_cents),
                                  ],
                                  [
                                    "Available Credit USD",
                                    money(data.available_usd_cents),
                                  ],
                                ]}
                              />
                            ) : (
                              <FinancialFacts
                                rows={[
                                  [
                                    "Held Deposit USD",
                                    money(data.held_usd_cents),
                                  ],
                                  [
                                    "Disposed Deposit USD",
                                    money(data.disposed_usd_cents),
                                  ],
                                  [
                                    "Refunded Deposit USD",
                                    money(data.refunded_usd_cents),
                                  ],
                                ]}
                              />
                            )}
                          </td>
                          <td>
                            {kind === "INVOICE" ? (
                              <>
                                {financialLabel(data.invoice_number)}
                                <br />
                                {financialLabel(data.status)}
                              </>
                            ) : kind === "LATE_PAYMENT_CHARGE" ? (
                              <>
                                {money(data.original_usd_cents)}
                                <br />
                                {data.reversed === true
                                  ? "Reversed Charge"
                                  : "Active Charge"}
                              </>
                            ) : kind === "CREDIT" ? (
                              money(data.recognized_usd_cents)
                            ) : (
                              <>
                                {financialLabel(data.deposit_type)}
                                <br />
                                {money(data.received_usd_cents)}
                              </>
                            )}
                          </td>
                        </>
                      ) : (
                        <>
                          <td>
                            Source: {financialLabel(data.source_kind)} ·{" "}
                            {financialLabel(data.source_id)}
                            <br />
                            {kind === "REFUND" ? (
                              <>
                                Refund: {financialLabel(data.refund_number)}
                                <br />
                                Net unreturned:{" "}
                                {money(data.unreturned_usd_cents)}
                              </>
                            ) : (
                              <>
                                Target: {financialLabel(data.target_kind)} ·{" "}
                                {financialLabel(data.target_id)}
                              </>
                            )}
                          </td>
                          <td>
                            {money(data.amount_usd_cents)}
                            <br />
                            {financialTimestamp(data.occurred_at)}
                          </td>
                        </>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {items.length > 50 && (
            <div className="button-row">
              <button
                type="button"
                disabled={current === 0}
                onClick={() => {
                  setPage(current - 1);
                }}
              >
                Previous reversal records
              </button>
              <button
                type="button"
                disabled={(current + 1) * 50 >= items.length}
                onClick={() => {
                  setPage(current + 1);
                }}
              >
                Next reversal records
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
export function AllocationRecordEvidence({ resource }: { resource: unknown }) {
  const row = record(resource),
    allocation = record(row.allocation),
    details = Array.isArray(row.details) ? row.details.map(record) : [];
  return (
    <>
      <OriginalApplicationEvidence
        allocation
        value={{
          ...allocation,
          target_id:
            allocation.invoice_id ?? allocation.late_payment_charge_id ?? null,
        }}
      />
      <LinkedReversalEvidence value={allocation.reversal} />
      {allocation.proposal_trace != null && (
        <FinancialProposalEvidence value={allocation.proposal_trace} />
      )}
      <div className="financial-table-scroll">
        <table>
          <caption>Original Allocation detail page</caption>
          <thead>
            <tr>
              <th>Sequence / reference</th>
              <th>Original target / category</th>
              <th>Original proposed USD</th>
              <th>Posted USD / attribution</th>
            </tr>
          </thead>
          <tbody>
            {details.map((line) => (
              <tr key={financialLabel(line.id)}>
                <td>
                  {exact(line.detail_sequence)} · {financialLabel(line.id)}
                </td>
                <td>
                  {financialLabel(
                    line.invoice_line_id ?? line.late_payment_charge_id,
                  )}
                  <br />
                  {line.invoice_line_category_snapshot === null
                    ? "Separate Charge"
                    : financialLabel(line.invoice_line_category_snapshot)}
                </td>
                <td>{money(line.proposed_amount_usd_cents)}</td>
                <td>
                  {money(line.posted_amount_usd_cents)}
                  <br />
                  {financialLabel(line.attribution_basis)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
export function ReceiptHistoryEvidence({ items }: { items: unknown }) {
  const rows = Array.isArray(items) ? items.map(record) : [];
  return rows.length ? (
    <div className="financial-table-scroll">
      <table>
        <caption>Original Receipt reprint history page</caption>
        <thead>
          <tr>
            <th>Reprint reference / time</th>
            <th>Actor</th>
            <th>Reason / delivery evidence</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={financialLabel(row.id)}>
              <td>
                {financialLabel(row.id)}
                <br />
                {financialTimestamp(row.reprinted_at)}
              </td>
              <td>{financialLabel(row.reprinted_by)}</td>
              <td>
                {financialLabel(row.reason)}
                <br />
                {optional(row.delivery_reference)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ) : (
    <p>No reprints on this history page.</p>
  );
}
