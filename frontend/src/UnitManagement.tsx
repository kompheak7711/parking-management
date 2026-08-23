import { FormEvent, useRef, useState } from "react";

import {
  UnitApi,
  UnitConflictError,
  UnitResource,
  UnitStatus,
  UnitTimelineEvent,
  UnitType,
  UnitUnavailableError,
  unitApi,
} from "./unitClient";

export interface UnitManagementProps {
  api?: UnitApi;
}

const unitTypes: UnitType[] = [
  "STUDIO",
  "ONE_BEDROOM",
  "TWO_BEDROOM",
  "THREE_BEDROOM",
];
const unitStatuses: UnitStatus[] = [
  "VACANT",
  "RESERVED",
  "OCCUPIED",
  "UNDER_MAINTENANCE",
  "CLEANING",
  "OUT_OF_SERVICE",
];

function message(error: unknown): string {
  if (error instanceof UnitUnavailableError) {
    return "Unit access is unavailable for this session.";
  }
  if (error instanceof UnitConflictError) return error.message;
  return "The Unit request was not completed. Retry when the service is available.";
}

function formString(data: FormData, name: string): string {
  const value = data.get(name);
  return typeof value === "string" ? value : "";
}

export function UnitManagement({ api = unitApi }: UnitManagementProps) {
  const [propertyId, setPropertyId] = useState("");
  const [units, setUnits] = useState<UnitResource[]>([]);
  const [canManage, setCanManage] = useState(false);
  const [selected, setSelected] = useState<UnitResource | null>(null);
  const [timeline, setTimeline] = useState<UnitTimelineEvent[]>([]);
  const [status, setStatus] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const sequence = useRef(0);

  function invalidate() {
    sequence.current += 1;
    setLoading(false);
    setUnits([]);
    setCanManage(false);
    setSelected(null);
    setTimeline([]);
  }

  function loadUnits(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const operation = ++sequence.current;
    setLoading(true);
    setStatus("Loading Units…");
    void api
      .list(propertyId)
      .then((page) => {
        if (operation !== sequence.current) return;
        setUnits(page.items);
        setCanManage(page.can_manage);
        setStatus(
          page.items.length === 0
            ? "No Units were found for this Property."
            : `${String(page.items.length)} Unit record(s) loaded.`,
        );
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        invalidate();
        setStatus(message(error));
      })
      .finally(() => {
        if (operation === sequence.current) setLoading(false);
      });
  }

  function openUnit(unitId: string) {
    const operation = ++sequence.current;
    setLoading(true);
    setStatus("Loading Unit detail and audit history…");
    void Promise.all([api.get(unitId), api.timeline(unitId)])
      .then(([detail, events]) => {
        if (operation !== sequence.current) return;
        setSelected(detail);
        setTimeline(events.items);
        setStatus("Unit detail loaded.");
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        setSelected(null);
        setTimeline([]);
        setStatus(message(error));
      })
      .finally(() => {
        if (operation === sequence.current) setLoading(false);
      });
  }

  function createUnit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const operation = ++sequence.current;
    setLoading(true);
    setStatus("Creating the Unit with an immutable audit event…");
    void api
      .create(propertyId, {
        unit_number: formString(data, "unit-number"),
        floor: formString(data, "unit-floor"),
        unit_type: formString(data, "unit-type") as UnitType,
        status: formString(data, "unit-status") as UnitStatus,
      })
      .then((created) => {
        if (operation !== sequence.current) return;
        setUnits((current) =>
          [...current, created].sort((left, right) =>
            left.unit_number.localeCompare(right.unit_number),
          ),
        );
        setSelected(created);
        setTimeline([]);
        setStatus(
          "Unit created. Its stable identity and initial history were preserved.",
        );
        form.reset();
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        setStatus(message(error));
      })
      .finally(() => {
        if (operation === sequence.current) setLoading(false);
      });
  }

  function updateUnit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selected === null) return;
    const data = new FormData(event.currentTarget);
    const operation = ++sequence.current;
    setLoading(true);
    setStatus("Submitting the version-checked Unit update…");
    void api
      .update(selected, {
        unit_number: formString(data, "edit-unit-number"),
        floor: formString(data, "edit-unit-floor"),
        unit_type: formString(data, "edit-unit-type") as UnitType,
        status: formString(data, "edit-unit-status") as UnitStatus,
      })
      .then((updated) => {
        if (operation !== sequence.current) return;
        setSelected(updated);
        setUnits((current) =>
          current.map((unit) =>
            unit.unit_id === updated.unit_id ? updated : unit,
          ),
        );
        setStatus("Unit source data updated without deleting history.");
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        setStatus(message(error));
      })
      .finally(() => {
        if (operation === sequence.current) setLoading(false);
      });
  }

  return (
    <section
      aria-labelledby="unit-management-heading"
      className="information-card"
    >
      <h3 id="unit-management-heading">Unit management</h3>
      <p>
        Load the Property’s Unit inventory. Operational status is a summary;
        later Reservation, Lease, Occupancy, Meter, and billing sources remain
        distinct.
      </p>
      <form className="form-stack inline-form" onSubmit={loadUnits}>
        <div className="form-field">
          <label htmlFor="unit-property-id">Unit Property identifier</label>
          <input
            id="unit-property-id"
            onChange={(event) => {
              invalidate();
              setPropertyId(event.currentTarget.value);
              setStatus(null);
            }}
            required
            value={propertyId}
          />
        </div>
        <button disabled={loading} type="submit">
          Load Units
        </button>
      </form>
      {status !== null && <p role="status">{status}</p>}

      {units.length > 0 && (
        <div className="table-scroll">
          <table>
            <caption>
              Current Unit source data and operational summaries
            </caption>
            <thead>
              <tr>
                <th scope="col">Unit</th>
                <th scope="col">Floor</th>
                <th scope="col">Type</th>
                <th scope="col">Status</th>
                <th scope="col">Alerts</th>
                <th scope="col">Detail</th>
              </tr>
            </thead>
            <tbody>
              {units.map((unit) => (
                <tr key={unit.unit_id}>
                  <th scope="row">{unit.unit_number}</th>
                  <td>{unit.floor}</td>
                  <td>{unit.unit_type}</td>
                  <td>{unit.status}</td>
                  <td>
                    {unit.operational_alerts.length === 0
                      ? "None"
                      : unit.operational_alerts.join(", ")}
                  </td>
                  <td>
                    <button
                      disabled={loading}
                      onClick={() => {
                        openUnit(unit.unit_id);
                      }}
                      type="button"
                    >
                      Open Unit {unit.unit_number}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {canManage && (
        <form className="form-stack" onSubmit={createUnit}>
          <h4>Create Unit</h4>
          <div className="form-field">
            <label htmlFor="unit-number">Unit identifier/name</label>
            <input id="unit-number" name="unit-number" required />
          </div>
          <div className="form-field">
            <label htmlFor="unit-floor">Floor</label>
            <input id="unit-floor" name="unit-floor" required />
          </div>
          <div className="form-field">
            <label htmlFor="unit-type">Unit type</label>
            <select id="unit-type" name="unit-type">
              {unitTypes.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </div>
          <div className="form-field">
            <label htmlFor="unit-status">Operational status</label>
            <select id="unit-status" name="unit-status">
              {unitStatuses.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </div>
          <button disabled={loading} type="submit">
            Create Unit
          </button>
        </form>
      )}

      {selected !== null && (
        <section aria-labelledby="unit-detail-heading">
          <h4 id="unit-detail-heading">Unit {selected.unit_number} detail</h4>
          <dl className="detail-list">
            <div>
              <dt>Stable identity</dt>
              <dd>{selected.unit_id}</dd>
            </div>
            <div>
              <dt>Version</dt>
              <dd>{selected.version}</dd>
            </div>
            <div>
              <dt>Reservations</dt>
              <dd>
                {selected.current_reservation === null
                  ? "No current source"
                  : "Linked"}
              </dd>
            </div>
            <div>
              <dt>Leases and Occupancy</dt>
              <dd>
                {selected.current_lease === null &&
                selected.current_occupancy === null
                  ? "No current sources"
                  : "Linked"}
              </dd>
            </div>
            <div>
              <dt>Meters and Readings</dt>
              <dd>
                {selected.active_meter_summary === null
                  ? "No current source"
                  : "Linked"}
              </dd>
            </div>
            <div>
              <dt>Billing history</dt>
              <dd>Available when billing sources are implemented.</dd>
            </div>
          </dl>

          {canManage && selected.can_manage !== false && (
            <form
              className="form-stack"
              key={`unit-${selected.unit_id}-${String(selected.version)}`}
              onSubmit={updateUnit}
            >
              <h5>Update approved Unit source data</h5>
              <div className="form-field">
                <label htmlFor="edit-unit-number">Unit identifier/name</label>
                <input
                  defaultValue={selected.unit_number}
                  id="edit-unit-number"
                  name="edit-unit-number"
                  required
                />
              </div>
              <div className="form-field">
                <label htmlFor="edit-unit-floor">Floor</label>
                <input
                  defaultValue={selected.floor}
                  id="edit-unit-floor"
                  name="edit-unit-floor"
                  required
                />
              </div>
              <div className="form-field">
                <label htmlFor="edit-unit-type">Unit type</label>
                <select
                  defaultValue={selected.unit_type}
                  id="edit-unit-type"
                  name="edit-unit-type"
                >
                  {unitTypes.map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-field">
                <label htmlFor="edit-unit-status">Operational status</label>
                <select
                  defaultValue={selected.status}
                  id="edit-unit-status"
                  name="edit-unit-status"
                >
                  {unitStatuses.map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </div>
              <button disabled={loading} type="submit">
                Save Unit source data
              </button>
              <p className="panel-help">
                No generic Unit deletion action is available.
              </p>
            </form>
          )}

          <section aria-labelledby="unit-timeline-heading">
            <h5 id="unit-timeline-heading">Audit history</h5>
            {timeline.length === 0 ? (
              <p>No Unit audit events were returned.</p>
            ) : (
              <ol className="record-list">
                {timeline.map((event) => (
                  <li key={event.event_id}>
                    <strong>{event.action}</strong>
                    <span>
                      {event.occurred_at} · actor {event.actor_id} ·{" "}
                      {event.reason}
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </section>
      )}
    </section>
  );
}
