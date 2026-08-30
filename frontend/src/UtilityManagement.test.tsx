import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UtilityManagement } from "./UtilityManagement";
import {
  UtilityApi,
  UtilityCalculation,
  UtilityConflictError,
  UtilitySnapshot,
} from "./utilityClient";

const propertyId = "10000000-0000-4000-8000-000000000011";
const unitId = "10000000-0000-4000-8000-000000000012";
const meterId = "10000000-0000-4000-8000-000000000013";
const readingId = "10000000-0000-4000-8000-000000000014";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function snapshot(): UtilitySnapshot {
  return {
    meters: [
      {
        id: meterId,
        property_id: propertyId,
        unit_id: unitId,
        utility_type: "ELECTRICITY",
        serial_number: "ELEC-301",
        measurement_unit_code: "KWH",
        description: null,
        installed_date: "2026-07-01",
        failure_date: null,
        deactivated_date: null,
        current: true,
        version: 2,
        memo: null,
        replacement: {
          replaced_meter_id: null,
          replacement_meter_id: null,
          replacement_date: null,
        },
        readings_url: `/api/v1/meters/${meterId}/readings`,
      },
    ],
    readings: {
      [meterId]: [
        {
          id: readingId,
          property_id: propertyId,
          meter_id: meterId,
          unit_id: unitId,
          utility_type: "ELECTRICITY",
          measurement_unit_code: "KWH",
          reading_date: "2026-07-31",
          original_value: "100.000000",
          effective_value: "105.000000",
          validated: true,
          validated_at: "2026-07-31T12:00:00Z",
          validated_by: "10000000-0000-4000-8000-000000000015",
          source: { kind: "MANUAL", evidence: "Meter photograph" },
          version: 2,
          corrections: [
            {
              id: "10000000-0000-4000-8000-000000000016",
              previous_value: "100.000000",
              corrected_value: "105.000000",
              reason: "Transcription correction",
              occurred_at: "2026-08-01T12:00:00Z",
              actor_id: "10000000-0000-4000-8000-000000000015",
              authorization_reference: "approval-1",
            },
          ],
        },
      ],
    },
    rates: [
      {
        id: "10000000-0000-4000-8000-000000000017",
        utility_type: "ELECTRICITY",
        measurement_unit_code: "KWH",
        rate_usd_per_unit: "0.250000",
        effective_date: "2026-08-01",
        notice_at: "2026-07-01T12:00:00+07:00",
        notice_evidence: "Customer notice batch 7",
        source_memo: null,
      },
    ],
  };
}

function api(): UtilityApi {
  const value = snapshot();
  return {
    load: vi.fn().mockResolvedValue(value),
    loadMeters: vi.fn(),
    loadReadings: vi.fn(),
    loadRates: vi.fn(),
    installMeter: vi.fn().mockResolvedValue(value.meters[0]),
    replaceMeter: vi.fn().mockResolvedValue(value.meters[0]),
    recordReading: vi.fn().mockResolvedValue(value.readings[meterId]?.[0]),
    correctReading: vi.fn(),
    recordBatch: vi.fn().mockResolvedValue([
      {
        index: 0,
        idempotency_key: crypto.randomUUID(),
        status: "SUCCEEDED",
        reading: value.readings[meterId]?.[0] ?? null,
        error: null,
      },
    ]),
    createRate: vi.fn().mockResolvedValue(value.rates[0]),
    preview: vi.fn(),
  };
}

