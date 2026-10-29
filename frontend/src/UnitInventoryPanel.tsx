import { FormEvent, useEffect, useRef, useState } from "react";

import { Icon } from "./shell/icons";
import { Dialog } from "./shell/ui";

import {
  UnitApi,
  UnitConflictError,
  UnitFeatureCount,
  UnitInventory,
  UnitInventoryItemName,
  UnitInventoryLine,
  UnitInvalidError,
  UnitSetupItem,
  UnitSetupLists,
  UnitUnavailableError,
} from "./unitClient";

// DL-078 answer 2: the Unit inventory, its count line, and Edit inventory. Each save is dated and
// goes into the Unit's History. V1.1 (DL-115 (I); mock-up round 13, image 3): Edit inventory is a
// table of Item type | Item name | Where | How many | ×, with the add row at the bottom. "Where" is
// optional and lists this Unit's own features (Bedroom 1, Bedroom 2, Kitchen …).

function failure(error: unknown): string {
  if (error instanceof UnitUnavailableError) {
    return "Parking inventory is unavailable for this session.";
  }
  if (error instanceof UnitConflictError) {
    return "Someone else saved this inventory first. Their list is shown now; edit it again if needed.";
  }
  if (error instanceof UnitInvalidError) {
    return "Check the items: each name once for its type and place, quantities from 1 to 999.";
  }
  return "The Parking inventory request was not completed. Retry when the service is available.";
}

function dateTime(value: string | null): string {
  if (value === null) return "";
  const date = new Date(value);
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Phnom_Penh",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const part = (type: string) =>
    parts.find((entry) => entry.type === type)?.value ?? "";
  return `${part("day")}/${part("month")}/${part("year")} ${part("hour")}:${part("minute")}`;
}

/** A place as one select value: the Unit feature and which one. */
function placeValue(itemId: string | null, number: number | null): string {
  return itemId === null || number === null
    ? ""
    : `${itemId}:${String(number)}`;
}

interface Place {
  value: string;
  label: string;
}

/** The Unit's own places: "Kitchen" for one, "Bedroom 1" and "Bedroom 2" for two. */
function placesOf(
  features: UnitFeatureCount[],
  lists: UnitSetupLists | null,
): Place[] {
  const items = lists?.lists.UNIT_FEATURE ?? [];
  const order = new Map(items.map((item, index) => [item.item_id, index]));
  return [...features]
    .sort(
      (left, right) =>
        (order.get(left.item_id) ?? 999) - (order.get(right.item_id) ?? 999),
    )
    .flatMap((feature) => {
      const name =
        items.find((item) => item.item_id === feature.item_id)?.name_en ??
        "Removed feature";
      return Array.from({ length: feature.count }, (_, index) => ({
        value: placeValue(feature.item_id, index + 1),
        label: feature.count === 1 ? name : `${name} ${String(index + 1)}`,
      }));
    });
}

function placeLabel(
  line: Pick<UnitInventoryLine, "where_item_id" | "where_number">,
  places: Place[],
  lists: UnitSetupLists | null,
): string | null {
  if (line.where_item_id === null || line.where_number === null) return null;
  const known = places.find(
    (place) =>
      place.value === placeValue(line.where_item_id, line.where_number),
  );
  if (known !== undefined) return known.label;
  // A place the Unit no longer has still shows by its name and number.
  const name =
    lists?.lists.UNIT_FEATURE.find(
      (item) => item.item_id === line.where_item_id,
    )?.name_en ?? "Removed feature";
  return `${name} ${String(line.where_number)}`;
}

interface Row {
  key: number;
  type: string;
  name: string;
  where: string;
  quantity: string;
}

export interface UnitInventoryPanelProps {
  api: UnitApi;
  propertyId: string;
  unitId: string;
  /** The Unit setup lists, for the Item types and the names of the places. */
  lists?: UnitSetupLists | null;
  /** The Unit's features: the places "Where" offers. */
  features?: UnitFeatureCount[];
  onSaved?: () => void;
}

