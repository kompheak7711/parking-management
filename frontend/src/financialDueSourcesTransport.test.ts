import { afterEach, describe, expect, it, vi } from "vitest";
import { FINANCIAL_DEADLINE_MS } from "./financialClient";
import {
  financialObject,
  invalidFinancial,
  type FinancialObject,
} from "./financialContracts";
import { stringifyFinancialJson } from "./financialJson";
import {
  type FinancialDueSourcesInput,
  type DueSourcesPurpose,
} from "./financialDueSources";
import {
  createFinancialReferenceClient,
  financialDueSourcesReplyProvenance,
  FINANCIAL_REFERENCE_REPLY_BYTES,
} from "./financialReferenceClient";
import { ids } from "./test/financialFixtures";

const revision = "a".repeat(64),
  cursor = `${revision}:DEBIT_ADJUSTMENT:${ids.event}`;
function scope(signal = new AbortController().signal) {
  return { actorId: ids.actor, propertyId: ids.property, signal };
}
function request(
  purpose: DueSourcesPurpose = "allocation",
): FinancialDueSourcesInput {
  return {
    operation: "financialDueSources",
    purpose,
    source_id: purpose === "allocation" ? ids.payment : ids.credit,
    invoice_id: ids.invoice,
    invoice_line_id: ids.other,
  };
}
function envelope(
  input: FinancialDueSourcesInput,
  requestId: string,
): FinancialObject {
  const debit = {
    source_kind: "DEBIT_ADJUSTMENT",
    source_id: ids.event,
    approved_due_date: "2027-01-01",
    source_occurred_at: "2026-08-01T01:02:03.123456Z",
    remaining_usd_cents: 100,
  };
  const original = {
    source_kind: "ORIGINAL_LINE",
    source_id: ids.other,
    approved_due_date: "2027-02-05",
    source_occurred_at: "2026-07-01T00:00:00Z",
    remaining_usd_cents: 200,
  };
  return {
    data: {
      property_id: ids.property,
      purpose: input.purpose,
      source_id: input.source_id,
      invoice_id: ids.invoice,
      invoice_line_id: ids.other,
      invoice_version: 7,
      revision,
      as_of: "2026-09-16T00:00:00Z",
      aggregate_outstanding_usd_cents: 300,
      item_count: 2,
      items: input.cursor
        ? [original]
        : input.limit === 1
          ? [debit]
          : [debit, original],
    },
    page: {
      limit: input.limit ?? 50,
      next_cursor: !input.cursor && input.limit === 1 ? cursor : null,
    },
    meta: {
      request_id: requestId,
      actor_id: ids.actor,
      property_id: ids.property,
    },
  };
}
function response(
  init: RequestInit,
  input: FinancialDueSourcesInput,
  mutate?: (row: FinancialObject, headers: Headers) => void,
): Response {
  const requestId =
    new Headers(init.headers).get("X-Request-ID") ?? invalidFinancial();
  const row = envelope(input, requestId),
    headers = new Headers({
      "Content-Type": "application/json",
      "X-Request-ID": requestId,
    });
  mutate?.(row, headers);
  return new Response(
    stringifyFinancialJson(row, FINANCIAL_REFERENCE_REPLY_BYTES),
    { status: 200, headers },
  );
}
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});
describe("dated-source reference transport", () => {
  it.each([
    ["allocation", undefined],
    ["allocation", 1],
    ["allocation", 100],
    ["credit_application", undefined],
    ["credit_application", 1],
    ["credit_application", 100],
  ] as const)(
    "TEST-FE-1055-SOURCE-TRANSPORT-1 reads %s page size %s privately",
    async (purpose, limit) => {
      const input = {
          ...request(purpose),
          ...(limit === undefined ? {} : { limit }),
        },
        csrf = vi.fn(() => "unused");
      const fetcher = vi.fn<typeof fetch>((_url, init) =>
        Promise.resolve(response(init ?? {}, input)),
      );
      const reply = await createFinancialReferenceClient(fetcher, csrf).read(
        scope(),
        input,
      );
      const [url, init] = fetcher.mock.calls[0] ?? invalidFinancial(),
        headers = new Headers(init?.headers);
      const parsed = new URL(
        typeof url === "string" ? url : invalidFinancial(),
        "http://localhost",
      );
      expect(parsed.pathname).toBe(
        `/api/v1/properties/${ids.property}/financial-due-sources`,
      );
      expect(Object.fromEntries(parsed.searchParams)).toEqual({
        purpose,
        source_id: input.source_id,
        invoice_id: ids.invoice,
        invoice_line_id: ids.other,
        ...(limit === undefined ? {} : { limit: String(limit) }),
      });
      expect(init).toMatchObject({
        method: "GET",
        credentials: "include",
        cache: "no-store",
        redirect: "error",
      });
      expect(init?.body).toBeUndefined();
      expect(headers.get("Idempotency-Key")).toBeNull();
      expect(headers.get("X-CSRF-Token")).toBeNull();
      expect(csrf).not.toHaveBeenCalled();
      expect(headers.get("X-Billing-Actor-ID")).toBe(ids.actor);
      expect(headers.get("X-Financial-Property-ID")).toBe(ids.property);
      expect(reply.operation).toBe("financialDueSources");
      expect(reply.page).toEqual({
        limit: limit ?? 50,
        nextCursor: limit === 1 ? cursor : null,
      });
      expect(financialDueSourcesReplyProvenance(reply)).toMatchObject({
        actorId: ids.actor,
        propertyId: ids.property,
        requestId: headers.get("X-Request-ID"),
        purpose,
        sourceId: input.source_id,
        invoiceId: ids.invoice,
        invoiceLineId: ids.other,
        cursor: null,
        limit: limit ?? 50,
        nextCursor: limit === 1 ? cursor : null,
      });
    },
  );
  it.each([
    "purpose",
    "source",
    "invoice",
    "line",
    "limit",
    "cursor",
    "extra",
    "property",
    "actor",
  ] as const)(
    "TEST-FE-1055-SOURCE-TRANSPORT-2 rejects invalid %s before transport",
    async (field) => {
      const input: Record<string, unknown> = { ...request() },
        selected = scope();
      switch (field) {
        case "purpose":
          input.purpose = "refund_return";
          break;
        case "source":
          input.source_id = "../payment";
          break;
        case "invoice":
          input.invoice_id = null;
          break;
        case "line":
          delete input.invoice_line_id;
          break;
        case "limit":
          input.limit = 101;
          break;
        case "cursor":
          input.cursor = "invented";
          break;
        case "extra":
          input.idempotency_key = ids.key;
          break;
        case "property":
          selected.propertyId = "../property";
          break;
        case "actor":
          selected.actorId = "invalid";
          break;
      }
      const fetcher = vi.fn<typeof fetch>();
      await expect(
        createFinancialReferenceClient(fetcher).read(
          selected,
          input as unknown as FinancialDueSourcesInput,
        ),
      ).rejects.toMatchObject({ code: "INVALID_REQUEST" });
      expect(fetcher).not.toHaveBeenCalled();
    },
  );
  it.each([
    "meta_actor",
    "meta_property",
    "meta_request",
    "meta_extra",
    "header_request",
    "media_type",
    "data_property",
    "data_source",
    "data_invoice",
    "data_line",
    "data_revision",
    "page_limit",
    "page_cursor",
    "extra",
    "missing_page",
  ] as const)(
    "TEST-FE-1055-SOURCE-TRANSPORT-3 rejects response binding or contract mismatch %s",
    async (failure) => {
      const input = request();
      const fetcher = vi.fn<typeof fetch>((_url, init) =>
        Promise.resolve(
          response(init ?? {}, input, (row, headers) => {
            const data = financialObject(row.data),
              meta = financialObject(row.meta),
              page = financialObject(row.page);
            switch (failure) {
              case "meta_actor":
                meta.actor_id = ids.other;
                break;
              case "meta_property":
                meta.property_id = ids.other;
                break;
              case "meta_request":
                meta.request_id = ids.other;
                break;
              case "meta_extra":
                meta.customer_id = ids.customer;
                break;
              case "header_request":
                headers.set("X-Request-ID", ids.other);
                break;
              case "media_type":
                headers.set("Content-Type", "text/plain");
                break;
              case "data_property":
                data.property_id = ids.other;
                break;
              case "data_source":
                data.source_id = ids.credit;
                break;
              case "data_invoice":
                data.invoice_id = ids.other;
                break;
              case "data_line":
                data.invoice_line_id = ids.invoice;
                break;
              case "data_revision":
                data.revision = "invalid";
                break;
              case "page_limit":
                page.limit = 49;
                break;
              case "page_cursor":
                page.next_cursor = cursor;
                break;
              case "extra":
                row.command = {};
                break;
              case "missing_page":
                delete row.page;
                break;
            }
          }),
        ),
      );
      await expect(
        createFinancialReferenceClient(fetcher).read(scope(), input),
      ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
      expect(fetcher).toHaveBeenCalledTimes(1);
    },
  );
  it.each([
    [400, "BAD_REQUEST"],
    [401, "UNAUTHORIZED"],
    [403, "FORBIDDEN"],
    [404, "NOT_FOUND"],
    [409, "CONFLICT"],
    [500, "INTERNAL_ERROR"],
    [503, "SERVICE_UNAVAILABLE"],
  ] as const)(
    "TEST-FE-1055-SOURCE-TRANSPORT-4 preserves safe rejection %s",
    async (status, code) => {
      const fetcher = vi.fn<typeof fetch>((_url, init) => {
        const id =
          new Headers(init?.headers).get("X-Request-ID") ?? invalidFinancial();
        return Promise.resolve(
          new Response(
            stringifyFinancialJson({
              error: { code, message: "Synthetic private server detail" },
              meta: { request_id: id },
            }),
            {
              status,
              headers: {
                "Content-Type": "application/json",
                "X-Request-ID": id,
              },
            },
          ),
        );
      });
      await expect(
        createFinancialReferenceClient(fetcher).read(scope(), request()),
      ).rejects.toMatchObject({ code: "HTTP_REJECTION", status });
      expect(fetcher).toHaveBeenCalledTimes(1);
    },
  );
  it.each(["allocation", "credit_application"] as const)(
    "TEST-FE-1055-SOURCE-TRANSPORT-5 preserves %s continued-page provenance",
    async (purpose) => {
      const first = { ...request(purpose), limit: 1 },
        next = { ...first, cursor };
      const fetcher = vi.fn<typeof fetch>((url, init) =>
        Promise.resolve(
          response(
            init ?? {},
            (typeof url === "string" ? url : invalidFinancial()).includes(
              "cursor=",
            )
              ? next
              : first,
          ),
        ),
      );
      const client = createFinancialReferenceClient(fetcher),
        initial = await client.read(scope(), first);
      const continued = await client.read(scope(), next),
        receipt =
          financialDueSourcesReplyProvenance(continued) ?? invalidFinancial();
      expect(initial.page?.nextCursor).toBe(cursor);
      expect(continued.page?.nextCursor).toBeNull();
      expect(receipt.cursor).toBe(cursor);
      expect(receipt.invoiceLineId).toBe(ids.other);
      expect(financialObject(continued.data).items).toHaveLength(1);
      expect(
        financialDueSourcesReplyProvenance({ ...continued }),
      ).toBeUndefined();
      expect(financialDueSourcesReplyProvenance({})).toBeUndefined();
      expect(Object.isFrozen(receipt)).toBe(true);
      const original = receipt.data;
      financialObject(continued.data).item_count = 999;
      continued.actorId = ids.other;
      if (continued.page) continued.page.nextCursor = "forged";
      expect(receipt.data).toBe(original);
      expect(receipt.actorId).toBe(ids.actor);
      expect(receipt.nextCursor).toBeNull();
    },
  );
  it("TEST-FE-1055-SOURCE-TRANSPORT-6 detaches caller scope and captures exact BIGINT facts", async () => {
    const input = request(),
      selected = scope(),
      maximum = 9223372036854775807n;
    const fetcher = vi.fn<typeof fetch>((_url, init) => {
      const reply = response(init ?? {}, input, (row) => {
        const data = financialObject(row.data);
        data.aggregate_outstanding_usd_cents = maximum;
        const items = data.items as FinancialObject[];
        financialObject(items[0]).remaining_usd_cents = maximum - 200n;
      });
      input.purpose = "credit_application";
      input.source_id = ids.credit;
      selected.actorId = ids.other;
      selected.propertyId = ids.other;
      return Promise.resolve(reply);
    });
    const result = await createFinancialReferenceClient(fetcher).read(
      selected,
      input,
    );
    const receipt =
      financialDueSourcesReplyProvenance(result) ?? invalidFinancial();
    expect(receipt).toMatchObject({
      actorId: ids.actor,
      propertyId: ids.property,
      sourceId: ids.payment,
      purpose: "allocation",
    });
    expect(financialObject(result.data).aggregate_outstanding_usd_cents).toBe(
      maximum,
    );
    expect(receipt.data).toContain("9223372036854775807");
  });
  it.each(["before", "during"] as const)(
    "TEST-FE-1055-SOURCE-TRANSPORT-7 cancels a stale workspace %s fetch",
    async (when) => {
      const controller = new AbortController(),
        fetcher = vi.fn<typeof fetch>(
          () =>
            new Promise<Response>(() => {
              // Deliberately uncooperative fetch: the client's abort race must settle it.
            }),
        );
      if (when === "before") controller.abort();
      const pending = createFinancialReferenceClient(fetcher).read(
        scope(controller.signal),
        request(),
      );
      const checked = expect(pending).rejects.toMatchObject({
        code: "WORKSPACE_INVALIDATED",
      });
      controller.abort();
      await checked;
      expect(fetcher).toHaveBeenCalledTimes(when === "before" ? 0 : 1);
    },
  );
  it("TEST-FE-1055-SOURCE-TRANSPORT-8 enforces the unchanged request deadline", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn<typeof fetch>(
      () =>
        new Promise<Response>(() => {
          // Deliberately unresolved so the existing deadline has to release the caller.
        }),
    );
    const pending = createFinancialReferenceClient(fetcher).read(
      scope(),
      request(),
    );
    const checked = expect(pending).rejects.toMatchObject({
      code: "UNAVAILABLE",
    });
    await vi.advanceTimersByTimeAsync(FINANCIAL_DEADLINE_MS);
    await checked;
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });
  it.each([
    "declared_size",
    "data_size",
    "invalid_json",
    "invalid_utf8",
  ] as const)(
    "TEST-FE-1055-SOURCE-TRANSPORT-9 bounds bytes and rejects malformed data %s",
    async (failure) => {
      const cancel = vi.fn(),
        input = request();
      const fetcher = vi.fn<typeof fetch>((_url, init) => {
        const requestId =
          new Headers(init?.headers).get("X-Request-ID") ?? invalidFinancial();
        const row = envelope(input, requestId);
        if (failure === "data_size")
          financialObject(row.data).revision = "a".repeat(100_001);
        const raw =
          failure === "invalid_json"
            ? "{"
            : stringifyFinancialJson(row, FINANCIAL_REFERENCE_REPLY_BYTES);
        const bytes =
          failure === "invalid_utf8"
            ? new Uint8Array([255])
            : new TextEncoder().encode(raw);
        const body = new ReadableStream<Uint8Array>({
          start(controller) {
            if (failure !== "declared_size") {
              controller.enqueue(bytes);
              controller.close();
            }
          },
          cancel() {
            cancel();
          },
        });
        const headers = new Headers({
          "Content-Type": "application/json",
          "X-Request-ID": requestId,
        });
        if (failure === "declared_size")
          headers.set(
            "Content-Length",
            String(FINANCIAL_REFERENCE_REPLY_BYTES + 1),
          );
        return Promise.resolve(new Response(body, { status: 200, headers }));
      });
      await expect(
        createFinancialReferenceClient(fetcher).read(scope(), input),
      ).rejects.toMatchObject({
        code:
          failure === "declared_size"
            ? "RESPONSE_TOO_LARGE"
            : "INVALID_RESPONSE",
      });
      if (failure === "declared_size") expect(cancel).toHaveBeenCalledTimes(1);
      expect(fetcher).toHaveBeenCalledTimes(1);
    },
  );
});
