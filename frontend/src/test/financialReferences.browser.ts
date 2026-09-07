// Real-browser reference transport and preservation of a synthetic encrypted intent.
import {
  createFinancialReferenceClient,
  FINANCIAL_CAPABILITIES,
  FinancialReferenceError,
} from "../financialReferenceClient";
import { financialObject } from "../financialContracts";
import { stringifyFinancialJson } from "../financialJson";
import { sealedIntentStore } from "../sealedIntentStore";
function check(value: unknown, message: string): asserts value {
  if (!value) throw new Error(message);
}
export async function runFinancialReferenceBrowserChecks(): Promise<string[]> {
  const passed: string[] = [],
    actor = crypto.randomUUID(),
    property = crypto.randomUUID(),
    method = crypto.randomUUID();
  const permissions = Object.fromEntries(
    FINANCIAL_CAPABILITIES.map((cap) => [cap, cap === "payments.record"]),
  );
  const requests: {
    url: string;
    method: string;
    idempotency: string | null;
    body: string | null;
  }[] = [];
  const fetcher: typeof fetch = (url, init) => {
    check(typeof url === "string", "Finite reference path");
    const headers = new Headers(init?.headers),
      requestId = headers.get("X-Request-ID");
    check(
      headers.get("X-Billing-Actor-ID") === actor && requestId,
      "Captured actor and local correlation",
    );
    const global = url.endsWith("/financial-workspaces"),
      preview = url.endsWith("/khr-preview");
    if (!global)
      check(
        headers.get("X-Financial-Property-ID") === property,
        "Scoped Property",
      );
    const data = global
      ? [
          {
            property_id: property,
            name: "Synthetic reference property",
            timezone: "Asia/Phnom_Penh",
            capabilities: permissions,
          },
        ]
      : url.endsWith("/payment-methods")
        ? [
            {
              id: method,
              property_id: property,
              code: "CASH",
              display_name: "Synthetic accepted cash",
            },
          ]
        : preview
          ? {
              property_id: property,
              usd_amount_cents: 1001,
              provisional: true,
              status: "available",
              reference_rate_khr_per_usd: "4062.000000",
              source_reference: "Synthetic approved ABA quote",
              applicable_at: "2026-05-01T00:00:00Z",
              fallback_reason: null,
              rate_source: "ABA_AUTOMATIC",
              automatic_source_unavailable: false,
              markup_basis_points: 50,
              system_rate_khr_per_usd: 4083,
              unrounded_khr_amount: "40870.83",
              payable_khr_amount: 40871,
            }
          : { property_id: property, capabilities: permissions };
    requests.push({
      url,
      method: init?.method ?? "",
      idempotency: headers.get("Idempotency-Key"),
      body: typeof init?.body === "string" ? init.body : null,
    });
    const row = {
      data,
      meta: {
        request_id: requestId,
        actor_id: actor,
        ...(global ? {} : { property_id: property }),
      },
      ...(global || url.endsWith("/payment-methods")
        ? { page: { limit: 50, next_cursor: null } }
        : {}),
    };
    return Promise.resolve(
      new Response(JSON.stringify(row), {
        headers: {
          "Content-Type": "application/json",
          "X-Request-ID": requestId,
        },
      }),
    );
  };
  const scope = {
    actorId: actor,
    propertyId: property,
    signal: new AbortController().signal,
  };
  const client = createFinancialReferenceClient(
    fetcher,
    () => "synthetic-csrf",
  );
  await client.read(
    { actorId: actor, signal: scope.signal },
    { operation: "workspaces" },
  );
  await client.read(scope, { operation: "capabilities" });
  await client.read(scope, { operation: "methods" });
  const quote = await client.read(scope, {
    operation: "khrPreview",
    usd_amount_cents: 1001,
  });
  check(
    financialObject(quote.data).payable_khr_amount === 40871,
    "Exact server quote validated in real browser",
  );
  check(
    requests.length === 4 &&
      requests.every((request) => request.idempotency === null),
    "No reference allocates financial idempotency",
  );
  check(
    requests[3]?.method === "POST" &&
      requests[3].body === '{"usd_amount_cents":1001}',
    "Explicit provisional payload",
  );
  passed.push("TEST-FE-344");
  const controller = new AbortController();
  const stalled: typeof fetch = () =>
    new Promise<never>(() => {
      /* Deliberately ignore abort. */
    });
  const pending = createFinancialReferenceClient(stalled).read(
    { ...scope, signal: controller.signal },
    { operation: "methods" },
  );
  controller.abort();
  const stopped: unknown = await pending.catch((error: unknown) => error);
  check(
    stopped instanceof FinancialReferenceError &&
      stopped.code === "WORKSPACE_INVALIDATED",
    "Browser abort settles noncooperating transport",
  );
  const streamed: typeof fetch = (_url, init) => {
    const id = new Headers(init?.headers).get("X-Request-ID");
    check(id, "Request correlation");
    const text = stringifyFinancialJson({
      data: {
        property_id: property,
        usd_amount_cents: 9000000000000000n,
        provisional: true,
        status: "available",
        reference_rate_khr_per_usd: "0.000001",
        source_reference: "Synthetic exact source",
        applicable_at: "2026-05-01T00:00:00Z",
        fallback_reason: null,
        rate_source: "ABA_AUTOMATIC",
        automatic_source_unavailable: false,
        markup_basis_points: 50,
        system_rate_khr_per_usd: 1,
        unrounded_khr_amount: "90000000000000.00",
        payable_khr_amount: 90000000000000,
      },
      meta: { request_id: id, actor_id: actor, property_id: property },
    });
    const bytes = new TextEncoder().encode(text);
    return Promise.resolve(
      new Response(
        new ReadableStream<Uint8Array>({
          start(stream) {
            stream.enqueue(bytes.slice(0, 37));
            stream.enqueue(bytes.slice(37));
            stream.close();
          },
        }),
        { headers: { "Content-Type": "application/json", "X-Request-ID": id } },
      ),
    );
  };
  const exact = await createFinancialReferenceClient(
    streamed,
    () => "synthetic-csrf",
  ).read(scope, {
    operation: "khrPreview",
    usd_amount_cents: 9000000000000000n,
  });
  check(
    financialObject(exact.data).payable_khr_amount === 90000000000000,
    "Exact stream and bigint capture",
  );
  passed.push("TEST-FE-345");
  const key = crypto.randomUUID(),
    plaintext = '{"synthetic_pending":"must remain unchanged"}';
  await sealedIntentStore.begin(actor, { requestKey: key, plaintext });
  try {
    const before = await sealedIntentStore.read(actor);
    await client.read(scope, {
      operation: "khrPreview",
      usd_amount_cents: 1001,
    });
    const after = await sealedIntentStore.read(actor);
    check(
      before?.requestKey === key &&
        after?.requestKey === key &&
        before.plaintext === plaintext &&
        after.plaintext === plaintext,
      "Read-only preview preserves existing encrypted pending key and original bytes",
    );
    passed.push("TEST-FE-346");
  } finally {
    await sealedIntentStore.clear(actor, key);
  }
  return passed;
}
