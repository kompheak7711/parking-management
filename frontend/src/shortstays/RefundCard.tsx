// Owner test 06/11/2026 (card "How should a free cancel give the money back to the guest?"): after
// a free cancel the paid money is the guest's Customer Credit; this card gives it back. It records
// a Refund draft of each Credit (migration 20270611_351 reads what is left), so a financial.approve
// holder confirms it in Waiting for approval, as every Refund.

import { type FormEvent, useEffect, useRef, useState } from "react";

import { usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import type { Language } from "../signInText";
import {
  type Booking,
  type RefundMethod,
  type ShortStaysApi,
  ShortStaysError,
} from "./shortStaysClient";
import { st } from "./text";

export function RefundCard({
  api,
  booking,
  language,
  may,
  propertyId,
  onDone,
}: {
  api: ShortStaysApi;
  booking: Booking;
  language: Language;
  may: (capability: string) => boolean;
  propertyId: string;
  onDone: () => void;
}) {
  const refund = booking.refund ?? null;
  const open =
    refund === null
      ? 0
      : Math.max(0, refund.left_usd_cents - refund.waiting_usd_cents);
  const mayRefund = may("refunds.create") && open > 0;
  const [methods, setMethods] = useState<RefundMethod[] | "failed" | null>(
    null,
  );
  const [methodId, setMethodId] = useState("");
  const [note, setNote] = useState("");
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<"f_failed" | "f_step_right" | null>(
    null,
  );
  // One key per Credit for this card, so a second press never records the Refund twice.
  const keys = useRef(new Map<string, string>());

  useEffect(() => {
    if (!mayRefund) return;
    let live = true;
    api
      .refundMethods(propertyId)
      .then((found) => {
        if (!live) return;
        setMethods(found);
        setMethodId((current) => current || (found[0]?.id ?? ""));
      })
      .catch(() => {
        if (live) setMethods("failed");
      });
    return () => {
      live = false;
    };
  }, [api, propertyId, mayRefund]);

  if (refund === null) return null;
  // DL-224: a stay that still stands has this Credit from a special discount after a move.
  const reason =
    booking.status === "BOOKED" ||
    booking.status === "CHECKED_IN" ||
    booking.status === "CHECKED_OUT"
      ? `Special discount ${booking.booking_number}: the money paid above the new price goes back`
      : `Free cancel ${booking.booking_number}: the money paid goes back`;
  const wrongMethod = methodId === "";
  const wrongNote = note.trim() === "";

  const give = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setChecked(true);
    setProblem(null);
    if (wrongMethod || wrongNote) return;
    setBusy(true);
    void (async () => {
      try {
        let left = open;
        for (const credit of refund.credits) {
          const amount = Math.min(credit.left_usd_cents, left);
          if (amount <= 0) continue;
          let key = keys.current.get(credit.credit_id);
          if (key === undefined) {
            key = crypto.randomUUID();
            keys.current.set(credit.credit_id, key);
          }
          await api.refund(
            propertyId,
            {
              credit_id: credit.credit_id,
              amount_usd_cents: amount,
              reason,
              refund_method_id: methodId,
              reference_note: note.trim(),
            },
            key,
          );
          left -= amount;
        }
        onDone();
      } catch (error: unknown) {
        setProblem(
          error instanceof ShortStaysError && error.status === 403
            ? "f_step_right"
            : "f_failed",
        );
      } finally {
        setBusy(false);
      }
    })();
  };

  return (
    <section aria-labelledby="ss-refund" className="ui-card">
      <h2 id="ss-refund">{st(language, "rf_t")}</h2>
      {refund.refunded_usd_cents > 0 && (
        <p className="ui-small">
          {st(language, "rf_done", usdFromCents(refund.refunded_usd_cents))}
        </p>
      )}
      {refund.waiting_usd_cents > 0 && (
        <p className="ui-small">
          {st(language, "rf_wait", usdFromCents(refund.waiting_usd_cents))}{" "}
          {may("financial.approve") && (
            <a href={hashForPage("approvals")}>{st(language, "rf_open")}</a>
          )}
        </p>
      )}
      {open > 0 && !may("refunds.create") && (
        <p className="ui-small ui-muted">{st(language, "rf_no_right")}</p>
      )}
      {mayRefund && (
        <form className="ui-form ss-form" noValidate onSubmit={give}>
          <p className="ui-small">{st(language, "rf_s", usdFromCents(open))}</p>
          {problem !== null && (
            <div className="ui-notice warn" role="alert">
              <Icon name="alert" />
              <p>{st(language, problem)}</p>
            </div>
          )}
          {methods === "failed" && (
            <p className="ui-error">
              <Icon name="alert" small />
              <span>{st(language, "failed")}</span>
            </p>
          )}
          <div className="ui-field">
            <label htmlFor="ss-rf-method">
              {st(language, "rf_method")}
              <span className="req">{st(language, "required")}</span>
            </label>
            <select
              aria-invalid={checked && wrongMethod}
              disabled={busy || !Array.isArray(methods)}
              id="ss-rf-method"
              onChange={(event) => {
                setMethodId(event.currentTarget.value);
              }}
              value={methodId}
            >
              <option value="">{st(language, "pick")}</option>
              {(Array.isArray(methods) ? methods : []).map((method) => (
                <option key={method.id} value={method.id}>
                  {method.name}
                </option>
              ))}
            </select>
          </div>
          <div className="ui-field">
            <label htmlFor="ss-rf-note">
              {st(language, "rf_note")}
              <span className="req">{st(language, "required")}</span>
            </label>
            <input
              aria-describedby="ss-rf-note-s"
              aria-invalid={checked && wrongNote}
              autoComplete="off"
              disabled={busy}
              id="ss-rf-note"
              maxLength={500}
              onChange={(event) => {
                setNote(event.currentTarget.value);
              }}
              value={note}
            />
            <p className="ui-small ui-muted" id="ss-rf-note-s">
              {st(language, "rf_note_s")}
            </p>
            {checked && wrongNote && (
              <p className="ui-error">
                <Icon name="alert" small />
                <span>{st(language, "e_rf_note")}</span>
              </p>
            )}
          </div>
          <div className="ui-actions">
            <button className="ui-btn primary" disabled={busy} type="submit">
              <Icon name="payments" small />
              {st(language, "rf_b", usdFromCents(open))}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
