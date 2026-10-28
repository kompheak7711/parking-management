// V1-060 B6: the nine registers and lists (DESIGN.md "Report page", DL-072, DL-079). Each has a
// Summary card (the headline numbers, a small by-kind table and a chart) and the full table with
// its footer total; every record in a table links to its own page. The summary, chart and totals
// come from the server over every row of the filter, not only the rows read so far.

import type {
  AuditActivityRow,
  PaymentRegisterRow,
  RegisterName,
  RegisterPage,
  RegisterRows,
  UtilityConsumptionRow,
} from "../reportsClient";
import { kindOf, kindText } from "../history/text";
import { dayText, usdFromCents } from "../shell/format";
import { Icon, type ShellIcon } from "../shell/icons";
import { Chip, type Tone } from "../shell/ui";
import type { Language } from "../signInText";
import { BarList, type ChartColumn, StackedBars } from "./charts";
import {
  codeText,
  CustomerLink,
  day,
  type Fact,
  link,
  type MiniRow,
  MiniTable,
  ReportTable,
  SummaryCard,
  type TableFrame,
  UnitLink,
} from "./parts";
import {
  axisUsd,
  type Bag,
  bag,
  decimalText,
  has,
  items,
  measureText,
  num,
  numberText,
  rielText,
  str,
} from "./reportsData";
import { monthName, monthShort, type ReportsTextKey, rpt } from "./text";

const usd = usdFromCents;

interface ViewProps<N extends RegisterName> {
  language: Language;
  page: RegisterPage<N>;
  rows: RegisterRows[N][];
  frame: Omit<TableFrame, "count">;
  /** "24 rows" for the lines on screen, or "Showing 200 of 340 rows". */
  count: (lines: number) => string;
  /** A Unit Type's name from the Settings list, in the screen's language. */
  typeName: (code: string) => string;
}

function monthColumns(
  language: Language,
  months: Bag[],
  values: (entry: Bag) => number[],
): ChartColumn[] {
  return months.map((entry) => {
    const month = str(entry, "month");
    return {
      label: monthShort(language, month),
      tip: monthName(language, month),
      values: values(entry),
    };
  });
}

/** A labelled bar list of the money totals the server adds up ("bars": key and amount). */
function MoneyBars({
  language,
  page,
  title,
  labels,
}: {
  language: Language;
  page: RegisterPage<RegisterName>;
  title: ReportsTextKey;
  labels: Readonly<Record<string, ReportsTextKey>>;
}) {
  return (
    <BarList
      format={usd}
      rows={items(page.chart, "bars").map((bar) => {
        const key = str(bar, "key");
        const label = labels[key];
        return {
          label: label === undefined ? key : rpt(language, label),
          value: num(bar, "amount"),
        };
      })}
      title={rpt(language, title)}
    />
  );
}

function Money({ cents }: { cents: number | null | undefined }) {
  return (
    <td className="r ui-num">
      {cents === null || cents === undefined ? "—" : usd(cents)}
    </td>
  );
}

// ---------- Invoice register and balances ----------

const GROUPS = ["days_1_19", "days_20_29", "days_30_plus"] as const;

function invoiceState(
  row: RegisterRows["invoice_register"],
): [Tone, ShellIcon | undefined, ReportsTextKey] {
  if (row.status === "VOID") return ["neutral", "x", "st_void"];
  if (row.status === "PAID") return ["ok", "check", "st_paid"];
  if (row.overdue_days !== null && row.overdue_days > 0)
    return ["err", "alert", "st_overdue"];
  if (row.status === "PARTIALLY_PAID") return ["warn", "clock", "st_part"];
  if (row.status === "DRAFT") return ["info", undefined, "st_draft"];
  return ["neutral", undefined, "st_unpaid"];
}

