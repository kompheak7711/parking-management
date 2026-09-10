import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createFinancialTransport,
  FINANCIAL_DEADLINE_MS,
  FINANCIAL_REPLY_BYTES,
} from "./financialClient";
import {
  captureFinancialRequest,
  commandBody,
  financialId,
  financialObject,
  isEnforcementCommand,
  type FinancialObject,
} from "./financialContracts";
import { parseFinancialJson, stringifyFinancialJson } from "./financialJson";
import {
  createEnforcementClient,
  readEnforcement,
} from "./leaseEnforcementClient";
import {
  captureEnforcementRead,
  type EnforcementRead,
} from "./leaseEnforcementContract";
import {
  commands,
  commandResponse,
  ids,
  readInputs,
  readData,
  readResponse,
  scope,
  warningBody,
  warningRecord,
} from "./test/leaseEnforcementFixtures";

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});
describe("Lease enforcement transport contracts", () => {
  it.each(commands)(
    "TEST-FE-589 binds original response metadata and exact command bytes for $operation",
    async (input) => {
      if (!isEnforcementCommand(input.operation)) throw new Error();
      const operation = input.operation;
      const fetcher = vi.fn<typeof fetch>(async (_url, init) =>
        Promise.resolve(commandResponse(operation, init, input.body)),
      );
      const transport = createFinancialTransport(
          fetcher,
          () => "synthetic-csrf",
        ),
        captured = captureFinancialRequest(input);
      const first = await transport.send(scope(), captured, ids.key),
        retry = await transport.send(scope(), captured, ids.key);
      expect(retry).toEqual(first);
      for (const [url, init] of fetcher.mock.calls) {
        expect(url).toMatch(/^\/api\/v1\/(leases|rent-nonpayment-cases)\//);
        expect(init).toMatchObject({
          method: "POST",
          body: captured.wireBody,
          credentials: "include",
          redirect: "error",
          cache: "no-store",
        });
        const headers = new Headers(init?.headers);
        expect(headers.get("X-Request-ID")).toBe(ids.key);
        expect(headers.get("Idempotency-Key")).toBe(ids.key);
        expect(headers.get("X-Billing-Actor-ID")).toBe(ids.actor);
        expect(headers.get("X-Financial-Property-ID")).toBe(ids.property);
        expect(headers.get("X-CSRF-Token")).toBe("synthetic-csrf");
      }
    },
  );
  it.each([
    { warning_sequence: true },
    { warning_sequence: 1.2 },
    { violation_date: "2026-02-29" },
    { warning_date: "2026-09-10T00:00:00Z" },
    { reason: " spaced " },
    { violation_description: "bad\0text" },
    { remaining_rent: 1 },
    { lease_provision: "x".repeat(2001) },
  ])(
    "TEST-FE-590 rejects invalid or server-derived warning input %# before dispatch",
    async (changes) => {
      const fetcher = vi.fn<typeof fetch>();
      const csrf = vi.fn(() => "csrf");
      await expect(
        createFinancialTransport(fetcher, csrf).send(
          scope(),
          {
            operation: "leaseWarningRecord",
            target: { id: ids.lease },
            query: {},
            wireBody: JSON.stringify({ ...warningBody, ...changes }),
          },
          ids.key,
        ),
      ).rejects.toMatchObject({ code: "INVALID_REQUEST", dispatched: false });
      expect(fetcher).not.toHaveBeenCalled();
      expect(csrf).not.toHaveBeenCalled();
    },
  );
  it.each([
    "actor_id",
    "lease_id",
    "violation_description",
    "warning_sequence",
  ])(
    "TEST-FE-591 rejects a successful warning reply with mismatched %s",
    async (field) => {
      const input = commands[0];
      if (!input) throw new Error();
      const fetcher = vi.fn<typeof fetch>(async (_url, init) =>
        Promise.resolve(
          commandResponse("leaseWarningRecord", init, input.body, (row) => {
            row[field] =
              field === "warning_sequence"
                ? 2
                : field.endsWith("_id")
                  ? ids.other
                  : "Different intent";
          }),
        ),
      );
      await expect(
        createFinancialTransport(fetcher, () => "csrf").send(
          scope(),
          captureFinancialRequest(input),
          ids.key,
        ),
      ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    },
  );
  it.each(readInputs)(
    "TEST-FE-592 validates authorized finite read $kind",
    async (input) => {
      const fetcher = vi.fn<typeof fetch>(async (_url, init) =>
        Promise.resolve(readResponse(input, init)),
      );
      const result = await readEnforcement(
        {
          ...scope(),
          propertyId: input.kind === "workspaces" ? null : ids.property,
        },
        input,
        createEnforcementClient(fetcher),
      );
      expect(result).toEqual(readData(input));
      const options = fetcher.mock.calls[0]?.[1],
        headers = new Headers(options?.headers);
      expect(options).toMatchObject({
        method: "GET",
        credentials: "include",
        cache: "no-store",
        redirect: "error",
      });
      expect(options?.body).toBeUndefined();
      expect(headers.has("Idempotency-Key")).toBe(false);
      expect(headers.has("X-CSRF-Token")).toBe(false);
      expect(headers.get("X-Billing-Actor-ID")).toBe(ids.actor);
      expect(headers.get("X-Financial-Property-ID")).toBe(
        input.kind === "workspaces" ? null : ids.property,
      );
    },
  );
  it.each([
    { kind: "unknown" },
    { kind: "alerts", limit: 101 },
    { kind: "alerts", limit: true },
    { kind: "alerts", cursor: "bad" },
    { kind: "events", caseId: ids.case, offset: -1 },
    { kind: "events", caseId: ids.case, offset: 1_000_001 },
    { kind: "leases", purpose: "ADMIN" },
    { kind: "warningContext", leaseId: ids.lease, limit: 25 },
    { kind: "sources", leaseId: ids.lease, grant: "all" },
  ])("TEST-FE-593 rejects unbounded or forged read input %#", (input) => {
    expect(() => captureEnforcementRead(input as EnforcementRead)).toThrow();
  });
  it.each([
    "property",
    "lease",
    "resource",
    "date",
    "money",
    "flag",
    "duplicate",
    "extra",
  ])("TEST-FE-594 rejects incorrect case read evidence %s", async (mode) => {
    const input: EnforcementRead = { kind: "case", caseId: ids.case };
    const data = readData(input);
    if (mode === "property") data.property_id = ids.other;
    if (mode === "lease") data.lease_id = "invalid";
    if (mode === "resource") data.id = ids.other;
    if (mode === "date") data.due_date_snapshot = "2026-02-30";
    if (mode === "money")
      financialObject(
        financialObject(data.assessment).remaining_rent,
      ).minor_units = 0.5;
    if (mode === "flag")
      financialObject(data.assessment).cure_eligible = "false";
    if (mode === "extra") data.customer_email = "synthetic@example.invalid";
    const fetcher = vi.fn<typeof fetch>(async (_url, init) => {
      const response = readResponse(input, init, data);
      return mode === "duplicate"
        ? new Response(
            (await response.text()).replace('"data":', '"data":{},"data":'),
            { headers: response.headers },
          )
        : response;
    });
    await expect(
      createEnforcementClient(fetcher).read(scope(), input),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });
  it.each(["utf8", "media", "request-id", "oversize", "declared", "status"])(
    "TEST-FE-595 rejects invalid or oversized read transport %s",
    async (mode) => {
      const input: EnforcementRead = { kind: "case", caseId: ids.case };
      const fetcher = vi.fn<typeof fetch>(async (_url, init) => {
        const good = readResponse(input, init);
        if (mode === "media") good.headers.set("Content-Type", "text/html");
        if (mode === "request-id") good.headers.set("X-Request-ID", ids.other);
        if (mode === "declared")
          good.headers.set("Content-Length", String(FINANCIAL_REPLY_BYTES + 1));
        if (["media", "request-id", "declared"].includes(mode)) return good;
        return new Response(
          mode === "utf8"
            ? new Uint8Array([0xc3, 0x28])
            : mode === "oversize"
              ? " ".repeat(FINANCIAL_REPLY_BYTES + 1)
              : await good.text(),
          { status: mode === "status" ? 201 : 200, headers: good.headers },
        );
      });
      await expect(
        createEnforcementClient(fetcher).read(scope(), input),
      ).rejects.toMatchObject({ dispatched: true });
    },
  );
  it.each(["fetch", "body"])(
    "TEST-FE-596 bounds a noncooperating read %s by one deadline",
    async (mode) => {
      vi.useFakeTimers();
      const cancel = vi.fn();
      const fetcher = vi.fn<typeof fetch>(async (_url, init) =>
        mode === "fetch"
          ? new Promise<Response>(() => {
              /* Never settles. */
            })
          : Promise.resolve(
              new Response(new ReadableStream({ cancel }), {
                headers: {
                  "Content-Type": "application/json",
                  "X-Request-ID":
                    new Headers(init?.headers).get("X-Request-ID") ?? "",
                },
              }),
            ),
      );
      const pending = createEnforcementClient(fetcher).read(scope(), {
        kind: "case",
        caseId: ids.case,
      });
      const assertion = expect(pending).rejects.toMatchObject({
        code: "UNAVAILABLE",
      });
      await vi.advanceTimersByTimeAsync(FINANCIAL_DEADLINE_MS);
      await assertion;
      if (mode === "body") expect(cancel).toHaveBeenCalledOnce();
    },
  );
  it("TEST-FE-597 captures read identity before awaiting and cancels a late response after invalidation", async () => {
    const controller = new AbortController(),
      mutable = { ...scope(), signal: controller.signal };
    const input: EnforcementRead = { kind: "case", caseId: ids.case };
    let release!: (response: Response) => void;
    const fetcher = vi.fn<typeof fetch>(
      () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }),
    );
    const pending = createEnforcementClient(fetcher).read(mutable, input),
      assertion = expect(pending).rejects.toMatchObject({
        code: "WORKSPACE_INVALIDATED",
      });
    mutable.propertyId = ids.other;
    input.caseId = ids.other;
    controller.abort();
    await assertion;
    expect(fetcher.mock.calls[0]?.[0]).toContain(ids.case);
    expect(
      new Headers(fetcher.mock.calls[0]?.[1]?.headers).get(
        "X-Financial-Property-ID",
      ),
    ).toBe(ids.property);
    const cancel = vi.fn();
    release(new Response(new ReadableStream({ cancel })));
    await Promise.resolve();
    await Promise.resolve();
    expect(cancel).toHaveBeenCalledOnce();
  });
  it("TEST-FE-598 rejects injected read metadata and detaches accepted evidence", async () => {
    const input: EnforcementRead = { kind: "case", caseId: ids.case },
      data = readData(input);
    const read = vi.fn(async () =>
      Promise.resolve({
        data,
        actorId: ids.actor,
        propertyId: ids.property,
        requestId: ids.key,
      }),
    );
    const accepted = await readEnforcement(scope(), input, { read });
    data.lease_id = ids.other;
    expect(accepted.lease_id).toBe(ids.lease);
    read.mockResolvedValue({
      data,
      actorId: ids.other,
      propertyId: ids.property,
      requestId: ids.key,
    });
    await expect(readEnforcement(scope(), input, { read })).rejects.toThrow();
  });
  it("TEST-FE-599 preserves published long warning history but rejects that text for a new command", async () => {
    const body = { ...warningBody, violation_description: "x".repeat(2001) },
      input: EnforcementRead = { kind: "warnings", leaseId: ids.lease };
    const data = {
      items: [warningRecord(body)],
      total: 1,
      limit: 50,
      offset: 0,
    };
    const fetcher = vi.fn<typeof fetch>(async (_url, init) =>
      Promise.resolve(readResponse(input, init, data)),
    );
    expect(
      await readEnforcement(scope(), input, createEnforcementClient(fetcher)),
    ).toEqual(data);
    expect(() =>
      commandBody("leaseWarningRecord", stringifyFinancialJson(body)),
    ).toThrow();
  });
  it("TEST-FE-620 validates keyset order, page bounds and account metadata without tolerating repeated identities", async () => {
    for (const variant of ["actor", "duplicate", "cursor", "count"] as const) {
      const input: EnforcementRead = { kind: "workspaces", limit: 1 },
        data = readData(input),
        rows = data.items as FinancialObject[];
      if (variant === "duplicate") data.items = [rows[0] ?? {}, rows[0] ?? {}];
      if (variant === "cursor") data.next_cursor = ids.other;
      if (variant === "count")
        data.items = [...rows, { ...rows[0], property_id: ids.other }];
      const fetcher = vi.fn<typeof fetch>(async (_url, init) => {
        const good = readResponse(input, init, data);
        if (variant !== "actor") return good;
        const envelope = financialObject(parseFinancialJson(await good.text()));
        financialObject(envelope.meta).actor_id = ids.other;
        return new Response(stringifyFinancialJson(envelope), {
          headers: good.headers,
        });
      });
      await expect(
        createEnforcementClient(fetcher).read(
          { ...scope(), propertyId: null },
          input,
        ),
      ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    }
    expect(financialId(ids.property)).toBe(ids.property);
  });
});
