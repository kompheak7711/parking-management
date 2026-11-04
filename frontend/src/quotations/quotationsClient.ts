// V1.1 part 6 (DL-123, API-QT-001): Office › Invoices › Quotations. A Quotation is made, then
// the Customer signs it (the server issues the Products Invoice and takes the Items out of
// stock) or refuses it. The server checks every right, price and stock; this client only reads
// and sends.

export type QuotationStatus = "WAITING" | "SIGNED" | "REPLACED" | "REFUSED";
/** The status today: a waiting Quotation past its day is EXPIRED. */
export type QuotationState = QuotationStatus | "EXPIRED";

export interface TakenFrom {
  unit_id: string;
  unit_number: string;
  item_id: string;
  number: number;
  name_en: string;
  name_kh: string | null;
  movement_number: string;
}

export interface QuotationLine {
  position: number;
  product_id: string;
  sku: string;
  name_en: string;
  name_kh: string | null;
  kind: "ITEM" | "SERVICE";
  measure_unit: string;
  quantity: number;
  list_price_usd_cents: number;
  price_usd_cents: number;
  amount_usd_cents: number;
  taken_from: TakenFrom | null;
}

export interface Quotation {
  quotation_id: string;
  quotation_number: string;
  status: QuotationStatus;
  state: QuotationState;
  customer_id: string;
  customer_name: string;
  customer_phone: string | null;
  lease_id: string | null;
  unit_number: string | null;
  note: string | null;
  made_on: string;
  valid_until: string;
  due_days: number;
  total_usd_cents: number;
  lowered_reason: string | null;
  replaces_id: string | null;
  replaces_number: string | null;
  replaced_by_id: string | null;
  replaced_by_number: string | null;
  signed_on: string | null;
  signed_at: string | null;
  signed_by_name: string | null;
  invoice_id: string | null;
  invoice_number: string | null;
  invoice_status: string | null;
  refused_reason: string | null;
  closed_at: string | null;
  closed_by_name: string | null;
  created_at: string;
  created_by_name: string | null;
  version: number;
  lines: QuotationLine[];
}

export interface NewQuotation {
  customer_id: string;
  lease_id: string | null;
  note: string | null;
  replaces_id: string | null;
  lowered_reason: string | null;
  lines: { product_id: string; quantity: number; price_usd_cents: number }[];
}

export interface Take {
  position: number;
  unit_id: string;
  item_id: string;
  number: number;
}

export interface QuotationsApi {
  list: (propertyId: string) => Promise<Quotation[]>;
  get: (propertyId: string, quotationId: string) => Promise<Quotation>;
  make: (propertyId: string, quotation: NewQuotation) => Promise<Quotation>;
  sign: (
    propertyId: string,
    quotation: Quotation,
    signedOn: string,
    takes: Take[],
  ) => Promise<Quotation>;
  refuse: (
    propertyId: string,
    quotation: Quotation,
    reason: string,
  ) => Promise<Quotation>;
}

export class QuotationsError extends Error {
  /** The HTTP status when the server answered: 403 no right, 404, 409 refused (an Item not in
   * stock, the Quotation no longer waiting), 412 changed meanwhile, 422 refused. */
  constructor(readonly status: number | null = null) {
    super("The Quotation command was not completed.");
    this.name = "QuotationsError";
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
  if (entry === undefined) throw new QuotationsError();
  const token = decodeURIComponent(entry.slice(prefix.length));
  if (token === "") throw new QuotationsError();
  return token;
}

async function request(
  path: string,
  init: RequestInit = { method: "GET" },
): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(path, { credentials: "include", ...init });
  } catch {
    throw new QuotationsError();
  }
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) throw new QuotationsError(response.status);
  if (!isObject(payload) || !("data" in payload)) throw new QuotationsError();
  return payload.data;
}

function send(method: string, body: unknown, version?: number): RequestInit {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-CSRF-Token": csrfToken(),
  };
  if (version !== undefined) headers["If-Match"] = `"${String(version)}"`;
  return { method, headers, body: JSON.stringify(body) };
}

function base(propertyId: string): string {
  return `/api/v1/properties/${encodeURIComponent(propertyId)}/quotations`;
}

function text(value: unknown): string {
  if (typeof value !== "string") throw new QuotationsError();
  return value;
}

function maybeText(value: unknown): string | null {
  return value === null || value === undefined ? null : text(value);
}

