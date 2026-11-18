// V1-058 R6: Home (DESIGN.md "Home layout", mock-up v43): the page head with "Receive payment"
// and "Enter meter readings", the cards, and the "What to do" list. The numbers come from the
// V1-057 Home read; a card or a to-do kind the person may not read is missing from the answer,
// so it is not shown.
// Owner 12/11/2026: the cards and their order are Vacant Units, Viewing requests waiting,
// Leases ending soon, Short stay bookings, Short stays checked in, Pending payment, Paid this
// month, Overdue, Approvals, Meter readings missing, Notices due, Problem reports, Birthdays,
// Low stock, Attendance; every card shows its number at the top right, beside its name.
// Home screen review (owner 14/11/2026): shorter names (Viewing requests, Bookings, Checked in,
// Missing readings); a card has a note only when it tells something the number does not.

import {
  GENERAL_LEDGER,
  HR,
  PRODUCTS,
  PROBLEM_REPORTS,
  SHORT_STAYS,
  TELEGRAM,
} from "../leases/parking";
import "../shell/screens.css";

import {
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import {
  type HomeCards,
  type HomePage,
  ReportsNotAllowedError,
  type TodoGroup,
  type TodoItem,
} from "../reportsClient";
import { dayText, momentText, usdFromCents } from "../shell/format";
import { Icon, type ShellIcon } from "../shell/icons";
import {
  type PageId,
  hashForPage,
  pageName,
  queryFromHash,
} from "../shell/navigation";
import { CardGrid, PageHeader } from "../shell/layouts";
import { hashForShow } from "../shell/useHashPage";
import type { Language } from "../signInText";
import {
  type ProblemSummary,
  type ProblemsApi,
  problemsApi as defaultProblemsApi,
} from "../problems/problemsClient";
import { costText } from "../problems/RepairCost";
import { type HomeTextKey, hmt } from "./text";
import { type HrApi, hrApi as defaultHrApi } from "../hr/hrClient";
import {
  type LedgerApi,
  ledgerApi as defaultLedgerApi,
} from "../ledger/ledgerClient";
import { OwnerMoney, attendanceToCheck } from "./OwnerMoney";
import {
  type ProductsApi,
  productsApi as defaultProductsApi,
} from "../products/productsClient";
import {
  type Booking,
  type ShortStaysApi,
  shortStaysApi as defaultShortStaysApi,
} from "../shortstays/shortStaysClient";
import {
  type TelegramApi,
  telegramApi as defaultTelegramApi,
} from "../telegram/telegramClient";

export interface HomeApi {
  home: (propertyId: string) => Promise<HomePage>;
}

export interface HomeScreenProps {
  language: Language;
  propertyId: string;
  /** Home reads again each time it is opened. */
  active: boolean;
  homeApi: HomeApi;
  capabilities: ReadonlySet<string> | null;
  /** DL-131: the Problem reports card, read only by a person who may see Problem reports. */
  problemsApi?: Pick<ProblemsApi, "summary">;
  /** UI v81: the Financial summary box (ledger.owner_money and ledger.read). */
  ledgerApi?: Pick<LedgerApi, "report">;
  /** UI v81: the Attendance card (hr.attendance.read). */
  attendanceApi?: Pick<HrApi, "day">;
  /** UI v81 round 2: the Viewing requests waiting card (visit_requests.read). */
  visitsApi?: Pick<TelegramApi, "visitRequests">;
  /** Owner 12/11/2026: the two Short stays cards (short_stays.read). */
  shortStaysApi?: Pick<ShortStaysApi, "list">;
  /** Owner 12/11/2026: the Low stock card (products.read). */
  productsApi?: Pick<ProductsApi, "catalogue">;
}

/** The two Short stays cards: bookings still to check in, and guests staying now. */
export interface StaysNow {
  booked: number;
  arriveToday: number;
  checkedIn: number;
  outToday: number;
}

/**
 * Counts the bookings by their status as the server gave it: "Booked" has not checked in yet,
 * "Checked in" is staying now. `today` is the Property's business date ("yyyy-mm-dd").
 */
export function staysNowOf(
  bookings: readonly {
    status: string;
    check_in_on: string;
    check_out_on: string;
  }[],
  today: string,
): StaysNow {
  const day = today.slice(0, 10);
  const booked = bookings.filter((item) => item.status === "BOOKED");
  const staying = bookings.filter((item) => item.status === "CHECKED_IN");
  return {
    booked: booked.length,
    arriveToday: booked.filter((item) => item.check_in_on.slice(0, 10) === day)
      .length,
    checkedIn: staying.length,
    outToday: staying.filter((item) => item.check_out_on.slice(0, 10) === day)
      .length,
  };
}

/** Products the server marks as low stock (stock at or below the reorder level), still sold. */
export function lowStockOf(
  products: readonly { low_stock: boolean; discontinued: boolean }[],
): number {
  return products.filter((item) => item.low_stock && !item.discontinued).length;
}

/** The Viewing requests card: new requests nobody took yet, how many are late, visits this week. */
export interface VisitsWaiting {
  waiting: number;
  late: number;
  visitsThisWeek: number;
}

/** Monday to Sunday of the week that holds `today` ("yyyy-mm-dd"), as a "yyyy-mm-dd" pair. */
function weekOf(today: string): [string, string] {
  const start = new Date(`${today.slice(0, 10)}T00:00:00Z`);
  const shift = (start.getUTCDay() + 6) % 7;
  start.setUTCDate(start.getUTCDate() - shift);
  const end = new Date(start);
  end.setUTCDate(start.getUTCDate() + 6);
  return [start.toISOString().slice(0, 10), end.toISOString().slice(0, 10)];
}

export function visitsWaitingOf(
  requests: readonly {
    status: string;
    late: boolean;
    visit_local: string | null;
  }[],
  today: string,
): VisitsWaiting {
  const [from, to] = weekOf(today);
  return {
    waiting: requests.filter((item) => item.status === "NEW").length,
    late: requests.filter((item) => item.status === "NEW" && item.late).length,
    visitsThisWeek: requests.filter((item) => {
      const day = item.visit_local?.slice(0, 10) ?? "";
      return day >= from && day <= to;
    }).length,
  };
}

type Tone = "err" | "warn" | "info" | "neutral" | "ok" | "brand";

/** Whole days from `from` to `to`, both "yyyy-mm-dd". */
function daysBetween(from: string, to: string): number {
  const start = Date.parse(`${from.slice(0, 10)}T00:00:00Z`);
  const end = Date.parse(`${to.slice(0, 10)}T00:00:00Z`);
  return Math.round((end - start) / 86_400_000);
}

// Kinds whose date is a deadline: a past date is "late". The others record when something
// started waiting, so a past date is "ago".
const DEADLINE_KINDS = new Set<TodoItem["kind"]>([
  "overdue_initial_rent",
  "lease_ending",
  "reservation_expiring",
  "readings_missing",
  "letter_day_20",
  "letter_day_30",
  "refund_due",
]);

function relativeText(language: Language, item: TodoItem, today: string) {
  const days = daysBetween(today, item.date);
  if (days === 0) return hmt(language, "rel_today");
  if (days === 1) return hmt(language, "rel_tomorrow");
  if (days > 1) return hmt(language, "rel_in", days);
  if (DEADLINE_KINDS.has(item.kind)) {
    return days === -1
      ? hmt(language, "rel_late1")
      : hmt(language, "rel_late", -days);
  }
  return days === -1
    ? hmt(language, "rel_yesterday")
    : hmt(language, "rel_ago", -days);
}

const DRAFT_KINDS = new Set([
  "REFUND",
  "DEPOSIT_FORFEITURE",
  "PAYMENT_MOVE",
  "FINAL_SETTLEMENT",
  "SETTLEMENT_CORRECTION",
]);

interface Row {
  icon: ShellIcon;
  title: string;
  detail: string;
  href: string;
  tip: string;
}

function rowOf(language: Language, item: TodoItem): Row | null {
  const unit = item.unit_number ?? "";
  const customer = item.customer_name ?? "";
  const join = (...parts: string[]) => parts.filter(Boolean).join(" · ");
  switch (item.kind) {
    case "overdue_initial_rent":
      return {
        icon: "alert",
        title: hmt(
          language,
          "r_over",
          item.invoice_number ?? "",
          usdFromCents(item.balance_usd_cents ?? 0),
        ),
        detail: hmt(language, "r_over_d", customer, unit),
        href: hashForPage("invoices", `inv:${item.invoice_id ?? ""}`),
        tip: hmt(language, "tip_inv"),
      };
    case "lease_ending":
      return {
        icon: "lease",
        title: hmt(language, "r_lease", unit),
        detail: hmt(language, "r_lease_d", customer),
        href: hashForPage("leases", item.lease_id ?? ""),
        tip: hmt(language, "tip_lease"),
      };
    case "reservation_expiring":
      return {
        icon: "calendar",
        title: hmt(language, "r_resv", unit),
        detail: customer,
        href: hashForPage("reservations", item.reservation_id ?? ""),
        tip: hmt(language, "tip_resv"),
      };
    case "draft_waiting": {
      const kind =
        item.draft_kind !== undefined && DRAFT_KINDS.has(item.draft_kind)
          ? (`dk_${item.draft_kind}` as HomeTextKey)
          : "dk_other";
      return {
        icon: "check",
        title: hmt(language, "r_appr", hmt(language, kind)),
        detail: hmt(language, "r_appr_d", dayText(item.date)),
        href: hashForPage("approvals"),
        tip: hmt(language, "tip_appr"),
      };
    }
    case "deposit_decision":
      return {
        icon: "calendar",
        title: hmt(language, "r_depdec", unit),
        detail: customer,
        href: hashForPage("reservations", item.reservation_id ?? ""),
        tip: hmt(language, "tip_resv"),
      };
    case "readings_missing":
      return {
        icon: "meter",
        title: hmt(language, "r_read"),
        detail: hmt(language, "r_read_d", item.count ?? 0),
        href: hashForPage("utilities"),
        tip: hmt(language, "tip_read"),
      };
    case "letter_day_20":
    case "letter_day_30":
      return {
        icon: "list",
        title: hmt(
          language,
          "r_letter",
          hmt(language, item.kind === "letter_day_20" ? "day20" : "day30"),
          unit,
        ),
        detail: join(customer, item.invoice_number ?? ""),
        href: hashForPage("letters"),
        tip: hmt(language, "tip_letter"),
      };
    case "settlement_open":
      return {
        icon: "moveout",
        title: hmt(language, "r_settle", unit),
        detail: customer,
        href: hashForPage("leases", item.lease_id ?? ""),
        tip: hmt(language, "tip_lease"),
      };
    case "refund_due":
      return {
        icon: "payments",
        title: hmt(language, "r_refund", unit),
        detail: hmt(
          language,
          "r_refund_d",
          customer,
          usdFromCents(item.held_usd_cents ?? 0),
        ),
        href: hashForPage("leases", item.lease_id ?? ""),
        tip: hmt(language, "tip_lease"),
      };
    default:
      // A kind added on the server later is left out until Home knows its words.
      return null;
  }
}

/**
 * The group a row shows in. The server groups by date, but for things that wait for a
 * person (a draft, a Deposit decision, an open Final Settlement) the date is when the wait
 * began, so a past date means "do it today", as in the mock-up, not "overdue".
 */
function groupOf(item: TodoItem, today: string): TodoGroup {
  if (!DEADLINE_KINDS.has(item.kind) && item.date.slice(0, 10) <= today) {
    return "today";
  }
  return item.group;
}

/**
 * The parts of a note that are above 0, joined with " · " ("1 urgent · 2 late"); no note when
 * every part is 0 (owner 14/11/2026: "0 urgent · 0 late" says nothing).
 */
export function partsText(
  parts: readonly (readonly [number, string])[],
): string | undefined {
  const shown = parts.filter(([count]) => count > 0).map(([, text]) => text);
  return shown.length === 0 ? undefined : shown.join(" · ");
}

/**
 * Meter readings still missing. Before the Reading day no reading is late yet, so the card
 * shows 0 (Home screen review, owner 14/11/2026; the Utilities page also waits for the
 * Reading day). `today` and the Reading day are "yyyy-mm-dd".
 */
export function readingsMissing(
  readings: { count: number; reading_date: string },
  today: string,
): number {
  return today.slice(0, 10) < readings.reading_date.slice(0, 10)
    ? 0
    : readings.count;
}

function Card({
  icon,
  tone,
  label,
  value,
  note,
  page,
  show,
  more,
  empty,
  money = false,
}: {
  icon: ShellIcon;
  tone: Tone;
  label: string;
  value: string;
  /**
   * Home screen review (owner 14/11/2026 00:23): a card has a note only when it tells
   * something the number does not; a line that only says what the card opens, or "nothing",
   * is not drawn.
   */
  note?: string;
  page: PageId;
  /**
   * UI v81 round 11 (owner 12/11/2026): the part of that page the card counts, so the card
   * opens it and not the whole list ("#/invoices?show=overdue"). `more` holds further words
   * ("period=month"). Left out when the page has one view.
   */
  show?: string;
  more?: Record<string, string>;
  empty: boolean;
  /** An amount of money: it stays at the top right while the name may take two lines. */
  money?: boolean;
}) {
  return (
    <a
      className={`ui-kpi ui-home-kpi ui-kpi-top${money ? " ui-kpi-amount" : ""} ${empty ? "none" : tone}`}
      href={
        show === undefined ? hashForPage(page) : hashForShow(page, show, more)
      }
    >
      {/* Owner 12/11/2026: the number sits at the top right, beside the name. */}
      <span className="ui-kpi-head">
        <span className="ui-kpi-label">
          <span className="ui-kpi-icon">
            <Icon name={icon} small />
          </span>
          <span>{label}</span>
        </span>
        <span className="ui-kpi-value ui-num">{value}</span>
      </span>
      {note !== undefined && note !== "" && (
        <span className="ui-kpi-note">{note}</span>
      )}
    </a>
  );
}

/** What the Attendance card shows: lines to check on today's sheet. */
type AttendanceNow = ReturnType<typeof attendanceToCheck>;

function Cards({
  language,
  cards,
  today,
  visits,
  problems,
  stays,
  lowStock,
  attendance,
}: {
  language: Language;
  cards: HomeCards;
  today: string;
  /** Cards from other reads; each is null for a person who may not read it. */
  visits: VisitsWaiting | null;
  problems: ProblemSummary | null;
  stays: StaysNow | null;
  lowStock: number | null;
  attendance: AttendanceNow | null;
}) {
  // Owner 12/11/2026: the order is Vacant Units, Viewing requests waiting, Leases ending soon,
  // the two Short stays cards, the three money cards, Approvals, Meter readings missing,
  // Notices due, Problem reports, Birthdays, Low stock, Attendance.
  const shown: ReactNode[] = [];
  const units = cards.units_occupied;
  if (units !== undefined) {
    shown.push(
      <Card
        empty={units.vacant === 0}
        icon="units"
        key="vacant"
        label={hmt(language, "k_vac")}
        note={hmt(language, "k_vac_s", units.total, units.reserved)}
        page="units"
        show="vacant"
        tone="brand"
        value={String(units.vacant)}
      />,
    );
  }
  if (visits !== null) {
    shown.push(
      <Card
        empty={visits.waiting === 0}
        icon="door"
        key="visits"
        label={hmt(language, "n_vr")}
        note={partsText([
          [visits.late, hmt(language, "n_vr_late", visits.late)],
          [
            visits.visitsThisWeek,
            hmt(language, "n_vr_week", visits.visitsThisWeek),
          ],
        ])}
        page="visitreqs"
        show="waiting"
        tone={visits.late > 0 ? "err" : "brand"}
        value={String(visits.waiting)}
      />,
    );
  }
  const renewal = cards.lease_renewal;
  if (renewal !== undefined) {
    shown.push(
      <Card
        empty={renewal.count === 0}
        icon="lease"
        key="renewal"
        label={hmt(language, "n_lease")}
        note={hmt(language, "n_lease_s", dayText(renewal.end_on_or_before))}
        page="leases"
        show="ending"
        tone="info"
        value={String(renewal.count)}
      />,
    );
  }
  if (stays !== null) {
    // Only a count above 0 is said ("2 arrive today"); "None arrive today" is not drawn.
    const countText = (count: number, one: HomeTextKey, many: HomeTextKey) =>
      count === 0 ? undefined : hmt(language, count === 1 ? one : many, count);
    shown.push(
      <Card
        empty={stays.booked === 0}
        icon="calendar"
        key="stays-booked"
        label={hmt(language, "n_ssb")}
        note={countText(stays.arriveToday, "n_ssb_s1", "n_ssb_s")}
        page="shortstays"
        show="booked"
        tone="info"
        value={String(stays.booked)}
      />,
      <Card
        empty={stays.checkedIn === 0}
        icon="moveout"
        key="stays-in"
        label={hmt(language, "n_ssin")}
        note={countText(stays.outToday, "n_ssin_s1", "n_ssin_s")}
        page="shortstays"
        show="checked_in"
        tone="ok"
        value={String(stays.checkedIn)}
      />,
    );
  }
  const pending = cards.pending_payment;
  if (pending !== undefined) {
    shown.push(
      <Card
        empty={pending.amount_usd_cents === 0}
        icon="invoice"
        key="pending"
        label={hmt(language, "k_pend")}
        money
        page="invoices"
        show="open"
        tone="warn"
        value={usdFromCents(pending.amount_usd_cents)}
      />,
    );
  }
  const paid = cards.paid_this_month;
  if (paid !== undefined) {
    const label = hmt(language, "k_paid");
    // Owner 16/11/2026: "Paid this month" is the money received this month, the same amount as
    // "Total received" on the Payments page (This month), and it opens that page. Only a person
    // who cannot read Payments sees the paid part of this month's Invoices instead.
    if (paid.received_usd_cents !== undefined) {
      shown.push(
        <Card
          empty={paid.received_usd_cents === 0}
          icon="payments"
          key="paid"
          label={label}
          money
          page="payments"
          tone="ok"
          value={usdFromCents(paid.received_usd_cents)}
        />,
      );
    } else if (paid.billed_usd_cents !== undefined) {
      const settled = paid.billed_paid_usd_cents ?? 0;
      shown.push(
        <Card
          empty={settled === 0}
          icon="payments"
          key="paid"
          label={label}
          money
          more={{ period: "month" }}
          page="invoices"
          show="paid"
          tone="ok"
          value={usdFromCents(settled)}
        />,
      );
    }
  }
  const overdue = cards.overdue;
  if (overdue !== undefined) {
    shown.push(
      <Card
        empty={overdue.amount_usd_cents === 0}
        icon="alert"
        key="overdue"
        label={hmt(language, "k_over")}
        money
        page="invoices"
        show="overdue"
        tone="err"
        value={usdFromCents(overdue.amount_usd_cents)}
      />,
    );
  }
  const waiting = cards.waiting_for_approval;
  if (waiting !== undefined) {
    shown.push(
      <Card
        empty={waiting.count === 0}
        icon="check"
        key="waiting"
        label={hmt(language, "n_appr")}
        note={
          waiting.money_out_count > 0
            ? hmt(
                language,
                "n_appr_m",
                usdFromCents(waiting.money_out_usd_cents),
              )
            : undefined
        }
        page="approvals"
        tone="warn"
        value={String(waiting.count)}
      />,
    );
  }
  const readings = cards.meter_readings_missing;
  if (readings !== undefined) {
    const missing = readingsMissing(readings, today);
    shown.push(
      <Card
        empty={missing === 0}
        icon="meter"
        key="readings"
        label={hmt(language, "n_read")}
        page="utilities"
        show="missing"
        tone="info"
        value={String(missing)}
      />,
    );
  }
  const letters = cards.letters_due;
  if (letters !== undefined) {
    shown.push(
      <Card
        empty={letters.count === 0}
        icon="list"
        key="letters"
        label={hmt(language, "n_letters")}
        page="letters"
        show="due"
        tone="err"
        value={String(letters.count)}
      />,
    );
  }
  if (problems !== null) {
    shown.push(
      <Card
        empty={problems.open === 0}
        icon="wrench"
        key="problems"
        label={hmt(language, "n_problems")}
        note={partsText([
          [
            problems.urgent,
            hmt(language, "n_problems_urgent", problems.urgent),
          ],
          [problems.late, hmt(language, "n_problems_late", problems.late)],
        ])}
        page="problems"
        show="open"
        tone={problems.urgent > 0 || problems.late > 0 ? "err" : "info"}
        value={String(problems.open)}
      />,
    );
  }
  const birthdays = cards.birthdays;
  if (birthdays !== undefined) {
    shown.push(
      <Card
        empty={birthdays.count === 0}
        icon="customers"
        key="birthdays"
        label={hmt(language, "n_bday")}
        note={hmt(language, "n_week_s", dayText(birthdays.to))}
        page="customers"
        show="birthdays"
        tone="info"
        value={String(birthdays.count)}
      />,
    );
  }
  if (lowStock !== null) {
    shown.push(
      <Card
        empty={lowStock === 0}
        icon="box"
        key="lowstock"
        label={hmt(language, "n_low")}
        page="products"
        show="low"
        tone="warn"
        value={String(lowStock)}
      />,
    );
  }
  if (attendance !== null) {
    shown.push(
      <Card
        empty={attendance.total === 0}
        icon="staff"
        key="attendance"
        label={hmt(language, "at_t")}
        note={
          attendance.total > 0
            ? hmt(language, "at_n", attendance.scans, attendance.noOut)
            : undefined
        }
        page="attendance"
        show="day"
        tone={attendance.total > 0 ? "warn" : "ok"}
        value={String(attendance.total)}
      />,
    );
  }
  if (shown.length === 0) return null;
  return (
    <CardGrid className="ui-home-kpis" five>
      {shown}
    </CardGrid>
  );
}

/** Home lists each repair cost still waiting for a Manager's check (mock-up round 32 A5). */
function CostsToCheck({
  language,
  summary,
}: {
  language: Language;
  summary: ProblemSummary;
}) {
  if (summary.costs_to_check.length === 0) return null;
  return (
    <section aria-labelledby="home-costs" className="ui-card">
      <h2 id="home-costs">{hmt(language, "n_costs")}</h2>
      <ul className="ui-plain">
        {summary.costs_to_check.map((item) => (
          <li key={item.report_id}>
            <a
              className="ui-num"
              href={hashForPage("problems", `pr:${item.report_id}`)}
            >
              {item.report_number}
            </a>{" "}
            ·{" "}
            {item.unit_number ??
              (language === "km" ? item.place_kh : null) ??
              item.place_en ??
              ""}{" "}
            ·{" "}
            {item.totals
              .map((total) => costText(total.currency, total.amount_minor))
              .join(" + ")}
          </li>
        ))}
      </ul>
    </section>
  );
}

// UI v81 round 3 (owner 07/11/2026 17:30): the Tasks are four cards in one row (two by two on a
// phone): Overdue, Today, This week, Later. Each shows its count and one short line; the chosen
// card's list opens under the cards, one list at a time, and the chosen card is kept in the
// address ("#/home?tasks=overdue") so Back returns to it. On open, Overdue is open when it has
// items; otherwise no list is open.
const TASK_CARDS: readonly {
  group: TodoGroup;
  tone: Tone;
  icon: ShellIcon;
  /** The word kept in the address. */
  word: string;
}[] = [
  { group: "overdue", tone: "err", icon: "alert", word: "overdue" },
  { group: "today", tone: "warn", icon: "check", word: "today" },
  { group: "this_week", tone: "info", icon: "calendar", word: "week" },
  { group: "later", tone: "neutral", icon: "list", word: "later" },
];

/** The Tasks card named in the address ("#/home?tasks=week"), or null. */
export function tasksFromHash(hash: string): TodoGroup | null {
  const word = queryFromHash(hash, "tasks");
  const card = TASK_CARDS.find((candidate) => candidate.word === word);
  return card === undefined ? null : card.group;
}

function tasksHash(group: TodoGroup | null): string {
  const home = hashForPage("home");
  if (group === null) return home;
  const card = TASK_CARDS.find((candidate) => candidate.group === group);
  return card === undefined ? home : `${home}?tasks=${card.word}`;
}

function TodoList({ language, page }: { language: Language; page: HomePage }) {
  const known = page.todo.filter((item) => rowOf(language, item) !== null);
  const inGroup = (group: TodoGroup) =>
    known.filter((item) => groupOf(item, page.business_date) === group);
  const counts = {
    overdue: inGroup("overdue").length,
    today: inGroup("today").length,
    this_week: inGroup("this_week").length,
  };
  const [chosen, setChosen] = useState<TodoGroup | null>(
    () =>
      tasksFromHash(window.location.hash) ??
      (counts.overdue > 0 ? "overdue" : null),
  );
  function choose(group: TodoGroup) {
    const next = chosen === group ? null : group;
    setChosen(next);
    window.history.replaceState(null, "", tasksHash(next));
  }
  // The earliest item of a group names its line: "Oldest: 29 days late", "Next: in 2 days".
  const earliest = (items: TodoItem[]) =>
    items.reduce((first, item) => (item.date < first.date ? item : first));
  const lineOf = (group: TodoGroup, items: TodoItem[]) => {
    // Owner 14/11/2026: no "Nothing overdue", "Nothing here" or "Do them today" line.
    if (items.length === 0 || group === "today") return "";
    const when = relativeText(language, earliest(items), page.business_date);
    return hmt(language, group === "overdue" ? "tk_oldest" : "tk_next", when);
  };
  const open = TASK_CARDS.find((card) => card.group === chosen);
  const openItems = open === undefined ? [] : inGroup(open.group);
  return (
    <section aria-labelledby="home-todo" className="ui-card ui-todo-card">
      {/* UI v81 round 4 (owner 08/11/2026): no summary line; the four cards say it. */}
      <header>
        <h2 id="home-todo">{hmt(language, "todo_t")}</h2>
      </header>
      <CardGrid label={hmt(language, "todo_t")} tasks>
        {TASK_CARDS.map(({ group, tone, icon }) => {
          const items = inGroup(group);
          return (
            <button
              aria-controls="home-tasks-list"
              aria-pressed={chosen === group}
              className={`ui-kpi ui-kpi-top ${items.length === 0 ? "none" : tone}`}
              key={group}
              onClick={() => {
                choose(group);
              }}
              type="button"
            >
              <span className="ui-kpi-head">
                <span className="ui-kpi-label">
                  <span className="ui-kpi-icon">
                    <Icon name={icon} small />
                  </span>
                  <span>{hmt(language, `g_${group}`)}</span>
                </span>
                <span className="ui-kpi-value ui-num">{items.length}</span>
              </span>
              {lineOf(group, items) !== "" && (
                <span className="ui-kpi-note">{lineOf(group, items)}</span>
              )}
            </button>
          );
        })}
      </CardGrid>
      <div
        className="ui-tasks-list"
        hidden={open === undefined || openItems.length === 0}
        id="home-tasks-list"
      >
        {open !== undefined && openItems.length > 0 && (
          <>
            <h3>
              <span className={`ui-dot ${open.tone}`} />
              {hmt(language, `g_${open.group}`)}
              <span className="ui-count ui-num">{openItems.length}</span>
            </h3>
            <ul className="ui-todos">
              {openItems.map((item, index) => {
                const row = rowOf(language, item);
                if (row === null) return null;
                return (
                  <li
                    className={`ui-todo ${open.tone}`}
                    key={`${item.kind}:${item.date}:${String(index)}`}
                  >
                    <span aria-hidden="true" className="ui-todo-icon">
                      <Icon name={row.icon} />
                    </span>
                    <span className="ui-todo-body">
                      <b>{row.title}</b>
                      {row.detail !== "" && <span>{row.detail}</span>}
                    </span>
                    <span className="ui-when ui-num">
                      {dayText(item.date)}
                      <small>
                        {relativeText(language, item, page.business_date)}
                      </small>
                    </span>
                    <a
                      aria-label={`${row.tip}: ${row.title}`}
                      className="ui-iconbtn ui-todo-go"
                      href={row.href}
                      title={row.tip}
                    >
                      <Icon name="forward" />
                    </a>
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </div>
    </section>
  );
}

/** The line under the list that confirms the last automatic jobs (owner, 12/10/2026). */
function JobsLine({
  language,
  page,
  place,
}: {
  language: Language;
  page: HomePage;
  /**
   * Home screen review (owner 14/11/2026): a warning (no billing run, no ABA rate) is a slim
   * yellow bar under the title; the calm line stays under the Tasks.
   */
  place: "top" | "bottom";
}) {
  const { last_billing_at, rate_updated_at, next_billing_date } = page.jobs;
  const parts = [
    last_billing_at === null
      ? hmt(language, "job_bill_none")
      : last_billing_at !== undefined
        ? hmt(language, "job_bill", momentText(last_billing_at))
        : "",
    rate_updated_at === null
      ? hmt(language, "job_rate_none")
      : rate_updated_at !== undefined
        ? hmt(language, "job_rate", momentText(rate_updated_at))
        : "",
    next_billing_date !== undefined
      ? hmt(language, "job_next", dayText(next_billing_date))
      : "",
  ].filter(Boolean);
  if (parts.length === 0) return null;
  const quiet = last_billing_at === null || rate_updated_at === null;
  if (quiet !== (place === "top")) return null;
  if (quiet)
    return (
      <p className="ui-notice warn ui-home-jobs" role="status">
        <Icon name="alert" small />
        <span>{parts.join(" · ")}</span>
      </p>
    );
  return (
    <p className="ui-addup">
      <Icon name="check" small />
      <span>{parts.join(" · ")}</span>
    </p>
  );
}

export function HomeScreen({
  language,
  propertyId,
  active,
  homeApi,
  capabilities,
  problemsApi = defaultProblemsApi,
  ledgerApi = defaultLedgerApi,
  attendanceApi = defaultHrApi,
  visitsApi = defaultTelegramApi,
  shortStaysApi = defaultShortStaysApi,
  productsApi = defaultProductsApi,
}: HomeScreenProps) {
  const may = (capability: string) =>
    capabilities === null || capabilities.has(capability);
  const [page, setPage] = useState<HomePage | null>(null);
  const [failure, setFailure] = useState<"failed" | "not_allowed" | null>(null);
  const [problems, setProblems] = useState<ProblemSummary | null>(null);
  const [visits, setVisits] = useState<VisitsWaiting | null>(null);
  const [bookings, setBookings] = useState<Booking[] | null>(null);
  const [lowStock, setLowStock] = useState<number | null>(null);
  const [attendance, setAttendance] = useState<AttendanceNow | null>(null);
  const sequence = useRef(0);
  // Parking Step 6: the cards of the parts Parking hides are never read.
  const seesVisits =
    TELEGRAM && capabilities?.has("visit_requests.read") === true;
  // Owner 12/11/2026: each of these cards is read only by a person known to hold its right.
  const seesStays =
    SHORT_STAYS && capabilities?.has("short_stays.read") === true;
  const seesStock = PRODUCTS && capabilities?.has("products.read") === true;
  const seesAttendance = HR && capabilities?.has("hr.attendance.read") === true;
  // Only a person known to see Problem reports reads the card.
  const seesProblems =
    PROBLEM_REPORTS && capabilities?.has("problem_reports.read") === true;
  const checksCosts = capabilities?.has("problem_reports.costs") === true;

  const load = useCallback(() => {
    if (propertyId === "") return;
    const operation = ++sequence.current;
    setFailure(null);
    homeApi
      .home(propertyId)
      .then((loaded) => {
        if (operation === sequence.current) setPage(loaded);
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        // An old page would show numbers that may be wrong now.
        setPage(null);
        setFailure(
          error instanceof ReportsNotAllowedError ? "not_allowed" : "failed",
        );
      });
    if (seesProblems)
      problemsApi
        .summary(propertyId)
        .then((loaded) => {
          if (operation === sequence.current) setProblems(loaded);
        })
        .catch(() => {
          // The card is left out; the rest of Home still shows.
          if (operation === sequence.current) setProblems(null);
        });
    if (seesVisits)
      visitsApi
        .visitRequests(propertyId)
        .then((loaded) => {
          if (operation === sequence.current)
            setVisits(visitsWaitingOf(loaded.requests, loaded.today));
        })
        .catch(() => {
          if (operation === sequence.current) setVisits(null);
        });
    // The Property's business date comes with the Home read, so the "today" notes of the two
    // Short stays cards are worked out when the cards are drawn.
    if (seesStays)
      shortStaysApi
        .list(propertyId)
        .then((loaded) => {
          if (operation === sequence.current) setBookings(loaded);
        })
        .catch(() => {
          if (operation === sequence.current) setBookings(null);
        });
    if (seesStock)
      productsApi
        .catalogue(propertyId)
        .then((loaded) => {
          if (operation === sequence.current)
            setLowStock(lowStockOf(loaded.products));
        })
        .catch(() => {
          if (operation === sequence.current) setLowStock(null);
        });
    if (seesAttendance)
      attendanceApi
        .day(propertyId, null)
        .then((loaded) => {
          if (operation === sequence.current)
            setAttendance(attendanceToCheck(loaded));
        })
        .catch(() => {
          if (operation === sequence.current) setAttendance(null);
        });
  }, [
    attendanceApi,
    homeApi,
    problemsApi,
    productsApi,
    propertyId,
    seesAttendance,
    seesProblems,
    seesStays,
    seesStock,
    seesVisits,
    shortStaysApi,
    visitsApi,
  ]);

  // Another Property never shows the numbers of the one before.
  useEffect(() => {
    sequence.current++;
    setPage(null);
    setProblems(null);
    setVisits(null);
    setBookings(null);
    setLowStock(null);
    setAttendance(null);
  }, [propertyId]);

  useEffect(() => {
    if (active) load();
  }, [active, load]);

  const actions = (may("payments.record") ||
    may("utility_readings.record")) && (
    <>
      {may("payments.record") && (
        <a
          className="ui-btn primary ui-homeact"
          href={hashForPage("payments", "receive")}
        >
          <Icon name="payments" />
          {hmt(language, "qa_record")}
        </a>
      )}
      {may("utility_readings.record") && (
        <a className="ui-btn ui-homeact" href={hashForPage("utilities")}>
          <Icon name="meter" />
          {hmt(language, "qa_readings")}
        </a>
      )}
    </>
  );

  if (propertyId === "") return null;

  // UI v81 round 4 (owner 08/11/2026): no line under the title; only the two buttons beside it.
  // Home batch (owner 08/11/2026 08:14): drawn with the shared PageHeader.
  const head = (
    <PageHeader actions={actions} title={pageName("home", language)} />
  );

  if (failure !== null) {
    return (
      <>
        {head}
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{hmt(language, failure)}</p>
          {failure === "failed" && (
            <button className="ui-btn" onClick={load} type="button">
              {hmt(language, "retry")}
            </button>
          )}
        </div>
      </>
    );
  }
  if (page === null) {
    return (
      <>
        {head}
        <p className="ui-muted" role="status">
          {hmt(language, "loading")}
        </p>
      </>
    );
  }
  // UI v81: shown only to a person known to hold the rights (the server checks again).
  const seesOwnerMoney =
    GENERAL_LEDGER &&
    capabilities?.has("ledger.owner_money") === true &&
    capabilities.has("ledger.read");
  return (
    <>
      {head}
      <JobsLine language={language} page={page} place="top" />
      {seesOwnerMoney && (
        <OwnerMoney
          active={active}
          api={ledgerApi}
          language={language}
          propertyId={propertyId}
          today={page.business_date}
        />
      )}
      <Cards
        attendance={attendance}
        cards={page.cards}
        language={language}
        lowStock={lowStock}
        problems={problems}
        stays={
          bookings === null ? null : staysNowOf(bookings, page.business_date)
        }
        today={page.business_date}
        visits={visits}
      />
      {problems !== null && checksCosts && (
        <CostsToCheck language={language} summary={problems} />
      )}
      <TodoList language={language} page={page} />
      <JobsLine language={language} page={page} place="bottom" />
    </>
  );
}
