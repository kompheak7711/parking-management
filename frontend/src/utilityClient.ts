export type UtilityType = "ELECTRICITY" | "WATER";

export interface UtilityMeter {
  id: string;
  property_id: string;
  unit_id: string;
  utility_type: UtilityType;
  serial_number: string;
  measurement_unit_code: string;
  description: string | null;
  installed_date: string;
  failure_date: string | null;
  deactivated_date: string | null;
  current: boolean;
  version: number;
  memo: string | null;
  replacement: {
    replaced_meter_id: string | null;
    replacement_meter_id: string | null;
    replacement_date: string | null;
  };
  readings_url: string;
}

export interface ReadingCorrection {
  id: string;
  previous_value: string;
  corrected_value: string;
  reason: string;
  occurred_at: string;
  actor_id: string;
  authorization_reference: string;
}

interface UtilityReadingEvidence {
  id: string;
  property_id: string;
  meter_id: string;
  unit_id: string;
  utility_type: UtilityType;
  measurement_unit_code: string;
  reading_date: string;
  original_value: string;
  effective_value: string;
  source: { kind: string; evidence: string };
  version: number;
  corrections: ReadingCorrection[];
}

export type UtilityReading = UtilityReadingEvidence &
  (
    | {
        validated: false;
        validated_at: null;
        validated_by: null;
      }
    | {
        validated: true;
        validated_at: string;
        validated_by: string;
      }
  );

export interface UtilityRate {
  id: string;
  utility_type: UtilityType;
  measurement_unit_code: string;
  rate_usd_per_unit: string;
  effective_date: string;
  notice_at: string;
  notice_evidence: string;
  source_memo: string | null;
}

export interface UtilityPage<T> {
  items: T[];
  nextCursor: string | null;
}

export interface UtilitySnapshot {
  meters: UtilityMeter[];
  readings: Record<string, UtilityReading[]>;
  rates: UtilityRate[];
}

export type UtilityBillingEffectKind =
  | "PRE_ISSUANCE_INPUT"
  | "POST_ISSUANCE_NO_AMOUNT_CHANGE"
  | "POST_ISSUANCE_ADJUSTMENT";

export interface AffectedCalculation {
  consumption_period_id: string;
  previous_consumption_quantity: string;
  corrected_consumption_quantity: string;
  billing_effect_kind: UtilityBillingEffectKind;
  issued_line: {
    invoice_line_id: string | null;
    source_invoice_id: string | null;
    calculated_difference_usd_cents: number | null;
    invoice_adjustment_id: string | null;
  };
}

export interface ReadingCorrectionResult {
  reading: UtilityReading;
  correction: ReadingCorrection;
  affected_calculations: AffectedCalculation[];
}

export interface UtilityCalculation {
  status: "READY" | "PENDING_FUTURE_ACTUAL_BASIS";
  property_id: string;
  unit_id: string;
  utility_type: UtilityType;
  consumption_period_id: string | null;
  calculation_kind: "ACTUAL" | "BROKEN_METER_ESTIMATE" | null;
  period_start: string | null;
  period_end: string | null;
  consumption_quantity: string | null;
  represented_days: number | null;
  meter_id: string | null;
  start_reading_id: string | null;
  end_reading_id: string | null;
  failed_meter_id: string | null;
  replacement_meter_id: string | null;
  basis_kind:
    | "LATEST_THREE_HISTORICAL"
    | "ALL_AVAILABLE_HISTORICAL_ONE_OR_TWO"
    | "FIRST_COMPLETE_FUTURE_ZERO_HISTORY"
    | null;
  basis_period_ids: string[];
  basis_sources: {
    consumption_period_id: string;
    meter_id: string;
    start_reading_id: string;
    end_reading_id: string;
  }[];
  total_basis_consumption: string | null;
  total_basis_days: number | null;
  weighted_daily_average: string | null;
  generation_date: string | null;
  rate_id: string | null;
  rate_effective_date: string | null;
  rate_usd_per_unit: string | null;
  amount_usd_cents: number | null;
}

