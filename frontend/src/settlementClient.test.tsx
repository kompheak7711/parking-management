import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  SettlementRequestError,
  SettlementUnavailableError,
  settlementApi,
} from "./settlementClient";

const PROPERTY = "11111111-1111-4111-8111-111111111111";
const SETTLEMENT = "22222222-2222-4222-8222-222222222222";
const KEY = "33333333-3333-4333-8333-333333333333";
const draft = {
  draft_id: "44444444-4444-4444-8444-444444444444",
  property_id: PROPERTY,
  kind: "SETTLEMENT_CORRECTION",
  prepare_capability: "final_settlements.prepare",
  payload: { variant: "REFUND" },
  reason: "The Rent was charged at the wrong amount",
  prepared_at: "2026-10-25T09:30:00+07:00",
  prepared_by: "55555555-5555-4555-8555-555555555555",
  state: "PENDING",
  decision: null,
};

function answer(body: unknown, status = 201): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function sent(mock: { mock: { calls: unknown[][] } }, call = 0) {
  const [path, init] = mock.mock.calls[call] as [string, RequestInit];
  return { path, init, headers: new Headers(init.headers) };
}

describe("settlementClient", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  beforeEach(() => {
    document.cookie = "__Host-prm_csrf=csrf-value; Secure; Path=/";
  });

  it("TEST-FE-S11-001 records a correction with its key, CSRF and Property", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(answer({ data: draft, meta: {} }));
    const form = {
      invoice_id: "66666666-6666-4666-8666-666666666666",
      invoice_line_id: "77777777-7777-4777-8777-777777777777",
      amount_usd_cents: 1000,
      refund_method_id: "88888888-8888-4888-8888-888888888888",
      reference_note: "Cash handed over at the front desk",
      reason: "The Rent was charged at the wrong amount",
    };
    const recorded = await settlementApi.refund(
      PROPERTY,
      SETTLEMENT,
      form,
      KEY,
    );
    expect(recorded.draft_id).toBe(draft.draft_id);
    const { path, init, headers } = sent(fetchMock);
    expect(path).toBe(
      `/api/v1/properties/${PROPERTY}/final-settlements/${SETTLEMENT}/corrections/refunds`,
    );
    expect(init).toMatchObject({ method: "POST", credentials: "include" });
    expect(JSON.parse(init.body as string)).toEqual(form);
    expect(headers.get("Idempotency-Key")).toBe(KEY);
    expect(headers.get("X-CSRF-Token")).toBe("csrf-value");
    expect(headers.get("X-Financial-Property-ID")).toBe(PROPERTY);
  });

  it("TEST-FE-S11-002 shows a named refusal's code, text, fields and rules", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      answer(
        {
          error: {
            code: "CORRECTION_REFUND_METHOD_OFF",
            message:
              "This Refund method is not an active method. Choose an active method.",
            rule_ids: ["BR-SETTLE-013", "BR-REFUND-014"],
            fields: ["refund_method_id"],
          },
        },
        422,
      ),
    );
    const refused = settlementApi
      .refund(
        PROPERTY,
        SETTLEMENT,
        {
          invoice_id: "a",
          invoice_line_id: "b",
          amount_usd_cents: 1,
          refund_method_id: "c",
          reference_note: "d",
          reason: "e",
        },
        KEY,
      )
      .catch((error: unknown) => error);
    const error = await refused;
    expect(error).toBeInstanceOf(SettlementRequestError);
    expect(error).toMatchObject({
      status: 422,
      code: "CORRECTION_REFUND_METHOD_OFF",
      message:
        "This Refund method is not an active method. Choose an active method.",
      fields: ["refund_method_id"],
      ruleIds: ["BR-SETTLE-013", "BR-REFUND-014"],
    });
  });

  it("TEST-FE-S11-003 tells an unavailable service from a refusal", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(answer({ error: {} }, 503))
      .mockRejectedValueOnce(new TypeError("offline"))
      .mockResolvedValueOnce(new Response("not json", { status: 404 }));
    await expect(
      settlementApi.settlementPreview(PROPERTY, SETTLEMENT),
    ).rejects.toBeInstanceOf(SettlementUnavailableError);
    await expect(
      settlementApi.settlementPreview(PROPERTY, SETTLEMENT),
    ).rejects.toBeInstanceOf(SettlementUnavailableError);
    await expect(
      settlementApi.settlementPreview(PROPERTY, SETTLEMENT),
    ).rejects.toMatchObject({ status: 404, code: null, fields: [] });
  });

  it("TEST-FE-S11-004 pages the shared drafts by state and keeps the cursor", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        answer(
          { data: [draft], meta: {}, page: { limit: 1, next_cursor: "older" } },
          200,
        ),
      );
    const page = await settlementApi.drafts(PROPERTY, {
      state: "PENDING",
      limit: 1,
      cursor: "newer",
    });
    expect(page).toEqual({ items: [draft], next_cursor: "older" });
    const { path, init } = sent(fetchMock);
    expect(path).toBe(
      `/api/v1/properties/${PROPERTY}/financial-drafts?state=PENDING&limit=1&cursor=newer`,
    );
    expect(init.method).toBe("GET");
  });

  it("TEST-FE-S11-005 confirms a draft with an empty body and its key", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        answer({ data: { draft: { ...draft, state: "CONFIRMED" } } }, 200),
      );
    const confirmed = await settlementApi.confirmDraft(
      PROPERTY,
      draft.draft_id,
      KEY,
    );
    expect(confirmed.draft).toMatchObject({ state: "CONFIRMED" });
    const { path, init, headers } = sent(fetchMock);
    expect(path).toBe(
      `/api/v1/properties/${PROPERTY}/financial-drafts/${draft.draft_id}/confirm`,
    );
    expect(init.body).toBe("{}");
    expect(headers.get("Idempotency-Key")).toBe(KEY);
  });

  it("TEST-FE-S11-006 sends each correction to its own route", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(() => Promise.resolve(answer({ data: draft })));
    const routes = {
      settlementDraft: "drafts",
      extraCharge: "corrections/extra-charges",
      chargeReduction: "corrections/charge-reductions",
      lateChargeReduction: "corrections/late-charge-reductions",
      returnedPayment: "corrections/returned-payments",
      paymentMove: "corrections/payment-moves",
      adjustmentReversal: "corrections/adjustment-reversals",
      refund: "corrections/refunds",
      lateChargeRefund: "corrections/late-charge-refunds",
      petClassification: "corrections/pet-classifications",
      refundReturn: "corrections/refund-returns",
      heldValueRefund: "corrections/held-value-refunds",
      forfeitureReversal: "corrections/forfeiture-reversals",
      depositReceiptCorrection: "corrections/deposit-receipt-corrections",
      returnReversal: "corrections/return-reversals",
    } as const;
    for (const name of Object.keys(routes) as (keyof typeof routes)[]) {
      const record = settlementApi[name] as (
        propertyId: string,
        settlementId: string,
        form: object,
        key: string,
      ) => Promise<unknown>;
      await record(PROPERTY, SETTLEMENT, {}, KEY);
    }
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual(
      Object.values(routes).map(
        (route) =>
          `/api/v1/properties/${PROPERTY}/final-settlements/${SETTLEMENT}/${route}`,
      ),
    );
  });

  it("TEST-FE-S11-007 records drafts on their own record and move-out charges", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(() => Promise.resolve(answer({ data: draft })));
    const record = "99999999-9999-4999-8999-999999999999";
    await settlementApi.forfeitureDraft(PROPERTY, record, {} as never, KEY);
    await settlementApi.forfeitureReversalDraft(
      PROPERTY,
      record,
      {} as never,
      KEY,
    );
    await settlementApi.receiptReversalDraft(
      PROPERTY,
      record,
      {} as never,
      KEY,
    );
    await settlementApi.paymentReturnDraft(PROPERTY, record, {} as never, KEY);
    await settlementApi.paymentMoveDraft(PROPERTY, record, {} as never, KEY);
    await settlementApi.adjustmentReversalDraft(
      PROPERTY,
      record,
      { reason: "r" },
      KEY,
    );
    await settlementApi.resolveHandBack(record, 3, {} as never, KEY);
    const base = `/api/v1/properties/${PROPERTY}`;
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      `${base}/deposits/${record}/forfeiture-drafts`,
      `${base}/deposit-dispositions/${record}/reversal-drafts`,
      `${base}/deposit-receipts/${record}/reversal-drafts`,
      `${base}/payments/${record}/return-drafts`,
      `${base}/payment-allocations/${record}/move-drafts`,
      `${base}/invoice-adjustments/${record}/reversal-drafts`,
      `/api/v1/invoices/${record}/hand-back-resolution`,
    ]);
    // A route with no Property in its path names none; the hand-back names its Invoice version.
    const handBack = sent(fetchMock, 6).headers;
    expect(handBack.has("X-Financial-Property-ID")).toBe(false);
    expect(handBack.get("If-Match")).toBe('"3"');
    expect(handBack.get("Idempotency-Key")).toBe(KEY);
  });

  it("TEST-FE-S11-008 sends no command without exactly one CSRF cookie", async () => {
    document.cookie = "__Host-prm_csrf=; Max-Age=0; Secure; Path=/";
    const fetchMock = vi.spyOn(globalThis, "fetch");
    await expect(
      settlementApi.startSettlement(PROPERTY, SETTLEMENT, KEY),
    ).rejects.toBeInstanceOf(SettlementRequestError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("TEST-FE-S11-009 names form fields without the body prefix and keeps the version", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        answer(
          {
            error: {
              code: "VALIDATION_FAILED",
              message: "Check the form.",
              rule_ids: [],
              fields: ["body.reason", "body.steps.amount_usd_cents", "reason"],
            },
          },
          422,
        ),
      )
      .mockResolvedValueOnce(
        answer(
          {
            error: {
              code: "PRECONDITION_FAILED",
              message: "The Invoice changed.",
              rule_ids: [],
              fields: [],
              current_version: 4,
            },
          },
          412,
        ),
      );
    await expect(
      settlementApi.rejectDraft(PROPERTY, SETTLEMENT, { reason: "" }, KEY),
    ).rejects.toMatchObject({
      fields: ["reason", "steps.amount_usd_cents"],
      currentVersion: null,
    });
    await expect(
      settlementApi.resolveHandBack(SETTLEMENT, 3, {} as never, KEY),
    ).rejects.toMatchObject({ status: 412, currentVersion: 4 });
    // A version that is not a whole number of 1 or more is never sent.
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockClear();
    for (const version of [0, Number.NaN, 1.5]) {
      await expect(
        settlementApi.resolveHandBack(SETTLEMENT, version, {} as never, KEY),
      ).rejects.toMatchObject({ status: 412 });
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("TEST-FE-S11-010 sends the cleaning rate and charge with their own ids and no key", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(() => Promise.resolve(answer({ data: {} })));
    await settlementApi.setCleaningRate(PROPERTY, SETTLEMENT, {
      rate_id: KEY,
      expected_current_rate_id: null,
      rate_usd_cents: 2500,
      reason: "Move-out cleaning rate for this Parking",
    });
    await settlementApi.chargeCleaning(PROPERTY, SETTLEMENT, {
      charge_id: KEY,
      expected_rate_id: KEY,
    });
    for (const call of [0, 1]) {
      const { headers } = sent(fetchMock, call);
      expect(headers.has("Idempotency-Key")).toBe(false);
      expect(headers.get("X-CSRF-Token")).toBe("csrf-value");
    }
  });

  it("TEST-FE-S11H-001 adds a Refund method and turns one off with no key", async () => {
    const method = {
      id: KEY,
      code: "WING",
      display_name: "Wing money transfer",
      active: true,
      seeded: false,
      updated_at: "2026-10-25T10:00:00+07:00",
    };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(answer({ data: method, meta: {} }))
      .mockResolvedValueOnce(
        answer({ data: { ...method, active: false }, meta: {} }, 200),
      );
    const added = await settlementApi.addRefundMethod(PROPERTY, {
      refund_method_id: KEY,
      code: "WING",
      display_name: "Wing money transfer",
    });
    expect(added).toEqual(method);
    const turned = await settlementApi.setRefundMethodState(PROPERTY, KEY, {
      active: false,
    });
    expect(turned.active).toBe(false);
    const first = sent(fetchMock, 0);
    expect(first.path).toBe(`/api/v1/properties/${PROPERTY}/refund-methods`);
    expect(JSON.parse(first.init.body as string)).toEqual({
      refund_method_id: KEY,
      code: "WING",
      display_name: "Wing money transfer",
    });
    const second = sent(fetchMock, 1);
    expect(second.path).toBe(
      `/api/v1/properties/${PROPERTY}/refund-methods/${KEY}/state`,
    );
    expect(JSON.parse(second.init.body as string)).toEqual({ active: false });
    for (const call of [0, 1]) {
      const { headers, init } = sent(fetchMock, call);
      expect(init.method).toBe("POST");
      expect(headers.has("Idempotency-Key")).toBe(false);
      expect(headers.get("X-CSRF-Token")).toBe("csrf-value");
      expect(headers.get("X-Financial-Property-ID")).toBe(PROPERTY);
    }
  });

  it("TEST-FE-984 reads one Lease's Final Settlements without starting one", async () => {
    const item = { id: SETTLEMENT, property_id: PROPERTY, pending_draft: true };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(answer({ data: [item], meta: {} }, 200))
      .mockResolvedValueOnce(answer({ data: [], meta: {} }, 200))
      .mockResolvedValueOnce(answer({ data: {}, meta: {} }, 200));
    expect(await settlementApi.settlements(PROPERTY, KEY)).toEqual([item]);
    expect(await settlementApi.settlements(PROPERTY)).toEqual([]);
    await expect(settlementApi.settlements(PROPERTY)).rejects.toBeInstanceOf(
      SettlementRequestError,
    );
    const first = sent(fetchMock, 0);
    expect(first.path).toBe(
      `/api/v1/properties/${PROPERTY}/final-settlements?lease_id=${KEY}`,
    );
    expect(first.init.method).toBe("GET");
    expect(first.headers.get("X-Financial-Property-ID")).toBe(PROPERTY);
    expect(sent(fetchMock, 1).path).toBe(
      `/api/v1/properties/${PROPERTY}/final-settlements`,
    );
  });
});
