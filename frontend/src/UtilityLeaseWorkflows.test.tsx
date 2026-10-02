import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UtilityLeaseWorkflows } from "./UtilityLeaseWorkflows";
import { UtilityLeaseApi, UtilityLeaseError } from "./utilityLeaseClient";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function client(overrides: Partial<UtilityLeaseApi> = {}): UtilityLeaseApi {
  return {
    readBaseline: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    recordBaseline: vi.fn(
      (_p: string, _l: string, input: { event_id: string }) =>
        Promise.resolve({ event_id: input.event_id, creates_reading: false }),
    ),
    readFinalInputs: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    recordFinalInputs: vi.fn(
      (_p: string, _l: string, input: { event_id: string }) =>
        Promise.resolve({ event_id: input.event_id, creates_charge: false }),
    ),
    createFinalInvoice: vi.fn(
      (_p: string, _l: string, input: { invoice_id: string }) =>
        Promise.resolve({ invoice_id: input.invoice_id, kind: "FINAL" }),
    ),
    createCatchUpInvoice: vi.fn(
      (_p: string, _l: string, input: { invoice_id: string }) =>
        Promise.resolve({ invoice_id: input.invoice_id, kind: "CATCH_UP" }),
    ),
    listUnbilled: vi.fn().mockResolvedValue({
      items: [
        {
          period_id: "period-late",
          unit_id: "unit-1",
          utility_type: "ELECTRICITY",
          start_date: "2026-08-03",
          end_date: "2026-08-31",
          consumption_quantity: "40",
          lease_id: "lease-1",
          can_catch_up: true,
          gap_reason: "LATE_AFTER_SUCCEEDED_RUN",
        },
        {
          period_id: "period-skipped",
          unit_id: "unit-1",
          utility_type: "WATER",
          start_date: "2026-08-03",
          end_date: "2026-08-31",
          consumption_quantity: "9",
          lease_id: "lease-1",
          can_catch_up: false,
          gap_reason: "NOT_MOVED_IN",
        },
      ],
      limit: 50,
      offset: 0,
      total: null,
    }),
    ...overrides,
  };
}

const fill = (label: string, value: string) => {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
};
function open(api: UtilityLeaseApi, leaseId = "lease-1") {
  render(<UtilityLeaseWorkflows api={api} propertyId="property-1" />);
  fill("Utility Lease identifier", leaseId);
}

