import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CleaningRatesCard, leftWithout } from "./CleaningRates";
import {
  type CleaningSettings,
  type CleaningSettingsApi,
  ServiceSettingsError,
} from "./serviceSettingsClient";

afterEach(() => {
  cleanup();
});

const SMALL = {
  cleaning_rate_id: "rate-small",
  name_en: "Small rooms",
  name_km: "បន្ទប់តូច",
  rate_usd_cents: 1500,
  version: 2,
  unit_types: ["STUDIO", "SPARE"],
};
const LARGE = {
  cleaning_rate_id: "rate-large",
  name_en: "Large rooms",
  name_km: null,
  rate_usd_cents: 2500,
  version: 1,
  unit_types: ["TWO_BEDROOM"],
};

function settingsOf(extra: Partial<CleaningSettings> = {}): CleaningSettings {
  return {
    cleaning_rates: [SMALL, LARGE],
    unit_types: [
      {
        code: "STUDIO",
        name_en: "Studio",
        name_km: "ស្ទូឌីយោ",
        units: 4,
        cleaning_rate_id: "rate-small",
      },
      {
        code: "SPARE",
        name_en: "Spare",
        name_km: null,
        units: 0,
        cleaning_rate_id: "rate-small",
      },
      {
        code: "TWO_BEDROOM",
        name_en: "Two Bedroom",
        name_km: null,
        units: 1,
        cleaning_rate_id: "rate-large",
      },
      {
        code: "PENTHOUSE",
        name_en: "Penthouse",
        name_km: null,
        units: 0,
        cleaning_rate_id: null,
      },
    ],
    can_manage: true,
    ...extra,
  };
}

function apiOf(
  read: () => Promise<CleaningSettings> = () => Promise.resolve(settingsOf()),
) {
  return {
    read: vi.fn<CleaningSettingsApi["read"]>(read),
    add: vi.fn<CleaningSettingsApi["add"]>(() => Promise.resolve({})),
    change: vi.fn<CleaningSettingsApi["change"]>(() => Promise.resolve({})),
    remove: vi.fn<CleaningSettingsApi["remove"]>(() => Promise.resolve({})),
  };
}

function show(api = apiOf(), language: "en" | "km" = "en") {
  render(
    <CleaningRatesCard
      active
      api={api}
      language={language}
      propertyId="property-1"
    />,
  );
  return api;
}

const save = (dialog: HTMLElement) => {
  fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
};

