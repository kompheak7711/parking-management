export interface ConfigurationCapabilities {
  read: boolean;
  manage_service_rates: boolean;
  manage_utility_rates: boolean;
  manage_exchange_rates: boolean;
}

export interface ConfiguredService {
  id: string;
  property_id: string;
  service_code: string;
  display_name: string;
}

export interface ServiceRate {
  id: string;
  property_service_id: string;
  service_code: string;
  display_name: string;
  monthly_rate_usd_cents: number;
  effective_date: string;
  source_memo: string | null;
}

export interface UtilityRate {
  id: string;
  utility_type: "ELECTRICITY" | "WATER";
  measurement_unit_code: string;
  rate_usd_per_unit: string;
  effective_date: string;
  notice_at: string;
  notice_evidence: string;
  source_memo: string | null;
}

export interface ExchangeRate {
  id: string;
  reference_rate_khr_per_usd: string;
  system_rate_khr_per_usd: number;
  rate_source: "ABA_AUTOMATIC" | "ABA_EQUIVALENT_MANUAL";
  source_reference: string | null;
  applicable_at: string;
  usd_amount_cents: number;
  unrounded_payable_khr: string;
  payable_khr: number;
  fallback_reason: string | null;
}

export interface ConfigurationPage<Record> {
  items: Record[];
  nextCursor: string | null;
}

export interface EffectiveConfigurationSnapshot {
  capabilities: ConfigurationCapabilities;
  configuredServices: ConfiguredService[];
  configuredServiceNextCursor: string | null;
  serviceRates: ServiceRate[];
  serviceNextCursor: string | null;
  utilityRates: UtilityRate[];
  utilityNextCursor: string | null;
  exchangeRates: ExchangeRate[];
  exchangeNextCursor: string | null;
}

export type ExchangeRateInput =
  | { rate_source: "ABA_AUTOMATIC"; usd_amount_cents: number }
  | {
      rate_source: "ABA_EQUIVALENT_MANUAL";
      reference_rate_khr_per_usd: string;
      source_reference: string;
      applicable_at: string;
      automatic_source_unavailable: true;
      fallback_reason: string;
      usd_amount_cents: number;
    };

export interface EffectiveConfigurationApi {
  load: (propertyId: string) => Promise<EffectiveConfigurationSnapshot>;
  loadConfiguredServices: (
    propertyId: string,
    cursor: string,
  ) => Promise<ConfigurationPage<ConfiguredService>>;
  loadServiceRates: (
    propertyId: string,
    cursor: string,
  ) => Promise<ConfigurationPage<ServiceRate>>;
  loadUtilityRates: (
    propertyId: string,
    cursor: string,
  ) => Promise<ConfigurationPage<UtilityRate>>;
  loadExchangeRates: (
    propertyId: string,
    cursor: string,
  ) => Promise<ConfigurationPage<ExchangeRate>>;
  createServiceRate: (
    propertyId: string,
    input: {
      property_service_id: string;
      monthly_rate_usd_cents: number;
      effective_date: string;
      source_memo: string | null;
    },
    idempotencyKey: string,
  ) => Promise<ServiceRate>;
  createUtilityRate: (
    propertyId: string,
    input: {
      utility_type: "ELECTRICITY" | "WATER";
      measurement_unit_code: string;
      rate_usd_per_unit: string;
      effective_date: string;
      notice_at: string;
      notice_evidence: string;
      source_memo: string | null;
    },
    idempotencyKey: string,
  ) => Promise<UtilityRate>;
  confirmExchangeRate: (
    propertyId: string,
    input: ExchangeRateInput,
    idempotencyKey: string,
  ) => Promise<ExchangeRate>;
}

export class EffectiveConfigurationError extends Error {
  readonly fields: string[];
  readonly requestId: string | null;

  constructor(
    message = "The effective configuration request failed.",
    fields: string[] = [],
    requestId: string | null = null,
  ) {
    super(message);
    this.name = "EffectiveConfigurationError";
    this.fields = fields;
    this.requestId = requestId;
  }
}

export class EffectiveConfigurationUnavailableError extends EffectiveConfigurationError {
  constructor(fields: string[] = [], requestId: string | null = null) {
    super(
      "Effective configuration is unavailable for this session.",
      fields,
      requestId,
    );
    this.name = "EffectiveConfigurationUnavailableError";
  }
}

export class EffectiveConfigurationConflictError extends EffectiveConfigurationError {
  constructor(fields: string[] = [], requestId: string | null = null) {
    super(
      "Configuration history changed or this command was already used.",
      fields,
      requestId,
    );
    this.name = "EffectiveConfigurationConflictError";
  }
}

function object(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new EffectiveConfigurationError();
  }
  return value as Record<string, unknown>;
}

interface Envelope {
  data: unknown;
  meta: Record<string, unknown>;
  page?: unknown;
}