function InvoiceRegister({
  language,
  page,
  rows,
  frame,
  count,
}: ViewProps<"invoice_register">) {
  const { summary } = page;
  const totals = page.totals ?? {};
  const groups = bag(summary, "overdue_groups");
  const voids = num(summary, "void_count");
  const facts: Fact[] = [
    [rpt(language, "s_issued"), usd(num(summary, "issued_usd_cents"))],
    [
      rpt(language, "s_paid_invoices"),
      usd(num(summary, "paid_to_invoices_usd_cents")),
    ],
    [
      rpt(language, "s_other_settled"),
      usd(num(summary, "other_settled_usd_cents")),
    ],
    [rpt(language, "c_owed"), usd(num(summary, "owed_usd_cents"))],
    voids > 0
      ? [
          rpt(language, "s_invoices"),
          numberText(num(summary, "invoice_count")),
          rpt(language, "s_void", voids),
        ]
      : [
          rpt(language, "s_invoices"),
          numberText(num(summary, "invoice_count")),
        ],
  ];
  return (
    <>
      <SummaryCard
        chart={
          <StackedBars
            axisFormat={axisUsd}
            columns={monthColumns(
              language,
              items(page.chart, "months"),
              (entry) => {
                const parts = bag(entry, "parts");
                return [
                  num(parts, "paid"),
                  num(parts, "other_settled"),
                  num(parts, "owed"),
                ];
              },
            )}
            format={usd}
            head={rpt(language, "month")}
            series={[
              rpt(language, "c_paid"),
              rpt(language, "c_other_settled"),
              rpt(language, "c_owed"),
            ]}
            title={rpt(language, "ch_invoice_register")}
            totalLabel={rpt(language, "total")}
          />
        }
        facts={facts}
        language={language}
        side={
          <MiniTable
            caption={rpt(language, "groups")}
            heads={[rpt(language, "s_invoices"), rpt(language, "c_owed")]}
            rows={GROUPS.map((group) => {
              const entry = bag(groups, group);
              return {
                label: rpt(language, group),
                values: [
                  numberText(num(entry, "count")),
                  usd(num(entry, "owed_usd_cents")),
                ],
              };
            })}
          />
        }
      />
      <ReportTable
        {...frame}
        columns={[
          { label: rpt(language, "c_invoice") },
          { label: rpt(language, "c_customer") },
          { label: rpt(language, "c_unit") },
          { label: rpt(language, "c_type") },
          { label: rpt(language, "c_issued") },
          { label: rpt(language, "c_due") },
          { label: rpt(language, "c_amount"), right: true },
          { label: rpt(language, "c_paid"), right: true },
          { label: rpt(language, "c_other_settled"), right: true },
          { label: rpt(language, "c_owed"), right: true },
          { label: rpt(language, "c_status") },
        ]}
        count={count(rows.length)}
        footer={[
          rpt(language, "total"),
          "",
          "",
          "",
          "",
          "",
          usd(num(totals, "total_usd_cents")),
          usd(num(totals, "paid_usd_cents")),
          usd(num(totals, "other_settled_usd_cents")),
          usd(num(totals, "owed_usd_cents")),
          "",
        ]}
      >
        {rows.map((row) => {
          const [tone, icon, state] = invoiceState(row);
          const late = row.overdue_days ?? 0;
          return (
            <tr key={row.invoice_id}>
              <td>
                <a className="ui-no ui-num" href={link.invoice(row.invoice_id)}>
                  {row.invoice_number}
                </a>
              </td>
              <td>
                <CustomerLink
                  customerId={row.customer_id}
                  name={row.customer_name}
                />
              </td>
              <td>
                <UnitLink unitId={row.unit_id} unitNumber={row.unit_number} />
              </td>
              <td>{codeText(language, "cat_", row.primary_category)}</td>
              <td className="ui-num">{day(row.invoice_date)}</td>
              <td className="ui-num">
                {day(row.due_date)}
                {late > 0 && (
                  <span className="ui-sub2 warn">
                    {late === 1
                      ? rpt(language, "days_over1")
                      : rpt(language, "days_over", late)}
                  </span>
                )}
              </td>
              <Money cents={row.total_usd_cents} />
              <Money cents={row.paid_usd_cents} />
              <Money cents={row.other_settled_usd_cents} />
              <Money cents={row.owed_usd_cents} />
              <td>
                <Chip icon={icon} tone={tone}>
                  {rpt(language, state)}
                </Chip>
              </td>
            </tr>
          );
        })}
      </ReportTable>
    </>
  );
}

// ---------- Payments and allocations ----------

// The parts of Paid to Invoices. Move-out charges are the cleaning, damage and other one-time
// Invoices (DL-079 answer 7), as on the Payments cards.
const INVOICE_PARTS = [
  ["p_rent", ["RENT"]],
  ["p_services", ["SERVICE_CHARGES"]],
  ["p_utilities", ["UTILITIES"]],
  ["p_move_out", ["DAMAGE_CHARGES", "MISCELLANEOUS_CHARGES"]],
] as const;

/** "Rent $100.00, Deposits $50.00": what one payment paid; Not allocated has its own column. */
function paidFor(language: Language, row: PaymentRegisterRow): string {
  const sums = new Map<string, number>();
  for (const part of row.parts) {
    if (part.kind === "NOT_ALLOCATED" || part.kind === "REVERSED_LATER") {
      continue;
    }
    const label =
      part.kind === "INVOICES" && part.category !== null
        ? codeText(language, "cat_", part.category)
        : rpt(language, `l_${part.kind}`);
    sums.set(label, (sums.get(label) ?? 0) + part.amount_usd_cents);
  }
  const text = [...sums]
    .map(([label, amount]) => `${label} ${usd(amount)}`)
    .join(", ");
  return text === "" ? "—" : text;
}

/** The riel a payment was made in, with its rate: information only. */
function rielLine(language: Language, row: PaymentRegisterRow): string | null {
  if (row.received_currency === "USD") return null;
  if (row.received_currency !== "KHR") {
    return `${row.received_amount_minor.toLocaleString("en-US")} ${row.received_currency}`;
  }
  const rate =
    row.rate_khr_per_usd === null
      ? ""
      : ` · ${rpt(language, "riel_rate", row.rate_khr_per_usd.toLocaleString("en-US"))}`;
  return `${rielText(row.received_amount_minor)}${rate}`;
}

