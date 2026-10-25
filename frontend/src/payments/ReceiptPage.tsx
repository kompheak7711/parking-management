// V1-058 R5c-3: the Receipt page (mock-up "Receipt"): the printed Receipt at the size of its
// column, what the money paid with links to the Invoices, the reprints, Print Receipt, and
// Reprint, which records why a copy was made before it prints a copy marked REPRINT (one Receipt
// per payment; it never changes).

import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { InvoiceClientError } from "../invoiceClient";
import type { InvoicesData } from "../invoices/invoicesData";
import { SheetFrame } from "../invoices/InvoiceDocument";
import { dayText, momentText, usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import type { PaymentsApi, ReceiptView } from "./paymentsClient";
import { PaymentChip } from "./PaymentsList";
import { ReceiptDocument } from "./ReceiptDocument";
import { pyt } from "./text";

/** Prints only the Receipt sheet (invoiceDocument.css) on A5 paper, then the page is as before.
 * The A5 page size is added only while printing, because the sheet prints out of the page flow
 * and a named page would never apply to it. */
function printSheet() {
  document.body.classList.add("ui-printing");
  const size = document.createElement("style");
  size.textContent = "@media print { @page { size: A5; margin: 0; } }";
  document.head.appendChild(size);
  const done = () => {
    document.body.classList.remove("ui-printing");
    size.remove();
  };
  window.addEventListener("afterprint", done, { once: true });
  window.print();
}

type InvoiceKind =
  | "RENT"
  | "UTILITIES"
  | "SERVICE_CHARGES"
  | "MISCELLANEOUS_CHARGES"
  | "DAMAGE_CHARGES";

const LINE_NAMES = {
  LATE_PAYMENT_CHARGE: "pfl_row",
  DEPOSIT: "c_DEPOSIT",
  CREDIT: "c_CREDIT",
  REFUND: "rc_refunded",
} as const;

const REASONS = ["reason_lost", "reason_copy", "reason_other"] as const;
type ReasonKey = (typeof REASONS)[number];

function ReprintDialog({
  language,
  receipt,
  api,
  onClose,
  onSaved,
}: {
  language: Language;
  receipt: ReceiptView;
  api: Pick<PaymentsApi, "reprint">;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [reason, setReason] = useState<ReasonKey | "">("");
  const [more, setMore] = useState("");
  const [problems, setProblems] = useState<("reason" | "more")[]>([]);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<"failed" | "unknown" | null>(null);
  const keys = useRef(new Map<string, string>());
  // After a press with no answer the reprint may be recorded, so the reason is locked and the
  // next press sends the same key (one record).
  const locked = failed === "unknown";

  const save = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy || receipt.receiptId === null) return;
    const found: ("reason" | "more")[] = [];
    if (reason === "") found.push("reason");
    if (reason === "reason_other" && more.trim() === "") found.push("more");
    setProblems(found);
    if (reason === "" || found.length > 0) return;
    // The record keeps the English words, like every other reason in History.
    const words =
      pyt("en", reason) + (more.trim() === "" ? "" : `: ${more.trim()}`);
    // The same reason keeps its key, so pressing Reprint again after no answer records once.
    const key = keys.current.get(words) ?? crypto.randomUUID();
    keys.current.set(words, key);
    setBusy(true);
    setFailed(null);
    void api
      .reprint(receipt.receiptId, words, key)
      .then(onSaved)
      .catch((error: unknown) => {
        setFailed(
          !(error instanceof InvoiceClientError) || error.outcomeUnknown
            ? "unknown"
            : "failed",
        );
      })
      .finally(() => {
        setBusy(false);
      });
  };

  return (
    <Dialog
      busy={busy}
      closeLabel={pyt(language, "cancel")}
      onClose={onClose}
      onSubmit={save}
      submitLabel={pyt(language, "rc_reprint")}
      title={pyt(language, "dlg_rp_t", receipt.receiptNumber ?? "")}
    >
      <p>{pyt(language, "dlg_rp_c", receipt.receiptNumber ?? "")}</p>
      <div className="ui-field">
        <label htmlFor="rp-reason">
          {pyt(language, "reason")}
          <span className="req">{pyt(language, "required")}</span>
        </label>
        <select
          aria-describedby={
            problems.includes("reason") ? "rp-reason-err" : undefined
          }
          aria-invalid={problems.includes("reason")}
          disabled={locked}
          id="rp-reason"
          onChange={(event) => {
            setReason(event.currentTarget.value as ReasonKey | "");
          }}
          value={reason}
        >
          <option value="">{pyt(language, "reason_pick")}</option>
          {REASONS.map((key) => (
            <option key={key} value={key}>
              {pyt(language, key)}
            </option>
          ))}
        </select>
        {problems.includes("reason") && (
          <p className="ui-error" id="rp-reason-err">
            <Icon name="alert" small />
            <span>{pyt(language, "err_reason")}</span>
          </p>
        )}
      </div>
      <div className="ui-field">
        <label htmlFor="rp-more">
          {pyt(language, "reason_more")}
          <span className="req">
            {pyt(language, reason === "reason_other" ? "required" : "optional")}
          </span>
        </label>
        <textarea
          aria-describedby={
            problems.includes("more") ? "rp-more-err" : undefined
          }
          aria-invalid={problems.includes("more")}
          disabled={locked}
          id="rp-more"
          maxLength={900}
          onChange={(event) => {
            setMore(event.currentTarget.value);
          }}
          rows={2}
          value={more}
        />
        {problems.includes("more") && (
          <p className="ui-error" id="rp-more-err">
            <Icon name="alert" small />
            <span>{pyt(language, "err_reason_more")}</span>
          </p>
        )}
      </div>
      {failed !== null && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>
            {pyt(language, failed === "unknown" ? "rp_unknown" : "rp_failed")}
          </p>
        </div>
      )}
    </Dialog>
  );
}

