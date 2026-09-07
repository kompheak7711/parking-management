import { describe, expect, it, vi } from "vitest";
import {
  createFinancialRecovery as createRecovery,
  type FinancialAttemptCoordinator,
  decodeFinancialIntent,
} from "./financialRecovery";
import {
  FinancialClientError,
  createFinancialTransport,
  type FinancialTransport,
} from "./financialClient";
import {
  captureFinancialRequest,
  financialObject,
  type FinancialRequest,
} from "./financialContracts";
import { stringifyFinancialJson } from "./financialJson";
import { type OpenIntent, type SealedIntentStore } from "./sealedIntentStore";
import { validateFinancialReply } from "./financialResponse";
import {
  ids,
  commands,
  command,
  fixture,
  paymentBody,
} from "./test/financialFixtures";
function memoryAttemptCoordinator(): FinancialAttemptCoordinator {
  const held = new Set<string>();
  return {
    async run<T>(actorId: string, action: () => Promise<T>): Promise<T | null> {
      if (held.has(actorId)) return null;
      held.add(actorId);
      try {
        return await action();
      } finally {
        held.delete(actorId);
      }
    },
  };
}
const sharedAttempts = memoryAttemptCoordinator();
function createFinancialRecovery(...args: Parameters<typeof createRecovery>) {
  return createRecovery(args[0], args[1], args[2], args[3] ?? sharedAttempts);
}
function scope() {
  return {
    actorId: ids.actor,
    propertyId: ids.property,
    signal: new AbortController().signal,
  };
}
function memory() {
  const records = new Map<string, OpenIntent>();
  const store = {
    read: vi.fn<SealedIntentStore["read"]>((actor) =>
      Promise.resolve().then(() => records.get(actor) ?? null),
    ),
    begin: vi.fn<SealedIntentStore["begin"]>((actor, record) =>
      Promise.resolve().then(() => {
        if (records.has(actor)) throw new Error("Reserved");
        records.set(actor, { ...record });
      }),
    ),
    clear: vi.fn<SealedIntentStore["clear"]>((actor, key) =>
      Promise.resolve().then(() => {
        if (records.get(actor)?.requestKey !== key)
          throw new Error("Mismatched key");
        records.delete(actor);
      }),
    ),
  };
  return { records, store };
}
function success(): FinancialTransport {
  return {
    send: vi.fn<FinancialTransport["send"]>((current, request) =>
      Promise.resolve().then(() =>
        validateFinancialReply(
          fixture(request.operation),
          request,
          current.propertyId,
          ids.key,
        ),
      ),
    ),
  };
}
function unknown(): FinancialTransport {
  return {
    send: vi.fn<FinancialTransport["send"]>(() =>
      Promise.resolve().then(() => {
        throw new FinancialClientError("UNAVAILABLE", true);
      }),
    ),
  };
}
describe("explicit financial recovery", () => {
  it("TEST-FE-305 only loads records without sending and distinguishes actor Property and foreign ownership", async () => {
    const { records, store } = memory(),
      transport = unknown(),
      recovery = createFinancialRecovery(store, transport, () => "csrf"),
      current = scope();
    expect(await recovery.load(current)).toEqual({ kind: "ready" });
    expect(transport.send).not.toHaveBeenCalled();
    expect((await recovery.submit(current, command(0))).kind).toBe("pending");
    expect(transport.send).toHaveBeenCalledOnce();
    expect((await recovery.load(current)).kind).toBe("pending");
    expect(transport.send).toHaveBeenCalledOnce();
    expect(await recovery.load({ ...current, actorId: ids.other })).toEqual({
      kind: "ready",
    });
    expect(await recovery.load({ ...current, propertyId: ids.other })).toEqual({
      kind: "other-property",
      propertyId: ids.property,
    });
    records.set(ids.actor, {
      requestKey: ids.key,
      plaintext:
        '{"key":"' +
        ids.key +
        '","command":{"action":"issue","propertyId":"' +
        ids.property +
        '"}}',
    });
    expect(await recovery.load(current)).toEqual({ kind: "foreign" });
    expect(transport.send).toHaveBeenCalledOnce();
  });
  it.each(commands)(
    "TEST-FE-306 persists before transmission and retires only validated exact-key success for $operation",
    async (input) => {
      const { records, store } = memory(),
        inner = success(),
        current = scope();
      const transport: FinancialTransport = {
        send: vi.fn<FinancialTransport["send"]>(
          async (actual, request, key) => {
            const saved = records.get(ids.actor);
            expect(saved?.requestKey).toBe(key);
            if (!saved) throw new Error();
            const pending = decodeFinancialIntent(saved, ids.actor);
            expect(pending?.wireBody).toBe(request.wireBody);
            expect(saved.plaintext).not.toContain("synthetic-csrf");
            return inner.send(actual, request, key);
          },
        ),
      };
      const result = await createFinancialRecovery(
        store,
        transport,
        () => "synthetic-csrf",
      ).submit(current, input);
      expect(result.kind).toBe("success");
      expect(records.size).toBe(0);
      expect(store.clear).toHaveBeenCalledOnce();
    },
  );
  it("TEST-FE-307 blocks a new command after unknown outcome and explicitly replays original bytes and key", async () => {
    const { records, store } = memory(),
      current = scope(),
      failing = unknown(),
      recovery = createFinancialRecovery(store, failing, () => "csrf");
    const first = await recovery.submit(current, command(6));
    if (first.kind !== "pending") throw new Error();
    const original = records.get(ids.actor);
    if (!original) throw new Error();
    const envelope = JSON.parse(original.plaintext) as Record<string, unknown>;
    envelope.wireBody = ' { "reason" : "Synthetic\\u0020correction" }\n';
    records.set(ids.actor, {
      ...original,
      plaintext: JSON.stringify(envelope),
    });
    expect((await recovery.submit(current, command(0))).kind).toBe("blocked");
    expect(failing.send).toHaveBeenCalledOnce();
    expect((await recovery.replay(current, ids.other)).kind).toBe("blocked");
    expect(failing.send).toHaveBeenCalledOnce();
    const passing = success(),
      retry = createFinancialRecovery(store, passing, () => "csrf");
    expect((await retry.replay(current, first.command.key)).kind).toBe(
      "success",
    );
    expect(passing.send).toHaveBeenCalledWith(
      current,
      expect.objectContaining({
        operation: "creditReverse",
        wireBody: envelope.wireBody,
      }),
      first.command.key,
    );
    expect(records.size).toBe(0);
  });
  it.each([400, 401, 403, 404, 409, 412, 422, 429, 500, 503])(
    "TEST-FE-308 preserves unknown outcome through later HTTP %s and clears only a fresh definitive rejection",
    async (status) => {
      const { records, store } = memory(),
        current = scope();
      const rejected: FinancialTransport = {
        send: vi.fn<FinancialTransport["send"]>(() =>
          Promise.resolve().then(() => {
            throw new FinancialClientError(
              "HTTP_REJECTION",
              true,
              status,
              ids.key,
              [400, 412, 422].includes(status),
            );
          }),
        ),
      };
      const fresh = createFinancialRecovery(store, rejected, () => "csrf");
      expect((await fresh.submit(current, command(0))).kind).toBe(
        [400, 412, 422].includes(status) ? "rejected" : "pending",
      );
      records.clear();
      vi.mocked(store.clear).mockClear();
      const uncertain = await createFinancialRecovery(
        store,
        unknown(),
        () => "csrf",
      ).submit(current, command(0));
      if (uncertain.kind !== "pending") throw new Error();
      expect((await fresh.replay(current, uncertain.command.key)).kind).toBe(
        "pending",
      );
      expect(records.size).toBe(1);
      expect(store.clear).not.toHaveBeenCalled();
    },
  );
  it("TEST-FE-309 preserves corrupt foreign unknown-version and mismatched-key envelopes without dispatch", async () => {
    const { records, store } = memory(),
      current = scope(),
      transport = unknown(),
      recovery = createFinancialRecovery(store, transport, () => "csrf");
    const initial = await recovery.submit(current, command(0));
    if (initial.kind !== "pending") throw new Error();
    const valid = records.get(ids.actor);
    if (!valid) throw new Error();
    const row = JSON.parse(valid.plaintext) as Record<string, unknown>;
    const candidates = [
      '{"invalid"',
      JSON.stringify({ ...row, namespace: "billing" }),
      JSON.stringify({ ...row, version: 2 }),
      JSON.stringify({ ...row, actorId: ids.other }),
      JSON.stringify({ ...row, propertyId: "bad" }),
      JSON.stringify({ ...row, key: ids.other }),
      JSON.stringify({ ...row, path: "/arbitrary" }),
      JSON.stringify({ ...row, operation: "arbitrary" }),
      JSON.stringify({ ...row, wireBody: '{"invalid":true}' }),
    ];
    vi.mocked(transport.send).mockClear();
    for (const plaintext of candidates) {
      records.set(ids.actor, { ...valid, plaintext });
      const before = records.get(ids.actor);
      expect((await recovery.submit(current, command(0))).kind).toBe("blocked");
      expect((await recovery.replay(current, initial.command.key)).kind).toBe(
        "blocked",
      );
      expect(records.get(ids.actor)).toBe(before);
    }
    expect(transport.send).not.toHaveBeenCalled();
    expect(store.clear).not.toHaveBeenCalled();
  });
  it("TEST-FE-310 captures reviewed input before delayed storage and rejects getters without transmission", async () => {
    const { records, store } = memory();
    let release: (() => void) | undefined;
    const original = store.begin;
    store.begin = vi.fn<SealedIntentStore["begin"]>(
      (actor, intent) =>
        new Promise<void>((resolve, reject) => {
          release = () => {
            void original(actor, intent).then(resolve, reject);
          };
        }),
    );
    const transport = unknown(),
      recovery = createFinancialRecovery(store, transport, () => "csrf");
    const input = {
      operation: "paymentRecord" as const,
      target: {},
      body: { ...paymentBody, amount: { currency: "USD", minor_units: 100 } },
    };
    const pending = recovery.submit(scope(), input);
    input.body.amount.minor_units = 999;
    release?.();
    expect((await pending).kind).toBe("pending");
    const saved = records.get(ids.actor);
    if (!saved) throw new Error();
    expect(decodeFinancialIntent(saved, ids.actor)?.wireBody).toContain(
      '"minor_units":100',
    );
    const getter = vi.fn(() => input.body);
    await expect(
      recovery.submit(scope(), {
        operation: "paymentRecord",
        target: {},
        get body() {
          return getter();
        },
      }),
    ).rejects.toThrow();
    expect(getter).not.toHaveBeenCalled();
    expect(transport.send).toHaveBeenCalledOnce();
  });
  it("TEST-FE-311 fails closed on storage admission read or clearance failures and preserves replacement reservations", async () => {
    const { records, store } = memory(),
      transport = success(),
      current = scope();
    store.begin = vi.fn<SealedIntentStore["begin"]>(() =>
      Promise.resolve().then(() => {
        throw new Error("Disk unavailable");
      }),
    );
    store.read = vi.fn<SealedIntentStore["read"]>(() =>
      Promise.resolve().then(() => {
        throw new Error("Disk unavailable");
      }),
    );
    expect(
      await createFinancialRecovery(store, transport, () => "csrf").submit(
        current,
        command(0),
      ),
    ).toEqual({ kind: "blocked", state: { kind: "unavailable" } });
    expect(transport.send).not.toHaveBeenCalled();
    const other = memory();
    const racing: FinancialTransport = {
      send: vi.fn<FinancialTransport["send"]>(async (actual, request, key) => {
        const reply = await transport.send(actual, request, key);
        other.records.set(ids.actor, {
          requestKey: ids.other,
          plaintext: '{"namespace":"other"}',
        });
        return reply;
      }),
    };
    expect(
      (
        await createFinancialRecovery(other.store, racing, () => "csrf").submit(
          current,
          command(0),
        )
      ).kind,
    ).toBe("blocked");
    expect(other.records.get(ids.actor)?.requestKey).toBe(ids.other);
    expect(records.size).toBe(0);
  });
  it("TEST-FE-312 prevents late success after workspace invalidation while preserving durable pending work", async () => {
    const { records, store } = memory();
    const controller = new AbortController();
    const current = { ...scope(), signal: controller.signal };
    const transport: FinancialTransport = {
      send: vi.fn<FinancialTransport["send"]>((_actual, request) =>
        Promise.resolve().then(() => {
          controller.abort();
          return validateFinancialReply(
            fixture(request.operation),
            request,
            ids.property,
            ids.key,
          );
        }),
      ),
    };
    expect(
      await createFinancialRecovery(store, transport, () => "csrf").submit(
        current,
        command(0),
      ),
    ).toEqual({ kind: "invalidated" });
    expect(records.size).toBe(1);
    expect(store.clear).not.toHaveBeenCalled();
  });
  it("TEST-FE-313 rejects missing CSRF invalid requests and mismatched successful evidence before retirement", async () => {
    const { records, store } = memory(),
      transport = success();
    const recovery = createFinancialRecovery(store, transport, () => {
      throw new FinancialClientError("CSRF_UNAVAILABLE", false);
    });
    await expect(recovery.submit(scope(), command(0))).rejects.toThrow();
    expect(store.begin).not.toHaveBeenCalled();
    expect(transport.send).not.toHaveBeenCalled();
    const unsafe: FinancialTransport = {
      send: vi.fn<FinancialTransport["send"]>((_scope, request) =>
        Promise.resolve().then(() => ({
          data: fixture(request.operation).data,
          propertyId: ids.other,
          requestId: ids.key,
        })),
      ),
    };
    expect(
      (
        await createFinancialRecovery(store, unsafe, () => "csrf").submit(
          scope(),
          command(0),
        )
      ).kind,
    ).toBe("pending");
    expect(records.size).toBe(1);
    expect(store.clear).not.toHaveBeenCalled();
    const invalid = {
      ...command(0),
      body: { amount: { currency: "KHR", minor_units: 100 } },
    } as FinancialRequest;
    expect(() => captureFinancialRequest(invalid)).toThrow();
    expect(stringifyFinancialJson({ amount: 100n })).toBe('{"amount":100}');
  });
});

