import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppShell, phnomPenhClock } from "./AppShell";
import { MENU, pageFromHash, type PageId } from "./navigation";
import { useHashPage } from "./useHashPage";
import type { Language } from "../signInText";

afterEach(() => {
  cleanup();
});

const NOW = new Date("2026-10-24T18:30:00Z").getTime();

function renderShell(
  page: PageId = "home",
  language: Language = "en",
  overrides: Partial<Parameters<typeof AppShell>[0]> = {},
) {
  const onSignOut = vi.fn();
  const onLanguageChange = vi.fn();
  render(
    <AppShell
      buildId="test-build"
      displayName="Sokha Chan"
      environment="development"
      language={language}
      notice={null}
      now={() => NOW}
      onLanguageChange={onLanguageChange}
      onSignOut={onSignOut}
      page={page}
      signOutDisabled={false}
      capabilities={null}
      {...overrides}
    >
      <p>Page body</p>
    </AppShell>,
  );
  return { onSignOut, onLanguageChange };
}

describe("V1-058 R1 app shell", () => {
  it("TEST-FE-801 shows the menu groups in the order the owner approved on 24/10/2026 with one link per page", () => {
    renderShell();
    const menu = screen.getByRole("navigation", { name: "Menu" });
    const links = within(menu)
      .getAllByRole("link")
      .map((link) => link.textContent);
    expect(links).toEqual([
      "Home",
      "Payments",
      "Invoices",
      "Utilities",
      "Waiting for approval",
      "Bookings",
      "Leases",
      "Customers",
      "Units",
      "Reports",
      "History",
      "Settings",
    ]);
    for (const group of ["Daily work", "Tenants", "Building", "Office"]) {
      expect(within(menu).getByText(group)).toBeInTheDocument();
    }
    expect(MENU.flatMap((group) => group.items)).toHaveLength(12);
  });

  it("TEST-FE-802 marks only the open page in the menu and names the work area after it", () => {
    renderShell("units");
    const menu = screen.getByRole("navigation", { name: "Menu" });
    expect(within(menu).getByRole("link", { name: "Units" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(
      within(menu).getByRole("link", { name: "Home" }),
    ).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("main")).toHaveAccessibleName("Units");
    expect(within(menu).getByRole("link", { name: "Units" })).toHaveAttribute(
      "href",
      "#/units",
    );
  });

  it("TEST-FE-803 shows the date as dd/mm/yyyy and the 24-hour time in Phnom Penh", () => {
    // 18:30 UTC is 01:30 the next day in Phnom Penh (UTC+7).
    expect(phnomPenhClock(NOW, "en")).toEqual({
      weekday: "Sunday",
      date: "25/10/2026",
      time: "01:30",
    });
    expect(phnomPenhClock(NOW, "km").weekday).toBe("ថ្ងៃអាទិត្យ");
    renderShell();
    expect(screen.getByText("Sunday 25/10/2026 · 01:30")).toBeInTheDocument();
    expect(screen.getByText("Phnom Penh time")).toBeInTheDocument();
  });

  it("TEST-FE-804 switches the menu to Khmer and back from the top bar", () => {
    const { onLanguageChange } = renderShell("home", "km");
    expect(document.documentElement.lang).toBe("km");
    const menu = screen.getByRole("navigation", { name: "ម៉ឺនុយ" });
    expect(
      within(menu).getByRole("link", { name: "បន្ទប់" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ខ្មែរ" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    fireEvent.click(screen.getByRole("button", { name: "EN" }));
    expect(onLanguageChange).toHaveBeenCalledWith("en");
    cleanup();
    expect(document.documentElement.lang).toBe("en");
  });

  it("TEST-FE-805 shows the signed-in name, the environment badge and a Sign out button", () => {
    const { onSignOut } = renderShell();
    expect(screen.getByText("Sokha Chan")).toBeInTheDocument();
    expect(screen.getByText("SC")).toBeInTheDocument();
    expect(screen.getByText("DEVELOPMENT")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(onSignOut).toHaveBeenCalledTimes(1);
  });

  it("TEST-FE-806 hides the environment badge in production and keeps Sign out locked while busy", () => {
    renderShell("home", "en", {
      environment: "production",
      displayName: null,
      signOutDisabled: true,
    });
    expect(screen.queryByText("PRODUCTION")).not.toBeInTheDocument();
    expect(screen.getByText("Signed in")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeDisabled();
  });

  it("TEST-FE-807 opens the slide-in menu as a dialog and closes it with its button or Escape", () => {
    renderShell();
    const button = screen.getByRole("button", { name: "Menu" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    // The focus starts on the first menu link and the page behind is inert.
    expect(screen.getByRole("link", { name: "Home" })).toHaveFocus();
    expect(document.querySelector(".shell-main")).toHaveAttribute("inert");
    fireEvent.click(screen.getByRole("button", { name: "Close the menu" }));
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveFocus();
    fireEvent.click(button);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveFocus();
    expect(document.querySelector(".shell-main")).not.toHaveAttribute("inert");
  });

  it("TEST-FE-810 shows only the menu items and tabs the person may use", () => {
    renderShell("moveout", "en", {
      capabilities: new Set(["units.read", "deposits.read", "audit.view"]),
    });
    const menu = screen.getByRole("navigation", { name: "Menu" });
    expect(
      within(menu)
        .getAllByRole("link")
        .map((link) => [link.textContent, link.getAttribute("href")]),
    ).toEqual([
      ["Home", "#/home"],
      ["Leases", "#/moveout"],
      ["Units", "#/units"],
      // audit.view reads the Audit activity report (V1-060 B6).
      ["Reports", "#/reports"],
      ["History", "#/history"],
    ]);
    expect(within(menu).queryByText("Daily work")).not.toBeInTheDocument();
    // One allowed tab: no tab bar.
    expect(
      screen.queryByRole("navigation", { name: "Leases" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-1060 shows Reports to anyone who may read one report and hides it from a person who may read none", () => {
    const shows = (rights: string[]) => {
      renderShell("home", "en", { capabilities: new Set(rights) });
      const menu = screen.getByRole("navigation", { name: "Menu" });
      const shown = within(menu).queryByRole("link", { name: "Reports" });
      cleanup();
      return shown !== null;
    };
    // Payments and Invoices without reports.read read no report (DL-072 answer 5).
    expect(shows(["payments.read", "invoices.read"])).toBe(false);
    expect(shows(["units.read", "reservations.read"])).toBe(false);
    expect(shows(["reports.read"])).toBe(true);
    expect(shows(["utility.read"])).toBe(true);
    expect(shows(["leases.read"])).toBe(true);
    expect(shows(["audit.view"])).toBe(true);
  });

  it("TEST-FE-811 opens My account from the name at the foot of the menu", () => {
    renderShell("account");
    const link = screen.getByRole("link", { name: /Sokha Chan/ });
    expect(link).toHaveAttribute("href", "#/account");
    expect(link).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("main")).toHaveAccessibleName("My account");
  });

  it("TEST-FE-812 moves the focus to the new page and starts it at the top", () => {
    const props = {
      buildId: "b",
      capabilities: null,
      displayName: null,
      environment: "production",
      language: "en" as const,
      notice: null,
      now: () => NOW,
      onLanguageChange: vi.fn(),
      onSignOut: vi.fn(),
      signOutDisabled: false,
      children: <p>Body</p>,
    };
    const { rerender } = render(<AppShell {...props} page="home" />);
    // The first page does not take the focus.
    expect(screen.getByRole("main")).not.toHaveFocus();
    document.documentElement.scrollTop = 500;
    rerender(<AppShell {...props} page="units" />);
    expect(screen.getByRole("main")).toHaveFocus();
    expect(document.documentElement.scrollTop).toBe(0);
  });

  it("TEST-FE-809 shows Letters and Move-out as tabs of Leases and keeps Leases marked in the menu", () => {
    renderShell("letters");
    const menu = screen.getByRole("navigation", { name: "Menu" });
    expect(within(menu).getByRole("link", { name: "Leases" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("main")).toHaveAccessibleName("Leases");
    const tabs = screen.getByRole("navigation", { name: "Leases" });
    expect(
      within(tabs)
        .getAllByRole("link")
        .map((link) => [link.textContent, link.getAttribute("href")]),
    ).toEqual([
      ["Leases", "#/leases"],
      ["Letters", "#/letters"],
      ["Move-out", "#/moveout"],
    ]);
    expect(within(tabs).getByRole("link", { name: "Letters" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    cleanup();
    renderShell("reservations");
    expect(screen.getByRole("main")).toHaveAccessibleName("Bookings");
    // Bookings has one tab in V1 (Visit requests comes in V1.1), so no tab bar.
    expect(
      screen.queryByRole("navigation", { name: "Bookings" }),
    ).not.toBeInTheDocument();
  });

  it("TEST-FE-808 reads the page from the address and follows address changes", () => {
    expect(pageFromHash("#/leases")).toBe("leases");
    expect(pageFromHash("#leases")).toBe("leases");
    expect(pageFromHash("#/nothing")).toBe("home");
    expect(pageFromHash("")).toBe("home");
    function Probe() {
      return <p>{useHashPage()}</p>;
    }
    window.history.replaceState(null, "", "#/invoices");
    render(<Probe />);
    expect(screen.getByText("invoices")).toBeInTheDocument();
    act(() => {
      window.history.replaceState(null, "", "#/letters");
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(screen.getByText("letters")).toBeInTheDocument();
  });
});
