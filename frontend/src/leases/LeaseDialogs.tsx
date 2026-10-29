// V1-058 R3 L2a: Sign Lease and Edit draft (DESIGN.md "Leases (round 2)"). Each request keeps
// one identity (record id and idempotency key) while its values stay the same, so "Try again"
// after an unknown result sends the very same request and the server records it once.

import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";

import {
  LeaseConflictError,
  LeaseUnavailableError,
  type LeaseApi,
  type LeaseResource,
  type OccupancyResource,
} from "../leaseClient";
import type { CustomerApi, CustomerListItem } from "../customerClient";
import { NewCustomerDialog } from "../customers/CustomerDialogs";
import type { CustomerCommandGate } from "../customers/commands";
import { outcomeOf } from "../payments/depositMoney";
import {
  type SettlementApi,
  SettlementRequestError,
} from "../settlementClient";
import { DateInput, isDay } from "../shell/DateInput";
import { dayText, todayInPhnomPenh, usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { Dialog } from "../shell/ui";
import { serverWords } from "../shell/serverText";
import type { Language } from "../signInText";
import type { UnitApi } from "../unitClient";
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
  held = null,
  signingApi,
  unitApi,
  mayLowerRent = null,
}: DialogProps & {
  /** V1-060 B6 (DL-100, DL-101): the draft's recorded Security Deposit; undefined hides the box. */
  planned?: number | null;
  /** DL-101: the Reservation's Security Deposit of a draft from a Booking. */
  held?: { required: number; received: number } | null;
  signingApi?: Pick<SettlementApi, "planSecurityDeposit">;
  /** V1-061 (DL-110): reads the Unit's default Rent; left out, only the server checks it. */
  unitApi?: Pick<UnitApi, "get">;
  /** V1-061 (DL-110): may agree a Rent below the Unit's default Rent; null when not known. */
  mayLowerRent?: boolean | null;
}) {
  // A walk-in draft may not go below the Unit's default Rent without the right (DL-110); a draft
  // from a Booking is checked by the server, which knows the Booking's agreed Rent.
  const [defaultRent, setDefaultRent] = useState<number | null>(null);
  useEffect(() => {
    if (unitApi === undefined || held !== null) return;
    const run = { live: true };
    unitApi
      .get(lease.unit_id)
      .then((unit) => {
        if (run.live)
          setDefaultRent(unit.default_monthly_rent_usd_cents ?? null);
      })
      .catch(() => {
        // Not known: the server still checks it.
      });
    return () => {
      run.live = false;
    };
  }, [unitApi, held, lease.unit_id]);
  const takesDeposit = planned !== undefined && signingApi !== undefined;
  const firstDeposit =
    planned ?? held?.required ?? lease.monthly_rent_usd_cents ?? null;
  const [deposit, setDeposit] = useState(
    firstDeposit === null ? "" : (firstDeposit / 100).toFixed(2),
  );
  // V1-060 B7: the box shows the recorded amount once it is known, unless something was typed.
  const typedDeposit = useRef(false);
  useEffect(() => {
    if (!typedDeposit.current)
      setDeposit(firstDeposit === null ? "" : (firstDeposit / 100).toFixed(2));
  }, [firstDeposit]);
  const [start, setStart] = useState(lease.start_date ?? "");
  const [end, setEnd] = useState(lease.end_date ?? "");
  const [rent, setRent] = useState(
    lease.monthly_rent_usd_cents === null
      ? ""
      : (lease.monthly_rent_usd_cents / 100).toFixed(2),
  );
  const [reason, setReason] = useState("");
  const [problems, setProblems] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>(null);
  // V1-060 B7: the dates and Rent are saved first, then the Security Deposit. When only the
  // first is saved, the dialog stays and Try again saves only the Security Deposit.
  const [depositIssue, setDepositIssue] = useState<
    { unknown: true } | { refused: string } | null
  >(null);
  const saved = useRef<{ fingerprint: string; lease: LeaseResource } | null>(
    null,
  );
  const updateIdentity = useValuesIdentity();
  const planIdentity = useValuesIdentity();

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const cents = centsOf(rent);
    const found: Record<string, string> = {};
    if (!isDay(start)) found.start = lt(language, "err_start");
    if (!isDay(end) || end <= start || !monthEnd(end))
      found.end = lt(language, "err_end");
    if (cents === null) found.rent = lt(language, "err_rent");
    else if (
      mayLowerRent === false &&
      defaultRent !== null &&
      cents !== lease.monthly_rent_usd_cents &&
      cents < defaultRent
    )
      found.rent = lt(language, "err_rent_below", usdFromCents(defaultRent));
    const depositCents = takesDeposit ? centsOf(deposit) : null;
    if (takesDeposit && depositCents === null)
      found.deposit = lt(language, "err_deposit");
    else if (
      held !== null &&
      depositCents !== null &&
      depositCents < held.received
    )
      found.deposit = lt(
        language,
        "err_deposit_below",
        usdFromCents(held.received),
      );
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
    const before = saved.current;
    const update = updateIdentity(fingerprint);
    const plan = planIdentity(
      JSON.stringify({ depositCents, reason: source.reason }),
    );
    setBusy(true);
    setOutcome(null);
    setDepositIssue(null);
    void (async () => {
      let current = before?.fingerprint === fingerprint ? before.lease : null;
      if (current === null) {
        try {
          current = await api.update(
            before?.lease ?? lease,
            { event_id: update.id, ...source },
            update.key,
          );
        } catch (error: unknown) {
          if (error instanceof LeaseConflictError) onConflict();
          // No answer, or the service was down: the request may or may not have been saved.
          else
            setOutcome(
              error instanceof LeaseUnavailableError ? "unknown" : "refused",
            );
          return;
        }
        saved.current = { fingerprint, lease: current };
      }
      if (takesDeposit && depositCents !== null && depositCents !== planned) {
        try {
          await signingApi.planSecurityDeposit(lease.lease_id, {
            plan_id: plan.id,
            required_usd_cents: depositCents,
            reason: source.reason,
          });
        } catch (error: unknown) {
          setDepositIssue(
            outcomeOf(error) === "unknown"
              ? { unknown: true }
              : {
                  refused:
                    error instanceof SettlementRequestError
                      ? serverWords(language, error)
                      : lt(language, "part_refused"),
                },
          );
          return;
        }
      }
      onSaved(current);
    })().finally(() => {
      setBusy(false);
    });
  }

  const field = (
    id: string,
    label: string,
    input: ReactNode,
    problem: string | undefined,
    help?: string,
  ) => (
    <div className="ui-field">
      <label htmlFor={id}>{label}</label>
      {input}
      {help !== undefined && <p className="help">{help}</p>}
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
          : outcome === "unknown" || depositIssue !== null
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
        defaultRent === null
          ? undefined
          : lt(language, "rent_default_help", usdFromCents(defaultRent)),
      )}
      {takesDeposit &&
        field(
          "lease-edit-deposit",
          lt(language, "deposit_box"),
          <input
            aria-invalid={problems.deposit !== undefined}
            id="lease-edit-deposit"
            inputMode="decimal"
            onChange={(event) => {
              typedDeposit.current = true;
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
      {depositIssue !== null && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>
            {"unknown" in depositIssue
              ? lt(language, "edit_part_unknown")
              : lt(language, "edit_part_saved", depositIssue.refused)}
          </p>
        </div>
      )}
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
  const named = new Map(
    lease.planned_occupants.map((person) => [
      person.customer_id,
      person.customer_name,
    ]),
  );
  const planned = lease.planned_occupant_customer_ids
    .filter((id) => !known.has(id))
    .map((id) => ({ customerId: id, name: named.get(id) ?? null }));
  return [...signers, ...planned];
}

/** The active Customers of the Property by name (at most 50 pages). */
async function activeCustomers(
  customerApi: Pick<CustomerApi, "list">,
  propertyId: string,
): Promise<CustomerListItem[]> {
  const found: CustomerListItem[] = [];
  let cursor: string | undefined;
  for (let page = 0; page < 50; page += 1) {
    const result = await customerApi.list(
      propertyId,
      cursor === undefined ? { active: true } : { active: true, cursor },
    );
    found.push(...result.items);
    if (result.next_cursor === null) break;
    cursor = result.next_cursor;
  }
  return found.sort((left, right) =>
    left.legal_name.localeCompare(right.legal_name),
  );
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
    void activeCustomers(customerApi, lease.property_id)
      .then((found) => {
        if (alive.current) setOthers(found);
      })
      .catch(() => undefined);
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
    if (!isDay(day) || day < first || day > last)
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

// The reason stored with an added occupant when no note is written names the person.
function occupantReason(name: string, day: string | null): string {
  return day === null
    ? `${name} moves in with the Lease`
    : `${name} moved in on ${dayText(day)}`;
}

/**
 * V1-060 B6 (DL-102): Add occupant on a draft or a running Lease (DESIGN.md 0.15). Before the
 * move-in the person is planned and moves in with the Lease; after it the person gets their
 * own move-in date, from the Lease's move-in to today, never after the End Date (BR-OCC-004).
 */
export function AddOccupantDialog({
  language,
  api,
  lease,
  customerApi,
  newCustomer,
  onClose,
  onSaved,
  onConflict,
}: Omit<DialogProps, "onSaved"> & {
  customerApi: Pick<CustomerApi, "list">;
  /** The New Customer form; null when the person may not add Customers. */
  newCustomer: { api: CustomerApi; gate: CustomerCommandGate } | null;
  onSaved: (saved: LeaseResource, message: string) => void;
}) {
  const today = todayInPhnomPenh();
  // The Lease's move-in: its earliest Occupancy; null while nobody has moved in.
  const first =
    lease.occupancies
      .map((occupancy) => occupancy.move_in_date)
      .sort()
      .at(0) ?? null;
  const last =
    lease.end_date !== null && lease.end_date < today ? lease.end_date : today;
  // Already on the Lease: the Primary Tenant, whoever lives there now and the planned people.
  const taken = new Set([
    lease.primary_tenant_id,
    ...lease.occupancies
      .filter((occupancy) => occupancy.move_out_date === null)
      .map((occupancy) => occupancy.customer_id),
    ...(first === null ? lease.planned_occupant_customer_ids : []),
  ]);
  const [customers, setCustomers] = useState<CustomerListItem[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [pick, setPick] = useState("");
  const [adding, setAdding] = useState(false);
  const [day, setDay] = useState(
    first === null || today < first ? (first ?? "") : last,
  );
  const [note, setNote] = useState("");
  const [problems, setProblems] = useState<Record<string, string>>({});
  // One Occupancy id per person for the life of the dialog, so a retry sends the same id.
  const occupancyIds = useRef(new Map<string, string>());
  const message = useRef("");
  const identity = useValuesIdentity();
  const { busy, outcome, send } = useSend((saved) => {
    onSaved(saved, message.current);
  }, onConflict);

  useEffect(() => {
    const alive = { current: true };
    void activeCustomers(customerApi, lease.property_id)
      .then((found) => {
        if (alive.current) setCustomers(found);
      })
      .catch(() => {
        if (alive.current) setFailed(true);
      });
    return () => {
      alive.current = false;
    };
  }, []);

  const choices = (customers ?? []).filter(
    (customer) => !taken.has(customer.customer_id),
  );

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const found: Record<string, string> = {};
    const person = choices.find((customer) => customer.customer_id === pick);
    if (person === undefined) found.name = lt(language, "ao_name_req");
    if (first !== null && (!isDay(day) || day < first || day > last))
      found.day = lt(language, "ao_date_err", dayText(first), dayText(last));
    setProblems(found);
    if (person === undefined || Object.keys(found).length > 0) return;
    const moveInDate = first === null ? null : day;
    let occupancyId: string | null = null;
    if (moveInDate !== null) {
      occupancyId = occupancyIds.current.get(pick) ?? crypto.randomUUID();
      occupancyIds.current.set(pick, occupancyId);
    }
    const reason =
      note.trim() === ""
        ? occupantReason(person.legal_name, moveInDate)
        : note.trim();
    message.current = lt(
      language,
      "ao_saved",
      person.legal_name,
      lease.unit_number,
    );
    const step = identity(JSON.stringify([pick, moveInDate, reason]));
    send(() =>
      api.addOccupant(
        lease,
        {
          event_id: step.id,
          customer_id: pick,
          occupancy_id: occupancyId,
          move_in_date: moveInDate,
          reason,
        },
        step.key,
      ),
    );
  }

  // The New Customer form takes the place of this dialog until it is saved or closed.
  if (adding && newCustomer !== null)
    return (
      <NewCustomerDialog
        api={newCustomer.api}
        gate={newCustomer.gate}
        language={language}
        onClose={() => {
          setAdding(false);
        }}
        onSaved={(customer) => {
          setCustomers((before) =>
            [
              ...(before ?? []).filter(
                (item) => item.customer_id !== customer.customer_id,
              ),
              {
                customer_id: customer.customer_id,
                legal_name: customer.legal_name,
                phone_number: customer.phone_number,
                active: true,
                relationship_indicators: [],
              },
            ].sort((left, right) =>
              left.legal_name.localeCompare(right.legal_name),
            ),
          );
          setPick(customer.customer_id);
          setAdding(false);
        }}
        propertyId={lease.property_id}
      />
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
      title={lt(language, "ao_title", lease.unit_number)}
    >
      <div className="ui-field">
        <label htmlFor="lease-occupant-name">
          {lt(language, "ao_name")}
          <span className="req">{lt(language, "required")}</span>
        </label>
        <div className="ui-pickrow">
          <select
            aria-invalid={problems.name !== undefined}
            disabled={busy || customers === null}
            id="lease-occupant-name"
            onChange={(event) => {
              setPick(event.currentTarget.value);
            }}
            value={pick}
          >
            <option value="">
              {customers === null && !failed
                ? lt(language, "ao_loading")
                : lt(language, "choose_customer")}
            </option>
            {choices.map((customer) => (
              <option key={customer.customer_id} value={customer.customer_id}>
                {customer.legal_name}
                {customer.phone_number ? ` · ${customer.phone_number}` : ""}
              </option>
            ))}
          </select>
          {newCustomer !== null && (
            <button
              aria-label={lt(language, "new_customer")}
              className="ui-btn ui-iconbtn"
              disabled={busy}
              onClick={() => {
                setAdding(true);
              }}
              title={lt(language, "new_customer")}
              type="button"
            >
              <Icon name="userplus" />
            </button>
          )}
        </div>
        <p className="ui-small ui-muted">{lt(language, "ao_name_help")}</p>
        {failed ? (
          <Problem message={lt(language, "ao_failed")} />
        ) : (
          customers !== null &&
          choices.length === 0 && (
            <p className="ui-small ui-muted">{lt(language, "ao_none")}</p>
          )
        )}
        <Problem message={problems.name ?? null} />
      </div>
      {first === null ? (
        <p className="ui-small ui-muted">{lt(language, "ao_pending_note")}</p>
      ) : (
        <div className="ui-field">
          <label htmlFor="lease-occupant-day">
            {lt(language, "ao_date")}
            <span className="req">{lt(language, "required")}</span>
          </label>
          <DateInput
            language={language}
            invalid={problems.day !== undefined}
            id="lease-occupant-day"
            max={last}
            min={first}
            onChange={(value) => {
              setDay(value);
            }}
            value={day}
          />
          <p className="ui-small ui-muted">
            {lt(language, "ao_date_help", dayText(first), dayText(last))}
          </p>
          <Problem message={problems.day ?? null} />
        </div>
      )}
      <div className="ui-field">
        <label htmlFor="lease-occupant-note">{lt(language, "note")}</label>
        <textarea
          id="lease-occupant-note"
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

/** The Signers who still live in the Unit under this Lease. */
export function livingSigners(lease: LeaseResource): string[] {
  const signers = new Set(lease.signers.map((signer) => signer.customer_id));
  return lease.occupancies
    .filter(
      (occupancy) =>
        occupancy.move_out_date === null && signers.has(occupancy.customer_id),
    )
    .map((occupancy) => occupancy.customer_id);
}

/**
 * V1-061 (owner 2026-10-29, DL-111): Move out one person on their own day. Never the Primary
 * Tenant (the Lease page shows no button for them). A Joint Signer needs every other Signer
 * to agree, and stays a Signer of the Lease; the last Signer living there gets no button.
 */
export function MoveOutOccupantDialog({
  language,
  api,
  lease,
  occupancy,
  onClose,
  onSaved,
  onConflict,
}: Omit<DialogProps, "onSaved"> & {
  occupancy: OccupancyResource;
  onSaved: (saved: LeaseResource, message: string) => void;
}) {
  const today = todayInPhnomPenh();
  const last =
    lease.end_date !== null && lease.end_date < today ? lease.end_date : today;
  const signer = lease.signers.some(
    (value) => value.customer_id === occupancy.customer_id,
  );
  const others = signer
    ? lease.signers.filter(
        (value) => value.customer_id !== occupancy.customer_id,
      )
    : [];
  const [day, setDay] = useState(last);
  const [agreed, setAgreed] = useState<Set<string>>(new Set());
  const [note, setNote] = useState("");
  const [problems, setProblems] = useState<Record<string, string>>({});
  const identity = useValuesIdentity();
  const message = lt(language, "mo_saved", occupancy.customer_name);
  const { busy, outcome, send } = useSend((saved) => {
    onSaved(saved, message);
  }, onConflict);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const found: Record<string, string> = {};
    if (!isDay(day) || day < occupancy.move_in_date || day > last)
      found.day = lt(
        language,
        "mo_date_err",
        dayText(occupancy.move_in_date),
        dayText(last),
      );
    if (others.some((value) => !agreed.has(value.customer_id)))
      found.agree = lt(language, "mo_err_agree");
    setProblems(found);
    if (Object.keys(found).length > 0) return;
    const reason =
      note.trim() === ""
        ? `${occupancy.customer_name} moved out on ${dayText(day)}`
        : note.trim();
    const ids = others.map((value) => value.customer_id).sort();
    const step = identity(JSON.stringify([day, ids, reason]));
    send(() =>
      api.moveOutOccupant(
        lease,
        occupancy.occupancy_id,
        {
          event_id: step.id,
          move_out_date: day,
          agreed_signer_customer_ids: ids,
          reason,
        },
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
            : lt(language, "mo_button")
      }
      title={lt(language, "mo_title", occupancy.customer_name)}
    >
      <div className="ui-field">
        <label htmlFor="lease-moveout-day">
          {lt(language, "mo_date")}
          <span className="req">{lt(language, "required")}</span>
        </label>
        <DateInput
          language={language}
          invalid={problems.day !== undefined}
          id="lease-moveout-day"
          max={last}
          min={occupancy.move_in_date}
          onChange={(value) => {
            setDay(value);
          }}
          value={day}
        />
        <Problem message={problems.day ?? null} />
      </div>
      {signer && (
        <fieldset className="ui-radios">
          <legend>{lt(language, "mo_agree_title")}</legend>
          {others.map((value) => (
            <label className="ui-chk" key={value.customer_id}>
              <input
                checked={agreed.has(value.customer_id)}
                disabled={busy}
                onChange={(event) => {
                  const next = new Set(agreed);
                  if (event.currentTarget.checked) next.add(value.customer_id);
                  else next.delete(value.customer_id);
                  setAgreed(next);
                }}
                type="checkbox"
              />
              <span>{lt(language, "mo_agrees", value.customer_name)}</span>
            </label>
          ))}
          <Problem message={problems.agree ?? null} />
        </fieldset>
      )}
      <p className="ui-small ui-muted">
        {signer
          ? lt(language, "mo_signer_note", occupancy.customer_name)
          : lt(language, "mo_note", occupancy.customer_name)}
      </p>
      <div className="ui-field">
        <label htmlFor="lease-moveout-note">{lt(language, "note")}</label>
        <textarea
          id="lease-moveout-note"
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
