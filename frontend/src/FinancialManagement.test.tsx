import { StrictMode } from "react";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FinancialManagement } from "./FinancialManagement";
import { FinancialCommandEvidence } from "./FinancialEvidence";
import { createFinancialTransport } from "./financialClient";
import {
  captureFinancialRequest,
  commandBody,
  financialObject,
  isFinancialCommand,
  type FinancialObject,
} from "./financialContracts";
import {
  FINANCIAL_CAPABILITIES,
  createFinancialReferenceClient,
} from "./financialReferenceClient";
import {
  createFinancialRecovery,
  decodeFinancialIntent,
  type FinancialAttemptCoordinator,
} from "./financialRecovery";
import { parseFinancialJson, stringifyFinancialJson } from "./financialJson";
import type { FinancialUiServices } from "./financialUi";
import type { OpenIntent, SealedIntentStore } from "./sealedIntentStore";
import { commands as commandFixtures, ids } from "./test/financialFixtures";

afterEach(cleanup);
function deferred() {
  let release!: () => void;
  const promise = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { promise, release };
}
function harness(paymentGrant = false) {
  const records = new Map<string, OpenIntent>();
  let outcome: "success" | "unknown" | 400 | 409 | 412 | 422 = "success";
  let sourceUnavailable = false,
    sourceAvailable = 200;
  let failStorage: "none" | "read" | "begin" = "none";
  let denyAttempt = false,
    grant = true;
  let barrier: {
    phase:
      | "discovery"
      | "capabilities"
      | "source"
      | "methods"
      | "post"
      | "begin";
    promise: Promise<void>;
  } | null = null;
  const calls: {
    url: string;
    method: string;
    body: string | null;
    key: string | null;
    property: string | null;
    actor: string | null;
    signal: AbortSignal | null | undefined;
  }[] = [];
  const store = {
    read: vi.fn<SealedIntentStore["read"]>((actor) =>
      Promise.resolve().then(() => {
        if (failStorage === "read")
          throw new Error("Synthetic storage unavailable");
        return records.get(actor) ?? null;
      }),
    ),
    begin: vi.fn<SealedIntentStore["begin"]>(async (actor, value) => {
      if (barrier?.phase === "begin") await barrier.promise;
      if (failStorage === "begin" || records.has(actor))
        throw new Error("Synthetic reservation unavailable");
      records.set(actor, { ...value });
    }),
    clear: vi.fn<SealedIntentStore["clear"]>((actor, key) =>
      Promise.resolve().then(() => {
        if (records.get(actor)?.requestKey !== key)
          throw new Error("Wrong original key");
        records.delete(actor);
      }),
    ),
  };
  const held = new Set<string>();
  const attempts: FinancialAttemptCoordinator = {
    async run<T>(actor: string, action: () => Promise<T>) {
      if (denyAttempt || held.has(actor)) return null;
      held.add(actor);
      try {
        return await action();
      } finally {
        held.delete(actor);
      }
    },
  };
  function grants() {
    return Object.fromEntries(
      FINANCIAL_CAPABILITIES.map((name) => [
        name,
        (name === "refunds.create" && grant) ||
          (name === "payments.record" && paymentGrant),
      ]),
    );
  }
  const fetcher: typeof fetch = async (url, init) => {
    if (typeof url !== "string")
      throw new Error("Expected finite synthetic URL");
    const headers = new Headers(init?.headers),
      property = headers.get("X-Financial-Property-ID"),
      actor = headers.get("X-Billing-Actor-ID"),
      requestId = headers.get("X-Request-ID");
    const call = {
      url,
      method: init?.method ?? "",
      body: typeof init?.body === "string" ? init.body : null,
      key: headers.get("Idempotency-Key"),
      property,
      actor,
      signal: init?.signal,
    };
    calls.push(call);
    const phase = url.includes("financial-workspaces")
      ? "discovery"
      : url.includes("financial-capabilities")
        ? "capabilities"
        : url.includes("/payment-methods")
          ? "methods"
          : call.method === "POST"
            ? "post"
            : "source";
    if (barrier?.phase === phase) await barrier.promise;
    const reply = (
      data: FinancialObject | FinancialObject[],
      page?: FinancialObject,
      status = 200,
    ) =>
      new Response(
        stringifyFinancialJson({
          data,
          ...(page ? { page } : {}),
          meta: {
            request_id: requestId,
            actor_id: actor,
            ...(property ? { property_id: property } : {}),
          },
        }),
        {
          status,
          headers: {
            "Content-Type": "application/json",
            "X-Request-ID": requestId ?? "",
          },
        },
      );
    if (phase === "discovery")
      return reply(
        [
          {
            property_id: ids.property,
            name: "Synthetic River Property",
            timezone: "Asia/Phnom_Penh",
            capabilities: { ...grants(), "refunds.create": true },
          },
          {
            property_id: ids.other,
            name: "Synthetic Garden Property",
            timezone: "Asia/Phnom_Penh",
            capabilities: { ...grants(), "refunds.create": true },
          },
        ],
        { limit: 100, next_cursor: null },
      );
    if (phase === "capabilities")
      return reply({ property_id: property, capabilities: grants() });
    if (phase === "methods")
      return reply(
        [
          {
            id: ids.method,
            property_id: property,
            code: "CASH",
            display_name: "Synthetic accepted cash",
          },
        ],
        { limit: 100, next_cursor: null },
      );
    const payment: FinancialObject = {
      id: ids.payment,
      property_id: property,
      payer_customer_id: ids.customer,
      payment_number: "PAY-SYNTHETIC",
      payment_method_id: ids.method,
      payment_method_name_snapshot: "Synthetic Bank",
      received_currency: "USD",
      received_amount_minor: 200,
      usd_accounting_value_cents: 200,
      payment_date: "2026-09-01",
      status: "RECEIVED",
      confirmed_at: "2026-09-01T12:00:00+07:00",
      confirmed_by: actor,
    };
    if (phase === "source" && sourceUnavailable)
      throw new Error("Synthetic related read unavailable");
    if (phase === "source")
      return reply({
        property_id: property,
        source_type: "PAYMENT",
        source_id: ids.payment,
        recipient_customer_id: ids.customer,
        refund_currency: "USD",
        available_usd_cents: sourceAvailable,
        eligible: true,
        source_payment: payment,
        source_exchange_rate: null,
        receipt_evidence: {
          received_at: "2026-09-01T11:59:00+07:00",
          evidence_reference: "Synthetic original receipt",
        },
      });
    if (outcome === "unknown") throw new Error("Synthetic lost reply");
    if (typeof outcome === "number")
      return new Response(
        stringifyFinancialJson({
          error: {
            code: (
              {
                400: "BAD_REQUEST",
                409: "CONFLICT",
                412: "PRECONDITION_FAILED",
                422: "VALIDATION_ERROR",
              } as const
            )[outcome],
          },
          meta: { request_id: requestId },
        }),
        {
          status: outcome,
          headers: {
            "Content-Type": "application/json",
            "X-Request-ID": requestId ?? "",
          },
        },
      );
    const body = financialObject(parseFinancialJson(call.body ?? ""));
    expect(headers.get("X-CSRF-Token")).toBe("synthetic-csrf");
    const saved = records.get(actor ?? "");
    expect(saved?.requestKey).toBe(call.key);
    expect(saved?.plaintext).not.toContain("synthetic-csrf");
    return reply(
      {
        refund: {
          id: ids.refund,
          refund_number: "REF-SYNTHETIC",
          recipient_customer_id: ids.customer,
          refund_currency: "USD",
          refund_amount_minor: body.amount_usd_cents ?? null,
          usd_accounting_value_cents: body.amount_usd_cents ?? null,
          source_payment_id: ids.payment,
          source_customer_credit_id: null,
          source_deposit_id: null,
          source_lifecycle_event_id: null,
          pet_refund_review_id: null,
          reason: body.reason ?? null,
          processed_at: "2026-09-08T11:00:00+07:00",
          processed_by: actor,
          authorization_reference: "refunds.create",
        },
        source: { type: "PAYMENT", id: ids.payment, property_id: property },
        net_refund_usd_cents: body.amount_usd_cents ?? null,
        source_payment: payment,
        source_exchange_rate: null,
        pet_refund_review: null,
        pet_departure: null,
        corrections: { items: [], page: { limit: 50, next_cursor: null } },
      },
      undefined,
      201,
    );
  };
  const transport = createFinancialTransport(fetcher, () => "synthetic-csrf");
  const services: FinancialUiServices = {
    references: createFinancialReferenceClient(fetcher),
    transport,
    recovery: createFinancialRecovery(
      store,
      transport,
      () => "synthetic-csrf",
      attempts,
    ),
  };
  return {
    services,
    records,
    store,
    calls,
    setSource: (available: number, unavailable = false) => {
      sourceAvailable = available;
      sourceUnavailable = unavailable;
    },
    setOutcome: (value: typeof outcome) => {
      outcome = value;
    },
    setStorage: (value: typeof failStorage) => {
      failStorage = value;
    },
    setAttemptDenied: (value: boolean) => {
      denyAttempt = value;
    },
    setGrant: (value: boolean) => {
      grant = value;
    },
    pause: (
      phase: NonNullable<typeof barrier>["phase"],
      promise: Promise<void>,
    ) => {
      barrier = { phase, promise };
    },
  };
}
async function openProperty() {
  await screen.findByRole("option", { name: "Synthetic River Property" });
  fireEvent.change(screen.getByLabelText("Financial Property"), {
    target: { value: ids.property },
  });
  await screen.findByLabelText("Source reference");
  await waitFor(() => {
    expect(
      screen.getByRole("button", { name: "Review Refund action" }),
    ).toBeEnabled();
  });
}
function fillRefund() {
  fireEvent.change(screen.getByLabelText("Source reference"), {
    target: { value: ids.payment },
  });
  fireEvent.change(screen.getByLabelText("Refund amount (USD)"), {
    target: { value: "1.01" },
  });
  fireEvent.change(screen.getByLabelText("Reason"), {
    target: { value: "Synthetic completed payout" },
  });
}
async function prepareRefund() {
  fillRefund();
  fireEvent.click(screen.getByRole("button", { name: "Review Refund action" }));
  return await screen.findByRole("dialog", {
    name: "Confirm: Record USD refund",
  });
}
function posts(h: ReturnType<typeof harness>) {
  return h.calls.filter((c) => c.method === "POST");
}
async function recorded() {
  return await screen.findByRole("region", {
    name: "Confirmed financial result",
  });
}

