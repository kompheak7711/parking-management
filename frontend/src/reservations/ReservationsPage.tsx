// V1-058 R3: the Reservations page of the rebuilt app. "#/reservations" shows the list;
// "#/reservations/<Reservation id>" shows the Reservation page. V1-060 B6: Make Reservation is a
// dialog on the list ("#/reservations/new", or "#/reservations/new:<Unit id>" from a Unit page).
// Telegram step 3c (DL-173): "#/reservations/visit:<Visit request id>" opens it with the person
// of a Visit request; once saved, the request becomes this Reservation.

import "../shell/screens.css";

import { useCallback, useEffect, useRef, useState } from "react";

import type { CustomerApi } from "../customerClient";
import type { CustomerCommandGate } from "../customers/commands";
import type { PaymentsApi } from "../payments/paymentsClient";
import type { ReservationApi } from "../reservationClient";
import {
  type TelegramApi,
  telegramApi as defaultTelegramApi,
} from "../telegram/telegramClient";
import { todayInPhnomPenh } from "../shell/format";
import { Icon } from "../shell/icons";
import { openPageInAddress, useHashDetail } from "../shell/useHashPage";
import type { Language } from "../signInText";
import type { UnitApi } from "../unitClient";
import {
  MakeReservationDialog,
  type VisitPrefill,
} from "./MakeReservationDialog";
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
  /** Telegram step 3c: reads the Visit request and records that it became a Reservation. */
  visitApi?: Pick<TelegramApi, "visitRequest" | "visitStep">;
}

/** "new", "new:<Unit id>" or "visit:<Visit request id>" opens Make Reservation; null for any
 * other address. */
function makeOf(
  detail: string | null,
): { unitId?: string; visitId?: string } | null {
  if (detail === "new") return {};
  if (detail?.startsWith("new:") === true) return { unitId: detail.slice(4) };
  if (detail?.startsWith("visit:") === true)
    return { visitId: detail.slice(6) };
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
  visitApi = defaultTelegramApi,
}: ReservationsPageProps) {
  const detail = useHashDetail("reservations");
  const visitId = makeOf(detail)?.visitId;
  // The Visit request: undefined while it is read, null when it could not be read.
  const [visit, setVisit] = useState<VisitPrefill | null | undefined>(
    undefined,
  );
  useEffect(() => {
    if (visitId === undefined || propertyId === "") return;
    let current = true;
    setVisit(undefined);
    visitApi.visitRequest(propertyId, visitId).then(
      (found) => {
        if (current)
          setVisit({
            number: found.number,
            name: found.name,
            phone: found.phone,
            email: found.email,
          });
      },
      () => {
        if (current) setVisit(null);
      },
    );
    return () => {
      current = false;
    };
  }, [visitApi, propertyId, visitId]);
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
  // V1.1 step 2b (DL-119): today's Reservation rules come with the list; until it arrives the
  // form uses the earlier values and follows the rules when they come (the server checks too).
  const dialog = make !== null &&
    mayMake &&
    (make.visitId === undefined || visit !== undefined) && (
      <MakeReservationDialog
        api={api}
        rules={data?.rules}
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
          if (make.visitId !== undefined)
            // The Reservation is saved; a failure here leaves the request open to mark again.
            void visitApi
              .visitStep(propertyId, make.visitId, "reserve", {
                reservation_id: saved.reservation_id,
              })
              .catch(() => undefined);
          openPageInAddress("reservations", true, saved.reservation_id);
        }}
        paymentsApi={paymentsApi}
        propertyId={propertyId}
        unitApi={unitApi}
        unitId={make.unitId}
        visit={visit ?? undefined}
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
