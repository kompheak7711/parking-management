// V1-060 B6 (owner 27/10/2026): a date box that takes a typed day as dd/mm/yyyy (for example
// 15/03/1986), so a year far back needs no paging through the calendar, and a calendar button
// beside it for picking a day. The value given and sent is yyyy-mm-dd; a box that does not hold a
// whole, real day sends what was typed (or "" when empty), so the form's own check refuses it.

import { useEffect, useRef, useState } from "react";

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
  const iso = `${year}-${month.padStart(2, "0")}-${day.padStart(2, "0")}`;
  const date = new Date(`${iso}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) &&
    date.toISOString().slice(0, 10) === iso
    ? iso
    : "";
}

/** Adds the slashes while digits are typed: "1503" → "15/03", "15031986" → "15/03/1986". */
function withSlashes(typed: string): string {
  if (!/^\d+$/.test(typed)) return typed;
  const digits = typed.slice(0, 8);
  if (digits.length <= 2) return digits;
  if (digits.length <= 4) return `${digits.slice(0, 2)}/${digits.slice(2)}`;
  return `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}`;
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
}: DateInputProps) {
  const [own, setOwn] = useState(defaultValue);
  const current = value ?? own;
  const [text, setText] = useState(dayText(current));
  const picker = useRef<HTMLInputElement>(null);

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
    <span className="ui-date">
      <input
        aria-describedby={describedBy}
        aria-invalid={invalid}
        autoComplete="off"
        disabled={disabled}
        id={id}
        inputMode="numeric"
        onBlur={() => {
          const parsed = parseDay(text);
          if (parsed !== "") setText(dayText(parsed));
        }}
        onChange={(event) => {
          const typed = withSlashes(event.currentTarget.value);
          setText(typed);
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
      <input
        aria-hidden="true"
        className="ui-date-picker"
        disabled={disabled}
        max={max}
        min={min}
        onChange={(event) => {
          const picked = event.currentTarget.value;
          setText(dayText(picked));
          set(picked);
        }}
        ref={picker}
        tabIndex={-1}
        type="date"
        value={parseDay(current)}
      />
      <button
        aria-label={calendarLabel}
        className="ui-date-button"
        disabled={disabled}
        onClick={() => {
          const box = picker.current;
          if (box === null) return;
          try {
            box.showPicker();
          } catch {
            box.focus();
            box.click();
          }
        }}
        type="button"
      >
        <Icon name="calendar" small />
      </button>
    </span>
  );
}