export interface BatchReadingResult {
  index: number;
  idempotency_key: string;
  status: "SUCCEEDED" | "FAILED";
  reading: UtilityReading | null;
  error: { code: string } | null;
}

export interface UtilityApi {
  load: (propertyId: string, unitId: string) => Promise<UtilitySnapshot>;
  loadMeters: (
    unitId: string,
    cursor?: string,
  ) => Promise<UtilityPage<UtilityMeter>>;
  loadReadings: (
    meterId: string,
    cursor?: string,
  ) => Promise<UtilityPage<UtilityReading>>;
  loadRates: (
    propertyId: string,
    cursor?: string,
  ) => Promise<UtilityPage<UtilityRate>>;
  installMeter: (
    unitId: string,
    input: MeterInstallInput,
    idempotencyKey: string,
  ) => Promise<UtilityMeter>;
  replaceMeter: (
    meterId: string,
    input: MeterReplaceInput,
    idempotencyKey: string,
  ) => Promise<UtilityMeter>;
  recordReading: (
    meterId: string,
    input: ReadingInput,
    idempotencyKey: string,
  ) => Promise<UtilityReading>;
  correctReading: (
    readingId: string,
    input: CorrectionInput,
    idempotencyKey: string,
  ) => Promise<ReadingCorrectionResult>;
  recordBatch: (
    propertyId: string,
    mode: "ATOMIC_ALL" | "PARTIAL",
    items: BatchReadingInput[],
    envelopeIdempotencyKey: string | undefined,
  ) => Promise<BatchReadingResult[]>;
  createRate: (
    propertyId: string,
    input: UtilityRateInput,
    idempotencyKey: string,
  ) => Promise<UtilityRate>;
  preview: (input: PreviewInput) => Promise<UtilityCalculation>;
}

export interface ReadingInput {
  expected_meter_version: number;
  reading_date: string;
  reading_value: string;
  source_kind: "MANUAL";
  source_evidence: string;
}

export interface MeterInstallInput {
  utility_type: UtilityType;
  serial_number: string;
  measurement_unit_code: string;
  description: string | null;
  installed_date: string;
  memo: string | null;
  initial_reading: {
    reading_date: string;
    reading_value: string;
    source_evidence: string;
  };
}

export interface MeterReplaceInput {
  expected_version: number;
  failed_boundary_reading_id: string;
  failure_date: string;
  replacement_date: string;
  reason: string;
  replacement_meter: {
    serial_number: string;
    description: string | null;
    memo: string | null;
  };
  replacement_initial_reading: {
    reading_date: string;
    reading_value: string;
    source_evidence: string;
  };
}

export interface CorrectionInput {
  expected_version: number;
  corrected_value: string;
  reason: string;
  authorization_reference: string;
}

export interface BatchReadingInput {
  idempotency_key: string;
  meter_id: string;
  reading: ReadingInput;
}

export interface UtilityRateInput {
  utility_type: UtilityType;
  measurement_unit_code: string;
  rate_usd_per_unit: string;
  effective_date: string;
  notice_at: string;
  notice_evidence: string;
  source_memo: string | null;
}

export interface PreviewInput {
  property_id: string;
  source_kind: "CONSUMPTION_PERIOD" | "ESTIMATION_CASE";
  source_id: string;
  generation_at: string;
}

export class UtilityClientError extends Error {
  readonly fields: string[];
  readonly requestId: string | null;

  constructor(
    message = "The Utility request failed.",
    fields: string[] = [],
    requestId: string | null = null,
  ) {
    super(message);
    this.name = "UtilityClientError";
    this.fields = fields;
    this.requestId = requestId;
  }
}

export class UtilityAuthorizationError extends UtilityClientError {
  constructor(fields: string[] = [], requestId: string | null = null) {
    super("The Utility action is not authorized.", fields, requestId);
    this.name = "UtilityAuthorizationError";
  }
}

