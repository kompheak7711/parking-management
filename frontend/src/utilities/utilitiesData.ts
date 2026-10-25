// V1-058 R4: what the Utilities screens read. The Unit API gives the Units; each Unit's
// meters and each meter's readings come from the Utility API, read once for the whole page.
// V1 has one building of a few dozen Units, so this is a few dozen small reads. The
// Customer of a Unit comes from the current signed Leases; a person who may not read Leases
// still sees the readings, without the names.

import { LeaseUnavailableError, type LeaseApi } from "../leaseClient";
import type { UnitApi, UnitResource } from "../unitClient";
import type {
  UtilityApi,
  UtilityMeter,
  UtilityReading,
  UtilityType,
} from "../utilityClient";

export interface UtilitiesData {
  units: UnitResource[];
  /** Every meter of every Unit, current and replaced. */
  meters: UtilityMeter[];
  /** The readings of each meter, newest first. */
  readings: ReadonlyMap<string, UtilityReading[]>;
  /** The Customer of each Unit with a current signed Lease (Unit id → name). */
  customers: ReadonlyMap<string, string>;
  /** Units whose meters could not be read; the page names them. */
  failedUnits: string[];
}

// More pages than this means something is wrong.
const MAX_PAGES = 50;
// How many reads run at the same time, so a slow connection is not flooded.
const AT_ONCE = 6;

async function allPages<T>(
  load: (cursor?: string) => Promise<{ items: T[]; next: string | null }>,
): Promise<T[]> {
  const items: T[] = [];
  let cursor: string | undefined;
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const result = await load(cursor);
    items.push(...result.items);
    if (result.next === null) return items;
    cursor = result.next;
  }
  return items;
}

async function inTurns<T, R>(
  items: readonly T[],
  work: (item: T) => Promise<R>,
): Promise<R[]> {
  const results: R[] = new Array<R>(items.length);
  let next = 0;
  async function worker() {
    while (next < items.length) {
      const index = next++;
      const item = items[index];
      if (item === undefined) return;
      results[index] = await work(item);
    }
  }
  await Promise.all(
    Array.from({ length: Math.min(AT_ONCE, items.length) }, worker),
  );
  return results;
}

export async function loadUtilitiesData(
  apis: {
    unitApi: Pick<UnitApi, "list">;
    leaseApi: Pick<LeaseApi, "list">;
    utilityApi: Pick<UtilityApi, "loadMeters" | "loadReadings">;
  },
  propertyId: string,
): Promise<UtilitiesData> {
  const [units, leases] = await Promise.all([
    allPages(async (cursor) => {
      const page = await apis.unitApi.list(
        propertyId,
        cursor === undefined ? {} : { cursor },
      );
      return { items: page.items, next: page.next_cursor };
    }),
    allPages(async (cursor) => {
      const page = await apis.leaseApi.list(propertyId, {
        status: "SIGNED",
        period: "current",
        ...(cursor === undefined ? {} : { cursor }),
      });
      return { items: page.items, next: page.next_cursor };
    }).catch((error: unknown) => {
      // A refused Lease list (a person who may not read Leases) shows the readings without
      // names; a lost connection is a failure of the whole page.
      if (error instanceof LeaseUnavailableError) throw error;
      return [];
    }),
  ]);
  units.sort((left, right) =>
    left.unit_number.localeCompare(right.unit_number, undefined, {
      numeric: true,
    }),
  );
  // A Unit whose meters or readings cannot be read is named on the page; the others show.
  const failed = new Set<string>();
  const perUnit = await inTurns(units, async (unit) => {
    try {
      const found = await allPages(async (cursor) => {
        const page = await apis.utilityApi.loadMeters(unit.unit_id, cursor);
        return { items: page.items, next: page.nextCursor };
      });
      const lists = await Promise.all(
        found.map((meter) =>
          allPages(async (cursor) => {
            const page = await apis.utilityApi.loadReadings(meter.id, cursor);
            return { items: page.items, next: page.nextCursor };
          }),
        ),
      );
      return found.map((meter, index) => ({
        meter,
        readings: lists[index] ?? [],
      }));
    } catch {
      failed.add(unit.unit_number);
      return [];
    }
  });
  const loaded = perUnit.flat();
  const meters = loaded.map((item) => item.meter);
  const readings = new Map<string, UtilityReading[]>();
  loaded.forEach(({ meter, readings: found }) => {
    const list = [...found];
    list.sort((left, right) =>
      right.reading_date.localeCompare(left.reading_date),
    );
    readings.set(meter.id, list);
  });
  const customers = new Map<string, string>();
  for (const lease of leases) {
    customers.set(lease.unit_id, lease.primary_tenant_name);
  }
  return {
    units,
    meters,
    readings,
    customers,
    failedUnits: units
      .map((unit) => unit.unit_number)
      .filter((number) => failed.has(number)),
  };
}

/** The owner's reading day: meters are read on the 24th and Invoices made on the 25th. */
export function readingDayOf(today: string): string {
  return `${today.slice(0, 7)}-24`;
}