async function response(path: string, init: RequestInit): Promise<Envelope> {
  let result: Response;
  try {
    result = await fetch(path, { credentials: "include", ...init });
  } catch {
    throw new EffectiveConfigurationError();
  }
  let payload: unknown = null;
  try {
    payload = await result.json();
  } catch {
    payload = null;
  }
  const rawEnvelope =
    typeof payload === "object" && payload !== null && !Array.isArray(payload)
      ? (payload as Record<string, unknown>)
      : null;
  const rawMeta =
    rawEnvelope !== null &&
    typeof rawEnvelope.meta === "object" &&
    rawEnvelope.meta !== null &&
    !Array.isArray(rawEnvelope.meta)
      ? (rawEnvelope.meta as Record<string, unknown>)
      : null;
  const rawError =
    rawEnvelope !== null &&
    typeof rawEnvelope.error === "object" &&
    rawEnvelope.error !== null &&
    !Array.isArray(rawEnvelope.error)
      ? (rawEnvelope.error as Record<string, unknown>)
      : null;
  const requestId =
    rawMeta !== null &&
    typeof rawMeta.request_id === "string" &&
    rawMeta.request_id.length <= 128
      ? rawMeta.request_id
      : null;
  const fields =
    rawError !== null && Array.isArray(rawError.fields)
      ? rawError.fields
          .filter(
            (field): field is string =>
              typeof field === "string" &&
              field.length > 0 &&
              field.length <= 128 &&
              /^[A-Za-z0-9_.[\]-]+$/.test(field),
          )
          .slice(0, 25)
      : [];
  if (result.status === 401 || result.status === 403) {
    throw new EffectiveConfigurationUnavailableError(fields, requestId);
  }
  if (result.status === 409 || result.status === 412) {
    throw new EffectiveConfigurationConflictError(fields, requestId);
  }
  if (!result.ok)
    throw new EffectiveConfigurationError(undefined, fields, requestId);
  try {
    const envelope = object(payload);
    const meta = object(envelope.meta);
    if (typeof meta.request_id !== "string") {
      throw new EffectiveConfigurationError();
    }
    return { data: envelope.data, meta, page: envelope.page };
  } catch (error) {
    if (
      error instanceof EffectiveConfigurationError ||
      error instanceof EffectiveConfigurationUnavailableError ||
      error instanceof EffectiveConfigurationConflictError
    ) {
      throw error;
    }
    throw new EffectiveConfigurationError();
  }
}

function csrfToken(): string {
  const prefix = "__Host-prm_csrf=";
  const value = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  if (value === undefined) throw new EffectiveConfigurationError();
  const token = decodeURIComponent(value.slice(prefix.length));
  if (token.length === 0) throw new EffectiveConfigurationError();
  return token;
}

function commandHeaders(idempotencyKey: string): HeadersInit {
  return {
    "Content-Type": "application/json",
    "Idempotency-Key": idempotencyKey,
    "X-CSRF-Token": csrfToken(),
  };
}

function capabilities(value: unknown): ConfigurationCapabilities {
  const item = object(value);
  const keys = [
    "read",
    "manage_service_rates",
    "manage_utility_rates",
    "manage_exchange_rates",
  ] as const;
  if (keys.some((key) => typeof item[key] !== "boolean")) {
    throw new EffectiveConfigurationError();
  }
  return {
    read: item.read as boolean,
    manage_service_rates: item.manage_service_rates as boolean,
    manage_utility_rates: item.manage_utility_rates as boolean,
    manage_exchange_rates: item.manage_exchange_rates as boolean,
  };
}

function list<T>(value: unknown, parse: (item: unknown) => T): T[] {
  if (!Array.isArray(value)) throw new EffectiveConfigurationError();
  return value.map(parse);
}

function configuredService(value: unknown): ConfiguredService {
  const item = object(value);
  if (
    typeof item.id !== "string" ||
    typeof item.property_id !== "string" ||
    typeof item.service_code !== "string" ||
    typeof item.display_name !== "string"
  )
    throw new EffectiveConfigurationError();
  return item as unknown as ConfiguredService;
}

function serviceRate(value: unknown): ServiceRate {
  const item = object(value);
  if (
    typeof item.id !== "string" ||
    typeof item.property_service_id !== "string" ||
    typeof item.service_code !== "string" ||
    typeof item.display_name !== "string" ||
    typeof item.monthly_rate_usd_cents !== "number" ||
    typeof item.effective_date !== "string" ||
    (item.source_memo !== null && typeof item.source_memo !== "string")
  )
    throw new EffectiveConfigurationError();
  return item as unknown as ServiceRate;
}

function utilityRate(value: unknown): UtilityRate {
  const item = object(value);
  if (
    typeof item.id !== "string" ||
    (item.utility_type !== "ELECTRICITY" && item.utility_type !== "WATER") ||
    typeof item.measurement_unit_code !== "string" ||
    typeof item.rate_usd_per_unit !== "string" ||
    typeof item.effective_date !== "string" ||
    typeof item.notice_at !== "string" ||
    typeof item.notice_evidence !== "string" ||
    (item.source_memo !== null && typeof item.source_memo !== "string")
  )
    throw new EffectiveConfigurationError();
  return item as unknown as UtilityRate;
}