function whole(value: unknown): number {
  if (typeof value !== "number" || !Number.isInteger(value))
    throw new QuotationsError();
  return value;
}

function record(value: unknown): Record<string, unknown> {
  if (!isObject(value)) throw new QuotationsError();
  return value;
}

function list(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw new QuotationsError();
  return value;
}

const STATES: readonly QuotationState[] = [
  "WAITING",
  "SIGNED",
  "REPLACED",
  "REFUSED",
  "EXPIRED",
];

function stateOf(value: unknown): QuotationState {
  const found = STATES.find((state) => state === value);
  if (found === undefined) throw new QuotationsError();
  return found;
}

function takenOf(value: unknown): TakenFrom | null {
  if (value === null || value === undefined) return null;
  const row = record(value);
  return {
    unit_id: text(row.unit_id),
    unit_number: text(row.unit_number),
    item_id: text(row.item_id),
    number: whole(row.number),
    name_en: text(row.name_en),
    name_kh: maybeText(row.name_kh),
    movement_number: text(row.movement_number),
  };
}

function lineOf(value: unknown): QuotationLine {
  const row = record(value);
  return {
    position: whole(row.position),
    product_id: text(row.product_id),
    sku: text(row.sku),
    name_en: text(row.name_en),
    name_kh: maybeText(row.name_kh),
    kind: row.kind === "SERVICE" ? "SERVICE" : "ITEM",
    measure_unit: text(row.measure_unit),
    quantity: whole(row.quantity),
    list_price_usd_cents: whole(row.list_price_usd_cents),
    price_usd_cents: whole(row.price_usd_cents),
    amount_usd_cents: whole(row.amount_usd_cents),
    taken_from: takenOf(row.taken_from),
  };
}

export function quotationOf(value: unknown): Quotation {
  const row = record(value);
  const status = stateOf(row.status);
  if (status === "EXPIRED") throw new QuotationsError();
  return {
    quotation_id: text(row.quotation_id),
    quotation_number: text(row.quotation_number),
    status,
    state: stateOf(row.state),
    customer_id: text(row.customer_id),
    customer_name: text(row.customer_name),
    customer_phone: maybeText(row.customer_phone),
    lease_id: maybeText(row.lease_id),
    unit_number: maybeText(row.unit_number),
    note: maybeText(row.note),
    made_on: text(row.made_on),
    valid_until: text(row.valid_until),
    due_days: whole(row.due_days),
    total_usd_cents: whole(row.total_usd_cents),
    lowered_reason: maybeText(row.lowered_reason),
    replaces_id: maybeText(row.replaces_id),
    replaces_number: maybeText(row.replaces_number),
    replaced_by_id: maybeText(row.replaced_by_id),
    replaced_by_number: maybeText(row.replaced_by_number),
    signed_on: maybeText(row.signed_on),
    signed_at: maybeText(row.signed_at),
    signed_by_name: maybeText(row.signed_by_name),
    invoice_id: maybeText(row.invoice_id),
    invoice_number: maybeText(row.invoice_number),
    invoice_status: maybeText(row.invoice_status),
    refused_reason: maybeText(row.refused_reason),
    closed_at: maybeText(row.closed_at),
    closed_by_name: maybeText(row.closed_by_name),
    created_at: text(row.created_at),
    created_by_name: maybeText(row.created_by_name),
    version: whole(row.version),
    lines: list(row.lines ?? []).map(lineOf),
  };
}

function one(propertyId: string, quotationId: string): string {
  return `${base(propertyId)}/${encodeURIComponent(quotationId)}`;
}

export const quotationsApi: QuotationsApi = {
  list: async (propertyId) =>
    list(await request(base(propertyId))).map(quotationOf),
  get: async (propertyId, quotationId) =>
    quotationOf(await request(one(propertyId, quotationId))),
  make: async (propertyId, quotation) =>
    quotationOf(await request(base(propertyId), send("POST", quotation))),
  sign: async (propertyId, quotation, signedOn, takes) =>
    quotationOf(
      await request(
        `${one(propertyId, quotation.quotation_id)}/sign`,
        send("POST", { signed_on: signedOn, takes }, quotation.version),
      ),
    ),
  refuse: async (propertyId, quotation, reason) =>
    quotationOf(
      await request(
        `${one(propertyId, quotation.quotation_id)}/refuse`,
        send("POST", { reason }, quotation.version),
      ),
    ),
};
