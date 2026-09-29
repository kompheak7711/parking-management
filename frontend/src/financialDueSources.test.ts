import { describe, expect, it } from "vitest";
import { financialObject, type FinancialObject } from "./financialContracts";
import { ExactJsonNumber, stringifyFinancialJson } from "./financialJson";
import {
  captureDueSources,
  dueSourcesCursor,
  dueSourcesQuery,
  validateDueSourcesPage,
  type DueSourcesPurpose,
} from "./financialDueSources";
import { ids } from "./test/financialFixtures";

const revision = "a".repeat(64);
const nil = "00000000-0000-0000-0000-000000000000";
const cursor = (kind = "DEBIT_ADJUSTMENT", id: string = ids.event) =>
  `${revision}:${kind}:${id}`;
function setup(purpose: DueSourcesPurpose = "allocation") {
  const input: FinancialObject = {
    operation: "financialDueSources",
    purpose,
    source_id: purpose === "allocation" ? ids.payment : ids.credit,
    invoice_id: ids.invoice,
    invoice_line_id: ids.other,
  };
  const debit: FinancialObject = {
    source_kind: "DEBIT_ADJUSTMENT",
    source_id: ids.event,
    approved_due_date: "2027-01-01",
    source_occurred_at: "2026-09-01T00:00:00.123456Z",
    remaining_usd_cents: 100,
  };
  const original: FinancialObject = {
    source_kind: "ORIGINAL_LINE",
    source_id: ids.other,
    approved_due_date: "2027-02-05",
    source_occurred_at: "2026-08-01T00:00:00Z",
    remaining_usd_cents: 200,
  };
  const data: FinancialObject = {
    property_id: ids.property,
    purpose,
    source_id: input.source_id ?? null,
    invoice_id: ids.invoice,
    invoice_line_id: ids.other,
    invoice_version: 7,
    revision,
    as_of: "2026-09-16T23:00:00+07:00",
    aggregate_outstanding_usd_cents: 300,
    item_count: 2,
    items: [debit, original],
  };
  const page: FinancialObject = { limit: 50, next_cursor: null };
  return { input, data, page, debit, original };
}
function check(f: ReturnType<typeof setup>) {
  return validateDueSourcesPage(f.data, f.page, f.input, ids.property);
}
describe("dated-source client contract", () => {
  it.each(["allocation", "credit_application"] as const)(
    "TEST-FE-1055-SOURCES-1 retains authoritative %s source facts",
    (purpose) => {
      const f = setup(purpose),
        result = check(f);
      expect(result.data).toEqual(f.data);
      expect(result.page).toEqual({ limit: 50, nextCursor: null });
      expect(result.data).not.toBe(f.data);
    },
  );
  const requestFailures = [
    "operation",
    "purpose",
    "source_missing",
    "invoice_missing",
    "line_missing",
    "source_nil",
    "invoice_nil",
    "line_nil",
    "source_object",
    "invoice_number",
    "line_null",
    "source_newline",
    "source_path",
    "extra",
    "command_key",
    "limit_zero",
    "limit_negative",
    "limit_float",
    "limit_bool",
    "limit_string",
    "limit_null",
    "limit_large",
    "limit_negative_zero",
    "cursor_null",
    "cursor_number",
    "request_oversize",
  ] as const;
  it.each(requestFailures)(
    "TEST-FE-1055-SOURCES-2 rejects invalid request %s",
    (failure) => {
      const { input } = setup();
      switch (failure) {
        case "operation":
          input.operation = "allocationPost";
          break;
        case "purpose":
          input.purpose = "refund_return";
          break;
        case "source_missing":
          delete input.source_id;
          break;
        case "invoice_missing":
          delete input.invoice_id;
          break;
        case "line_missing":
          delete input.invoice_line_id;
          break;
        case "source_nil":
          input.source_id = nil;
          break;
        case "invoice_nil":
          input.invoice_id = nil;
          break;
        case "line_nil":
          input.invoice_line_id = nil;
          break;
        case "source_object":
          input.source_id = {};
          break;
        case "invoice_number":
          input.invoice_id = 1;
          break;
        case "line_null":
          input.invoice_line_id = null;
          break;
        case "source_newline":
          input.source_id = ids.payment + "\n";
          break;
        case "source_path":
          input.source_id = "../payments";
          break;
        case "extra":
          input.target_kind = "INVOICE";
          break;
        case "command_key":
          input.idempotency_key = ids.key;
          break;
        case "limit_zero":
          input.limit = 0;
          break;
        case "limit_negative":
          input.limit = -1;
          break;
        case "limit_float":
          input.limit = 1.5;
          break;
        case "limit_bool":
          input.limit = true;
          break;
        case "limit_string":
          input.limit = "1";
          break;
        case "limit_null":
          input.limit = null;
          break;
        case "limit_large":
          input.limit = 101;
          break;
        case "limit_negative_zero":
          input.limit = -0;
          break;
        case "cursor_null":
          input.cursor = null;
          break;
        case "cursor_number":
          input.cursor = 1;
          break;
        case "request_oversize":
          input.purpose = "a".repeat(32_769);
          break;
      }
      expect(() => captureDueSources(input)).toThrow();
      expect(() => dueSourcesQuery(input)).toThrow();
    },
  );
  const cursorFailures = [
    "",
    "a".repeat(121),
    `${revision}:DEBIT_ADJUSTMENT:${nil}`,
    `${revision}:OTHER:${ids.event}`,
    `${revision}:ORIGINAL_LINE:${ids.event.toUpperCase()}`,
    `${revision.toUpperCase()}:DEBIT_ADJUSTMENT:${ids.event}`,
    `${revision.slice(1)}:DEBIT_ADJUSTMENT:${ids.event}`,
    `${revision}0:DEBIT_ADJUSTMENT:${ids.event}`,
    cursor() + "\n",
    cursor() + ":extra",
    " " + cursor(),
    cursor() + " ",
    `${revision}:DEBIT_ADJUSTMENT:../a`,
    `${revision}:DEBIT_ADJUSTMENT:${ids.event.slice(1)}`,
  ];
  it.each(cursorFailures)(
    "TEST-FE-1055-SOURCES-3 rejects malformed cursor %s",
    (value) => {
      expect(() => dueSourcesCursor(value)).toThrow();
      expect(() =>
        captureDueSources({ ...setup().input, cursor: value }),
      ).toThrow();
    },
  );
  it.each([1, 2, 100])(
    "TEST-FE-1055-SOURCES-4 verifies first-page limit %s and continuation",
    (limit) => {
      const f = setup();
      f.input.limit = limit;
      f.page.limit = limit;
      if (limit === 1) {
        f.data.items = [f.debit];
        f.page.next_cursor = cursor();
      }
      expect(check(f).page).toEqual({
        limit,
        nextCursor: limit === 1 ? cursor() : null,
      });
    },
  );
  it.each([false, true])(
    "TEST-FE-1055-SOURCES-5 verifies final continuation empty=%s",
    (empty) => {
      const f = setup();
      f.input.cursor = empty ? cursor("ORIGINAL_LINE", ids.other) : cursor();
      f.data.items = empty ? [] : [f.original];
      expect(check(f).page.nextCursor).toBeNull();
    },
  );
  const responseFailures = [
    "property",
    "purpose",
    "source",
    "invoice",
    "line",
    "uppercase_id",
    "id_newline",
    "extra",
    "missing",
    "version_zero",
    "version_large",
    "version_bool",
    "version_float",
    "revision_short",
    "revision_newline",
    "revision_changed",
    "naive_asof",
    "invalid_asof",
    "asof_newline",
    "aggregate_negative",
    "aggregate_overflow",
    "aggregate_decimal",
    "aggregate_unsafe",
    "aggregate_bool",
    "count_negative",
    "count_float",
    "count_bool",
    "count_overflow",
    "count_exceeds_money",
    "count_zero",
    "wrong_sum",
    "items_missing",
    "items_object",
    "items_short",
    "items_long",
    "page_limit",
    "page_extra",
    "page_missing",
    "cursor_missing",
    "cursor_wrong_last",
    "cursor_wrong_revision",
    "cursor_unneeded",
    "anchor_repeated",
    "continuation_count",
    "continuation_more_count",
    "row_extra",
    "row_missing",
    "row_kind",
    "row_identity",
    "original_identity",
    "duplicate_source",
    "date_invalid",
    "date_unpadded",
    "date_newline",
    "time_naive",
    "time_invalid",
    "time_future",
    "time_newline",
    "remaining_zero",
    "remaining_negative",
    "remaining_bool",
    "remaining_float",
    "remaining_overflow",
  ] as const;
  it.each(responseFailures)(
    "TEST-FE-1055-SOURCES-6 rejects malformed or inconsistent page %s",
    (failure) => {
      const f = setup(),
        { input, data, page, debit, original } = f;
      switch (failure) {
        case "property":
          data.property_id = ids.other;
          break;
        case "purpose":
          data.purpose = "credit_application";
          break;
        case "source":
          data.source_id = ids.credit;
          break;
        case "invoice":
          data.invoice_id = ids.other;
          break;
        case "line":
          data.invoice_line_id = ids.invoice;
          break;
        case "uppercase_id":
          data.invoice_id = ids.invoice.toUpperCase();
          break;
        case "id_newline":
          data.invoice_id = ids.invoice + "\n";
          break;
        case "extra":
          data.has_more = false;
          break;
        case "missing":
          delete data.revision;
          break;
        case "version_zero":
          data.invoice_version = 0;
          break;
        case "version_large":
          data.invoice_version = 10000000000n;
          break;
        case "version_bool":
          data.invoice_version = true;
          break;
        case "version_float":
          data.invoice_version = 1.5;
          break;
        case "revision_short":
          data.revision = revision.slice(1);
          break;
        case "revision_newline":
          data.revision = revision + "\n";
          break;
        case "revision_changed":
          input.cursor = cursor();
          data.items = [original];
          data.revision = "b".repeat(64);
          break;
        case "naive_asof":
          data.as_of = "2026-09-16T23:00:00";
          break;
        case "invalid_asof":
          data.as_of = "2026-02-30T00:00:00Z";
          break;
        case "asof_newline":
          data.as_of = "2026-09-16T00:00:00Z\n";
          break;
        case "aggregate_negative":
          data.aggregate_outstanding_usd_cents = -1;
          break;
        case "aggregate_overflow":
          data.aggregate_outstanding_usd_cents = 9223372036854775808n;
          break;
        case "aggregate_decimal":
          data.aggregate_outstanding_usd_cents = new ExactJsonNumber("300.0");
          break;
        case "aggregate_unsafe":
          data.aggregate_outstanding_usd_cents = Number.MAX_SAFE_INTEGER + 1;
          break;
        case "aggregate_bool":
          data.aggregate_outstanding_usd_cents = true;
          break;
        case "count_negative":
          data.item_count = -1;
          break;
        case "count_float":
          data.item_count = 2.5;
          break;
        case "count_bool":
          data.item_count = true;
          break;
        case "count_overflow":
          data.item_count = 9223372036854775808n;
          break;
        case "count_exceeds_money":
          data.item_count = 301;
          break;
        case "count_zero":
          data.item_count = 0;
          break;
        case "wrong_sum":
          data.aggregate_outstanding_usd_cents = 301;
          break;
        case "items_missing":
          delete data.items;
          break;
        case "items_object":
          data.items = {};
          break;
        case "items_short":
          data.items = [debit];
          break;
        case "items_long":
          input.limit = 1;
          page.limit = 1;
          page.next_cursor = cursor();
          break;
        case "page_limit":
          page.limit = 49;
          break;
        case "page_extra":
          page.total = 2;
          break;
        case "page_missing":
          delete page.limit;
          break;
        case "cursor_missing":
          input.limit = 1;
          page.limit = 1;
          data.items = [debit];
          break;
        case "cursor_wrong_last":
          input.limit = 1;
          page.limit = 1;
          data.items = [debit];
          page.next_cursor = cursor("ORIGINAL_LINE", ids.other);
          break;
        case "cursor_wrong_revision":
          input.limit = 1;
          page.limit = 1;
          data.items = [debit];
          page.next_cursor = cursor().replace(revision, "b".repeat(64));
          break;
        case "cursor_unneeded":
          page.next_cursor = cursor("ORIGINAL_LINE", ids.other);
          break;
        case "anchor_repeated":
          input.cursor = cursor();
          data.items = [debit];
          break;
        case "continuation_count":
          input.cursor = cursor();
          break;
        case "continuation_more_count":
          input.cursor = cursor();
          input.limit = 1;
          page.limit = 1;
          data.items = [original];
          page.next_cursor = cursor("ORIGINAL_LINE", ids.other);
          break;
        case "row_extra":
          debit.memo = "unrelated";
          break;
        case "row_missing":
          delete debit.remaining_usd_cents;
          break;
        case "row_kind":
          debit.source_kind = "PAYMENT";
          break;
        case "row_identity":
          debit.source_id = nil;
          break;
        case "original_identity":
          original.source_id = ids.event;
          break;
        case "duplicate_source":
          data.items = [
            debit,
            {
              ...debit,
              approved_due_date: "2027-02-05",
              remaining_usd_cents: 200,
            },
          ];
          break;
        case "date_invalid":
          debit.approved_due_date = "2027-02-29";
          break;
        case "date_unpadded":
          debit.approved_due_date = "2027-1-01";
          break;
        case "date_newline":
          debit.approved_due_date = "2027-01-01\n";
          break;
        case "time_naive":
          debit.source_occurred_at = "2026-09-01T00:00:00";
          break;
        case "time_invalid":
          debit.source_occurred_at = "2026-09-01T24:00:00Z";
          break;
        case "time_future":
          debit.source_occurred_at = "2026-09-17T00:00:00Z";
          break;
        case "time_newline":
          debit.source_occurred_at = "2026-09-01T00:00:00Z\n";
          break;
        case "remaining_zero":
          debit.remaining_usd_cents = 0;
          break;
        case "remaining_negative":
          debit.remaining_usd_cents = -1;
          break;
        case "remaining_bool":
          debit.remaining_usd_cents = true;
          break;
        case "remaining_float":
          debit.remaining_usd_cents = 1.5;
          break;
        case "remaining_overflow":
          debit.remaining_usd_cents = 9223372036854775808n;
          break;
      }
      expect(() => check(f)).toThrow();
    },
  );
  it.each(["date", "microsecond", "offset", "kind", "identity"] as const)(
    "TEST-FE-1055-SOURCES-7 enforces full source ordering by %s",
    (axis) => {
      const f = setup(),
        { debit, original } = f;
      if (axis !== "date") {
        original.approved_due_date = debit.approved_due_date ?? null;
        original.source_occurred_at = debit.source_occurred_at ?? null;
      }
      if (axis === "microsecond")
        original.source_occurred_at = "2026-09-01T00:00:00.123457Z";
      if (axis === "offset")
        original.source_occurred_at = "2026-08-31T19:00:00.123457-05:00";
      if (axis === "identity") original.source_kind = "DEBIT_ADJUSTMENT";
      expect(() => check(f)).not.toThrow();
      f.data.items = [original, debit];
      expect(() => check(f)).toThrow();
    },
  );
  it.each([100, 101])(
    "TEST-FE-1055-SOURCES-8 enforces bounded page size %s",
    (count) => {
      const f = setup();
      f.input.limit = 100;
      f.page.limit = 100;
      f.data.items = Array.from({ length: count }, (_, index) => ({
        ...f.debit,
        source_id: `00000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
        remaining_usd_cents: 1,
      }));
      f.data.item_count = count;
      f.data.aggregate_outstanding_usd_cents = count;
      if (count === 100) expect(() => check(f)).not.toThrow();
      else expect(() => check(f)).toThrow();
    },
  );
  it("TEST-FE-1055-SOURCES-9 captures detached inputs and outputs", () => {
    const f = setup();
    f.input.invoice_id = ids.invoice.toUpperCase();
    const captured = captureDueSources(f.input);
    expect(captured.invoice_id).toBe(ids.invoice);
    f.input.invoice_id = ids.other;
    expect(captured.invoice_id).toBe(ids.invoice);
    f.input = captured;
    const reply = check(f);
    f.debit.remaining_usd_cents = 999;
    expect(stringifyFinancialJson(reply.data)).not.toContain("999");
    expect(
      financialObject((reply.data.items as FinancialObject[])[0])
        .remaining_usd_cents,
    ).toBe(100);
  });
  it("TEST-FE-1055-SOURCES-10 preserves exact BIGINT balances and maximum version", () => {
    const f = setup(),
      maximum = 9223372036854775807n;
    f.debit.remaining_usd_cents = maximum - 200n;
    f.data.aggregate_outstanding_usd_cents = maximum;
    f.data.invoice_version = 9999999999;
    const result = check(f);
    expect(result.data.aggregate_outstanding_usd_cents).toBe(maximum);
    expect(stringifyFinancialJson(result.data)).toContain(
      "9223372036854775807",
    );
  });
  it("TEST-FE-1055-SOURCES-11 builds only finite read query fields", () => {
    const f = setup();
    f.input.limit = 1;
    f.input.cursor = cursor();
    expect(Object.fromEntries(dueSourcesQuery(f.input))).toEqual({
      purpose: "allocation",
      source_id: ids.payment,
      invoice_id: ids.invoice,
      invoice_line_id: ids.other,
      limit: "1",
      cursor: cursor(),
    });
    expect(dueSourcesCursor(cursor("ORIGINAL_LINE", ids.other))).toEqual({
      revision,
      kind: "ORIGINAL_LINE",
      id: ids.other,
    });
  });
  it.each(["zero", "data_budget", "page_budget"] as const)(
    "TEST-FE-1055-SOURCES-12 enforces complete zero balance and byte bounds %s",
    (mode) => {
      const f = setup();
      if (mode === "zero") {
        f.data.items = [];
        f.data.item_count = 0;
        f.data.aggregate_outstanding_usd_cents = 0;
        expect(check(f).data.items).toEqual([]);
        f.input.cursor = cursor();
        expect(() => check(f)).toThrow();
      } else {
        if (mode === "data_budget") f.data.revision = "a".repeat(100_001);
        else f.page.next_cursor = "a".repeat(1025);
        expect(() => check(f)).toThrow();
      }
    },
  );
});
