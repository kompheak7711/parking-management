// V1-058 R5c-3: the Payments list (DESIGN.md "Summary cards (Payments)"): the period switch, the
// cards that filter the list (Total received and the kinds of what the money paid), the
// add-up line, and the list of payments with their Receipt, Customer, amount, what they paid
// and whether all the money is used. The server splits each payment, so the cards add up.
//
// UI v81 round 9 (owner 12/11/2026): the list said "Move-out charges" for a Receipt whose page
// said "Short stay". The one-time charges are now split by the type of the Invoice (DL-221):
// Short stay, Products, Damage, Other charges, the names the Receipt page uses.

import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import type { InvoicesData } from "../invoices/invoicesData";
import { dayText, momentText, usdFromCents } from "../shell/format";
import { Icon, type ShellIcon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { openPageInAddress } from "../shell/useHashPage";
import { Chip, CountCard, type Tone } from "../shell/ui";
import type { Language } from "../signInText";
import {
  PAY_KINDS,
  type PayKind,
  type PaymentRow,
  type PaymentsApi,
  type PaymentsSummary,
} from "./paymentsClient";
import { pyt } from "./text";
import { PageHead } from "../shell/pageHead";

export type PayPeriod = "all" | "today" | "month" | "last" | "pick";

const KIND_LOOK: Record<PayKind, [ShellIcon, Tone | "brand"]> = {
  RENT: ["home", "brand"],
  UTIL: ["zap", "info"],
  SVC: ["list", "brand"],
  LATE: ["clock", "warn"],
  DEPOSIT: ["lease", "info"],
  SHORT_STAY: ["calendar", "brand"],
  PRODUCTS: ["box", "brand"],
  DAMAGE: ["wrench", "brand"],
  OTHER: ["invoice", "brand"],
  CREDIT: ["customers", "brand"],
};

function shiftDay(day: string, days: number): string {
  const date = new Date(`${day}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

/** "dd/mm/yyyy" → "yyyy-mm-dd", or null when it is not a real day. */
export function isoDay(value: string): string | null {
  const match = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(value.trim());
  if (match === null) return null;
  const [, day = "", month = "", year = ""] = match;
  const iso = `${year}-${month}-${day}`;
  const date = new Date(`${iso}T00:00:00Z`);
  return Number.isNaN(date.getTime()) || date.toISOString().slice(0, 10) !== iso
    ? null
    : iso;
}

/** The first and last day of a period, as "yyyy-mm-dd"; "All" is the last two years, the
 * longest period the server reads at once. */
export function periodRange(
  period: Exclude<PayPeriod, "pick">,
  today: string,
): [string, string] {
  const first = `${today.slice(0, 8)}01`;
  if (period === "today") return [today, today];
  if (period === "month") return [first, today];
  if (period === "last")
    return [shiftDay(first, -1).slice(0, 8) + "01", shiftDay(first, -1)];
  return [shiftDay(today, -730), today];
}

function countText(language: Language, count: number): string {
  return count === 1 ? pyt(language, "c_n1") : pyt(language, "c_n", count);
}

export function rielText(minor: number): string {
  return `${minor.toLocaleString("en-US")} ៛`;
}

export function PaymentChip({
  language,
  row,
}: {
  language: Language;
  row: Pick<PaymentRow, "status" | "left" | "usdCents">;
}) {
  if (row.status === "REVERSED")
    return (
      <Chip icon="x" tone="neutral">
        {pyt(language, "st_reversed")}
      </Chip>
    );
  if (row.left <= 0)
    return (
      <Chip icon="check" tone="ok">
        {pyt(language, "st_matched")}
      </Chip>
    );
  return row.left < row.usdCents ? (
    <Chip tone="warn">{pyt(language, "st_partmatched")}</Chip>
  ) : (
    <Chip icon="alert" tone="warn">
      {pyt(language, "st_notmatched")}
    </Chip>
  );
}

export function PaymentsList({
  language,
  propertyId,
  api,
  data,
  today,
  mayReceive,
}: {
  language: Language;
  propertyId: string;
  api: Pick<PaymentsApi, "summary">;
  data: InvoicesData | null;
  today: string;
  mayReceive: boolean;
}) {
  const [period, setPeriod] = useState<PayPeriod>("month");
  const [picked, setPicked] = useState<[string, string]>(() =>
    periodRange("month", today),
  );
  const [fromText, setFromText] = useState(dayText(picked[0]));
  const [toText, setToText] = useState(dayText(picked[1]));
  const [pickError, setPickError] = useState(false);
  const [card, setCard] = useState<PayKind | "all">("all");
  // Owner 13/11/2026 (Operations fix 1): the cards of kinds with no money in the period fold
  // away behind one "more" card, so the list starts higher.
  const [showZero, setShowZero] = useState(false);
  // Owner 16/11/2026: a large screen has room for every card, so nothing folds there; only a
  // phone, iPad or laptop folds the $0.00 cards.
  const allFit = useAllCardsFit();
  const [onlyLeft, setOnlyLeft] = useState(false);
  const [summary, setSummary] = useState<PaymentsSummary | null>(null);
  const [failed, setFailed] = useState(false);
  const sequence = useRef(0);

  const [from, to] = period === "pick" ? picked : periodRange(period, today);

  const load = useCallback(() => {
    const operation = ++sequence.current;
    setFailed(false);
    setSummary(null);
    api
      .summary(propertyId, from, to)
      .then((loaded) => {
        if (operation === sequence.current) setSummary(loaded);
      })
      .catch(() => {
        if (operation === sequence.current) setFailed(true);
      });
  }, [api, from, propertyId, to]);

  useEffect(load, [load]);

  const pick = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const start = isoDay(fromText);
    const end = isoDay(toText);
    if (start === null || end === null || start > end) {
      setPickError(true);
      return;
    }
    setPickError(false);
    setPicked([start, end]);
  };

  const name = (customerId: string) => data?.names.get(customerId) ?? null;
  const unit = (customerId: string) =>
    data?.customerUnits.get(customerId) ?? "";
  const open = (paymentId: string) => {
    openPageInAddress("payments", false, `receipt:${paymentId}`);
  };

  // Owner 13/11/2026 (Operations screen): no date line under the title; the period switch sits
  // beside the title instead (it wraps under it on a narrow screen).
  const periodSwitch = (
    <div
      aria-label={pyt(language, "pc_period")}
      className="ui-seg ui-headseg"
      role="group"
    >
      {(
        [
          ["all", "f_all"],
          ["today", "pc_today"],
          ["month", "pc_month"],
          ["last", "pc_last"],
          ["pick", "pc_pick"],
        ] as const
      ).map(([value, key]) => (
        <button
          aria-pressed={period === value}
          key={value}
          onClick={() => {
            setPeriod(value);
            setCard("all");
          }}
          type="button"
        >
          {pyt(language, key)}
        </button>
      ))}
    </div>
  );

  const head = (
    <PageHead>
      {periodSwitch}
      {mayReceive && (
        <div className="ui-actions">
          <a
            className="ui-btn primary"
            href={hashForPage("payments", "receive")}
          >
            <Icon name="payments" />
            {pyt(language, "rp_title")}
          </a>
        </div>
      )}
    </PageHead>
  );

  const filters = period === "pick" && (
    <div className="ui-filters">
      {
        <form className="ui-pick" noValidate onSubmit={pick}>
          <label>
            {pyt(language, "pc_from")}{" "}
            <input
              aria-describedby={pickError ? "pc-err" : undefined}
              aria-invalid={pickError}
              className="ui-inp ui-num"
              id="pc-from"
              inputMode="numeric"
              onChange={(event) => {
                setFromText(event.currentTarget.value);
              }}
              placeholder="dd/mm/yyyy"
              value={fromText}
            />
          </label>
          <label>
            {pyt(language, "pc_to")}{" "}
            <input
              aria-describedby={pickError ? "pc-err" : undefined}
              aria-invalid={pickError}
              className="ui-inp ui-num"
              id="pc-to"
              inputMode="numeric"
              onChange={(event) => {
                setToText(event.currentTarget.value);
              }}
              placeholder="dd/mm/yyyy"
              value={toText}
            />
          </label>
          <button className="ui-btn" type="submit">
            {pyt(language, "pc_apply")}
          </button>
          {pickError && (
            <p className="ui-perr" id="pc-err" role="alert">
              <Icon name="alert" small />
              {pyt(language, "pc_bad")}
            </p>
          )}
        </form>
      }
    </div>
  );

  if (failed)
    return (
      <>
        {head}
        {filters}
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{pyt(language, "failed")}</p>
          <button className="ui-btn" onClick={load} type="button">
            {pyt(language, "retry")}
          </button>
        </div>
      </>
    );
  if (summary === null)
    return (
      <>
        {head}
        {filters}
        <p className="ui-muted" role="status">
          {pyt(language, "loading")}
        </p>
      </>
    );

  const kindsTotal = PAY_KINDS.reduce(
    (total, kind) => total + summary.kinds[kind].cents,
    0,
  );
  const zeroKinds = PAY_KINDS.filter(
    (kind) =>
      !allFit &&
      summary.kinds[kind].cents === 0 &&
      summary.kinds[kind].payments === 0 &&
      card !== kind,
  );
  const shownKinds = showZero
    ? PAY_KINDS
    : PAY_KINDS.filter((kind) => !zeroKinds.includes(kind));
  const inCard = (row: PaymentRow) =>
    card === "all" || (row.status !== "REVERSED" && (row.kinds[card] ?? 0) > 0);
  const listed = summary.rows.filter(inCard);
  const leftCount = listed.filter((row) => row.left > 0).length;
  const rows = onlyLeft ? listed.filter((row) => row.left > 0) : listed;
  const anyLeft = rows.some((row) => row.left > 0);
  const reversed = listed.filter((row) => row.status === "REVERSED").length;
  // The app checks the sum itself, so a kind of money the cards miss shows as a problem.
  const addsUp =
    kindsTotal + summary.refunded + summary.left === summary.received;
  const addUp = [
    !addsUp
      ? pyt(
          language,
          "pc_addup_bad",
          usdFromCents(kindsTotal),
          usdFromCents(summary.refunded),
          usdFromCents(summary.left),
          usdFromCents(kindsTotal + summary.refunded + summary.left),
          usdFromCents(summary.received),
        )
      : summary.refunded > 0
        ? pyt(
            language,
            "pc_addup_r",
            usdFromCents(kindsTotal),
            usdFromCents(summary.refunded),
            usdFromCents(summary.left),
            usdFromCents(summary.received),
          )
        : summary.left > 0
          ? pyt(
              language,
              "pc_addup",
              usdFromCents(kindsTotal),
              usdFromCents(summary.left),
              usdFromCents(summary.received),
            )
          : pyt(language, "pc_addup0", usdFromCents(summary.received)),
    summary.rielMinor > 0
      ? pyt(
          language,
          "pc_basis",
          rielText(summary.rielMinor),
          usdFromCents(summary.rielUsd),
        )
      : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <>
      {head}
      {filters}
      <div className="ui-kpis ui-kpis-pay">
        <CountCard
          icon="payments"
          label={pyt(language, "c_total")}
          onPress={() => {
            setCard("all");
          }}
          pressed={card === "all"}
          tone="brand"
          value={summary.received}
          valueText={usdFromCents(summary.received)}
        />
        {shownKinds.map((kind) => {
          const [icon, tone] = KIND_LOOK[kind];
          const { cents } = summary.kinds[kind];
          return (
            <CountCard
              icon={icon}
              key={kind}
              label={pyt(language, `c_${kind}`)}
              onPress={() => {
                setCard(card === kind ? "all" : kind);
              }}
              pressed={card === kind}
              tone={cents === 0 ? "none" : tone}
              value={cents}
              valueText={usdFromCents(cents)}
            />
          );
        })}
        {zeroKinds.length > 0 && (
          <button
            aria-expanded={showZero}
            aria-label={`${pyt(language, showZero ? "c_fewer" : "c_more")}: ${String(zeroKinds.length)}. ${pyt(language, showZero ? "c_fewer_s" : "c_more_s")}`}
            className="ui-kpi ui-kpi-top none ui-kpi-more"
            onClick={() => {
              setShowZero(!showZero);
            }}
            type="button"
          >
            <span className="ui-kpi-head">
              <span className="ui-kpi-label">
                <span className="ui-kpi-icon">
                  <Icon name={showZero ? "x" : "plus"} small />
                </span>
                <span>{pyt(language, showZero ? "c_fewer" : "c_more")}</span>
              </span>
              <span className="ui-kpi-value ui-num">
                {String(zeroKinds.length)}
              </span>
            </span>
          </button>
        )}
      </div>
      <p className={addsUp ? "ui-addup" : "ui-addup ui-warnv"}>
        <Icon name={addsUp ? "check" : "alert"} small />
        <span>{addUp}</span>
      </p>
      <div className="ui-card pad0">
        <div className="ui-listbar">
          <div
            aria-label={pyt(language, "col_status")}
            className="ui-seg"
            role="group"
          >
            <button
              aria-pressed={!onlyLeft}
              onClick={() => {
                setOnlyLeft(false);
              }}
              type="button"
            >
              {pyt(language, "f_all")}{" "}
              <span className="ui-num ui-muted">{listed.length}</span>
            </button>
            <button
              aria-pressed={onlyLeft}
              onClick={() => {
                setOnlyLeft(true);
              }}
              type="button"
            >
              {pyt(language, "st_notmatched")}{" "}
              <span className="ui-num ui-muted">{leftCount}</span>
            </button>
          </div>
          {reversed > 0 && (
            <span className="ui-small ui-muted">
              {pyt(language, "pc_rev_note", String(reversed))}
            </span>
          )}
          {card !== "all" && (
            <span className="ui-showing">
              {pyt(language, "pc_showing", pyt(language, `c_${card}`))}{" "}
              <button
                className="ui-btn link"
                onClick={() => {
                  setCard("all");
                }}
                type="button"
              >
                {pyt(language, "pc_clear")}
              </button>
            </span>
          )}
        </div>
        {rows.length === 0 ? (
          <p className="ui-empty">
            {pyt(
              language,
              onlyLeft && listed.length > 0 ? "pc_none_left" : "pc_none",
            )}
          </p>
        ) : (
          <div className="ui-tablewrap">
            <table className="ui-table ui-paylist">
              <thead>
                <tr>
                  <th scope="col">{pyt(language, "col_receipt")}</th>
                  <th className="ui-wide" scope="col">
                    {pyt(language, "col_received")}
                  </th>
                  <th scope="col">{pyt(language, "col_cust")}</th>
                  <th className="r ui-wide" scope="col">
                    {pyt(language, "col_amount")}
                  </th>
                  <th className="ui-wide" scope="col">
                    {pyt(language, "col_for")}
                  </th>
                  <th className="ui-wide" scope="col">
                    {pyt(language, "col_status")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const [date = "", time = ""] = momentText(
                    row.receivedAt,
                  ).split(" ");
                  const kinds = PAY_KINDS.filter(
                    (kind) => (row.kinds[kind] ?? 0) > 0,
                  );
                  const who = name(row.customerId);
                  return (
                    <tr
                      className="ui-row"
                      key={row.paymentId}
                      onClick={() => {
                        open(row.paymentId);
                      }}
                    >
                      <td>
                        <a
                          className="ui-no ui-num"
                          href={hashForPage(
                            "payments",
                            `receipt:${row.paymentId}`,
                          )}
                          onClick={(event) => {
                            event.stopPropagation();
                          }}
                        >
                          {row.receiptNumber ?? "—"}
                        </a>
                        {/* On a phone the time and the amount fold under the number. */}
                        <span className="ui-sub2 ui-phone ui-num">
                          {`${date} ${time} · ${usdFromCents(row.usdCents)}`}
                        </span>
                        <span className="ui-phone" aria-hidden="true">
                          <PaymentChip language={language} row={row} />
                        </span>
                      </td>
                      <td className="ui-num ui-wide">
                        <span className="ui-nw">{date}</span>
                        <span className="ui-sub2">{time}</span>
                      </td>
                      <td>
                        {who ?? <span className="ui-muted">—</span>}
                        <span className="ui-sub2">{unit(row.customerId)}</span>
                      </td>
                      <td className="r ui-num ui-nw ui-wide">
                        {usdFromCents(row.usdCents)}
                        {row.currency === "KHR" && (
                          <span className="ui-sub2">
                            {rielText(row.receivedMinor)}
                          </span>
                        )}
                        <span className="ui-sub2">{row.methodName}</span>
                      </td>
                      <td className="ui-wide ui-small">
                        {kinds.length === 0 ? (
                          <span className="ui-muted">—</span>
                        ) : (
                          kinds.map((kind) => (
                            <span className="ui-pf" key={kind}>
                              {pyt(language, `c_${kind}`)}
                            </span>
                          ))
                        )}
                      </td>
                      <td className="ui-wide">
                        <PaymentChip language={language} row={row} />
                        {row.left > 0 && (
                          <span className="ui-sub2 ui-num">
                            {pyt(language, "pc_left", usdFromCents(row.left))}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {(summary.truncated || anyLeft) && (
          <div className="ui-tfoot">
            {summary.truncated
              ? pyt(language, "pc_more")
              : countText(language, rows.length)}
          </div>
        )}
      </div>
    </>
  );
}

/** The width from which a large screen shows every Payments card (owner 16/11/2026). */
const ALL_CARDS_FIT = "(min-width: 1600px)";

/** True while the window is a large screen, where every Payments card shows. */
function useAllCardsFit(): boolean {
  const query = () =>
    typeof window.matchMedia === "function" &&
    window.matchMedia(ALL_CARDS_FIT).matches;
  const [fit, setFit] = useState(query);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(ALL_CARDS_FIT);
    const changed = () => {
      setFit(media.matches);
    };
    media.addEventListener("change", changed);
    return () => {
      media.removeEventListener("change", changed);
    };
  }, []);
  return fit;
}
