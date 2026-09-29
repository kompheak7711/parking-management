import {
  captureDueSources,
  validateDueSourcesPage,
  type FinancialDueSourcesInput,
} from "./financialDueSources";
import {
  financialId,
  financialInstant,
  financialInteger,
  financialObject,
  invalidFinancial,
  type FinancialObject,
} from "./financialContracts";
import { parseFinancialJson, stringifyFinancialJson } from "./financialJson";
import {
  financialDueSourcesReplyProvenance,
  type FinancialReferenceReply,
} from "./financialReferenceClient";

const maximumBytes = 8_388_608;
type Order = readonly [string, bigint, string, string];
function precedes(left: Order, right: Order): boolean {
  for (let index = 0; index < 4; index++) {
    const a = left[index] ?? invalidFinancial(),
      b = right[index] ?? invalidFinancial();
    if (a !== b) return a < b;
  }
  return false;
}

/** Complete read facts only. This sequence never calculates or authorizes posting. */
export class FinancialDueSourcesSequence {
  #scope: Readonly<{
    actorId: string;
    propertyId: string;
    input: Readonly<FinancialDueSourcesInput>;
  }>;
  #next: string | null = null;
  #complete = false;
  #failed = false;
  #snapshot: string | null = null;
  #facts: FinancialObject | null = null;
  #items: FinancialObject[] = [];
  #bytes = 0;
  #total = 0n;
  #last: Order | null = null;
  #sources = new Set<string>();
  #requests = new Set<string>();
  constructor(
    actorId: string,
    propertyId: string,
    request: FinancialDueSourcesInput,
  ) {
    if (
      financialId(actorId) !== actorId ||
      financialId(propertyId) !== propertyId
    )
      invalidFinancial();
    const input = captureDueSources(request);
    if (input.cursor !== undefined) invalidFinancial();
    this.#scope = Object.freeze({
      actorId,
      propertyId,
      input: Object.freeze(input as unknown as FinancialDueSourcesInput),
    });
    Object.freeze(this);
  }
  get actorId(): string {
    return this.#scope.actorId;
  }
  get propertyId(): string {
    return this.#scope.propertyId;
  }
  get request(): Readonly<FinancialDueSourcesInput> {
    return this.#scope.input;
  }
  get complete(): boolean {
    return this.#complete && !this.#failed;
  }
  get nextCursor(): string | null {
    return this.#next;
  }
  get data(): FinancialObject | null {
    if (!this.complete || this.#facts === null) return null;
    return financialObject(
      parseFinancialJson(
        stringifyFinancialJson(
          { ...this.#facts, items: this.#items },
          maximumBytes,
        ),
        maximumBytes,
      ),
    );
  }
  append(reply: FinancialReferenceReply): void {
    try {
      const receipt = financialDueSourcesReplyProvenance(reply),
        input = this.#scope.input;
      if (
        !receipt ||
        this.#failed ||
        this.#complete ||
        receipt.actorId !== this.actorId ||
        receipt.propertyId !== this.propertyId ||
        receipt.purpose !== input.purpose ||
        receipt.sourceId !== input.source_id ||
        receipt.invoiceId !== input.invoice_id ||
        receipt.invoiceLineId !== input.invoice_line_id ||
        receipt.limit !== (input.limit ?? 50) ||
        receipt.cursor !== this.#next ||
        this.#requests.has(receipt.requestId) ||
        reply.operation !== "financialDueSources" ||
        reply.actorId !== receipt.actorId ||
        reply.propertyId !== receipt.propertyId ||
        reply.requestId !== receipt.requestId ||
        reply.page?.limit !== receipt.limit ||
        reply.page.nextCursor !== receipt.nextCursor ||
        stringifyFinancialJson(reply.data, 100_000) !== receipt.data
      )
        invalidFinancial();
      const { data: row } = validateDueSourcesPage(
        parseFinancialJson(receipt.data, 100_000),
        { limit: receipt.limit, next_cursor: receipt.nextCursor },
        {
          ...input,
          ...(receipt.cursor === null ? {} : { cursor: receipt.cursor }),
        },
        this.propertyId,
      );
      const { items, as_of: asOf, ...facts } = row;
      if (typeof asOf !== "string") invalidFinancial();
      // Key order and the advancing statement clock do not change stable facts.
      const snapshot = stringifyFinancialJson(
        [
          row.property_id,
          row.purpose,
          row.source_id,
          row.invoice_id,
          row.invoice_line_id,
          row.invoice_version,
          row.revision,
          row.aggregate_outstanding_usd_cents,
          row.item_count,
        ],
        100_000,
      );
      if (this.#snapshot !== null && this.#snapshot !== snapshot)
        invalidFinancial();
      const incoming = items as FinancialObject[],
        count = Number(financialInteger(row.item_count, 0n, 32767n)),
        length = this.#items.length + incoming.length;
      if (length > count || (receipt.nextCursor !== null && length >= count))
        invalidFinancial();
      const encoder = new TextEncoder();
      const bytes =
        this.#bytes +
        encoder.encode(stringifyFinancialJson(incoming, 100_000)).byteLength -
        2 +
        (this.#items.length > 0 && incoming.length > 0 ? 1 : 0);
      if (
        encoder.encode(
          stringifyFinancialJson({ ...facts, as_of: asOf, items: [] }, 100_000),
        ).byteLength +
          bytes >
        maximumBytes
      )
        invalidFinancial();
      for (const item of incoming) {
        const kind = item.source_kind as string,
          id = financialId(item.source_id),
          identity = `${kind}:${id}`;
        const order: Order = [
          item.approved_due_date as string,
          financialInstant(item.source_occurred_at),
          kind,
          id,
        ];
        if (
          this.#sources.has(identity) ||
          (this.#last !== null && !precedes(this.#last, order))
        )
          invalidFinancial();
        this.#sources.add(identity);
        this.#last = order;
        this.#total += BigInt(financialInteger(item.remaining_usd_cents, 1n));
      }
      const aggregate = BigInt(
        financialInteger(row.aggregate_outstanding_usd_cents),
      );
      if (
        this.#total > aggregate ||
        (receipt.nextCursor === null &&
          (length !== count || this.#total !== aggregate))
      )
        invalidFinancial();
      this.#snapshot = snapshot;
      this.#facts = { ...facts, as_of: asOf };
      this.#items.push(...incoming);
      this.#bytes = bytes;
      this.#requests.add(receipt.requestId);
      this.#next = receipt.nextCursor;
      this.#complete = this.#next === null;
    } catch (error) {
      this.#failed = true;
      this.#complete = false;
      this.#snapshot = null;
      this.#facts = null;
      this.#items = [];
      this.#bytes = 0;
      this.#total = 0n;
      this.#last = null;
      this.#sources.clear();
      this.#requests.clear();
      this.#next = null;
      throw error;
    }
  }
}
