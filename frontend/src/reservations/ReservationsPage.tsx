// V1-058 R3: the Reservations page of the rebuilt app. "#/reservations" shows the list;
// "#/reservations/<Reservation id>" shows the Reservation page. V1-060 B6: Make Reservation is a
// dialog on the list ("#/reservations/new", or "#/reservations/new:<Unit id>" from a Unit page).

import "../shell/screens.css";

import { useCallback, useEffect, useRef, useState } from "react";

import type { CustomerApi } from "../customerClient";
import type { CustomerCommandGate } from "../customers/commands";
import type { PaymentsApi } from "../payments/paymentsClient";
import type { ReservationApi } from "../reservationClient";
import { todayInPhnomPenh } from "../shell/format";
import { Icon } from "../shell/icons";
import { openPageInAddress, useHashDetail } from "../shell/useHashPage";
import type { Language } from "../signInText";
import type { UnitApi } from "../unitClient";
import { MakeReservationDialog } from "./MakeReservationDialog";
import { ReservationDetail } from "./ReservationDetail";
import { ReservationsList } from "./ReservationsList";
import { ReservationsData, loadReservationsData } from "./reservationsData";
import { rt } from "./text";

export interface ReservationsPageProps {
  language: Language;
  propertyId: string;
  /** Only the page that is shown loads; a hidden page waits until it is opened. */
  active: boolean;
  api: ReservationApi;
  capabilities: ReadonlySet<string> | null;
  /** V1-060 B6: what Make Reservation needs; without them the button is not shown. */
  unitApi?: Pick<UnitApi, "list">;
  customerApi?: CustomerApi;
  paymentsApi?: PaymentsApi;
  customerGate?: CustomerCommandGate;
}

/** "new" or "new:<Unit id>" opens Make Reservation; null for any other address. */
function makeOf(detail: string | null): { unitId?: string } | null {
  if (detail === "new") return {};
  if (detail?.startsWith("new:") === true) return { unitId: detail.slice(4) };
  return null;
}

export function ReservationsPage({
  language,
  propertyId,
  active,
  api,
  capabilities,
  unitApi,
  customerApi,
  paymentsApi,
  customerGate,
}: ReservationsPageProps) {
  const detail = useHashDetail("reservations");
  const [data, setData] = useState<ReservationsData | null>(null);
  const [failed, setFailed] = useState(false);
  const sequence = useRef(0);

  const load = useCallback(() => {
    if (propertyId === "") return;
    const operation = ++sequence.current;
    setFailed(false);
    void loadReservationsData(api, propertyId)
      .then((loaded) => {
        if (operation === sequence.current) setData(loaded);
      })
      .catch(() => {
        if (operation === sequence.current) setFailed(true);
      });
  }, [api, propertyId]);

  // Another Property never shows the Reservations of the one before.
  useEffect(() => {
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
        <p>{rt(language, "no_property")}</p>
      </div>
    );
  }

  const make = makeOf(detail);
  // Unknown capabilities show the button; the server still refuses what is not allowed.
  const mayMake =
    unitApi !== undefined &&
    customerApi !== undefined &&
    paymentsApi !== undefined &&
    (capabilities === null ||
      (capabilities.has("reservations.create") &&
        capabilities.has("payments.record")));
  const dialog = make !== null && mayMake && (
    <MakeReservationDialog
      api={api}
      customerApi={customerApi}
      gate={
        capabilities === null || capabilities.has("customers.manage")
          ? customerGate
          : undefined
      }
      language={language}
      mayLowerRent={
        capabilities === null ? null : capabilities.has("rent.below_default")
      }
      mayOverride={
        capabilities === null
          ? null
          : capabilities.has("reservation_deposits.override")
      }
      onClose={() => {
        // V1-060 B7 (third review): a Reservation may be saved after a lost answer.
        load();
        openPageInAddress("reservations");
      }}
      onSaved={(saved) => {
        load();
        openPageInAddress("reservations", true, saved.reservation_id);
      }}
      paymentsApi={paymentsApi}
      propertyId={propertyId}
      unitApi={unitApi}
      unitId={make.unitId}
    />
  );

  // The Reservation page reads its own record, so it does not wait for the list.
  if (detail !== null && make === null) {
    return (
      <ReservationDetail
        api={api}
        capabilities={capabilities}
        key={detail}
        language={language}
        onChanged={load}
        propertyId={propertyId}
        reservationId={detail}
      />
    );
  }

  const failure = failed && (
    <div className="ui-notice warn" role="status">
      <Icon name="alert" />
      <p>{rt(language, "failed")}</p>
      <button className="ui-btn" onClick={load} type="button">
        {rt(language, "retry")}
      </button>
    </div>
  );
  // The dialog keeps one place, so what was typed (and money already saved) stays while the
  // list arrives (V1-060 B7).
  if (data === null) {
    return (
      <>
        {dialog}
        {failure || (
          <p className="ui-muted" role="status">
            {rt(language, "loading")}
          </p>
        )}
      </>
    );
  }
  return (
    <>
      {dialog}
      {failure}
      <ReservationsList
        action={
          mayMake && (
            <button
              className="ui-btn primary"
              onClick={() => {
                openPageInAddress("reservations", false, "new");
              }}
              type="button"
            >
              <Icon name="plus" small />
              {rt(language, "make")}
            </button>
          )
        }
        data={data}
        language={language}
        today={todayInPhnomPenh()}
      />
    </>
  );
}
