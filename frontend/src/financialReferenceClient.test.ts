import { FinancialActionContextSequence } from "./financialActionContextSequence";
import {
  FINANCIAL_ACTION_PURPOSES,
  type FinancialActionContextInput,
} from "./financialActionContext";
import {
  actionContextFixtures,
  type FinancialActionFixture,
} from "./test/financialActionContextFixtures";
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

function actionCopy(sample: FinancialActionFixture): FinancialActionFixture {
  return structuredClone(sample);
}
function actionResponse(
  sample: FinancialActionFixture,
  init: RequestInit,
  mutate?: (envelope: FinancialObject) => void,
  status = 200,
): Response {
  const requestId = new Headers(init.headers).get("X-Request-ID") ?? "";
  const envelope: FinancialObject = {
    data: actionCopy(sample).data,
    page: { ...sample.page },
    meta: {
      actor_id: sample.actorId,
      property_id: sample.propertyId,
      request_id: requestId,
    },
  };
  mutate?.(envelope);
  return new Response(
    stringifyFinancialJson(envelope, FINANCIAL_REFERENCE_REPLY_BYTES),
    {
      status,
      headers: {
        "Content-Type": "application/json",
        "X-Request-ID": requestId,
      },
    },
  );
}
function actionClient(
  sample: FinancialActionFixture,
  mutate?: (envelope: FinancialObject) => void,
) {
  const fetcher = vi.fn<typeof fetch>((_url, init) =>
    Promise.resolve(actionResponse(sample, init ?? {}, mutate)),
  );
  return { fetcher, client: createFinancialReferenceClient(fetcher) };
}
function actionScope(
  sample: FinancialActionFixture,
  signal = new AbortController().signal,
) {
  return { actorId: sample.actorId, propertyId: sample.propertyId, signal };
}
function actionSequence(sample: FinancialActionFixture) {
  return new FinancialActionContextSequence(
    sample.actorId,
    sample.propertyId,
    sample.request,
  );
}
const actionCases = actionContextFixtures.map((sample, index) => ({
  sample,
  name: `${index.toString()} ${sample.request.purpose}`,
}));
function postingSample(): FinancialActionFixture {
  const original = actionContextFixtures.find(
    (sample) =>
      sample.request.purpose === "allocation" &&
      sample.request.target_kind === "INVOICE",
  );
  if (!original) throw new Error("Synthetic Invoice fixture missing");
  const sample = actionCopy(original);
  sample.request.limit = 1;
  sample.page.limit = 1;
  return sample;
}
describe("selected financial action context", () => {
  it.each(actionCases)(
    "TEST-FE-374 accepts actual synthetic PostgreSQL context $name and preserves read-only routing",
    async ({ sample }) => {
      const { client, fetcher } = actionClient(sample);
      const reply = await client.read(actionScope(sample), sample.request);
      const sequence = actionSequence(sample);
      sequence.append(reply);
      expect(sequence.complete).toBe(true);
      expect(sequence.data).toEqual(sample.data);
      const [url, init] = fetcher.mock.calls[0] ?? [];
      const paths = {
        allocation: `/payments/${sample.request.source_id}/allocation-context`,
        allocation_reversal: `/payment-allocations/${sample.request.source_id}/reversal-context`,
        receipt_reprint: `/receipts/${sample.request.source_id}/reprint-context`,
        credit_recognition: `/payments/${sample.request.source_id}/credit-recognition-context`,
        credit_reversal: `/customer-credits/${sample.request.source_id}/reversal-context`,
        credit_application: `/customer-credits/${sample.request.source_id}/application-context`,
        credit_application_reversal: `/credit-applications/${sample.request.source_id}/reversal-context`,
        refund_return: `/refunds/${sample.request.source_id}/verified-return-context`,
        refund_correction_reversal: `/refunds/${sample.request.refund_id ?? ""}/corrections/${sample.request.source_id}/reversal-context`,
      };
      const parsed = new URL(url as string, "https://synthetic.invalid");
      expect(parsed.pathname).toBe(
        `/api/v1/properties/${sample.propertyId}${paths[sample.request.purpose]}`,
      );
      expect(parsed.searchParams.get("target_id")).toBe(
        sample.request.target_id ?? null,
      );
      expect(parsed.searchParams.get("target_kind")).toBe(
        sample.request.target_kind ?? null,
      );
      expect(init).toMatchObject({
        method: "GET",
        cache: "no-store",
        credentials: "include",
        redirect: "error",
      });
      expect(init?.body).toBeUndefined();
      const headers = new Headers(init?.headers);
      expect(headers.get("Idempotency-Key")).toBeNull();
      expect(headers.get("X-CSRF-Token")).toBeNull();
      expect(headers.get("X-Billing-Actor-ID")).toBe(sample.actorId);
      expect(headers.get("X-Financial-Property-ID")).toBe(sample.propertyId);
    },
  );
  it.each(FINANCIAL_ACTION_PURPOSES)(
    "TEST-FE-375 rejects malformed %s requests before transport",
    async (purpose) => {
      const sample = actionContextFixtures.find(
        (row) => row.request.purpose === purpose,
      );
      expect(sample).toBeDefined();
      if (!sample) return;
      for (const patch of [
        { source_id: "" },
        { source_id: "00000000-0000-0000-0000-000000000000" },
        { target_kind: "INVOICE", target_id: undefined },
        { target_kind: "SETTLEMENT", target_id: contextIds.other },
        { limit: 0 },
        { limit: 101 },
        { cursor: "a:1:bad" },
        { extra: true },
        {
          refund_id:
            purpose === "refund_correction_reversal"
              ? undefined
              : contextIds.other,
        },
      ]) {
        const { client, fetcher } = actionClient(sample);
        await expect(
          client.read(actionScope(sample), {
            ...sample.request,
            ...patch,
          } as FinancialActionContextInput),
        ).rejects.toMatchObject({ code: "INVALID_REQUEST" });
        expect(fetcher).not.toHaveBeenCalled();
      }
    },
  );
  it.each(actionCases)(
    "TEST-FE-376 rejects substituted binding or malformed context $name",
    async ({ sample }) => {
      for (const mutate of [
        (row: FinancialObject) => {
          financialObject(row.meta).actor_id = contextIds.other;
        },
        (row: FinancialObject) => {
          financialObject(row.data).property_id = contextIds.other;
        },
        (row: FinancialObject) => {
          financialObject(row.data).source_id = contextIds.other;
        },
        (row: FinancialObject) => {
          financialObject(row.data).purpose = "future_settlement";
        },
        (row: FinancialObject) => {
          financialObject(row.data).refund_id = contextIds.other;
        },
        (row: FinancialObject) => {
          financialObject(row.data).requested_target_id = contextIds.other;
        },
        (row: FinancialObject) => {
          financialObject(row.data).revision = "invalid";
        },
        (row: FinancialObject) => {
          financialObject(row.data).context = {};
        },
        (row: FinancialObject) => {
          financialObject(row.page).next_cursor =
            "b".repeat(64) + ":1:" + contextIds.other;
        },
      ].filter(
        (_mutate, index) =>
          !(index === 7 && sample.request.purpose === "allocation"),
      )) {
        const { client } = actionClient(sample, mutate);
        await expect(
          client.read(actionScope(sample), sample.request),
        ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
      }
    },
  );
  it("TEST-FE-377 rejects wrong original event, receipt, refund and credit amounts", async () => {
    for (const sample of actionContextFixtures) {
      const { client } = actionClient(sample, (envelope) => {
        const row = financialObject(envelope.data),
          context = financialObject(row.context);
        if (context.refund)
          financialObject(
            financialObject(context.refund).refund,
          ).refund_currency = "KHR";
        else if (context.application)
          financialObject(context.application).customer_credit_id =
            contextIds.other;
        else if (context.allocation)
          financialObject(context.allocation).payment_id = contextIds.other;
        else if (context.receipt)
          financialObject(context.receipt).payment_id = contextIds.other;
        else if (context.credit)
          financialObject(
            financialObject(context.credit).position,
          ).available_usd_cents = 1;
        else
          financialObject(
            financialObject(row.payment_resource).payment,
          ).usd_accounting_value_cents = -1;
      });
      await expect(
        client.read(actionScope(sample), sample.request),
      ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    }
  });
  it("TEST-FE-378 requires actual initial page and complete Invoice totals across continuation", async () => {
    const sample = postingSample(),
      cursor = `${sample.data.revision as string}:1:${contextIds.event}`;
    const item = financialObject((sample.data.items as FinancialObject[])[0]);
    const amount = BigInt(
      financialObject(item.data).outstanding_usd_cents as number,
    );
    const firstAmount = amount / 2n,
      secondAmount = amount - firstAmount;
    sample.data.item_count = 2;
    const declaredTarget = financialObject(sample.data.target);
    declaredTarget.line_count = 2;
    declaredTarget.original_total_usd_cents =
      BigInt(financialObject(item.data).original_amount_usd_cents as number) *
      2n;
    declaredTarget.adjusted_total_usd_cents =
      BigInt(financialObject(item.data).adjusted_amount_usd_cents as number) *
      2n;
    const client = createFinancialReferenceClient((url, init) =>
      Promise.resolve(
        actionResponse(sample, init ?? {}, (envelope) => {
          const next = new URL(
            url as string,
            "https://synthetic.invalid",
          ).searchParams.has("cursor");
          const row = financialObject(envelope.data);
          row.items = [
            {
              ...item,
              sequence: next ? 2 : 1,
              id: next ? contextIds.other : contextIds.event,
              data: {
                ...financialObject(item.data),
                outstanding_usd_cents: next ? secondAmount : firstAmount,
              },
            },
          ];
          financialObject(envelope.page).next_cursor = next ? null : cursor;
        }),
      ),
    );
    const first = await client.read(actionScope(sample), sample.request),
      last = await client.read(actionScope(sample), {
        ...sample.request,
        cursor,
      });
    const sequence = actionSequence(sample);
    sequence.append(first);
    expect(sequence.complete).toBe(false);
    expect(sequence.data).toBeNull();
    expect(sequence.nextCursor).toBe(cursor);
    sequence.append(last);
    expect(sequence.complete).toBe(true);
    expect(sequence.data?.items).toHaveLength(2);
    const isolated = actionSequence(sample);
    expect(() => {
      isolated.append(last);
    }).toThrow();
    expect(isolated.complete).toBe(false);
  });
  it.each([
    "copy",
    "data",
    "page",
    "actor",
    "property",
    "operation",
    "request",
  ] as const)(
    "TEST-FE-379 rejects forged or mutated reply provenance %s",
    async (kind) => {
      const sample = postingSample(),
        { client } = actionClient(sample);
      let reply = await client.read(actionScope(sample), sample.request);
      if (kind === "copy") reply = { ...reply };
      if (kind === "data")
        financialObject(reply.data).revision = "b".repeat(64);
      if (kind === "page" && reply.page) reply.page.limit = 2;
      if (kind === "actor") reply.actorId = contextIds.other;
      if (kind === "property") reply.propertyId = contextIds.other;
      if (kind === "operation") reply.operation = "paymentReversalContext";
      if (kind === "request") reply.requestId = contextIds.other;
      const sequence = actionSequence(sample);
      expect(() => {
        sequence.append(reply);
      }).toThrow();
      expect(sequence.complete).toBe(false);
      expect(sequence.data).toBeNull();
    },
  );
  it("TEST-FE-380 prevents actor, source, target and Refund scope bridges", async () => {
    for (const sample of actionContextFixtures) {
      const { client } = actionClient(sample),
        reply = await client.read(actionScope(sample), sample.request);
      for (const request of [
        { ...sample.request, source_id: contextIds.other },
        ...(sample.request.target_id
          ? [{ ...sample.request, target_id: contextIds.other }]
          : []),
        ...(sample.request.refund_id
          ? [{ ...sample.request, refund_id: contextIds.other }]
          : []),
      ]) {
        const sequence = new FinancialActionContextSequence(
          sample.actorId,
          sample.propertyId,
          request,
        );
        expect(() => {
          sequence.append(reply);
        }).toThrow();
        expect(sequence.complete).toBe(false);
      }
      const sequence = new FinancialActionContextSequence(
        contextIds.other,
        sample.propertyId,
        sample.request,
      );
      expect(() => {
        sequence.append(reply);
      }).toThrow();
      expect(sequence.complete).toBe(false);
    }
  });
  it("TEST-FE-381 runtime scope cannot be assigned, shadowed, rebound or mutated through request and result copies", async () => {
    const sample = postingSample(),
      sequence = actionSequence(sample),
      original = { ...sample.request };
    sample.request.source_id = contextIds.other;
    expect(sequence.request).toEqual(original);
    for (const mutation of [
      () => Object.assign(sequence, { actorId: contextIds.other }),
      () =>
        Object.defineProperty(sequence, "propertyId", {
          value: contextIds.other,
        }),
      () => {
        Object.setPrototypeOf(sequence, {});
      },
      () => Object.assign(sequence.request, { source_id: contextIds.other }),
    ])
      expect(mutation).toThrow();
    sample.request = original;
    const { client } = actionClient(sample);
    sequence.append(await client.read(actionScope(sample), original));
    const detached = sequence.data;
    expect(detached).not.toBeNull();
    if (detached) detached.items = [];
    expect(sequence.data?.items).toHaveLength(1);
    expect(sequence.complete).toBe(true);
  });
  it.each([
    "allocation",
    "allocation_reversal",
    "credit_application",
    "credit_application_reversal",
  ] as const)(
    "TEST-FE-382 incomplete %s details never establish complete action context",
    async (purpose) => {
      const sample = actionContextFixtures.find(
        (row) =>
          row.request.purpose === purpose &&
          Array.isArray(row.data.items) &&
          row.data.items.length &&
          financialObject(row.data.target).kind === "INVOICE",
      );
      expect(sample).toBeDefined();
      if (!sample) return;
      const { client } = actionClient(sample, (envelope) => {
        financialObject(envelope.data).items = [];
      });
      const reply = await client.read(actionScope(sample), sample.request),
        sequence = actionSequence(sample);
      expect(() => {
        sequence.append(reply);
      }).toThrow();
      expect(sequence.complete).toBe(false);
      expect(sequence.data).toBeNull();
    },
  );
  it.each(FINANCIAL_ACTION_PURPOSES)(
    "TEST-FE-383 aborting %s invalidates the read before transport",
    async (purpose) => {
      const sample = actionContextFixtures.find(
        (row) => row.request.purpose === purpose,
      );
      expect(sample).toBeDefined();
      if (!sample) return;
      const controller = new AbortController();
      controller.abort();
      const { client, fetcher } = actionClient(sample);
      await expect(
        client.read(actionScope(sample, controller.signal), sample.request),
      ).rejects.toMatchObject({ code: "WORKSPACE_INVALIDATED" });
      expect(fetcher).not.toHaveBeenCalled();
    },
  );
});

describe("financial action context adjusted and coherent values", () => {
  it("TEST-FE-384 accepts authoritative Invoice debit increases without imposing the original line ceiling", async () => {
    const sample = postingSample();
    const { client } = actionClient(sample, (envelope) => {
      const row = financialObject(envelope.data),
        target = financialObject(row.target),
        detail = financialObject(
          financialObject((row.items as FinancialObject[])[0]).data,
        );
      detail.adjusted_amount_usd_cents =
        BigInt(detail.original_amount_usd_cents as number) + 100n;
      detail.outstanding_usd_cents = detail.adjusted_amount_usd_cents;
      target.outstanding_usd_cents = detail.adjusted_amount_usd_cents;
      target.adjusted_total_usd_cents = detail.adjusted_amount_usd_cents;
    });
    const reply = await client.read(actionScope(sample), sample.request),
      sequence = actionSequence(sample);
    sequence.append(reply);
    expect(sequence.complete).toBe(true);
  });
  it.each(["available", "original", "disposition", "currency"] as const)(
    "TEST-FE-385 rejects inconsistent Payment position %s",
    async (field) => {
      const sample = postingSample(),
        { client } = actionClient(sample, (envelope) => {
          const resource = financialObject(
              financialObject(envelope.data).payment_resource,
            ),
            position = financialObject(resource.position);
          if (field === "available") position.available_usd_cents = 1;
          if (field === "original") position.original_usd_cents = 1;
          if (field === "disposition")
            financialObject(position.dispositions).credit_usd_cents = 1;
          if (field === "currency") position.currency = "KHR";
        });
      await expect(
        client.read(actionScope(sample), sample.request),
      ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    },
  );
  it("TEST-FE-386 rejects mismatched Credit source currency and original Payment value", async () => {
    const sample = actionContextFixtures.find(
      (row) => row.request.purpose === "credit_application",
    );
    expect(sample).toBeDefined();
    if (!sample) return;
    for (const change of [
      { received_currency: "KHR" },
      { received_amount_minor: 1 },
      { payer_customer_id: contextIds.other },
    ]) {
      const { client } = actionClient(sample, (envelope) => {
        const credit = financialObject(
          financialObject(financialObject(envelope.data).context).credit,
        );
        Object.assign(financialObject(credit.source_payment), change);
      });
      await expect(
        client.read(actionScope(sample), sample.request),
      ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    }
  });
});

const PUT_BACK = "PUT_BACK_BY_CORRECTION";
function reversalSamples(
  purpose: "allocation_reversal" | "credit_application_reversal",
  kind: string,
): FinancialActionFixture[] {
  return actionContextFixtures.filter(
    (row) =>
      row.request.purpose === purpose &&
      financialObject(row.data.target).kind === kind &&
      Array.isArray(row.data.items) &&
      row.data.items.length > 0,
  );
}
function putBack(data: FinancialObject, payment: boolean, lines: boolean) {
  const context = financialObject(data.context);
  if (payment) {
    const original = financialObject(context.application ?? context.allocation);
    original.within_invoice_basis = PUT_BACK;
    // A Credit payment put back carries no designation and no proposal; an allocation keeps
    // its own fields, so only the label refuses it.
    if (context.application !== undefined) {
      original.customer_designation_reference = null;
      original.proposal_generated_at = null;
    }
  }
  if (lines && Array.isArray(data.items))
    for (const item of data.items) {
      const line = financialObject(financialObject(item).data);
      if ("attribution_basis" in line) line.attribution_basis = PUT_BACK;
    }
}

describe("financial action context put-back label (V1-056 sub-slice 10e-3e-2)", () => {
  it("TEST-FE-676 shows the re-posted rest of a Credit payment a correction put back, with its label", async () => {
    const samples = reversalSamples("credit_application_reversal", "INVOICE");
    expect(samples).toHaveLength(5);
    expect(
      new Set(
        samples.map(
          (sample) => financialObject(sample.data.context).reversal === null,
        ),
      ),
    ).toEqual(new Set([true, false]));
    for (const sample of samples) {
      const { client } = actionClient(sample, (envelope) => {
        putBack(financialObject(envelope.data), true, true);
      });
      const reply = await client.read(actionScope(sample), sample.request),
        sequence = actionSequence(sample);
      sequence.append(reply);
      expect(sequence.complete).toBe(true);
      const expected = actionCopy(sample).data;
      putBack(expected, true, true);
      expect(sequence.data).toEqual(expected);
      expect(
        financialObject(financialObject(sequence.data?.context).application)
          .within_invoice_basis,
      ).toBe(PUT_BACK);
      const items = sequence.data?.items;
      expect(Array.isArray(items) && items.length > 0).toBe(true);
      if (Array.isArray(items))
        for (const item of items)
          expect(
            financialObject(financialObject(item).data).attribution_basis,
          ).toBe(PUT_BACK);
    }
  });
  it("TEST-FE-677 refuses the put-back label where the database never writes it", async () => {
    const allocation = reversalSamples("allocation_reversal", "INVOICE")[0],
      credit = reversalSamples("credit_application_reversal", "INVOICE")[0],
      charge = reversalSamples(
        "credit_application_reversal",
        "LATE_PAYMENT_CHARGE",
      )[0];
    const cases: [FinancialActionFixture | undefined, boolean, boolean][] = [
      [allocation, true, false],
      [allocation, false, true],
      // Each with its lines too, so only the allocation lists and the Charge rule refuse them.
      [allocation, true, true],
      [charge, true, true],
      [charge, true, false],
      [charge, false, true],
      // A line and its payment must carry the label together.
      [credit, true, false],
      [credit, false, true],
    ];
    for (const [sample, payment, lines] of cases) {
      expect(sample).toBeDefined();
      if (!sample) throw new Error("Synthetic fixture missing");
      const { client } = actionClient(sample, (envelope) => {
        putBack(financialObject(envelope.data), payment, lines);
      });
      await expect(
        client.read(actionScope(sample), sample.request),
      ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    }
  });
});

function selectedCreditSample(reversed = false): FinancialActionFixture {
  const found = actionContextFixtures.find(
    (sample) =>
      sample.request.purpose === "credit_reversal" &&
      (financialObject(sample.data.context).reversal !== null) === reversed,
  );
  if (!found) throw new Error("Synthetic Credit context is required");
  return actionCopy(found);
}
function invoiceCoverageSample(
  count: number,
  status = "PAID",
): FinancialActionFixture {
  const sample = postingSample();
  const item = financialObject((sample.data.items as FinancialObject[])[0]);
  const detail = financialObject(item.data);
  const target = financialObject(sample.data.target);
  target.status = status;
  target.outstanding_usd_cents = 0;
  if (status === "DRAFT") target.issued_at = null;
  detail.outstanding_usd_cents = 0;
  // New authoritative declarations are installed with the corrected PG fixtures.
  // These controls also run against the preserved pre-correction wire shape.
  if (Object.hasOwn(sample.data, "item_count")) sample.data.item_count = count;
  if (Object.hasOwn(target, "line_count")) {
    target.line_count = count;
    target.original_total_usd_cents =
      BigInt(detail.original_amount_usd_cents as number) * BigInt(count);
    target.adjusted_total_usd_cents =
      BigInt(detail.adjusted_amount_usd_cents as number) * BigInt(count);
  }
  return sample;
}
function invoiceCoveragePages(
  sample: FinancialActionFixture,
  count: number,
  descriptionBytes = 20,
  descriptionCharacter = "x",
) {
  const original = financialObject((sample.data.items as FinancialObject[])[0]);
  const identities = Array.from({ length: count }, () => crypto.randomUUID());
  const cursorFor = (index: number) =>
    `${sample.data.revision as string}:${(index + 1).toString()}:${identities[index] ?? ""}`;
  const client = createFinancialReferenceClient((url, init) => {
    const cursor = new URL(
      url as string,
      "https://synthetic.invalid",
    ).searchParams.get("cursor");
    const index =
      cursor === null
        ? 0
        : identities.findIndex((_id, i) => cursorFor(i) === cursor) + 1;
    if (index < 0 || index >= count)
      throw new Error("Unexpected synthetic continuation");
    return Promise.resolve(
      actionResponse(sample, init ?? {}, (envelope) => {
        financialObject(envelope.data).items = [
          {
            ...original,
            sequence: index + 1,
            id: identities[index] ?? "",
            data: {
              ...financialObject(original.data),
              description: descriptionCharacter.repeat(descriptionBytes),
            },
          },
        ];
        financialObject(envelope.page).next_cursor =
          index + 1 === count ? null : cursorFor(index);
      }),
    );
  });
  return { client, cursorFor };
}

describe("independent review06 financial context regressions", () => {
  it.each([
    "reversed_available",
    "partial_reversal",
    "missing_reversal",
    "recognition_above_source",
    "fabricated_usd_fx",
  ] as const)(
    "TEST-FE-390 rejects contradictory Credit facts %s before provenance",
    async (fault) => {
      const sample = selectedCreditSample(
        fault === "reversed_available" || fault === "missing_reversal",
      );
      const baseline = actionClient(sample);
      const original = actionSequence(sample);
      original.append(
        await baseline.client.read(actionScope(sample), sample.request),
      );
      expect(original.complete).toBe(true);
      const { client } = actionClient(sample, (envelope) => {
        const context = financialObject(financialObject(envelope.data).context);
        const credit = financialObject(context.credit);
        const position = financialObject(credit.position);
        const recognized = BigInt(position.recognized_usd_cents as number);
        if (fault === "reversed_available") {
          position.available_usd_cents = recognized;
          position.reversed_usd_cents = 0;
        } else if (fault === "partial_reversal") {
          position.reversed_usd_cents = 1;
          position.available_usd_cents = recognized - 1n;
        } else if (fault === "missing_reversal") context.reversal = null;
        else if (fault === "recognition_above_source") {
          financialObject(credit.credit).recognized_usd_cents = recognized + 1n;
          position.recognized_usd_cents = recognized + 1n;
          position.available_usd_cents = recognized + 1n;
        } else credit.exchange_rate = { fabricated: "FX for USD" };
      });
      await expect(
        client.read(actionScope(sample), sample.request),
      ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    },
  );
  it.each([
    "missing",
    "null",
    "identity",
    "reference",
    "system",
    "channel_amount",
    "channel_usd",
    "channel_currency",
    "timestamp",
    "receipt_link",
    "unknown_field",
  ] as const)(
    "TEST-FE-391 rejects incoherent original KHR evidence %s",
    async (fault) => {
      const fixture = actionContextFixtures[fault === "receipt_link" ? 2 : 0];
      if (!fixture) throw new Error("Original KHR source fixture is required");
      const sample = actionCopy(fixture);
      const { client } = actionClient(sample, (envelope) => {
        const resource = financialObject(
          financialObject(envelope.data).payment_resource,
        );
        const fx = financialObject(resource.exchange_rate);
        if (fault === "missing") delete resource.exchange_rate;
        else if (fault === "null") resource.exchange_rate = null;
        else if (fault === "identity") fx.id = crypto.randomUUID();
        else if (fault === "reference")
          fx.reference_rate_khr_per_usd = "1.000000";
        else if (fault === "system") fx.system_rate_khr_per_usd = 1;
        else if (fault === "channel_amount") fx.channel_actual_amount_minor = 1;
        else if (fault === "channel_usd") fx.channel_actual_usd_value_cents = 1;
        else if (fault === "channel_currency")
          fx.channel_actual_currency = "USD";
        else if (fault === "timestamp")
          fx.channel_confirmed_at = "2099-01-01T00:00:00Z";
        else if (fault === "receipt_link")
          financialObject(resource.receipt).id = crypto.randomUUID();
        else resource.unverified = "unexpected source field";
      });
      await expect(
        client.read(actionScope(sample), sample.request),
      ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    },
  );
  it.each(["PAID", "DRAFT", "VOID", "ADJUSTED_TO_ZERO"])(
    "TEST-FE-392 never marks omitted %s Invoice originals complete",
    async (status) => {
      const sample = invoiceCoverageSample(
        1,
        status === "ADJUSTED_TO_ZERO" ? "PAID" : status,
      );
      if (status === "ADJUSTED_TO_ZERO") {
        financialObject(
          (sample.data.items as FinancialObject[])[0]?.data,
        ).adjusted_amount_usd_cents = 0;
        const target = financialObject(sample.data.target);
        if (Object.hasOwn(target, "adjusted_total_usd_cents"))
          target.adjusted_total_usd_cents = 0;
      }
      const control = actionSequence(sample);
      control.append(
        await actionClient(sample).client.read(
          actionScope(sample),
          sample.request,
        ),
      );
      expect(control.complete).toBe(true);
      const sequence = actionSequence(sample);
      const broken = actionClient(sample, (envelope) => {
        financialObject(envelope.data).items = [];
      });
      await expect(
        (async () => {
          sequence.append(
            await broken.client.read(actionScope(sample), sample.request),
          );
        })(),
      ).rejects.toThrow();
      expect(sequence.complete).toBe(false);
      expect(sequence.data).toBeNull();
    },
  );
  it("TEST-FE-393 rejects a premature final page omitting a fully paid line", async () => {
    const sample = invoiceCoverageSample(2, "PARTIALLY_PAID");
    const item = financialObject((sample.data.items as FinancialObject[])[0]);
    const amount = BigInt(
      financialObject(item.data).adjusted_amount_usd_cents as number,
    );
    financialObject(sample.data.target).outstanding_usd_cents = amount;
    const firstId = crypto.randomUUID(),
      lastId = crypto.randomUUID();
    const cursor = `${sample.data.revision as string}:1:${firstId}`;
    const makeClient = (omit: boolean) =>
      createFinancialReferenceClient((url, init) => {
        const later = new URL(
          url as string,
          "https://synthetic.invalid",
        ).searchParams.has("cursor");
        return Promise.resolve(
          actionResponse(sample, init ?? {}, (envelope) => {
            financialObject(envelope.data).items = [
              {
                ...item,
                sequence: later ? 2 : 1,
                id: later ? lastId : firstId,
                data: {
                  ...financialObject(item.data),
                  outstanding_usd_cents: later ? 0 : amount,
                },
              },
            ];
            financialObject(envelope.page).next_cursor =
              later || omit ? null : cursor;
          }),
        );
      });
    const client = makeClient(false),
      control = actionSequence(sample);
    control.append(await client.read(actionScope(sample), sample.request));
    expect(control.complete).toBe(false);
    control.append(
      await client.read(actionScope(sample), { ...sample.request, cursor }),
    );
    expect(control.complete).toBe(true);
    const broken = actionSequence(sample);
    await expect(
      (async () => {
        broken.append(
          await makeClient(true).read(actionScope(sample), sample.request),
        );
      })(),
    ).rejects.toThrow();
    expect(broken.complete).toBe(false);
    expect(broken.data).toBeNull();
  });
  it.each([4, 22])(
    "TEST-FE-394 enforces cumulative bytes across %i individually bounded pages",
    async (count) => {
      const sample = invoiceCoverageSample(count);
      const { client, cursorFor } = invoiceCoveragePages(
        sample,
        count,
        400_000,
      );
      const sequence = actionSequence(sample);
      let failure: unknown = null;
      let processed = 0;
      for (let i = 0; i < count; i++) {
        const reply = await client.read(actionScope(sample), {
          ...sample.request,
          ...(i === 0 ? {} : { cursor: cursorFor(i - 1) }),
        });
        try {
          sequence.append(reply);
          processed += 1;
        } catch (error) {
          failure = error;
          break;
        }
      }
      if (count === 4) {
        expect(failure).toBeNull();
        expect(processed).toBe(4);
        expect(sequence.complete).toBe(true);
        expect(sequence.data?.items).toHaveLength(4);
      } else {
        expect(failure).not.toBeNull();
        expect(processed).toBeLessThan(count);
        expect(sequence.complete).toBe(false);
        expect(sequence.data).toBeNull();
        const small = invoiceCoverageSample(1);
        const reply = await actionClient(small).client.read(
          actionScope(small),
          small.request,
        );
        expect(() => {
          sequence.append(reply);
        }).toThrow();
        expect(sequence.complete).toBe(false);
      }
    },
  );
});

describe("financial action context review correction boundaries", () => {
  it.each([
    "identity",
    "rate",
    "source",
    "time",
    "unknown",
    "missing",
    "channel_time",
  ] as const)(
    "TEST-FE-395 binds repeated Credit FX to the original Payment %s",
    async (fault) => {
      const fixture = actionContextFixtures.find((sample) => {
        const credit = financialObject(sample.data.context).credit;
        if (!credit) return false;
        const rate = financialObject(credit).exchange_rate;
        return (
          rate !== null &&
          financialObject(rate).channel_actual_amount_minor !== null &&
          financialObject(rate).channel_actual_usd_value_cents !== null
        );
      });
      if (!fixture)
        throw new Error("Real synthetic KHR Credit evidence is required");
      const sample = actionCopy(fixture);
      const { client } = actionClient(sample, (envelope) => {
        const credit = financialObject(
          financialObject(financialObject(envelope.data).context).credit,
        );
        const rate = financialObject(credit.exchange_rate);
        if (fault === "identity") rate.id = contextIds.other;
        if (fault === "rate") {
          rate.reference_rate_khr_per_usd = "4081.000000";
          rate.system_rate_khr_per_usd = 4102;
        }
        if (fault === "source") rate.rate_source = "ABA_EQUIVALENT_MANUAL";
        if (fault === "time") rate.applicable_at = "2020-01-01T00:00:00Z";
        if (fault === "channel_time")
          rate.channel_confirmed_at = "2020-01-01T00:00:00Z";
        if (fault === "unknown") rate.fabricated = "source";
        if (fault === "missing") delete rate.reference_rate_khr_per_usd;
      });
      await expect(
        client.read(actionScope(sample), sample.request),
      ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    },
  );
  it.each([
    "missing_count",
    "negative_count",
    "fractional_count",
    "huge_count",
    "boolean_count",
    "wrong_line_count",
    "original_total",
    "adjusted_total",
  ] as const)(
    "TEST-FE-396 rejects missing or inconsistent collection declarations %s",
    async (fault) => {
      const sample = invoiceCoverageSample(1);
      const { client } = actionClient(sample, (envelope) => {
        const data = financialObject(envelope.data),
          target = financialObject(data.target);
        if (fault === "missing_count") delete data.item_count;
        if (fault === "negative_count") data.item_count = -1;
        if (fault === "fractional_count") data.item_count = "1.5";
        if (fault === "huge_count") data.item_count = 32768;
        if (fault === "boolean_count") data.item_count = true;
        if (fault === "wrong_line_count") target.line_count = 2;
        if (fault === "original_total")
          target.original_total_usd_cents =
            BigInt(target.original_total_usd_cents as number) + 1n;
        if (fault === "adjusted_total")
          target.adjusted_total_usd_cents =
            BigInt(target.adjusted_total_usd_cents as number) + 1n;
      });
      const sequence = actionSequence(sample);
      await expect(
        (async () => {
          sequence.append(
            await client.read(actionScope(sample), sample.request),
          );
        })(),
      ).rejects.toThrow();
      expect(sequence.complete).toBe(false);
      expect(sequence.data).toBeNull();
    },
  );
  it("TEST-FE-397 rejects changed cardinality even when a server repeats the prior revision", async () => {
    const sample = invoiceCoverageSample(2);
    const { client, cursorFor } = invoiceCoveragePages(sample, 2);
    const sequence = actionSequence(sample);
    sequence.append(await client.read(actionScope(sample), sample.request));
    sample.data.item_count = 3;
    const target = financialObject(sample.data.target);
    target.line_count = 3;
    target.original_total_usd_cents =
      (BigInt(target.original_total_usd_cents as number) / 2n) * 3n;
    target.adjusted_total_usd_cents =
      (BigInt(target.adjusted_total_usd_cents as number) / 2n) * 3n;
    const last = await client.read(actionScope(sample), {
      ...sample.request,
      cursor: cursorFor(0),
    });
    expect(() => {
      sequence.append(last);
    }).toThrow();
    expect(sequence.nextCursor).toBeNull();
    expect(sequence.data).toBeNull();
  });
  it("TEST-FE-398 accepts a valid legacy Payment reversal reference and rejects remaining dispositions", async () => {
    const sample = postingSample();
    sample.request = {
      operation: "financialActionContext",
      purpose: "allocation",
      source_id: sample.request.source_id,
    };
    sample.page.limit = 50;
    sample.data.requested_target_kind = null;
    sample.data.requested_target_id = null;
    sample.data.target = null;
    sample.data.items = [];
    sample.data.item_count = 0;
    const resource = financialObject(sample.data.payment_resource),
      payment = financialObject(resource.payment);
    payment.status = "REVERSED";
    payment.authorization_reference = "Legacy approved receipt reference";
    const position = financialObject(resource.position);
    position.available_usd_cents = 0;
    const dispositions = financialObject(position.dispositions);
    for (const key of Object.keys(dispositions)) dispositions[key] = 0;
    if (
      typeof payment.id !== "string" ||
      typeof payment.confirmed_at !== "string"
    )
      throw new Error(
        "Legacy control requires original Payment identity and instant",
      );
    resource.reversal = {
      id: contextIds.event,
      payment_id: payment.id,
      reason: "Correct recorded source",
      occurred_at: payment.confirmed_at,
      actor_id: sample.actorId,
      authorization_reference: "Legacy reversal review reference",
    };
    const sequence = actionSequence(sample);
    sequence.append(
      await actionClient(sample).client.read(
        actionScope(sample),
        sample.request,
      ),
    );
    expect(sequence.complete).toBe(true);
    dispositions.allocation_usd_cents = 1;
    await expect(
      actionClient(sample).client.read(actionScope(sample), sample.request),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });
  it("TEST-FE-399 counts UTF-8 bytes across pages and poisons an oversized context", async () => {
    const sample = invoiceCoverageSample(22);
    const { client, cursorFor } = invoiceCoveragePages(
      sample,
      22,
      100_000,
      "😀",
    );
    const sequence = actionSequence(sample);
    let failed = false;
    for (let index = 0; index < 22; index++) {
      const reply = await client.read(actionScope(sample), {
        ...sample.request,
        ...(index === 0 ? {} : { cursor: cursorFor(index - 1) }),
      });
      try {
        sequence.append(reply);
      } catch {
        failed = true;
        break;
      }
    }
    expect(failed).toBe(true);
    expect(sequence.complete).toBe(false);
    expect(sequence.nextCursor).toBeNull();
    expect(sequence.data).toBeNull();
  });
});

function reviewAAValue(row: FinancialObject, key: string): FinancialJson {
  const value = row[key];
  if (value === undefined)
    throw new Error("Required synthetic original field missing");
  return value;
}
function reviewAASample(index: number): FinancialActionFixture {
  const sample = actionContextFixtures[index];
  if (!sample)
    throw new Error("Required immutable AA synthetic projection missing");
  return actionCopy(sample);
}
function reviewAAPosition(
  sample: FinancialActionFixture,
  creditSource: boolean,
) {
  const resource = financialObject(sample.data.payment_resource);
  const context = financialObject(sample.data.context);
  const position = financialObject(
    creditSource ? financialObject(context.credit).position : resource.position,
  );
  return {
    position,
    aggregate: creditSource ? position : financialObject(position.dispositions),
  };
}
function reviewAAAggregate(
  sample: FinancialActionFixture,
  creditSource: boolean,
  field: string,
  amount: bigint,
) {
  const { position, aggregate } = reviewAAPosition(sample, creditSource);
  const old = BigInt(aggregate[field] as number);
  aggregate[field] = amount;
  position.available_usd_cents =
    BigInt(position.available_usd_cents as number) + old - amount;
}
function reviewAAReversePayment(sample: FinancialActionFixture) {
  const resource = financialObject(sample.data.payment_resource),
    payment = financialObject(resource.payment);
  if (
    typeof payment.id !== "string" ||
    typeof payment.confirmed_at !== "string"
  )
    throw new Error("Original Payment required");
  payment.status = "REVERSED";
  const position = financialObject(resource.position),
    dispositions = financialObject(position.dispositions);
  for (const key of Object.keys(dispositions)) dispositions[key] = 0;
  position.available_usd_cents = 0;
  resource.reversal = {
    id: crypto.randomUUID(),
    payment_id: payment.id,
    reason: "Historical full reversal",
    occurred_at: "2099-01-01T00:00:00Z",
    actor_id: sample.actorId,
    authorization_reference: "Legacy approved reversal reference",
  };
}
async function reviewAAComplete(sample: FinancialActionFixture) {
  const sequence = actionSequence(sample);
  sequence.append(
    await actionClient(sample).client.read(actionScope(sample), sample.request),
  );
  expect(sequence.complete).toBe(true);
  expect(sequence.data).not.toBeNull();
}
const reviewAAReturnFields = [
  "verified_return_amount_minor",
  "verified_return_currency",
  "verified_returned_at",
  "return_method_reference",
] as const;

describe("independent reviewAA finite selected facts", () => {
  it.each([
    [7, false, "allocation_usd_cents"],
    [11, true, "applied_usd_cents"],
    [13, false, "refund_usd_cents"],
    [16, true, "refunded_usd_cents"],
  ] as const)(
    "TEST-FE-402 rejects selected event below conserved source aggregate %i",
    async (index, creditSource, field) => {
      for (const below of [0n, 1n]) {
        const sample = reviewAASample(index);
        await reviewAAComplete(sample);
        const context = financialObject(sample.data.context);
        const amount =
          index === 7 || index === 11
            ? BigInt(
                financialObject(
                  context[index === 7 ? "allocation" : "application"],
                ).amount_usd_cents as number,
              )
            : BigInt(
                financialObject(context.refund).net_refund_usd_cents as number,
              );
        reviewAAAggregate(
          sample,
          creditSource,
          field,
          below === 0n ? 0n : amount - 1n,
        );
        await expect(
          actionClient(sample).client.read(actionScope(sample), sample.request),
        ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
      }
    },
  );
  it.each([8, 12, 13, 16])(
    "TEST-FE-403 rejects original selected amount above immutable source %i",
    async (index) => {
      const sample = reviewAASample(index),
        context = financialObject(sample.data.context);
      const ceiling = BigInt(
        index === 12 || index === 16
          ? (financialObject(financialObject(context.credit).credit)
              .recognized_usd_cents as number)
          : (financialObject(
              financialObject(sample.data.payment_resource).payment,
            ).usd_accounting_value_cents as number),
      );
      if (index === 8 || index === 12) {
        const event = financialObject(
            context[index === 8 ? "allocation" : "application"],
          ),
          old = BigInt(event.amount_usd_cents as number);
        event.amount_usd_cents = ceiling + 1n;
        const first = financialObject(
            (sample.data.items as FinancialObject[])[0]?.data,
          ),
          key =
            index === 8
              ? "posted_amount_usd_cents"
              : "applied_amount_usd_cents";
        first[key] = BigInt(first[key] as number) + ceiling + 1n - old;
      } else {
        const refund = financialObject(financialObject(context.refund).refund);
        refund.refund_amount_minor = ceiling + 1n;
        refund.usd_accounting_value_cents = ceiling + 1n;
      }
      await expect(
        actionClient(sample).client.read(actionScope(sample), sample.request),
      ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    },
  );
  it.each([15, 18, 27])(
    "TEST-FE-404 rejects active selected return exceeding current total returned %i",
    async (index) => {
      const sample = reviewAASample(index);
      await reviewAAComplete(sample);
      financialObject(sample.data.context).reversal = null;
      await expect(
        actionClient(sample).client.read(actionScope(sample), sample.request),
      ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    },
  );
  it.each(
    [14, 17, 26].flatMap((index) =>
      [
        "all_null",
        "original_null",
        "wrong_auth",
        "before_payout",
        "after_correction",
        "correction_at_payout",
        "extra",
        "missing",
      ].map((fault) => ({ index, fault })),
    ),
  )(
    "TEST-FE-405 rejects current return evidence $index $fault",
    async ({ index, fault }) => {
      const sample = reviewAASample(index),
        context = financialObject(sample.data.context),
        correction = financialObject(context.correction),
        refund = financialObject(financialObject(context.refund).refund);
      await reviewAAComplete(sample);
      if (fault === "all_null") {
        for (const key of reviewAAReturnFields) correction[key] = null;
        correction.source_balance_effect_original_minor = null;
      } else if (fault === "original_null")
        correction.source_balance_effect_original_minor = null;
      else if (fault === "wrong_auth")
        correction.authorization_reference = "refunds.create";
      else if (fault === "before_payout")
        correction.verified_returned_at = "2000-01-01T00:00:00Z";
      else if (fault === "after_correction")
        correction.verified_returned_at = "2099-01-01T00:00:00Z";
      else if (fault === "correction_at_payout") {
        correction.occurred_at = reviewAAValue(refund, "processed_at");
        correction.verified_returned_at = reviewAAValue(refund, "processed_at");
      } else if (fault === "extra") correction.invented_amount_usd_cents = 123;
      else delete correction.return_method_reference;
      await expect(
        actionClient(sample).client.read(actionScope(sample), sample.request),
      ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    },
  );
  it.each(
    [15, 18, 27].flatMap((index) =>
      ["original_null", "wrong_auth", "same_instant", "extra"].map((fault) => ({
        index,
        fault,
      })),
    ),
  )(
    "TEST-FE-406 rejects current reversal evidence $index $fault",
    async ({ index, fault }) => {
      const sample = reviewAASample(index),
        context = financialObject(sample.data.context),
        reversal = financialObject(context.reversal);
      await reviewAAComplete(sample);
      if (fault === "original_null")
        reversal.source_balance_effect_original_minor = null;
      else if (fault === "wrong_auth")
        reversal.authorization_reference = "refunds.correct";
      else if (fault === "same_instant")
        reversal.occurred_at = reviewAAValue(
          financialObject(context.correction),
          "occurred_at",
        );
      else reversal.invented_amount_usd_cents = 123;
      await expect(
        actionClient(sample).client.read(actionScope(sample), sample.request),
      ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    },
  );
  it.each([
    "empty",
    "missing_name",
    "null_name",
    "blank_name",
    "unknown_snapshot",
    "unknown_receipt",
    "wrong_issuer",
    "before_confirmation",
    "wrong_number",
    "missing_issuance",
  ])(
    "TEST-FE-407 rejects immutable Receipt contradictions %s",
    async (fault) => {
      const sample = reviewAASample(2),
        receipt = financialObject(financialObject(sample.data.context).receipt),
        snapshot = financialObject(receipt.identity_snapshot);
      await reviewAAComplete(sample);
      if (fault === "empty") receipt.identity_snapshot = {};
      else if (fault === "missing_name") delete snapshot.payer_legal_name;
      else if (fault === "null_name") snapshot.payer_legal_name = null;
      else if (fault === "blank_name") snapshot.payer_legal_name = "   ";
      else if (fault === "unknown_snapshot")
        snapshot.current_payer_name = "Synthetic later name";
      else if (fault === "unknown_receipt") receipt.amount_usd_cents = 999;
      else if (fault === "wrong_issuer")
        receipt.issued_by = crypto.randomUUID();
      else if (fault === "before_confirmation")
        receipt.issued_at = "2000-01-01T00:00:00Z";
      else if (fault === "wrong_number") {
        receipt.receipt_number = "Fabricated receipt number";
        financialObject(
          financialObject(sample.data.payment_resource).receipt,
        ).receipt_number = receipt.receipt_number;
      } else delete receipt.issued_at;
      await expect(
        actionClient(sample).client.read(actionScope(sample), sample.request),
      ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    },
  );
  it("TEST-FE-V059B-05 accepts a Receipt that carries its Payment's RCP number", async () => {
    const sample = reviewAASample(2),
      receipt = financialObject(financialObject(sample.data.context).receipt),
      payment = financialObject(
        financialObject(sample.data.payment_resource).payment,
      );
    await reviewAAComplete(sample);
    payment.payment_number = "RCP260001";
    receipt.receipt_number = "RCP260001";
    financialObject(
      financialObject(sample.data.payment_resource).receipt,
    ).receipt_number = "RCP260001";
    await expect(
      actionClient(sample).client.read(actionScope(sample), sample.request),
    ).resolves.toBeTruthy();
    receipt.receipt_number = "RCP260002";
    financialObject(
      financialObject(sample.data.payment_resource).receipt,
    ).receipt_number = "RCP260002";
    await expect(
      actionClient(sample).client.read(actionScope(sample), sample.request),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });
  it("TEST-FE-408 preserves multiple contributing sources, reversed originals and full returns after parent reversal", async () => {
    for (const [index, creditSource, field] of [
      [7, false, "allocation_usd_cents"],
      [11, true, "applied_usd_cents"],
      [13, false, "refund_usd_cents"],
      [16, true, "refunded_usd_cents"],
    ] as const) {
      const sample = reviewAASample(index);
      // Give CREDIT Refund a second contribution by increasing recognized/source disposition consistently.
      if (index === 16) {
        const context = financialObject(sample.data.context),
          credit = financialObject(context.credit),
          position = financialObject(credit.position);
        financialObject(credit.credit).recognized_usd_cents = 9000;
        position.recognized_usd_cents = 9000;
        position.available_usd_cents = 1000;
        reviewAAAggregate(sample, false, "credit_usd_cents", 9000n);
      }
      const { aggregate, position } = reviewAAPosition(sample, creditSource);
      if (BigInt(position.available_usd_cents as number) > 0n)
        reviewAAAggregate(
          sample,
          creditSource,
          field,
          BigInt(aggregate[field] as number) + 1n,
        );
      await reviewAAComplete(sample);
    }
    for (const index of [8, 12]) await reviewAAComplete(reviewAASample(index));
    const invalid = reviewAASample(7);
    reviewAAReversePayment(invalid);
    await expect(
      actionClient(invalid).client.read(actionScope(invalid), invalid.request),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    for (const index of [13, 16]) {
      const sample = reviewAASample(index),
        context = financialObject(sample.data.context);
      financialObject(context.refund).net_refund_usd_cents = 0;
      if (index === 16) {
        const position = financialObject(
          financialObject(context.credit).position,
        );
        position.refunded_usd_cents = 0;
        position.reversed_usd_cents = reviewAAValue(
          position,
          "recognized_usd_cents",
        );
        position.available_usd_cents = 0;
      }
      reviewAAReversePayment(sample);
      await reviewAAComplete(sample);
    }
  });
  it.each([26, 27])(
    "TEST-FE-409 preserves legacy Reservation null evidence and rejects invented evidence %i",
    async (index) => {
      const sample = reviewAASample(index),
        context = financialObject(sample.data.context),
        refund = financialObject(financialObject(context.refund).refund);
      refund.source_lifecycle_event_id = crypto.randomUUID();
      refund.pet_refund_review_id = null;
      financialObject(context.deposit_source).deposit_type = "SECURITY";
      for (const value of [context.correction, context.reversal])
        if (value !== null) {
          const row = financialObject(value);
          row.source_balance_effect_original_minor = null;
          for (const key of reviewAAReturnFields) row[key] = null;
          row.authorization_reference =
            "Legacy coordinated Reservation correction reference";
        }
      await reviewAAComplete(sample);
      const correction = financialObject(context.correction);
      correction.source_balance_effect_original_minor = reviewAAValue(
        correction,
        "source_balance_effect_usd_cents",
      );
      await expect(
        actionClient(sample).client.read(actionScope(sample), sample.request),
      ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    },
  );
  it("TEST-FE-410 preserves historical Receipt identity for a different reader and microsecond issuance ordering", async () => {
    const sample = reviewAASample(2),
      receipt = financialObject(financialObject(sample.data.context).receipt),
      payment = financialObject(
        financialObject(sample.data.payment_resource).payment,
      );
    sample.actorId = crypto.randomUUID();
    financialObject(receipt.identity_snapshot).payer_legal_name =
      "Original historical synthetic name";
    receipt.issued_at = reviewAAValue(payment, "confirmed_at");
    await reviewAAComplete(sample);
    if (typeof payment.confirmed_at !== "string")
      throw new Error("Original confirmation instant required");
    const confirmed = payment.confirmed_at,
      match = /^(.*T\d\d:\d\d:\d\d)\.(\d{1,6})([+-]\d\d:\d\d|Z)$/.exec(
        confirmed,
      );
    if (!match?.[1] || !match[2] || !match[3])
      throw new Error("Microsecond fixture instant required");
    const micros = Number(match[2].padEnd(6, "0"));
    if (micros === 0)
      throw new Error("Nonzero microsecond fixture instant required");
    receipt.issued_at = `${match[1]}.${String(micros - 1).padStart(6, "0")}${match[3]}`;
    await expect(
      actionClient(sample).client.read(actionScope(sample), sample.request),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });
});

describe("selected financial source chronology", () => {
  it.each([
    [7, "allocation"],
    [8, "allocation_reversal"],
    [11, "application"],
    [12, "application_reversal"],
    [3, "recognition"],
    [5, "recognition_reversal"],
    [13, "payment_refund"],
    [16, "credit_refund"],
    [8, "payment_reversal"],
  ] as const)(
    "TEST-FE-411 rejects a selected event preceding its immutable source %s %s",
    async (index, fault) => {
      const sample = reviewAASample(index),
        context = financialObject(sample.data.context);
      await reviewAAComplete(sample);
      const earlier = "2000-01-01T00:00:00Z";
      if (fault === "allocation")
        financialObject(context.allocation).posted_at = earlier;
      else if (fault === "application")
        financialObject(context.application).occurred_at = earlier;
      else if (
        [
          "allocation_reversal",
          "application_reversal",
          "recognition_reversal",
        ].includes(fault)
      )
        financialObject(context.reversal).occurred_at = earlier;
      else if (fault === "recognition")
        financialObject(financialObject(context.credit).credit).recognized_at =
          earlier;
      else if (fault === "payment_reversal") {
        reviewAAReversePayment(sample);
        financialObject(
          financialObject(sample.data.payment_resource).reversal,
        ).occurred_at = earlier;
      } else
        financialObject(financialObject(context.refund).refund).processed_at =
          earlier;
      await expect(
        actionClient(sample).client.read(actionScope(sample), sample.request),
      ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    },
  );
});
