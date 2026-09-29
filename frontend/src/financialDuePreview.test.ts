import { describe, expect, it, vi } from "vitest";
import {
  duePreviewBody,
  validateDuePreviewReply,
  type DuePreviewKind,
} from "./financialDuePreview";
import { financialObject, type FinancialObject } from "./financialContracts";
import { ExactJsonNumber, stringifyFinancialJson } from "./financialJson";

function required<T>(value: T | undefined): T {
  if (value === undefined) throw new Error("Missing synthetic fixture value");
  return value;
}
const kinds: DuePreviewKind[] = ["PAYMENT", "CREDIT"];
const id = (n: number) =>
  `00000000-0000-4000-8000-${n.toString().padStart(12, "0")}`;
const list = (v: unknown): FinancialObject[] => {
  if (!Array.isArray(v)) throw new Error("Invalid synthetic fixture");
  return v.map(financialObject);
};
function setup(kind: DuePreviewKind, explicit = false, charge = false) {
  const parts: FinancialObject[] = [
    {
      source_kind: "DEBIT_ADJUSTMENT",
      source_id: id(5),
      approved_due_date: "2026-08-01",
      source_occurred_at: "2026-07-01T08:00:00.123456+07:00",
      outstanding_usd_cents: 9223372036854775807n,
      amount_usd_cents: 40,
    },
    {
      source_kind: "ORIGINAL_LINE",
      source_id: id(4),
      approved_due_date: "2026-09-01",
      source_occurred_at: "2026-06-01T01:00:00Z",
      outstanding_usd_cents: 100,
      amount_usd_cents: 60,
    },
  ];
  const line: FinancialObject = {
    invoice_line_id: id(4),
    amount_usd_cents: 100,
  };
  if (explicit)
    line.source_parts = parts.map((p) => ({
      source_kind: required(p.source_kind),
      source_id: required(p.source_id),
      amount_usd_cents: required(p.amount_usd_cents),
    }));
  const target: FinancialObject = charge
    ? { late_payment_charge_id: id(3), amount_usd_cents: 100 }
    : { invoice_id: id(3), amount_usd_cents: 100, details: [line] };
  const confirmation: FinancialObject = charge
    ? { ...target }
    : {
        ...target,
        invoice_version: 7,
        details: [
          {
            invoice_line_id: id(4),
            amount_usd_cents: 100,
            due_attribution: {
              basis: explicit ? "CUSTOMER_DESIGNATED" : "EARLIEST_DUE",
              parts,
            },
          },
        ],
      };
  const base = {
    mode: "DESIGNATED",
    designation_reference: "Synthetic customer choice",
  };
  const intent: FinancialObject =
    kind === "PAYMENT"
      ? { ...base, targets: [target] }
      : { ...base, ...target };
  const confirmed: FinancialObject =
    kind === "PAYMENT"
      ? { ...base, targets: [confirmation] }
      : { ...base, ...confirmation };
  const body: FinancialObject =
    kind === "PAYMENT" ? { intent } : { currency: "USD", intent };
  const reply: FinancialObject = {
    property_id: id(1),
    [kind === "PAYMENT" ? "payment_id" : "credit_id"]: id(2),
    available_usd_cents: 100,
    amount_usd_cents: 100,
    part_count: charge ? 0 : 2,
    intent: confirmed,
  };
  return { body, reply, intent, target, line, confirmation, confirmed, parts };
}
function validate(kind: DuePreviewKind, body: FinancialObject, reply: unknown) {
  return validateDuePreviewReply(
    kind,
    stringifyFinancialJson(body),
    reply,
    id(1),
    id(2),
  );
}

