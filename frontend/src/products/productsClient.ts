// V1.1 part 4 (DL-121): Building › Products reads and changes products, prices, stock movements
// and Locations. The server sets every price, checks every right and keeps stock from going
// below 0; this client only reads and sends.

export type ProductKind = "ITEM" | "SERVICE";

export type MovementKind =
  | "PURCHASE"
  | "TRANSFER"
  | "ADJUSTMENT_IN"
  | "ADJUSTMENT_OUT";

export type MovementRowKind =
  | "PURCHASE"
  | "ADJUSTMENT_IN"
  | "ADJUSTMENT_OUT"
  | "TRANSFER_OUT"
  | "TRANSFER_IN";

/** Item units, by group (DESIGN.md round 16), then the Service units. */
export const ITEM_UNITS = [
  "PIECE",
  "SET",
  "PAIR",
  "METRE",
  "KILOGRAM",
  "LITRE",
  "BOX",
  "PACK",
  "BOTTLE",
] as const;
export const SERVICE_UNITS = ["TIME", "HOUR", "BAG"] as const;
export type MeasureUnit =
  | (typeof ITEM_UNITS)[number]
  | (typeof SERVICE_UNITS)[number];

/** Units counted in whole numbers; the others may have up to 3 decimals. */
export const WHOLE_UNITS: ReadonlySet<string> = new Set([
  "PIECE",
  "SET",
  "PAIR",
  "BOX",
  "PACK",
  "BOTTLE",
  "TIME",
  "BAG",
]);

export interface PriceRules {
  mark_up_basis_points: number | null;
  min_mark_up_basis_points: number | null;
  max_mark_up_basis_points: number | null;
  price_round_up_usd_cents: number | null;
}

export interface ProductCategory {
  code: string;
  name_en: string;
  name_kh: string | null;
  kind: ProductKind;
}

export interface Product {
  product_id: string;
  sku: string;
  name_en: string;
  name_kh: string | null;
  description: string | null;
  category_code: string;
  kind: ProductKind;
  measure_unit: string;
  cost_usd_cents: number | null;
  mark_up_basis_points: number;
  min_mark_up_basis_points: number;
  max_mark_up_basis_points: number | null;
  price_usd_cents: number | null;
  real_mark_up_basis_points: number | null;
  reorder_level: number | null;
  reorder_quantity: number | null;
  discontinued: boolean;
  version: number;
  /** The quantity in stock at every place, as a decimal text such as "3" or "2.5". */
  stock: string;
  low_stock: boolean;
}

export interface Catalogue {
  rules: PriceRules;
  categories: ProductCategory[];
  products: Product[];
}

export interface ProductFields {
  name_en: string;
  name_kh: string | null;
  description: string | null;
  category_code: string;
  measure_unit: string;
  reorder_level: number | null;
  reorder_quantity: number | null;
}

export interface NewProduct extends ProductFields {
  service_cost_usd_cents: number | null;
}

export interface MarkUps {
  mark_up_basis_points: number;
  min_mark_up_basis_points: number;
  max_mark_up_basis_points: number | null;
}

export interface PriceChange {
  price_usd_cents: number;
  cost_usd_cents: number;
  mark_up_basis_points: number;
  cause: "PURCHASE" | "SERVICE_COST" | "MARK_UP";
  created_at: string;
  created_by_name: string | null;
}

export interface PlaceRef {
  unit_id: string;
  item_id: string;
  number: number;
}

export interface Movement {
  movement_number: string;
  kind: MovementRowKind;
  product_id: string;
  sku: string;
  product_name_en: string;
  measure_unit: string;
  quantity: string;
  unit_id: string;
  unit_number: string;
  place_item_id: string;
  place_name_en: string;
  place_name_kh: string | null;
  place_number: number;
  unit_cost_usd_cents: number | null;
  supplier: string | null;
  receipt_reference: string | null;
  reason: string | null;
  business_date: string;
  recorded_at: string;
  recorded_by_name: string | null;
}

