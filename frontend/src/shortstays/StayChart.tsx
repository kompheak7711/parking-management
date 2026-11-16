// Leasing batch (owner 13/11/2026, design "Short-stay calendar samples", FINAL): the Short stays
// Calendar as a booking chart. One row per Unit under a row per Unit type that counts the free
// rooms each night; each stay is one bar across its nights with the guest's name (an orange dot
// when it is not paid); a free night opens New booking for that Unit and night. The Unit's own
// state (Ready, Needs cleaning, …) is under its number. Display only: the server checks every
// night again when a booking is made.

import { dayText } from "../shell/format";
import { hashForPage } from "../shell/navigation";
import type { Language } from "../signInText";
import { type Night, nightOf } from "./nights";
import { unitTypeText } from "./ShortStaysPage";
import type {
  CalendarBooking,
  CalendarUnit,
  StayCalendar,
} from "./shortStaysClient";
import { hasText, st } from "./text";

/** Several nights of one Unit that hold the same thing, drawn as one bar. */
interface Segment {
  key: string;
  start: number;
  length: number;
  night: Night;
}

function segmentKey(night: Night): string {
  switch (night.kind) {
    case "BOOKING":
      return `b:${night.booking.booking_id}:${night.clash === null ? "" : night.clash.hold_id}`;
    case "HOLD":
      return `h:${night.hold.hold_id}`;
    case "FREE":
      // Every free night is its own square: each opens New booking for that night.
      return "";
    default:
      return night.kind;
  }
}

/** The Unit's nights in the window, joined where they hold the same thing. */
export function segmentsOf(
  unit: CalendarUnit,
  days: readonly string[],
): Segment[] {
  const segments: Segment[] = [];
  days.forEach((day, index) => {
    const night = nightOf(unit, day);
    const key = segmentKey(night);
    const last = segments[segments.length - 1];
    if (key !== "" && last !== undefined && last.key === key) {
      last.length += 1;
      return;
    }
    segments.push({
      key: key === "" ? `f:${day}` : key,
      start: index,
      length: 1,
      night,
    });
  });
  return segments;
}

function bookingTone(booking: CalendarBooking): string {
  if (booking.status === "CHECKED_IN") return "in";
  if (booking.status === "CHECKED_OUT") return "out";
  if (booking.source === "BOOKING_SITE") return "site";
  return "booked";
}

/** The Unit's own state, as a word under its number. */
export function roomWord(language: Language, status: string): string | null {
  const key = `rm_${status}`;
  return hasText(key) ? st(language, key) : null;
}

function weekday(language: Language, day: string): string {
  return new Intl.DateTimeFormat(language === "km" ? "km-KH" : "en-GB", {
    weekday: "short",
    timeZone: "UTC",
  }).format(new Date(`${day}T00:00:00Z`));
}

export function StayChart({
  language,
  calendar,
  days,
  mayBook,
  onOpenBooking,
}: {
  language: Language;
  calendar: StayCalendar;
  days: readonly string[];
  mayBook: boolean;
  onOpenBooking: (event: React.MouseEvent, bookingId: string) => void;
}) {
  // One group per Unit type, in the order the Units come.
  const groups: { type: string; units: CalendarUnit[] }[] = [];
  for (const unit of calendar.units) {
    const group = groups.find((entry) => entry.type === unit.unit_type);
    if (group === undefined)
      groups.push({ type: unit.unit_type, units: [unit] });
    else group.units.push(unit);
  }
  return (
    <div className="ss-chartwrap">
      <table className="ss-chart">
        <thead>
          <tr>
            <th className="ss-unitcol" scope="col">
              {st(language, "c_unit")}
            </th>
            {days.map((day) => (
              <th
                className={day === calendar.today ? "today" : undefined}
                key={day}
                scope="col"
              >
                <span className="ss-wd">{weekday(language, day)}</span>
                <span className="ui-num">{dayText(day).slice(0, 5)}</span>
              </th>
            ))}
          </tr>
        </thead>
        {groups.map((group) => (
          <tbody key={group.type}>
            <tr className="ss-grp">
              <th className="ss-unitcol" scope="rowgroup">
                {unitTypeText(language, group.type)}
              </th>
              {days.map((day) => {
                const free = group.units.filter(
                  (unit) => nightOf(unit, day).kind === "FREE",
                ).length;
                return (
                  <td className={free === 0 ? "full" : undefined} key={day}>
                    {free === 0
                      ? st(language, "grp_full")
                      : st(language, "grp_free", free)}
                  </td>
                );
              })}
            </tr>
            {group.units.map((unit) => {
              const room = roomWord(language, unit.status);
              return (
                <tr key={unit.unit_id}>
                  <th className="ss-unitcol" scope="row">
                    <b className="ui-num">{unit.unit_number}</b>
                    {room !== null && (
                      <span
                        className={`ss-room${unit.status === "VACANT" ? " ok" : unit.status === "CLEANING" ? " warn" : ""}`}
                      >
                        {room}
                      </span>
                    )}
                  </th>
                  {segmentsOf(unit, days).map((segment) => (
                    <SegmentCell
                      day={days[segment.start] ?? ""}
                      key={segment.key}
                      language={language}
                      mayBook={mayBook}
                      onOpenBooking={onOpenBooking}
                      segment={segment}
                      today={calendar.today}
                      unit={unit}
                    />
                  ))}
                </tr>
              );
            })}
          </tbody>
        ))}
      </table>
    </div>
  );
}