describe("dated designation preview contract", () => {
  it.each(
    kinds.flatMap((kind) =>
      [false, true].flatMap((explicit) =>
        [false, true].map((charge) => ({ kind, explicit, charge })),
      ),
    ),
  )(
    "TEST-FE-1055-DUE-1 preserves exact detached $kind explicit=$explicit charge=$charge evidence",
    ({ kind, explicit, charge }) => {
      const { body, reply } = setup(kind, explicit, charge),
        raw = stringifyFinancialJson(body);
      const parsed = duePreviewBody(kind, raw),
        result = validate(kind, body, reply);
      expect(parsed).toEqual(body);
      expect(result).toEqual(reply);
      expect(result).not.toBe(reply);
      expect(result.intent).not.toBe(reply.intent);
      expect(stringifyFinancialJson(body)).toBe(raw);
      expect(stringifyFinancialJson(result)).toBe(
        stringifyFinancialJson(reply),
      );
    },
  );
  const inputs = [
    "mode",
    "body_extra",
    "currency",
    "reference_blank",
    "reference_space",
    "reference_nul",
    "reference_long",
    "computed_version",
    "computed_due",
    "target_extra",
    "target_nil",
    "zero",
    "negative",
    "bool",
    "null",
    "float",
    "unsafe",
    "exponent",
    "too_large",
    "empty_details",
    "duplicate_line",
    "line_extra",
    "line_sum",
    "empty_parts",
    "source_kind",
    "source_nil",
    "source_extra",
    "duplicate_source",
    "source_sum",
  ] as const;
  it.each(kinds.flatMap((kind) => inputs.map((reason) => ({ kind, reason }))))(
    "TEST-FE-1055-DUE-2 rejects invalid $kind selection $reason",
    ({ kind, reason }) => {
      const { body, intent, target, line } = setup(kind, true);
      const parts = list(line.source_parts),
        part = required(parts[0]);
      switch (reason) {
        case "mode":
          intent.mode = "PROPOSAL";
          break;
        case "body_extra":
          body.unknown = "x";
          break;
        case "currency":
          body.currency = "KHR";
          break;
        case "reference_blank":
          intent.designation_reference = "";
          break;
        case "reference_space":
          intent.designation_reference = " x";
          break;
        case "reference_nul":
          intent.designation_reference = "x\0y";
          break;
        case "reference_long":
          intent.designation_reference = "x".repeat(501);
          break;
        case "computed_version":
          target.invoice_version = 7;
          break;
        case "computed_due":
          line.due_attribution = {};
          break;
        case "target_extra":
          target.extra = 1;
          break;
        case "target_nil":
          target.invoice_id = "00000000-0000-0000-0000-000000000000";
          break;
        case "zero":
          target.amount_usd_cents = 0;
          break;
        case "negative":
          target.amount_usd_cents = -1;
          break;
        case "bool":
          target.amount_usd_cents = true;
          break;
        case "null":
          target.amount_usd_cents = null;
          break;
        case "float":
          target.amount_usd_cents = 1.25;
          break;
        case "unsafe":
          target.amount_usd_cents = Number.MAX_SAFE_INTEGER + 1;
          break;
        case "exponent":
          target.amount_usd_cents = new ExactJsonNumber("1e2");
          break;
        case "too_large":
          target.amount_usd_cents = 9000000000000001n;
          break;
        case "empty_details":
          target.details = [];
          break;
        case "duplicate_line":
          target.details = [line, line];
          break;
        case "line_extra":
          line.unknown = 1;
          break;
        case "line_sum":
          line.amount_usd_cents = 99;
          break;
        case "empty_parts":
          line.source_parts = [];
          break;
        case "source_kind":
          part.source_kind = "UNKNOWN";
          break;
        case "source_nil":
          part.source_id = "00000000-0000-0000-0000-000000000000";
          break;
        case "source_extra":
          part.approved_due_date = "2026-09-01";
          break;
        case "duplicate_source":
          line.source_parts = [part, part];
          break;
        case "source_sum":
          part.amount_usd_cents = 39;
          break;
      }
      // Credit's single target is embedded directly, so reflect scalar field edits.
      if (kind === "CREDIT") Object.assign(intent, target);
      expect(() =>
        duePreviewBody(kind, stringifyFinancialJson(body)),
      ).toThrow();
    },
  );
  const replies = [
    "property",
    "source",
    "extra",
    "availability",
    "total",
    "count",
    "reference",
    "target",
    "target_extra",
    "version_missing",
    "version_zero",
    "version_large",
    "line_id",
    "line_amount",
    "line_extra",
    "line_count",
    "basis",
    "parts_empty",
    "duplicate_source",
    "kind",
    "original_id",
    "due_invalid",
    "due_unpadded",
    "timestamp_naive",
    "timestamp_invalid",
    "outstanding_zero",
    "over_applied",
    "amount_float",
    "amount_bool",
    "part_sum",
    "part_extra",
    "part_missing",
  ] as const;
  it.each(kinds.flatMap((kind) => replies.map((reason) => ({ kind, reason }))))(
    "TEST-FE-1055-DUE-3 rejects inconsistent $kind confirmation $reason",
    ({ kind, reason }) => {
      const { body, reply, confirmation, confirmed, parts } = setup(kind);
      const line = required(list(confirmation.details)[0]),
        due = financialObject(line.due_attribution),
        part = required(parts[0]);
      switch (reason) {
        case "property":
          reply.property_id = id(90);
          break;
        case "source":
          reply[kind === "PAYMENT" ? "payment_id" : "credit_id"] = id(90);
          break;
        case "extra":
          reply.unknown = 1;
          break;
        case "availability":
          reply.available_usd_cents = 99;
          break;
        case "total":
          reply.amount_usd_cents = 99;
          break;
        case "count":
          reply.part_count = 1;
          break;
        case "reference":
          confirmed.designation_reference = "Other";
          break;
        case "target":
          confirmation.invoice_id = id(90);
          break;
        case "target_extra":
          confirmation.unknown = 1;
          break;
        case "version_missing":
          delete confirmation.invoice_version;
          break;
        case "version_zero":
          confirmation.invoice_version = 0;
          break;
        case "version_large":
          confirmation.invoice_version = 10000000000n;
          break;
        case "line_id":
          line.invoice_line_id = id(90);
          break;
        case "line_amount":
          line.amount_usd_cents = 99;
          break;
        case "line_extra":
          line.source_parts = [];
          break;
        case "line_count":
          confirmation.details = [];
          break;
        case "basis":
          due.basis = "CUSTOMER_DESIGNATED";
          break;
        case "parts_empty":
          due.parts = [];
          break;
        case "duplicate_source":
          due.parts = [part, part];
          break;
        case "kind":
          part.source_kind = "UNKNOWN";
          break;
        case "original_id":
          required(parts[1]).source_id = id(90);
          break;
        case "due_invalid":
          part.approved_due_date = "2026-02-30";
          break;
        case "due_unpadded":
          part.approved_due_date = "2026-2-01";
          break;
        case "timestamp_naive":
          part.source_occurred_at = "2026-07-01T08:00:00";
          break;
        case "timestamp_invalid":
          part.source_occurred_at = "2026-07-01T25:00:00Z";
          break;
        case "outstanding_zero":
          part.outstanding_usd_cents = 0;
          break;
        case "over_applied":
          part.outstanding_usd_cents = 39;
          break;
        case "amount_float":
          part.amount_usd_cents = 40.5;
          break;
        case "amount_bool":
          part.amount_usd_cents = true;
          break;
        case "part_sum":
          part.amount_usd_cents = 39;
          break;
        case "part_extra":
          part.extra = 1;
          break;
        case "part_missing":
          delete part.source_occurred_at;
          break;
      }
      if (kind === "CREDIT") {
        delete confirmed.invoice_id;
        delete confirmed.amount_usd_cents;
        delete confirmed.invoice_version;
        delete confirmed.details;
        Object.assign(confirmed, confirmation);
      }
      expect(() => validate(kind, body, reply)).toThrow();
    },
  );
  it.each(
    kinds.flatMap((kind) =>
      ["order", "identity", "amount", "basis"].map((change) => ({
        kind,
        change,
      })),
    ),
  )(
    "TEST-FE-1055-DUE-4 binds explicit $kind source choices including $change",
    ({ kind, change }) => {
      const { body, reply, confirmation, parts } = setup(kind, true);
      const due = financialObject(
        required(list(confirmation.details)[0]).due_attribution,
      );
      if (change === "order") parts.reverse();
      if (change === "identity") required(parts[0]).source_id = id(80);
      if (change === "amount") {
        required(parts[0]).amount_usd_cents = 30;
        required(parts[1]).amount_usd_cents = 70;
      }
      if (change === "basis") due.basis = "EARLIEST_DUE";
      expect(() => validate(kind, body, reply)).toThrow();
    },
  );
  it("TEST-FE-1055-DUE-5 preserves mixed Payment targets and rejects substituted order or repeated targets", () => {
    const a = setup("PAYMENT"),
      b = setup("PAYMENT", false, true);
    a.intent.targets = [a.target, b.target];
    a.confirmed.targets = [a.confirmation, b.confirmation];
    a.reply.amount_usd_cents = 200;
    a.reply.available_usd_cents = 200;
    expect(validate("PAYMENT", a.body, a.reply)).toEqual(a.reply);
    a.confirmed.targets = [b.confirmation, a.confirmation];
    expect(() => validate("PAYMENT", a.body, a.reply)).toThrow();
    a.intent.targets = [a.target, a.target];
    expect(() =>
      duePreviewBody("PAYMENT", stringifyFinancialJson(a.body)),
    ).toThrow();
  });
  it.each(kinds)(
    "TEST-FE-1055-DUE-6 rejects duplicate JSON and response getters without executing them for %s",
    (kind) => {
      const { body, reply } = setup(kind),
        getter = vi.fn(() => "x");
      expect(() =>
        duePreviewBody(
          kind,
          stringifyFinancialJson(body).replace(
            '"intent":',
            '"intent":{},"intent":',
          ),
        ),
      ).toThrow();
      Object.defineProperty(reply, "intent", { enumerable: true, get: getter });
      expect(() => validate(kind, body, reply)).toThrow();
      expect(getter).not.toHaveBeenCalled();
    },
  );
  it.each(kinds)(
    "TEST-FE-1055-DUE-7 accepts500 exact parts but rejects501 whole-selection parts for %s",
    (kind) => {
      const { body, reply, intent, target, line, confirmation, confirmed } =
        setup(kind, true);
      const selected = Array.from({ length: 500 }, (_, n) => ({
        source_kind: "DEBIT_ADJUSTMENT",
        source_id: id(100 + n),
        amount_usd_cents: 1,
      }));
      line.amount_usd_cents = 500;
      line.source_parts = selected;
      target.amount_usd_cents = 500;
      confirmation.amount_usd_cents = 500;
      confirmation.details = [
        {
          invoice_line_id: id(4),
          amount_usd_cents: 500,
          due_attribution: {
            basis: "CUSTOMER_DESIGNATED",
            parts: selected.map((p) => ({
              ...p,
              approved_due_date: "2026-09-01",
              source_occurred_at: "2026-07-01T00:00:00Z",
              outstanding_usd_cents: 1,
            })),
          },
        },
      ];
      if (kind === "CREDIT") {
        Object.assign(intent, target);
        Object.assign(confirmed, confirmation);
      }
      reply.amount_usd_cents = 500;
      reply.available_usd_cents = 500;
      reply.part_count = 500;
      expect(validate(kind, body, reply)).toEqual(reply);
      line.source_parts = [
        ...selected,
        { ...required(selected[0]), source_id: id(900) },
      ];
      line.amount_usd_cents = 501;
      target.amount_usd_cents = 501;
      if (kind === "CREDIT") Object.assign(intent, target);
      expect(() =>
        duePreviewBody(kind, stringifyFinancialJson(body)),
      ).toThrow();
    },
  );
  it("TEST-FE-1055-DUE-8 rejects101 Payment targets and whole-selection amount overflow", () => {
    const { body, intent } = setup("PAYMENT", false, true);
    intent.targets = Array.from({ length: 100 }, (_, n) => ({
      late_payment_charge_id: id(100 + n),
      amount_usd_cents: 1,
    }));
    expect(duePreviewBody("PAYMENT", stringifyFinancialJson(body))).toEqual(
      body,
    );
    intent.targets = [
      ...list(intent.targets),
      { late_payment_charge_id: id(900), amount_usd_cents: 1 },
    ];
    expect(() =>
      duePreviewBody("PAYMENT", stringifyFinancialJson(body)),
    ).toThrow();
    intent.targets = [
      { late_payment_charge_id: id(3), amount_usd_cents: 9000000000000000n },
      { late_payment_charge_id: id(4), amount_usd_cents: 1 },
    ];
    expect(() =>
      duePreviewBody("PAYMENT", stringifyFinancialJson(body)),
    ).toThrow();
  });
});
