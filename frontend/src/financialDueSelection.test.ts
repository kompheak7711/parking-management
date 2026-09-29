import { describe, expect, it } from "vitest";
import { invalidFinancial, type FinancialObject } from "./financialContracts";
import {
  dueAmountText,
  dueSourceKey,
  selectedDueSources,
} from "./financialDueSelection";
import { stringifyFinancialJson } from "./financialJson";
import { ids } from "./test/financialFixtures";

function setup() {
  const rows: FinancialObject[] = [
    {
      source_kind: "DEBIT_ADJUSTMENT",
      source_id: ids.event,
      remaining_usd_cents: 100,
    },
    {
      source_kind: "ORIGINAL_LINE",
      source_id: ids.other,
      remaining_usd_cents: 200,
    },
  ];
  const data: FinancialObject = {
    item_count: 2,
    aggregate_outstanding_usd_cents: 300,
    items: rows,
  };
  return {
    data,
    rows,
    first: rows[0] ?? invalidFinancial(),
    second: rows[1] ?? invalidFinancial(),
  };
}
function many(count: number) {
  const rows = Array.from({ length: count }, (_, index) => ({
    source_kind: "DEBIT_ADJUSTMENT",
    source_id: `00000000-0000-4000-8000-${(index + 1).toString(16).padStart(12, "0")}`,
    remaining_usd_cents: 1,
  }));
  return {
    data: {
      item_count: count,
      aggregate_outstanding_usd_cents: count,
      items: rows,
    },
    values: Object.fromEntries(
      rows.map((row) => [dueSourceKey(row), "0.01"] as const),
    ),
  };
}
describe("explicit dated-source selections", () => {
  it("TEST-FE-1055-DUE-SELECTION-1 preserves chosen sources and amounts in server display order", () => {
    const { data, first, second } = setup();
    const result = selectedDueSources(data, {
      [dueSourceKey(second)]: "0.80",
      [dueSourceKey(first)]: "0.60",
    });
    expect(result).toEqual({
      amount: 140n,
      parts: [
        {
          source_kind: "DEBIT_ADJUSTMENT",
          source_id: ids.event,
          amount_usd_cents: 60n,
        },
        {
          source_kind: "ORIGINAL_LINE",
          source_id: ids.other,
          amount_usd_cents: 80n,
        },
      ],
    });
  });
  it("TEST-FE-1055-DUE-SELECTION-1 neither mutates facts nor retains editable amounts", () => {
    const { data, first } = setup(),
      before = stringifyFinancialJson(data),
      values = { [dueSourceKey(first)]: "0.75" },
      result = selectedDueSources(data, values);
    expect(stringifyFinancialJson(data)).toBe(before);
    expect(values[dueSourceKey(first)]).toBe("0.75");
    values[dueSourceKey(first)] = "0.01";
    first.remaining_usd_cents = 1;
    expect(result.parts[0]?.amount_usd_cents).toBe(75n);
  });
  it("TEST-FE-1055-DUE-SELECTION-2 ignores blank and zero entries without adding sources", () => {
    const { data, first, second } = setup();
    const result = selectedDueSources(data, {
      [dueSourceKey(first)]: "1.00",
      [dueSourceKey(second)]: "0.00",
      unused: "",
    });
    expect(result.amount).toBe(100n);
    expect(result.parts).toHaveLength(1);
  });
  it.each(["", "0", "-1", "1.001", "1e2", "NaN", "Infinity", "2.01"])(
    "TEST-FE-1055-DUE-SELECTION-2 rejects invalid or excessive amount %s",
    (text) => {
      const { data, first } = setup();
      expect(() =>
        selectedDueSources(data, { [dueSourceKey(first)]: text }),
      ).toThrow();
    },
  );
  it.each([`DEBIT_ADJUSTMENT:${ids.customer}`, "not-a-source"])(
    "TEST-FE-1055-DUE-SELECTION-3 rejects unavailable positive source %s",
    (key) => {
      expect(() =>
        selectedDueSources(setup().data, { [key]: "0.01" }),
      ).toThrow();
    },
  );
  it.each(["count", "aggregate", "duplicate", "kind", "id", "remaining"])(
    "TEST-FE-1055-DUE-SELECTION-3 rejects incomplete or inconsistent facts %s",
    (failure) => {
      const { data, rows, first } = setup(),
        key = dueSourceKey(first);
      if (failure === "count") data.item_count = 3;
      if (failure === "aggregate") data.aggregate_outstanding_usd_cents = 301;
      if (failure === "duplicate") rows[1] = { ...first };
      if (failure === "kind") first.source_kind = "OTHER";
      if (failure === "id") first.source_id = "invalid";
      if (failure === "remaining") first.remaining_usd_cents = 0;
      expect(() => selectedDueSources(data, { [key]: "0.01" })).toThrow();
    },
  );
  it("TEST-FE-1055-DUE-SELECTION-3 refuses an empty selection", () => {
    expect(() =>
      selectedDueSources(
        { items: [], item_count: 0, aggregate_outstanding_usd_cents: 0 },
        {},
      ),
    ).toThrow();
  });
  it("TEST-FE-1055-DUE-SELECTION-4 retains all 500 allowed explicit parts", () => {
    const { data, values } = many(500),
      result = selectedDueSources(data, values);
    expect(result.parts).toHaveLength(500);
    expect(result.amount).toBe(500n);
    expect(result.parts[499]?.source_id).toBe(
      "00000000-0000-4000-8000-0000000001f4",
    );
  });
  it("TEST-FE-1055-DUE-SELECTION-4 rejects 501 selected parts without truncation", () => {
    const { data, values } = many(501);
    expect(() => selectedDueSources(data, values)).toThrow();
  });
  it.each([
    [0n, "0.00"],
    [1n, "0.01"],
    [10n, "0.10"],
    [100n, "1.00"],
    [9_000_000_000_000_000n, "90000000000000.00"],
  ] as const)(
    "TEST-FE-1055-DUE-SELECTION-5 formats %s exact cents without floating-point conversion",
    (amount, expected) => {
      expect(dueAmountText(amount)).toBe(expected);
    },
  );
  it.each([-1n, 9_000_000_000_000_001n])(
    "TEST-FE-1055-DUE-SELECTION-5 refuses out-of-range text amount %s",
    (amount) => {
      expect(() => dueAmountText(amount)).toThrow();
    },
  );
  it("TEST-FE-1055-DUE-SELECTION-6 rejects a selected total above the existing command limit", () => {
    const { data, first, second } = setup();
    first.remaining_usd_cents = 9_000_000_000_000_000n;
    second.remaining_usd_cents = 1;
    data.aggregate_outstanding_usd_cents = 9_000_000_000_000_001n;
    expect(() =>
      selectedDueSources(data, {
        [dueSourceKey(first)]: "90000000000000.00",
        [dueSourceKey(second)]: "0.01",
      }),
    ).toThrow();
  });
  it("TEST-FE-1055-DUE-SELECTION-6 rejects a noncanonical source identity", () => {
    const { first } = setup();
    first.source_id = ids.event.toUpperCase();
    expect(() => dueSourceKey(first)).toThrow();
  });
});
