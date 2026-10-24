import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ConfigurationManagement } from "./ConfigurationManagement";
import {
  EffectiveConfigurationApi,
  EffectiveConfigurationConflictError,
  EffectiveConfigurationError,
  EffectiveConfigurationSnapshot,
  EffectiveConfigurationUnavailableError,
} from "./configurationClient";

const propertyId = "10000000-0000-4000-8000-000000000028";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function snapshot(
  capabilities: Partial<EffectiveConfigurationSnapshot["capabilities"]> = {},
): EffectiveConfigurationSnapshot {
  return {
    capabilities: {
      read: true,
      manage_service_rates: false,
      manage_utility_rates: false,
      manage_exchange_rates: false,
      ...capabilities,
    },
    configuredServices: [
      {
        id: "30000000-0000-4000-8000-000000000028",
        property_id: propertyId,
        service_code: "TRASH_COLLECTION",
        display_name: "Trash Collection",
      },
    ],
    configuredServiceNextCursor: null,
    serviceRates: [
      {
        id: "20000000-0000-4000-8000-000000000028",
        property_service_id: "30000000-0000-4000-8000-000000000028",
        service_code: "TRASH_COLLECTION",
        display_name: "Trash Collection",
        monthly_rate_usd_cents: 1250,
        effective_date: "2026-09-01",
        source_memo: "Approved",
      },
    ],
    serviceNextCursor: null,
    utilityRates: [],
    utilityNextCursor: null,
    exchangeRates: [],
    exchangeNextCursor: null,
  };
}

function api(value: EffectiveConfigurationSnapshot): EffectiveConfigurationApi {
  return {
    load: vi.fn().mockResolvedValue(value),
    loadConfiguredServices: vi.fn(),
    loadServiceRates: vi.fn(),
    loadUtilityRates: vi.fn(),
    loadExchangeRates: vi.fn(),
    createServiceRate: vi.fn().mockResolvedValue(value.serviceRates[0]),
    createUtilityRate: vi.fn(),
    confirmExchangeRate: vi.fn(),
  };
}

