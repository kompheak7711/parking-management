import { afterEach, describe, expect, it, vi } from "vitest";
import { billingJournal, PendingBillingCommand } from "./invoiceClient";
import { sealedIntentStore } from "./sealedIntentStore";

afterEach(() => vi.restoreAllMocks());
const pending = (): PendingBillingCommand => ({
  key: "original-key",
  command: {
    action: "adjust",
    propertyId: "property",
    id: "invoice",
    version: 2,
    input: {
      invoice_line_id: "line",
      adjustment_type: "CREDIT",
      amount: { currency: "USD", minor_units: 9000000000000000n },
      source_reference: "approved",
      reason: "correction",
    },
  },
});

describe("legacy billing over the shared encrypted store", () => {
  it("TEST-FE-272 keeps legacy command keys, bodies and exact bigint amounts", async () => {
    const begin = vi.spyOn(sealedIntentStore, "begin").mockResolvedValue();
    const p = pending();
    await billingJournal.begin("actor", p);
    const captured = begin.mock.calls[0];
    expect(captured?.[0]).toBe("actor");
    expect(captured?.[1].requestKey).toBe(p.key);
    expect(captured?.[1].plaintext).toContain('"minor_units":9000000000000000');
    const read = vi
      .spyOn(sealedIntentStore, "read")
      .mockResolvedValue(captured?.[1] ?? null);
    expect(await billingJournal.load("actor")).toEqual({
      ...p,
      command: {
        ...p.command,
        input: {
          invoice_line_id: "line",
          adjustment_type: "CREDIT",
          amount: { currency: "USD", minor_units: 9000000000000000 },
          source_reference: "approved",
          reason: "correction",
        },
      },
    });
    const legacy = {
      key: "old",
      command: {
        action: "issue",
        propertyId: "property",
        id: "invoice",
        version: 3,
      },
    };
    read.mockResolvedValue({
      requestKey: "old",
      plaintext: JSON.stringify(legacy),
    });
    expect(await billingJournal.load("actor")).toEqual(legacy);
  });
  it.each([
    '{"key":"different","command":{"action":"issue","propertyId":"property"}}',
    '{"key":"original-key","command":{"action":"financial.confirm","propertyId":"property"}}',
    '{"key":"original-key","command":{"action":"issue","propertyId":""}}',
    '{"key":"original-key","key":"original-key","command":{}}',
    "broken",
    "null",
  ])(
    "TEST-FE-273 keeps malformed or foreign commands blocked without clearing %s",
    async (plaintext) => {
      vi.spyOn(sealedIntentStore, "read").mockResolvedValue({
        requestKey: "original-key",
        plaintext,
      });
      const clear = vi.spyOn(sealedIntentStore, "clear").mockResolvedValue();
      await expect(billingJournal.load("actor")).rejects.toThrow();
      expect(clear).not.toHaveBeenCalled();
    },
  );
  it("TEST-FE-274 propagates persistence and clearance failures without bypass", async () => {
    vi.spyOn(sealedIntentStore, "begin").mockRejectedValue(
      new Error("unavailable"),
    );
    await expect(billingJournal.begin("actor", pending())).rejects.toThrow();
    const clear = vi
      .spyOn(sealedIntentStore, "clear")
      .mockRejectedValue(new Error("wrong key"));
    await expect(
      billingJournal.clear("actor", "original-key"),
    ).rejects.toThrow();
    expect(clear).toHaveBeenCalledWith("actor", "original-key");
    vi.spyOn(sealedIntentStore, "read").mockRejectedValue(new Error("decrypt"));
    await expect(billingJournal.load("actor")).rejects.toThrow();
  });
  it("TEST-FE-275 loading an empty journal never reserves or transmits", async () => {
    vi.spyOn(sealedIntentStore, "read").mockResolvedValue(null);
    const begin = vi.spyOn(sealedIntentStore, "begin");
    const fetcher = vi.spyOn(globalThis, "fetch");
    expect(await billingJournal.load("actor")).toBeNull();
    expect(begin).not.toHaveBeenCalled();
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("TEST-FE-276 captures the reviewed command before asynchronous sealing", async () => {
    let finish: (() => void) | undefined;
    const begin = vi.spyOn(sealedIntentStore, "begin").mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    const p = pending();
    const saved = billingJournal.begin("actor", p);
    p.key = "later-key";
    p.command.propertyId = "other-property";
    expect(begin.mock.calls[0]?.[1].requestKey).toBe("original-key");
    expect(begin.mock.calls[0]?.[1].plaintext).toContain(
      '"propertyId":"property"',
    );
    finish?.();
    await saved;
  });
});
