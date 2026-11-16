// Property fix 1 (owner 14/11/2026): a table row's buttons sit in one small "Edit" menu.
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RowMenu } from "./ui";

afterEach(() => {
  cleanup();
});

describe("Row menu", () => {
  it("TEST-FE-2213 the Edit menu shows its buttons only when opened, and a choice, Escape or a press outside closes it", async () => {
    const edit = vi.fn();
    render(
      <div>
        <button type="button">Outside</button>
        <RowMenu label="Edit" name="Edit: Fan">
          <button onClick={edit} type="button">
            Details
          </button>
        </RowMenu>
      </div>,
    );
    const summary = screen.getByLabelText("Edit: Fan");
    expect(screen.queryByRole("button", { name: "Details" })).toBeNull();

    const open = async () => {
      fireEvent.click(summary);
      return screen.findByRole("button", { name: "Details" });
    };

    fireEvent.click(await open());
    expect(edit).toHaveBeenCalledTimes(1);
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Details" })).toBeNull();
    });

    await open();
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Details" })).toBeNull();
    });
    expect(document.activeElement).toBe(summary);

    await open();
    fireEvent.pointerDown(screen.getByRole("button", { name: "Outside" }));
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Details" })).toBeNull();
    });
  });
});
