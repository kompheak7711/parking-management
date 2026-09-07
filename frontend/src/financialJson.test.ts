import { describe, expect, it, vi } from "vitest";
import {
  ExactJsonNumber,
  FinancialJsonError,
  parseFinancialJson,
  stringifyFinancialJson,
} from "./financialJson";

describe("exact financial JSON", () => {
  it("TEST-FE-260 preserves bigint boundaries and original decimal tokens", () => {
    const raw =
      '{"min":-9223372036854775808,"max":9223372036854775807,"amount":9000000000000000,"rate":4100.12345678901234567890,"exponent":1.2300e-7,"string":"1.2300e-7"}';
    const parsed = parseFinancialJson(raw);
    expect(parsed).toEqual({
      min: -9223372036854775808n,
      max: 9223372036854775807n,
      amount: 9000000000000000,
      rate: new ExactJsonNumber("4100.12345678901234567890"),
      exponent: new ExactJsonNumber("1.2300e-7"),
      string: "1.2300e-7",
    });
    expect(stringifyFinancialJson(parsed)).toBe(raw);
  });
  it.each([0.1, 1.5, NaN, Infinity, -Infinity, Number.MAX_SAFE_INTEGER + 1])(
    "TEST-FE-261 refuses an already rounded or noninteger native number %s",
    (value) => {
      expect(() => stringifyFinancialJson({ value })).toThrow(
        FinancialJsonError,
      );
    },
  );
  it.each([
    "",
    " ",
    "01",
    "+1",
    "1.",
    ".1",
    "1e",
    "NaN",
    "Infinity",
    "null true",
    "[1,]",
    '{"a":1,}',
    '{"a":1,"a":2}',
    '{"a":1,"\\u0061":2}',
    '{"inner":{"a":1,"a":2}}',
    '{"a" 1}',
    "[}",
    "{]",
    '"unterminated',
    '"bad\\x"',
    '"line\nbreak"',
    '"\\ud800"',
    '"\\udc00"',
    '"\ud800"',
    "\ufeff{}",
  ])("TEST-FE-262 rejects malformed or ambiguous JSON %s", (raw) => {
    expect(() => parseFinancialJson(raw)).toThrow(FinancialJsonError);
  });
  it("TEST-FE-263 preserves dangerous-looking keys only as own data", () => {
    const raw = '{"__proto__":{"polluted":true},"constructor":4,"prototype":5}';
    const parsed = parseFinancialJson(raw);
    expect(Object.getPrototypeOf(parsed)).toBe(Object.prototype);
    expect(Object.hasOwn(parsed as object, "__proto__")).toBe(true);
    expect(Object.hasOwn({}, "polluted")).toBe(false);
    expect(stringifyFinancialJson(parsed)).toBe(raw);
  });
  it.each([
    "Khmer ខ្មែរ",
    "emoji 😀",
    'quotes " and slash \\',
    "1e4 [,] {} :",
    "\u0000\b\f\r\n\t",
    "\\ud800",
  ])("TEST-FE-264 preserves escaped string values and keys %s", (text) => {
    const raw = JSON.stringify({ [text]: [text, null, true, false] });
    expect(stringifyFinancialJson(parseFinancialJson(raw))).toBe(raw);
  });
  it("TEST-FE-265 processes deep valid structures without recursive stack overflow", () => {
    const raw = "[".repeat(8000) + "9223372036854775807" + "]".repeat(8000);
    expect(stringifyFinancialJson(parseFinancialJson(raw))).toBe(raw);
    const child = { a: 1 };
    expect(stringifyFinancialJson([child, child])).toBe('[{"a":1},{"a":1}]');
  });
  it("TEST-FE-266 counts exact UTF8 bytes and fails before exceeding its caller limit", () => {
    const raw = '"ខ😀"';
    const size = new TextEncoder().encode(raw).byteLength;
    expect(parseFinancialJson(raw, size)).toBe("ខ😀");
    expect(stringifyFinancialJson("ខ😀", size)).toBe(raw);
    expect(() => parseFinancialJson(raw, size - 1)).toThrow(FinancialJsonError);
    expect(() => stringifyFinancialJson("ខ😀", size - 1)).toThrow(
      FinancialJsonError,
    );
    expect(() => stringifyFinancialJson([1, 2], 4)).toThrow(FinancialJsonError);
    expect(stringifyFinancialJson([1, 2], 5)).toBe("[1,2]");
  });
  it("TEST-FE-267 rejects cycles, holes, exotic values and getters without invoking them", () => {
    const get = vi.fn(() => 1);
    const access = Object.defineProperty({}, "secret", {
      enumerable: true,
      get,
    });
    const cycle: unknown[] = [];
    cycle.push(cycle);
    for (const value of [
      undefined,
      () => 1,
      Symbol("x"),
      new Date(),
      new Map(),
      access,
      cycle,
      new Array(3),
      { [Symbol("x")]: 1 },
      { missing: undefined },
    ])
      expect(() => stringifyFinancialJson(value)).toThrow(FinancialJsonError);
    expect(get).not.toHaveBeenCalled();
  });
  it("TEST-FE-268 preserves a reviewed proposal through an outer encrypted-intent envelope", () => {
    const raw =
      '{"currency":"USD","intent":{"mode":"PROPOSAL","proposal":{"amount_usd_cents":9000000000000000,"outstanding_usd_cents":9223372036854775807,"source_rate":4100.000000000001}}}';
    const wireBody = stringifyFinancialJson(parseFinancialJson(raw));
    const sealedText = stringifyFinancialJson({ key: "original", wireBody });
    expect(JSON.parse(sealedText) as unknown).toEqual({
      key: "original",
      wireBody: raw,
    });
  });
  it.each([0, -1, 1.1, NaN, Infinity])(
    "TEST-FE-269 rejects invalid byte budgets %s",
    (limit) => {
      expect(() => parseFinancialJson("0", limit)).toThrow(FinancialJsonError);
      expect(() => stringifyFinancialJson(0, limit)).toThrow(
        FinancialJsonError,
      );
    },
  );
  it.each(["-0", "0.0", "1e999", "-0E-100", "100.00", "1E+3"])(
    "TEST-FE-270 preserves numeric token form %s",
    (literal) => {
      expect(stringifyFinancialJson(parseFinancialJson(literal))).toBe(literal);
      expect(() => JSON.stringify(new ExactJsonNumber(literal))).toThrow(
        FinancialJsonError,
      );
    },
  );
  it("TEST-FE-271 never invokes custom serialization hooks", () => {
    const hook = vi.fn(() => ({ amount: 1 }));
    expect(() => stringifyFinancialJson({ toJSON: hook })).toThrow(
      FinancialJsonError,
    );
    expect(hook).not.toHaveBeenCalled();
    for (const literal of ["01", '0);fetch("/")', "", "+2", "NaN"])
      expect(() => new ExactJsonNumber(literal)).toThrow(FinancialJsonError);
    expect(stringifyFinancialJson(-0)).toBe("-0");
  });
});
