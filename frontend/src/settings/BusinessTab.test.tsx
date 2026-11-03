import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ExchangeRate } from "../configurationClient";
import {
  type PaymentMethodConfiguration,
  type PropertyBusinessConfiguration,
  PropertyConfigurationError,
  PropertyConfigurationUnavailableError,
  PropertySavedReadFailedError,
} from "../propertyClient";
import { BusinessTab, methodCode, ruleCode } from "./BusinessTab";
import {
  type BusinessRule,
  BusinessSettingsError,
  type InvoiceType,
  type NumberRule,
  ruleValueFromText,
  ruleValueText,
} from "./businessSettingsClient";

afterEach(() => {
  cleanup();
});

const METHODS: PaymentMethodConfiguration[] = [
  { code: "CASH", display_name: "Cash", accepted: true },
  { code: "ABA_PAY", display_name: "ABA PAY", accepted: true },
  { code: "CHEQUE", display_name: "Cheque", accepted: false },
];

const PROPERTY: PropertyBusinessConfiguration = {
  property_id: "property-1",
  name: "CHETANA Parking",
  address_text: "Street 271, Phnom Penh",
  description: "Apartments near Camko",
  business_name: null,
  timezone_name: "Asia/Phnom_Penh",
  payment_methods: METHODS,
  version: 4,
};

const TODAY = "2026-11-03";
const START = {
  effective_from: "2026-01-01",
  reason: "First value",
  created_at: "2026-11-03T00:00:00Z",
};

const RULES: BusinessRule[] = [
  {
    code: "METER_READING_DAY",
    name_en: "Meters read on",
    name_kh: "អានកុងទ័រនៅ",
    value_unit: "DAY_OF_MONTH",
    area: "BILLING",
    used_by_app: false,
    in_force: { value: 24, ...START },
    waiting: null,
    history: [{ value: 24, ...START }],
  },
  {
    code: "LATE_PAYMENT_PERCENT",
    name_en: "Late-payment charge",
    name_kh: "ថ្លៃបង់យឺត",
    value_unit: "PERCENT",
    area: "BILLING",
    used_by_app: true,
    in_force: { value: 1000, ...START },
    waiting: {
      value: 500,
      effective_from: "2026-12-01",
      reason: "Lower",
      created_at: "2026-11-03T01:00:00Z",
    },
    history: [
      { value: 1000, ...START },
      {
        value: 500,
        effective_from: "2026-12-01",
        reason: "Lower",
        created_at: "2026-11-03T01:00:00Z",
      },
    ],
  },
  {
    code: "PRICE_ROUND_UP",
    name_en: "Round prices up to",
    name_kh: "បង្គត់តម្លៃឡើង",
    value_unit: "USD_CENTS",
    area: "PRICES",
    used_by_app: false,
    in_force: { value: 10, ...START },
    waiting: null,
    history: [{ value: 10, ...START }],
  },
  {
    code: "PRODUCT_MAX_MARK_UP",
    name_en: "Highest mark-up",
    name_kh: "ការបន្ថែមខ្ពស់បំផុត",
    value_unit: "PERCENT",
    area: "PRICES",
    used_by_app: false,
    in_force: null,
    waiting: null,
    history: [],
  },
];

const NUMBERS: NumberRule[] = [
  {
    document_type: "INVOICE",
    letters: "INV",
    format: "INVyy000n",
    year: 2026,
    last_number: 124,
    next_number: "INV260125",
  },
  {
    document_type: "RECEIPT",
    letters: "RCP",
    format: "RCPyy000n",
    year: 2026,
    last_number: 61,
    next_number: "RCP260062",
  },
];

const TYPES: InvoiceType[] = [
  {
    code: "FIRST_RENT",
    name_en: "First Rent",
    name_kh: "ថ្លៃឈ្នួលដំបូង",
    late_payment: true,
    version: 1,
  },
  {
    code: "UTILITIES",
    name_en: "Utilities",
    name_kh: "ថ្លៃទឹកភ្លើង",
    late_payment: false,
    version: 2,
  },
];