describe("exact finite confirmation summaries", () => {
  it.each(commandFixtures.map((input, index) => ({ input, index })))(
    "TEST-FE-449 renders the captured command $index without altering any original wire bytes",
    ({ input }) => {
      const captured = captureFinancialRequest(input);
      if (!isFinancialCommand(captured.operation) || captured.wireBody === null)
        throw new Error("Expected command fixture");
      const body = commandBody(captured.operation, captured.wireBody),
        request = {
          operation: captured.operation,
          target: captured.target,
          body,
        };
      render(<FinancialCommandEvidence request={request} />);
      const region = screen.getByRole("region", {
        name: "Exact action to confirm",
      });
      expect(region).not.toHaveTextContent("[object Object]");
      if (captured.target.id)
        expect(region).toHaveTextContent(captured.target.id);
      if (typeof body.reason === "string")
        expect(region).toHaveTextContent(body.reason);
      if (captured.operation === "refundReturn")
        expect(region).toHaveTextContent("Demonstrated returned USD");
      if (captured.operation === "refundReturnReverse")
        expect(region).toHaveTextContent(captured.target.correctionId ?? "");
      if (captured.operation === "paymentRecord")
        expect(region).toHaveTextContent("USD 1.00");
      expect(stringifyFinancialJson(body)).toBe(captured.wireBody);
      expect(screen.queryByRole("textbox")).toBeNull();
    },
  );
});

