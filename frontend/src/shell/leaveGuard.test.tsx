import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useLeaveGuard } from "./leaveGuard";
import { useHashPage } from "./useHashPage";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function Page({ money }: { money: boolean }) {
  const page = useHashPage();
  useLeaveGuard(money, "en");
  return <p>{`page ${page}`}</p>;
}

function goBack(from: string, to: string) {
  // Back: the browser has already moved the address when hashchange fires.
  window.history.replaceState(null, "", to);
  act(() => {
    window.dispatchEvent(
      new HashChangeEvent("hashchange", {
        oldURL: `${window.location.origin}/${from}`,
        newURL: `${window.location.origin}/${to}`,
      }),
    );
  });
}

function reload(): boolean {
  const event = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(event);
  return event.defaultPrevented;
}

describe("Leave a money window (V1-061 Fix 3)", () => {
  it("TEST-FE-1114 Back or reload asks while a money window is open; staying keeps the page and its address, leaving follows the address, and with no money window nothing asks", () => {
    window.history.replaceState(null, "", "#/leases");
    const ask = vi.spyOn(window, "confirm").mockReturnValue(false);
    const { rerender } = render(<Page money />);
    expect(screen.getByText("page leases")).toBeInTheDocument();
    expect(reload()).toBe(true);

    goBack("#/leases", "#/units");
    expect(ask).toHaveBeenCalledTimes(1);
    expect(ask.mock.calls[0]?.[0]).toMatch(/^Leave this page\? A money window/);
    expect(screen.getByText("page leases")).toBeInTheDocument();
    expect(window.location.hash).toBe("#/leases");

    ask.mockReturnValue(true);
    goBack("#/leases", "#/units");
    expect(ask).toHaveBeenCalledTimes(2);
    expect(screen.getByText("page units")).toBeInTheDocument();

    // The money window is closed: nothing asks.
    rerender(<Page money={false} />);
    expect(reload()).toBe(false);
    goBack("#/units", "#/payments");
    expect(ask).toHaveBeenCalledTimes(2);
    expect(screen.getByText("page payments")).toBeInTheDocument();
  });
});