export interface NewMovement {
  kind: MovementKind;
  product_id: string;
  quantity: string;
  from: PlaceRef | null;
  to: PlaceRef | null;
  unit_cost_usd_cents: number | null;
  supplier: string | null;
  receipt_reference: string | null;
  reason: string | null;
}

export interface PlaceStock {
  product_id: string;
  sku: string;
  name_en: string;
  measure_unit: string;
  quantity: string;
}

export interface Place {
  unit_id: string;
  unit_number: string;
  for_rent: boolean;
  item_id: string;
  name_en: string;
  name_kh: string | null;
  number: number;
  stock: PlaceStock[];
}

export interface PlaceKind {
  item_id: string;
  name_en: string;
  name_kh: string | null;
}

export interface Locations {
  places: Place[];
  features: PlaceKind[];
}

export interface ProductsApi {
  catalogue: (propertyId: string) => Promise<Catalogue>;
  addProduct: (propertyId: string, product: NewProduct) => Promise<Catalogue>;
  changeProduct: (
    propertyId: string,
    product: Product,
    change: ProductFields & { discontinued: boolean },
  ) => Promise<Catalogue>;
  setMarkUps: (
    propertyId: string,
    product: Product,
    change: MarkUps,
  ) => Promise<Catalogue>;
  setServiceCost: (
    propertyId: string,
    product: Product,
    costUsdCents: number,
  ) => Promise<Catalogue>;
  prices: (propertyId: string, productId: string) => Promise<PriceChange[]>;
  movements: (propertyId: string) => Promise<Movement[]>;
  recordMovement: (
    propertyId: string,
    movement: NewMovement,
  ) => Promise<string>;
  /** V1.1 part 5: several movements saved together or not at all. */
  recordMovements: (
    propertyId: string,
    movements: NewMovement[],
  ) => Promise<string[]>;
  locations: (propertyId: string) => Promise<Locations>;
  addPlace: (
    propertyId: string,
    unitId: string,
    itemId: string,
  ) => Promise<number>;
}

export class ProductsError extends Error {
  /** The HTTP status when the server answered: 403 no right, 409 refused by the stock or a name
   * already used, 412 changed meanwhile, 422 refused. */
  constructor(
    readonly status: number | null = null,
    readonly detail: string | null = null,
  ) {
    super("The products command was not completed.");
    this.name = "ProductsError";
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
  if (entry === undefined) throw new ProductsError();
  const token = decodeURIComponent(entry.slice(prefix.length));
  if (token === "") throw new ProductsError();
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
    throw new ProductsError();
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
    throw new ProductsError(response.status, detail);
  }
  if (!isObject(payload) || !("data" in payload)) throw new ProductsError();
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
  return `/api/v1/properties/${encodeURIComponent(propertyId)}`;
}

function text(value: unknown): string {
  if (typeof value !== "string") throw new ProductsError();
  return value;
}

function maybeText(value: unknown): string | null {
  return value === null || value === undefined ? null : text(value);
}

function whole(value: unknown): number {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new ProductsError();
  }
  return value;
}

function maybeWhole(value: unknown): number | null {
  return value === null || value === undefined ? null : whole(value);
}

function list(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw new ProductsError();
  return value;
}

function record(value: unknown): Record<string, unknown> {
  if (!isObject(value)) throw new ProductsError();
  return value;
}

