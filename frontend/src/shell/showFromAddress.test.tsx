// UI v81 round 11 (owner 12/11/2026: "check all card is link to correct place"): the part of a
// page named in the address ("#/invoices?show=overdue"). TEST-FE-1944.
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { hashForShow, useHashShow, useShowFromAddress } from "./useHashPage";

const PARTS = ["all", "open", "overdue"] as const;

/** A tiny list: its chosen part follows the address, and a choice by hand is kept there. */
function List() {
  const [part, setPart] = useState<string>("all");
  const [period, setPeriod] = useState<string>("all");
  const keep = useShowFromAddress("invoices", (show, query) => {
    if ((PARTS as readonly string[]).includes(show)) setPart(show);
    setPeriod(query.get("period") ?? "all");
  });
  const asked = useHashShow("invoices");
  return (
    <div>
      <p>
        Part {part}, period {period}, asked {asked ?? "nothing"}
      </p>
      {PARTS.map((each) => (
        <button
          key={each}
          onClick={() => {
            setPart(each);
            keep(each === "all" ? null : each);
          }}
          type="button"
        >
          {each}
        </button>
      ))}
      <button
        onClick={() => {
          keep("open", { period: "month" });
        }}
        type="button"
      >
        open this month
      </button>
    </div>
  );
}

function go(hash: string) {
  act(() => {
    window.history.pushState(null, "", hash);
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  });
}

beforeEach(() => {
  window.history.replaceState(null, "", "#/home");
});
afterEach(() => {
  cleanup();
});

describe("The part of a page in the address (UI v81 round 11)", () => {
  it("TEST-FE-1944 a list opens on the part its address names and follows each later address of its own page; a choice by hand is kept in the address without a new history step and keeps the history state; a record's address and another page's address change nothing", () => {
    expect(hashForShow("invoices", "overdue")).toBe("#/invoices?show=overdue");
    expect(hashForShow("invoices", "paid", { period: "month" })).toBe(
      "#/invoices?show=paid&period=month",
    );

    // The list opens under the address of a Home card.
    window.history.replaceState(null, "", "#/invoices?show=overdue");
    render(<List />);
    expect(
      screen.getByText("Part overdue, period all, asked overdue"),
    ).toBeTruthy();

    // A second card's address while the list is open: the part follows, with its other words.
    go("#/invoices?show=open&period=month");
    expect(
      screen.getByText("Part open, period month, asked open"),
    ).toBeTruthy();

    // An unknown word leaves the part as it is; the list decides which words it knows.
    go("#/invoices?show=nothing-like-this");
    expect(screen.getByText(/^Part open, period all/)).toBeTruthy();

    // A choice by hand: the address names it, the history has no new step and keeps its state.
    window.history.replaceState({ from: "home" }, "", "#/invoices");
    const steps = window.history.length;
    fireEvent.click(screen.getByRole("button", { name: "overdue" }));
    expect(window.location.hash).toBe("#/invoices?show=overdue");
    expect(window.history.length).toBe(steps);
    expect(window.history.state).toEqual({ from: "home" });
    fireEvent.click(screen.getByRole("button", { name: "open this month" }));
    expect(window.location.hash).toBe("#/invoices?show=open&period=month");
    // The whole list has the plain address again.
    fireEvent.click(screen.getByRole("button", { name: "all" }));
    expect(window.location.hash).toBe("#/invoices");
    expect(window.history.length).toBe(steps);

    // A record of the page, or another page: nothing is applied and nothing is written.
    go("#/invoices/inv:inv-6?show=overdue");
    expect(
      screen.getByText(/^Part all, period all, asked nothing/),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "overdue" }));
    expect(window.location.hash).toBe("#/invoices/inv:inv-6?show=overdue");
    go("#/units?show=overdue");
    expect(screen.getByText(/asked nothing/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "open" }));
    expect(window.location.hash).toBe("#/units?show=overdue");

    // Back to the card's address: the part is applied again.
    go("#/invoices?show=overdue");
    expect(
      screen.getByText("Part overdue, period all, asked overdue"),
    ).toBeTruthy();
  });
});