describe("989d934 independent review regressions", () => {
  it.each(["USD", "KHR"] as const)(
    "TEST-FE-322 accepts actual %s confirmation shape and retires original exact key",
    async (currency) => {
      const { store, records } = memory(),
        current = scope();
      const input: FinancialRequest =
        currency === "USD"
          ? command(0)
          : {
              operation: "paymentRecord",
              target: {},
              body: {
                ...paymentBody,
                amount: { currency: "KHR", minor_units: 4020 },
                usd_accounting_amount: { currency: "USD", minor_units: 100 },
              },
            };
      const makeReply = (init: RequestInit): Response => {
        const row = fixture("paymentRecord"),
          data = financialObject(row.data);
        delete data.position;
        data.receipt = {
          id: ids.receipt,
          payment_id: ids.payment,
          receipt_number: "R-SYNTHETIC",
          issued_at: "2026-09-01T12:00:00+00:00",
        };
        data.received_at = "2026-09-01T05:00:00+00:00";
        data.evidence_reference = "Synthetic receipt";
        data.property_timezone = "Asia/Phnom_Penh";
        const payment = financialObject(data.payment);
        payment.received_currency = currency;
        payment.received_amount_minor = currency === "KHR" ? 4020 : 100;
        if (currency === "KHR")
          data.exchange_rate_record = {
            id: ids.event,
            reference_rate_khr_per_usd: "4000.000000",
            system_rate_khr_per_usd: 4020,
            final_khr_payable: 4020,
          };
        const requestId = new Headers(init.headers).get("X-Request-ID") ?? "";
        row.meta.request_id = requestId;
        return new Response(stringifyFinancialJson(row), {
          status: 201,
          headers: {
            "Content-Type": "application/json",
            "X-Request-ID": requestId,
          },
        });
      };
      const fetcher = vi.fn<typeof fetch>((_url, init) =>
        Promise.resolve(makeReply(init ?? {})),
      );
      const recovery = createFinancialRecovery(
        store,
        createFinancialTransport(fetcher, () => "csrf"),
        () => "csrf",
      );
      expect((await recovery.submit(current, input)).kind).toBe("success");
      expect(records.size).toBe(0);
      vi.mocked(store.clear).mockClear();
      fetcher.mockRejectedValueOnce(new Error("Synthetic lost reply"));
      const pending = await recovery.submit(current, input);
      if (pending.kind !== "pending")
        throw new Error("Expected saved unknown outcome");
      const original = records.get(ids.actor);
      expect((await recovery.replay(current, pending.command.key)).kind).toBe(
        "success",
      );
      expect(store.clear).toHaveBeenCalledWith(ids.actor, original?.requestKey);
      const first = fetcher.mock.calls[1]?.[1],
        replay = fetcher.mock.calls[2]?.[1];
      expect(replay?.body).toBe(first?.body);
      expect(new Headers(replay?.headers).get("Idempotency-Key")).toBe(
        new Headers(first?.headers).get("Idempotency-Key"),
      );
      expect(records.size).toBe(0);
    },
  );

  it("TEST-FE-323 excludes a competing replay while an initial attempt can still reject", async () => {
    const { store, records } = memory(),
      current = scope();
    let rejectInitial: (error: Error) => void = () => {
      throw new Error("Initial not started");
    };
    const initialTransport: FinancialTransport = {
      send: vi.fn<FinancialTransport["send"]>(
        () =>
          new Promise((_resolve, reject) => {
            rejectInitial = reject;
          }),
      ),
    };
    const replayTransport = unknown();
    const first = createFinancialRecovery(
      store,
      initialTransport,
      () => "csrf",
    ).submit(current, command(0));
    await vi.waitFor(() => {
      expect(initialTransport.send).toHaveBeenCalledOnce();
    });
    const key = records.get(ids.actor)?.requestKey;
    if (!key) throw new Error("Expected reserved command");
    const second = await createFinancialRecovery(
      store,
      replayTransport,
      () => "csrf",
    ).replay(current, key);
    rejectInitial(
      new FinancialClientError("HTTP_REJECTION", true, 422, ids.key, true),
    );
    const completed = await first;
    expect(second.kind).toBe("blocked");
    expect(replayTransport.send).not.toHaveBeenCalled();
    expect(completed.kind).toBe("rejected");
    expect(records.size).toBe(0);
  });

  it.each(["refundReturn", "refundReturnReverse"] as const)(
    "TEST-FE-324 keeps %s unresolved when a successful reply has no correction",
    async (operation) => {
      const { store, records } = memory(),
        current = scope();
      const input = commands.find((entry) => entry.operation === operation);
      if (!input) throw new Error("Missing command");
      const transport: FinancialTransport = {
        send: () =>
          Promise.resolve({
            data: fixture("refundGet").data,
            requestId: ids.key,
            propertyId: ids.property,
          }),
      };
      const recovery = createFinancialRecovery(store, transport, () => "csrf");
      const first = await recovery.submit(current, input);
      expect(first.kind).toBe("pending");
      if (first.kind !== "pending")
        throw new Error("Missing correction must remain pending");
      expect((await recovery.replay(current, first.command.key)).kind).toBe(
        "pending",
      );
      expect(records.size).toBe(1);
      expect(store.clear).not.toHaveBeenCalled();
    },
  );

  it("TEST-FE-325 dispatches an admitted large allocation and replays identical original bytes", async () => {
    const details = Array.from({ length: 30 }, () => ({
      invoice_line_id: ids.invoice,
      amount_usd_cents: 1,
    }));
    const targets = Array.from({ length: 100 }, () => ({
      invoice_id: ids.invoice,
      amount_usd_cents: 30,
      details,
    }));
    const input: FinancialRequest = {
      operation: "allocationPost",
      target: { id: ids.payment },
      body: {
        intent: {
          mode: "PROPOSAL",
          proposal: { payment_id: ids.payment, targets },
        },
      },
    };
    const request = captureFinancialRequest(input);
    expect(
      new TextEncoder().encode(request.wireBody ?? "").length,
    ).toBeLessThan(262144);
    expect(
      new TextEncoder().encode(stringifyFinancialJson(request, 1048576)).length,
    ).toBeGreaterThan(262144);
    const { store, records } = memory(),
      current = scope();
    const fetcher = vi
      .fn<typeof fetch>()
      .mockRejectedValueOnce(new Error("Synthetic uncertain response"))
      .mockImplementation((_url, init) => {
        const row = fixture("allocationPost"),
          requestId = new Headers(init?.headers).get("X-Request-ID") ?? "";
        row.meta.request_id = requestId;
        return Promise.resolve(
          new Response(stringifyFinancialJson(row), {
            status: 201,
            headers: {
              "Content-Type": "application/json",
              "X-Request-ID": requestId,
            },
          }),
        );
      });
    const recovery = createFinancialRecovery(
      store,
      createFinancialTransport(fetcher, () => "csrf"),
      () => "csrf",
    );
    const first = await recovery.submit(current, input);
    expect(fetcher).toHaveBeenCalledOnce();
    if (first.kind !== "pending") throw new Error("Expected unknown outcome");
    expect((await recovery.replay(current, first.command.key)).kind).toBe(
      "success",
    );
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher.mock.calls[0]?.[1]?.body).toBe(request.wireBody);
    expect(fetcher.mock.calls[1]?.[1]?.body).toBe(request.wireBody);
    expect(records.size).toBe(0);
  });
});

