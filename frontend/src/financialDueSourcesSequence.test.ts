import { afterEach, describe, expect, it, vi } from "vitest";
import {
  financialObject,
  invalidFinancial,
  type FinancialObject,
} from "./financialContracts";
import type {
  DueSourcesPurpose,
  FinancialDueSourcesInput,
} from "./financialDueSources";
import { FinancialDueSourcesSequence } from "./financialDueSourcesSequence";
import { stringifyFinancialJson } from "./financialJson";
import {
  createFinancialReferenceClient,
  type FinancialReferenceReply,
} from "./financialReferenceClient";
import { ids } from "./test/financialFixtures";

const revision = "a".repeat(64);
const scope = () => ({
  actorId: ids.actor,
  propertyId: ids.property,
  signal: new AbortController().signal,
});
function input(
  purpose: DueSourcesPurpose = "allocation",
  limit = 1,
): FinancialDueSourcesInput {
  return {
    operation: "financialDueSources",
    purpose,
    source_id: purpose === "allocation" ? ids.payment : ids.credit,
    invoice_id: ids.invoice,
    invoice_line_id: ids.other,
    limit,
  };
}
function source(
  id: string,
  date = "2027-01-01",
  amount: number | bigint = 100,
): FinancialObject {
  return {
    source_kind: id === ids.other ? "ORIGINAL_LINE" : "DEBIT_ADJUSTMENT",
    source_id: id,
    approved_due_date: date,
    source_occurred_at: "2026-08-01T00:00:00.000001Z",
    remaining_usd_cents: amount,
  };
}
function cursor(item: FinancialObject): string {
  const kind = item.source_kind,
    id = item.source_id;
  if (typeof kind !== "string" || typeof id !== "string")
    return invalidFinancial();
  return `${revision}:${kind}:${id}`;
}
const first = () => source(ids.event),
  second = () => source(ids.other, "2027-02-05");