function productOf(value: unknown): Product {
  const row = record(value);
  return {
    product_id: text(row.product_id),
    sku: text(row.sku),
    name_en: text(row.name_en),
    name_kh: maybeText(row.name_kh),
    description: maybeText(row.description),
    category_code: text(row.category_code),
    kind: row.kind === "SERVICE" ? "SERVICE" : "ITEM",
    measure_unit: text(row.measure_unit),
    cost_usd_cents: maybeWhole(row.cost_usd_cents),
    mark_up_basis_points: whole(row.mark_up_basis_points),
    min_mark_up_basis_points: whole(row.min_mark_up_basis_points),
    max_mark_up_basis_points: maybeWhole(row.max_mark_up_basis_points),
    price_usd_cents: maybeWhole(row.price_usd_cents),
    real_mark_up_basis_points: maybeWhole(row.real_mark_up_basis_points),
    reorder_level: maybeWhole(row.reorder_level),
    reorder_quantity: maybeWhole(row.reorder_quantity),
    discontinued: row.discontinued === true,
    version: whole(row.version),
    stock: text(row.stock),
    low_stock: row.low_stock === true,
  };
}

function catalogueOf(value: unknown): Catalogue {
  const data = record(value);
  const rules = record(data.rules);
  return {
    rules: {
      mark_up_basis_points: maybeWhole(rules.mark_up_basis_points),
      min_mark_up_basis_points: maybeWhole(rules.min_mark_up_basis_points),
      max_mark_up_basis_points: maybeWhole(rules.max_mark_up_basis_points),
      price_round_up_usd_cents: maybeWhole(rules.price_round_up_usd_cents),
    },
    categories: list(data.categories).map((item) => {
      const row = record(item);
      return {
        code: text(row.code),
        name_en: text(row.name_en),
        name_kh: maybeText(row.name_kh),
        kind: row.kind === "SERVICE" ? "SERVICE" : "ITEM",
      };
    }),
    products: list(data.products).map(productOf),
  };
}

function movementOf(value: unknown): Movement {
  const row = record(value);
  return {
    movement_number: text(row.movement_number),
    kind: text(row.kind) as MovementRowKind,
    product_id: text(row.product_id),
    sku: text(row.sku),
    product_name_en: text(row.product_name_en),
    measure_unit: text(row.measure_unit),
    quantity: text(row.quantity),
    unit_id: text(row.unit_id),
    unit_number: text(row.unit_number),
    place_item_id: text(row.place_item_id),
    place_name_en: text(row.place_name_en),
    place_name_kh: maybeText(row.place_name_kh),
    place_number: whole(row.place_number),
    unit_cost_usd_cents: maybeWhole(row.unit_cost_usd_cents),
    supplier: maybeText(row.supplier),
    receipt_reference: maybeText(row.receipt_reference),
    reason: maybeText(row.reason),
    business_date: text(row.business_date),
    recorded_at: text(row.recorded_at),
    recorded_by_name: maybeText(row.recorded_by_name),
  };
}

function locationsOf(value: unknown): Locations {
  const data = record(value);
  return {
    places: list(data.places).map((item) => {
      const row = record(item);
      return {
        unit_id: text(row.unit_id),
        unit_number: text(row.unit_number),
        for_rent: row.for_rent === true,
        item_id: text(row.item_id),
        name_en: text(row.name_en),
        name_kh: maybeText(row.name_kh),
        number: whole(row.number),
        stock: list(row.stock).map((line) => {
          const held = record(line);
          return {
            product_id: text(held.product_id),
            sku: text(held.sku),
            name_en: text(held.name_en),
            measure_unit: text(held.measure_unit),
            quantity: text(held.quantity),
          };
        }),
      };
    }),
    features: list(data.features).map((item) => {
      const row = record(item);
      return {
        item_id: text(row.item_id),
        name_en: text(row.name_en),
        name_kh: maybeText(row.name_kh),
      };
    }),
  };
}

function product(propertyId: string, productId: string): string {
  return `${base(propertyId)}/products/${encodeURIComponent(productId)}`;
}

