import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FinancialConfirmation } from "./FinancialConfirmation";
import { FinancialRecoveryNotice } from "./FinancialRecoveryNotice";
import type {
  FinancialRecoveryState,
  PendingFinancialCommand,
} from "./financialRecovery";

afterEach(cleanup);
function props() {
  return {
    title: "Confirm original Allocation reversal",
    consequence:
      "This creates a linked reversal and preserves the original Allocation.",
    actionLabel: "Confirm reversal",
    noticeId: "financial-test-notice",
    busy: false,
    onConfirm: vi.fn(),
    onCancel: vi.fn(),
    children: <p>Original selected amount: USD 1.01</p>,
  };
}
describe("financial confirmation keyboard and dispatch boundary", () => {
  it("TEST-FE-424 traps keyboard focus, cancels without confirming and restores the opener", () => {
    const opener = document.createElement("button");
    opener.textContent = "Review reversal";
    document.body.append(opener);
    opener.focus();
    const p = props(),
      { unmount } = render(<FinancialConfirmation {...p} />);
    const dialog = screen.getByRole("dialog", { name: p.title });
    const cancel = within(dialog).getByRole("button", { name: "Cancel" });
    const confirm = within(dialog).getByRole("button", { name: p.actionLabel });
    expect(dialog).toHaveFocus();
    expect(dialog).toHaveAccessibleDescription(p.consequence);
    expect(p.onConfirm).not.toHaveBeenCalled();
    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(cancel).toHaveFocus();
    fireEvent.keyDown(cancel, { key: "Tab", shiftKey: true });
    expect(confirm).toHaveFocus();
    fireEvent.keyDown(confirm, { key: "Tab" });
    expect(cancel).toHaveFocus();
    opener.focus();
    expect(dialog).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(p.onCancel).toHaveBeenCalledTimes(1);
    expect(p.onConfirm).not.toHaveBeenCalled();
    unmount();
    expect(opener).toHaveFocus();
    opener.remove();
  });
  it("TEST-FE-425 requires explicit confirmation and prevents repeated clicks or busy Escape dismissal", () => {
    const p = props();
    render(<FinancialConfirmation {...p} />);
    const dialog = screen.getByRole("dialog"),
      confirm = screen.getByRole("button", { name: p.actionLabel });
    fireEvent.keyDown(dialog, { key: "Enter" });
    expect(p.onConfirm).not.toHaveBeenCalled();
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(p.onConfirm).toHaveBeenCalledTimes(1);
    expect(confirm).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(p.onCancel).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Wait for its recorded outcome",
    );
  });
  it("TEST-FE-426 returns focus to the financial notice if the old opener is unavailable", () => {
    const opener = document.createElement("button"),
      notice = document.createElement("section");
    notice.id = "financial-test-notice";
    notice.tabIndex = -1;
    document.body.append(opener, notice);
    opener.focus();
    const p = props(),
      { unmount } = render(<FinancialConfirmation {...p} busy />);
    expect(screen.getByRole("button", { name: p.actionLabel })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: p.actionLabel }));
    expect(p.onConfirm).not.toHaveBeenCalled();
    opener.disabled = true;
    unmount();
    expect(notice).toHaveFocus();
    opener.remove();
    notice.remove();
  });
});

const original: PendingFinancialCommand = {
  namespace: "property-rental.financial-command",
  version: 1,
  actorId: "11111111-1111-4111-8111-111111111111",
  propertyId: "22222222-2222-4222-8222-222222222222",
  key: "33333333-3333-4333-8333-333333333333",
  operation: "refundReturn",
  target: { id: "44444444-4444-4444-8444-444444444444" },
  wireBody:
    '{"currency":"USD","returned_amount_minor":101,"returned_at":"2026-09-08T10:00:00+07:00","return_method_reference":"Synthetic bank return","evidence_reference":"Synthetic verified return evidence","reason":"Synthetic original reason only for explicit review"}',
};
const states: (FinancialRecoveryState | null)[] = [
  null,
  { kind: "ready" },
  { kind: "pending", command: original },
  { kind: "other-property", propertyId: original.propertyId },
  { kind: "foreign" },
  { kind: "unavailable" },
  { kind: "invalidated" },
];
describe("financial recovery notice", () => {
  it.each(states.map((state) => ({ state, kind: state?.kind ?? "loading" })))(
    "TEST-FE-427 presents $kind recovery without automatic replay or destructive controls",
    ({ state, kind }) => {
      const review = vi.fn();
      const { rerender } = render(
        <FinancialRecoveryNotice
          id="recovery"
          state={state}
          busy={false}
          onReviewPending={review}
        />,
      );
      expect(screen.getByRole("status")).toHaveTextContent(/.+/);
      expect(review).not.toHaveBeenCalled();
      if (kind === "foreign") {
        expect(screen.getByRole("status")).toHaveTextContent(
          "another workflow",
        );
        expect(screen.getByRole("status")).not.toHaveTextContent(
          "different signed-in account",
        );
      }
      for (const name of [
        /discard/i,
        /replace/i,
        /retry/i,
        /replay/i,
        /clear/i,
      ])
        expect(screen.queryByRole("button", { name })).toBeNull();
      expect(
        screen.queryByText(
          "Synthetic original reason only for explicit review",
        ),
      ).toBeNull();
      if (kind === "pending") {
        expect(screen.getByText(original.key)).toBeVisible();
        expect(screen.getByText("Record verified USD return")).toBeVisible();
        fireEvent.click(
          screen.getByRole("button", { name: "Review original action" }),
        );
        expect(review).toHaveBeenCalledTimes(1);
        rerender(
          <FinancialRecoveryNotice
            id="recovery"
            state={state}
            busy
            onReviewPending={review}
          />,
        );
        expect(
          screen.getByRole("button", { name: "Review original action" }),
        ).toBeDisabled();
      } else {
        expect(screen.queryByRole("button")).toBeNull();
        expect(screen.queryByText(original.key)).toBeNull();
      }
    },
  );
});

it("TEST-FE-448 keeps Cancel and Escape available when current permission disables confirmation", () => {
  const p = props();
  render(<FinancialConfirmation {...p} confirmDisabled />);
  const dialog = screen.getByRole("dialog"),
    cancel = screen.getByRole("button", { name: "Cancel" });
  expect(screen.getByRole("button", { name: p.actionLabel })).toBeDisabled();
  expect(cancel).toBeEnabled();
  expect(screen.queryByRole("status")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: p.actionLabel }));
  expect(p.onConfirm).not.toHaveBeenCalled();
  fireEvent.keyDown(dialog, { key: "Tab" });
  expect(cancel).toHaveFocus();
  fireEvent.keyDown(cancel, { key: "Escape" });
  expect(p.onCancel).toHaveBeenCalledTimes(1);
});
