import {
  ids as contextIds,
  fixture as financialFixture,
} from "./financialFixtures";
import { PaymentReversalContextSequence } from "../paymentReversalContext";
// Real-browser reference transport and preservation of a synthetic encrypted intent.
import {
  createFinancialReferenceClient,
  FINANCIAL_CAPABILITIES,
  FinancialReferenceError,
} from "../financialReferenceClient";
import {
  captureFinancialRequest,
  financialObject,
} from "../financialContracts";
import { createFinancialTransport } from "../financialClient";
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

  const evidence = "Synthetic\nsource\t" + "😀".repeat(300),
    displayName = "Cash\tcounter\n" + "😀".repeat(700);
  const compatible: typeof fetch = (url, init) => {
    const id = new Headers(init?.headers).get("X-Request-ID");
    check(id && typeof url === "string", "Scoped compatible reference");
    const preview = url.endsWith("/khr-preview"),
      global = url.endsWith("/financial-workspaces");
    const data = preview
      ? {
          ...financialObject(quote.data),
          source_reference: evidence,
          fallback_reason: evidence,
          rate_source: "ABA_EQUIVALENT_MANUAL",
          automatic_source_unavailable: true,
        }
      : global
        ? [
            {
              property_id: property,
              name: displayName,
              timezone: "Asia/Phnom_Penh",
              capabilities: permissions,
            },
          ]
        : [
            {
              id: method,
              property_id: property,
              code: "Cash\tcounter",
              display_name: displayName,
            },
          ];
    return Promise.resolve(
      new Response(
        JSON.stringify({
          data,
          meta: {
            actor_id: actor,
            request_id: id,
            ...(global ? {} : { property_id: property }),
          },
          ...(preview ? {} : { page: { limit: 50, next_cursor: null } }),
        }),
        { headers: { "Content-Type": "application/json", "X-Request-ID": id } },
      ),
    );
  };
  const compatibleClient = createFinancialReferenceClient(
    compatible,
    () => "synthetic-csrf",
  );
  for (const operation of ["workspaces", "methods"] as const) {
    const reply = await compatibleClient.read(
      operation === "workspaces"
        ? { actorId: actor, signal: scope.signal }
        : scope,
      { operation },
    );
    check(Array.isArray(reply.data), "Compatible reference page");
    check(
      financialObject(reply.data[0])[
        operation === "workspaces" ? "name" : "display_name"
      ] === displayName,
      "Whole configured label survives actual browser transport",
    );
  }
  const manualReply = await compatibleClient.read(scope, {
    operation: "khrPreview",
    usd_amount_cents: 1001,
    manual_reference: {
      reference_rate_khr_per_usd: "4062.000000",
      source_reference: evidence,
      applicable_at: "2026-05-01T00:00:00Z",
      fallback_reason: evidence,
    },
  });
  check(
    financialObject(manualReply.data).source_reference === evidence &&
      financialObject(manualReply.data).fallback_reason === evidence,
    "Unicode and internal whitespace manual evidence remains exact",
  );
  passed.push("TEST-FE-355");

  for (const transport of ["reference", "financial"] as const) {
    const abort = new AbortController();
    let finish: ((value: Response) => void) | undefined;
    const cancellation = { count: 0 };
    const late: typeof fetch = () =>
      new Promise<Response>((resolve) => {
        finish = resolve;
      });
    const context = { ...scope, signal: abort.signal };
    const request =
      transport === "reference"
        ? createFinancialReferenceClient(late).read(context, {
            operation: "methods",
          })
        : createFinancialTransport(late).send(
            context,
            captureFinancialRequest({ operation: "paymentList", target: {} }),
          );
    const result = request.catch((error: unknown) => error);
    abort.abort();
    check(
      (await result) instanceof Error,
      "Interrupted request settles without a response",
    );
    check(finish, "Synthetic fetch was dispatched");
    const stream = new ReadableStream<Uint8Array>({
      cancel() {
        cancellation.count += 1;
        return new Promise<void>(() => {
          /* Cleanup itself deliberately never settles. */
        });
      },
    });
    finish(new Response(stream));
    await Promise.resolve();
    await Promise.resolve();
    check(
      cancellation.count === 1,
      "Late stream is cancelled in actual Chromium",
    );
    check(
      (await stream.getReader().read()).done,
      "Cancelled late stream is closed despite noncooperating cleanup",
    );
  }
  passed.push("TEST-FE-356");
  return passed;
}

function contextProgress(sequence: PaymentReversalContextSequence): {
  complete: boolean;
  nextCursor: string | null;
} {
  return { complete: sequence.complete, nextCursor: sequence.nextCursor };
}
export async function runPaymentReversalContextBrowserChecks(): Promise<
  string[]
