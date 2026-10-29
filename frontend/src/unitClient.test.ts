import { afterEach, describe, expect, it, vi } from "vitest";

import {
  UnitInvalidError,
  UnitRequestError,
  type UnitResource,
  unitApi,
} from "./unitClient";

afterEach(() => {
  vi.unstubAllGlobals();
  Object.defineProperty(document, "cookie", { configurable: true, value: "" });
});

const current: UnitResource = {
  unit_id: "unit-1",
  property_id: "property-1",
  unit_number: "101",
  floor: "Ground floor",
  floor_item_id: "floor-1",
  unit_type: "STUDIO",
  status: "VACANT",
  version: 3,
  size_square_metres: null,
  bedrooms: null,
  bathrooms: null,
  view_item_id: null,
  kitchen_item_id: null,
  notes: null,
  room_feature_ids: [],
  current_reservation: null,
  current_lease: null,
  current_occupancy: null,
  active_meter_summary: null,
  operational_alerts: [],
};

function item(list_kind: string, code: string, item_id: string) {
  return {
    item_id,
    list_kind,
    code,
    name_en: code,
    name_km: null,
    sort_order: 10,
    removed: false,
    in_use: false,
    version: 1,
  };
}

function respond(status: number, data: unknown) {
  return new Response(JSON.stringify({ data, meta: { request_id: "r" } }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Parking API client", () => {
  it("TEST-FE-817 reads Parking details and setup lists, never sends a Parking number on update, and names a refused pick", async () => {
    Object.defineProperty(document, "cookie", {
      configurable: true,
      value: "__Host-prm_csrf=token-1",
    });
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        respond(200, {
          lists: {
            FLOOR: [item("FLOOR", "F001", "floor-1")],
            UNIT_TYPE: [item("UNIT_TYPE", "STUDIO", "type-1")],
            VIEW: [],
            KITCHEN: [],
            ROOM_FEATURE: [item("ROOM_FEATURE", "BALCONY", "feature-1")],
          },
          can_manage: false,
        }),
      )
      .mockResolvedValueOnce(
        respond(200, {
          ...current,
          version: 4,
          size_square_metres: "42.50",
          bedrooms: 1,
          room_feature_ids: ["feature-1"],
        }),
      )
      .mockResolvedValueOnce(respond(422, null))
      .mockResolvedValueOnce(
        respond(200, {
          lists: {
            FLOOR: [item("UNIT_TYPE", "STUDIO", "type-1")],
            UNIT_TYPE: [],
            VIEW: [],
            KITCHEN: [],
            ROOM_FEATURE: [],
          },
          can_manage: false,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const lists = await unitApi.setupLists("property-1");
    const updated = await unitApi.update(current, {
      size_square_metres: "42.50",
      bedrooms: 1,
      room_feature_ids: ["feature-1"],
    });
    const refused = unitApi.update(current, { floor_item_id: "removed" });

    expect(lists.lists.FLOOR.map((entry) => entry.code)).toEqual(["F001"]);
    expect(lists.lists.ROOM_FEATURE[0]?.item_id).toBe("feature-1");
    expect(lists.can_manage).toBe(false);
    expect(updated.size_square_metres).toBe("42.50");
    expect(updated.room_feature_ids).toEqual(["feature-1"]);
    const [path, init] = fetchMock.mock.calls[1] ?? [];
    expect(path).toBe("/units/unit-1");
    expect(init?.headers).toMatchObject({ "If-Match": '"3"' });
    const body = JSON.parse(init?.body as string) as Record<string, unknown>;
    expect(body).not.toHaveProperty("unit_number");
    expect(body).toEqual({
      size_square_metres: "42.50",
      bedrooms: 1,
      room_feature_ids: ["feature-1"],
    });
    await expect(refused).rejects.toBeInstanceOf(UnitInvalidError);
    await expect(unitApi.setupLists("property-1")).rejects.toBeInstanceOf(
      UnitRequestError,
    );
  });

  it("TEST-FE-821 reads the Parking inventory and saves it against the record number it showed", async () => {
    Object.defineProperty(document, "cookie", {
      configurable: true,
      value: "__Host-prm_csrf=token-1",
    });
    const shown = {
      unit_id: "unit-1",
      record_number: 2,
      recorded_at: "2026-10-24T05:30:00+00:00",
      recorded_by: "actor-1",
      lines: [{ item_group: "FURNITURE", item_name: "Bed", quantity: 1 }],
      counts: { FURNITURE: 1, APPLIANCES: 0, KITCHEN: 0, BATHROOM: 0 },
      can_manage: true,
    };
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(respond(200, shown))
      .mockResolvedValueOnce(respond(200, { ...shown, record_number: 3 }))
      .mockResolvedValueOnce(
        respond(200, {
          items: [{ item_group: "GARDEN", item_name: "Hose" }],
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const current = await unitApi.inventory("unit-1");
    const saved = await unitApi.saveInventory(current, current.lines);

    expect(current.lines).toEqual(shown.lines);
    expect(current.counts.FURNITURE).toBe(1);
    expect(saved.record_number).toBe(3);
    const [path, init] = fetchMock.mock.calls[1] ?? [];
    expect(path).toBe("/units/unit-1/inventory");
    expect(init?.method).toBe("PUT");
    expect(init?.headers).toMatchObject({ "If-Match": '"2"' });
    expect(JSON.parse(init?.body as string)).toEqual({ lines: shown.lines });
    await expect(unitApi.inventoryItems("property-1")).rejects.toBeInstanceOf(
      UnitRequestError,
    );
  });
});
