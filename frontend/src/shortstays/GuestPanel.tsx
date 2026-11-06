// Daily and weekly rent, phase 6 step 5b: the guest on the booking page (migration 20270607_317).
// Every stay of the guest in this building, the nights and money, the notes and the
// problem-guest mark. The front desk adds a note; a problem guest shows on every later booking.

import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { dayText, momentText, usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { Chip } from "../shell/ui";
import type { Language } from "../signInText";
import { BookingChip } from "./ShortStaysPage";
import {
  type Booking,
  type GuestHistory,
  type ShortStaysApi,
  ShortStaysError,
} from "./shortStaysClient";
import { st, type StaysTextKey } from "./text";

export function GuestPanel({
  language,
  propertyId,
  booking,
  api,
  may,
}: {
  language: Language;
  propertyId: string;
  booking: Booking;
  api: ShortStaysApi;
  may: (capability: string) => boolean;
}) {
  const [history, setHistory] = useState<GuestHistory | null>(null);
  const [failed, setFailed] = useState(false);
  const [note, setNote] = useState("");
  const [problem, setProblem] = useState(false);
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState<StaysTextKey | null>(null);
  const sequence = useRef(0);
  const customerId = booking.customer_id;

  const load = useCallback(() => {
    const operation = ++sequence.current;
    setFailed(false);
    void api
      .guest(propertyId, customerId)
      .then((found) => {
        if (operation === sequence.current) setHistory(found);
      })
      .catch(() => {
        if (operation === sequence.current) setFailed(true);
      });
  }, [api, propertyId, customerId]);

  useEffect(() => {
    load();
  }, [load]);

  const add = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setChecked(true);
    if (note.trim() === "" || busy) return;
    const operation = ++sequence.current;
    setBusy(true);
    setRefused(null);
    void api
      .addGuestNote(propertyId, customerId, {
        note: note.trim(),
        problem_guest: problem,
        booking_id: booking.booking_id,
      })
      .then((found) => {
        if (operation !== sequence.current) return;
        setHistory(found);
        setNote("");
        setProblem(false);
        setChecked(false);
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        setRefused(
          error instanceof ShortStaysError && error.status === 403
            ? "f_step_right"
            : "f_failed",
        );
      })
      .finally(() => {
        setBusy(false);
      });
  };

  const others = (history?.stays ?? []).filter(
    (stay) => stay.booking_id !== booking.booking_id,
  );
  const problemGuest = history?.problem_guest ?? booking.problem_guest;
  return (
    <section aria-labelledby="ss-guest" className="ui-card">
      <div className="ui-hrow">
        <h2 id="ss-guest">{st(language, "gh_t")}</h2>
        {problemGuest && <Chip tone="warn">{st(language, "gh_problem")}</Chip>}
        {(history?.returning ?? booking.returning_guest) ? (
          <Chip tone="ok">{st(language, "gh_returning")}</Chip>
        ) : (
          <Chip tone="neutral">{st(language, "gh_new")}</Chip>
        )}
      </div>
      <p>
        <b>{booking.guest_name}</b>
        {booking.guest_phone !== null && (
          <span className="ui-sub2 ui-num">{booking.guest_phone}</span>
        )}
      </p>
      {failed ? (
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{st(language, "failed")}</p>
          <button className="ui-btn" onClick={load} type="button">
            {st(language, "retry")}
          </button>
        </div>
      ) : history === null ? (
        <p className="ui-muted" role="status">
          {st(language, "loading")}
        </p>
      ) : (
        <>
          <p className="ui-small ui-muted ui-num">
            {st(
              language,
              "gh_sum",
              history.stays_done,
              history.nights_done,
              usdFromCents(history.spent_usd_cents),
            )}
          </p>
          {others.length > 0 && (
            <>
              <h3>{st(language, "gh_stays")}</h3>
              <ul className="ui-plain ss-ready">
                {others.map((stay) => (
                  <li key={stay.booking_id}>
                    <a
                      className="ui-num"
                      href={hashForPage("shortstays", `st:${stay.booking_id}`)}
                    >
                      {stay.booking_number}
                    </a>
                    <span className="ui-num">
                      {stay.unit_number} ·{" "}
                      {st(
                        language,
                        "d_dates",
                        dayText(stay.check_in_on),
                        dayText(stay.check_out_on),
                      )}
                    </span>
                    <BookingChip language={language} status={stay.status} />
                  </li>
                ))}
              </ul>
            </>
          )}
          <h3>{st(language, "gh_notes")}</h3>
          {history.notes.length === 0 ? (
            <p className="ui-small ui-muted">{st(language, "gh_no_notes")}</p>
          ) : (
            <ul className="ui-plain ss-notes">
              {history.notes.map((entry, index) => (
                <li key={index}>
                  {entry.problem_guest && (
                    <Chip tone="warn">{st(language, "gh_problem")}</Chip>
                  )}
                  <span className="note">{entry.note}</span>
                  <small className="ui-muted ui-num">
                    {momentText(entry.created_at)}
                    {entry.booking_number !== null &&
                      ` · ${entry.booking_number}`}
                  </small>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      {may("short_stays.desk") && (
        <form className="ui-form ss-form" noValidate onSubmit={add}>
          <div className="ui-field">
            <label htmlFor="ss-guest-note">{st(language, "gh_note")}</label>
            <textarea
              aria-invalid={checked && note.trim() === ""}
              disabled={busy}
              id="ss-guest-note"
              maxLength={500}
              onChange={(event) => {
                setNote(event.currentTarget.value);
              }}
              rows={2}
              value={note}
            />
            {checked && note.trim() === "" && (
              <p className="ui-error">
                <Icon name="alert" small />
                <span>{st(language, "gh_empty")}</span>
              </p>
            )}
          </div>
          <label className="ui-chk">
            <input
              checked={problem}
              disabled={busy}
              onChange={(event) => {
                setProblem(event.currentTarget.checked);
              }}
              type="checkbox"
            />
            {st(language, "gh_mark")}
          </label>
          {refused !== null && (
            <p className="ui-error" role="alert">
              <Icon name="alert" small />
              <span>{st(language, refused)}</span>
            </p>
          )}
          <div className="ui-actions">
            <button className="ui-btn" disabled={busy} type="submit">
              {st(language, "gh_add")}
            </button>
            {may("customers.read") && (
              <a
                className="ui-btn"
                href={hashForPage("customers", booking.customer_id)}
              >
                {st(language, "d_open_customer")}
              </a>
            )}
          </div>
        </form>
      )}
      {!may("short_stays.desk") && may("customers.read") && (
        <div className="ui-actions">
          <a
            className="ui-btn"
            href={hashForPage("customers", booking.customer_id)}
          >
            {st(language, "d_open_customer")}
          </a>
        </div>
      )}
    </section>
  );
}
