import {
  exactKeys,
  financialId,
  financialInstant,
  financialObject,
  invalidFinancial,
} from "./financialContracts";
import { parseFinancialJson } from "./financialJson";

export const LEDGER_REPLY_BYTES = 5_242_880;
export const LEDGER_DEADLINE_MS = 15_000;
export const LEDGER_EVENTS = {
  INVOICE_ISSUED: [10, "Invoice charged"],
  INVOICE_ADJUSTED: [20, "Invoice adjusted"],
  INVOICE_ADJUSTMENT_REVERSED: [21, "Invoice adjustment reversed"],
  DEPOSIT_REQUIREMENT_ADJUSTED: [22, "Deposit requirement adjusted"],
  LATE_PAYMENT_WAIVED: [25, "Late-payment charge waived"],
  LATE_PAYMENT_CHARGED: [30, "Late-payment charge confirmed"],
  LATE_PAYMENT_CORRECTED: [31, "Late-payment charge corrected"],
  PAYMENT_RECEIVED: [40, "Payment received"],
  DEPOSIT_RECEIVED: [45, "Deposit received"],
  DEPOSIT_RECEIPT_REVERSED: [46, "Deposit receipt reversed"],
  PAYMENT_ALLOCATED: [50, "Payment applied"],
  PAYMENT_ALLOCATION_REVERSED: [51, "Payment application reversed"],
  CREDIT_RECOGNIZED: [60, "Customer Credit recognized"],
  CREDIT_RECOGNITION_REVERSED: [61, "Customer Credit recognition reversed"],
  CREDIT_APPLIED: [70, "Customer Credit applied"],
  CREDIT_APPLICATION_REVERSED: [71, "Customer Credit application reversed"],
  DEPOSIT_DISPOSED: [80, "Deposit disposed"],
  DEPOSIT_DISPOSITION_REVERSED: [81, "Deposit disposition reversed"],
  REFUND_PAID: [82, "Refund paid"],
  REFUND_CORRECTED: [83, "Refund corrected"],
  INVOICE_VOIDED: [90, "Invoice voided"],
  DRAFT_INVOICE_VOIDED: [90, "Draft Invoice voided"],
  PAYMENT_REVERSED: [99, "Payment reversed"],
} as const;
export type LedgerEventKind = keyof typeof LEDGER_EVENTS;
export const LEDGER_BUCKETS = {
  invoice: "Invoice outstanding",
  charge: "Late-payment Charges outstanding",
  credit: "Available Customer Credit",
  payment: "Unallocated Payment",
  security_deposit: "Security Deposit held",
  pet_deposit: "Pet Deposit held",
} as const;
export const LEDGER_BALANCES = {
  INVOICE: "Invoice outstanding",
  LATE_PAYMENT_CHARGE: "Late-payment Charge outstanding",
  CREDIT: "Available Customer Credit",
  UNALLOCATED_PAYMENT: "Unallocated Payment",
  SECURITY_DEPOSIT: "Security Deposit held",
  PET_DEPOSIT: "Pet Deposit held",
} as const;
type Bucket = keyof typeof LEDGER_BUCKETS;
export type LedgerPosition = Readonly<
  Record<`${Bucket | "total_owed"}_usd_cents`, string>
>;
export type LedgerAudit =
  | null
  | boolean
  | string
  | readonly LedgerAudit[]
  | { readonly [key: string]: LedgerAudit };
export interface LedgerCommon {
  readonly property_id: string;
  readonly customer_id: string;
  readonly event_kind: LedgerEventKind;
  readonly event_order: number;
  readonly event_id: string;
  readonly occurred_at: string;
  readonly business_date: string;
  readonly source_table: string;
  readonly source_reference: string | null;
  readonly recorded_amount_usd_cents: string | null;
  readonly source_audit: Readonly<Record<string, LedgerAudit>>;
  readonly invoice_id: string | null;
  readonly late_payment_charge_id: string | null;
  readonly payment_id: string | null;
  readonly customer_credit_id: string | null;
  readonly deposit_id: string | null;
  readonly refund_id: string | null;
}
export type LedgerHistory = LedgerCommon &
  Readonly<Record<`${Bucket}_effect_usd_cents`, string>> & {
    readonly component_count: number;
    readonly position_after_instant: LedgerPosition;
  };
