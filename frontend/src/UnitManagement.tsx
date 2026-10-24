import { FormEvent, useRef, useState } from "react";

import {
  UnitApi,
  UnitConflictError,
  UnitDetails,
  UnitInvalidError,
  UnitResource,
  UnitSetupItem,
  UnitSetupLists,
  UnitStatus,
  UnitTimelineEvent,
  UnitUnavailableError,
  unitApi,
} from "./unitClient";

export interface UnitManagementProps {
  api?: UnitApi;
}

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
  if (error instanceof UnitInvalidError) return error.message;
  return "The Unit request was not completed. Retry when the service is available.";
}

function formString(data: FormData, name: string): string {
  const value = data.get(name);
  return typeof value === "string" ? value : "";
}

function optionalText(data: FormData, name: string): string | null {
  const value = formString(data, name).trim();
  return value === "" ? null : value;
}

function optionalCount(data: FormData, name: string): number | null {
  const value = optionalText(data, name);
  return value === null ? null : Number(value);
}

// DL-078 answer 1: the optional details, read from fields named `${prefix}-…`.
function detailsFrom(data: FormData, prefix: string): UnitDetails {
  const size = optionalText(data, `${prefix}-size`);
  return {
    size_square_metres: size === null ? null : Number(size).toFixed(2),
    bedrooms: optionalCount(data, `${prefix}-bedrooms`),
    bathrooms: optionalCount(data, `${prefix}-bathrooms`),
    view_item_id: optionalText(data, `${prefix}-view`),
    kitchen_item_id: optionalText(data, `${prefix}-kitchen`),
    notes: optionalText(data, `${prefix}-notes`),
    room_feature_ids: data
      .getAll(`${prefix}-features`)
      .filter((value): value is string => typeof value === "string"),
  };
}

function itemName(item: UnitSetupItem): string {
  return item.name_km === null
    ? item.name_en
    : `${item.name_en} · ${item.name_km}`;
}

// The items a form may pick: those not removed, plus the one the Unit already uses.
function choices(items: UnitSetupItem[], current?: string | null) {
  return items.filter((item) => !item.removed || item.item_id === current);
}

function typeName(lists: UnitSetupLists | null, code: string): string {
  const item = lists?.lists.UNIT_TYPE.find((entry) => entry.code === code);
  return item === undefined ? code : item.name_en;
}

function itemNameById(
  lists: UnitSetupLists | null,
  itemId: string | null,
): string {
  if (itemId === null) return "Not recorded";
  for (const items of Object.values(lists?.lists ?? {})) {
    const item = items.find((entry) => entry.item_id === itemId);
    if (item !== undefined) return item.name_en;
  }
  return "Not recorded";
}

function UnitDetailFields({
  lists,
  prefix,
  unit,
}: {
  lists: UnitSetupLists;
  prefix: string;
  unit?: UnitResource;
}) {
  const optionalSelect = (
    kind: "VIEW" | "KITCHEN",
    label: string,
    current: string | null,
  ) => (
    <div className="form-field">
      <label htmlFor={`${prefix}-${kind.toLowerCase()}`}>{label}</label>
      <select
        defaultValue={current ?? ""}
        id={`${prefix}-${kind.toLowerCase()}`}
        name={`${prefix}-${kind.toLowerCase()}`}
      >
        <option value="">Not recorded</option>
        {choices(lists.lists[kind], current).map((item) => (
          <option key={item.item_id} value={item.item_id}>
            {itemName(item)}
          </option>
        ))}
      </select>
    </div>
  );
  const features = choices(lists.lists.ROOM_FEATURE).concat(
    lists.lists.ROOM_FEATURE.filter(
      (item) => item.removed && unit?.room_feature_ids.includes(item.item_id),
    ),
  );
  return (
    <>
      <div className="form-field">
        <label htmlFor={`${prefix}-size`}>Size (m²)</label>
        <input
          defaultValue={unit?.size_square_metres ?? ""}
          id={`${prefix}-size`}
          inputMode="decimal"
          max="10000"
          min="0.01"
          name={`${prefix}-size`}
          step="0.01"
          type="number"
        />
      </div>
      <div className="form-field">
        <label htmlFor={`${prefix}-bedrooms`}>Bedrooms</label>
        <input
          defaultValue={unit?.bedrooms ?? ""}
          id={`${prefix}-bedrooms`}
          max="20"
          min="0"
          name={`${prefix}-bedrooms`}
          step="1"
          type="number"
        />
      </div>
      <div className="form-field">
        <label htmlFor={`${prefix}-bathrooms`}>Bathrooms</label>
        <input
          defaultValue={unit?.bathrooms ?? ""}
          id={`${prefix}-bathrooms`}
          max="20"
          min="0"
          name={`${prefix}-bathrooms`}
          step="1"
          type="number"
        />
      </div>
      {optionalSelect("VIEW", "View", unit?.view_item_id ?? null)}
      {optionalSelect("KITCHEN", "Kitchen", unit?.kitchen_item_id ?? null)}
      <fieldset className="form-field">
        <legend>Room features</legend>
        {features.length === 0 ? (
          <p className="muted">No Room features are in Settings yet.</p>
        ) : (
          features.map((item) => (
            <label key={item.item_id}>
              <input
                defaultChecked={unit?.room_feature_ids.includes(item.item_id)}
                name={`${prefix}-features`}
                type="checkbox"
                value={item.item_id}
              />{" "}
              {itemName(item)}
            </label>
          ))
        )}
      </fieldset>
      <div className="form-field">
        <label htmlFor={`${prefix}-notes`}>Notes</label>
        <textarea
          defaultValue={unit?.notes ?? ""}
          id={`${prefix}-notes`}
          maxLength={2000}
          name={`${prefix}-notes`}
        />
      </div>
    </>
  );
}

