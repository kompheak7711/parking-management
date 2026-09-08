import { createElement, StrictMode, type ReactNode } from "react";
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FinancialReferenceError } from "./financialReferenceClient";
import type { FinancialScope } from "./financialClient";
import { financialObject, type FinancialObject } from "./financialContracts";
import { parseFinancialJson, stringifyFinancialJson } from "./financialJson";
import { createFinancialReferenceClient } from "./financialReferenceClient";
import {
  FINANCIAL_UI_CONTEXT_BYTES,
  loadFinancialActionContext,
  loadPaymentReversalContext,
  useFinancialTask,
  useFinancialSnapshot,
  useFinancialDraft,
} from "./financialUiContext";
import {
  actionContextFixtures,
  type FinancialActionFixture,
} from "./test/financialActionContextFixtures";
import { fixture, ids } from "./test/financialFixtures";

afterEach(cleanup);

const scope = (
  sample?: FinancialActionFixture,
  signal = new AbortController().signal,
) => ({
  actorId: sample?.actorId ?? ids.actor,
  propertyId: sample?.propertyId ?? ids.property,
  signal,
});
function response(
  data: FinancialObject,
  init: RequestInit,
  s: ReturnType<typeof scope>,
  limit = 50,
  next: string | null = null,
): Response {
  const headers = new Headers(init.headers),
    requestId = headers.get("X-Request-ID");
  expect(init.method).toBe("GET");
  expect(init.body).toBeUndefined();
  expect(headers.get("Idempotency-Key")).toBeNull();
  expect(headers.get("X-CSRF-Token")).toBeNull();
  return new Response(
    stringifyFinancialJson(
      {
        data,
        page: { limit, next_cursor: next },
        meta: {
          request_id: requestId,
          actor_id: s.actorId,
          property_id: s.propertyId,
        },
      },
      1_048_576,
    ),
    {
      headers: {
        "Content-Type": "application/json",
        "X-Request-ID": requestId ?? "",
      },
    },
  );
}
function invoicePair() {
  const original = actionContextFixtures.find(
    (s) =>
      s.request.purpose === "allocation" && s.request.target_kind === "INVOICE",
  );
  if (!original) throw new Error("Synthetic Invoice fixture missing");
  const sample = structuredClone(original);
  sample.request.limit = 1;
  sample.data.item_count = 2;
  const target = financialObject(sample.data.target);
  target.line_count = 2;
  for (const key of [
    "original_total_usd_cents",
    "adjusted_total_usd_cents",
    "outstanding_usd_cents",
  ]) {
    const amount = target[key];
    if (typeof amount !== "number" && typeof amount !== "bigint")
      throw new Error("Synthetic amount missing");
    target[key] = BigInt(amount) * 2n;
  }
  if (!Array.isArray(sample.data.items) || sample.data.items.length !== 1)
    throw new Error("Expected one synthetic line");
  const first = financialObject(sample.data.items[0]);
  first.sequence = 1;
  const second = structuredClone(sample.data);
  second.items = [{ ...structuredClone(first), sequence: 2, id: ids.other }];
  if (typeof sample.data.revision !== "string" || typeof first.id !== "string")
    throw new Error("Synthetic revision or identity missing");
  const cursor = `${sample.data.revision}:1:${first.id}`;
  return { sample, first: sample.data, second, cursor };
}
const revision = "a".repeat(64);
function invoiceResult(index: number): FinancialObject {
  return {
    ordinal: 1,
    kind: "INVOICE",
    id: `00000000-0000-4000-8000-${(index + 1).toString().padStart(12, "0")}`,
    data: {
      invoice_number: `Invoice ${index.toString()}`,
      status: "PAID",
      outstanding_usd_cents: 0,
    },
  };
}
function resultData(items: FinancialObject[]): FinancialObject {
  return {
    payment_resource: fixture("paymentGet").data,
    view: "result",
    revision,
    items,
  };
}

