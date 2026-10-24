import { FormEvent, useEffect, useRef, useState } from "react";

import {
  UnitApi,
  UnitConflictError,
  UnitInventory,
  UnitInventoryGroup,
  UnitInventoryItemName,
  UnitInventoryLine,
  UnitInvalidError,
  UnitUnavailableError,
  unitInventoryGroups,
} from "./unitClient";

// DL-078 answer 2: the Unit inventory, its count line, and Edit inventory with a number box for
// every known item (0 takes an item out). Each save is dated and goes into the Unit's History.

const groupNames: Record<UnitInventoryGroup, string> = {
  FURNITURE: "Furniture",
  APPLIANCES: "Appliances",
  KITCHEN: "Kitchen",
  BATHROOM: "Bathroom",
};

const countWords: Record<UnitInventoryGroup, string> = {
  FURNITURE: "furniture items",
  APPLIANCES: "appliances",
  KITCHEN: "kitchen items",
  BATHROOM: "bathroom items",
};

function failure(error: unknown): string {
  if (error instanceof UnitUnavailableError) {
    return "Unit inventory is unavailable for this session.";
  }
  if (error instanceof UnitConflictError) {
    return "Someone else saved this inventory first. Their list is shown now; edit it again if needed.";
  }
  if (error instanceof UnitInvalidError) {
    return "Check the items: each name once in its group, quantities from 0 to 999.";
  }
  return "The Unit inventory request was not completed. Retry when the service is available.";
}

function text(data: FormData, name: string): string {
  const value = data.get(name);
  return typeof value === "string" ? value : "";
}

