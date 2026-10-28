// V1-060 B6: the pieces every report page shares (DESIGN.md "Report page"): the Summary card
// with its headline numbers, small side table and chart, the report table with its footer total
// and Generated line, and the links from a row to the record's own page.

import { Fragment, type ReactNode, useId } from "react";

import { dayText } from "../shell/format";
import { Icon, type ShellIcon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import type { Language } from "../signInText";
import { hasText, rpt } from "./text";

/** A headline number: its name, its value and an optional line under it. */
export type Fact = readonly [label: string, value: string, note?: string];

export function Facts({ facts }: { facts: readonly Fact[] }) {
  return (
    <dl className="ui-kv">
      {facts.map(([label, value, note], index) => (
        <Fragment key={`${String(index)}:${label}`}>
          <dt>{label}</dt>
          <dd className="ui-num">{value}</dd>
          {note !== undefined && <dd className="note">{note}</dd>}
        </Fragment>
      ))}
    </dl>
  );
}

export interface MiniRow {
  label: string;
  values: readonly string[];
  /** A line that is part of the line above it ("of which Rent"). */
  sub?: boolean;
}

/** The small by-kind or by-group table on the right of the summary. */
export function MiniTable({
  caption,
  heads,
  rows,
  total,
}: {
  caption: string;
  /** Column heads after the first (label) column; none for a two-column list. */
  heads?: readonly string[];
  rows: readonly MiniRow[];
  total?: MiniRow;
}) {
  const line = (row: MiniRow, index: number) => (
    <tr className={row.sub === true ? "sub" : undefined} key={index}>
      <th scope="row">{row.label}</th>
      {row.values.map((value, column) => (
        <td className="r ui-num" key={column}>
          {value}
        </td>
      ))}
    </tr>
  );
  return (
    <table className="rp-mini">
      <caption>{caption}</caption>
      {heads !== undefined && (
        <thead>
          <tr>
            <td />
            {heads.map((head) => (
              <th className="r" key={head} scope="col">
                {head}
              </th>
            ))}
          </tr>
        </thead>
      )}
      <tbody>{rows.map(line)}</tbody>
      {total !== undefined && <tfoot>{line(total, 0)}</tfoot>}
    </table>
  );
}

export function SummaryCard({
  language,
  facts,
  extra,
  side,
  chart,
  after,
}: {
  language: Language;
  facts: readonly Fact[];
  /** Under the headline numbers, such as the riel received. */
  extra?: ReactNode;
  /** The small table on the right. */
  side?: ReactNode;
  chart: ReactNode;
  /** Under the chart, such as the Utility Rates. */
  after?: ReactNode;
}) {
  const id = useId();
  return (
    <section aria-labelledby={id} className="ui-card">
      <div className="ui-chead">
        <h3 id={id}>{rpt(language, "summary")}</h3>
      </div>
      <div className={side === undefined ? "rp-sum one" : "rp-sum"}>
        <div className="rp-side">
          <Facts facts={facts} />
          {extra}
        </div>
        {side !== undefined && <div className="rp-side">{side}</div>}
      </div>
      <div className="rp-chartrow">{chart}</div>
      {after}
      <p className="ui-small ui-muted">{rpt(language, "currency")}</p>
    </section>
  );
}

export interface TableColumn {
  label: string;
  /** Amounts and counts are right-aligned. */
  right?: boolean;
}

export interface TableFrame {
  language: Language;
  title: string;
  icon: ShellIcon;
  /** "24 rows", or "Showing 200 of 340 rows". */
  count: string;
  /** "28/10/2026, 10:30", for the Generated line. */
  generated: string;
  /** Show more, and its failure note. */
  more?: ReactNode;
  /** V1-060 B7: "Total, all 340 rows" while only some rows are shown (the total is for all). */
  totalLabel?: string;
}

export function ReportTable({
  language,
  title,
  icon,
  count,
  generated,
  more,
  totalLabel,
  columns,
  footer,
  children,
  below,
  grid = false,
}: TableFrame & {
  columns: readonly TableColumn[];
  /** The footer total, one cell for each column; null for none. */
  footer: readonly ReactNode[] | null;
  children: ReactNode;
  /** Under the table, such as the reconciliation sentence. */
  below?: ReactNode;
  /** The year-by-month table keeps its first column in place. */
  grid?: boolean;
}) {
  const id = useId();
  return (
    <section aria-labelledby={id} className="ui-card pad0">
      <div className="ui-chead pad">
        <h3 id={id}>
          <Icon name={icon} small /> {title}
        </h3>
        <span className="ui-small ui-muted">{count}</span>
      </div>
      <div className="ui-tablewrap">
        <table
          aria-labelledby={id}
          className={grid ? "ui-table ui-grid rp-xtab" : "ui-table"}
        >
          <thead>
            <tr>
              {columns.map((column, index) => (
                <th
                  className={column.right === true ? "r" : undefined}
                  key={index}
                  scope="col"
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>{children}</tbody>
          {footer !== null && (
            <tfoot>
              <tr>
                {footer.map((cell, index) => (
                  <td
                    className={
                      columns[index]?.right === true ? "r ui-num" : undefined
                    }
                    key={index}
                  >
                    {index === 0 ? <b>{totalLabel ?? cell}</b> : cell}
                  </td>
                ))}
              </tr>
            </tfoot>
          )}
        </table>
      </div>
      {below}
      <div className="ui-tfoot ui-tfoot-row">
        <span>{rpt(language, "generated", generated)}</span>
        {more}
      </div>
    </section>
  );
}

// The pages a row links to (the same addresses the other screens use).
export const link = {
  unit: (id: string) => hashForPage("units", id),
  customer: (id: string) => hashForPage("customers", id),
  invoice: (id: string) => hashForPage("invoices", `inv:${id}`),
  receipt: (paymentId: string) =>
    hashForPage("payments", `receipt:${paymentId}`),
  lease: (id: string) => hashForPage("leases", id),
  reservation: (id: string) => hashForPage("reservations", id),
  settlement: (leaseId: string) => hashForPage("moveout", leaseId),
  history: () => hashForPage("history"),
};

export function UnitLink({
  unitId,
  unitNumber,
}: {
  unitId: string | null;
  unitNumber: string | null;
}) {
  if (unitId === null) return <span className="ui-muted">—</span>;
  return (
    <a className="ui-no ui-num" href={link.unit(unitId)}>
      {unitNumber ?? unitId.slice(0, 8)}
    </a>
  );
}

export function CustomerLink({
  customerId,
  name,
}: {
  customerId: string | null;
  name: string | null;
}) {
  if (customerId === null) return <span className="ui-muted">—</span>;
  return (
    <a href={link.customer(customerId)}>{name ?? customerId.slice(0, 8)}</a>
  );
}

/** A day as dd/mm/yyyy, or "—". */
export function day(value: string | null): string {
  return value === null || value === "" ? "—" : dayText(value);
}

/** The words for a code from the server ("cat_" + "RENT"), or the code itself. */
export function codeText(
  language: Language,
  prefix: string,
  code: string | null,
): string {
  if (code === null) return "—";
  const key = `${prefix}${code}`;
  return hasText(key) ? rpt(language, key) : code;
}

/** Saves a file the server made, as the History export does. */
export function save(file: { fileName: string; file: Blob }) {
  const url = URL.createObjectURL(file.file);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = file.fileName;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
