import { describe, expect, it, vi } from "vitest";
import {
  createFinancialTransport,
  FinancialClientError,
  type FinancialTransport,
} from "./financialClient";
import { financialObject } from "./financialContracts";
import {
  createFinancialRecovery,
  decodeFinancialIntent,
} from "./financialRecovery";
import { stringifyFinancialJson } from "./financialJson";
import { commands as financeCommands } from "./test/financialFixtures";
import {
  commands,
  commandResponse,
  ids,
  memory,
  scope,
  caseRecord,
} from "./test/leaseEnforcementFixtures";

describe("Lease enforcement original-command recovery", () => {
  it("TEST-FE-600 retains a lost case-opening reply through VOID and replays exact bytes and original request metadata", async () => {
    const saved = memory(),
      request = commands[1];
    if (!request) throw new Error();
    let original: Response | null = null,
      lost = true;
    const fetcher = vi.fn<typeof fetch>(async (_url, init) => {
      original ??= commandResponse("rentNonpaymentOpen", init);
      if (lost) throw new FinancialClientError("UNAVAILABLE", true);
      return Promise.resolve(original.clone());
    });
    const recovery = createFinancialRecovery(
      saved.store,
      createFinancialTransport(fetcher, () => "csrf"),
      () => "csrf",
      saved.attempts,
    );
    const first = await recovery.submit(scope(), request);
    if (first.kind !== "pending") throw new Error();
    const frozen = saved.records.get(ids.actor);
    expect(frozen).toBeDefined();
    expect((await recovery.submit(scope(), request)).kind).toBe("blocked");
    expect(fetcher).toHaveBeenCalledOnce();
    expect(
      financialObject(
        financialObject(caseRecord(true).assessment).remaining_rent,
      ).minor_units,
    ).toBe(0);
    lost = false;
    const reply = await recovery.replay(scope(), first.command.key);
    expect(reply.kind).toBe("success");
    if (reply.kind !== "success") throw new Error();
    expect(
      financialObject(
        financialObject(financialObject(reply.reply.data).assessment)
          .remaining_rent,
      ).minor_units,
    ).toBe(80000);
    expect(reply.reply.requestId).toBe(first.command.key);
    expect(saved.records.size).toBe(0);
    const [initial, retry] = fetcher.mock.calls;
    expect(initial?.[0]).toBe(retry?.[0]);
    expect(initial?.[1]?.body).toBe(retry?.[1]?.body);
    expect(new Headers(initial?.[1]?.headers).get("X-Request-ID")).toBe(
      new Headers(retry?.[1]?.headers).get("X-Request-ID"),
    );
  });
  it("TEST-FE-601 shares actor reservations across recovery instances and preserves a late outcome after Property invalidation", async () => {
    const saved = memory(),
      request = commands[1];
    if (!request) throw new Error();
    let release!: () => void;
    const hold = new Promise<void>((resolve) => {
      release = resolve;
    });
    const fetcher = vi.fn<typeof fetch>(async (_url, init) => {
      await hold;
      return commandResponse("rentNonpaymentOpen", init);
    });
    const transport = createFinancialTransport(fetcher, () => "csrf"),
      recovery = createFinancialRecovery(
        saved.store,
        transport,
        () => "csrf",
        saved.attempts,
      ),
      other = createFinancialRecovery(
        saved.store,
        transport,
        () => "csrf",
        saved.attempts,
      );
    const controller = new AbortController(),
      first = recovery.submit(
        { ...scope(), signal: controller.signal },
        request,
      );
    for (let n = 0; n < 20 && fetcher.mock.calls.length === 0; n++)
      await Promise.resolve();
    expect(fetcher).toHaveBeenCalledOnce();
    expect((await other.submit(scope(), request)).kind).toBe("blocked");
    controller.abort();
    expect((await first).kind).toBe("invalidated");
    release();
    await Promise.resolve();
    await Promise.resolve();
    expect(saved.records.size).toBe(1);
    expect((await recovery.load(scope())).kind).toBe("pending");
    expect(await recovery.load({ ...scope(), propertyId: ids.other })).toEqual({
      kind: "other-property",
      propertyId: ids.property,
    });
  });
  it("TEST-FE-602 blocks unrelated financial actions behind the same sealed enforcement intent", async () => {
    const saved = memory(),
      request = commands[0],
      financial = financeCommands[0];
    if (!request || !financial) throw new Error();
    const transport: FinancialTransport = {
      send: vi.fn(async () => {
        await Promise.resolve();
        throw new FinancialClientError("UNAVAILABLE", true);
      }),
    };
    const recovery = createFinancialRecovery(
      saved.store,
      transport,
      () => "csrf",
      saved.attempts,
    );
    expect((await recovery.submit(scope(), request)).kind).toBe("pending");
    const original = saved.records.get(ids.actor);
    expect((await recovery.submit(scope(), financial)).kind).toBe("blocked");
    expect(saved.records.get(ids.actor)).toEqual(original);
    expect(transport.send).toHaveBeenCalledOnce();
    expect(await recovery.load({ ...scope(), actorId: ids.other })).toEqual({
      kind: "ready",
    });
  });
  it.each(["request", "actor", "intent", "property"])(
    "TEST-FE-603 keeps recovery sealed after forged injected success %s",
    async (field) => {
      const saved = memory(),
        request = commands[1];
      if (!request) throw new Error();
      const transport: FinancialTransport = {
        send: vi.fn<FinancialTransport["send"]>(
          async (_scope, _request, key) => {
            const data = caseRecord();
            if (field === "actor") data.opened_by = ids.other;
            if (field === "intent") data.rent_invoice_line_id = ids.other;
            return Promise.resolve({
              data,
              propertyId: field === "property" ? ids.other : ids.property,
              requestId: field === "request" ? ids.other : (key ?? ids.key),
            });
          },
        ),
      };
      const recovery = createFinancialRecovery(
        saved.store,
        transport,
        () => "csrf",
        saved.attempts,
      );
      expect((await recovery.submit(scope(), request)).kind).toBe("pending");
      expect(saved.records.size).toBe(1);
    },
  );
  it.each([400, 422])(
    "TEST-FE-604 retires a fresh definitive %s but retains an identical replay rejection",
    async (status) => {
      const saved = memory(),
        request = commands[1];
      if (!request) throw new Error();
      const transport: FinancialTransport = {
        send: vi.fn(async () => {
          await Promise.resolve();
          throw new FinancialClientError(
            "HTTP_REJECTION",
            true,
            status,
            ids.key,
            true,
          );
        }),
      };
      const recovery = createFinancialRecovery(
        saved.store,
        transport,
        () => "csrf",
        saved.attempts,
      );
      expect((await recovery.submit(scope(), request)).kind).toBe("rejected");
      expect(saved.records.size).toBe(0);
      const pending = {
        namespace: "property-rental.financial-command",
        version: 1,
        actorId: ids.actor,
        propertyId: ids.property,
        key: ids.key,
        operation: request.operation,
        target: request.target,
        wireBody: stringifyFinancialJson(request.body),
      };
      saved.records.set(ids.actor, {
        requestKey: ids.key,
        plaintext: stringifyFinancialJson(pending),
      });
      expect((await recovery.replay(scope(), ids.key)).kind).toBe("pending");
      const record = saved.records.get(ids.actor);
      if (!record) throw new Error();
      expect(decodeFinancialIntent(record, ids.actor)?.key).toBe(ids.key);
    },
  );
  it.each(["valid", "missing", "wrong"])(
    "TEST-FE-621 preserves a conflicting original key and validates %s scoped conflict metadata",
    async (metadata) => {
      const saved = memory(),
        request = commands[1];
      if (!request) throw new Error();
      const fetcher = vi.fn<typeof fetch>(async (_url, init) => {
        const key = new Headers(init?.headers).get("X-Request-ID");
        return Promise.resolve(
          new Response(
            stringifyFinancialJson({
              error: { code: "IDEMPOTENCY_KEY_REUSED" },
              meta: {
                request_id: key,
                ...(metadata === "missing"
                  ? {}
                  : {
                      property_id:
                        metadata === "valid" ? ids.property : ids.other,
                    }),
              },
            }),
            {
              status: 409,
              headers: {
                "Content-Type": "application/json",
                "X-Request-ID": key ?? "",
              },
            },
          ),
        );
      });
      const recovery = createFinancialRecovery(
          saved.store,
          createFinancialTransport(fetcher, () => "csrf"),
          () => "csrf",
          saved.attempts,
        ),
        result = await recovery.submit(scope(), request);
      expect(result.kind).toBe("pending");
      if (result.kind !== "pending") throw new Error();
      expect(result.error?.code).toBe(
        metadata === "valid" ? "IDEMPOTENCY_KEY_REUSED" : "INVALID_RESPONSE",
      );
      expect(saved.records.size).toBe(1);
    },
  );
});
