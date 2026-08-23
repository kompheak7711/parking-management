import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UnitManagement } from "./UnitManagement";
import {
  UnitApi,
  UnitConflictError,
  UnitResource,
  UnitUnavailableError,
} from "./unitClient";

const unit: UnitResource = {
  unit_id: "unit-1",
  property_id: "property-1",
  unit_number: "101",
  floor: "1",
  unit_type: "STUDIO",
  status: "UNDER_MAINTENANCE",
  version: 2,
  current_reservation: null,
  current_lease: null,
  current_occupancy: null,
  active_meter_summary: null,
  operational_alerts: ["UNDER_MAINTENANCE"],
  can_manage: true,
};

afterEach(cleanup);

function api(overrides: Partial<UnitApi> = {}): UnitApi {
  return {
    list: vi.fn().mockResolvedValue({
      items: [unit],
      next_cursor: null,
      can_manage: true,
    }),
    get: vi.fn().mockResolvedValue(unit),
    create: vi.fn().mockResolvedValue(unit),
    update: vi
      .fn()
      .mockResolvedValue({ ...unit, status: "CLEANING", version: 3 }),
    timeline: vi.fn().mockResolvedValue({
      items: [
        {
          event_id: "event-1",
          occurred_at: "2026-08-24T00:00:00Z",
          actor_id: "actor-1",
          action: "unit.updated",
          entity_type: "unit",
          reason: "Authorized update",
          previous_state: { status: "VACANT" },
          resulting_state: { status: "UNDER_MAINTENANCE" },
          correlation_id: "correlation-1",
          outcome: "SUCCEEDED",
        },
      ],
      next_cursor: null,
    }),
    ...overrides,
  };
}

async function loadUnits(client: UnitApi) {
  render(<UnitManagement api={client} />);
  fireEvent.change(screen.getByLabelText("Unit Property identifier"), {
    target: { value: "property-1" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Load Units" }));
  await screen.findByText("1 Unit record(s) loaded.");
}

describe("Unit management", () => {
  it("TEST-FE-027 shows a semantic Unit table, alerts, and authorized controls", async () => {
    const client = api();
    await loadUnits(client);

    expect(
      screen.getByRole("table", { name: /Current Unit source data/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "Status" }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByText("UNDER_MAINTENANCE").length,
    ).toBeGreaterThanOrEqual(2);
    expect(
      screen.getByRole("heading", { name: "Create Unit" }),
    ).toBeInTheDocument();
  });

  it("TEST-FE-028 hides Unit mutations without server capability", async () => {
    const client = api({
      list: vi.fn().mockResolvedValue({
        items: [unit],
        next_cursor: null,
        can_manage: false,
      }),
    });
    await loadUnits(client);

    expect(
      screen.queryByRole("heading", { name: "Create Unit" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-029 separates Unit sources and immutable audit history", async () => {
    const client = api();
    await loadUnits(client);
    fireEvent.click(screen.getByRole("button", { name: "Open Unit 101" }));

    expect(
      await screen.findByRole("heading", { name: "Unit 101 detail" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Reservations")).toBeInTheDocument();
    expect(screen.getByText("Leases and Occupancy")).toBeInTheDocument();
    expect(screen.getByText("Meters and Readings")).toBeInTheDocument();
    expect(screen.getByText("Billing history")).toBeInTheDocument();
    expect(screen.getByText("unit.updated")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /delete/i }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-030 announces Unit authorization and concurrency failures", async () => {
    const denied = api({
      list: vi.fn().mockRejectedValue(new UnitUnavailableError()),
    });
    render(<UnitManagement api={denied} />);
    fireEvent.change(screen.getByLabelText("Unit Property identifier"), {
      target: { value: "property-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load Units" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Unit access is unavailable for this session.",
    );
    expect(
      screen.queryByRole("heading", { name: "Create Unit" }),
    ).not.toBeInTheDocument();

    cleanup();
    const conflicting = api({
      update: vi.fn().mockRejectedValue(new UnitConflictError()),
    });
    await loadUnits(conflicting);
    fireEvent.click(screen.getByRole("button", { name: "Open Unit 101" }));
    await screen.findByRole("heading", { name: "Unit 101 detail" });
    fireEvent.click(
      screen.getByRole("button", { name: "Save Unit source data" }),
    );
    await waitFor(() => {
      expect(screen.getAllByRole("status").at(-1)).toHaveTextContent(
        "The Unit changed. Reload it before retrying.",
      );
    });

    cleanup();
    let resolveCreate!: (created: UnitResource) => void;
    const staleCreate = api({
      create: vi.fn().mockReturnValue(
        new Promise<UnitResource>((resolve) => {
          resolveCreate = resolve;
        }),
      ),
    });
    await loadUnits(staleCreate);
    fireEvent.change(screen.getByLabelText("Unit identifier/name"), {
      target: { value: "102" },
    });
    fireEvent.change(screen.getByLabelText("Floor"), {
      target: { value: "2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create Unit" }));
    fireEvent.change(screen.getByLabelText("Unit Property identifier"), {
      target: { value: "property-2" },
    });
    act(() => {
      resolveCreate({ ...unit, unit_id: "unit-2", unit_number: "102" });
    });
    expect(
      screen.queryByRole("table", { name: /Current Unit source data/ }),
    ).not.toBeInTheDocument();
  });
});