export class UtilityConflictError extends UtilityClientError {
  constructor(fields: string[] = [], requestId: string | null = null) {
    super(
      "Utility history changed or the command conflicts.",
      fields,
      requestId,
    );
    this.name = "UtilityConflictError";
  }
}

// DL-071 answer 12: another Meter of the Property, current or replaced, has this serial.
export class MeterSerialNumberInUseError extends UtilityConflictError {
  constructor(fields: string[] = [], requestId: string | null = null) {
    super(fields, requestId);
    this.message =
      "Another Meter of this Property, current or replaced, already has this serial number.";
    this.name = "MeterSerialNumberInUseError";
  }
}

function object(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new UtilityClientError();
  }
  return value as Record<string, unknown>;
}

function string(value: unknown): string {
  if (typeof value !== "string") throw new UtilityClientError();
  return value;
}

function nullableString(value: unknown): string | null {
  return value === null ? null : string(value);
}

function number(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value)) {
    throw new UtilityClientError();
  }
  return value;
}

function utilityType(value: unknown): UtilityType {
  if (value !== "ELECTRICITY" && value !== "WATER") {
    throw new UtilityClientError();
  }
  return value;
}

interface Envelope {
  data: unknown;
  page?: unknown;
}

async function response(
  path: string,
  init: RequestInit = {},
): Promise<Envelope> {
  let result: Response;
  try {
    result = await fetch(path, { credentials: "include", ...init });
  } catch {
    throw new UtilityClientError();
  }
  let payload: unknown = null;
  try {
    payload = await result.json();
  } catch {
    payload = null;
  }
  const envelope =
    typeof payload === "object" && payload !== null && !Array.isArray(payload)
      ? (payload as Record<string, unknown>)
      : null;
  const meta =
    envelope !== null &&
    typeof envelope.meta === "object" &&
    envelope.meta !== null
      ? (envelope.meta as Record<string, unknown>)
      : null;
  const error =
    envelope !== null &&
    typeof envelope.error === "object" &&
    envelope.error !== null
      ? (envelope.error as Record<string, unknown>)
      : null;
  const requestId =
    meta !== null && typeof meta.request_id === "string"
      ? meta.request_id.slice(0, 128)
      : null;
  const fields =
    error !== null && Array.isArray(error.fields)
      ? error.fields
          .filter(
            (field): field is string =>
              typeof field === "string" &&
              /^[A-Za-z0-9_.[\]-]{1,128}$/.test(field),
          )
          .slice(0, 25)
      : [];
  if (result.status === 401 || result.status === 403) {
    throw new UtilityAuthorizationError(fields, requestId);
  }
  if (
    result.status === 409 &&
    error !== null &&
    error.code === "METER_SERIAL_NUMBER_IN_USE"
  ) {
    throw new MeterSerialNumberInUseError(fields, requestId);
  }
  if (result.status === 409 || result.status === 412) {
    throw new UtilityConflictError(fields, requestId);
  }
  if (!result.ok || envelope === null || !("data" in envelope)) {
    throw new UtilityClientError(undefined, fields, requestId);
  }
  return { data: envelope.data, page: envelope.page };
}

function csrfToken(): string {
  const prefix = "__Host-prm_csrf=";
  const part = document.cookie
    .split(";")
    .map((value) => value.trim())
    .find((value) => value.startsWith(prefix));
  if (part === undefined) throw new UtilityClientError();
  return decodeURIComponent(part.slice(prefix.length));
}

function mutation(input: unknown, idempotencyKey?: string): RequestInit {
  return {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrfToken(),
      ...(idempotencyKey === undefined
        ? {}
        : { "Idempotency-Key": idempotencyKey }),
    },
    body: JSON.stringify(input),
  };
}

