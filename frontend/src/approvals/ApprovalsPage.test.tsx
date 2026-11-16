import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  SettlementRequestError,
  SettlementUnavailableError,
} from "../settlementClient";
import {
  ApprovalsNotAllowedError,
  ApprovalsUnavailableError,
  type DraftSummary,
  type WaitingDraft,
  type WaitingPage,
} from "./approvalsClient";
import { ApprovalsPage, type DraftDecisionApi } from "./ApprovalsPage";

afterEach(() => {
  cleanup();
});

const OWNER = "actor-owner";
const STAFF = "actor-staff";

function summary(extra: Partial<DraftSummary>): DraftSummary {
  return {
    variant: null,
    amount_usd_cents: null,
    direction: "INTERNAL",
    customer_id: null,
    customer_name: null,
    lease_id: null,
    reservation_id: null,
    deposit_type: null,
    unit_id: null,
    unit_number: null,
    prepared_by_name: "Sok Dara",
    decided_by_name: null,
    ...extra,
  };
}

function draft(
  id: string,
  kind: string,
  extra: Partial<DraftSummary>,
  more: Partial<WaitingDraft> = {},
): WaitingDraft {
  return {
    draft_id: id,
    property_id: "property-1",
    kind,
    prepare_capability: "refunds.create",
    payload: { variant: extra.variant ?? null },
    reason: `Reason of ${id}`,
    prepared_at: "2026-11-02T02:15:00Z",
    prepared_by: STAFF,
    state: "PENDING",
    decision: null,
    summary: summary(extra),
    ...more,
  };
}

const RES_REFUND = draft("d-1", "REFUND", {
  variant: "RESERVATION_OUTCOME",
  amount_usd_cents: 20_000,
  direction: "OUT",
  customer_name: "Long Sreyneang",
  reservation_id: "res-305",
  unit_id: "unit-305",
  unit_number: "U305",
});
const KEEP = draft("d-2", "DEPOSIT_FORFEITURE", {
  variant: "LEASE_FORFEITURE",
  amount_usd_cents: 40_000,
  direction: "KEPT",
  customer_name: "Lim Dara",
  lease_id: "lease-204",
  deposit_type: "SECURITY",
  unit_id: "unit-204",
  unit_number: "U204",
});
const MOVE = draft(
  "d-3",
  "PAYMENT_MOVE",
  {
    variant: "WRONG_UNIT_MOVE",
    amount_usd_cents: 1_200,
    customer_name: "Ouk Chanthy",
    unit_id: "unit-201",
    unit_number: "U201",
    prepared_by_name: "Chan Vy",
  },
  { prepared_by: OWNER },
);
const CORRECTION = draft("d-4", "SETTLEMENT_CORRECTION", {
  variant: "EXTRA_CHARGE",
  amount_usd_cents: 2_500,
  customer_name: "Sok Mean",
});
const DECIDED = draft(
  "d-9",
  "REFUND",
  {
    variant: "CREDIT_CUSTOMER",
    amount_usd_cents: 500,
    direction: "OUT",
    customer_name: "Tep Sreymom",
    unit_number: "U406",
    unit_id: "unit-406",
    decided_by_name: "Chan Vy",
  },
  {
    state: "REJECTED",
    decision: {
      decision: "REJECTED",
      reason: "Paid at the desk",
      decided_at: "2026-11-03T03:00:00Z",
      decided_by: OWNER,
      authorization_reference: null,
      result: null,
    },
  },
);

const PAGE: WaitingPage = {
  business_date: "2026-11-03",
  waiting: [RES_REFUND, KEEP, MOVE, CORRECTION],
  decided_today: [DECIDED],
};

function decisions(overrides: Partial<DraftDecisionApi> = {}) {
  return {
    confirmDraft: vi.fn(() =>
      Promise.resolve({ draft: RES_REFUND, result: null }),
    ),
    rejectDraft: vi.fn(() => Promise.resolve({})),
    withdrawDraft: vi.fn(() => Promise.resolve({})),
    ...overrides,
  };
}