export interface LedgerComponent extends LedgerCommon {
  readonly invoice_line_id: string | null;
  readonly balance_kind: keyof typeof LEDGER_BALANCES | "NONE";
  readonly balance_source_id: string | null;
  readonly effect_usd_cents: string;
  readonly category: string | null;
  readonly description: string | null;
  readonly detail_key: string;
}
export interface LedgerComposition {
  readonly property_id: string;
  readonly customer_id: string;
  readonly balance_kind: keyof typeof LEDGER_BALANCES;
  readonly balance_source_id: string;
  readonly invoice_id: string | null;
  readonly invoice_line_id: string | null;
  readonly late_payment_charge_id: string | null;
  readonly category: string | null;
  readonly description: string | null;
  readonly balance_usd_cents: string;
  readonly detail_key: string;
}
// These handles carry no wire data. Only this client's validated replies issue them.
export interface LedgerCursor {
  readonly type: "ledger-cursor";
}
export interface LedgerSnapshot {
  readonly type: "ledger-snapshot";
}
export interface LedgerScope {
  actorId: string;
  propertyId?: string;
  signal: AbortSignal;
}
export interface LedgerFilters {
  from?: string;
  through?: string;
  kind?: LedgerEventKind;
}
export type LedgerRequest =
  | { section: "customers"; limit?: number; cursor?: LedgerCursor }
  | {
      section: "history" | "composition" | "components";
      customerId: string;
      limit?: number;
      cursor?: LedgerCursor;
      snapshot?: LedgerSnapshot;
      filters?: LedgerFilters;
      eventKind?: LedgerEventKind;
      eventId?: string;
      source?: LedgerHistory;
    };
interface ReplyBase {
  readonly actorId: string;
  readonly propertyId: string;
  readonly requestId: string;
  readonly nextCursor: LedgerCursor | null;
}
export interface LedgerCustomerPage extends ReplyBase {
  readonly section: "customers";
  readonly items: readonly {
    readonly id: string;
    readonly legal_name: string;
  }[];
}
interface LedgerPageBase extends ReplyBase {
  readonly customerId: string;
  readonly customerName: string;
  readonly sourceRevision: string;
  readonly snapshot: LedgerSnapshot;
  readonly position: LedgerPosition;
  readonly eventCount: number;
}
export type LedgerPage = LedgerPageBase &
  (
    | { readonly section: "history"; readonly items: readonly LedgerHistory[] }
    | {
        readonly section: "components";
        readonly items: readonly LedgerComponent[];
      }
    | {
        readonly section: "composition";
        readonly items: readonly LedgerComposition[];
      }
  );
