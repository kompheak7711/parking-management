// Daily and weekly rent, phase 6 step 2: Tenants › Short stays (mock-up rounds 28, 31, 35).
// "#/shortstays" shows the Calendar (one row per Unit, one square per night) and the Bookings
// list; "#/shortstays/new" (or "new:<Unit id>:<day>" from a free square) is New booking and
// "#/shortstays/st:<id>" one booking. Step 4a adds the Cleaning tab (one day's cleans); step 5b
// the Quotes tab, step 5c the Weekly report (Owner and Manager). Buttons show only to a person who holds the right; the
// server checks every right and every night again.

import "../shell/screens.css";
import "./shortStays.css";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  type CustomerApi,
  customerApi as defaultCustomerApi,
} from "../customerClient";
import { dayText, todayInPhnomPenh, usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage, pageName } from "../shell/navigation";
import {
  openPageInAddress,
  useHashDetail,
  useShowFromAddress,
} from "../shell/useHashPage";
import { Chip, type Tone, useSubTab } from "../shell/ui";
import { TabHead } from "../shell/layouts";
import type { Language } from "../signInText";
import { BookingDetail } from "./BookingDetail";
import { CleaningList } from "./CleaningList";
import { CreditsDue } from "./CreditsDue";
import { DamageDue } from "./DamageDue";
import { NewBookingForm } from "./NewBooking";
import { forShortStays } from "./nights";
import { StayChart } from "./StayChart";
import { TodayPanel } from "./TodayPanel";
import {
  addDays,
  type Booking,
  type BookingStatus,
  type ShortStaysApi,
  type StayCalendar,
  shortStaysApi as defaultShortStaysApi,
} from "./shortStaysClient";
import { hasText, st } from "./text";
import { PageHead } from "../shell/pageHead";

export interface ShortStaysPageProps {
  language: Language;
  propertyId: string;
  /** Only the page that is shown loads; a hidden page waits until it is opened. */
  active: boolean;
  capabilities: ReadonlySet<string> | null;
  api?: ShortStaysApi;
  customerApi?: CustomerApi;
  /** Now, for the first day of the calendar; tests pass a fixed moment. */
  now?: Date;
}

// Leasing batch: the Calendar shows a week, 2 weeks or a month; Earlier and Later move a week
// (a month at a time on Month).
const VIEWS = { week: 7, "2weeks": 14, month: 30 } as const;
type View = keyof typeof VIEWS;
const STEP = 7;

const CHIPS: Record<BookingStatus, Tone> = {
  BOOKED: "info",
  CHECKED_IN: "ok",
  CHECKED_OUT: "neutral",
  CANCELLED: "neutral",
  NO_SHOW: "warn",
};

export function BookingChip({
  language,
  status,
}: {
  language: Language;
  status: BookingStatus;
}) {
  return <Chip tone={CHIPS[status]}>{st(language, `st_${status}`)}</Chip>;
}

/** "Studio", "1 bedroom"; a type the app does not know shows its code. */
export function unitTypeText(language: Language, type: string): string {
  const key = `t_${type}`;
  return hasText(key) ? st(language, key) : type;
}

export function nightsText(language: Language, nights: number): string {
  return nights === 1
    ? st(language, "nights1")
    : st(language, "nights", nights);
}

/** A plain click opens the record here; with a key held the browser opens the link itself. */
function plainClick(event: React.MouseEvent): boolean {
  return !(
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  );
}

// Leasing batch (owner 13/11/2026): no Quotes tab (the price message is copied on New booking);
// the tab is "?tab=<id>" in the address, so the menu's Short stays sub-items open it.
// Owner 13/11/2026 evening: the Weekly report is in Reports and Booking sites in Settings.
type Tab = "cal" | "list" | "clean";
const ALL_TABS: readonly Tab[] = ["cal", "list", "clean"];

// UI v81 round 11: the Bookings list can show one status. The word in the address is the
// status in small letters ("#/shortstays?show=booked", "?show=checked_in").
const LIST_STATUSES: readonly BookingStatus[] = [
  "BOOKED",
  "CHECKED_IN",
  "CHECKED_OUT",
  "CANCELLED",
  "NO_SHOW",
];