function Payments({
  language,
  page,
  rows,
  frame,
  count,
}: ViewProps<"payments">) {
  const { summary } = page;
  const totals = page.totals ?? {};
  const lines = bag(summary, "lines");
  const categories = bag(summary, "paid_to_invoices_by_category");
  const received = num(summary, "received_usd_cents");
  const reversals = num(summary, "reversals_usd_cents");
  const riel = num(bag(summary, "received_other_currency_minor"), "KHR");
  const toInvoices = num(lines, "INVOICES");
  const facts: Fact[] = [
    [rpt(language, "s_received"), usd(received)],
    [rpt(language, "s_payments"), numberText(num(summary, "payment_count"))],
  ];
  if (reversals !== 0) {
    facts.push(
      [rpt(language, "s_reversals"), usd(reversals)],
      [rpt(language, "s_net"), usd(num(summary, "net_usd_cents"))],
    );
  }
  const line = (key: ReportsTextKey, code: string): MiniRow => ({
    label: rpt(language, key),
    values: [usd(num(lines, code))],
  });
  const where: MiniRow[] = [
    line("l_INVOICES", "INVOICES"),
    ...INVOICE_PARTS.map(([key, codes]) => ({
      label: rpt(language, "of_which", rpt(language, key)),
      values: [
        usd(codes.reduce((sum, code) => sum + num(categories, code), 0)),
      ],
      sub: true,
    })),
    line("l_DEPOSITS", "DEPOSITS"),
    line("l_CREDIT", "CREDIT"),
    line("l_LATE_PAYMENT_CHARGES", "LATE_PAYMENT_CHARGES"),
    ...(num(lines, "REFUNDED") === 0 ? [] : [line("l_REFUNDED", "REFUNDED")]),
    line("l_NOT_ALLOCATED", "NOT_ALLOCATED"),
    ...(num(lines, "REVERSED_LATER") === 0
      ? []
      : [line("l_REVERSED_LATER", "REVERSED_LATER")]),
  ];
  return (
    <>
      <SummaryCard
        chart={
          <StackedBars
            axisFormat={axisUsd}
            columns={monthColumns(
              language,
              items(page.chart, "months"),
              (entry) => {
                const parts = bag(entry, "parts");
                return [
                  num(parts, "paid_to_invoices"),
                  num(parts, "deposits"),
                  num(parts, "other"),
                ];
              },
            )}
            format={usd}
            head={rpt(language, "month")}
            series={[
              rpt(language, "s_paid_to_invoices"),
              rpt(language, "s_deposits"),
              rpt(language, "s_other_payment"),
            ]}
            title={rpt(language, "ch_payments")}
            totalLabel={rpt(language, "total")}
          />
        }
        extra={
          riel > 0 && (
            <p className="ui-small ui-muted">
              {rpt(language, "riel_received", rielText(riel))}
            </p>
          )
        }
        facts={facts}
        language={language}
        side={
          <>
            <MiniTable
              caption={rpt(language, "s_where")}
              rows={where}
              total={{
                label: rpt(language, "s_received"),
                values: [usd(received)],
              }}
            />
            <p className="ui-small ui-muted">
              {rpt(language, "recon", usd(toInvoices))}
            </p>
          </>
        }
      />
      <ReportTable
        {...frame}
        columns={[
          { label: rpt(language, "c_receipt") },
          { label: rpt(language, "c_received") },
          { label: rpt(language, "c_customer") },
          { label: rpt(language, "c_unit") },
          { label: rpt(language, "c_method") },
          { label: rpt(language, "c_amount"), right: true },
          { label: rpt(language, "c_for") },
          { label: rpt(language, "c_unalloc"), right: true },
          { label: rpt(language, "c_status") },
        ]}
        count={count(rows.length)}
        footer={[
          rpt(language, "total"),
          "",
          "",
          "",
          "",
          usd(num(totals, "amount_usd_cents")),
          "",
          usd(num(totals, "not_allocated_usd_cents")),
          "",
        ]}
      >
        {rows.map((row) => {
          const riel = rielLine(language, row);
          return (
            <tr key={row.payment_id}>
              <td>
                <a className="ui-no ui-num" href={link.receipt(row.payment_id)}>
                  {row.receipt_number}
                </a>
              </td>
              <td className="ui-num">{day(row.payment_date)}</td>
              <td>
                <CustomerLink
                  customerId={row.customer_id}
                  name={row.customer_name}
                />
              </td>
              <td>
                <UnitLink unitId={row.unit_id} unitNumber={row.unit_number} />
              </td>
              <td>{row.method_name}</td>
              <td className="r ui-num">
                {usd(row.amount_usd_cents)}
                {riel !== null && <span className="ui-sub2">{riel}</span>}
              </td>
              <td className="wrap">{paidFor(language, row)}</td>
              <td className="r ui-num">
                {row.not_allocated_usd_cents === 0
                  ? "—"
                  : usd(row.not_allocated_usd_cents)}
              </td>
              <td>
                {row.reversed_on === null ? (
                  <Chip icon="check" tone="ok">
                    {rpt(language, "st_received")}
                  </Chip>
                ) : (
                  <Chip icon="x" tone="warn">
                    {rpt(language, "reversed_on", dayText(row.reversed_on))}
                  </Chip>
                )}
              </td>
            </tr>
          );
        })}
      </ReportTable>
    </>
  );
}

// ---------- Utility consumption ----------

interface UtilityLine {
  key: string;
  first: UtilityConsumptionRow;
  electricity?: UtilityConsumptionRow;
  water?: UtilityConsumptionRow;
}

