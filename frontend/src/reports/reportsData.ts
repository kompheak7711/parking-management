// V1-060 B6: what the Reports screens need besides their words: the list of reports and who may
// read them, the period of the parameter bar, safe reads of the register summaries (their
// fields differ by register; ops/V1_057_PLAN.md) and the number formats of the tables.

import type { RegisterName, TotalsReport } from "../reportsClient";
import { dayText, momentText } from "../shell/format";
import type { ShellIcon } from "../shell/icons";
import type { Language } from "../signInText";
import { rpt } from "./text";

export type ReportKey = TotalsReport | RegisterName;

interface DefBase {
  icon: ShellIcon;
  /** Every right the report needs; the server checks the same ones. */
  needs: readonly string[];
  /** Money, audit and export reports carry the "Owner and Manager" tag (mock-up round 4). */
  tagged: boolean;
}

export type ReportDef =
  | (DefBase & { kind: "totals"; key: TotalsReport })
  | (DefBase & { kind: "register"; key: RegisterName });

const MONEY = ["reports.read"] as const;

// The owner's order (14/10/2026): the four Totals tables, then the registers and lists.
export const REPORTS: readonly ReportDef[] = [
  {
    kind: "totals",
    key: "total_income",
    icon: "invoice",
    needs: MONEY,
    tagged: true,
  },
  {
    kind: "totals",
    key: "total_payment",
    icon: "payments",
    needs: MONEY,
    tagged: true,
  },
  {
    kind: "totals",
    key: "total_electricity",
    icon: "zap",
    needs: MONEY,
    tagged: true,
  },
  {
    kind: "totals",
    key: "total_water",
    icon: "drop",
    needs: MONEY,
    tagged: true,
  },
  {
    kind: "register",
    key: "invoice_register",
    icon: "invoice",
    needs: MONEY,
    tagged: true,
  },
  {
    kind: "register",
    key: "payments",
    icon: "payments",
    needs: MONEY,
    tagged: true,
  },
  {
    kind: "register",
    key: "utility_consumption",
    icon: "meter",
    needs: ["utility.read"],
    tagged: false,
  },
  {
    kind: "register",
    key: "credit_ledger",
    icon: "customers",
    needs: MONEY,
    tagged: true,
  },
  {
    kind: "register",
    key: "deposits",
    icon: "lock",
    needs: MONEY,
    tagged: true,
  },
  {
    kind: "register",
    key: "final_settlements",
    icon: "moveout",
    needs: MONEY,
    tagged: true,
  },
  {
    kind: "register",
    key: "unit_occupancy",
    icon: "units",
    needs: ["units.read", "leases.read", "reservations.read"],
    tagged: false,
  },
  {
    kind: "register",
    key: "lease_dates",
    icon: "lease",
    needs: ["leases.read"],
    tagged: false,
  },
  {
    kind: "register",
    key: "audit_activity",
    icon: "history",
    needs: ["audit.view"],
    tagged: true,
  },
];

export function reportDef(key: string | null): ReportDef | null {
  return REPORTS.find((def) => def.key === key) ?? null;
}

/** May the person read this report? Unknown access (null) shows everything. */
export function mayRead(
  def: ReportDef,
  capabilities: ReadonlySet<string> | null,
): boolean {
  return (
    capabilities === null ||
    def.needs.every((capability) => capabilities.has(capability))
  );
}

/** An export needs data.export and the report's own read rights (DL-072 answer 14). */
export function mayExport(
  def: ReportDef,
  capabilities: ReadonlySet<string> | null,
): boolean {
  return (
    capabilities === null ||
    (capabilities.has("data.export") && mayRead(def, capabilities))
  );
}

// Unit occupancy and Deposit liability show today; the period does not apply to them.
const TODAY_ONLY: ReadonlySet<ReportKey> = new Set<ReportKey>([
  "deposits",
  "unit_occupancy",
]);

export function periodApplies(key: ReportKey): boolean {
  return !TODAY_ONLY.has(key);
}

/** Audit activity counts the whole Property; the floor does not apply to it. */
export function floorApplies(key: ReportKey): boolean {
  return key !== "audit_activity";
}

export type Period = "all" | "month" | "last" | "pick";

