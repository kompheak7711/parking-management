// V1-058 R5d: the late-payment card on the Invoice page and its Reduce or waive dialog
// (DESIGN.md "Late-payment card" and "Reduce or waive dialog"). The app adds the charge itself on
// the first day after the Due Date (DL-076); a Manager or the Owner only lowers it after a staff
// mistake, with one of three fixed reasons and what happened. The amount only goes down.

import { type FormEvent, Fragment, useRef, useState } from "react";

import { InvoiceClientError } from "../invoiceClient";
import type {
  LateChargeCard as Card,
  PaymentsApi,
  ReductionReason,
} from "../payments/paymentsClient";
import { momentText, usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { Chip, Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import { centsOf } from "./invoicesData";
import { ivt, type InvoicesTextKey } from "./text";

const REASONS: readonly ReductionReason[] = [
  "WRONG_INVOICE",
  "PAID_ON_TIME_RECORDED_LATE",
  "OTHER_STAFF_MISTAKE",
];

/** The day a moment falls on in Phnom Penh, dd/mm/yyyy. */
function dayOf(moment: string): string {
  return momentText(moment).slice(0, 10);
}

/** Charged, Reduced, Waived or Paid (DESIGN.md). */
/** The word of one change: reduced, waived or a reduction undone. */
function changeWord(change: Card["changes"][number]) {
  if (change.kind === "REDUCTION_REVERSAL") return "lt_REVERSED" as const;
  return change.resulting === 0
    ? ("lt_WAIVED" as const)
    : ("lt_REDUCED" as const);
}

/** A Deposit paid part of it: the reduction command refuses such a charge. */
export function depositPaid(card: Card): boolean {
  return card.paidBy.some((item) => item.kind === "DEPOSIT");
}

export function lateState(
  card: Card,
): "lt_CHARGED" | "lt_REDUCED" | "lt_WAIVED" | "lt_PAID" {
  if (card.now === 0) return "lt_WAIVED";
  if (card.stillOwed === 0) return "lt_PAID";
  return card.now < card.original ? "lt_REDUCED" : "lt_CHARGED";
}

/** The History lines of the charge: added, each change, each payment. */
export function lateHistory(
  language: Language,
  card: Card,
): [string, string][] {
  const lines: [string, string][] = [
    [
      card.chargedAt,
      card.byApp && card.fullRate
        ? ivt(
            language,
            "lt_h_add",
            usdFromCents(card.original),
            card.rateBasisPoints / 100,
            usdFromCents(card.unpaidAtCharge),
          )
        : ivt(
            language,
            "lt_h_add_by",
            usdFromCents(card.original),
            card.addedBy ?? "—",
          ),
    ],
  ];
  for (const change of card.changes) {
    const why =
      change.reasonCode === null
        ? change.reason
        : ivt(language, `lt_why_${change.reasonCode}`);
    const word = changeWord(change);
    lines.push([
      change.at,
      word === "lt_WAIVED"
        ? ivt(language, "lt_h_waive", "", change.by ?? "—", why)
        : ivt(
            language,
            word === "lt_REVERSED" ? "lt_h_rev" : "lt_h_red",
            usdFromCents(change.resulting),
            change.by ?? "—",
            why,
          ),
    ]);
  }
  for (const item of card.paidBy)
    lines.push([
      item.at,
      ivt(
        language,
        "lt_h_paid",
        usdFromCents(item.amount),
        item.kind === "PAYMENT"
          ? (item.receiptNumber ?? "—")
          : ivt(
              language,
              item.kind === "CREDIT" ? "lt_from_credit" : "lt_from_deposit",
            ),
      ),
    ]);
  return lines;
}

function Problem({ id, text }: { id: string; text: string }) {
  return (
    <p className="ui-error" id={id}>
      <Icon name="alert" small />
      <span>{text}</span>
    </p>
  );
}

function ReduceDialog({
  language,
  card,
  invoiceNumber,
  who,
  api,
  onClose,
  onSaved,
  onChanged,
}: {
  language: Language;
  card: Card;
  invoiceNumber: string;
  /** The Customer and Unit, for the facts at the top. */
  who: string;
  api: Pick<PaymentsApi, "reduceLateCharge">;
  onClose: () => void;
  onSaved: () => void;
  /** The charge changed meanwhile; the page reads it again. */
  onChanged: () => void;
}) {
  const [choice, setChoice] = useState<"reduce" | "waive" | null>(null);
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState<ReductionReason | "">("");
  const [what, setWhat] = useState("");
  const [problems, setProblems] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<InvoicesTextKey | null>(null);
  const keys = useRef(new Map<string, string>());
  // After a press with no answer the change may be saved, so the form is locked and the next
  // press sends the same key (one change).
  const locked = busy || outcome === "unknown";
  const paid = card.paid;
  const mayWaive = paid === 0;
  const typed = centsOf(amount);
  const newAmount = choice === "waive" ? 0 : choice === "reduce" ? typed : null;
  const amountOk =
    typed !== null && typed < card.now && typed >= Math.max(paid, 1);

  const save = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy) return;
    const found = new Set<string>();
    if (choice === null || (choice === "waive" && !mayWaive)) found.add("pick");
    if (choice === "reduce" && !amountOk) found.add("amt");
    if (reason === "") found.add("reason");
    if (what.trim() === "") found.add("what");
    setProblems(found);
    if (found.size > 0 || newAmount === null || reason === "") return;
    const sent = JSON.stringify([newAmount, reason, what.trim()]);
    const key = keys.current.get(sent) ?? crypto.randomUUID();
    keys.current.set(sent, key);
    setBusy(true);
    // "No answer" stays until a definite answer, so the form stays locked.
    setOutcome((current) => (current === "unknown" ? current : null));
    void api
      .reduceLateCharge(card.chargeId, newAmount, reason, what.trim(), key)
      .then(onSaved)
      .catch((error: unknown) => {
        if (!(error instanceof InvoiceClientError) || error.outcomeUnknown) {
          setOutcome("unknown");
          return;
        }
        if (error.status === 409 || error.status === 412) {
          onChanged();
          return;
        }
        setOutcome("refused");
      })
      .finally(() => {
        setBusy(false);
      });
  };

  return (
    <Dialog
      busy={busy}
      closeLabel={ivt(language, "cancel")}
      onClose={onClose}
      onSubmit={save}
      submitLabel={ivt(language, "lt_save")}
      title={ivt(language, "lt_fix_t", invoiceNumber)}
    >
      <dl className="ui-kv">
        <dt>{ivt(language, "cust_t")}</dt>
        <dd>{who}</dd>
        <dt>{ivt(language, "lt_bal_at")}</dt>
        <dd className="ui-num">{usdFromCents(card.unpaidAtCharge)}</dd>
        <dt>{ivt(language, "lt_now")}</dt>
        <dd className="ui-num">{usdFromCents(card.now)}</dd>
        <dt>{ivt(language, "lt_paid")}</dt>
        <dd className="ui-num">{usdFromCents(paid)}</dd>
      </dl>
      <fieldset
        aria-describedby={problems.has("pick") ? "lt-pick-err" : undefined}
        className="ui-radios"
        disabled={locked}
      >
        <legend>{ivt(language, "lt_choice")}</legend>
        <label className="ui-chk">
          <input
            checked={choice === "reduce"}
            name="lt-choice"
            onChange={() => {
              setChoice("reduce");
            }}
            type="radio"
          />
          <span>
            {ivt(language, "lt_o_red")}
            <small className="ui-sub2">
              {paid > 0
                ? ivt(
                    language,
                    "lt_o_red_s",
                    usdFromCents(paid),
                    usdFromCents(card.now),
                  )
                : ivt(language, "lt_o_red_s0", usdFromCents(card.now))}
            </small>
          </span>
        </label>
        <label className="ui-chk">
          <input
            checked={choice === "waive"}
            disabled={!mayWaive}
            name="lt-choice"
            onChange={() => {
              setChoice("waive");
            }}
            type="radio"
          />
          <span>
            {ivt(language, "lt_o_waive")}
            <small className="ui-sub2">
              {mayWaive
                ? ivt(language, "lt_o_waive_s")
                : ivt(language, "lt_o_waive_no", usdFromCents(paid))}
            </small>
          </span>
        </label>
        {problems.has("pick") && (
          <Problem id="lt-pick-err" text={ivt(language, "lt_e_pick")} />
        )}
      </fieldset>
      {choice === "reduce" && (
        <div className="ui-field">
          <label htmlFor="lt-amt">{ivt(language, "lt_red_amt")}</label>
          <div className="ui-money">
            <span aria-hidden="true">$</span>
            <input
              aria-describedby={problems.has("amt") ? "lt-amt-err" : undefined}
              aria-invalid={problems.has("amt")}
              autoComplete="off"
              disabled={locked}
              id="lt-amt"
              inputMode="decimal"
              onChange={(event) => {
                setAmount(event.currentTarget.value);
              }}
              value={amount}
            />
          </div>
          {problems.has("amt") && (
            <Problem
              id="lt-amt-err"
              text={
                paid > 0
                  ? ivt(
                      language,
                      "lt_e_amt_paid",
                      usdFromCents(paid),
                      usdFromCents(card.now),
                    )
                  : ivt(language, "lt_e_amt", usdFromCents(card.now))
              }
            />
          )}
        </div>
      )}
      <div className="ui-field">
        <label htmlFor="lt-reason">
          {ivt(language, "lt_reason")}
          <span className="req">{ivt(language, "required")}</span>
        </label>
        <select
          aria-describedby={
            problems.has("reason") ? "lt-reason-err" : undefined
          }
          aria-invalid={problems.has("reason")}
          disabled={locked}
          id="lt-reason"
          onChange={(event) => {
            setReason(event.currentTarget.value as ReductionReason | "");
          }}
          value={reason}
        >
          <option value="">{ivt(language, "lt_reason_pick")}</option>
          {REASONS.map((code) => (
            <option key={code} value={code}>
              {ivt(language, `lt_why_${code}`)}
            </option>
          ))}
        </select>
        {problems.has("reason") && (
          <Problem id="lt-reason-err" text={ivt(language, "lt_e_reason")} />
        )}
      </div>
      <div className="ui-field">
        <label htmlFor="lt-what">
          {ivt(language, "lt_detail")}
          <span className="req">{ivt(language, "required")}</span>
        </label>
        <textarea
          aria-describedby={problems.has("what") ? "lt-what-err" : undefined}
          aria-invalid={problems.has("what")}
          disabled={locked}
          id="lt-what"
          maxLength={500}
          onChange={(event) => {
            setWhat(event.currentTarget.value);
          }}
          placeholder={ivt(language, "lt_detail_ph")}
          rows={2}
          value={what}
        />
        {problems.has("what") && (
          <Problem id="lt-what-err" text={ivt(language, "lt_e_detail")} />
        )}
      </div>
      {newAmount !== null && (newAmount === 0 || amountOk) && (
        <p className="ui-small" role="status">
          {newAmount === 0
            ? ivt(language, "lt_prev_zero", invoiceNumber)
            : ivt(
                language,
                "lt_prev_red",
                usdFromCents(card.now),
                usdFromCents(newAmount),
                usdFromCents(Math.max(0, newAmount - paid)),
              )}
        </p>
      )}
      <p className="ui-muted ui-small">{ivt(language, "lt_fix_note")}</p>
      {outcome !== null && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>{ivt(language, outcome)}</p>
        </div>
      )}
    </Dialog>
  );
}

