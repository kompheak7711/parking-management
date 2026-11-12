// Daily and weekly rent, phase 6 step 3: the steps of a stay on the booking page (migration
// 20270602_312). Payment (the booking's Invoice, paid on Receive payment, or paid on the booking
// site), the deposit (cash or a card hold, never a card number), check-in, check-out, the room
// check with any damage, the decision on damage and the end of the deposit. DL-222 (migration
// 20270716_391): the room check reports problems as Problem reports, and the person who bills
// damage chooses Charge the guest or No charge on the booking, with no approval. Each button
// shows only to a person who holds its right; the server checks every step again. Step 4a adds the
// early check-in and late check-out fee, extending the stay and the fee and extension Invoices.

import { type FormEvent, useEffect, useState } from "react";

import { DateInput } from "../shell/DateInput";

import { dayText, momentText, usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { Chip, type Tone } from "../shell/ui";
import type { ProblemType } from "../problems/problemsClient";
import type { Language } from "../signInText";
import {
  addDays,
  type Booking,
  type PaymentState,
  type StayStep,
} from "./shortStaysClient";
import { hasText, st, type StaysTextKey } from "./text";

export interface StepsProps {
  language: Language;
  booking: Booking;
  today: string;
  may: (capability: string) => boolean;
  busy: boolean;
  /** Runs one step; the page shows the booking the server answers with. */
  onStep: (step: StayStep, body: Record<string, unknown> | null) => void;
  onDecide: (damageId: string, approve: boolean, note: string) => void;
  /** The whole stay's new total for another check-out day (fees kept); null when it fails. */
  onPrice: (checkOut: string) => Promise<number | null>;
  /** DL-222: the problem types the room check offers; empty until read or without the right. */
  problemTypes: ProblemType[];
}

/** Minutes after midnight as "14:00". */
export function timeText(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  return `${String(hours).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
}

const PAY_TONES: Record<PaymentState, Tone> = {
  NOT_BILLED: "warn",
  UNPAID: "warn",
  PARTIALLY_PAID: "warn",
  PAID: "ok",
  PAID_ON_SITE: "ok",
};

function isPaid(booking: Booking): boolean {
  return booking.payment === "PAID" || booking.payment === "PAID_ON_SITE";
}

/** "80" or "80.50" dollars as cents; null when it is not a money amount. */
export function centsOf(text: string): number | null {
  const match = /^(\d{1,7})(?:\.(\d{1,2}))?$/.exec(text.trim());
  if (match === null) return null;
  const cents =
    Number(match[1]) * 100 + Number((match[2] ?? "").padEnd(2, "0"));
  return cents > 0 ? cents : null;
}

function Done({ ok, text }: { ok: boolean; text: string }) {
  return (
    <li className={ok ? "ss-ok" : "ss-todo"}>
      <Icon name={ok ? "check" : "x"} small />
      <span>{text}</span>
    </li>
  );
}

export function PaymentCard({
  language,
  booking,
  may,
  busy,
  onStep,
}: StepsProps) {
  const open = booking.status === "BOOKED" && booking.payment === "NOT_BILLED";
  return (
    <section aria-labelledby="ss-pay" className="ui-card">
      <div className="ui-hrow">
        <h2 id="ss-pay">{st(language, "pay_t")}</h2>
        <Chip tone={PAY_TONES[booking.payment]}>
          {st(language, `pay_${booking.payment}`)}
        </Chip>
      </div>
      {booking.invoice !== null && booking.payment !== "NOT_BILLED" && (
        <p>
          <a
            className="ui-num"
            href={hashForPage("invoices", `inv:${booking.invoice.invoice_id}`)}
          >
            {st(language, "open_inv", booking.invoice.invoice_number)}
          </a>{" "}
          ·{" "}
          <span className="ui-num">
            {st(
              language,
              "pay_due",
              usdFromCents(booking.invoice.due_usd_cents),
            )}
          </span>
        </p>
      )}
      {booking.extra_invoices.length > 0 && (
        <ul className="ui-plain ss-ready">
          {booking.extra_invoices.map((extra) => (
            <li key={extra.invoice_id}>
              <a href={hashForPage("invoices", `inv:${extra.invoice_id}`)}>
                {st(
                  language,
                  "pay_extra",
                  st(language, `x_${extra.kind}`),
                  extra.invoice_number,
                )}
              </a>
              <span className="ui-num">
                {usdFromCents(extra.total_usd_cents)}
              </span>
              <Chip tone={extra.status === "PAID" ? "ok" : "warn"}>
                {hasText(`inv_${extra.status}`)
                  ? st(language, `inv_${extra.status}` as StaysTextKey)
                  : extra.status}
              </Chip>
            </li>
          ))}
        </ul>
      )}
      {open && <p className="ui-small ui-muted">{st(language, "bill_s")}</p>}
      <div className="ui-actions">
        {open && may("short_stays.desk") && (
          <button
            className="ui-btn primary"
            disabled={busy}
            onClick={() => {
              onStep("bill", { version: booking.version });
            }}
            type="button"
          >
            <Icon name="invoice" small />
            {st(language, "bill")}
          </button>
        )}
        {open &&
          booking.source === "BOOKING_SITE" &&
          may("short_stays.desk") && (
            <button
              className="ui-btn"
              disabled={busy}
              onClick={() => {
                onStep("paid-on-site", { version: booking.version });
              }}
              title={st(language, "on_site_s", booking.site_name ?? "")}
              type="button"
            >
              {st(language, "on_site")}
            </button>
          )}
        {(booking.payment === "UNPAID" ||
          booking.payment === "PARTIALLY_PAID") &&
          may("payments.record") && (
            <a
              className="ui-btn primary"
              href={hashForPage("payments", `receive:${booking.customer_id}`)}
            >
              <Icon name="payments" small />
              {st(language, "receive")}
            </a>
          )}
      </div>
    </section>
  );
}

export function DepositCard({
  language,
  booking,
  may,
  busy,
  onStep,
}: StepsProps) {
  const [kind, setKind] = useState<"CASH" | "CARD_HOLD">("CASH");
  const [reference, setReference] = useState("");
  const [last4, setLast4] = useState("");
  const deposit = booking.deposit;
  const mayTake =
    deposit === null &&
    (booking.status === "BOOKED" || booking.status === "CHECKED_IN") &&
    may("short_stays.desk");
  const kept = booking.damages
    .filter((damage) => damage.status === "APPROVED")
    .reduce((sum, damage) => sum + damage.from_deposit_usd_cents, 0);
  const endReady =
    deposit?.status === "HELD" &&
    booking.status === "CHECKED_OUT" &&
    booking.room_check?.status === "DONE" &&
    !booking.damage_due &&
    !booking.damages.some((damage) => damage.status === "WAITING");
  const mayEnd = endReady && may("short_stays.desk");
  const referenceOk = kind === "CASH" || reference.trim() !== "";
  const last4Ok = kind === "CASH" || last4 === "" || /^\d{4}$/.test(last4);
  const take = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!referenceOk || !last4Ok) return;
    onStep("deposit", {
      kind,
      ...(kind === "CARD_HOLD" ? { hold_reference: reference.trim() } : {}),
      ...(kind === "CARD_HOLD" && last4 !== "" ? { card_last4: last4 } : {}),
    });
  };
  return (
    <section aria-labelledby="ss-dep" className="ui-card">
      <h2 id="ss-dep">{st(language, "dep_t")}</h2>
      {deposit === null ? (
        <p className="ui-muted">{st(language, "dep_none")}</p>
      ) : (
        <p>
          {st(language, `dep_${deposit.kind}`)} ·{" "}
          <b className="ui-num">{usdFromCents(deposit.amount_usd_cents)}</b> ·{" "}
          {deposit.status === "KEPT"
            ? st(language, "dep_KEPT", usdFromCents(deposit.kept_usd_cents))
            : st(language, `dep_${deposit.status}`)}
          {deposit.hold_reference !== null && (
            <span className="ui-sub2 ui-num">
              {deposit.hold_reference}
              {deposit.card_last4 !== null && ` · •••• ${deposit.card_last4}`}
            </span>
          )}
        </p>
      )}
      {mayTake && (
        <form className="ui-form ss-form" noValidate onSubmit={take}>
          <fieldset className="ui-radios">
            <legend className="ui-sr">{st(language, "dep_t")}</legend>
            {(["CASH", "CARD_HOLD"] as const).map((value) => (
              <label className="ui-chk" key={value}>
                <input
                  checked={kind === value}
                  disabled={busy}
                  name="ss-dep-kind"
                  onChange={() => {
                    setKind(value);
                  }}
                  type="radio"
                />
                {st(language, `dep_${value}`)}
              </label>
            ))}
          </fieldset>
          {kind === "CARD_HOLD" && (
            <div className="ui-row2">
              <div className="ui-field">
                <label htmlFor="ss-dep-ref">
                  {st(language, "dep_ref")}
                  <span className="req">{st(language, "required")}</span>
                </label>
                <input
                  aria-describedby="ss-dep-never"
                  autoComplete="off"
                  disabled={busy}
                  id="ss-dep-ref"
                  maxLength={60}
                  onChange={(event) => {
                    setReference(event.currentTarget.value);
                  }}
                  value={reference}
                />
                <p className="ui-small ui-muted" id="ss-dep-never">
                  {st(language, "dep_never")}
                </p>
              </div>
              <div className="ui-field">
                <label htmlFor="ss-dep-last4">
                  {st(language, "dep_last4")}
                </label>
                <input
                  aria-invalid={!last4Ok}
                  autoComplete="off"
                  disabled={busy}
                  id="ss-dep-last4"
                  inputMode="numeric"
                  maxLength={4}
                  onChange={(event) => {
                    setLast4(event.currentTarget.value);
                  }}
                  value={last4}
                />
              </div>
            </div>
          )}
          <div className="ui-actions">
            <button
              className="ui-btn primary"
              disabled={busy || !referenceOk || !last4Ok}
              type="submit"
            >
              {st(language, "dep_take")}
            </button>
          </div>
        </form>
      )}
      {deposit?.status === "HELD" &&
        booking.status === "CHECKED_OUT" &&
        !endReady && (
          <p className="ui-small ui-muted">{st(language, "dep_wait")}</p>
        )}
      {mayEnd && (
        <div className="ui-actions">
          <button
            className="ui-btn primary"
            disabled={busy}
            onClick={() => {
              onStep("deposit/end", null);
            }}
            type="button"
          >
            {kept > 0
              ? st(
                  language,
                  "dep_end_keep",
                  usdFromCents(kept),
                  usdFromCents(deposit.amount_usd_cents - kept),
                )
              : st(language, "dep_end")}
          </button>
        </div>
      )}
    </section>
  );
}

export function CheckInCard({
  language,
  booking,
  today,
  may,
  busy,
  onStep,
}: StepsProps) {
  const [copy, setCopy] = useState(false);
  const [rules, setRules] = useState(false);
  if (booking.status !== "BOOKED") return null;
  const day = today >= booking.check_in_on && today < booking.check_out_on;
  const ready = {
    paid: isPaid(booking),
    deposit: booking.deposit?.status === "HELD",
    id: booking.guest_has_id,
    day,
    room: booking.unit_status === "VACANT",
  };
  const all = Object.values(ready).every(Boolean) && copy && rules;
  return (
    <section aria-labelledby="ss-in" className="ui-card">
      <h2 id="ss-in">{st(language, "in_t")}</h2>
      <ul className="ui-plain ss-ready">
        <Done ok={ready.paid} text={st(language, "in_paid")} />
        <Done ok={ready.deposit} text={st(language, "in_deposit")} />
        <Done ok={ready.id} text={st(language, "in_id")} />
        <Done
          ok={ready.day}
          text={st(language, "in_day", dayText(booking.check_in_on))}
        />
        <Done ok={ready.room} text={st(language, "in_room")} />
      </ul>
      {may("short_stays.desk") && (
        <>
          <label className="ui-chk">
            <input
              checked={copy}
              disabled={busy}
              onChange={(event) => {
                setCopy(event.currentTarget.checked);
              }}
              type="checkbox"
            />
            {st(language, "in_copy")}
          </label>
          <label className="ui-chk">
            <input
              checked={rules}
              disabled={busy}
              onChange={(event) => {
                setRules(event.currentTarget.checked);
              }}
              type="checkbox"
            />
            {st(language, "in_rules")}
          </label>
          <div className="ui-actions">
            <button
              className="ui-btn primary"
              disabled={busy || !all}
              onClick={() => {
                onStep("check-in", {
                  version: booking.version,
                  id_copy_made: true,
                  house_rules_signed: true,
                });
              }}
              type="button"
            >
              <Icon name="door" small />
              {st(language, "in_b")}
            </button>
          </div>
        </>
      )}
    </section>
  );
}

export function CheckOutCard({
  language,
  booking,
  may,
  busy,
  onStep,
}: StepsProps) {
  if (booking.status !== "CHECKED_IN") return null;
  return (
    <section aria-labelledby="ss-out" className="ui-card">
      <h2 id="ss-out">{st(language, "out_t")}</h2>
      <p className="ui-small ui-muted">{st(language, "out_s")}</p>
      {may("short_stays.desk") && (
        <div className="ui-actions">
          <button
            className="ui-btn primary"
            disabled={busy}
            onClick={() => {
              onStep("check-out", { version: booking.version });
            }}
            type="button"
          >
            <Icon name="moveout" small />
            {st(language, "out_b")}
          </button>
        </div>
      )}
    </section>
  );
}

/** One problem the housekeeper is reporting, before the room check is sent. */
interface ProblemRow {
  key: number;
  typeId: string;
  what: string;
  urgent: boolean;
}

function typeName(language: Language, type: ProblemType): string {
  return language === "km" && type.name_kh !== null
    ? type.name_kh
    : type.name_en;
}

/** DL-222: the room check reports problems as Problem reports of the Unit, never a cost. */
export function RoomCheckCard({
  language,
  booking,
  may,
  busy,
  onStep,
  problemTypes,
}: StepsProps) {
  const [note, setNote] = useState("");
  const [rows, setRows] = useState<ProblemRow[]>([]);
  const [nextKey, setNextKey] = useState(1);
  const [checked, setChecked] = useState(false);
  const task = booking.room_check;
  if (task === null) return null;
  if (task.status !== "TO_DO")
    return (
      <section aria-labelledby="ss-room" className="ui-card">
        <h2 id="ss-room">{st(language, "room_t")}</h2>
        <p>
          {st(language, "room_done", momentText(task.done_at))}
          {task.note !== null && <span className="ui-sub2">{task.note}</span>}
        </p>
      </section>
    );
  const mayReport = may("problem_reports.add") && problemTypes.length > 0;
  const typeOf = (id: string) => problemTypes.find((type) => type.id === id);
  const wrong = rows.some((row) => row.typeId === "" || row.what.trim() === "");
  const change = (key: number, patch: Partial<ProblemRow>) => {
    setRows((before) =>
      before.map((row) => (row.key === key ? { ...row, ...patch } : row)),
    );
  };
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setChecked(true);
    if (wrong) return;
    onStep("room-check", {
      ...(note.trim() === "" ? {} : { note: note.trim() }),
      ...(rows.length === 0
        ? {}
        : {
            problems: rows.map((row) => ({
              problem_type_id: row.typeId,
              description: row.what.trim(),
              urgent: row.urgent || typeOf(row.typeId)?.always_urgent === true,
            })),
          }),
    });
  };
  return (
    <section aria-labelledby="ss-room" className="ui-card">
      <h2 id="ss-room">{st(language, "room_t")}</h2>
      <p className="ui-small ui-muted">
        {st(language, "room_due", dayText(task.task_on))}
      </p>
      {may("short_stays.housekeeping") && (
        <form className="ui-form ss-form" noValidate onSubmit={submit}>
          <fieldset className="ss-problems">
            <legend>{st(language, "room_problems")}</legend>
            <p className="ui-small ui-muted">{st(language, "room_hint")}</p>
            {rows.map((row, index) => {
              const id = `ss-room-${String(row.key)}`;
              const always = typeOf(row.typeId)?.always_urgent === true;
              return (
                <div className="ss-problem" key={row.key}>
                  <div className="ui-row2">
                    <div className="ui-field">
                      <label htmlFor={`${id}-type`}>
                        {st(language, "room_type")} {index + 1}
                        <span className="req">{st(language, "required")}</span>
                      </label>
                      <select
                        aria-invalid={checked && row.typeId === ""}
                        disabled={busy}
                        id={`${id}-type`}
                        onChange={(event) => {
                          change(row.key, {
                            typeId: event.currentTarget.value,
                          });
                        }}
                        value={row.typeId}
                      >
                        <option value="">{st(language, "room_pick")}</option>
                        {problemTypes.map((type) => (
                          <option key={type.id} value={type.id}>
                            {typeName(language, type)}
                          </option>
                        ))}
                      </select>
                      {checked && row.typeId === "" && (
                        <p className="ui-error">
                          <Icon name="alert" small />
                          <span>{st(language, "e_type")}</span>
                        </p>
                      )}
                    </div>
                    <div className="ui-field">
                      <label htmlFor={`${id}-what`}>
                        {st(language, "room_wrong")} {index + 1}
                        <span className="req">{st(language, "required")}</span>
                      </label>
                      <input
                        aria-invalid={checked && row.what.trim() === ""}
                        autoComplete="off"
                        disabled={busy}
                        id={`${id}-what`}
                        maxLength={1000}
                        onChange={(event) => {
                          change(row.key, { what: event.currentTarget.value });
                        }}
                        value={row.what}
                      />
                      {checked && row.what.trim() === "" && (
                        <p className="ui-error">
                          <Icon name="alert" small />
                          <span>{st(language, "e_wrong")}</span>
                        </p>
                      )}
                    </div>
                  </div>
                  <div className="ui-hrow">
                    <label className="ui-chk">
                      <input
                        checked={row.urgent || always}
                        disabled={busy || always}
                        onChange={(event) => {
                          change(row.key, {
                            urgent: event.currentTarget.checked,
                          });
                        }}
                        type="checkbox"
                      />
                      {st(language, "room_urgent")}
                    </label>
                    <button
                      className="ui-btn link"
                      disabled={busy}
                      onClick={() => {
                        setRows((before) =>
                          before.filter((other) => other.key !== row.key),
                        );
                      }}
                      type="button"
                    >
                      <Icon name="x" small />
                      {st(language, "room_remove")} {index + 1}
                    </button>
                  </div>
                </div>
              );
            })}
            {mayReport ? (
              rows.length < 20 && (
                <div className="ui-actions">
                  <button
                    className="ui-btn"
                    disabled={busy}
                    onClick={() => {
                      setRows((before) => [
                        ...before,
                        { key: nextKey, typeId: "", what: "", urgent: false },
                      ]);
                      setNextKey(nextKey + 1);
                    }}
                    type="button"
                  >
                    <Icon name="alert" small />
                    {st(language, "room_add")}
                  </button>
                </div>
              )
            ) : (
              <p className="ui-small ui-muted">
                {st(language, "room_no_right")}
              </p>
            )}
          </fieldset>
          <div className="ui-field">
            <label htmlFor="ss-room-note">{st(language, "room_note")}</label>
            <input
              autoComplete="off"
              disabled={busy}
              id="ss-room-note"
              maxLength={500}
              onChange={(event) => {
                setNote(event.currentTarget.value);
              }}
              value={note}
            />
          </div>
          <div className="ui-actions">
            <button className="ui-btn primary" disabled={busy} type="submit">
              <Icon name="check" small />
              {st(language, "room_b")}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

const DAMAGE_TONES = {
  WAITING: "warn",
  APPROVED: "err",
  REFUSED: "neutral",
} as const;

/** DL-222: Charge the guest (what for and how much) or No charge, by the person who bills damage. */
function DamageDecisionForm({
  language,
  booking,
  busy,
  onStep,
}: Pick<StepsProps, "language" | "booking" | "busy" | "onStep">) {
  const [charge, setCharge] = useState(true);
  // What the guest pays for starts from the problems the room check reported.
  const [what, setWhat] = useState(() =>
    booking.problems
      .map((problem) => problem.description)
      .join("; ")
      .slice(0, 500),
  );
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [checked, setChecked] = useState(false);
  const cents = centsOf(amount);
  const wrongWhat = charge && what.trim() === "";
  const wrongAmount = charge && cents === null;
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setChecked(true);
    if (wrongWhat || wrongAmount) return;
    onStep(
      "damage",
      charge
        ? { charge: true, description: what.trim(), amount_usd_cents: cents }
        : {
            charge: false,
            ...(note.trim() === "" ? {} : { note: note.trim() }),
          },
    );
  };
  return (
    <form className="ui-form ss-form" noValidate onSubmit={submit}>
      <div className="ui-notice warn" role="note">
        <Icon name="alert" />
        <p>{st(language, "dmg_due")}</p>
      </div>
      <fieldset className="ui-radios">
        <legend className="ui-sr">{st(language, "dmg_t")}</legend>
        {([true, false] as const).map((value) => (
          <label className="ui-chk" key={String(value)}>
            <input
              checked={charge === value}
              disabled={busy}
              name="ss-dmg-charge"
              onChange={() => {
                setCharge(value);
              }}
              type="radio"
            />
            {st(language, value ? "dmg_charge" : "dmg_none")}
          </label>
        ))}
      </fieldset>
      {charge ? (
        <>
          <div className="ui-row2">
            <div className="ui-field">
              <label htmlFor="ss-dmg-for">
                {st(language, "dmg_for")}
                <span className="req">{st(language, "required")}</span>
              </label>
              <input
                aria-invalid={checked && wrongWhat}
                autoComplete="off"
                disabled={busy}
                id="ss-dmg-for"
                maxLength={500}
                onChange={(event) => {
                  setWhat(event.currentTarget.value);
                }}
                value={what}
              />
              {checked && wrongWhat && (
                <p className="ui-error">
                  <Icon name="alert" small />
                  <span>{st(language, "e_for")}</span>
                </p>
              )}
            </div>
            <div className="ui-field">
              <label htmlFor="ss-dmg-amount">
                {st(language, "dmg_amount")}
                <span className="req">{st(language, "required")}</span>
              </label>
              <input
                aria-invalid={checked && wrongAmount}
                autoComplete="off"
                disabled={busy}
                id="ss-dmg-amount"
                inputMode="decimal"
                maxLength={10}
                onChange={(event) => {
                  setAmount(event.currentTarget.value);
                }}
                value={amount}
              />
              {checked && wrongAmount && (
                <p className="ui-error">
                  <Icon name="alert" small />
                  <span>{st(language, "e_cost")}</span>
                </p>
              )}
            </div>
          </div>
          <p className="ui-small ui-muted">{st(language, "dmg_rule")}</p>
        </>
      ) : (
        <div className="ui-field">
          <label htmlFor="ss-dmg-note">{st(language, "dmg_note_opt")}</label>
          <input
            autoComplete="off"
            disabled={busy}
            id="ss-dmg-note"
            maxLength={500}
            onChange={(event) => {
              setNote(event.currentTarget.value);
            }}
            value={note}
          />
        </div>
      )}
      <div className="ui-actions">
        <button className="ui-btn primary" disabled={busy} type="submit">
          {st(language, "dmg_save")}
        </button>
      </div>
    </form>
  );
}

export function DamagesCard({
  language,
  booking,
  may,
  busy,
  onStep,
  onDecide,
}: StepsProps) {
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [missing, setMissing] = useState<string | null>(null);
  const decision = booking.damage_decision;
  if (booking.damages.length === 0 && booking.problems.length === 0)
    return null;
  const mayBill = may("damage_charges.bill");
  return (
    <section aria-labelledby="ss-dmg" className="ui-card">
      <h2 id="ss-dmg">{st(language, "dmg_t")}</h2>
      {booking.problems.length > 0 && (
        <>
          <h3 className="ui-small">{st(language, "dmg_problems")}</h3>
          <ul className="ui-plain ss-found">
            {booking.problems.map((problem) => (
              <li key={problem.report_id}>
                <div>
                  <a
                    className="ui-num"
                    href={hashForPage("problems", `pr:${problem.report_id}`)}
                  >
                    {problem.report_number}
                  </a>{" "}
                  ·{" "}
                  {language === "km" && problem.type_name_kh !== null
                    ? problem.type_name_kh
                    : problem.type_name_en}
                  <span className="ui-sub2">{problem.description}</span>
                </div>
                {problem.urgent && (
                  <Chip tone="err">{st(language, "room_urgent")}</Chip>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
      {decision?.outcome === "NO_CHARGE" && (
        <p>
          {st(language, "dmg_no_charge")}
          {decision.note !== null && (
            <span className="ui-sub2">{decision.note}</span>
          )}
        </p>
      )}
      {booking.damages.length > 0 && (
        <ul className="ui-plain ss-found">
          {booking.damages.map((damage) => {
            const note = notes[damage.damage_id] ?? "";
            return (
              <li className="ss-damage" key={damage.damage_id}>
                <div>
                  <b>{damage.description}</b> ·{" "}
                  <span className="ui-num">
                    {usdFromCents(damage.amount_usd_cents)}
                  </span>{" "}
                  <Chip tone={DAMAGE_TONES[damage.status]}>
                    {st(language, `dmg_${damage.status}`)}
                  </Chip>
                  {damage.status === "APPROVED" && (
                    <span className="ui-sub2">
                      {damage.from_deposit_usd_cents > 0 &&
                        st(
                          language,
                          "dmg_from",
                          usdFromCents(damage.from_deposit_usd_cents),
                        )}
                      {damage.from_deposit_usd_cents > 0 &&
                        damage.invoice_number !== null &&
                        " · "}
                      {damage.invoice_id !== null &&
                        damage.invoice_number !== null && (
                          <a
                            href={hashForPage(
                              "invoices",
                              `inv:${damage.invoice_id}`,
                            )}
                          >
                            {st(language, "dmg_inv", damage.invoice_number)}
                          </a>
                        )}
                    </span>
                  )}
                  {damage.decision_note !== null && (
                    <span className="ui-sub2">{damage.decision_note}</span>
                  )}
                </div>
                {damage.status === "WAITING" && mayBill && (
                  <div className="ui-stack">
                    <label
                      className="ui-sr"
                      htmlFor={`ss-dmg-${damage.damage_id}`}
                    >
                      {st(language, "dmg_note")}
                    </label>
                    <input
                      autoComplete="off"
                      disabled={busy}
                      id={`ss-dmg-${damage.damage_id}`}
                      maxLength={500}
                      onChange={(event) => {
                        const value = event.currentTarget.value;
                        setNotes((before) => ({
                          ...before,
                          [damage.damage_id]: value,
                        }));
                      }}
                      placeholder={st(language, "dmg_note")}
                      value={note}
                    />
                    {missing === damage.damage_id && (
                      <p className="ui-error">
                        <Icon name="alert" small />
                        <span>{st(language, "e_reason")}</span>
                      </p>
                    )}
                    <div className="ui-actions">
                      <button
                        className="ui-btn primary"
                        disabled={busy}
                        onClick={() => {
                          onDecide(damage.damage_id, true, note.trim());
                        }}
                        type="button"
                      >
                        {st(language, "dmg_ok")}
                      </button>
                      <button
                        className="ui-btn"
                        disabled={busy}
                        onClick={() => {
                          if (note.trim() === "") {
                            setMissing(damage.damage_id);
                            return;
                          }
                          setMissing(null);
                          onDecide(damage.damage_id, false, note.trim());
                        }}
                        type="button"
                      >
                        {st(language, "dmg_no")}
                      </button>
                    </div>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {booking.damage_due &&
        (mayBill ? (
          <DamageDecisionForm
            booking={booking}
            busy={busy}
            language={language}
            onStep={onStep}
          />
        ) : (
          <p className="ui-small ui-muted">{st(language, "dmg_wait")}</p>
        ))}
    </section>
  );
}

export function FeesCard({ language, booking, may, busy, onStep }: StepsProps) {
  const early = booking.status === "BOOKED" && !booking.early_check_in;
  const late =
    (booking.status === "BOOKED" || booking.status === "CHECKED_IN") &&
    !booking.late_check_out;
  const until = timeText(booking.late_check_out_until);
  if (!early && !late && !booking.early_check_in && !booking.late_check_out)
    return null;
  return (
    <section aria-labelledby="ss-fee" className="ui-card">
      <h2 id="ss-fee">{st(language, "fee_t")}</h2>
      <p className="ui-small ui-muted">
        {booking.fee_usd_cents > 0
          ? st(language, "fee_cost", usdFromCents(booking.fee_usd_cents))
          : st(language, "fee_free")}
      </p>
      {(booking.early_check_in || booking.late_check_out) && (
        <ul className="ui-plain ss-ready">
          {booking.early_check_in && (
            <Done ok text={st(language, "fee_has_early")} />
          )}
          {booking.late_check_out && (
            <Done ok text={st(language, "fee_has_late", until)} />
          )}
        </ul>
      )}
      {may("short_stays.desk") && (early || late) && (
        <div className="ui-actions">
          {early && (
            <button
              className="ui-btn"
              disabled={busy}
              onClick={() => {
                onStep("fee", {
                  version: booking.version,
                  kind: "EARLY_CHECK_IN",
                });
              }}
              type="button"
            >
              {st(language, "fee_early")}
            </button>
          )}
          {late && (
            <button
              className="ui-btn"
              disabled={busy}
              onClick={() => {
                onStep("fee", {
                  version: booking.version,
                  kind: "LATE_CHECK_OUT",
                });
              }}
              type="button"
            >
              {st(language, "fee_late", until)}
            </button>
          )}
        </div>
      )}
    </section>
  );
}

export function ExtendCard({
  language,
  booking,
  may,
  busy,
  onStep,
  onPrice,
}: StepsProps) {
  const first = addDays(booking.check_out_on, 1);
  const [out, setOut] = useState(first);
  const [total, setTotal] = useState<number | null | "pricing">("pricing");
  const open =
    (booking.status === "BOOKED" || booking.status === "CHECKED_IN") &&
    may("short_stays.desk");
  const valid = out > booking.check_out_on;
  useEffect(() => {
    if (!open || !valid) return;
    let current = true;
    setTotal("pricing");
    void onPrice(out).then((found) => {
      if (current) setTotal(found);
    });
    return () => {
      current = false;
    };
  }, [open, valid, out, onPrice]);
  if (!open) return null;
  const billed = booking.payment !== "NOT_BILLED";
  return (
    <section aria-labelledby="ss-ext" className="ui-card">
      <h2 id="ss-ext">{st(language, "ext_t")}</h2>
      <div className="ui-field">
        <label htmlFor="ss-ext-out">{st(language, "ext_out")}</label>
        <DateInput
          calendarLabel={st(language, "tab_cal")}
          describedBy={valid ? undefined : "ss-ext-err"}
          disabled={busy}
          id="ss-ext-out"
          invalid={!valid}
          language={language}
          min={first}
          onChange={(value) => {
            setOut(value);
          }}
          value={out}
        />
        {!valid && (
          <p className="ui-error" id="ss-ext-err">
            <Icon name="alert" small />
            <span>{st(language, "e_out", dayText(booking.check_out_on))}</span>
          </p>
        )}
      </div>
      {valid && (
        <p aria-live="polite" className="ui-small">
          {total === "pricing"
            ? st(language, "ext_pricing")
            : total === null
              ? null
              : total > booking.total_usd_cents
                ? st(
                    language,
                    "ext_price",
                    usdFromCents(total),
                    usdFromCents(total - booking.total_usd_cents),
                  )
                : st(language, "ext_same", usdFromCents(total))}
        </p>
      )}
      {billed && (
        <p className="ui-small ui-muted">{st(language, "ext_bill")}</p>
      )}
      <div className="ui-actions">
        <button
          className="ui-btn primary"
          disabled={busy || !valid}
          onClick={() => {
            onStep("extend", { version: booking.version, check_out_on: out });
          }}
          type="button"
        >
          <Icon name="calendar" small />
          {st(language, "ext_b")}
        </button>
      </div>
    </section>
  );
}

export function CancelCard({
  language,
  booking,
  today,
  may,
  busy,
  onStep,
}: StepsProps) {
  const [reason, setReason] = useState("");
  const [checked, setChecked] = useState(false);
  if (booking.status !== "BOOKED" || !may("short_stays.desk")) return null;
  const free = today <= booking.free_cancel_until;
  const site =
    booking.payment === "PAID_ON_SITE" ? (booking.site_name ?? "") : null;
  const wrong = reason.trim() === "";
  const send = (noShow: boolean) => {
    setChecked(true);
    if (wrong) return;
    onStep("cancel", {
      version: booking.version,
      reason: reason.trim(),
      ...(noShow ? { no_show: true } : {}),
    });
  };
  return (
    <section aria-labelledby="ss-can" className="ui-card">
      <h2 id="ss-can">{st(language, "can_t")}</h2>
      <p className="ui-small ui-muted">
        {site !== null
          ? st(language, "can_site", site)
          : st(
              language,
              free ? "can_free" : "can_late",
              dayText(booking.free_cancel_until),
            )}
      </p>
      <div className="ui-field">
        <label htmlFor="ss-can-why">
          {st(language, "can_reason")}
          <span className="req">{st(language, "required")}</span>
        </label>
        <input
          aria-invalid={checked && wrong}
          autoComplete="off"
          disabled={busy}
          id="ss-can-why"
          maxLength={500}
          onChange={(event) => {
            setReason(event.currentTarget.value);
          }}
          value={reason}
        />
        {checked && wrong && (
          <p className="ui-error">
            <Icon name="alert" small />
            <span>{st(language, "e_why")}</span>
          </p>
        )}
      </div>
      <div className="ui-actions">
        <button
          className="ui-btn"
          disabled={busy}
          onClick={() => {
            send(false);
          }}
          type="button"
        >
          {st(language, "can_b")}
        </button>
        {today >= booking.check_in_on && (
          <button
            className="ui-btn"
            disabled={busy}
            onClick={() => {
              send(true);
            }}
            type="button"
          >
            {st(language, "can_no_show")}
          </button>
        )}
      </div>
    </section>
  );
}

export function CancelledCard({
  language,
  booking,
  today,
  may,
  busy,
  onStep,
}: StepsProps) {
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [checked, setChecked] = useState(false);
  const done = booking.cancellation;
  if (done === null) return null;
  const mayCredit =
    !done.free &&
    done.kept_usd_cents > 0 &&
    booking.credit === null &&
    may("short_stays.credit");
  const cents = centsOf(amount);
  const wrongAmount = cents === null || cents > done.kept_usd_cents;
  const wrongNote = note.trim() === "";
  const give = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setChecked(true);
    if (wrongAmount || wrongNote) return;
    onStep("credit", { amount_usd_cents: cents, note: note.trim() });
  };
  return (
    <section aria-labelledby="ss-can-done" className="ui-card">
      <h2 id="ss-can-done">{st(language, `st_${done.kind}`)}</h2>
      {booking.cancel_reason !== null && <p>{booking.cancel_reason}</p>}
      <p className="ui-small">
        {done.paid_usd_cents === 0
          ? st(language, "can_nothing")
          : done.free
            ? st(language, "can_back", usdFromCents(done.back_usd_cents))
            : st(language, "can_kept", usdFromCents(done.kept_usd_cents))}
      </p>
      {done.back_usd_cents > 0 && may("customers.read") && (
        <div className="ui-actions">
          <a
            className="ui-btn"
            href={hashForPage("customers", booking.customer_id)}
          >
            {st(language, "can_open")}
          </a>
        </div>
      )}
      {booking.credit !== null && (
        <p>
          <b>{st(language, "cr_t")}</b>
          <span className="ui-sub2 ui-num">
            {st(
              language,
              "cr_given",
              usdFromCents(booking.credit.amount_usd_cents),
              dayText(booking.credit.use_by),
            )}
          </span>
          <span className="ui-sub2">{booking.credit.note}</span>
          {booking.credit.ended !== null ? (
            <span className="ui-sub2">
              {booking.credit.ended.left_usd_cents === 0
                ? st(
                    language,
                    "cr_ended_none",
                    dayText(booking.credit.ended.at.slice(0, 10)),
                  )
                : st(
                    language,
                    "cr_ended",
                    usdFromCents(booking.credit.ended.left_usd_cents),
                    booking.credit.ended.invoice_number ?? "",
                  )}
            </span>
          ) : (
            booking.credit.left_usd_cents !==
              booking.credit.amount_usd_cents && (
              <span className="ui-sub2 ui-num">
                {st(
                  language,
                  "cr_left",
                  usdFromCents(booking.credit.left_usd_cents),
                )}
              </span>
            )
          )}
        </p>
      )}
      {booking.credit !== null &&
        booking.credit.ended === null &&
        booking.credit.use_by < today &&
        may("short_stays.credit") && (
          <div className="ui-actions">
            <p className="ui-small">{st(language, "cr_end_s")}</p>
            <button
              className="ui-btn"
              disabled={busy}
              onClick={() => {
                onStep("credit/end", null);
              }}
              type="button"
            >
              {st(language, "cr_end_b")}
            </button>
          </div>
        )}
      {mayCredit && (
        <form className="ui-form ss-form" noValidate onSubmit={give}>
          <h3>{st(language, "cr_t")}</h3>
          <p className="ui-small ui-muted">{st(language, "cr_s")}</p>
          <div className="ui-row2">
            <div className="ui-field">
              <label htmlFor="ss-cr-amount">
                {st(language, "cr_amount")}
                <span className="req">{st(language, "required")}</span>
              </label>
              <input
                aria-invalid={checked && wrongAmount}
                autoComplete="off"
                disabled={busy}
                id="ss-cr-amount"
                inputMode="decimal"
                maxLength={10}
                onChange={(event) => {
                  setAmount(event.currentTarget.value);
                }}
                value={amount}
              />
              {checked && wrongAmount && (
                <p className="ui-error">
                  <Icon name="alert" small />
                  <span>
                    {st(
                      language,
                      "e_credit",
                      usdFromCents(done.kept_usd_cents),
                    )}
                  </span>
                </p>
              )}
            </div>
            <div className="ui-field">
              <label htmlFor="ss-cr-note">
                {st(language, "cr_note")}
                <span className="req">{st(language, "required")}</span>
              </label>
              <input
                aria-invalid={checked && wrongNote}
                autoComplete="off"
                disabled={busy}
                id="ss-cr-note"
                maxLength={500}
                onChange={(event) => {
                  setNote(event.currentTarget.value);
                }}
                value={note}
              />
              {checked && wrongNote && (
                <p className="ui-error">
                  <Icon name="alert" small />
                  <span>{st(language, "e_why")}</span>
                </p>
              )}
            </div>
          </div>
          <div className="ui-actions">
            <button className="ui-btn primary" disabled={busy} type="submit">
              {st(language, "cr_b")}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

/** Step 4c: a guest who changes to a Lease gets money off the first month. */
export function LeaseCard({
  language,
  booking,
  may,
  busy,
  onStep,
}: StepsProps) {
  const [chosen, setChosen] = useState("");
  const offer = booking.lease_offer;
  const stayed =
    booking.status === "CHECKED_IN" || booking.status === "CHECKED_OUT";
  if (offer !== null) {
    return (
      <section aria-labelledby="ss-lease" className="ui-card">
        <h2 id="ss-lease">{st(language, "ls_t")}</h2>
        <p>
          {st(
            language,
            "ls_linked",
            offer.unit_number,
            usdFromCents(offer.off_usd_cents),
          )}
        </p>
        <p className="ui-small ui-muted">
          {st(
            language,
            offer.lease_status === "DRAFTED" ? "ls_at_sign" : "ls_signed",
          )}
        </p>
        <div className="ui-actions">
          <a className="ui-btn" href={hashForPage("leases", offer.lease_id)}>
            {st(language, "ls_open")}
          </a>
        </div>
      </section>
    );
  }
  if (!stayed || !may("short_stays.desk") || booking.lease_off_usd_cents < 1)
    return null;
  const drafts = booking.lease_drafts;
  const pick =
    drafts.find((draft) => draft.lease_id === chosen)?.lease_id ??
    drafts[0]?.lease_id;
  return (
    <section aria-labelledby="ss-lease" className="ui-card">
      <h2 id="ss-lease">{st(language, "ls_t")}</h2>
      <p className="ui-small ui-muted">
        {st(language, "ls_s", usdFromCents(booking.lease_off_usd_cents))}
      </p>
      {pick === undefined ? (
        <p className="ui-small">{st(language, "ls_none")}</p>
      ) : (
        <div className="ui-field">
          <label htmlFor="ss-lease-pick">{st(language, "ls_pick")}</label>
          <select
            disabled={busy}
            id="ss-lease-pick"
            onChange={(event) => {
              setChosen(event.currentTarget.value);
            }}
            value={pick}
          >
            {drafts.map((draft) => (
              <option key={draft.lease_id} value={draft.lease_id}>
                {st(
                  language,
                  "ls_draft",
                  draft.unit_number,
                  draft.start_date === null ? "" : dayText(draft.start_date),
                  usdFromCents(draft.monthly_rent_usd_cents),
                )}
              </option>
            ))}
          </select>
        </div>
      )}
      <div className="ui-actions">
        <a className="ui-btn" href={hashForPage("leases", "new")}>
          {st(language, "ls_new")}
        </a>
        {pick !== undefined && (
          <button
            className="ui-btn primary"
            disabled={busy}
            onClick={() => {
              onStep("lease", { lease_id: pick });
            }}
            type="button"
          >
            {st(language, "ls_b")}
          </button>
        )}
      </div>
    </section>
  );
}

/** Step 5b: the Owner's or Manager's extra discount, with a reason, before the Invoice. */
export function DiscountCard({
  language,
  booking,
  may,
  busy,
  onStep,
}: StepsProps) {
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [checked, setChecked] = useState(false);
  const given = booking.lines.find((line) => line.kind === "EXTRA_DISCOUNT");
  const open = booking.status === "BOOKED" && booking.payment === "NOT_BILLED";
  if (given === undefined && (!open || !may("short_stays.approve")))
    return null;
  if (given !== undefined) {
    return (
      <section aria-labelledby="ss-disc" className="ui-card">
        <h2 id="ss-disc">{st(language, "dc_t")}</h2>
        <p>
          {st(
            language,
            "dc_given",
            usdFromCents(-given.amount_usd_cents),
            booking.history
              .filter((event) => event.kind === "DISCOUNT")
              .map((event) => event.note ?? "")
              .join(" "),
          )}
        </p>
      </section>
    );
  }
  const cents = centsOf(amount);
  const wrong =
    cents === null || cents >= booking.total_usd_cents || reason.trim() === "";
  const give = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setChecked(true);
    if (wrong) return;
    onStep("discount", {
      version: booking.version,
      amount_usd_cents: cents,
      reason: reason.trim(),
    });
  };
  return (
    <section aria-labelledby="ss-disc" className="ui-card">
      <h2 id="ss-disc">{st(language, "dc_t")}</h2>
      <p className="ui-small ui-muted">{st(language, "dc_s")}</p>
      <form className="ui-form ss-form" noValidate onSubmit={give}>
        <div className="ui-row2">
          <div className="ui-field">
            <label htmlFor="ss-disc-amount">{st(language, "dc_amount")}</label>
            <input
              aria-invalid={
                checked && (cents === null || cents >= booking.total_usd_cents)
              }
              disabled={busy}
              id="ss-disc-amount"
              inputMode="decimal"
              onChange={(event) => {
                setAmount(event.currentTarget.value);
              }}
              value={amount}
            />
          </div>
          <div className="ui-field">
            <label htmlFor="ss-disc-reason">{st(language, "dc_reason")}</label>
            <input
              aria-invalid={checked && reason.trim() === ""}
              disabled={busy}
              id="ss-disc-reason"
              maxLength={500}
              onChange={(event) => {
                setReason(event.currentTarget.value);
              }}
              value={reason}
            />
          </div>
        </div>
        {checked && wrong && (
          <p className="ui-error">
            <Icon name="alert" small />
            <span>{st(language, "dc_wrong")}</span>
          </p>
        )}
        <div className="ui-actions">
          <button className="ui-btn" disabled={busy} type="submit">
            {st(language, "dc_b")}
          </button>
        </div>
      </form>
    </section>
  );
}

/** The owner's Google Maps place (mock-up round 31): the review link sent after a stay. */
export const REVIEW_LINK =
  "https://search.google.com/local/writereview?placeid=ChIJH87t_fRTCTER6g_sn780yZI";

/** Step 5b: after the check-out the desk sends a review request once. */
export function ReviewCard({
  language,
  booking,
  may,
  busy,
  onStep,
}: StepsProps) {
  const [copied, setCopied] = useState(false);
  if (booking.status !== "CHECKED_OUT") return null;
  if (booking.review_asked_at !== null)
    return (
      <section aria-labelledby="ss-review" className="ui-card">
        <h2 id="ss-review">{st(language, "rv_t")}</h2>
        <p className="ui-small ui-muted">
          {st(language, "rv_done", momentText(booking.review_asked_at))}
        </p>
      </section>
    );
  if (!may("short_stays.desk")) return null;
  const message = st(
    language,
    "rv_message",
    booking.guest_name.split(" ")[0] ?? booking.guest_name,
    REVIEW_LINK,
  );
  return (
    <section aria-labelledby="ss-review" className="ui-card">
      <h2 id="ss-review">{st(language, "rv_t")}</h2>
      <p className="ui-small ui-muted">{st(language, "rv_s")}</p>
      <textarea
        aria-labelledby="ss-review"
        className="ss-message"
        readOnly
        rows={4}
        value={message}
      />
      {copied && (
        <p className="ui-small" role="status">
          {st(language, "rv_copied")}
        </p>
      )}
      <div className="ui-actions">
        <button
          className="ui-btn"
          onClick={() => {
            void copyText(message).then(setCopied);
          }}
          type="button"
        >
          {st(language, "rv_copy")}
        </button>
        <button
          className="ui-btn primary"
          disabled={busy}
          onClick={() => {
            onStep("review", null);
          }}
          type="button"
        >
          {st(language, "rv_b")}
        </button>
      </div>
    </section>
  );
}

/** Puts text on the clipboard; false when the browser does not allow it. */
export async function copyText(value: string): Promise<boolean> {
  try {
    if (typeof navigator === "undefined" || !("clipboard" in navigator))
      return false;
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    return false;
  }
}