/** The parameter bar, shared by every report while the page is open. */
export interface Params {
  period: Period;
  /** The picked days (yyyy-mm-dd) for Pick dates. */
  from: string;
  to: string;
  /** "" is the whole Property. */
  floor: string;
  /** "" is All Units (the Totals tables). */
  unitId: string;
}

export const START_PARAMS: Params = {
  period: "all",
  from: "",
  to: "",
  floor: "",
  unitId: "",
};

/** The first and last day of the period (yyyy-mm-dd); null for All. */
export function rangeOf(
  params: Pick<Params, "period" | "from" | "to">,
  today: string,
): [string, string] | null {
  if (params.period === "month") return [`${today.slice(0, 7)}-01`, today];
  if (params.period === "last") {
    const end = new Date(`${today.slice(0, 7)}-01T00:00:00Z`);
    end.setUTCDate(0);
    const last = end.toISOString().slice(0, 10);
    return [`${last.slice(0, 7)}-01`, last];
  }
  if (params.period === "pick" && params.from !== "" && params.to !== "") {
    return [params.from, params.to];
  }
  return null;
}

/** V1-060 B7: the Totals tables count whole months, so picked days widen to their months. */
export function wholeMonths(range: [string, string]): [string, string] {
  const end = new Date(`${range[1].slice(0, 7)}-01T00:00:00Z`);
  end.setUTCMonth(end.getUTCMonth() + 1, 0);
  return [`${range[0].slice(0, 7)}-01`, end.toISOString().slice(0, 10)];
}

/** "01/10/2026 to 28/10/2026", or "All dates". */
export function rangeText(
  language: Language,
  range: [string, string] | null,
): string {
  return range === null
    ? rpt(language, "all_dates")
    : rpt(language, "range", dayText(range[0]), dayText(range[1]));
}

/** A floor named only by its number shows as "Floor 2" (as on the Units screens). */
export function floorName(language: Language, floor: string): string {
  return /^\d+$/.test(floor) ? rpt(language, "floor_n", floor) : floor;
}

// Safe reads of the summary, chart and totals of a register: a missing field reads as zero or
// empty, so a field the server leaves out (no money right) never breaks the page.
export type Bag = Record<string, unknown>;

function isBag(value: unknown): value is Bag {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function num(source: unknown, key: string): number {
  const value = isBag(source) ? source[key] : undefined;
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

export function has(source: unknown, key: string): boolean {
  return isBag(source) && typeof source[key] === "number";
}

export function str(source: unknown, key: string): string {
  const value = isBag(source) ? source[key] : undefined;
  return typeof value === "string" ? value : "";
}

export function bag(source: unknown, key: string): Bag {
  const value = isBag(source) ? source[key] : undefined;
  return isBag(value) ? value : {};
}

export function items(source: unknown, key: string): Bag[] {
  const value = isBag(source) ? source[key] : undefined;
  return Array.isArray(value) ? value.filter(isBag) : [];
}

/** "1234.5" → "1,234.5": a decimal from the server, grouped and never rounded. */
export function decimalText(value: string): string {
  const match = /^(-?)(\d+)(\.\d+)?$/.exec(value.trim());
  if (match === null) return value;
  const [, sign = "", whole = "", fraction = ""] = match;
  return `${sign}${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}${fraction}`;
}

/** A count or a quantity for a chart: 1234.5 → "1,234.5". */
export function numberText(value: number): string {
  return value.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

/** 184263 → "184,263 ៛" (information only; never added to USD). */
export function rielText(amount: number): string {
  return `${amount.toLocaleString("en-US")} ៛`;
}

/** Whole dollars for a chart axis: 125000 cents → "$1,250". */
export function axisUsd(cents: number): string {
  const dollars = Math.round(Math.abs(cents) / 100);
  return `${cents < 0 ? "-" : ""}$${dollars.toLocaleString("en-US")}`;
}

/** "Generated 28/10/2026, 10:30" uses the moment the report was read, in Phnom Penh. */
export function generatedText(milliseconds: number): string {
  const moment = momentText(new Date(milliseconds).toISOString());
  return `${moment.slice(0, 10)}, ${moment.slice(11)}`;
}

/** "kWh" or "m³" for a measurement unit code from the server. */
export function measureText(code: string): string {
  return code.toUpperCase() === "M3" ? "m³" : "kWh";
}