async function page(
  request: FinancialDueSourcesInput,
  items: FinancialObject[],
  more: boolean,
  changes: FinancialObject = {},
  boundary = scope(),
): Promise<FinancialReferenceReply> {
  const fetcher = vi.fn<typeof fetch>((_url, init) => {
    const requestId =
      new Headers(init?.headers).get("X-Request-ID") ?? invalidFinancial();
    const body = {
      data: {
        property_id: boundary.propertyId,
        purpose: request.purpose,
        source_id: request.source_id,
        invoice_id: request.invoice_id,
        invoice_line_id: request.invoice_line_id,
        invoice_version: 7,
        revision,
        as_of: "2026-09-16T00:00:00Z",
        aggregate_outstanding_usd_cents: 200,
        item_count: 2,
        items,
        ...changes,
      },
      page: {
        limit: request.limit ?? 50,
        next_cursor: more ? cursor(items.at(-1) ?? invalidFinancial()) : null,
      },
      meta: {
        actor_id: boundary.actorId,
        property_id: boundary.propertyId,
        request_id: requestId,
      },
    };
    return Promise.resolve(
      new Response(stringifyFinancialJson(body, 1_048_576), {
        status: 200,
        headers: {
          "Content-Type": "application/json",
          "X-Request-ID": requestId,
        },
      }),
    );
  });
  return createFinancialReferenceClient(fetcher).read(boundary, request);
}
function sequence(request = input()) {
  return new FinancialDueSourcesSequence(ids.actor, ids.property, request);
}
function continued(
  request = input(),
  anchor = first(),
): FinancialDueSourcesInput {
  return { ...request, cursor: cursor(anchor) };
}
function rejected(
  seq: FinancialDueSourcesSequence,
  reply: FinancialReferenceReply,
) {
  expect(() => {
    seq.append(reply);
  }).toThrow();
  expect(seq.data).toBeNull();
  expect(seq.complete).toBe(false);
  expect(seq.nextCursor).toBeNull();
}
afterEach(() => {
  vi.restoreAllMocks();
});
describe("complete dated-source sequence", () => {
  it.each(["allocation", "credit_application"] as const)(
    "TEST-FE-1055-SOURCE-SEQUENCE-1 assembles %s across advancing snapshots",
    async (purpose) => {
      const request = input(purpose),
        seq = sequence(request);
      expect(seq.data).toBeNull();
      expect(seq.complete).toBe(false);
      seq.append(await page(request, [first()], true));
      expect(seq.data).toBeNull();
      expect(seq.nextCursor).toBe(cursor(first()));
      seq.append(
        await page(continued(request), [second()], false, {
          as_of: "2026-09-16T00:00:01.123456+00:00",
        }),
      );
      expect(seq.complete).toBe(true);
      expect(seq.nextCursor).toBeNull();
      expect(seq.data).toMatchObject({
        purpose,
        item_count: 2,
        aggregate_outstanding_usd_cents: 200,
        items: [first(), second()],
        as_of: "2026-09-16T00:00:01.123456+00:00",
      });
      const copy = seq.data ?? invalidFinancial();
      copy.items = [];
      copy.item_count = 0;
      expect(seq.data?.items).toEqual([first(), second()]);
    },
  );
  it.each(["allocation", "credit_application"] as const)(
    "TEST-FE-1055-SOURCE-SEQUENCE-1 accepts one complete %s page",
    async (purpose) => {
      const request = input(purpose, 50),
        seq = sequence(request);
      seq.append(await page(request, [first(), second()], false));
      expect(seq.data?.items).toEqual([first(), second()]);
      expect(seq.complete).toBe(true);
    },
  );
  it.each(["allocation", "credit_application"] as const)(
    "TEST-FE-1055-SOURCE-SEQUENCE-1 accepts empty %s facts",
    async (purpose) => {
      const request = input(purpose),
        seq = sequence(request);
      seq.append(
        await page(request, [], false, {
          item_count: 0,
          aggregate_outstanding_usd_cents: 0,
        }),
      );
      expect(seq.complete).toBe(true);
      expect(seq.data?.items).toEqual([]);
    },
  );
  it("TEST-FE-1055-SOURCE-SEQUENCE-2 captures and freezes the request", async () => {
    const request = input(),
      seq = sequence(request);
    request.source_id = ids.credit;
    expect(seq.actorId).toBe(ids.actor);
    expect(seq.propertyId).toBe(ids.property);
    expect(seq.request.source_id).toBe(ids.payment);
    expect(Object.isFrozen(seq.request)).toBe(true);
    expect(Object.isFrozen(seq)).toBe(true);
    seq.append(await page(input(), [first()], true));
    expect(seq.data).toBeNull();
  });
  it("TEST-FE-1055-SOURCE-SEQUENCE-1 assembles three full source pages", async () => {
    const seq = sequence(),
      a = first(),
      b = source(ids.method, "2027-01-02"),
      c = second(),
      facts = { item_count: 3, aggregate_outstanding_usd_cents: 300 };
    seq.append(await page(input(), [a], true, facts));
    seq.append(await page(continued(input(), a), [b], true, facts));
    seq.append(await page(continued(input(), b), [c], false, facts));
    expect(seq.data?.items).toEqual([a, b, c]);
    expect(seq.complete).toBe(true);
  });
  it("TEST-FE-1055-SOURCE-SEQUENCE-1 uses the default page limit without mutating input", async () => {
    const { limit: omitted, ...request } = input();
    expect(omitted).toBe(1);
    const seq = sequence(request);
    seq.append(await page(request, [first(), second()], false));
    expect(seq.complete).toBe(true);
    expect(seq.request.limit).toBeUndefined();
  });
  it.each([
    "actor",
    "property",
    "purpose",
    "source",
    "invoice",
    "line",
    "limit",
  ])(
    "TEST-FE-1055-SOURCE-SEQUENCE-3 refuses genuine mismatched %s receipts",
    async (field) => {
      const boundary = scope(),
        request = input(),
        seq = sequence();
      if (field === "actor") boundary.actorId = ids.customer;
      if (field === "property") boundary.propertyId = ids.customer;
      if (field === "purpose") request.purpose = "credit_application";
      if (field === "source") request.source_id = ids.credit;
      if (field === "invoice") request.invoice_id = ids.customer;
      if (field === "line") request.invoice_line_id = ids.customer;
      if (field === "limit") request.limit = 2;
      const reply = await page(
        request,
        field === "limit" ? [first(), second()] : [first()],
        field !== "limit",
        {},
        boundary,
      );
      rejected(seq, reply);
    },
  );
  it("TEST-FE-1055-SOURCE-SEQUENCE-2 rejects an initial cursor", () => {
    expect(() => sequence(continued())).toThrow();
  });
  it.each([
    "copy",
    "operation",
    "actorId",
    "propertyId",
    "requestId",
    "data",
    "page",
    "pageLimit",
    "pageCursor",
  ])(
    "TEST-FE-1055-SOURCE-SEQUENCE-4 refuses copied or changed %s",
    async (field) => {
      let reply = await page(input(), [first()], true);
      if (field === "copy") reply = { ...reply };
      else if (field === "data")
        financialObject(reply.data).invoice_version = 8;
      else if (field === "page") Object.assign(reply, { page: undefined });
      else if (field === "pageLimit")
        Object.assign(reply.page ?? invalidFinancial(), { limit: 2 });
      else if (field === "pageCursor")
        Object.assign(reply.page ?? invalidFinancial(), { nextCursor: null });
      else Object.assign(reply, { [field]: "changed" });
      rejected(sequence(), reply);
    },
  );
  it.each(["invoice_version", "item_count", "aggregate_outstanding_usd_cents"])(
    "TEST-FE-1055-SOURCE-SEQUENCE-5 rejects changed stable %s",
    async (field) => {
      const seq = sequence();
      seq.append(await page(input(), [first()], true));
      rejected(
        seq,
        await page(continued(), [second()], false, {
          [field]:
            field === "invoice_version" ? 8 : field === "item_count" ? 3 : 201,
        }),
      );
    },
  );
  it.each(["date", "instant", "kind", "id"])(
    "TEST-FE-1055-SOURCE-SEQUENCE-6 rejects cross-page descending %s",
    async (field) => {
      const a = first(),
        b = second();
      if (field === "date") b.approved_due_date = "2026-12-31";
      else {
        b.approved_due_date = a.approved_due_date ?? invalidFinancial();
        if (field === "instant") b.source_occurred_at = "2026-08-01T00:00:00Z";
        if (field === "kind") {
          a.source_kind = "ORIGINAL_LINE";
          a.source_id = ids.other;
          b.source_kind = "DEBIT_ADJUSTMENT";
          b.source_id = ids.event;
        }
        if (field === "id") {
          b.source_kind = "DEBIT_ADJUSTMENT";
          b.source_id = ids.customer;
        }
      }
      const seq = sequence();
      seq.append(await page(input(), [a], true));
      rejected(seq, await page(continued(input(), a), [b], false));
    },
  );
  it("TEST-FE-1055-SOURCE-SEQUENCE-6 rejects a source repeated beyond the current anchor", async () => {
    const seq = sequence(),
      a = first(),
      b = source(ids.method, "2027-01-02"),
      repeated = { ...a, approved_due_date: "2027-01-03" },
      facts = { item_count: 3, aggregate_outstanding_usd_cents: 300 };
    seq.append(await page(input(), [a], true, facts));
    seq.append(await page(continued(input(), a), [b], true, facts));
    rejected(seq, await page(continued(input(), b), [repeated], false, facts));
  });
  it.each(["count", "sum", "empty"])(
    "TEST-FE-1055-SOURCE-SEQUENCE-7 rejects incomplete terminal %s",
    async (failure) => {
      const seq = sequence(),
        facts: FinancialObject =
          failure === "count"
            ? { item_count: 3, aggregate_outstanding_usd_cents: 300 }
            : {};
      seq.append(await page(input(), [first()], true, facts));
      const b = second();
      if (failure === "sum") b.remaining_usd_cents = 99;
      rejected(
        seq,
        await page(continued(), failure === "empty" ? [] : [b], false, facts),
      );
    },
  );
  it.each(["skipped", "repeated", "afterComplete"])(
    "TEST-FE-1055-SOURCE-SEQUENCE-8 rejects %s cursor delivery",
    async (failure) => {
      const seq = sequence(),
        a = await page(input(), [first()], true),
        b = await page(continued(), [second()], false);
      if (failure === "skipped") rejected(seq, b);
      else {
        seq.append(a);
        if (failure === "afterComplete") seq.append(b);
        rejected(seq, failure === "repeated" ? a : b);
      }
    },
  );
  it("TEST-FE-1055-SOURCE-SEQUENCE-8 rejects repeated request identities", async () => {
    vi.spyOn(crypto, "randomUUID").mockReturnValue(
      "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
    );
    const seq = sequence();
    seq.append(await page(input(), [first()], true));
    rejected(seq, await page(continued(), [second()], false));
  });
  it("TEST-FE-1055-SOURCE-SEQUENCE-9 cannot recover a rejected sequence by appending valid facts", async () => {
    const seq = sequence(),
      a = await page(input(), [first()], true);
    rejected(seq, { ...a });
    rejected(seq, a);
    const fresh = sequence();
    fresh.append(a);
    expect(fresh.nextCursor).toBe(cursor(first()));
  });
  it("TEST-FE-1055-SOURCE-SEQUENCE-9 rejects source counts beyond the bounded complete-read budget", async () => {
    rejected(
      sequence(),
      await page(input(), [first()], true, {
        item_count: 32768,
        aggregate_outstanding_usd_cents: 3276800,
      }),
    );
  });
  it("TEST-FE-1055-SOURCE-SEQUENCE-10 preserves full BIGINT precision across pages", async () => {
    const amount = 4_611_686_018_427_387_903n,
      facts = { aggregate_outstanding_usd_cents: amount * 2n },
      seq = sequence(),
      a = source(ids.event, "2027-01-01", amount),
      b = source(ids.other, "2027-02-05", amount);
    seq.append(await page(input(), [a], true, facts));
    seq.append(await page(continued(), [b], false, facts));
    expect(seq.data?.aggregate_outstanding_usd_cents).toBe(amount * 2n);
    expect(seq.data?.items).toEqual([a, b]);
  });
  it("TEST-FE-1055-SOURCE-SEQUENCE-10 compares instants across offsets at microsecond precision", async () => {
    const seq = sequence(),
      a = first(),
      b = second();
    b.approved_due_date = a.approved_due_date ?? invalidFinancial();
    b.source_occurred_at = "2026-08-01T07:00:00.000002+07:00";
    seq.append(await page(input(), [a], true));
    seq.append(await page(continued(), [b], false));
    expect(seq.complete).toBe(true);
  });
  it.each(["actor", "property", "request"])(
    "TEST-FE-1055-SOURCE-SEQUENCE-2 rejects malformed initial %s",
    (field) => {
      const request = input();
      if (field === "request") request.source_id = "invalid";
      expect(
        () =>
          new FinancialDueSourcesSequence(
            field === "actor" ? "invalid" : ids.actor,
            field === "property" ? "invalid" : ids.property,
            request,
          ),
      ).toThrow();
    },
  );
});
