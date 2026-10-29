// V1-060 B6 (owner 27/10/2026): a date box that takes a typed day as dd/mm/yyyy (for example
// 15/03/1986), so a year far back needs no paging through the calendar, and a calendar button
// beside it for picking a day. The calendar is drawn here, large enough to tap on the iPad, with
// month and year lists: the browser's own calendar cannot be made bigger. The value given and sent is yyyy-mm-dd; a box that does not hold a
// whole, real day sends what was typed (or "" when empty), so the form's own check refuses it.

import { RefObject, useEffect, useLayoutEffect, useRef, useState } from "react";

import { dayText } from "./format";
import { Icon } from "./icons";

/** yyyy-mm-dd from what was typed: dd/mm/yyyy (also with "-" or "."), or yyyy-mm-dd. */
export function parseDay(typed: string): string {
  const text = typed.trim();
  let match = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(text);
  let year: string, month: string, day: string;
  if (match !== null) {
    [, year = "", month = "", day = ""] = match;
  } else {
    match = /^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$/.exec(text);
    if (match === null) return "";
    [, day = "", month = "", year = ""] = match;
  }
  // V1-060 B7: a year before 1900 is a typing slip here ("01/01/0000"), never a real day.
  if (Number(year) < 1900) return "";
  const iso = `${year}-${month.padStart(2, "0")}-${day.padStart(2, "0")}`;
  const date = new Date(`${iso}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) &&
    date.toISOString().slice(0, 10) === iso
    ? iso
    : "";
}

/** A real day written yyyy-mm-dd, as a date box passes it on once a whole day is typed. */
export function isDay(value: string): boolean {
  return value !== "" && parseDay(value) === value;
}

/** Adds the slashes while digits are typed: "1503" → "15/03", "15031986" → "15/03/1986".
 * V1-060 B7: also after the slashes it added ("15/031" → "15/03/1"), so a keypad with no "/"
 * still gets both; slashes typed in other places ("5/3/1986") stay as typed. Only text added at
 * the end is shaped: an edit inside the date, a deletion, text that already has both slashes or
 * more than eight digits stays as typed, so the form refuses a wrong day instead of the box
 * quietly making another one. Third review: up to eight digits alone (a day pasted over the
 * whole box) are shaped too, as slashes then only go between them. */
function withSlashes(typed: string, before: string, atEnd: boolean): string {
  if (
    !atEnd ||
    (!/^\d{1,8}$/.test(typed) &&
      (typed.length <= before.length ||
        !typed.startsWith(before) ||
        /^\d{2}\/\d{2}\//.test(before) ||
        !/^(\d{2}\/(\d{2}\/)?)?\d*$/.test(typed)))
  )
    return typed;
  const digits = typed.replace(/\//g, "");
  if (digits.length > 8) return typed;
  // A slash typed where one goes stays ("15/").
  const end =
    typed.endsWith("/") && (digits.length === 2 || digits.length === 4)
      ? "/"
      : "";
  if (digits.length <= 2) return digits + end;
  if (digits.length <= 4)
    return `${digits.slice(0, 2)}/${digits.slice(2)}${end}`;
  return `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}`;
}

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
const WEEKDAYS = {
  en: ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"],
  km: ["ច", "អ", "ព", "ព្រ", "សុ", "ស", "អា"],
} as const;
const WORDS = {
  en: {
    previous: "Previous month",
    next: "Next month",
    month: "Month",
    year: "Year",
    today: "Today",
    close: "Close calendar",
  },
  km: {
    previous: "ខែមុន",
    next: "ខែបន្ទាប់",
    month: "ខែ",
    year: "ឆ្នាំ",
    today: "ថ្ងៃនេះ",
    close: "បិទប្រតិទិន",
  },
} as const;

const WRONG_DAY = {
  en: "This is not a real day. Type it as dd/mm/yyyy, for example 28/02/2026.",
  km: "នេះមិនមែនជាថ្ងៃពិតទេ។ សូមវាយជា ថ្ងៃ/ខែ/ឆ្នាំ ឧទាហរណ៍ 28/02/2026។",
} as const;

function iso(year: number, month: number, day: number): string {
  return `${String(year).padStart(4, "0")}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

/** Today in Phnom Penh as yyyy-mm-dd. */
function todayIso(): string {
  return new Date(Date.now() + 7 * 3_600_000).toISOString().slice(0, 10);
}

function Calendar({
  value,
  min,
  max,
  language,
  onPick,
  onClose,
  anchor,
}: {
  /** The date box and its button: the calendar floats under it (or above, without room). */
  anchor: RefObject<HTMLElement | null>;
  value: string;
  min?: string;
  max?: string;
  language: "en" | "km";
  onPick: (value: string) => void;
  /** refocus: the calendar had the focus (Close, Escape), so it goes back to the button. */
  onClose: (refocus: boolean) => void;
}) {
  const today = todayIso();
  const start = value !== "" ? value : today;
  const [year, setYear] = useState(Number(start.slice(0, 4)));
  const [month, setMonth] = useState(Number(start.slice(5, 7)) - 1);
  const words = WORDS[language];
  const thisYear = Number(today.slice(0, 4));
  const firstYear = min ? Number(min.slice(0, 4)) : thisYear - 100;
  const lastYear = max ? Number(max.slice(0, 4)) : thisYear + 10;
  const years: number[] = [];
  for (let y = Math.min(firstYear, year); y <= Math.max(lastYear, year); y += 1)
    years.push(y);
  const days = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  // Monday first: 0 for a month starting on Monday.
  const lead = (new Date(Date.UTC(year, month, 1)).getUTCDay() + 6) % 7;
  const outside = (day: string) =>
    (min !== undefined && min !== "" && day < min) ||
    (max !== undefined && max !== "" && day > max);
  // Floats over the page (position: fixed), so a dialog or card never cuts it off; it follows
  // the box while the page scrolls and closes on a tap outside the box and the calendar.
  const box = useRef<HTMLDivElement>(null);
  const [place, setPlace] = useState<{ top: number; left: number } | null>(
    null,
  );
  const shut = useRef(onClose);
  useEffect(() => {
    shut.current = onClose;
  });
  useLayoutEffect(() => {
    const measure = () => {
      const field = anchor.current?.getBoundingClientRect();
      const own = box.current?.getBoundingClientRect();
      if (field === undefined || own === undefined) return;
      const gap = 6;
      const below = field.bottom + gap;
      const top =
        below + own.height > window.innerHeight &&
        field.top - gap - own.height >= 0
          ? field.top - gap - own.height
          : below;
      const left = Math.max(
        8,
        Math.min(field.left, window.innerWidth - own.width - 8),
      );
      setPlace((now) =>
        now?.top === top && now.left === left ? now : { top, left },
      );
    };
    measure();
    const away = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (
        target !== null &&
        !anchor.current?.contains(target) &&
        !box.current?.contains(target)
      )
        shut.current(false);
    };
    window.addEventListener("scroll", measure, true);
    window.addEventListener("resize", measure);
    document.addEventListener("pointerdown", away);
    return () => {
      window.removeEventListener("scroll", measure, true);
      window.removeEventListener("resize", measure);
      document.removeEventListener("pointerdown", away);
    };
  }, [anchor, year, month]);

  const step = (by: number) => {
    const next = month + by;
    setYear(year + Math.floor(next / 12));
    setMonth(((next % 12) + 12) % 12);
  };

  return (
    <div
      className="ui-cal"
      ref={box}
      style={
        place === null
          ? { visibility: "hidden", top: 0, left: 0 }
          : { top: place.top, left: place.left }
      }
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          onClose(true);
        }
      }}
      role="group"
    >
      <div className="ui-cal-head">
        <button
          aria-label={words.previous}
          className="ui-cal-nav"
          onClick={() => {
            step(-1);
          }}
          type="button"
        >
          ‹
        </button>
        <select
          aria-label={words.month}
          onChange={(event) => {
            setMonth(Number(event.currentTarget.value));
          }}
          value={month}
        >
          {MONTHS[language].map((name, index) => (
            <option key={name} value={index}>
              {name}
            </option>
          ))}
        </select>
        <select
          aria-label={words.year}
          onChange={(event) => {
            setYear(Number(event.currentTarget.value));
          }}
          value={year}
        >
          {years.map((y) => (
            <option key={y} value={y}>
              {y}
            </option>
          ))}
        </select>
        <button
          aria-label={words.next}
          className="ui-cal-nav"
          onClick={() => {
            step(1);
          }}
          type="button"
        >
          ›
        </button>
      </div>
      <div className="ui-cal-grid">
        {WEEKDAYS[language].map((name) => (
          <span className="ui-cal-wd" key={name}>
            {name}
          </span>
        ))}
        {Array.from({ length: lead }, (_, index) => (
          <span key={`lead-${String(index)}`} />
        ))}
        {Array.from({ length: days }, (_, index) => {
          const day = iso(year, month, index + 1);
          return (
            <button
              aria-label={dayText(day)}
              aria-pressed={day === value}
              className={`ui-cal-day${day === value ? " on" : ""}${day === today ? " today" : ""}`}
              disabled={outside(day)}
              key={day}
              onClick={() => {
                onPick(day);
              }}
              type="button"
            >
              {index + 1}
            </button>
          );
        })}
      </div>
      <div className="ui-cal-foot">
        <button
          className="ui-btn"
          disabled={outside(today)}
          onClick={() => {
            onPick(today);
          }}
          type="button"
        >
          {words.today}
        </button>
        <button
          className="ui-btn"
          onClick={() => {
            onClose(true);
          }}
          type="button"
        >
          {words.close}
        </button>
      </div>
    </div>
  );
}

