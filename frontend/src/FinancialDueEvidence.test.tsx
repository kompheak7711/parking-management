import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import {
  FinancialCommandEvidence,
  FinancialProposalEvidence,
} from "./FinancialEvidence";
import {
  financialInteger,
  financialObject,
  type FinancialObject,
} from "./financialContracts";
import { stringifyFinancialJson } from "./financialJson";
import { ids } from "./test/financialFixtures";

function detail(basis = "EARLIEST_DUE"): FinancialObject {
  return {
    invoice_line_id: ids.other,
    amount_usd_cents: 100,
    due_attribution: {
      basis,
      parts: [
        {
          source_kind: "DEBIT_ADJUSTMENT",
          source_id: ids.event,
          approved_due_date: "2026-09-01",
          source_occurred_at: "2026-08-01T01:02:03.456789+07:00",
          outstanding_usd_cents: 9223372036854775807n,
          amount_usd_cents: 40,
        },
        {
          source_kind: "ORIGINAL_LINE",
          source_id: ids.other,
          approved_due_date: "2026-09-10",
          source_occurred_at: "2026-07-01T00:00:00Z",
          outstanding_usd_cents: 100,
          amount_usd_cents: 60,
        },
      ],
    },
  };
}
function command(kind: "PAYMENT" | "CREDIT", line = detail()) {
  const target = {
    invoice_id: ids.invoice,
    invoice_version: 7,
    amount_usd_cents: financialInteger(line.amount_usd_cents, 1n),
    details: [line],
  };
  const body: FinancialObject =
    kind === "CREDIT"
      ? {
          currency: "USD",
          intent: {
            mode: "DESIGNATED",
            ...target,
            designation_reference: "Synthetic customer choice",
          },
        }
      : {
          intent: {
            mode: "DESIGNATED",
            targets: [target],
            designation_reference: "Synthetic customer choice",
          },
        };
  return {
    operation:
      kind === "CREDIT"
        ? ("creditApply" as const)
        : ("allocationPost" as const),
    target: { id: kind === "CREDIT" ? ids.credit : ids.payment },
    body,
  };
}
function proposal(
  kind: "PAYMENT" | "CREDIT",
  line = detail(),
): FinancialObject {
  const shared = {
    generated_at: "2026-09-16T00:00:00Z",
    available_usd_cents: 100,
    policy: "Synthetic preserved order",
    continuation_status: "COMPLETE",
  };
  return kind === "CREDIT"
    ? {
        ...shared,
        credit_id: ids.credit,
        invoice_id: ids.invoice,
        invoice_version: 7,
        requested_amount_usd_cents: 100,
        amount_usd_cents: 100,
        remaining_requested_usd_cents: 0,
        details: [line],
      }
    : {
        ...shared,
        payment_id: ids.payment,
        proposal_batch_id: ids.key,
        payment_scope: "CUSTOMER",
        designation_reference: null,
        unallocated_after_usd_cents: 0,
        targets: [
          {
            invoice_id: ids.invoice,
            invoice_number: "SYNTHETIC-1",
            target_customer_id: ids.customer,
            sequence: 1,
            due_date: "2026-09-10",
            issued_at: "2026-07-01T00:00:00Z",
            version: 7,
            amount_usd_cents: 100,
            details: [line],
          },
        ],
      };
}
const region = () =>
  screen.getByRole("region", {
    name: `Dated amounts for Invoice line ${ids.other}`,
  });
afterEach(() => {
  cleanup();
});