function page<T>(
  envelope: Envelope,
  parse: (value: unknown) => T,
): UtilityPage<T> {
  if (!Array.isArray(envelope.data)) throw new UtilityClientError();
  const metadata = object(envelope.page);
  return {
    items: envelope.data.map(parse),
    nextCursor: nullableString(metadata.next_cursor),
  };
}

function correction(value: unknown): ReadingCorrection {
  const item = object(value);
  return {
    id: string(item.id),
    previous_value: string(item.previous_value),
    corrected_value: string(item.corrected_value),
    reason: string(item.reason),
    occurred_at: string(item.occurred_at),
    actor_id: string(item.actor_id),
    authorization_reference: string(item.authorization_reference),
  };
}

function meter(value: unknown): UtilityMeter {
  const item = object(value);
  const replacement = object(item.replacement);
  if (typeof item.current !== "boolean") throw new UtilityClientError();
  return {
    id: string(item.id),
    property_id: string(item.property_id),
    unit_id: string(item.unit_id),
    utility_type: utilityType(item.utility_type),
    serial_number: string(item.serial_number),
    measurement_unit_code: string(item.measurement_unit_code),
    description: nullableString(item.description),
    installed_date: string(item.installed_date),
    failure_date: nullableString(item.failure_date),
    deactivated_date: nullableString(item.deactivated_date),
    current: item.current,
    version: number(item.version),
    memo: nullableString(item.memo),
    replacement: {
      replaced_meter_id: nullableString(replacement.replaced_meter_id),
      replacement_meter_id: nullableString(replacement.replacement_meter_id),
      replacement_date: nullableString(replacement.replacement_date),
    },
    readings_url: string(item.readings_url),
  };
}

function reading(value: unknown): UtilityReading {
  const item = object(value);
  const source = object(item.source);
  if (typeof item.validated !== "boolean" || !Array.isArray(item.corrections)) {
    throw new UtilityClientError();
  }
  const validatedAt = nullableString(item.validated_at);
  const validatedBy = nullableString(item.validated_by);
  const evidence = {
    id: string(item.id),
    property_id: string(item.property_id),
    meter_id: string(item.meter_id),
    unit_id: string(item.unit_id),
    utility_type: utilityType(item.utility_type),
    measurement_unit_code: string(item.measurement_unit_code),
    reading_date: string(item.reading_date),
    original_value: string(item.original_value),
    effective_value: string(item.effective_value),
    source: { kind: string(source.kind), evidence: string(source.evidence) },
    version: number(item.version),
    corrections: item.corrections.map(correction),
  };
  if (item.validated) {
    if (validatedAt === null || validatedBy === null) {
      throw new UtilityClientError();
    }
    return {
      ...evidence,
      validated: true,
      validated_at: validatedAt,
      validated_by: validatedBy,
    };
  }
  if (validatedAt !== null || validatedBy !== null) {
    throw new UtilityClientError();
  }
  return {
    ...evidence,
    validated: false,
    validated_at: null,
    validated_by: null,
  };
}

function rate(value: unknown): UtilityRate {
  const item = object(value);
  return {
    id: string(item.id),
    utility_type: utilityType(item.utility_type),
    measurement_unit_code: string(item.measurement_unit_code),
    rate_usd_per_unit: string(item.rate_usd_per_unit),
    effective_date: string(item.effective_date),
    notice_at: string(item.notice_at),
    notice_evidence: string(item.notice_evidence),
    source_memo: nullableString(item.source_memo),
  };
}

function affectedCalculation(value: unknown): AffectedCalculation {
  const item = object(value);
  const issuedLine = object(item.issued_line);
  const billingEffectKind = item.billing_effect_kind;
  if (
    billingEffectKind !== "PRE_ISSUANCE_INPUT" &&
    billingEffectKind !== "POST_ISSUANCE_NO_AMOUNT_CHANGE" &&
    billingEffectKind !== "POST_ISSUANCE_ADJUSTMENT"
  ) {
    throw new UtilityClientError();
  }
  return {
    consumption_period_id: string(item.consumption_period_id),
    previous_consumption_quantity: string(item.previous_consumption_quantity),
    corrected_consumption_quantity: string(item.corrected_consumption_quantity),
    billing_effect_kind: billingEffectKind,
    issued_line: {
      invoice_line_id: nullableString(issuedLine.invoice_line_id),
      source_invoice_id: nullableString(issuedLine.source_invoice_id),
      calculated_difference_usd_cents:
        issuedLine.calculated_difference_usd_cents === null
          ? null
          : number(issuedLine.calculated_difference_usd_cents),
      invoice_adjustment_id: nullableString(issuedLine.invoice_adjustment_id),
    },
  };
}

