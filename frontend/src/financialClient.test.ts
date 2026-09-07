import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createFinancialTransport,
  FinancialClientError,
  FINANCIAL_DEADLINE_MS,
  FINANCIAL_REPLY_BYTES,
  readFinancial,
} from "./financialClient";
import { captureFinancialRequest, financialObject } from "./financialContracts";
import { ExactJsonNumber, stringifyFinancialJson } from "./financialJson";
import {
  commands,
  reads,
  command,
  read,
  ids,
  fixture,
} from "./test/financialFixtures";
const scope = () => ({
  actorId: ids.actor,
  propertyId: ids.property,
  signal: new AbortController().signal,
});
function response(
  input: (typeof reads)[number],
  init: RequestInit,
  mutate?: (row: ReturnType<typeof fixture>) => void,
  status?: number,
): Response {
  const row = fixture(input.operation);
  financialObject(row.meta).request_id =
    new Headers(init.headers).get("X-Request-ID") ?? "";
  mutate?.(row);
  return new Response(stringifyFinancialJson(row, FINANCIAL_REPLY_BYTES), {
    status:
      status ??
      (input.operation === "paymentRecord" ||
      input.operation === "allocationPost" ||
      input.operation === "creditRecognize" ||
      input.operation === "creditApply" ||
      input.operation === "refundCreate"
        ? 201
        : 200),
    headers: {
      "Content-Type": "application/json",
      "X-Request-ID": new Headers(init.headers).get("X-Request-ID") ?? "",
    },
  });
}
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});
describe("financial HTTP transport", () => {
  it.each([...reads, ...commands])(
    "TEST-FE-297 validates canonical successful evidence and scoped transmission for $operation",
    async (input) => {
      const fetcher = vi.fn<typeof fetch>((_url, init) =>
        Promise.resolve().then(() => response(input, init ?? {})),
      );
      const request = captureFinancialRequest(input),
        command = request.wireBody !== null;
      const reply = await createFinancialTransport(
        fetcher,
        () => "synthetic-csrf",
      ).send(scope(), request, command ? ids.key : undefined);
      expect(reply.propertyId).toBe(ids.property);
      expect(reply.data).toEqual(fixture(input.operation).data);
      const options = fetcher.mock.calls[0]?.[1];
      if (!options) throw new Error();
      const headers = new Headers(options.headers);
      expect(options).toMatchObject({
        method: command ? "POST" : "GET",
        credentials: "include",
        cache: "no-store",
        redirect: "error",
      });
      expect(headers.get("X-Financial-Property-ID")).toBe(ids.property);
      expect(headers.get("X-Billing-Actor-ID")).toBe(ids.actor);
      expect(headers.get("Idempotency-Key")).toBe(command ? ids.key : null);
      expect(headers.get("X-CSRF-Token")).toBe(
        command ? "synthetic-csrf" : null,
      );
      expect(options.body).toBe(command ? request.wireBody : undefined);
      expect(reply.requestId).toBe(headers.get("X-Request-ID"));
    },
  );
  it.each([...reads, ...commands])(
    "TEST-FE-298 rejects missing wrong or injected Property metadata for $operation",
    async (input) => {
      for (const property of [undefined, ids.other, null]) {
        const fetcher = vi.fn<typeof fetch>((_url, init) =>
          Promise.resolve().then(() =>
            response(input, init ?? {}, (row) => {
              if (property === undefined)
                delete financialObject(row.meta).property_id;
              else financialObject(row.meta).property_id = property;
            }),
          ),
        );
        const request = captureFinancialRequest(input);
        await expect(
          createFinancialTransport(fetcher, () => "csrf").send(
            scope(),
            request,
            request.wireBody ? ids.key : undefined,
          ),
        ).rejects.toMatchObject({ code: "INVALID_RESPONSE", dispatched: true });
      }
    },
  );
  it("TEST-FE-299 rejects invalid UTF8 duplicate JSON interrupted streams wrong status media and oversized evidence", async () => {
    const input = read(1),
      request = captureFinancialRequest(input);
    const cases = [
      "utf8",
      "duplicate",
      "stream-error",
      "media",
      "status",
      "oversize",
      "declared",
      "request-id",
      "empty",
    ];
    for (const mode of cases) {
      const fetcher = vi.fn<typeof fetch>(async (_url, init) => {
        const good = response(input, init ?? {});
        const id = good.headers.get("X-Request-ID") ?? "";
        if (mode === "status")
          return new Response(await good.text(), {
            status: 201,
            headers: good.headers,
          });
        if (mode === "media") good.headers.set("Content-Type", "text/html");
        if (mode === "declared")
          good.headers.set("Content-Length", String(FINANCIAL_REPLY_BYTES + 1));
        if (mode === "request-id") good.headers.set("X-Request-ID", ids.other);
        if (["media", "declared", "request-id"].includes(mode)) return good;
        if (mode === "empty")
          return new Response(null, { headers: good.headers });
        const bytes =
          mode === "utf8"
            ? new Uint8Array([0xc3, 0x28])
            : new TextEncoder().encode(
                mode === "oversize"
                  ? " ".repeat(FINANCIAL_REPLY_BYTES + 1)
                  : '{"data":{},"data":{},"meta":{"request_id":"' + id + '"}}',
              );
        const stream = new ReadableStream<Uint8Array>({
          start(controller) {
            if (mode === "stream-error")
              controller.error(new Error("secret backend trace"));
            else {
              controller.enqueue(bytes);
              controller.close();
            }
          },
        });
        return new Response(stream, { headers: good.headers });
      });
      await expect(
        createFinancialTransport(fetcher).send(scope(), request),
      ).rejects.toBeInstanceOf(FinancialClientError);
    }
  });
  it.each(["fetch", "body"])(
    "TEST-FE-300 enforces one overall deadline when %s ignores abort",
    async (mode) => {
      vi.useFakeTimers();
      const cancelled = vi.fn();
      const fetcher = vi.fn<typeof fetch>(async (_url, init) => {
        if (mode === "fetch")
          return new Promise<Response>(() => {
            /* Deliberately noncooperating fetch. */
          });
        return new Response(new ReadableStream({ cancel: cancelled }), {
          headers: {
            "Content-Type": "application/json",
            "X-Request-ID":
              new Headers(init?.headers).get("X-Request-ID") ?? "",
          },
        });
      });
      const pending = createFinancialTransport(fetcher).send(
        scope(),
        captureFinancialRequest(read(1)),
      );
      const rejected = expect(pending).rejects.toMatchObject({
        code: "UNAVAILABLE",
        dispatched: true,
      });
      await vi.advanceTimersByTimeAsync(FINANCIAL_DEADLINE_MS);
      await rejected;
      if (mode === "body") expect(cancelled).toHaveBeenCalledOnce();
      expect(vi.getTimerCount()).toBe(0);
    },
  );
  it("TEST-FE-301 rejects late replies after scope invalidation and pre-aborted dispatch", async () => {
    const controller = new AbortController();
    let resolve: ((response: Response) => void) | undefined;
    const fetcher = vi.fn<typeof fetch>(
      (_url, init) =>
        new Promise((done) => {
          resolve = () => {
            done(response(read(1), init ?? {}));
          };
        }),
    );
    const current = { ...scope(), signal: controller.signal };
    const pending = createFinancialTransport(fetcher).send(
      current,
      captureFinancialRequest(read(1)),
    );
    controller.abort();
    resolve?.(new Response());
    await expect(pending).rejects.toMatchObject({
      code: "WORKSPACE_INVALIDATED",
      dispatched: true,
    });
    await expect(
      createFinancialTransport(fetcher).send(
        current,
        captureFinancialRequest(read(1)),
      ),
    ).rejects.toMatchObject({ dispatched: false });
    expect(fetcher).toHaveBeenCalledOnce();
  });
  it.each([400, 401, 403, 404, 409, 412, 422, 429, 500, 503])(
    "TEST-FE-302 classifies only canonical fresh validation rejection %s without echoing private text",
    async (status) => {
      const codes: Record<number, string> = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        412: "PRECONDITION_FAILED",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMITED",
        500: "INTERNAL_ERROR",
        503: "SERVICE_UNAVAILABLE",
      };
      const fetcher = vi.fn<typeof fetch>((_url, init) =>
        Promise.resolve().then(() => {
          const request_id =
            new Headers(init?.headers).get("X-Request-ID") ?? "";
          return new Response(
            JSON.stringify({
              error: {
                code: codes[status],
                message: "private SQL credentials",
                fields: [],
              },
              meta: { request_id },
            }),
            {
              status,
              headers: {
                "Content-Type": "application/json",
                "X-Request-ID": request_id,
              },
            },
          );
        }),
      );
      const pending = createFinancialTransport(fetcher, () => "csrf").send(
        scope(),
        captureFinancialRequest(command(0)),
        ids.key,
      );
      await expect(pending).rejects.toMatchObject({
        code: "HTTP_REJECTION",
        status,
        definitiveRejection: [400, 412, 422].includes(status),
      });
      await expect(pending).rejects.not.toHaveProperty(
        "message",
        "private SQL credentials",
      );
    },
  );
  it("TEST-FE-303 accepts empty scoped pages and exact large integers and rejects wrong resource money or source", async () => {
    const input = read(1),
      request = captureFinancialRequest(input);
    const good = vi.fn<typeof fetch>((_url, init) =>
      Promise.resolve().then(() =>
        response(input, init ?? {}, (row) => {
          financialObject(row.data).evidence = {
            amount_usd_cents: 9_223_372_036_854_775_807n,
            exact_rate: new ExactJsonNumber("4100.1234567890123456789"),
          };
        }),
      ),
    );
    const reply = await createFinancialTransport(good).send(scope(), request);
    expect(
      financialObject(financialObject(reply.data).evidence).amount_usd_cents,
    ).toBe(9_223_372_036_854_775_807n);
    for (const value of [
      new ExactJsonNumber("100.0"),
      new ExactJsonNumber("1e2"),
      new ExactJsonNumber("-0"),
      "100",
    ]) {
      const fetcher = vi.fn<typeof fetch>((_url, init) =>
        Promise.resolve().then(() =>
          response(input, init ?? {}, (row) => {
            financialObject(
              financialObject(row.data).payment,
            ).received_amount_minor = value;
          }),
        ),
      );
      await expect(
        createFinancialTransport(fetcher).send(scope(), request),
      ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    }
    const wrong = vi.fn<typeof fetch>((_url, init) =>
      Promise.resolve().then(() =>
        response(input, init ?? {}, (row) => {
          financialObject(financialObject(row.data).payment).id = ids.other;
        }),
      ),
    );
    await expect(
      createFinancialTransport(wrong).send(scope(), request),
    ).rejects.toThrow();
    const empty = vi.fn<typeof fetch>((_url, init) =>
      Promise.resolve().then(() =>
        response(read(0), init ?? {}, (row) => {
          row.data = [];
        }),
      ),
    );
    expect(
      (
        await createFinancialTransport(empty).send(
          scope(),
          captureFinancialRequest(read(0)),
        )
      ).data,
    ).toEqual([]);
  });
  it("TEST-FE-304 captures request body before fetch and blocks command through the read-only entry", async () => {
    const fetcher = vi.fn<typeof fetch>((_url, init) =>
      Promise.resolve().then(() => response(command(0), init ?? {})),
    );
    const transport = createFinancialTransport(fetcher, () => "csrf");
    await expect(
      readFinancial(scope(), command(0), transport),
    ).rejects.toMatchObject({ dispatched: false });
    expect(fetcher).not.toHaveBeenCalled();
    const badCsrf = createFinancialTransport(fetcher, () => {
      throw new FinancialClientError("CSRF_UNAVAILABLE", false);
    });
    await expect(
      badCsrf.send(scope(), captureFinancialRequest(command(0)), ids.key),
    ).rejects.toMatchObject({ code: "CSRF_UNAVAILABLE", dispatched: false });
    expect(fetcher).not.toHaveBeenCalled();
  });
});

