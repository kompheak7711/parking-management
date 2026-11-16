// UI v81 round 11 (owner 12/11/2026: "check all card is link to correct place"): the coming
// birthdays that Home's Birthdays card opens on the Customers page. TEST-FE-1948.
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { BirthdayRow } from "../reportsClient";
import { BirthdaysCard, birthdayText } from "./Birthdays";

afterEach(() => {
  cleanup();
});

function person(
  customer_id: string,
  customer_name: string,
  unit_number: string,
  birthday: string,
  role: BirthdayRow["role"] = "PRIMARY",
): BirthdayRow {
  return {
    customer_id,
    customer_name,
    role,
    unit_id: `unit-${unit_number.toLowerCase()}`,
    unit_number,
    birthday,
  };
}

// The read gives each person's next birthday, in no order.
const ROWS = [
  person("c-5", "Sok Pisey", "U401", "2026-12-01"),
  person("c-4", "Lim Vanna", "U102", "2026-11-20"),
  person("c-3", "Chan Dara", "U303", "2026-11-19"),
  person("c-2", "Srey Mom", "U202", "2026-11-13", "OCCUPANT"),
  person("c-6", "Keo Sophal", "U1001", "2026-11-12"),
  person("c-1", "Kong Heng", "U101", "2026-11-12"),
];

function show(birthdays: () => Promise<{ items: BirthdayRow[] }>) {
  const api = { birthdays: vi.fn(birthdays) };
  const onHide = vi.fn();
  render(
    <BirthdaysCard
      api={api}
      language="en"
      onHide={onHide}
      propertyId="property-1"
      today="2026-11-12"
    />,
  );
  return { api, onHide };
}

const lines = (list: HTMLElement) =>
  within(list)
    .getAllByRole("listitem")
    .map((line) => line.textContent);

describe("Customers: the coming birthdays (UI v81 round 11)", () => {
  it("TEST-FE-1948 lists the birthdays of today and the next 7 days (what Home's card counts) in date order with the person's role, Unit and how soon, then the later ones of this month; only the day and month show; each row opens the Customer and the Unit; Hide closes it; a failed read offers Retry", async () => {
    expect(birthdayText("2026-11-14")).toBe("14/11");
    const { api, onHide } = show(() => Promise.resolve({ items: ROWS }));
    expect(screen.getByText("Loading the birthdays…")).toBeTruthy();
    const card = await screen.findByRole("region", { name: "Birthdays 4" });
    expect(api.birthdays).toHaveBeenCalledWith("property-1");

    const [week, later] = within(card).getAllByRole("list");
    if (week === undefined || later === undefined)
      throw new Error("two lists are expected");
    expect(
      within(card)
        .getAllByRole("heading", { level: 3 })
        .map((heading) => heading.textContent),
    ).toEqual(["Today and the next 7 days4", "Later this month1"]);
    // Two people on one day are in Unit order (U101 before U1001).
    expect(lines(week)).toEqual([
      "Kong HengPrimary Tenant · U10112/11today",
      "Keo SophalPrimary Tenant · U100112/11today",
      "Srey MomOccupant · U20213/11tomorrow",
      "Chan DaraPrimary Tenant · U30319/11in 7 days",
    ]);
    // The eighth day is not in Home's count; next month's birthday is not listed at all.
    expect(lines(later)).toEqual([
      "Lim VannaPrimary Tenant · U10220/11in 8 days",
    ]);
    expect(card.textContent).not.toContain("Sok Pisey");
    // Never the year or the age.
    expect(card.textContent).not.toContain("2026");

    expect(
      within(week).getByRole("link", { name: "U202" }).getAttribute("href"),
    ).toBe("#/units/unit-u202");
    expect(
      within(week)
        .getByRole("link", { name: "Open Customer: Srey Mom" })
        .getAttribute("href"),
    ).toBe("#/customers/c-2");

    fireEvent.click(within(card).getByRole("button", { name: "Hide" }));
    expect(onHide).toHaveBeenCalledTimes(1);
    cleanup();

    // Nobody in these days: the first group says so and there is no second group.
    show(() =>
      Promise.resolve({
        items: [person("c-5", "Sok Pisey", "U401", "2026-12-01")],
      }),
    );
    const none = await screen.findByRole("region", { name: "Birthdays 0" });
    expect(within(none).getByText("No birthdays in these days.")).toBeTruthy();
    expect(within(none).queryByText("Later this month")).toBeNull();
    cleanup();

    // A read that fails says so; Retry reads again.
    let fail = true;
    const again = show(() =>
      fail
        ? Promise.reject(new Error("down"))
        : Promise.resolve({ items: ROWS }),
    );
    expect(
      await screen.findByText("The birthdays could not be loaded."),
    ).toBeTruthy();
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(
      await screen.findByRole("region", { name: "Birthdays 4" }),
    ).toBeTruthy();
    expect(again.api.birthdays).toHaveBeenCalledTimes(2);
  });
});
