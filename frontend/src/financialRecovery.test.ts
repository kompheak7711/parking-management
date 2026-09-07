import { describe, expect, it, vi } from "vitest";
import {
  createFinancialRecovery,
  decodeFinancialIntent,
} from "./financialRecovery";
import {
  FinancialClientError,
  type FinancialTransport,
} from "./financialClient";
import {
  captureFinancialRequest,
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