describe("shared financial confirmation and recovery", () => {
  it("TEST-FE-450 discovers only financial Properties and fresh capabilities without automatic commands", async () => {
    const h = harness();
    render(<FinancialManagement actorId={ids.actor} services={h.services} />);
    await openProperty();
    expect(
      screen.getByRole("combobox", { name: "Financial Property" }),
    ).toHaveAccessibleName("Financial Property");
    expect(h.calls.map((c) => c.url)).toEqual([
      "/api/v1/financial-workspaces?limit=100",
      `/api/v1/properties/${ids.property}/financial-capabilities`,
    ]);
    expect(
      h.calls.every(
        (c) => c.method === "GET" && c.key === null && c.actor === ids.actor,
      ),
    ).toBe(true);
    expect(h.store.begin).not.toHaveBeenCalled();
    expect(posts(h)).toHaveLength(0);
  });
  it("TEST-FE-451 sends only after explicit confirmation, preserves exact USD and prevents duplicate clicks", async () => {
    const h = harness();
    render(<FinancialManagement actorId={ids.actor} services={h.services} />);
    await openProperty();
    let dialog = await prepareRefund();
    expect(
      within(dialog).getByRole("region", { name: "Exact action to confirm" }),
    ).toHaveTextContent("USD 1.01");
    expect(posts(h)).toHaveLength(0);
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(h.store.begin).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "Review Refund action" }),
    );
    dialog = await screen.findByRole("dialog");
    const button = within(dialog).getByRole("button", {
      name: "Record USD refund",
    });
    fireEvent.click(button);
    fireEvent.click(button);
    const result = await recorded();
    expect(result).toHaveTextContent("REF-SYNTHETIC");
    expect(result).toHaveTextContent("USD 1.01");
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    expect(posts(h)).toHaveLength(1);
    expect(h.records.size).toBe(0);
    expect(h.store.clear).toHaveBeenCalledTimes(1);
    expect(posts(h)[0]?.body).toContain('"amount_usd_cents":101');
  });
  it("TEST-FE-452 keeps an unknown outcome through reload and replays original bytes and key only after explicit review", async () => {
    const h = harness();
    h.setOutcome("unknown");
    const view = render(
      <FinancialManagement actorId={ids.actor} services={h.services} />,
    );
    await openProperty();
    let dialog = await prepareRefund();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Record USD refund" }),
    );
    await screen.findByRole("button", { name: "Review original action" });
    expect(posts(h)).toHaveLength(1);
    expect(h.records.size).toBe(1);
    const first = posts(h)[0];
    view.unmount();
    h.setOutcome("success");
    render(<FinancialManagement actorId={ids.actor} services={h.services} />);
    await screen.findByRole("option", { name: "Synthetic River Property" });
    fireEvent.change(screen.getByLabelText("Financial Property"), {
      target: { value: ids.property },
    });
    fireEvent.click(
      await screen.findByRole("button", { name: "Review original action" }),
    );
    dialog = await screen.findByRole("dialog", {
      name: "Review original unresolved action",
    });
    expect(
      within(dialog).getByText("Record USD refund", { exact: true }),
    ).toBeInTheDocument();
    expect(dialog).toHaveTextContent("USD 1.01");
    expect(posts(h)).toHaveLength(1);
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "Send original action again",
      }),
    );
    await recorded();
    await waitFor(() => {
      expect(h.records.size).toBe(0);
    });
    expect(posts(h)).toHaveLength(2);
    expect(posts(h)[1]?.body).toBe(first?.body);
    expect(posts(h)[1]?.key).toBe(first?.key);
    expect(h.store.begin).toHaveBeenCalledTimes(1);
  });
  it.each([400, 409, 412, 422] as const)(
    "TEST-FE-453 treats canonical HTTP%s according to original uncertainty",
    async (status) => {
      const h = harness();
      h.setOutcome(status);
      render(<FinancialManagement actorId={ids.actor} services={h.services} />);
      await openProperty();
      const dialog = await prepareRefund();
      fireEvent.click(
        within(dialog).getByRole("button", { name: "Record USD refund" }),
      );
      await waitFor(() => {
        expect(screen.queryByRole("dialog")).toBeNull();
      });
      expect(posts(h)).toHaveLength(1);
      expect(h.records.size).toBe(status === 409 ? 1 : 0);
      if (status === 409)
        expect(
          await screen.findByRole("button", { name: "Review original action" }),
        ).toBeEnabled();
      else {
        expect(
          screen.getByRole("button", { name: "Review Refund action" }),
        ).toBeEnabled();
        expect(
          screen.getByText(/new action was rejected before recording/),
        ).toBeVisible();
      }
      expect(
        screen.queryByRole("region", { name: "Confirmed financial result" }),
      ).toBeNull();
    },
  );
  it.each(["read", "begin", "attempt"] as const)(
    "TEST-FE-454 prevents financial sends when recovery %s is unavailable",
    async (phase) => {
      const h = harness();
      if (phase === "read") h.setStorage("read");
      render(<FinancialManagement actorId={ids.actor} services={h.services} />);
      await screen.findByRole("option", { name: "Synthetic River Property" });
      fireEvent.change(screen.getByLabelText("Financial Property"), {
        target: { value: ids.property },
      });
      await screen.findByLabelText("Source reference");
      if (phase === "read")
        expect(
          screen.getByRole("button", { name: "Review Refund action" }),
        ).toBeDisabled();
      else {
        await waitFor(() => {
          expect(
            screen.getByRole("button", { name: "Review Refund action" }),
          ).toBeEnabled();
        });
        if (phase === "begin") h.setStorage("begin");
        else h.setAttemptDenied(true);
        const dialog = await prepareRefund();
        fireEvent.click(
          within(dialog).getByRole("button", { name: "Record USD refund" }),
        );
        await waitFor(() => {
          expect(screen.queryByRole("dialog")).toBeNull();
        });
      }
      expect(posts(h)).toHaveLength(0);
      expect(h.records.size).toBe(0);
    },
  );
  it.each(["source", "post", "begin"] as const)(
    "TEST-FE-455 discards old Property %s completion and preserves unresolved evidence",
    async (phase) => {
      const h = harness(),
        gate = deferred();
      render(<FinancialManagement actorId={ids.actor} services={h.services} />);
      await openProperty();
      if (phase === "source") {
        h.pause(phase, gate.promise);
        fillRefund();
        fireEvent.click(
          screen.getByRole("button", { name: "Review Refund action" }),
        );
        await waitFor(() => {
          expect(h.calls.some((c) => c.url.includes("refund-sources"))).toBe(
            true,
          );
        });
      } else {
        const dialog = await prepareRefund();
        h.pause(phase, gate.promise);
        fireEvent.click(
          within(dialog).getByRole("button", { name: "Record USD refund" }),
        );
        await waitFor(() => {
          if (phase === "post") expect(posts(h)).toHaveLength(1);
          else expect(h.store.begin).toHaveBeenCalledTimes(1);
        });
      }
      const discard = vi.spyOn(window, "confirm").mockReturnValue(true);
      try {
        fireEvent.change(screen.getByLabelText("Financial Property"), {
          target: { value: ids.other },
        });
        expect(discard).toHaveBeenCalledOnce();
      } finally {
        discard.mockRestore();
      }
      await screen.findByRole("region", {
        name: "Financial Property Synthetic Garden Property",
      });
      await act(async () => {
        gate.release();
        await Promise.resolve();
      });
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(
        screen.queryByRole("region", { name: "Confirmed financial result" }),
      ).toBeNull();
      expect(posts(h).every((c) => c.property === ids.property)).toBe(true);
      if (phase === "source") expect(posts(h)).toHaveLength(0);
      else
        await waitFor(() => {
          expect(h.records.size).toBe(1);
        });
    },
  );
  it.each(["actor", "unmount"] as const)(
    "TEST-FE-456 rejects late discovery after %s changes",
    async (change) => {
      const h = harness(),
        gate = deferred();
      h.pause("discovery", gate.promise);
      const view = render(
        <FinancialManagement actorId={ids.actor} services={h.services} />,
      );
      await waitFor(() => {
        expect(h.calls).toHaveLength(1);
      });
      if (change === "actor")
        view.rerender(
          <FinancialManagement actorId={ids.customer} services={h.services} />,
        );
      else view.unmount();
      expect(h.calls[0]?.signal?.aborted).toBe(true);
      await act(async () => {
        gate.release();
        await Promise.resolve();
      });
      if (change === "actor") {
        await screen.findByRole("option", { name: "Synthetic River Property" });
        expect(h.calls.at(-1)?.actor).toBe(ids.customer);
      } else
        expect(
          screen.queryByRole("heading", { name: "Financial records" }),
        ).toBeNull();
      expect(posts(h)).toHaveLength(0);
    },
  );
  it("TEST-FE-457 opens a live scope after StrictMode cleanup without duplicate financial sends", async () => {
    const h = harness();
    render(
      <StrictMode>
        <FinancialManagement actorId={ids.actor} services={h.services} />
      </StrictMode>,
    );
    await openProperty();
    const dialog = await prepareRefund();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Record USD refund" }),
    );
    await recorded();
    expect(posts(h)).toHaveLength(1);
    expect(posts(h)[0]?.signal?.aborted).toBe(true);
  });
  it("TEST-FE-458 allows closing an original unresolved review after its command grant is removed", async () => {
    const h = harness();
    h.setOutcome("unknown");
    render(<FinancialManagement actorId={ids.actor} services={h.services} />);
    await openProperty();
    const dialog = await prepareRefund();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Record USD refund" }),
    );
    await screen.findByRole("button", { name: "Review original action" });
    h.setGrant(false);
    const discard = vi.spyOn(window, "confirm").mockReturnValue(true);
    try {
      fireEvent.click(
        screen.getByRole("button", {
          name: "Refresh financial access and recovery",
        }),
      );
      expect(discard).toHaveBeenCalledOnce();
    } finally {
      discard.mockRestore();
    }
    await waitFor(() => {
      expect(screen.queryByLabelText("Source reference")).toBeNull();
    });
    fireEvent.click(
      await screen.findByRole("button", { name: "Review original action" }),
    );
    const pending = await screen.findByRole("dialog");
    expect(
      within(pending).getByRole("button", {
        name: "Send original action again",
      }),
    ).toBeDisabled();
    expect(
      within(pending).getByRole("button", { name: "Cancel" }),
    ).toBeEnabled();
    fireEvent.keyDown(pending, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(posts(h)).toHaveLength(1);
    const original = h.records.get(ids.actor);
    expect(
      original && decodeFinancialIntent(original, ids.actor)?.operation,
    ).toBe("refundCreate");
  });
});

