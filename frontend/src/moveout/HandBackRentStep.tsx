// DL-229 (D1, owner 12 Nov 2026): after a hand-back before the 5th, the monthly Rent Invoice of
// that month goes down to the days used, for every tenant alike. What was paid for the other
// days becomes Customer Credit. After a hand-back on or after the 25th, next month's Invoice
// has no day used: it is made Void when nothing is paid, and paid money comes back as Customer
// Credit. The server decides every amount (BR-RENT-012); this step shows the server's
// assessment and sends the same numbers back, so a change in between is refused.

import { type FormEvent, useEffect, useRef, useState } from "react";

import type { InvoiceApi, InvoiceResource } from "../invoiceClient";
import {
  type SettlementApi,
  SettlementRequestError,
} from "../settlementClient";
import { dayText, usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { serverWords } from "../shell/serverText";
import type { Language } from "../signInText";
import { type Keys, keyFor } from "./ChargeDialogs";
import { Kv } from "./parts";
import { mt } from "./text";

const MAX_PAGES = 5;
const ISSUED = new Set(["UNPAID", "PARTIALLY_PAID", "PAID"]);

/** The first day of the month whose Rent Invoice the hand-back day decides; null: no month. */
export function handBackRentMonth(day: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return null;
  const year = Number(day.slice(0, 4));
  const month = Number(day.slice(5, 7));
  const dayOfMonth = Number(day.slice(8, 10));
  if (dayOfMonth < 5) return `${day.slice(0, 7)}-01`;
  if (dayOfMonth < 25) return null;
  const next = month === 12 ? [year + 1, 1] : [year, month + 1];
  return `${String(next[0])}-${String(next[1]).padStart(2, "0")}-01`;
}

export interface HandBackAssessment {
  action: "KEEP" | "VOID" | "CREDIT_ADJUSTMENT";
  next_month: boolean;
  invoice_version: number;
  days_used: number;
  days_in_month: number;
  outstanding_usd_cents: number;
  kept_usd_cents: number;
  credit_usd_cents: number;
  released_usd_cents: number;
}

/** The server's assessment, or null when the answer cannot be read. */
export function assessmentOf(
  record: Record<string, unknown>,
): HandBackAssessment | null {
  const whole = (value: unknown): value is number =>
    typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
  const {
    action,
    coverage,
    invoice_version,
    days_used,
    days_in_month,
    outstanding_usd_cents,
    kept_usd_cents,
    credit_usd_cents,
    released_usd_cents,
  } = record;
  if (
    (action !== "KEEP" &&
      action !== "VOID" &&
      action !== "CREDIT_ADJUSTMENT") ||
    (coverage !== "HAND_BACK_MONTH" && coverage !== "NEXT_MONTH") ||
    !whole(invoice_version) ||
    !whole(days_used) ||
    !whole(days_in_month) ||
    !whole(outstanding_usd_cents) ||
    !whole(kept_usd_cents) ||
    !whole(credit_usd_cents) ||
    !whole(released_usd_cents)
  )
    return null;
  return {
    action,
    next_month: coverage === "NEXT_MONTH",
    invoice_version,
    days_used,
    days_in_month,
    outstanding_usd_cents,
    kept_usd_cents,
    credit_usd_cents,
    released_usd_cents,
  };
}

function periodStart(invoice: InvoiceResource): string | null {
  const period = invoice.billing_period;
  if (typeof period !== "object" || period === null || Array.isArray(period))
    return null;
  return typeof period.start === "string" ? period.start : null;
}

type State =
  | { state: "none" | "loading" | "failed" }
  | { state: "shown"; invoice: InvoiceResource; shown: HandBackAssessment };

export function HandBackRentStep({
  language,
  propertyId,
  leaseId,
  handBackDay,
  invoiceApi,
  settlementApi,
  capabilities,
  onDone,
}: {
  language: Language;
  propertyId: string;
  leaseId: string;
  /** The hand-back day in force (YYYY-MM-DD). */
  handBackDay: string;
  invoiceApi: Pick<InvoiceApi, "list">;
  settlementApi: Pick<SettlementApi, "handBackAssessment" | "resolveHandBack">;
  capabilities: ReadonlySet<string> | null;
  /** The Invoice was changed: the page says so and reads its records again. */
  onDone: (message: string) => void;
}) {
  const [found, setFound] = useState<State>({ state: "none" });
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [reads, setReads] = useState(0);
  const keys = useRef<Keys>(new Map());
  const may = (capability: string) =>
    capabilities === null || capabilities.has(capability);
  const mayRead = may("invoices.read") && may("leases.read");
  const month = handBackRentMonth(handBackDay);

  useEffect(() => {
    if (month === null || !mayRead) {
      setFound({ state: "none" });
      return;
    }
    let current = true;
    setFound({ state: "loading" });
    void (async () => {
      const invoices: InvoiceResource[] = [];
      let cursor: string | undefined;
      for (let count = 0; count < MAX_PAGES; count += 1) {
        const next = await invoiceApi.list(propertyId, {
          lease_id: leaseId,
          category: "RENT",
          ...(cursor === undefined ? {} : { cursor }),
        });
        invoices.push(...next.items);
        if (next.next_cursor === null) break;
        cursor = next.next_cursor;
      }
      const invoice = invoices.find(
        (item) => ISSUED.has(item.status) && periodStart(item) === month,
      );
      if (invoice === undefined) return { state: "none" } as const;
      const shown = assessmentOf(
        await settlementApi.handBackAssessment(invoice.id),
      );
      return shown === null
        ? ({ state: "failed" } as const)
        : ({ state: "shown", invoice, shown } as const);
    })()
      .catch((error: unknown) =>
        // Refused: the rule does not cover this Lease or Invoice, or this person may not see it.
        error instanceof SettlementRequestError &&
        error.status >= 400 &&
        error.status < 500
          ? ({ state: "none" } as const)
          : ({ state: "failed" } as const),
      )
      .then((next) => {
        if (current) setFound(next);
      });
    return () => {
      current = false;
    };
  }, [invoiceApi, settlementApi, propertyId, leaseId, month, mayRead, reads]);

  if (found.state === "none") return null;
  if (found.state === "loading")
    return (
      <p className="ui-small ui-muted" role="status">
        {mt(language, "hbr_loading")}
      </p>
    );
  if (found.state !== "shown")
    return <p className="ui-small ui-muted">{mt(language, "hbr_failed")}</p>;

  const { invoice, shown } = found;
  const link = (
    <a href={hashForPage("invoices", `inv:${invoice.id}`)}>
      {mt(language, "open_invoice")}
    </a>
  );
  if (shown.action === "KEEP")
    return (
      <p className="ui-small">
        {mt(
          language,
          "hbr_kept",
          invoice.invoice_number,
          usdFromCents(shown.kept_usd_cents),
        )}{" "}
        {link}
      </p>
    );

  const voids = shown.action === "VOID";
  const mayAct = may(voids ? "invoices.void" : "invoices.adjust");
  const offered = mt(
    language,
    "hbr_reason_default",
    dayText(handBackDay),
    shown.days_used,
    shown.days_in_month,
  );
  const said = reason.trim() === "" ? offered : reason.trim();

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !mayAct) return;
    setBusy(true);
    setProblem(null);
    const version = shown.invoice_version;
    settlementApi
      .resolveHandBack(
        invoice.id,
        version,
        {
          action: voids ? "VOID" : "CREDIT_ADJUSTMENT",
          expected_outstanding_usd_cents: shown.outstanding_usd_cents,
          expected_credit_usd_cents: shown.credit_usd_cents,
          reason: said,
        },
        // After a lost answer the same key and version are sent again.
        keyFor(
          keys.current,
          "resolve",
          `${invoice.id}:${String(version)}:${said}`,
        ),
      )
      .then(() => {
        onDone(
          mt(
            language,
            voids ? "hbr_done_void" : "hbr_done",
            invoice.invoice_number,
            usdFromCents(shown.kept_usd_cents),
          ),
        );
        setReads((count) => count + 1);
      })
      .catch((error: unknown) => {
        if (
          error instanceof SettlementRequestError &&
          error.status >= 400 &&
          error.status < 500
        ) {
          setProblem(serverWords(language, error));
          // The amounts or the Invoice changed: show the new numbers.
          if (error.status === 409 || error.status === 412)
            setReads((count) => count + 1);
        } else setProblem(mt(language, "c_unknown"));
      })
      .finally(() => {
        setBusy(false);
      });
  }

  return (
    <form aria-labelledby="hbr-title" className="ui-stack" onSubmit={submit}>
      <p id="hbr-title">
        <strong>{mt(language, "hbr_t")}</strong>{" "}
        {shown.next_month
          ? mt(language, "hbr_next", invoice.invoice_number)
          : mt(
              language,
              "hbr_days",
              invoice.invoice_number,
              shown.days_used,
              shown.days_in_month,
            )}{" "}
        {link}
      </p>
      <Kv
        rows={[
          [
            mt(language, "hbr_now"),
            usdFromCents(shown.kept_usd_cents + shown.credit_usd_cents),
          ],
          [mt(language, "hbr_keep"), usdFromCents(shown.kept_usd_cents)],
          [mt(language, "hbr_off"), usdFromCents(shown.credit_usd_cents)],
          [mt(language, "hbr_back"), usdFromCents(shown.released_usd_cents)],
          [
            mt(language, "hbr_owed"),
            usdFromCents(
              voids
                ? 0
                : shown.outstanding_usd_cents -
                    (shown.credit_usd_cents - shown.released_usd_cents),
            ),
          ],
        ]}
      />
      {problem !== null && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>{problem}</p>
        </div>
      )}
      {mayAct ? (
        <>
          <div className="ui-field">
            <label htmlFor="hbr-reason">{mt(language, "hbr_reason")}</label>
            <input
              autoComplete="off"
              id="hbr-reason"
              maxLength={500}
              onChange={(event) => {
                setReason(event.target.value);
              }}
              placeholder={offered}
              value={reason}
            />
            <p className="help">{mt(language, "hbr_reason_help")}</p>
          </div>
          <div className="ui-actions">
            <button className="ui-btn primary" disabled={busy} type="submit">
              {busy
                ? mt(language, "saving")
                : mt(language, voids ? "hbr_btn_void" : "hbr_btn")}
            </button>
          </div>
        </>
      ) : (
        <p className="ui-small ui-muted">
          {mt(language, voids ? "hbr_no_void" : "hbr_no_adjust")}
        </p>
      )}
    </form>
  );
}
