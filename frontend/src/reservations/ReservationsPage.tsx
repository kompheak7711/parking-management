// V1-058 R3: the Reservations page of the rebuilt app. "#/reservations" shows the list;
// "#/reservations/<Reservation id>" shows the Reservation page. Make Reservation receives the
// deposit, so it stays in the earlier form that App shows under this page until step R5.

import "../shell/screens.css";

import { useCallback, useEffect, useRef, useState } from "react";

import type { ReservationApi } from "../reservationClient";
import { todayInPhnomPenh } from "../shell/format";
import { Icon } from "../shell/icons";
import { useHashDetail } from "../shell/useHashPage";
import type { Language } from "../signInText";
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
}

export function ReservationsPage({
  language,
  propertyId,
  active,
  api,
  capabilities,
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

  // The Reservation page reads its own record, so it does not wait for the list.
  if (detail !== null) {
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
  if (data === null) {
    return (
      failure || (
        <p className="ui-muted" role="status">
          {rt(language, "loading")}
        </p>
      )
    );
  }
  return (
    <>
      {failure}
      <ReservationsList
        data={data}
        language={language}
        today={todayInPhnomPenh()}
      />
    </>
  );
}
