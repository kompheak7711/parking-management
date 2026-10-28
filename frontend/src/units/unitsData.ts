// V1-058 R2: what the Units screens read. The Unit API gives each Unit and its status; the
// Until column comes from the signed Leases and the active Reservations, read once for the
// whole list. A person who may not read Leases or Reservations still sees the Units, with "—"
// in that column.

import type { LeaseApi, LeaseResource } from "../leaseClient";
import type { ReservationApi, ReservationResource } from "../reservationClient";
import type {
  UnitApi,
  UnitResource,
  UnitSetupLists,
  UnitStatus,
} from "../unitClient";

export type UnitCard = "occupied" | "reserved" | "vacant" | "na";

export interface UnitsData {
  units: UnitResource[];
  canManage: boolean;
  /** Null when the Settings lists could not be read; the forms then stay closed. */
  lists: UnitSetupLists | null;
  /** Null when the person may not read them (or they could not be read). */
  leases: LeaseResource[] | null;
  reservations: ReservationResource[] | null;
}

// More pages than this means something is wrong; V1 has one building of a few dozen Units.
const MAX_PAGES = 50;

export async function allPages<T>(
  load: (
    cursor?: string,
  ) => Promise<{ items: T[]; next_cursor: string | null }>,
): Promise<T[]> {
  const items: T[] = [];
  let cursor: string | undefined;
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const result = await load(cursor);
    items.push(...result.items);
    if (result.next_cursor === null) return items;
    cursor = result.next_cursor;
  }
  return items;
}

export async function loadUnitsData(
  apis: {
    unitApi: UnitApi;
    leaseApi: LeaseApi;
    reservationApi: ReservationApi;
  },
  propertyId: string,
): Promise<UnitsData> {
  let canManage = false;
  const [units, lists, leases, reservations] = await Promise.all([
    allPages(async (cursor) => {
      const page = await apis.unitApi.list(
        propertyId,
        cursor === undefined ? {} : { cursor },
      );
      canManage = page.can_manage;
      return page;
    }),
    apis.unitApi.setupLists(propertyId).catch(() => null),
    // Every signed Lease, not only the ones running today: signing makes the Unit Occupied
    // before the Start Date (BR-LEASE-016), and a Lease stays signed after its End Date until
    // the move-out (BR-OCC-008).
    allPages((cursor) =>
      apis.leaseApi.list(propertyId, {
        status: "SIGNED",
        ...(cursor === undefined ? {} : { cursor }),
      }),
    ).catch(() => null),
    allPages((cursor) =>
      apis.reservationApi.list(propertyId, "ACTIVE", cursor),
    ).catch(() => null),
  ]);
  return {
    units: units.sort((left, right) =>
      left.unit_number.localeCompare(right.unit_number, undefined, {
        numeric: true,
      }),
    ),
    canManage,
    lists,
    leases,
    reservations,
  };
}

export function cardOf(status: UnitStatus): UnitCard {
  if (status === "OCCUPIED") return "occupied";
  if (status === "RESERVED") return "reserved";
  if (status === "VACANT") return "vacant";
  return "na";
}

/** The Unit's signed Lease in effect today: the latest one that has started; when none has
 * started yet, the one that starts first. */
export function leaseFor(
  data: Pick<UnitsData, "leases">,
  unitId: string,
  today: string,
): LeaseResource | null {
  const signed = (data.leases ?? []).filter(
    (lease) => lease.unit_id === unitId && lease.start_date !== null,
  );
  const start = (lease: LeaseResource) => lease.start_date ?? "";
  const started = signed
    .filter((lease) => start(lease) <= today)
    .sort((left, right) => start(right).localeCompare(start(left)));
  const upcoming = signed
    .filter((lease) => start(lease) > today)
    .sort((left, right) => start(left).localeCompare(start(right)));
  return started[0] ?? upcoming[0] ?? null;
}

export function reservationFor(
  data: Pick<UnitsData, "reservations">,
  unitId: string,
): ReservationResource | null {
  return (
    data.reservations?.find((reservation) => reservation.unit_id === unitId) ??
    null
  );
}

/** The English or Khmer name of a Settings list item; the code when it is not in the list. */
export function typeName(
  lists: UnitSetupLists | null,
  code: string,
  khmer: boolean,
): string {
  const item = lists?.lists.UNIT_TYPE.find((entry) => entry.code === code);
  if (item === undefined) return code;
  return khmer && item.name_km !== null ? item.name_km : item.name_en;
}

export function itemName(
  lists: UnitSetupLists | null,
  itemId: string | null,
  khmer: boolean,
): string | null {
  if (itemId === null || lists === null) return null;
  for (const items of Object.values(lists.lists)) {
    const item = items.find((entry) => entry.item_id === itemId);
    if (item !== undefined)
      return khmer && item.name_km !== null ? item.name_km : item.name_en;
  }
  return null;
}