> {
  const actor = crypto.randomUUID(),
    key = crypto.randomUUID(),
    revision = "a".repeat(64);
  const property = contextIds.property,
    payment = contextIds.payment;
  const controller = new AbortController(),
    scope = { actorId: actor, propertyId: property, signal: controller.signal };
  const plaintext =
    '{"synthetic_pending":"original request bytes survive reversal context reads"}';
  const cursor = `${revision}:3:${contextIds.credit}`;
  const sequence = new PaymentReversalContextSequence(
    actor,
    property,
    payment,
    "impact",
  );
  const original = financialFixture("paymentGet").data;
  const calls: string[] = [];
  const client = createFinancialReferenceClient((url, init) => {
    check(typeof url === "string", "Finite context URL");
    const parsed = new URL(url, "https://synthetic.invalid");
    check(
      parsed.pathname ===
        `/api/v1/properties/${property}/payments/${payment}/reversal-context`,
      "Original Payment and Property path",
    );
    check(
      init?.method === "GET" &&
        init.body === undefined &&
        init.cache === "no-store",
      "Context is a read",
    );
    const headers = new Headers(init.headers),
      requestId = headers.get("X-Request-ID");
    check(
      requestId &&
        headers.get("X-Billing-Actor-ID") === actor &&
        headers.get("X-Financial-Property-ID") === property,
      "Captured exact context identity",
    );
    check(
      headers.get("Idempotency-Key") === null &&
        headers.get("X-CSRF-Token") === null,
      "Read never creates a financial command",
    );
    calls.push(url);
    const result = parsed.searchParams.get("view") === "result";
    const next = parsed.searchParams.get("cursor");
    check(next === null || next === cursor, "Finite continuation");
    const identity = next === null ? contextIds.credit : contextIds.other;
    const items = result
      ? [
          {
            ordinal: 1,
            kind: "INVOICE",
            id: contextIds.invoice,
            data: {
              invoice_number: "Invoice\tOriginal\n😀",
              status: "UNPAID",
              outstanding_usd_cents: 9007199254740993n,
            },
          },
        ]
      : [
          {
            ordinal: 3,
            kind: "CREDIT",
            id: identity,
            data: {
              source_kind: "PAYMENT",
              source_id: payment,
              target_kind: "CREDIT",
              target_id: identity,
              amount_usd_cents: 50,
              occurred_at: "2026-09-01T05:00:00Z",
            },
          },
        ];
    const raw = stringifyFinancialJson({
      data: {
        payment_resource: original,
        view: result ? "result" : "impact",
        revision,
        items,
      },
      page: { limit: 1, next_cursor: result || next !== null ? null : cursor },
      meta: { actor_id: actor, property_id: property, request_id: requestId },
    });
    const bytes = new TextEncoder().encode(raw);
    return Promise.resolve(
      new Response(
        new ReadableStream<Uint8Array>({
          start(stream) {
            for (let i = 0; i < bytes.length; i += 31)
              stream.enqueue(bytes.slice(i, i + 31));
            stream.close();
          },
        }),
        {
          headers: {
            "Content-Type": "application/json",
            "X-Request-ID": requestId,
          },
        },
      ),
    );
  });
  await sealedIntentStore.begin(actor, { requestKey: key, plaintext });
  try {
    const request = {
      operation: "paymentReversalContext" as const,
      payment_id: payment,
      limit: 1,
    };
    sequence.append(await client.read(scope, request));
    check(
      !sequence.complete && sequence.nextCursor === cursor,
      "A partial page never claims complete impact",
    );
    sequence.append(await client.read(scope, { ...request, cursor }), cursor);
    const completed = contextProgress(sequence);
    check(
      completed.complete && completed.nextCursor === null,
      "Complete original impact after exact continuation",
    );
    const result = await client.read(scope, { ...request, view: "result" });
    const rows = financialObject(result.data).items;
    check(
      Array.isArray(rows) &&
        financialObject(financialObject(rows[0]).data).outstanding_usd_cents ===
          9007199254740993n,
      "Actual browser preserves exact large result integer",
    );
    check(
      financialObject(financialObject(rows[0]).data).invoice_number ===
        "Invoice\tOriginal\n😀",
      "Whole original label survives byte-boundary decoding",
    );
    const conflict = createFinancialReferenceClient((_url, init) => {
      const requestId = new Headers(init?.headers).get("X-Request-ID");
      check(requestId, "Conflict correlation");
      return Promise.resolve(
        new Response(
          JSON.stringify({
            error: { code: "CONFLICT" },
            meta: { request_id: requestId },
          }),
          {
            status: 409,
            headers: {
              "Content-Type": "application/json",
              "X-Request-ID": requestId,
            },
          },
        ),
      );
    });
    const changed: unknown = await conflict
      .read(scope, { ...request, cursor })
      .catch((error: unknown) => error);
    check(
      changed instanceof FinancialReferenceError && changed.status === 409,
      "Changed revision stays an explicit reload rejection",
    );
    const late = new AbortController();
    const pending = createFinancialReferenceClient(
      () =>
        new Promise<never>(() => {
          /* Synthetic transport ignores cancellation. */
        }),
    ).read({ ...scope, signal: late.signal }, request);
    late.abort();
    const stopped: unknown = await pending.catch((error: unknown) => error);
    check(
      stopped instanceof FinancialReferenceError &&
        stopped.code === "WORKSPACE_INVALIDATED",
      "Stale workspace settles noncooperating context read",
    );
    const before = calls.length;
    controller.abort();
    const invalid: unknown = await client
      .read(scope, request)
      .catch((error: unknown) => error);
    check(
      invalid instanceof FinancialReferenceError && calls.length === before,
      "Invalidated Property sends no context request",
    );
    const preserved = await sealedIntentStore.read(actor);
    check(
      preserved?.requestKey === key && preserved.plaintext === plaintext,
      "All context reads and rejections preserve original encrypted pending intent",
    );
    const passed: string[] = [];
    passed.push("TEST-FE-365");
    passed.push("TEST-FE-366");
    return passed;
  } finally {
    await sealedIntentStore.clear(actor, key);
  }
}