function exchangeRate(value: unknown): ExchangeRate {
  const item = object(value);
  if (
    typeof item.id !== "string" ||
    typeof item.reference_rate_khr_per_usd !== "string" ||
    typeof item.system_rate_khr_per_usd !== "number" ||
    (item.rate_source !== "ABA_AUTOMATIC" &&
      item.rate_source !== "ABA_EQUIVALENT_MANUAL") ||
    (item.source_reference !== null &&
      typeof item.source_reference !== "string") ||
    typeof item.applicable_at !== "string" ||
    typeof item.usd_amount_cents !== "number" ||
    typeof item.unrounded_payable_khr !== "string" ||
    typeof item.payable_khr !== "number" ||
    (item.fallback_reason !== null && typeof item.fallback_reason !== "string")
  )
    throw new EffectiveConfigurationError();
  return item as unknown as ExchangeRate;
}

function page<Record>(
  envelope: Envelope,
  parse: (item: unknown) => Record,
): ConfigurationPage<Record> {
  const metadata = object(envelope.page);
  if (
    typeof metadata.limit !== "number" ||
    (metadata.next_cursor !== null && typeof metadata.next_cursor !== "string")
  ) {
    throw new EffectiveConfigurationError();
  }
  return {
    items: list(envelope.data, parse),
    nextCursor: metadata.next_cursor,
  };
}

async function historyPage<Record>(
  propertyId: string,
  resource: string,
  cursor: string | null,
  parse: (item: unknown) => Record,
): Promise<ConfigurationPage<Record>> {
  const query = new URLSearchParams({ limit: "25" });
  if (cursor !== null) query.set("cursor", cursor);
  return page(
    await response(
      `/api/v1/properties/${encodeURIComponent(propertyId)}/${resource}?${query.toString()}`,
      { method: "GET" },
    ),
    parse,
  );
}

async function configuredServicePage(
  propertyId: string,
  cursor: string | null,
): Promise<ConfigurationPage<ConfiguredService>> {
  return historyPage(
    propertyId,
    "configured-services",
    cursor,
    configuredService,
  );
}

async function load(
  propertyId: string,
): Promise<EffectiveConfigurationSnapshot> {
  const encoded = encodeURIComponent(propertyId);
  const grants = capabilities(
    (
      await response(
        `/api/v1/properties/${encoded}/configuration-capabilities`,
        {
          method: "GET",
        },
      )
    ).data,
  );
  if (!grants.read) throw new EffectiveConfigurationUnavailableError();
  const [services, serviceRates, utilityRates, exchangeRates] =
    await Promise.all([
      configuredServicePage(propertyId, null),
      historyPage(propertyId, "service-rates", null, serviceRate),
      historyPage(propertyId, "utility-rates", null, utilityRate),
      historyPage(propertyId, "exchange-rates", null, exchangeRate),
    ]);
  return {
    capabilities: grants,
    configuredServices: services.items,
    configuredServiceNextCursor: services.nextCursor,
    serviceRates: serviceRates.items,
    serviceNextCursor: serviceRates.nextCursor,
    utilityRates: utilityRates.items,
    utilityNextCursor: utilityRates.nextCursor,
    exchangeRates: exchangeRates.items,
    exchangeNextCursor: exchangeRates.nextCursor,
  };
}

async function mutate<T>(
  path: string,
  body: object,
  idempotencyKey: string,
  parse: (value: unknown) => T,
): Promise<T> {
  return parse(
    (
      await response(path, {
        method: "POST",
        headers: commandHeaders(idempotencyKey),
        body: JSON.stringify(body),
      })
    ).data,
  );
}

export const effectiveConfigurationApi: EffectiveConfigurationApi = {
  load,
  loadConfiguredServices: (propertyId, cursor) =>
    configuredServicePage(propertyId, cursor),
  loadServiceRates: (propertyId, cursor) =>
    historyPage(propertyId, "service-rates", cursor, serviceRate),
  loadUtilityRates: (propertyId, cursor) =>
    historyPage(propertyId, "utility-rates", cursor, utilityRate),
  loadExchangeRates: (propertyId, cursor) =>
    historyPage(propertyId, "exchange-rates", cursor, exchangeRate),
  createServiceRate: (propertyId, input, idempotencyKey) =>
    mutate(
      `/api/v1/properties/${encodeURIComponent(propertyId)}/service-rates`,
      input,
      idempotencyKey,
      serviceRate,
    ),
  createUtilityRate: (propertyId, input, idempotencyKey) =>
    mutate(
      `/api/v1/properties/${encodeURIComponent(propertyId)}/utility-rates`,
      input,
      idempotencyKey,
      utilityRate,
    ),
  confirmExchangeRate: (propertyId, input, idempotencyKey) =>
    mutate(
      `/api/v1/properties/${encodeURIComponent(propertyId)}/exchange-rates:confirm`,
      input,
      idempotencyKey,
      exchangeRate,
    ),
};
