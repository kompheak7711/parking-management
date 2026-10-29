// V1-058 R2: the Units page of the rebuilt app. "#/units" shows the list; "#/units/<Unit id>"
// shows the Unit page.

import "../shell/screens.css";

import { useCallback, useEffect, useRef, useState } from "react";

import type { LeaseApi } from "../leaseClient";
import type { ReservationApi } from "../reservationClient";
import { todayInPhnomPenh } from "../shell/format";
import { Icon } from "../shell/icons";
import { openPageInAddress, useHashDetail } from "../shell/useHashPage";
import type { Language } from "../signInText";
import type { UnitApi, UnitResource } from "../unitClient";
import { NewUnitDialog } from "./UnitDialogs";
import { UnitDetail } from "./UnitDetail";
import { UnitsList } from "./UnitsList";
import { ut } from "./text";
import { type UtilityPricesApi, UtilityPricesStrip } from "./UtilityPrices";
import { UnitsData, loadUnitsData, reservationFor } from "./unitsData";

export interface UnitsPageProps {
  language: Language;
  propertyId: string;
  /** Only the page that is shown loads; a hidden page waits until it is opened. */
  active: boolean;
  unitApi: UnitApi;
  leaseApi: LeaseApi;
  reservationApi: ReservationApi;
  capabilities: ReadonlySet<string> | null;
  /** V1-061: the Utility prices and the Unit's Meters. */
  utilityApi: UtilityPricesApi;
}

export function UnitsPage({
  language,
  propertyId,
  active,
  unitApi,
  leaseApi,
  reservationApi,
  capabilities,
  utilityApi,
}: UnitsPageProps) {
  const detail = useHashDetail("units");
  const [data, setData] = useState<UnitsData | null>(null);
  const [failed, setFailed] = useState(false);
  const [adding, setAdding] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const sequence = useRef(0);

  const load = useCallback(() => {
    if (propertyId === "") return;
    const operation = ++sequence.current;
    setFailed(false);
    void loadUnitsData({ unitApi, leaseApi, reservationApi }, propertyId)
      .then((loaded) => {
        if (operation === sequence.current) setData(loaded);
      })
      .catch(() => {
        if (operation === sequence.current) setFailed(true);
      });
  }, [leaseApi, propertyId, reservationApi, unitApi]);

  // Read again each time the page is opened, so it shows what others changed meanwhile.
  useEffect(() => {
    if (active) load();
  }, [active, load]);

  function changed(unit: UnitResource) {
    setData((current) =>
      current === null
        ? current
        : {
            ...current,
            units: current.units.map((entry) =>
              entry.unit_id === unit.unit_id ? unit : entry,
            ),
          },
    );
  }

  if (propertyId === "") {
    return (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>{ut(language, "no_property")}</p>
      </div>
    );
  }
  if (failed && data === null) {
    return (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>{ut(language, "failed")}</p>
        <button className="ui-btn" onClick={load} type="button">
          {ut(language, "retry")}
        </button>
      </div>
    );
  }
  if (data === null) {
    return (
      <p className="ui-muted" role="status">
        {ut(language, "loading")}
      </p>
    );
  }

  if (detail !== null) {
    return (
      <UnitDetail
        canManage={data.canManage}
        capabilities={capabilities}
        key={detail}
        language={language}
        leaseApi={leaseApi}
        lists={data.lists}
        onChanged={changed}
        propertyId={propertyId}
        reservation={reservationFor(data, detail)}
        tenanciesKnown={data.leases !== null && data.reservations !== null}
        unitApi={unitApi}
        unitId={detail}
        utilityApi={utilityApi}
      />
    );
  }

  const lists = data.lists;
  return (
    <>
      {notice !== null && (
        <div className="ui-notice ok" role="status">
          <Icon name="check" />
          <p>{notice}</p>
        </div>
      )}
      {data.canManage && lists === null && (
        <div className="ui-notice warn">
          <Icon name="alert" />
          <p>{ut(language, "lists_failed")}</p>
        </div>
      )}
      <UtilityPricesStrip
        allowed={capabilities === null || capabilities.has("utility.read")}
        api={utilityApi}
        language={language}
        propertyId={propertyId}
        today={todayInPhnomPenh()}
      />
      <UnitsList
        data={data}
        language={language}
        onNewUnit={
          data.canManage && lists !== null
            ? () => {
                setNotice(null);
                setAdding(true);
              }
            : null
        }
      />
      {adding && lists !== null && (
        <NewUnitDialog
          api={unitApi}
          language={language}
          lists={lists}
          onClose={() => {
            setAdding(false);
          }}
          onCreated={(unit) => {
            setAdding(false);
            setNotice(ut(language, "new_saved", unit.unit_number));
            setData((current) =>
              current === null
                ? current
                : { ...current, units: [...current.units, unit] },
            );
            load();
            openPageInAddress("units", false, unit.unit_id);
          }}
          propertyId={propertyId}
        />
      )}
    </>
  );
}
