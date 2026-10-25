// V1-058 R5c: the Payments page of the rebuilt app. "#/payments/receive" (or
// "#/payments/receive:<Customer id>") is Receive payment. The payment list, matching, Credit and
// refunds stay in the earlier forms that App shows under this page until the next steps.

import "../shell/screens.css";

import { useCallback, useEffect, useRef, useState } from "react";

import type { CustomerApi } from "../customerClient";
import type { InvoiceApi } from "../invoiceClient";
import { type InvoicesData, loadInvoicesData } from "../invoices/invoicesData";
import type { LeaseApi } from "../leaseClient";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { useHashDetail } from "../shell/useHashPage";
import type { Language } from "../signInText";
import type { PaymentsApi } from "./paymentsClient";
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
  const customerId =
    detail?.startsWith("receive:") === true ? detail.slice(8) : "";
  const mayReceive =
    capabilities === null || capabilities.has("payments.record");
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

  useEffect(() => {
    if (active && receiving) load();
  }, [active, load, receiving]);

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
        key={`${propertyId}:${customerId}`}
        language={language}
        onSaved={load}
        propertyId={propertyId}
      />
    );
  }

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