function key(group: UnitInventoryGroup, name: string): string {
  return `${group}:${name.toLowerCase()}`;
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

export interface UnitInventoryPanelProps {
  api: UnitApi;
  propertyId: string;
  unitId: string;
  onSaved?: () => void;
}

export function UnitInventoryPanel({
  api,
  propertyId,
  unitId,
  onSaved,
}: UnitInventoryPanelProps) {
  const [inventory, setInventory] = useState<UnitInventory | null>(null);
  const [known, setKnown] = useState<UnitInventoryItemName[] | null>(null);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const sequence = useRef(0);

  useEffect(() => {
    const operation = ++sequence.current;
    setInventory(null);
    setEditing(false);
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

  function startEditing() {
    const operation = ++sequence.current;
    setBusy(true);
    setNote(null);
    void api
      .inventoryItems(propertyId)
      .then((items) => {
        if (operation !== sequence.current) return;
        setKnown(items);
        setEditing(true);
      })
      .catch((error: unknown) => {
        if (operation === sequence.current) setNote(failure(error));
      })
      .finally(() => {
        if (operation === sequence.current) setBusy(false);
      });
  }

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inventory === null) return;
    const data = new FormData(event.currentTarget);
    const lines: UnitInventoryLine[] = [];
    for (const item of choices()) {
      // An emptied box keeps the quantity the Unit has; only 0 takes an item out.
      const entered = text(data, key(item.item_group, item.item_name)).trim();
      const quantity = entered === "" ? quantityOf(item) : Number(entered);
      if (quantity > 0) lines.push({ ...item, quantity });
    }
    const extraName = text(data, "inventory-new-name").trim();
    const extraQuantity = Number(text(data, "inventory-new-quantity"));
    if (extraName !== "" && extraQuantity > 0) {
      const extraGroup = text(
        data,
        "inventory-new-group",
      ) as UnitInventoryGroup;
      // A name already in the group adds to that item instead of a second line.
      const same = lines.find(
        (line) =>
          key(line.item_group, line.item_name) === key(extraGroup, extraName),
      );
      if (same !== undefined) {
        same.quantity += extraQuantity;
      } else {
        lines.push({
          item_group: extraGroup,
          item_name: extraName,
          quantity: extraQuantity,
        });
      }
    }
    const operation = ++sequence.current;
    setBusy(true);
    setNote("Saving the Unit inventory…");
    void api
      .saveInventory(inventory, lines)
      .then((saved) => {
        if (operation !== sequence.current) return;
        setInventory(saved);
        setEditing(false);
        setNote("Unit inventory saved. The earlier list stays in History.");
        onSaved?.();
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        setNote(failure(error));
        if (error instanceof UnitConflictError) {
          setEditing(false);
          void api
            .inventory(unitId)
            .then((latest) => {
              if (operation === sequence.current) setInventory(latest);
            })
            .catch(() => undefined);
        }
      })
      .finally(() => {
        if (operation === sequence.current) setBusy(false);
      });
  }

  // Every known item and every item already in the Unit, one per group and name.
  function choices(): UnitInventoryItemName[] {
    const seen = new Set<string>();
    const all: UnitInventoryItemName[] = [];
    for (const item of [...(inventory?.lines ?? []), ...(known ?? [])]) {
      const itemKey = key(item.item_group, item.item_name);
      if (seen.has(itemKey)) continue;
      seen.add(itemKey);
      all.push({ item_group: item.item_group, item_name: item.item_name });
    }
    return all;
  }

  function quantityOf(item: UnitInventoryItemName): number {
    return (
      inventory?.lines.find(
        (line) =>
          key(line.item_group, line.item_name) ===
          key(item.item_group, item.item_name),
      )?.quantity ?? 0
    );
  }

  return (
    <section aria-labelledby="unit-inventory-heading">
      <h5 id="unit-inventory-heading">Unit inventory</h5>
      {note !== null && <p role="status">{note}</p>}
      {inventory !== null && (
        <>
          <p>
            {unitInventoryGroups
              .map(
                (group) =>
                  `${String(inventory.counts[group])} ${countWords[group]}`,
              )
              .join(" · ")}
            {inventory.recorded_at !== null &&
              ` · saved ${dateTime(inventory.recorded_at)}`}
          </p>
          {inventory.lines.length === 0 ? (
            <p>No inventory has been recorded for this Unit yet.</p>
          ) : (
            unitInventoryGroups
              .filter((group) =>
                inventory.lines.some((line) => line.item_group === group),
              )
              .map((group) => (
                <div key={group}>
                  <h6>{groupNames[group]}</h6>
                  <ul>
                    {inventory.lines
                      .filter((line) => line.item_group === group)
                      .map((line) => (
                        <li key={key(group, line.item_name)}>
                          {line.item_name}
                          {line.quantity > 1 && ` ×${String(line.quantity)}`}
                        </li>
                      ))}
                  </ul>
                </div>
              ))
          )}
          {inventory.can_manage && !editing && (
            <button disabled={busy} onClick={startEditing} type="button">
              Edit inventory
            </button>
          )}
          {editing && (
            <form className="form-stack" onSubmit={save}>
              <p className="muted">
                Enter how many of each item are in the Unit. 0 takes an item
                out.
              </p>
              {unitInventoryGroups.map((group) => (
                <fieldset key={group}>
                  <legend>{groupNames[group]}</legend>
                  {choices()
                    .filter((item) => item.item_group === group)
                    .map((item) => {
                      const itemKey = key(group, item.item_name);
                      return (
                        <div className="form-field" key={itemKey}>
                          <label htmlFor={`inventory-${itemKey}`}>
                            {item.item_name}
                          </label>
                          <input
                            defaultValue={quantityOf(item)}
                            id={`inventory-${itemKey}`}
                            max="999"
                            min="0"
                            name={itemKey}
                            step="1"
                            type="number"
                          />
                        </div>
                      );
                    })}
                </fieldset>
              ))}
              <fieldset>
                <legend>Another item</legend>
                <div className="form-field">
                  <label htmlFor="inventory-new-group">Group</label>
                  <select id="inventory-new-group" name="inventory-new-group">
                    {unitInventoryGroups.map((group) => (
                      <option key={group} value={group}>
                        {groupNames[group]}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="form-field">
                  <label htmlFor="inventory-new-name">Item name</label>
                  <input
                    id="inventory-new-name"
                    maxLength={100}
                    name="inventory-new-name"
                  />
                </div>
                <div className="form-field">
                  <label htmlFor="inventory-new-quantity">How many</label>
                  <input
                    defaultValue={1}
                    id="inventory-new-quantity"
                    max="999"
                    min="1"
                    name="inventory-new-quantity"
                    step="1"
                    type="number"
                  />
                </div>
              </fieldset>
              <button disabled={busy} type="submit">
                Save inventory
              </button>
              <button
                disabled={busy}
                onClick={() => {
                  setEditing(false);
                }}
                type="button"
              >
                Cancel
              </button>
            </form>
          )}
        </>
      )}
    </section>
  );
}
