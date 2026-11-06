// Daily and weekly rent, phase 6 step 5b: Tenants › Short stays › Quotes (migration 20270607_317).
// The front desk makes a quote (SQ…) with today's price for a room and nights, and copies a
// message for the guest's Telegram. A quote is not a promise: the booking is priced when it is
// made. The list shows the last 100 quotes.

import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { DateInput } from "../shell/DateInput";
import { dayText, usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import type { Language } from "../signInText";
import { PriceLines } from "./NewBooking";
import { nightsText, unitTypeText } from "./ShortStaysPage";
import {
  addDays,
  type CalendarUnit,
  type ShortStaysApi,
  ShortStaysError,
  type StayQuote,
} from "./shortStaysClient";
import { copyText, timeText } from "./StaySteps";
import { st, type StaysTextKey } from "./text";

function quoteProblem(error: unknown): StaysTextKey {
  if (!(error instanceof ShortStaysError)) return "f_failed";
  if (error.status === 403) return "f_step_right";
  if (error.status === 409)
    return error.detail?.includes("no monthly Rent") === true
      ? "p_no_rent"
      : "q_not_free";
  if (error.status === 422 || error.status === 404) return "q_wrong";
  return "f_failed";
}

/** The message for the guest, in the screen's language. */
export function quoteMessage(language: Language, quote: StayQuote): string {
  const month =
    quote.month_only_usd_cents === null || quote.monthly_rent_usd_cents === null
      ? ""
      : `\n${st(
          language,
          "q_month",
          usdFromCents(quote.month_only_usd_cents),
          usdFromCents(quote.monthly_rent_usd_cents),
        )}`;
  return `${st(
    language,
    "q_message",
    quote.quote_number,
    `${quote.unit_number ?? ""} (${unitTypeText(language, quote.unit_type)})`,
    quote.guest_count,
    dayText(quote.check_in_on),
    dayText(quote.check_out_on),
    nightsText(language, quote.nights),
    usdFromCents(quote.total_usd_cents),
    timeText(quote.check_in_time),
    timeText(quote.check_out_time),
    usdFromCents(quote.deposit_usd_cents),
  )}${month}`;
}

export function Quotes({
  language,
  propertyId,
  api,
  may,
  today,
}: {
  language: Language;
  propertyId: string;
  api: ShortStaysApi;
  may: (capability: string) => boolean;
  today: string;
}) {
  const [quotes, setQuotes] = useState<StayQuote[] | null>(null);
  const [units, setUnits] = useState<CalendarUnit[]>([]);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<StaysTextKey | null>(null);
  const [made, setMade] = useState<StayQuote | null>(null);
  const [copied, setCopied] = useState(false);
  const [unitId, setUnitId] = useState("");
  const [checkIn, setCheckIn] = useState(today);
  const [nightsTyped, setNightsTyped] = useState("1");
  const [guests, setGuests] = useState("1");
  const [name, setName] = useState("");
  const [contact, setContact] = useState("");
  const [checked, setChecked] = useState(false);
  const sequence = useRef(0);

  const load = useCallback(() => {
    const operation = ++sequence.current;
    setFailed(false);
    void Promise.all([
      api.quotes(propertyId),
      api.calendar(propertyId, today, 1),
    ])
      .then(([found, calendar]) => {
        if (operation !== sequence.current) return;
        setQuotes(found);
        setUnits(calendar.units.filter((unit) => unit.for_rent));
      })
      .catch(() => {
        if (operation === sequence.current) setFailed(true);
      });
  }, [api, propertyId, today]);

  useEffect(() => {
    load();
  }, [load]);

  const nights = /^\d{1,2}$/.test(nightsTyped.trim())
    ? Number(nightsTyped.trim())
    : 0;
  const guestCount = /^\d{1,2}$/.test(guests.trim())
    ? Number(guests.trim())
    : 0;
  const wrong =
    unitId === "" ||
    !/^\d{4}-\d{2}-\d{2}$/.test(checkIn) ||
    nights < 1 ||
    guestCount < 1 ||
    guestCount > 10 ||
    name.trim() === "";

  const make = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setChecked(true);
    if (wrong || busy) return;
    const operation = ++sequence.current;
    setBusy(true);
    setProblem(null);
    setMade(null);
    setCopied(false);
    void api
      .quote(propertyId, {
        unit_id: unitId,
        guest_name: name.trim(),
        ...(contact.trim() === "" ? {} : { guest_contact: contact.trim() }),
        guest_count: guestCount,
        check_in_on: checkIn,
        check_out_on: addDays(checkIn, nights),
      })
      .then((quote) => {
        if (operation !== sequence.current) return;
        setMade(quote);
        setChecked(false);
        setName("");
        setContact("");
        load();
      })
      .catch((error: unknown) => {
        if (operation === sequence.current) setProblem(quoteProblem(error));
      })
      .finally(() => {
        setBusy(false);
      });
  };

  if (failed)
    return (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>{st(language, "failed")}</p>
        <button className="ui-btn" onClick={load} type="button">
          {st(language, "retry")}
        </button>
      </div>
    );
  if (quotes === null)
    return (
      <p className="ui-muted" role="status">
        {st(language, "loading")}
      </p>
    );
  const message = made === null ? "" : quoteMessage(language, made);
  return (
    <>
      <p className="ui-small ui-muted">{st(language, "q_s")}</p>
      {made !== null && (
        <section aria-labelledby="ss-quote-made" className="ui-card">
          <h2 id="ss-quote-made">
            {st(language, "q_made", made.quote_number)}
          </h2>
          <PriceLines language={language} lines={made.lines} />
          <p className="ss-total">
            <span>{st(language, "total")}</span>
            <b className="ui-num">{usdFromCents(made.total_usd_cents)}</b>
          </p>
          <textarea
            aria-labelledby="ss-quote-made"
            className="ss-message"
            readOnly
            rows={7}
            value={message}
          />
          {copied && (
            <p className="ui-small" role="status">
              {st(language, "rv_copied")}
            </p>
          )}
          <div className="ui-actions">
            <button
              className="ui-btn"
              onClick={() => {
                void copyText(message).then(setCopied);
              }}
              type="button"
            >
              {st(language, "rv_copy")}
            </button>
            {made.unit_id !== null && may("short_stays.desk") && (
              <a
                className="ui-btn primary"
                href={hashForPage(
                  "shortstays",
                  `new:${made.unit_id}:${made.check_in_on}`,
                )}
              >
                {st(language, "q_book")}
              </a>
            )}
          </div>
        </section>
      )}
      {may("short_stays.desk") && (
        <form className="ui-card ui-form ss-form" noValidate onSubmit={make}>
          <h2>{st(language, "q_new")}</h2>
          {problem !== null && (
            <div className="ui-notice warn" role="alert">
              <Icon name="alert" />
              <p>{st(language, problem)}</p>
            </div>
          )}
          <div className="ui-row2">
            <div className="ui-field">
              <label htmlFor="sq-unit">
                {st(language, "c_unit")}
                <span className="req">{st(language, "required")}</span>
              </label>
              <select
                aria-invalid={checked && unitId === ""}
                className="ui-sel"
                disabled={busy}
                id="sq-unit"
                onChange={(event) => {
                  setUnitId(event.currentTarget.value);
                }}
                value={unitId}
              >
                <option value="">{st(language, "pick")}</option>
                {units.map((unit) => (
                  // A quote is priced from the monthly Rent, so a Unit without one waits.
                  <option
                    disabled={unit.monthly_rent_usd_cents === null}
                    key={unit.unit_id}
                    value={unit.unit_id}
                  >
                    {unit.unit_number} ·{" "}
                    {unitTypeText(language, unit.unit_type)}
                    {unit.monthly_rent_usd_cents === null
                      ? ` · ${st(language, "u_no_rent")}`
                      : ""}
                  </option>
                ))}
              </select>
            </div>
            <div className="ui-field">
              <label htmlFor="sq-in">
                {st(language, "q_in")}
                <span className="req">{st(language, "required")}</span>
              </label>
              <DateInput
                calendarLabel={st(language, "tab_cal")}
                disabled={busy}
                id="sq-in"
                language={language}
                min={today}
                onChange={(value) => {
                  setCheckIn(value);
                }}
                value={checkIn}
              />
            </div>
          </div>
          <div className="ui-row2">
            <div className="ui-field">
              <label htmlFor="sq-nights">
                {st(language, "q_nights")}
                <span className="req">{st(language, "required")}</span>
              </label>
              <input
                aria-invalid={checked && nights < 1}
                disabled={busy}
                id="sq-nights"
                inputMode="numeric"
                onChange={(event) => {
                  setNightsTyped(event.currentTarget.value);
                }}
                value={nightsTyped}
              />
            </div>
            <div className="ui-field">
              <label htmlFor="sq-guests">
                {st(language, "q_guests")}
                <span className="req">{st(language, "required")}</span>
              </label>
              <input
                aria-invalid={checked && (guestCount < 1 || guestCount > 10)}
                disabled={busy}
                id="sq-guests"
                inputMode="numeric"
                onChange={(event) => {
                  setGuests(event.currentTarget.value);
                }}
                value={guests}
              />
            </div>
          </div>
          <div className="ui-row2">
            <div className="ui-field">
              <label htmlFor="sq-name">
                {st(language, "q_name")}
                <span className="req">{st(language, "required")}</span>
              </label>
              <input
                aria-invalid={checked && name.trim() === ""}
                autoComplete="off"
                disabled={busy}
                id="sq-name"
                maxLength={120}
                onChange={(event) => {
                  setName(event.currentTarget.value);
                }}
                value={name}
              />
            </div>
            <div className="ui-field">
              <label htmlFor="sq-contact">{st(language, "q_contact")}</label>
              <input
                autoComplete="off"
                disabled={busy}
                id="sq-contact"
                maxLength={120}
                onChange={(event) => {
                  setContact(event.currentTarget.value);
                }}
                value={contact}
              />
            </div>
          </div>
          {checked && wrong && (
            <p className="ui-error">
              <Icon name="alert" small />
              <span>{st(language, "q_wrong")}</span>
            </p>
          )}
          <div className="ui-actions">
            <button className="ui-btn primary" disabled={busy} type="submit">
              <Icon name="plus" small />
              {st(language, "q_b")}
            </button>
          </div>
        </form>
      )}
      {quotes.length === 0 ? (
        <p className="ui-empty">{st(language, "q_none")}</p>
      ) : (
        <div className="ui-card pad0 ui-tablewrap">
          <table className="ui-table">
            <caption className="ui-sr">{st(language, "tab_quotes")}</caption>
            <thead>
              <tr>
                <th scope="col">{st(language, "c_no")}</th>
                <th scope="col">{st(language, "c_guest")}</th>
                <th scope="col">{st(language, "c_unit")}</th>
                <th scope="col">{st(language, "c_dates")}</th>
                <th className="r" scope="col">
                  {st(language, "c_total")}
                </th>
              </tr>
            </thead>
            <tbody>
              {quotes.map((quote) => (
                <tr key={quote.quote_id}>
                  <td className="ui-num">{quote.quote_number}</td>
                  <td>
                    {quote.guest_name ?? ""}
                    {quote.guest_contact !== null && (
                      <span className="ui-sub2">{quote.guest_contact}</span>
                    )}
                  </td>
                  <td className="ui-num">{quote.unit_number ?? ""}</td>
                  <td className="ui-num">
                    {st(
                      language,
                      "d_dates",
                      dayText(quote.check_in_on),
                      dayText(quote.check_out_on),
                    )}
                  </td>
                  <td className="r ui-num">
                    {usdFromCents(quote.total_usd_cents)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
