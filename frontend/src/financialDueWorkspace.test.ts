import { describe, expect, it } from "vitest";
import {
  replaceDueLineSelection,
  selectedDueLineIntent,
} from "./financialDueWorkspace";
import { type FinancialDueSelection } from "./financialDueSelection";
import { type FinancialObject } from "./financialContracts";
import { stringifyFinancialJson } from "./financialJson";

const id = (n: number) =>
  `00000000-0000-4000-8000-${n.toString().padStart(12, "0")}`;
function choice(count = 1, start = 10): FinancialDueSelection {
  return {
    amount: BigInt(count),
    parts: Array.from({ length: count }, (_, n) => ({
      source_kind: "DEBIT_ADJUSTMENT",
      source_id: id(start + n),
      amount_usd_cents: 1n,
    })),
  };
}
const data: FinancialObject = {
  items: [1, 2].map((n) => ({
    id: id(n),
    kind: "INVOICE_LINE",
    data: { outstanding_usd_cents: 1000 },
  })),
};

describe("workspace dated selection preservation", () => {
  it("TEST-FE-1055-DUE-LINES-1 leaves undesignated sources for server earliest-due attribution", () => {
    expect(selectedDueLineIntent(data, { [id(1)]: "1.23" }, {})).toEqual({
      total: 123n,
      details: [{ invoice_line_id: id(1), amount_usd_cents: 123n }],
    });
  });
  it("TEST-FE-1055-DUE-LINES-2 detaches exact parts and preserves mixed line intent", () => {
    const selected = choice(2),
      choices = { [id(1)]: selected },
      before = stringifyFinancialJson(choices);
    const result = selectedDueLineIntent(
      data,
      { [id(1)]: "0.02", [id(2)]: "1.00" },
      choices,
    );
    expect(result).toEqual({
      total: 102n,
      details: [
        {
          invoice_line_id: id(1),
          amount_usd_cents: 2n,
          source_parts: selected.parts,
        },
        { invoice_line_id: id(2), amount_usd_cents: 100n },
      ],
    });
    expect(result.details[0]?.source_parts).not.toBe(selected.parts);
    expect(stringifyFinancialJson(choices)).toBe(before);
  });
  it.each([499, 500])(
    "TEST-FE-1055-DUE-LINES-3 accepts $0 parts across lines without truncation",
    (count) => {
      const existing = { [id(1)]: choice(count - 1) },
        added = choice(1, 1000);
      const result = replaceDueLineSelection(existing, id(2), added);
      expect(result[id(1)]?.parts).toHaveLength(count - 1);
      expect(result[id(2)]?.parts).toEqual(added.parts);
      expect(result[id(1)]).not.toBe(existing[id(1)]);
      expect(result[id(2)]?.parts).not.toBe(added.parts);
    },
  );
  it("TEST-FE-1055-DUE-LINES-4 rejects 501 parts and preserves both drafts", () => {
    const old = { [id(1)]: choice(500) },
      addition = choice(1, 1000),
      before = stringifyFinancialJson({ old, addition });
    expect(() => {
      replaceDueLineSelection(old, id(2), addition);
    }).toThrow(/500/);
    expect(stringifyFinancialJson({ old, addition })).toBe(before);
  });
  it("TEST-FE-1055-DUE-LINES-5 counts replacement once without dropping another line", () => {
    const old = { [id(1)]: choice(499), [id(2)]: choice(1, 1000) };
    const next = replaceDueLineSelection(old, id(1), choice(499, 2000));
    expect(next[id(1)]?.parts).toHaveLength(499);
    expect(next[id(2)]).toEqual(old[id(2)]);
    expect(old[id(1)]?.parts[0]?.source_id).toBe(id(10));
  });
  it.each([
    "empty",
    "duplicate",
    "sum",
    "zero",
    "negative",
    "overflow",
    "source",
    "line",
  ])(
    "TEST-FE-1055-DUE-LINES-6 rejects inconsistent $0 selection without mutation",
    (issue) => {
      const value = choice(),
        first = value.parts[0];
      if (!first) throw new Error("Missing synthetic source");
      let line = id(1);
      if (issue === "empty") value.parts = [];
      if (issue === "duplicate") {
        value.parts.push({ ...first });
        value.amount = 2n;
      }
      if (issue === "sum") value.amount = 2n;
      if (issue === "zero") {
        first.amount_usd_cents = 0n;
        value.amount = 0n;
      }
      if (issue === "negative") {
        first.amount_usd_cents = -1n;
        value.amount = -1n;
      }
      if (issue === "overflow") {
        first.amount_usd_cents = 9_000_000_000_000_001n;
        value.amount = first.amount_usd_cents;
      }
      if (issue === "source") first.source_id = "invalid";
      if (issue === "line") line = "invalid";
      const before = stringifyFinancialJson(value);
      expect(() => {
        replaceDueLineSelection({}, line, value);
      }).toThrow();
      expect(stringifyFinancialJson(value)).toBe(before);
    },
  );
  it.each(["missing", "blank", "zero", "mismatch", "removed", "overbalance"])(
    "TEST-FE-1055-DUE-LINES-7 refuses silent fallback for $0 explicit choices",
    (issue) => {
      let values = { [id(1)]: "0.01", [id(2)]: "0.01" };
      const choices = { [id(1)]: choice() };
      let context = data;
      if (issue === "missing")
        values = Object.fromEntries(
          Object.entries(values).filter(([line]) => line !== id(1)),
        );
      if (issue === "blank") values[id(1)] = "";
      if (issue === "zero") values[id(1)] = "0.00";
      if (issue === "mismatch") values[id(1)] = "0.02";
      if (issue === "removed") context = { items: [] };
      if (issue === "overbalance") values[id(1)] = "10.01";
      expect(() => {
        selectedDueLineIntent(context, values, choices);
      }).toThrow();
      expect(choices[id(1)]?.parts).toHaveLength(1);
    },
  );
});