function show(
  waiting: () => Promise<WaitingPage>,
  {
    capabilities = null as ReadonlySet<string> | null,
    actorId = OWNER,
    language = "en" as "en" | "km",
    decisionApi = decisions(),
  } = {},
) {
  const api = { waiting: vi.fn(waiting) };
  render(
    <ApprovalsPage
      active
      actorId={actorId}
      approvalsApi={api}
      capabilities={capabilities}
      decisionApi={decisionApi}
      language={language}
      propertyId="property-1"
    />,
  );
  return { api, decisionApi };
}

const rowLabels = () =>
  screen
    .getAllByRole("row")
    .slice(1)
    .map((row) => row.querySelector("b")?.textContent);

describe("Waiting for approval", () => {
  it("TEST-FE-932 shows the four cards, the waiting drafts oldest first with their names, Parking, Customer, preparer and amount, the cards filter the list, and what was decided today", async () => {
    const { api } = show(() => Promise.resolve(PAGE));
    expect(await screen.findByText("Refund: Reservation Deposit")).toBeTruthy();
    expect(api.waiting).toHaveBeenCalledWith("property-1");
    // Owner 13/11/2026 23:44: the line under the title is gone.
    expect(
      screen.queryByText(
        /Drafts move no money until the Owner or a Manager confirms them/,
      ),
    ).toBeNull();

    const cards = screen
      .getAllByRole("button", { pressed: false })
      .map((button) => button.getAttribute("aria-label"));
    expect(cards).toEqual([
      "Pending approval: 4.",
      "Refunds pending: $200.00.",
      "Deposit forfeitures pending: $400.00.",
      "Processed today: 1.",
    ]);
    expect(rowLabels()).toEqual([
      "Refund: Reservation Deposit",
      "Keep: Security Deposit",
      "Move payment to the right Parking",
      "Correction: extra charge",
    ]);
    const first = screen.getAllByRole("row")[1];
    if (first === undefined) throw new Error("no row");
    expect(
      within(first).getByRole("link", { name: "U305" }).getAttribute("href"),
    ).toBe("#/units/unit-305");
    expect(first.textContent).toContain("Long Sreyneang");
    expect(first.textContent).toContain("Sok Dara02/11/2026 09:15");
    expect(first.textContent).toContain("$200.00");
    expect(first.textContent).toContain("Pending approval");

    fireEvent.click(
      screen.getByRole("button", { name: /^Deposit forfeitures pending:/ }),
    );
    expect(rowLabels()).toEqual(["Keep: Security Deposit"]);
    expect(
      screen.getByText(/Showing: Deposit forfeitures pending/),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /^Processed today:/ }));
    expect(rowLabels()).toEqual(["Refund: Customer Credit"]);
    fireEvent.click(screen.getByRole("button", { name: "Show all" }));
    expect(rowLabels()).toHaveLength(4);

    expect(
      screen.getByText(
        "The person who prepared a draft may also confirm it only if they have approval rights. Both names are kept in the audit log.",
      ),
    ).toBeTruthy();
    const done = screen.getByRole("region", { name: "Processed today" });
    expect(done.textContent).toContain(
      "Refund: Customer Credit · U406 · Tep Sreymom",
    );
    expect(done.textContent).toContain(
      "Chan Vy · 03/11/2026 10:00 · Paid at the desk",
    );
    expect(done.textContent).toContain("Rejected");
  });

  it("TEST-FE-933 Open shows the draft and what confirming does; Confirm sends one decision and reads the list again; Reject needs a reason and sends it", async () => {
    let page = PAGE;
    const decisionApi = decisions();
    const { api } = show(() => Promise.resolve(page), { decisionApi });
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Review: Refund: Reservation Deposit",
      }),
    );
    const dialog = screen.getByRole("dialog", {
      name: "Refund: Reservation Deposit · U305",
    });
    expect(dialog.textContent).toContain("Reason of d-1");
    expect(dialog.textContent).toContain(
      "The money is paid back to Long Sreyneang. A Refund number is given now.",
    );
    expect(dialog.textContent).toContain(
      "Only the Owner or a Manager can confirm.",
    );
    expect(
      within(dialog).getByRole("link", { name: "Open" }).getAttribute("href"),
    ).toBe("#/reservations/res-305");
    // The Owner did not prepare this one, so there is no Withdraw.
    expect(
      within(dialog).queryByRole("button", { name: "Withdraw" }),
    ).toBeNull();

    page = { ...PAGE, waiting: PAGE.waiting.slice(1) };
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    expect(
      await screen.findByText("Refund: Reservation Deposit confirmed."),
    ).toBeTruthy();
    expect(decisionApi.confirmDraft).toHaveBeenCalledWith(
      "property-1",
      "d-1",
      expect.any(String),
    );
    await waitFor(() => {
      expect(api.waiting).toHaveBeenCalledTimes(2);
    });
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Review: Keep: Security Deposit",
      }),
    );
    expect(
      screen.getByText(
        "The Deposit is kept by CHETANA and counts as income this month.",
      ),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    const reject = screen.getByRole("dialog", {
      name: "Reject this draft · U204",
    });
    fireEvent.click(within(reject).getByRole("button", { name: "Reject" }));
    expect(within(reject).getByText("Write why it is rejected.")).toBeTruthy();
    expect(decisionApi.rejectDraft).not.toHaveBeenCalled();
    fireEvent.change(within(reject).getByLabelText(/Why is it rejected/), {
      target: { value: "  The tenant paid the damage  " },
    });
    fireEvent.click(within(reject).getByRole("button", { name: "Reject" }));
    expect(
      await screen.findByText(
        "Keep: Security Deposit rejected. No money moved.",
      ),
    ).toBeTruthy();
    expect(decisionApi.rejectDraft).toHaveBeenCalledWith(
      "property-1",
      "d-2",
      { reason: "The tenant paid the damage" },
      expect.any(String),
    );
  });

  it("TEST-FE-934 without approval rights there is no Confirm or Reject; the preparer may withdraw with a reason; a refusal shows its words; an answer that did not come back sends the same key again", async () => {
    const withdrawDraft = vi
      .fn()
      .mockRejectedValueOnce(new SettlementUnavailableError())
      .mockResolvedValueOnce({});
    const decisionApi = decisions({ withdrawDraft });
    show(() => Promise.resolve(PAGE), {
      capabilities: new Set(["payments.allocations.reverse"]),
      actorId: OWNER,
      decisionApi,
    });
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Review: Move payment to the right Unit",
      }),
    );
    const dialog = screen.getByRole("dialog");
    expect(
      within(dialog).queryByRole("button", { name: "Confirm" }),
    ).toBeNull();
    expect(within(dialog).queryByRole("button", { name: "Reject" })).toBeNull();
    expect(dialog.textContent).toContain(
      "You can see this draft. Only the Owner or a Manager can confirm or reject it.",
    );
    expect(dialog.textContent).toContain(
      "The payment stays the same. It stops paying the wrong Invoice and pays the right one instead.",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Withdraw" }));
    const withdraw = screen.getByRole("dialog", {
      name: "Withdraw this draft · U201",
    });
    fireEvent.change(
      within(withdraw).getByLabelText(/Why do you withdraw it/),
      {
        target: { value: "Wrong Invoice picked" },
      },
    );
    fireEvent.click(within(withdraw).getByRole("button", { name: "Withdraw" }));
    expect(
      await within(withdraw).findByText(
        "The answer did not come back. Close this and look at the list before trying again.",
      ),
    ).toBeTruthy();
    fireEvent.click(within(withdraw).getByRole("button", { name: "Withdraw" }));
    expect(
      await screen.findByText(
        "Move payment to the right Parking withdrawn. No money moved.",
      ),
    ).toBeTruthy();
    const calls = withdrawDraft.mock.calls as unknown[][];
    expect(calls).toHaveLength(2);
    expect(calls[0]?.[3]).toBe(calls[1]?.[3]);
    cleanup();

    const refused = decisions({
      confirmDraft: vi.fn(() =>
        Promise.reject(
          new SettlementRequestError(
            409,
            "DRAFT_NOT_PENDING",
            "This draft was already decided.",
          ),
        ),
      ),
    });
    const { api } = show(() => Promise.resolve(PAGE), { decisionApi: refused });
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Review: Correction: extra charge",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(
      await screen.findByText("This draft was already decided."),
    ).toBeTruthy();
    await waitFor(() => {
      expect(api.waiting).toHaveBeenCalledTimes(2);
    });
  });

  it("TEST-FE-935 a failed read offers Retry and shows no old list; no right to read says so; nothing waiting says so; Khmer words come from the mock-up", async () => {
    let fail = true;
    const { api } = show(() =>
      fail
        ? Promise.reject(new ApprovalsUnavailableError())
        : Promise.resolve({ ...PAGE, waiting: [], decided_today: [] }),
    );
    expect(
      await screen.findByText(
        "The drafts could not be loaded. Check the connection and try again.",
      ),
    ).toBeTruthy();
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(
      await screen.findByText(
        "Nothing is pending. Every draft has been processed.",
      ),
    ).toBeTruthy();
    // Operations fix 7: no empty "Processed today" box.
    expect(screen.queryAllByText("Nothing decided yet today.")).toHaveLength(0);
    expect(api.waiting).toHaveBeenCalledTimes(2);
    cleanup();

    show(() => Promise.reject(new ApprovalsNotAllowedError()));
    expect(
      await screen.findByText(
        "Your account cannot see the drafts. Use the menu to open your work.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    cleanup();

    show(() => Promise.resolve(PAGE), { language: "km" });
    expect(await screen.findByText("សងប្រាក់៖ ប្រាក់កក់ការកក់")).toBeTruthy();
    expect(screen.getByText("រក្សាទុក៖ ប្រាក់កក់ធានា")).toBeTruthy();
    expect(screen.getAllByText("បានសម្រេចថ្ងៃនេះ").length).toBeGreaterThan(0);
  });
  it("TEST-FE-936 a reject refused because someone decided first shows the draft as decided with the refusal words; more than 200 waiting says so; a refund worked out at confirm is named on Money out", async () => {
    let page = PAGE;
    const decisionApi = decisions({
      rejectDraft: vi.fn(() => {
        page = {
          ...PAGE,
          waiting: PAGE.waiting.slice(1),
          decided_today: [
            {
              ...RES_REFUND,
              state: "CONFIRMED" as const,
              decision: {
                decision: "CONFIRMED" as const,
                reason: null,
                decided_at: "2026-11-03T03:00:00Z",
                decided_by: OWNER,
                authorization_reference: null,
                result: null,
              },
              summary: { ...RES_REFUND.summary, decided_by_name: "Chan Vy" },
            },
          ],
        };
        return Promise.reject(
          new SettlementRequestError(
            409,
            "DRAFT_ALREADY_DECIDED",
            "This draft was already decided.",
          ),
        );
      }),
    });
    show(() => Promise.resolve(page), { decisionApi });
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Review: Refund: Reservation Deposit",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    const reject = screen.getByRole("dialog");
    fireEvent.change(within(reject).getByLabelText(/Why is it rejected/), {
      target: { value: "Paid twice" },
    });
    fireEvent.click(within(reject).getByRole("button", { name: "Reject" }));
    const decided = await screen.findByRole("dialog", {
      name: "Refund: Reservation Deposit · U305",
    });
    await waitFor(() => {
      expect(decided.textContent).toContain(
        "Confirmed: Chan Vy · 03/11/2026 10:00",
      );
    });
    expect(decided.textContent).toContain("This draft was already decided.");
    expect(
      within(decided).queryByRole("button", { name: "Confirm" }),
    ).toBeNull();
    cleanup();

    const held = draft("d-7", "SETTLEMENT_CORRECTION", {
      variant: "HELD_VALUE_REFUND",
      direction: "OUT",
      customer_name: "Sok Mean",
    });
    show(() =>
      Promise.resolve({
        ...PAGE,
        waiting: [...PAGE.waiting, held],
        truncated: true,
      }),
    );
    expect(
      await screen.findByText(
        "Only the 200 oldest drafts are shown. Decide these first to see the rest.",
      ),
    ).toBeTruthy();
    expect(
      screen
        .getByRole("button", { name: /^Refunds pending:/ })
        .getAttribute("aria-label"),
    ).toBe(
      "Refunds pending: $200.00. Refunds pending approval · 1 calculated when confirmed",
    );
  });

  it("TEST-FE-2143 (round 15) the row button says Review; Review shows the Refund method by name and the reference note; a name that could not be read leaves its row out; a Customer with no Unit is written as plain text in the list", async () => {
    const CREDIT = draft(
      "d-7",
      "REFUND",
      {
        variant: "USD",
        amount_usd_cents: 6_930,
        direction: "OUT",
        customer_name: "Mao Sophea",
      },
      {
        payload: {
          source_kind: "CREDIT",
          refund_method_id: "method-cash",
          reference_note: "Cash at the front desk",
        },
      },
    );
    const page = { ...PAGE, waiting: [CREDIT] };
    const refundMethods = vi.fn(() =>
      Promise.resolve([
        { id: "method-bank", display_name: "Bank transfer" },
        { id: "method-cash", display_name: "Cash" },
      ]),
    );
    show(() => Promise.resolve(page), {
      decisionApi: { ...decisions(), refundMethods },
    });
    const button = await screen.findByRole("button", {
      name: "Review: Refund: Customer Credit",
    });
    expect(button.textContent).toBe("Review");
    const cell = screen.getByText("Mao Sophea");
    expect(cell.tagName).toBe("TD");
    fireEvent.click(button);
    let dialog = screen.getByRole("dialog", {
      name: "Refund: Customer Credit",
    });
    const facts = () =>
      Array.from(dialog.querySelectorAll("dt")).map((term) => [
        term.textContent,
        term.nextElementSibling?.textContent,
      ]);
    await waitFor(() => {
      expect(facts()).toContainEqual(["Refund method", "Cash"]);
    });
    expect(facts()).toContainEqual(["Reference", "Cash at the front desk"]);
    expect(facts()).toContainEqual(["Reason", "Reason of d-7"]);
    expect(refundMethods).toHaveBeenCalledWith("property-1");
    cleanup();

    show(() => Promise.resolve(page), {
      decisionApi: {
        ...decisions(),
        refundMethods: vi.fn(() => Promise.reject(new Error("down"))),
      },
    });
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Review: Refund: Customer Credit",
      }),
    );
    dialog = screen.getByRole("dialog", { name: "Refund: Customer Credit" });
    expect(facts().map(([term]) => term)).not.toContain("Refund method");
    expect(facts()).toContainEqual(["Reference", "Cash at the front desk"]);
  });
});

describe("Operations screen (owner 13/11/2026)", () => {
  it("TEST-FE-2196 (owner 13/11/2026) the drafts table carries the phone card look, and the Processed today box shows only when something was decided today", async () => {
    show(() => Promise.resolve({ ...PAGE, decided_today: [] }));
    expect(await screen.findByText("Refund: Reservation Deposit")).toBeTruthy();
    expect(screen.getByRole("table").classList.contains("ui-applist")).toBe(
      true,
    );
    expect(
      screen.queryByRole("region", { name: "Processed today" }),
    ).toBeNull();
    cleanup();

    show(() => Promise.resolve(PAGE));
    expect(
      await screen.findByRole("region", { name: "Processed today" }),
    ).toBeTruthy();
  });
});