function calculation(value: unknown): UtilityCalculation {
  const item = object(value);
  if (
    item.status !== "READY" &&
    item.status !== "PENDING_FUTURE_ACTUAL_BASIS"
  ) {
    throw new UtilityClientError();
  }
  if (
    !Array.isArray(item.basis_period_ids) ||
    !Array.isArray(item.basis_sources)
  ) {
    throw new UtilityClientError();
  }
  const basisKind = item.basis_kind;
  if (
    basisKind !== null &&
    basisKind !== "LATEST_THREE_HISTORICAL" &&
    basisKind !== "ALL_AVAILABLE_HISTORICAL_ONE_OR_TWO" &&
    basisKind !== "FIRST_COMPLETE_FUTURE_ZERO_HISTORY"
  ) {
    throw new UtilityClientError();
  }
  const kind = item.calculation_kind;
  if (kind !== null && kind !== "ACTUAL" && kind !== "BROKEN_METER_ESTIMATE") {
    throw new UtilityClientError();
  }
  return {
    status: item.status,
    property_id: string(item.property_id),
    unit_id: string(item.unit_id),
    utility_type: utilityType(item.utility_type),
    consumption_period_id: nullableString(item.consumption_period_id),
    calculation_kind: kind,
    period_start: nullableString(item.period_start),
    period_end: nullableString(item.period_end),
    consumption_quantity: nullableString(item.consumption_quantity),
    represented_days:
      item.represented_days === null ? null : number(item.represented_days),
    meter_id: nullableString(item.meter_id),
    start_reading_id: nullableString(item.start_reading_id),
    end_reading_id: nullableString(item.end_reading_id),
    failed_meter_id: nullableString(item.failed_meter_id),
    replacement_meter_id: nullableString(item.replacement_meter_id),
    basis_kind: basisKind,
    basis_period_ids: item.basis_period_ids.map(string),
    basis_sources: item.basis_sources.map((sourceValue) => {
      const source = object(sourceValue);
      return {
        consumption_period_id: string(source.consumption_period_id),
        meter_id: string(source.meter_id),
        start_reading_id: string(source.start_reading_id),
        end_reading_id: string(source.end_reading_id),
      };
    }),
    total_basis_consumption: nullableString(item.total_basis_consumption),
    total_basis_days:
      item.total_basis_days === null ? null : number(item.total_basis_days),
    weighted_daily_average: nullableString(item.weighted_daily_average),
    generation_date: nullableString(item.generation_date),
    rate_id: nullableString(item.rate_id),
    rate_effective_date: nullableString(item.rate_effective_date),
    rate_usd_per_unit: nullableString(item.rate_usd_per_unit),
    amount_usd_cents:
      item.amount_usd_cents === null ? null : number(item.amount_usd_cents),
  };
}

function query(cursor?: string): string {
  return cursor === undefined
    ? "?limit=25"
    : `?limit=25&cursor=${encodeURIComponent(cursor)}`;
}

async function exhaustCursor<T>(
  loadPage: (cursor?: string) => Promise<UtilityPage<T>>,
): Promise<T[]> {
  const items: T[] = [];
  const nextCursors = new Set<string>();
  let cursor: string | undefined;
  for (;;) {
    const current = await loadPage(cursor);
    items.push(...current.items);
    if (current.nextCursor === null) return items;
    if (nextCursors.has(current.nextCursor)) throw new UtilityClientError();
    nextCursors.add(current.nextCursor);
    cursor = current.nextCursor;
  }
}