describe("confirmed results and independent current-fact refresh", () => {
  it.each([false, true])(
    "TEST-FE-490 refreshes current source facts after validated success, original-key replay %s",
    async (replay) => {
      const h = harness();
      if (replay) h.setOutcome("unknown");
      render(<FinancialManagement actorId={ids.actor} services={h.services} />);
      await openProperty();
      let dialog = await prepareRefund();
      fireEvent.click(
        within(dialog).getByRole("button", { name: "Record USD refund" }),
      );
      if (replay) {
        fireEvent.click(
          await screen.findByRole("button", { name: "Review original action" }),
        );
        dialog = await screen.findByRole("dialog", {
          name: "Review original unresolved action",
        });
        h.setOutcome("success");
        h.setSource(99);
        fireEvent.click(
          within(dialog).getByRole("button", {
            name: "Send original action again",
          }),
        );
      }
      const result = await recorded();
      const current = await screen.findByRole("region", {
        name: "Related facts refreshed after confirmation",
      });
      await waitFor(() => {
        expect(
          within(current).getByRole("region", {
            name: "Selected Refund source",
          }),
        ).toBeVisible();
      });
      expect(result).toHaveTextContent("USD 1.01");
      expect(
        screen.getAllByRole("region", { name: "Original completed Refund" }),
      ).toHaveLength(1);
      if (replay) expect(current).toHaveTextContent("USD 0.99");
      expect(
        h.calls.filter((c) => c.url.includes("refund-sources")).length,
      ).toBe(2);
      expect(posts(h)).toHaveLength(replay ? 2 : 1);
      expect(h.records.size).toBe(0);
      if (replay) {
        expect(posts(h)[0]?.body).toBe(posts(h)[1]?.body);
        expect(posts(h)[0]?.key).toBe(posts(h)[1]?.key);
      }
    },
  );
  it("TEST-FE-491 keeps the recorded result and cleared journal when a later current-source read fails", async () => {
    const h = harness();
    render(<FinancialManagement actorId={ids.actor} services={h.services} />);
    await openProperty();
    const dialog = await prepareRefund();
    h.setSource(99, true);
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Record USD refund" }),
    );
    const result = await recorded();
    const current = await screen.findByRole("region", {
      name: "Related facts refreshed after confirmation",
    });
    await waitFor(() => {
      expect(within(current).getByRole("alert")).toHaveTextContent(
        "The action is recorded. Current related facts could not be loaded.",
      );
    });
    expect(result).toHaveTextContent("REF-SYNTHETIC");
    expect(h.records.size).toBe(0);
    expect(h.store.clear).toHaveBeenCalledOnce();
    expect(posts(h)).toHaveLength(1);
    expect(
      screen.queryByRole("button", { name: "Review original action" }),
    ).toBeNull();
  });
});

