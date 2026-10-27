// V1-058 R3: the Reservations list (DESIGN.md "Reservations (round 2)"): four count cards that
// filter the table, and the table of Reservations.

import { type ReactNode, useState } from "react";

import type {
  ReservationResource,
  ReservationStatus,
} from "../reservationClient";
import { dayText, usdFromCents } from "../shell/format";
import type { ShellIcon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { openPageInAddress } from "../shell/useHashPage";
import { Chip, CountCard, type Tone } from "../shell/ui";
import type { Language } from "../signInText";
import {
  ReservationCard,
  ReservationsData,
  cardOf,
  daysLeft,
  isEnding,
  resultOf,
} from "./reservationsData";
import { rt } from "./text";

const STATUS_CHIPS: Record<ReservationStatus, [Tone, ShellIcon | undefined]> = {
  ACTIVE: ["ok", "check"],
  COMPLETED: ["info", "lease"],
  CANCELLED: ["neutral", undefined],
};

export function ReservationChip({
  language,
  status,
}: {
  language: Language;
  status: ReservationStatus;
}) {
  const [tone, icon] = STATUS_CHIPS[status];
  return (
    <Chip icon={icon} tone={tone}>
      {rt(language, `s_${status}`)}
    </Chip>
  );
}

/** "5 days left", "1 day left" or "last day today". */
export function leftText(language: Language, days: number): string {
  if (days <= 0) return rt(language, "last_day");
  return days === 1
    ? rt(language, "day_left")
    : rt(language, "days_left", days);
}

export function resultText(
  language: Language,
  reservation: ReservationResource,
): string | null {
  const result = resultOf(reservation);
  return result === null ? null : rt(language, `r_${result}`);
}

const CARDS: [ReservationCard, ShellIcon, Tone | "brand"][] = [
  ["active", "check", "ok"],
  ["ending", "clock", "warn"],
  ["completed", "lease", "info"],
  ["cancelled", "x", "neutral"],
];

export function ReservationsList({
  language,
  data,
  today,
  action,
}: {
  language: Language;
  data: ReservationsData;
  today: string;
  /** V1-060 B6: the Make Reservation button. */
  action?: ReactNode;
}) {
  const [card, setCard] = useState<ReservationCard | "all">("all");
  const inCard = (reservation: ReservationResource, value: ReservationCard) =>
    value === "ending"
      ? isEnding(reservation, today)
      : cardOf(reservation) === value;
  const shown = data.reservations.filter(
    (reservation) => card === "all" || inCard(reservation, card),
  );
  const open = (id: string) => {
    openPageInAddress("reservations", false, id);
  };

  return (
    <>
      <div className="ui-head">
        <p>{rt(language, "sub", data.reservations.length)}</p>
        {action !== undefined && <div className="ui-actions">{action}</div>}
      </div>
      <div className="ui-kpis">
        {CARDS.map(([value, icon, tone]) => (
          <CountCard
            icon={icon}
            key={value}
            label={rt(language, `c_${value}`)}
            note={rt(language, `c_${value}_s`)}
            onPress={() => {
              setCard(card === value ? "all" : value);
            }}
            pressed={card === value}
            tone={tone}
            value={
              data.reservations.filter((reservation) =>
                inCard(reservation, value),
              ).length
            }
          />
        ))}
      </div>
      <div className="ui-card pad0">
        {card !== "all" && (
          <div className="ui-listbar">
            {rt(language, "showing", rt(language, `c_${card}`))}
            <button
              className="ui-btn link"
              onClick={() => {
                setCard("all");
              }}
              type="button"
            >
              {rt(language, "show_all")}
            </button>
          </div>
        )}
        {shown.length === 0 ? (
          <p className="ui-empty">{rt(language, "none")}</p>
        ) : (
          <>
            <div className="ui-tablewrap">
              <table className="ui-table">
                <thead>
                  <tr>
                    <th scope="col">{rt(language, "unit")}</th>
                    <th scope="col">{rt(language, "customer")}</th>
                    <th scope="col">{rt(language, "reserved_on")}</th>
                    <th scope="col">{rt(language, "expires")}</th>
                    <th className="r" scope="col">
                      {rt(language, "deposit")}
                    </th>
                    <th scope="col">{rt(language, "status")}</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((reservation) => {
                    const id = reservation.reservation_id;
                    const active = reservation.status === "ACTIVE";
                    const notes = [
                      reservation.extension_notice !== null
                        ? rt(language, "extended_once")
                        : null,
                      active
                        ? leftText(language, daysLeft(reservation, today))
                        : null,
                    ].filter((note) => note !== null);
                    const result = resultText(language, reservation);
                    return (
                      <tr
                        className="ui-row"
                        key={id}
                        onClick={() => {
                          open(id);
                        }}
                      >
                        <td>
                          <a
                            className="ui-no ui-num"
                            href={hashForPage("reservations", id)}
                            onClick={(event) => {
                              event.stopPropagation();
                              // A plain click opens the Reservation here; with a key held the
                              // browser opens the link as it normally does.
                              if (
                                event.button !== 0 ||
                                event.metaKey ||
                                event.ctrlKey ||
                                event.shiftKey ||
                                event.altKey
                              )
                                return;
                              event.preventDefault();
                              open(id);
                            }}
                          >
                            {reservation.unit_number}
                          </a>
                        </td>
                        <td>{reservation.customer_name}</td>
                        <td className="ui-num">
                          {dayText(reservation.reservation_date)}
                        </td>
                        <td className="ui-num">
                          {dayText(reservation.effective_expiration_date)}
                          {notes.length > 0 && (
                            <span
                              className={
                                active && isEnding(reservation, today)
                                  ? "ui-sub2 warn"
                                  : "ui-sub2"
                              }
                            >
                              {notes.join(" · ")}
                            </span>
                          )}
                        </td>
                        <td className="r ui-num">
                          {usdFromCents(reservation.deposit_received_usd_cents)}
                          <span className="ui-sub2">
                            {rt(
                              language,
                              "of",
                              usdFromCents(
                                reservation.deposit_required_usd_cents,
                              ),
                            )}
                          </span>
                        </td>
                        <td className="wrap">
                          <ReservationChip
                            language={language}
                            status={reservation.status}
                          />
                          {result !== null && (
                            <span className="ui-sub2">{result}</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="ui-tfoot">
              {shown.length === 1
                ? rt(language, "n1")
                : rt(language, "n", shown.length)}
            </div>
          </>
        )}
      </div>
    </>
  );
}