export const utilityApi: UtilityApi = {
  async loadMeters(unitId, cursor) {
    return page(
      await response(
        `/api/v1/units/${encodeURIComponent(unitId)}/meters${query(cursor)}`,
      ),
      meter,
    );
  },
  async loadReadings(meterId, cursor) {
    return page(
      await response(
        `/api/v1/meters/${encodeURIComponent(meterId)}/readings${query(cursor)}`,
      ),
      reading,
    );
  },
  async loadRates(propertyId, cursor) {
    return page(
      await response(
        `/api/v1/properties/${encodeURIComponent(propertyId)}/utility-rates${query(cursor)}`,
      ),
      rate,
    );
  },
  async load(propertyId, unitId) {
    const [meters, rates] = await Promise.all([
      exhaustCursor((cursor) => this.loadMeters(unitId, cursor)),
      exhaustCursor((cursor) => this.loadRates(propertyId, cursor)),
    ]);
    const readingPages = await Promise.all(
      meters.map(
        async (item) =>
          [
            item.id,
            await exhaustCursor((cursor) => this.loadReadings(item.id, cursor)),
          ] as const,
      ),
    );
    return {
      meters,
      readings: Object.fromEntries(readingPages),
      rates,
    };
  },
  async installMeter(unitId, input, idempotencyKey) {
    return meter(
      (
        await response(
          `/api/v1/units/${encodeURIComponent(unitId)}/meters`,
          mutation(input, idempotencyKey),
        )
      ).data,
    );
  },
  async replaceMeter(meterId, input, idempotencyKey) {
    return meter(
      (
        await response(
          `/api/v1/meters/${encodeURIComponent(meterId)}/replace`,
          mutation(input, idempotencyKey),
        )
      ).data,
    );
  },
  async recordReading(meterId, input, idempotencyKey) {
    return reading(
      (
        await response(
          `/api/v1/meters/${encodeURIComponent(meterId)}/readings`,
          mutation(input, idempotencyKey),
        )
      ).data,
    );
  },
  async correctReading(readingId, input, idempotencyKey) {
    const data = object(
      (
        await response(
          `/api/v1/utility-readings/${encodeURIComponent(readingId)}/correct`,
          mutation(input, idempotencyKey),
        )
      ).data,
    );
    if (!Array.isArray(data.affected_calculations))
      throw new UtilityClientError();
    return {
      reading: reading(data.reading),
      correction: correction(data.correction),
      affected_calculations:
        data.affected_calculations.map(affectedCalculation),
    };
  },
  async recordBatch(propertyId, mode, items, envelopeIdempotencyKey) {
    const data = object(
      (
        await response(
          `/api/v1/properties/${encodeURIComponent(propertyId)}/utility-readings:batch`,
          mutation({ mode, items }, envelopeIdempotencyKey),
        )
      ).data,
    );
    if (!Array.isArray(data.items)) throw new UtilityClientError();
    return data.items.map((value): BatchReadingResult => {
      const item = object(value);
      if (item.status !== "SUCCEEDED" && item.status !== "FAILED") {
        throw new UtilityClientError();
      }
      const error = item.error === null ? null : object(item.error);
      return {
        index: number(item.index),
        idempotency_key: string(item.idempotency_key),
        status: item.status,
        reading: item.reading === null ? null : reading(item.reading),
        error: error === null ? null : { code: string(error.code) },
      };
    });
  },
  async createRate(propertyId, input, idempotencyKey) {
    return rate(
      (
        await response(
          `/api/v1/properties/${encodeURIComponent(propertyId)}/utility-rates`,
          mutation(input, idempotencyKey),
        )
      ).data,
    );
  },
  async preview(input) {
    return calculation(
      (await response("/api/v1/utility-billing/preview", mutation(input))).data,
    );
  },
};
