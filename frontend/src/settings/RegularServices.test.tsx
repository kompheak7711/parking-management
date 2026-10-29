import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RegularServicesCard } from "./RegularServices";
import {
  type RegularServices,
  type RegularServicesApi,
  regularServicesOf,
  ServiceSettingsError,
} from "./serviceSettingsClient";

afterEach(() => {
  cleanup();
});

const LAUNDRY = {
  regular_service_id: "svc-laundry",
  name_en: "Laundry bag",
  name_km: "កាបូបបោកខោអាវ",
  price_usd_cents: 450,
  version: 2,
  used_this_year: 3,
};
const CLEANING = {
  regular_service_id: "svc-cleaning",
  name_en: "Extra cleaning",
  name_km: null,
  price_usd_cents: 1500,
  version: 1,
  used_this_year: 0,
};

function listOf(extra: Partial<RegularServices> = {}): RegularServices {
  return { regular_services: [CLEANING, LAUNDRY], can_manage: true, ...extra };
}

function apiOf(list = listOf()) {
  return {
    read: vi.fn<RegularServicesApi["read"]>(() => Promise.resolve(list)),
    add: vi.fn<RegularServicesApi["add"]>(() => Promise.resolve({})),
    change: vi.fn<RegularServicesApi["change"]>(() => Promise.resolve({})),
    remove: vi.fn<RegularServicesApi["remove"]>(() => Promise.resolve({})),
  };
}

function show(api = apiOf()) {
  render(
    <RegularServicesCard
      active
      api={api}
      language="en"
      propertyId="property-1"
    />,
  );
  return api;
}

const save = (dialog: HTMLElement) => {
  fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
};

describe("Settings: Regular services (V1.1, DL-115 (I))", () => {
  it("TEST-FE-1127 lists each Regular service with its price and use this year; Add needs a name and a price and keeps its id after a lost answer; Edit sends the version; a service used this year cannot be removed", async () => {
    const api = show();
    const card = await screen.findByRole("region", {
      name: "Regular services",
    });
    expect(
      within(card)
        .getAllByRole("row")
        .slice(1)
        .map((row) => row.textContent),
    ).toEqual([
      "Extra cleaning$15.000EditRemove",
      "Laundry bag$4.503EditRemove",
    ]);

    fireEvent.click(within(card).getByRole("button", { name: "Add service" }));
    let dialog = screen.getByRole("dialog", { name: "Add service" });
    save(dialog);
    expect(
      within(dialog).getByText("Enter a name of 1 to 100 letters."),
    ).toBeTruthy();
    expect(api.add).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByLabelText(/^Name in English/), {
      target: { value: " Key copy " },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Price/), {
      target: { value: "3" },
    });
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
    expect(first?.[1]).toEqual({
      regular_service_id: again?.[1].regular_service_id,
      name_en: "Key copy",
      name_km: null,
      price_usd_cents: 300,
    });
    expect(await screen.findByText("Key copy added.")).toBeTruthy();

    fireEvent.click(
      within(card).getByRole("button", { name: "Edit: Laundry bag" }),
    );
    dialog = screen.getByRole("dialog", {
      name: "Change a Regular service · Laundry bag",
    });
    fireEvent.change(within(dialog).getByLabelText(/^Price/), {
      target: { value: "5.25" },
    });
    save(dialog);
    await waitFor(() => {
      expect(api.change).toHaveBeenCalledWith("property-1", "svc-laundry", {
        name_en: "Laundry bag",
        name_km: "កាបូបបោកខោអាវ",
        price_usd_cents: 525,
        version: 2,
      });
    });

    fireEvent.click(
      within(card).getByRole("button", { name: "Remove: Laundry bag" }),
    );
    dialog = screen.getByRole("dialog", { name: "Remove · Laundry bag" });
    expect(
      within(dialog).getByText(
        "Used on 3 Invoice items this year. It can be removed next year.",
      ),
    ).toBeTruthy();
    expect(within(dialog).queryByRole("button", { name: "Remove" })).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    fireEvent.click(
      within(card).getByRole("button", { name: "Remove: Extra cleaning" }),
    );
    dialog = screen.getByRole("dialog", { name: "Remove · Extra cleaning" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove" }));
    await waitFor(() => {
      expect(api.remove).toHaveBeenCalledWith("property-1", "svc-cleaning", 1);
    });
  });

  it("TEST-FE-1128 a user without Settings access sees the prices but no changes, and the client reads only a well-formed answer", async () => {
    show(apiOf(listOf({ can_manage: false })));
    const card = await screen.findByRole("region", {
      name: "Regular services",
    });
    expect(
      within(card).queryByRole("button", { name: "Add service" }),
    ).toBeNull();
    expect(within(card).queryByRole("button", { name: /^Edit/ })).toBeNull();
    expect(regularServicesOf(listOf())).toEqual(listOf());
    expect(() =>
      regularServicesOf({
        regular_services: [{ ...LAUNDRY, price_usd_cents: "4.50" }],
        can_manage: true,
      }),
    ).toThrow(ServiceSettingsError);
    expect(() => regularServicesOf({ regular_services: [] })).toThrow(
      ServiceSettingsError,
    );
  });
});
