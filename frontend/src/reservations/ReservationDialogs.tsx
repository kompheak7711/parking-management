// V1-058 R3: Extend and Cancel Reservation (DESIGN.md "Reservations (round 2)"). Each dialog
// keeps one request identity (record id and idempotency key) while its values stay the same,
// so "Try again" after an unknown result sends the very same request and the server records
// it once.

import { FormEvent, ReactNode, useRef, useState } from "react";

import {
  ReservationConflictError,
  ReservationUnavailableError,
  type CancellationResponsibility,
  type ReservationApi,
  type ReservationResource,
} from "../reservationClient";
import { DateInput, isDay } from "../shell/DateInput";
import { dayText, todayInPhnomPenh, usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import { leftText } from "./ReservationsList";
import { addDays, daysLeft } from "./reservationsData";
import { rt } from "./text";

type Outcome = "unknown" | "refused" | null;

function Problem({ message }: { message: string | null }) {
  if (message === null) return null;
  return (
    <p className="ui-error" role="alert">
      <Icon name="alert" small />
      <span>{message}</span>
    </p>
  );
}

function OutcomeNotice({
  language,
  outcome,
}: {
  language: Language;
  outcome: Outcome;
}) {
  if (outcome === null) return null;
  return (
    <div className="ui-notice warn" role="alert">
      <Icon name="alert" />
      <p>{rt(language, outcome)}</p>
    </div>
  );
}

/** Sends a request and sorts its ending: saved, someone else changed it, unknown, refused. */
function useSend(
  onSaved: (saved: ReservationResource) => void,
  onConflict: () => void,
) {
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>(null);
  function send(request: () => Promise<ReservationResource>) {
    setBusy(true);
    setOutcome(null);
    void request()
      .then(onSaved)
      .catch((error: unknown) => {
        if (error instanceof ReservationConflictError) {
          onConflict();
          return;
        }
        // No answer, or the service was down: the request may or may not have been saved.
        setOutcome(
          error instanceof ReservationUnavailableError ? "unknown" : "refused",
        );
      })
      .finally(() => {
        setBusy(false);
      });
  }
  return { busy, outcome, send };
}

interface Identity<T> {
  fingerprint: string;
  key: string;
  id: string;
  source: T;
}

/** The same identity while the values stay the same; new values get a new one. */
function identityFor<T>(
  current: { current: Identity<T> | null },
  source: T,
): Identity<T> {
  const fingerprint = JSON.stringify(source);
  if (current.current?.fingerprint !== fingerprint)
    current.current = {
      fingerprint,
      key: crypto.randomUUID(),
      id: crypto.randomUUID(),
      source,
    };
  return current.current;
}

export function ExtendDialog({
  language,
  api,
  reservation,
  onClose,
  onSaved,
  onConflict,
}: {
  language: Language;
  api: ReservationApi;
  reservation: ReservationResource;
  onClose: () => void;
  onSaved: (saved: ReservationResource) => void;
  onConflict: () => void;
}) {
  const earliest = addDays(reservation.effective_expiration_date, 1);
  const latest = addDays(reservation.effective_expiration_date, 14);
  const [date, setDate] = useState(latest);
  const [memo, setMemo] = useState("");
  const [wrong, setWrong] = useState(false);
  const identity = useRef<Identity<{ date: string; memo: string }> | null>(
    null,
  );
  const { busy, outcome, send } = useSend(onSaved, onConflict);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const bad = !isDay(date) || date < earliest || date > latest;
    setWrong(bad);
    if (bad) return;
    const chosen = identityFor(identity, { date, memo: memo.trim() });
    send(() =>
      api.extend(
        reservation,
        {
          notice_id: chosen.id,
          new_expiration_date: chosen.source.date,
          reason_memo: chosen.source.memo,
        },
        chosen.key,
      ),
    );
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={rt(language, "close")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={
        busy
          ? rt(language, "saving")
          : outcome === "unknown"
            ? rt(language, "try_again")
            : rt(language, "save_extend")
      }
      title={rt(language, "extend_title", reservation.unit_number)}
    >
      <p>{rt(language, "extend_note")}</p>
      <p className="ui-small ui-muted">
        {rt(
          language,
          "left_now",
          leftText(language, daysLeft(reservation, todayInPhnomPenh())),
        )}{" "}
        {rt(language, "latest", dayText(latest))}
      </p>
      <div className="ui-field">
        <label htmlFor="reservation-new-date">{rt(language, "new_date")}</label>
        <DateInput
          language={language}
          invalid={wrong}
          id="reservation-new-date"
          max={latest}
          min={earliest}
          onChange={(value) => {
            setDate(value);
          }}
          value={date}
        />
        <Problem
          message={
            wrong
              ? rt(
                  language,
                  "e_date",
                  dayText(reservation.effective_expiration_date),
                  dayText(latest),
                )
              : null
          }
        />
      </div>
      <div className="ui-field">
        <label htmlFor="reservation-extend-memo">
          {rt(language, "memo_optional")}
        </label>
        <textarea
          id="reservation-extend-memo"
          maxLength={500}
          onChange={(event) => {
            setMemo(event.currentTarget.value);
          }}
          rows={2}
          value={memo}
        />
      </div>
      <OutcomeNotice language={language} outcome={outcome} />
    </Dialog>
  );
}

interface CancelSource {
  responsibility: CancellationResponsibility;
  memo: string;
  offered: string;
}

export function CancelDialog({
  language,
  api,
  reservation,
  onClose,
  onSaved,
  onConflict,
}: {
  language: Language;
  api: ReservationApi;
  reservation: ReservationResource;
  onClose: () => void;
  onSaved: (saved: ReservationResource) => void;
  onConflict: () => void;
}) {
  const [responsibility, setResponsibility] =
    useState<CancellationResponsibility | null>(null);
  const [memo, setMemo] = useState("");
  const [offered, setOffered] = useState("");
  const [problems, setProblems] = useState<Record<string, string>>({});
  const identity = useRef<Identity<CancelSource> | null>(null);
  const { busy, outcome, send } = useSend(onSaved, onConflict);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const found: Record<string, string> = {};
    if (responsibility === null) found.why = rt(language, "e_why");
    if (memo.trim() === "") found.memo = rt(language, "e_memo");
    if (responsibility === "PROPERTY" && offered.trim() === "")
      found.offered = rt(language, "e_offered");
    setProblems(found);
    if (responsibility === null || Object.keys(found).length > 0) return;
    const chosen = identityFor(identity, {
      responsibility,
      memo: memo.trim(),
      offered: responsibility === "PROPERTY" ? offered.trim() : "",
    });
    const customer = chosen.source.responsibility === "CUSTOMER";
    send(() =>
      api.cancel(
        reservation,
        {
          event_id: chosen.id,
          reason_code: customer
            ? "CUSTOMER_NO_LONGER_WANTS_UNIT"
            : "PROPERTY_CANNOT_PROVIDE_UNIT",
          responsibility: chosen.source.responsibility,
          property_could_provide_unit: customer,
          reason_memo: chosen.source.memo,
          coordination_reference: customer ? null : chosen.source.offered,
        },
        chosen.key,
      ),
    );
  }

  const choice = (value: CancellationResponsibility, label: ReactNode) => (
    <label className="ui-chk">
      <input
        checked={responsibility === value}
        name="reservation-why"
        onChange={() => {
          setResponsibility(value);
        }}
        type="radio"
        value={value}
      />
      <span>{label}</span>
    </label>
  );

  return (
    <Dialog
      busy={busy}
      closeLabel={rt(language, "keep")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={
        busy
          ? rt(language, "saving")
          : outcome === "unknown"
            ? rt(language, "try_again")
            : rt(language, "cancel_res")
      }
      title={rt(language, "cancel_title", reservation.unit_number)}
    >
      <p className="ui-small">
        {rt(
          language,
          "deposit_now",
          usdFromCents(reservation.deposit_received_usd_cents),
        )}
      </p>
      <fieldset className="ui-radios">
        <legend>{rt(language, "why")}</legend>
        {choice("CUSTOMER", rt(language, "why_customer"))}
        {choice("PROPERTY", rt(language, "why_property"))}
        <Problem message={problems.why ?? null} />
      </fieldset>
      {responsibility === "PROPERTY" && (
        <div className="ui-field">
          <label htmlFor="reservation-offered">
            {rt(language, "offered")}
            <span className="req">{rt(language, "required")}</span>
          </label>
          <input
            aria-invalid={problems.offered !== undefined}
            id="reservation-offered"
            maxLength={255}
            onChange={(event) => {
              setOffered(event.currentTarget.value);
            }}
            value={offered}
          />
          <p className="help">{rt(language, "offered_help")}</p>
          <Problem message={problems.offered ?? null} />
        </div>
      )}
      <div className="ui-field">
        <label htmlFor="reservation-cancel-memo">
          {rt(language, "memo_req")}
          <span className="req">{rt(language, "required")}</span>
        </label>
        <textarea
          aria-invalid={problems.memo !== undefined}
          id="reservation-cancel-memo"
          maxLength={500}
          onChange={(event) => {
            setMemo(event.currentTarget.value);
          }}
          rows={2}
          value={memo}
        />
        <Problem message={problems.memo ?? null} />
      </div>
      <p className="ui-small ui-muted">{rt(language, "cancel_effects")}</p>
      <OutcomeNotice language={language} outcome={outcome} />
    </Dialog>
  );
}