it.each([
  "paymentRecord",
  "creditApply",
  "creditReverse",
  "creditApplicationReverse",
  "receiptReprint",
] as const)(
  "TEST-FE-319 refuses successful replies with mismatched command consequences for %s",
  async (operation) => {
    const input = commands.find((value) => value.operation === operation);
    if (!input) throw new Error();
    const fetcher = vi.fn<typeof fetch>((_url, init) =>
      Promise.resolve(
        response(input, init ?? {}, (row) => {
          const data = financialObject(row.data);
          if (operation === "paymentRecord")
            financialObject(data.payment).status = "REVERSED";
          else if (operation === "creditApply") {
            financialObject(data.application).late_payment_charge_id =
              ids.other;
            financialObject(data.application).amount_usd_cents = 101;
          } else if (operation === "creditReverse")
            data.recognition_reversal = null;
          else if (operation === "creditApplicationReverse")
            data.reversal = null;
          else financialObject(data.reprint).receipt_id = ids.other;
        }),
      ),
    );
    await expect(
      createFinancialTransport(fetcher, () => "csrf").send(
        scope(),
        captureFinancialRequest(input),
        ids.key,
      ),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE", dispatched: true });
  },
);
it("TEST-FE-320 binds filtered Refund recipient identity without inventing a customer field", async () => {
  const input = {
    operation: "refundList" as const,
    target: {},
    query: { customer_id: ids.customer },
  };
  const fetcher = vi.fn<typeof fetch>((_url, init) =>
    Promise.resolve(response(input, init ?? {})),
  );
  expect(
    (
      await createFinancialTransport(fetcher).send(
        scope(),
        captureFinancialRequest(input),
      )
    ).data,
  ).toEqual(fixture("refundList").data);
});

describe("989d934 error correlation regression", () => {
  it.each(["json", "utf8", "contract"])(
    "TEST-FE-326 preserves local correlation and observed status after invalid %s evidence",
    async (kind) => {
      let requestId: string | null = null;
      const fetcher = vi.fn<typeof fetch>((_url, init) => {
        requestId = new Headers(init?.headers).get("X-Request-ID");
        return Promise.resolve(
          new Response(
            kind === "utf8"
              ? new Uint8Array([0xc3, 0x28])
              : kind === "json"
                ? "{"
                : "{}",
            {
              status: 200,
              headers: {
                "Content-Type": "application/json",
                "X-Request-ID": requestId ?? "",
              },
            },
          ),
        );
      });
      const error: unknown = await createFinancialTransport(fetcher)
        .send(scope(), captureFinancialRequest(read(1)))
        .catch((error: unknown) => error);
      expect(requestId).toBeTruthy();
      expect(error).toMatchObject({
        code: "INVALID_RESPONSE",
        dispatched: true,
        status: 200,
        requestId,
      });
      expect(String(error)).not.toContain("Synthetic secret");
    },
  );
});

describe("shared late-body cleanup regression", () => {
  it.each(["abort", "deadline"])(
    "TEST-FE-353 cancels an inherited financial transport body arriving after %s",
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
      const pending = createFinancialTransport(fetcher).send(
        { ...scope(), signal: controller.signal },
        captureFinancialRequest(read(0)),
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
        streamController?.enqueue(new Uint8Array(FINANCIAL_REPLY_BYTES + 1)),
      ).toThrow();
      expect(fetcher).toHaveBeenCalledOnce();
    },
  );
  it.each(["correlation", "content_type", "content_length"])(
    "TEST-FE-354 cancels an inherited financial body rejected before reader for %s",
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
                ? { "Content-Length": (FINANCIAL_REPLY_BYTES + 1).toString() }
                : {}),
            },
          }),
        ),
      );
      await expect(
        createFinancialTransport(fetcher).send(
          scope(),
          captureFinancialRequest(read(0)),
        ),
      ).rejects.toMatchObject({
        code:
          kind === "content_length" ? "RESPONSE_TOO_LARGE" : "INVALID_RESPONSE",
      });
      expect(cancel).toHaveBeenCalledOnce();
    },
  );
});