export type LedgerReply = LedgerCustomerPage | LedgerPage;
export interface CustomerLedgerApi {
  read(input: LedgerRequest, scope: LedgerScope): Promise<LedgerReply>;
}
export class CustomerLedgerError extends Error {
  constructor(
    readonly code:
      | "INVALID_REQUEST"
      | "INVALID_RESPONSE"
      | "UNAVAILABLE"
      | "ABORTED"
      | "HTTP_REJECTION"
      | "RESPONSE_TOO_LARGE",
    readonly status: number | null = null,
    readonly requestId: string | null = null,
  ) {
    super("The Customer ledger could not be loaded.");
    this.name = "CustomerLedgerError";
  }
}
export function ledgerMoney(value: string): string {
  const cents = BigInt(money(value, true)),
    magnitude = cents < 0n ? -cents : cents;
  return `${cents < 0n ? "−" : ""}$${(magnitude / 100n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",")}.${(magnitude % 100n).toString().padStart(2, "0")}`;
}
function id(v: unknown): string {
  const result = financialId(v);
  if (v !== result) invalidFinancial();
  return result;
}
function text(v: unknown, maximum = 4000): string {
  if (typeof v !== "string" || new TextEncoder().encode(v).length > maximum)
    return invalidFinancial();
  return v;
}
function digest(v: unknown): string {
  const s = text(v, 64);
  if (!/^[a-f0-9]{64}$/.test(s)) invalidFinancial();
  return s;
}
function count(v: unknown, min = 0): number {
  if (
    typeof v !== "number" ||
    !Number.isSafeInteger(v) ||
    Object.is(v, -0) ||
    v < min
  )
    return invalidFinancial();
  return v;
}
function money(v: unknown, signed = false): string {
  if (
    typeof v !== "string" ||
    !/^-?(?:0|[1-9][0-9]{0,63})$/.test(v) ||
    v === "-0" ||
    (!signed && v.startsWith("-"))
  )
    return invalidFinancial();
  return v;
}
function eventKind(v: unknown): LedgerEventKind {
  if (typeof v !== "string" || !Object.hasOwn(LEDGER_EVENTS, v))
    return invalidFinancial();
  return v as LedgerEventKind;
}
function position(v: unknown): LedgerPosition {
  const row = financialObject(v);
  exactKeys(
    row,
    [...Object.keys(LEDGER_BUCKETS), "total_owed"].map((k) => `${k}_usd_cents`),
  );
  for (const value of Object.values(row)) money(value);
  if (
    BigInt(money(row.invoice_usd_cents)) +
      BigInt(money(row.charge_usd_cents)) !==
    BigInt(money(row.total_owed_usd_cents))
  )
    invalidFinancial();
  return row as LedgerPosition;
}
function audit(v: unknown, depth = 0): void {
  if (depth > 12) invalidFinancial();
  if (v === null || typeof v === "boolean") return;
  if (typeof v === "string") {
    text(v, 1_048_576);
    return;
  }
  if (Array.isArray(v)) {
    if (v.length > 1000) invalidFinancial();
    v.forEach((x) => {
      audit(x, depth + 1);
    });
    return;
  }
  const row = financialObject(v);
  if (Object.keys(row).length > 1000) invalidFinancial();
  for (const [k, x] of Object.entries(row)) {
    text(k, 200);
    if (
      k.endsWith("_usd_cents") ||
      k === "usd_accounting_value_cents" ||
      k === "channel_actual_usd_value_cents"
    ) {
      if (x !== null) money(x);
    } else audit(x, depth + 1);
  }
}
function freeze<T>(value: T): T {
  if (value && typeof value === "object") {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}
const links = [
  "invoice_id",
  "late_payment_charge_id",
  "payment_id",
  "customer_credit_id",
  "deposit_id",
  "refund_id",
];
const common = [
  "property_id",
  "customer_id",
  "event_kind",
  "event_order",
  "event_id",
  "occurred_at",
  "business_date",
  "source_table",
  "source_reference",
  "recorded_amount_usd_cents",
  "source_audit",
  ...links,
];
type Order = readonly [bigint, number, string, string] | string;
function compare(a: Order, b: Order): number {
  if (typeof a === "string" || typeof b === "string") {
    if (typeof a !== "string" || typeof b !== "string")
      return invalidFinancial();
    return a === b ? 0 : a < b ? -1 : 1;
  }
  for (let i = 0; i < 4; i++) {
    const x = a[i],
      y = b[i];
    if (x === undefined || y === undefined) return invalidFinancial();
    if (x !== y) return x < y ? -1 : 1;
  }
  return 0;
}
interface SnapshotReceipt {
  actorId: string;
  propertyId: string;
  customerId: string;
  revision: string;
  position: string;
  name: string;
  count: number;
}
interface CursorReceipt {
  consumed: number;
  selection: string;
  token: string;
  after: Order;
  snapshot?: LedgerSnapshot;
  propertyId: string;
}
interface Captured {
  section: LedgerRequest["section"];
  actorId: string;
  propertyId?: string;
  customerId?: string;
  limit: number;
  from?: string;
  through?: string;
  kind?: LedgerEventKind;
  eventKind?: LedgerEventKind;
  eventId?: string;
  source?: LedgerHistory;
  snapshot?: LedgerSnapshot;
  expected?: SnapshotReceipt;
  cursor?: CursorReceipt;
  selection: string;
}
function rows(
  value: unknown,
  request: Captured,
  prop: string,
): {
  items: (LedgerHistory | LedgerComponent | LedgerComposition)[];
  last?: Order;
} {
  if (!Array.isArray(value) || value.length > request.limit)
    return invalidFinancial();
  let previous = request.cursor?.after;
  for (const raw of value) {
    const row = financialObject(raw),
      composition = request.section === "composition",
      history = request.section === "history";
    const keys = composition
      ? [
          "property_id",
          "customer_id",
          "balance_kind",
          "balance_source_id",
          "invoice_id",
          "invoice_line_id",
          "late_payment_charge_id",
          "category",
          "description",
          "balance_usd_cents",
          "detail_key",
        ]
      : [
          ...common,
          ...(history
            ? [
                "component_count",
                "position_after_instant",
                ...Object.keys(LEDGER_BUCKETS).map(
                  (k) => `${k}_effect_usd_cents`,
                ),
              ]
            : [
                "invoice_line_id",
                "balance_kind",
                "balance_source_id",
                "effect_usd_cents",
                "category",
                "description",
                "detail_key",
              ]),
        ];
    exactKeys(row, keys);
    if (
      id(row.property_id) !== prop ||
      id(row.customer_id) !== request.customerId
    )
      invalidFinancial();
    for (const k of [...links, "invoice_line_id", "balance_source_id"])
      if (Object.hasOwn(row, k) && row[k] !== null) id(row[k]);
    for (const k of ["source_reference", "category", "description"])
      if (Object.hasOwn(row, k) && row[k] !== null) text(row[k]);
    let order: Order;
    if (composition) {
      if (
        typeof row.balance_kind !== "string" ||
        !Object.hasOwn(LEDGER_BALANCES, row.balance_kind)
      )
        invalidFinancial();
      id(row.balance_source_id);
      order = text(row.detail_key, 80);
      if (
        order !== `${row.balance_kind}:${id(row.balance_source_id)}` ||
        BigInt(money(row.balance_usd_cents)) <= 0n
      )
        invalidFinancial();
    } else {
      const kind = eventKind(row.event_kind),
        key = id(row.event_id),
        instant = financialInstant(row.occurred_at);
      if (row.event_order !== LEDGER_EVENTS[kind][0]) invalidFinancial();
      const day = text(row.business_date, 10);
      if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) invalidFinancial();
      financialInstant(day + "T00:00:00Z");
      if (!/^[a-z_]{1,80}$/.test(text(row.source_table, 80)))
        invalidFinancial();
      if (row.recorded_amount_usd_cents !== null)
        money(row.recorded_amount_usd_cents);
      financialObject(row.source_audit);
      audit(row.source_audit);
      if (
        new TextEncoder().encode(JSON.stringify(row.source_audit)).length >
        1_048_576
      )
        invalidFinancial();
      if (history) {
        if (
          (request.kind && kind !== request.kind) ||
          (request.from && instant < financialInstant(request.from)) ||
          (request.through && instant > financialInstant(request.through))
        )
          invalidFinancial();
        count(row.component_count, 1);
        position(row.position_after_instant);
        for (const k of Object.keys(LEDGER_BUCKETS))
          money(row[`${k}_effect_usd_cents`], true);
        order = [instant, LEDGER_EVENTS[kind][0], kind, key];
      } else {
        if (kind !== request.eventKind || key !== request.eventId)
          invalidFinancial();
        if (
          typeof row.balance_kind !== "string" ||
          !(
            row.balance_kind === "NONE" ||
            Object.hasOwn(LEDGER_BALANCES, row.balance_kind)
          )
        )
          invalidFinancial();
        const effect = money(row.effect_usd_cents, true);
        if (row.balance_kind === "NONE" && effect !== "0") invalidFinancial();
        order = digest(row.detail_key);
      }
    }
    if (previous !== undefined && compare(previous, order) >= 0)
      invalidFinancial();
    previous = order;
  }
  return {
    items: value as (LedgerHistory | LedgerComponent | LedgerComposition)[],
    last: previous,
  };
}

