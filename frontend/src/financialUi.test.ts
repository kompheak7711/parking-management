import { describe, expect, it } from "vitest";
import {
  confirmedFinancialRequest,
  financialLocalInstant,
  financialMoney,
  financialTimestamp,
  financialUiError,
  parseFinancialAmount,
  parseFinancialRate,
  prepareFinancialCommand,
  type FinancialCommandRequest,
} from "./financialUi";
import {
  captureFinancialRequest,
  FinancialContractError,
} from "./financialContracts";
import { FinancialClientError } from "./financialClient";
import { FinancialReferenceError } from "./financialReferenceClient";

const actor = "11111111-1111-4111-8111-111111111111";
const property = "22222222-2222-4222-8222-222222222222";
const source = "33333333-3333-4333-8333-333333333333";
const scope = () => ({
  actorId: actor,
  propertyId: property,
  signal: new AbortController().signal,
});

describe("staff financial inputs and confirmation snapshots", () => {
  it("TEST-FE-413 parses exact dollars and whole riel at the command bounds", () => {
    expect(parseFinancialAmount("0.01")).toBe(1n);
    expect(parseFinancialAmount("10.1")).toBe(1010n);
    expect(parseFinancialAmount("90000000000000.00")).toBe(
      9_000_000_000_000_000n,
    );
    expect(parseFinancialAmount("9000000000000000", "KHR")).toBe(
      9_000_000_000_000_000n,
    );
    expect(parseFinancialAmount("0", "USD", true)).toBe(0n);
    for (const value of [
      "",
      "0",
      "-1",
      "+1",
      "01",
      ".1",
      "1.",
      "1e2",
      "1,000",
      " 1",
      "1 ",
      "1.001",
      "90000000000000.01",
      "9".repeat(100000),
    ])
      expect(() => parseFinancialAmount(value)).toThrow();
    for (const value of ["1.0", "0.01", "9000000000000001"])
      expect(() => parseFinancialAmount(value, "KHR")).toThrow();
    expect(parseFinancialRate("4062.000001")).toBe("4062.000001");
    expect(parseFinancialRate("0.000001")).toBe("0.000001");
    for (const value of [
      "0",
      "0.000000",
      "1e3",
      "-1",
      "1.0000001",
      "100000000000000",
      " 4062",
    ])
      expect(() => parseFinancialRate(value)).toThrow();
  });

  it("TEST-FE-414 displays exact signed aggregate cents and retains recorded timestamp precision", () => {
    expect(financialMoney(9_223_372_036_854_775_807n)).toBe(
      "USD 92,233,720,368,547,758.07",
    );
    expect(financialMoney(-9_223_372_036_854_775_808n)).toBe(
      "USD −92,233,720,368,547,758.08",
    );
    expect(financialMoney(40871, "KHR")).toBe("KHR 40,871");
    expect(financialMoney(1)).toBe("USD 0.01");
    for (const value of [
      null,
      undefined,
      "100",
      1.2,
      Number.MAX_SAFE_INTEGER + 1,
      9_223_372_036_854_775_808n,
    ])
      expect(financialMoney(value)).toBe("Unavailable");
    expect(financialLocalInstant("2028-02-29T15:04")).toBe(
      "2028-02-29T15:04:00+07:00",
    );
    expect(financialLocalInstant("2028-02-29T15:04:05.123456")).toBe(
      "2028-02-29T15:04:05.123456+07:00",
    );
    for (const value of [
      "2027-02-29T15:04",
      "2028-13-01T15:04",
      "2028-01-01T24:00",
      "2028-01-01T15:04Z",
      "2028-01-01T15:04:05.1234567",
    ])
      expect(() => financialLocalInstant(value)).toThrow();
    expect(financialTimestamp("2028-02-29T15:04:05.123456+07:00")).toBe(
      "2028-02-29 15:04:05.123456+07:00",
    );
    expect(financialTimestamp("private invalid input")).toBe("Unavailable");
  });

  it("TEST-FE-415 detaches and freezes the exact confirmed command and rejects other actor Property or copied snapshots", () => {
    const s = scope();
    const input: FinancialCommandRequest = {
      operation: "creditApply",
      target: { id: source },
      body: {
        currency: "USD",
        intent: {
          mode: "DIRECT_CHARGE",
          late_payment_charge_id: property,
          amount_usd_cents: 101n,
        },
      },
    };
    const prepared = prepareFinancialCommand(s, input);
    const originalBytes = prepared.wireBody;
    input.target.id = actor;
    input.body.intent = {
      mode: "DIRECT_CHARGE",
      late_payment_charge_id: actor,
      amount_usd_cents: 999,
    };
    expect(confirmedFinancialRequest(s, prepared).target).toEqual({
      id: source,
    });
    expect(
      captureFinancialRequest(confirmedFinancialRequest(s, prepared)).wireBody,
    ).toBe(originalBytes);
    expect(originalBytes).toContain('"amount_usd_cents":101');
    expect(Object.isFrozen(prepared)).toBe(true);
    expect(Object.isFrozen(prepared.request)).toBe(true);
    expect(Object.isFrozen(prepared.request.target)).toBe(true);
    expect(Object.isFrozen(prepared.request.body)).toBe(true);
    expect(Object.isFrozen(prepared.request.body.intent)).toBe(true);
    expect(() =>
      Object.assign(prepared.request.body, { currency: "KHR" }),
    ).toThrow();
    expect(() =>
      confirmedFinancialRequest({ ...s, actorId: source }, prepared),
    ).toThrow();
    expect(() =>
      confirmedFinancialRequest({ ...s, propertyId: source }, prepared),
    ).toThrow();
    expect(() => confirmedFinancialRequest(s, { ...prepared })).toThrow();
    const aborter = new AbortController();
    const active = { ...s, signal: aborter.signal };
    const beforeAbort = prepareFinancialCommand(active, {
      operation: "allocationReverse",
      target: { id: source },
      body: { reason: "Original event correction" },
    });
    aborter.abort();
    expect(() => confirmedFinancialRequest(active, beforeAbort)).toThrow();
    expect(() => prepareFinancialCommand(active, input)).toThrow();
  });

  it("TEST-FE-416 gives finite safe explanations without exposing server or arbitrary exception text", () => {
    expect(
      financialUiError(new Error("secret SQL and customer body")),
    ).not.toContain("secret");
    expect(
      financialUiError(new FinancialReferenceError("HTTP_REJECTION", 403)),
    ).toContain("permission");
    expect(
      financialUiError(new FinancialReferenceError("HTTP_REJECTION", 404)),
    ).toContain("Property");
    expect(
      financialUiError(new FinancialClientError("HTTP_REJECTION", true, 409)),
    ).toContain("Review its outcome");
    expect(
      financialUiError(new FinancialReferenceError("RESPONSE_TOO_LARGE")),
    ).toContain("complete view is unavailable");
    expect(financialUiError(new FinancialContractError())).toContain(
      "Check the financial fields",
    );
  });
});

it.each([false, true])(
  "TEST-FE-423 rejects an old confirmation in a new same-actor same-Property workspace, original aborted %s",
  (abortOriginal) => {
    const aborter = new AbortController();
    const original = { ...scope(), signal: aborter.signal };
    const prepared = prepareFinancialCommand(original, {
      operation: "allocationReverse",
      target: { id: source },
      body: { reason: "Original correction" },
    });
    if (abortOriginal) aborter.abort();
    expect(() => confirmedFinancialRequest(scope(), prepared)).toThrow();
  },
);
