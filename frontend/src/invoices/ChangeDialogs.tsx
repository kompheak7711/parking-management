// V1-058 R5: Adjust and Void on the Invoice page (DESIGN.md "Invoice page": both locked to a
// Manager). An issued Invoice is never edited: an Adjustment is a new record that raises or
// lowers one line, and Void ends what is owed while the Invoice stays with its History. The
// server checks every amount; the same request keeps its key, so pressing again after no
// answer saves once.

import { type FormEvent, useRef, useState } from "react";

import {
  InvoiceClientError,
  type InvoiceApi,
  type InvoiceResource,
} from "../invoiceClient";
import { usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import { cents, centsOf } from "./invoicesData";
import { ivt, type InvoicesTextKey } from "./text";

type Outcome = InvoicesTextKey | null;

/** One key per distinct request, kept while the dialog is open. */
function useKeys() {
  const keys = useRef(new Map<string, string>());
  return (sent: string) => {
    const key = keys.current.get(sent) ?? crypto.randomUUID();
    keys.current.set(sent, key);
    return key;
  };
}

/** Sends a change and sorts the ending: saved, changed meanwhile, unknown, refused. */
function useSend(
  onSaved: (saved: InvoiceResource) => void,
  onChanged: () => void,
) {
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>(null);
  const send = (request: () => Promise<InvoiceResource>) => {
    setBusy(true);
    setOutcome(null);
    void request()
      .then(onSaved)
      .catch((error: unknown) => {
        if (!(error instanceof InvoiceClientError) || error.outcomeUnknown) {
          setOutcome("unknown");
          return;
        }
        if (error.status === 409 || error.status === 412) {
          if (error.code === "INVOICE_LINE_FULLY_PAID") {
            setOutcome("adj_err_paid");
            return;
          }
          onChanged();
          return;
        }
        setOutcome(
          error.code === "INVOICE_LINE_FULLY_PAID" ? "adj_err_paid" : "refused",
        );
      })
      .finally(() => {
        setBusy(false);
      });
  };
  return { busy, outcome, send };
}

function Problem({ id, text }: { id: string; text: string }) {
  return (
    <p className="ui-error" id={id}>
      <Icon name="alert" small />
      <span>{text}</span>
    </p>
  );
}

interface Props {
  language: Language;
  invoice: InvoiceResource;
  onClose: () => void;
  onSaved: (saved: InvoiceResource) => void;
  /** The Invoice changed meanwhile; the page reads it again. */
  onChanged: () => void;
}

export function AdjustDialog({
  language,
  api,
  invoice,
  onClose,
  onSaved,
  onChanged,
}: Props & { api: Pick<InvoiceApi, "adjust"> }) {
  const lines = [...invoice.lines].sort(
    (left, right) => left.sequence - right.sequence,
  );
  const [lineId, setLineId] = useState(lines[0]?.id ?? "");
  const [direction, setDirection] = useState<"CREDIT" | "DEBIT" | null>(null);
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [source, setSource] = useState("");
  const [problems, setProblems] = useState<Set<string>>(new Set());
  const keyFor = useKeys();
  const { busy, outcome, send } = useSend(onSaved, onChanged);
  const line = lines.find((entry) => entry.id === lineId);
  const now = line === undefined ? 0 : cents(line.adjusted_amount);
  const typed = centsOf(amount);
  const after =
    typed === null || direction === null
      ? null
      : direction === "CREDIT"
        ? now - typed
        : now + typed;

  const save = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy || line === undefined) return;
    const found = new Set<string>();
    if (direction === null) found.add("dir");
    // A line cannot go below $0.00; the server also checks what is already paid.
    if (typed === null || (direction === "CREDIT" && typed > now))
      found.add("amt");
    if (reason.trim() === "") found.add("reason");
    if (source.trim() === "") found.add("src");
    setProblems(found);
    if (found.size > 0 || direction === null || typed === null) return;
    const input = {
      invoice_line_id: line.id,
      adjustment_type: direction,
      amount: { currency: "USD" as const, minor_units: typed },
      source_reference: source.trim(),
      reason: reason.trim(),
    };
    const key = keyFor(JSON.stringify(input));
    send(() => api.adjust(invoice.id, input, invoice.version, key));
  };

  return (
    <Dialog
      busy={busy}
      closeLabel={ivt(language, "cancel")}
      onClose={onClose}
      onSubmit={save}
      submitLabel={ivt(language, "adj_save")}
      title={ivt(language, "adj_t", invoice.invoice_number)}
    >
      <p className="ui-muted">{ivt(language, "adj_note")}</p>
      {lines.length > 1 && (
        <div className="ui-field">
          <label htmlFor="adj-line">{ivt(language, "adj_line")}</label>
          <select
            id="adj-line"
            onChange={(event) => {
              setLineId(event.currentTarget.value);
            }}
            value={lineId}
          >
            {lines.map((entry) => (
              <option key={entry.id} value={entry.id}>
                {entry.description} ·{" "}
                {usdFromCents(cents(entry.adjusted_amount))}
              </option>
            ))}
          </select>
        </div>
      )}
      <fieldset
        aria-describedby={problems.has("dir") ? "adj-dir-err" : undefined}
        className="ui-radios"
      >
        <legend>{ivt(language, "adj_dir")}</legend>
        {(
          [
            ["CREDIT", "adj_credit"],
            ["DEBIT", "adj_debit"],
          ] as const
        ).map(([value, key]) => (
          <label className="ui-chk" key={value}>
            <input
              checked={direction === value}
              name="adj-dir"
              onChange={() => {
                setDirection(value);
              }}
              type="radio"
            />
            {ivt(language, key)}
          </label>
        ))}
        {problems.has("dir") && (
          <Problem id="adj-dir-err" text={ivt(language, "adj_err_dir")} />
        )}
      </fieldset>
      <div className="ui-field">
        <label htmlFor="adj-amt">{ivt(language, "ni_amt")}</label>
        <div className="ui-money">
          <span aria-hidden="true">$</span>
          <input
            aria-describedby={problems.has("amt") ? "adj-amt-err" : undefined}
            aria-invalid={problems.has("amt")}
            autoComplete="off"
            id="adj-amt"
            inputMode="decimal"
            onChange={(event) => {
              setAmount(event.currentTarget.value);
            }}
            value={amount}
          />
        </div>
        {problems.has("amt") && (
          <Problem
            id="adj-amt-err"
            text={
              direction === "CREDIT" && typed !== null
                ? ivt(language, "adj_err_more", usdFromCents(now))
                : ivt(language, "err_amount")
            }
          />
        )}
      </div>
      {line !== undefined && after !== null && after >= 0 && (
        <p className="ui-live" role="status">
          {ivt(
            language,
            "adj_live",
            line.description,
            usdFromCents(now),
            usdFromCents(after),
          )}
        </p>
      )}
      <div className="ui-field">
        <label htmlFor="adj-reason">{ivt(language, "ni_reason")}</label>
        <input
          aria-describedby={
            problems.has("reason") ? "adj-reason-err" : undefined
          }
          aria-invalid={problems.has("reason")}
          autoComplete="off"
          id="adj-reason"
          maxLength={500}
          onChange={(event) => {
            setReason(event.currentTarget.value);
          }}
          value={reason}
        />
        {problems.has("reason") && (
          <Problem id="adj-reason-err" text={ivt(language, "ni_err_reason")} />
        )}
      </div>
      <div className="ui-field">
        <label htmlFor="adj-src">{ivt(language, "ni_src")}</label>
        <input
          aria-describedby={problems.has("src") ? "adj-src-err" : undefined}
          aria-invalid={problems.has("src")}
          autoComplete="off"
          id="adj-src"
          maxLength={500}
          onChange={(event) => {
            setSource(event.currentTarget.value);
          }}
          value={source}
        />
        {problems.has("src") && (
          <Problem id="adj-src-err" text={ivt(language, "adj_err_src")} />
        )}
      </div>
      {outcome !== null && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>{ivt(language, outcome)}</p>
        </div>
      )}
    </Dialog>
  );
}

