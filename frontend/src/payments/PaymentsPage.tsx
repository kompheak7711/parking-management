// V1-058 R5c: the Payments page of the rebuilt app: the list with its eight cards,
// "#/payments/receive" (or "#/payments/receive:<Customer id>") for Receive payment, and
// "#/payments/receipt:<Payment id>" for a Receipt. Matching, Credit and refunds stay in the
// earlier forms that App shows under this page until the next steps.

import "../shell/screens.css";

import { useCallback, useEffect, useRef, useState } from "react";

import type { CustomerApi } from "../customerClient";
import type { InvoiceApi } from "../invoiceClient";
import { type InvoicesData, loadInvoicesData } from "../invoices/invoicesData";
import type { LeaseApi } from "../leaseClient";
import { Icon } from "../shell/icons";
import { todayInPhnomPenh } from "../shell/format";
import { hashForPage } from "../shell/navigation";
import { useHashDetail } from "../shell/useHashPage";
import type { Language } from "../signInText";
import type { PaymentsApi } from "./paymentsClient";
import { PaymentsList } from "./PaymentsList";
import { ReceiptPage } from "./ReceiptPage";
import { ReceivePayment } from "./ReceivePayment";
import { pyt } from "./text";

export interface PaymentsPageProps {
  language: Language;
  propertyId: string;
  /** Only the page that is shown loads; a hidden page waits until it is opened. */
  active: boolean;
  paymentsApi: PaymentsApi;
  invoiceApi: Pick<InvoiceApi, "list">;
  leaseApi: Pick<LeaseApi, "list">;
  customerApi: Pick<CustomerApi, "list">;
  capabilities: ReadonlySet<string> | null;
}

export function PaymentsPage({
  language,
  propertyId,
  active,
  paymentsApi,
  invoiceApi,
  leaseApi,
  customerApi,
  capabilities,
}: PaymentsPageProps) {
  const detail = useHashDetail("payments");
  const receiving =
    detail === "receive" || detail?.startsWith("receive:") === true;
  // "receive:<Customer id>:<late-payment charge id>" opens the form with only that charge ticked.
  const [customerId = "", chargeId = ""] =
    detail?.startsWith("receive:") === true ? detail.slice(8).split(":") : [];
  const receiptOf =
    detail?.startsWith("receipt:") === true ? detail.slice(8) : null;
  const may = (capability: string) =>
    capabilities === null || capabilities.has(capability);
  const mayReceive = may("payments.record");
  const mayList = may("payments.read");
  const [data, setData] = useState<InvoicesData | null>(null);
  const [failed, setFailed] = useState(false);
  const sequence = useRef(0);

  const load = useCallback(() => {
    if (propertyId === "") return;
    const operation = ++sequence.current;
    setFailed(false);
    void loadInvoicesData({ invoiceApi, leaseApi, customerApi }, propertyId)
      .then((loaded) => {
        if (operation === sequence.current) setData(loaded);
      })
      .catch(() => {
        if (operation === sequence.current) setFailed(true);
      });
  }, [customerApi, invoiceApi, leaseApi, propertyId]);

  // Another Property never shows the Customers of the one before.
  useEffect(() => {
    sequence.current++;
    setData(null);
  }, [propertyId]);

  // The list and the Receipt use the Customer names and Units too.
  useEffect(() => {
    if (active) load();
  }, [active, load]);

  if (propertyId === "") {
    return (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>{pyt(language, "no_property")}</p>
      </div>
    );
  }

  if (receiving && mayReceive) {
    if (failed)
      return (
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{pyt(language, "failed")}</p>
          <button className="ui-btn" onClick={load} type="button">
            {pyt(language, "retry")}
          </button>
        </div>
      );
    if (data === null)
      return (
        <p className="ui-muted" role="status">
          {pyt(language, "loading")}
        </p>
      );
    return (
      <ReceivePayment
        api={paymentsApi}
        data={data}
        initialCustomer={data.customerLeases.has(customerId) ? customerId : ""}
        initialPick={chargeId}
        key={`${propertyId}:${customerId}:${chargeId}`}
        language={language}
        onSaved={load}
        propertyId={propertyId}
      />
    );
  }

  if (receiptOf !== null && may("receipts.read"))
    return (
      <ReceiptPage
        api={paymentsApi}
        data={data}
        key={`${propertyId}:${receiptOf}`}
        language={language}
        mayReprint={may("receipts.reprint")}
        namesFailed={failed}
        onRetryNames={load}
        paymentId={receiptOf}
        propertyId={propertyId}
      />
    );

  if (mayList && active)
    return (
      <PaymentsList
        api={paymentsApi}
        data={data}
        key={propertyId}
        language={language}
        mayReceive={mayReceive}
        propertyId={propertyId}
        today={todayInPhnomPenh()}
      />
    );

  return (
    <div className="ui-head">
      <div>
        <h2>{pyt(language, "pay_title")}</h2>
      </div>
      {mayReceive && (
        <div className="ui-actions">
          <a
            className="ui-btn primary"
            href={hashForPage("payments", "receive")}
          >
            <Icon name="payments" />
            {pyt(language, "rp_title")}
          </a>
        </div>
      )}
    </div>
  );
}