/** One line for each Unit and reading period, Electricity and Water side by side. */
function utilityLines(rows: readonly UtilityConsumptionRow[]): UtilityLine[] {
  const lines: UtilityLine[] = [];
  const open = new Map<string, UtilityLine[]>();
  for (const row of rows) {
    const key = `${row.unit_id ?? ""}|${row.period_start}|${row.period_end}`;
    const slot = row.utility_type === "ELECTRICITY" ? "electricity" : "water";
    const line = open.get(key)?.find((entry) => entry[slot] === undefined);
    if (line !== undefined) {
      line[slot] = row;
      continue;
    }
    const added: UtilityLine = { key, first: row, [slot]: row };
    lines.push(added);
    open.set(key, [...(open.get(key) ?? []), added]);
  }
  return lines;
}

function Used({
  language,
  row,
}: {
  language: Language;
  row: UtilityConsumptionRow | undefined;
}) {
  return (
    <td className="r ui-num">
      {row === undefined ? "—" : decimalText(row.quantity)}
      {row?.is_estimate === true && (
        <span className="ui-sub2">{rpt(language, "estimate")}</span>
      )}
    </td>
  );
}

function Billed({
  language,
  row,
}: {
  language: Language;
  row: UtilityConsumptionRow | undefined;
}) {
  return (
    <td className="r ui-num">
      {row?.amount_usd_cents === undefined ? "—" : usd(row.amount_usd_cents)}
      {row !== undefined && !row.billed && (
        <span className="ui-sub2">{rpt(language, "not_billed")}</span>
      )}
    </td>
  );
}

function UtilityConsumption({
  language,
  page,
  rows,
  frame,
  count,
}: ViewProps<"utility_consumption">) {
  const { summary } = page;
  const totals = page.totals ?? {};
  // Amounts and Rates come only with the money right (reports.read).
  const money = has(summary, "electricity_usd_cents");
  const lines = utilityLines(rows);
  const months = items(page.chart, "months");
  const columns = (key: string) =>
    monthColumns(language, months, (entry) => [Number(str(entry, key)) || 0]);
  const used = (source: unknown, key: string, measure: string) =>
    `${decimalText(str(source, key) || "0")} ${measure}`;
  const kinds: MiniRow[] = [
    {
      label: rpt(language, "c_electricity"),
      values: [
        used(summary, "electricity_kwh", "kWh"),
        ...(money ? [usd(num(summary, "electricity_usd_cents"))] : []),
      ],
    },
    {
      label: rpt(language, "c_water"),
      values: [
        used(summary, "water_m3", "m³"),
        ...(money ? [usd(num(summary, "water_usd_cents"))] : []),
      ],
    },
  ];
  const rates = [...(page.rates ?? [])].sort((left, right) =>
    right.effective_date.localeCompare(left.effective_date),
  );
  return (
    <>
      <SummaryCard
        after={
          money &&
          rates.length > 0 && (
            <div className="rp-side">
              <MiniTable
                caption={rpt(language, "rates_t")}
                heads={[rpt(language, "c_rate"), rpt(language, "c_since")]}
                rows={rates.map((rate) => ({
                  label: rpt(
                    language,
                    rate.utility_type === "WATER" ? "c_water" : "c_electricity",
                  ),
                  values: [
                    `$${decimalText(rate.rate_usd)} / ${measureText(rate.measurement_unit_code)}`,
                    dayText(rate.effective_date),
                  ],
                }))}
              />
              <p className="ui-small ui-muted">{rpt(language, "rates_n")}</p>
            </div>
          )
        }
        chart={
          <div className="rp-pair even">
            <StackedBars
              axisFormat={numberText}
              columns={columns("electricity_kwh")}
              format={(value) => `${numberText(value)} kWh`}
              head={rpt(language, "month")}
              series={["kWh"]}
              title={rpt(language, "ch_kwh")}
              totalLabel={rpt(language, "total")}
            />
            <StackedBars
              axisFormat={numberText}
              color={2}
              columns={columns("water_m3")}
              format={(value) => `${numberText(value)} m³`}
              head={rpt(language, "month")}
              series={["m³"]}
              title={rpt(language, "ch_m3")}
              totalLabel={rpt(language, "total")}
            />
          </div>
        }
        facts={[
          [
            rpt(language, "s_periods"),
            numberText(num(summary, "period_count")),
          ],
          [
            rpt(language, "s_estimates"),
            numberText(num(summary, "estimate_count")),
          ],
        ]}
        language={language}
        side={
          <MiniTable
            caption={rpt(language, "by_type")}
            heads={[
              rpt(language, "used"),
              ...(money ? [rpt(language, "c_amount")] : []),
            ]}
            rows={kinds}
          />
        }
      />
      <ReportTable
        {...frame}
        columns={[
          { label: rpt(language, "c_unit") },
          { label: rpt(language, "c_period") },
          { label: rpt(language, "c_kwh"), right: true },
          ...(money
            ? [{ label: rpt(language, "c_electricity"), right: true }]
            : []),
          { label: rpt(language, "c_m3"), right: true },
          ...(money ? [{ label: rpt(language, "c_water"), right: true }] : []),
        ]}
        count={count(lines.length)}
        footer={[
          rpt(language, "total"),
          "",
          decimalText(str(totals, "electricity_kwh") || "0"),
          ...(money ? [usd(num(totals, "electricity_usd_cents"))] : []),
          decimalText(str(totals, "water_m3") || "0"),
          ...(money ? [usd(num(totals, "water_usd_cents"))] : []),
        ]}
      >
        {lines.map((line, index) => (
          <tr key={`${line.key}:${String(index)}`}>
            <td>
              <UnitLink
                unitId={line.first.unit_id}
                unitNumber={line.first.unit_number}
              />
            </td>
            <td className="ui-num">
              {day(line.first.period_start)} – {day(line.first.period_end)}
            </td>
            <Used language={language} row={line.electricity} />
            {money && <Billed language={language} row={line.electricity} />}
            <Used language={language} row={line.water} />
            {money && <Billed language={language} row={line.water} />}
          </tr>
        ))}
      </ReportTable>
    </>
  );
}

