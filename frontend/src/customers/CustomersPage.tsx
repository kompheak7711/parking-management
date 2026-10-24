// V1-058 R2: the Customers page of the rebuilt app. "#/customers" shows the list;
// "#/customers/<Customer id>" shows the Customer page. Adding, Edit contact and deactivating
// still use the earlier form that App shows under this page until step C2.

import "../shell/screens.css";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { CustomerApi } from "../customerClient";
import type { CustomerLedgerApi } from "../customerLedgerClient";
import type { LeaseApi } from "../leaseClient";
import type { ReservationApi } from "../reservationClient";
import { todayInPhnomPenh } from "../shell/format";
import { Icon } from "../shell/icons";
import { useHashDetail } from "../shell/useHashPage";
import type { Language } from "../signInText";
import { CustomerDetail } from "./CustomerDetail";
import { CustomersList, ServerMatch } from "./CustomersList";
import { ct } from "./text";
import { CustomersData, loadCustomersData, standingOf } from "./customersData";

export interface CustomersPageProps {
  language: Language;
  propertyId: string;
  actorId: string;
  /** Only the page that is shown loads; a hidden page waits until it is opened. */
  active: boolean;
  customerApi: CustomerApi;
  ledgerApi: CustomerLedgerApi;
  leaseApi: LeaseApi;
  reservationApi: ReservationApi;
  capabilities: ReadonlySet<string> | null;
  onOpenLedger: ((customerId: string) => void) | null;
}

export function CustomersPage({
  language,
  propertyId,
  actorId,
  active,
  customerApi,
  ledgerApi,
  leaseApi,
  reservationApi,
  capabilities,
  onOpenLedger,
}: CustomersPageProps) {
  const detail = useHashDetail("customers");
  const [data, setData] = useState<CustomersData | null>(null);
  const [failed, setFailed] = useState(false);
  const [serverMatch, setServerMatch] = useState<ServerMatch | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchFailed, setSearchFailed] = useState(false);
  const sequence = useRef(0);
  const searchSequence = useRef(0);

  const load = useCallback(() => {
    if (propertyId === "") return;
    const operation = ++sequence.current;
    setFailed(false);
    void loadCustomersData(
      { customerApi, leaseApi, reservationApi },
      propertyId,
    )
      .then((loaded) => {
        if (operation === sequence.current) setData(loaded);
      })
      .catch(() => {
        if (operation === sequence.current) setFailed(true);
      });
  }, [customerApi, leaseApi, propertyId, reservationApi]);

  // Another Property never shows the Customers of the one before.
  useEffect(() => {
    setData(null);
    setServerMatch(null);
    setSearchFailed(false);
  }, [propertyId]);

  // Read again each time the page is opened, so it shows what others changed meanwhile.
  useEffect(() => {
    if (active) load();
  }, [active, load]);

  const standings = useMemo(() => {
    const today = todayInPhnomPenh();
    return new Map(
      (data?.customers ?? []).map((customer) => [
        customer.customer_id,
        standingOf(
          data ?? { leases: null, reservations: null },
          customer.customer_id,
          today,
        ),
      ]),
    );
  }, [data]);

  function search(text: string) {
    const operation = ++searchSequence.current;
    setSearching(true);
    setSearchFailed(false);
    void (async () => {
      const ids = new Set<string>();
      let cursor: string | undefined;
      // The server finds a whole ID or passport number, which the list never shows.
      for (let page = 0; page < 10; page += 1) {
        const result = await customerApi.list(propertyId, {
          query: text,
          ...(cursor === undefined ? {} : { cursor }),
        });
        for (const item of result.items) ids.add(item.customer_id);
        if (result.next_cursor === null) break;
        cursor = result.next_cursor;
      }
      return ids;
    })()
      .then((ids) => {
        if (operation === searchSequence.current) setServerMatch({ text, ids });
      })
      .catch(() => {
        if (operation === searchSequence.current) setSearchFailed(true);
      })
      .finally(() => {
        if (operation === searchSequence.current) setSearching(false);
      });
  }

  if (propertyId === "") {
    return (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>{ct(language, "no_property")}</p>
      </div>
    );
  }
  if (failed && data === null) {
    return (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>{ct(language, "failed")}</p>
        <button className="ui-btn" onClick={load} type="button">
          {ct(language, "retry")}
        </button>
      </div>
    );
  }
  if (data === null) {
    return (
      <p className="ui-muted" role="status">
        {ct(language, "loading")}
      </p>
    );
  }

  if (detail !== null) {
    return (
      <CustomerDetail
        actorId={actorId}
        capabilities={capabilities}
        customerApi={customerApi}
        customerId={detail}
        data={data}
        key={detail}
        language={language}
        ledgerApi={ledgerApi}
        onOpenLedger={onOpenLedger}
        propertyId={propertyId}
      />
    );
  }

  return (
    <>
      {failed && (
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{ct(language, "failed")}</p>
          <button className="ui-btn" onClick={load} type="button">
            {ct(language, "retry")}
          </button>
        </div>
      )}
      {searchFailed && (
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{ct(language, "search_failed")}</p>
        </div>
      )}
      <CustomersList
        data={data}
        language={language}
        onSearch={search}
        searching={searching}
        serverMatch={serverMatch}
        standings={standings}
      />
    </>
  );
}
