export interface PaymentMethodConfiguration {
  code: string;
  display_name: string;
  accepted: boolean;
}

export interface PropertyBusinessConfiguration {
  property_id: string;
  name: string;
  address_text: string | null;
  timezone_name: "Asia/Phnom_Penh";
  payment_methods: PaymentMethodConfiguration[];
  version: number;
}

export interface PropertyConfigurationApi {
  load: (propertyId: string) => Promise<PropertyBusinessConfiguration>;
  updateSource: (
    property: PropertyBusinessConfiguration,
    source: { name: string; address_text: string | null },
  ) => Promise<PropertyBusinessConfiguration>;
  updatePaymentMethods: (
    property: PropertyBusinessConfiguration,
    methods: PaymentMethodConfiguration[],
  ) => Promise<PropertyBusinessConfiguration>;
}

// The change was saved, but reading the Property again afterwards failed.
export class PropertySavedReadFailedError extends Error {
  constructor() {
    super("The change was saved, but the Property could not be read again.");
  }
}

async function loadAfterSave(
  propertyId: string,
): Promise<PropertyBusinessConfiguration> {
  try {
    return await load(propertyId);
  } catch {
    throw new PropertySavedReadFailedError();
  }
}

export class PropertyConfigurationUnavailableError extends Error {
  constructor() {
    super("Business configuration is unavailable for this session.");
    this.name = "PropertyConfigurationUnavailableError";
  }
}

export class PropertyConfigurationError extends Error {
  /** The HTTP status when the server answered (V1-058 R7b-4: 409 or 412 means it changed). */
  constructor(readonly status: number | null = null) {
    super("The business configuration command was not completed.");
    this.name = "PropertyConfigurationError";
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function csrfToken(): string | null {
  const prefix = "__Host-prm_csrf=";
  const entry = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  return entry === undefined
    ? null
    : decodeURIComponent(entry.slice(prefix.length));
}

async function request(
  path: string,
  init: RequestInit,
): Promise<Record<string, unknown>> {
  let response: Response;
  try {
    response = await fetch(path, { credentials: "include", ...init });
  } catch {
    throw new PropertyConfigurationError();
  }
  if (response.status === 401 || response.status === 403) {
    throw new PropertyConfigurationUnavailableError();
  }
  if (!response.ok) throw new PropertyConfigurationError(response.status);
  try {
    const payload: unknown = await response.json();
    if (!isObject(payload) || !isObject(payload.data)) {
      throw new PropertyConfigurationError();
    }
    return payload.data;
  } catch (error) {
    if (error instanceof PropertyConfigurationError) throw error;
    throw new PropertyConfigurationError();
  }
}

function methods(value: unknown): PaymentMethodConfiguration[] {
  if (!Array.isArray(value)) throw new PropertyConfigurationError();
  return value.map((method) => {
    if (
      !isObject(method) ||
      typeof method.code !== "string" ||
      typeof method.display_name !== "string" ||
      typeof method.accepted !== "boolean"
    ) {
      throw new PropertyConfigurationError();
    }
    return {
      code: method.code,
      display_name: method.display_name,
      accepted: method.accepted,
    };
  });
}

function property(
  resource: Record<string, unknown>,
  configuration: Record<string, unknown>,
): PropertyBusinessConfiguration {
  if (
    typeof resource.property_id !== "string" ||
    typeof resource.name !== "string" ||
    (resource.address_text !== null &&
      typeof resource.address_text !== "string") ||
    resource.timezone_name !== "Asia/Phnom_Penh" ||
    typeof resource.version !== "number" ||
    configuration.property_id !== resource.property_id ||
    configuration.timezone_name !== resource.timezone_name ||
    configuration.version !== resource.version
  ) {
    throw new PropertyConfigurationError();
  }
  return {
    property_id: resource.property_id,
    name: resource.name,
    address_text: resource.address_text,
    timezone_name: resource.timezone_name,
    payment_methods: methods(configuration.payment_methods),
    version: resource.version,
  };
}

function mutationHeaders(version: number): HeadersInit {
  const token = csrfToken();
  if (token === null || token.length === 0) {
    throw new PropertyConfigurationError();
  }
  return {
    "Content-Type": "application/json",
    "If-Match": `"${String(version)}"`,
    "X-CSRF-Token": token,
  };
}

async function load(
  propertyId: string,
): Promise<PropertyBusinessConfiguration> {
  const encoded = encodeURIComponent(propertyId);
  const [resource, configuration] = await Promise.all([
    request(`/properties/${encoded}`, { method: "GET" }),
    request(`/properties/${encoded}/configuration`, { method: "GET" }),
  ]);
  return property(resource, configuration);
}

async function updateSource(
  current: PropertyBusinessConfiguration,
  source: { name: string; address_text: string | null },
): Promise<PropertyBusinessConfiguration> {
  await request(`/properties/${encodeURIComponent(current.property_id)}`, {
    method: "PATCH",
    headers: mutationHeaders(current.version),
    body: JSON.stringify(source),
  });
  return loadAfterSave(current.property_id);
}

async function updatePaymentMethods(
  current: PropertyBusinessConfiguration,
  configuredMethods: PaymentMethodConfiguration[],
): Promise<PropertyBusinessConfiguration> {
  await request(
    `/properties/${encodeURIComponent(current.property_id)}/configuration`,
    {
      method: "PATCH",
      headers: mutationHeaders(current.version),
      body: JSON.stringify({
        timezone_name: current.timezone_name,
        payment_methods: configuredMethods,
      }),
    },
  );
  return loadAfterSave(current.property_id);
}

export const propertyConfigurationApi: PropertyConfigurationApi = {
  load,
  updateSource,
  updatePaymentMethods,
};
