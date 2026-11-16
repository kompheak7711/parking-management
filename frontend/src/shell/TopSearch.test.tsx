// UI v81: the top-bar search. TEST-FE-1909, TEST-FE-1913.
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TopSearch, looksLikeDocumentNumber } from "./TopSearch";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("Top-bar search (UI v81)", () => {
  it("TEST-FE-1909 finds Units by number and Customers by name, opens the chosen record with Enter, and says when nothing is found", async () => {
    vi.useFakeTimers();
    const customers = vi.fn((_: string, query: string) =>
      Promise.resolve(
        query === "kong"
          ? [{ customer_id: "cust-1", legal_name: "Kong Heng" }]
          : [],
      ),
    );
    const units = vi.fn(() =>
      Promise.resolve([
        { unit_id: "unit-101", unit_number: "U101" },
        { unit_id: "unit-102", unit_number: "U102" },
      ]),
    );
    window.history.replaceState(null, "", "#/home");
    render(
      <TopSearch
        language="en"
        propertyId="property-1"
        sources={{ customers, units }}
      />,
    );
    const box = screen.getByRole("combobox", { name: "Search" });
    fireEvent.change(box, { target: { value: "kong" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(
      screen.getAllByRole("option").map((option) => option.textContent),
    ).toEqual(["Kong HengCustomer"]);
    fireEvent.change(box, { target: { value: "u10" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(
      screen.getAllByRole("option").map((option) => option.textContent),
    ).toEqual(["U101Unit", "U102Unit"]);
    fireEvent.keyDown(box, { key: "ArrowDown" });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(window.location.hash).toBe("#/units/unit-102");

    fireEvent.change(box, { target: { value: "zz" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(screen.getByText("Nothing found for “zz”.")).toBeTruthy();
  });
  it("TEST-FE-1913 names Invoice and Receipt in the placeholder and says that their numbers cannot be searched yet", async () => {
    vi.useFakeTimers();
    render(
      <TopSearch
        language="en"
        propertyId="property-1"
        sources={{
          customers: () => Promise.resolve([]),
          units: () => Promise.resolve([]),
        }}
      />,
    );
    const box = screen.getByRole("combobox", { name: "Search" });
    expect(box).toHaveAttribute(
      "placeholder",
      "Search Invoice, Receipt, Customer or Unit",
    );
    fireEvent.change(box, { target: { value: "INV260006" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(
      screen.getByText(
        "Invoice and Receipt numbers cannot be searched yet. Open Invoices or Payments and use the filters there.",
      ),
    ).toBeInTheDocument();
    expect(looksLikeDocumentNumber("PAY-2026-0012")).toBe(true);
    expect(looksLikeDocumentNumber("inv 12")).toBe(true);
    expect(looksLikeDocumentNumber("Kong Heng")).toBe(false);
    expect(looksLikeDocumentNumber("Prak Sok")).toBe(false);
  });
});
