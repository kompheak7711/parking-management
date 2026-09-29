import { afterEach, describe, expect, it, vi } from "vitest";
import {
  FINANCIAL_OPERATIONS,
  captureFinancialRequest,
  captureWireRequest,
  financialObject,
  financialPath,
  isFinancialCommand,
  isFinancialPreview,
  type FinancialObject,
  type FinancialPreviewOperation,
} from "./financialContracts";
import {
  createFinancialTransport,
  FINANCIAL_DEADLINE_MS,
  FinancialClientError,
  readFinancial,
} from "./financialClient";
import {
  createFinancialRecovery,
  decodeFinancialIntent,
} from "./financialRecovery";
import type { SealedIntentStore } from "./sealedIntentStore";
import type { FinancialReadRequest } from "./financialUi";
import { readFinancialRecord } from "./financialUiContext";
import { stringifyFinancialJson } from "./financialJson";
import { fixture, ids } from "./test/financialFixtures";

const operations: FinancialPreviewOperation[] = [
  "allocationPreview",
  "creditPreview",
];
const scope = () => ({
  actorId: ids.actor,
  propertyId: ids.property,
  signal: new AbortController().signal,
});
function sample(operation: FinancialPreviewOperation, invoice = false) {
  const data = financialObject(fixture(operation).data);
  const selected: FinancialObject = invoice
    ? {
        invoice_id: ids.invoice,
        amount_usd_cents: 100,
        details: [{ invoice_line_id: ids.other, amount_usd_cents: 100 }],
      }
    : { late_payment_charge_id: ids.invoice, amount_usd_cents: 100 };
  const target: FinancialObject = invoice
    ? {
        ...selected,
        invoice_version: 1,
        details: [
          {
            invoice_line_id: ids.other,
            amount_usd_cents: 100,
            due_attribution: {
              basis: "EARLIEST_DUE",
              parts: [
                {
                  source_kind: "ORIGINAL_LINE",
                  source_id: ids.other,
                  approved_due_date: "2026-09-01",
                  source_occurred_at: "2026-08-01T01:02:03.456789Z",
                  outstanding_usd_cents: 9223372036854775807n,
                  amount_usd_cents: 100,
                },
              ],
            },
          },
        ],
      }
    : { ...selected };
  const base = {
    mode: "DESIGNATED",
    designation_reference: "Synthetic customer choice",
  };
  const intent: FinancialObject =
    operation === "allocationPreview"
      ? { ...base, targets: [selected] }
      : { ...base, ...selected };
  data.intent =
    operation === "allocationPreview"
      ? { ...base, targets: [target] }
      : { ...base, ...target };
  data.part_count = invoice ? 1 : 0;
  const body: FinancialObject =
    operation === "allocationPreview"
      ? { intent }
      : { currency: "USD", intent };
  const input: FinancialReadRequest = {
    operation,
    target: {
      id: operation === "allocationPreview" ? ids.payment : ids.credit,
    },
    body,
  };
  return { input, data, intent, target };
}
function response(
  data: FinancialObject,
  init: RequestInit,
  status = 200,
  change?: (envelope: FinancialObject) => void,
) {
  const requestId = new Headers(init.headers).get("X-Request-ID") ?? "";
  const envelope: FinancialObject = {
    data,
    meta: { property_id: ids.property, request_id: requestId },
  };
  change?.(envelope);
  return new Response(stringifyFinancialJson(envelope), {
    status,
    headers: { "Content-Type": "application/json", "X-Request-ID": requestId },
  });
}
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});
describe("explicit POST preview reads", () => {
  it.each(
    operations.flatMap((operation) =>
      [false, true].map((invoice) => ({ operation, invoice })),
    ),
  )(
    "TEST-FE-1055-TRANSPORT-1 captures and transmits $operation invoice=$invoice as a scoped read",
    async ({ operation, invoice }) => {
      const { input, data } = sample(operation, invoice),
        request = captureFinancialRequest(input);
      expect(isFinancialPreview(operation)).toBe(true);
      expect(isFinancialCommand(operation)).toBe(false);
      expect(FINANCIAL_OPERATIONS[operation][0]).toBe("POST");
      expect(FINANCIAL_OPERATIONS[operation][2]).toBe(200);
      expect(request.wireBody).not.toBeNull();
      expect(request.query).toEqual({});
      const csrf = vi.fn(() => "synthetic-csrf"),
        fetcher = vi.fn<typeof fetch>((_url, init) =>
          Promise.resolve(response(data, init ?? {})),
        );
      const reply = await readFinancial(
        scope(),
        input,
        createFinancialTransport(fetcher, csrf),
      );
      expect(reply.data).toEqual(data);
      expect(fetcher).toHaveBeenCalledTimes(1);
      expect(csrf).toHaveBeenCalledTimes(1);
      const [url, options] = fetcher.mock.calls[0] ?? [];
      if (!options) throw new Error("Missing request");
      expect(url).toBe(financialPath(request, ids.property));
      expect(url).toBe(
        operation === "allocationPreview"
          ? `/api/v1/payments/${ids.payment}/allocation-preview`
          : `/api/v1/customer-credits/${ids.credit}/application-preview`,
      );
      expect(options).toMatchObject({
        method: "POST",
        credentials: "include",
        cache: "no-store",
        redirect: "error",
        body: request.wireBody,
      });
      const headers = new Headers(options.headers);
      expect(headers.get("Idempotency-Key")).toBeNull();
      expect(headers.get("Content-Type")).toBe("application/json");
      expect(headers.get("X-CSRF-Token")).toBe("synthetic-csrf");
      expect(headers.get("X-Financial-Property-ID")).toBe(ids.property);
      expect(headers.get("X-Billing-Actor-ID")).toBe(ids.actor);
      expect(reply.requestId).toBe(headers.get("X-Request-ID"));
    },
  );
  it.each(operations)(
    "TEST-FE-1055-TRANSPORT-2 preserves captured bytes and uses the existing UI read helper for %s",
    async (operation) => {
      const { input, data, intent } = sample(operation);
      const request = captureFinancialRequest(input),
        raw = request.wireBody;
      const fetcher = vi.fn<typeof fetch>((_url, init) =>
          Promise.resolve(response(data, init ?? {})),
        ),
        transport = createFinancialTransport(fetcher, () => "synthetic-csrf");
      intent.designation_reference = "Changed after capture";
      await transport.send(scope(), request);
      expect(fetcher.mock.calls[0]?.[1]?.body).toBe(raw);
      intent.designation_reference = "Synthetic customer choice";
      const reply = await readFinancialRecord(scope(), input, transport);
      expect(reply.data).toEqual(data);
      expect(fetcher).toHaveBeenCalledTimes(2);
    },
  );
  it.each(
    operations.flatMap((operation) =>
      ["query", "both_body_forms", "no_body", "target", "computed", "mode"].map(
        (reason) => ({ operation, reason }),
      ),
    ),
  )(
    "TEST-FE-1055-TRANSPORT-3 rejects ambiguous $operation capture $reason",
    ({ operation, reason }) => {
      const { input, intent } = sample(operation);
      const row: FinancialObject = { ...input };
      if (reason === "query") row.query = {};
      if (reason === "both_body_forms")
        row.wireBody = stringifyFinancialJson(row.body);
      if (reason === "no_body") delete row.body;
      if (reason === "target") row.target = { id: "../other" };
      if (reason === "computed") intent.invoice_version = 1;
      if (reason === "mode") intent.mode = "PROPOSAL";
      expect(() => captureWireRequest(row)).toThrow();
    },
  );
  it.each(
    operations.flatMap((operation) =>
      ["key", "csrf", "aborted"].map((reason) => ({ operation, reason })),
    ),
  )(
    "TEST-FE-1055-TRANSPORT-4 stops $operation before dispatch for $reason",
    async ({ operation, reason }) => {
      const { input } = sample(operation),
        fetcher = vi.fn<typeof fetch>(),
        controller = new AbortController();
      if (reason === "aborted") controller.abort();
      const csrf = () => {
        if (reason === "csrf")
          throw new FinancialClientError("CSRF_UNAVAILABLE", false);
        return "synthetic-csrf";
      };
      const transport = createFinancialTransport(fetcher, csrf);
      await expect(
        transport.send(
          { ...scope(), signal: controller.signal },
          captureFinancialRequest(input),
          reason === "key" ? ids.key : undefined,
        ),
      ).rejects.toMatchObject({
        code:
          reason === "key"
            ? "INVALID_REQUEST"
            : reason === "csrf"
              ? "CSRF_UNAVAILABLE"
              : "WORKSPACE_INVALIDATED",
        dispatched: false,
      });
      expect(fetcher).not.toHaveBeenCalled();
    },
  );
  it.each(
    operations.flatMap((operation) =>
      [
        "property",
        "source",
        "selection",
        "amount",
        "count",
        "version",
        "date",
        "meta",
        "request_id",
        "status",
      ].map((reason) => ({ operation, reason })),
    ),
  )(
    "TEST-FE-1055-TRANSPORT-5 rejects altered $operation reply $reason",
    async ({ operation, reason }) => {
      const { input, data, target } = sample(operation, true);
      if (reason === "property") data.property_id = ids.other;
      if (reason === "source")
        data[operation === "allocationPreview" ? "payment_id" : "credit_id"] =
          ids.other;
      if (reason === "selection") target.invoice_id = ids.other;
      if (reason === "amount") data.amount_usd_cents = 99;
      if (reason === "count") data.part_count = 0;
      if (reason === "version") target.invoice_version = 0;
      if (reason === "date") {
        if (!Array.isArray(target.details)) throw new Error("Missing details");
        const due = financialObject(
          financialObject(target.details[0]).due_attribution,
        );
        if (!Array.isArray(due.parts)) throw new Error("Missing parts");
        financialObject(due.parts[0]).approved_due_date = "2026-02-30";
      }
      // Credit embeds scalar fields at the top level; preserve the mutated target there.
      if (operation === "creditPreview")
        Object.assign(financialObject(data.intent), target);
      const fetcher = vi.fn<typeof fetch>((_url, init) =>
        Promise.resolve(
          response(
            data,
            init ?? {},
            reason === "status" ? 201 : 200,
            (envelope) => {
              if (reason === "meta")
                financialObject(envelope.meta).property_id = ids.other;
              if (reason === "request_id")
                financialObject(envelope.meta).request_id = ids.other;
            },
          ),
        ),
      );
      await expect(
        readFinancial(
          scope(),
          input,
          createFinancialTransport(fetcher, () => "synthetic-csrf"),
        ),
      ).rejects.toMatchObject({ code: "INVALID_RESPONSE", dispatched: true });
      expect(fetcher).toHaveBeenCalledTimes(1);
    },
  );
  const errors = [
    { status: 400, code: "BAD_REQUEST" },
    { status: 401, code: "UNAUTHORIZED" },
    { status: 403, code: "FORBIDDEN" },
    { status: 404, code: "NOT_FOUND" },
    { status: 409, code: "CONFLICT" },
    { status: 422, code: "VALIDATION_ERROR" },
    { status: 503, code: "SERVICE_UNAVAILABLE" },
  ];
  it.each(
    operations.flatMap((operation) =>
      errors.map((error) => ({ operation, ...error })),
    ),
  )(
    "TEST-FE-1055-TRANSPORT-6 maps $operation HTTP$status without retry or command identity",
    async ({ operation, status, code }) => {
      const { input } = sample(operation);
      const fetcher = vi.fn<typeof fetch>((_url, init) => {
        const requestId = new Headers(init?.headers).get("X-Request-ID") ?? "";
        return Promise.resolve(
          new Response(
            stringifyFinancialJson({
              error: { code, message: "Synthetic unavailable preview" },
              meta: { request_id: requestId },
            }),
            {
              status,
              headers: {
                "Content-Type": "application/json",
                "X-Request-ID": requestId,
              },
            },
          ),
        );
      });
      await expect(
        readFinancial(
          scope(),
          input,
          createFinancialTransport(fetcher, () => "synthetic-csrf"),
        ),
      ).rejects.toMatchObject({
        code: "HTTP_REJECTION",
        status,
        dispatched: true,
      });
      expect(fetcher).toHaveBeenCalledTimes(1);
      expect(
        new Headers(fetcher.mock.calls[0]?.[1]?.headers).get("Idempotency-Key"),
      ).toBeNull();
    },
  );
  it.each(
    operations.flatMap((operation) =>
      ["timeout", "abort"].map((reason) => ({ operation, reason })),
    ),
  )(
    "TEST-FE-1055-TRANSPORT-7 bounds in-flight $operation $reason without retry",
    async ({ operation, reason }) => {
      vi.useFakeTimers();
      const { input } = sample(operation),
        controller = new AbortController();
      const fetcher = vi.fn<typeof fetch>(
        () =>
          new Promise<Response>(() => {
            // Remain unresolved to exercise the existing deadline and abort handlers.
          }),
      );
      const sent = readFinancial(
        { ...scope(), signal: controller.signal },
        input,
        createFinancialTransport(fetcher, () => "synthetic-csrf"),
      );
      const observed = expect(sent).rejects.toMatchObject({
        code: reason === "abort" ? "WORKSPACE_INVALIDATED" : "UNAVAILABLE",
        dispatched: true,
      });
      if (reason === "abort") controller.abort();
      else await vi.advanceTimersByTimeAsync(FINANCIAL_DEADLINE_MS);
      await observed;
      expect(fetcher).toHaveBeenCalledTimes(1);
      expect(fetcher.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
      expect(vi.getTimerCount()).toBe(0);
    },
  );
  it.each(operations)(
    "TEST-FE-1055-TRANSPORT-8 refuses direct and stored command recovery for %s",
    async (operation) => {
      const { input } = sample(operation),
        request = captureFinancialRequest(input),
        fetcher = vi.fn<typeof fetch>();
      const store = {
        read: vi.fn<SealedIntentStore["read"]>(() => Promise.resolve(null)),
        begin: vi.fn<SealedIntentStore["begin"]>(() => Promise.resolve()),
        clear: vi.fn<SealedIntentStore["clear"]>(() => Promise.resolve()),
      };
      const csrf = vi.fn(() => "synthetic-csrf"),
        recovery = createFinancialRecovery(
          store,
          createFinancialTransport(fetcher, csrf),
          csrf,
        );
      await expect(recovery.submit(scope(), input)).rejects.toThrow();
      expect(store.read).not.toHaveBeenCalled();
      expect(store.begin).not.toHaveBeenCalled();
      expect(store.clear).not.toHaveBeenCalled();
      expect(fetcher).not.toHaveBeenCalled();
      expect(csrf).not.toHaveBeenCalled();
      const plaintext = stringifyFinancialJson({
        namespace: "property-rental.financial-command",
        version: 1,
        actorId: ids.actor,
        propertyId: ids.property,
        key: ids.key,
        operation,
        target: request.target,
        wireBody: request.wireBody,
      });
      expect(() =>
        decodeFinancialIntent({ plaintext, requestKey: ids.key }, ids.actor),
      ).toThrow();
    },
  );
  it("TEST-FE-1055-TRANSPORT-9 keeps every other operation classified by its original method", () => {
    for (const operation of Object.keys(
      FINANCIAL_OPERATIONS,
    ) as (keyof typeof FINANCIAL_OPERATIONS)[]) {
      if (isFinancialPreview(operation)) continue;
      expect(isFinancialCommand(operation)).toBe(
        FINANCIAL_OPERATIONS[operation][0] === "POST",
      );
    }
  });
});