export interface DateInputProps {
  id: string;
  /** yyyy-mm-dd or "". Leave out for a box that keeps its own value (with `name`). */
  value?: string;
  defaultValue?: string;
  onChange?: (value: string) => void;
  /** The form field that carries yyyy-mm-dd, for forms read with FormData. */
  name?: string;
  min?: string;
  max?: string;
  required?: boolean;
  disabled?: boolean;
  invalid?: boolean;
  describedBy?: string;
  /** The calendar button's name for screen readers, in the screen's language. */
  calendarLabel?: string;
  /** The language of the calendar's month and day names. */
  language?: "en" | "km";
}

export function DateInput({
  id,
  value,
  defaultValue = "",
  onChange,
  name,
  min,
  max,
  required,
  disabled,
  invalid,
  describedBy,
  calendarLabel = "Calendar",
  language = "en",
}: DateInputProps) {
  const [own, setOwn] = useState(defaultValue);
  const current = value ?? own;
  const [text, setText] = useState(dayText(current));
  const [open, setOpen] = useState(false);
  // V1-061 (owner test 29/10): a whole date that is not a real day (30/02/2026) is said at once
  // when the box is left, not only when the form is saved.
  const [wrong, setWrong] = useState(false);
  const wrapper = useRef<HTMLSpanElement>(null);
  const button = useRef<HTMLButtonElement>(null);

  // V1-060 B7 (WCAG 2.4.3): a calendar that closes while it has the focus gives it back to its
  // button, so the next Tab stays in the dialog; a tap outside keeps the focus where it went.
  function close(refocus: boolean) {
    setOpen(false);
    if (refocus) button.current?.focus();
  }

  // A new value from outside (a default, the calendar, another field) shows as dd/mm/yyyy;
  // what is being typed stays as typed while it means the same day.
  useEffect(() => {
    setText((typed) =>
      parseDay(typed) === current || typed.trim() === current
        ? typed
        : dayText(current),
    );
  }, [current]);

  function set(next: string) {
    if (value === undefined) setOwn(next);
    onChange?.(next);
  }

  return (
    <span
      className="ui-date"
      onKeyDown={(event) => {
        // V1-060 B7: Escape on the box or its button while the calendar is open closes the
        // calendar only, never the dialog around it (that would lose what was typed there).
        if (event.key === "Escape" && open) {
          event.stopPropagation();
          close(false);
        }
      }}
      ref={wrapper}
    >
      <input
        aria-describedby={describedBy}
        aria-invalid={invalid === true || wrong}
        autoComplete="off"
        disabled={disabled}
        id={id}
        inputMode="numeric"
        onBlur={() => {
          const parsed = parseDay(text);
          if (parsed !== "") setText(dayText(parsed));
          setWrong(parsed === "" && text.trim() !== "");
        }}
        onChange={(event) => {
          const box = event.currentTarget;
          const typed = withSlashes(
            box.value,
            text,
            box.selectionStart === box.value.length,
          );
          setText(typed);
          setWrong(false);
          const parsed = parseDay(typed);
          const next = parsed === "" ? typed.trim() : parsed;
          if (next !== current) set(next);
        }}
        placeholder="dd/mm/yyyy"
        required={required}
        type="text"
        value={text}
      />
      {name !== undefined && (
        <input name={name} type="hidden" value={current} />
      )}
      <button
        aria-expanded={open}
        aria-label={calendarLabel}
        className="ui-date-button"
        disabled={disabled}
        onClick={() => {
          setOpen(!open);
        }}
        ref={button}
        type="button"
      >
        <Icon name="calendar" small />
      </button>
      {open && !disabled && (
        <Calendar
          anchor={wrapper}
          language={language}
          max={max}
          min={min}
          onClose={close}
          onPick={(picked) => {
            setWrong(false);
            setText(dayText(picked));
            set(picked);
            close(true);
          }}
          value={parseDay(current)}
        />
      )}
      {wrong && (
        <span className="ui-date-wrong" lang={language} role="alert">
          {WRONG_DAY[language]}
        </span>
      )}
    </span>
  );
}
