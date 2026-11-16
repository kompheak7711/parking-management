// UI v81 (B4, design v81 Home): the Owner's money box on Home ("Financial summary", owner
// 12/11/2026) and what the Attendance card counts.
// Display only: the numbers come from the Ledger reports and the Attendance day sheet the app
// already reads; nothing here works out money of its own beyond adding report lines.

import { useEffect, useState } from "react";

import type { AttendanceDay } from "../hr/hrClient";
import type { LedgerApi, Report } from "../ledger/ledgerClient";
import { usdFromCents } from "../shell/format";
import { Icon, type ShellIcon } from "../shell/icons";
import { CardGrid } from "../shell/layouts";
import type { PageId } from "../shell/navigation";
import { hashForShow } from "../shell/useHashPage";
import type { Language } from "../signInText";
import { hmt } from "./text";

/** The Financial summary numbers, in cents; null when that report could not be read. */
export interface OwnerMoneyNumbers {
  cash: number | null;
  owe: number | null;
  over30: number | null;
  spent: number | null;
  budget: number | null;
  profit: number | null;
  year: string;
}

function cents(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

/** Cash and bank: the asset lines 1000 to 1099 of the Balance sheet. */
export function cashOf(report: Report): number {
  return report.rows
    .filter(
      (row) =>
        row.line === "account" &&
        typeof row.code === "string" &&
        /^10\d\d$/.test(row.code),
    )
    .reduce((sum, row) => sum + cents(row.amount), 0);
}

/** Customers owe (the Total line) and the part more than 30 days late. */
export function owedOf(report: Report): { owe: number; over30: number } {
  const total = report.rows.find((row) => row.line === "total");
  if (total === undefined) return { owe: 0, over30: 0 };
  return {
    owe: cents(total.total),
    over30:
      cents(total.days_31_60) + cents(total.days_61_90) + cents(total.over_90),
  };
}

/** Profit this year: the "Profit (or loss)" line, year to date. */
export function profitOf(report: Report): number {
  const line = report.rows.find(
    (row) => row.line === "total" && row.name === "Profit (or loss)",
  );
  return cents(line?.year_to_date);
}

/** Spent this month and its budget: the expense lines (5000 to 6999) of Budget vs actual. */
export function spentOf(report: Report): { spent: number; budget: number } {
  const lines = report.rows.filter(
    (row) =>
      row.line === "account" &&
      typeof row.code === "string" &&
      /^[56]\d{3}$/.test(row.code),
  );
  return {
    spent: lines.reduce((sum, row) => sum + cents(row.actual_month), 0),
    budget: lines.reduce((sum, row) => sum + cents(row.budget_month), 0),
  };
}

function MoneyCard({
  icon,
  tone,
  label,
  value,
  note,
  page,
  show,
}: {
  icon: ShellIcon;
  tone: string;
  label: string;
  value: number | null;
  /** Owner 14/11/2026: only a line that tells something ("Budget $500.00"). */
  note?: string;
  page: PageId;
  /** UI v81 round 11: the statement the card's number comes from, so the card opens it. */
  show: string;
}) {
  return (
    <a
      className={`ui-kpi ui-home-kpi ui-kpi-top ui-kpi-amount ${value === null ? "none" : tone}`}
      href={hashForShow(page, show)}
    >
      {/* Owner 12/11/2026: the number sits at the top right, beside the name. */}
      <span className="ui-kpi-head">
        <span className="ui-kpi-label">
          <span className="ui-kpi-icon">
            <Icon name={icon} small />
          </span>
          <span>{label}</span>
        </span>
        <span className="ui-kpi-value ui-num">
          {value === null ? "—" : usdFromCents(value)}
        </span>
      </span>
      {note !== undefined && <span className="ui-kpi-note">{note}</span>}
    </a>
  );
}

/**
 * The Owner's money on Home ("Financial summary"): four cards (owner 14/11/2026), shown to the Owner only
 * (ledger.owner_money with ledger.read). Owner 12/11/2026: the box no longer says so in words.
 */
export function OwnerMoney({
  language,
  propertyId,
  active,
  api,
  today,
}: {
  language: Language;
  propertyId: string;
  active: boolean;
  api: Pick<LedgerApi, "report">;
  today: string;
}) {
  const [numbers, setNumbers] = useState<OwnerMoneyNumbers | null>(null);
  useEffect(() => {
    if (!active || propertyId === "") return;
    let current = true;
    const month = `${today.slice(0, 7)}-01`;
    const read = <T,>(
      name: Parameters<LedgerApi["report"]>[1],
      query: Parameters<LedgerApi["report"]>[2],
      pick: (report: Report) => T,
    ): Promise<T | null> =>
      api.report(propertyId, name, query).then(pick, () => null);
    void Promise.all([
      read("balance-sheet", { as_of: today }, cashOf),
      read("customer-aging", {}, owedOf),
      read("budget", { month }, spentOf),
      read("profit-and-loss", { month }, profitOf),
    ]).then(([cash, owed, spent, profit]) => {
      if (!current) return;
      setNumbers({
        cash,
        owe: owed?.owe ?? null,
        over30: owed?.over30 ?? null,
        spent: spent?.spent ?? null,
        budget: spent?.budget ?? null,
        profit,
        year: today.slice(0, 4),
      });
    });
    return () => {
      current = false;
    };
  }, [active, api, propertyId, today]);
  if (numbers === null) return null;
  const over = (numbers.spent ?? 0) > (numbers.budget ?? 0);
  return (
    <section aria-labelledby="home-owner-money" className="ui-card">
      <div className="ui-chead">
        <h2 id="home-owner-money">{hmt(language, "om_t")}</h2>
      </div>
      <CardGrid className="ui-home-kpis ui-om" five>
        <MoneyCard
          icon="payments"
          label={hmt(language, "om_cash")}
          page="statements"
          show="balance-sheet"
          tone="brand"
          value={numbers.cash}
        />
        {/* Owner 14/11/2026: no "Customers owe" card; it is the same number as Unpaid. */}
        <MoneyCard
          icon="history"
          label={hmt(language, "om_over")}
          page="statements"
          show="customer-aging"
          tone={(numbers.over30 ?? 0) > 0 ? "err" : "ok"}
          value={numbers.over30}
        />
        <MoneyCard
          icon="list"
          label={hmt(language, "om_spent")}
          note={
            (numbers.budget ?? 0) > 0
              ? hmt(language, "om_spent_s", usdFromCents(numbers.budget ?? 0))
              : hmt(language, "om_nobudget")
          }
          page="statements"
          show="budget"
          tone={(numbers.budget ?? 0) > 0 && over ? "err" : "info"}
          value={numbers.spent}
        />
        <MoneyCard
          icon="reports"
          label={hmt(language, "om_profit")}
          page="statements"
          show="profit-and-loss"
          tone={(numbers.profit ?? 0) >= 0 ? "ok" : "err"}
          value={numbers.profit}
        />
      </CardGrid>
    </section>
  );
}

/** Attendance lines that need a look today: scans to check and people with no check-out. */
export function attendanceToCheck(day: AttendanceDay): {
  total: number;
  scans: number;
  noOut: number;
} {
  const scans = day.people.filter((line) =>
    line.scans.some((scan) => scan.needs_check && !scan.accepted),
  ).length;
  const noOut = day.people.filter((line) => line.no_check_out === true).length;
  const total = day.people.filter(
    (line) =>
      line.no_check_out === true ||
      line.scans.some((scan) => scan.needs_check && !scan.accepted),
  ).length;
  return { total, scans, noOut };
}
