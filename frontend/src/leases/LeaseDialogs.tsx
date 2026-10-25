// V1-058 R3 L2a: Sign Lease and Edit draft (DESIGN.md "Leases (round 2)"). Each request keeps
// one identity (record id and idempotency key) while its values stay the same, so "Try again"
// after an unknown result sends the very same request and the server records it once.

import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";

import {
  LeaseConflictError,
  LeaseUnavailableError,
  type LeaseApi,
  type LeaseResource,
} from "../leaseClient";
import type { ReservationApi } from "../reservationClient";
import { dayText, todayInPhnomPenh, usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import { initialRent } from "./leasesData";
import { lt } from "./text";

type Outcome = "unknown" | "refused" | null;

// The reason stored with each signature; the dialog's tick is the person's statement.
const SIGN_REASON = "Every Signer signed the paper Lease";

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
  refused = "refused",
}: {
  language: Language;
  outcome: Outcome;
  refused?: "refused" | "sign_refused";
}) {
  if (outcome === null) return null;
  return (
    <div className="ui-notice warn" role="alert">
      <Icon name="alert" />
      <p>{lt(language, outcome === "refused" ? refused : outcome)}</p>
    </div>
  );
}

type ReservationCheck =
  | { state: "loading" }
  | { state: "done"; id: string | null }
  | { state: "failed" };

/** The active Reservation of this Lease's Primary Tenant for its Unit, if there is one. */
async function activeReservationOf(
  api: Pick<ReservationApi, "list">,
  lease: LeaseResource,
): Promise<string | null> {
  let cursor: string | undefined;
  for (;;) {
    const page = await api.list(lease.property_id, "ACTIVE", cursor);
    const found = page.items.find(
      (item) =>
        item.unit_id === lease.unit_id &&
        item.customer_id === lease.primary_tenant_id,
    );
    if (found !== undefined) return found.reservation_id;
    if (page.next_cursor === null) return null;
    cursor = page.next_cursor;
  }
}

/** Sends a request and sorts its ending: saved, changed meanwhile, unknown, refused. */
function useSend(
  onSaved: (saved: LeaseResource) => void,
  onConflict: () => void,
) {
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>(null);
  function send(request: () => Promise<LeaseResource>) {
    setBusy(true);
    setOutcome(null);
    void request()
      .then(onSaved)
      .catch((error: unknown) => {
        if (error instanceof LeaseConflictError) {
          onConflict();
          return;
        }
        // No answer, or the service was down: the request may or may not have been saved.
        setOutcome(
          error instanceof LeaseUnavailableError ? "unknown" : "refused",
        );
      })
      .finally(() => {
        setBusy(false);
      });
  }
  return { busy, outcome, send };
}

interface Identity {
  key: string;
  id: string;
}

/** One identity per step name, kept for the life of the dialog. */
function useIdentities() {
  const map = useRef(new Map<string, Identity>());
  return (step: string): Identity => {
    const known = map.current.get(step);
    if (known !== undefined) return known;
    const made = { key: crypto.randomUUID(), id: crypto.randomUUID() };
    map.current.set(step, made);
    return made;
  };
}

interface DialogProps {
  language: Language;
  api: LeaseApi;
  lease: LeaseResource;
  onClose: () => void;
  onSaved: (saved: LeaseResource) => void;
  onConflict: () => void;
}

