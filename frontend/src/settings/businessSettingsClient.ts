// V1.1 part 2 (DL-118): Settings › Business reads and changes the business rules (with their
// history), the document numbering and the Invoice types. The server keeps every change with a
// reason; this client only reads and sends.

export type RuleUnit =
  | "USD_CENTS"
  | "PERCENT"
  | "DAYS"
  | "DAY_OF_MONTH"
  | "COUNT"
  | "MINUTES"
  | "HOURS"
  | "METRES"
  | "YES_NO"
  | "TIME_OF_DAY";

export const RULE_UNITS: readonly RuleUnit[] = [
  "USD_CENTS",
  "PERCENT",
  "DAYS",
  "DAY_OF_MONTH",
  "COUNT",
  "MINUTES",
  "HOURS",
  "METRES",
  "YES_NO",
  "TIME_OF_DAY",
];

export type RuleArea =
  | "BILLING"
  | "RESERVATIONS"
  | "PRICES"
  | "QUOTATIONS"
  | "RIEL_RATE"
  | "LEDGER"
  | "STAFF"
  | "ATTENDANCE"
  | "OTHER";

export const RULE_AREAS: readonly RuleArea[] = [
  "BILLING",
  "RESERVATIONS",
  "PRICES",
  "QUOTATIONS",
  "RIEL_RATE",
  "LEDGER",
  "STAFF",
  "ATTENDANCE",
  "OTHER",
];

export interface RuleValue {
  value: number;
  effective_from: string;
  reason: string | null;
  created_at: string;
}

export interface BusinessRule {
  code: string;
  name_en: string;
  name_kh: string;
  value_unit: RuleUnit;
  area: RuleArea;
  used_by_app: boolean;
  in_force: RuleValue | null;
  /** A change that starts later. */
  waiting: RuleValue | null;
  history: RuleValue[];
}

export interface BusinessRules {
  rules: BusinessRule[];
  /** Today at the Property (yyyy-mm-dd). */
  today: string;
}

export interface NumberRule {
  document_type: string;
  letters: string;
  format: string;
  year: number;
  last_number: number;
  next_number: string;
}

export interface InvoiceType {
  code: string;
  name_en: string;
  name_kh: string;
  late_payment: boolean;
  version: number;
}

export interface NewBusinessRule {
  code: string;
  name_en: string;
  name_kh: string;
  value_unit: RuleUnit;
  area: RuleArea;
  value: number;
  effective_from: string;
  reason: string | null;
}

export interface BusinessSettingsApi {
  rules: (propertyId: string) => Promise<BusinessRules>;
  setRule: (
    propertyId: string,
    code: string,
    change: { value: number; effective_from: string; reason: string },
  ) => Promise<BusinessRules>;
  addRule: (
    propertyId: string,
    rule: NewBusinessRule,
  ) => Promise<BusinessRules>;
  numbers: (propertyId: string) => Promise<NumberRule[]>;
  setLetters: (
    propertyId: string,
    documentType: string,
    letters: string,
  ) => Promise<NumberRule[]>;
  invoiceTypes: (propertyId: string) => Promise<InvoiceType[]>;
  setLatePayment: (
    propertyId: string,
    code: string,
    latePayment: boolean,
    reason: string,
  ) => Promise<InvoiceType[]>;
}

export class BusinessSettingsError extends Error {
  /** The HTTP status when the server answered: 403 no right, 409 taken or met another change,
   * 422 refused. */
  constructor(
    readonly status: number | null = null,
    readonly detail: string | null = null,
  ) {
    super("The business settings command was not completed.");
    this.name = "BusinessSettingsError";
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function csrfToken(): string {
  const prefix = "__Host-prm_csrf=";
  const entry = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  if (entry === undefined) throw new BusinessSettingsError();
  const token = decodeURIComponent(entry.slice(prefix.length));
  if (token === "") throw new BusinessSettingsError();
  return token;
}

async function request(
  path: string,
  init: RequestInit = { method: "GET" },
): Promise<Record<string, unknown>> {
  let response: Response;
  try {
    response = await fetch(path, { credentials: "include", ...init });
  } catch {
    throw new BusinessSettingsError();
  }
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const detail =
      isObject(payload) && typeof payload.detail === "string"
        ? payload.detail
        : null;
    throw new BusinessSettingsError(response.status, detail);
  }
  if (!isObject(payload) || !Array.isArray(payload.data)) {
    throw new BusinessSettingsError();
  }
  return payload;
}

function send(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrfToken(),
    },
    body: JSON.stringify(body),
  };
}

function base(propertyId: string): string {
  return `/api/v1/properties/${encodeURIComponent(propertyId)}`;
}

function text(value: unknown): string {
  if (typeof value !== "string") throw new BusinessSettingsError();
  return value;
}

function whole(value: unknown): number {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new BusinessSettingsError();
  }
  return value;
}

function ruleValue(value: unknown): RuleValue | null {
  if (value === null || value === undefined) return null;
  if (!isObject(value)) throw new BusinessSettingsError();
  return {
    value: whole(value.value),
    effective_from: text(value.effective_from),
    reason: value.reason === null ? null : text(value.reason),
    created_at: text(value.created_at),
  };
}

