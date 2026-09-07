import { describe, expect, it, vi } from "vitest";
import {
  ExactJsonNumber,
  parseFinancialJson,
  stringifyFinancialJson,
} from "./financialJson";
import {
  captureFinancialRequest,
  captureWireRequest,
  financialPath,
  financialInteger,
  type FinancialRequest,
} from "./financialContracts";
import { commands, reads, ids, paymentBody } from "./test/financialFixtures";

describe("financial operation contracts", () => {
  it("TEST-FE-289 maps the complete 14 read and 12 command inventory to canonical paths", () => {
    const expected = [
      ["paymentList", "GET", `/properties/${ids.property}/payments`],
      ["paymentGet", "GET", `/payments/${ids.payment}`],
      [
        "allocationProposal",
        "GET",
        `/payments/${ids.payment}/allocation-proposal`,
      ],
      ["allocationList", "GET", `/payments/${ids.payment}/allocations`],
      ["paymentReceipt", "GET", `/payments/${ids.payment}/receipt`],
      ["receiptGet", "GET", `/receipts/${ids.receipt}`],
      ["creditList", "GET", `/customers/${ids.customer}/credits`],
      ["creditGet", "GET", `/customer-credits/${ids.credit}`],
      ["creditLedger", "GET", `/customer-credits/${ids.credit}/ledger`],
      [
        "creditProposal",
        "GET",
        `/customer-credits/${ids.credit}/application-proposal?invoice_id=${ids.invoice}&amount_usd_cents=100`,
      ],
      ["creditApplication", "GET", `/credit-applications/${ids.application}`],
      ["refundList", "GET", `/properties/${ids.property}/refunds`],
      ["refundGet", "GET", `/refunds/${ids.refund}`],
      ["refundSource", "GET", `/refund-sources/PAYMENT/${ids.payment}`],
      ["paymentRecord", "POST", `/properties/${ids.property}/payments`],
      ["allocationPost", "POST", `/payments/${ids.payment}/allocations`],
      [
        "allocationReverse",
        "POST",
        `/payment-allocations/${ids.allocation}/reverse`,
      ],
      ["paymentReverse", "POST", `/payments/${ids.payment}/reverse`],
      ["receiptReprint", "POST", `/receipts/${ids.receipt}/reprints`],
      [
        "creditRecognize",
        "POST",
        `/payments/${ids.payment}/credit-recognitions`,
      ],
      ["creditReverse", "POST", `/customer-credits/${ids.credit}/reverse`],
      ["creditApply", "POST", `/customer-credits/${ids.credit}/applications`],
      [
        "creditApplicationReverse",
        "POST",
        `/credit-applications/${ids.application}/reverse`,
      ],
      ["refundCreate", "POST", "/refunds"],
      ["refundReturn", "POST", `/refunds/${ids.refund}/verified-returns`],
      [
        "refundReturnReverse",
        "POST",
        `/refunds/${ids.refund}/verified-returns/${ids.event}/reverse`,
      ],
    ];
    expect(
      [...reads, ...commands].map((input) => {
        const request = captureFinancialRequest(input);
        return [
          request.operation,
          request.wireBody === null ? "GET" : "POST",
          financialPath(request, ids.property).slice(7),
        ];
      }),
    ).toEqual(expected);
    expect(new Set(expected.map((row) => row[0])).size).toBe(26);
  });
  it.each([
    "../payments",
    "",
    "00000000-0000-0000-0000-000000000000",
    ids.payment.replaceAll("-", ""),
    "https://example.com",
    false,
    null,
  ])(
    "TEST-FE-290 rejects unsafe or noncanonical target identifiers %s",
    (value) => {
      expect(() =>
        captureWireRequest({ operation: "paymentGet", target: { id: value } }),
      ).toThrow();
    },
  );
  it.each(commands)(
    "TEST-FE-291 rejects missing extra and unsupported body fields for $operation",
    (input) => {
      if (!("body" in input)) throw new Error();
      expect(() =>
        captureFinancialRequest({
          ...input,
          body: { ...input.body, status: "ACCEPTED" },
        } as FinancialRequest),
      ).toThrow();
      for (const key of Object.keys(input.body).filter(
        (key) => key !== "delivery_reference",
      )) {
        const body = Object.fromEntries(
          Object.entries(input.body).filter(([field]) => field !== key),
        );
        expect(() =>
          captureFinancialRequest({ ...input, body } as FinancialRequest),
        ).toThrow();
      }
    },
  );
  it("TEST-FE-292 aligns Unicode code points timestamps exact rates and normalized evidence", () => {
    const valid = {
      ...paymentBody,
      evidence_reference: "😀".repeat(500),
      received_at: "2024-02-29T23:59:59.123456-23:59",
    };
    expect(() =>
      captureFinancialRequest({
        operation: "paymentRecord",
        target: {},
        body: valid,
      }),
    ).not.toThrow();
    for (const received_at of [
      "2023-02-29T00:00:00Z",
      "2024-02-30T00:00:00Z",
      "0000-01-01T00:00:00Z",
      "2024-01-01T24:00:00Z",
      "2024-01-01T00:00:60Z",
      "2024-01-01T00:00:00",
      "2024-01-01T00:00:00.1234567Z",
    ])
      expect(() =>
        captureFinancialRequest({
          operation: "paymentRecord",
          target: {},
          body: { ...valid, received_at },
        }),
      ).toThrow();
    for (const evidence_reference of [
      "😀".repeat(501),
      "\u0085text",
      "text\u001c",
      "text\0",
      "\ud800",
    ])
      expect(() =>
        captureFinancialRequest({
          operation: "paymentRecord",
          target: {},
          body: { ...valid, evidence_reference },
        }),
      ).toThrow();
    expect(() =>
      captureFinancialRequest({
        operation: "paymentRecord",
        target: {},
        body: { ...valid, evidence_reference: "\ufefftext" },
      }),
    ).not.toThrow();
    const khr = {
      ...paymentBody,
      amount: { currency: "KHR", minor_units: 4100 },
      usd_accounting_amount: { currency: "USD", minor_units: 100 },
      manual_reference: {
        reference_rate_khr_per_usd: "4100.123456",
        source_reference: "Synthetic source",
        applicable_at: "2026-09-01T00:00:00Z",
        fallback_reason: "Synthetic fallback",
      },
    };
    expect(
      captureFinancialRequest({
        operation: "paymentRecord",
        target: {},
        body: khr,
      }).wireBody,
    ).toContain('"4100.123456"');
    for (const rate of [4100, "4100.1234567", "4.1e3", "-1", "01"])
      expect(() =>
        captureFinancialRequest({
          operation: "paymentRecord",
          target: {},
          body: {
            ...khr,
            manual_reference: {
              ...khr.manual_reference,
              reference_rate_khr_per_usd: rate,
            },
          },
        }),
      ).toThrow();
  });
  it("TEST-FE-293 preserves opaque proposal integers and rejects decimals booleans range depth and detail excess", () => {
    const proposal = {
      invoice_id: ids.invoice,
      amount_usd_cents: 100,
      details: [
        {
          invoice_line_id: ids.invoice,
          outstanding_usd_cents: 9_223_372_036_854_775_807n,
          amount_usd_cents: 100,
        },
      ],
    };
    const make = (value: typeof proposal) =>
      captureFinancialRequest({
        operation: "creditApply",
        target: { id: ids.credit },
        body: {
          currency: "USD",
          intent: { mode: "PROPOSAL", proposal: value },
        },
      });
    expect(make(proposal).wireBody).toContain("9223372036854775807");
    for (const amount of [
      new ExactJsonNumber("100.0"),
      true,
      9_000_000_000_000_001n,
      -0,
    ])
      expect(() =>
        captureFinancialRequest({
          operation: "creditApply",
          target: { id: ids.credit },
          body: {
            currency: "USD",
            intent: {
              mode: "DIRECT_CHARGE",
              late_payment_charge_id: ids.invoice,
              amount_usd_cents: amount,
            },
          },
        }),
      ).toThrow();
    expect(() =>
      make({
        ...proposal,
        details: Array.from(
          { length: 501 },
          () =>
            proposal.details[0] ?? {
              invoice_line_id: ids.invoice,
              outstanding_usd_cents: 100n,
              amount_usd_cents: 100,
            },
        ),
      }),
    ).toThrow();
    const nested = parseFinancialJson(
      '{"a":'.repeat(25) + "null" + "}".repeat(25),
    );
    expect(() =>
      captureFinancialRequest({
        operation: "creditApply",
        target: { id: ids.credit },
        body: {
          currency: "USD",
          intent: { mode: "PROPOSAL", proposal: { ...proposal, nested } },
        },
      }),
    ).toThrow();
    for (const value of [
      new ExactJsonNumber("-0"),
      new ExactJsonNumber("1e0"),
      new ExactJsonNumber("1.0"),
      true,
      "100",
      2 ** 53,
    ])
      expect(() => financialInteger(value)).toThrow();
  });
  it("TEST-FE-294 restores original request bytes and rejects unsupported recovery routes or currencies", () => {
    const wireBody = ' { "reason" : "Synthetic\\u0020correction" }\n';
    expect(
      captureWireRequest({
        operation: "creditReverse",
        target: { id: ids.credit },
        wireBody,
      }).wireBody,
    ).toBe(wireBody);
    for (const input of [
      { operation: "__proto__", target: {}, wireBody },
      {
        operation: "creditReverse",
        target: { id: ids.credit },
        wireBody,
        path: "/elsewhere",
      },
      {
        operation: "creditReverse",
        target: { id: ids.credit },
        wireBody,
        body: {},
      },
      {
        operation: "creditReverse",
        target: { id: ids.credit },
        wireBody: '{"reason":"a","reason":"b"}',
      },
    ])
      expect(() => captureWireRequest(input)).toThrow();
    for (const source_type of [
      "DEPOSIT",
      "SETTLEMENT",
      "SECURITY",
      "PET_DEPOSIT",
    ])
      expect(() =>
        captureFinancialRequest({
          operation: "refundCreate",
          target: {},
          body: {
            currency: "USD",
            source_type,
            source_id: ids.payment,
            amount_usd_cents: 100,
            reason: "Synthetic",
          },
        }),
      ).toThrow();
    expect(() =>
      captureFinancialRequest({
        operation: "refundCreate",
        target: {},
        body: {
          currency: "KHR",
          source_type: "PAYMENT",
          source_id: ids.payment,
          amount_usd_cents: 100,
          reason: "Synthetic",
        },
      }),
    ).toThrow();
  });
  it("TEST-FE-295 captures caller data without invoking getters or retaining mutable objects", () => {
    const getter = vi.fn(() => "creditReverse");
    const input = {
      get operation() {
        return getter();
      },
      target: { id: ids.credit },
      body: { reason: "Synthetic" },
    };
    expect(() => captureFinancialRequest(input as FinancialRequest)).toThrow();
    expect(getter).not.toHaveBeenCalled();
    const original = {
      operation: "paymentRecord" as const,
      target: {},
      body: { ...paymentBody, amount: { currency: "USD", minor_units: 100 } },
    };
    const captured = captureFinancialRequest(original);
    original.body.amount.minor_units = 900;
    expect(captured.wireBody).toContain('"minor_units":100');
    expect(Object.isFrozen(captured.target)).toBe(true);
  });
  it("TEST-FE-296 validates finite query keys bounds positive exact amounts and Pet review binding", () => {
    for (const query of [
      { status: "PENDING" },
      { limit: "50" },
      { limit: 0 },
      { limit: 101 },
      { cursor: "x".repeat(257) },
      { sort: "payment_date" },
      { include: "all" },
      { customer_id: null },
    ])
      expect(() =>
        captureWireRequest({ operation: "paymentList", target: {}, query }),
      ).toThrow();
    const amount = 9_000_000_000_000_000n;
    const request = captureFinancialRequest({
      operation: "creditProposal",
      target: { id: ids.credit },
      query: { invoice_id: ids.invoice, amount_usd_cents: amount },
    });
    expect(financialPath(request, ids.property)).toContain(
      "amount_usd_cents=9000000000000000",
    );
    expect(() =>
      captureFinancialRequest({
        operation: "refundSource",
        target: { id: ids.payment, sourceType: "PAYMENT" },
        query: { pet_refund_review_id: ids.event },
      }),
    ).toThrow();
    expect(() =>
      captureFinancialRequest({
        operation: "refundSource",
        target: { id: ids.payment, sourceType: "PET_DEPOSIT" },
        query: { pet_refund_review_id: ids.event },
      }),
    ).not.toThrow();
    expect(() =>
      captureWireRequest({
        operation: "paymentRecord",
        target: {},
        wireBody: " ".repeat(262145) + stringifyFinancialJson(paymentBody),
      }),
    ).toThrow();
  });
});

it.each(["creditReverse", "allocationReverse", "receiptReprint"] as const)(
  "TEST-FE-321 rejects PostgreSQL-incompatible NUL text before %s persistence",
  (operation) => {
    expect(() =>
      captureFinancialRequest({
        operation,
        target: { id: ids.credit },
        body: { reason: "Synthetic\0reason" },
      }),
    ).toThrow();
  },
);
