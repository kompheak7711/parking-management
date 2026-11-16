// UI v81 round 11 (owner 12/11/2026: "check all card is link to correct place"): the coming
// birthdays on the Customers page. Home's "Birthdays" card opens "#/customers?show=birthdays";
// the list is what the card counts: the Primary Tenants and Occupants of active Leases with a
// birthday today or in the next 7 days. As in mock-up v81's Birthdays page, a second group
// lists the birthdays later this month. The read (GET /properties/{id}/birthdays,
// customers.read) gives each person's next birthday; only the day and month show, never the
// year or the age. Read only.

import { useEffect, useState } from "react";

import { type BirthdayRow, reportsApi } from "../reportsClient";
import { todayInPhnomPenh } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import type { Language } from "../signInText";
import { ct } from "./text";

export type BirthdaysApi = Pick<typeof reportsApi, "birthdays">;

/** Whole days from `from` to `to`, both "yyyy-mm-dd". */
function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(to) - Date.parse(from)) / 86_400_000);
}

/** "2026-11-14" → "14/11": the day and month only. */
export function birthdayText(day: string): string {
  return `${day.slice(8, 10)}/${day.slice(5, 7)}`;
}

export function BirthdaysCard({
  language,
  propertyId,
  onHide,
  api = reportsApi,
  today = todayInPhnomPenh(),
}: {
  language: Language;
  propertyId: string;
  onHide: () => void;
  api?: BirthdaysApi;
  today?: string;
}) {
  const [rows, setRows] = useState<BirthdayRow[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (propertyId === "") return;
    let current = true;
    api.birthdays(propertyId).then(
      (page) => {
        if (!current) return;
        setFailed(false);
        setRows(page.items);
      },
      () => {
        if (!current) return;
        setRows(null);
        setFailed(true);
      },
    );
    return () => {
      current = false;
    };
  }, [api, propertyId, attempt]);

  const daysTo = (row: BirthdayRow) =>
    daysBetween(today, row.birthday.slice(0, 10));
  const when = (row: BirthdayRow) => {
    const days = daysTo(row);
    if (days <= 0) return ct(language, "bd_today");
    if (days === 1) return ct(language, "bd_tomorrow");
    return ct(language, "bd_in", days);
  };
  const sorted = [...(rows ?? [])].sort(
    (left, right) =>
      left.birthday.localeCompare(right.birthday) ||
      left.unit_number.localeCompare(right.unit_number, undefined, {
        numeric: true,
      }),
  );
  // Home's card counts today and the next 7 days; the first group is exactly those.
  const week = sorted.filter((row) => daysTo(row) <= 7);
  const later = sorted.filter(
    (row) => daysTo(row) > 7 && row.birthday.startsWith(today.slice(0, 7)),
  );
  const list = (items: BirthdayRow[]) =>
    items.length === 0 ? (
      <p className="ui-muted">{ct(language, "bd_none")}</p>
    ) : (
      <ul className="ui-todos">
        {items.map((row) => (
          <li
            className="ui-todo info"
            key={`${row.customer_id}:${row.unit_id}`}
          >
            <span aria-hidden="true" className="ui-todo-icon">
              <Icon name="customers" />
            </span>
            <span className="ui-todo-body">
              <b>{row.customer_name}</b>
              <span>
                {ct(
                  language,
                  row.role === "OCCUPANT" ? "bd_occupant" : "bd_primary",
                )}
                {" · "}
                <a className="ui-num" href={hashForPage("units", row.unit_id)}>
                  {row.unit_number}
                </a>
              </span>
            </span>
            <span className="ui-when ui-num">
              {birthdayText(row.birthday)}
              <small>{when(row)}</small>
            </span>
            <a
              aria-label={`${ct(language, "bd_open")}: ${row.customer_name}`}
              className="ui-iconbtn ui-todo-go"
              href={hashForPage("customers", row.customer_id)}
              title={ct(language, "bd_open")}
            >
              <Icon name="forward" />
            </a>
          </li>
        ))}
      </ul>
    );

  return (
    <section aria-labelledby="customers-birthdays" className="ui-card">
      <header className="ui-chead">
        <h2 id="customers-birthdays">
          {ct(language, "bd_title")}
          {rows !== null && (
            <>
              {" "}
              <span className="ui-count ui-num">{week.length}</span>
            </>
          )}
        </h2>
        <span className="ui-actions">
          <button className="ui-btn link" onClick={onHide} type="button">
            {ct(language, "bd_hide")}
          </button>
        </span>
      </header>
      {failed ? (
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{ct(language, "bd_failed")}</p>
          <button
            className="ui-btn"
            onClick={() => {
              setFailed(false);
              setAttempt((value) => value + 1);
            }}
            type="button"
          >
            {ct(language, "retry")}
          </button>
        </div>
      ) : rows === null ? (
        <p className="ui-muted" role="status">
          {ct(language, "bd_loading")}
        </p>
      ) : (
        <div className="ui-tasks-list">
          <h3>
            <span className="ui-dot info" />
            {ct(language, "bd_week")}
            <span className="ui-count ui-num">{week.length}</span>
          </h3>
          {list(week)}
          {later.length > 0 && (
            <>
              <h3>
                <span className="ui-dot neutral" />
                {ct(language, "bd_later")}
                <span className="ui-count ui-num">{later.length}</span>
              </h3>
              {list(later)}
            </>
          )}
        </div>
      )}
    </section>
  );
}
