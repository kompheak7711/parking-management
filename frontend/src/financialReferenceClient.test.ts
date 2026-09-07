import { afterEach, describe, expect, it, vi } from "vitest";
import { FINANCIAL_DEADLINE_MS } from "./financialClient";
import { financialObject, type FinancialObject } from "./financialContracts";
import { stringifyFinancialJson, type FinancialJson } from "./financialJson";
import {
  createFinancialReferenceClient,
  FINANCIAL_CAPABILITIES,
  FINANCIAL_REFERENCE_REPLY_BYTES,
  type FinancialReferenceRequest,
} from "./financialReferenceClient";
const actor = "00000000-0000-4000-8000-000000000001",
  property = "00000000-0000-4000-8000-000000000002",
  method = "00000000-0000-4000-8000-000000000003";
const operations = [
  "workspaces",
  "capabilities",
  "methods",
  "khrPreview",
] as const;
const permissions = Object.fromEntries(
  FINANCIAL_CAPABILITIES.map((cap) => [cap, cap === "payments.record"]),
);
const scope = (operation: string, signal = new AbortController().signal) => ({
  actorId: actor,
  ...(operation === "workspaces" ? {} : { propertyId: property }),
  signal,
});
const input = (
  operation: (typeof operations)[number],
): FinancialReferenceRequest =>
  operation === "khrPreview"
    ? { operation, usd_amount_cents: 1001 }
    : { operation };
