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
import type { CustomerApi, CustomerListItem } from "../customerClient";
import type { SettlementApi } from "../settlementClient";
import { DateInput } from "../shell/DateInput";
import { dayText, todayInPhnomPenh } from "../shell/format";
import { Icon } from "../shell/icons";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import { lt, type LeaseTextKey } from "./text";

export type Outcome = "unknown" | "refused" | null;

// The reason stored with a move-in when no note is written.
const MOVE_IN_REASON = "Move-in recorded";

export function Problem({ message }: { message: string | null }) {
  if (message === null) return null;
  return (
    <p className="ui-error" role="alert">
      <Icon name="alert" small />
      <span>{message}</span>
    </p>
  );
}

export function OutcomeNotice({
  language,
  outcome,
  refused = "refused",
}: {
  language: Language;
  outcome: Outcome;
  refused?: LeaseTextKey;
}) {
  if (outcome === null) return null;
  return (
    <div className="ui-notice warn" role="alert">
      <Icon name="alert" />
      <p>{lt(language, outcome === "refused" ? refused : outcome)}</p>
    </div>
  );
}

/** Sends a request and sorts its ending: saved, changed meanwhile, unknown, refused. */
export function useSend(
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

export interface Identity {
  key: string;
  id: string;
}

/** One identity per step name, kept for the life of the dialog. */
export function useIdentities() {
  const map = useRef(new Map<string, Identity>());
  return (step: string): Identity => {
    const known = map.current.get(step);
    if (known !== undefined) return known;
    const made = { key: crypto.randomUUID(), id: crypto.randomUUID() };
    map.current.set(step, made);
    return made;
  };
}

export interface DialogProps {
  language: Language;
  api: LeaseApi;
  lease: LeaseResource;
  onClose: () => void;
  onSaved: (saved: LeaseResource) => void;
  onConflict: () => void;
}

/** "500.00" or "500" as cents; null when it is not a whole-cent amount above zero. */
export function centsOf(text: string): number | null {
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
  planned,
  signingApi,
}: DialogProps & {
  /** V1-060 B6 (DL-100): a walk-in draft's planned Security Deposit; undefined hides the box. */
  planned?: number | null;
  signingApi?: Pick<SettlementApi, "planSecurityDeposit">;
}) {
  const walkIn = planned !== undefined && signingApi !== undefined;
  const [deposit, setDeposit] = useState(
    planned === undefined || planned === null
      ? lease.monthly_rent_usd_cents === null
        ? ""
        : (lease.monthly_rent_usd_cents / 100).toFixed(2)
      : (planned / 100).toFixed(2),
  );
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
    const depositCents = walkIn ? centsOf(deposit) : null;
    if (walkIn && depositCents === null)
      found.deposit = lt(language, "err_deposit");
    if (reason.trim() === "") found.reason = lt(language, "err_reason");
    setProblems(found);
    if (cents === null || Object.keys(found).length > 0) return;
    const source = {
      start_date: start,
      end_date: end,
      monthly_rent_usd_cents: cents,
      reason: reason.trim(),
    };
    const fingerprint = JSON.stringify({ ...source, depositCents });
    if (identity.current?.fingerprint !== fingerprint)
      identity.current = {
        fingerprint,
        key: crypto.randomUUID(),
        id: crypto.randomUUID(),
      };
    const chosen = identity.current;
    send(async () => {
      const saved = await api.update(
        lease,
        { event_id: chosen.id, ...source },
        chosen.key,
      );
      if (walkIn && depositCents !== null && depositCents !== planned)
        await signingApi.planSecurityDeposit(lease.lease_id, {
          plan_id: chosen.id,
          required_usd_cents: depositCents,
          reason: source.reason,
        });
      return saved;
    });
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
        <DateInput
          language={language}
          invalid={problems.start !== undefined}
          id="lease-edit-start"
          onChange={(value) => {
            setStart(value);
          }}
          value={start}
        />,
        problems.start,
      )}
      {field(
        "lease-edit-end",
        lt(language, "end"),
        <DateInput
          language={language}
          invalid={problems.end !== undefined}
          id="lease-edit-end"
          onChange={(value) => {
            setEnd(value);
          }}
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
      {walkIn &&
        field(
          "lease-edit-deposit",
          lt(language, "deposit_box"),
          <input
            aria-invalid={problems.deposit !== undefined}
            id="lease-edit-deposit"
            inputMode="decimal"
            onChange={(event) => {
              setDeposit(event.currentTarget.value);
            }}
            value={deposit}
          />,
          problems.deposit,
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

/** One identity per set of values: the same values keep it, so Try again sends the same request. */
export function useValuesIdentity() {
  const kept = useRef<({ fingerprint: string } & Identity) | null>(null);
  return (fingerprint: string): Identity => {
    if (kept.current?.fingerprint !== fingerprint)
      kept.current = {
        fingerprint,
        key: crypto.randomUUID(),
        id: crypto.randomUUID(),
      };
    return kept.current;
  };
}

export function CancelDraftDialog({
  language,
  api,
  lease,
  onClose,
  onSaved,
  onConflict,
}: DialogProps) {
  const [memo, setMemo] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const identity = useValuesIdentity();
  const { busy, outcome, send } = useSend(onSaved, onConflict);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const reason = memo.trim();
    setProblem(reason === "" ? lt(language, "err_memo") : null);
    if (reason === "") return;
    const chosen = identity(reason);
    send(() => api.cancel(lease, { event_id: chosen.id, reason }, chosen.key));
  }

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
            : lt(language, "cancel_ok")
      }
      title={lt(language, "cancel_title", lease.unit_number)}
    >
      <p className="ui-small">{lt(language, "cancel_note")}</p>
      <div className="ui-field">
        <label htmlFor="lease-cancel-memo">
          {lt(language, "memo")}
          <span className="req">{lt(language, "required")}</span>
        </label>
        <textarea
          aria-invalid={problem !== null}
          id="lease-cancel-memo"
          maxLength={500}
          onChange={(event) => {
            setMemo(event.currentTarget.value);
          }}
          rows={2}
          value={memo}
        />
        <Problem message={problem} />
      </div>
      <OutcomeNotice language={language} outcome={outcome} />
    </Dialog>
  );
}

interface Person {
  customerId: string;
  name: string | null;
}

/** The people who may move in: the Signers, then the planned occupants who did not sign. */
function peopleOf(lease: LeaseResource): Person[] {
  const signers = lease.signers.map((signer) => ({
    customerId: signer.customer_id,
    name: signer.customer_name,
  }));
  const known = new Set(signers.map((person) => person.customerId));
  const planned = lease.planned_occupant_customer_ids
    .filter((id) => !known.has(id))
    .map((id) => ({ customerId: id, name: null }));
  return [...signers, ...planned];
}

export function MoveInDialog({
  language,
  api,
  lease,
  customerApi,
  onClose,
  onSaved,
  onConflict,
}: DialogProps & {
  /** Names of planned occupants who did not sign; null when the person may not read Customers. */
  customerApi: Pick<CustomerApi, "get" | "list"> | null;
}) {
  const today = todayInPhnomPenh();
  const start = lease.start_date ?? today;
  const signedDay =
    lease.signed_at === null
      ? start
      : todayInPhnomPenh(new Date(lease.signed_at));
  const first = signedDay > start ? signedDay : start;
  const last =
    lease.end_date !== null && lease.end_date < today ? lease.end_date : today;
  const [extra, setExtra] = useState<Person[]>([]);
  const [pick, setPick] = useState("");
  const [others, setOthers] = useState<CustomerListItem[]>([]);
  const people = [...peopleOf(lease), ...extra];
  const planned = new Set(lease.planned_occupant_customer_ids);
  const [day, setDay] = useState(
    today < first ? first : today > last ? last : today,
  );
  const [chosen, setChosen] = useState<ReadonlySet<string>>(
    () =>
      new Set(
        planned.size > 0
          ? people
              .filter((person) => planned.has(person.customerId))
              .map((person) => person.customerId)
          : [lease.primary_tenant_id],
      ),
  );
  const [names, setNames] = useState<ReadonlyMap<string, string>>(new Map());
  const [note, setNote] = useState("");
  const [problems, setProblems] = useState<Record<string, string>>({});
  // One Occupancy id per person for the life of the dialog, so a retry sends the same ids.
  const occupancyIds = useRef(new Map<string, string>());
  const identity = useValuesIdentity();
  const { busy, outcome, send } = useSend(onSaved, onConflict);

  useEffect(() => {
    if (customerApi === null) return;
    const alive = { current: true };
    for (const person of people) {
      if (person.name !== null) continue;
      void customerApi
        .get(person.customerId)
        .then((customer) => {
          if (alive.current)
            setNames((before) =>
              new Map(before).set(person.customerId, customer.legal_name),
            );
        })
        .catch(() => undefined);
    }
    // Other active Customers, so someone not named in the Lease can move in too.
    void (async () => {
      const found: CustomerListItem[] = [];
      let cursor: string | undefined;
      for (let page = 0; page < 50; page += 1) {
        const result = await customerApi.list(
          lease.property_id,
          cursor === undefined ? { active: true } : { active: true, cursor },
        );
        found.push(...result.items);
        if (result.next_cursor === null) break;
        cursor = result.next_cursor;
      }
      if (alive.current)
        setOthers(
          found.sort((left, right) =>
            left.legal_name.localeCompare(right.legal_name),
          ),
        );
    })().catch(() => undefined);
    return () => {
      alive.current = false;
    };
  }, []);

  const addable = others.filter(
    (customer) =>
      !people.some((person) => person.customerId === customer.customer_id),
  );

  function occupancyOf(customerId: string): string {
    const known = occupancyIds.current.get(customerId);
    if (known !== undefined) return known;
    const made = crypto.randomUUID();
    occupancyIds.current.set(customerId, made);
    return made;
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const found: Record<string, string> = {};
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || day < first || day > last)
      found.day =
        first > last
          ? lt(language, "err_movein_early", dayText(first))
          : lt(language, "err_movein_day", dayText(first), dayText(last));
    if (chosen.size === 0) found.who = lt(language, "err_who");
    setProblems(found);
    if (Object.keys(found).length > 0) return;
    const occupants = people
      .filter((person) => chosen.has(person.customerId))
      .map((person) => ({
        occupancy_id: occupancyOf(person.customerId),
        customer_id: person.customerId,
      }));
    const reason = note.trim() === "" ? MOVE_IN_REASON : note.trim();
    const step = identity(JSON.stringify([day, occupants, reason]));
    send(() =>
      api.recordMoveIn(
        lease,
        { event_id: step.id, actual_move_in_date: day, occupants, reason },
        step.key,
      ),
    );
  }

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
            : lt(language, "movein_ok")
      }
      title={lt(language, "movein_title", lease.unit_number)}
    >
      <div className="ui-field">
        <label htmlFor="lease-movein-day">{lt(language, "movein_day")}</label>
        <DateInput
          language={language}
          invalid={problems.day !== undefined}
          id="lease-movein-day"
          max={last}
          min={first}
          onChange={(value) => {
            setDay(value);
          }}
          value={day}
        />
        <Problem message={problems.day ?? null} />
      </div>
      <fieldset className="ui-radios">
        <legend>{lt(language, "movein_who")}</legend>
        {people.map((person) => {
          const name =
            person.name ??
            names.get(person.customerId) ??
            lt(language, "occupant_unnamed");
          return (
            <label className="ui-chk" key={person.customerId}>
              <input
                checked={chosen.has(person.customerId)}
                disabled={busy}
                onChange={(event) => {
                  const next = new Set(chosen);
                  if (event.currentTarget.checked) next.add(person.customerId);
                  else next.delete(person.customerId);
                  setChosen(next);
                }}
                type="checkbox"
              />
              <span>
                {name}
                {person.customerId === lease.primary_tenant_id &&
                  ` · ${lt(language, "primary_tag")}`}
                {planned.has(person.customerId) &&
                  person.customerId !== lease.primary_tenant_id &&
                  ` · ${lt(language, "planned_tag")}`}
              </span>
            </label>
          );
        })}
        <Problem message={problems.who ?? null} />
      </fieldset>
      {people.length < 20 && addable.length > 0 ? (
        <div className="ui-field">
          <label htmlFor="lease-movein-add">{lt(language, "movein_add")}</label>
          <div className="ui-addrow">
            <select
              disabled={busy}
              id="lease-movein-add"
              onChange={(event) => {
                setPick(event.currentTarget.value);
              }}
              value={pick}
            >
              <option value="">{lt(language, "add_person")}</option>
              {addable.map((customer) => (
                <option key={customer.customer_id} value={customer.customer_id}>
                  {customer.legal_name}
                  {customer.phone_number ? ` · ${customer.phone_number}` : ""}
                </option>
              ))}
            </select>
            {/* A separate button: arrow keys on a closed select fire change. */}
            <button
              className="ui-btn"
              disabled={busy || pick === ""}
              onClick={() => {
                const customer = addable.find(
                  (item) => item.customer_id === pick,
                );
                if (customer === undefined) return;
                setExtra([
                  ...extra,
                  { customerId: pick, name: customer.legal_name },
                ]);
                setChosen(new Set([...chosen, pick]));
                setPick("");
              }}
              type="button"
            >
              {lt(language, "add_button")}
            </button>
          </div>
        </div>
      ) : (
        customerApi === null && (
          <p className="ui-small ui-muted">{lt(language, "movein_others")}</p>
        )
      )}
      <div className="ui-field">
        <label htmlFor="lease-movein-note">{lt(language, "note")}</label>
        <textarea
          id="lease-movein-note"
          maxLength={500}
          onChange={(event) => {
            setNote(event.currentTarget.value);
          }}
          rows={2}
          value={note}
        />
      </div>
      <OutcomeNotice language={language} outcome={outcome} />
    </Dialog>
  );
}
