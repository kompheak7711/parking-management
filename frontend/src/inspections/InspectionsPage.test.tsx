// UI v81 round 2: Property › Inspections. TEST-FE-1914.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { InspectionsPage } from "./InspectionsPage";

afterEach(() => {
  cleanup();
});

describe("Inspections (UI v81 round 2)", () => {
  it("TEST-FE-1914 says where inspections are for now and opens Move-outs and Problem reports", () => {
    render(<InspectionsPage language="en" />);
    expect(
      screen.getByText(
        "This page does not list inspections yet. For now, find them here:",
      ),
    ).toBeInTheDocument();
    // Property fix 5 (owner 14/11/2026): no build-step notes for staff.
    expect(screen.queryByText(/V1\.2/)).toBeNull();
    expect(
      screen.getByRole("link", { name: "Open Move-outs" }),
    ).toHaveAttribute("href", "#/moveout");
    expect(
      screen.getByRole("link", { name: "Open Problem reports" }),
    ).toHaveAttribute("href", "#/problems");
    cleanup();
    render(<InspectionsPage language="km" />);
    expect(
      screen.getByRole("link", { name: "បើកការចាកចេញ" }),
    ).toBeInTheDocument();
  });
});
