// Parking Step 4 (owner 2026-10-30): the vehicle takes the Occupancy slot of a Lease. One
// vehicle at a time; the vehicle of the Primary Tenant or a Signer moves in; Change vehicle ends
// the old vehicle's row and starts the new one the same day; the only vehicle never moves out
// alone (it leaves with the Lease at Move-out). Hidden names stay Property Rental's.
import { FormEvent, ReactNode, useEffect, useState } from "react";

import type { CustomerApi, VehicleResource } from "../customerClient";
import { vehicleTypeText } from "../customers/text";
import {
  type LeaseApi,
  LeaseConflictError,
  LeaseRefusedError,
  type LeaseResource,
  LeaseUnavailableError,
  type OccupancyResource,
} from "../leaseClient";
import { DateInput, isDay } from "../shell/DateInput";
import { dayText, todayInPhnomPenh } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { serverWords } from "../shell/serverText";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import { Problem, useValuesIdentity } from "./LeaseDialogs";
import { lt } from "./text";

const MOVE_IN_REASON = "Vehicle moved in";

/** The Occupancy rows that carry a vehicle, the one moved in now first. */
export function vehicleRows(lease: LeaseResource): OccupancyResource[] {
  return lease.occupancies
    .filter(
      (occupancy) =>
        occupancy.vehicle_id !== null && occupancy.vehicle_id !== undefined,
    )
    .sort((left, right) =>
      left.move_out_date === null && right.move_out_date !== null
        ? -1
        : right.move_out_date === null && left.move_out_date !== null
          ? 1
          : right.move_in_date.localeCompare(left.move_in_date),
    );
}

