// The one-time Telegram QR (DL-214, owner 11 Nov 2026 "Yes, QR for tenants and guests"): on a
// signed Lease or a guest's stay, staff show a QR; the person scans it, taps Start in Telegram and
// is linked at once. The server keeps only the code's hash, so a QR is shown once and never read
// again. The server checks the right again (Sign Lease for a Lease, the front desk for a Booking).

import { useRef, useState } from "react";

import { momentText } from "../shell/format";
import { Icon } from "../shell/icons";
import type { Language } from "../signInText";
import {
  type LinkCodeMade,
  type LinkPeople,
  type LinkQrApi,
  type LinkStay,
  linkQrApi,
  TelegramError,
} from "./telegramClient";
import { type TelegramTextKey, tt } from "./text";

function problemOf(error: unknown): TelegramTextKey {
  if (!(error instanceof TelegramError)) return "e_save";
  switch (error.status) {
    case 403:
      return "e_403";
    case 409:
      return "qr_e_409";
    case 422:
      return "qr_e_422";
    default:
      return "e_save";
  }
}

export function TelegramQrCard({
  language,
  propertyId,
  stay,
  api = linkQrApi,
}: {
  language: Language;
  propertyId: string;
  stay: LinkStay;
  api?: LinkQrApi;
}) {
  const [people, setPeople] = useState<LinkPeople | null>(null);
  const [made, setMade] = useState<LinkCodeMade | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<TelegramTextKey | null>(null);
  // An answer that comes after Close or a newer click is not shown.
  const sequence = useRef(0);
  const guest = "booking_id" in stay;

  const start = <T,>(work: () => Promise<T>, done: (value: T) => void) => {
    sequence.current += 1;
    const mine = sequence.current;
    setBusy(true);
    setProblem(null);
    work().then(
      (value) => {
        if (mine !== sequence.current) return;
        setBusy(false);
        done(value);
      },
      (error: unknown) => {
        if (mine !== sequence.current) return;
        setBusy(false);
        setProblem(problemOf(error));
      },
    );
  };

  const open = () => {
    start(() => api.people(propertyId, stay), setPeople);
  };

  const close = () => {
    sequence.current += 1;
    setBusy(false);
    setMade(null);
    setPeople(null);
    setProblem(null);
  };

  return (
    <section aria-labelledby="tg-qr-h" className="ui-card">
      <h2 id="tg-qr-h">{tt(language, "qr_h")}</h2>
      <p className="ui-small ui-muted">
        {tt(language, guest ? "qr_sub_stay" : "qr_sub_lease")}
      </p>
      {problem !== null && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>{tt(language, problem)}</p>
        </div>
      )}
      {made !== null ? (
        <div className="tg-qr-made">
          <img
            alt={tt(language, "qr_alt")}
            className="tg-qr"
            src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(made.qr_svg)}`}
          />
          <p role="status">
            {tt(
              language,
              "qr_scan",
              made.name,
              made.unit_number ?? "",
              momentText(made.expires_at),
            )}
          </p>
          <p className="ui-small ui-muted">{tt(language, "qr_once")}</p>
          <div className="ui-actions">
            <button className="ui-btn" onClick={close} type="button">
              {tt(language, "qr_close")}
            </button>
          </div>
        </div>
      ) : people === null ? (
        <div className="ui-actions">
          <button
            className="ui-btn"
            disabled={busy}
            onClick={open}
            type="button"
          >
            {tt(language, busy ? "loading" : "qr_open")}
          </button>
        </div>
      ) : !people.bot_ready ? (
        <p className="ui-muted" role="status">
          {tt(language, "qr_not_ready")}
        </p>
      ) : people.people.length === 0 ? (
        <p className="ui-muted" role="status">
          {tt(language, "qr_none")}
        </p>
      ) : (
        <div className="ui-actions">
          {people.people.map((person) => (
            <button
              className="ui-btn primary"
              disabled={busy}
              key={person.customer_id}
              onClick={() => {
                start(
                  () => api.make(propertyId, stay, person.customer_id),
                  setMade,
                );
              }}
              type="button"
            >
              {tt(language, "qr_for", person.name)}
            </button>
          ))}
          <button className="ui-btn" onClick={close} type="button">
            {tt(language, "cancel")}
          </button>
        </div>
      )}
    </section>
  );
}
