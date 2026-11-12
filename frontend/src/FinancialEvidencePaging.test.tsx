import { useLayoutEffect, useRef, type ReactNode } from "react";
import { afterEach, describe, expect, it } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";

import { PaymentReversalEvidence } from "./FinancialEvidence";

afterEach(cleanup);

function impact(count: number, paymentId: string, revision: string) {
  return {
    view: "impact",
    revision,
    payment_resource: { payment: { id: paymentId } },
    items: Array.from({ length: count }, (_, i) => ({
      kind: "CREDIT",
      id: `60000000-0000-4000-8000-${(i + 1).toString().padStart(12, "0")}`,
      data: { amount_usd_cents: 1 },
    })),
  };
}

// Clicks "Next reversal records" while the first commit is still running (a layout effect runs
// before any passive effect). On a busy machine a real click can land in that same gap.
function ClickNextOnFirstCommit({ children }: { children: ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const next = Array.from(box.current?.querySelectorAll("button") ?? []).find(
      (button) => button.textContent === "Next reversal records",
    );
    next?.click();
  }, []);
  return <div ref={box}>{children}</div>;
}

describe("paged reversal evidence", () => {
  it("TEST-FE-2100 keeps the next page when Next is clicked before the table has finished mounting", () => {
    render(
      <ClickNextOnFirstCommit>
        <PaymentReversalEvidence value={impact(101, "p1", "r1")} />
      </ClickNextOnFirstCommit>,
    );
    const region = screen.getByRole("region", {
      name: "Complete Payment reversal impact",
    });
    expect(region).toHaveTextContent("showing 51–100 of 101");
    expect(within(region).getAllByRole("row")).toHaveLength(51);
  });

  it("TEST-FE-2101 goes back to the first page only when the payment, view or revision changes", () => {
    const { rerender } = render(
      <PaymentReversalEvidence value={impact(101, "p1", "r1")} />,
    );
    const region = () =>
      screen.getByRole("region", { name: "Complete Payment reversal impact" });
    fireEvent.click(
      within(region()).getByRole("button", { name: "Next reversal records" }),
    );
    expect(region()).toHaveTextContent("showing 51–100");
    rerender(<PaymentReversalEvidence value={impact(101, "p1", "r1")} />);
    expect(region()).toHaveTextContent("showing 51–100");
    rerender(<PaymentReversalEvidence value={impact(101, "p1", "r2")} />);
    expect(region()).toHaveTextContent("showing 1–50");
  });
});