describe("ConfigurationManagement", () => {
  it("TEST-FE-161 renders bounded protected history and hides unauthorized controls", async () => {
    const client = api(snapshot());
    render(<ConfigurationManagement api={client} propertyId={propertyId} />);
    fireEvent.click(
      screen.getByRole("button", {
        name: "Load effective-dated configuration",
      }),
    );
    expect(
      await screen.findByRole("cell", {
        name: "Trash Collection (TRASH_COLLECTION)",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("12.50")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Append Service rate" }),
    ).not.toBeInTheDocument();
    expect(client.load).toHaveBeenCalledWith(propertyId);
  });

  it("TEST-FE-162 submits an authorized effective-dated Service rate and reloads history", async () => {
    const value = snapshot({ manage_service_rates: true });
    const client = api(value);
    render(<ConfigurationManagement api={client} propertyId={propertyId} />);
    fireEvent.click(
      screen.getByRole("button", {
        name: "Load effective-dated configuration",
      }),
    );
    await screen.findByRole("button", { name: "Append Service rate" });
    fireEvent.change(screen.getByLabelText("Configured Service"), {
      target: { value: value.serviceRates[0]?.property_service_id ?? "" },
    });
    fireEvent.change(screen.getByLabelText("Monthly rate in USD cents"), {
      target: { value: "1500" },
    });
    fireEvent.change(
      screen.getByLabelText("Effective date", {
        selector: "input[name='service-effective-date']",
      }),
      { target: { value: "2026-10-01" } },
    );
    const serviceForm = screen
      .getByRole("button", { name: "Append Service rate" })
      .closest("form");
    if (serviceForm === null) throw new Error("Service form is missing");
    fireEvent.submit(serviceForm);
    await waitFor(() => {
      expect(client.createServiceRate).toHaveBeenCalledWith(
        propertyId,
        expect.objectContaining({
          monthly_rate_usd_cents: 1500,
          effective_date: "2026-10-01",
        }),
        expect.any(String),
      );
    });
    expect(
      await screen.findByText("Service rate appended to protected history."),
    ).toHaveAttribute("role", "status");
  });

  it("TEST-FE-163 exposes Utility and exchange workflows only with exact capabilities", async () => {
    const client = api(
      snapshot({ manage_utility_rates: true, manage_exchange_rates: true }),
    );
    render(<ConfigurationManagement api={client} propertyId={propertyId} />);
    fireEvent.click(
      screen.getByRole("button", {
        name: "Load effective-dated configuration",
      }),
    );
    expect(
      await screen.findByRole("button", { name: "Append Utility rate" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Confirm and calculate exchange rate",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Append Service rate" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/server applies 0.5%/i)).toBeInTheDocument();
  });

  it("TEST-FE-164 announces conflicts as accessible failures without discarding history", async () => {
    const value = snapshot({ manage_service_rates: true });
    const client = api(value);
    vi.mocked(client.createServiceRate).mockRejectedValue(
      new EffectiveConfigurationConflictError(
        ["effective_date"],
        "configuration-conflict-reference",
      ),
    );
    render(<ConfigurationManagement api={client} propertyId={propertyId} />);
    fireEvent.click(
      screen.getByRole("button", {
        name: "Load effective-dated configuration",
      }),
    );
    await screen.findByRole("button", { name: "Append Service rate" });
    fireEvent.change(screen.getByLabelText("Configured Service"), {
      target: { value: value.serviceRates[0]?.property_service_id ?? "" },
    });
    fireEvent.change(screen.getByLabelText("Monthly rate in USD cents"), {
      target: { value: "1500" },
    });
    fireEvent.change(
      screen.getByLabelText("Effective date", {
        selector: "input[name='service-effective-date']",
      }),
      { target: { value: "2026-10-01" } },
    );
    const serviceForm = screen
      .getByRole("button", { name: "Append Service rate" })
      .closest("form");
    if (serviceForm === null) throw new Error("Service form is missing");
    fireEvent.submit(serviceForm);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Reload before retrying");
    expect(alert).toHaveTextContent("configuration-conflict-reference");
    expect(alert).toHaveTextContent("effective_date");
    expect(
      screen.getByRole("cell", { name: "Trash Collection (TRASH_COLLECTION)" }),
    ).toBeInTheDocument();
  });

  it("TEST-FE-178 announces a safe authorization correlation reference", async () => {
    const client = api(snapshot());
    vi.mocked(client.load).mockRejectedValue(
      new EffectiveConfigurationUnavailableError(
        ["property_id"],
        "configuration-authorization-reference",
      ),
    );
    render(<ConfigurationManagement api={client} propertyId={propertyId} />);
    fireEvent.click(
      screen.getByRole("button", {
        name: "Load effective-dated configuration",
      }),
    );
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "not available for this session and Property",
    );
    expect(alert).toHaveTextContent("configuration-authorization-reference");
    expect(alert).toHaveTextContent("property_id");
  });

  it("TEST-FE-170 reaches exact configuration capabilities without Property-management access", async () => {
    const client = api(snapshot());
    render(<ConfigurationManagement api={client} />);
    fireEvent.change(
      screen.getByLabelText("Effective configuration Property identifier"),
      {
        target: { value: propertyId },
      },
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Load effective-dated configuration",
      }),
    );
    await screen.findByText("12.50");
    expect(client.load).toHaveBeenCalledWith(propertyId);
  });

  it("TEST-FE-171 preserves one idempotency key across a lost-response retry", async () => {
    const value = snapshot({ manage_service_rates: true });
    const client = api(value);
    const existingServiceRate = value.serviceRates[0];
    if (existingServiceRate === undefined)
      throw new Error("Service rate is missing");
    vi.mocked(client.createServiceRate)
      .mockRejectedValueOnce(new Error("response lost"))
      .mockResolvedValueOnce(existingServiceRate);
    vi.spyOn(crypto, "randomUUID").mockReturnValue(
      "40000000-0000-4000-8000-000000000028",
    );
    render(<ConfigurationManagement api={client} propertyId={propertyId} />);
    fireEvent.click(
      screen.getByRole("button", {
        name: "Load effective-dated configuration",
      }),
    );
    await screen.findByRole("button", { name: "Append Service rate" });
    fireEvent.change(screen.getByLabelText("Configured Service"), {
      target: { value: value.configuredServices[0]?.id ?? "" },
    });
    fireEvent.change(screen.getByLabelText("Monthly rate in USD cents"), {
      target: { value: "1500" },
    });
    fireEvent.change(
      screen.getByLabelText("Effective date", {
        selector: "input[name='service-effective-date']",
      }),
      { target: { value: "2026-10-01" } },
    );
    const button = screen.getByRole("button", { name: "Append Service rate" });
    const form = button.closest("form");
    if (form === null) throw new Error("Service form is missing");
    fireEvent.submit(form);
    await screen.findByRole("alert");
    fireEvent.submit(form);
    await waitFor(() => {
      expect(client.createServiceRate).toHaveBeenCalledTimes(2);
    });
    expect(vi.mocked(client.createServiceRate).mock.calls[0]?.[2]).toBe(
      vi.mocked(client.createServiceRate).mock.calls[1]?.[2],
    );
  });

  it("TEST-FE-172 serializes browser-local Cambodia timestamps with an explicit offset", async () => {
    const value = snapshot({ manage_utility_rates: true });
    const client = api(value);
    vi.mocked(client.createUtilityRate).mockResolvedValue({
      id: "70000000-0000-4000-8000-000000000028",
      utility_type: "WATER",
      measurement_unit_code: "M3",
      rate_usd_per_unit: "0.5",
      effective_date: "2026-10-01",
      notice_at: "2026-09-01T09:00:00+07:00",
      notice_evidence: "Notice",
      source_memo: null,
    });
    render(<ConfigurationManagement api={client} propertyId={propertyId} />);
    fireEvent.click(
      screen.getByRole("button", {
        name: "Load effective-dated configuration",
      }),
    );
    await screen.findByRole("button", { name: "Append Utility rate" });
    fireEvent.change(screen.getByLabelText("Utility type"), {
      target: { value: "WATER" },
    });
    // DL-071 answer 9: the unit follows the Utility Type (m³ for water).
    expect(
      screen.getAllByText("Electricity is measured in kWh and water in m³.")
        .length,
    ).toBeGreaterThan(0);
    fireEvent.change(screen.getByLabelText("USD rate per unit"), {
      target: { value: "0.5" },
    });
    fireEvent.change(
      screen.getByLabelText("Effective date", {
        selector: "input[name='utility-effective-date']",
      }),
      { target: { value: "2026-10-01" } },
    );
    fireEvent.change(screen.getByLabelText("Notice timestamp"), {
      target: { value: "2026-09-01T09:00" },
    });
    fireEvent.change(screen.getByLabelText("Advance-notice evidence"), {
      target: { value: "Notice" },
    });
    const utilityForm = screen
      .getByRole("button", { name: "Append Utility rate" })
      .closest("form");
    if (utilityForm === null) throw new Error("Utility form is missing");
    fireEvent.submit(utilityForm);
    await waitFor(() => {
      expect(client.createUtilityRate).toHaveBeenCalledWith(
        propertyId,
        expect.objectContaining({ notice_at: "2026-09-01T09:00:00+07:00" }),
        expect.any(String),
      );
    });
  });

  it("TEST-FE-173 submits bounded manual fallback only with explicit source failure evidence", async () => {
    const value = snapshot({ manage_exchange_rates: true });
    const client = api(value);
    vi.mocked(client.confirmExchangeRate).mockResolvedValue({
      id: "80000000-0000-4000-8000-000000000028",
      reference_rate_khr_per_usd: "4062.500000",
      system_rate_khr_per_usd: 4083,
      rate_source: "ABA_EQUIVALENT_MANUAL",
      source_reference: "ABA evidence 28",
      applicable_at: "2026-08-25T10:00:00+07:00",
      usd_amount_cents: 10001,
      unrounded_payable_khr: "408340.83",
      payable_khr: 408341,
      fallback_reason: "Automatic source timed out",
    });
    render(<ConfigurationManagement api={client} propertyId={propertyId} />);
    fireEvent.click(
      screen.getByRole("button", {
        name: "Load effective-dated configuration",
      }),
    );
    await screen.findByRole("button", {
      name: "Confirm and calculate exchange rate",
    });
    fireEvent.change(screen.getByLabelText("Rate source"), {
      target: { value: "ABA_EQUIVALENT_MANUAL" },
    });
    fireEvent.change(
      screen.getByLabelText("ABA-equivalent reference sell rate"),
      {
        target: { value: "4062.5" },
      },
    );
    fireEvent.change(screen.getByLabelText("Source evidence reference"), {
      target: { value: "ABA evidence 28" },
    });
    fireEvent.change(screen.getByLabelText("Automatic-source failure reason"), {
      target: { value: "Automatic source timed out" },
    });
    fireEvent.change(screen.getByLabelText("Applicable timestamp"), {
      target: { value: "2026-08-25T10:00" },
    });
    fireEvent.change(screen.getByLabelText("Payment amount in USD cents"), {
      target: { value: "10001" },
    });
    const exchangeForm = screen
      .getByRole("button", { name: "Confirm and calculate exchange rate" })
      .closest("form");
    if (exchangeForm === null) throw new Error("Exchange form is missing");
    fireEvent.submit(exchangeForm);
    await waitFor(() => {
      expect(client.confirmExchangeRate).toHaveBeenCalledWith(
        propertyId,
        expect.objectContaining({
          automatic_source_unavailable: true,
          fallback_reason: "Automatic source timed out",
          applicable_at: "2026-08-25T10:00:00+07:00",
        }),
        expect.any(String),
      );
    });
  });

  it("TEST-FE-174 loads older protected history through the returned cursor", async () => {
    const value = { ...snapshot(), serviceNextCursor: "older-service-cursor" };
    const client = api(value);
    const currentRate = value.serviceRates[0];
    if (currentRate === undefined) throw new Error("Service rate is missing");
    vi.mocked(client.loadServiceRates).mockResolvedValue({
      items: [
        {
          ...currentRate,
          id: "90000000-0000-4000-8000-000000000028",
          effective_date: "2026-01-01",
        },
      ],
      nextCursor: null,
    });
    render(<ConfigurationManagement api={client} propertyId={propertyId} />);
    fireEvent.click(
      screen.getByRole("button", {
        name: "Load effective-dated configuration",
      }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Load older Service rates" }),
    );
    await screen.findByRole("cell", { name: "2026-01-01" });
    expect(client.loadServiceRates).toHaveBeenCalledWith(
      propertyId,
      "older-service-cursor",
    );
  });

  it("TEST-FE-176 retains a successful append when the history refresh fails", async () => {
    const value = snapshot({ manage_service_rates: true });
    const client = api(value);
    vi.mocked(client.load)
      .mockResolvedValueOnce(value)
      .mockRejectedValueOnce(
        new EffectiveConfigurationError(
          undefined,
          ["effective_date"],
          "configuration-refresh-reference",
        ),
      );
    render(<ConfigurationManagement api={client} propertyId={propertyId} />);
    fireEvent.click(
      screen.getByRole("button", {
        name: "Load effective-dated configuration",
      }),
    );
    await screen.findByRole("button", { name: "Append Service rate" });
    fireEvent.change(screen.getByLabelText("Configured Service"), {
      target: { value: value.configuredServices[0]?.id ?? "" },
    });
    fireEvent.change(screen.getByLabelText("Monthly rate in USD cents"), {
      target: { value: "1500" },
    });
    fireEvent.change(
      screen.getByLabelText("Effective date", {
        selector: "input[name='service-effective-date']",
      }),
      { target: { value: "2026-10-01" } },
    );
    const form = screen
      .getByRole("button", { name: "Append Service rate" })
      .closest("form");
    if (form === null) throw new Error("Service form is missing");
    fireEvent.submit(form);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Service rate appended");
    expect(alert).toHaveTextContent("saved result is retained");
    expect(alert).toHaveTextContent("configuration-refresh-reference");
    expect(alert).toHaveTextContent("effective_date");
    expect(alert).not.toHaveTextContent("change was not completed");
  });

  it("TEST-FE-177 follows configured-Service pagination without losing selections", async () => {
    const value = {
      ...snapshot({ manage_service_rates: true }),
      configuredServiceNextCursor: "configured-service-next",
    };
    const client = api(value);
    vi.mocked(client.loadConfiguredServices).mockResolvedValue({
      items: [
        {
          id: "30000000-0000-4000-8000-000000000029",
          property_id: propertyId,
          service_code: "WIFI",
          display_name: "Wi-Fi",
        },
      ],
      nextCursor: null,
    });
    render(<ConfigurationManagement api={client} propertyId={propertyId} />);
    fireEvent.click(
      screen.getByRole("button", {
        name: "Load effective-dated configuration",
      }),
    );
    const pagination = await screen.findByRole("button", {
      name: "Load more configured Services",
    });
    fireEvent.change(screen.getByLabelText("Configured Service"), {
      target: { value: value.configuredServices[0]?.id ?? "" },
    });
    fireEvent.change(screen.getByLabelText("Monthly rate in USD cents"), {
      target: { value: "1500" },
    });
    fireEvent.change(
      screen.getByLabelText("Effective date", {
        selector: "input[name='service-effective-date']",
      }),
      { target: { value: "2026-10-01" } },
    );
    fireEvent.click(pagination);
    expect(
      await screen.findByRole("option", { name: "Wi-Fi (WIFI)" }),
    ).toBeInTheDocument();
    expect(client.loadConfiguredServices).toHaveBeenCalledWith(
      propertyId,
      "configured-service-next",
    );
    expect(client.createServiceRate).not.toHaveBeenCalled();
    expect(
      screen.getByRole("option", {
        name: "Trash Collection (TRASH_COLLECTION)",
      }),
    ).toBeInTheDocument();
  });
});