describe("exact dated confirmation evidence", () => {
  it.each([
    ["PAYMENT", "EARLIEST_DUE"],
    ["PAYMENT", "CUSTOMER_DESIGNATED"],
    ["CREDIT", "EARLIEST_DUE"],
    ["CREDIT", "CUSTOMER_DESIGNATED"],
  ] as const)(
    "TEST-FE-1055-DUE-EVIDENCE-1 renders %s %s without changing captured facts",
    (kind, basis) => {
      const request = command(kind, detail(basis)),
        before = stringifyFinancialJson(request.body);
      render(<FinancialCommandEvidence request={request} />);
      const evidence = region(),
        rows = within(evidence).getAllByRole("row");
      expect(rows).toHaveLength(3);
      expect(rows[1]).toHaveTextContent("Debit Adjustment");
      expect(rows[1]).toHaveTextContent(ids.event);
      expect(rows[1]).toHaveTextContent("2026-09-01");
      expect(rows[2]).toHaveTextContent("Original Invoice line");
      expect(rows[2]).toHaveTextContent(ids.other);
      expect(rows[2]).toHaveTextContent("2026-09-10");
      expect(evidence).toHaveTextContent(
        basis === "EARLIEST_DUE"
          ? "Earliest approved due date within this line"
          : "Customer-designated dated amounts",
      );
      expect(evidence).toHaveTextContent("Outstanding at confirmation preview");
      expect(stringifyFinancialJson(request.body)).toBe(before);
    },
  );
  it.each([
    ["PAYMENT", false],
    ["PAYMENT", true],
    ["CREDIT", false],
    ["CREDIT", true],
  ] as const)(
    "TEST-FE-1055-DUE-EVIDENCE-2 renders %s recorded=%s dated proposals",
    (kind, recorded) => {
      const value = proposal(kind),
        before = stringifyFinancialJson(value);
      render(<FinancialProposalEvidence value={value} recorded={recorded} />);
      expect(region()).toHaveTextContent("Outstanding at proposal");
      expect(region()).toHaveTextContent("2026-09-01");
      expect(stringifyFinancialJson(value)).toBe(before);
      if (recorded)
        expect(screen.getByText(/saved at proposal time/)).toBeInTheDocument();
      else
        expect(
          screen.getByText(/Confirmation posts only the displayed batch/),
        ).toBeInTheDocument();
    },
  );
  it.each(["PAYMENT", "CREDIT"] as const)(
    "TEST-FE-1055-DUE-EVIDENCE-3 preserves legacy %s lines without inventing dates",
    (kind) => {
      const legacy = { invoice_line_id: ids.other, amount_usd_cents: 100 };
      render(<FinancialCommandEvidence request={command(kind, legacy)} />);
      expect(
        screen.queryByRole("region", {
          name: /Dated amounts for Invoice line/,
        }),
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole("table", { name: "Exact selected line amounts" }),
      ).toHaveTextContent(ids.other);
      expect(screen.queryByText("2026-09-01")).not.toBeInTheDocument();
    },
  );
  it("TEST-FE-1055-DUE-EVIDENCE-4 preserves exact large balances and selected cents", () => {
    render(<FinancialCommandEvidence request={command("CREDIT")} />);
    const evidence = region();
    expect(evidence).toHaveTextContent("92,233,720,368,547,758.07");
    expect(evidence).toHaveTextContent("0.40");
    expect(evidence).toHaveTextContent("0.60");
  });
  it("TEST-FE-1055-DUE-EVIDENCE-5 displays unavailable evidence without inferring a basis or dates", () => {
    const line = detail();
    line.due_attribution = {};
    render(<FinancialCommandEvidence request={command("PAYMENT", line)} />);
    expect(region()).toHaveTextContent("Dated allocation basis unavailable");
    expect(region()).toHaveTextContent("Dated source evidence unavailable.");
    expect(within(region()).queryByRole("table")).not.toBeInTheDocument();
  });
  it("TEST-FE-1055-DUE-EVIDENCE-6 preserves approved calendar dates and timestamp precision", () => {
    render(<FinancialCommandEvidence request={command("PAYMENT")} />);
    expect(region()).toHaveTextContent("2026-08-01 01:02:03.456789+07:00");
    expect(region()).toHaveTextContent("2026-09-01");
    expect(region()).toHaveTextContent("2026-09-10");
  });
  it("TEST-FE-1055-DUE-EVIDENCE-7 displays every permitted part without truncating", () => {
    const line = detail(),
      due = financialObject(line.due_attribution);
    due.parts = Array.from({ length: 500 }, (_, index) => ({
      source_kind: "DEBIT_ADJUSTMENT",
      source_id: `00000000-0000-4000-8000-${(index + 1).toString().padStart(12, "0")}`,
      approved_due_date: "2026-09-01",
      source_occurred_at: "2026-08-01T00:00:00Z",
      outstanding_usd_cents: 1,
      amount_usd_cents: 1,
    }));
    line.amount_usd_cents = 500;
    render(<FinancialCommandEvidence request={command("CREDIT", line)} />);
    expect(within(region()).getAllByRole("row")).toHaveLength(501);
    expect(region()).toHaveTextContent("00000000-0000-4000-8000-000000000500");
  });
});