export function VehicleCard({
  language,
  lease,
  mayChange,
  customerLink,
  onChange,
}: {
  language: Language;
  lease: LeaseResource;
  mayChange: boolean;
  customerLink: (customerId: string, name: string) => ReactNode;
  onChange: () => void;
}) {
  const rows = vehicleRows(lease);
  return (
    <section aria-labelledby="lease-vehicle" className="ui-card">
      <div className="ui-chead">
        <h2 id="lease-vehicle">{lt(language, "vehicle")}</h2>
        {mayChange && (
          <button className="ui-btn" onClick={onChange} type="button">
            <Icon name="swap" />
            {lt(language, "change_vehicle")}
          </button>
        )}
      </div>
      {rows.length === 0 ? (
        <p className="ui-muted">{lt(language, "v_none")}</p>
      ) : (
        <ul className="ui-plain">
          {rows.map((row) => (
            <li className="ui-line" key={row.occupancy_id}>
              <span>
                <b className="ui-num">{row.plate_text}</b>
                {" · "}
                <span>
                  {row.vehicle_type === null || row.vehicle_type === undefined
                    ? ""
                    : vehicleTypeText(language, row.vehicle_type)}
                </span>
                {" · "}
                {customerLink(row.customer_id, row.customer_name)}
              </span>
              <span className="ui-small ui-num">
                {lt(language, "in_since", dayText(row.move_in_date))}
                {row.move_out_date !== null &&
                  ` · ${lt(language, "out_on", dayText(row.move_out_date))}`}
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="ui-small ui-muted">{lt(language, "v_note")}</p>
    </section>
  );
}

/** The vehicles of the Lease's Signers (the Primary Tenant signs too); null while loading. */
function useSignerVehicles(
  lease: LeaseResource,
  customerApi: Pick<CustomerApi, "listVehicles"> | null,
): { vehicles: VehicleResource[] | null; failed: boolean } {
  const [vehicles, setVehicles] = useState<VehicleResource[] | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (customerApi === null) {
      setFailed(true);
      return;
    }
    const alive = { current: true };
    void Promise.all(
      lease.signers.map((signer) =>
        customerApi.listVehicles(signer.customer_id),
      ),
    )
      .then((lists) => {
        if (alive.current) setVehicles(lists.flat());
      })
      .catch(() => {
        if (alive.current) setFailed(true);
      });
    return () => {
      alive.current = false;
    };
  }, []);
  return { vehicles, failed };
}

/** Sends a vehicle command and sorts its ending; a coded refusal keeps the server's words. */
function useVehicleSend(
  language: Language,
  onSaved: (saved: LeaseResource) => void,
  onConflict: () => void,
) {
  const [busy, setBusy] = useState(false);
  const [unknown, setUnknown] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  function send(request: () => Promise<LeaseResource>) {
    setBusy(true);
    setUnknown(false);
    setRefusal(null);
    void request()
      .then(onSaved)
      .catch((error: unknown) => {
        if (error instanceof LeaseConflictError) {
          onConflict();
          return;
        }
        if (error instanceof LeaseUnavailableError) {
          setUnknown(true);
          return;
        }
        setRefusal(
          error instanceof LeaseRefusedError
            ? serverWords(language, error)
            : lt(language, "refused"),
        );
      })
      .finally(() => {
        setBusy(false);
      });
  }
  return { busy, unknown, refusal, send };
}

function VehiclePick({
  language,
  lease,
  vehicles,
  failed,
  chosen,
  busy,
  onPick,
  problem,
}: {
  language: Language;
  lease: LeaseResource;
  vehicles: VehicleResource[] | null;
  failed: boolean;
  chosen: string;
  busy: boolean;
  onPick: (vehicleId: string) => void;
  problem: string | null;
}) {
  return (
    <fieldset className="ui-radios">
      <legend>{lt(language, "v_which")}</legend>
      {failed ? (
        <p className="ui-small ui-muted">{lt(language, "v_failed")}</p>
      ) : vehicles === null ? null : vehicles.length === 0 ? (
        <p className="ui-small">
          {lt(language, "v_none_yet")}{" "}
          <a
            className="ui-no"
            href={hashForPage("customers", lease.primary_tenant_id)}
          >
            {lease.primary_tenant_name}
          </a>
        </p>
      ) : (
        vehicles.map((vehicle) => (
          <label className="ui-chk" key={vehicle.vehicle_id}>
            <input
              checked={chosen === vehicle.vehicle_id}
              disabled={busy}
              name="lease-vehicle-pick"
              onChange={() => {
                onPick(vehicle.vehicle_id);
              }}
              type="radio"
            />
            <span>
              {vehicle.plate_text} ·{" "}
              {vehicleTypeText(language, vehicle.vehicle_type)} ·{" "}
              {vehicle.customer_name}
            </span>
          </label>
        ))
      )}
      <Problem message={problem} />
    </fieldset>
  );
}

function RefusalNotice({
  language,
  unknown,
  refusal,
}: {
  language: Language;
  unknown: boolean;
  refusal: string | null;
}) {
  if (!unknown && refusal === null) return null;
  return (
    <div className="ui-notice warn" role="alert">
      <Icon name="alert" />
      <p>{unknown ? lt(language, "unknown") : refusal}</p>
    </div>
  );
}

export function MoveInVehicleDialog({
  language,
  api,
  lease,
  customerApi,
  onClose,
  onSaved,
  onConflict,
}: {
  language: Language;
  api: Pick<LeaseApi, "recordVehicleMoveIn">;
  lease: LeaseResource;
  customerApi: Pick<CustomerApi, "listVehicles"> | null;
  onClose: () => void;
  onSaved: (saved: LeaseResource) => void;
  onConflict: () => void;
}) {
  const today = todayInPhnomPenh();
  const start = lease.start_date ?? today;
  const signedDay =
    lease.signed_at === null
      ? start
      : todayInPhnomPenh(new Date(lease.signed_at));
  const first = signedDay > start ? signedDay : start;
  const last =
    lease.end_date !== null && lease.end_date < today ? lease.end_date : today;
  const [day, setDay] = useState(
    today < first ? first : today > last ? last : today,
  );
  const [chosen, setChosen] = useState("");
  const [note, setNote] = useState("");
  const [problems, setProblems] = useState<Record<string, string>>({});
  const { vehicles, failed } = useSignerVehicles(lease, customerApi);
  const identity = useValuesIdentity();
  const occupancy = useValuesIdentity();
  const { busy, unknown, refusal, send } = useVehicleSend(
    language,
    onSaved,
    onConflict,
  );

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const found: Record<string, string> = {};
    if (!isDay(day) || day < first || day > last)
      found.day =
        first > last
          ? lt(language, "err_movein_early", dayText(first))
          : lt(language, "err_movein_day", dayText(first), dayText(last));
    if (chosen === "") found.vehicle = lt(language, "v_choose");
    setProblems(found);
    if (Object.keys(found).length > 0) return;
    const reason = note.trim() === "" ? MOVE_IN_REASON : note.trim();
    // One Occupancy id per vehicle for the life of the dialog, so a retry sends the same.
    const occupancyId = occupancy(chosen).id;
    const step = identity(JSON.stringify([day, chosen, occupancyId, reason]));
    send(() =>
      api.recordVehicleMoveIn(
        lease,
        {
          event_id: step.id,
          actual_move_in_date: day,
          occupancy_id: occupancyId,
          vehicle_id: chosen,
          reason,
        },
        step.key,
      ),
    );
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={lt(language, "close")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={
        busy
          ? lt(language, "saving")
          : unknown
            ? lt(language, "try_again")
            : lt(language, "movein_ok")
      }
      title={lt(language, "movein_title", lease.unit_number)}
    >
      <div className="ui-field">
        <label htmlFor="lease-movein-day">{lt(language, "movein_day")}</label>
        <DateInput
          language={language}
          invalid={problems.day !== undefined}
          id="lease-movein-day"
          max={last}
          min={first}
          onChange={(value) => {
            setDay(value);
          }}
          value={day}
        />
        <Problem message={problems.day ?? null} />
      </div>
      <VehiclePick
        busy={busy}
        chosen={chosen}
        failed={failed}
        language={language}
        lease={lease}
        onPick={setChosen}
        problem={problems.vehicle ?? null}
        vehicles={vehicles}
      />
      <div className="ui-field">
        <label htmlFor="lease-movein-note">{lt(language, "note")}</label>
        <textarea
          id="lease-movein-note"
          maxLength={500}
          onChange={(event) => {
            setNote(event.currentTarget.value);
          }}
          rows={2}
          value={note}
        />
      </div>
      <RefusalNotice language={language} refusal={refusal} unknown={unknown} />
    </Dialog>
  );
}

export function ChangeVehicleDialog({
  language,
  api,
  lease,
  customerApi,
  onClose,
  onSaved,
  onConflict,
}: {
  language: Language;
  api: Pick<LeaseApi, "changeVehicle">;
  lease: LeaseResource;
  customerApi: Pick<CustomerApi, "listVehicles"> | null;
  onClose: () => void;
  onSaved: (saved: LeaseResource) => void;
  onConflict: () => void;
}) {
  const today = todayInPhnomPenh();
  const current = vehicleRows(lease).find((row) => row.move_out_date === null);
  const first = current?.move_in_date ?? today;
  const last =
    lease.end_date !== null && lease.end_date < today ? lease.end_date : today;
  const [day, setDay] = useState(
    today < first ? first : today > last ? last : today,
  );
  const [chosen, setChosen] = useState("");
  const [reason, setReason] = useState("");
  const [problems, setProblems] = useState<Record<string, string>>({});
  const loaded = useSignerVehicles(lease, customerApi);
  const vehicles =
    loaded.vehicles === null
      ? null
      : loaded.vehicles.filter(
          (vehicle) => vehicle.vehicle_id !== current?.vehicle_id,
        );
  const identity = useValuesIdentity();
  const occupancy = useValuesIdentity();
  const { busy, unknown, refusal, send } = useVehicleSend(
    language,
    onSaved,
    onConflict,
  );

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const found: Record<string, string> = {};
    if (!isDay(day) || day < first || day > last)
      found.day = lt(language, "err_movein_day", dayText(first), dayText(last));
    if (chosen === "") found.vehicle = lt(language, "v_choose");
    else if (reason.trim() === "") found.reason = lt(language, "cv_reason_req");
    setProblems(found);
    if (Object.keys(found).length > 0) return;
    const occupancyId = occupancy(chosen).id;
    const step = identity(
      JSON.stringify([day, chosen, occupancyId, reason.trim()]),
    );
    send(() =>
      api.changeVehicle(
        lease,
        {
          event_id: step.id,
          change_date: day,
          occupancy_id: occupancyId,
          vehicle_id: chosen,
          reason: reason.trim(),
        },
        step.key,
      ),
    );
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={lt(language, "close")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={
        busy
          ? lt(language, "saving")
          : unknown
            ? lt(language, "try_again")
            : lt(language, "change_vehicle")
      }
      title={lt(language, "cv_title", lease.unit_number)}
    >
      <p className="ui-small ui-muted">{lt(language, "cv_note")}</p>
      <VehiclePick
        busy={busy}
        chosen={chosen}
        failed={loaded.failed}
        language={language}
        lease={lease}
        onPick={setChosen}
        problem={problems.vehicle ?? null}
        vehicles={vehicles}
      />
      <div className="ui-field">
        <label htmlFor="lease-vehicle-day">{lt(language, "cv_day")}</label>
        <DateInput
          language={language}
          invalid={problems.day !== undefined}
          id="lease-vehicle-day"
          max={last}
          min={first}
          onChange={(value) => {
            setDay(value);
          }}
          value={day}
        />
        <Problem message={problems.day ?? null} />
      </div>
      <div className="ui-field">
        <label htmlFor="lease-vehicle-reason">
          {lt(language, "cv_reason")}
        </label>
        <textarea
          aria-invalid={problems.reason !== undefined}
          id="lease-vehicle-reason"
          maxLength={500}
          onChange={(event) => {
            setReason(event.currentTarget.value);
          }}
          rows={2}
          value={reason}
        />
        <Problem message={problems.reason ?? null} />
      </div>
      <RefusalNotice language={language} refusal={refusal} unknown={unknown} />
    </Dialog>
  );
}
