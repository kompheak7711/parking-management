// Daily and weekly rent, phase 6 step 2: New booking (mock-up rounds 28, 31, 35). The front desk
// picks the check-in day, the nights and a Unit free on all of them; the guest is a Customer,
// found by name or phone or added here. The price box asks the server, which prices every stay
// from the owner's rules in Settings, and shows the monthly hint and why a Unit cannot be booked.

import { type FormEvent, useEffect, useRef, useState } from "react";

import {
  type CustomerApi,
  CustomerConflictError,
  CustomerIdNumberInUseError,
  type CustomerListItem,
  type CustomerSource,
  CustomerUnavailableError,
} from "../customerClient";
import { DateInput } from "../shell/DateInput";
import { dayText, usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { openPageInAddress } from "../shell/useHashPage";
import type { Language } from "../signInText";
import { freeForStay } from "./nights";
import { nightsText, unitTypeText } from "./ShortStaysPage";
import {
  addDays,
  type Booking,
  type BookingSource,
  type CalendarUnit,
  type GuestHistory,
  type NewBooking,
  type PriceLine,
  SOURCES,
  type ShortStaysApi,
  ShortStaysError,
  type StayPrice,
} from "./shortStaysClient";
import { hasText, st } from "./text";

export const SITES = ["Booking.com", "Agoda", "Airbnb"];

/** The price lines kept with a booking, or worked out for the price box. */
export function PriceLines({
  language,
  lines,
}: {
  language: Language;
  lines: readonly PriceLine[];
}) {
  return (
    <ul className="ui-plain ss-lines">
      {lines.map((line) => {
        const key = `l_${line.kind}`;
        const what = hasText(key)
          ? st(
              language,
              key,
              line.quantity,
              usdFromCents(line.unit_price_usd_cents),
            )
          : line.kind;
        return (
          <li key={line.position}>
            <span>
              {what}
              {line.discount_basis_points > 0 && (
                <span className="ui-muted">
                  {" "}
                  ({st(language, "off", line.discount_basis_points / 100)})
                </span>
              )}
            </span>
            <span className="ui-num">
              {usdFromCents(line.amount_usd_cents)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

export function bookingRefusal(language: Language, error: unknown): string {
  if (error instanceof ShortStaysError) {
    if (error.status === 403) return st(language, "f_right");
    if (error.status === 409) {
      const detail = error.detail ?? "";
      if (detail.includes("cannot be booked")) return st(language, "e_free");
      if (detail.includes("no monthly Rent")) return st(language, "p_no_rent");
      // Only a clash on the nights (with a booking or a Lease) is "just booked"; any other
      // refusal shows the server's own reason, so the desk knows what to fix.
      if (
        detail === "" ||
        /already booked|Lease on one of these nights/.test(detail)
      )
        return st(language, "f_taken");
      return st(language, "f_why", detail);
    }
    if (error.status === 422 || error.status === 404)
      return st(language, "f_refused");
  }
  return st(language, "f_failed");
}

function Missing({ id, text }: { id: string; text: string | null }) {
  if (text === null) return null;
  return (
    <p className="ui-error" id={id}>
      <Icon name="alert" small />
      <span>{text}</span>
    </p>
  );
}

interface Guest {
  customer_id: string;
  legal_name: string;
  phone: string | null;
}
type PriceProblem = "too_long" | "no_rent" | "failed";
type GuestProblem =
  | { kind: "same"; candidates: CustomerListItem[] }
  | { kind: "id_used"; candidates: CustomerListItem[] }
  | { kind: "no_right" }
  | { kind: "failed" };

function wholeNights(text: string): number | null {
  if (!/^\d{1,2}$/.test(text.trim())) return null;
  const nights = Number(text.trim());
  return nights >= 1 ? nights : null;
}

export function NewBookingForm({
  language,
  propertyId,
  api,
  customerApi,
  mayAddGuest,
  startUnit,
  startDay,
  today,
  onSaved,
}: {
  language: Language;
  propertyId: string;
  api: ShortStaysApi;
  customerApi: CustomerApi;
  /** The person holds customers.manage, so a new guest can be added here. */
  mayAddGuest: boolean;
  /** From a free square on the calendar: that Unit and night. */
  startUnit: string;
  startDay: string;
  today: string;
  onSaved: (made: Booking) => void;
}) {
  const [checkIn, setCheckIn] = useState(startDay);
  const [nightsTyped, setNightsTyped] = useState("1");
  const [unitId, setUnitId] = useState(startUnit);
  const [units, setUnits] = useState<CalendarUnit[] | null>(null);
  const [unitsFailed, setUnitsFailed] = useState(false);
  const [price, setPrice] = useState<StayPrice | null>(null);
  const [priceProblem, setPriceProblem] = useState<PriceProblem | null>(null);
  const [guestCount, setGuestCount] = useState("1");
  const [source, setSource] = useState<BookingSource>("WALK_IN");
  const [siteName, setSiteName] = useState("");
  const [siteReference, setSiteReference] = useState("");
  const [note, setNote] = useState("");
  // The guest: a Customer found here, or a new one added with the booking.
  const [guest, setGuest] = useState<Guest | null>(null);
  // Owner test 06/11/2026: one guest form; typing the name or the phone shows the Customers
  // who match, to pick instead of adding the guest again.
  const [found, setFound] = useState<CustomerListItem[] | null>(null);
  const [findFailed, setFindFailed] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [idNumber, setIdNumber] = useState("");
  const [guestProblem, setGuestProblem] = useState<GuestProblem | null>(null);
  // Step 5b: a picked guest's history, for the thank-you and the problem-guest mark.
  const [history, setHistory] = useState<GuestHistory | null>(null);
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  // One Customer id and command key per new-guest form, so a retry never adds the guest twice.
  const command = useRef<{ text: string; id: string; key: string } | null>(
    null,
  );

  const nights = wholeNights(nightsTyped);
  const dayOk = /^\d{4}-\d{2}-\d{2}$/.test(checkIn);
  const checkOut = dayOk && nights !== null ? addDays(checkIn, nights) : "";

  // Which Units are free on all the nights: the calendar for exactly these nights.
  useEffect(() => {
    if (!dayOk || nights === null) return;
    let current = true;
    setUnitsFailed(false);
    void api
      .calendar(propertyId, checkIn, Math.min(nights, 62))
      .then((calendar) => {
        if (current) setUnits(calendar.units);
      })
      .catch(() => {
        if (current) setUnitsFailed(true);
      });
    return () => {
      current = false;
    };
  }, [api, propertyId, checkIn, nights, dayOk]);

  const guestId = guest?.customer_id ?? "";
  useEffect(() => {
    setHistory(null);
    if (guestId === "") return;
    let current = true;
    void api
      .guest(propertyId, guestId)
      .then((found) => {
        if (current) setHistory(found);
      })
      .catch(() => {
        // The hints are a help only; the booking is priced by the server either way.
      });
    return () => {
      current = false;
    };
  }, [api, propertyId, guestId]);

  // The price box follows the Unit and the nights.
  useEffect(() => {
    setPrice(null);
    setPriceProblem(null);
    if (unitId === "" || checkOut === "") return;
    let current = true;
    void api
      .price(propertyId, unitId, checkIn, checkOut)
      .then((answer) => {
        if (current) setPrice(answer);
      })
      .catch((error: unknown) => {
        if (!current) return;
        setPriceProblem(
          error instanceof ShortStaysError && error.status === 422
            ? "too_long"
            : error instanceof ShortStaysError && error.status === 409
              ? "no_rent"
              : "failed",
        );
      });
    return () => {
      current = false;
    };
  }, [api, propertyId, unitId, checkIn, checkOut]);

  const adding = guest === null && mayAddGuest;
  // The words to look for: the phone when typed, else the name (2 letters at least).
  const lookFor =
    phone.trim().length >= 3
      ? phone.trim()
      : name.trim().length >= 2
        ? name.trim()
        : "";
  useEffect(() => {
    setFound(null);
    setFindFailed(false);
    if (guest !== null || lookFor === "") return;
    let current = true;
    const wait = window.setTimeout(() => {
      void customerApi
        .list(propertyId, { query: lookFor, active: true })
        .then((page) => {
          if (current) setFound(page.items.slice(0, 5));
        })
        .catch(() => {
          if (current) setFindFailed(true);
        });
    }, 300);
    return () => {
      current = false;
      window.clearTimeout(wait);
    };
  }, [customerApi, propertyId, guest, lookFor]);

  const count = Number(guestCount);
  // Step 5a: nights a booking site holds; a booking from that same site is that guest.
  const heldBy = (price?.site_holds ?? []).filter(
    (hold) =>
      source !== "BOOKING_SITE" ||
      hold.site_name.toLowerCase() !== siteName.toLowerCase(),
  );
  const problems: Record<string, string | null> = {
    in: dayOk ? null : st(language, "e_in"),
    nights: nights === null ? st(language, "e_nights") : null,
    unit: unitId === "" ? st(language, "e_unit") : null,
    guest: guest === null && !adding ? st(language, "e_guest") : null,
    name: adding && name.trim() === "" ? st(language, "e_name") : null,
    id: adding && idNumber.trim() === "" ? st(language, "e_id") : null,
    guests:
      Number.isInteger(count) && count >= 1 && count <= 10
        ? null
        : st(language, "e_guests"),
    site:
      source === "BOOKING_SITE" && siteName === ""
        ? st(language, "e_site")
        : null,
    free:
      price !== null && (price.blockers.length > 0 || heldBy.length > 0)
        ? st(language, "e_free")
        : null,
  };
  const FIELDS: Record<string, string> = {
    in: "sb-in",
    nights: "sb-nights",
    unit: "sb-unit",
    guest: "sb-name",
    name: "sb-name",
    id: "sb-id",
    guests: "sb-guests",
    site: "sb-site",
    free: "sb-unit",
  };
  const shown = (key: string) => (checked ? (problems[key] ?? null) : null);
  const wrong = Object.entries(problems).filter(([, text]) => text !== null);

  /** The new guest as a Customer, or the one picked; null when the desk must choose first. */
  const theGuest = async (
    confirmedDistinct: boolean,
  ): Promise<Guest | null> => {
    if (!adding) return guest;
    const body: CustomerSource = {
      legal_name: name.trim(),
      id_document_number: idNumber.trim(),
      ...(phone.trim() === "" ? {} : { phone_number: phone.trim() }),
      ...(confirmedDistinct ? { confirmed_distinct: true } : {}),
    };
    const text = JSON.stringify(body);
    if (command.current?.text !== text)
      command.current = {
        text,
        id: crypto.randomUUID(),
        key: crypto.randomUUID(),
      };
    try {
      const made = await customerApi.create(
        propertyId,
        command.current.id,
        body,
        command.current.key,
      );
      const added = {
        customer_id: made.customer_id,
        legal_name: made.legal_name,
        phone: made.phone_number,
      };
      // Added once: a later try books this Customer and never adds the guest again.
      setGuest(added);
      return added;
    } catch (error: unknown) {
      if (error instanceof CustomerIdNumberInUseError)
        setGuestProblem({ kind: "id_used", candidates: error.candidates });
      else if (error instanceof CustomerConflictError)
        setGuestProblem({ kind: "same", candidates: error.candidates });
      else if (error instanceof CustomerUnavailableError)
        setGuestProblem({ kind: "no_right" });
      else setGuestProblem({ kind: "failed" });
      return null;
    }
  };

  const save = (confirmedDistinct = false) => {
    setChecked(true);
    setFailure(null);
    setGuestProblem(null);
    const first = wrong[0];
    if (first !== undefined) {
      document.getElementById(FIELDS[first[0]] ?? "sb-in")?.focus();
      return;
    }
    setBusy(true);
    void (async () => {
      const who = await theGuest(confirmedDistinct);
      if (who === null) {
        setBusy(false);
        return;
      }
      const body: NewBooking = {
        unit_id: unitId,
        customer_id: who.customer_id,
        guest_count: count,
        check_in_on: checkIn,
        check_out_on: checkOut,
        source,
      };
      if (source === "BOOKING_SITE") {
        body.site_name = siteName;
        if (siteReference.trim() !== "")
          body.site_reference = siteReference.trim();
      }
      if (note.trim() !== "") body.note = note.trim();
      try {
        onSaved(await api.book(propertyId, body));
      } catch (error: unknown) {
        setBusy(false);
        setFailure(bookingRefusal(language, error));
      }
    })();
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    save();
  };

  const back = (
    <button
      className="ui-crumb"
      onClick={() => {
        openPageInAddress("shortstays");
      }}
      type="button"
    >
      <Icon name="back" small />
      {st(language, "back")}
    </button>
  );

  const pickGuest = (item: CustomerListItem) => {
    setGuest({
      customer_id: item.customer_id,
      legal_name: item.legal_name,
      phone: item.phone_number ?? null,
    });
    setGuestProblem(null);
  };

  const priceBox = (
    <section aria-labelledby="sb-price" aria-live="polite" className="ui-card">
      <h2 id="sb-price">{st(language, "p_title")}</h2>
      {priceProblem !== null ? (
        <p className="ui-muted">
          {st(
            language,
            priceProblem === "too_long"
              ? "p_too_long"
              : priceProblem === "no_rent"
                ? "p_no_rent"
                : "failed",
          )}
        </p>
      ) : price === null ? (
        <p className="ui-muted">
          {unitId === "" || checkOut === ""
            ? st(language, "p_pick")
            : st(language, "loading")}
        </p>
      ) : (
        <>
          <p className="ui-sub2">
            {price.unit_number} · {unitTypeText(language, price.unit_type)} ·{" "}
            {nightsText(language, price.nights)} ·{" "}
            <span className="ui-num">
              {st(
                language,
                "d_dates",
                dayText(price.check_in_on),
                dayText(price.check_out_on),
              )}
            </span>
          </p>
          <PriceLines language={language} lines={price.lines} />
          <p className="ss-total">
            <span>{st(language, "total")}</span>
            <b className="ui-num">{usdFromCents(price.total_usd_cents)}</b>
          </p>
          {price.charged_as_whole_weeks && (
            <p className="ui-small ui-muted">{st(language, "as_weeks")}</p>
          )}
          {price.suggest_month && price.month_only_usd_cents !== null && (
            <div className="ui-notice info" role="note">
              <Icon name="info" />
              <p>
                {st(language, "hint", usdFromCents(price.month_only_usd_cents))}
              </p>
            </div>
          )}
          {history !== null &&
            history.returning &&
            source !== "BOOKING_SITE" &&
            history.thank_you_usd_cents > 0 && (
              <div className="ui-notice ok" role="note">
                <Icon name="check" />
                <p>
                  {st(
                    language,
                    "nb_returning",
                    usdFromCents(history.thank_you_usd_cents),
                  )}
                </p>
              </div>
            )}
          {history?.problem_guest === true && (
            <div className="ui-notice warn" role="note">
              <Icon name="alert" />
              <p>
                {st(
                  language,
                  "nb_problem",
                  history.notes.find((entry) => entry.problem_guest)?.note ??
                    "",
                )}
              </p>
            </div>
          )}
          {heldBy.length > 0 && (
            <div className="ui-notice err" role="note">
              <Icon name="alert" />
              <ul className="ui-plain">
                {heldBy.map((hold) => (
                  <li key={hold.hold_id}>
                    {st(
                      language,
                      "b_SITE_HOLD",
                      hold.site_name,
                      dayText(hold.start_on),
                      dayText(hold.end_on),
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {price.blockers.length > 0 && (
            <div className="ui-notice err" role="note">
              <Icon name="alert" />
              <ul className="ui-plain">
                {price.blockers.map((blocker) => {
                  const key = `b_${blocker}`;
                  return (
                    <li key={blocker}>
                      {hasText(key) ? st(language, key) : blocker}
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </>
      )}
    </section>
  );

  return (
    <>
      {back}
      <div className="ui-head">
        <div>
          <h2>{st(language, "add")}</h2>
          <p>{st(language, "new_sub")}</p>
        </div>
      </div>
      {checked && wrong.length > 0 && (
        <div className="ui-notice err" role="alert">
          <Icon name="alert" />
          <div>
            <p>
              {wrong.length === 1
                ? st(language, "e_sum1")
                : st(language, "e_sum", wrong.length)}
            </p>
            <ul>
              {wrong.map(([key, text]) => (
                <li key={key}>{text}</li>
              ))}
            </ul>
          </div>
        </div>
      )}
      <div className="ui-split">
        <form className="ui-card ui-form ss-form" noValidate onSubmit={submit}>
          <div className="ui-row2">
            <div className="ui-field">
              <label htmlFor="sb-in">
                {st(language, "f_in")}
                <span className="req">{st(language, "required")}</span>
              </label>
              <DateInput
                calendarLabel={st(language, "tab_cal")}
                describedBy={shown("in") === null ? undefined : "sb-in-err"}
                disabled={busy}
                id="sb-in"
                invalid={shown("in") !== null}
                language={language}
                min={today}
                onChange={(value) => {
                  setCheckIn(value);
                }}
                value={checkIn}
              />
              <Missing id="sb-in-err" text={shown("in")} />
            </div>
            <div className="ui-field">
              <label htmlFor="sb-nights">
                {st(language, "f_nights")}
                <span className="req">{st(language, "required")}</span>
              </label>
              <input
                aria-describedby={
                  shown("nights") === null ? undefined : "sb-nights-err"
                }
                aria-invalid={shown("nights") !== null}
                autoComplete="off"
                disabled={busy}
                id="sb-nights"
                inputMode="numeric"
                maxLength={2}
                onChange={(event) => {
                  setNightsTyped(event.currentTarget.value);
                }}
                value={nightsTyped}
              />
              {checkOut !== "" && (
                <p className="ui-small ui-muted">
                  {st(language, "f_out")}:{" "}
                  <span className="ui-num">{dayText(checkOut)}</span>
                </p>
              )}
              <Missing id="sb-nights-err" text={shown("nights")} />
            </div>
          </div>
          <div className="ui-field">
            <label htmlFor="sb-unit">
              {st(language, "f_unit")}
              <span className="req">{st(language, "required")}</span>
            </label>
            <select
              aria-describedby={
                shown("unit") === null && shown("free") === null
                  ? "sb-unit-note"
                  : "sb-unit-err"
              }
              aria-invalid={shown("unit") !== null || shown("free") !== null}
              className="ui-sel"
              disabled={busy}
              id="sb-unit"
              onChange={(event) => {
                setUnitId(event.currentTarget.value);
              }}
              value={unitId}
            >
              <option value="">{st(language, "pick")}</option>
              {(units ?? []).map((unit) => {
                const free =
                  checkOut === "" ||
                  freeForStay(
                    unit,
                    checkIn,
                    checkOut,
                    source === "BOOKING_SITE" ? siteName : null,
                  );
                // A short stay is priced from the monthly Rent, so a Unit without one waits.
                const priced = unit.monthly_rent_usd_cents !== null;
                return (
                  <option
                    disabled={(!free || !priced) && unit.unit_id !== unitId}
                    key={unit.unit_id}
                    value={unit.unit_id}
                  >
                    {unit.unit_number} ·{" "}
                    {unitTypeText(language, unit.unit_type)}
                    {!priced
                      ? ` · ${st(language, "u_no_rent")}`
                      : free
                        ? ""
                        : ` · ${st(language, "u_busy")}`}
                  </option>
                );
              })}
            </select>
            <p className="ui-small ui-muted" id="sb-unit-note">
              {unitsFailed
                ? st(language, "failed")
                : st(language, "f_free_only")}
            </p>
            <Missing id="sb-unit-err" text={shown("unit") ?? shown("free")} />
          </div>
          <fieldset className="ui-radios">
            <legend>
              {st(language, "f_guest")}
              <span className="req">{st(language, "required")}</span>
            </legend>
            {guest !== null ? (
              <p>
                <b>{guest.legal_name}</b>
                {guest.phone !== null && (
                  <span className="ui-num"> · {guest.phone}</span>
                )}{" "}
                <button
                  className="ui-btn link"
                  disabled={busy}
                  onClick={() => {
                    setGuest(null);
                  }}
                  type="button"
                >
                  {st(language, "g_change")}
                </button>
              </p>
            ) : (
              <>
                <div className="ui-field">
                  <label htmlFor="sb-name">
                    {st(language, "f_name")}
                    {mayAddGuest && (
                      <span className="req">{st(language, "required")}</span>
                    )}
                  </label>
                  <input
                    aria-describedby="sb-name-err"
                    aria-invalid={
                      shown("name") !== null || shown("guest") !== null
                    }
                    autoComplete="off"
                    disabled={busy}
                    id="sb-name"
                    maxLength={255}
                    onChange={(event) => {
                      setName(event.currentTarget.value);
                    }}
                    value={name}
                  />
                  <Missing
                    id="sb-name-err"
                    text={shown("name") ?? shown("guest")}
                  />
                </div>
                <div className="ui-row2">
                  {mayAddGuest && (
                    <div className="ui-field">
                      <label htmlFor="sb-id">
                        {st(language, "f_id")}
                        <span className="req">{st(language, "required")}</span>
                      </label>
                      <input
                        aria-invalid={shown("id") !== null}
                        autoComplete="off"
                        disabled={busy}
                        id="sb-id"
                        maxLength={64}
                        onChange={(event) => {
                          setIdNumber(event.currentTarget.value);
                        }}
                        value={idNumber}
                      />
                      <Missing id="sb-id-err" text={shown("id")} />
                    </div>
                  )}
                  <div className="ui-field">
                    <label htmlFor="sb-phone">{st(language, "f_phone")}</label>
                    <input
                      autoComplete="off"
                      disabled={busy}
                      id="sb-phone"
                      inputMode="tel"
                      maxLength={100}
                      onChange={(event) => {
                        setPhone(event.currentTarget.value);
                      }}
                      value={phone}
                    />
                  </div>
                </div>
                {findFailed && (
                  <p className="ui-error">
                    <Icon name="alert" small />
                    <span>{st(language, "failed")}</span>
                  </p>
                )}
                {found !== null && found.length > 0 && (
                  <div aria-live="polite">
                    <p className="ui-small ui-muted">
                      {st(language, "g_matches")}
                    </p>
                    <ul className="ui-plain ss-found">
                      {found.map((item) => (
                        <li key={item.customer_id}>
                          <span>
                            <b>{item.legal_name}</b>
                            {item.phone_number != null && (
                              <span className="ui-num">
                                {" "}
                                · {item.phone_number}
                              </span>
                            )}
                          </span>
                          <button
                            className="ui-btn"
                            disabled={busy}
                            onClick={() => {
                              pickGuest(item);
                            }}
                            type="button"
                          >
                            {st(language, "g_choose")}
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {!mayAddGuest && (
                  <p className="ui-small ui-muted">
                    {st(language, "g_no_right")}
                  </p>
                )}
              </>
            )}
            {guestProblem !== null && (
              <div className="ui-notice err" role="alert">
                <Icon name="alert" />
                <div>
                  <p>
                    {st(
                      language,
                      guestProblem.kind === "same"
                        ? "g_same"
                        : guestProblem.kind === "id_used"
                          ? "g_id_used"
                          : guestProblem.kind === "no_right"
                            ? "g_no_right"
                            : "g_failed",
                    )}
                  </p>
                  {(guestProblem.kind === "same" ||
                    guestProblem.kind === "id_used") && (
                    <ul className="ui-plain ss-found">
                      {guestProblem.candidates.map((item) => (
                        <li key={item.customer_id}>
                          <b>{item.legal_name}</b>
                          <button
                            className="ui-btn"
                            disabled={busy}
                            onClick={() => {
                              pickGuest(item);
                            }}
                            type="button"
                          >
                            {st(language, "g_use")}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                  {guestProblem.kind === "same" && (
                    <button
                      className="ui-btn"
                      disabled={busy}
                      onClick={() => {
                        save(true);
                      }}
                      type="button"
                    >
                      {st(language, "g_other")}
                    </button>
                  )}
                </div>
              </div>
            )}
          </fieldset>
          <div className="ui-row2">
            <div className="ui-field">
              <label htmlFor="sb-guests">
                {st(language, "f_guests")}
                <span className="req">{st(language, "required")}</span>
              </label>
              <input
                aria-invalid={shown("guests") !== null}
                autoComplete="off"
                disabled={busy}
                id="sb-guests"
                inputMode="numeric"
                maxLength={2}
                onChange={(event) => {
                  setGuestCount(event.currentTarget.value);
                }}
                value={guestCount}
              />
              <Missing id="sb-guests-err" text={shown("guests")} />
            </div>
            <div className="ui-field">
              <label htmlFor="sb-source">{st(language, "f_source")}</label>
              <select
                className="ui-sel"
                disabled={busy}
                id="sb-source"
                onChange={(event) => {
                  const value = SOURCES.find(
                    (entry) => entry === event.currentTarget.value,
                  );
                  if (value !== undefined) setSource(value);
                }}
                value={source}
              >
                {SOURCES.map((value) => (
                  <option key={value} value={value}>
                    {st(language, `src_${value}`)}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {source === "BOOKING_SITE" && (
            <div className="ui-row2">
              <div className="ui-field">
                <label htmlFor="sb-site">
                  {st(language, "f_site")}
                  <span className="req">{st(language, "required")}</span>
                </label>
                <select
                  aria-invalid={shown("site") !== null}
                  className="ui-sel"
                  disabled={busy}
                  id="sb-site"
                  onChange={(event) => {
                    setSiteName(event.currentTarget.value);
                  }}
                  value={siteName}
                >
                  <option value="">{st(language, "pick")}</option>
                  {SITES.map((site) => (
                    <option key={site} value={site}>
                      {site}
                    </option>
                  ))}
                </select>
                <Missing id="sb-site-err" text={shown("site")} />
              </div>
              <div className="ui-field">
                <label htmlFor="sb-ref">{st(language, "f_ref")}</label>
                <input
                  autoComplete="off"
                  disabled={busy}
                  id="sb-ref"
                  maxLength={80}
                  onChange={(event) => {
                    setSiteReference(event.currentTarget.value);
                  }}
                  value={siteReference}
                />
              </div>
            </div>
          )}
          <div className="ui-field">
            <label htmlFor="sb-note">{st(language, "f_note")}</label>
            <textarea
              disabled={busy}
              id="sb-note"
              maxLength={500}
              onChange={(event) => {
                setNote(event.currentTarget.value);
              }}
              rows={2}
              value={note}
            />
          </div>
          {failure !== null && (
            <div className="ui-notice err" role="alert">
              <Icon name="alert" />
              <p>{failure}</p>
            </div>
          )}
          <div className="ui-actions">
            <button
              className="ui-btn"
              disabled={busy}
              onClick={() => {
                openPageInAddress("shortstays");
              }}
              type="button"
            >
              {st(language, "cancel")}
            </button>
            <button className="ui-btn primary" disabled={busy} type="submit">
              {st(language, busy ? "saving" : "save")}
            </button>
          </div>
        </form>
        <div className="ui-stack">{priceBox}</div>
      </div>
    </>
  );
}
