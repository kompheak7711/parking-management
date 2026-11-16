// UI v81 (design v81 "Customer" card): one Customer beside a record or a form: the name with a
// status chip, the role and Unit, the phone, "Paid on time" (migration 20270711_362), the
// Customer Credit and the Unpaid Invoices (the Customer's ledger position), and "Open Customer".
// First built for the Lease page (pilot, owner 08/11/2026 06:55); the Payments pages use the same
// card (module batch 2). Display only: it reads, it changes nothing.

import { type ReactNode, useEffect, useState } from "react";

import type { CustomerApi, CustomerDetail } from "../customerClient";
import {
  ledgerMoney,
  type CustomerLedgerApi,
  type LedgerPosition,
} from "../customerLedgerClient";
// The card's words were written for the Lease page and stay in one place.
import { lt } from "../leases/text";
import type { PaidOnTime, reportsApi } from "../reportsClient";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { Chip } from "../shell/ui";
import type { Language } from "../signInText";

type Read<T> = "reading" | "failed" | T;

export interface CustomerSideCardProps {
  language: Language;
  customerId: string;
  /** The name to show until the Customer is read, or when the read is not allowed. */
  fallbackName: string;
  propertyId: string;
  /** The id of the card's title, for the page's outline. */
  headingId: string;
  /** The chip beside the name (the Lease's status); a deactivated Customer says so instead. */
  chip?: ReactNode;
  /** The line under the name, such as "Primary Tenant · U101". */
  role?: ReactNode;
  customerApi: Pick<CustomerApi, "get">;
  /** The Customer's ledger position (Credit, Unpaid Invoices); left out, the rows say so. */
  ledgerApi?: Pick<CustomerLedgerApi, "read">;
  actorId?: string;
  /** "Paid on time"; left out, the row says so. */
  reports?: Pick<typeof reportsApi, "customerPaidOnTime">;
  mayCustomers: boolean;
  mayInvoices: boolean;
}

function initials(name: string): string {
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((word) => word.charAt(0).toUpperCase())
    .join("");
}

export function CustomerSideCard({
  language,
  customerId,
  fallbackName,
  propertyId,
  headingId,
  chip,
  role,
  customerApi,
  ledgerApi,
  actorId,
  reports,
  mayCustomers,
  mayInvoices,
}: CustomerSideCardProps) {
  const [customer, setCustomer] = useState<Read<CustomerDetail>>("reading");
  const [position, setPosition] = useState<Read<LedgerPosition | null>>(
    ledgerApi === undefined || actorId === undefined ? "failed" : "reading",
  );
  const [onTime, setOnTime] = useState<Read<PaidOnTime>>(
    reports === undefined || !mayInvoices ? "failed" : "reading",
  );

  useEffect(() => {
    let live = true;
    const controller = new AbortController();
    setCustomer("reading");
    if (mayCustomers) {
      // A client without `get` (older callers) counts as a failed read, not a crash.
      void Promise.resolve()
        .then(() => customerApi.get(customerId))
        .then((loaded) => {
          if (live) setCustomer(loaded);
        })
        .catch(() => {
          if (live) setCustomer("failed");
        });
    } else {
      setCustomer("failed");
    }
    if (ledgerApi !== undefined && actorId !== undefined) {
      setPosition("reading");
      // One ledger line is enough: every page carries the Customer's position.
      void ledgerApi
        .read(
          { section: "history", customerId, limit: 1 },
          { actorId, propertyId, signal: controller.signal },
        )
        .then((reply) => {
          if (live)
            setPosition(reply.section === "customers" ? null : reply.position);
        })
        .catch(() => {
          if (live) setPosition("failed");
        });
    }
    if (reports !== undefined && mayInvoices) {
      setOnTime("reading");
      void reports
        .customerPaidOnTime(propertyId, customerId)
        .then((loaded) => {
          if (live) setOnTime(loaded);
        })
        .catch(() => {
          if (live) setOnTime("failed");
        });
    }
    return () => {
      live = false;
      controller.abort();
    };
  }, [
    actorId,
    customerApi,
    customerId,
    ledgerApi,
    mayCustomers,
    mayInvoices,
    propertyId,
    reports,
  ]);

  const name =
    customer === "reading" || customer === "failed"
      ? fallbackName
      : customer.legal_name;
  const phone =
    customer === "reading" ? (
      <span className="ui-muted">{lt(language, "cu_loading")}</span>
    ) : customer === "failed" ? (
      <span className="ui-muted">{lt(language, "cu_failed")}</span>
    ) : customer.phone_number === null || customer.phone_number === "" ? (
      <span className="ui-muted">—</span>
    ) : (
      <span className="ui-num">{customer.phone_number}</span>
    );
  const owed =
    position !== "reading" && position !== "failed" && position !== null
      ? position.total_owed_usd_cents
      : null;
  const owing = owed !== null && Number(owed) > 0;
  const money = (value: string | null, state: Read<unknown>) =>
    state === "reading" ? (
      <span className="ui-muted">{lt(language, "cu_loading")}</span>
    ) : value === null ? (
      <span className="ui-muted">{lt(language, "cu_failed")}</span>
    ) : (
      <span className="ui-num">{ledgerMoney(value)}</span>
    );

  return (
    <section aria-labelledby={headingId} className="ui-card">
      <div className="ui-chead">
        <h2 id={headingId}>{lt(language, "cu_title")}</h2>
        {mayCustomers && (
          <a
            className="ui-btn link"
            href={hashForPage("customers", customerId)}
          >
            {lt(language, "cu_open")}
          </a>
        )}
      </div>
      <div className="ui-who">
        <span aria-hidden="true" className="ui-who-av">
          {initials(name)}
        </span>
        <div>
          <div className="ui-hrow">
            <b className="ui-who-name">{name}</b>
            {customer !== "reading" &&
            customer !== "failed" &&
            !customer.active ? (
              <Chip tone="neutral">{lt(language, "cu_inactive")}</Chip>
            ) : (
              chip
            )}
          </div>
          {role !== undefined && role !== null && role !== "" && (
            <p className="ui-small ui-muted">{role}</p>
          )}
        </div>
      </div>
      <dl className="ui-kv2 ui-cu">
        <dt>
          <Icon name="phone" small />
          {lt(language, "cu_phone")}
        </dt>
        <dd>{phone}</dd>
        <dt>
          <Icon name="check" small />
          {lt(language, "cu_ontime")}
        </dt>
        <dd>
          {onTime === "reading" ? (
            <span className="ui-muted">{lt(language, "cu_loading")}</span>
          ) : onTime === "failed" ? (
            <span className="ui-muted">{lt(language, "cu_failed")}</span>
          ) : onTime.invoice_count === 0 ? (
            <span className="ui-muted">{lt(language, "cu_ontime_none")}</span>
          ) : (
            <span className="ui-num">
              {lt(
                language,
                "cu_ontime_v",
                String(onTime.on_time),
                String(onTime.invoice_count),
              )}
            </span>
          )}
        </dd>
        <dd className="note">{lt(language, "cu_ontime_note")}</dd>
        <dt>
          <Icon name="payments" small />
          {lt(language, "cu_credit")}
        </dt>
        <dd>
          {money(
            position !== "reading" && position !== "failed" && position !== null
              ? position.credit_usd_cents
              : null,
            position,
          )}
        </dd>
      </dl>
      <div className={owing ? "ui-well owed" : "ui-well"}>
        <div className="line">
          <b>
            <Icon name="alert" small />
            {lt(language, "cu_unpaid")}
          </b>
          <b>{money(owed, position)}</b>
        </div>
      </div>
    </section>
  );
}
