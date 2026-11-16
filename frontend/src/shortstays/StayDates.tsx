// Owner 16/11/2026 (picture of a hotel site's calendar): New booking picks the stay on a calendar of
// two months side by side. The first tap is the check-in day, the second the check-out day; the
// nights between are shown at once, in the box and under the calendar. A phone shows one month.

import { type KeyboardEvent, useEffect, useRef, useState } from "react";

import { dayText } from "../shell/format";
import { Icon } from "../shell/icons";
import type { Language } from "../signInText";
import { nightsText } from "./ShortStaysPage";
import { addDays, daysBetween } from "./shortStaysClient";
import { st } from "./text";

const MONTHS = {
  en: [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
  ],
  km: [
    "មករា",
    "កុម្ភៈ",
    "មីនា",
    "មេសា",
    "ឧសភា",
    "មិថុនា",
    "កក្កដា",
    "សីហា",
    "កញ្ញា",
    "តុលា",
    "វិច្ឆិកា",
    "ធ្នូ",
  ],
} as const;
// Monday first, as the app's other calendars.
const WEEKDAYS = {
  en: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
  km: ["ច", "អ", "ព", "ព្រ", "សុ", "ស", "អា"],
} as const;

/** "Tue 17/11/2026": the weekday helps the desk read the stay at a glance. */
export function dayWithWeekday(language: Language, day: string): string {
  const index = (new Date(`${day}T00:00:00Z`).getUTCDay() + 6) % 7;
  return `${WEEKDAYS[language === "km" ? "km" : "en"][index] ?? ""} ${dayText(day)}`;
}

function monthStart(day: string): string {
  return `${day.slice(0, 7)}-01`;
}

function addMonths(first: string, months: number): string {
  const moment = new Date(`${first}T00:00:00Z`);
  moment.setUTCMonth(moment.getUTCMonth() + months);
  return moment.toISOString().slice(0, 10);
}

