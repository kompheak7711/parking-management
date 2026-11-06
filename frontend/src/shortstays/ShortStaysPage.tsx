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
import { hashForPage } from "../shell/navigation";
import { openPageInAddress, useHashDetail } from "../shell/useHashPage";
import { Chip, type Tone } from "../shell/ui";
import type { Language } from "../signInText";
import { BookingDetail } from "./BookingDetail";
import { CleaningList } from "./CleaningList";
import { CreditsDue } from "./CreditsDue";
import { NewBookingForm } from "./NewBooking";
import { nightOf } from "./nights";
import { Quotes } from "./Quotes";
import { SiteCalendars } from "./SiteCalendars";
import { WeekReport } from "./WeekReport";
import {
  addDays,
  type Booking,
  type BookingStatus,
  type ShortStaysApi,
  type StayCalendar,
  shortStaysApi as defaultShortStaysApi,
} from "./shortStaysClient";
import { hasText, st } from "./text";

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

const DAYS = 14;
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

function weekday(language: Language, day: string): string {
  return new Intl.DateTimeFormat(language === "km" ? "km-KH" : "en-GB", {
    weekday: "short",
    timeZone: "UTC",
  }).format(new Date(`${day}T00:00:00Z`));
}

type Tab = "cal" | "list" | "clean" | "quotes" | "report" | "sites";

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
  const [tab, setTab] = useState<Tab>("cal");
  const [from, setFrom] = useState(today);
  const [calendar, setCalendar] = useState<StayCalendar | null>(null);
  const [bookings, setBookings] = useState<Booking[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);
  const sequence = useRef(0);

  const load = useCallback(() => {
    if (propertyId === "" || (tab !== "cal" && tab !== "list")) return;
    const operation = ++sequence.current;
    setFailed(false);
    const read =
      tab === "cal"
        ? api.calendar(propertyId, from, DAYS).then((found) => {
            if (operation === sequence.current) setCalendar(found);
          })
        : api.list(propertyId).then((found) => {
            if (operation === sequence.current) setBookings(found);
          });
    void read.catch(() => {
      if (operation === sequence.current) setFailed(true);
    });
  }, [api, propertyId, tab, from]);

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

  const days = Array.from({ length: DAYS }, (_, index) => addDays(from, index));
  const calendarView =
    calendar === null || calendar.from !== from ? (
      loading
    ) : (
      <>
        {failure}
        <div className="ui-filters">
          <div className="ui-actions">
            <button
              className="ui-btn"
              onClick={() => {
                setFrom(addDays(from, -STEP));
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
                setFrom(addDays(from, STEP));
              }}
              type="button"
            >
              {st(language, "next")}
              <Icon name="forward" small />
            </button>
          </div>
          <span className="ui-muted ui-num">
            {st(
              language,
              "cal_days",
              dayText(from),
              dayText(addDays(from, DAYS - 1)),
            )}
          </span>
        </div>
        <div className="ui-card pad0">
          {calendar.units.length === 0 ? (
            <p className="ui-empty">{st(language, "cal_none")}</p>
          ) : (
            <div className="ui-tablewrap">
              <table className="ss-cal">
                <thead>
                  <tr>
                    <th scope="col">{st(language, "c_unit")}</th>
                    {days.map((day) => (
                      <th
                        className={day === calendar.today ? "today" : undefined}
                        key={day}
                        scope="col"
                      >
                        <span className="ss-wd">{weekday(language, day)}</span>
                        <span className="ui-num">
                          {dayText(day).slice(0, 5)}
                        </span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {calendar.units.map((unit) => (
                    <tr key={unit.unit_id}>
                      <th scope="row">
                        <b className="ui-num">{unit.unit_number}</b>
                        <span className="ui-sub2">
                          {unitTypeText(language, unit.unit_type)}
                        </span>
                      </th>
                      {days.map((day) => {
                        const night = nightOf(unit, day);
                        const past = day < calendar.today;
                        if (night.kind === "BOOKING") {
                          const booking = night.booking;
                          return (
                            <td
                              className={`ss-night ss-${booking.status.toLowerCase()}${
                                booking.status === "BOOKED" && !booking.paid
                                  ? " ss-unpaid"
                                  : ""
                              }${night.clash === null ? "" : " ss-clash"}`}
                              key={day}
                              title={
                                night.clash === null
                                  ? undefined
                                  : st(
                                      language,
                                      "cal_clash",
                                      night.clash.site_name,
                                    )
                              }
                            >
                              <a
                                href={hashForPage(
                                  "shortstays",
                                  `st:${booking.booking_id}`,
                                )}
                                onClick={(event) => {
                                  openBooking(event, booking.booking_id);
                                }}
                                title={`${booking.booking_number} · ${booking.guest_name}`}
                              >
                                <Icon
                                  name={
                                    booking.status === "CHECKED_IN"
                                      ? "door"
                                      : "calendar"
                                  }
                                  small
                                />
                                <span>
                                  {night.first
                                    ? booking.guest_name
                                    : st(
                                        language,
                                        booking.status === "CHECKED_IN"
                                          ? "cal_in"
                                          : booking.status === "BOOKED" &&
                                              !booking.paid
                                            ? "cal_unpaid"
                                            : `st_${booking.status}`,
                                      )}
                                </span>
                              </a>
                            </td>
                          );
                        }
                        if (night.kind === "HOLD") {
                          return (
                            <td className="ss-night ss-hold" key={day}>
                              <span
                                title={st(
                                  language,
                                  "b_SITE_HOLD",
                                  night.hold.site_name,
                                  dayText(night.hold.start_on),
                                  dayText(night.hold.end_on),
                                )}
                              >
                                <Icon name="lock" small />
                                <span>{night.hold.site_name}</span>
                              </span>
                            </td>
                          );
                        }
                        if (night.kind === "FREE") {
                          return (
                            <td className="ss-night ss-free" key={day}>
                              {!past && may("short_stays.desk") ? (
                                <a
                                  aria-label={st(
                                    language,
                                    "cal_book",
                                    unit.unit_number,
                                    dayText(day),
                                  )}
                                  href={hashForPage(
                                    "shortstays",
                                    `new:${unit.unit_id}:${day}`,
                                  )}
                                >
                                  <Icon name="plus" small />
                                  <span>{st(language, "cal_free")}</span>
                                </a>
                              ) : (
                                <span className="ui-muted">
                                  {st(language, "cal_free")}
                                </span>
                              )}
                            </td>
                          );
                        }
                        const word = {
                          LEASE: st(language, "lease"),
                          RESERVED: st(language, "reserved"),
                          NOT_FOR_RENT: st(language, "not_for_rent"),
                          CLOSED: st(language, "cal_closed"),
                        }[night.kind];
                        return (
                          <td
                            className={`ss-night ss-${night.kind.toLowerCase()}`}
                            key={day}
                          >
                            <span>
                              <Icon
                                name={night.kind === "LEASE" ? "lease" : "lock"}
                                small
                              />
                              <span>{word}</span>
                            </span>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </>
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
        <div className="ui-card pad0">
          {bookings.length === 0 ? (
            <p className="ui-empty">{st(language, "none")}</p>
          ) : (
            <>
              <div className="ui-tablewrap">
                <table className="ui-table">
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
                    {bookings.map((booking) => (
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
                {bookings.length === 1
                  ? st(language, "n1")
                  : st(language, "n", bookings.length)}
              </div>
            </>
          )}
        </div>
      </>
    );

  return (
    <>
      <div className="ui-head">
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
      </div>
      <div className="ui-filters">
        <div aria-label={st(language, "tabs")} className="ui-seg" role="group">
          {(may("short_stays.approve")
            ? (["cal", "list", "clean", "quotes", "report", "sites"] as const)
            : (["cal", "list", "clean", "quotes"] as const)
          ).map((value) => (
            <button
              aria-pressed={tab === value}
              key={value}
              onClick={() => {
                setTab(value);
              }}
              type="button"
            >
              {st(language, `tab_${value}`)}
            </button>
          ))}
        </div>
      </div>
      {tab === "cal" ? (
        calendarView
      ) : tab === "list" ? (
        listView
      ) : tab === "quotes" ? (
        <Quotes
          api={api}
          key={propertyId}
          language={language}
          may={may}
          propertyId={propertyId}
          today={today}
        />
      ) : tab === "report" ? (
        <WeekReport
          api={api}
          key={propertyId}
          language={language}
          may={may}
          propertyId={propertyId}
          today={today}
        />
      ) : tab === "sites" ? (
        <SiteCalendars
          api={api}
          key={propertyId}
          language={language}
          propertyId={propertyId}
          today={today}
        />
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
    </>
  );
}
