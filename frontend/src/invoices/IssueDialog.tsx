// V1-058 R5: Issue a Draft Invoice (DESIGN.md "Create Invoice and Draft Invoices"). The Draft
// gets its number and is owed from now. The Due Date follows the Settings rule unless the
// Manager chooses another date with a reason (BR-INV-011, BR-INV-018); the server checks it.

import { type FormEvent, useRef, useState } from "react";

import {
  InvoiceClientError,
  type InvoiceApi,
  type InvoiceResource,
} from "../invoiceClient";
import { DateInput, isDay } from "../shell/DateInput";
import { usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import { cents } from "./invoicesData";
import { ivt } from "./text";

export function IssueDialog({
  language,
  api,
  invoice,
  name,
  today,
  onClose,
  onSaved,
  onChanged,
}: {
  language: Language;
  api: Pick<InvoiceApi, "issue">;
  invoice: InvoiceResource;
  name: string | null;
  today: string;
  onClose: () => void;
  onSaved: (issued: InvoiceResource) => void;
  /** The Invoice changed meanwhile; the page reads it again. */
  onChanged: () => void;
}) {
  const [other, setOther] = useState(false);
  const [due, setDue] = useState("");
  const [reason, setReason] = useState("");
  const [problems, setProblems] = useState<("date" | "reason")[]>([]);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<"unknown" | "refused" | null>(null);
  const keys = useRef(new Map<string, string>());

  const save = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy) return;
    const found: ("date" | "reason")[] = [];
    if (other) {
      if (!isDay(due) || due < today) found.push("date");
      if (reason.trim() === "") found.push("reason");
    }
    setProblems(found);
    if (found.length > 0) return;
    const chosen = other
      ? { due_date: due, due_date_reason: reason.trim() }
      : undefined;
    // The same request keeps its key, so pressing Issue again after no answer issues once.
    const sent = JSON.stringify(chosen ?? null);
    const key = keys.current.get(sent) ?? crypto.randomUUID();
    keys.current.set(sent, key);
    setBusy(true);
    setOutcome(null);
    void api
      .issue(invoice.id, invoice.version, key, chosen)
      .then(onSaved)
      .catch((error: unknown) => {
        if (
          error instanceof InvoiceClientError &&
          !error.outcomeUnknown &&
          (error.status === 409 || error.status === 412)
        ) {
          onChanged();
          return;
        }
        setOutcome(
          error instanceof InvoiceClientError && !error.outcomeUnknown
            ? "refused"
            : "unknown",
        );
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
      submitLabel={ivt(language, "act_issue")}
      title={ivt(language, "iss_t")}
    >
      <p>
        {ivt(
          language,
          "iss_b",
          name ?? ivt(language, "unknown_customer"),
          usdFromCents(cents(invoice.adjusted_total)),
        )}
      </p>
      <p className="ui-muted">{ivt(language, "iss_rule")}</p>
      <label className="ui-chk">
        <input
          checked={other}
          onChange={(event) => {
            setOther(event.currentTarget.checked);
          }}
          type="checkbox"
        />
        {ivt(language, "iss_other")}
      </label>
      {other && (
        <>
          <div className="ui-field">
            <label htmlFor="iss-date">{ivt(language, "iss_date")}</label>
            <DateInput
              language={language}
              describedBy={
                problems.includes("date") ? "iss-date-err" : undefined
              }
              invalid={problems.includes("date")}
              id="iss-date"
              min={today}
              onChange={(value) => {
                setDue(value);
              }}
              value={due}
            />
            {problems.includes("date") && (
              <p className="ui-error" id="iss-date-err">
                <Icon name="alert" small />
                <span>{ivt(language, "iss_err_date")}</span>
              </p>
            )}
          </div>
          <div className="ui-field">
            <label htmlFor="iss-reason">{ivt(language, "iss_reason")}</label>
            <input
              aria-describedby={
                problems.includes("reason") ? "iss-reason-err" : undefined
              }
              aria-invalid={problems.includes("reason")}
              autoComplete="off"
              id="iss-reason"
              maxLength={500}
              onChange={(event) => {
                setReason(event.currentTarget.value);
              }}
              value={reason}
            />
            {problems.includes("reason") && (
              <p className="ui-error" id="iss-reason-err">
                <Icon name="alert" small />
                <span>{ivt(language, "iss_err_reason")}</span>
              </p>
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