/**
 * "2026-10-24" → "2026-11-24": the same day number months on. The day is kept as it is, so
 * "2026-03-31" gives "2026-04-31"; that is only used to compare dates, where it sorts right.
 */
export function addMonths(day: string, months: number): string {
  const total =
    Number(day.slice(0, 4)) * 12 + Number(day.slice(5, 7)) - 1 + months;
  const year = Math.floor(total / 12);
  const month = (total % 12) + 1;
  return `${String(year)}-${String(month).padStart(2, "0")}${day.slice(7)}`;
}

/** A broken meter: found broken and not replaced yet. Its readings are refused. */
export function isBroken(meter: UtilityMeter): boolean {
  return meter.current && meter.failure_date !== null;
}

export type MeterState = "working" | "broken" | "replaced";

export function meterState(meter: UtilityMeter): MeterState {
  if (!meter.current) return "replaced";
  return meter.failure_date === null ? "working" : "broken";
}

/** One saved reading with the use since the reading before it on the same meter. */
export interface ReadingLine {
  reading: UtilityReading;
  meter: UtilityMeter;
  /** Null for the first reading of a meter. */
  use: number | null;
}

export function readingLines(
  meter: UtilityMeter,
  readings: readonly UtilityReading[],
): ReadingLine[] {
  // Newest first; the use of each reading is measured from the next one in the list.
  return readings.map((reading, index) => {
    const before = readings[index + 1];
    return {
      reading,
      meter,
      use:
        before === undefined
          ? null
          : roundUse(
              Number(reading.effective_value) - Number(before.effective_value),
            ),
    };
  });
}

function roundUse(value: number): number {
  return Math.round(value * 100) / 100;
}

/** The usual use between two readings: the average of the last three, or null. */
export function usualUse(lines: readonly ReadingLine[]): number | null {
  const uses = lines
    .map((line) => line.use)
    .filter((use): use is number => use !== null)
    .slice(0, 3);
  if (uses.length === 0) return null;
  return roundUse(uses.reduce((sum, use) => sum + use, 0) / uses.length);
}

/** One meter on the reading-day list. */
export interface EntryRow {
  unit: UnitResource;
  meter: UtilityMeter;
  /** The reading saved on or after this reading day, if any. */
  saved: UtilityReading | null;
  /** The last reading before this reading day. */
  last: UtilityReading | null;
  usual: number | null;
}

export function entryRows(
  data: UtilitiesData,
  type: UtilityType,
  readingDay: string,
): EntryRow[] {
  const units = new Map(data.units.map((unit) => [unit.unit_id, unit]));
  const rows: EntryRow[] = [];
  for (const meter of data.meters) {
    const unit = units.get(meter.unit_id);
    if (!meter.current || meter.utility_type !== type || unit === undefined) {
      continue;
    }
    const list = data.readings.get(meter.id) ?? [];
    const saved = list.find((reading) => reading.reading_date >= readingDay);
    const earlier = list.filter((reading) => reading.reading_date < readingDay);
    rows.push({
      unit,
      meter,
      saved: saved ?? null,
      last: earlier[0] ?? null,
      usual: usualUse(readingLines(meter, earlier)),
    });
  }
  return rows.sort((left, right) =>
    left.unit.unit_number.localeCompare(right.unit.unit_number, undefined, {
      numeric: true,
    }),
  );
}

/** Every saved reading of one type, newest first, with its meter and use. */
export function allLines(
  data: UtilitiesData,
  type: UtilityType,
  unitId: string | null,
): ReadingLine[] {
  const lines: ReadingLine[] = [];
  for (const meter of data.meters) {
    if (meter.utility_type !== type) continue;
    if (unitId !== null && meter.unit_id !== unitId) continue;
    lines.push(...readingLines(meter, data.readings.get(meter.id) ?? []));
  }
  return lines.sort((left, right) =>
    right.reading.reading_date.localeCompare(left.reading.reading_date),
  );
}

/** "U302", "u302" or "302" → the Unit; null for an empty box; undefined for no such Unit. */
export function findUnit(
  units: readonly UnitResource[],
  typed: string,
): UnitResource | null | undefined {
  const word = typed.trim().split(/\s/)[0]?.toUpperCase() ?? "";
  if (word === "") return null;
  const wanted = /^\d+$/.test(word) ? `U${word}` : word;
  return units.find((unit) => unit.unit_number.toUpperCase() === wanted);
}

/** A reading as staff type it: whole numbers only, commas allowed. */
export function parseReading(typed: string): number | null {
  const raw = typed.trim().replace(/,/g, "");
  if (!/^\d{1,9}$/.test(raw)) return null;
  return Number(raw);
}

/** Is this use much more than usual? Then staff check the meter before saving. */
export function muchMore(use: number, usual: number | null): boolean {
  if (usual === null) return false;
  return use > Math.max(5, Math.round(usual * 2.5));
}

/** "1234.5" → "1,234.5". */
export function amountText(value: number | string): string {
  const number = typeof value === "number" ? value : Number(value);
  return number.toLocaleString("en-US", { maximumFractionDigits: 2 });
}
