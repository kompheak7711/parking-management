// V1-058 R2: what the Customers screens read. The Customer API gives each person; the Unit
// and Relationship columns come from every Lease of the Property and the active
// Reservations, read once for the whole list. A person who may not read Leases or
// Reservations still sees the Customers, with "—" in those columns.

import type { CustomerApi, CustomerListItem } from "../customerClient";
import type { LeaseApi, LeaseResource } from "../leaseClient";
import type { ReservationApi, ReservationResource } from "../reservationClient";

/** The relationship that names a Customer in the list, strongest first. */
export type CustomerKind = "tenant" | "other" | "res" | "former" | "none";

export type CustomerRole = "primary" | "signer" | "occupant" | "res" | "former";

export interface CustomersData {
  customers: CustomerListItem[];
  canManage: boolean;
  /** Null when the person may not read them (or they could not be read). */
  leases: LeaseResource[] | null;
  reservations: ReservationResource[] | null;
}

export interface CustomerStanding {
  kind: CustomerKind;
  role: CustomerRole | null;
  /** The Unit of that relationship; for a former tenant, the Unit of the latest Lease. */
  unitNumber: string | null;
  unitId: string | null;
}

// More pages than this means something is wrong; V1 has one building of a few dozen Units.
const MAX_PAGES = 50;

async function allPages<T>(
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

export async function loadCustomersData(
  apis: {
    customerApi: CustomerApi;
    leaseApi: LeaseApi;
    reservationApi: ReservationApi;
  },
  propertyId: string,
): Promise<CustomersData> {
  let canManage = false;
  const [customers, leases, reservations] = await Promise.all([
    allPages(async (cursor) => {
      const page = await apis.customerApi.list(
        propertyId,
        cursor === undefined ? {} : { cursor },
      );
      canManage = page.can_manage;
      return page;
    }),
    allPages((cursor) =>
      apis.leaseApi.list(propertyId, cursor === undefined ? {} : { cursor }),
    ).catch(() => null),
    allPages((cursor) =>
      apis.reservationApi.list(propertyId, "ACTIVE", cursor),
    ).catch(() => null),
  ]);
  return {
    customers: customers.sort((left, right) =>
      left.legal_name.localeCompare(right.legal_name),
    ),
    canManage,
    leases,
    reservations,
  };
}

/** A signed Lease whose End Date has not passed. */
export function isCurrentLease(lease: LeaseResource, today: string): boolean {
  return (
    lease.status === "SIGNED" &&
    (lease.end_date === null || lease.end_date >= today)
  );
}

/** Every Lease the person is on: as Primary Tenant, as a Signer or as an occupant. */
export function leasesOf(
  leases: LeaseResource[] | null,
  customerId: string,
): LeaseResource[] {
  return (leases ?? []).filter(
    (lease) =>
      lease.primary_tenant_id === customerId ||
      lease.signers.some((signer) => signer.customer_id === customerId) ||
      lease.occupancies.some(
        (occupancy) => occupancy.customer_id === customerId,
      ),
  );
}

export function roleOn(
  lease: LeaseResource,
  customerId: string,
): "primary" | "signer" | "occupant" {
  if (lease.primary_tenant_id === customerId) return "primary";
  if (lease.signers.some((signer) => signer.customer_id === customerId))
    return "signer";
  return "occupant";
}

export function standingOf(
  data: Pick<CustomersData, "leases" | "reservations">,
  customerId: string,
  today: string,
): CustomerStanding {
  const own = leasesOf(data.leases, customerId);
  const current = own.filter((lease) => isCurrentLease(lease, today));
  const primary = current.find(
    (lease) => lease.primary_tenant_id === customerId,
  );
  if (primary !== undefined)
    return {
      kind: "tenant",
      role: "primary",
      unitNumber: primary.unit_number,
      unitId: primary.unit_id,
    };
  // A Signer counts while the Lease runs; an occupant until the move-out.
  const other = current.find(
    (lease) =>
      lease.signers.some((signer) => signer.customer_id === customerId) ||
      lease.occupancies.some(
        (occupancy) =>
          occupancy.customer_id === customerId &&
          occupancy.move_out_date === null,
      ),
  );
  if (other !== undefined)
    return {
      kind: "other",
      role: roleOn(other, customerId),
      unitNumber: other.unit_number,
      unitId: other.unit_id,
    };
  const reservation = data.reservations?.find(
    (entry) => entry.customer_id === customerId,
  );
  if (reservation !== undefined)
    return {
      kind: "res",
      role: "res",
      unitNumber: reservation.unit_number,
      unitId: reservation.unit_id,
    };
  // Former: was on a signed or terminated Lease and is not on one now (an ended Lease, or
  // an occupant who moved out of a Lease that still runs).
  const ended = (lease: LeaseResource) =>
    lease.actual_termination_date ?? lease.end_date ?? "";
  const past = own
    .filter(
      (lease) => lease.status === "TERMINATED" || lease.status === "SIGNED",
    )
    .sort((left, right) => ended(right).localeCompare(ended(left)));
  const latest = past[0];
  if (latest !== undefined)
    return {
      kind: "former",
      role: "former",
      unitNumber: latest.unit_number,
      unitId: latest.unit_id,
    };
  return { kind: "none", role: null, unitNumber: null, unitId: null };
}

/** Digits only, so "012 345 678" and "012345678" match. */
export function phoneKey(value: string): string {
  return value.replace(/\D/g, "");
}