describe("shared preparation ownership across financial forms", () => {
  it.each([false, true])(
    "TEST-FE-505 ignores a delayed Payment preparation after a newer Refund review, including cancellation %s",
    async (cancel) => {
      const h = harness(true);
      render(<FinancialManagement actorId={ids.actor} services={h.services} />);
      await openProperty();
      fireEvent.click(
        screen.getByRole("button", { name: "Load accepted Payment methods" }),
      );
      await screen.findByRole("option", {
        name: "Synthetic accepted cash · CASH",
      });
      for (const [label, value] of [
        ["Payer Customer reference", ids.customer],
        ["Accepted Payment method", ids.method],
        [
          "Payment received at (Asia/Phnom_Penh, +07:00)",
          "2026-09-08T11:00:00.123",
        ],
        ["Payment evidence reference", "Synthetic original incoming evidence"],
        ["Original received amount (USD)", "1.01"],
      ] as const)
        fireEvent.change(screen.getByLabelText(label), { target: { value } });
      const waiting = deferred();
      h.pause("methods", waiting.promise);
      fireEvent.click(
        screen.getByRole("button", { name: "Review incoming Payment" }),
      );
      await waitFor(() => {
        expect(
          h.calls.filter((c) => c.url.includes("/payment-methods")),
        ).toHaveLength(2);
      });
      const dialog = await prepareRefund();
      expect(dialog).toHaveTextContent("USD 1.01");
      if (cancel)
        fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
      act(() => {
        waiting.release();
      });
      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: "Review incoming Payment" }),
        ).toBeEnabled();
      });
      expect(
        screen.queryByRole("dialog", { name: "Confirm: Record payment" }),
      ).toBeNull();
      if (cancel) expect(screen.queryByRole("dialog")).toBeNull();
      else
        expect(
          screen.getByRole("dialog", { name: "Confirm: Record USD refund" }),
        ).toBeVisible();
      expect(posts(h)).toHaveLength(0);
      expect(h.records.size).toBe(0);
    },
  );
});