export function SignDialog({
  language,
  api,
  lease,
  reservationApi,
  securityOutstanding,
  dueChanged,
  onClose,
  onSaved,
  onConflict,
  onProgress,
}: DialogProps & {
  reservationApi: Pick<ReservationApi, "list">;
  securityOutstanding: number | null;
  /** An approved Initial Rent Due Date replaces Start Date + 5 days. */
  dueChanged: boolean;
  /** Each recorded signature, so the page shows it even if a later step fails. */
  onProgress: (current: LeaseResource) => void;
}) {
  const unsigned = lease.signers.filter((signer) => signer.signed_at === null);
  const [ticked, setTicked] = useState<ReadonlySet<string>>(new Set());
  const [wrong, setWrong] = useState(false);
  const [reservation, setReservation] = useState<ReservationCheck>({
    state: "loading",
  });
  const identity = useIdentities();
  // The Lease as the last answered step left it, so a retry carries on from there.
  const latest = useRef(lease);
  const { busy, outcome, send } = useSend(onSaved, onConflict);
  const rent = lease.monthly_rent_usd_cents;
  const initial =
    lease.start_date !== null && rent !== null
      ? initialRent(lease.start_date, rent)
      : null;

  // Looked up once when the dialog opens: signing completes the Reservation, so a retry
  // must name the same one the first try named.
  useEffect(() => {
    let live = true;
    activeReservationOf(reservationApi, lease)
      .then((id) => {
        if (live) setReservation({ state: "done", id });
      })
      .catch(() => {
        if (live) setReservation({ state: "failed" });
      });
    return () => {
      live = false;
    };
  }, []);

  async function run(reservationId: string | null): Promise<LeaseResource> {
    let current = latest.current;
    for (const signer of unsigned) {
      const now = current.signers.find(
        (entry) => entry.signer_id === signer.signer_id,
      );
      if (typeof now?.signed_at === "string") continue;
      const step = identity(`signer:${signer.signer_id}`);
      current = await api.recordSignature(
        current,
        signer.signer_id,
        { event_id: step.id, reason: SIGN_REASON },
        step.key,
      );
      latest.current = current;
      onProgress(current);
    }
    const step = identity("sign");
    return api.sign(
      current,
      reservationId === null
        ? { event_id: step.id, reason: SIGN_REASON }
        : {
            event_id: step.id,
            reason: SIGN_REASON,
            reservation_id: reservationId,
          },
      step.key,
    );
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || reservation.state === "loading") return;
    const all = unsigned.every((signer) => ticked.has(signer.signer_id));
    setWrong(!all);
    if (!all) return;
    const reservationId = reservation.state === "done" ? reservation.id : null;
    send(() => run(reservationId));
  }

  const reserved = reservation.state === "done" && reservation.id !== null;

  return (
    <Dialog
      busy={busy || reservation.state === "loading"}
      closeLabel={lt(language, "close")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={
        busy
          ? lt(language, "saving")
          : outcome === "unknown"
            ? lt(language, "try_again")
            : lt(language, "sign_ok")
      }
      title={lt(language, "sign_title", lease.unit_number)}
    >
      <p className="ui-small ui-num">
        {lease.primary_tenant_name} ·{" "}
        {lt(
          language,
          "from_to",
          dayText(lease.start_date),
          dayText(lease.end_date),
        )}
        {rent !== null &&
          ` · ${lt(language, "rent_month", usdFromCents(rent))}`}
      </p>
      <fieldset className="ui-radios">
        <legend>{lt(language, "sign_confirm")}</legend>
        {lease.signers.map((signer) => {
          const done = signer.signed_at !== null;
          return (
            <label className="ui-chk" key={signer.signer_id}>
              <input
                checked={done || ticked.has(signer.signer_id)}
                disabled={done || busy}
                onChange={(event) => {
                  const next = new Set(ticked);
                  if (event.currentTarget.checked) next.add(signer.signer_id);
                  else next.delete(signer.signer_id);
                  setTicked(next);
                }}
                type="checkbox"
              />
              <span>
                {signer.customer_name}
                {signer.is_primary_tenant &&
                  ` · ${lt(language, "primary_tag")}`}
                {signer.signed_at !== null &&
                  ` · ${lt(language, "sign_already", dayText(todayInPhnomPenh(new Date(signer.signed_at))))}`}
              </span>
            </label>
          );
        })}
        <Problem message={wrong ? lt(language, "sign_all") : null} />
      </fieldset>
      <h3>{lt(language, "sign_what")}</h3>
      <ul className="ui-small">
        <li>{lt(language, "sign_s1", lease.unit_number)}</li>
        {reserved && <li>{lt(language, "sign_s2")}</li>}
        {initial !== null && (
          <li>
            {dueChanged
              ? lt(language, "sign_s3_set", usdFromCents(initial.total))
              : lt(
                  language,
                  "sign_s3",
                  usdFromCents(initial.total),
                  dayText(initial.due),
                )}
          </li>
        )}
        {securityOutstanding !== null && securityOutstanding > 0 && (
          <li>{lt(language, "sign_s4", usdFromCents(securityOutstanding))}</li>
        )}
      </ul>
      {reservation.state === "loading" && (
        <p className="ui-small ui-muted" role="status">
          {lt(language, "sign_res_check")}
        </p>
      )}
      {reservation.state === "failed" && (
        <p className="ui-small ui-muted" role="status">
          {lt(language, "sign_res_failed")}
        </p>
      )}
      <OutcomeNotice
        language={language}
        outcome={outcome}
        refused="sign_refused"
      />
    </Dialog>
  );
}

