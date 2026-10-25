// V1-058 R3: the Leases page of the rebuilt app. "#/leases" shows the list; "#/leases/<Lease
// id>" shows the Lease page. New Lease and the Lease actions stay in the earlier forms that App
// shows under this page until the next step moves them into the design.

import "../shell/screens.css";

import { useCallback, useEffect, useRef, useState } from "react";

import type { DepositApi } from "../depositClient";
import type { LeaseApi } from "../leaseClient";
import type { CustomerApi } from "../customerClient";
import type { ReservationApi } from "../reservationClient";
import type { UnitApi } from "../unitClient";
import { todayInPhnomPenh } from "../shell/format";
import { Icon } from "../shell/icons";
import { useHashDetail } from "../shell/useHashPage";
import type { Language } from "../signInText";
import type { LettersApi } from "../letters/lettersClient";
import { LeaseDetail } from "./LeaseDetail";
import type { ServiceSettingsApi } from "../settings/serviceSettingsClient";
import { LeaseForm, formModeOf } from "./LeaseForm";
import { LeasesList } from "./LeasesList";
import {
  DepositCell,
  LeasesData,
  loadDepositCells,
  loadLeasesData,
} from "./leasesData";
import { lt } from "./text";

export interface LeasesPageProps {
  language: Language;
  propertyId: string;
  /** Only the page that is shown loads; a hidden page waits until it is opened. */
  active: boolean;
  api: LeaseApi;
  depositApi: DepositApi;
  reservationApi: Pick<ReservationApi, "list" | "get">;
  customerApi: Pick<CustomerApi, "get" | "list">;
  unitApi: Pick<UnitApi, "list">;
  lettersApi: Pick<LettersApi, "warnings" | "notices" | "recordNotice">;
  capabilities: ReadonlySet<string> | null;
  /** The Services from Settings for the New Lease form; the real server when not given. */
  servicesApi?: Pick<ServiceSettingsApi, "read">;
}

export function LeasesPage({
  language,
  propertyId,
  active,
  api,
  depositApi,
  reservationApi,
  customerApi,
  unitApi,
  lettersApi,
  capabilities,
  servicesApi,
}: LeasesPageProps) {
  const detail = useHashDetail("leases");
  const [data, setData] = useState<LeasesData | null>(null);
  const [deposits, setDeposits] = useState<Map<string, DepositCell> | null>(
    null,
  );
  const [failed, setFailed] = useState(false);
  const sequence = useRef(0);
  const mayDeposits =
    capabilities === null || capabilities.has("deposits.read");

  const load = useCallback(() => {
    if (propertyId === "") return;
    const operation = ++sequence.current;
    setFailed(false);
    void loadLeasesData(api, propertyId)
      .then(async (loaded) => {
        if (operation !== sequence.current) return;
        setData(loaded);
        const cells = await loadDepositCells(
          depositApi,
          loaded.leases,
          mayDeposits,
        );
        if (operation === sequence.current) setDeposits(cells);
      })
      .catch(() => {
        if (operation === sequence.current) setFailed(true);
      });
  }, [api, depositApi, propertyId, mayDeposits]);

  // Another Property never shows the Leases of the one before.
  useEffect(() => {
    setData(null);
    setDeposits(null);
  }, [propertyId]);

  // Read again each time the page is opened, so it shows what others changed meanwhile.
  useEffect(() => {
    if (active && detail === null) load();
  }, [active, detail, load]);

  if (propertyId === "") {
    return (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>{lt(language, "no_property")}</p>
      </div>
    );
  }

  // New Lease and Renew read what they need themselves.
  const formMode = detail === null ? null : formModeOf(detail);
  if (formMode !== null) {
    return (
      <LeaseForm
        api={api}
        customerApi={customerApi}
        key={`${detail ?? ""}:${propertyId}`}
        language={language}
        mode={formMode}
        propertyId={propertyId}
        reservationApi={reservationApi}
        servicesApi={servicesApi}
        unitApi={unitApi}
      />
    );
  }

  // The Lease page reads its own record, so it does not wait for the list.
  if (detail !== null) {
    // "terminate:<id>" opens the Lease with its Terminate dialog (the Letters next step).
    const terminate = detail.startsWith("terminate:");
    return (
      <LeaseDetail
        api={api}
        capabilities={capabilities}
        depositApi={depositApi}
        key={`${detail}:${propertyId}`}
        language={language}
        leaseId={terminate ? detail.slice("terminate:".length) : detail}
        lettersApi={lettersApi}
        terminateOnOpen={terminate}
        propertyId={propertyId}
        reservationApi={reservationApi}
        customerApi={customerApi}
      />
    );
  }

  const failure = failed && (
    <div className="ui-notice warn" role="status">
      <Icon name="alert" />
      <p>{lt(language, "failed")}</p>
      <button className="ui-btn" onClick={load} type="button">
        {lt(language, "retry")}
      </button>
    </div>
  );
  if (data === null) {
    return (
      failure || (
        <p className="ui-muted" role="status">
          {lt(language, "loading")}
        </p>
      )
    );
  }
  return (
    <>
      {failure}
      <LeasesList
        canCreate={
          data.canCreate &&
          (capabilities === null || capabilities.has("leases.draft"))
        }
        data={data}
        deposits={deposits}
        language={language}
        today={todayInPhnomPenh()}
      />
    </>
  );
}