function rate(extra: Partial<ExchangeRate>): ExchangeRate {
  return {
    id: "rate-1",
    reference_rate_khr_per_usd: "4100",
    system_rate_khr_per_usd: 4121,
    rate_source: "ABA_AUTOMATIC",
    source_reference: null,
    applicable_at: "2026-10-20T02:00:00Z",
    usd_amount_cents: 10000,
    unrounded_payable_khr: "412100",
    payable_khr: 412100,
    fallback_reason: null,
    ...extra,
  };
}

function apiOf(
  property: () => Promise<PropertyBusinessConfiguration> = () =>
    Promise.resolve(PROPERTY),
) {
  return {
    property: {
      load: vi.fn(property),
      updateSource: vi.fn(() => Promise.resolve(PROPERTY)),
      updatePaymentMethods: vi.fn(() => Promise.resolve(PROPERTY)),
    },
    settings: {
      rules: vi.fn(() => Promise.resolve({ rules: RULES, today: TODAY })),
      setRule: vi.fn(() => Promise.resolve({ rules: RULES, today: TODAY })),
      addRule: vi.fn(() => Promise.resolve({ rules: RULES, today: TODAY })),
      numbers: vi.fn(() => Promise.resolve(NUMBERS)),
      setLetters: vi.fn(() => Promise.resolve(NUMBERS)),
      invoiceTypes: vi.fn(() => Promise.resolve(TYPES)),
      setLatePayment: vi.fn(() => Promise.resolve(TYPES)),
    },
    units: {
      list: vi.fn(() =>
        Promise.resolve({
          items: [
            { unit_id: "u1", for_rent: true },
            { unit_id: "u2", for_rent: false },
            { unit_id: "u3", for_rent: true },
          ] as never[],
          next_cursor: null,
          can_manage: true,
        }),
      ),
    },
    rates: {
      load: vi.fn(() =>
        Promise.resolve({
          capabilities: {
            read: true,
            manage_service_rates: true,
            manage_utility_rates: true,
            manage_exchange_rates: true,
          },
          configuredServices: [],
          configuredServiceNextCursor: null,
          serviceRates: [],
          serviceNextCursor: null,
          utilityRates: [],
          utilityNextCursor: null,
          exchangeRates: [
            rate({}),
            rate({
              id: "rate-2",
              system_rate_khr_per_usd: 4135,
              rate_source: "ABA_EQUIVALENT_MANUAL",
              applicable_at: "2026-10-24T03:00:00Z",
            }),
          ],
          exchangeNextCursor: null,
        }),
      ),
    },
  };
}

function show(api = apiOf(), language: "en" | "km" = "en") {
  render(
    <BusinessTab
      active
      api={api}
      language={language}
      propertyId="property-1"
    />,
  );
  return api;
}

const card = (name: string) => screen.getByRole("region", { name });
const pairs = (region: HTMLElement) =>
  Array.from(region.querySelectorAll("dt")).map(
    (term) =>
      `${term.textContent}: ${term.nextElementSibling?.textContent ?? ""}`,
  );

const rowsOf = (table: HTMLElement) =>
  within(table)
    .getAllByRole("row")
    .slice(1)
    .map((row) =>
      within(row)
        .getAllByRole("cell")
        .map((cell) => cell.textContent)
        .join(" | "),
    );