// ---------- Customer Credit ledger ----------

function CreditLedger({
  language,
  page,
  rows,
  frame,
  count,
}: ViewProps<"credit_ledger">) {
  const { summary } = page;
  const totals = page.totals ?? {};
  return (
    <>
      <SummaryCard
        chart={
          <MoneyBars
            labels={{
              recognized: "c_credit",
              applied: "c_used",
              refunded: "c_refunded",
              reversed: "c_reversed",
              available: "c_left",
            }}
            language={language}
            page={page}
            title="ch_credit_ledger"
          />
        }
        facts={[
          [
            rpt(language, "s_credits"),
            numberText(num(summary, "credit_count")),
          ],
          [
            rpt(language, "c_credit"),
            usd(num(summary, "recognized_usd_cents")),
          ],
          [
            rpt(language, "s_left_now"),
            usd(num(summary, "available_usd_cents")),
          ],
        ]}
        language={language}
      />
      <ReportTable
        {...frame}
        columns={[
          { label: rpt(language, "c_customer") },
          { label: rpt(language, "c_unit") },
          { label: rpt(language, "c_origin") },
          { label: rpt(language, "c_recorded") },
          { label: rpt(language, "c_credit"), right: true },
          { label: rpt(language, "c_used"), right: true },
          { label: rpt(language, "c_refunded"), right: true },
          { label: rpt(language, "c_reversed"), right: true },
          { label: rpt(language, "c_left"), right: true },
        ]}
        count={count(rows.length)}
        footer={[
          rpt(language, "total"),
          "",
          "",
          "",
          usd(num(totals, "recognized_usd_cents")),
          usd(num(totals, "applied_usd_cents")),
          usd(num(totals, "refunded_usd_cents")),
          usd(num(totals, "reversed_usd_cents")),
          usd(num(totals, "available_usd_cents")),
        ]}
      >
        {rows.map((row) => (
          <tr key={row.credit_id}>
            <td>
              <CustomerLink
                customerId={row.customer_id}
                name={row.customer_name}
              />
            </td>
            <td>
              <UnitLink unitId={row.unit_id} unitNumber={row.unit_number} />
            </td>
            <td>
              <a
                className="ui-no ui-num"
                href={link.receipt(row.source_payment_id)}
              >
                {row.receipt_number}
              </a>
            </td>
            <td className="ui-num">{day(row.recognized_on)}</td>
            <Money cents={row.recognized_usd_cents} />
            <Money cents={row.applied_usd_cents} />
            <Money cents={row.refunded_usd_cents} />
            <Money cents={row.reversed_usd_cents} />
            <Money cents={row.available_usd_cents} />
          </tr>
        ))}
      </ReportTable>
    </>
  );
}

// ---------- Deposit liability and disposition ----------

function Deposits({
  language,
  page,
  rows,
  frame,
  count,
}: ViewProps<"deposits">) {
  const { summary } = page;
  const totals = page.totals ?? {};
  const byType = bag(summary, "held_by_type");
  return (
    <>
      <SummaryCard
        chart={
          <MoneyBars
            labels={{
              received: "c_received_amount",
              applied: "c_applied",
              kept: "c_kept",
              refunded: "c_refunded",
              held: "c_held",
            }}
            language={language}
            page={page}
            title="ch_deposits"
          />
        }
        facts={[
          [rpt(language, "s_held_now"), usd(num(summary, "held_usd_cents"))],
          [
            rpt(language, "s_deposit_count"),
            numberText(num(summary, "deposit_count")),
          ],
        ]}
        language={language}
        side={
          <MiniTable
            caption={rpt(language, "by_type")}
            heads={[rpt(language, "c_held")]}
            rows={(["SECURITY", "PET"] as const).map((type) => ({
              label: rpt(language, `dep_${type}`),
              values: [usd(num(byType, type))],
            }))}
          />
        }
      />
      <ReportTable
        {...frame}
        columns={[
          { label: rpt(language, "c_unit") },
          { label: rpt(language, "c_customer") },
          { label: rpt(language, "c_kind") },
          { label: rpt(language, "c_status") },
          { label: rpt(language, "c_required"), right: true },
          { label: rpt(language, "c_received_amount"), right: true },
          { label: rpt(language, "c_applied"), right: true },
          { label: rpt(language, "c_kept"), right: true },
          { label: rpt(language, "c_refunded"), right: true },
          { label: rpt(language, "c_held"), right: true },
        ]}
        count={count(rows.length)}
        footer={[
          rpt(language, "total"),
          "",
          "",
          "",
          "",
          usd(num(totals, "received_usd_cents")),
          usd(num(totals, "applied_usd_cents")),
          usd(num(totals, "kept_usd_cents")),
          usd(num(totals, "refunded_usd_cents")),
          usd(num(totals, "held_usd_cents")),
        ]}
      >
        {rows.map((row) => (
          <tr key={row.deposit_id}>
            <td>
              <UnitLink unitId={row.unit_id} unitNumber={row.unit_number} />
            </td>
            <td>
              <CustomerLink
                customerId={row.customer_id}
                name={row.customer_name}
              />
            </td>
            <td>{rpt(language, `dep_${row.deposit_type}`)}</td>
            <td>
              {row.lease_id !== null ? (
                <a href={link.lease(row.lease_id)}>
                  {rpt(language, "rec_lease")}
                </a>
              ) : row.reservation_id !== null ? (
                <a href={link.reservation(row.reservation_id)}>
                  {rpt(language, "rec_reservation")}
                </a>
              ) : (
                "—"
              )}
              <span className="ui-sub2">
                {row.settlement_closed
                  ? rpt(language, "settled")
                  : codeText(language, "rs_", row.record_status)}
              </span>
            </td>
            <Money cents={row.required_usd_cents} />
            <Money cents={row.received_usd_cents} />
            <Money cents={row.applied_usd_cents} />
            <Money cents={row.kept_usd_cents} />
            <Money cents={row.refunded_usd_cents} />
            <Money cents={row.held_usd_cents} />
          </tr>
        ))}
      </ReportTable>
    </>
  );
}

