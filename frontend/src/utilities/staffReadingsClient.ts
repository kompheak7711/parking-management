// Telegram bots step 4c (DL-176, API-TG-006): the readings the meter reader typed in the
// Staff bot wait in Utilities until someone who may record readings answers them. The server
// checks every right and saves a confirmed reading as a normal meter reading; this client only
// reads and sends.

import type { UtilityType } from "../utilityClient";

export type StaffDecision = "CONFIRMED" | "ASK_AGAIN" | "NOT_USED";

export interface StaffReading {
  proposal_id: string;
  unit_id: string;
  unit: string;
  utility_type: UtilityType;
  reading_value: string;
  last_value: string | null;
  last_date: string | null;
  flag: "LOWER" | "HIGH" | null;
  /** A reading for this meter is already saved for the day it was read. */
  already: boolean;
}

export interface StaffReadingRun {
  run_id: string;
  reading_date: string;
  sent_at: string;
  sent_by: string;
  readings: StaffReading[];
}

export interface StaffDecisionResult {
  decision: StaffDecision;
  done: number;
  /** Units left waiting because their meter already has a reading that day. */
  already: string[];
}

export interface StaffReadingsApi {
  waiting: (propertyId: string) => Promise<StaffReadingRun[]>;
  decide: (
    propertyId: string,
    proposalIds: string[],
    decision: StaffDecision,
  ) => Promise<StaffDecisionResult>;
}

export class StaffReadingsError extends Error {
  /** The HTTP status when the server answered: 403 no right, 404, 422 refused. */
  constructor(readonly status: number | null = null) {
    super("The staff readings command was not completed.");
    this.name = "StaffReadingsError";
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function text(value: unknown): string {
  if (typeof value !== "string") throw new StaffReadingsError();
  return value;
}

function maybeText(value: unknown): string | null {
  return value === null || value === undefined ? null : text(value);
}

function list(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw new StaffReadingsError();
  return value;
}

function csrfToken(): string {
  const prefix = "__Host-prm_csrf=";
  const entry = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  const token =
    entry === undefined ? "" : decodeURIComponent(entry.slice(prefix.length));
  if (token === "") throw new StaffReadingsError();
  return token;
}

async function request(path: string, init?: RequestInit): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(path, {
      credentials: "include",
      ...(init ?? { method: "GET" }),
    });
  } catch {
    throw new StaffReadingsError();
  }
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) throw new StaffReadingsError(response.status);
  if (!isObject(payload) || !("data" in payload))
    throw new StaffReadingsError();
  return payload.data;
}

function reading(value: unknown): StaffReading {
  if (!isObject(value)) throw new StaffReadingsError();
  const type = value.utility_type;
  if (type !== "ELECTRICITY" && type !== "WATER")
    throw new StaffReadingsError();
  const flag = value.flag;
  if (flag !== null && flag !== "LOWER" && flag !== "HIGH")
    throw new StaffReadingsError();
  return {
    proposal_id: text(value.proposal_id),
    unit_id: text(value.unit_id),
    unit: text(value.unit),
    utility_type: type,
    reading_value: text(value.reading_value),
    last_value: maybeText(value.last_value),
    last_date: maybeText(value.last_date),
    flag,
    already: value.already === true,
  };
}

function run(value: unknown): StaffReadingRun {
  if (!isObject(value)) throw new StaffReadingsError();
  return {
    run_id: text(value.run_id),
    reading_date: text(value.reading_date),
    sent_at: text(value.sent_at),
    sent_by: text(value.sent_by),
    readings: list(value.readings).map(reading),
  };
}

function path(propertyId: string): string {
  return `/api/v1/properties/${encodeURIComponent(propertyId)}/staff-meter-readings`;
}

export const staffReadingsApi: StaffReadingsApi = {
  async waiting(propertyId) {
    return list(await request(path(propertyId))).map(run);
  },
  async decide(propertyId, proposalIds, decision) {
    const data = await request(`${path(propertyId)}/decisions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken(),
      },
      body: JSON.stringify({ proposal_ids: proposalIds, decision }),
    });
    if (!isObject(data)) throw new StaffReadingsError();
    const done = data.done;
    if (typeof done !== "number" || !Number.isInteger(done))
      throw new StaffReadingsError();
    return {
      decision,
      done,
      already: list(data.already).map(text),
    };
  },
};
