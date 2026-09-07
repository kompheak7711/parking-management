import {
  captureFinancialActionContext,
  validateFinancialActionContext,
  type FinancialActionContextInput,
} from "./financialActionContext";
import {
  financialId,
  financialInteger,
  financialObject,
  invalidFinancial,
  type FinancialObject,
} from "./financialContracts";
import { parseFinancialJson, stringifyFinancialJson } from "./financialJson";
import {
  financialActionContextReplyProvenance,
  type FinancialReferenceReply,
} from "./financialReferenceClient";

/** Complete selected-source facts in memory. A context never authorizes a command. */
export class FinancialActionContextSequence {
  #scope: Readonly<{
    actorId: string;
    propertyId: string;
    input: Readonly<FinancialActionContextInput>;
  }>;
  #next: string | null = null;
  #complete = false;
  #failed = false;
  #snapshot: string | null = null;
  #items: FinancialObject[] = [];
  constructor(
    actorId: string,
    propertyId: string,
    request: FinancialActionContextInput,
  ) {
    if (
      financialId(actorId) !== actorId ||
      financialId(propertyId) !== propertyId
    )
      invalidFinancial();
    const input = financialObject(
      parseFinancialJson(stringifyFinancialJson(request, 32768), 32768),
    );
    captureFinancialActionContext(input);
    if (input.cursor !== undefined) invalidFinancial();
    this.#scope = Object.freeze({
      actorId,
      propertyId,
      input: Object.freeze(input as unknown as FinancialActionContextInput),
    });
    Object.freeze(this);
  }
  get actorId(): string {
    return this.#scope.actorId;
  }
  get propertyId(): string {
    return this.#scope.propertyId;
  }
  get request(): Readonly<FinancialActionContextInput> {
    return this.#scope.input;
  }
  get complete(): boolean {
    return this.#complete && !this.#failed;
  }
  get nextCursor(): string | null {
    return this.#next;
  }
  get data(): FinancialObject | null {
    if (!this.complete || this.#snapshot === null) return null;
    // Detached copies prevent a consumer from changing the verified internal facts.
    const row = financialObject(parseFinancialJson(this.#snapshot, 1_048_576));
    row.items = this.#items.map((item) =>
      parseFinancialJson(stringifyFinancialJson(item, 1_048_576), 1_048_576),
    );
    return row;
  }
  append(reply: FinancialReferenceReply): void {
    try {
      const receipt = financialActionContextReplyProvenance(reply),
        input = this.#scope.input;
      if (
        !receipt ||
        this.#failed ||
        this.#complete ||
        receipt.actorId !== this.#scope.actorId ||
        receipt.propertyId !== this.#scope.propertyId ||
        receipt.purpose !== input.purpose ||
        receipt.sourceId !== input.source_id ||
        receipt.refundId !== (input.refund_id ?? null) ||
        receipt.targetKind !== (input.target_kind ?? null) ||
        receipt.targetId !== (input.target_id ?? null) ||
        receipt.limit !== (input.limit ?? 50) ||
        receipt.cursor !== this.#next ||
        (this.#snapshot === null && receipt.cursor !== null) ||
        reply.operation !== "financialActionContext" ||
        reply.actorId !== receipt.actorId ||
        reply.propertyId !== receipt.propertyId ||
        reply.requestId !== receipt.requestId ||
        reply.page?.limit !== receipt.limit ||
        reply.page.nextCursor !== receipt.nextCursor ||
        stringifyFinancialJson(reply.data, 1_048_576) !== receipt.data
      )
        invalidFinancial();
      const row = financialObject(parseFinancialJson(receipt.data, 1_048_576));
      validateFinancialActionContext(
        {
          data: row,
          page: { limit: receipt.limit, next_cursor: receipt.nextCursor },
        },
        financialObject({
          ...input,
          ...(receipt.cursor === null ? {} : { cursor: receipt.cursor }),
        }),
        this.#scope.propertyId,
        receipt.requestId,
      );
      const { items, ...facts } = row;
      const snapshot = stringifyFinancialJson(facts, 1_048_576);
      if (this.#snapshot !== null && snapshot !== this.#snapshot)
        invalidFinancial();
      this.#snapshot = snapshot;
      this.#items.push(...(items as FinancialObject[]));
      if (this.#items.length > 32767) invalidFinancial();
      this.#next = receipt.nextCursor;
      if (this.#next === null) {
        this.#validateComplete(row);
        this.#complete = true;
      }
    } catch (error) {
      this.#failed = true;
      this.#complete = false;
      throw error;
    }
  }
  #validateComplete(row: FinancialObject): void {
    const context = financialObject(row.context),
      input = this.#scope.input;
    const allocation = input.purpose === "allocation_reversal",
      application = input.purpose === "credit_application_reversal";
    const invoice =
      (input.purpose === "allocation" ||
        input.purpose === "credit_application") &&
      row.target !== null &&
      financialObject(row.target).kind === "INVOICE";
    const identities = new Set<string>(),
      sequences = new Set<string>(),
      targets = new Set<string>();
    let total = 0n;
    for (const item of this.#items) {
      const identity = financialId(item.id),
        sequence = financialInteger(item.sequence, 1n).toString(),
        detail = financialObject(item.data);
      if (identities.has(identity) || sequences.has(sequence))
        invalidFinancial();
      identities.add(identity);
      sequences.add(sequence);
      if (allocation || application) {
        const target = financialId(detail.target_id);
        if (targets.has(target)) invalidFinancial();
        targets.add(target);
      }
      total += BigInt(
        financialInteger(
          detail[
            allocation
              ? "posted_amount_usd_cents"
              : application
                ? "applied_amount_usd_cents"
                : "outstanding_usd_cents"
          ],
        ),
      );
    }
    if (allocation || application) {
      if (
        total !==
        BigInt(
          financialInteger(
            financialObject(context[allocation ? "allocation" : "application"])
              .amount_usd_cents,
            1n,
          ),
        )
      )
        invalidFinancial();
    } else if (
      invoice &&
      total !==
        BigInt(
          financialInteger(financialObject(row.target).outstanding_usd_cents),
        )
    )
      invalidFinancial();
  }
}