// ---------- Final Settlement register ----------

function FinalSettlements({
  language,
  page,
  rows,
  frame,
  count,
}: ViewProps<"final_settlements">) {
  const { summary } = page;
  const totals = page.totals ?? {};
  return (
    <>
      <SummaryCard
        chart={
          <MoneyBars
            labels={{
              deposits_applied: "c_deposits_applied",
              credit_applied: "c_credit_applied",
              deposits_kept: "c_deposits_kept",
              refunded: "c_refunded",
              balance_due: "c_balance",
            }}
            language={language}
            page={page}
            title="ch_final_settlements"
          />
        }
        facts={[
          [rpt(language, "st_open"), numberText(num(summary, "open_count"))],
          [
            rpt(language, "st_closed"),
            numberText(num(summary, "closed_count")),
          ],
          [
            rpt(language, "c_refunded"),
            usd(num(summary, "refunded_usd_cents")),
          ],
          [
            rpt(language, "c_balance"),
            usd(num(summary, "balance_due_usd_cents")),
          ],
        ]}
        language={language}
      />
      <ReportTable
        {...frame}
        columns={[
          { label: rpt(language, "c_unit") },
          { label: rpt(language, "c_customer") },
          { label: rpt(language, "c_started") },
          { label: rpt(language, "c_move_out") },
          { label: rpt(language, "c_closed") },
          { label: rpt(language, "c_deposits_applied"), right: true },
          { label: rpt(language, "c_credit_applied"), right: true },
          { label: rpt(language, "c_deposits_kept"), right: true },
          { label: rpt(language, "c_refunded"), right: true },
          { label: rpt(language, "c_balance"), right: true },
          { label: rpt(language, "c_status") },
        ]}
        count={count(rows.length)}
        footer={[
          rpt(language, "total"),
          "",
          "",
          "",
          "",
          usd(num(totals, "deposits_applied_usd_cents")),
          usd(num(totals, "credit_applied_usd_cents")),
          usd(num(totals, "deposits_kept_usd_cents")),
          usd(num(totals, "refunded_usd_cents")),
          usd(num(totals, "balance_due_usd_cents")),
          "",
        ]}
      >
        {rows.map((row) => (
          <tr key={row.final_settlement_id}>
            <td>
              {/* A Final Settlement is named by its Unit, as the mock-up does. */}
              <a className="ui-no ui-num" href={link.settlement(row.lease_id)}>
                {row.unit_number ?? row.lease_id.slice(0, 8)}
              </a>
            </td>
            <td>
              <CustomerLink
                customerId={row.customer_id}
                name={row.customer_name}
              />
            </td>
            <td className="ui-num">{day(row.started_on)}</td>
            <td className="ui-num">{day(row.move_out_date)}</td>
            <td className="ui-num">{day(row.closed_on)}</td>
            <Money cents={row.deposits_applied_usd_cents} />
            <Money cents={row.credit_applied_usd_cents} />
            <Money cents={row.deposits_kept_usd_cents} />
            <Money cents={row.refunded_usd_cents} />
            <Money cents={row.balance_due_usd_cents} />
            <td>
              {row.status === "OPEN" ? (
                <Chip icon="clock" tone="info">
                  {rpt(language, "st_open")}
                </Chip>
              ) : (
                <Chip icon="check" tone="neutral">
                  {rpt(language, "st_closed")}
                </Chip>
              )}
            </td>
          </tr>
        ))}
      </ReportTable>
    </>
  );
}

// ---------- Unit occupancy ----------

const UNIT_CHIPS: Readonly<
  Partial<Record<string, readonly [Tone, ShellIcon]>>
> = {
  OCCUPIED: ["ok", "check"],
  RESERVED: ["info", "calendar"],
  VACANT: ["neutral", "door"],
};

const OCCUPANCY_BARS: Readonly<Record<string, ReportsTextKey>> = {
  occupied: "s_occupied",
  reserved: "s_reserved",
  vacant: "s_vacant",
  not_available: "s_not_available",
};