describe("unsent financial drafts survive cancelled navigation", () => {
  it("TEST-FE-519 warns before a Property switch and preserves draft and scope when cancelled", async () => {
    const h = harness(),
      discard = vi.spyOn(window, "confirm").mockReturnValue(false);
    try {
      render(<FinancialManagement actorId={ids.actor} services={h.services} />);
      await openProperty();
      fillRefund();
      const before = h.calls.length;
      const signalsBefore = h.calls.map((c) => c.signal?.aborted);
      fireEvent.change(screen.getByLabelText("Financial Property"), {
        target: { value: ids.other },
      });
      expect(discard).toHaveBeenCalledOnce();
      expect(screen.getByLabelText("Financial Property")).toHaveValue(
        ids.property,
      );
      expect(screen.getByLabelText("Refund amount (USD)")).toHaveValue("1.01");
      expect(screen.getByLabelText("Reason")).toHaveValue(
        "Synthetic completed payout",
      );
      expect(h.calls).toHaveLength(before);
      expect(h.calls.map((c) => c.signal?.aborted)).toEqual(signalsBefore);
      discard.mockReturnValue(true);
      fireEvent.change(screen.getByLabelText("Financial Property"), {
        target: { value: ids.other },
      });
      await screen.findByRole("region", {
        name: "Financial Property Synthetic Garden Property",
      });
      expect(screen.getByLabelText("Refund amount (USD)")).toHaveValue("");
      expect(
        h.calls
          .slice(before)
          .filter((c) => c.property !== null)
          .every((c) => c.property === ids.other),
      ).toBe(true);
      expect(posts(h)).toHaveLength(0);
      expect(h.records.size).toBe(0);
    } finally {
      discard.mockRestore();
    }
  });
  it.each([
    "Refresh financial Properties",
    "Refresh financial access and recovery",
  ])(
    "TEST-FE-520 preserves unsent values when %s discard is cancelled",
    async (label) => {
      const h = harness(),
        discard = vi.spyOn(window, "confirm").mockReturnValue(false);
      try {
        render(
          <FinancialManagement actorId={ids.actor} services={h.services} />,
        );
        await openProperty();
        fillRefund();
        const before = h.calls.length;
        fireEvent.click(screen.getByRole("button", { name: label }));
        expect(discard).toHaveBeenCalledOnce();
        expect(screen.getByLabelText("Financial Property")).toHaveValue(
          ids.property,
        );
        expect(screen.getByLabelText("Refund amount (USD)")).toHaveValue(
          "1.01",
        );
        expect(screen.getByLabelText("Reason")).toHaveValue(
          "Synthetic completed payout",
        );
        expect(h.calls).toHaveLength(before);
        expect(posts(h)).toHaveLength(0);
      } finally {
        discard.mockRestore();
      }
    },
  );
  it("TEST-FE-521 warns on unload only while unsent financial values exist", async () => {
    const h = harness();
    const view = render(
      <FinancialManagement actorId={ids.actor} services={h.services} />,
    );
    await openProperty();
    const pristine = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(pristine);
    expect(pristine.defaultPrevented).toBe(false);
    fillRefund();
    const dirty = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(dirty);
    expect(dirty.defaultPrevented).toBe(true);
    view.unmount();
    const gone = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(gone);
    expect(gone.defaultPrevented).toBe(false);
    expect(posts(h)).toHaveLength(0);
    expect(h.records.size).toBe(0);
  });
});