describe("correction attempt coordination and consequence evidence", () => {
  it("TEST-FE-327 fails closed when shared coordination is unavailable without dispatch or deleting existing intent", async () => {
    const { store, records } = memory(),
      current = scope(),
      transport = unknown();
    const unavailable: FinancialAttemptCoordinator = {
      run: () => Promise.reject(new Error("Synthetic coordination failure")),
    };
    const blocked = createFinancialRecovery(
      store,
      transport,
      () => "csrf",
      unavailable,
    );
    expect(await blocked.submit(current, command(0))).toEqual({
      kind: "blocked",
      state: { kind: "unavailable" },
    });
    expect(store.begin).not.toHaveBeenCalled();
    expect(transport.send).not.toHaveBeenCalled();
    const pending = await createFinancialRecovery(
      store,
      unknown(),
      () => "csrf",
    ).submit(current, command(0));
    if (pending.kind !== "pending") throw new Error();
    expect((await blocked.replay(current, pending.command.key)).kind).toBe(
      "blocked",
    );
    expect(records.size).toBe(1);
    expect(store.clear).not.toHaveBeenCalled();
  });
  it.each(["refundReturn", "refundReturnReverse"] as const)(
    "TEST-FE-328 binds %s correction identity value and evidence before retirement",
    async (operation) => {
      const input = commands.find((entry) => entry.operation === operation);
      if (!input) throw new Error();
      const mutations: Record<string, string | number> =
        operation === "refundReturn"
          ? {
              refund_id: ids.other,
              correction_kind: "CORRECTION_REVERSAL",
              verified_return_amount_minor: 99,
              verified_return_currency: "KHR",
              verified_returned_at: "2026-09-01T12:00:00.000001Z",
              return_method_reference: "Other method",
              source_balance_effect_usd_cents: 99,
              source_balance_effect_original_minor: 99,
              previous_net_refund_usd_cents: 99,
              resulting_net_refund_usd_cents: 1,
              reverses_correction_id: ids.other,
              reason: "Other reason",
              evidence_reference: "Other evidence",
            }
          : {
              refund_id: ids.other,
              correction_kind: "VALUE_CORRECTION",
              reverses_correction_id: ids.other,
              source_balance_effect_usd_cents: 100,
              source_balance_effect_original_minor: -99,
              previous_net_refund_usd_cents: 1,
              resulting_net_refund_usd_cents: 99,
              verified_return_currency: "USD",
              reason: "Other reason",
              evidence_reference: "Other evidence",
            };
      for (const [field, value] of Object.entries(mutations)) {
        const { store, records } = memory(),
          current = scope();
        const transport: FinancialTransport = {
          send: () => {
            const row = fixture(operation),
              data = financialObject(row.data);
            const items = financialObject(data.corrections).items;
            if (!Array.isArray(items)) throw new Error();
            financialObject(items[0])[field] = value;
            return Promise.resolve({
              data,
              propertyId: ids.property,
              requestId: ids.key,
            });
          },
        };
        const recovery = createFinancialRecovery(
          store,
          transport,
          () => "csrf",
        );
        const result = await recovery.submit(current, input);
        expect(result.kind, field).toBe("pending");
        if (result.kind !== "pending") throw new Error();
        expect(
          (await recovery.replay(current, result.command.key)).kind,
          field,
        ).toBe("pending");
        expect(records.size).toBe(1);
        expect(store.clear).not.toHaveBeenCalled();
      }
    },
  );
});