export function VoidDialog({
  language,
  api,
  invoice,
  onClose,
  onSaved,
  onChanged,
}: Props & { api: Pick<InvoiceApi, "void"> }) {
  const [reason, setReason] = useState("");
  const [missing, setMissing] = useState(false);
  const keyFor = useKeys();
  const { busy, outcome, send } = useSend(onSaved, onChanged);
  // Money already paid toward it must be moved or returned first (its own workflow).
  const paid = cents(invoice.active_application_total) > 0;

  const save = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy || paid) return;
    const text = reason.trim();
    setMissing(text === "");
    if (text === "") return;
    const key = keyFor(text);
    send(() => api.void(invoice.id, text, invoice.version, key));
  };

  return (
    <Dialog
      busy={busy}
      closeLabel={ivt(language, paid ? "close" : "cancel")}
      onClose={onClose}
      onSubmit={paid ? undefined : save}
      submitLabel={ivt(language, "void_save")}
      title={ivt(language, "void_t", invoice.invoice_number)}
    >
      {paid ? (
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{ivt(language, "void_paid")}</p>
        </div>
      ) : (
        <>
          <p>
            {ivt(
              language,
              "void_b",
              usdFromCents(Math.max(0, cents(invoice.outstanding_balance))),
            )}
          </p>
          <div className="ui-field">
            <label htmlFor="void-reason">{ivt(language, "ni_reason")}</label>
            <input
              aria-describedby={missing ? "void-reason-err" : undefined}
              aria-invalid={missing}
              autoComplete="off"
              id="void-reason"
              maxLength={500}
              onChange={(event) => {
                setReason(event.currentTarget.value);
              }}
              value={reason}
            />
            {missing && (
              <Problem
                id="void-reason-err"
                text={ivt(language, "void_err_reason")}
              />
            )}
          </div>
        </>
      )}
      {outcome !== null && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>{ivt(language, outcome)}</p>
        </div>
      )}
    </Dialog>
  );
}
