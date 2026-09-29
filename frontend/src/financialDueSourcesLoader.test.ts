import { describe, expect, it, vi } from "vitest";
import { type FinancialScope } from "./financialClient";
import { invalidFinancial } from "./financialContracts";
import {
  type DueSourcesPurpose,
  type FinancialDueSourcesInput,
} from "./financialDueSources";
import { loadFinancialDueSources } from "./financialDueSourcesLoader";
import { stringifyFinancialJson } from "./financialJson";
import {
  createFinancialReferenceClient,
  FinancialReferenceError,
  type FinancialReferenceRequest,
} from "./financialReferenceClient";
import { ids } from "./test/financialFixtures";

const revision = "a".repeat(64);
function scope(signal = new AbortController().signal): FinancialScope {
  return { actorId: ids.actor, propertyId: ids.property, signal };
}
function input(
  purpose: DueSourcesPurpose = "allocation",
): FinancialDueSourcesInput {
  return {
    operation: "financialDueSources",
    purpose,
    source_id: purpose === "allocation" ? ids.payment : ids.credit,
    invoice_id: ids.invoice,
    invoice_line_id: ids.other,
    limit: 1,
  };
}
function client(count = 2) {
  const fetcher = vi.fn<typeof fetch>((url, init) => {
    const parsed = new URL(
      typeof url === "string" ? url : invalidFinancial(),
      "http://localhost",
    );
    const query = parsed.searchParams,
      anchor = query.get("cursor");
    const index = anchor === null ? 0 : Number.parseInt(anchor.slice(-12), 16);
    const sourceId = `00000000-0000-4000-8000-${(index + 1).toString(16).padStart(12, "0")}`;
    const headers = new Headers(init?.headers),
      requestId = headers.get("X-Request-ID") ?? invalidFinancial();
    const property =
        headers.get("X-Financial-Property-ID") ?? invalidFinancial(),
      actor = headers.get("X-Billing-Actor-ID") ?? invalidFinancial();
    const body = {
      data: {
        property_id: property,
        purpose: query.get("purpose"),
        source_id: query.get("source_id"),
        invoice_id: query.get("invoice_id"),
        invoice_line_id: query.get("invoice_line_id"),
        invoice_version: 7,
        revision,
        as_of: "2026-09-16T00:00:00Z",
        aggregate_outstanding_usd_cents: count * 100,
        item_count: count,
        items:
          count === 0
            ? []
            : [
                {
                  source_kind: "DEBIT_ADJUSTMENT",
                  source_id: sourceId,
                  approved_due_date: "2027-01-01",
                  source_occurred_at: "2026-08-01T00:00:00Z",
                  remaining_usd_cents: 100,
                },
              ],
      },
      page: {
        limit: 1,
        next_cursor:
          index + 1 < count ? `${revision}:DEBIT_ADJUSTMENT:${sourceId}` : null,
      },
      meta: { request_id: requestId, actor_id: actor, property_id: property },
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
  return { transport: createFinancialReferenceClient(fetcher), fetcher };
}
describe("bounded dated-source loader", () => {
  it.each(["allocation", "credit_application"] as const)(
    "TEST-FE-1055-SOURCE-LOADER-1 reads every %s page in order",
    async (purpose) => {
      const { transport, fetcher } = client(),
        result = await loadFinancialDueSources(
          scope(),
          input(purpose),
          transport,
        );
      expect(result.purpose).toBe(purpose);
      expect(result.items).toHaveLength(2);
      expect(fetcher).toHaveBeenCalledTimes(2);
      const urls = fetcher.mock.calls.map(
        ([url]) =>
          new URL(
            typeof url === "string" ? url : invalidFinancial(),
            "http://localhost",
          ),
      );
      expect(urls[0]?.searchParams.has("cursor")).toBe(false);
      expect(urls[1]?.searchParams.get("cursor")).toBe(
        `${revision}:DEBIT_ADJUSTMENT:00000000-0000-4000-8000-000000000001`,
      );
    },
  );
  it("TEST-FE-1055-SOURCE-LOADER-1 returns genuine complete empty facts", async () => {
    const { transport, fetcher } = client(0),
      result = await loadFinancialDueSources(scope(), input(), transport);
    expect(result.items).toEqual([]);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("TEST-FE-1055-SOURCE-LOADER-2 refuses a cancelled workspace before reading", async () => {
    const controller = new AbortController(),
      { transport, fetcher } = client();
    controller.abort();
    await expect(
      loadFinancialDueSources(scope(controller.signal), input(), transport),
    ).rejects.toMatchObject({ code: "WORKSPACE_INVALIDATED" });
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("TEST-FE-1055-SOURCE-LOADER-2 discards a returned page when the workspace changes", async () => {
    const controller = new AbortController(),
      { transport, fetcher } = client();
    const read = vi.fn(
      async (boundary: FinancialScope, request: FinancialReferenceRequest) => {
        const reply = await transport.read(boundary, request);
        controller.abort();
        return reply;
      },
    );
    await expect(
      loadFinancialDueSources(scope(controller.signal), input(), { read }),
    ).rejects.toMatchObject({ code: "WORKSPACE_INVALIDATED" });
    expect(read).toHaveBeenCalledTimes(1);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("TEST-FE-1055-SOURCE-LOADER-3 refuses valid replies for another actor", async () => {
    const { transport, fetcher } = client();
    const read = vi.fn(
      (boundary: FinancialScope, request: FinancialReferenceRequest) =>
        transport.read({ ...boundary, actorId: ids.customer }, request),
    );
    await expect(
      loadFinancialDueSources(scope(), input(), { read }),
    ).rejects.toThrow();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it.each(["HTTP_REJECTION", "UNAVAILABLE"] as const)(
    "TEST-FE-1055-SOURCE-LOADER-4 propagates %s without retry",
    async (code) => {
      const status = code === "HTTP_REJECTION" ? 409 : null;
      const read = vi.fn(() =>
        Promise.reject(new FinancialReferenceError(code, status)),
      );
      await expect(
        loadFinancialDueSources(scope(), input(), { read }),
      ).rejects.toMatchObject({ code, status });
      expect(read).toHaveBeenCalledTimes(1);
    },
  );
  it("TEST-FE-1055-SOURCE-LOADER-3 rejects copied receipts without another read", async () => {
    const { transport, fetcher } = client();
    const read = vi.fn(
      async (boundary: FinancialScope, request: FinancialReferenceRequest) => ({
        ...(await transport.read(boundary, request)),
      }),
    );
    await expect(
      loadFinancialDueSources(scope(), input(), { read }),
    ).rejects.toThrow();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("TEST-FE-1055-SOURCE-LOADER-5 captures input before an asynchronous caller mutation", async () => {
    const request = input(),
      { transport } = client();
    const read = vi.fn(
      (boundary: FinancialScope, captured: FinancialReferenceRequest) => {
        request.source_id = ids.credit;
        return transport.read(boundary, captured);
      },
    );
    const result = await loadFinancialDueSources(scope(), request, { read });
    expect(result.source_id).toBe(ids.payment);
    expect(read).toHaveBeenCalledTimes(2);
  });
  it("TEST-FE-1055-SOURCE-LOADER-5 captures actor and Property before caller mutation", async () => {
    const boundary = scope(),
      { transport } = client();
    const read = vi.fn(
      (captured: FinancialScope, request: FinancialReferenceRequest) => {
        boundary.actorId = ids.customer;
        boundary.propertyId = ids.customer;
        return transport.read(captured, request);
      },
    );
    const result = await loadFinancialDueSources(boundary, input(), { read });
    expect(result.property_id).toBe(ids.property);
    expect(
      read.mock.calls.every(
        ([captured]) =>
          captured.actorId === ids.actor &&
          captured.propertyId === ids.property,
      ),
    ).toBe(true);
  });
  it("TEST-FE-1055-SOURCE-LOADER-6 stops at the page ceiling without partial facts or retry", async () => {
    const { transport, fetcher } = client(1001);
    await expect(
      loadFinancialDueSources(scope(), input(), transport),
    ).rejects.toMatchObject({ code: "RESPONSE_TOO_LARGE" });
    expect(fetcher).toHaveBeenCalledTimes(1000);
  });
});