export function UnitManagement({ api = unitApi }: UnitManagementProps) {
  const [propertyId, setPropertyId] = useState("");
  const [units, setUnits] = useState<UnitResource[]>([]);
  const [lists, setLists] = useState<UnitSetupLists | null>(null);
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
    setLists(null);
    setCanManage(false);
    setSelected(null);
    setTimeline([]);
  }

  function loadUnits(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const operation = ++sequence.current;
    setLoading(true);
    setStatus("Loading Units…");
    // The Units still show when the lists cannot be read; the forms then stay hidden.
    const setup = api.setupLists(propertyId).catch(() => null);
    void Promise.all([api.list(propertyId), setup])
      .then(([page, setupLists]) => {
        if (operation !== sequence.current) return;
        setUnits(page.items);
        setLists(setupLists);
        setCanManage(page.can_manage);
        setStatus(
          (page.items.length === 0
            ? "No Units were found for this Property."
            : `${String(page.items.length)} Unit record(s) loaded.`) +
            (setupLists === null && page.can_manage
              ? " The Settings lists could not be read, so Units cannot be added or changed now."
              : ""),
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
        floor_item_id: formString(data, "unit-floor"),
        unit_type: formString(data, "unit-type"),
        status: formString(data, "unit-status") as UnitStatus,
        ...detailsFrom(data, "unit"),
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
        floor_item_id: formString(data, "edit-unit-floor"),
        unit_type: formString(data, "edit-unit-type"),
        status: formString(data, "edit-unit-status") as UnitStatus,
        ...detailsFrom(data, "edit-unit"),
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
                  <td>{typeName(lists, unit.unit_type)}</td>
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

      {canManage && lists !== null && (
        <form className="form-stack" onSubmit={createUnit}>
          <h4>Create Unit</h4>
          <div className="form-field">
            <label htmlFor="unit-number">Unit identifier/name</label>
            <input id="unit-number" name="unit-number" required />
            <p className="muted">The Unit number cannot change later.</p>
          </div>
          <div className="form-field">
            <label htmlFor="unit-floor">Floor</label>
            <select id="unit-floor" name="unit-floor" required>
              <option value="">Choose a Floor</option>
              {choices(lists.lists.FLOOR).map((item) => (
                <option key={item.item_id} value={item.item_id}>
                  {itemName(item)}
                </option>
              ))}
            </select>
          </div>
          <div className="form-field">
            <label htmlFor="unit-type">Unit type</label>
            <select id="unit-type" name="unit-type" required>
              {choices(lists.lists.UNIT_TYPE).map((item) => (
                <option key={item.item_id} value={item.code}>
                  {itemName(item)}
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
          <UnitDetailFields lists={lists} prefix="unit" />
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
              <dt>Floor</dt>
              <dd>{selected.floor}</dd>
            </div>
            <div>
              <dt>Unit type</dt>
              <dd>{typeName(lists, selected.unit_type)}</dd>
            </div>
            <div>
              <dt>Size</dt>
              <dd>
                {selected.size_square_metres === null
                  ? "Not recorded"
                  : `${selected.size_square_metres} m²`}
              </dd>
            </div>
            <div>
              <dt>Bedrooms and bathrooms</dt>
              <dd>
                {selected.bedrooms ?? "–"} bedroom(s) ·{" "}
                {selected.bathrooms ?? "–"} bathroom(s)
              </dd>
            </div>
            <div>
              <dt>View and kitchen</dt>
              <dd>
                {itemNameById(lists, selected.view_item_id)} ·{" "}
                {itemNameById(lists, selected.kitchen_item_id)}
              </dd>
            </div>
            <div>
              <dt>Room features</dt>
              <dd>
                {selected.room_feature_ids.length === 0
                  ? "None"
                  : selected.room_feature_ids
                      .map((itemId) => itemNameById(lists, itemId))
                      .join(", ")}
              </dd>
            </div>
            <div>
              <dt>Notes</dt>
              <dd>{selected.notes ?? "None"}</dd>
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

          {canManage && lists !== null && selected.can_manage !== false && (
            <form
              className="form-stack"
              key={`unit-${selected.unit_id}-${String(selected.version)}`}
              onSubmit={updateUnit}
            >
              <h5>Update approved Unit source data</h5>
              <p>
                Unit number <strong>{selected.unit_number}</strong> cannot
                change.
              </p>
              <div className="form-field">
                <label htmlFor="edit-unit-floor">Floor</label>
                <select
                  defaultValue={selected.floor_item_id ?? ""}
                  id="edit-unit-floor"
                  name="edit-unit-floor"
                  required
                >
                  <option value="">Choose a Floor</option>
                  {choices(lists.lists.FLOOR, selected.floor_item_id).map(
                    (item) => (
                      <option key={item.item_id} value={item.item_id}>
                        {itemName(item)}
                      </option>
                    ),
                  )}
                </select>
              </div>
              <div className="form-field">
                <label htmlFor="edit-unit-type">Unit type</label>
                <select
                  defaultValue={selected.unit_type}
                  id="edit-unit-type"
                  name="edit-unit-type"
                >
                  {lists.lists.UNIT_TYPE.filter(
                    (item) => !item.removed || item.code === selected.unit_type,
                  ).map((item) => (
                    <option key={item.item_id} value={item.code}>
                      {itemName(item)}
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
              <UnitDetailFields
                lists={lists}
                prefix="edit-unit"
                unit={selected}
              />
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
