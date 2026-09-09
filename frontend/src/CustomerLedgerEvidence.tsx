import {
  LEDGER_BALANCES,
  LEDGER_BUCKETS,
  LEDGER_EVENTS,
  ledgerMoney,
  type LedgerAudit,
  type LedgerCommon,
  type LedgerComponent,
  type LedgerComposition,
  type LedgerHistory,
  type LedgerPosition,
} from "./customerLedgerClient";

export function LedgerPositionSummary({
  position,
  historical = false,
}: {
  position: LedgerPosition;
  historical?: boolean;
}) {
  return (
    <dl className="ledger-position">
      <div>
        <dt>
          {historical
            ? "Amount owed after this instant"
            : "Current amount owed"}
        </dt>
        <dd>{ledgerMoney(position.total_owed_usd_cents)}</dd>
      </div>
      {Object.entries(LEDGER_BUCKETS).map(([key, label]) => (
        <div key={key}>
          <dt>{label}</dt>
          <dd>
            {ledgerMoney(
              position[`${key as keyof typeof LEDGER_BUCKETS}_usd_cents`],
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}
export function LedgerHistoryTable({
  rows,
  openSource,
}: {
  rows: readonly LedgerHistory[];
  openSource: (row: LedgerHistory) => void;
}) {
  return (
    <div
      className="financial-table-scroll"
      tabIndex={0}
      role="region"
      aria-label="Chronological ledger events"
    >
      <table>
        <caption>Chronological financial history — this page</caption>
        <thead>
          <tr>
            <th scope="col">Event and time</th>
            <th scope="col">Recorded amount</th>
            <th scope="col">Business effects</th>
            <th scope="col">Resulting position</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.event_kind}:${row.event_id}`}>
              <th scope="row">
                <strong>{LEDGER_EVENTS[row.event_kind][1]}</strong>
                <br />
                <time dateTime={row.occurred_at}>{row.occurred_at}</time>
                <br />
                Business date: {row.business_date}
                <br />
                <button
                  type="button"
                  aria-controls="account-ledger-source"
                  onClick={() => {
                    openSource(row);
                  }}
                >
                  View source:{" "}
                  {row.source_reference ?? LEDGER_EVENTS[row.event_kind][1]}
                </button>
              </th>
              <td>
                {row.recorded_amount_usd_cents === null
                  ? "Not recorded"
                  : ledgerMoney(row.recorded_amount_usd_cents)}
              </td>
              <td>
                <dl className="ledger-effects">
                  {Object.entries(LEDGER_BUCKETS).map(([key, label]) => {
                    const amount =
                        row[
                          `${key as keyof typeof LEDGER_BUCKETS}_effect_usd_cents`
                        ],
                      value = BigInt(amount);
                    return value === 0n ? null : (
                      <div key={key}>
                        <dt>{label}</dt>
                        <dd>
                          {value > 0n ? "Increase " : "Decrease "}
                          {ledgerMoney(
                            value < 0n ? (-value).toString() : amount,
                          )}
                        </dd>
                      </div>
                    );
                  })}
                </dl>
                {Object.keys(LEDGER_BUCKETS).every(
                  (key) =>
                    row[
                      `${key as keyof typeof LEDGER_BUCKETS}_effect_usd_cents`
                    ] === "0",
                ) && "No balance change"}
              </td>
              <td>
                <details>
                  <summary>
                    Amount owed{" "}
                    {ledgerMoney(
                      row.position_after_instant.total_owed_usd_cents,
                    )}{" "}
                    — view all balances
                  </summary>
                  <LedgerPositionSummary
                    position={row.position_after_instant}
                    historical
                  />
                </details>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
const sourceLabels = {
  invoice_id: "Invoice",
  invoice_line_id: "Invoice line",
  late_payment_charge_id: "Late-payment Charge",
  payment_id: "Payment",
  customer_credit_id: "Customer Credit",
  deposit_id: "Deposit",
  refund_id: "Refund",
} as const;
export function LedgerSourceIdentities({
  row,
}: {
  row: Partial<Record<keyof typeof sourceLabels, string | null>>;
}) {
  return (
    <dl className="financial-facts">
      {Object.entries(sourceLabels).map(([key, label]) => {
        const value = row[key as keyof typeof sourceLabels];
        return value ? (
          <div key={key}>
            <dt>{label} record</dt>
            <dd>{value}</dd>
          </div>
        ) : null;
      })}
    </dl>
  );
}
const auditLabels: Record<string, string> = {
  due_date: "Due date",
  lease_id: "Lease record",
  adjustment_id: "Adjustment record",
  adjustment_type: "Adjustment direction",
  reason: "Reason",
  reverses_event_id: "Original event reversed",
  payable_at: "Payable at",
  decision_id: "Decision record",
  correction_kind: "Correction kind",
  outcome: "Decision outcome",
  received_currency: "Original Payment currency",
  received_amount_minor: "Original Payment amount (minor units)",
  usd_accounting_value_cents: "Original USD accounting value",
  payment_scope_kind: "Payment scope",
  payment_method: "Payment method",
  exchange_rate_record_id: "Original exchange-rate record",
  exchange_rate: "Original exchange-rate evidence",
  reference_rate_khr_per_usd: "Original reference rate (KHR per USD)",
  markup_basis_points: "Original markup (basis points)",
  system_rate_khr_per_usd: "Original system rate (KHR per USD)",
  applicable_at: "Rate applicable at",
  rate_source: "Rate source",
  channel_actual_currency: "Channel currency",
  channel_actual_amount_minor: "Channel amount (minor units)",
  channel_actual_usd_value_cents: "Channel USD value",
  channel_actual_rate_khr_per_usd: "Channel rate (KHR per USD)",
  channel_confirmed_at: "Channel confirmation time",
  application_id: "Application record",
  target_kind: "Application target",
  target_customer_id: "Beneficiary Customer record",
  within_invoice_basis: "Within-Invoice application basis",
  deposit_type: "Deposit type",
  effective_date: "Effective date",
  currency: "Refund currency",
  verified_return_currency: "Verified returned currency",
  verified_return_amount_minor: "Verified returned amount (minor units)",
  verified_returned_at: "Verified returned at",
  refund_amount_minor: "Original Refund amount (minor units)",
};
function label(key: string): string {
  return (
    auditLabels[key] ??
    key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())
  );
}
function fact(key: string, value: LedgerAudit): React.ReactNode {
  if (value === null) return "Not recorded";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "string") {
    if (
      key.endsWith("_usd_cents") ||
      key === "usd_accounting_value_cents" ||
      key === "channel_actual_usd_value_cents"
    )
      return ledgerMoney(value);
    if (key === "adjustment_type")
      return value === "DEBIT"
        ? "Increase"
        : value === "CREDIT"
          ? "Decrease"
          : value;
    return value || "Not recorded";
  }
  if (Array.isArray(value))
    return (
      <ol>
        {(value as readonly LedgerAudit[]).map((item, index) => (
          <li key={index}>{fact(key, item)}</li>
        ))}
      </ol>
    );
  return (
    <dl className="financial-facts">
      {Object.entries(value).map(([name, item]) => (
        <div key={name}>
          <dt>{label(name)}</dt>
          <dd>{fact(name, item)}</dd>
        </div>
      ))}
    </dl>
  );
}
export function LedgerEventEvidence({ row }: { row: LedgerCommon }) {
  return (
    <>
      <p>
        {LEDGER_EVENTS[row.event_kind][1]}. Recorded amount:{" "}
        {row.recorded_amount_usd_cents === null
          ? "Not recorded"
          : ledgerMoney(row.recorded_amount_usd_cents)}
        . Component effects below explain which balances changed; they are not
        additional receipts.
      </p>
      <dl className="financial-facts">
        <div>
          <dt>Source reference</dt>
          <dd>{row.source_reference ?? "No display reference"}</dd>
        </div>
        <div>
          <dt>Source event record</dt>
          <dd>{row.event_id}</dd>
        </div>
        <div>
          <dt>Event time</dt>
          <dd>
            <time dateTime={row.occurred_at}>{row.occurred_at}</time>
          </dd>
        </div>
        <div>
          <dt>Business date</dt>
          <dd>{row.business_date}</dd>
        </div>
      </dl>
      <LedgerSourceIdentities row={row} />
      {Object.keys(row.source_audit).length > 0 && (
        <details open>
          <summary>Original source evidence</summary>
          <p>
            Original currency and exchange rates are retained as recorded. This
            view does not select a new rate.
          </p>
          {fact("source_audit", row.source_audit)}
        </details>
      )}
    </>
  );
}
export function LedgerComponentTable({
  rows,
}: {
  rows: readonly LedgerComponent[];
}) {
  return (
    <div
      className="financial-table-scroll"
      tabIndex={0}
      role="region"
      aria-label="Source balance effects"
    >
      <table>
        <caption>Source components — this page</caption>
        <thead>
          <tr>
            <th scope="col">Balance</th>
            <th scope="col">Source and composition</th>
            <th scope="col">Effect</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.detail_key}>
              <th scope="row">
                {row.balance_kind === "NONE"
                  ? "Presentation only"
                  : LEDGER_BALANCES[row.balance_kind]}
              </th>
              <td>
                {row.category && <strong>{row.category}</strong>}
                {row.description && <p>{row.description}</p>}
                <LedgerSourceIdentities row={row} />
                {row.balance_source_id && (
                  <p>Balance source record: {row.balance_source_id}</p>
                )}
              </td>
              <td>
                {row.effect_usd_cents === "0" ? (
                  "No balance change"
                ) : (
                  <>
                    {BigInt(row.effect_usd_cents) > 0n
                      ? "Increase "
                      : "Decrease "}
                    {ledgerMoney(row.effect_usd_cents.replace(/^-/, ""))}
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
export function LedgerCompositionTable({
  rows,
}: {
  rows: readonly LedgerComposition[];
}) {
  return (
    <div
      className="financial-table-scroll"
      tabIndex={0}
      role="region"
      aria-label="Current balance composition"
    >
      <table>
        <caption>Remaining balance composition — this page</caption>
        <thead>
          <tr>
            <th scope="col">Balance group</th>
            <th scope="col">Source and composition</th>
            <th scope="col">Remaining</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.detail_key}>
              <th scope="row">{LEDGER_BALANCES[row.balance_kind]}</th>
              <td>
                {row.category && <strong>{row.category}</strong>}
                {row.description && <p>{row.description}</p>}
                <LedgerSourceIdentities row={row} />
                <p>Balance source record: {row.balance_source_id}</p>
              </td>
              <td>{ledgerMoney(row.balance_usd_cents)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
