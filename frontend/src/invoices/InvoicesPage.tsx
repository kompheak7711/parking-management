// V1-058 R5: the Invoices page of the rebuilt app. "#/invoices" shows the list;
// "#/invoices/inv:<id>" one Invoice; "#/invoices/for:<Customer id>" the list for one Customer.
// Create Invoice, issue, adjust, void and the billing runs stay in the earlier forms that App
// shows under this page until the next steps move them into the design.

import "../shell/screens.css";

import { useCallback, useEffect, useRef, useState } from "react";

import type { CustomerApi } from "../customerClient";
import type { InvoiceApi } from "../invoiceClient";
import type { LeaseApi } from "../leaseClient";
import { todayInPhnomPenh } from "../shell/format";
import { Icon } from "../shell/icons";
import { openPageInAddress, useHashDetail } from "../shell/useHashPage";
import type { Language } from "../signInText";
import { InvoiceDetail } from "./InvoiceDetail";
import { InvoicesList } from "./InvoicesList";
import { type InvoicesData, loadInvoicesData } from "./invoicesData";
import { ivt } from "./text";

export interface InvoicesPageProps {
  language: Language;
  propertyId: string;
  /** Only the page that is shown loads; a hidden page waits until it is opened. */
  active: boolean;
  invoiceApi: Pick<InvoiceApi, "list" | "get">;
  leaseApi: Pick<LeaseApi, "list">;
  customerApi: Pick<CustomerApi, "list">;
  capabilities: ReadonlySet<string> | null;
  /** Today in Phnom Penh; tests pass a fixed day. */
  today?: string;
}

export function InvoicesPage({
  language,
  propertyId,
  active,
  invoiceApi,
  leaseApi,
  customerApi,
  capabilities,
  today: fixedToday,
}: InvoicesPageProps) {
  const detail = useHashDetail("invoices");
  const invoiceId =
    detail?.startsWith("inv:") === true ? detail.slice(4) : null;
  const customerId =
    detail?.startsWith("for:") === true ? detail.slice(4) : null;
  const today = fixedToday ?? todayInPhnomPenh();
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

  // Another Property never shows the Invoices of the one before.
  useEffect(() => {
    sequence.current++;
    setData(null);
  }, [propertyId]);

  // Read again each time the page is opened, so it shows what others changed meanwhile.
  useEffect(() => {
    if (active) load();
  }, [active, load]);

  if (propertyId === "") {
    return (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>{ivt(language, "no_property")}</p>
      </div>
    );
  }

  // The Invoice page reads its own record, so it does not wait for the list.
  if (invoiceId !== null) {
    return (
      <InvoiceDetail
        api={invoiceApi}
        capabilities={capabilities}
        data={data}
        invoiceId={invoiceId}
        key={`${invoiceId}:${propertyId}`}
        propertyId={propertyId}
        language={language}
        today={today}
      />
    );
  }

  const failure = failed && (
    <div className="ui-notice warn" role="status">
      <Icon name="alert" />
      <p>{ivt(language, "failed")}</p>
      <button className="ui-btn" onClick={load} type="button">
        {ivt(language, "retry")}
      </button>
    </div>
  );
  if (data === null) {
    return (
      failure || (
        <p className="ui-muted" role="status">
          {ivt(language, "loading")}
        </p>
      )
    );
  }
  return (
    <>
      {failure}
      <InvoicesList
        customerId={customerId}
        data={data}
        language={language}
        onClearCustomer={() => {
          openPageInAddress("invoices");
        }}
        today={today}
      />
    </>
  );
}