describe("V1-055 Lease Utility workflows", () => {
  it("TEST-FE-661 records a baseline with parsed items after confirmation and replays the same identities after a failure", async () => {
    const recordBaseline = vi
      .fn()
      .mockRejectedValueOnce(new UtilityLeaseError(null, "NETWORK"))
      .mockImplementation(
        (_p: string, _l: string, input: { event_id: string }) =>
          Promise.resolve({ event_id: input.event_id, creates_reading: false }),
      );
    const api = client({ recordBaseline });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    open(api);
    fill("Baseline date", "2026-09-02");
    fill("Baseline reason", "Baseline after cleaning");
    fill("Baseline evidence reference", "Sheet 17");
    fill(
      "Baseline items (one per line: Meter ID, Reading ID)",
      "meter-1, reading-1\nmeter-2 reading-2",
    );
    const submit = () => {
      fireEvent.click(
        screen.getByRole("button", { name: "Record Utility baseline" }),
      );
    };
    submit();
    await waitFor(() => {
      expect(recordBaseline).toHaveBeenCalledTimes(1);
    });
    await screen.findByText(/could not be completed/);
    submit();
    await waitFor(() => {
      expect(recordBaseline).toHaveBeenCalledTimes(2);
    });
    expect(recordBaseline.mock.calls[1]).toEqual(recordBaseline.mock.calls[0]);
    expect(recordBaseline.mock.calls[0]?.slice(0, 3)).toEqual([
      "property-1",
      "lease-1",
      expect.objectContaining({
        baseline_date: "2026-09-02",
        evidence_reference: "Sheet 17",
        items: [
          { meter_id: "meter-1", reading_id: "reading-1" },
          { meter_id: "meter-2", reading_id: "reading-2" },
        ],
      }),
    ]);
    const evidence = await screen.findByRole("region", {
      name: "Utility evidence",
    });
    expect(evidence).toHaveTextContent('"creates_reading": false');
  });

  it("TEST-FE-662 parses reading, estimate and unresolved final inputs and refuses a malformed line", async () => {
    const api = client();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    open(api);
    fill("Move-out event identifier", "departure-1");
    fill("Final input reason", "Reviewed");
    fill("Final input authorization reference", "AUTH-1");
    fill("Final input evidence reference", "SHEET-2");
    fill("Final input items (Meter ID, resolution, source)", "meter-1 READING");
    fireEvent.click(
      screen.getByRole("button", { name: "Record final Utility inputs" }),
    );
    expect(api.recordFinalInputs).not.toHaveBeenCalled();
    fill(
      "Final input items (Meter ID, resolution, source)",
      "meter-1, READING, reading-1\nmeter-2, ESTIMATE, estimate-1\nmeter-3, UNRESOLVED, MISSING_READING",
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Record final Utility inputs" }),
    );
    await waitFor(() => {
      expect(api.recordFinalInputs).toHaveBeenCalledTimes(1);
    });
    expect(vi.mocked(api.recordFinalInputs).mock.calls[0]?.[2]).toMatchObject({
      move_out_event_id: "departure-1",
      items: [
        { meter_id: "meter-1", resolution: "READING", reading_id: "reading-1" },
        {
          meter_id: "meter-2",
          resolution: "ESTIMATE",
          estimate_id: "estimate-1",
        },
        {
          meter_id: "meter-3",
          resolution: "UNRESOLVED",
          unresolved_reason: "MISSING_READING",
        },
      ],
    });
  });

  it("TEST-FE-663 needs both parts of a Due Date and shows the plain reason when the final Invoice is refused", async () => {
    const createFinalInvoice = vi
      .fn()
      .mockRejectedValue(
        new UtilityLeaseError(422, "UTILITY_UNRESOLVED_FINAL_INPUT", "req-9"),
      );
    const api = client({ createFinalInvoice });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    open(api);
    fill("Final input event identifier", "final-event-1");
    fill("Final Invoice Due Date (optional)", "2026-10-20");
    fireEvent.click(
      screen.getByRole("button", { name: "Create final Utility Invoice" }),
    );
    expect(createFinalInvoice).not.toHaveBeenCalled();
    fill("Final Invoice Due Date reason", "Owner agreed a date");
    fireEvent.click(
      screen.getByRole("button", { name: "Create final Utility Invoice" }),
    );
    await waitFor(() => {
      expect(createFinalInvoice).toHaveBeenCalledTimes(1);
    });
    expect(createFinalInvoice.mock.calls[0]?.[2]).toMatchObject({
      final_input_event_id: "final-event-1",
      due_date: "2026-10-20",
      due_date_reason: "Owner agreed a date",
    });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("A final input is still unresolved");
    expect(alert).toHaveTextContent("Support request ID: req-9");
  });

  it("TEST-FE-664 lists unbilled periods and selects an eligible one for the catch-up Invoice", async () => {
    const api = client();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<UtilityLeaseWorkflows api={api} propertyId="property-1" />);
    fireEvent.click(
      screen.getByRole("button", { name: "Load unbilled Utility periods" }),
    );
    const table = await screen.findByRole("table", {
      name: "Unbilled Utility periods",
    });
    expect(within(table).getByText("Not yet eligible")).toBeInTheDocument();
    expect(
      within(table).getByText("Skipped: Customer had not moved in"),
    ).toBeInTheDocument();
    fireEvent.click(
      within(table).getByRole("button", {
        name: "Select period period-late for catch-up",
      }),
    );
    expect(screen.getByLabelText("Utility Lease identifier")).toHaveValue(
      "lease-1",
    );
    expect(screen.getByLabelText("Catch-up period identifier")).toHaveValue(
      "period-late",
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Create catch-up Utility Invoice" }),
    );
    await waitFor(() => {
      expect(api.createCatchUpInvoice).toHaveBeenCalledTimes(1);
    });
    expect(
      vi.mocked(api.createCatchUpInvoice).mock.calls[0]?.slice(0, 3),
    ).toEqual([
      "property-1",
      "lease-1",
      expect.objectContaining({ consumption_period_id: "period-late" }),
    ]);
    expect(await screen.findByText(/"kind": "CATCH_UP"/)).toBeInTheDocument();
  });

  it("TEST-FE-665 sends nothing when the confirmation is declined or the Lease is missing", () => {
    const api = client();
    vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<UtilityLeaseWorkflows api={api} propertyId="property-1" />);
    fill("Catch-up period identifier", "period-1");
    fireEvent.click(
      screen.getByRole("button", { name: "Create catch-up Utility Invoice" }),
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Enter the Lease identifier first.",
    );
    fill("Utility Lease identifier", "lease-1");
    fireEvent.click(
      screen.getByRole("button", { name: "Create catch-up Utility Invoice" }),
    );
    expect(api.createCatchUpInvoice).not.toHaveBeenCalled();
  });

  it("TEST-FE-666 loads the baseline and final input histories read only and prompts for a Property", async () => {
    const api = client();
    open(api);
    fireEvent.click(
      screen.getByRole("button", { name: "Load baseline history" }),
    );
    await waitFor(() => {
      expect(api.readBaseline).toHaveBeenCalledWith("property-1", "lease-1");
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Load final input history" }),
    );
    await waitFor(() => {
      expect(api.readFinalInputs).toHaveBeenCalledWith("property-1", "lease-1");
    });
    expect(api.recordBaseline).not.toHaveBeenCalled();
    cleanup();
    render(<UtilityLeaseWorkflows api={api} propertyId="" />);
    expect(
      screen.getByText(
        "Select an authorized Property to use Lease Utility records.",
      ),
    ).toBeInTheDocument();
  });
});