describe("Settings: move-out cleaning rates", () => {
  it("TEST-FE-1005 lists each rate with its Unit Types and warns of a type with no rate; Add sends its own id and the ticked types (a type of another rate moves); Edit sends the version; untick and Remove of a type with Units are refused with its name", async () => {
    const api = show();
    const card = await screen.findByRole("region", {
      name: "Move-out cleaning rates",
    });
    expect(
      within(card)
        .getAllByRole("row")
        .slice(1)
        .map((row) => row.textContent),
    ).toEqual([
      "Small roomsStudio, Spare$15.00EditRemove",
      "Large roomsTwo Bedroom$25.00EditRemove",
    ]);
    expect(
      within(card).getByText(
        "No cleaning rate yet: Penthouse. Tick them in a cleaning rate.",
      ),
    ).toBeTruthy();

    // Add: a name and an amount are needed; ticking Two Bedroom says it moves here.
    fireEvent.click(
      within(card).getByRole("button", { name: "Add a cleaning rate" }),
    );
    let dialog = screen.getByRole("dialog", { name: "Add a cleaning rate" });
    save(dialog);
    expect(
      within(dialog).getByText("Enter a name of 1 to 100 letters."),
    ).toBeTruthy();
    expect(api.add).not.toHaveBeenCalled();
    expect(
      within(dialog).getByText("Now in Large rooms; ticking moves it here."),
    ).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/^Name in English/), {
      target: { value: " Big " },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Rate/), {
      target: { value: "30" },
    });
    fireEvent.click(within(dialog).getByLabelText(/^Penthouse/));
    fireEvent.click(within(dialog).getByLabelText(/^Two Bedroom/));
    api.add.mockRejectedValueOnce(new ServiceSettingsError("unknown"));
    save(dialog);
    expect(
      await within(dialog).findByText(/may be saved already/),
    ).toBeTruthy();
    save(dialog);
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    const [first, again] = api.add.mock.calls;
    // The same id after a lost answer; the types in the order of the Unit setup list.
    expect(first?.[1]).toEqual({
      cleaning_rate_id: again?.[1].cleaning_rate_id,
      name_en: "Big",
      name_km: null,
      rate_usd_cents: 3000,
      unit_types: ["TWO_BEDROOM", "PENTHOUSE"],
    });
    expect(await screen.findByText("Big added.")).toBeTruthy();

    // Edit: unticking Studio (it has Units) is refused here; Spare (no Units) may go.
    fireEvent.click(
      within(card).getByRole("button", { name: "Edit: Small rooms" }),
    );
    dialog = screen.getByRole("dialog", { name: "Edit · Small rooms" });
    fireEvent.click(within(dialog).getByLabelText(/^Studio/));
    fireEvent.click(within(dialog).getByLabelText(/^Spare/));
    save(dialog);
    expect(
      within(dialog).getByText(
        "Studio has Units and needs a cleaning rate. Put it in another rate first.",
      ),
    ).toBeTruthy();
    expect(api.change).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByLabelText(/^Studio/));
    fireEvent.change(within(dialog).getByLabelText(/^Rate/), {
      target: { value: "16.5" },
    });
    // Another person changed it first: the form stays and the list is read again.
    api.change.mockRejectedValueOnce(new ServiceSettingsError("out_of_date"));
    const reads = api.read.mock.calls.length;
    save(dialog);
    expect(await within(dialog).findByText(/Someone changed this first/));
    await waitFor(() => {
      expect(api.read.mock.calls.length).toBe(reads + 1);
    });
    // From the next read on, the Studios have moved out: only Two Bedroom has a Unit.
    api.read.mockResolvedValue(
      settingsOf({
        unit_types: settingsOf().unit_types.map((type) => ({
          ...type,
          units: type.code === "TWO_BEDROOM" ? 1 : 0,
        })),
      }),
    );
    save(dialog);
    await waitFor(() => {
      expect(api.change).toHaveBeenCalledTimes(2);
    });
    expect(api.change.mock.calls[1]).toEqual([
      "property-1",
      "rate-small",
      {
        name_en: "Small rooms",
        name_km: "បន្ទប់តូច",
        rate_usd_cents: 1650,
        unit_types: ["STUDIO"],
        version: 2,
      },
    ]);

    // Remove: a rate whose type has Units cannot go; the dialog says why, with no Remove.
    fireEvent.click(
      await within(card).findByRole("button", { name: "Remove: Large rooms" }),
    );
    dialog = screen.getByRole("dialog", { name: "Remove · Large rooms" });
    expect(
      within(dialog).getByText(
        "Two Bedroom has Units and needs a cleaning rate. Put it in another rate first.",
      ),
    ).toBeTruthy();
    expect(within(dialog).queryByRole("button", { name: "Remove" })).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    // The server's refusal says so too, and reads the list again.
    fireEvent.click(
      within(card).getByRole("button", { name: "Remove: Small rooms" }),
    );
    dialog = screen.getByRole("dialog", { name: "Remove · Small rooms" });
    api.remove.mockRejectedValueOnce(new ServiceSettingsError("needs_rate"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove" }));
    expect(
      await within(dialog).findByText(/needs a cleaning rate\. Put it in/),
    ).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove" }));
    await waitFor(() => {
      expect(api.remove).toHaveBeenLastCalledWith(
        "property-1",
        "rate-small",
        2,
      );
    });
    expect(await screen.findByText("Small rooms removed.")).toBeTruthy();

    // The helper on its own.
    const types = settingsOf().unit_types;
    expect(leftWithout(null, new Set(), types)).toBeNull();
    expect(leftWithout(SMALL, new Set(["STUDIO"]), types)).toBeNull();
    expect(leftWithout(SMALL, new Set(), types)?.code).toBe("STUDIO");
  });

  it("TEST-FE-1007 without Settings access the rates show with no buttons; a failed read offers Retry; a rate removed by another person closes the form; Khmer names show in Khmer", async () => {
    const api = show(
      apiOf(() => Promise.resolve(settingsOf({ can_manage: false }))),
    );
    const card = await screen.findByRole("region", {
      name: "Move-out cleaning rates",
    });
    expect(within(card).queryAllByRole("button")).toEqual([]);
    expect(api.read).toHaveBeenCalledWith("property-1");
    cleanup();

    const failing = apiOf(() => Promise.reject(new Error("down")));
    show(failing);
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect(failing.read).toHaveBeenCalledTimes(2);
    cleanup();

    // A rate another person removed: the form closes and says it is gone.
    const gone = show();
    fireEvent.click(
      await screen.findByRole("button", { name: "Edit: Large rooms" }),
    );
    gone.change.mockRejectedValueOnce(new ServiceSettingsError("not_found"));
    save(screen.getByRole("dialog", { name: "Edit · Large rooms" }));
    expect(
      await screen.findByText(/This is no longer in the list/),
    ).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    cleanup();

    show(apiOf(), "km");
    const khmer = await screen.findByRole("region", {
      name: "អត្រាសម្អាតពេលចាកចេញ",
    });
    expect(within(khmer).getByText("បន្ទប់តូច")).toBeTruthy();
    expect(within(khmer).getByText(/ស្ទូឌីយោ/)).toBeTruthy();
  });
});