function SegmentCell({
  language,
  segment,
  unit,
  day,
  today,
  mayBook,
  onOpenBooking,
}: {
  language: Language;
  segment: Segment;
  unit: CalendarUnit;
  day: string;
  today: string;
  mayBook: boolean;
  onOpenBooking: (event: React.MouseEvent, bookingId: string) => void;
}) {
  const { night } = segment;
  if (night.kind === "FREE") {
    return (
      <td className="ss-cell ss-free">
        {day >= today && mayBook ? (
          <a
            aria-label={st(
              language,
              "cal_book",
              unit.unit_number,
              dayText(day),
            )}
            href={hashForPage("shortstays", `new:${unit.unit_id}:${day}`)}
          >
            +
          </a>
        ) : (
          <span className="ui-sr">{st(language, "cal_free")}</span>
        )}
      </td>
    );
  }
  if (night.kind === "BOOKING") {
    const { booking } = night;
    const unpaid = booking.status === "BOOKED" && !booking.paid;
    const name = booking.guest_name;
    const label = unpaid
      ? st(language, "bar_unpaid", name)
      : booking.status === "CHECKED_OUT"
        ? st(language, "bar_out", name)
        : name;
    return (
      <td
        className={`ss-cell${night.clash === null ? "" : " ss-clash"}`}
        colSpan={segment.length}
        title={
          night.clash === null
            ? undefined
            : st(language, "cal_clash", night.clash.site_name)
        }
      >
        <a
          aria-label={`${label} · ${booking.booking_number}`}
          className={`ss-bar ${bookingTone(booking)}`}
          href={hashForPage("shortstays", `st:${booking.booking_id}`)}
          onClick={(event) => {
            onOpenBooking(event, booking.booking_id);
          }}
          title={`${booking.booking_number} · ${label}`}
        >
          {unpaid && <span aria-hidden="true" className="ss-dot" />}
          <span>{name}</span>
        </a>
      </td>
    );
  }
  const word =
    night.kind === "HOLD"
      ? night.hold.site_name
      : {
          LEASE: st(language, "lease"),
          RESERVED: st(language, "reserved"),
          NOT_FOR_RENT: st(language, "not_for_rent"),
          CLOSED: st(language, "cal_closed"),
        }[night.kind];
  const title =
    night.kind === "HOLD"
      ? st(
          language,
          "b_SITE_HOLD",
          night.hold.site_name,
          dayText(night.hold.start_on),
          dayText(night.hold.end_on),
        )
      : undefined;
  const tone =
    night.kind === "HOLD"
      ? "site"
      : night.kind === "LEASE"
        ? "lease"
        : "closed";
  return (
    <td className="ss-cell" colSpan={segment.length} title={title}>
      <span className={`ss-bar ${tone}`}>
        <span>{word}</span>
      </span>
    </td>
  );
}