export function createCustomerLedgerClient(
  fetcher: typeof fetch = (...args) => fetch(...args),
): CustomerLedgerApi {
  const sources = new WeakMap<LedgerHistory, LedgerSnapshot>();
  const snapshots = new WeakMap<LedgerSnapshot, SnapshotReceipt>(),
    cursors = new WeakMap<LedgerCursor, CursorReceipt>();
  function capture(input: LedgerRequest, scope: LedgerScope): Captured {
    const section = input.section;
    if (
      !["customers", "history", "components", "composition"].includes(section)
    )
      invalidFinancial();
    const allowed =
      section === "customers"
        ? ["section", "limit", "cursor"]
        : [
            "section",
            "customerId",
            "limit",
            "cursor",
            "snapshot",
            "filters",
            "eventKind",
            "eventId",
            "source",
          ];
    if (Object.keys(input).some((k) => !allowed.includes(k)))
      invalidFinancial();
    const r: Captured = {
      section,
      actorId: id(scope.actorId),
      ...(scope.propertyId === undefined
        ? {}
        : { propertyId: id(scope.propertyId) }),
      limit: count(input.limit ?? 50, 1),
      selection: "",
    };
    if (r.limit > 100) invalidFinancial();
    if (input.section !== "customers") {
      r.customerId = id(input.customerId);
      if (input.filters !== undefined) {
        if (
          Object.keys(input.filters).some(
            (k) => !["from", "through", "kind"].includes(k),
          )
        )
          invalidFinancial();
        if (section !== "history" && Object.keys(input.filters).length)
          invalidFinancial();
        if (input.filters.from !== undefined) {
          financialInstant(input.filters.from);
          r.from = input.filters.from;
        }
        if (input.filters.through !== undefined) {
          financialInstant(input.filters.through);
          r.through = input.filters.through;
        }
        if (
          r.from &&
          r.through &&
          financialInstant(r.from) > financialInstant(r.through)
        )
          invalidFinancial();
        if (input.filters.kind !== undefined)
          r.kind = eventKind(input.filters.kind);
      }
      if (section === "components") {
        r.eventKind = eventKind(input.eventKind);
        r.eventId = id(input.eventId);
      } else if (input.eventKind !== undefined || input.eventId !== undefined)
        invalidFinancial();
      if (input.snapshot !== undefined) {
        r.snapshot = input.snapshot;
        r.expected = snapshots.get(input.snapshot);
        if (
          !r.expected ||
          r.expected.actorId !== r.actorId ||
          r.expected.customerId !== r.customerId ||
          (r.propertyId !== undefined && r.expected.propertyId !== r.propertyId)
        )
          invalidFinancial();
        r.propertyId = r.expected.propertyId;
      } else if (section !== "history") invalidFinancial();
      if (section === "components") {
        if (
          !input.source ||
          sources.get(input.source) !== r.snapshot ||
          input.source.event_kind !== r.eventKind ||
          input.source.event_id !== r.eventId
        )
          invalidFinancial();
        r.source = input.source;
      } else if (input.source !== undefined) invalidFinancial();
    }
    r.selection = JSON.stringify([
      r.actorId,
      r.propertyId,
      r.customerId,
      section,
      r.limit,
      r.from,
      r.through,
      r.kind,
      r.eventKind,
      r.eventId,
      r.expected?.revision,
    ]);
    if (input.cursor !== undefined) {
      r.cursor = cursors.get(input.cursor);
      if (
        !r.cursor ||
        r.cursor.selection !== r.selection ||
        r.cursor.snapshot !== r.snapshot
      )
        invalidFinancial();
    }
    return r;
  }
  function validate(
    value: unknown,
    r: Captured,
    requestId: string,
  ): LedgerReply {
    const envelope = financialObject(value);
    exactKeys(envelope, ["data", "page", "meta"]);
    const meta = financialObject(envelope.meta);
    exactKeys(meta, ["actor_id", "property_id", "request_id"]);
    const prop = id(meta.property_id);
    if (
      id(meta.actor_id) !== r.actorId ||
      meta.request_id !== requestId ||
      (r.propertyId !== undefined && r.propertyId !== prop)
    )
      invalidFinancial();
    const page = financialObject(envelope.page);
    exactKeys(page, ["limit", "next_cursor"]);
    if (page.limit !== r.limit) invalidFinancial();
    const base = {
      actorId: r.actorId,
      propertyId: prop,
      requestId,
      nextCursor: null as LedgerCursor | null,
    };
    let result: LedgerReply,
      last: Order | undefined,
      snapshot: LedgerSnapshot | undefined;
    if (r.section === "customers") {
      const list = envelope.data;
      if (!Array.isArray(list) || list.length > r.limit)
        return invalidFinancial();
      last = r.cursor?.after;
      for (const raw of list) {
        const row = financialObject(raw);
        exactKeys(row, ["id", "legal_name"]);
        const key = id(row.id);
        text(row.legal_name);
        if (last !== undefined && compare(last, key) >= 0) invalidFinancial();
        last = key;
      }
      result = {
        ...base,
        section: "customers",
        items: list as { id: string; legal_name: string }[],
      };
    } else {
      const data = financialObject(envelope.data);
      exactKeys(data, [
        "property_id",
        "customer_id",
        "customer_name",
        "source_revision",
        "position",
        "event_count",
        "section",
        "items",
      ]);
      if (
        id(data.property_id) !== prop ||
        id(data.customer_id) !== r.customerId ||
        data.section !== r.section
      )
        invalidFinancial();
      const revision = digest(data.source_revision),
        pos = position(data.position),
        name = text(data.customer_name),
        total = count(data.event_count);
      const serialized = JSON.stringify(
        Object.keys(pos)
          .sort()
          .map((k) => [k, pos[k as keyof LedgerPosition]]),
      );
      if (
        r.expected &&
        (revision !== r.expected.revision ||
          serialized !== r.expected.position ||
          name !== r.expected.name ||
          total !== r.expected.count)
      )
        invalidFinancial();
      const checked = rows(data.items, r, prop);
      last = checked.last;
      const consumed = (r.cursor?.consumed ?? 0) + checked.items.length;
      const expectedCount =
        r.section === "components"
          ? r.source?.component_count
          : r.section === "history"
            ? total
            : undefined;
      const completeCount =
        r.section === "components" ||
        (r.section === "history" && !r.from && !r.through && !r.kind);
      if (
        expectedCount !== undefined &&
        (consumed > expectedCount ||
          (page.next_cursor !== null && consumed >= expectedCount) ||
          (completeCount &&
            page.next_cursor === null &&
            consumed !== expectedCount))
      )
        invalidFinancial();
      if (
        r.section === "history" &&
        total === 0 &&
        Object.values(pos).some((x) => x !== "0")
      )
        invalidFinancial();
      snapshot =
        r.snapshot ?? Object.freeze({ type: "ledger-snapshot" as const });
      if (!r.snapshot)
        snapshots.set(snapshot, {
          actorId: r.actorId,
          propertyId: prop,
          customerId: id(data.customer_id),
          revision,
          position: serialized,
          name,
          count: total,
        });
      if (r.source) {
        const expectedFacts = JSON.stringify(
          common.map((k) => [k, r.source?.[k as keyof LedgerCommon]]),
        );
        for (const item of checked.items as LedgerComponent[])
          if (
            JSON.stringify(
              common.map((k) => [k, item[k as keyof LedgerCommon]]),
            ) !== expectedFacts
          )
            invalidFinancial();
      }
      result = {
        ...base,
        customerId: id(data.customer_id),
        customerName: name,
        sourceRevision: revision,
        snapshot,
        position: pos,
        eventCount: total,
        section: r.section,
        items: checked.items,
      } as LedgerPage;
    }
    if (page.next_cursor !== null) {
      if (result.items.length !== r.limit || last === undefined)
        invalidFinancial();
      const token = text(page.next_cursor, 1024);
      if (r.section === "customers") {
        if (id(token) !== last) invalidFinancial();
      } else {
        if (!/^[A-Za-z0-9_-]+={0,2}$/.test(token)) invalidFinancial();
        const decoded = atob(token.replace(/-/g, "+").replace(/_/g, "/"));
        const data: unknown = JSON.parse(decoded);
        if (
          !Array.isArray(data) ||
          data.length !== (r.section === "history" ? 6 : 4) ||
          data[0] !== 1
        )
          invalidFinancial();
        digest(data[1]);
        if (result.section === "customers" || data[2] !== result.sourceRevision)
          invalidFinancial();
        if (
          btoa(JSON.stringify(data)).replace(/\+/g, "-").replace(/\//g, "_") !==
          token
        )
          invalidFinancial();
        const after: Order =
          r.section === "history"
            ? [
                financialInstant(data[3]),
                LEDGER_EVENTS[eventKind(data[4])][0],
                eventKind(data[4]),
                id(data[5]),
              ]
            : text(data[3], 80);
        if (compare(after, last) !== 0) invalidFinancial();
      }
      const handle: LedgerCursor = Object.freeze({ type: "ledger-cursor" });
      // A first read discovers its Property and snapshot; all continuation requests bind both.
      const selection = JSON.stringify([
        r.actorId,
        prop,
        r.customerId,
        r.section,
        r.limit,
        r.from,
        r.through,
        r.kind,
        r.eventKind,
        r.eventId,
        result.section === "customers" ? undefined : result.sourceRevision,
      ]);
      cursors.set(handle, {
        consumed: (r.cursor?.consumed ?? 0) + result.items.length,
        token,
        selection,
        after: last,
        snapshot,
        propertyId: prop,
      });
      result = { ...result, nextCursor: handle };
    }
    if (result.section === "history")
      for (const item of result.items) sources.set(item, result.snapshot);
    return freeze(result);
  }
  return {
    async read(input, scope) {
      let sent = false,
        status: number | null = null,
        requestId: string | null = null;
      const controller = new AbortController();
      let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
      const body: { current: ReadableStream<Uint8Array> | null } = {
        current: null,
      };
      let timer: ReturnType<typeof setTimeout> | undefined,
        release = () => {
          /* Best-effort cleanup must not delay settlement. */
        };
      try {
        const r = capture(input, scope);
        requestId = crypto.randomUUID();
        id(requestId);
        if (scope.signal.aborted) throw new CustomerLedgerError("ABORTED");
        const params = new URLSearchParams({ limit: String(r.limit) });
        if (r.section !== "customers") params.set("section", r.section);
        for (const [key, v] of [
          ["from", r.from],
          ["through", r.through],
          ["kind", r.kind],
          ["event_kind", r.eventKind],
          ["event_id", r.eventId],
          ["revision", r.expected?.revision],
          ["cursor", r.cursor?.token],
        ])
          if (key && v !== undefined) params.set(key, v);
        const headers = new Headers({
          Accept: "application/json",
          "X-Request-ID": requestId,
          "X-Billing-Actor-ID": r.actorId,
        });
        if (r.propertyId) headers.set("X-Financial-Property-ID", r.propertyId);
        const interrupted = new Promise<never>((_resolve, reject) => {
          const stop = () => {
            controller.abort();
            reject(
              new CustomerLedgerError(
                scope.signal.aborted ? "ABORTED" : "UNAVAILABLE",
                status,
                requestId,
              ),
            );
          };
          scope.signal.addEventListener("abort", stop, { once: true });
          release = () => {
            scope.signal.removeEventListener("abort", stop);
          };
          timer = setTimeout(stop, LEDGER_DEADLINE_MS);
        });
        const guard = <T>(promise: Promise<T>) =>
          Promise.race([promise, interrupted]);
        const path =
          r.section === "customers"
            ? "/api/v1/customer-ledger/customers"
            : `/api/v1/customers/${r.customerId ?? ""}/account-ledger`;
        sent = true;
        const response = await guard(
          fetcher(`${path}?${params}`, {
            method: "GET",
            headers,
            credentials: "include",
            cache: "no-store",
            redirect: "error",
            signal: controller.signal,
          }).then((received) => {
            body.current = received.body;
            if (controller.signal.aborted)
              void body.current?.cancel().catch(() => {
                /* Best-effort cleanup must not delay settlement. */
              });
            return received;
          }),
        );
        status = response.status;
        if (
          response.redirected ||
          response.headers.get("X-Request-ID") !== requestId ||
          !/^application\/json(?:\s*;\s*charset=utf-8)?$/i.test(
            response.headers.get("Content-Type") ?? "",
          ) ||
          response.headers.get("Cache-Control") !== "private, no-store" ||
          !(response.headers.get("Vary") ?? "")
            .split(",")
            .some((v) => v.trim().toLowerCase() === "cookie") ||
          !response.body
        )
          invalidFinancial();
        const length = response.headers.get("Content-Length");
        if (
          length !== null &&
          (!/^(?:0|[1-9][0-9]*)$/.test(length) ||
            BigInt(length) > BigInt(LEDGER_REPLY_BYTES))
        )
          throw new CustomerLedgerError(
            "RESPONSE_TOO_LARGE",
            status,
            requestId,
          );
        reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8", { fatal: true });
        let raw = "",
          bytes = 0;
        for (;;) {
          const chunk = await guard(reader.read());
          if (chunk.done) break;
          bytes += chunk.value.byteLength;
          if (bytes > LEDGER_REPLY_BYTES)
            throw new CustomerLedgerError(
              "RESPONSE_TOO_LARGE",
              status,
              requestId,
            );
          raw += decoder.decode(chunk.value, { stream: true });
        }
        raw += decoder.decode();
        if (controller.signal.aborted || isAborted(scope.signal))
          throw new CustomerLedgerError("ABORTED", status, requestId);
        const envelope = parseFinancialJson(raw, LEDGER_REPLY_BYTES);
        if (status !== 200) {
          const e = financialObject(envelope);
          exactKeys(e, ["error", "meta"]);
          const meta = financialObject(e.meta);
          exactKeys(meta, ["request_id"]);
          if (meta.request_id !== requestId) invalidFinancial();
          const err = financialObject(e.error);
          exactKeys(err, [
            "code",
            "message",
            "fields",
            "rule_ids",
            "current_version",
          ]);
          const codes: Record<number, string> = {
            400: "BAD_REQUEST",
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            409: "CONFLICT",
            412: "PRECONDITION_FAILED",
            422: "VALIDATION_ERROR",
            429: "RATE_LIMITED",
            500: "INTERNAL_ERROR",
            503: "SERVICE_UNAVAILABLE",
          };
          if (!Object.hasOwn(codes, status) || err.code !== codes[status])
            invalidFinancial();
          text(err.message);
          for (const k of ["fields", "rule_ids"]) {
            const list = err[k];
            if (!Array.isArray(list) || list.length > 50) invalidFinancial();
            list.forEach((x) => text(x, 200));
          }
          if (err.current_version !== null) count(err.current_version);
          throw new CustomerLedgerError("HTTP_REJECTION", status, requestId);
        }
        return validate(envelope, r, requestId);
      } catch (error) {
        if (error instanceof CustomerLedgerError) throw error;
        throw new CustomerLedgerError(
          sent ? "INVALID_RESPONSE" : "INVALID_REQUEST",
          status,
          requestId,
        );
      } finally {
        if (timer !== undefined) clearTimeout(timer);
        release();
        controller.abort();
        if (reader)
          void reader.cancel().catch(() => {
            /* Best-effort cleanup must not delay settlement. */
          });
        else
          void body.current?.cancel().catch(() => {
            /* Best-effort cleanup must not delay settlement. */
          });
      }
    },
  };
}
function isAborted(signal: AbortSignal): boolean {
  return signal.aborted;
}
export const customerLedgerClient = createCustomerLedgerClient();
