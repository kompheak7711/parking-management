import {
  financialId,
  financialInteger,
  financialObject,
  invalidFinancial,
  type FinancialObject,
} from "./financialContracts";
import { parseFinancialJson, stringifyFinancialJson } from "./financialJson";
import {
  reversalContextReplyProvenance,
  type FinancialReferenceReply,
} from "./financialReferenceClient";
import {
  validateReversalContext,
  type ReversalContextView,
} from "./paymentReversalContext";
function text(value: unknown): string {
  if (typeof value !== "string") return invalidFinancial();
  return value;
}
function id(value: unknown): string {
  const identity = financialId(value);
  if (identity !== value) invalidFinancial();
  return identity;
}

/** Own a complete, sequential context in memory; never persist or authorize a write. */
export class PaymentReversalContextSequence {
  #revision: string | null = null;
  #next: string | null = null;
  #started = false;
  #complete = false;
  #failed = false;
  #items: FinancialObject[] = [];
  #scope: Readonly<{
    actorId: string;
    propertyId: string;
    paymentId: string;
    view: ReversalContextView;
  }>;
  constructor(
    actorId: string,
    propertyId: string,
    paymentId: string,
    view: ReversalContextView,
  ) {
    id(actorId);
    id(propertyId);
    id(paymentId);
    if (!["impact", "result"].includes(view)) invalidFinancial();
    this.#scope = Object.freeze({ actorId, propertyId, paymentId, view });
    // Public properties cannot be reassigned, shadowed or rebound through a new prototype.
    // JavaScript private state can still advance as real continuation pages arrive.
    Object.freeze(this);
  }
  get actorId(): string {
    return this.#scope.actorId;
  }
  get propertyId(): string {
    return this.#scope.propertyId;
  }
  get paymentId(): string {
    return this.#scope.paymentId;
  }
  get view(): ReversalContextView {
    return this.#scope.view;
  }
  get complete(): boolean {
    return this.#complete && !this.#failed;
  }
  get nextCursor(): string | null {
    return this.#next;
  }
  append(reply: FinancialReferenceReply, suppliedCursor?: string | null): void {
    try {
      const receipt = reversalContextReplyProvenance(reply);
      if (!receipt) invalidFinancial();
      const cursor = receipt.cursor;
      if (
        this.#failed ||
        this.#complete ||
        receipt.actorId !== this.#scope.actorId ||
        receipt.propertyId !== this.#scope.propertyId ||
        receipt.paymentId !== this.#scope.paymentId ||
        receipt.view !== this.#scope.view ||
        reply.operation !== "paymentReversalContext" ||
        reply.actorId !== receipt.actorId ||
        reply.propertyId !== receipt.propertyId ||
        reply.requestId !== receipt.requestId ||
        cursor !== this.#next ||
        (!this.#started && cursor !== null) ||
        (suppliedCursor !== undefined && suppliedCursor !== cursor) ||
        !reply.page ||
        reply.page.limit !== receipt.limit ||
        reply.page.nextCursor !== receipt.nextCursor ||
        stringifyFinancialJson(reply.data, 1_048_576) !== receipt.data
      )
        invalidFinancial();
      const row = financialObject(parseFinancialJson(receipt.data, 1_048_576));
      const input: FinancialObject = {
        operation: "paymentReversalContext",
        payment_id: this.#scope.paymentId,
        view: this.#scope.view,
        limit: receipt.limit,
        ...(cursor === null ? {} : { cursor }),
      };
      const page = validateReversalContext(
        {
          data: row,
          page: { limit: receipt.limit, next_cursor: receipt.nextCursor },
        },
        input,
        this.#scope.propertyId,
        receipt.requestId,
      );
      if (this.#revision !== null && row.revision !== this.#revision)
        invalidFinancial();
      this.#items.push(...(row.items as FinancialObject[]));
      this.#revision = text(row.revision);
      this.#started = true;
      this.#next = page.nextCursor;
      if (this.#next === null) {
        if (this.#scope.view === "impact") this.#validateGraph();
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