export function UnitInventoryPanel({
  api,
  propertyId,
  unitId,
  lists = null,
  features = [],
  onSaved,
}: UnitInventoryPanelProps) {
  const [inventory, setInventory] = useState<UnitInventory | null>(null);
  const [known, setKnown] = useState<UnitInventoryItemName[]>([]);
  const [rows, setRows] = useState<Row[] | null>(null);
  const [adding, setAdding] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const sequence = useRef(0);
  const nextKey = useRef(1);

  const types: UnitSetupItem[] = lists?.lists.ITEM_TYPE ?? [];
  const typeName = (itemId: string) =>
    types.find((type) => type.item_id === itemId)?.name_en ?? "Other";
  const offeredTypes = (current: string) =>
    types.filter((type) => !type.removed || type.item_id === current);
  const places = placesOf(features, lists);

  useEffect(() => {
    const operation = ++sequence.current;
    setInventory(null);
    setRows(null);
    setBusy(false);
    setNote(null);
    void api
      .inventory(unitId)
      .then((loaded) => {
        if (operation === sequence.current) setInventory(loaded);
      })
      .catch((error: unknown) => {
        if (operation === sequence.current) setNote(failure(error));
      });
  }, [api, unitId]);

  function blankRow(): Row {
    return {
      key: nextKey.current++,
      type: offeredTypes("").find((type) => !type.removed)?.item_id ?? "",
      name: "",
      where: "",
      quantity: "1",
    };
  }

  function startEditing() {
    if (inventory === null) return;
    const operation = ++sequence.current;
    setBusy(true);
    setNote(null);
    setProblem(null);
    void api
      .inventoryItems(propertyId)
      .catch(() => [])
      .then((items) => {
        if (operation !== sequence.current) return;
        setKnown(items);
        setRows(
          inventory.lines.map((line) => ({
            key: nextKey.current++,
            type: line.item_type_item_id,
            name: line.item_name,
            where: placeValue(line.where_item_id, line.where_number),
            quantity: String(line.quantity),
          })),
        );
        setAdding(blankRow());
      })
      .finally(() => {
        if (operation === sequence.current) setBusy(false);
      });
  }

  function change(key: number, patch: Partial<Row>) {
    setRows((current) =>
      (current ?? []).map((row) =>
        row.key === key ? { ...row, ...patch } : row,
      ),
    );
    setProblem(null);
  }

  function addRow() {
    if (adding === null) return;
    if (adding.name.trim() === "") {
      setProblem("Enter the new item's name, then Add.");
      return;
    }
    setRows((current) => [...(current ?? []), adding]);
    setAdding(blankRow());
    setProblem(null);
  }

  function linesOf(all: Row[]): UnitInventoryLine[] | string {
    const lines: UnitInventoryLine[] = [];
    const seen = new Set<string>();
    for (const row of all) {
      const name = row.name.trim();
      const quantity = Number(row.quantity);
      if (name === "") return "Every line needs an item name.";
      if (row.type === "") return "Every line needs an Item type.";
      if (!/^\d{1,3}$/.test(row.quantity.trim()) || quantity < 1) {
        return `How many ${name}: enter a whole number from 1 to 999.`;
      }
      const same = `${row.type}|${name.toLowerCase()}|${row.where}`;
      if (seen.has(same)) {
        return `${name} is listed twice for the same type and place. Put them on one line.`;
      }
      seen.add(same);
      const [whereId, whereNumber] = row.where.split(":");
      const placed = row.where !== "" && whereNumber !== undefined;
      lines.push({
        item_type_item_id: row.type,
        item_name: name,
        where_item_id: placed ? (whereId ?? null) : null,
        where_number: placed ? Number(whereNumber) : null,
        quantity,
      });
    }
    return lines;
  }

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inventory === null || rows === null) return;
    // A filled add row is saved too, as if Add was pressed.
    const all =
      adding !== null && adding.name.trim() !== "" ? [...rows, adding] : rows;
    const lines = linesOf(all);
    if (typeof lines === "string") {
      setProblem(lines);
      return;
    }
    const operation = ++sequence.current;
    setBusy(true);
    setProblem(null);
    setNote("Saving the Unit inventory…");
    void api
      .saveInventory(inventory, lines)
      .then((saved) => {
        if (operation !== sequence.current) return;
        setInventory(saved);
        setRows(null);
        setNote("Unit inventory saved. The earlier list stays in History.");
        onSaved?.();
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        if (error instanceof UnitConflictError) {
          setRows(null);
          setNote(failure(error));
          void api
            .inventory(unitId)
            .then((latest) => {
              if (operation === sequence.current) setInventory(latest);
            })
            .catch(() => undefined);
        } else {
          setNote(null);
          setProblem(failure(error));
        }
      })
      .finally(() => {
        if (operation === sequence.current) setBusy(false);
      });
  }

  const typeSelect = (
    id: string,
    label: string,
    value: string,
    onChange: (value: string) => void,
  ) => (
    <select
      aria-label={label}
      disabled={busy}
      id={id}
      onChange={(event) => {
        onChange(event.currentTarget.value);
      }}
      value={value}
    >
      {value !== "" && !types.some((type) => type.item_id === value) && (
        <option value={value}>{typeName(value)}</option>
      )}
      {offeredTypes(value).map((type) => (
        <option key={type.item_id} value={type.item_id}>
          {type.name_en}
        </option>
      ))}
    </select>
  );

  const placeSelect = (
    label: string,
    value: string,
    onChange: (value: string) => void,
    empty: string,
  ) => (
    <select
      aria-label={label}
      disabled={busy}
      onChange={(event) => {
        onChange(event.currentTarget.value);
      }}
      value={value}
    >
      <option value="">{empty}</option>
      {value !== "" && !places.some((place) => place.value === value) && (
        <option value={value}>
          {placeLabel(
            {
              where_item_id: value.split(":")[0] ?? null,
              where_number: Number(value.split(":")[1]),
            },
            places,
            lists,
          )}
        </option>
      )}
      {places.map((place) => (
        <option key={place.value} value={place.value}>
          {place.label}
        </option>
      ))}
    </select>
  );

  const nameList = (type: string) => `inventory-names-${type}`;
  const listedTypes = [
    ...new Set([...(rows ?? []).map((row) => row.type), adding?.type ?? ""]),
  ].filter((type) => type !== "");

  const editForm = rows !== null && (
    <>
      <p className="ui-small ui-muted">
        Things handed over and checked back at move-in and move-out.
      </p>
      {listedTypes.map((type) => (
        <datalist id={nameList(type)} key={type}>
          {known
            .filter((item) => item.item_type_item_id === type)
            .map((item) => (
              <option key={item.item_name} value={item.item_name} />
            ))}
        </datalist>
      ))}
      <table className="ui-invtable">
        <thead>
          <tr>
            <th scope="col">Item type</th>
            <th scope="col">Item name</th>
            <th scope="col">Where</th>
            <th scope="col">How many</th>
            <th scope="col">
              <span className="ui-sr">Remove</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const label = row.name.trim() || `line ${String(index + 1)}`;
            return (
              <tr key={row.key}>
                <td>
                  {typeSelect(
                    `inventory-type-${String(row.key)}`,
                    `Item type of ${label}`,
                    row.type,
                    (type) => {
                      change(row.key, { type });
                    },
                  )}
                </td>
                <td>
                  <input
                    aria-label={`Item name of ${label}`}
                    disabled={busy}
                    list={nameList(row.type)}
                    maxLength={100}
                    onChange={(event) => {
                      change(row.key, { name: event.currentTarget.value });
                    }}
                    value={row.name}
                  />
                </td>
                <td>
                  {placeSelect(
                    `Where is ${label}`,
                    row.where,
                    (where) => {
                      change(row.key, { where });
                    },
                    "Not set",
                  )}
                </td>
                <td>
                  <input
                    aria-label={`How many ${label}`}
                    disabled={busy}
                    inputMode="numeric"
                    maxLength={3}
                    onChange={(event) => {
                      change(row.key, { quantity: event.currentTarget.value });
                    }}
                    value={row.quantity}
                  />
                </td>
                <td>
                  <button
                    aria-label={`Remove ${label}`}
                    className="ui-btn link"
                    disabled={busy}
                    onClick={() => {
                      setRows((current) =>
                        (current ?? []).filter(
                          (other) => other.key !== row.key,
                        ),
                      );
                    }}
                    type="button"
                  >
                    ×
                  </button>
                </td>
              </tr>
            );
          })}
          {adding !== null && (
            <tr className="ui-invadd">
              <td>
                {typeSelect(
                  "inventory-new-type",
                  "New item type",
                  adding.type,
                  (type) => {
                    setAdding({ ...adding, type });
                  },
                )}
              </td>
              <td>
                <input
                  aria-label="New item name"
                  disabled={busy}
                  list={nameList(adding.type)}
                  maxLength={100}
                  onChange={(event) => {
                    setAdding({ ...adding, name: event.currentTarget.value });
                  }}
                  placeholder="New item name"
                  value={adding.name}
                />
              </td>
              <td>
                {placeSelect(
                  "New item: where",
                  adding.where,
                  (where) => {
                    setAdding({ ...adding, where });
                  },
                  "Where (optional)",
                )}
              </td>
              <td>
                <input
                  aria-label="New item: how many"
                  disabled={busy}
                  inputMode="numeric"
                  maxLength={3}
                  onChange={(event) => {
                    setAdding({
                      ...adding,
                      quantity: event.currentTarget.value,
                    });
                  }}
                  value={adding.quantity}
                />
              </td>
              <td>
                <button
                  className="ui-btn"
                  disabled={busy}
                  onClick={addRow}
                  type="button"
                >
                  Add
                </button>
              </td>
            </tr>
          )}
        </tbody>
      </table>
      <p className="ui-small ui-muted">
        {places.length === 0
          ? "Where lists this Unit's own features. Add them with Edit features first."
          : `Where lists this Unit's own features (${places
              .map((place) => place.label)
              .join(", ")}).`}{" "}
        Each save is dated and kept in History.
      </p>
      {problem !== null && (
        <p className="ui-error" role="alert">
          <Icon name="alert" small />
          <span>{problem}</span>
        </p>
      )}
    </>
  );

  const shownTypes =
    inventory === null
      ? []
      : [
          ...types.map((type) => type.item_id),
          ...inventory.lines
            .map((line) => line.item_type_item_id)
            .filter((id) => !types.some((type) => type.item_id === id)),
        ].filter((id) =>
          inventory.lines.some((line) => line.item_type_item_id === id),
        );

  return (
    <section aria-labelledby="unit-inventory-heading">
      <div className="ui-chead gap">
        <div>
          <h3 id="unit-inventory-heading">Parking inventory</h3>
          {inventory !== null && (
            <p className="ui-small ui-muted">
              {shownTypes
                .map(
                  (type) =>
                    `${String(inventory.counts[type] ?? 0)} ${typeName(type).toLowerCase()}`,
                )
                .join(" · ")}
              {inventory.recorded_at !== null &&
                `${shownTypes.length === 0 ? "" : " · "}saved ${dateTime(inventory.recorded_at)}`}
            </p>
          )}
        </div>
        {inventory?.can_manage === true && (
          <button
            className="ui-btn"
            disabled={busy || rows !== null || lists === null}
            onClick={startEditing}
            type="button"
          >
            <Icon name="list" />
            Edit inventory
          </button>
        )}
      </div>
      {note !== null && rows === null && (
        <p className="ui-small" role="status">
          {note}
        </p>
      )}
      {inventory !== null &&
        (inventory.lines.length === 0 ? (
          <p className="ui-small ui-muted">
            No inventory has been recorded for this Parking yet.
          </p>
        ) : (
          shownTypes.map((type) => (
            <div className="ui-grp" key={type}>
              <h4>{typeName(type)}</h4>
              <ul className="ui-ulist">
                {inventory.lines
                  .filter((line) => line.item_type_item_id === type)
                  .map((line) => {
                    const where = placeLabel(line, places, lists);
                    return (
                      <li
                        key={`${line.item_name}|${placeValue(line.where_item_id, line.where_number)}`}
                      >
                        <Icon name="check" small />
                        <span>
                          {line.item_name}
                          {where !== null && (
                            <span className="ui-muted"> · {where}</span>
                          )}
                        </span>
                        {line.quantity > 1 && (
                          <span className="ui-qty ui-num">
                            ×{line.quantity}
                          </span>
                        )}
                      </li>
                    );
                  })}
              </ul>
            </div>
          ))
        ))}
      {rows !== null && (
        <Dialog
          busy={busy}
          closeLabel="Cancel"
          onClose={() => {
            setRows(null);
            setProblem(null);
          }}
          onSubmit={save}
          submitLabel="Save inventory"
          title="Edit inventory"
        >
          {editForm}
        </Dialog>
      )}
    </section>
  );
}
