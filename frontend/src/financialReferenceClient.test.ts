import {
  ids as contextIds,
  fixture as financialFixture,
} from "./test/financialFixtures";
import { PaymentReversalContextSequence } from "./paymentReversalContextSequence";
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
            capabilities: { ...permissions },
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
          ? { property_id: property, capabilities: { ...permissions } }
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
              expect(permissions).not.toHaveProperty("admin");
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

describe("reference review correction1", () => {
  it.each([
    "Synthetic\nreference",
    "Cash\tcounter",
    "😀".repeat(300),
    "😀".repeat(500),
    "\ufeffReference\ufeff",
  ])(
    "TEST-FE-348 preserves backend-valid evidence %s through automatic and manual preview",
    async (value) => {
      for (const manualInput of [false, true]) {
        const selected = {
          reference_rate_khr_per_usd: "4062.000000",
          source_reference: value,
          applicable_at: "2026-05-01T00:00:00Z",
          fallback_reason: value,
        };
        const fetcher = vi.fn<typeof fetch>((_url, init) =>
          Promise.resolve(
            response("khrPreview", init ?? {}, (row) => {
              Object.assign(financialObject(row.data), {
                source_reference: value,
                fallback_reason: manualInput ? value : null,
                rate_source: manualInput
                  ? "ABA_EQUIVALENT_MANUAL"
                  : "ABA_AUTOMATIC",
                automatic_source_unavailable: manualInput,
              });
            }),
          ),
        );
        const result = await createFinancialReferenceClient(
          fetcher,
          () => "csrf",
        ).read(scope("khrPreview"), {
          operation: "khrPreview",
          usd_amount_cents: 1001,
          ...(manualInput ? { manual_reference: selected } : {}),
        });
        expect(financialObject(result.data).source_reference).toBe(value);
        expect(financialObject(result.data).fallback_reason).toBe(
          manualInput ? value : null,
        );
        expect(fetcher).toHaveBeenCalledOnce();
      }
    },
  );
  it.each(["workspaces", "methods"] as const)(
    "TEST-FE-349 preserves whole configured %s labels",
    async (operation) => {
      const label = "Synthetic\nCash\tcounter " + "😀".repeat(700);
      const fetcher = vi.fn<typeof fetch>((_url, init) =>
        Promise.resolve(
          response(operation, init ?? {}, (row) => {
            if (!Array.isArray(row.data)) throw new Error();
            const item = financialObject(row.data[0]);
            item[operation === "workspaces" ? "name" : "display_name"] = label;
            if (operation === "methods") item.code = "Cash\tcounter";
          }),
        ),
      );
      const result = await createFinancialReferenceClient(fetcher).read(
        scope(operation),
        { operation },
      );
      if (!Array.isArray(result.data)) throw new Error();
      expect(
        financialObject(result.data[0])[
          operation === "workspaces" ? "name" : "display_name"
        ],
      ).toBe(label);
    },
  );
  it.each([
    "😀".repeat(501),
    "\u001cReference",
    "Reference\u001f",
    "Reference\0source",
    "\ud800",
  ])(
    "TEST-FE-350 rejects evidence outside the backend contract %s",
    async (value) => {
      const fetcher = vi.fn<typeof fetch>();
      await expect(
        createFinancialReferenceClient(fetcher, () => "csrf").read(
          scope("khrPreview"),
          {
            operation: "khrPreview",
            usd_amount_cents: 1001,
            manual_reference: {
              reference_rate_khr_per_usd: "4062.000000",
              source_reference: value,
              applicable_at: "2026-05-01T00:00:00Z",
              fallback_reason: "outage",
            },
          },
        ),
      ).rejects.toMatchObject({ code: "INVALID_REQUEST" });
      expect(fetcher).not.toHaveBeenCalled();
    },
  );
  it.each(["abort", "deadline"])(
    "TEST-FE-351 cancels a body arriving after %s",
    async (kind) => {
      vi.useFakeTimers();
      const controller = new AbortController(),
        cancel = vi.fn();
      let resolve: ((value: Response) => void) | undefined;
      let streamController:
        | ReadableStreamDefaultController<Uint8Array>
        | undefined;
      const fetcher = vi.fn<typeof fetch>(
        () =>
          new Promise<Response>((done) => {
            resolve = done;
          }),
      );
      const pending = createFinancialReferenceClient(fetcher).read(
        scope("methods", controller.signal),
        { operation: "methods" },
      );
      const rejected = expect(pending).rejects.toMatchObject({
        code: kind === "abort" ? "WORKSPACE_INVALIDATED" : "UNAVAILABLE",
      });
      if (kind === "abort") controller.abort();
      else await vi.advanceTimersByTimeAsync(FINANCIAL_DEADLINE_MS + 1);
      await rejected;
      if (!resolve) throw new Error();
      resolve(
        new Response(
          new ReadableStream<Uint8Array>({
            start(value) {
              streamController = value;
            },
            cancel,
          }),
        ),
      );
      await Promise.resolve();
      await Promise.resolve();
      expect(cancel).toHaveBeenCalledOnce();
      expect(() =>
        streamController?.enqueue(
          new Uint8Array(FINANCIAL_REFERENCE_REPLY_BYTES + 1),
        ),
      ).toThrow();
      expect(fetcher).toHaveBeenCalledOnce();
    },
  );
  it.each(["correlation", "content_type", "content_length"])(
    "TEST-FE-352 cancels a body rejected before reader acquisition for %s",
    async (kind) => {
      const cancel = vi.fn();
      const fetcher = vi.fn<typeof fetch>((_url, init) =>
        Promise.resolve(
          new Response(new ReadableStream<Uint8Array>({ cancel }), {
            headers: {
              "Content-Type":
                kind === "content_type" ? "text/plain" : "application/json",
              "X-Request-ID":
                kind === "correlation"
                  ? "wrong"
                  : (new Headers(init?.headers).get("X-Request-ID") ?? ""),
              ...(kind === "content_length"
                ? {
                    "Content-Length": (
                      FINANCIAL_REFERENCE_REPLY_BYTES + 1
                    ).toString(),
                  }
                : {}),
            },
          }),
        ),
      );
      await expect(
        createFinancialReferenceClient(fetcher).read(scope("methods"), {
          operation: "methods",
        }),
      ).rejects.toMatchObject({
        code:
          kind === "content_length" ? "RESPONSE_TOO_LARGE" : "INVALID_RESPONSE",
      });
      expect(cancel).toHaveBeenCalledOnce();
    },
  );
});

