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
  UtilityClientError,
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

function batchSection(): HTMLElement {
  const section = screen.getByRole("heading", {
    name: "Bounded bulk Reading entry",
  }).parentElement;
  if (section === null) throw new Error("Batch section missing");
  return section;
}

function fillBatchRow(
  section: HTMLElement,
  index: number,
  values: {
    meterId: string;
    version: string;
    readingDate: string;
    readingValue: string;
    evidence: string;
  },
) {
  const fieldset = section.querySelectorAll("fieldset")[index];
  if (fieldset === undefined) throw new Error("Batch row missing");
  const [meter, version, readingDate, readingValue, evidence] =
    fieldset.querySelectorAll("input");
  if (
    meter === undefined ||
    version === undefined ||
    readingDate === undefined ||
    readingValue === undefined ||
    evidence === undefined
  ) {
    throw new Error("Batch controls missing");
  }
  fireEvent.change(meter, { target: { value: values.meterId } });
  fireEvent.change(version, { target: { value: values.version } });
  fireEvent.change(readingDate, { target: { value: values.readingDate } });
  fireEvent.change(readingValue, { target: { value: values.readingValue } });
  fireEvent.change(evidence, { target: { value: values.evidence } });
}

describe("UtilityManagement", () => {
  it("TEST-FE-217 renders Meter, corrected Reading, and Rate evidence", async () => {
    const client = api();
    await loadWorkspace(client);
    expect(screen.getByText("105.000000 kWh")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Validated by 10000000-0000-4000-8000-000000000015 at 2026-07-31T12:00:00Z",
      ),
    ).toBeInTheDocument();
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
    const partialCall = vi.mocked(client.recordBatch).mock.calls[0];
    expect(partialCall?.[1]).toBe("PARTIAL");
    expect(partialCall?.[2]).toHaveLength(1);
    expect(partialCall?.[2][0]?.meter_id).toBe(meterId);
    expect(partialCall?.[2][0]?.idempotency_key).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );
    expect(partialCall?.[3]).toBeUndefined();
    expect(
      await screen.findByRole("cell", { name: "SUCCEEDED" }),
    ).toBeInTheDocument();
  });

  it("TEST-FE-231 submits ATOMIC_ALL with one envelope UUID and ordered item results", async () => {
    const client = api();
    const validated = snapshot().readings[meterId]?.[0];
    if (validated === undefined) throw new Error("Reading fixture missing");
    vi.mocked(client.recordBatch).mockImplementation(
      (_targetPropertyId, _mode, items) =>
        Promise.resolve(
          items.map((item, index) => ({
            index,
            idempotency_key: item.idempotency_key,
            status: "SUCCEEDED",
            reading: {
              ...validated,
              id: `10000000-0000-4000-8000-00000000003${String(index)}`,
              reading_date: item.reading.reading_date,
              effective_value: item.reading.reading_value,
            },
            error: null,
          })),
        ),
    );
    await loadWorkspace(client);
    const batch = batchSection();
    fireEvent.change(screen.getByLabelText("Batch behavior"), {
      target: { value: "ATOMIC_ALL" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add Reading row" }));
    fillBatchRow(batch, 0, {
      meterId,
      version: "2",
      readingDate: "2026-08-31",
      readingValue: "151",
      evidence: "Photo 8",
    });
    fillBatchRow(batch, 1, {
      meterId,
      version: "3",
      readingDate: "2026-09-30",
      readingValue: "205",
      evidence: "Photo 9",
    });

    fireEvent.click(
      screen.getByRole("button", { name: "Submit Reading batch" }),
    );

    await waitFor(() => {
      expect(client.recordBatch).toHaveBeenCalledTimes(1);
    });
    const atomicCall = vi.mocked(client.recordBatch).mock.calls[0];
    expect(atomicCall?.[0]).toBe(propertyId);
    expect(atomicCall?.[1]).toBe("ATOMIC_ALL");
    expect(atomicCall?.[2].map((item) => item.reading.reading_value)).toEqual([
      "151",
      "205",
    ]);
    expect(atomicCall?.[2].map((item) => item.idempotency_key)).toEqual([
      expect.stringMatching(
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
      ),
      expect.stringMatching(
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
      ),
    ]);
    expect(atomicCall?.[2][0]?.idempotency_key).not.toBe(
      atomicCall?.[2][1]?.idempotency_key,
    );
    expect(atomicCall?.[3]).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );
    const results = await screen.findByRole("table", {
      name: "Reading batch item results",
    });
    const rows = results.querySelectorAll("tbody tr");
    expect(rows[0]).toHaveTextContent("1SUCCEEDED151");
    expect(rows[1]).toHaveTextContent("2SUCCEEDED205");
  });

  it("TEST-FE-232 retains equivalent ATOMIC_ALL replay identity and changes it with input", async () => {
    const client = api();
    vi.mocked(client.recordBatch)
      .mockRejectedValueOnce(new UtilityClientError())
      .mockRejectedValueOnce(
        new UtilityConflictError(["items[0].reading_value"], "atomic-conflict"),
      )
      .mockRejectedValueOnce(new UtilityClientError());
    await loadWorkspace(client);
    const batch = batchSection();
    fireEvent.change(screen.getByLabelText("Batch behavior"), {
      target: { value: "ATOMIC_ALL" },
    });
    fillBatchRow(batch, 0, {
      meterId,
      version: "2",
      readingDate: "2026-08-31",
      readingValue: "150",
      evidence: "Photo 8",
    });
    const submit = screen.getByRole("button", { name: "Submit Reading batch" });

    fireEvent.click(submit);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The ATOMIC_ALL batch was not completed",
    );
    await waitFor(() => {
      expect(submit).not.toBeDisabled();
    });

    const evidence = batch
      .querySelectorAll("fieldset")[0]
      ?.querySelectorAll("input")[4];
    if (evidence === undefined)
      throw new Error("Batch evidence control missing");
    fireEvent.change(evidence, { target: { value: "  Photo 8  " } });
    fireEvent.click(submit);
    await waitFor(() => {
      expect(client.recordBatch).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "atomic-conflict",
    );
    await waitFor(() => {
      expect(submit).not.toBeDisabled();
    });

    const readingValue = batch
      .querySelectorAll("fieldset")[0]
      ?.querySelectorAll("input")[3];
    if (readingValue === undefined)
      throw new Error("Batch value control missing");
    fireEvent.change(readingValue, { target: { value: "151" } });
    fireEvent.click(submit);
    await waitFor(() => {
      expect(client.recordBatch).toHaveBeenCalledTimes(3);
    });

    const calls = vi.mocked(client.recordBatch).mock.calls;
    const firstEnvelopeKey = calls[0]?.[3];
    const equivalentEnvelopeKey = calls[1]?.[3];
    const changedEnvelopeKey = calls[2]?.[3];
    const firstItemKey = calls[0]?.[2][0]?.idempotency_key;
    const equivalentItemKey = calls[1]?.[2][0]?.idempotency_key;
    const changedItemKey = calls[2]?.[2][0]?.idempotency_key;
    expect(firstEnvelopeKey).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );
    expect(equivalentEnvelopeKey).toBe(firstEnvelopeKey);
    expect(equivalentItemKey).toBe(firstItemKey);
    expect(changedEnvelopeKey).not.toBe(firstEnvelopeKey);
    expect(changedItemKey).not.toBe(firstItemKey);
    expect(calls.map((call) => call[1])).toEqual([
      "ATOMIC_ALL",
      "ATOMIC_ALL",
      "ATOMIC_ALL",
    ]);
    expect(calls.every((call) => call[1] !== "PARTIAL")).toBe(true);
    expect(client.load).toHaveBeenCalledTimes(1);
  });

  it("TEST-FE-233 preserves ATOMIC_ALL success when history refresh fails", async () => {
    const client = api();
    const original = snapshot();
    const validated = original.readings[meterId]?.[0];
    if (validated === undefined) throw new Error("Reading fixture missing");
    vi.mocked(client.load)
      .mockResolvedValueOnce(original)
      .mockRejectedValueOnce(new UtilityClientError())
      .mockResolvedValueOnce(original);
    vi.mocked(client.recordBatch).mockImplementation(
      (_targetPropertyId, _mode, items) =>
        Promise.resolve(
          items.map((item, index) => ({
            index,
            idempotency_key: item.idempotency_key,
            status: "SUCCEEDED",
            reading: {
              ...validated,
              id: `10000000-0000-4000-8000-00000000004${String(index)}`,
              reading_date: item.reading.reading_date,
              effective_value: item.reading.reading_value,
            },
            error: null,
          })),
        ),
    );
    await loadWorkspace(client);
    const batch = batchSection();
    fireEvent.change(screen.getByLabelText("Batch behavior"), {
      target: { value: "ATOMIC_ALL" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add Reading row" }));
    fillBatchRow(batch, 0, {
      meterId,
      version: "2",
      readingDate: "2026-08-31",
      readingValue: "151",
      evidence: "Photo 8",
    });
    fillBatchRow(batch, 1, {
      meterId,
      version: "3",
      readingDate: "2026-09-30",
      readingValue: "205",
      evidence: "Photo 9",
    });

    fireEvent.click(
      screen.getByRole("button", { name: "Submit Reading batch" }),
    );

    const refreshAlert = await screen.findByRole("alert");
    expect(refreshAlert).toHaveTextContent(
      "The ATOMIC_ALL batch completed successfully, but Utility history could not be refreshed.",
    );
    expect(refreshAlert).not.toHaveTextContent(
      /not completed|no row is retained|roll(?:ed)? back|rollback|PARTIAL/i,
    );
    const results = screen.getByRole("table", {
      name: "Reading batch item results",
    });
    const rows = results.querySelectorAll("tbody tr");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("1SUCCEEDED151");
    expect(rows[1]).toHaveTextContent("2SUCCEEDED205");
    expect(client.recordBatch).toHaveBeenCalledTimes(1);
    const atomicCall = vi.mocked(client.recordBatch).mock.calls[0];
    expect(atomicCall?.[1]).toBe("ATOMIC_ALL");
    expect(atomicCall?.[3]).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );
    expect(client.load).toHaveBeenCalledTimes(2);

    fireEvent.click(
      screen.getByRole("button", { name: "Load Utility workspace" }),
    );
    await screen.findByText("Complete Utility history loaded.");

    expect(client.load).toHaveBeenCalledTimes(3);
    expect(client.recordBatch).toHaveBeenCalledTimes(1);
    expect(rows[0]).toHaveTextContent("1SUCCEEDED151");
    expect(rows[1]).toHaveTextContent("2SUCCEEDED205");
  });

  it("TEST-FE-234 reports resolved ATOMIC_ALL rollback when history refresh fails", async () => {
    const client = api();
    const original = snapshot();
    vi.mocked(client.load)
      .mockResolvedValueOnce(original)
      .mockRejectedValueOnce(new UtilityClientError())
      .mockResolvedValueOnce(original);
    vi.mocked(client.recordBatch).mockImplementation(
      (_targetPropertyId, _mode, items) =>
        Promise.resolve([
          {
            index: 0,
            idempotency_key: items[0]?.idempotency_key ?? "missing-key-0",
            status: "FAILED",
            reading: null,
            error: { code: "ATOMIC_ROLLBACK" },
          },
          {
            index: 1,
            idempotency_key: items[1]?.idempotency_key ?? "missing-key-1",
            status: "FAILED",
            reading: null,
            error: { code: "NOT_FOUND" },
          },
        ]),
    );
    await loadWorkspace(client);
    const batch = batchSection();
    fireEvent.change(screen.getByLabelText("Batch behavior"), {
      target: { value: "ATOMIC_ALL" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add Reading row" }));
    fillBatchRow(batch, 0, {
      meterId,
      version: "2",
      readingDate: "2026-08-31",
      readingValue: "151",
      evidence: "Photo 8",
    });
    fillBatchRow(batch, 1, {
      meterId: "10000000-0000-4000-8000-000000000099",
      version: "1",
      readingDate: "2026-09-30",
      readingValue: "205",
      evidence: "Photo 9",
    });

    fireEvent.click(
      screen.getByRole("button", { name: "Submit Reading batch" }),
    );

    const refreshAlert = await screen.findByRole("alert");
    expect(refreshAlert).toHaveTextContent(
      "The ATOMIC_ALL batch failed and was rolled back, and Utility history also could not be refreshed.",
    );
    expect(refreshAlert).not.toHaveTextContent(
      /completed successfully|PARTIAL/i,
    );
    const results = screen.getByRole("table", {
      name: "Reading batch item results",
    });
    const rows = results.querySelectorAll("tbody tr");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("1FAILEDATOMIC_ROLLBACK");
    expect(rows[1]).toHaveTextContent("2FAILEDNOT_FOUND");
    expect(client.recordBatch).toHaveBeenCalledTimes(1);
    const atomicCall = vi.mocked(client.recordBatch).mock.calls[0];
    expect(atomicCall?.[1]).toBe("ATOMIC_ALL");
    expect(atomicCall?.[3]).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );
    expect(vi.mocked(client.recordBatch).mock.calls).not.toContainEqual(
      expect.arrayContaining([propertyId, "PARTIAL"]),
    );
    expect(client.load).toHaveBeenCalledTimes(2);

    fireEvent.click(
      screen.getByRole("button", { name: "Load Utility workspace" }),
    );
    await screen.findByText("Complete Utility history loaded.");

    expect(client.load).toHaveBeenCalledTimes(3);
    expect(client.recordBatch).toHaveBeenCalledTimes(1);
    expect(rows[0]).toHaveTextContent("1FAILEDATOMIC_ROLLBACK");
    expect(rows[1]).toHaveTextContent("2FAILEDNOT_FOUND");

    cleanup();
    const mixedClient = api();
    const validated = original.readings[meterId]?.[0];
    if (validated === undefined) throw new Error("Reading fixture missing");
    vi.mocked(mixedClient.load)
      .mockResolvedValueOnce(original)
      .mockRejectedValueOnce(new UtilityClientError());
    vi.mocked(mixedClient.recordBatch).mockImplementation(
      (_targetPropertyId, _mode, items) =>
        Promise.resolve([
          {
            index: 0,
            idempotency_key: items[0]?.idempotency_key ?? "missing-key-0",
            status: "SUCCEEDED",
            reading: validated,
            error: null,
          },
          {
            index: 1,
            idempotency_key: items[1]?.idempotency_key ?? "missing-key-1",
            status: "FAILED",
            reading: null,
            error: { code: "NOT_FOUND" },
          },
        ]),
    );
    await loadWorkspace(mixedClient);
    const mixedBatch = batchSection();
    fireEvent.change(screen.getByLabelText("Batch behavior"), {
      target: { value: "ATOMIC_ALL" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add Reading row" }));
    fillBatchRow(mixedBatch, 0, {
      meterId,
      version: "2",
      readingDate: "2026-08-31",
      readingValue: "151",
      evidence: "Photo 8",
    });
    fillBatchRow(mixedBatch, 1, {
      meterId,
      version: "3",
      readingDate: "2026-09-30",
      readingValue: "205",
      evidence: "Photo 9",
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Submit Reading batch" }),
    );

    const mixedAlert = await screen.findByRole("alert");
    expect(mixedAlert).toHaveTextContent(
      "The ATOMIC_ALL batch failed and was rolled back, and Utility history also could not be refreshed.",
    );
    expect(mixedAlert).not.toHaveTextContent(/completed successfully|PARTIAL/i);
    const mixedRows = screen
      .getByRole("table", { name: "Reading batch item results" })
      .querySelectorAll("tbody tr");
    expect(mixedRows[0]).toHaveTextContent("1SUCCEEDED105.000000");
    expect(mixedRows[1]).toHaveTextContent("2FAILEDNOT_FOUND");
    expect(mixedClient.recordBatch).toHaveBeenCalledTimes(1);
    expect(vi.mocked(mixedClient.recordBatch).mock.calls[0]?.[1]).toBe(
      "ATOMIC_ALL",
    );
  });

  it("TEST-FE-230 renders mixed pending and validated history without pending correction", async () => {
    const client = api();
    const mixed = snapshot();
    const validated = mixed.readings[meterId]?.[0];
    if (validated === undefined)
      throw new Error("Validated Reading fixture missing");
    mixed.readings[meterId] = [
      {
        ...validated,
        id: "10000000-0000-4000-8000-000000000025",
        reading_date: "2026-08-31",
        original_value: "150.000000",
        effective_value: "150.000000",
        validated: false,
        validated_at: null,
        validated_by: null,
        version: 1,
        corrections: [],
      },
      validated,
    ];
    vi.mocked(client.load).mockResolvedValue(mixed);

    await loadWorkspace(client);

    expect(screen.getByText("Pending validation")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Validated by 10000000-0000-4000-8000-000000000015 at 2026-07-31T12:00:00Z",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Correction unavailable while pending"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "Correct Reading from 2026-08-31 for Meter ELEC-301",
      }),
    ).not.toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: /Correct Reading from/ }),
    ).toHaveLength(1);
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

  it("TEST-FE-225 binds per-row correction review and renders server impact evidence", async () => {
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
    expect(sourceRegion).toHaveTextContent("100.000000 kWh");
    expect(sourceRegion).toHaveTextContent("105.000000 kWh");
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
    ).toHaveTextContent("105.000000 kWh to 110 kWh");

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

  it("TEST-FE-226 preserves correction input and idempotency after conflict", async () => {
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