export const productsApi: ProductsApi = {
  catalogue: async (propertyId) =>
    catalogueOf(await request(`${base(propertyId)}/products`)),
  addProduct: async (propertyId, change) =>
    catalogueOf(
      await request(`${base(propertyId)}/products`, send("POST", change)),
    ),
  changeProduct: async (propertyId, item, change) =>
    catalogueOf(
      await request(
        product(propertyId, item.product_id),
        send("PUT", change, item.version),
      ),
    ),
  setMarkUps: async (propertyId, item, change) =>
    catalogueOf(
      await request(
        `${product(propertyId, item.product_id)}/mark-ups`,
        send("PUT", change, item.version),
      ),
    ),
  setServiceCost: async (propertyId, item, cost) =>
    catalogueOf(
      await request(
        `${product(propertyId, item.product_id)}/service-cost`,
        send("PUT", { cost_usd_cents: cost }, item.version),
      ),
    ),
  prices: async (propertyId, productId) =>
    list(await request(`${product(propertyId, productId)}/prices`)).map(
      (item) => {
        const row = record(item);
        return {
          price_usd_cents: whole(row.price_usd_cents),
          cost_usd_cents: whole(row.cost_usd_cents),
          mark_up_basis_points: whole(row.mark_up_basis_points),
          cause: text(row.cause) as PriceChange["cause"],
          created_at: text(row.created_at),
          created_by_name: maybeText(row.created_by_name),
        };
      },
    ),
  movements: async (propertyId) =>
    list(await request(`${base(propertyId)}/stock-movements`)).map(movementOf),
  recordMovement: async (propertyId, movement) => {
    const data = record(
      await request(
        `${base(propertyId)}/stock-movements`,
        send("POST", movement),
      ),
    );
    return text(data.movement_number);
  },
  recordMovements: async (propertyId, movements) => {
    const data = record(
      await request(
        `${base(propertyId)}/stock-movements/batch`,
        send("POST", { movements }),
      ),
    );
    return list(data.movement_numbers).map(text);
  },
  locations: async (propertyId) =>
    locationsOf(await request(`${base(propertyId)}/locations`)),
  addPlace: async (propertyId, unitId, itemId) => {
    const data = record(
      await request(
        `${base(propertyId)}/units/${encodeURIComponent(unitId)}/places`,
        send("POST", { item_id: itemId }),
      ),
    );
    return whole(data.number);
  },
};

/** Cents as "$12.60". */
export function dollars(cents: number | null): string {
  if (cents === null) return "—";
  return `$${(cents / 100).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/** Basis points as "20%" or "12.5%". */
export function percent(basisPoints: number | null): string {
  return basisPoints === null ? "—" : `${String(basisPoints / 100)}%`;
}

/** What a person typed as dollars, in cents; null when it does not fit. */
export function centsFromText(typed: string): number | null {
  const value = typed.trim().replace(/[$,]/g, "");
  if (!/^\d{1,7}(\.\d{1,2})?$/.test(value)) return null;
  const [whole = "0", part = ""] = value.split(".");
  return Number(whole) * 100 + Number(part.padEnd(2, "0"));
}

/** What a person typed as a percent, in basis points; null when it does not fit. */
export function basisPointsFromText(typed: string): number | null {
  const value = typed.trim().replace(/%/g, "");
  if (!/^\d{1,4}(\.\d{1,2})?$/.test(value)) return null;
  const [whole = "0", part = ""] = value.split(".");
  const points = Number(whole) * 100 + Number(part.padEnd(2, "0"));
  return points <= 100000 ? points : null;
}

/** A typed quantity the server takes ("3", "2.5"), or null. */
export function quantityFromText(typed: string, unit: string): string | null {
  const value = typed.trim();
  const shape = WHOLE_UNITS.has(unit)
    ? /^[1-9]\d{0,8}$/
    : /^\d{1,9}(\.\d{1,3})?$/;
  if (!shape.test(value) || Number(value) <= 0) return null;
  return value;
}

/** The price the server will set: cost × (1 + mark-up), rounded up to the step. */
export function priceFor(
  cost: number,
  markUpBasisPoints: number,
  step: number,
): number {
  const raw = (cost * (10000 + markUpBasisPoints)) / 10000;
  return Math.ceil(raw / step - 1e-9) * step;
}
