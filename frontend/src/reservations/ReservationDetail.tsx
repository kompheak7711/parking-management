// V1-058 R3: the Reservation page (DESIGN.md "Reservations (round 2)"). Left: the facts, why
// it can or cannot be extended, the Extension card and the Cancellation or Expired card.
// Right: the Security Deposit with what happens to that money, and History.

import { ReactNode, useCallback, useEffect, useRef, useState } from "react";

import {
  ReservationUnavailableError,
  type ReservationApi,
  type ReservationResource,
} from "../reservationClient";
import {
  dayText,
  momentText,
  todayInPhnomPenh,
  usdFromCents,
} from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { openPageInAddress } from "../shell/useHashPage";
import type { Language } from "../signInText";
import { CancelDialog, ExtendDialog } from "./ReservationDialogs";
import { ReservationChip, leftText, resultText } from "./ReservationsList";
import { daysLeft, suggestedDeposit } from "./reservationsData";
import { rt, type ReservationTextKey } from "./text";

function Kv({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="ui-kv">
      {rows.map(([term, value]) => (
        <div key={term} style={{ display: "contents" }}>
          <dt>{term}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** What happens to the money received with this Reservation. */
function moneyKey(reservation: ReservationResource): ReservationTextKey {
  if (reservation.deposit_received_usd_cents === 0) return "m_none";
  if (reservation.status !== "CANCELLED") return "m_continues";
  const state = reservation.deposit_outcome_state;
  if (state === "REFUND") return "m_refunded";
  if (state === "NON_REFUNDABLE_DISPOSITION") return "m_kept";
  return reservation.cancellation_responsibility === "PROPERTY"
    ? "m_refund_wait"
    : "m_keep_wait";
}

interface HistoryLine {
  at: string;
  text: string;
}

function historyLines(
  language: Language,
  reservation: ReservationResource,
): HistoryLine[] {
  const lines: HistoryLine[] = [
    {
      at: reservation.reservation_date,
      text: rt(language, "h_reserved", reservation.customer_name),
    },
  ];
  for (const receipt of reservation.receipts)
    lines.push({
      at: receipt.occurred_at,
      text: rt(language, "h_receipt", usdFromCents(receipt.amount_usd_cents)),
    });
  const notice = reservation.extension_notice;
  if (notice !== null)
    lines.push({
      at: notice.approved_at,
      text: rt(language, "h_extended", dayText(notice.new_expiration_date)),
    });
  for (const event of reservation.lifecycle_events)
    lines.push({
      at: event.occurred_at,
      text:
        event.event_kind === "EXPIRATION"
          ? rt(language, "h_expired")
          : rt(
              language,
              "h_cancelled",
              resultText(language, reservation) ?? event.reason_code,
            ),
    });
  for (const outcome of reservation.deposit_outcomes)
    lines.push({
      at: outcome.occurred_at,
      text: rt(
        language,
        outcome.outcome_kind === "REFUND" ? "h_refund" : "h_kept",
        usdFromCents(outcome.amount_usd_cents),
      ),
    });
  return lines.sort((left, right) => right.at.localeCompare(left.at));
}

function when(value: string): string {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) ? dayText(value) : momentText(value);
}

export interface ReservationDetailProps {
  language: Language;
  reservationId: string;
  /** A Reservation of another Property is not shown. */
  propertyId: string;
  api: ReservationApi;
  capabilities: ReadonlySet<string> | null;
  /** A saved change; the list reads the Reservations again. */
  onChanged: () => void;
}

export function ReservationDetail({
  language,
  reservationId,
  propertyId,
  api,
  capabilities,
  onChanged,
}: ReservationDetailProps) {
  const [reservation, setReservation] = useState<ReservationResource | null>(
    null,
  );
  const [missing, setMissing] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [dialog, setDialog] = useState<"extend" | "cancel" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const sequence = useRef(0);
  const today = todayInPhnomPenh();
  const may = (capability: string) =>
    capabilities === null || capabilities.has(capability);

  const load = useCallback(() => {
    const operation = ++sequence.current;
    void api
      .get(reservationId)
      .then((loaded) => {
        if (operation !== sequence.current) return;
        setLoadFailed(false);
        if (loaded.property_id !== propertyId) {
          setReservation(null);
          setMissing(true);
          return;
        }
        setReservation(loaded);
        setMissing(false);
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        // No answer is not "not found": keep what is shown and offer Retry.
        if (error instanceof ReservationUnavailableError) setLoadFailed(true);
        else setMissing(true);
      });
  }, [api, reservationId, propertyId]);

  useEffect(() => {
    setReservation(null);
    load();
  }, [load]);

  const back = (
    <button
      className="ui-crumb"
      onClick={() => {
        openPageInAddress("reservations");
      }}
      type="button"
    >
      <Icon name="back" small />
      {rt(language, "back")}
    </button>
  );

  const failure = loadFailed && (
    <div className="ui-notice warn" role="status">
      <Icon name="alert" />
      <p>{rt(language, "load_failed")}</p>
      <button className="ui-btn" onClick={load} type="button">
        {rt(language, "retry")}
      </button>
    </div>
  );

  if (missing) {
    return (
      <>
        {back}
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{rt(language, "missing")}</p>
        </div>
      </>
    );
  }
  if (reservation === null) {
    return (
      <>
        {back}
        {failure || (
          <p className="ui-muted" role="status">
            {rt(language, "loading")}
          </p>
        )}
      </>
    );
  }

  const active = reservation.status === "ACTIVE";
  const left = daysLeft(reservation, today);
  const suggested = suggestedDeposit(reservation.agreed_monthly_rent_usd_cents);
  const accepted = reservation.deposit_required_usd_cents;
  const cancellation = reservation.lifecycle_events.at(-1) ?? null;
  const notice_ = reservation.extension_notice;
  const history = historyLines(language, reservation);

  return (
    <>
      {back}
      <div className="ui-head">
        <div>
          <div className="ui-hrow">
            <h2 className="ui-num">
              {rt(language, "title", reservation.unit_number)}
            </h2>
            <ReservationChip language={language} status={reservation.status} />
          </div>
          <p>
            {rt(
              language,
              "head_sub",
              reservation.customer_name,
              dayText(reservation.reservation_date),
              dayText(reservation.effective_expiration_date),
            )}
          </p>
        </div>
        <div className="ui-actions">
          {active && may("leases.draft") && (
            <a
              className="ui-btn primary"
              href={hashForPage("leases", `new:${reservation.reservation_id}`)}
            >
              <Icon name="lease" />
              {rt(language, "new_lease")}
            </a>
          )}
          {reservation.status === "COMPLETED" && may("leases.read") && (
            <a
              className="ui-btn"
              href={hashForPage(
                "leases",
                reservation.resulting_lease_id ?? undefined,
              )}
            >
              <Icon name="lease" />
              {rt(language, "open_lease")}
            </a>
          )}
          {active && reservation.can_extend && (
            <button
              className="ui-btn"
              onClick={() => {
                setNotice(null);
                setWarning(null);
                setDialog("extend");
              }}
              type="button"
            >
              <Icon name="calendar" />
              {rt(language, "extend")}
              <span className="ui-badge">{rt(language, "manager")}</span>
            </button>
          )}
          {active && reservation.can_cancel && (
            <button
              className="ui-btn"
              onClick={() => {
                setNotice(null);
                setWarning(null);
                setDialog("cancel");
              }}
              type="button"
            >
              <Icon name="x" />
              {rt(language, "cancel_res")}
            </button>
          )}
        </div>
      </div>
      {failure}
      {active && left <= 7 && (
        <div className="ui-notice warn" role="status">
          <Icon name="clock" />
          <p>{rt(language, "ending_warn", leftText(language, left))}</p>
        </div>
      )}
      {warning !== null && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>{warning}</p>
        </div>
      )}
      {notice !== null && (
        <div className="ui-notice ok" role="status">
          <Icon name="check" />
          <p>{notice}</p>
        </div>
      )}
      <div className="ui-split">
        <div className="ui-stack">
          <section aria-labelledby="reservation-facts" className="ui-card">
            <h2 id="reservation-facts">{rt(language, "facts")}</h2>
            <Kv
              rows={[
                [
                  rt(language, "unit"),
                  may("units.read") ? (
                    <a
                      className="ui-no ui-num"
                      href={hashForPage("units", reservation.unit_id)}
                    >
                      {reservation.unit_number}
                    </a>
                  ) : (
                    <b className="ui-num">{reservation.unit_number}</b>
                  ),
                ],
                [
                  rt(language, "customer"),
                  may("customers.read") ? (
                    <a
                      className="ui-no"
                      href={hashForPage("customers", reservation.customer_id)}
                    >
                      {reservation.customer_name}
                    </a>
                  ) : (
                    reservation.customer_name
                  ),
                ],
                [
                  rt(language, "reserved_on"),
                  <span className="ui-num">
                    {dayText(reservation.reservation_date)}
                  </span>,
                ],
                [
                  rt(language, "original"),
                  <span className="ui-num">
                    {dayText(reservation.original_expiration_date)}
                  </span>,
                ],
                [
                  rt(language, "expires"),
                  <span className="ui-num">
                    {dayText(reservation.effective_expiration_date)}
                    {active && (
                      <span className="ui-sub2">
                        {leftText(language, left)}
                      </span>
                    )}
                  </span>,
                ],
                [
                  rt(language, "agreed"),
                  <span>
                    <span className="ui-num">
                      {usdFromCents(reservation.agreed_monthly_rent_usd_cents)}
                    </span>
                    <span className="ui-sub2">
                      {rt(language, "agreed_note")}
                    </span>
                  </span>,
                ],
              ]}
            />
            {active && notice_ !== null && (
              <p className="ui-small ui-muted">
                {rt(language, "no_extend_used")}
              </p>
            )}
          </section>
          {notice_ !== null && (
            <section
              aria-labelledby="reservation-extension"
              className="ui-card"
            >
              <h2 id="reservation-extension">{rt(language, "extension")}</h2>
              <Kv
                rows={[
                  [
                    rt(language, "was"),
                    <span className="ui-num">
                      {dayText(notice_.previous_expiration_date)}
                    </span>,
                  ],
                  [
                    rt(language, "new_exp"),
                    <span className="ui-num">
                      {dayText(notice_.new_expiration_date)}
                    </span>,
                  ],
                  [
                    rt(language, "approved_on"),
                    <span className="ui-num">
                      {momentText(notice_.approved_at)}
                    </span>,
                  ],
                  [
                    rt(language, "memo"),
                    notice_.reason_memo ?? <span className="ui-muted">—</span>,
                  ],
                ]}
              />
            </section>
          )}
          {cancellation !== null && (
            <section
              aria-labelledby="reservation-cancellation"
              className="ui-card"
            >
              <h2 id="reservation-cancellation">
                {rt(
                  language,
                  cancellation.event_kind === "EXPIRATION"
                    ? "expired_card"
                    : "cancellation",
                )}
              </h2>
              <Kv
                rows={[
                  [
                    rt(language, "reason"),
                    resultText(language, reservation) ??
                      cancellation.reason_code,
                  ],
                  [
                    rt(language, "responsibility"),
                    rt(language, `resp_${cancellation.responsibility}`),
                  ],
                  [
                    rt(language, "when"),
                    <span className="ui-num">
                      {momentText(cancellation.occurred_at)}
                    </span>,
                  ],
                  ...(cancellation.coordination_reference !== null
                    ? ([
                        [
                          rt(language, "offered"),
                          cancellation.coordination_reference,
                        ],
                      ] as [string, ReactNode][])
                    : []),
                  [
                    rt(language, "memo"),
                    cancellation.reason_memo ?? (
                      <span className="ui-muted">—</span>
                    ),
                  ],
                ]}
              />
            </section>
          )}
        </div>
        <div className="ui-stack">
          <section aria-labelledby="reservation-deposit" className="ui-card">
            <h2 id="reservation-deposit">{rt(language, "security")}</h2>
            <Kv
              rows={[
                [
                  rt(language, "suggested"),
                  <span>
                    <span className="ui-num">{usdFromCents(suggested)}</span>
                    <span className="ui-sub2">
                      {rt(language, "suggested_note")}
                    </span>
                  </span>,
                ],
                [
                  rt(language, "accepted"),
                  <span>
                    <span className="ui-num">{usdFromCents(accepted)}</span>
                    <span className="ui-sub2">
                      {rt(
                        language,
                        accepted === suggested ? "same" : "different",
                      )}
                    </span>
                  </span>,
                ],
                [
                  rt(language, "received"),
                  <span>
                    <b className="ui-num">
                      {usdFromCents(reservation.deposit_received_usd_cents)}
                    </b>
                    {reservation.receipts.map((receipt) => (
                      <span className="ui-sub2 ui-num" key={receipt.receipt_id}>
                        {rt(
                          language,
                          "receipt_line",
                          usdFromCents(receipt.amount_usd_cents),
                          momentText(receipt.occurred_at),
                        )}
                      </span>
                    ))}
                  </span>,
                ],
              ]}
            />
            <div
              className={
                reservation.status === "CANCELLED"
                  ? "ui-notice warn"
                  : "ui-notice ok"
              }
            >
              <Icon name="info" />
              <p>{rt(language, moneyKey(reservation))}</p>
            </div>
          </section>
          <section aria-labelledby="reservation-history" className="ui-card">
            <h2 id="reservation-history">{rt(language, "history")}</h2>
            <ol className="ui-timeline">
              {history.map((line, index) => (
                <li key={`${line.at}-${String(index)}`}>
                  <div>
                    {line.text}
                    <small className="ui-num">{when(line.at)}</small>
                  </div>
                </li>
              ))}
            </ol>
          </section>
        </div>
      </div>
      {dialog === "extend" && (
        <ExtendDialog
          api={api}
          language={language}
          onClose={() => {
            setDialog(null);
          }}
          onConflict={() => {
            setDialog(null);
            setWarning(rt(language, "conflict"));
            load();
          }}
          onSaved={(saved) => {
            setDialog(null);
            setReservation(saved);
            setNotice(
              rt(
                language,
                "saved_extend",
                dayText(saved.effective_expiration_date),
              ),
            );
            onChanged();
            load();
          }}
          reservation={reservation}
        />
      )}
      {dialog === "cancel" && (
        <CancelDialog
          api={api}
          language={language}
          onClose={() => {
            setDialog(null);
          }}
          onConflict={() => {
            setDialog(null);
            setWarning(rt(language, "conflict"));
            load();
          }}
          onSaved={(saved) => {
            setDialog(null);
            setReservation(saved);
            setNotice(rt(language, "saved_cancel"));
            onChanged();
            load();
          }}
          reservation={reservation}
        />
      )}
    </>
  );
}
