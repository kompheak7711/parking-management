import { FinancialActionContextSequence } from "../financialActionContextSequence";
import { actionContextFixtures } from "./financialActionContextFixtures";
import type { FinancialObject } from "../financialContracts";
import {
  ids as contextIds,
  fixture as financialFixture,
} from "./financialFixtures";
import { PaymentReversalContextSequence } from "../paymentReversalContextSequence";
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
    await contextProvenanceBrowserChecks(actor, property, payment);
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
    passed.push("TEST-FE-372");
    passed.push("TEST-FE-373");
    return passed;
  } finally {
    await sealedIntentStore.clear(actor, key);
  }
}

async function contextProvenanceBrowserChecks(
  actor: string,
  property: string,
  payment: string,
): Promise<void> {
  const revision = "c".repeat(64),
    firstId = "60000000-0000-4000-8000-000000000001",
    lastId = "60000000-0000-4000-8000-000000000002",
    cursor = `${revision}:3:${firstId}`;
  function rejects(action: () => void, message: string): void {
    let rejected = false;
    try {
      action();
    } catch {
      rejected = true;
    }
    check(rejected, message);
  }
  const client = createFinancialReferenceClient((url, init) => {
    check(typeof url === "string", "Finite provenance URL");
    const query = new URL(url, "https://synthetic.invalid").searchParams,
      view = query.get("view"),
      identity = query.has("cursor") ? lastId : firstId,
      headers = new Headers(init?.headers),
      requestId = headers.get("X-Request-ID");
    check(
      requestId && init?.method === "GET" && !init.body,
      "Provenance is read-only",
    );
    check(!headers.has("Idempotency-Key"), "No new command key");
    const value =
      view === "impact"
        ? {
            source_kind: "PAYMENT",
            source_id: payment,
            target_kind: "CREDIT",
            target_id: identity,
            amount_usd_cents: 100,
            occurred_at: "2026-09-01T05:00:00Z",
          }
        : {
            recognized_usd_cents: 100,
            applied_usd_cents: 0,
            refunded_usd_cents: 0,
            reversed_usd_cents: 0,
            available_usd_cents: 100,
          };
    return Promise.resolve(
      new Response(
        stringifyFinancialJson({
          data: {
            payment_resource: financialFixture("paymentGet").data,
            view,
            revision,
            items: [{ ordinal: 3, kind: "CREDIT", id: identity, data: value }],
          },
          page: { limit: 1, next_cursor: identity === firstId ? cursor : null },
          meta: {
            actor_id: headers.get("X-Billing-Actor-ID"),
            property_id: property,
            request_id: requestId,
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
  const scope = {
    actorId: actor,
    propertyId: property,
    signal: new AbortController().signal,
  };
  for (const view of ["impact", "result"] as const) {
    const request = {
        operation: "paymentReversalContext" as const,
        payment_id: payment,
        view,
        limit: 1,
      },
      last = await client.read(scope, { ...request, cursor });
    for (const alleged of [undefined, null, cursor]) {
      const sequence = new PaymentReversalContextSequence(
        actor,
        property,
        payment,
        view,
      );
      rejects(() => {
        sequence.append(last, alleged);
      }, "Continuation cannot establish complete impact/result");
      check(!sequence.complete, "Rejected final-only sequence is incomplete");
    }
    const first = await client.read(scope, request),
      sequence = new PaymentReversalContextSequence(
        actor,
        property,
        payment,
        view,
      );
    const assertScope = () => {
      for (const field of ["actorId", "propertyId", "paymentId", "view"]) {
        rejects(() => {
          Object.assign(sequence, { [field]: "forged" });
        }, "Scope assignment must fail");
        rejects(() => {
          Object.defineProperty(sequence, field, { value: "forged" });
        }, "Scope shadowing must fail");
      }
      rejects(() => {
        Object.setPrototypeOf(sequence, {});
      }, "Scope prototype must remain fixed");
      check(
        sequence.actorId === actor &&
          sequence.propertyId === property &&
          sequence.paymentId === payment &&
          sequence.view === view,
        "Original runtime scope preserved",
      );
    };
    assertScope();
    sequence.append(first);
    assertScope();
    check(!sequence.complete, "First page incomplete");
    sequence.append(last);
    assertScope();
    check(
      contextProgress(sequence).complete,
      "Actual captured continuation completes without a cursor argument",
    );
    const copied = new PaymentReversalContextSequence(
      actor,
      property,
      payment,
      view,
    );
    rejects(() => {
      copied.append({ ...first });
    }, "A reply copy has no client provenance");
    const mixed = new PaymentReversalContextSequence(
      actor,
      property,
      payment,
      view,
    );
    mixed.append(first);
    const foreignActor = crypto.randomUUID();
    rejects(() => {
      Object.assign(mixed, { actorId: foreignActor });
    }, "Actor cannot bridge pages");
    const foreign = await client.read(
      { ...scope, actorId: foreignActor },
      { ...request, cursor },
    );
    rejects(() => {
      mixed.append(foreign, cursor);
    }, "Foreign actor continuation rejected");
    check(!mixed.complete, "Mixed actor sequence incomplete");
  }
}

export async function runFinancialActionContextBrowserChecks(): Promise<
  string[]
> {
  const actor = crypto.randomUUID(),
    key = crypto.randomUUID(),
    plaintext =
      '{"synthetic_pending":"action context never retires an unknown command"}';
  await sealedIntentStore.begin(actor, { requestKey: key, plaintext });
  let calls = 0;
  try {
    for (const fixture of actionContextFixtures) {
      const sample = structuredClone(fixture),
        controller = new AbortController();
      const scope = {
        actorId: actor,
        propertyId: sample.propertyId,
        signal: controller.signal,
      };
      const client = createFinancialReferenceClient((url, init) => {
        check(typeof url === "string", "Action context finite URL");
        const headers = new Headers(init?.headers),
          requestId = headers.get("X-Request-ID");
        check(
          requestId &&
            headers.get("X-Billing-Actor-ID") === actor &&
            headers.get("X-Financial-Property-ID") === sample.propertyId,
          "Action read scope",
        );
        check(
          init?.method === "GET" &&
            init.body === undefined &&
            init.cache === "no-store" &&
            headers.get("Idempotency-Key") === null &&
            headers.get("X-CSRF-Token") === null,
          "Read never creates a command",
        );
        calls += 1;
        return Promise.resolve(
          new Response(
            stringifyFinancialJson(
              {
                data: sample.data,
                page: sample.page,
                meta: {
                  actor_id: actor,
                  property_id: sample.propertyId,
                  request_id: requestId,
                },
              },
              1_048_576,
            ),
            {
              headers: {
                "Content-Type": "application/json",
                "X-Request-ID": requestId,
              },
            },
          ),
        );
      });
      const reply = await client.read(scope, sample.request);
      const sequence = new FinancialActionContextSequence(
        actor,
        sample.propertyId,
        sample.request,
      );
      sequence.append(reply);
      check(
        sequence.complete && sequence.data !== null,
        "Actual PostgreSQL source becomes complete in Chromium",
      );
      let rejected = false;
      try {
        new FinancialActionContextSequence(
          actor,
          sample.propertyId,
          sample.request,
        ).append({ ...reply });
      } catch {
        rejected = true;
      }
      check(rejected, "Copied response cannot establish request provenance");
      rejected = false;
      try {
        Object.defineProperty(sequence, "actorId", {
          value: crypto.randomUUID(),
        });
      } catch {
        rejected = true;
      }
      check(
        rejected && sequence.actorId === actor,
        "Runtime context binding cannot change",
      );
      const before = calls;
      controller.abort();
      const failure: unknown = await client
        .read(scope, sample.request)
        .catch((error: unknown) => error);
      check(
        failure instanceof FinancialReferenceError &&
          failure.code === "WORKSPACE_INVALIDATED" &&
          calls === before,
        "Aborted scope sends no request",
      );
    }
    const fixture = actionContextFixtures.find(
      (sample) =>
        sample.request.purpose === "allocation" &&
        sample.request.target_kind === "INVOICE",
    );
    check(fixture, "Synthetic Invoice posting source");
    const sample = structuredClone(fixture),
      revision = sample.data.revision;
    check(typeof revision === "string", "Revision is exact");
    const cursor = `${revision}:1:${contextIds.event}`,
      originalItem = financialObject(
        (sample.data.items as FinancialObject[])[0],
      );
    const scope = {
      actorId: actor,
      propertyId: sample.propertyId,
      signal: new AbortController().signal,
    };
    const request = { ...sample.request, limit: 1 };
    const large = 9007199254740993n;
    sample.data.item_count = 2;
    const declaredTarget = financialObject(sample.data.target);
    declaredTarget.line_count = 2;
    declaredTarget.outstanding_usd_cents = large;
    declaredTarget.original_total_usd_cents = large;
    declaredTarget.adjusted_total_usd_cents = large;
    const client = createFinancialReferenceClient((url, init) => {
      check(typeof url === "string", "Finite continuation URL");
      const last = new URL(url, "https://synthetic.invalid").searchParams.has(
          "cursor",
        ),
        headers = new Headers(init?.headers),
        requestId = headers.get("X-Request-ID");
      check(requestId, "Actual browser correlation");
      const amount = last ? large - 1n : 1n;
      const data = {
        ...sample.data,
        items: [
          {
            ...originalItem,
            sequence: last ? 2 : 1,
            id: last ? contextIds.other : contextIds.event,
            data: {
              ...financialObject(originalItem.data),
              original_amount_usd_cents: amount,
              adjusted_amount_usd_cents: amount,
              outstanding_usd_cents: amount,
            },
          },
        ],
      };
      return Promise.resolve(
        new Response(
          stringifyFinancialJson(
            {
              data,
              page: { limit: 1, next_cursor: last ? null : cursor },
              meta: {
                actor_id: actor,
                property_id: sample.propertyId,
                request_id: requestId,
              },
            },
            1_048_576,
          ),
          {
            headers: {
              "Content-Type": "application/json",
              "X-Request-ID": requestId,
            },
          },
        ),
      );
    });
    const first = await client.read(scope, request),
      last = await client.read(scope, { ...request, cursor });
    const sequence = new FinancialActionContextSequence(
      actor,
      sample.propertyId,
      request,
    );
    sequence.append(first);
    const firstProgress = {
      complete: sequence.complete,
      data: sequence.data,
      nextCursor: sequence.nextCursor,
    };
    check(
      !firstProgress.complete &&
        firstProgress.data === null &&
        firstProgress.nextCursor === cursor,
      "First page never implies completion",
    );
    sequence.append(last);
    const snapshot = sequence.data;
    check(
      sequence.complete &&
        snapshot !== null &&
        Array.isArray(snapshot.items) &&
        snapshot.items.length === 2 &&
        financialObject(snapshot.target).outstanding_usd_cents === large,
      "Complete exact large integer target survives real-browser transport",
    );
    let rejected = false;
    try {
      new FinancialActionContextSequence(
        actor,
        sample.propertyId,
        request,
      ).append(last);
    } catch {
      rejected = true;
    }
    check(rejected, "Actual continuation cannot be substituted for first page");
    snapshot.items = [];
    const detachedAgain = sequence.data;
    check(
      detachedAgain !== null &&
        Array.isArray(detachedAgain.items) &&
        detachedAgain.items.length === 2,
      "Detached snapshot cannot mutate completed facts",
    );
    await checkActionContextReviewBoundaries(actor);
    const preserved = await sealedIntentStore.read(actor);
    check(
      preserved?.requestKey === key && preserved.plaintext === plaintext,
      "Action reads preserve actual IndexedDB encrypted pending command",
    );
    check(
      calls === actionContextFixtures.length,
      "All actual PostgreSQL examples checked exactly once",
    );
    const passed: string[] = [];
    passed.push("TEST-FE-387");
    passed.push("TEST-FE-388");
    passed.push("TEST-FE-389");
    passed.push("TEST-FE-400");
    passed.push("TEST-FE-401");
    passed.push("TEST-FE-412");
    return passed;
  } finally {
    await sealedIntentStore.clear(actor, key);
  }
}

async function checkActionContextReviewBoundaries(
  actor: string,
): Promise<void> {
  for (const index of [7, 11, 13, 16, 15, 26, 2]) {
    const fixture = actionContextFixtures[index];
    check(fixture, "Required AA regression fixture exists");
    const sample = structuredClone(fixture),
      context = financialObject(sample.data.context);
    if ([7, 11, 13, 16].includes(index)) {
      const creditSource = index === 11 || index === 16;
      const position = financialObject(
        creditSource
          ? financialObject(context.credit).position
          : financialObject(sample.data.payment_resource).position,
      );
      const aggregate = creditSource
        ? position
        : financialObject(position.dispositions);
      const field =
        index === 7
          ? "allocation_usd_cents"
          : index === 11
            ? "applied_usd_cents"
            : index === 13
              ? "refund_usd_cents"
              : "refunded_usd_cents";
      position.available_usd_cents =
        BigInt(position.available_usd_cents as number) +
        BigInt(aggregate[field] as number);
      aggregate[field] = 0;
    } else if (index === 15) context.reversal = null;
    else if (index === 26) {
      const correction = financialObject(context.correction);
      for (const field of [
        "source_balance_effect_original_minor",
        "verified_return_amount_minor",
        "verified_return_currency",
        "verified_returned_at",
        "return_method_reference",
      ])
        correction[field] = null;
    } else financialObject(context.receipt).identity_snapshot = {};
    const scope = {
      actorId: actor,
      propertyId: sample.propertyId,
      signal: new AbortController().signal,
    };
    const client = createFinancialReferenceClient((_url, init) => {
      const requestId = new Headers(init?.headers).get("X-Request-ID");
      check(requestId, "AA regression uses actual correlation");
      return Promise.resolve(
        new Response(
          stringifyFinancialJson(
            {
              data: sample.data,
              page: sample.page,
              meta: {
                actor_id: actor,
                property_id: sample.propertyId,
                request_id: requestId,
              },
            },
            1_048_576,
          ),
          {
            headers: {
              "Content-Type": "application/json",
              "X-Request-ID": requestId,
            },
          },
        ),
      );
    });
    const sequence = new FinancialActionContextSequence(
      actor,
      sample.propertyId,
      sample.request,
    );
    let rejected = false;
    try {
      sequence.append(await client.read(scope, sample.request));
    } catch {
      rejected = true;
    }
    check(
      rejected && !sequence.complete && sequence.data === null,
      "Contradictory source/Refund/Receipt facts never complete in Chromium",
    );
  }
  const invoice = actionContextFixtures.find(
    (sample) =>
      sample.request.purpose === "allocation" &&
      sample.request.target_kind === "INVOICE",
  );
  const reversed = actionContextFixtures.find(
    (sample) =>
      sample.request.purpose === "credit_reversal" &&
      financialObject(sample.data.context).reversal !== null,
  );
  const khr = actionContextFixtures.find(
    (sample) =>
      sample.request.purpose === "allocation" &&
      financialObject(financialObject(sample.data.payment_resource).payment)
        .received_currency === "KHR",
  );
  check(
    invoice && reversed && khr,
    "Synthetic review regression sources exist",
  );
  for (const kind of ["credit", "fx", "omitted"] as const) {
    const sample = structuredClone(
      kind === "credit" ? reversed : kind === "fx" ? khr : invoice,
    );
    if (kind === "credit") {
      const credit = financialObject(
          financialObject(sample.data.context).credit,
        ),
        position = financialObject(credit.position);
      position.reversed_usd_cents = 0;
      position.available_usd_cents = position.recognized_usd_cents ?? null;
    } else if (kind === "fx") {
      financialObject(sample.data.payment_resource).exchange_rate = null;
    } else {
      const target = financialObject(sample.data.target);
      target.status = "PAID";
      target.outstanding_usd_cents = 0;
      sample.data.items = [];
    }
    const scope = {
      actorId: actor,
      propertyId: sample.propertyId,
      signal: new AbortController().signal,
    };
    const client = createFinancialReferenceClient((_url, init) => {
      const requestId = new Headers(init?.headers).get("X-Request-ID");
      check(requestId, "Actual regression request correlation");
      return Promise.resolve(
        new Response(
          stringifyFinancialJson(
            {
              data: sample.data,
              page: sample.page,
              meta: {
                actor_id: actor,
                property_id: sample.propertyId,
                request_id: requestId,
              },
            },
            1_048_576,
          ),
          {
            headers: {
              "Content-Type": "application/json",
              "X-Request-ID": requestId,
            },
          },
        ),
      );
    });
    const sequence = new FinancialActionContextSequence(
      actor,
      sample.propertyId,
      sample.request,
    );
    let rejected = false;
    try {
      sequence.append(await client.read(scope, sample.request));
    } catch {
      rejected = true;
    }
    check(
      rejected && !sequence.complete && sequence.data === null,
      "Inconsistent source or omitted zero line never completes in Chromium",
    );
  }
  const sample = structuredClone(invoice),
    count = 22;
  sample.request.limit = 1;
  sample.data.item_count = count;
  const target = financialObject(sample.data.target),
    item = financialObject((sample.data.items as FinancialObject[])[0]),
    detail = financialObject(item.data);
  target.status = "PAID";
  target.line_count = count;
  target.outstanding_usd_cents = 0;
  target.original_total_usd_cents =
    BigInt(detail.original_amount_usd_cents as number) * BigInt(count);
  target.adjusted_total_usd_cents =
    BigInt(detail.adjusted_amount_usd_cents as number) * BigInt(count);
  const identities = Array.from({ length: count }, () => crypto.randomUUID());
  const cursorFor = (index: number) =>
    `${sample.data.revision as string}:${(index + 1).toString()}:${identities[index] ?? ""}`;
  const scope = {
    actorId: actor,
    propertyId: sample.propertyId,
    signal: new AbortController().signal,
  };
  const client = createFinancialReferenceClient((url, init) => {
    check(typeof url === "string", "Bounded continuation URL");
    const cursor = new URL(url, "https://synthetic.invalid").searchParams.get(
        "cursor",
      ),
      index =
        cursor === null
          ? 0
          : identities.findIndex((_identity, i) => cursorFor(i) === cursor) + 1;
    check(index >= 0 && index < count, "Known ordered continuation");
    const requestId = new Headers(init?.headers).get("X-Request-ID");
    check(requestId, "Actual budget request correlation");
    return Promise.resolve(
      new Response(
        stringifyFinancialJson(
          {
            data: {
              ...sample.data,
              items: [
                {
                  ...item,
                  sequence: index + 1,
                  id: identities[index] ?? "",
                  data: {
                    ...detail,
                    outstanding_usd_cents: 0,
                    description: "😀".repeat(100_000),
                  },
                },
              ],
            },
            page: {
              limit: 1,
              next_cursor: index + 1 === count ? null : cursorFor(index),
            },
            meta: {
              actor_id: actor,
              property_id: sample.propertyId,
              request_id: requestId,
            },
          },
          1_048_576,
        ),
        {
          headers: {
            "Content-Type": "application/json",
            "X-Request-ID": requestId,
          },
        },
      ),
    );
  });
  const sequence = new FinancialActionContextSequence(
    actor,
    sample.propertyId,
    sample.request,
  );
  let rejected = false;
  for (let index = 0; index < count; index++) {
    const reply = await client.read(scope, {
      ...sample.request,
      ...(index === 0 ? {} : { cursor: cursorFor(index - 1) }),
    });
    try {
      sequence.append(reply);
    } catch {
      rejected = true;
      break;
    }
  }
  check(
    rejected &&
      !sequence.complete &&
      sequence.data === null &&
      sequence.nextCursor === null,
    "Chromium rejects cumulative UTF-8 evidence above eight MiB and releases the sequence",
  );
}
