// UI v81 round 2: Property › Inspections. TEST-FE-1914; owner 16/11/2026 list: TEST-FE-2215.
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  type ProblemsApi,
  ProblemsError,
  type PropertyInspections,
} from "../problems/problemsClient";
import { InspectionsPage } from "./InspectionsPage";

afterEach(() => {
  cleanup();
});

const LIST: PropertyInspections = {
  as_of: "2026-11-16",
  move_outs: [
    {
      inspection_id: "i-1",
      lease_id: "l-1",
      lease_number: "U101L0026",
      unit_id: "u-101",
      unit_number: "U101",
      tenant_name: "Sok Dara",
      inspection_date: "2026-11-03",
      findings: 2,
    },
  ],
  unit_checks: [
    {
      check_id: "c-1",
      unit_id: "u-203",
      unit_number: "U203",
      check_date: "2026-11-10",
      kind: "REGULAR",
      findings: 2,
      checked_by_en: "Son Sokhen",
      checked_by_km: "សន សុខខេន",
      reports: [
        { report_id: "r-1", report_number: "UP260004" },
        { report_id: "r-2", report_number: "UP260005" },
      ],
    },
    {
      check_id: "c-2",
      unit_id: "u-305",
      unit_number: "U305",
      check_date: "2026-11-08",
      kind: "AFTER_REPAIR",
      findings: 0,
      checked_by_en: "Son Sokhen",
      checked_by_km: null,
      reports: [],
    },
  ],
};

function apiWith(inspections: ProblemsApi["inspections"]): ProblemsApi {
  return { inspections } as unknown as ProblemsApi;
}

describe("Inspections", () => {
  it("TEST-FE-1914 with nothing recorded yet, says where move-out inspections and Parking checks come from", async () => {
    const inspections = vi.fn(() =>
      Promise.resolve({ as_of: "2026-11-16", move_outs: [], unit_checks: [] }),
    );
    render(
      <InspectionsPage
        api={apiWith(inspections)}
        language="en"
        propertyId="property-1"
      />,
    );
    expect(
      await screen.findByText(
        "No move-out inspection yet. It is recorded on the Lease's Move-out page.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "No Parking check yet. Staff send Parking checks from the Telegram Staff bot.",
      ),
    ).toBeInTheDocument();
    expect(inspections).toHaveBeenCalledWith("property-1");
    // Property fix 5 (owner 14/11/2026): no build-step notes for staff.
    expect(screen.queryByText(/V1\.2|not list inspections yet/)).toBeNull();
    cleanup();
    render(
      <InspectionsPage
        api={apiWith(() => Promise.reject(new ProblemsError(403)))}
        language="km"
        propertyId="property-1"
      />,
    );
    expect(
      await screen.findByText(
        "អ្នកត្រូវមានសិទ្ធិ អានចំណត ដើម្បីមើលការត្រួតពិនិត្យ។",
      ),
    ).toBeInTheDocument();
  });

  it("TEST-FE-2215 (owner 16/11/2026) lists the move-out inspections and the Staff bot's Parking checks with links to the Parking, the Move-out page and each Problem report; a page that is not on screen reads nothing", async () => {
    const inspections = vi.fn(() => Promise.resolve(LIST));
    const { rerender } = render(
      <InspectionsPage
        active={false}
        api={apiWith(inspections)}
        language="en"
        propertyId="property-1"
      />,
    );
    expect(inspections).not.toHaveBeenCalled();
    rerender(
      <InspectionsPage
        active
        api={apiWith(inspections)}
        language="en"
        propertyId="property-1"
      />,
    );
    const moveOuts = await screen.findByRole("region", {
      name: "Move-out inspections 1",
    });
    const row = within(moveOuts).getByRole("row", { name: /U101L0026/ });
    expect(within(row).getByText("03/11/2026")).toBeInTheDocument();
    expect(within(row).getByText("Sok Dara")).toBeInTheDocument();
    expect(
      within(row).getByRole("link", { name: "U101" }).getAttribute("href"),
    ).toBe("#/units/u-101");
    expect(
      within(row).getByRole("link", { name: "Open" }).getAttribute("href"),
    ).toBe("#/moveout/l-1");

    const checks = screen.getByRole("region", { name: "Parking checks 2" });
    const regular = within(checks).getByRole("row", { name: /U203/ });
    expect(within(regular).getByText("Regular check")).toBeInTheDocument();
    expect(within(regular).getByText("Son Sokhen")).toBeInTheDocument();
    expect(
      within(regular)
        .getByRole("link", { name: "UP260005" })
        .getAttribute("href"),
    ).toBe("#/problems/pr%3Ar-2");
    const after = within(checks).getByRole("row", { name: /U305/ });
    expect(within(after).getByText("After repair")).toBeInTheDocument();
    expect(within(after).getByText("All good")).toBeInTheDocument();
  });
});
