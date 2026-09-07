import {
  captureFinancialRequest,
  exactKeys,
  financialId,
  financialInstant,
  financialInteger,
  financialObject,
  invalidFinancial,
  type FinancialObject,
} from "./financialContracts";
import { parseFinancialJson, stringifyFinancialJson } from "./financialJson";
import { validateFinancialReply } from "./financialResponse";

export type ReversalContextView = "impact" | "result";
const impactKinds = [
  "ALLOCATION",
  "ALLOCATION_LINE",
  "CREDIT",
  "CREDIT_APPLICATION",
  "CREDIT_APPLICATION_LINE",
  "DEPOSIT_RECEIPT",
  "DEPOSIT_DISPOSITION",
  "REFUND",
] as const;
const resultKinds = [
  "INVOICE",
  "LATE_PAYMENT_CHARGE",
  "CREDIT",
  "DEPOSIT",
] as const;
const revisionPattern = /^[0-9a-f]{64}$/;
function text(value: unknown): string {
  if (typeof value !== "string") return invalidFinancial();
  return value;
}
function id(value: unknown): string {
  const result = financialId(value);
  if (value !== result) invalidFinancial();
  return result;
}
function choice(value: unknown, values: readonly string[]): string {
  if (typeof value !== "string" || !values.includes(value))
    return invalidFinancial();
  return value;
}
function label(value: unknown): void {
  if (typeof value !== "string" || !/[^ ]/.test(value) || value.includes("\0"))
    invalidFinancial();
}
export function reversalContextCursor(
  value: unknown,
  view: ReversalContextView,
): { revision: string; ordinal: number; id: string } {
  if (typeof value !== "string") return invalidFinancial();
  const match =
    /^([0-9a-f]{64}):([1-8]):([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$/.exec(
      value,
    );
  if (!match || (view === "result" && Number(match[2]) > 4))
    return invalidFinancial();
  return {
    revision: match[1] ?? invalidFinancial(),
    ordinal: Number(match[2]),
    id: id(match[3]),
  };
}
export function captureReversalContext(input: FinancialObject): void {
  exactKeys(input, ["operation", "payment_id"], ["view", "limit", "cursor"]);
  input.payment_id = financialId(input.payment_id);
  if (input.view !== undefined) choice(input.view, ["impact", "result"]);
  if (input.limit !== undefined) financialInteger(input.limit, 1n, 100n);
  if (input.cursor !== undefined)
    reversalContextCursor(
      input.cursor,
      (input.view ?? "impact") as ReversalContextView,
    );
}

function event(
  kind: string,
  identity: string,
  value: FinancialObject,
  payment: string,
): void {
  const refund = kind === "REFUND";
  exactKeys(value, [
    "source_kind",
    "source_id",
    "amount_usd_cents",
    "occurred_at",
    ...(refund
      ? ["refund_number", "unreturned_usd_cents"]
      : ["target_kind", "target_id"]),
  ]);
  id(value.source_id);
  financialInstant(value.occurred_at);
  const amount = BigInt(financialInteger(value.amount_usd_cents, 1n));
  const source =
    kind === "ALLOCATION_LINE"
      ? "ALLOCATION"
      : kind === "CREDIT_APPLICATION_LINE"
        ? "CREDIT_APPLICATION"
        : kind === "CREDIT_APPLICATION"
          ? "CREDIT"
          : kind === "DEPOSIT_DISPOSITION"
            ? "DEPOSIT"
            : "PAYMENT";
  choice(
    value.source_kind,
    refund ? ["PAYMENT", "CREDIT", "DEPOSIT"] : [source],
  );
  if (value.source_kind === "PAYMENT" && value.source_id !== payment)
    invalidFinancial();
  if (refund) {
    label(value.refund_number);
    financialInteger(value.unreturned_usd_cents, 1n, amount);
    return;
  }
  id(value.target_id);
  const targets =
    kind === "CREDIT"
      ? ["CREDIT"]
      : kind.startsWith("DEPOSIT_")
        ? ["DEPOSIT"]
        : kind.endsWith("_LINE")
          ? ["INVOICE_LINE", "LATE_PAYMENT_CHARGE"]
          : ["INVOICE", "LATE_PAYMENT_CHARGE"];
  choice(value.target_kind, targets);
  if (
    (kind === "CREDIT" && value.target_id !== identity) ||
    (kind === "DEPOSIT_DISPOSITION" && value.target_id !== value.source_id)
  )
    invalidFinancial();
}
function result(kind: string, value: FinancialObject): void {
  if (kind === "INVOICE") {
    exactKeys(value, ["invoice_number", "status", "outstanding_usd_cents"]);
    label(value.invoice_number);
    choice(value.status, ["DRAFT", "UNPAID", "PARTIALLY_PAID", "PAID", "VOID"]);
    const outstanding = BigInt(financialInteger(value.outstanding_usd_cents));
    if (
      (value.status === "DRAFT" ||
        value.status === "VOID" ||
        value.status === "PAID") &&
      outstanding !== 0n
    )
      invalidFinancial();
  } else if (kind === "LATE_PAYMENT_CHARGE") {
    exactKeys(value, [
      "source_invoice_id",
      "original_usd_cents",
      "reversed",
      "adjusted_obligation_usd_cents",
      "remaining_balance_usd_cents",
    ]);
    id(value.source_invoice_id);
    const original = BigInt(financialInteger(value.original_usd_cents, 1n));
    const adjusted = BigInt(
      financialInteger(value.adjusted_obligation_usd_cents, 0n, original),
    );
    financialInteger(value.remaining_balance_usd_cents, 0n, adjusted);
    if (
      typeof value.reversed !== "boolean" ||
      (value.reversed && adjusted !== 0n)
    )
      invalidFinancial();
  } else if (kind === "CREDIT") {
    exactKeys(value, [
      "recognized_usd_cents",
      "applied_usd_cents",
      "refunded_usd_cents",
      "reversed_usd_cents",
      "available_usd_cents",
    ]);
    const recognized = BigInt(financialInteger(value.recognized_usd_cents, 1n));
    const amounts = [
      "applied_usd_cents",
      "refunded_usd_cents",
      "reversed_usd_cents",
      "available_usd_cents",
    ].map((key) => BigInt(financialInteger(value[key], 0n, recognized)));
    if (amounts.reduce((a, b) => a + b, 0n) !== recognized) invalidFinancial();
  } else {
    exactKeys(value, [
      "deposit_type",
      "held_usd_cents",
      "received_usd_cents",
      "disposed_usd_cents",
      "refunded_usd_cents",
    ]);
    choice(value.deposit_type, ["SECURITY", "PET"]);
    const held = BigInt(financialInteger(value.held_usd_cents));
    const received = BigInt(financialInteger(value.received_usd_cents));
    const disposed = BigInt(financialInteger(value.disposed_usd_cents));
    const refunded = BigInt(financialInteger(value.refunded_usd_cents));
    if (held + disposed + refunded !== received) invalidFinancial();
  }
}

export function validateReversalContext(
  envelope: FinancialObject,
  input: FinancialObject,
  property: string,
  requestId: string,
): { limit: number; nextCursor: string | null } {
  const row = financialObject(envelope.data);
  exactKeys(row, ["payment_resource", "view", "revision", "items"]);
  const view = (input.view ?? "impact") as ReversalContextView;
  if (
    row.view !== view ||
    typeof row.revision !== "string" ||
    !revisionPattern.test(row.revision)
  )
    invalidFinancial();
  const payment = financialId(input.payment_id);
  validateFinancialReply(
    {
      data: row.payment_resource ?? invalidFinancial(),
      meta: { property_id: property, request_id: requestId },
    },
    captureFinancialRequest({
      operation: "paymentGet",
      target: { id: payment },
    }),
    property,
    requestId,
  );
  const page = financialObject(envelope.page);
  exactKeys(page, ["limit", "next_cursor"]);
  const limit = Number(financialInteger(input.limit ?? 50, 1n, 100n));
  if (
    page.limit !== limit ||
    !Array.isArray(row.items) ||
    row.items.length > limit
  )
    invalidFinancial();
  let previous =
    input.cursor === undefined
      ? null
      : reversalContextCursor(input.cursor, view);
  if (previous && previous.revision !== row.revision) invalidFinancial();
  const kinds = view === "impact" ? impactKinds : resultKinds;
  for (const raw of row.items) {
    const item = financialObject(raw);
    exactKeys(item, ["ordinal", "kind", "id", "data"]);
    const ordinal = Number(
      financialInteger(item.ordinal, 1n, BigInt(kinds.length)),
    );
    const identity = id(item.id);
    if (
      item.kind !== kinds[ordinal - 1] ||
      (previous &&
        (ordinal < previous.ordinal ||
          (ordinal === previous.ordinal && identity <= previous.id)))
    )
      invalidFinancial();
    if (view === "impact")
      event(text(item.kind), identity, financialObject(item.data), payment);
    else result(text(item.kind), financialObject(item.data));
    previous = { ordinal, id: identity, revision: text(row.revision) };
  }
  const nextCursor = page.next_cursor === null ? null : text(page.next_cursor);
  if (nextCursor !== null) {
    reversalContextCursor(page.next_cursor, view);
    if (
      row.items.length !== limit ||
      !previous ||
      nextCursor !==
        `${row.revision}:${previous.ordinal.toString()}:${previous.id}`
    )
      invalidFinancial();
  }
  return { limit, nextCursor };
}

/** Own a complete, sequential context in memory; never persist or authorize a write. */
export class PaymentReversalContextSequence {
  #revision: string | null = null;
  #next: string | null = null;
  #started = false;
  #complete = false;
  #failed = false;
  #items: FinancialObject[] = [];
  constructor(
    readonly actorId: string,
    readonly propertyId: string,
    readonly paymentId: string,
    readonly view: ReversalContextView,
  ) {
    id(actorId);
    id(propertyId);
    id(paymentId);
    choice(view, ["impact", "result"]);
  }
  get complete(): boolean {
    return this.#complete && !this.#failed;
  }
  get nextCursor(): string | null {
    return this.#next;
  }
  append(
    reply: {
      operation: string;
      actorId: string;
      propertyId: string | null;
      requestId: string;
      data: unknown;
      page: { limit: number; nextCursor: string | null } | null;
    },
    cursor: string | null = null,
  ): void {
    try {
      if (
        this.#failed ||
        this.#complete ||
        reply.operation !== "paymentReversalContext" ||
        reply.actorId !== this.actorId ||
        reply.propertyId !== this.propertyId ||
        cursor !== this.#next ||
        (!this.#started && cursor !== null) ||
        !reply.page
      )
        invalidFinancial();
      const row = financialObject(
        parseFinancialJson(
          stringifyFinancialJson(reply.data, 1_048_576),
          1_048_576,
        ),
      );
      const input: FinancialObject = {
        operation: "paymentReversalContext",
        payment_id: this.paymentId,
        view: this.view,
        limit: reply.page.limit,
        ...(cursor === null ? {} : { cursor }),
      };
      const page = validateReversalContext(
        {
          data: row,
          page: { limit: reply.page.limit, next_cursor: reply.page.nextCursor },
        },
        input,
        this.propertyId,
        reply.requestId,
      );
      if (this.#revision !== null && row.revision !== this.#revision)
        invalidFinancial();
      this.#items.push(...(row.items as FinancialObject[]));
      this.#revision = text(row.revision);
      this.#started = true;
      this.#next = page.nextCursor;
      if (this.#next === null) {
        if (this.view === "impact") this.#validateGraph();
        this.#complete = true;
      }
    } catch (error) {
      this.#failed = true;
      this.#complete = false;
      throw error;
    }
  }
  #validateGraph(): void {
    const byKind = new Map<string, Map<string, FinancialObject>>();
    const deposits = new Set<string>();
    for (const item of this.#items) {
      const kind = text(item.kind),
        value = financialObject(item.data);
      const group = byKind.get(kind) ?? new Map<string, FinancialObject>();
      if (group.has(id(item.id))) invalidFinancial();
      group.set(id(item.id), value);
      byKind.set(kind, group);
      if (kind === "DEPOSIT_RECEIPT") deposits.add(id(value.target_id));
    }
    const detailTotals = new Map<string, bigint>();
    for (const item of this.#items) {
      const value = financialObject(item.data),
        sourceKind = text(value.source_kind),
        sourceId = id(value.source_id);
      if (sourceKind === "PAYMENT") continue;
      if (sourceKind === "DEPOSIT") {
        if (!deposits.has(sourceId)) invalidFinancial();
        continue;
      }
      const parent = byKind.get(sourceKind)?.get(sourceId);
      if (!parent) invalidFinancial();
      if (
        item.kind === "ALLOCATION_LINE" ||
        item.kind === "CREDIT_APPLICATION_LINE"
      ) {
        if (
          parent.target_kind === "LATE_PAYMENT_CHARGE" &&
          (value.target_kind !== "LATE_PAYMENT_CHARGE" ||
            value.target_id !== parent.target_id)
        )
          invalidFinancial();
        if (
          parent.target_kind === "INVOICE" &&
          value.target_kind !== "INVOICE_LINE"
        )
          invalidFinancial();
        const key = `${sourceKind}:${sourceId}`;
        detailTotals.set(
          key,
          (detailTotals.get(key) ?? 0n) +
            BigInt(financialInteger(value.amount_usd_cents)),
        );
      }
    }
    for (const kind of ["ALLOCATION", "CREDIT_APPLICATION"])
      for (const [identity, value] of byKind.get(kind) ?? []) {
        if (
          detailTotals.get(`${kind}:${identity}`) !==
          BigInt(financialInteger(value.amount_usd_cents))
        )
          invalidFinancial();
      }
  }
}