function fixture(operation: string): FinancialObject {
  const data: FinancialJson =
    operation === "workspaces"
      ? [
          {
            property_id: property,
            name: "Synthetic property",
            timezone: "Asia/Phnom_Penh",
            capabilities: permissions,
          },
        ]
      : operation === "methods"
        ? [
            {
              id: method,
              property_id: property,
              code: "cash",
              display_name: "Accepted cash",
            },
          ]
        : operation === "capabilities"
          ? { property_id: property, capabilities: permissions }
          : {
              property_id: property,
              usd_amount_cents: 1001,
              provisional: true,
              status: "available",
              reference_rate_khr_per_usd: "4062.000000",
              source_reference: "Synthetic ABA quote",
              applicable_at: "2026-05-01T00:00:00Z",
              fallback_reason: null,
              rate_source: "ABA_AUTOMATIC",
              automatic_source_unavailable: false,
              markup_basis_points: 50,
              system_rate_khr_per_usd: 4083,
              unrounded_khr_amount: "40870.83",
              payable_khr_amount: 40871,
            };
  return {
    data,
    meta: {
      actor_id: actor,
      ...(operation === "workspaces" ? {} : { property_id: property }),
      request_id: "",
    },
    ...(["workspaces", "methods"].includes(operation)
      ? { page: { limit: 50, next_cursor: null } }
      : {}),
  };
}
function response(
  operation: string,
  init: RequestInit,
  mutate?: (row: FinancialObject) => void,
): Response {
  const row = fixture(operation),
    requestId = new Headers(init.headers).get("X-Request-ID") ?? "";
  financialObject(row.meta).request_id = requestId;
  mutate?.(row);
  return new Response(
    stringifyFinancialJson(row, FINANCIAL_REFERENCE_REPLY_BYTES),
    {
      status: 200,
      headers: {
        "Content-Type": "application/json",
        "X-Request-ID": requestId,
      },
    },
  );
}
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});
describe("financial references and provisional preview", () => {
  it.each(operations)(
    "TEST-FE-333 routes and validates %s with actor and Property binding without idempotency",
    async (operation) => {
      const fetcher = vi.fn<typeof fetch>((_url, init) =>
        Promise.resolve(response(operation, init ?? {})),
      );
      const result = await createFinancialReferenceClient(
        fetcher,
        () => "csrf",
      ).read(scope(operation), input(operation));
      const [url, init] = fetcher.mock.calls[0] ?? [];
      const headers = new Headers(init?.headers);
      expect(url).toBe(
        operation === "workspaces"
          ? "/api/v1/financial-workspaces"
          : `/api/v1/properties/${property}/${operation === "capabilities" ? "financial-capabilities" : operation === "methods" ? "payment-methods" : "payments/khr-preview"}`,
      );
      expect(init).toMatchObject({
        method: operation === "khrPreview" ? "POST" : "GET",
        credentials: "include",
        cache: "no-store",
        redirect: "error",
      });
      expect(headers.get("Idempotency-Key")).toBeNull();
      expect(headers.get("X-Billing-Actor-ID")).toBe(actor);
      expect(headers.get("X-Financial-Property-ID")).toBe(
        operation === "workspaces" ? null : property,
      );
      expect(result.actorId).toBe(actor);
      expect(result.propertyId).toBe(
        operation === "workspaces" ? null : property,
      );
      expect(init?.body).toBe(
        operation === "khrPreview" ? '{"usd_amount_cents":1001}' : undefined,
      );
      expect(headers.get("X-CSRF-Token")).toBe(
        operation === "khrPreview" ? "csrf" : null,
      );
    },
  );
  it.each(operations)(
    "TEST-FE-334 rejects wrong actor or Property metadata for %s",
    async (operation) => {
      for (const mutate of [
        (row: FinancialObject) => {
          financialObject(row.meta).actor_id = method;
        },
        (row: FinancialObject) => {
          financialObject(row.meta).property_id = method;
        },
      ]) {
        const fetcher = vi.fn<typeof fetch>((_url, init) =>
          Promise.resolve(response(operation, init ?? {}, mutate)),
        );
        await expect(
          createFinancialReferenceClient(fetcher, () => "csrf").read(
            scope(operation),
            input(operation),
          ),
        ).rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 200 });
      }
    },
  );
  it.each([
    { operation: "outside" },
    { operation: "capabilities", limit: 1 },
    { operation: "methods", limit: 101 },
    { operation: "methods", cursor: "bad" },
    { operation: "khrPreview", usd_amount_cents: 1.1 },
    { operation: "khrPreview", usd_amount_cents: 9000000000000001n },
    { operation: "khrPreview", usd_amount_cents: 1, markup_basis_points: 0 },
  ])(
    "TEST-FE-335 rejects finite-contract invalid input before dispatch $operation",
    async (request) => {
      const fetcher = vi.fn<typeof fetch>();
      await expect(
        createFinancialReferenceClient(fetcher).read(
          scope(request.operation),
          request as FinancialReferenceRequest,
        ),
      ).rejects.toMatchObject({ code: "INVALID_REQUEST" });
      expect(fetcher).not.toHaveBeenCalled();
    },
  );
  it("TEST-FE-336 captures original preview amount and scope before delayed responses", async () => {
    let complete: (() => void) | undefined;
    const request = {
      operation: "khrPreview" as const,
      usd_amount_cents: 1001,
    };
    const originalScope = scope("khrPreview");
    const fetcher = vi.fn<typeof fetch>(
      (_url, init) =>
        new Promise((resolve) => {
          complete = () => {
            resolve(response("khrPreview", init ?? {}));
          };
        }),
    );
    const pending = createFinancialReferenceClient(fetcher, () => "csrf").read(
      originalScope,
      request,
    );
    request.usd_amount_cents = 2000;
    originalScope.actorId = method;
    originalScope.propertyId = method;
    complete?.();
    const reply = await pending;
    expect(reply.actorId).toBe(actor);
    expect(financialObject(reply.data).usd_amount_cents).toBe(1001);
    expect(fetcher.mock.calls[0]?.[1]?.body).toBe('{"usd_amount_cents":1001}');
  });
  it.each(["abort", "fetch_deadline", "body_deadline"])(
    "TEST-FE-337 settles %s despite noncooperating work",
    async (kind) => {
      vi.useFakeTimers();
      const controller = new AbortController();
      const fetcher = vi.fn<typeof fetch>((_url, init) =>
        kind === "body_deadline"
          ? Promise.resolve(
              new Response(
                new ReadableStream({
                  pull: () =>
                    new Promise<never>(() => {
                      /* Deliberately noncooperating transport. */
                    }),
                }),
                {
                  headers: {
                    "Content-Type": "application/json",
                    "X-Request-ID":
                      new Headers(init?.headers).get("X-Request-ID") ?? "",
                  },
                },
              ),
            )
          : new Promise<never>(() => {
              /* Deliberately noncooperating transport. */
            }),
      );
      const pending = createFinancialReferenceClient(fetcher).read(
        scope("methods", controller.signal),
        input("methods"),
      );
      const rejected = expect(pending).rejects.toMatchObject({
        code: kind === "abort" ? "WORKSPACE_INVALIDATED" : "UNAVAILABLE",
      });
      if (kind === "abort") controller.abort();
      else await vi.advanceTimersByTimeAsync(FINANCIAL_DEADLINE_MS + 1);
      await rejected;
      expect(fetcher.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
    },
  );
  it.each(["declared", "streamed", "utf8", "duplicate", "correlation"])(
    "TEST-FE-338 rejects bounded malformed %s reply with local correlation",
    async (kind) => {
      const fetcher = vi.fn<typeof fetch>((_url, init) => {
        const requestId = new Headers(init?.headers).get("X-Request-ID") ?? "";
        const headers: Record<string, string> = {
          "Content-Type": "application/json",
          "X-Request-ID": kind === "correlation" ? method : requestId,
        };
        if (kind === "declared")
          headers["Content-Length"] = String(
            FINANCIAL_REFERENCE_REPLY_BYTES + 1,
          );
        const body =
          kind === "streamed"
            ? " ".repeat(FINANCIAL_REFERENCE_REPLY_BYTES + 1)
            : kind === "utf8"
              ? new Uint8Array([0xff])
              : kind === "duplicate"
                ? '{"data":[],"data":[]}'
                : "{}";
        return Promise.resolve(new Response(body, { headers }));
      });
      await expect(
        createFinancialReferenceClient(fetcher).read(
          scope("methods"),
          input("methods"),
        ),
      ).rejects.toMatchObject({
        code: ["declared", "streamed"].includes(kind)
          ? "RESPONSE_TOO_LARGE"
          : "INVALID_RESPONSE",
        status: 200,
        requestId: expect.any(String) as unknown,
      });
    },
  );
  it.each([
    "amount",
    "system",
    "payable",
    "unrounded",
    "markup",
    "source",
    "status",
  ])(
    "TEST-FE-339 rejects inconsistent provisional preview %s",
    async (field) => {
      const mutations: Record<string, FinancialObject> = {
        amount: { usd_amount_cents: 1002 },
        system: { system_rate_khr_per_usd: 4082 },
        payable: { payable_khr_amount: 40870 },
        unrounded: { unrounded_khr_amount: "40870.84" },
        markup: { markup_basis_points: 0 },
        source: { automatic_source_unavailable: true },
        status: { provisional: false },
      };
      const fetcher = vi.fn<typeof fetch>((_url, init) =>
        Promise.resolve(
          response("khrPreview", init ?? {}, (row) =>
            Object.assign(financialObject(row.data), mutations[field]),
          ),
        ),
      );
      await expect(
        createFinancialReferenceClient(fetcher, () => "csrf").read(
          scope("khrPreview"),
          input("khrPreview"),
        ),
      ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    },
  );
  it("TEST-FE-340 accepts exact boundary money and long legacy method labels without truncation", async () => {
    const preview = vi.fn<typeof fetch>((_url, init) =>
      Promise.resolve(
        response("khrPreview", init ?? {}, (row) =>
          Object.assign(financialObject(row.data), {
            usd_amount_cents: 9000000000000000n,
            reference_rate_khr_per_usd: "0.000001",
            system_rate_khr_per_usd: 1,
            unrounded_khr_amount: "90000000000000.00",
            payable_khr_amount: 90000000000000,
          }),
        ),
      ),
    );
    const value = await createFinancialReferenceClient(
      preview,
      () => "csrf",
    ).read(scope("khrPreview"), {
      operation: "khrPreview",
      usd_amount_cents: 9000000000000000n,
    });
    expect(financialObject(value.data).payable_khr_amount).toBe(90000000000000);
    const label = "Legacy " + "x".repeat(10000);
    const methods = vi.fn<typeof fetch>((_url, init) =>
      Promise.resolve(
        response("methods", init ?? {}, (row) => {
          if (Array.isArray(row.data))
            financialObject(row.data[0]).display_name = label;
        }),
      ),
    );
    const reply = await createFinancialReferenceClient(methods).read(
      scope("methods"),
      input("methods"),
    );
    expect(
      Array.isArray(reply.data) && financialObject(reply.data[0]).display_name,
    ).toBe(label);
  });
  it.each([
    "valid",
    "wrong_cursor",
    "duplicate",
    "wrong_method_property",
    "unknown_grant",
  ])(
    "TEST-FE-341 validates stable pages and exact capabilities %s",
    async (mode) => {
      const operation = mode === "unknown_grant" ? "capabilities" : "methods";
      const fetcher = vi.fn<typeof fetch>((_url, init) =>
        Promise.resolve(
          response(operation, init ?? {}, (row) => {
            if (operation === "capabilities") {
              financialObject(financialObject(row.data).capabilities).admin =
                true;
              return;
            }
            if (mode === "wrong_method_property" && Array.isArray(row.data))
              financialObject(row.data[0]).property_id = method;
            if (mode === "duplicate" && Array.isArray(row.data))
              row.data.push(row.data[0] ?? null);
            row.page = {
              limit: 1,
              next_cursor: mode === "wrong_cursor" ? property : method,
            };
          }),
        ),
      );
      const pending = createFinancialReferenceClient(fetcher).read(
        scope(operation),
        operation === "capabilities" ? { operation } : { operation, limit: 1 },
      );
      if (mode === "valid")
        expect((await pending).page).toEqual({ limit: 1, nextCursor: method });
      else
        await expect(pending).rejects.toMatchObject({
          code: "INVALID_RESPONSE",
        });
    },
  );
  it("TEST-FE-342 distinguishes automatic unavailability and validates explicit manual echo", async () => {
    const selected = {
      reference_rate_khr_per_usd: "4062",
      source_reference: "Explicit manual quote",
      applicable_at: "2026-05-01T00:00:00Z",
      fallback_reason: "Approved source unavailable",
    };
    const fetcher = vi.fn<typeof fetch>((_url, init) =>
      Promise.resolve(
        response("khrPreview", init ?? {}, (row) => {
          row.data = {
            property_id: property,
            usd_amount_cents: 1001,
            provisional: true,
            status: "source_unavailable",
            manual_fallback_allowed: true,
          };
        }),
      ),
    );
    const api = createFinancialReferenceClient(fetcher, () => "csrf");
    const reply = await api.read(scope("khrPreview"), input("khrPreview"));
    expect(financialObject(reply.data).manual_fallback_allowed).toBe(true);
    await expect(
      api.read(scope("khrPreview"), {
        operation: "khrPreview",
        usd_amount_cents: 1001,
        manual_reference: selected,
      }),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    const manualFetcher = vi.fn<typeof fetch>((_url, init) =>
      Promise.resolve(
        response("khrPreview", init ?? {}, (row) =>
          Object.assign(financialObject(row.data), selected, {
            rate_source: "ABA_EQUIVALENT_MANUAL",
            automatic_source_unavailable: true,
          }),
        ),
      ),
    );
    const manualReply = await createFinancialReferenceClient(
      manualFetcher,
      () => "csrf",
    ).read(scope("khrPreview"), {
      operation: "khrPreview",
      usd_amount_cents: 1001,
      manual_reference: selected,
    });
    expect(financialObject(manualReply.data).fallback_reason).toBe(
      selected.fallback_reason,
    );
  });
  it("TEST-FE-343 canonical HTTP rejection keeps safe local status and request correlation", async () => {
    const fetcher = vi.fn<typeof fetch>((_url, init) => {
      const requestId = new Headers(init?.headers).get("X-Request-ID") ?? "";
      return Promise.resolve(
        new Response(
          JSON.stringify({
            error: { code: "FORBIDDEN", message: "private upstream text" },
            meta: { request_id: requestId },
          }),
          {
            status: 403,
            headers: {
              "Content-Type": "application/json",
              "X-Request-ID": requestId,
            },
          },
        ),
      );
    });
    const error = await createFinancialReferenceClient(fetcher)
      .read(scope("methods"), input("methods"))
      .catch((value: unknown) => value);
    expect(error).toMatchObject({
      code: "HTTP_REJECTION",
      status: 403,
      requestId: expect.any(String) as unknown,
    });
    expect(error).toBeInstanceOf(Error);
    if (!(error instanceof Error))
      throw new Error("Expected safe reference error");
    expect(error.message).not.toContain("private upstream");
  });
  it.each(["same", "earlier", "later"])(
    "TEST-FE-347 compares normalized requested cursor against returned page identities %s",
    async (mode) => {
      const cursor = "00000000-0000-4000-8000-0000000000AA";
      const returned =
        mode === "same"
          ? cursor.toLowerCase()
          : mode === "earlier"
            ? "00000000-0000-4000-8000-0000000000a9"
            : "00000000-0000-4000-8000-0000000000ab";
      const fetcher = vi.fn<typeof fetch>((_url, init) =>
        Promise.resolve(
          response("methods", init ?? {}, (row) => {
            if (Array.isArray(row.data))
              financialObject(row.data[0]).id = returned;
          }),
        ),
      );
      const pending = createFinancialReferenceClient(fetcher).read(
        scope("methods"),
        { operation: "methods", cursor },
      );
      if (mode === "later") expect((await pending).page?.nextCursor).toBeNull();
      else
        await expect(pending).rejects.toMatchObject({
          code: "INVALID_RESPONSE",
        });
      expect(fetcher.mock.calls[0]?.[0]).toBe(
        `/api/v1/properties/${property}/payment-methods?cursor=${cursor.toLowerCase()}`,
      );
    },
  );
});
