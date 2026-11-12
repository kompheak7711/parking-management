// DL-224 (owner's rules of 12 Nov 2026, migration 20270720_375): Change Unit for a short-stay
// booking that is not checked in yet. The front desk moves the guest to a Unit that is free on
// every night of the stay (the same type first) and says why; the guest keeps the agreed price.
// After a move an Owner or Manager may give a special discount, once for each move; when the stay
// is already paid the amount becomes the guest's Credit. The server checks every step again.

import { type FormEvent, useEffect, useState } from "react";

import { usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import type { Language } from "../signInText";
import { unitTypeText } from "./ShortStaysPage";
import {
  type Booking,
  type BookingHistoryEntry,
  type MoveUnit,
  type ShortStaysApi,
  type StayStep,
} from "./shortStaysClient";
import { centsOf } from "./StaySteps";
import { st } from "./text";

type OnStep = (step: StayStep, body: Record<string, unknown> | null) => void;

function word(event: BookingHistoryEntry, key: string): string {
  const value = event.details?.[key];
  return typeof value === "string" ? value : "";
}

function cents(event: BookingHistoryEntry, key: string): number {
  const value = event.details?.[key];
  return typeof value === "number" && Number.isInteger(value) ? value : 0;
}

/** The moves of a stay to another Unit, the oldest first, as its History keeps them. */
export function movesOf(booking: Booking): BookingHistoryEntry[] {
  return booking.history.filter((event) => event.kind === "UNIT_CHANGED");
}

/** "U301 to U505" for a move in the History; null for any other step. */
export function moveText(
  language: Language,
  event: BookingHistoryEntry,
): string | null {
  const from = word(event, "from_unit_number");
  const to = word(event, "to_unit_number");
  return event.kind !== "UNIT_CHANGED" || from === "" || to === ""
    ? null
    : st(language, "cu_hist", from, to);
}

export function ChangeUnitCard({
  language,
  propertyId,
  booking,
  api,
  may,
  busy,
  onStep,
}: {
  language: Language;
  propertyId: string;
  booking: Booking;
  api: ShortStaysApi;
  may: (capability: string) => boolean;
  busy: boolean;
  onStep: OnStep;
}) {
  const [open, setOpen] = useState(false);
  const [units, setUnits] = useState<MoveUnit[] | "failed" | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [unitId, setUnitId] = useState("");
  const [reason, setReason] = useState("");
  const [checked, setChecked] = useState(false);
  const bookingId = booking.booking_id;

  // The free Units are read when the form opens, and again after a step that was refused: a
  // Unit may have been taken in the meantime.
  useEffect(() => {
    if (!open || busy) return;
    let live = true;
    api
      .moveUnits(propertyId, bookingId)
      .then((found) => {
        if (!live) return;
        setUnits(found);
        setUnitId((current) =>
          found.some((unit) => unit.unit_id === current) ? current : "",
        );
      })
      .catch(() => {
        if (live) setUnits("failed");
      });
    return () => {
      live = false;
    };
  }, [api, propertyId, bookingId, open, busy, attempt]);

  const last = movesOf(booking).at(-1);
  const desk = may("short_stays.desk");
  const mayMove = booking.status === "BOOKED" && desk;
  if (!mayMove && last === undefined) return null;

  const found = Array.isArray(units) ? units : [];
  const same = found.filter((unit) => unit.same_type);
  const other = found.filter((unit) => !unit.same_type);
  const chosen = found.find((unit) => unit.unit_id === unitId);
  const wrongReason = reason.trim() === "";
  const moved = last === undefined ? null : moveText(language, last);
  const live = booking.status === "BOOKED" || booking.status === "CHECKED_IN";

  const move = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setChecked(true);
    if (chosen === undefined || wrongReason) return;
    onStep("unit", {
      version: booking.version,
      unit_id: chosen.unit_id,
      reason: reason.trim(),
    });
  };
  const option = (unit: MoveUnit) => (
    <option key={unit.unit_id} value={unit.unit_id}>
      {unit.unit_number} · {unitTypeText(language, unit.unit_type)}
    </option>
  );

  return (
    <section aria-labelledby="ss-cu" className="ui-card">
      <h2 id="ss-cu">{st(language, "cu_t")}</h2>
      {last !== undefined && moved !== null && (
        <p>
          {st(
            language,
            "cu_moved",
            word(last, "from_unit_number"),
            word(last, "to_unit_number"),
          )}
        </p>
      )}
      {last !== undefined && live && desk && (
        <p className="ui-small ui-muted">{st(language, "cu_no_extend")}</p>
      )}
      {mayMove && !open && (
        <>
          <p className="ui-small ui-muted">
            {st(language, "cu_s", usdFromCents(booking.total_usd_cents))}
          </p>
          <div className="ui-actions">
            <button
              className="ui-btn"
              disabled={busy}
              onClick={() => {
                setOpen(true);
              }}
              type="button"
            >
              {st(language, "cu_t")}
            </button>
          </div>
        </>
      )}
      {mayMove && open && units === null && (
        <p className="ui-muted" role="status">
          {st(language, "cu_loading")}
        </p>
      )}
      {mayMove && open && units === "failed" && (
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{st(language, "cu_failed")}</p>
          <button
            className="ui-btn"
            onClick={() => {
              setUnits(null);
              setAttempt((count) => count + 1);
            }}
            type="button"
          >
            {st(language, "retry")}
          </button>
        </div>
      )}
      {mayMove && open && Array.isArray(units) && units.length === 0 && (
        <p className="ui-small" role="status">
          {st(language, "cu_none")}
        </p>
      )}
      {mayMove && open && Array.isArray(units) && units.length > 0 && (
        <form className="ui-form ss-form" noValidate onSubmit={move}>
          <div className="ui-field">
            <label htmlFor="ss-cu-unit">
              {st(language, "cu_to")}
              <span className="req">{st(language, "required")}</span>
            </label>
            <select
              aria-invalid={checked && chosen === undefined}
              className="ui-sel"
              disabled={busy}
              id="ss-cu-unit"
              onChange={(event) => {
                setUnitId(event.currentTarget.value);
              }}
              value={unitId}
            >
              <option value="">{st(language, "pick")}</option>
              {same.length > 0 && (
                <optgroup label={st(language, "cu_same")}>
                  {same.map(option)}
                </optgroup>
              )}
              {other.length > 0 && (
                <optgroup label={st(language, "cu_other")}>
                  {other.map(option)}
                </optgroup>
              )}
            </select>
            {chosen !== undefined && !chosen.same_type && (
              <p className="ui-small ui-muted">
                {st(language, "cu_other_note")}
              </p>
            )}
          </div>
          <div className="ui-field">
            <label htmlFor="ss-cu-reason">
              {st(language, "dc_reason")}
              <span className="req">{st(language, "required")}</span>
            </label>
            <input
              aria-invalid={checked && wrongReason}
              autoComplete="off"
              disabled={busy}
              id="ss-cu-reason"
              maxLength={500}
              onChange={(event) => {
                setReason(event.currentTarget.value);
              }}
              value={reason}
            />
          </div>
          {checked && (chosen === undefined || wrongReason) && (
            <p className="ui-error">
              <Icon name="alert" small />
              <span>{st(language, "cu_wrong")}</span>
            </p>
          )}
          <div className="ui-actions">
            <button className="ui-btn primary" disabled={busy} type="submit">
              {st(language, "cu_b")}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

/** The special discount after a move: Owner or Manager, with a reason, once for each move. */
export function MoveDiscountCard({
  language,
  booking,
  may,
  busy,
  onStep,
}: {
  language: Language;
  booking: Booking;
  may: (capability: string) => boolean;
  busy: boolean;
  onStep: OnStep;
}) {
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [checked, setChecked] = useState(false);
  const given = booking.history.filter(
    (event) => event.kind === "MOVE_DISCOUNT",
  );
  // A stay paid on the booking site has no Invoice here to take a discount off.
  const open =
    booking.status === "BOOKED" &&
    movesOf(booking).length > given.length &&
    booking.payment !== "PAID_ON_SITE" &&
    may("short_stays.approve");
  if (!open && given.length === 0) return null;

  const off = centsOf(amount);
  const wrongAmount = off === null || off >= booking.total_usd_cents;
  const wrongReason = reason.trim() === "";
  const give = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setChecked(true);
    if (wrongAmount || wrongReason) return;
    onStep("move-discount", {
      version: booking.version,
      amount_usd_cents: off,
      reason: reason.trim(),
    });
  };

  return (
    <section aria-labelledby="ss-md" className="ui-card">
      <h2 id="ss-md">{st(language, "md_t")}</h2>
      {given.map((event) => {
        const credit = cents(event, "credit_usd_cents");
        return (
          <div key={event.occurred_at}>
            <p>
              {st(
                language,
                "dc_given",
                usdFromCents(cents(event, "amount_usd_cents")),
                event.note ?? "",
              )}
            </p>
            {credit > 0 && (
              <p className="ui-small">
                {st(language, "md_credit", usdFromCents(credit))}
              </p>
            )}
          </div>
        );
      })}
      {open && (
        <form className="ui-form ss-form" noValidate onSubmit={give}>
          <p className="ui-small ui-muted">{st(language, "md_s")}</p>
          <div className="ui-row2">
            <div className="ui-field">
              <label htmlFor="ss-md-amount">{st(language, "dc_amount")}</label>
              <input
                aria-invalid={checked && wrongAmount}
                disabled={busy}
                id="ss-md-amount"
                inputMode="decimal"
                onChange={(event) => {
                  setAmount(event.currentTarget.value);
                }}
                value={amount}
              />
            </div>
            <div className="ui-field">
              <label htmlFor="ss-md-reason">{st(language, "dc_reason")}</label>
              <input
                aria-invalid={checked && wrongReason}
                disabled={busy}
                id="ss-md-reason"
                maxLength={460}
                onChange={(event) => {
                  setReason(event.currentTarget.value);
                }}
                value={reason}
              />
            </div>
          </div>
          {checked && (wrongAmount || wrongReason) && (
            <p className="ui-error">
              <Icon name="alert" small />
              <span>{st(language, "dc_wrong")}</span>
            </p>
          )}
          <div className="ui-actions">
            <button className="ui-btn" disabled={busy} type="submit">
              {st(language, "md_b")}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