export function ShortStaysPage({
  language,
  propertyId,
  active,
  capabilities,
  api = defaultShortStaysApi,
  customerApi = defaultCustomerApi,
  now,
}: ShortStaysPageProps) {
  const detail = useHashDetail("shortstays");
  const may = (capability: string) =>
    capabilities === null || capabilities.has(capability);
  const today = todayInPhnomPenh(now);
  const [tab, setTabState] = useSubTab<Tab>(ALL_TABS, "cal");
  const tabs = ALL_TABS;
  const shownTab: Tab = tabs.includes(tab) ? tab : "cal";
  const [status, setStatusState] = useState<BookingStatus | "all">("all");
  const [query, setQuery] = useState("");
  // UI v81 round 11: Home's two Short stays cards open the Bookings list on their status
  // ("Short stay bookings" on Booked, "Short stays checked in" on Checked in).
  const keepShow = useShowFromAddress("shortstays", (show) => {
    const asked = LIST_STATUSES.find((value) => value.toLowerCase() === show);
    if (asked === undefined && show !== "all") return;
    setTabState("list");
    setStatusState(asked ?? "all");
  });
  const setStatus = (next: BookingStatus | "all") => {
    setStatusState(next);
    keepShow(next === "all" ? null : next.toLowerCase(), { tab: "list" });
  };
  const [from, setFrom] = useState(today);
  const [view, setView] = useState<View>("2weeks");
  const span = VIEWS[view];
  // The Today panel reads again each time the Calendar does.
  const [reloadKey, setReloadKey] = useState(0);
  const [calendar, setCalendar] = useState<StayCalendar | null>(null);
  const [bookings, setBookings] = useState<Booking[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);
  const sequence = useRef(0);

  const load = useCallback(() => {
    if (propertyId === "" || (shownTab !== "cal" && shownTab !== "list"))
      return;
    const operation = ++sequence.current;
    setFailed(false);
    const read =
      shownTab === "cal"
        ? api.calendar(propertyId, from, span).then((found) => {
            if (operation === sequence.current) {
              setCalendar(found);
              setReloadKey((key) => key + 1);
            }
          })
        : api.list(propertyId).then((found) => {
            if (operation === sequence.current) setBookings(found);
          });
    void read.catch(() => {
      if (operation === sequence.current) setFailed(true);
    });
  }, [api, propertyId, shownTab, from, span]);

  // Another Property never shows the bookings of the one before.
  useEffect(() => {
    sequence.current++;
    setCalendar(null);
    setBookings(null);
  }, [propertyId]);

  // Read again each time the page is opened, so it shows what others booked meanwhile.
  useEffect(() => {
    if (active && detail === null) load();
  }, [active, detail, load]);

  if (propertyId === "") {
    return (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>{st(language, "no_property")}</p>
      </div>
    );
  }

  if (detail?.startsWith("st:") === true) {
    const bookingId = detail.slice(3);
    return (
      <BookingDetail
        api={api}
        bookingId={bookingId}
        flash={flash}
        key={`${bookingId}:${propertyId}`}
        language={language}
        may={may}
        onFlashShown={() => {
          setFlash(null);
        }}
        propertyId={propertyId}
        today={today}
      />
    );
  }
  if (
    (detail === "new" || detail?.startsWith("new:") === true) &&
    may("short_stays.desk")
  ) {
    const [, unitId = "", day = ""] = detail.split(":");
    return (
      <NewBookingForm
        api={api}
        customerApi={customerApi}
        key={`${detail}:${propertyId}`}
        language={language}
        mayAddGuest={may("customers.manage")}
        onSaved={(made) => {
          setFlash(st(language, "made", made.booking_number));
          openPageInAddress("shortstays", true, `st:${made.booking_id}`);
        }}
        propertyId={propertyId}
        startDay={day === "" ? today : day}
        startUnit={unitId}
        today={today}
      />
    );
  }

  const failure = failed && (
    <div className="ui-notice warn" role="status">
      <Icon name="alert" />
      <p>{st(language, "failed")}</p>
      <button className="ui-btn" onClick={load} type="button">
        {st(language, "retry")}
      </button>
    </div>
  );
  const loading = failure || (
    <p className="ui-muted" role="status">
      {st(language, "loading")}
    </p>
  );
  const openBooking = (event: React.MouseEvent, bookingId: string) => {
    event.stopPropagation();
    if (!plainClick(event)) return;
    event.preventDefault();
    openPageInAddress("shortstays", false, `st:${bookingId}`);
  };

  const days = Array.from({ length: span }, (_, index) => addDays(from, index));
  const step = span === VIEWS.month ? span : STEP;
  // The Today panel stays on the screen while the chart moves to other days.
  // Owner 14/11/2026: only the Units a short-stay guest can have (not a leased one).
  const shortStayUnits =
    calendar === null
      ? []
      : calendar.units.filter((unit) =>
          forShortStays(
            unit,
            calendar.today,
            calendar.from,
            addDays(calendar.from, calendar.days - 1),
          ),
        );
  const calendarView = (
    <div className="ss-calgrid">
      <TodayPanel
        api={api}
        language={language}
        may={may}
        onChanged={load}
        propertyId={propertyId}
        reloadKey={reloadKey}
        today={calendar?.today ?? today}
      />
      {calendar === null || calendar.from !== from ? (
        <div className="ss-calmain">{loading}</div>
      ) : (
        <div className="ss-calmain">
          {failure}
          <div className="ui-filters">
            <div className="ui-actions">
              <button
                className="ui-btn"
                onClick={() => {
                  setFrom(addDays(from, -step));
                }}
                type="button"
              >
                <Icon name="back" small />
                {st(language, "prev")}
              </button>
              <button
                className="ui-btn"
                disabled={from === calendar.today}
                onClick={() => {
                  setFrom(calendar.today);
                }}
                type="button"
              >
                {st(language, "this_week")}
              </button>
              <button
                className="ui-btn"
                onClick={() => {
                  setFrom(addDays(from, step));
                }}
                type="button"
              >
                {st(language, "next")}
                <Icon name="forward" small />
              </button>
            </div>
            <div
              aria-label={st(language, "v_label")}
              className="ui-seg ss-views"
              role="group"
            >
              {(Object.keys(VIEWS) as View[]).map((value) => (
                <button
                  aria-pressed={view === value}
                  key={value}
                  onClick={() => {
                    if (value === view) return;
                    setCalendar(null);
                    setView(value);
                  }}
                  type="button"
                >
                  {st(language, `v_${value}`)}
                </button>
              ))}
            </div>
            <span className="ui-muted ui-num">
              {st(
                language,
                "cal_days",
                dayText(from),
                dayText(addDays(from, span - 1)),
              )}
            </span>
          </div>
          <div className="ui-card pad0">
            {shortStayUnits.length === 0 ? (
              <p className="ui-empty">{st(language, "cal_none")}</p>
            ) : (
              <StayChart
                calendar={{ ...calendar, units: shortStayUnits }}
                days={days}
                language={language}
                mayBook={may("short_stays.desk")}
                onOpenBooking={openBooking}
              />
            )}
          </div>
          <ul aria-label={st(language, "lg_label")} className="ss-legend">
            {(["booked", "in", "site", "lease", "closed"] as const).map(
              (tone) => (
                <li key={tone}>
                  <span aria-hidden="true" className={`ss-sw ${tone}`} />
                  {st(language, `lg_${tone}`)}
                </li>
              ),
            )}
            <li>
              <span aria-hidden="true" className="ss-dot" />
              {st(language, "lg_unpaid")}
            </li>
          </ul>
        </div>
      )}
    </div>
  );

  // Owner 13/11/2026: the Bookings list has a search box (guest, phone, booking number or Unit);
  // the status counts are of the bookings that match it.
  const words = query.trim().toLowerCase();
  const matched = (bookings ?? []).filter(
    (booking) =>
      words === "" ||
      [
        booking.guest_name,
        booking.guest_phone ?? "",
        booking.booking_number,
        booking.unit_number,
      ].some((value) => value.toLowerCase().includes(words)),
  );
  const listed = matched.filter(
    (booking) => status === "all" || booking.status === status,
  );
  const listView =
    bookings === null ? (
      loading
    ) : (
      <>
        {failure}
        {may("short_stays.credit") && (
          <CreditsDue api={api} language={language} propertyId={propertyId} />
        )}
        {may("damage_charges.bill") && (
          <DamageDue api={api} language={language} propertyId={propertyId} />
        )}
        {bookings.length > 0 && (
          <div className="ui-filters">
            <label className="ui-sr" htmlFor="shortstays-search">
              {st(language, "f_search")}
            </label>
            <input
              className="ui-search"
              id="shortstays-search"
              maxLength={100}
              onChange={(event) => {
                setQuery(event.currentTarget.value);
              }}
              placeholder={st(language, "f_search")}
              type="search"
              value={query}
            />
            <div
              aria-label={st(language, "c_status")}
              className="ui-seg"
              role="group"
            >
              {(["all", ...LIST_STATUSES] as const)
                .filter(
                  (value) =>
                    value === "all" ||
                    value === "BOOKED" ||
                    value === "CHECKED_IN" ||
                    value === status ||
                    matched.some((booking) => booking.status === value),
                )
                .map((value) => (
                  <button
                    aria-pressed={status === value}
                    key={value}
                    onClick={() => {
                      setStatus(value);
                    }}
                    type="button"
                  >
                    {value === "all"
                      ? st(language, "f_all")
                      : st(language, `st_${value}`)}{" "}
                    <span className="ui-num">
                      {value === "all"
                        ? matched.length
                        : matched.filter((booking) => booking.status === value)
                            .length}
                    </span>
                  </button>
                ))}
            </div>
          </div>
        )}
        <div className="ui-card pad0">
          {listed.length === 0 ? (
            <p className="ui-empty">
              {st(language, bookings.length === 0 ? "none" : "f_none")}
            </p>
          ) : (
            <>
              <div className="ui-tablewrap">
                <table className="ui-table ss-booklist">
                  <thead>
                    <tr>
                      <th scope="col">{st(language, "c_no")}</th>
                      <th scope="col">{st(language, "c_guest")}</th>
                      <th scope="col">{st(language, "c_unit")}</th>
                      <th scope="col">{st(language, "c_dates")}</th>
                      <th className="r" scope="col">
                        {st(language, "c_total")}
                      </th>
                      <th scope="col">{st(language, "c_status")}</th>
                      <th className="ui-wide" scope="col">
                        {st(language, "c_source")}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {listed.map((booking) => (
                      <tr
                        className="ui-row"
                        key={booking.booking_id}
                        onClick={() => {
                          openPageInAddress(
                            "shortstays",
                            false,
                            `st:${booking.booking_id}`,
                          );
                        }}
                      >
                        <td>
                          <a
                            className="ui-no ui-num"
                            href={hashForPage(
                              "shortstays",
                              `st:${booking.booking_id}`,
                            )}
                            onClick={(event) => {
                              openBooking(event, booking.booking_id);
                            }}
                          >
                            {booking.booking_number}
                          </a>
                        </td>
                        <td>
                          {booking.guest_name}
                          {booking.guest_phone !== null && (
                            <span className="ui-sub2 ui-num">
                              {booking.guest_phone}
                            </span>
                          )}
                        </td>
                        <td>
                          <span className="ui-num">{booking.unit_number}</span>
                          <span className="ui-sub2">
                            {unitTypeText(language, booking.unit_type)}
                          </span>
                        </td>
                        <td className="ui-num">
                          {st(
                            language,
                            "d_dates",
                            dayText(booking.check_in_on),
                            dayText(booking.check_out_on),
                          )}
                          <span className="ui-sub2">
                            {nightsText(language, booking.nights)}
                          </span>
                        </td>
                        <td className="r ui-num">
                          {usdFromCents(booking.total_usd_cents)}
                        </td>
                        <td>
                          <BookingChip
                            language={language}
                            status={booking.status}
                          />
                        </td>
                        <td className="ui-wide">
                          {booking.source === "BOOKING_SITE" &&
                          booking.site_name !== null
                            ? booking.site_name
                            : st(language, `src_${booking.source}`)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="ui-tfoot">
                {listed.length === 1
                  ? st(language, "n1")
                  : st(language, "n", listed.length)}
              </div>
            </>
          )}
        </div>
      </>
    );

  // Owner 14/11/2026 00:00: the tabs look like the Invoices tabs (a line under the chosen one)
  // and are the page's head; New booking sits at the right end of the tab row.
  return (
    <TabHead
      tabs={
        <nav aria-label={st(language, "tabs")} className="ui-subtabs ss-tabs">
          {tabs.map((value) => (
            <a
              aria-current={shownTab === value ? "page" : undefined}
              href={`${hashForPage("shortstays")}?tab=${value}`}
              key={value}
              onClick={() => {
                setTabState(value);
                if (value === "list") setStatusState("all");
              }}
            >
              {st(language, `tab_${value}`)}
            </a>
          ))}
        </nav>
      }
      title={pageName("shortstays", language)}
    >
      <PageHead>
        <p>{st(language, "sub")}</p>
        {may("short_stays.desk") && (
          <div className="ui-actions">
            <a
              className="ui-btn primary"
              href={hashForPage("shortstays", "new")}
            >
              <Icon name="plus" />
              {st(language, "add")}
            </a>
          </div>
        )}
      </PageHead>
      {shownTab === "cal" ? (
        calendarView
      ) : shownTab === "list" ? (
        listView
      ) : (
        <CleaningList
          api={api}
          key={propertyId}
          language={language}
          may={may}
          propertyId={propertyId}
          today={today}
        />
      )}
    </TabHead>
  );
}
