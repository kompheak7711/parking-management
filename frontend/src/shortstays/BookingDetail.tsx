// Daily and weekly rent, phase 6 steps 2 and 3: one booking (Tenants › Short stays › ST…). It shows
// the stay, the guest, the price lines kept at booking time and the history, and (step 3) the steps
// of the stay: payment, deposit, check-in, check-out, room check and damage. DL-222: the room
// check reports problems of the types the Problem reports page offers.

import { useCallback, useEffect, useRef, useState } from "react";
import { BackLink } from "../shell/backNav";

import type { ProblemType } from "../problems/problemsClient";

import { dayText, momentText, usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import type { Language } from "../signInText";
import { TelegramQrCard } from "../telegram/TelegramQrCard";
import { GuestPanel } from "./GuestPanel";
import { RefundCard } from "./RefundCard";
import {
  ChangeUnitCard,
  MoveDiscountCard,
  movesOf,
  moveText,
} from "./ChangeUnit";
import { PriceLines } from "./NewBooking";
import { BookingChip, nightsText, unitTypeText } from "./ShortStaysPage";
import {
  type Booking,
  type ShortStaysApi,
  ShortStaysError,
  type StayStep,
} from "./shortStaysClient";
import {
  CancelCard,
  CancelledCard,
  CheckInCard,
  CheckOutCard,
  DamagesCard,
  DepositCard,
  DiscountCard,
  ExtendCard,
  FeesCard,
  LeaseCard,
  PaymentCard,
  ReviewCard,
  RoomCheckCard,
  type StepsProps,
  timeText,
} from "./StaySteps";
import { hasText, st, type StaysTextKey } from "./text";
import { PageHead } from "../shell/pageHead";

/** The words for a refused step; 412 and 409 also show the booking as it is now. */
export function stepProblem(error: unknown): StaysTextKey {
  if (!(error instanceof ShortStaysError)) return "f_failed";
  switch (error.status) {
    case 412:
      return "f_stale";
    case 409:
      return "f_not_now";
    case 403:
      return "f_step_right";
    case 422:
      return "f_step_refused";
    default:
      return "f_failed";
  }
}

export function BookingDetail({
  language,
  propertyId,
  bookingId,
  api,
  may,
  today,
  flash,
  onFlashShown,
}: {
  language: Language;
  propertyId: string;
  bookingId: string;
  api: ShortStaysApi;
  may: (capability: string) => boolean;
  /** Today in Phnom Penh, for the check-in day. */
  today: string;
  /** "Booking ST… made." after New booking, shown once. */
  flash: string | null;
  onFlashShown: () => void;
}) {
  const [booking, setBooking] = useState<Booking | null>(null);
  const [problem, setProblem] = useState<"missing" | "failed" | null>(null);
  const [notice, setNotice] = useState<string | null>(flash);
  const [busy, setBusy] = useState(false);
  const [stepError, setStepError] = useState<StaysTextKey | null>(null);
  const [problemTypes, setProblemTypes] = useState<ProblemType[]>([]);
  const sequence = useRef(0);

  // DL-222: the problem types, read once a room check waits and the person may report a problem.
  const roomCheckDue =
    booking?.room_check?.status === "TO_DO" &&
    may("short_stays.housekeeping") &&
    may("problem_reports.add") &&
    may("problem_reports.read");
  useEffect(() => {
    if (!roomCheckDue) return;
    let live = true;
    void api
      .problemTypes(propertyId)
      .then((found) => {
        if (live) setProblemTypes(found);
      })
      .catch(() => {
        // The room check still works; it then reports no problem.
        if (live) setProblemTypes([]);
      });
    return () => {
      live = false;
    };
  }, [api, propertyId, roomCheckDue]);

  useEffect(() => {
    if (flash !== null) onFlashShown();
  }, [flash, onFlashShown]);

  const load = useCallback(() => {
    const operation = ++sequence.current;
    setProblem(null);
    void api
      .get(propertyId, bookingId)
      .then((found) => {
        if (operation === sequence.current) setBooking(found);
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        setProblem(
          error instanceof ShortStaysError && error.status === 404
            ? "missing"
            : "failed",
        );
      });
  }, [api, propertyId, bookingId]);

  useEffect(() => {
    load();
  }, [load]);

  const run = (work: () => Promise<Booking>) => {
    if (busy) return;
    const operation = ++sequence.current;
    setBusy(true);
    setStepError(null);
    setNotice(null);
    void work()
      .then((answer) => {
        if (operation === sequence.current) setBooking(answer);
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        const key = stepProblem(error);
        setStepError(key);
        if (key === "f_stale" || key === "f_not_now") load();
      })
      .finally(() => {
        setBusy(false);
      });
  };

  // The new total for a later check-out: the stay priced again, with its fees kept.
  const unitId = booking?.unit_id ?? "";
  const checkIn = booking?.check_in_on ?? "";
  const kept = (booking?.lines ?? [])
    .filter((line) => line.kind !== "NIGHTS" && line.kind !== "WEEKS")
    .reduce((sum, line) => sum + line.amount_usd_cents, 0);
  const priceFor = useCallback(
    (checkOut: string) =>
      api
        .price(propertyId, unitId, checkIn, checkOut)
        .then((found) => found.total_usd_cents + kept)
        .catch(() => null),
    [api, propertyId, unitId, checkIn, kept],
  );

  const back = <BackLink language={language} parent="shortstays" />;

  if (booking === null)
    return (
      <>
        {back}
        {problem === null ? (
          <p className="ui-muted" role="status">
            {st(language, "loading")}
          </p>
        ) : (
          <div className="ui-notice warn" role="status">
            <Icon name="alert" />
            <p>
              {st(language, problem === "missing" ? "not_found" : "failed")}
            </p>
            {problem === "failed" && (
              <button className="ui-btn" onClick={load} type="button">
                {st(language, "retry")}
              </button>
            )}
          </div>
        )}
      </>
    );

  const steps: StepsProps = {
    language,
    booking,
    today,
    may,
    busy,
    onStep: (step: StayStep, body) => {
      run(() => api.step(propertyId, booking.booking_id, step, body));
    },
    onDecide: (damageId, approve, note) => {
      run(() =>
        api.decide(propertyId, damageId, {
          approve,
          ...(note === "" ? {} : { note }),
        }),
      );
    },
    onPrice: priceFor,
    problemTypes,
  };
  // The cards keep what was typed until the booking changes.
  const cards = `${booking.booking_id}:${String(booking.version)}`;

  // DL-214: a guest on a live stay can get a one-time Telegram QR at check-in.
  const stayLive =
    booking.check_out_on >= today &&
    (booking.status === "CHECKED_IN" ||
      (booking.status === "BOOKED" && booking.check_in_on <= today));

  const source =
    booking.source === "BOOKING_SITE" && booking.site_name !== null
      ? booking.site_name
      : st(language, `src_${booking.source}`);

  return (
    <>
      {back}
      <PageHead>
        <div>
          <div className="ui-hrow">
            <h2 className="ui-num" data-record-title="">
              {booking.booking_number}
            </h2>
            <BookingChip language={language} status={booking.status} />
          </div>
          <p>
            {booking.guest_name} · {booking.unit_number} ·{" "}
            {nightsText(language, booking.nights)}
          </p>
        </div>
      </PageHead>
      {booking.problem_guest && (
        <div className="ui-notice warn" role="note">
          <Icon name="alert" />
          <p>{st(language, "gh_problem")}</p>
        </div>
      )}
      {notice !== null && (
        <div className="ui-notice ok" role="status">
          <Icon name="check" />
          <p>{notice}</p>
        </div>
      )}
      {stepError !== null && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>{st(language, stepError)}</p>
        </div>
      )}
      <div className="ui-split">
        <div className="ui-stack">
          <section aria-labelledby="ss-stay" className="ui-card">
            <h2 id="ss-stay">{st(language, "d_stay")}</h2>
            <dl className="ui-kv">
              <dt>{st(language, "d_unit")}</dt>
              <dd>
                <span className="ui-num">{booking.unit_number}</span> ·{" "}
                {unitTypeText(language, booking.unit_type)}
              </dd>
              <dt>{st(language, "d_stay")}</dt>
              <dd className="ui-num">
                {st(
                  language,
                  "d_dates",
                  dayText(booking.check_in_on),
                  dayText(booking.check_out_on),
                )}
              </dd>
              <dt>{st(language, "d_nights")}</dt>
              <dd>
                {nightsText(language, booking.nights)}
                <span className="ui-sub2 ui-num">
                  {st(
                    language,
                    "d_times",
                    timeText(booking.check_in_time),
                    timeText(booking.check_out_time),
                  )}
                </span>
              </dd>
              <dt>{st(language, "d_guests")}</dt>
              <dd className="ui-num">{booking.guest_count}</dd>
              <dt>{st(language, "d_source")}</dt>
              <dd>
                {source}
                {booking.site_reference !== null && (
                  <span className="ui-sub2 ui-num">
                    {booking.site_reference}
                  </span>
                )}
              </dd>
              {booking.note !== null && (
                <>
                  <dt>{st(language, "d_note")}</dt>
                  <dd className="note">{booking.note}</dd>
                </>
              )}
            </dl>
          </section>
          <PaymentCard key={`pay:${cards}`} {...steps} />
          <DepositCard key={`dep:${cards}`} {...steps} />
          <FeesCard key={`fee:${cards}`} {...steps} />
          <DiscountCard key={`disc:${cards}`} {...steps} />
          <MoveDiscountCard key={`md:${cards}`} {...steps} />
          <section aria-labelledby="ss-price" className="ui-card">
            <h2 id="ss-price">{st(language, "d_price")}</h2>
            <PriceLines language={language} lines={booking.lines} />
            <p className="ss-total">
              <span>{st(language, "total")}</span>
              <b className="ui-num">{usdFromCents(booking.total_usd_cents)}</b>
            </p>
          </section>
        </div>
        <div className="ui-stack">
          <CheckInCard key={`in:${cards}`} {...steps} />
          {stayLive && may("short_stays.desk") && (
            <TelegramQrCard
              key={`tg:${booking.booking_id}`}
              language={language}
              propertyId={propertyId}
              stay={{ booking_id: booking.booking_id }}
            />
          )}
          <CheckOutCard key={`out:${cards}`} {...steps} />
          <ChangeUnitCard
            api={api}
            key={`unit:${cards}`}
            propertyId={propertyId}
            {...steps}
          />
          {/* DL-224: a moved stay keeps its agreed price, so it is not extended. */}
          {movesOf(booking).length === 0 && (
            <ExtendCard key={`ext:${cards}`} {...steps} />
          )}
          <CancelCard key={`can:${cards}`} {...steps} />
          <CancelledCard key={`done:${cards}`} {...steps} />
          <RefundCard
            api={api}
            booking={booking}
            key={`refund:${cards}`}
            language={language}
            may={may}
            onDone={load}
            propertyId={propertyId}
          />
          <LeaseCard key={`lease:${cards}`} {...steps} />
          <RoomCheckCard key={`room:${cards}`} {...steps} />
          <DamagesCard key={`dmg:${cards}`} {...steps} />
          <ReviewCard key={`rev:${cards}`} {...steps} />
          <GuestPanel
            api={api}
            booking={booking}
            key={booking.customer_id}
            language={language}
            may={may}
            propertyId={propertyId}
          />
          <section aria-labelledby="ss-hist" className="ui-card">
            <h2 id="ss-hist">{st(language, "d_hist")}</h2>
            <ol className="ui-timeline">
              {booking.history.map((event, index) => {
                const key = `ev_${event.kind}`;
                const units = moveText(language, event);
                return (
                  <li key={index}>
                    <div>
                      {hasText(key) ? st(language, key) : event.kind}
                      {units !== null && (
                        <span className="ui-sub2 ui-num">{units}</span>
                      )}
                      {event.note !== null && (
                        <span className="ui-sub2">{event.note}</span>
                      )}
                      <small className="ui-num">
                        {momentText(event.occurred_at)}
                      </small>
                    </div>
                  </li>
                );
              })}
            </ol>
          </section>
        </div>
      </div>
    </>
  );
}