export function LateChargeSection({
  language,
  card,
  invoiceNumber,
  who,
  mayReceive,
  mayFix,
  api,
  onSaved,
  onChanged,
}: {
  language: Language;
  card: Card;
  invoiceNumber: string;
  who: string;
  mayReceive: boolean;
  mayFix: boolean;
  api: Pick<PaymentsApi, "reduceLateCharge">;
  onSaved: () => void;
  onChanged: () => void;
}) {
  const [fixing, setFixing] = useState(false);
  const [lockedNote, setLockedNote] = useState(false);
  const state = lateState(card);
  const tone =
    state === "lt_PAID"
      ? "ok"
      : state === "lt_WAIVED"
        ? "neutral"
        : state === "lt_REDUCED"
          ? "info"
          : "warn";
  const added = momentText(card.chargedAt).replace(" ", ", ");
  const byDeposit = depositPaid(card);
  return (
    <section aria-labelledby="inv-late" className="ui-card">
      <div className="ui-chead">
        <h2 id="inv-late">{ivt(language, "lt_t")}</h2>
        <Chip tone={tone}>{ivt(language, state)}</Chip>
      </div>
      <dl className="ui-kv ui-is">
        <dt>{ivt(language, "lt_base", dayOf(card.chargedAt))}</dt>
        <dd className="ui-num">{usdFromCents(card.unpaidAtCharge)}</dd>
        <dt>
          {card.fullRate
            ? ivt(language, "lt_added", card.rateBasisPoints / 100)
            : ivt(language, "lt_added_plain")}
          <span className="ui-sub2">
            {card.byApp || card.addedBy === null
              ? ivt(language, "lt_added_s", added)
              : ivt(language, "lt_added_by", card.addedBy, added)}
          </span>
        </dt>
        <dd className="ui-num">{usdFromCents(card.original)}</dd>
        {card.changes.map((change, index) => (
          <Fragment key={index}>
            <dt>
              {ivt(language, changeWord(change))}
              <span className="ui-sub2">
                {ivt(
                  language,
                  "lt_ch_s",
                  change.by ?? "—",
                  momentText(change.at),
                  [
                    change.reasonCode === null
                      ? change.reason
                      : `${ivt(language, `lt_why_${change.reasonCode}`)}.`,
                    change.whatHappened ?? "",
                  ]
                    .filter(Boolean)
                    .join(" "),
                )}
              </span>
            </dt>
            <dd className="ui-num">{usdFromCents(change.resulting)}</dd>
          </Fragment>
        ))}
        <dt>
          {ivt(language, "lt_paid")}
          {card.paidBy.map((item, index) => (
            <span className="ui-sub2" key={index}>
              {item.kind === "PAYMENT" && item.paymentId !== null ? (
                <a
                  className="ui-num"
                  href={hashForPage("payments", `receipt:${item.paymentId}`)}
                >
                  {item.receiptNumber ?? "—"}
                </a>
              ) : (
                ivt(
                  language,
                  item.kind === "CREDIT" ? "lt_from_credit" : "lt_from_deposit",
                )
              )}{" "}
              · <span className="ui-num">{usdFromCents(item.amount)}</span>
            </span>
          ))}
        </dt>
        <dd className={`ui-num${card.paid > 0 ? " okv" : " ui-muted"}`}>
          {usdFromCents(card.paid)}
        </dd>
        <dt className="tot">{ivt(language, "lt_left")}</dt>
        <dd className={`ui-num tot${card.stillOwed > 0 ? " errv" : ""}`}>
          {usdFromCents(card.stillOwed)}
        </dd>
      </dl>
      <p className="ui-muted ui-small">
        {ivt(language, "lt_sep", invoiceNumber)}
      </p>
      <div className="ui-actions">
        {card.stillOwed > 0 && mayReceive && (
          <a
            className="ui-btn"
            href={hashForPage(
              "payments",
              `receive:${card.customerId}:${card.chargeId}`,
            )}
          >
            <Icon name="payments" />
            {ivt(language, "lt_pay")}
          </a>
        )}
        {card.now > card.paid && !byDeposit && (
          <button
            aria-disabled={!mayFix}
            className={mayFix ? "ui-btn" : "ui-btn ui-locked"}
            onClick={() => {
              if (mayFix) setFixing(true);
              else setLockedNote(true);
            }}
            type="button"
          >
            {!mayFix && <Icon name="lock" small />}
            {ivt(language, "lt_fix")}
            <span className="ui-badge">{ivt(language, "mgr_badge")}</span>
          </button>
        )}
      </div>
      {byDeposit && card.now > card.paid && (
        <p className="ui-small ui-muted">{ivt(language, "lt_dep_note")}</p>
      )}
      {lockedNote && (
        <p className="ui-small ui-muted" role="status">
          {ivt(language, "lt_locked")}
        </p>
      )}
      {fixing && (
        <ReduceDialog
          api={api}
          card={card}
          invoiceNumber={invoiceNumber}
          language={language}
          onChanged={() => {
            setFixing(false);
            onChanged();
          }}
          onClose={() => {
            setFixing(false);
          }}
          onSaved={() => {
            setFixing(false);
            onSaved();
          }}
          who={who}
        />
      )}
    </section>
  );
}
