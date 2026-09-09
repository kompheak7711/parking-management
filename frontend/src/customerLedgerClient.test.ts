import { afterEach, describe, expect, it, vi } from "vitest";
import { financialObject, type FinancialObject } from "./financialContracts";
import {
  createCustomerLedgerClient,
  ledgerMoney,
  LEDGER_DEADLINE_MS,
  LEDGER_EVENTS,
  LEDGER_REPLY_BYTES,
  type LedgerRequest,
} from "./customerLedgerClient";
import {
  ledgerRequestUrl,
  canonicalLedgerEvents,
  ledgerComponent,
  ledgerCursorToken,
  ledgerEnvelope,
  ledgerErrorResponse,
  ledgerEvent,
  ledgerId,
  ledgerIds,
  ledgerWireResponse,
  syntheticLedgerResponse,
} from "./customerLedgerFixtures";
const scope = () => ({
  actorId: ledgerIds.actor,
  propertyId: ledgerIds.property,
  signal: new AbortController().signal,
});
const request: LedgerRequest = {
  section: "history",
  customerId: ledgerIds.customer,
};
const serve = (mutate?: (data: FinancialObject) => void) =>
  vi.fn<typeof fetch>((_url, init) => {
    const envelope = ledgerEnvelope();
    mutate?.(envelope);
    return Promise.resolve(ledgerWireResponse(envelope, init ?? {}));
  });
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});
describe("Customer ledger read contract", () => {
  it("TEST-FE-546 reads only the fixed ledger route with private session and actor/Property binding", async () => {
    const fetcher = serve(),
      api = createCustomerLedgerClient(fetcher),
      reply = await api.read(request, scope());
    expect(reply.section).toBe("history");
    expect(reply.propertyId).toBe(ledgerIds.property);
    const [url, init] = fetcher.mock.calls[0] ?? [];
    expect(url).toBe(
      `/api/v1/customers/${ledgerIds.customer}/account-ledger?limit=50&section=history`,
    );
    expect(init).toMatchObject({
      method: "GET",
      credentials: "include",
      cache: "no-store",
      redirect: "error",
    });
    expect(init?.body).toBeUndefined();
    const headers = new Headers(init?.headers);
    expect(headers.get("X-Billing-Actor-ID")).toBe(ledgerIds.actor);
    expect(headers.get("X-Financial-Property-ID")).toBe(ledgerIds.property);
    expect(headers.has("Idempotency-Key")).toBe(false);
    expect(headers.has("X-CSRF-Token")).toBe(false);
    expect(Object.isFrozen(reply)).toBe(true);
    expect(Object.isFrozen(reply.items[0])).toBe(true);
  });
  it.each(["0", "1", "100", "18000000000000000", "9".repeat(64)])(
    "TEST-FE-547 preserves exact ledger money %s including the full64digit contract",
    (value) => {
      const expectedWhole = (BigInt(value) / 100n).toLocaleString("en-US"),
        fraction = (BigInt(value) % 100n).toString().padStart(2, "0");
      expect(ledgerMoney(value)).toBe(`$${expectedWhole}.${fraction}`);
    },
  );
  it.each(["-0", "01", "1.01", "1e2", "9".repeat(65), "NaN", " 1"])(
    "TEST-FE-548 rejects noncanonical or oversized exact amounts %s",
    (value) => {
      expect(() => ledgerMoney(value)).toThrow();
    },
  );
  it.each([
    ledgerIds.customer.toUpperCase().replace("000000000003", "00000000000A"),
    ledgerIds.customer.replaceAll("-", ""),
    "00000000-0000-0000-0000-000000000000",
    "../payments",
  ])(
    "TEST-FE-549 rejects a noncanonical Customer identity before network access %s",
    (customerId) => {
      const fetcher = serve();
      return expect(
        createCustomerLedgerClient(fetcher).read(
          { ...request, customerId },
          scope(),
        ),
      )
        .rejects.toMatchObject({ code: "INVALID_REQUEST" })
        .then(() => {
          expect(fetcher).not.toHaveBeenCalled();
        });
    },
  );
  it.each([
    [
      "numeric money",
      (e: FinancialObject) => {
        financialObject(financialObject(e.data).position).invoice_usd_cents =
          21000;
      },
    ],
    [
      "aggregate mismatch",
      (e: FinancialObject) => {
        financialObject(financialObject(e.data).position).total_owed_usd_cents =
          "0";
      },
    ],
    [
      "wrong actor",
      (e: FinancialObject) => {
        financialObject(e.meta).actor_id = ledgerIds.other;
      },
    ],
    [
      "wrong Property",
      (e: FinancialObject) => {
        financialObject(e.meta).property_id = ledgerIds.other;
      },
    ],
    [
      "wrong Customer",
      (e: FinancialObject) => {
        financialObject(e.data).customer_id = ledgerIds.other;
      },
    ],
    [
      "wrong section",
      (e: FinancialObject) => {
        financialObject(e.data).section = "components";
      },
    ],
    [
      "invalid revision",
      (e: FinancialObject) => {
        financialObject(e.data).source_revision = "x";
      },
    ],
    [
      "row scope",
      (e: FinancialObject) => {
        financialObject(e.data).items = [
          ledgerEvent("INVOICE_ISSUED", 1, { customer_id: ledgerIds.other }),
        ];
      },
    ],
    [
      "unknown event",
      (e: FinancialObject) => {
        financialObject(e.data).items = [
          ledgerEvent("INVOICE_ISSUED", 1, { event_kind: "SETTLEMENT" }),
        ];
      },
    ],
    [
      "wrong event order",
      (e: FinancialObject) => {
        financialObject(e.data).items = [
          ledgerEvent("INVOICE_ISSUED", 1, { event_order: 99 }),
        ];
      },
    ],
    [
      "duplicate events",
      (e: FinancialObject) => {
        financialObject(e.data).items = [ledgerEvent(), ledgerEvent()];
      },
    ],
    [
      "invalid date",
      (e: FinancialObject) => {
        financialObject(e.data).items = [
          ledgerEvent("INVOICE_ISSUED", 1, { business_date: "2026-02-30" }),
        ];
      },
    ],
    [
      "numeric audit evidence",
      (e: FinancialObject) => {
        financialObject(e.data).items = [
          ledgerEvent("INVOICE_ISSUED", 1, {
            source_audit: { original_amount: 12 },
          }),
        ];
      },
    ],
    [
      "incomplete next page",
      (e: FinancialObject) => {
        financialObject(e.page).next_cursor = ledgerCursorToken(ledgerEvent());
      },
    ],
  ] as const)(
    "TEST-FE-550 fails closed for malformed or mismatched %s",
    async (_name, mutate) => {
      await expect(
        createCustomerLedgerClient(serve(mutate)).read(request, scope()),
      ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    },
  );
  it.each(Object.keys(LEDGER_EVENTS))(
    "TEST-FE-551 accepts source kind %s without inventing later-scope events",
    async (kind) => {
      const fetcher = serve((e) => {
        financialObject(e.data).event_count = 1;
        financialObject(e.data).items = [
          ledgerEvent(kind as keyof typeof LEDGER_EVENTS),
        ];
      });
      expect(
        (await createCustomerLedgerClient(fetcher).read(request, scope()))
          .items,
      ).toHaveLength(1);
    },
  );
  it("TEST-FE-552 preserves microseconds and orders same-instant peers by kind and UUID", async () => {
    const a = ledgerEvent("INVOICE_ISSUED", 1, {
      occurred_at: "2026-07-01T00:00:00.000001+00:00",
    });
    const b = ledgerEvent("PAYMENT_RECEIVED", 2, {
      occurred_at: "2026-07-01T00:00:00.000001+00:00",
    });
    const c = ledgerEvent("INVOICE_ISSUED", 3, {
      occurred_at: "2026-07-01T00:00:00.000002+00:00",
    });
    const fetcher = serve((e) => {
      financialObject(e.data).event_count = 3;
      financialObject(e.data).items = [a, b, c];
    });
    expect(
      (await createCustomerLedgerClient(fetcher).read(request, scope())).items,
    ).toHaveLength(3);
    const reversed = serve((e) => {
      financialObject(e.data).items = [c, b, a];
    });
    await expect(
      createCustomerLedgerClient(reversed).read(request, scope()),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });
  it("TEST-FE-553 binds history cursors to issued snapshot, actor, Property, Customer, filter and section", async () => {
    const fetcher = vi.fn<typeof fetch>((url, init) =>
      Promise.resolve(
        syntheticLedgerResponse(ledgerRequestUrl(url), init ?? {}),
      ),
    );
    const api = createCustomerLedgerClient(fetcher),
      first = await api.read({ ...request, limit: 2 }, scope());
    if (first.section !== "history" || !first.nextCursor)
      throw Error("Expected synthetic history continuation");
    const second = await api.read(
      {
        ...request,
        limit: 2,
        snapshot: first.snapshot,
        cursor: first.nextCursor,
      },
      scope(),
    );
    expect(second.items).toHaveLength(2);
    const invalid: LedgerRequest[] = [
      { ...request, limit: 2, cursor: first.nextCursor },
      {
        ...request,
        limit: 2,
        snapshot: first.snapshot,
        cursor: { ...first.nextCursor },
      },
      {
        ...request,
        limit: 2,
        snapshot: first.snapshot,
        cursor: first.nextCursor,
        filters: { kind: "PAYMENT_RECEIVED" },
      },
      {
        ...request,
        limit: 2,
        customerId: ledgerIds.other,
        snapshot: first.snapshot,
        cursor: first.nextCursor,
      },
      {
        section: "composition",
        customerId: ledgerIds.customer,
        limit: 2,
        snapshot: first.snapshot,
        cursor: first.nextCursor,
      },
    ];
    for (const input of invalid)
      await expect(api.read(input, scope())).rejects.toMatchObject({
        code: "INVALID_REQUEST",
      });
    await expect(
      api.read(
        { ...request, snapshot: first.snapshot },
        { ...scope(), actorId: ledgerIds.other },
      ),
    ).rejects.toMatchObject({ code: "INVALID_REQUEST" });
    await expect(
      api.read(
        { ...request, snapshot: first.snapshot },
        { ...scope(), propertyId: ledgerIds.other },
      ),
    ).rejects.toMatchObject({ code: "INVALID_REQUEST" });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it("TEST-FE-554 binds a minimal Customer picker continuation to the discovered Property", async () => {
    const fetcher = vi.fn<typeof fetch>((url, init) =>
      Promise.resolve(
        syntheticLedgerResponse(ledgerRequestUrl(url), init ?? {}, {
          customers: [
            { id: ledgerId(1), legal_name: "One" },
            { id: ledgerId(2), legal_name: "Two" },
          ],
        }),
      ),
    );
    const api = createCustomerLedgerClient(fetcher),
      first = await api.read(
        { section: "customers", limit: 1 },
        { actorId: ledgerIds.actor, signal: scope().signal },
      );
    if (first.section !== "customers" || !first.nextCursor)
      throw Error("Expected picker continuation");
    const next = await api.read(
      { section: "customers", limit: 1, cursor: first.nextCursor },
      { ...scope(), propertyId: first.propertyId },
    );
    expect(next.items).toEqual([{ id: ledgerId(2), legal_name: "Two" }]);
    await expect(
      api.read(
        { section: "customers", limit: 1, cursor: first.nextCursor },
        { ...scope(), propertyId: ledgerIds.other },
      ),
    ).rejects.toMatchObject({ code: "INVALID_REQUEST" });
  });
  it("TEST-FE-555 rejects component source identity/evidence and revision changes within a snapshot", async () => {
    let changed = false;
    const fetcher = vi.fn<typeof fetch>((url, init) => {
      if (!ledgerRequestUrl(url).includes("section=components"))
        return Promise.resolve(
          syntheticLedgerResponse(ledgerRequestUrl(url), init ?? {}),
        );
      const e = ledgerEnvelope(
        [ledgerComponent(canonicalLedgerEvents()[0])],
        "components",
      );
      if (changed) financialObject(e.data).source_revision = "c".repeat(64);
      else
        financialObject(e.data).items = [
          ledgerComponent(canonicalLedgerEvents()[0], 1, {
            recorded_amount_usd_cents: "1",
          }),
        ];
      return Promise.resolve(ledgerWireResponse(e, init ?? {}));
    });
    const api = createCustomerLedgerClient(fetcher),
      first = await api.read(request, scope());
    if (first.section !== "history") throw new Error("Expected history source");
    const componentRequest: LedgerRequest = {
      section: "components",
      customerId: ledgerIds.customer,
      snapshot: first.snapshot,
      eventKind: "INVOICE_ISSUED",
      eventId: ledgerId(1),
      source: first.items[0],
    };
    await expect(api.read(componentRequest, scope())).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
    });
    changed = true;
    await expect(api.read(componentRequest, scope())).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
    });
  });
  it.each([401, 403, 404, 409, 422, 503])(
    "TEST-FE-556 returns only a validated safe error for HTTP%s",
    async (status) => {
      const fetcher = vi.fn<typeof fetch>((_url, init) =>
        Promise.resolve(ledgerErrorResponse(status, init ?? {})),
      );
      await expect(
        createCustomerLedgerClient(fetcher).read(request, scope()),
      ).rejects.toMatchObject({ code: "HTTP_REJECTION", status });
    },
  );
  it.each(["Cache-Control", "Vary", "X-Request-ID", "Content-Type"])(
    "TEST-FE-557 rejects missing private/correlation response metadata %s",
    async (header) => {
      const fetcher = vi.fn<typeof fetch>((_url, init) => {
        const response = ledgerWireResponse(ledgerEnvelope(), init ?? {});
        response.headers.delete(header);
        return Promise.resolve(response);
      });
      await expect(
        createCustomerLedgerClient(fetcher).read(request, scope()),
      ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    },
  );
  it("TEST-FE-558 cancels response ownership on the full page byte ceiling", async () => {
    const cancel = vi.fn(),
      fetcher = vi.fn<typeof fetch>((_url, init) =>
        Promise.resolve(
          new Response(
            new ReadableStream({
              pull(controller) {
                controller.enqueue(new Uint8Array(LEDGER_REPLY_BYTES + 1));
              },
              cancel,
            }),
            {
              headers: {
                "Content-Type": "application/json",
                "X-Request-ID":
                  new Headers(init?.headers).get("X-Request-ID") ?? "",
                "Cache-Control": "private, no-store",
                Vary: "Cookie",
              },
            },
          ),
        ),
      );
    await expect(
      createCustomerLedgerClient(fetcher).read(request, scope()),
    ).rejects.toMatchObject({ code: "RESPONSE_TOO_LARGE" });
    expect(cancel).toHaveBeenCalledTimes(1);
  });
  it("TEST-FE-559 accepts an API-sized page above the unrelated reference-client ceiling", async () => {
    const data = ledgerEnvelope([
      ledgerEvent("INVOICE_ISSUED", 1, {
        source_audit: { evidence: "x".repeat(700000) },
      }),
      ledgerEvent("PAYMENT_RECEIVED", 2, {
        source_audit: { evidence: "y".repeat(700000) },
      }),
    ]);
    const fetcher = vi.fn<typeof fetch>((_url, init) =>
      Promise.resolve(ledgerWireResponse(data, init ?? {})),
    );
    expect(
      (await createCustomerLedgerClient(fetcher).read(request, scope())).items,
    ).toHaveLength(2);
  });
  it("TEST-FE-560 settles an uncooperative fetch at deadline and cancels its late body", async () => {
    vi.useFakeTimers();
    let resolve: ((response: Response) => void) | undefined;
    const fetcher = vi.fn<typeof fetch>(
      () =>
        new Promise<Response>((done) => {
          resolve = done;
        }),
    );
    const pending = createCustomerLedgerClient(fetcher).read(request, scope()),
      checked = expect(pending).rejects.toMatchObject({ code: "UNAVAILABLE" });
    await vi.advanceTimersByTimeAsync(LEDGER_DEADLINE_MS);
    await checked;
    const cancel = vi.fn();
    resolve?.(new Response(new ReadableStream({ cancel })));
    await Promise.resolve();
    expect(cancel).toHaveBeenCalledTimes(1);
  });
  it("TEST-FE-561 aborts before network and during an uncooperative read", async () => {
    const abort = new AbortController();
    abort.abort();
    const fetcher = serve();
    await expect(
      createCustomerLedgerClient(fetcher).read(request, {
        ...scope(),
        signal: abort.signal,
      }),
    ).rejects.toMatchObject({ code: "ABORTED" });
    expect(fetcher).not.toHaveBeenCalled();
    const active = new AbortController(),
      stalled = vi.fn<typeof fetch>(
        () =>
          new Promise(() => {
            /* Synthetic noncooperating transport. */
          }),
      );
    const pending = createCustomerLedgerClient(stalled).read(request, {
      ...scope(),
      signal: active.signal,
    });
    active.abort();
    await expect(pending).rejects.toMatchObject({ code: "ABORTED" });
  });
});

it("TEST-FE-579 requires an issued immutable history row for source navigation and rejects forged or cross-snapshot copies", async () => {
  const fetcher = vi.fn<typeof fetch>((url, init) =>
    Promise.resolve(syntheticLedgerResponse(ledgerRequestUrl(url), init ?? {})),
  );
  const api = createCustomerLedgerClient(fetcher),
    first = await api.read(request, scope());
  if (first.section !== "history" || !first.items[0])
    throw new Error("Expected source history");
  const row = first.items[0],
    input: LedgerRequest = {
      section: "components",
      customerId: ledgerIds.customer,
      snapshot: first.snapshot,
      eventKind: row.event_kind,
      eventId: row.event_id,
      source: row,
    };
  expect((await api.read(input, scope())).items).toHaveLength(2);
  await expect(
    api.read({ ...input, source: { ...row } }, scope()),
  ).rejects.toMatchObject({ code: "INVALID_REQUEST" });
  const refreshed = await api.read(request, scope());
  if (refreshed.section !== "history")
    throw new Error("Expected refreshed history");
  await expect(
    api.read({ ...input, snapshot: refreshed.snapshot }, scope()),
  ).rejects.toMatchObject({ code: "INVALID_REQUEST" });
  expect(fetcher).toHaveBeenCalledTimes(3);
});

it.each([
  [1, 2, false],
  [3, 2, false],
  [3, 4, false],
  [5, 4, false],
  [2, 2, true],
] as const)(
  "TEST-FE-581 rejects missing/excess ledger rows declared=%s actual=%s extraCursor=%s across pages",
  async (declared, actual, extraCursor) => {
    for (const section of ["history", "components"] as const) {
      const source = ledgerEvent("INVOICE_ISSUED", 1, {
        component_count: declared,
      });
      const events =
        section === "components"
          ? [source]
          : Array.from({ length: actual }, (_, index) =>
              ledgerEvent("INVOICE_ISSUED", index + 1),
            );
      const components = Array.from({ length: actual }, (_, index) =>
        ledgerComponent(source, index + 1),
      );
      const api = createCustomerLedgerClient(async (url, init) => {
        const wireUrl = ledgerRequestUrl(url),
          options = init ?? {};
        const response = syntheticLedgerResponse(wireUrl, options, {
          events,
          components,
        });
        const envelope = financialObject(await response.json());
        const data = financialObject(envelope.data);
        if (section === "history") data.event_count = declared;
        if (data.section === section && extraCursor) {
          const items = data.items as FinancialObject[];
          financialObject(envelope.page).next_cursor = ledgerCursorToken(
            items.at(-1) ?? {},
            section,
          );
        }
        return ledgerWireResponse(envelope, options);
      });
      let selected: LedgerRequest = { ...request, limit: 2 };
      if (section === "components") {
        const history = await api.read(request, scope());
        if (history.section !== "history" || !history.items[0])
          throw new Error("Missing synthetic source");
        selected = {
          section,
          customerId: ledgerIds.customer,
          limit: 2,
          snapshot: history.snapshot,
          source: history.items[0],
          eventKind: "INVOICE_ISSUED",
          eventId: ledgerId(1),
        };
      }
      await expect(
        (async () => {
          for (let page = 0; page < 3; page++) {
            const reply = await api.read(selected, scope());
            if (reply.section === "customers")
              throw new Error("Wrong synthetic section");
            if (!reply.nextCursor) return;
            selected = {
              ...selected,
              snapshot: reply.snapshot,
              cursor: reply.nextCursor,
            };
          }
        })(),
      ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    }
  },
);

it.each([
  "usd_accounting_value_cents",
  "channel_actual_usd_value_cents",
  "amount_usd_cents",
])(
  "TEST-FE-582 validates monetary audit key %s before rendering any nested evidence",
  async (key) => {
    for (const value of [
      "not-money",
      "9".repeat(65),
      "01",
      "-1",
      100,
      true,
      ["not-money"],
    ]) {
      const api = createCustomerLedgerClient(
        serve((envelope) => {
          const data = financialObject(envelope.data);
          data.items = [
            ledgerEvent("PAYMENT_RECEIVED", 1, {
              source_audit: { original: { [key]: value } },
            }),
          ];
          data.event_count = 1;
        }),
      );
      await expect(api.read(request, scope())).rejects.toMatchObject({
        code: "INVALID_RESPONSE",
      });
    }
  },
);

it("TEST-FE-583 accepts complete continuation, filtered subsets and exact/null audit money", async () => {
  const events = Array.from({ length: 3 }, (_, index) =>
    ledgerEvent("INVOICE_ISSUED", index + 1, {
      component_count: 3,
      source_audit: {
        usd_accounting_value_cents: "9".repeat(64),
        channel_actual_usd_value_cents: null,
        nested: { amount_usd_cents: "0" },
      },
    }),
  );
  const api = createCustomerLedgerClient((url, init) =>
    Promise.resolve(
      syntheticLedgerResponse(ledgerRequestUrl(url), init ?? {}, {
        events,
        components: Array.from({ length: 3 }, (_, index) =>
          ledgerComponent(events[0], index + 1),
        ),
      }),
    ),
  );
  const first = await api.read({ ...request, limit: 2 }, scope());
  if (first.section !== "history" || !first.nextCursor || !first.items[0])
    throw new Error("Expected history continuation");
  const next = await api.read(
    {
      ...request,
      limit: 2,
      snapshot: first.snapshot,
      cursor: first.nextCursor,
    },
    scope(),
  );
  expect(next.items).toHaveLength(1);
  expect(next.nextCursor).toBeNull();
  const source: LedgerRequest = {
    section: "components",
    customerId: ledgerIds.customer,
    eventKind: "INVOICE_ISSUED",
    eventId: ledgerId(1),
    source: first.items[0],
    snapshot: first.snapshot,
    limit: 2,
  };
  const components = await api.read(source, scope());
  expect(components.items).toHaveLength(2);
  if (!components.nextCursor)
    throw new Error("Expected component continuation");
  const last = await api.read(
    { ...source, cursor: components.nextCursor },
    scope(),
  );
  expect(last.items).toHaveLength(1);
  expect(last.nextCursor).toBeNull();
  const filtered = await api.read(
    { ...request, filters: { from: "2026-07-03T00:00:00Z" } },
    scope(),
  );
  expect(filtered.items).toHaveLength(1);
  const empty = await api.read(
    { ...request, filters: { kind: "REFUND_PAID" } },
    scope(),
  );
  expect(empty.items).toHaveLength(0);
});