describe("complete staff financial contexts", () => {
  it.each(actionContextFixtures.map((sample, index) => ({ sample, index })))(
    "TEST-FE-417 loads complete actual database history $index through the existing read-only client",
    async ({ sample }) => {
      const s = scope(sample);
      const fetcher = vi.fn<typeof fetch>((_url, init) =>
        Promise.resolve(response(sample.data, init ?? {}, s)),
      );
      const csrf = vi.fn(() => "unused");
      const result = await loadFinancialActionContext(
        s,
        sample.request,
        createFinancialReferenceClient(fetcher, csrf),
      );
      expect(result).toEqual(sample.data);
      expect(result).not.toBe(sample.data);
      expect(fetcher).toHaveBeenCalledTimes(1);
      expect(csrf).not.toHaveBeenCalled();
    },
  );

  it("TEST-FE-418 continues the exact action revision and returns only the complete Invoice lines", async () => {
    const { sample, first, second, cursor } = invoicePair();
    const s = scope(sample);
    let calls = 0;
    const fetcher = vi.fn<typeof fetch>((url, init) => {
      if (typeof url !== "string") throw new Error("Expected finite URL");
      const after = new URL(url, "https://synthetic.invalid").searchParams.get(
        "cursor",
      );
      expect(after).toBe(calls++ === 0 ? null : cursor);
      return Promise.resolve(
        response(
          after === null ? first : second,
          init ?? {},
          s,
          1,
          after === null ? cursor : null,
        ),
      );
    });
    const result = await loadFinancialActionContext(
      s,
      sample.request,
      createFinancialReferenceClient(fetcher),
    );
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(result.items).toEqual([
      ...(first.items as FinancialObject[]),
      ...(second.items as FinancialObject[]),
    ]);
    expect(result.item_count).toBe(2);
  });

  it.each(["stale", "abort", "forged"] as const)(
    "TEST-FE-419 rejects %s action continuation without exposing partial completed evidence",
    async (kind) => {
      const { sample, first, second, cursor } = invoicePair();
      const aborter = new AbortController(),
        s = scope(sample, aborter.signal);
      let calls = 0;
      const fetcher = vi.fn<typeof fetch>((_url, init) => {
        calls++;
        if (calls === 2 && kind === "abort") aborter.abort();
        const data = calls === 1 ? first : structuredClone(second);
        if (calls === 2 && kind === "stale") data.revision = "b".repeat(64);
        return Promise.resolve(
          response(data, init ?? {}, s, 1, calls === 1 ? cursor : null),
        );
      });
      const actual = createFinancialReferenceClient(fetcher);
      const client =
        kind === "forged"
          ? {
              read: async (...args: Parameters<typeof actual.read>) => ({
                ...(await actual.read(...args)),
              }),
            }
          : actual;
      await expect(
        loadFinancialActionContext(s, sample.request, client),
      ).rejects.toThrow();
      expect(calls).toBe(kind === "forged" ? 1 : 2);
      aborter.abort();
      await expect(
        loadFinancialActionContext(s, sample.request, actual),
      ).rejects.toMatchObject({ code: "WORKSPACE_INVALIDATED" });
      expect(calls).toBe(kind === "forged" ? 1 : 2);
    },
  );

  it.each([0, 1])(
    "TEST-FE-420 bounds complete Payment reversal display and graph at eight MiB plus %s byte",
    async (extra) => {
      const s = scope();
      const all = resultData(
        Array.from({ length: 900 }, (_, index) => invoiceResult(index)),
      );
      const target = FINANCIAL_UI_CONTEXT_BYTES + extra;
      const originalBytes = new TextEncoder().encode(
        stringifyFinancialJson(all, target),
      ).byteLength;
      const padding = target - originalBytes;
      if (!Array.isArray(all.items)) throw new Error("Missing synthetic items");
      for (let index = 0; index < all.items.length; index++) {
        const item = financialObject(all.items[index]),
          data = financialObject(item.data);
        const amount =
          Math.floor(padding / 900) + (index < padding % 900 ? 1 : 0);
        if (typeof data.invoice_number !== "string")
          throw new Error("Missing invoice number");
        data.invoice_number +=
          "😀".repeat(Math.floor(amount / 4)) + "x".repeat(amount % 4);
      }
      expect(
        new TextEncoder().encode(stringifyFinancialJson(all, target))
          .byteLength,
      ).toBe(target);
      const items = all.items;
      let offset = 0,
        expectedCursor: string | null = null;
      const fetcher = vi.fn<typeof fetch>((url, init) => {
        if (typeof url !== "string") throw new Error("Expected finite URL");
        expect(
          new URL(url, "https://synthetic.invalid").searchParams.get("cursor"),
        ).toBe(expectedCursor);
        const page = items.slice(offset, offset + 100),
          last = financialObject(page[page.length - 1]);
        offset += 100;
        if (typeof last.id !== "string")
          throw new Error("Missing item identity");
        expectedCursor =
          offset < items.length ? `${revision}:1:${last.id}` : null;
        return Promise.resolve(
          response({ ...all, items: page }, init ?? {}, s, 100, expectedCursor),
        );
      });
      const result = loadPaymentReversalContext(
        s,
        ids.payment,
        "result",
        createFinancialReferenceClient(fetcher),
      );
      if (extra)
        await expect(result).rejects.toMatchObject({
          code: "RESPONSE_TOO_LARGE",
        });
      else {
        const complete = await result;
        expect(complete.items).toHaveLength(900);
        expect(
          new TextEncoder().encode(stringifyFinancialJson(complete, target))
            .byteLength,
        ).toBe(target);
      }
      expect(fetcher).toHaveBeenCalledTimes(9);
    },
  );

  it("TEST-FE-421 rejects a changed Payment header between otherwise coherent result pages", async () => {
    const s = scope(),
      items = Array.from({ length: 101 }, (_, i) => invoiceResult(i));
    let offset = 0;
    const fetcher = vi.fn<typeof fetch>((_url, init) => {
      const data = resultData(items.slice(offset, offset + 100));
      if (offset)
        financialObject(
          financialObject(data.payment_resource).payment,
        ).payer_intent_memo = "Changed original facts";
      offset += 100;
      const next =
        offset === 100
          ? `${revision}:1:00000000-0000-4000-8000-000000000100`
          : null;
      return Promise.resolve(response(data, init ?? {}, s, 100, next));
    });
    await expect(
      loadPaymentReversalContext(
        s,
        ids.payment,
        "result",
        createFinancialReferenceClient(fetcher),
      ),
    ).rejects.toThrow();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it.each([false, true])(
    "TEST-FE-422 requires a complete original Allocation dependency graph, missing line %s",
    async (missing) => {
      const s = scope();
      const items: FinancialObject[] = [
        {
          ordinal: 1,
          kind: "ALLOCATION",
          id: ids.allocation,
          data: {
            source_kind: "PAYMENT",
            source_id: ids.payment,
            target_kind: "INVOICE",
            target_id: ids.invoice,
            amount_usd_cents: 100,
            occurred_at: "2026-09-01T05:00:00Z",
          },
        },
      ];
      if (!missing)
        items.push({
          ordinal: 2,
          kind: "ALLOCATION_LINE",
          id: ids.event,
          data: {
            source_kind: "ALLOCATION",
            source_id: ids.allocation,
            target_kind: "INVOICE_LINE",
            target_id: ids.other,
            amount_usd_cents: 100,
            occurred_at: "2026-09-01T05:00:00Z",
          },
        });
      const data: FinancialObject = {
        payment_resource: fixture("paymentGet").data,
        view: "impact",
        revision,
        items,
      };
      const fetcher = vi.fn<typeof fetch>((_url, init) =>
        Promise.resolve(response(data, init ?? {}, s, 100)),
      );
      const result = loadPaymentReversalContext(
        s,
        ids.payment,
        "impact",
        createFinancialReferenceClient(fetcher),
      );
      if (missing) await expect(result).rejects.toThrow();
      else
        expect(await result).toEqual(
          financialObject(
            parseFinancialJson(
              stringifyFinancialJson(data, 1_048_576),
              1_048_576,
            ),
          ),
        );
    },
  );
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

describe("financial read task ownership", () => {
  it.each(["resolve", "reject"] as const)(
    "TEST-FE-433 ignores an older %s after the next read succeeds",
    async (outcome) => {
      const root = scope(),
        first = deferred<string>(),
        second = deferred<string>();
      const accept = vi.fn();
      const { result } = renderHook(() => useFinancialTask(root));
      let oldSignal: AbortSignal | undefined;
      let old!: Promise<void>, next!: Promise<void>;
      act(() => {
        old = result.current.run((s) => {
          oldSignal = s.signal;
          return first.promise;
        }, accept);
        next = result.current.run(() => second.promise, accept);
      });
      expect(oldSignal?.aborted).toBe(true);
      expect(result.current.busy).toBe(true);
      await act(async () => {
        second.resolve("current");
        await next;
      });
      expect(accept).toHaveBeenCalledExactlyOnceWith("current");
      await act(async () => {
        first[outcome]("stale");
        await old;
      });
      expect(accept).toHaveBeenCalledTimes(1);
      expect(result.current.error).toBeNull();
      expect(result.current.busy).toBe(false);
    },
  );

  it("TEST-FE-434 cancels a record read immediately even when transport ignores abort", async () => {
    const root = scope(),
      request = deferred<string>(),
      accept = vi.fn();
    const { result } = renderHook(() => useFinancialTask(root));
    let pending!: Promise<void>, child: AbortSignal | undefined;
    act(() => {
      pending = result.current.run((s) => {
        child = s.signal;
        return request.promise;
      }, accept);
    });
    act(() => {
      result.current.cancel();
    });
    expect(child?.aborted).toBe(true);
    expect(root.signal.aborted).toBe(false);
    expect(result.current.busy).toBe(false);
    await act(async () => {
      request.resolve("old record");
      await pending;
    });
    expect(accept).not.toHaveBeenCalled();
  });

  it.each(["actor", "property", "signal"] as const)(
    "TEST-FE-435 discards old scope results and stale callbacks after %s changes",
    async (field) => {
      const initial = scope(),
        request = deferred<string>(),
        accept = vi.fn();
      const { result, rerender } = renderHook(
        (s: FinancialScope) => useFinancialTask(s),
        { initialProps: initial },
      );
      const oldRun = result.current.run;
      let pending!: Promise<void>, child: AbortSignal | undefined;
      act(() => {
        pending = oldRun((s) => {
          child = s.signal;
          return request.promise;
        }, accept);
      });
      const next = {
        ...initial,
        ...(field === "actor"
          ? { actorId: ids.other }
          : field === "property"
            ? { propertyId: ids.other }
            : { signal: new AbortController().signal }),
      };
      rerender(next);
      expect(child?.aborted).toBe(true);
      const staleWork = vi.fn(() => Promise.resolve("stale invocation"));
      await act(async () => {
        await oldRun(staleWork, accept);
        request.resolve("old result");
        await pending;
      });
      expect(staleWork).not.toHaveBeenCalled();
      expect(accept).not.toHaveBeenCalled();
      await act(async () => {
        await result.current.run((s) => {
          expect(s.actorId).toBe(next.actorId);
          expect(s.propertyId).toBe(next.propertyId);
          return Promise.resolve("new result");
        }, accept);
      });
      expect(accept).toHaveBeenCalledExactlyOnceWith("new result");
    },
  );

  it.each(["abort", "unmount"] as const)(
    "TEST-FE-436 prevents publication and future work after %s",
    async (mode) => {
      const controller = new AbortController(),
        root = scope(undefined, controller.signal),
        request = deferred<string>(),
        accept = vi.fn();
      const remove = vi.spyOn(root.signal, "removeEventListener");
      const { result, unmount } = renderHook(() => useFinancialTask(root));
      const run = result.current.run;
      let pending!: Promise<void>, child: AbortSignal | undefined;
      act(() => {
        pending = run((s) => {
          child = s.signal;
          return request.promise;
        }, accept);
      });
      act(() => {
        if (mode === "abort") controller.abort();
        else unmount();
      });
      expect(child?.aborted).toBe(true);
      if (mode === "abort") expect(result.current.busy).toBe(false);
      const work = vi.fn(() => Promise.resolve("late"));
      await act(async () => {
        request.resolve("old");
        await pending;
        await run(work, accept);
      });
      expect(work).not.toHaveBeenCalled();
      expect(accept).not.toHaveBeenCalled();
      expect(remove).toHaveBeenCalledWith("abort", expect.any(Function));
    },
  );

  it("TEST-FE-437 accepts current work after StrictMode setup cleanup and releases its listener", async () => {
    const root = scope(),
      accept = vi.fn();
    const add = vi.spyOn(root.signal, "addEventListener"),
      remove = vi.spyOn(root.signal, "removeEventListener");
    const { result } = renderHook(() => useFinancialTask(root), {
      wrapper: ({ children }: { children: ReactNode }) =>
        createElement(StrictMode, null, children),
    });
    await act(async () => {
      await result.current.run((s) => {
        expect(s.signal.aborted).toBe(false);
        return Promise.resolve("current");
      }, accept);
    });
    expect(accept).toHaveBeenCalledExactlyOnceWith("current");
    expect(result.current.busy).toBe(false);
    expect(add).toHaveBeenCalledTimes(1);
    expect(remove).toHaveBeenCalledWith("abort", add.mock.calls[0]?.[1]);
  });

  it("TEST-FE-438 presents finite current errors and clears them for a fresh explicit read", async () => {
    const root = scope(),
      accept = vi.fn();
    const { result } = renderHook(() => useFinancialTask(root));
    await act(async () => {
      await result.current.run(
        () => Promise.reject(new Error("private transport payload")),
        accept,
      );
    });
    expect(result.current.error).toMatch(/Financial evidence is unavailable/);
    expect(result.current.error).not.toContain("private");
    expect(result.current.busy).toBe(false);
    await act(async () => {
      await result.current.run(
        () => Promise.reject(new FinancialReferenceError("RESPONSE_TOO_LARGE")),
        accept,
      );
    });
    expect(result.current.error).toMatch(/exceeds the display limit/);
    await act(async () => {
      await result.current.run(() => Promise.resolve("recovered"), accept);
    });
    expect(result.current.error).toBeNull();
    expect(accept).toHaveBeenCalledExactlyOnceWith("recovered");
  });
});

it("TEST-FE-508 cancels a pre-command read and cannot promote its retained snapshot into a newer revision", async () => {
  const captured = scope();
  let release!: (value: string) => void;
  const delayed = new Promise<string>((resolve) => {
    release = resolve;
  });
  const { result, rerender } = renderHook(
    ({ revision }) => {
      const task = useFinancialTask(captured, revision);
      const [value, setValue, current] = useFinancialSnapshot<string>(revision);
      return { ...task, value, setValue, current };
    },
    { initialProps: { revision: 0 } },
  );
  act(() => {
    result.current.setValue("Original facts");
  });
  let completion!: Promise<void>;
  let signal!: AbortSignal;
  act(() => {
    completion = result.current.run(async (s) => {
      signal = s.signal;
      return await delayed;
    }, result.current.setValue);
  });
  const oldRun = result.current.run;
  rerender({ revision: 1 });
  expect(signal.aborted).toBe(true);
  expect(result.current.value).toBe("Original facts");
  expect(result.current.current).toBe(false);
  const obsoleteWork = vi.fn(() => Promise.resolve("Old revision request"));
  await act(async () => {
    await oldRun(obsoleteWork, result.current.setValue);
  });
  expect(obsoleteWork).not.toHaveBeenCalled();
  await act(async () => {
    release("Obsolete balance");
    await completion;
  });
  expect(result.current.value).toBe("Original facts");
  expect(result.current.current).toBe(false);
  await act(async () => {
    await result.current.run(
      () => Promise.resolve("Fresh authorized facts"),
      result.current.setValue,
    );
  });
  expect(result.current.value).toBe("Fresh authorized facts");
  expect(result.current.current).toBe(true);
});

describe("scope-bound financial draft acknowledgement", () => {
  it("TEST-FE-522 acknowledges only the exact edit generation that was confirmed", () => {
    const changed = vi.fn(),
      supplied = scope();
    const h = renderHook(() => useFinancialDraft(supplied, changed));
    act(() => {
      h.result.current.edited();
    });
    const previous = h.result.current.captureRecorded();
    act(() => {
      h.result.current.edited();
    });
    act(previous);
    expect(changed).toHaveBeenLastCalledWith(true);
    const current = h.result.current.captureRecorded();
    act(current);
    expect(changed).toHaveBeenLastCalledWith(false);
    const calls = changed.mock.calls.length;
    act(current);
    expect(changed).toHaveBeenCalledTimes(calls);
  });
  it.each(["actor", "Property", "signal"] as const)(
    "TEST-FE-522 ignores old draft callbacks after a %s transition",
    (kind) => {
      const changed = vi.fn(),
        supplied = scope();
      const h = renderHook(({ value }) => useFinancialDraft(value, changed), {
        initialProps: { value: supplied },
      });
      const old = h.result.current;
      act(old.edited);
      const acknowledged = old.captureRecorded();
      h.rerender({
        value: {
          ...supplied,
          ...(kind === "actor"
            ? { actorId: ids.other }
            : kind === "Property"
              ? { propertyId: ids.other }
              : { signal: new AbortController().signal }),
        },
      });
      expect(changed).toHaveBeenLastCalledWith(false);
      act(() => {
        h.result.current.edited();
      });
      const calls = changed.mock.calls.length;
      act(() => {
        old.edited();
        old.clear();
        acknowledged();
      });
      expect(changed).toHaveBeenCalledTimes(calls);
      expect(changed).toHaveBeenLastCalledWith(true);
      expect(old.confirmDiscard()).toBe(false);
    },
  );
  it("TEST-FE-522 immediately drops dirty state on forced abort without a discard prompt", () => {
    const changed = vi.fn(),
      controller = new AbortController(),
      discard = vi.spyOn(window, "confirm").mockReturnValue(false);
    try {
      const h = renderHook(() =>
        useFinancialDraft(scope(undefined, controller.signal), changed),
      );
      act(() => {
        h.result.current.edited();
      });
      const current = h.result.current;
      act(() => {
        controller.abort();
      });
      expect(changed).toHaveBeenLastCalledWith(false);
      expect(current.confirmDiscard()).toBe(false);
      act(current.edited);
      expect(changed).toHaveBeenLastCalledWith(false);
      expect(discard).not.toHaveBeenCalled();
    } finally {
      discard.mockRestore();
    }
  });
  it("TEST-FE-522 preserves dirty state when only its notification callback changes", () => {
    const first = vi.fn(),
      next = vi.fn(),
      supplied = scope();
    const h = renderHook(({ notify }) => useFinancialDraft(supplied, notify), {
      initialProps: { notify: first },
    });
    act(() => {
      h.result.current.edited();
    });
    h.rerender({ notify: next });
    expect(next).toHaveBeenLastCalledWith(true);
    act(h.result.current.captureRecorded());
    expect(next).toHaveBeenLastCalledWith(false);
  });
});
