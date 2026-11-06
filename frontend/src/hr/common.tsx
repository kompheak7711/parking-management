// HRIS phase 6: small pieces the four HR screens share. The server checks every right, rule
// and amount again, so these only help the person type the right thing.

import "../shell/screens.css";

import { type ReactNode, useState } from "react";

import { usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import type { Language } from "../signInText";
import { HrError, type Named, type ShiftCode } from "./hrClient";
import { codeText, ht } from "./text";

export function money(cents: number | null | undefined): string {
  return cents === null || cents === undefined ? "" : usdFromCents(cents);
}

/** The person's or thing's name in the chosen language; English when Khmer is empty. */
export function nameOf(language: Language, item: Named): string {
  return language === "km" && item.name_km.trim() !== ""
    ? item.name_km
    : item.name_en;
}

export function shiftText(language: Language, code: ShiftCode | null): string {
  return code === null ? "" : codeText(language, "sh_", code);
}

const CARETAKER_SHIFTS: readonly ShiftCode[] = [
  "MORNING",
  "AFTERNOON",
  "NIGHT",
];
const OFFICE_ONLY: readonly ShiftCode[] = ["OFFICE"];

/** The shifts a person can work: the caretaker's three, or office hours for any other job. */
export function shiftChoices(
  usesShifts: boolean | undefined,
): readonly ShiftCode[] {
  return usesShifts === true ? CARETAKER_SHIFTS : OFFICE_ONLY;
}

/** What the person sees when a command did not go through. */
export function failureText(language: Language, error: unknown): string {
  if (error instanceof HrError) {
    if (error.status === 403) return ht(language, "f_right");
    if (error.status === 404) return ht(language, "not_found");
    if ((error.status === 409 || error.status === 412) && error.detail === null)
      return ht(language, "f_stale");
    if (error.detail !== null && error.status !== null && error.status < 500)
      return ht(language, "f_refused", error.detail);
  }
  return ht(language, "f_failed");
}

/** One command at a time: busy while it runs, and the failure words when it fails. */
export function useHrBusy(language: Language): {
  busy: boolean;
  failure: string | null;
  setFailure: (text: string | null) => void;
  run: <T>(work: () => Promise<T>, done: (value: T) => void) => void;
} {
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const run = <T,>(work: () => Promise<T>, done: (value: T) => void) => {
    setBusy(true);
    setFailure(null);
    work().then(
      (value) => {
        setBusy(false);
        done(value);
      },
      (error: unknown) => {
        setBusy(false);
        setFailure(failureText(language, error));
      },
    );
  };
  return { busy, failure, setFailure, run };
}

export function Waiting({
  language,
  failed,
  onRetry,
}: {
  language: Language;
  failed: boolean;
  onRetry: () => void;
}) {
  if (!failed) {
    return (
      <p className="ui-muted" role="status">
        {ht(language, "loading")}
      </p>
    );
  }
  return (
    <div className="ui-notice warn" role="status">
      <Icon name="alert" />
      <p>{ht(language, "failed")}</p>
      <button className="ui-btn" onClick={onRetry} type="button">
        {ht(language, "retry")}
      </button>
    </div>
  );
}

export function NoProperty({ language }: { language: Language }) {
  return (
    <div className="ui-notice warn" role="status">
      <Icon name="alert" />
      <p>{ht(language, "no_property")}</p>
    </div>
  );
}

export function Done({ text }: { text: string | null }) {
  if (text === null) return null;
  return (
    <div className="ui-notice ok" role="status">
      <Icon name="check" />
      <p>{text}</p>
    </div>
  );
}

export function Failure({ text }: { text: string | null }) {
  if (text === null) return null;
  return (
    <p className="ui-error" role="alert">
      {text}
    </p>
  );
}

/** A labelled field; `note` is the small word after the label (Required or Optional). */
export function Field({
  id,
  label,
  note,
  help,
  error,
  children,
}: {
  id: string;
  label: string;
  note?: string;
  help?: string;
  error?: string | null;
  children: ReactNode;
}) {
  return (
    <div className="ui-field">
      <label htmlFor={id}>
        {label}
        {note !== undefined && <span className="req">{note}</span>}
      </label>
      {children}
      {help !== undefined && help !== "" && (
        <p className="ui-muted" id={`${id}-h`}>
          {help}
        </p>
      )}
      {error !== undefined && error !== null && (
        <p className="ui-error" id={`${id}-e`}>
          {error}
        </p>
      )}
    </div>
  );
}

/** The reason box most HR steps need; the server refuses a step without one. */
export function ReasonField({
  id,
  language,
  value,
  onChange,
  optional = false,
  label,
}: {
  id: string;
  language: Language;
  value: string;
  onChange: (value: string) => void;
  optional?: boolean;
  label?: string;
}) {
  return (
    <div className="ui-field">
      <label htmlFor={id}>
        {label ?? ht(language, "reason")}
        <span className="req">
          {ht(language, optional ? "optional" : "required")}
        </span>
      </label>
      <textarea
        id={id}
        maxLength={500}
        onChange={(event) => {
          onChange(event.target.value);
        }}
        required={!optional}
        rows={2}
        value={value}
      />
    </div>
  );
}

/** "120", "120.5" or "$1,200.00" in whole cents; null when it is not an amount. */
export function centsOf(typed: string): number | null {
  const value = typed.trim().replace(/[$,]/g, "");
  if (!/^\d{1,7}(\.\d{1,2})?$/.test(value)) return null;
  const [whole = "0", part = ""] = value.split(".");
  const cents = Number(whole) * 100 + Number(part.padEnd(2, "0"));
  return cents > 0 ? cents : null;
}

/** A typed time "7:05" or "07:05" as "07:05"; null when it is not a time. */
export function clockOf(typed: string): string | null {
  const match = /^(\d{1,2}):(\d{2})$/.exec(typed.trim());
  if (match === null) return null;
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  if (hours > 23 || minutes > 59) return null;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

/** "2026-11-04T07:05:00+07:00" as "07:05" in Phnom Penh. */
export function clockText(moment: string | null): string {
  if (moment === null) return "";
  const date = new Date(moment);
  if (Number.isNaN(date.getTime())) return moment;
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Phnom_Penh",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(date);
}

export function addDays(day: string, days: number): string {
  const [year = 0, month = 1, date = 1] = day.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, date + days))
    .toISOString()
    .slice(0, 10);
}

/** ISO weekday of a day: 1 Monday to 7 Sunday. */
export function weekdayOf(day: string): number {
  const [year = 0, month = 1, date = 1] = day.split("-").map(Number);
  const weekday = new Date(Date.UTC(year, month - 1, date)).getUTCDay();
  return weekday === 0 ? 7 : weekday;
}

/** The first day of the month of `day`, and the month after it. */
export function monthStart(day: string): string {
  return `${day.slice(0, 7)}-01`;
}

export function nextMonth(day: string): string {
  const [year = 0, month = 1] = day.split("-").map(Number);
  return new Date(Date.UTC(year, month, 1)).toISOString().slice(0, 10);
}

export function previousMonth(day: string): string {
  const [year = 0, month = 1] = day.split("-").map(Number);
  return new Date(Date.UTC(year, month - 2, 1)).toISOString().slice(0, 10);
}