describe("financial draft boundaries around explicit confirmation", () => {
  it.each([false, true])(
    "TEST-FE-523 acknowledges a confirmed draft without another discard warning, original-key replay %s",
    async (replay) => {
      const h = harness(),
        discard = vi.spyOn(window, "confirm").mockReturnValue(false);
      try {
        if (replay) h.setOutcome("unknown");
        render(
          <FinancialManagement actorId={ids.actor} services={h.services} />,
        );
        await openProperty();
        const dialog = await prepareRefund();
        fireEvent.click(
          within(dialog).getByRole("button", { name: "Record USD refund" }),
        );
        if (replay) {
          const review = await screen.findByRole("button", {
            name: "Review original action",
          });
          const dirty = new Event("beforeunload", { cancelable: true });
          window.dispatchEvent(dirty);
          expect(dirty.defaultPrevented).toBe(true);
          h.setOutcome("success");
          fireEvent.click(review);
          const pending = await screen.findByRole("dialog", {
            name: "Review original unresolved action",
          });
          fireEvent.click(
            within(pending).getByRole("button", {
              name: "Send original action again",
            }),
          );
        }
        await recorded();
        const clean = new Event("beforeunload", { cancelable: true });
        window.dispatchEvent(clean);
        expect(clean.defaultPrevented).toBe(false);
        fireEvent.change(screen.getByLabelText("Financial Property"), {
          target: { value: ids.other },
        });
        await screen.findByRole("region", {
          name: "Financial Property Synthetic Garden Property",
        });
        expect(discard).not.toHaveBeenCalled();
        expect(posts(h)).toHaveLength(replay ? 2 : 1);
        expect(h.records.size).toBe(0);
        if (replay) {
          expect(posts(h)[1]?.key).toBe(posts(h)[0]?.key);
          expect(posts(h)[1]?.body).toBe(posts(h)[0]?.body);
        }
      } finally {
        discard.mockRestore();
      }
    },
  );
  it("TEST-FE-524 preserves a competing Payment draft after a Refund is confirmed", async () => {
    const h = harness(true),
      discard = vi.spyOn(window, "confirm").mockReturnValue(false);
    try {
      render(<FinancialManagement actorId={ids.actor} services={h.services} />);
      await openProperty();
      fireEvent.change(
        screen.getByLabelText("Original received amount (USD)"),
        { target: { value: "234.56" } },
      );
      const dialog = await prepareRefund();
      fireEvent.click(
        within(dialog).getByRole("button", { name: "Record USD refund" }),
      );
      await recorded();
      fireEvent.change(screen.getByLabelText("Financial Property"), {
        target: { value: ids.other },
      });
      expect(discard).toHaveBeenCalledOnce();
      expect(screen.getByLabelText("Financial Property")).toHaveValue(
        ids.property,
      );
      expect(
        screen.getByLabelText("Original received amount (USD)"),
      ).toHaveValue("234.56");
      expect(posts(h)).toHaveLength(1);
      expect(posts(h)[0]?.url).toContain("/refunds");
      expect(h.records.size).toBe(0);
    } finally {
      discard.mockRestore();
    }
  });
});