export function ReceiptPage({
  language,
  propertyId,
  paymentId,
  api,
  data,
  namesFailed,
  onRetryNames,
  mayReprint,
}: {
  language: Language;
  propertyId: string;
  paymentId: string;
  api: Pick<PaymentsApi, "receipt" | "reprint">;
  data: InvoicesData | null;
  /** The Customer names could not be read; the Receipt does not print without them. */
  namesFailed: boolean;
  onRetryNames: () => void;
  mayReprint: boolean;
}) {
  const [receipt, setReceipt] = useState<ReceiptView | null>(null);
  const [problem, setProblem] = useState<"missing" | "failed" | null>(null);
  const [reprinting, setReprinting] = useState(false);
  // Each reprint is a new object, so a second reprint on the same day prints too.
  const [copy, setCopy] = useState<{ day: string } | null>(null);
  const sequence = useRef(0);

  const load = useCallback(() => {
    const operation = ++sequence.current;
    setProblem(null);
    api
      .receipt(propertyId, paymentId)
      .then((loaded) => {
        if (operation === sequence.current) setReceipt(loaded);
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        // A Payment id that is not one (422) is missing too; trying again never helps.
        setProblem(
          error instanceof InvoiceClientError &&
            (error.status === 404 || error.status === 422)
            ? "missing"
            : "failed",
        );
      });
  }, [api, paymentId, propertyId]);

  useEffect(load, [load]);

  // A reprint prints after the page shows the copy marked REPRINT.
  useEffect(() => {
    if (copy !== null) printSheet();
  }, [copy]);

  const back = (
    <a className="ui-crumb" href={hashForPage("payments")}>
      <Icon name="back" small />
      {pyt(language, "back")}
    </a>
  );

  if (problem !== null)
    return (
      <>
        {back}
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>
            {pyt(language, problem === "missing" ? "rc_missing" : "failed")}
          </p>
          {problem === "failed" && (
            <button className="ui-btn" onClick={load} type="button">
              {pyt(language, "retry")}
            </button>
          )}
        </div>
      </>
    );
  if (receipt === null)
    return (
      <>
        {back}
        <p className="ui-muted" role="status">
          {pyt(language, "loading")}
        </p>
      </>
    );

  const name = data?.names.get(receipt.customerId) ?? null;
  const unit = data?.customerUnits.get(receipt.customerId) ?? "";
  // Once a Receipt was reprinted, every print is marked REPRINT with the day of the last one
  // (mock-up receiptDoc), so Print Receipt never makes an unmarked second original.
  const lastReprint = receipt.reprints[receipt.reprints.length - 1];
  const reprintDay =
    copy?.day ??
    (lastReprint === undefined
      ? null
      : momentText(lastReprint.at).slice(0, 10));
  const ready = data !== null;

  return (
    <>
      {back}
      <div className="ui-head">
        <div>
          <div className="ui-hrow">
            <h2 className="ui-num">
              {pyt(language, "rc_title", receipt.receiptNumber ?? "—")}
            </h2>
            <PaymentChip
              language={language}
              row={{
                status: receipt.status,
                left: receipt.left,
                usdCents: receipt.usdCents,
              }}
            />
          </div>
          <p>
            {[name ?? "—", unit, usdFromCents(receipt.usdCents)]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
        <div className="ui-actions">
          <button
            className="ui-btn"
            disabled={!ready}
            onClick={printSheet}
            type="button"
          >
            <Icon name="print" />
            {pyt(language, "rc_print")}
          </button>
          {mayReprint && receipt.receiptId !== null && (
            <button
              className="ui-btn"
              disabled={!ready}
              onClick={() => {
                setReprinting(true);
              }}
              type="button"
            >
              <Icon name="invoice" />
              {pyt(language, "rc_reprint")}
            </button>
          )}
        </div>
      </div>
      {namesFailed && (
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{pyt(language, "rc_names_failed")}</p>
          <button className="ui-btn" onClick={onRetryNames} type="button">
            {pyt(language, "retry")}
          </button>
        </div>
      )}
      {receipt.status === "REVERSED" && (
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{pyt(language, "rc_reversed")}</p>
        </div>
      )}
      {copy !== null && (
        <div className="ui-notice ok" role="status">
          <Icon name="check" />
          <p>{pyt(language, "rp_saved")}</p>
        </div>
      )}
      <div className="ui-split ui-split-receipt">
        <SheetFrame>
          <ReceiptDocument
            name={name}
            receipt={receipt}
            reprint={reprintDay}
            unit={unit}
          />
        </SheetFrame>
        <div className="ui-stack">
          <section aria-labelledby="h-mt" className="ui-card">
            <h3 id="h-mt">{pyt(language, "rc_matched_to")}</h3>
            {receipt.lines.length === 0 ? (
              <p className="ui-muted">{pyt(language, "rc_not_matched")}</p>
            ) : (
              <ul className="ui-apps">
                {receipt.lines.map((line, index) => {
                  const invoiceLink =
                    line.invoiceId === null ? null : (
                      <a
                        className="ui-num"
                        href={hashForPage("invoices", `inv:${line.invoiceId}`)}
                      >
                        {line.invoiceNumber}
                      </a>
                    );
                  return (
                    <li key={index}>
                      <span>
                        {line.kind === "INVOICE" ? (
                          <>
                            {invoiceLink}
                            {line.category !== null &&
                              ` · ${pyt(language, line.category as InvoiceKind)}`}
                          </>
                        ) : (
                          pyt(language, LINE_NAMES[line.kind])
                        )}
                        {line.kind === "LATE_PAYMENT_CHARGE" ? (
                          <small>
                            {pyt(language, "rc_on")} {invoiceLink}
                          </small>
                        ) : (
                          line.dueDate !== null && (
                            <small className="ui-num">
                              {dayText(line.dueDate)}
                            </small>
                          )
                        )}
                      </span>
                      <b className="ui-num">{usdFromCents(line.amount)}</b>
                    </li>
                  );
                })}
              </ul>
            )}
            {receipt.left > 0 && (
              <p className="ui-small ui-warnv">
                {pyt(language, "pf_left", usdFromCents(receipt.left))}
              </p>
            )}
          </section>
          <section aria-labelledby="h-rr" className="ui-card">
            <h3 id="h-rr">{pyt(language, "rc_reprints")}</h3>
            {receipt.reprints.length === 0 ? (
              <p className="ui-muted">{pyt(language, "rc_noreprints")}</p>
            ) : (
              <ul className="ui-apps">
                {receipt.reprints.map((reprint, index) => (
                  <li key={index}>
                    <span>
                      {pyt(
                        language,
                        "rp_row",
                        momentText(reprint.at),
                        reprint.by,
                        reprint.reason,
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <div className="ui-notice info">
            <Icon name="info" />
            <p>{pyt(language, "rc_one")}</p>
          </div>
        </div>
      </div>
      {reprinting && (
        <ReprintDialog
          api={api}
          language={language}
          onClose={() => {
            setReprinting(false);
          }}
          onSaved={() => {
            setReprinting(false);
            load();
            setCopy({ day: momentText(new Date().toISOString()).slice(0, 10) });
          }}
          receipt={receipt}
        />
      )}
    </>
  );
}