function UnitOccupancy({
  language,
  page,
  rows,
  frame,
  count,
  typeName,
}: ViewProps<"unit_occupancy">) {
  const { summary } = page;
  // Monthly Rent comes only with the money right (reports.read).
  const money = rows.some((row) => "monthly_rent_usd_cents" in row);
  const units = num(summary, "unit_count");
  return (
    <>
      <SummaryCard
        chart={
          <BarList
            format={numberText}
            rows={items(page.chart, "bars").map((bar) => {
              const key = OCCUPANCY_BARS[str(bar, "key")];
              return {
                label: key === undefined ? str(bar, "key") : rpt(language, key),
                value: num(bar, "count"),
              };
            })}
            title={rpt(language, "ch_unit_occupancy")}
          />
        }
        facts={[
          [rpt(language, "s_units"), numberText(units)],
          [rpt(language, "s_occupied"), numberText(num(summary, "occupied"))],
          [rpt(language, "s_reserved"), numberText(num(summary, "reserved"))],
          [rpt(language, "s_vacant"), numberText(num(summary, "vacant"))],
          [
            rpt(language, "s_not_available"),
            numberText(num(summary, "not_available")),
          ],
        ]}
        language={language}
      />
      <ReportTable
        {...frame}
        columns={[
          { label: rpt(language, "c_unit") },
          { label: rpt(language, "c_unit_type") },
          { label: rpt(language, "c_status") },
          { label: rpt(language, "c_customer") },
          { label: rpt(language, "c_lease") },
          ...(money ? [{ label: rpt(language, "c_rent"), right: true }] : []),
          { label: rpt(language, "c_until") },
        ]}
        count={count(rows.length)}
        footer={[
          rpt(language, "total"),
          units === 1
            ? rpt(language, "n_units1")
            : rpt(language, "n_units", units),
          "",
          "",
          "",
          ...(money ? [""] : []),
          "",
        ]}
      >
        {rows.map((row, index) => {
          const [tone, icon] = UNIT_CHIPS[row.unit_status] ?? [
            "warn",
            "wrench",
          ];
          return (
            <tr key={row.unit_id ?? String(index)}>
              <td>
                <UnitLink unitId={row.unit_id} unitNumber={row.unit_number} />
              </td>
              <td>{typeName(row.unit_type)}</td>
              <td>
                <Chip icon={icon} tone={tone}>
                  {codeText(language, "u_", row.unit_status)}
                </Chip>
              </td>
              <td>
                <CustomerLink
                  customerId={row.customer_id}
                  name={row.customer_name}
                />
              </td>
              <td>
                {row.lease_id !== null ? (
                  <a href={link.lease(row.lease_id)}>
                    {rpt(language, "rec_lease")}
                  </a>
                ) : row.reservation_id !== null ? (
                  <a href={link.reservation(row.reservation_id)}>
                    {rpt(language, "rec_reservation")}
                  </a>
                ) : (
                  <span className="ui-muted">—</span>
                )}
              </td>
              {money && <Money cents={row.monthly_rent_usd_cents} />}
              <td className="ui-num">{day(row.until_date)}</td>
            </tr>
          );
        })}
      </ReportTable>
    </>
  );
}

// ---------- Lease dates ----------

function LeaseDates({
  language,
  page,
  rows,
  frame,
  count,
}: ViewProps<"lease_dates">) {
  const { summary } = page;
  // Monthly Rent comes only with the money right (reports.read).
  const money = rows.some((row) => "monthly_rent_usd_cents" in row);
  return (
    <>
      <SummaryCard
        chart={
          <StackedBars
            columns={monthColumns(
              language,
              items(page.chart, "months"),
              (entry) => [num(entry, "count")],
            )}
            format={numberText}
            head={rpt(language, "month")}
            series={[rpt(language, "leases")]}
            title={rpt(language, "ch_lease_dates")}
            totalLabel={rpt(language, "total")}
          />
        }
        facts={[
          [
            rpt(language, "s_current"),
            numberText(num(summary, "current_count")),
          ],
          [
            rpt(language, "s_ending"),
            numberText(num(summary, "ending_60_days_count")),
          ],
          [
            rpt(language, "s_no_renewal"),
            numberText(num(summary, "ending_without_renewal_count")),
          ],
          [
            rpt(language, "s_terminated"),
            numberText(num(summary, "terminated_count")),
          ],
        ]}
        language={language}
      />
      <ReportTable
        {...frame}
        columns={[
          { label: rpt(language, "c_unit") },
          { label: rpt(language, "c_customer") },
          { label: rpt(language, "c_start") },
          { label: rpt(language, "c_end") },
          ...(money ? [{ label: rpt(language, "c_rent"), right: true }] : []),
          { label: rpt(language, "c_renewal") },
          { label: rpt(language, "c_status") },
        ]}
        count={count(rows.length)}
        footer={[
          rpt(language, "total"),
          page.row_count === 1
            ? rpt(language, "n_leases1")
            : rpt(language, "n_leases", page.row_count),
          "",
          "",
          ...(money ? [""] : []),
          "",
          "",
        ]}
      >
        {rows.map((row) => {
          const ending =
            row.status === "SIGNED" &&
            row.days_to_end !== null &&
            row.days_to_end >= 0 &&
            row.days_to_end <= 60;
          return (
            <tr key={row.lease_id}>
              <td>
                {/* A Lease is named by its Unit (DESIGN.md Do's and Don'ts). */}
                <a className="ui-no ui-num" href={link.lease(row.lease_id)}>
                  {row.unit_number ?? row.lease_id.slice(0, 8)}
                </a>
              </td>
              <td>
                <CustomerLink
                  customerId={row.customer_id}
                  name={row.customer_name}
                />
              </td>
              <td className="ui-num">{day(row.start_date)}</td>
              <td className="ui-num">
                {day(row.end_date)}
                {ending && (
                  <span className="ui-sub2 warn">
                    {rpt(language, "in_days", row.days_to_end ?? 0)}
                  </span>
                )}
                {row.actual_termination_date !== null && (
                  <span className="ui-sub2">
                    {rpt(language, "ended_early")}
                  </span>
                )}
              </td>
              {money && <Money cents={row.monthly_rent_usd_cents} />}
              <td>
                {row.renewal_drafted ? (
                  <Chip tone="info">{rpt(language, "drafted")}</Chip>
                ) : (
                  <span className="ui-muted">—</span>
                )}
              </td>
              <td>
                {row.status === "SIGNED" ? (
                  <Chip icon="check" tone="ok">
                    {rpt(language, "rs_SIGNED")}
                  </Chip>
                ) : (
                  <Chip tone="neutral">{rpt(language, "rs_TERMINATED")}</Chip>
                )}
              </td>
            </tr>
          );
        })}
      </ReportTable>
    </>
  );
}

