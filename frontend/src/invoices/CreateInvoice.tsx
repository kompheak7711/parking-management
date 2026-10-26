// V1-058 R5: Create Invoice (DESIGN.md "Create Invoice and Draft Invoices"). Only a one-time
// Miscellaneous charge is typed here; a Damage charge comes from a Move-out inspection finding.
// Saving records the approved charge and makes a Draft Invoice from it, in two requests that
// keep their ids and keys while the form is unchanged, so "Save" again after an unknown result
// is saved once.

import { type FormEvent, type ReactNode, useRef, useState } from "react";

import {
  InvoiceClientError,
  type InvoiceApi,
  type InvoiceResource,
} from "../invoiceClient";
import { usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { openPageInAddress } from "../shell/useHashPage";
import { Chip, Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import { type InvoicesData, centsOf } from "./invoicesData";
import { ivt, type InvoicesTextKey } from "./text";

type Field = "cust" | "desc" | "amt" | "reason" | "src";

const IDS: Record<Field, string> = {
  cust: "ni-cust",
  desc: "ni-desc",
  amt: "ni-amt",
  reason: "ni-reason",
  src: "ni-src",
};

const ERRORS: Record<Field, InvoicesTextKey> = {
  cust: "ni_err_cust",
  desc: "ni_err_desc",
  amt: "err_amount",
  reason: "ni_err_reason",
  src: "ni_err_src",
};

type Outcome = "unknown" | "refused" | null;

export function CreateInvoice({
  language,
  propertyId,
  api,
  data,
  onSaved,
}: {
  language: Language;
  propertyId: string;
  api: Pick<InvoiceApi, "recordOneTimeCharge" | "create">;
  data: InvoicesData;
  /** The list reads again, so it shows the new Draft. */
  onSaved: () => void;
}) {
  const [kind, setKind] = useState<"MISC" | "DAMAGE">("MISC");
  const [customer, setCustomer] = useState("");
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [source, setSource] = useState("");
  const [problems, setProblems] = useState<Field[] | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>(null);
  const [done, setDone] = useState<InvoiceResource | null>(null);
  const summary = useRef<HTMLDivElement>(null);
  // One charge id and two keys for these exact values; a change makes a new request.
  const identity = useRef<{
    sent: string;
    charge: string;
    key: string;
    draftKey: string;
  } | null>(null);

  const customers = [...data.customerLeases.keys()]
    .map((id) => ({
      id,
      name: data.names.get(id) ?? ivt(language, "unknown_customer"),
      unit: data.customerUnits.get(id) ?? "",
    }))
    .sort(
      (left, right) =>
        left.unit.localeCompare(right.unit, undefined, { numeric: true }) ||
        left.name.localeCompare(right.name),
    );
  const cents = centsOf(amount);
  const chosen = customers.find((entry) => entry.id === customer);

  const check = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const found: Field[] = [];
    if (chosen === undefined) found.push("cust");
    if (description.trim() === "") found.push("desc");
    if (cents === null) found.push("amt");
    if (reason.trim() === "") found.push("reason");
    if (source.trim() === "") found.push("src");
    setProblems(found);
    if (found.length > 0) {
      // The summary takes the focus, so a screen reader reads what to fix.
      setTimeout(() => summary.current?.focus(), 0);
      return;
    }
    setOutcome(null);
    setConfirming(true);
  };

  const save = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (chosen === undefined || cents === null || busy) return;
    const leaseId = data.customerLeases.get(chosen.id) ?? null;
    const input = {
      category: "MISCELLANEOUS_CHARGES" as const,
      customer_id: chosen.id,
      lease_id: leaseId,
      inspection_damage_finding_id: null,
      description: description.trim(),
      amount: { currency: "USD" as const, minor_units: cents },
      reason: reason.trim(),
      evidence_reference: source.trim(),
    };
    const sent = JSON.stringify(input);
    if (identity.current?.sent !== sent)
      identity.current = {
        sent,
        charge: crypto.randomUUID(),
        key: crypto.randomUUID(),
        draftKey: crypto.randomUUID(),
      };
    const { charge, key, draftKey } = identity.current;
    setBusy(true);
    setOutcome(null);
    void api
      .recordOneTimeCharge(propertyId, { ...input, charge_id: charge }, key)
      .then((recorded) =>
        api.create(propertyId, recorded.obligation_id, draftKey),
      )
      .then((draft) => {
        setDone(draft);
        setConfirming(false);
        onSaved();
      })
      .catch((error: unknown) => {
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

  const back = (
    <button
      className="ui-crumb"
      onClick={() => {
        openPageInAddress("invoices");
      }}
      type="button"
    >
      <Icon name="back" small />
      {ivt(language, "back")}
    </button>
  );

  if (done !== null) {
    return (
      <>
        <div className="ui-head">
          <div className="ui-hrow">
            <h2>{ivt(language, "ni_done_t")}</h2>
            <Chip tone="info">{ivt(language, "st_draft")}</Chip>
          </div>
        </div>
        <section className="ui-card">
          <div className="ui-notice ok" role="status">
            <Icon name="check" />
            <p>
              {ivt(
                language,
                "ni_done_b",
                chosen?.name ?? "",
                chosen?.unit ?? "",
                description.trim(),
                usdFromCents(cents ?? 0),
              )}
            </p>
          </div>
          <div className="ui-actions">
            <a
              className="ui-btn primary"
              href={hashForPage("invoices", `inv:${done.id}`)}
            >
              <Icon name="invoice" />
              {ivt(language, "ni_open")}
            </a>
            <button
              className="ui-btn"
              onClick={() => {
                openPageInAddress("invoices");
              }}
              type="button"
            >
              {ivt(language, "ni_to_list")}
            </button>
          </div>
        </section>
      </>
    );
  }

  const shown = new Set(problems ?? []);
  const field = (
    name: Field,
    label: InvoicesTextKey,
    input: ReactNode,
    help?: InvoicesTextKey,
  ) => (
    <div className="ui-field">
      <label htmlFor={IDS[name]}>
        {ivt(language, label)}
        <span className="req">{ivt(language, "required")}</span>
      </label>
      {input}
      {help !== undefined && (
        <p className="help" id={`${IDS[name]}-help`}>
          {ivt(language, help)}
        </p>
      )}
      {shown.has(name) && (
        <p className="ui-error" id={`${IDS[name]}-err`}>
          <Icon name="alert" small />
          <span>{ivt(language, ERRORS[name])}</span>
        </p>
      )}
    </div>
  );
  const describedBy = (name: Field, help: boolean) =>
    [help ? `${IDS[name]}-help` : "", shown.has(name) ? `${IDS[name]}-err` : ""]
      .filter(Boolean)
      .join(" ") || undefined;

  return (
    <>
      {back}
      <div className="ui-head">
        <div>
          <h2>{ivt(language, "ni_btn")}</h2>
          <p>{ivt(language, "ni_intro")}</p>
        </div>
      </div>
      <div className="ui-split">
        <form
          aria-label={ivt(language, "ni_btn")}
          className="ui-card ui-form ui-pageform"
          noValidate
          onSubmit={check}
        >
          {problems !== null && problems.length > 0 && (
            <div
              className="ui-notice err"
              ref={summary}
              role="alert"
              tabIndex={-1}
            >
              <Icon name="alert" />
              <div>
                <b>{ivt(language, "err_sum", problems.length)}</b>
                <ul>
                  {problems.map((name) => (
                    <li key={name}>
                      <a
                        href={`#${IDS[name]}`}
                        onClick={(event) => {
                          event.preventDefault();
                          document.getElementById(IDS[name])?.focus();
                        }}
                      >
                        {ivt(language, ERRORS[name])}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
          <div className="ui-field">
            <span className="lbl" id="ni-kind">
              {ivt(language, "ni_kind")}
            </span>
            <div aria-labelledby="ni-kind" className="ui-seg" role="group">
              {(
                [
                  ["MISC", "MISCELLANEOUS_CHARGES"],
                  ["DAMAGE", "DAMAGE_CHARGES"],
                ] as const
              ).map(([value, key]) => (
                <button
                  aria-pressed={kind === value}
                  key={value}
                  onClick={() => {
                    setKind(value);
                  }}
                  type="button"
                >
                  {ivt(language, key)}
                </button>
              ))}
            </div>
          </div>
          {kind === "DAMAGE" ? (
            <div className="ui-notice" role="note">
              <Icon name="info" />
              <p>{ivt(language, "ni_damage")}</p>
            </div>
          ) : customers.length === 0 ? (
            <div className="ui-notice warn" role="status">
              <Icon name="alert" />
              <p>{ivt(language, "ni_none")}</p>
            </div>
          ) : (
            <>
              {field(
                "cust",
                "f_customer",
                <select
                  aria-describedby={describedBy("cust", true)}
                  aria-invalid={shown.has("cust")}
                  id={IDS.cust}
                  onChange={(event) => {
                    setCustomer(event.currentTarget.value);
                  }}
                  value={customer}
                >
                  <option value="">{ivt(language, "f_choose")}</option>
                  {customers.map((entry) => (
                    <option key={entry.id} value={entry.id}>
                      {entry.unit === ""
                        ? entry.name
                        : `${entry.name} · ${entry.unit}`}
                    </option>
                  ))}
                </select>,
                "ni_cust_help",
              )}
              {field(
                "desc",
                "ni_desc",
                <input
                  aria-describedby={describedBy("desc", true)}
                  aria-invalid={shown.has("desc")}
                  autoComplete="off"
                  id={IDS.desc}
                  maxLength={80}
                  onChange={(event) => {
                    setDescription(event.currentTarget.value);
                  }}
                  value={description}
                />,
                "ni_desc_help",
              )}
              {field(
                "amt",
                "ni_amt",
                <div className="ui-money">
                  <span aria-hidden="true">$</span>
                  <input
                    aria-describedby={describedBy("amt", true)}
                    aria-invalid={shown.has("amt")}
                    autoComplete="off"
                    id={IDS.amt}
                    inputMode="decimal"
                    onChange={(event) => {
                      setAmount(event.currentTarget.value);
                    }}
                    value={amount}
                  />
                </div>,
                "ni_amt_help",
              )}
              {field(
                "reason",
                "ni_reason",
                <input
                  aria-describedby={describedBy("reason", false)}
                  aria-invalid={shown.has("reason")}
                  autoComplete="off"
                  id={IDS.reason}
                  maxLength={500}
                  onChange={(event) => {
                    setReason(event.currentTarget.value);
                  }}
                  value={reason}
                />,
              )}
              {field(
                "src",
                "ni_src",
                <input
                  aria-describedby={describedBy("src", true)}
                  aria-invalid={shown.has("src")}
                  autoComplete="off"
                  id={IDS.src}
                  maxLength={500}
                  onChange={(event) => {
                    setSource(event.currentTarget.value);
                  }}
                  value={source}
                />,
                "ni_src_help",
              )}
              <div className="ui-actions">
                <button className="ui-btn primary" type="submit">
                  <Icon name="check" />
                  {ivt(language, "ni_submit")}
                </button>
                <button
                  className="ui-btn"
                  onClick={() => {
                    openPageInAddress("invoices");
                  }}
                  type="button"
                >
                  {ivt(language, "cancel")}
                </button>
              </div>
            </>
          )}
        </form>
        <div className="ui-stack">
          <section aria-labelledby="ni-next" className="ui-card">
            <h2 id="ni-next">{ivt(language, "ni_what_t")}</h2>
            <ol className="ui-steps">
              <li>{ivt(language, "ni_w1")}</li>
              <li>{ivt(language, "ni_w2")}</li>
              <li>{ivt(language, "ni_w3")}</li>
              <li>{ivt(language, "ni_w4")}</li>
            </ol>
          </section>
        </div>
      </div>
      {confirming && chosen !== undefined && cents !== null && (
        <Dialog
          busy={busy}
          closeLabel={ivt(language, "cancel")}
          onClose={() => {
            setConfirming(false);
          }}
          onSubmit={save}
          submitLabel={ivt(language, "ni_submit")}
          title={ivt(language, "ni_dlg_t")}
        >
          <dl className="ui-kv">
            <dt>{ivt(language, "ni_kind")}</dt>
            <dd>{ivt(language, "MISCELLANEOUS_CHARGES")}</dd>
            <dt>{ivt(language, "f_customer")}</dt>
            <dd>
              {chosen.unit === ""
                ? chosen.name
                : `${chosen.name} · ${chosen.unit}`}
            </dd>
            <dt>{ivt(language, "ni_desc")}</dt>
            <dd>{description.trim()}</dd>
            <dt>{ivt(language, "ni_amt")}</dt>
            <dd className="ui-num">{usdFromCents(cents)}</dd>
            <dt>{ivt(language, "ni_reason")}</dt>
            <dd>{reason.trim()}</dd>
            <dt>{ivt(language, "ni_src")}</dt>
            <dd>{source.trim()}</dd>
          </dl>
          <p>{ivt(language, "ni_dlg_c")}</p>
          {outcome !== null && (
            <div className="ui-notice warn" role="alert">
              <Icon name="alert" />
              <p>{ivt(language, outcome)}</p>
            </div>
          )}
        </Dialog>
      )}
    </>
  );
}
