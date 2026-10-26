// V1-058 R3 Move-out: which Leases the Move-out list shows and where each one is.

import type { DepositApi } from "../depositClient";
import type { LeaseResource, LeaseTimelineEvent } from "../leaseClient";
import { addDays } from "../reservations/reservationsData";

/**
 * soon: the Lease ends within 60 days (no renewal), or ended or was terminated and someone is
 * still in the Unit. out: everyone left (or nobody ever moved in); the later steps remain.
 * confirm: a draft Final Settlement waits for a Manager. closed: the Final Settlement closed.
 */
export type MoveOutStage = "soon" | "out" | "confirm" | "closed";

/** The finer step shown in the chip (DESIGN.md "Move-out (round 3)"). */
export type MoveOutStep = "soon" | "in" | "out" | "skip" | "confirm" | "closed";

/** What the list knows of a Lease's Final Settlement. */
export interface SettlementMark {
  closed: boolean;
  pending_draft: boolean;
}

/** A Final Settlement waiting for a Manager, or closed, comes before the earlier steps. */
export function settledStep(
  step: MoveOutStep | null,
  settlement: SettlementMark | undefined,
): MoveOutStep | null {
  if (step === null || settlement === undefined) return step;
  if (settlement.closed) return "closed";
  return settlement.pending_draft ? "confirm" : step;
}

export const SOON_DAYS = 60;

export function stillIn(lease: LeaseResource): boolean {
  return lease.occupancies.some(
    (occupancy) => occupancy.move_out_date === null,
  );
}

/** The last move-out date of the Lease, once nobody is left in the Unit. */
export function handedBackOn(lease: LeaseResource): string | null {
  if (lease.occupancies.length === 0 || stillIn(lease)) return null;
  return (
    lease.occupancies
      .map((occupancy) => occupancy.move_out_date ?? "")
      .sort()
      .at(-1) ?? null
  );
}

export function stepOf(
  lease: LeaseResource,
  today: string,
  renewed: boolean,
): MoveOutStep | null {
  if (lease.status === "TERMINATED") {
    if (lease.occupancies.length === 0) return "skip";
    return stillIn(lease) ? "in" : "out";
  }
  if (lease.status !== "SIGNED" || lease.end_date === null) return null;
  // A renewal continues the Occupancies, so the Unit is not handed back.
  if (renewed) return null;
  return lease.end_date <= addDays(today, SOON_DAYS) ? "soon" : null;
}

export function stageOf(step: MoveOutStep): MoveOutStage {
  if (step === "confirm" || step === "closed") return step;
  return step === "soon" || step === "in" ? "soon" : "out";
}

/** The day the Lease ends: the termination date, else the End Date. */
export function endOf(lease: LeaseResource): string | null {
  return lease.actual_termination_date ?? lease.end_date;
}

/**
 * Leases a signed renewal continues (BR-LEASE: only a signed renewal keeps the Occupancies; a
 * drafted or cancelled one does not, so that Lease still moves out).
 */
export function signedRenewalOf(leases: LeaseResource[]): Set<string> {
  return new Set(
    leases.flatMap((lease) =>
      (lease.status === "SIGNED" || lease.status === "TERMINATED") &&
      lease.predecessor_lease_id !== null
        ? [lease.predecessor_lease_id]
        : [],
    ),
  );
}

/** The termination event of a terminated Lease (the newest, if a timeline holds more). */
export function terminationOf(
  timeline: LeaseTimelineEvent[],
): LeaseTimelineEvent | null {
  return (
    timeline
      .filter((event) => event.event_kind === "lease.terminate")
      .sort((left, right) => left.occurred_at.localeCompare(right.occurred_at))
      .at(-1) ?? null
  );
}

export type HeldCell =
  | { state: "shown"; held: number }
  | { state: "hidden" | "failed" };

/** What the Security and Pet Deposits of each Lease still hold, read a few at a time. */
export async function loadHeld(
  api: Pick<DepositApi, "leaseDeposits">,
  leases: LeaseResource[],
  canRead: boolean,
): Promise<Map<string, HeldCell>> {
  const cells = new Map<string, HeldCell>();
  if (!canRead) {
    for (const lease of leases) cells.set(lease.lease_id, { state: "hidden" });
    return cells;
  }
  let next = 0;
  async function worker() {
    for (;;) {
      const lease = leases.at(next);
      next += 1;
      if (lease === undefined) return;
      try {
        const { items } = await api.leaseDeposits(lease.lease_id);
        cells.set(lease.lease_id, {
          state: "shown",
          held: items.reduce(
            (total, deposit) => total + deposit.held_refundable_usd_cents,
            0,
          ),
        });
      } catch {
        cells.set(lease.lease_id, { state: "failed" });
      }
    }
  }
  await Promise.all(Array.from({ length: 6 }, worker));
  return cells;
}