async function loadWorkspace(client: UtilityApi) {
  render(<UtilityManagement api={client} propertyId={propertyId} />);
  fireEvent.change(screen.getByLabelText("Unit identifier"), {
    target: { value: unitId },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Load Utility workspace" }),
  );
  await screen.findByText("Complete Utility history loaded.");
}

describe("UtilityManagement", () => {
  it("TEST-FE-217 renders Meter, corrected Reading, and Rate evidence", async () => {
    const client = api();
    await loadWorkspace(client);
    expect(screen.getByText("105.000000 KWH")).toBeInTheDocument();
    expect(
      screen.getByText("105.000000: Transcription correction"),
    ).toBeInTheDocument();
    expect(screen.getByText("Customer notice batch 7")).toBeInTheDocument();
    expect(screen.getByText(/never calculates or issues/i)).toBeInTheDocument();
  });

  it("TEST-FE-218 submits bounded PARTIAL rows and displays per-row server results", async () => {
    const client = api();
    await loadWorkspace(client);
    const batch = screen.getByRole("heading", {
      name: "Bounded bulk Reading entry",
    }).parentElement;
    if (batch === null) throw new Error("Batch section missing");
    const inputs = batch.querySelectorAll("input");
    const [meter, version, readingDate, readingValue, evidence] = inputs;
    if (
      meter === undefined ||
      version === undefined ||
      readingDate === undefined ||
      readingValue === undefined ||
      evidence === undefined
    ) {
      throw new Error("Batch controls missing");
    }
    fireEvent.change(meter, { target: { value: meterId } });
    fireEvent.change(version, { target: { value: "2" } });
    fireEvent.change(readingDate, { target: { value: "2026-08-31" } });
    fireEvent.change(readingValue, { target: { value: "150" } });
    fireEvent.change(evidence, { target: { value: "Photo 8" } });
    fireEvent.click(
      screen.getByRole("button", { name: "Submit Reading batch" }),
    );
    await waitFor(() => {
      expect(client.recordBatch).toHaveBeenCalled();
    });
    expect(
      await screen.findByRole("cell", { name: "SUCCEEDED" }),
    ).toBeInTheDocument();
  });

  it("TEST-FE-219 displays the explicit pending future-basis state without client arithmetic", async () => {
    const client = api();
    const pending: UtilityCalculation = {
      status: "PENDING_FUTURE_ACTUAL_BASIS",
      property_id: propertyId,
      unit_id: unitId,
      utility_type: "ELECTRICITY",
      consumption_period_id: null,
      calculation_kind: null,
      period_start: "2026-08-01",
      period_end: "2026-08-31",
      consumption_quantity: null,
      represented_days: 31,
      meter_id: null,
      start_reading_id: null,
      end_reading_id: null,
      failed_meter_id: meterId,
      replacement_meter_id: "10000000-0000-4000-8000-000000000018",
      basis_kind: null,
      basis_period_ids: [],
      basis_sources: [],
      total_basis_consumption: null,
      total_basis_days: null,
      weighted_daily_average: null,
      generation_date: null,
      rate_id: null,
      rate_effective_date: null,
      rate_usd_per_unit: null,
      amount_usd_cents: null,
    };
    vi.mocked(client.preview).mockResolvedValue(pending);
    await loadWorkspace(client);
    fireEvent.change(screen.getByLabelText("Source kind"), {
      target: { value: "ESTIMATION_CASE" },
    });
    fireEvent.change(screen.getByLabelText("Source identifier"), {
      target: { value: "10000000-0000-4000-8000-000000000019" },
    });
    fireEvent.change(
      screen.getByLabelText(
        "Invoice generation timestamp (Property local time)",
      ),
      { target: { value: "2026-08-31T10:00" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Preview on server—do not issue" }),
    );
    expect(
      await screen.findByText(/zero complete historical actual periods/i),
    ).toBeInTheDocument();
    expect(screen.getByText("Pending—no charge")).toBeInTheDocument();
    expect(screen.queryByLabelText(/comparable unit/i)).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText(/arbitrary estimate/i),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-220 exposes labeled install, replacement, correction, and Rate evidence controls", async () => {
    await loadWorkspace(api());
    expect(screen.getByLabelText("Boundary Reading evidence")).toBeRequired();
    expect(
      screen.getByLabelText("Failed boundary Reading identifier"),
    ).toBeRequired();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Correct Reading from 2026-07-31 for Meter ELEC-301",
      }),
    );
    expect(screen.getByLabelText("Correction reason")).toBeRequired();
    expect(screen.getByLabelText("Authorization reference")).toBeRequired();
    expect(screen.getByLabelText("Advance-notice evidence")).toBeRequired();
  });

  it("correction C binds per-row review and renders server impact evidence", async () => {
    const client = api();
    const source = snapshot().readings[meterId]?.[0];
    if (source === undefined) throw new Error("Reading fixture missing");
    vi.mocked(client.correctReading).mockResolvedValue({
      reading: {
        ...source,
        effective_value: "110.000000",
        version: 3,
      },
      correction: {
        id: "10000000-0000-4000-8000-000000000020",
        previous_value: "105.000000",
        corrected_value: "110.000000",
        reason: "Verified photograph",
        occurred_at: "2026-08-02T12:00:00Z",
        actor_id: "10000000-0000-4000-8000-000000000015",
        authorization_reference: "approval-2",
      },
      affected_calculations: [
        {
          consumption_period_id: "10000000-0000-4000-8000-000000000021",
          previous_consumption_quantity: "20.000000",
          corrected_consumption_quantity: "25.000000",
          billing_effect_kind: "POST_ISSUANCE_ADJUSTMENT",
          issued_line: {
            invoice_line_id: "10000000-0000-4000-8000-000000000022",
            source_invoice_id: "10000000-0000-4000-8000-000000000023",
            calculated_difference_usd_cents: 125,
            invoice_adjustment_id: "10000000-0000-4000-8000-000000000024",
          },
        },
      ],
    });
    await loadWorkspace(client);

    fireEvent.click(
      screen.getByRole("button", {
        name: "Correct Reading from 2026-07-31 for Meter ELEC-301",
      }),
    );
    const sourceRegion = screen.getByRole("region", {
      name: "Selected Reading correction source",
    });
    expect(sourceRegion).toHaveTextContent(readingId);
    expect(sourceRegion).toHaveTextContent("100.000000 KWH");
    expect(sourceRegion).toHaveTextContent("105.000000 KWH");
    expect(sourceRegion).toHaveTextContent(/Expected Reading version\s*2/);
    expect(
      screen.queryByLabelText("Reading identifier"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText("Expected Reading version"),
    ).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Corrected value"), {
      target: { value: "110" },
    });
    fireEvent.change(screen.getByLabelText("Correction reason"), {
      target: { value: "Verified photograph" },
    });
    fireEvent.change(screen.getByLabelText("Authorization reference"), {
      target: { value: "approval-2" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Review Reading correction" }),
    );
    expect(client.correctReading).not.toHaveBeenCalled();
    expect(
      screen.getByRole("region", { name: "Confirm Reading correction" }),
    ).toHaveTextContent("105.000000 KWH to 110 KWH");

    fireEvent.click(
      screen.getByRole("button", { name: "Confirm and append correction" }),
    );
    await waitFor(() => {
      expect(client.correctReading).toHaveBeenCalledWith(
        readingId,
        {
          expected_version: 2,
          corrected_value: "110",
          reason: "Verified photograph",
          authorization_reference: "approval-2",
        },
        expect.any(String),
      );
    });
    const result = await screen.findByRole("region", {
      name: "Reading correction recorded",
    });
    expect(result).toHaveTextContent(/Original value\s*100\.000000/);
    expect(result).toHaveTextContent(/Previous effective value\s*105\.000000/);
    expect(result).toHaveTextContent(/Corrected effective value\s*110\.000000/);
    expect(
      screen.getByText("Server-authoritative affected calculations"),
    ).toBeInTheDocument();
    expect(screen.getByText("POST_ISSUANCE_ADJUSTMENT")).toBeInTheDocument();
    expect(result).toHaveTextContent("125 USD cents");
    expect(result).toHaveTextContent("10000000-0000-4000-8000-000000000024");
  });

  it("correction C preserves correction input and idempotency after conflict", async () => {
    const client = api();
    vi.mocked(client.correctReading).mockRejectedValue(
      new UtilityConflictError(["expected_version"], "conflict-ref"),
    );
    await loadWorkspace(client);
    fireEvent.click(
      screen.getByRole("button", {
        name: "Correct Reading from 2026-07-31 for Meter ELEC-301",
      }),
    );
    fireEvent.change(screen.getByLabelText("Corrected value"), {
      target: { value: "110" },
    });
    fireEvent.change(screen.getByLabelText("Correction reason"), {
      target: { value: "Verified photograph" },
    });
    fireEvent.change(screen.getByLabelText("Authorization reference"), {
      target: { value: "approval-2" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Review Reading correction" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Confirm and append correction" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Reload before retrying",
    );
    expect(screen.getByLabelText("Corrected value")).toHaveValue(110);
    expect(screen.getByLabelText("Correction reason")).toHaveValue(
      "Verified photograph",
    );
    expect(screen.getByLabelText("Authorization reference")).toHaveValue(
      "approval-2",
    );
    const firstKey = vi.mocked(client.correctReading).mock.calls[0]?.[2];
    fireEvent.click(
      screen.getByRole("button", { name: "Confirm and append correction" }),
    );
    await waitFor(() => {
      expect(client.correctReading).toHaveBeenCalledTimes(2);
    });
    expect(vi.mocked(client.correctReading).mock.calls[1]?.[2]).toBe(firstKey);
  });
});