describe("Settings: Business", () => {
  it("TEST-FE-950 shows the Property with its description and counted Rentable Units, the business name, the business rules by group with Not used yet and a waiting change, the Invoice types, Payment Methods, the latest riel rate, App preferences and the document numbering with the next numbers", async () => {
    const api = show();
    const property = await screen.findByRole("region", { name: "Property" });
    expect(api.property.load).toHaveBeenCalledWith("property-1");
    expect(api.settings.rules).toHaveBeenCalledWith("property-1");
    expect(pairs(property)).toEqual([
      "Property: CHETANA Residence",
      "Description: Apartments near Camko",
      "Address: Street 271, Phnom Penh",
      "Rentable Units: 2Counted from the Units list each time. Never typed.",
    ]);
    expect(pairs(card("Business"))).toEqual([
      "Business name: Not givenCan differ from the property name.",
    ]);
    const rules = card("Business rules");
    expect(
      rowsOf(within(rules).getByRole("table", { name: "Billing" })),
    ).toEqual([
      "Meters read on Not used yet | Day 24 | 01/01/2026 | Edit",
      "Late-payment charge | 10%From 01/12/2026: 5% | 01/01/2026 | Edit",
    ]);
    expect(
      rowsOf(within(rules).getByRole("table", { name: "Prices" })),
    ).toEqual([
      "Round prices up to Not used yet | $0.10 | 01/01/2026 | Edit",
      "Highest mark-up Not used yet | Not set | — | Edit",
    ]);
    expect(within(rules).queryByRole("table", { name: "Ledger" })).toBeNull();
    expect(rowsOf(within(card("Invoice types")).getByRole("table"))).toEqual([
      "First Rent | Yes | Change",
      "Utilities | No | Change",
    ]);
    const methods = card("Payment Methods");
    expect(
      within(methods)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual([
      "CashCASHActiveEdit",
      "ABA PAYABA_PAYActiveEdit",
      "ChequeCHEQUETurned offEdit",
    ]);
    // The newest confirmed rate.
    const fx = card("Riel exchange rate");
    expect(fx.textContent).toContain("4,135 ៛ per $1");
    expect(fx.textContent).toContain("Entered by hand, 24/10/2026 10:00.");
    expect(pairs(card("App preferences"))).toEqual([
      "Time zone: Asia/Phnom_Penh (UTC+7), from the business location (Cambodia)Due dates, expiry and reading days use Phnom Penh time.",
      "Screen language: Chosen on each phone or iPad; the browser remembers it",
    ]);
    expect(
      rowsOf(within(card("Document numbering")).getByRole("table")),
    ).toEqual([
      "Invoice | INVyy000n | INV260125",
      "Receipt | RCPyy000n | RCP260062",
    ]);
    expect(screen.queryByText("Same as this device")).toBeNull();
  });

  it("TEST-FE-951 Edit changes the Property name, description and address; Edit business changes only the business name; a Payment Method is added with a new code, renamed or turned off, but one stays on", async () => {
    const api = show();
    fireEvent.click(
      await screen.findByRole("button", { name: "Edit: Property" }),
    );
    let dialog = screen.getByRole("dialog", { name: "Property" });
    fireEvent.change(within(dialog).getByLabelText(/^Property/), {
      target: { value: " " },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByText("Enter a name.")).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/^Property/), {
      target: { value: "CHETANA Parking 2" },
    });
    fireEvent.change(within(dialog).getByLabelText("Description"), {
      target: { value: " Rooms by the river " },
    });
    fireEvent.change(within(dialog).getByLabelText("Address"), {
      target: { value: "  " },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved.")).toBeTruthy();
    expect(api.property.updateSource).toHaveBeenCalledWith(PROPERTY, {
      name: "CHETANA Residence 2",
      description: "Rooms by the river",
      address_text: null,
    });
    expect(api.property.load).toHaveBeenCalledTimes(2);

    fireEvent.click(screen.getByRole("button", { name: "Edit: Business" }));
    dialog = screen.getByRole("dialog", { name: "Edit business" });
    fireEvent.change(within(dialog).getByLabelText("Business name"), {
      target: { value: " CHETANA Co. " },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(api.property.updateSource).toHaveBeenLastCalledWith(PROPERTY, {
        name: "CHETANA Residence",
        address_text: "Street 271, Phnom Penh",
        business_name: "CHETANA Co.",
      });
    });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });

    fireEvent.click(
      screen.getByRole("button", { name: "Add a method: Payment Methods" }),
    );
    dialog = screen.getByRole("dialog", { name: "Add a method" });
    fireEvent.change(within(dialog).getByLabelText(/^Method name/), {
      target: { value: "cash" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      within(dialog).getByText('"cash" is already in the list.'),
    ).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/^Method name/), {
      target: { value: "Wing transfer" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Wing transfer saved.")).toBeTruthy();
    expect(api.property.updatePaymentMethods).toHaveBeenLastCalledWith(
      PROPERTY,
      [
        ...METHODS,
        {
          code: "WING_TRANSFER",
          display_name: "Wing transfer",
          accepted: true,
        },
      ],
    );

    fireEvent.click(screen.getByRole("button", { name: "Edit: ABA PAY" }));
    dialog = screen.getByRole("dialog", { name: "Edit method" });
    fireEvent.click(within(dialog).getByRole("checkbox"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await screen.findByText("ABA PAY saved.");
    expect(api.property.updatePaymentMethods).toHaveBeenLastCalledWith(
      PROPERTY,
      [METHODS[0], { ...METHODS[1], accepted: false }, METHODS[2]],
    );
    expect(methodCode("ABA pay", METHODS)).toBe("ABA_PAY_2");
    expect(methodCode("ពាក្យ", METHODS)).toBe("METHOD");
  });

  it("TEST-FE-952 a change that met another change says so and reads again; the last method on cannot be turned off; Khmer words; a failed read offers Retry; no right says so; a saved change whose read-back failed still says saved; Save waits for the new version; a Property change drops an old answer", async () => {
    const api = apiOf(() =>
      Promise.resolve({
        ...PROPERTY,
        payment_methods: METHODS.slice(0, 1),
      }),
    );
    api.property.updatePaymentMethods.mockRejectedValueOnce(
      new PropertyConfigurationError(412),
    );
    show(api);
    fireEvent.click(await screen.findByRole("button", { name: "Edit: Cash" }));
    let dialog = screen.getByRole("dialog", { name: "Edit method" });
    fireEvent.click(within(dialog).getByRole("checkbox"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      within(dialog).getByText("Keep at least one method turned on."),
    ).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("checkbox"));
    fireEvent.change(within(dialog).getByLabelText(/^Method name/), {
      target: { value: "Cash (USD or riel)" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText(
        "Someone changed these settings. They were read again; check and try again.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(api.property.load).toHaveBeenCalledTimes(2);
    cleanup();

    show(apiOf(), "km");
    expect(
      await screen.findByRole("region", { name: "ច្បាប់អាជីវកម្ម" }),
    ).toBeTruthy();
    expect(screen.getAllByText("មិនទាន់ប្រើ").length).toBe(3);
    expect(screen.getByText("ថ្លៃឈ្នួលដំបូង")).toBeTruthy();
    expect(screen.getByText("ថ្ងៃទី 24")).toBeTruthy();
    cleanup();

    let fail = true;
    show(
      apiOf(() =>
        fail ? Promise.reject(new Error("down")) : Promise.resolve(PROPERTY),
      ),
    );
    const retry = await screen.findByRole("button", { name: "Retry" });
    fail = false;
    fireEvent.click(retry);
    expect(
      await screen.findByRole("region", { name: "Property" }),
    ).toBeTruthy();
    cleanup();

    show(
      apiOf(() => Promise.reject(new PropertyConfigurationUnavailableError())),
    );
    expect(
      await screen.findByText("Your account cannot open this tab."),
    ).toBeTruthy();
    dialog = document.body;
    expect(within(dialog).queryByRole("button", { name: "Retry" })).toBeNull();
    cleanup();

    // A refused rules read means no right, not a failure.
    const noRules = apiOf();
    noRules.settings.rules.mockRejectedValue(new BusinessSettingsError(403));
    show(noRules);
    expect(
      await screen.findByText("Your account cannot open this tab."),
    ).toBeTruthy();
    cleanup();

    // Saved, but reading back failed: it still says saved and reads again.
    // Save stays busy until the new version is read.
    const slow = apiOf();
    slow.property.updateSource.mockRejectedValueOnce(
      new PropertySavedReadFailedError(),
    );
    show(slow);
    fireEvent.click(
      await screen.findByRole("button", { name: "Edit: Property" }),
    );
    const finish: {
      read?: (value: PropertyBusinessConfiguration) => void;
      save?: () => void;
    } = {};
    slow.property.load.mockImplementationOnce(
      () =>
        new Promise<PropertyBusinessConfiguration>((resolve) => {
          finish.read = resolve;
        }),
    );
    dialog = screen.getByRole("dialog", { name: "Property" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved.")).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: "Add a method: Payment Methods" }),
    );
    const save = () =>
      within(
        screen.getByRole("dialog", { name: "Add a method" }),
      ).getByRole<HTMLButtonElement>("button", { name: "Save" });
    expect(save().disabled).toBe(true);
    finish.read?.({ ...PROPERTY, version: 5 });
    await waitFor(() => {
      expect(save().disabled).toBe(false);
    });
    cleanup();

    // A Property change while a save is out: the old answer is dropped.
    const race = apiOf();
    race.property.updateSource.mockImplementationOnce(
      () =>
        new Promise<PropertyBusinessConfiguration>((resolve) => {
          finish.save = () => {
            resolve(PROPERTY);
          };
        }),
    );
    const { rerender } = render(
      <BusinessTab active api={race} language="en" propertyId="property-1" />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Edit: Property" }),
    );
    fireEvent.click(
      within(screen.getByRole("dialog", { name: "Property" })).getByRole(
        "button",
        { name: "Save" },
      ),
    );
    rerender(
      <BusinessTab active api={race} language="en" propertyId="property-2" />,
    );
    await screen.findByRole("region", { name: "Property" });
    finish.save?.();
    await Promise.resolve();
    expect(screen.queryByText("Saved.")).toBeNull();
    expect(race.property.load).toHaveBeenLastCalledWith("property-2");
  });

  it("TEST-FE-1135 a business rule change needs a value that fits, a start day today or later and a reason, shows the history, and a day already used says so; Add rule makes a code from the English name and starts Not used yet", async () => {
    const api = show();
    fireEvent.click(
      await screen.findByRole("button", { name: "Edit: Late-payment charge" }),
    );
    let dialog = screen.getByRole("dialog", {
      name: "Change: Late-payment charge",
    });
    expect(
      within(within(dialog).getByRole("list", { name: "History" }))
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual(["01/12/2026 5%Lower", "01/01/2026 10%First value"]);
    const value = within(dialog).getByLabelText(/^New value/);
    expect((value as HTMLInputElement).value).toBe("5");
    fireEvent.change(value, { target: { value: "ten" } });
    fireEvent.change(within(dialog).getByLabelText(/^Starts on/), {
      target: { value: "01/11/2026" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      within(dialog).getByText("Type a value that fits the unit."),
    ).toBeTruthy();
    expect(
      within(dialog).getByText("Type a real date, dd/mm/yyyy, today or later."),
    ).toBeTruthy();
    expect(within(dialog).getByText("Say why.")).toBeTruthy();
    expect(api.settings.setRule).not.toHaveBeenCalled();

    api.settings.setRule.mockRejectedValueOnce(new BusinessSettingsError(409));
    fireEvent.change(value, { target: { value: "8" } });
    fireEvent.change(within(dialog).getByLabelText(/^Starts on/), {
      target: { value: "03/11/2026" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Reason/), {
      target: { value: "Owner decision" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await within(dialog).findByText(
        "A change already starts on that day. Choose another day.",
      ),
    ).toBeTruthy();
    expect(api.settings.setRule).toHaveBeenLastCalledWith(
      "property-1",
      "LATE_PAYMENT_PERCENT",
      { value: 800, effective_from: TODAY, reason: "Owner decision" },
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText(
        "Late-payment charge saved. It starts on 03/11/2026.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(
      screen.getByRole("button", { name: "Add rule: Business rules" }),
    );
    dialog = screen.getByRole("dialog", { name: "Add a business rule" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getAllByText("Type the rule name.").length).toBe(2);
    fireEvent.change(within(dialog).getByLabelText(/^Name in English/), {
      target: { value: "Key copy price" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Name in Khmer/), {
      target: { value: "តម្លៃថតកូនសោ" },
    });
    fireEvent.change(within(dialog).getByLabelText("Group"), {
      target: { value: "PRICES" },
    });
    fireEvent.change(within(dialog).getByLabelText("Value unit"), {
      target: { value: "USD_CENTS" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Starting value/), {
      target: { value: "2.50" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Rule added: Key copy price")).toBeTruthy();
    expect(api.settings.addRule).toHaveBeenCalledWith("property-1", {
      code: "KEY_COPY_PRICE",
      name_en: "Key copy price",
      name_kh: "តម្លៃថតកូនសោ",
      area: "PRICES",
      value_unit: "USD_CENTS",
      value: 250,
      effective_from: TODAY,
      reason: null,
    });
  });

  it("TEST-FE-1136 late payment for an Invoice type changes with a reason; new letters for a document must be 2 to 5 capitals no other document uses and show the next number", async () => {
    const api = show();
    fireEvent.click(
      await screen.findByRole("button", { name: "Change: First Rent" }),
    );
    let dialog = screen.getByRole("dialog", {
      name: "Late payment: First Rent",
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByText("Nothing changed.")).toBeTruthy();
    expect(within(dialog).getByText("Say why.")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("checkbox"));
    fireEvent.change(within(dialog).getByLabelText(/^Reason/), {
      target: { value: "Paid at signing" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText("First Rent: late payment No."),
    ).toBeTruthy();
    expect(api.settings.setLatePayment).toHaveBeenCalledWith(
      "property-1",
      "FIRST_RENT",
      false,
      "Paid at signing",
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Change the letters for Receipt" }),
    );
    dialog = screen.getByRole("dialog", {
      name: "Change the letters for Receipt",
    });
    const letters = within(dialog).getByLabelText(/^Letters/);
    fireEvent.change(letters, { target: { value: "INV" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      within(dialog).getByText(
        "Use 2 to 5 capital letters that no other document uses.",
      ),
    ).toBeTruthy();
    fireEvent.change(letters, { target: { value: "rc" } });
    expect(
      within(dialog).getByText("Next number will be RC260062"),
    ).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText("Numbers saved. Next RC260062"),
    ).toBeTruthy();
    expect(api.settings.setLetters).toHaveBeenCalledWith(
      "property-1",
      "RECEIPT",
      "RC",
    );
  });

  it("TEST-FE-1137 rule values are typed and shown in their unit, and a new rule's code comes from its English name", () => {
    expect(ruleValueFromText("USD_CENTS", "$12.5")).toBe(1250);
    expect(ruleValueFromText("USD_CENTS", "1.234")).toBeNull();
    expect(ruleValueFromText("PERCENT", "0.5")).toBe(50);
    expect(ruleValueFromText("PERCENT", "10%")).toBe(1000);
    expect(ruleValueFromText("TIME_OF_DAY", "22:00")).toBe(1320);
    expect(ruleValueFromText("TIME_OF_DAY", "25:00")).toBeNull();
    expect(ruleValueFromText("DAY_OF_MONTH", "32")).toBeNull();
    expect(ruleValueFromText("DAYS", "-1")).toBeNull();
    expect(ruleValueFromText("YES_NO", "1")).toBe(1);
    expect(ruleValueText("USD_CENTS", 1250, "en")).toBe("$12.50");
    expect(ruleValueText("PERCENT", 1050, "en")).toBe("10.5%");
    expect(ruleValueText("TIME_OF_DAY", 1320, "en")).toBe("22:00");
    expect(ruleValueText("DAYS", 7, "km")).toBe("7 ថ្ងៃ");
    expect(ruleValueText("YES_NO", 0, "en")).toBe("No");
    expect(ruleCode("Late-payment charge", RULES)).toBe("LATE_PAYMENT_CHARGE");
    expect(ruleCode("Round prices up to", [])).toBe("ROUND_PRICES_UP_TO");
    expect(ruleCode("ពាក្យ", RULES)).toBe("RULE");
    expect(ruleCode("12 meters read on", RULES)).toBe("METERS_READ_ON");
  });
});