describe("Refund correction payout bounds", () => {
  const cases = [
    ["refundReturn", 200n, 100n, 100n],
    ["refundReturn", 201n, 100n, 101n],
    ["refundReturnReverse", 0n, -200n, 200n],
    ["refundReturnReverse", 101n, -100n, 201n],
  ] as const;
  it.each(
    cases.flatMap(([operation, previous, effect, resulting]) =>
      [false, true].map((lost) => ({
        operation,
        previous,
        effect,
        resulting,
        lost,
      })),
    ),
  )(
    "TEST-FE-330 keeps impossible $operation payout transition $previous/$resulting pending after lost=$lost",
    async ({ operation, previous, effect, resulting, lost }) => {
      const { store, records } = memory(),
        current = scope();
      const input = commands.find((entry) => entry.operation === operation);
      if (!input) throw new Error("Missing correction command");
      const fetcher = vi.fn<typeof fetch>((_url, init) => {
        const reply = fixture(operation),
          data = financialObject(reply.data);
        const items = financialObject(data.corrections).items;
        if (!Array.isArray(items)) throw new Error("Missing corrections");
        const event = financialObject(items[0]);
        event.previous_net_refund_usd_cents = previous;
        event.source_balance_effect_usd_cents = effect;
        event.source_balance_effect_original_minor = effect;
        event.resulting_net_refund_usd_cents = resulting;
        data.net_refund_usd_cents = resulting;
        const requestId = new Headers(init?.headers).get("X-Request-ID");
        if (!requestId) throw new Error("Missing correlation");
        reply.meta.request_id = requestId;
        return Promise.resolve(
          new Response(stringifyFinancialJson(reply), {
            status: 200,
            headers: {
              "Content-Type": "application/json",
              "X-Request-ID": requestId,
            },
          }),
        );
      });
      if (lost)
        fetcher.mockRejectedValueOnce(
          new Error("Synthetic lost original reply"),
        );
      const recovery = createFinancialRecovery(
        store,
        createFinancialTransport(fetcher, () => "csrf"),
        () => "csrf",
      );
      const first = await recovery.submit(current, input);
      expect(first.kind).toBe("pending");
      if (first.kind !== "pending")
        throw new Error("Impossible payout must remain unresolved");
      const original = records.get(ids.actor);
      expect((await recovery.replay(current, first.command.key)).kind).toBe(
        "pending",
      );
      expect(records.get(ids.actor)).toEqual(original);
      expect(records.size).toBe(1);
      expect(store.clear).not.toHaveBeenCalled();
      expect(fetcher).toHaveBeenCalledTimes(2);
      const initial = fetcher.mock.calls[0]?.[1],
        replay = fetcher.mock.calls[1]?.[1];
      expect(replay?.body).toBe(initial?.body);
      expect(new Headers(initial?.headers).get("Idempotency-Key")).toBe(
        first.command.key,
      );
      expect(new Headers(replay?.headers).get("Idempotency-Key")).toBe(
        first.command.key,
      );
    },
  );

  it.each(
    (["refundReturn", "refundReturnReverse"] as const).flatMap((operation) =>
      [1n, 100n, 9_000_000_000_000_000n].map((payout) => ({
        operation,
        payout,
      })),
    ),
  )(
    "TEST-FE-331 accepts exact $operation payout boundary $payout on original and explicit replay",
    async ({ operation, payout }) => {
      const { store, records } = memory(),
        current = scope();
      const template = commands.find((entry) => entry.operation === operation);
      if (!template || !("body" in template))
        throw new Error("Missing correction command");
      const input = {
        ...template,
        body: {
          ...financialObject(template.body),
          ...(operation === "refundReturn"
            ? { returned_amount_minor: payout }
            : {}),
        },
      };
      const fetcher = vi.fn<typeof fetch>((_url, init) => {
        const reply = fixture(operation),
          data = financialObject(reply.data);
        financialObject(data.refund).refund_amount_minor = payout;
        const items = financialObject(data.corrections).items;
        if (!Array.isArray(items)) throw new Error("Missing corrections");
        const event = financialObject(items[0]),
          returning = operation === "refundReturn";
        event.previous_net_refund_usd_cents = returning ? payout : 0n;
        event.source_balance_effect_usd_cents = returning ? payout : -payout;
        event.source_balance_effect_original_minor = returning
          ? payout
          : -payout;
        event.resulting_net_refund_usd_cents = returning ? 0n : payout;
        data.net_refund_usd_cents = returning ? 0n : payout;
        if (returning) event.verified_return_amount_minor = payout;
        const requestId = new Headers(init?.headers).get("X-Request-ID");
        if (!requestId) throw new Error("Missing correlation");
        reply.meta.request_id = requestId;
        return Promise.resolve(
          new Response(stringifyFinancialJson(reply), {
            status: 200,
            headers: {
              "Content-Type": "application/json",
              "X-Request-ID": requestId,
            },
          }),
        );
      });
      const recovery = createFinancialRecovery(
        store,
        createFinancialTransport(fetcher, () => "csrf"),
        () => "csrf",
      );
      expect((await recovery.submit(current, input)).kind).toBe("success");
      expect(records.size).toBe(0);
      store.clear.mockClear();
      fetcher.mockRejectedValueOnce(new Error("Synthetic lost original reply"));
      const pending = await recovery.submit(current, input);
      if (pending.kind !== "pending")
        throw new Error("Expected unknown outcome");
      expect((await recovery.replay(current, pending.command.key)).kind).toBe(
        "success",
      );
      expect(store.clear).toHaveBeenCalledExactlyOnceWith(
        ids.actor,
        pending.command.key,
      );
      expect(records.size).toBe(0);
      const original = fetcher.mock.calls[1]?.[1],
        replay = fetcher.mock.calls[2]?.[1];
      expect(replay?.body).toBe(original?.body);
      expect(new Headers(replay?.headers).get("Idempotency-Key")).toBe(
        pending.command.key,
      );
    },
  );
});