const contextScope = () => ({
  actorId: contextIds.actor,
  propertyId: contextIds.property,
  signal: new AbortController().signal,
});
const contextInput = (
  view: "impact" | "result" = "impact",
): FinancialReferenceRequest => ({
  operation: "paymentReversalContext",
  payment_id: contextIds.payment,
  view,
});
const contextRevision = "a".repeat(64);
const contextEvent = (
  ordinal: number,
  kind: string,
  identity: string,
  sourceKind: string,
  source: string,
  targetKind: string,
  target: string,
): FinancialObject => ({
  ordinal,
  kind,
  id: identity,
  data: {
    source_kind: sourceKind,
    source_id: source,
    target_kind: targetKind,
    target_id: target,
    amount_usd_cents: 100,
    occurred_at: "2026-09-01T05:00:00Z",
  },
});
function contextEvents(): FinancialObject[] {
  return [
    contextEvent(
      1,
      "ALLOCATION",
      contextIds.allocation,
      "PAYMENT",
      contextIds.payment,
      "INVOICE",
      contextIds.invoice,
    ),
    contextEvent(
      2,
      "ALLOCATION_LINE",
      contextIds.event,
      "ALLOCATION",
      contextIds.allocation,
      "INVOICE_LINE",
      contextIds.other,
    ),
    contextEvent(
      3,
      "CREDIT",
      contextIds.credit,
      "PAYMENT",
      contextIds.payment,
      "CREDIT",
      contextIds.credit,
    ),
    contextEvent(
      4,
      "CREDIT_APPLICATION",
      contextIds.application,
      "CREDIT",
      contextIds.credit,
      "LATE_PAYMENT_CHARGE",
      contextIds.invoice,
    ),
    contextEvent(
      5,
      "CREDIT_APPLICATION_LINE",
      contextIds.event,
      "CREDIT_APPLICATION",
      contextIds.application,
      "LATE_PAYMENT_CHARGE",
      contextIds.invoice,
    ),
    contextEvent(
      6,
      "DEPOSIT_RECEIPT",
      contextIds.receipt,
      "PAYMENT",
      contextIds.payment,
      "DEPOSIT",
      contextIds.other,
    ),
    contextEvent(
      7,
      "DEPOSIT_DISPOSITION",
      contextIds.event,
      "DEPOSIT",
      contextIds.other,
      "DEPOSIT",
      contextIds.other,
    ),
    {
      ordinal: 8,
      kind: "REFUND",
      id: contextIds.refund,
      data: {
        source_kind: "CREDIT",
        source_id: contextIds.credit,
        amount_usd_cents: 100,
        unreturned_usd_cents: 50,
        refund_number: "RF\tOriginal\n😀",
        occurred_at: "2026-09-01T05:00:00Z",
      },
    },
  ];
}
function contextResults(): FinancialObject[] {
  return [
    {
      ordinal: 1,
      kind: "INVOICE",
      id: contextIds.invoice,
      data: {
        invoice_number: "INV\tOriginal\n😀",
        status: "PARTIALLY_PAID",
        outstanding_usd_cents: 9007199254740993n,
      },
    },
    {
      ordinal: 2,
      kind: "LATE_PAYMENT_CHARGE",
      id: contextIds.other,
      data: {
        source_invoice_id: contextIds.invoice,
        original_usd_cents: 100,
        reversed: false,
        adjusted_obligation_usd_cents: 90,
        remaining_balance_usd_cents: 80,
      },
    },
    {
      ordinal: 3,
      kind: "CREDIT",
      id: contextIds.credit,
      data: {
        recognized_usd_cents: 100,
        applied_usd_cents: 10,
        refunded_usd_cents: 20,
        reversed_usd_cents: 0,
        available_usd_cents: 70,
      },
    },
    {
      ordinal: 4,
      kind: "DEPOSIT",
      id: contextIds.event,
      data: {
        deposit_type: "PET",
        held_usd_cents: 70,
        received_usd_cents: 100,
        disposed_usd_cents: 20,
        refunded_usd_cents: 10,
      },
    },
  ];
}
function contextEnvelope(
  view: "impact" | "result" = "impact",
): FinancialObject {
  return {
    data: {
      payment_resource: financialFixture("paymentGet").data,
      view,
      revision: contextRevision,
      items: view === "impact" ? contextEvents() : contextResults(),
    },
    meta: {
      actor_id: contextIds.actor,
      property_id: contextIds.property,
      request_id: "",
    },
    page: { limit: 50, next_cursor: null },
  };
}
function contextResponse(
  init: RequestInit,
  envelope: FinancialObject,
): Response {
  const requestId = new Headers(init.headers).get("X-Request-ID") ?? "";
  financialObject(envelope.meta).request_id = requestId;
  return new Response(
    stringifyFinancialJson(envelope, FINANCIAL_REFERENCE_REPLY_BYTES),
    {
      headers: {
        "Content-Type": "application/json",
        "X-Request-ID": requestId,
      },
    },
  );
}
describe("Payment reversal context", () => {
  it.each(["impact", "result"] as const)(
    "TEST-FE-357 maps %s to the exact read-only Property and Payment route",
    async (view) => {
      const fetcher = vi.fn<typeof fetch>((url, init) => {
        expect(url).toBe(
          `/api/v1/properties/${contextIds.property}/payments/${contextIds.payment}/reversal-context?view=${view}`,
        );
        expect(init?.method).toBe("GET");
        expect(init?.body).toBeUndefined();
        expect(init?.cache).toBe("no-store");
        const headers = new Headers(init?.headers);
        expect(headers.get("Idempotency-Key")).toBeNull();
        expect(headers.get("X-CSRF-Token")).toBeNull();
        expect(headers.get("X-Financial-Property-ID")).toBe(
          contextIds.property,
        );
        return Promise.resolve(
          contextResponse(init ?? {}, contextEnvelope(view)),
        );
      });
      const csrf = vi.fn(() => "unused");
      const reply = await createFinancialReferenceClient(fetcher, csrf).read(
        contextScope(),
        contextInput(view),
      );
      expect(reply.page).toEqual({ limit: 50, nextCursor: null });
      expect(fetcher).toHaveBeenCalledTimes(1);
      expect(csrf).not.toHaveBeenCalled();
      const sequence = new PaymentReversalContextSequence(
        contextIds.actor,
        contextIds.property,
        contextIds.payment,
        view,
      );
      sequence.append(reply);
      expect(sequence.complete).toBe(true);
    },
  );
  it("TEST-FE-358 preserves exact large result amounts and whole immutable labels", async () => {
    const reply = await createFinancialReferenceClient((_url, init) =>
      Promise.resolve(contextResponse(init ?? {}, contextEnvelope("result"))),
    ).read(contextScope(), contextInput("result"));
    const rows = financialObject(reply.data).items as FinancialObject[];
    expect(financialObject(rows[0]?.data).outstanding_usd_cents).toBe(
      9007199254740993n,
    );
    expect(financialObject(rows[0]?.data).invoice_number).toBe(
      "INV\tOriginal\n😀",
    );
  });
  it.each([
    { payment_id: "x" },
    { payment_id: "00000000-0000-0000-0000-000000000000" },
    { view: "all" },
    { limit: 0 },
    { limit: 101 },
    { limit: 1.5 },
    { limit: "1" },
    { cursor: "" },
    { cursor: `${"A".repeat(64)}:1:${contextIds.event}` },
    { cursor: `${contextRevision}:0:${contextIds.event}` },
    { view: "result", cursor: `${contextRevision}:5:${contextIds.event}` },
    { idempotency_key: contextIds.key },
    { unknown: true },
  ])(
    "TEST-FE-359 rejects invalid context requests before transmission %j",
    async (invalid) => {
      const fetcher = vi.fn<typeof fetch>();
      await expect(
        createFinancialReferenceClient(fetcher).read(contextScope(), {
          ...contextInput(),
          ...invalid,
        } as FinancialReferenceRequest),
      ).rejects.toMatchObject({ code: "INVALID_REQUEST" });
      expect(fetcher).not.toHaveBeenCalled();
    },
  );
  const corruptions: [string, (row: FinancialObject) => void][] = [
    [
      "actor",
      (row) => {
        financialObject(row.meta).actor_id = contextIds.other;
      },
    ],
    [
      "property",
      (row) => {
        financialObject(row.meta).property_id = contextIds.other;
      },
    ],
    [
      "payment",
      (row) => {
        financialObject(
          financialObject(financialObject(row.data).payment_resource).payment,
        ).id = contextIds.other;
      },
    ],
    [
      "source property",
      (row) => {
        financialObject(
          financialObject(financialObject(row.data).payment_resource).payment,
        ).property_id = contextIds.other;
      },
    ],
    [
      "revision",
      (row) => {
        financialObject(row.data).revision = "A".repeat(64);
      },
    ],
    [
      "view",
      (row) => {
        financialObject(row.data).view = "result";
      },
    ],
    [
      "unexpected data",
      (row) => {
        financialObject(row.data).secret_command = "x";
      },
    ],
    [
      "page limit",
      (row) => {
        financialObject(row.page).limit = 1;
      },
    ],
    [
      "next cursor",
      (row) => {
        financialObject(row.page).next_cursor = "x";
      },
    ],
    [
      "order",
      (row) => {
        (financialObject(row.data).items as FinancialObject[]).reverse();
      },
    ],
    [
      "duplicate",
      (row) => {
        const list = financialObject(row.data).items as FinancialObject[];
        list[1] = list[0] ?? {};
      },
    ],
    [
      "kind",
      (row) => {
        const list = financialObject(row.data).items as FinancialObject[];
        if (list[0]) list[0].kind = "REFUND";
      },
    ],
    [
      "wrong direct source",
      (row) => {
        const list = financialObject(row.data).items as FinancialObject[];
        financialObject(list[0]?.data).source_id = contextIds.other;
      },
    ],
    [
      "unreturned zero",
      (row) => {
        const list = financialObject(row.data).items as FinancialObject[];
        financialObject(list[7]?.data).unreturned_usd_cents = 0;
      },
    ],
    [
      "unreturned overflow",
      (row) => {
        const list = financialObject(row.data).items as FinancialObject[];
        financialObject(list[7]?.data).unreturned_usd_cents = 101;
      },
    ],
    [
      "wrong receipt target",
      (row) => {
        const list = financialObject(row.data).items as FinancialObject[];
        financialObject(list[5]?.data).target_kind = "INVOICE";
      },
    ],
    [
      "negative amount",
      (row) => {
        const list = financialObject(row.data).items as FinancialObject[];
        financialObject(list[0]?.data).amount_usd_cents = -1;
      },
    ],
    [
      "bad timestamp",
      (row) => {
        const list = financialObject(row.data).items as FinancialObject[];
        financialObject(list[0]?.data).occurred_at = "yesterday";
      },
    ],
  ];
  it.each(corruptions)(
    "TEST-FE-360 rejects malformed or foreign response: %s",
    async (_name, corrupt) => {
      const envelope = contextEnvelope();
      corrupt(envelope);
      await expect(
        createFinancialReferenceClient((_url, init) =>
          Promise.resolve(contextResponse(init ?? {}, envelope)),
        ).read(contextScope(), contextInput()),
      ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    },
  );
  it.each([
    "credit total",
    "deposit total",
    "charge balance",
    "charge reversed",
    "invoice negative",
    "void invoice balance",
    "future deposit kind",
  ])("TEST-FE-360 rejects impossible current result: %s", async (fault) => {
    const envelope = contextEnvelope("result"),
      rows = financialObject(envelope.data).items as FinancialObject[];
    if (fault === "credit total")
      financialObject(rows[2]?.data).available_usd_cents = 71;
    else if (fault === "deposit total")
      financialObject(rows[3]?.data).held_usd_cents = 71;
    else if (fault === "charge balance")
      financialObject(rows[1]?.data).remaining_balance_usd_cents = 91;
    else if (fault === "charge reversed")
      financialObject(rows[1]?.data).reversed = true;
    else if (fault === "invoice negative")
      financialObject(rows[0]?.data).outstanding_usd_cents = -1;
    else if (fault === "void invoice balance")
      financialObject(rows[0]?.data).status = "VOID";
    else financialObject(rows[3]?.data).deposit_type = "RESERVATION";
    await expect(
      createFinancialReferenceClient((_url, init) =>
        Promise.resolve(contextResponse(init ?? {}, envelope)),
      ).read(contextScope(), contextInput("result")),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });
  it("TEST-FE-361 consumes complete cross-page dependencies and refuses stale continuation", async () => {
    const all = contextEvents(),
      first = contextEnvelope(),
      next = `${contextRevision}:4:${contextIds.application}`;
    financialObject(first.data).items = all.slice(0, 4);
    first.page = { limit: 4, next_cursor: next };
    const last = contextEnvelope();
    financialObject(last.data).items = all.slice(4);
    last.page = { limit: 4, next_cursor: null };
    const scope = contextScope(),
      sequence = new PaymentReversalContextSequence(
        contextIds.actor,
        contextIds.property,
        contextIds.payment,
        "impact",
      );
    const client = createFinancialReferenceClient((url, init) =>
      Promise.resolve(
        contextResponse(
          init ?? {},
          typeof url === "string" && url.includes("cursor=") ? last : first,
        ),
      ),
    );
    sequence.append(
      await client.read(scope, {
        ...contextInput(),
        limit: 4,
      } as FinancialReferenceRequest),
    );
    expect(sequence.complete).toBe(false);
    expect(sequence.nextCursor).toBe(next);
    sequence.append(
      await client.read(scope, {
        ...contextInput(),
        limit: 4,
        cursor: next,
      } as FinancialReferenceRequest),
      next,
    );
    expect(sequence.complete).toBe(true);
    financialObject(last.data).revision = "b".repeat(64);
    await expect(
      client.read(scope, {
        ...contextInput(),
        limit: 4,
        cursor: next,
      } as FinancialReferenceRequest),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });
  it.each([
    "skipped page",
    "different actor",
    "different property",
    "different payment",
    "different view",
    "duplicate final",
  ])("TEST-FE-362 sequence cannot claim completeness for %s", async (fault) => {
    const reply = await createFinancialReferenceClient((_url, init) =>
      Promise.resolve(contextResponse(init ?? {}, contextEnvelope())),
    ).read(contextScope(), contextInput());
    const sequence = new PaymentReversalContextSequence(
      contextIds.actor,
      contextIds.property,
      fault === "different payment" ? contextIds.other : contextIds.payment,
      fault === "different view" ? "result" : "impact",
    );
    if (fault === "different actor") reply.actorId = contextIds.other;
    if (fault === "different property") reply.propertyId = contextIds.other;
    if (fault === "duplicate final") sequence.append(reply);
    expect(() => {
      sequence.append(
        reply,
        fault === "skipped page"
          ? `${contextRevision}:1:${contextIds.allocation}`
          : null,
      );
    }).toThrow();
    expect(sequence.complete).toBe(false);
  });
  it.each([
    "orphan",
    "line total",
    "missing detail",
    "charge mismatch",
    "missing deposit",
  ])("TEST-FE-363 complete graph rejects %s", async (fault) => {
    const envelope = contextEnvelope(),
      rows = financialObject(envelope.data).items as FinancialObject[];
    if (fault === "orphan")
      financialObject(rows[1]?.data).source_id = contextIds.other;
    else if (fault === "line total")
      financialObject(rows[1]?.data).amount_usd_cents = 99;
    else if (fault === "missing detail") rows.splice(1, 1);
    else if (fault === "charge mismatch")
      financialObject(rows[4]?.data).target_id = contextIds.other;
    else
      financialObject(rows[6]?.data).source_id = financialObject(
        rows[6]?.data,
      ).target_id = contextIds.credit;
    const reply = await createFinancialReferenceClient((_url, init) =>
      Promise.resolve(contextResponse(init ?? {}, envelope)),
    ).read(contextScope(), contextInput());
    const sequence = new PaymentReversalContextSequence(
      contextIds.actor,
      contextIds.property,
      contextIds.payment,
      "impact",
    );
    expect(() => {
      sequence.append(reply);
    }).toThrow();
    expect(sequence.complete).toBe(false);
  });
  it("TEST-FE-364 rejects invalidated actor/Property context without dispatch", async () => {
    const controller = new AbortController(),
      fetcher = vi.fn<typeof fetch>();
    controller.abort();
    await expect(
      createFinancialReferenceClient(fetcher).read(
        { ...contextScope(), signal: controller.signal },
        contextInput(),
      ),
    ).rejects.toMatchObject({ code: "WORKSPACE_INVALIDATED" });
    expect(fetcher).not.toHaveBeenCalled();
  });
});

function contextPair(view: "impact" | "result") {
  const firstId = "60000000-0000-4000-8000-000000000001",
    secondId = "60000000-0000-4000-8000-000000000002",
    cursor = `${contextRevision}:3:${firstId}`;
  const client = createFinancialReferenceClient((url, init) => {
    if (typeof url !== "string")
      throw new Error("Finite synthetic URL required");
    const envelope = contextEnvelope(view),
      identity = url.includes("cursor=") ? secondId : firstId,
      headers = new Headers(init?.headers);
    financialObject(envelope.meta).actor_id = headers.get("X-Billing-Actor-ID");
    financialObject(envelope.data).items = [
      view === "impact"
        ? contextEvent(
            3,
            "CREDIT",
            identity,
            "PAYMENT",
            contextIds.payment,
            "CREDIT",
            identity,
          )
        : {
            ordinal: 3,
            kind: "CREDIT",
            id: identity,
            data: {
              recognized_usd_cents: 100,
              applied_usd_cents: 0,
              refunded_usd_cents: 0,
              reversed_usd_cents: 0,
              available_usd_cents: 100,
            },
          },
    ];
    envelope.page = {
      limit: 1,
      next_cursor: identity === firstId ? cursor : null,
    };
    return Promise.resolve(contextResponse(init ?? {}, envelope));
  });
  const input: FinancialReferenceRequest = {
    operation: "paymentReversalContext",
    payment_id: contextIds.payment,
    view,
    limit: 1,
  };
  const sequence = () =>
    new PaymentReversalContextSequence(
      contextIds.actor,
      contextIds.property,
      contextIds.payment,
      view,
    );
  return { client, input, cursor, sequence };
}

describe("Payment reversal context correction1", () => {
  it.each(["impact", "result"] as const)(
    "TEST-FE-367 rejects actual %s continuation first with omitted or falsified cursor",
    async (view) => {
      const pair = contextPair(view);
      const last = await pair.client.read(contextScope(), {
        ...pair.input,
        cursor: pair.cursor,
      });
      for (const cursor of [undefined, null, pair.cursor]) {
        const sequence = pair.sequence();
        expect(() => {
          sequence.append(last, cursor);
        }).toThrow();
        expect(sequence.complete).toBe(false);
      }
    },
  );
  it.each(["impact", "result"] as const)(
    "TEST-FE-367 consumes real %s request provenance without caller cursor authority",
    async (view) => {
      const pair = contextPair(view),
        sequence = pair.sequence();
      sequence.append(await pair.client.read(contextScope(), pair.input));
      expect(sequence.complete).toBe(false);
      expect(sequence.nextCursor).toBe(pair.cursor);
      sequence.append(
        await pair.client.read(contextScope(), {
          ...pair.input,
          cursor: pair.cursor,
        }),
      );
      expect(sequence.complete).toBe(true);
    },
  );
  it.each(["impact", "result"] as const)(
    "TEST-FE-368 rejects copied %s reply provenance even with plausible data",
    async (view) => {
      const pair = contextPair(view),
        sequence = pair.sequence();
      const first = await pair.client.read(contextScope(), pair.input);
      expect(() => {
        sequence.append({ ...first });
      }).toThrow();
      expect(sequence.complete).toBe(false);
    },
  );
  it.each(["actorId", "propertyId", "paymentId", "view"] as const)(
    "TEST-FE-369 protects %s at runtime before, during and after completion",
    async (field) => {
      const pair = contextPair("result");
      for (const stage of [0, 1, 2]) {
        const sequence = pair.sequence(),
          original = sequence[field];
        if (stage > 0)
          sequence.append(await pair.client.read(contextScope(), pair.input));
        if (stage > 1)
          sequence.append(
            await pair.client.read(contextScope(), {
              ...pair.input,
              cursor: pair.cursor,
            }),
            pair.cursor,
          );
        expect(() =>
          Object.assign(sequence, {
            [field]: field === "view" ? "impact" : contextIds.other,
          }),
        ).toThrow();
        expect(() =>
          Object.defineProperty(sequence, field, { value: "forged" }),
        ).toThrow();
        expect(sequence[field]).toBe(original);
        expect(sequence.complete).toBe(stage === 2);
      }
    },
  );
  it.each(["impact", "result"] as const)(
    "TEST-FE-370 rejects actor bridging during %s continuation",
    async (view) => {
      const pair = contextPair(view),
        sequence = pair.sequence();
      sequence.append(await pair.client.read(contextScope(), pair.input));
      try {
        Object.assign(sequence, { actorId: contextIds.other });
      } catch {
        /* Mutation must fail. */
      }
      const foreign = await pair.client.read(
        { ...contextScope(), actorId: contextIds.other },
        { ...pair.input, cursor: pair.cursor },
      );
      expect(() => {
        sequence.append(foreign, pair.cursor);
      }).toThrow();
      expect(sequence.complete).toBe(false);
    },
  );
  it.each(["actorId", "propertyId", "requestId", "page", "data"] as const)(
    "TEST-FE-371 rejects reply %s changed after validation",
    async (field) => {
      const pair = contextPair("result"),
        sequence = pair.sequence();
      const first = await pair.client.read(contextScope(), pair.input);
      if (field === "page") {
        if (!first.page) throw new Error("Synthetic page required");
        first.page.nextCursor = null;
      } else if (field === "data") {
        const rows = financialObject(first.data).items as FinancialObject[];
        financialObject(rows[0]?.data).recognized_usd_cents = 101;
        financialObject(rows[0]?.data).available_usd_cents = 101;
      } else first[field] = contextIds.other;
      expect(() => {
        sequence.append(first);
      }).toThrow();
      expect(sequence.complete).toBe(false);
    },
  );
});
