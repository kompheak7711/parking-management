import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FinancialDueSourcePicker } from "./FinancialDueSourcePicker";
import { type FinancialScope } from "./financialClient";
import { invalidFinancial } from "./financialContracts";
import {
  type DueSourcesPurpose,
  type FinancialDueSourcesInput,
} from "./financialDueSources";
import { type FinancialDueSelection } from "./financialDueSelection";
import { stringifyFinancialJson } from "./financialJson";
import { createFinancialReferenceClient } from "./financialReferenceClient";
import { ids } from "./test/financialFixtures";

const revision = "a".repeat(64);
const identity = (index: number) =>
  `00000000-0000-4000-8000-${index.toString(16).padStart(12, "0")}`;
const sourceKey = (index: number) => `DEBIT_ADJUSTMENT:${identity(index)}`;
const inputFor = (index: number) =>
  screen.getByLabelText(`Selected USD for dated source ${sourceKey(index)}`);
function harness(count = 2, purpose: DueSourcesPurpose = "allocation") {
  const controller = new AbortController();
  const scope: FinancialScope = {
    actorId: ids.actor,
    propertyId: ids.property,
    signal: controller.signal,
  };
  const input: FinancialDueSourcesInput = {
    operation: "financialDueSources",
    purpose,
    source_id: purpose === "allocation" ? ids.payment : ids.credit,
    invoice_id: ids.invoice,
    invoice_line_id: ids.other,
    limit: 50,
  };
  let status = 200;
  const fetcher = vi.fn<typeof fetch>((url, init) => {
    const parsed = new URL(
        typeof url === "string" ? url : invalidFinancial(),
        "http://localhost",
      ),
      query = parsed.searchParams,
      anchor = query.get("cursor"),
      offset = anchor === null ? 0 : Number.parseInt(anchor.slice(-12), 16),
      limit = Number(query.get("limit") ?? 50);
    const headers = new Headers(init?.headers),
      requestId = headers.get("X-Request-ID") ?? invalidFinancial(),
      actor = headers.get("X-Billing-Actor-ID") ?? invalidFinancial(),
      property = headers.get("X-Financial-Property-ID") ?? invalidFinancial();
    const length = Math.min(limit, count - offset);
    const items = Array.from({ length }, (_, index) => ({
      source_kind: "DEBIT_ADJUSTMENT",
      source_id: identity(offset + index + 1),
      approved_due_date: "2027-01-01",
      source_occurred_at: "2026-08-01T01:02:03.123456Z",
      remaining_usd_cents: 100,
    }));
    const body = {
      data: {
        property_id: property,
        purpose: query.get("purpose"),
        source_id: query.get("source_id"),
        invoice_id: query.get("invoice_id"),
        invoice_line_id: query.get("invoice_line_id"),
        invoice_version: 7,
        revision,
        as_of: "2026-09-16T00:00:00Z",
        aggregate_outstanding_usd_cents: count * 100,
        item_count: count,
        items,
      },
      page: {
        limit,
        next_cursor:
          offset + length < count
            ? `${revision}:DEBIT_ADJUSTMENT:${identity(offset + length)}`
            : null,
      },
      meta: { actor_id: actor, property_id: property, request_id: requestId },
    };
    return Promise.resolve(
      new Response(stringifyFinancialJson(body, 1_048_576), {
        status,
        headers: {
          "Content-Type": "application/json",
          "X-Request-ID": requestId,
        },
      }),
    );
  });
  const props = {
    scope,
    input,
    references: createFinancialReferenceClient(fetcher),
    onDirty: vi.fn<() => void>(),
    onApply: vi.fn<(selection: FinancialDueSelection) => void>(),
    onDiscard: vi.fn<() => void>(),
  };
  return {
    props,
    fetcher,
    controller,
    setStatus: (value: number) => {
      status = value;
    },
  };
}
async function load() {
  fireEvent.click(
    screen.getByRole("button", { name: "Load approved dated amounts" }),
  );
  return await screen.findByRole("table", { name: /Available dated sources/ });
}
function apply() {
  fireEvent.click(
    screen.getByRole("button", { name: "Use selected dated amounts" }),
  );
}
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
describe("explicit dated-source picker", () => {
  it.each(["allocation", "credit_application"] as const)(
    "TEST-FE-1055-DUE-PICKER-1 selects %s facts without posting",
    async (purpose) => {
      const h = harness(2, purpose);
      render(<FinancialDueSourcePicker {...h.props} />);
      await load();
      expect(screen.getAllByText("2027-01-01")).toHaveLength(2);
      expect(screen.getAllByText("2026-08-01 01:02:03.123456Z")).toHaveLength(
        2,
      );
      fireEvent.change(inputFor(1), { target: { value: "0.40" } });
      fireEvent.change(inputFor(2), { target: { value: "0.60" } });
      apply();
      expect(h.props.onApply).toHaveBeenCalledWith({
        amount: 100n,
        parts: [
          {
            source_kind: "DEBIT_ADJUSTMENT",
            source_id: identity(1),
            amount_usd_cents: 40n,
          },
          {
            source_kind: "DEBIT_ADJUSTMENT",
            source_id: identity(2),
            amount_usd_cents: 60n,
          },
        ],
      });
      expect(h.props.onDirty).toHaveBeenCalledTimes(2);
      expect(h.fetcher).toHaveBeenCalledTimes(1);
      expect(
        h.fetcher.mock.calls.every(([, init]) => init?.method === "GET"),
      ).toBe(true);
    },
  );
  it("TEST-FE-1055-DUE-PICKER-1 withholds apply until complete facts load", () => {
    const h = harness();
    render(<FinancialDueSourcePicker {...h.props} />);
    expect(
      screen.getByRole("button", { name: "Use selected dated amounts" }),
    ).toBeDisabled();
    expect(h.fetcher).not.toHaveBeenCalled();
    expect(h.props.onApply).not.toHaveBeenCalled();
  });
  it.each(["2.00", "-1", "0"])(
    "TEST-FE-1055-DUE-PICKER-2 rejects selected amount %s without losing the edit",
    async (amount) => {
      const h = harness();
      render(<FinancialDueSourcePicker {...h.props} />);
      await load();
      fireEvent.change(inputFor(1), { target: { value: amount } });
      apply();
      expect(screen.getByRole("alert")).toBeInTheDocument();
      expect(inputFor(1)).toHaveValue(amount);
      expect(h.props.onApply).not.toHaveBeenCalled();
    },
  );
  it("TEST-FE-1055-DUE-PICKER-3 discards local edits without applying them", async () => {
    const h = harness();
    render(<FinancialDueSourcePicker {...h.props} />);
    await load();
    fireEvent.change(inputFor(1), { target: { value: "0.50" } });
    fireEvent.click(
      screen.getByRole("button", { name: "Discard source edits" }),
    );
    expect(h.props.onDiscard).toHaveBeenCalledTimes(1);
    expect(h.props.onApply).not.toHaveBeenCalled();
  });
  it("TEST-FE-1055-DUE-PICKER-3 clears only after an explicit clear action and preserves supplied selection", async () => {
    const h = harness(),
      initial: FinancialDueSelection = {
        amount: 50n,
        parts: [
          {
            source_kind: "DEBIT_ADJUSTMENT",
            source_id: identity(1),
            amount_usd_cents: 50n,
          },
        ],
      },
      before = stringifyFinancialJson(initial);
    render(<FinancialDueSourcePicker {...h.props} initial={initial} />);
    await load();
    expect(inputFor(1)).toHaveValue("0.50");
    fireEvent.click(
      screen.getByRole("button", { name: "Clear dated selections" }),
    );
    expect(inputFor(1)).toHaveValue("");
    expect(h.props.onDirty).toHaveBeenCalledTimes(1);
    expect(stringifyFinancialJson(initial)).toBe(before);
    apply();
    expect(h.props.onApply).not.toHaveBeenCalled();
  });
  it.each(["actor", "property", "source"])(
    "TEST-FE-1055-DUE-PICKER-4 hides stale facts and drafts after %s changes",
    async (field) => {
      const h = harness(),
        view = render(<FinancialDueSourcePicker {...h.props} />);
      await load();
      fireEvent.change(inputFor(1), { target: { value: "0.50" } });
      const scope = { ...h.props.scope },
        input = { ...h.props.input };
      if (field === "actor") scope.actorId = ids.customer;
      if (field === "property") scope.propertyId = ids.customer;
      if (field === "source") input.source_id = ids.credit;
      view.rerender(
        <FinancialDueSourcePicker {...h.props} scope={scope} input={input} />,
      );
      expect(screen.queryByRole("table")).not.toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Use selected dated amounts" }),
      ).toBeDisabled();
      await load();
      expect(inputFor(1)).toHaveValue("");
      expect(h.props.onApply).not.toHaveBeenCalled();
    },
  );
  it("TEST-FE-1055-DUE-PICKER-5 refuses apply after the signal aborts without changed props", async () => {
    const h = harness();
    render(<FinancialDueSourcePicker {...h.props} />);
    await load();
    fireEvent.change(inputFor(1), { target: { value: "0.50" } });
    act(() => {
      h.controller.abort();
    });
    apply();
    expect(h.props.onApply).not.toHaveBeenCalled();
  });
  it("TEST-FE-1055-DUE-PICKER-5 discards an outstanding read on workspace cancellation", async () => {
    const h = harness();
    let release: () => void = () => {
      throw new Error("Gate not prepared");
    };
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const references = {
      read: async (...args: Parameters<typeof h.props.references.read>) => {
        await gate;
        return h.props.references.read(...args);
      },
    };
    render(<FinancialDueSourcePicker {...h.props} references={references} />);
    fireEvent.click(
      screen.getByRole("button", { name: "Load approved dated amounts" }),
    );
    await act(async () => {
      h.controller.abort();
      release();
      await gate;
    });
    await waitFor(() => {
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    });
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(h.fetcher).not.toHaveBeenCalled();
    expect(h.props.onApply).not.toHaveBeenCalled();
  });
  it.each([409, 503])(
    "TEST-FE-1055-DUE-PICKER-6 surfaces read status %s without retry or partial selection",
    async (status) => {
      const h = harness();
      h.setStatus(status);
      render(<FinancialDueSourcePicker {...h.props} />);
      fireEvent.click(
        screen.getByRole("button", { name: "Load approved dated amounts" }),
      );
      await screen.findByRole("alert");
      expect(h.fetcher).toHaveBeenCalledTimes(1);
      expect(screen.queryByRole("table")).not.toBeInTheDocument();
      expect(h.props.onApply).not.toHaveBeenCalled();
    },
  );
  it("TEST-FE-1055-DUE-PICKER-7 retains selections across display pages after a complete read", async () => {
    const h = harness(51);
    render(<FinancialDueSourcePicker {...h.props} />);
    await load();
    expect(h.fetcher).toHaveBeenCalledTimes(2);
    fireEvent.change(inputFor(1), { target: { value: "0.25" } });
    fireEvent.click(screen.getByRole("button", { name: "Next dated sources" }));
    fireEvent.change(inputFor(51), { target: { value: "0.75" } });
    fireEvent.click(
      screen.getByRole("button", { name: "Previous dated sources" }),
    );
    expect(inputFor(1)).toHaveValue("0.25");
    apply();
    expect(h.props.onApply).toHaveBeenCalledWith({
      amount: 100n,
      parts: [
        {
          source_kind: "DEBIT_ADJUSTMENT",
          source_id: identity(1),
          amount_usd_cents: 25n,
        },
        {
          source_kind: "DEBIT_ADJUSTMENT",
          source_id: identity(51),
          amount_usd_cents: 75n,
        },
      ],
    });
  });
  it("TEST-FE-1055-DUE-PICKER-6 withholds stale facts after a failed explicit reload", async () => {
    const h = harness();
    render(<FinancialDueSourcePicker {...h.props} />);
    await load();
    fireEvent.change(inputFor(1), { target: { value: "0.50" } });
    h.setStatus(409);
    fireEvent.click(
      screen.getByRole("button", { name: "Load approved dated amounts" }),
    );
    await screen.findByRole("alert");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Use selected dated amounts" }),
    ).toBeDisabled();
    expect(h.props.onApply).not.toHaveBeenCalled();
  });
  it("TEST-FE-1055-DUE-PICKER-8 retains edits when the parent rejects the combined selection", async () => {
    const h = harness();
    h.props.onApply.mockImplementation(() => {
      throw new Error("Combined selection rejected");
    });
    render(<FinancialDueSourcePicker {...h.props} />);
    await load();
    fireEvent.change(inputFor(1), { target: { value: "0.50" } });
    apply();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(inputFor(1)).toHaveValue("0.50");
    expect(h.props.onDiscard).not.toHaveBeenCalled();
  });
  it("TEST-FE-1055-DUE-PICKER-8 never silently replaces an unavailable explicit source", async () => {
    const h = harness(),
      initial: FinancialDueSelection = {
        amount: 50n,
        parts: [
          {
            source_kind: "DEBIT_ADJUSTMENT",
            source_id: identity(99),
            amount_usd_cents: 50n,
          },
        ],
      };
    render(<FinancialDueSourcePicker {...h.props} initial={initial} />);
    await load();
    apply();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(h.props.onApply).not.toHaveBeenCalled();
    expect(initial.parts[0]?.source_id).toBe(identity(99));
  });
});