it.each(
  (["refundReturn", "refundReturnReverse"] as const).flatMap((operation) =>
    [9_000_000_000_000_001n, 9_223_372_036_854_775_807n].map((payout) => ({
      operation,
      payout,
    })),
  ),
)(
  "TEST-FE-332 retains $operation correction with unsupported original payout $payout",
  async ({ operation, payout }) => {
    const { store, records } = memory(),
      current = scope();
    const input = commands.find((entry) => entry.operation === operation);
    if (!input) throw new Error("Missing correction command");
    const transport: FinancialTransport = {
      send: () => {
        const data = financialObject(fixture(operation).data);
        financialObject(data.refund).refund_amount_minor = payout;
        return Promise.resolve({
          data,
          propertyId: ids.property,
          requestId: ids.key,
        });
      },
    };
    const recovery = createFinancialRecovery(store, transport, () => "csrf");
    const first = await recovery.submit(current, input);
    expect(first.kind).toBe("pending");
    if (first.kind !== "pending")
      throw new Error("Impossible original payout must remain pending");
    const original = records.get(ids.actor);
    expect((await recovery.replay(current, first.command.key)).kind).toBe(
      "pending",
    );
    expect(records.get(ids.actor)).toEqual(original);
    expect(store.clear).not.toHaveBeenCalled();
  },
);
