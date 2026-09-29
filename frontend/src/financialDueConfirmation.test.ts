import { describe, expect, it } from "vitest";
import {
  captureFinancialRequest,
  captureWireRequest,
  commandBody,
  financialObject,
  type FinancialObject,
  type FinancialRequest,
} from "./financialContracts";
import { validateDueConfirmation } from "./financialDueConfirmation";
import { decodeFinancialIntent } from "./financialRecovery";
import { stringifyFinancialJson } from "./financialJson";
import { ids } from "./test/financialFixtures";

const identity = (n: number) =>
  `00000000-0000-4000-8000-${n.toString().padStart(12, "0")}`;
function setup(basis = "EARLIEST_DUE") {
  const part: FinancialObject = {
    source_kind: "DEBIT_ADJUSTMENT",
    source_id: ids.event,
    approved_due_date: "2026-09-01",
    source_occurred_at: "2026-08-01T01:02:03.456789+07:00",
    outstanding_usd_cents: 9223372036854775807n,
    amount_usd_cents: 40,
  };
  const original: FinancialObject = {
    source_kind: "ORIGINAL_LINE",
    source_id: ids.other,
    approved_due_date: "2026-09-10",
    source_occurred_at: "2026-07-01T00:00:00Z",
    outstanding_usd_cents: 100,
    amount_usd_cents: 60,
  };
  const due: FinancialObject = { basis, parts: [part, original] };
  const detail: FinancialObject = {
    invoice_line_id: ids.other,
    amount_usd_cents: 100,
    due_attribution: due,
  };
  const intent: FinancialObject = {
    mode: "DESIGNATED",
    invoice_id: ids.invoice,
    invoice_version: 7,
    amount_usd_cents: 100,
    designation_reference: "Synthetic customer choice",
    details: [detail],
  };
  const body: FinancialObject = { currency: "USD", intent };
  return { body, intent, detail, due, part, original };
}
const request = (body: FinancialObject): FinancialRequest => ({
  operation: "creditApply",
  target: { id: ids.credit },
  body,
});
describe("dated Credit confirmation commands", () => {
  it.each(["EARLIEST_DUE", "CUSTOMER_DESIGNATED"])(
    "TEST-FE-1055-CONFIRM-1 preserves exact %s evidence and captured bytes",
    (basis) => {
      const { body, intent } = setup(basis),
        raw =
          ' {"currency":"USD", "intent":' +
          stringifyFinancialJson(intent) +
          "}\n";
      const captured = captureWireRequest({
        operation: "creditApply",
        target: { id: ids.credit },
        wireBody: raw,
      });
      expect(captured.wireBody).toBe(raw);
      expect(commandBody("creditApply", raw)).toEqual(body);
      const fromInput = captureFinancialRequest(request(body));
      expect(fromInput.wireBody).toBe(stringifyFinancialJson(body));
      intent.designation_reference = "Changed after capture";
      expect(captured.wireBody).toBe(raw);
      expect(fromInput.wireBody).not.toContain("Changed after capture");
    },
  );
  const failures = [
    "version_missing",
    "version_zero",
    "version_negative",
    "version_float",
    "version_bool",
    "version_large",
    "extra_intent",
    "both_targets",
    "empty_details",
    "too_many_details",
    "duplicate_line",
    "line_nil",
    "line_extra",
    "line_amount_zero",
    "line_amount_bool",
    "line_amount_float",
    "line_total",
    "due_missing",
    "due_extra",
    "basis",
    "empty_parts",
    "part_extra",
    "part_missing",
    "source_kind",
    "source_nil",
    "source_duplicate",
    "original_identity",
    "date_invalid",
    "date_unpadded",
    "timestamp_naive",
    "timestamp_invalid",
    "outstanding_zero",
    "outstanding_overflow",
    "over_applied",
    "part_amount_zero",
    "part_amount_bool",
    "part_amount_float",
    "part_total",
    "top_total",
    "mixed_details",
  ] as const;
  it.each(failures)(
    "TEST-FE-1055-CONFIRM-2 rejects invalid dated Credit %s",
    (failure) => {
      const { body, intent, detail, due, part, original } = setup();
      switch (failure) {
        case "version_missing":
          delete intent.invoice_version;
          break;
        case "version_zero":
          intent.invoice_version = 0;
          break;
        case "version_negative":
          intent.invoice_version = -1;
          break;
        case "version_float":
          intent.invoice_version = 1.5;
          break;
        case "version_bool":
          intent.invoice_version = true;
          break;
        case "version_large":
          intent.invoice_version = 10000000000n;
          break;
        case "extra_intent":
          intent.source_parts = [];
          break;
        case "both_targets":
          intent.late_payment_charge_id = ids.event;
          break;
        case "empty_details":
          intent.details = [];
          break;
        case "too_many_details":
          intent.details = Array.from({ length: 501 }, () => detail);
          break;
        case "duplicate_line":
          intent.details = [detail, detail];
          intent.amount_usd_cents = 200;
          break;
        case "line_nil":
          detail.invoice_line_id = "00000000-0000-0000-0000-000000000000";
          break;
        case "line_extra":
          detail.source_parts = [];
          break;
        case "line_amount_zero":
          detail.amount_usd_cents = 0;
          break;
        case "line_amount_bool":
          detail.amount_usd_cents = true;
          break;
        case "line_amount_float":
          detail.amount_usd_cents = 100.5;
          break;
        case "line_total":
          detail.amount_usd_cents = 99;
          break;
        case "due_missing":
          delete detail.due_attribution;
          break;
        case "due_extra":
          due.unknown = 1;
          break;
        case "basis":
          due.basis = "UNKNOWN";
          break;
        case "empty_parts":
          due.parts = [];
          break;
        case "part_extra":
          part.unknown = 1;
          break;
        case "part_missing":
          delete part.approved_due_date;
          break;
        case "source_kind":
          part.source_kind = "UNKNOWN";
          break;
        case "source_nil":
          part.source_id = "00000000-0000-0000-0000-000000000000";
          break;
        case "source_duplicate":
          due.parts = [part, { ...part, amount_usd_cents: 60 }];
          break;
        case "original_identity":
          original.source_id = ids.invoice;
          break;
        case "date_invalid":
          part.approved_due_date = "2026-02-30";
          break;
        case "date_unpadded":
          part.approved_due_date = "2026-9-01";
          break;
        case "timestamp_naive":
          part.source_occurred_at = "2026-08-01T01:02:03";
          break;
        case "timestamp_invalid":
          part.source_occurred_at = "2026-08-01T24:02:03Z";
          break;
        case "outstanding_zero":
          part.outstanding_usd_cents = 0;
          break;
        case "outstanding_overflow":
          part.outstanding_usd_cents = 9223372036854775808n;
          break;
        case "over_applied":
          part.outstanding_usd_cents = 39;
          break;
        case "part_amount_zero":
          part.amount_usd_cents = 0;
          break;
        case "part_amount_bool":
          part.amount_usd_cents = true;
          break;
        case "part_amount_float":
          part.amount_usd_cents = 40.5;
          break;
        case "part_total":
          part.amount_usd_cents = 39;
          break;
        case "top_total":
          intent.amount_usd_cents = 99;
          break;
        case "mixed_details":
          intent.details = [
            detail,
            { invoice_line_id: ids.receipt, amount_usd_cents: 100 },
          ];
          intent.amount_usd_cents = 200;
          break;
      }
      expect(() => captureFinancialRequest(request(body))).toThrow();
    },
  );
  it.each([false, true])(
    "TEST-FE-1055-CONFIRM-3 preserves stored Credit legacy=%s bytes without asserting new server acceptance",
    (legacy) => {
      const { body, intent, detail } = setup();
      if (legacy) {
        delete intent.invoice_version;
        delete detail.due_attribution;
      }
      const raw = "\n " + stringifyFinancialJson(body) + " ";
      const opened = {
        requestKey: ids.key,
        plaintext: stringifyFinancialJson({
          namespace: "property-rental.financial-command",
          version: 1,
          actorId: ids.actor,
          propertyId: ids.property,
          key: ids.key,
          operation: "creditApply",
          target: { id: ids.credit },
          wireBody: raw,
        }),
      };
      const decoded = decodeFinancialIntent(opened, ids.actor);
      expect(decoded?.wireBody).toBe(raw);
      expect(decoded?.key).toBe(ids.key);
      expect(decoded?.operation).toBe("creditApply");
    },
  );
  it.each(["PAYMENT_DESIGNATED", "PAYMENT_PROPOSAL", "CREDIT_PROPOSAL"])(
    "TEST-FE-1055-CONFIRM-4 retains connected %s source evidence without normalizing it",
    (mode) => {
      const { intent } = setup();
      const target: FinancialObject = {
        invoice_id: intent.invoice_id ?? ids.invoice,
        invoice_version: 7,
        amount_usd_cents: 100,
        details: intent.details ?? [],
      };
      const selected: FinancialObject =
        mode === "PAYMENT_DESIGNATED"
          ? {
              mode: "DESIGNATED",
              designation_reference: "Synthetic choice",
              targets: [target],
            }
          : mode === "PAYMENT_PROPOSAL"
            ? {
                mode: "PROPOSAL",
                proposal: {
                  payment_id: ids.payment,
                  property_id: ids.property,
                  targets: [target],
                },
              }
            : {
                mode: "PROPOSAL",
                proposal: {
                  ...target,
                  credit_id: ids.credit,
                  property_id: ids.property,
                },
              };
      const operation =
        mode === "CREDIT_PROPOSAL" ? "creditApply" : "allocationPost";
      const body: FinancialObject =
        operation === "creditApply"
          ? { currency: "USD", intent: selected }
          : { intent: selected };
      const raw = stringifyFinancialJson(body);
      const captured = captureWireRequest({
        operation,
        target: { id: operation === "creditApply" ? ids.credit : ids.payment },
        wireBody: raw,
      });
      expect(captured.wireBody).toBe(raw);
      expect(commandBody(operation, raw)).toEqual(body);
    },
  );
  it.each(["DIRECT_CHARGE", "DESIGNATED"])(
    "TEST-FE-1055-CONFIRM-5 keeps %s Charge commands separate and rejects Invoice-only fields",
    (mode) => {
      const intent: FinancialObject = {
        mode,
        late_payment_charge_id: ids.event,
        amount_usd_cents: 100,
      };
      if (mode === "DESIGNATED")
        intent.designation_reference = "Synthetic charge choice";
      const body = { currency: "USD", intent },
        raw = stringifyFinancialJson(body);
      expect(commandBody("creditApply", raw)).toEqual(body);
      intent.invoice_version = 7;
      expect(() =>
        commandBody("creditApply", stringifyFinancialJson(body)),
      ).toThrow();
    },
  );
  it("TEST-FE-1055-CONFIRM-6 accepts500 total parts and rejects501 across otherwise valid lines", () => {
    const { body, intent } = setup();
    const line = (lineNumber: number, count: number): FinancialObject => ({
      invoice_line_id: identity(lineNumber),
      amount_usd_cents: count,
      due_attribution: {
        basis: "CUSTOMER_DESIGNATED",
        parts: Array.from({ length: count }, (_, n) => ({
          source_kind: "DEBIT_ADJUSTMENT",
          source_id: identity(lineNumber * 1000 + n),
          approved_due_date: "2026-09-01",
          source_occurred_at: "2026-08-01T01:00:00Z",
          outstanding_usd_cents: 1,
          amount_usd_cents: 1,
        })),
      },
    });
    intent.details = [line(1, 250), line(2, 250)];
    intent.amount_usd_cents = 500;
    expect(commandBody("creditApply", stringifyFinancialJson(body))).toEqual(
      body,
    );
    intent.details = [line(1, 250), line(2, 251)];
    intent.amount_usd_cents = 501;
    expect(() => captureFinancialRequest(request(body))).toThrow();
  });
  it("TEST-FE-1055-CONFIRM-7 accepts maximum exact amount and version without losing integer evidence", () => {
    const { body, intent, detail, due, part } = setup();
    intent.invoice_version = 9999999999;
    intent.amount_usd_cents = 9000000000000000;
    detail.amount_usd_cents = 9000000000000000;
    part.amount_usd_cents = 9000000000000000;
    due.parts = [part];
    const before = stringifyFinancialJson(body);
    validateDueConfirmation(
      intent.details,
      intent.amount_usd_cents,
      intent.invoice_version,
    );
    expect(stringifyFinancialJson(body)).toBe(before);
    expect(commandBody("creditApply", before)).toEqual(body);
  });
  it("TEST-FE-1055-CONFIRM-8 requires every versioned detail and leaves the old no-version shape unchanged", () => {
    const { body, intent, detail } = setup();
    delete detail.due_attribution;
    expect(() => captureFinancialRequest(request(body))).toThrow();
    delete intent.invoice_version;
    expect(
      financialObject(
        commandBody("creditApply", stringifyFinancialJson(body)).intent,
      ),
    ).toEqual(intent);
    detail.unexpected = "x";
    expect(() => captureFinancialRequest(request(body))).toThrow();
  });
});