// ---------- Audit activity ----------

function AuditActivity({
  language,
  page,
  rows,
  frame,
  count,
}: ViewProps<"audit_activity">) {
  const { summary } = page;
  const totals = page.totals ?? {};
  // Action families named as the History kinds; families of one kind are added together.
  const kinds = new Map<string, number>();
  for (const entry of items(summary, "by_kind")) {
    const name = kindText(language, kindOf(str(entry, "kind")));
    kinds.set(name, (kinds.get(name) ?? 0) + num(entry, "count"));
  }
  // The chart shows the last 31 days that have events.
  const days = items(page.chart, "days").slice(-31);
  return (
    <>
      <SummaryCard
        chart={
          <StackedBars
            columns={days.map((entry) => {
              const text = dayText(str(entry, "day"));
              return {
                label: text.slice(0, 5),
                tip: text,
                values: [num(entry, "count")],
              };
            })}
            format={numberText}
            head={rpt(language, "c_day")}
            series={[rpt(language, "c_events")]}
            title={rpt(language, "ch_audit_activity")}
            totalLabel={rpt(language, "total")}
          />
        }
        extra={
          <p>
            <a className="ui-btn" href={link.history()}>
              <Icon name="history" small />
              {rpt(language, "open_history")}
            </a>
          </p>
        }
        facts={[
          [rpt(language, "s_events"), numberText(num(summary, "event_count"))],
        ]}
        language={language}
        side={
          <>
            <MiniTable
              caption={rpt(language, "by_actor")}
              rows={items(summary, "by_actor").map((entry) => {
                const name = str(entry, "name");
                return {
                  label: name === "System" ? rpt(language, "system") : name,
                  values: [numberText(num(entry, "count"))],
                };
              })}
            />
            <MiniTable
              caption={rpt(language, "by_kind")}
              rows={[...kinds]
                .sort((left, right) => right[1] - left[1])
                .map(([label, events]) => ({
                  label,
                  values: [numberText(events)],
                }))}
            />
          </>
        }
      />
      <ReportTable
        {...frame}
        columns={[
          { label: rpt(language, "c_day") },
          { label: rpt(language, "c_events"), right: true },
        ]}
        count={count(rows.length)}
        footer={[rpt(language, "total"), numberText(num(totals, "count"))]}
      >
        {rows.map((row: AuditActivityRow) => (
          <tr key={row.day}>
            <td>
              {/* History has no address for one day; the day opens History. */}
              <a className="ui-num" href={link.history()}>
                {dayText(row.day)}
              </a>
            </td>
            <td className="r ui-num">{numberText(row.count)}</td>
          </tr>
        ))}
      </ReportTable>
    </>
  );
}

// ---------- the register on screen ----------

export interface RegisterContentProps {
  language: Language;
  name: RegisterName;
  page: RegisterPage<RegisterName>;
  rows: RegisterRows[RegisterName][];
  frame: Omit<TableFrame, "count">;
  count: (lines: number) => string;
  typeName: (code: string) => string;
}

export function RegisterContent(props: RegisterContentProps) {
  switch (props.name) {
    case "invoice_register":
      return <InvoiceRegister {...(props as ViewProps<"invoice_register">)} />;
    case "payments":
      return <Payments {...(props as ViewProps<"payments">)} />;
    case "utility_consumption":
      return (
        <UtilityConsumption {...(props as ViewProps<"utility_consumption">)} />
      );
    case "credit_ledger":
      return <CreditLedger {...(props as ViewProps<"credit_ledger">)} />;
    case "deposits":
      return <Deposits {...(props as ViewProps<"deposits">)} />;
    case "final_settlements":
      return (
        <FinalSettlements {...(props as ViewProps<"final_settlements">)} />
      );
    case "unit_occupancy":
      return <UnitOccupancy {...(props as ViewProps<"unit_occupancy">)} />;
    case "lease_dates":
      return <LeaseDates {...(props as ViewProps<"lease_dates">)} />;
    case "audit_activity":
      return <AuditActivity {...(props as ViewProps<"audit_activity">)} />;
  }
}
