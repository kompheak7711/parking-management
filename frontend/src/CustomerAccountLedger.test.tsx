import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CustomerAccountLedger } from "./CustomerAccountLedger";
import {
  createCustomerLedgerClient,
  LEDGER_EVENTS,
  type CustomerLedgerApi,
  type LedgerReply,
} from "./customerLedgerClient";
import {
  ledgerRequestUrl,
  ledgerVoidScenario,
  ledgerComposition,
  ledgerEvent,
  ledgerKhrScenario,
  ledgerId,
  ledgerIds,
  ledgerPosition,
  syntheticLedgerResponse,
  type SyntheticLedger,
} from "./customerLedgerFixtures";
function setup(state: SyntheticLedger = {}) {
  const fetcher = vi.fn<typeof fetch>((url, init) =>
    Promise.resolve(
      syntheticLedgerResponse(ledgerRequestUrl(url), init ?? {}, state),
    ),
  );
  return { state, fetcher, api: createCustomerLedgerClient(fetcher) };
}
const selected = {
  customerId: ledgerIds.customer,
  propertyId: ledgerIds.property,
  sequence: 1,
};
async function account() {
  return screen.findByRole("heading", { name: "Account: Synthetic Customer" });
}
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
describe("Customer account ledger", () => {
  it("TEST-FE-562 opens the separate ledger picker only on request and never sends commands or persists financial data", async () => {
    const { api, fetcher } = setup(),
      writeLocal = vi.spyOn(Storage.prototype, "setItem");
    render(<CustomerAccountLedger actorId={ledgerIds.actor} api={api} />);
    expect(fetcher).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "Open Customer account ledger" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Synthetic Customer" }),
    );
    await account();
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(writeLocal).not.toHaveBeenCalled();
    for (const [, init] of fetcher.mock.calls) {
      expect(init?.method).toBe("GET");
      expect(init?.body).toBeUndefined();
    }
    expect(location.search).toBe("");
    expect(location.hash).toBe("");
  });
  it("TEST-FE-563 shows the canonical $510 charge, $300 application, separate $21 Charge and $231 owed with Rent/Service composition", async () => {
    const { api } = setup({
      composition: [
        ledgerComposition(),
        ledgerComposition(2),
        ledgerComposition(3, {
          balance_kind: "LATE_PAYMENT_CHARGE",
          balance_source_id: ledgerIds.other,
          invoice_id: null,
          invoice_line_id: null,
          late_payment_charge_id: ledgerIds.other,
          category: null,
          description: "Separate Late-payment Charge",
          balance_usd_cents: "2100",
          detail_key: `LATE_PAYMENT_CHARGE:${ledgerIds.other}`,
        }),
      ],
    });
    render(
      <CustomerAccountLedger
        actorId={ledgerIds.actor}
        api={api}
        requested={selected}
      />,
    );
    await account();
    const totals = screen.getByText("Current amount owed").closest("div");
    expect(totals).toHaveTextContent("$231.00");
    for (const label of [
      "Invoice outstanding",
      "Late-payment Charges outstanding",
      "Available Customer Credit",
      "Unallocated Payment",
      "Security Deposit held",
      "Pet Deposit held",
    ])
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    const table = screen.getByRole("table", {
      name: /Chronological financial history/,
    });
    expect(table).toHaveTextContent("$510.00");
    expect(table).toHaveTextContent("$300.00");
    expect(table).toHaveTextContent("$21.00");
    fireEvent.click(
      screen.getByRole("button", { name: "Balance composition" }),
    );
    const composition = await screen.findByRole("table", {
      name: /Remaining balance composition/,
    });
    expect(composition).toHaveTextContent("July Rent");
    expect(composition).toHaveTextContent("Trash Collection");
    expect(composition).toHaveTextContent("$200.00");
    expect(composition).toHaveTextContent("$10.00");
    expect(composition).toHaveTextContent("$21.00");
  });
  it("TEST-FE-564 displays all23 operational event kinds and separate reversal records", async () => {
    const events = Object.keys(LEDGER_EVENTS).map((kind, index) =>
      ledgerEvent(kind as keyof typeof LEDGER_EVENTS, index + 1),
    );
    const { api } = setup({ events });
    render(
      <CustomerAccountLedger
        actorId={ledgerIds.actor}
        api={api}
        requested={selected}
      />,
    );
    await account();
    const history = screen.getByRole("table", {
      name: /Chronological financial history/,
    });
    for (const [, label] of Object.values(LEDGER_EVENTS))
      expect(within(history).getByText(label)).toBeInTheDocument();
    expect(within(history).getAllByRole("row")).toHaveLength(24);
    expect(screen.getByText(/Events at the same instant/)).toBeInTheDocument();
  });
  it("TEST-FE-565 retains original KHR and FX evidence with accessible source navigation and focus return", async () => {
    const { api } = setup(ledgerKhrScenario());
    render(
      <CustomerAccountLedger
        actorId={ledgerIds.actor}
        api={api}
        requested={selected}
      />,
    );
    await account();
    const source = screen.getByRole("button", {
      name: "View source: SYNTHETIC-1",
    });
    source.focus();
    fireEvent.click(source);
    expect(
      await screen.findByRole("heading", {
        name: "Source details: Payment received",
      }),
    ).toHaveFocus();
    expect(screen.getByText("KHR")).toBeInTheDocument();
    expect(screen.getByText("408300")).toBeInTheDocument();
    expect(screen.getByText("4062.000000")).toBeInTheDocument();
    expect(screen.getByText("4083.000000")).toBeInTheDocument();
    await screen.findByRole("table", { name: /Source components/ });
    fireEvent.click(
      screen.getByRole("button", { name: "Close source details" }),
    );
    expect(source).toHaveFocus();
  });
  it("TEST-FE-566 preserves exact64digit balances in the staff view", async () => {
    const value = "9".repeat(64),
      { api } = setup({ position: ledgerPosition(value, "0") });
    render(
      <CustomerAccountLedger
        actorId={ledgerIds.actor}
        api={api}
        requested={selected}
      />,
    );
    await account();
    expect(
      screen.getByText("Current amount owed").closest("div"),
    ).toHaveTextContent(
      `$${"9".repeat(62).replace(/\B(?=(\d{3})+(?!\d))/g, ",")}.99`,
    );
  });
  it("TEST-FE-567 reads every bounded history page without dropping equal-time rows", async () => {
    const events = Array.from({ length: 101 }, (_, index) =>
      ledgerEvent("INVOICE_ISSUED", index + 1, {
        occurred_at: "2026-07-01T00:00:00.000001+00:00",
      }),
    );
    const { api, fetcher } = setup({ events });
    render(
      <CustomerAccountLedger
        actorId={ledgerIds.actor}
        api={api}
        requested={selected}
      />,
    );
    await account();
    expect(
      screen.getAllByRole("button", { name: /^View source:/ }),
    ).toHaveLength(50);
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await screen.findByRole("button", { name: "View source: SYNTHETIC-100" });
    expect(
      screen.queryByRole("button", { name: "View source: SYNTHETIC-1" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await screen.findByRole("button", { name: "View source: SYNTHETIC-101" });
    expect(
      screen.getAllByRole("button", { name: /^View source:/ }),
    ).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Previous page" }));
    await screen.findByRole("button", { name: "View source: SYNTHETIC-100" });
    expect(fetcher).toHaveBeenCalledTimes(4);
  });
  it("TEST-FE-568 filters UTC history without altering authoritative account balances", async () => {
    const { api, fetcher } = setup();
    render(
      <CustomerAccountLedger
        actorId={ledgerIds.actor}
        api={api}
        requested={selected}
      />,
    );
    await account();
    fireEvent.change(screen.getByLabelText("Event kind"), {
      target: { value: "REFUND_PAID" },
    });
    fireEvent.change(screen.getByLabelText("From date"), {
      target: { value: "2026-07-01" },
    });
    fireEvent.change(screen.getByLabelText("Through date"), {
      target: { value: "2026-07-31" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Apply history filters" }),
    );
    await screen.findByText(
      "No financial events match these filters on this page.",
    );
    expect(
      screen.getByText("Current amount owed").closest("div"),
    ).toHaveTextContent("$231.00");
    const url = new URL(
      ledgerRequestUrl(fetcher.mock.calls.at(-1)?.[0]),
      "http://127.0.0.1",
    );
    expect(url.searchParams.get("from")).toBe("2026-07-01T00:00:00Z");
    expect(url.searchParams.get("through")).toBe("2026-07-31T23:59:59.999999Z");
    expect(url.searchParams.get("kind")).toBe("REFUND_PAID");
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    await screen.findByRole("table", {
      name: /Chronological financial history/,
    });
  });
  it("TEST-FE-569 rejects reversed filter dates without starting a new read", async () => {
    const { api, fetcher } = setup();
    render(
      <CustomerAccountLedger
        actorId={ledgerIds.actor}
        api={api}
        requested={selected}
      />,
    );
    await account();
    fireEvent.change(screen.getByLabelText("From date"), {
      target: { value: "2026-08-01" },
    });
    fireEvent.change(screen.getByLabelText("Through date"), {
      target: { value: "2026-07-01" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Apply history filters" }),
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "start date must be on or before",
    );
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it.each(["composition", "source"])(
    "TEST-FE-570 clears all revision-dependent displays after a409 from %s and refreshes the whole account",
    async (section) => {
      const state: SyntheticLedger = {},
        { api } = setup(state);
      render(
        <CustomerAccountLedger
          actorId={ledgerIds.actor}
          api={api}
          requested={selected}
        />,
      );
      await account();
      state.revision = "c".repeat(64);
      fireEvent.click(
        screen.getByRole("button", {
          name:
            section === "composition"
              ? "Balance composition"
              : "View source: SYNTHETIC-1",
        }),
      );
      await screen.findByRole("alert");
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Financial records changed",
      );
      expect(screen.queryByText("Current amount owed")).not.toBeInTheDocument();
      expect(
        screen.queryByRole("heading", { name: /Source details:/ }),
      ).not.toBeInTheDocument();
      fireEvent.click(
        screen.getByRole("button", { name: "Refresh whole account" }),
      );
      await account();
    },
  );
  it.each([401, 403, 404, 503])(
    "TEST-FE-571 presents a safe HTTP%s state without financial data and supports retry",
    async (status) => {
      const state: SyntheticLedger = { failure: status },
        { api } = setup(state);
      render(
        <CustomerAccountLedger
          actorId={ledgerIds.actor}
          api={api}
          requested={selected}
        />,
      );
      await screen.findByRole("alert");
      expect(screen.queryByText("Current amount owed")).not.toBeInTheDocument();
      state.failure = undefined;
      fireEvent.click(
        screen.getByRole("button", {
          name: status === 503 ? "Try again" : "Refresh whole account",
        }),
      );
      await account();
    },
  );
  it("TEST-FE-572 clears balances when ledger permission is revoked during a dependent read", async () => {
    const state: SyntheticLedger = {},
      { api } = setup(state);
    render(
      <CustomerAccountLedger
        actorId={ledgerIds.actor}
        api={api}
        requested={selected}
      />,
    );
    await account();
    state.failure = 403;
    fireEvent.click(
      screen.getByRole("button", { name: "Balance composition" }),
    );
    await screen.findByRole("alert");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "do not have permission",
    );
    expect(screen.queryByText("Current amount owed")).not.toBeInTheDocument();
  });
  it("TEST-FE-573 distinguishes a genuinely empty account from an empty filtered page", async () => {
    const { api } = setup({ events: [] });
    render(
      <CustomerAccountLedger
        actorId={ledgerIds.actor}
        api={api}
        requested={selected}
      />,
    );
    await account();
    expect(
      screen.getByText("This Customer has no recorded financial events."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Current amount owed").closest("div"),
    ).toHaveTextContent("$0.00");
  });
  it.each(["actor", "Customer", "filter", "close"])(
    "TEST-FE-574 ignores an old noncooperating response after a%s transition",
    async (transition) => {
      const actual = setup(),
        reply = await actual.api.read(
          { section: "history", customerId: ledgerIds.customer },
          {
            actorId: ledgerIds.actor,
            propertyId: ledgerIds.property,
            signal: new AbortController().signal,
          },
        );
      let resolve: ((value: LedgerReply) => void) | undefined;
      const read = vi.fn<CustomerLedgerApi["read"]>(
        () =>
          new Promise((done) => {
            resolve = done;
          }),
      );
      const api = { read };
      const view = render(
        <CustomerAccountLedger
          actorId={ledgerIds.actor}
          api={api}
          requested={selected}
        />,
      );
      const first = resolve;
      if (transition === "actor")
        view.rerender(
          <CustomerAccountLedger actorId={ledgerIds.other} api={api} />,
        );
      else if (transition === "Customer")
        fireEvent.click(
          screen.getByRole("button", { name: "Choose another Customer" }),
        );
      else if (transition === "filter") {
        fireEvent.change(screen.getByLabelText("Event kind"), {
          target: { value: "REFUND_PAID" },
        });
        fireEvent.click(
          screen.getByRole("button", { name: "Apply history filters" }),
        );
      } else
        fireEvent.click(
          screen.getByRole("button", { name: "Close Customer ledger" }),
        );
      expect(read.mock.calls[0]?.[1].signal.aborted).toBe(true);
      await act(async () => {
        first?.(reply);
        await Promise.resolve();
      });
      expect(
        screen.queryByRole("heading", { name: "Account: Synthetic Customer" }),
      ).not.toBeInTheDocument();
    },
  );
  it("TEST-FE-575 cancels all account reads on unmount for logout isolation", () => {
    const read = vi.fn<CustomerLedgerApi["read"]>(
      () =>
        new Promise(() => {
          /* Synthetic pending read. */
        }),
    );
    const view = render(
      <CustomerAccountLedger
        actorId={ledgerIds.actor}
        api={{ read }}
        requested={selected}
      />,
    );
    view.unmount();
    expect(read.mock.calls[0]?.[1].signal.aborted).toBe(true);
  });
  it("TEST-FE-576 traverses all remaining balance composition pages", async () => {
    const composition = Array.from({ length: 51 }, (_, index) =>
      ledgerComposition(index + 1),
    );
    const { api } = setup({ composition });
    render(
      <CustomerAccountLedger
        actorId={ledgerIds.actor}
        api={api}
        requested={selected}
      />,
    );
    await account();
    fireEvent.click(
      screen.getByRole("button", { name: "Balance composition" }),
    );
    await screen.findByRole("table", { name: /Remaining balance composition/ });
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
    });
    expect(screen.getAllByText(ledgerId(151)).length).toBeGreaterThan(0);
  });
});

it.each([false, true])(
  "TEST-FE-586 shows absent recorded amount and authoritative effects for Invoice void draft=%s",
  async (draft) => {
    const { api, fetcher } = setup(ledgerVoidScenario(draft));
    render(
      <CustomerAccountLedger
        actorId={ledgerIds.actor}
        api={api}
        requested={selected}
      />,
    );
    await account();
    const history = screen.getByRole("table", {
      name: /Chronological financial history/,
    });
    const eventRow = within(history).getAllByRole("row")[1];
    if (!eventRow) throw new Error("Expected void history row");
    expect(within(eventRow).getAllByRole("cell")[0]).toHaveTextContent(
      /^Not recorded$/,
    );
    expect(eventRow).toHaveTextContent(
      draft ? "No balance change" : "Decrease $510.00",
    );
    fireEvent.click(
      within(eventRow).getByRole("button", {
        name: "View source: SYNTHETIC-1",
      }),
    );
    const heading = await screen.findByRole("heading", {
      name: draft
        ? "Source details: Draft Invoice voided"
        : "Source details: Invoice voided",
    });
    expect(heading).toHaveFocus();
    const source = screen.getByRole("region", {
      name: heading.textContent,
    });
    expect(source).toHaveTextContent("Recorded amount: Not recorded");
    const components = await within(source).findByRole("table", {
      name: /Source components/,
    });
    expect(components).toHaveTextContent(
      draft ? "No balance change" : "Decrease $500.00",
    );
    if (!draft) expect(components).toHaveTextContent("Decrease $10.00");
    expect(
      screen.getByText("Current amount owed").closest("div"),
    ).toHaveTextContent("$0.00");
    for (const [, init] of fetcher.mock.calls) {
      expect(init?.method).toBe("GET");
      expect(init?.body).toBeUndefined();
    }
  },
);