function rulesOf(payload: Record<string, unknown>): BusinessRules {
  const meta = isObject(payload.meta) ? payload.meta : {};
  const rows = payload.data as unknown[];
  return {
    today: typeof meta.today === "string" ? meta.today : "",
    rules: rows.map((row) => {
      if (!isObject(row)) throw new BusinessSettingsError();
      const unit = text(row.value_unit) as RuleUnit;
      const area = text(row.area) as RuleArea;
      if (!RULE_UNITS.includes(unit)) throw new BusinessSettingsError();
      return {
        code: text(row.code),
        name_en: text(row.name_en),
        name_kh: text(row.name_kh),
        value_unit: unit,
        area: RULE_AREAS.includes(area) ? area : "OTHER",
        used_by_app: row.used_by_app === true,
        in_force: ruleValue(row.in_force),
        waiting: ruleValue(row.waiting),
        history: Array.isArray(row.history)
          ? row.history
              .map(ruleValue)
              .filter((item): item is RuleValue => item !== null)
          : [],
      };
    }),
  };
}

function numbersOf(payload: Record<string, unknown>): NumberRule[] {
  return (payload.data as unknown[]).map((row) => {
    if (!isObject(row)) throw new BusinessSettingsError();
    return {
      document_type: text(row.document_type),
      letters: text(row.letters),
      format: text(row.format),
      year: whole(row.year),
      last_number: whole(row.last_number),
      next_number: text(row.next_number),
    };
  });
}

function typesOf(payload: Record<string, unknown>): InvoiceType[] {
  return (payload.data as unknown[]).map((row) => {
    if (!isObject(row) || typeof row.late_payment !== "boolean") {
      throw new BusinessSettingsError();
    }
    return {
      code: text(row.code),
      name_en: text(row.name_en),
      name_kh: text(row.name_kh),
      late_payment: row.late_payment,
      version: whole(row.version),
    };
  });
}

export const businessSettingsApi: BusinessSettingsApi = {
  rules: async (propertyId) =>
    rulesOf(await request(`${base(propertyId)}/business-rules`)),
  setRule: async (propertyId, code, change) =>
    rulesOf(
      await request(
        `${base(propertyId)}/business-rules/${encodeURIComponent(code)}`,
        send("PUT", change),
      ),
    ),
  addRule: async (propertyId, rule) =>
    rulesOf(
      await request(`${base(propertyId)}/business-rules`, send("POST", rule)),
    ),
  numbers: async (propertyId) =>
    numbersOf(await request(`${base(propertyId)}/number-rules`)),
  setLetters: async (propertyId, documentType, letters) =>
    numbersOf(
      await request(
        `${base(propertyId)}/number-rules/${encodeURIComponent(documentType)}`,
        send("PUT", { letters }),
      ),
    ),
  invoiceTypes: async (propertyId) =>
    typesOf(await request(`${base(propertyId)}/invoice-types`)),
  setLatePayment: async (propertyId, code, latePayment, reason) =>
    typesOf(
      await request(
        `${base(propertyId)}/invoice-types/${encodeURIComponent(code)}`,
        send("PUT", { late_payment: latePayment, reason }),
      ),
    ),
};

/** A whole-number rule value as the screen shows it (USD_CENTS money, PERCENT in hundredths). */
export function ruleValueText(
  unit: RuleUnit,
  value: number,
  language: "en" | "km",
): string {
  const km = language === "km";
  switch (unit) {
    case "USD_CENTS":
      return `$${(value / 100).toLocaleString("en-US", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })}`;
    case "PERCENT":
      return `${String(value / 100)}%`;
    case "DAYS":
      return km ? `${String(value)} ថ្ងៃ` : `${String(value)} days`;
    case "DAY_OF_MONTH":
      return km ? `ថ្ងៃទី ${String(value)}` : `Day ${String(value)}`;
    case "MINUTES":
      return km ? `${String(value)} នាទី` : `${String(value)} minutes`;
    case "HOURS":
      return km ? `${String(value)} ម៉ោង` : `${String(value)} hours`;
    case "METRES":
      return km ? `${String(value)} ម៉ែត្រ` : `${String(value)} metres`;
    case "YES_NO":
      return value === 1 ? (km ? "បាទ/ចាស" : "Yes") : km ? "ទេ" : "No";
    case "TIME_OF_DAY":
      return `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`;
    case "COUNT":
      return value.toLocaleString("en-US");
  }
}

/** What a person typed, as the whole-number value the server keeps; null when it does not fit. */
export function ruleValueFromText(
  unit: RuleUnit,
  typed: string,
): number | null {
  const value = typed.trim().replace(/[$%,]/g, "");
  if (unit === "USD_CENTS") {
    if (!/^\d+(\.\d{1,2})?$/.test(value)) return null;
    const [dollars = "0", cents = ""] = value.split(".");
    return Number(dollars) * 100 + Number(cents.padEnd(2, "0"));
  }
  if (unit === "PERCENT") {
    if (!/^\d+(\.\d{1,2})?$/.test(value)) return null;
    const [whole = "0", part = ""] = value.split(".");
    return Number(whole) * 100 + Number(part.padEnd(2, "0"));
  }
  if (unit === "TIME_OF_DAY") {
    const match = /^(\d{1,2}):(\d{2})$/.exec(value);
    if (match === null) return null;
    const hours = Number(match[1]);
    const minutes = Number(match[2]);
    return hours < 24 && minutes < 60 ? hours * 60 + minutes : null;
  }
  if (unit === "YES_NO") return value === "1" ? 1 : value === "0" ? 0 : null;
  if (!/^\d{1,11}$/.test(value)) return null;
  const number = Number(value);
  if (unit === "DAY_OF_MONTH" && (number < 1 || number > 31)) return null;
  return number;
}

/** The value as it goes back into the edit box. */
export function ruleValueInput(unit: RuleUnit, value: number): string {
  if (unit === "USD_CENTS") return (value / 100).toFixed(2);
  if (unit === "PERCENT") return String(value / 100);
  if (unit === "TIME_OF_DAY") return ruleValueText(unit, value, "en");
  return String(value);
}