/** "500.00" or "500" as cents; null when it is not a whole-cent amount above zero. */
function centsOf(text: string): number | null {
  const value = text.trim();
  if (!/^\d{1,7}(\.\d{1,2})?$/.test(value)) return null;
  const [dollars = "0", part = ""] = value.split(".");
  const cents = Number(dollars) * 100 + Number(part.padEnd(2, "0"));
  return cents > 0 ? cents : null;
}

/** A Lease ends on the last day of a calendar month (the server checks it too). */
function monthEnd(day: string): boolean {
  const [year = 0, month = 0, date = 0] = day.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, date + 1)).getUTCDate() === 1;
}

export function EditDraftDialog({
  language,
  api,
  lease,
  onClose,
  onSaved,
  onConflict,
}: DialogProps) {
  const [start, setStart] = useState(lease.start_date ?? "");
  const [end, setEnd] = useState(lease.end_date ?? "");
  const [rent, setRent] = useState(
    lease.monthly_rent_usd_cents === null
      ? ""
      : (lease.monthly_rent_usd_cents / 100).toFixed(2),
  );
  const [reason, setReason] = useState("");
  const [problems, setProblems] = useState<Record<string, string>>({});
  const identity = useRef<{ fingerprint: string } & Identity>(null);
  const { busy, outcome, send } = useSend(onSaved, onConflict);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const cents = centsOf(rent);
    const found: Record<string, string> = {};
    if (!/^\d{4}-\d{2}-\d{2}$/.test(start))
      found.start = lt(language, "err_start");
    if (!/^\d{4}-\d{2}-\d{2}$/.test(end) || end <= start || !monthEnd(end))
      found.end = lt(language, "err_end");
    if (cents === null) found.rent = lt(language, "err_rent");
    if (reason.trim() === "") found.reason = lt(language, "err_reason");
    setProblems(found);
    if (cents === null || Object.keys(found).length > 0) return;
    const source = {
      start_date: start,
      end_date: end,
      monthly_rent_usd_cents: cents,
      reason: reason.trim(),
    };
    const fingerprint = JSON.stringify(source);
    if (identity.current?.fingerprint !== fingerprint)
      identity.current = {
        fingerprint,
        key: crypto.randomUUID(),
        id: crypto.randomUUID(),
      };
    const chosen = identity.current;
    send(() =>
      api.update(lease, { event_id: chosen.id, ...source }, chosen.key),
    );
  }

  const field = (
    id: string,
    label: string,
    input: ReactNode,
    problem: string | undefined,
  ) => (
    <div className="ui-field">
      <label htmlFor={id}>{label}</label>
      {input}
      <Problem message={problem ?? null} />
    </div>
  );

  return (
    <Dialog
      busy={busy}
      closeLabel={lt(language, "close")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={
        busy
          ? lt(language, "saving")
          : outcome === "unknown"
            ? lt(language, "try_again")
            : lt(language, "save")
      }
      title={lt(language, "edit_title", lease.unit_number)}
    >
      <p className="ui-small ui-muted">{lt(language, "edit_note")}</p>
      {field(
        "lease-edit-start",
        lt(language, "start"),
        <input
          aria-invalid={problems.start !== undefined}
          id="lease-edit-start"
          onChange={(event) => {
            setStart(event.currentTarget.value);
          }}
          type="date"
          value={start}
        />,
        problems.start,
      )}
      {field(
        "lease-edit-end",
        lt(language, "end"),
        <input
          aria-invalid={problems.end !== undefined}
          id="lease-edit-end"
          onChange={(event) => {
            setEnd(event.currentTarget.value);
          }}
          type="date"
          value={end}
        />,
        problems.end,
      )}
      {field(
        "lease-edit-rent",
        lt(language, "rent"),
        <input
          aria-invalid={problems.rent !== undefined}
          id="lease-edit-rent"
          inputMode="decimal"
          onChange={(event) => {
            setRent(event.currentTarget.value);
          }}
          value={rent}
        />,
        problems.rent,
      )}
      <div className="ui-field">
        <label htmlFor="lease-edit-reason">
          {lt(language, "why_change")}
          <span className="req">{lt(language, "required")}</span>
        </label>
        <textarea
          aria-invalid={problems.reason !== undefined}
          id="lease-edit-reason"
          maxLength={500}
          onChange={(event) => {
            setReason(event.currentTarget.value);
          }}
          rows={2}
          value={reason}
        />
        <Problem message={problems.reason ?? null} />
      </div>
      <OutcomeNotice language={language} outcome={outcome} />
    </Dialog>
  );
}