function Month({
  language,
  first,
  second,
  checkIn,
  checkOut,
  shownOut,
  today,
  tabDay,
  onPick,
  onHover,
}: {
  language: Language;
  /** yyyy-mm-01 of this month. */
  first: string;
  /** The month on the right, hidden on a phone. */
  second: boolean;
  checkIn: string;
  checkOut: string;
  /** The check-out shown: the one picked, or the day under the pointer while picking it. */
  shownOut: string;
  today: string;
  /** The one day Tab reaches; the arrow keys move from it. */
  tabDay: string;
  onPick: (day: string) => void;
  onHover: (day: string) => void;
}) {
  const lang = language === "km" ? "km" : "en";
  const year = Number(first.slice(0, 4));
  const month = Number(first.slice(5, 7)) - 1;
  const days = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  const lead = (new Date(Date.UTC(year, month, 1)).getUTCDay() + 6) % 7;
  const title = `${MONTHS[lang][month] ?? ""} ${String(year)}`;
  return (
    <div className={second ? "ss-range-month second" : "ss-range-month"}>
      <h3 className="ss-range-title">{title}</h3>
      <div className="ss-range-grid">
        {WEEKDAYS[lang].map((name, index) => (
          <span
            aria-hidden="true"
            className={index >= 5 ? "ss-range-wd we" : "ss-range-wd"}
            key={name}
          >
            {name}
          </span>
        ))}
        {Array.from({ length: lead }, (_, index) => (
          <span key={`lead-${String(index)}`} />
        ))}
        {Array.from({ length: days }, (_, index) => {
          const day = `${first.slice(0, 8)}${String(index + 1).padStart(2, "0")}`;
          const isIn = day === checkIn;
          const isOut = shownOut !== "" && day === shownOut;
          const between =
            checkIn !== "" &&
            shownOut !== "" &&
            day > checkIn &&
            day < shownOut;
          const names = ["ss-range-day"];
          if (isIn) names.push("in");
          if (isOut) names.push("out");
          if (between) names.push("mid");
          if (day === today) names.push("today");
          if (isOut && shownOut !== checkOut) names.push("preview");
          return (
            <button
              aria-label={dayWithWeekday(language, day)}
              aria-pressed={isIn || (isOut && shownOut === checkOut)}
              className={names.join(" ")}
              data-day={day}
              disabled={day < today}
              key={day}
              onClick={() => {
                onPick(day);
              }}
              onFocus={() => {
                onHover(day);
              }}
              onMouseEnter={() => {
                onHover(day);
              }}
              tabIndex={day === tabDay ? 0 : -1}
              type="button"
            >
              {index + 1}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function StayDates({
  id,
  language,
  checkIn,
  checkOut,
  today,
  disabled,
  invalid,
  describedBy,
  startOpen,
  onChange,
}: {
  id: string;
  language: Language;
  /** yyyy-mm-dd, or "" before a day is picked. */
  checkIn: string;
  checkOut: string;
  /** No day before today can be picked. */
  today: string;
  disabled?: boolean;
  invalid?: boolean;
  describedBy?: string;
  /** Open at first: the dates are the first thing to choose. */
  startOpen?: boolean;
  onChange: (checkIn: string, checkOut: string) => void;
}) {
  const [open, setOpen] = useState(startOpen === true);
  // After a full stay the next tap starts a new one; after the check-in it is the check-out.
  const [pickingOut, setPickingOut] = useState(
    checkIn !== "" && checkOut === "",
  );
  const [hover, setHover] = useState("");
  const [view, setView] = useState(
    monthStart(checkIn === "" ? today : checkIn),
  );
  const [focusDay, setFocusDay] = useState("");
  const field = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);

  // A day reached with the arrow keys gets the focus once its month is drawn.
  useEffect(() => {
    if (focusDay === "") return;
    panel.current
      ?.querySelector<HTMLButtonElement>(`[data-day="${focusDay}"]`)
      ?.focus();
  }, [focusDay, view]);

  const nights =
    checkIn !== "" && checkOut !== "" ? daysBetween(checkIn, checkOut) : null;
  const shownOut =
    pickingOut && hover !== "" && checkIn !== "" && hover > checkIn
      ? hover
      : pickingOut
        ? ""
        : checkOut;
  const shownNights =
    checkIn !== "" && shownOut !== "" ? daysBetween(checkIn, shownOut) : null;

  const pick = (day: string) => {
    if (pickingOut && checkIn !== "" && day > checkIn) {
      onChange(checkIn, day);
      setPickingOut(false);
      setHover("");
      setOpen(false);
      field.current?.focus();
      return;
    }
    onChange(day, "");
    setPickingOut(true);
  };

  const keys = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      setOpen(false);
      field.current?.focus();
      return;
    }
    const target = event.target as HTMLElement;
    const day = target.dataset.day;
    const by: Record<string, number> = {
      ArrowLeft: -1,
      ArrowRight: 1,
      ArrowUp: -7,
      ArrowDown: 7,
    };
    const step = by[event.key];
    if (day === undefined || step === undefined) return;
    event.preventDefault();
    const next = addDays(day, step);
    if (next < today) return;
    const last = addMonths(view, 2);
    if (next < view) setView(monthStart(next));
    else if (next >= last) setView(addMonths(monthStart(next), -1));
    setFocusDay(next);
  };

  const firstMonth = view <= monthStart(today);
  const end = addMonths(view, 2);
  const tabDay =
    focusDay !== "" && focusDay >= view && focusDay < end
      ? focusDay
      : checkIn !== "" && checkIn >= view && checkIn < end
        ? checkIn
        : today > view
          ? today
          : view;
  return (
    <div className="ss-range">
      <button
        aria-controls={`${id}-panel`}
        aria-describedby={describedBy}
        aria-expanded={open}
        aria-invalid={invalid === true}
        className="ss-range-field"
        disabled={disabled}
        id={id}
        onClick={() => {
          setOpen(!open);
        }}
        ref={field}
        type="button"
      >
        <Icon name="calendar" small />
        <span className="ui-num">
          {checkIn === ""
            ? st(language, "rg_none")
            : dayWithWeekday(language, checkIn)}
        </span>
        <span aria-hidden="true">–</span>
        <span className="ui-num">
          {checkOut === "" ? "…" : dayWithWeekday(language, checkOut)}
        </span>
        {nights !== null && (
          <span className="ss-range-nights">
            {nightsText(language, nights)}
          </span>
        )}
      </button>
      {open && !disabled && (
        <div
          aria-label={st(language, "f_dates")}
          className="ss-range-panel"
          id={`${id}-panel`}
          onKeyDown={keys}
          onMouseLeave={() => {
            setHover("");
          }}
          ref={panel}
          role="group"
        >
          <button
            aria-label={st(language, "rg_prev")}
            className="ss-range-nav prev"
            disabled={firstMonth}
            onClick={() => {
              setView(addMonths(view, -1));
            }}
            type="button"
          >
            <Icon name="chevron" small />
          </button>
          <button
            aria-label={st(language, "rg_next")}
            className="ss-range-nav next"
            onClick={() => {
              setView(addMonths(view, 1));
            }}
            type="button"
          >
            <Icon name="chevron" small />
          </button>
          <div className="ss-range-months">
            {[0, 1].map((index) => (
              <Month
                checkIn={checkIn}
                checkOut={checkOut}
                first={addMonths(view, index)}
                key={index}
                language={language}
                onHover={setHover}
                onPick={pick}
                second={index === 1}
                shownOut={shownOut}
                tabDay={tabDay}
                today={today}
              />
            ))}
          </div>
          <div className="ss-range-foot">
            <p aria-live="polite">
              {checkIn === "" ? (
                st(language, "rg_in")
              ) : shownNights === null ? (
                st(language, "rg_out")
              ) : (
                <>
                  <span className="ui-num">
                    {st(
                      language,
                      "d_dates",
                      dayWithWeekday(language, checkIn),
                      dayWithWeekday(language, shownOut),
                    )}
                  </span>{" "}
                  <b>({nightsText(language, shownNights)})</b>
                </>
              )}
            </p>
            <button
              className="ui-btn"
              onClick={() => {
                setOpen(false);
                field.current?.focus();
              }}
              type="button"
            >
              {st(language, "rg_close")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
