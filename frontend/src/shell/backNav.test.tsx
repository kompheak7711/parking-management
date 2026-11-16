// UI v81 (B3): the shared Back helper. TEST-FE-1900 to TEST-FE-1903.
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { useEffect, useState } from "react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { BackLink, currentPageLabel, useRemembered } from "./backNav";

/** A tiny page frame: the Unit page links to its Customer; the Customer page has Back. */
function Frame() {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const follow = () => {
      setHash(window.location.hash);
    };
    window.addEventListener("hashchange", follow);
    return () => {
      window.removeEventListener("hashchange", follow);
    };
  }, []);
  return (
    <div id="shell-view">
      {hash === "#/units/u101" && (
        <>
          <h1 data-record-title="">U101</h1>
          <a href="#/customers/kong-heng">Kong Heng</a>
        </>
      )}
      {hash === "#/customers/kong-heng" && (
        <>
          <BackLink language="en" parent="customers" />
          <h1 data-record-title="">Kong Heng</h1>
        </>
      )}
      {hash === "#/customers" && <h1 id="page-title">Customers</h1>}
    </div>
  );
}

beforeEach(() => {
  window.history.replaceState(null, "", "#/home");
});
afterEach(() => {
  cleanup();
});

describe("Back helper (UI v81 B3)", () => {
  it("TEST-FE-1900 U101, then Kong Heng, then Back returns to U101 and says so", async () => {
    window.history.pushState(null, "", "#/units/u101");
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    render(<Frame />);
    expect(await screen.findByRole("heading", { name: "U101" })).toBeTruthy();

    // A real link click: the helper remembers U101 before the address moves.
    const link = screen.getByRole("link", { name: "Kong Heng" });
    act(() => {
      fireEvent.click(link);
      window.history.pushState(null, "", "#/customers/kong-heng");
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    const back = await screen.findByRole("button", { name: "Back to U101" });
    fireEvent.click(back);
    await waitFor(() => {
      expect(window.location.hash).toBe("#/units/u101");
    });
    expect(await screen.findByRole("heading", { name: "U101" })).toBeTruthy();
  });

  it("TEST-FE-1901 a Customer opened directly says Back to Customers and opens the list", async () => {
    window.history.replaceState(null, "", "#/customers/kong-heng");
    render(<Frame />);
    const back = await screen.findByRole("button", {
      name: "Back to Customers",
    });
    const steps = window.history.length;
    fireEvent.click(back);
    expect(window.location.hash).toBe("#/customers");
    // The list replaces the record: Back does not add a step.
    expect(window.history.length).toBe(steps);
    expect(
      await screen.findByRole("heading", { name: "Customers" }),
    ).toBeTruthy();
  });

  it("TEST-FE-1902 Back inside a page drawn in another names the parent and runs its own step", () => {
    let backs = 0;
    render(
      <BackLink
        language="en"
        onBack={() => {
          backs += 1;
        }}
        parent="customers"
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Back to Customers" }));
    expect(backs).toBe(1);
  });

  it("TEST-FE-1903 a list keeps its filter for the tab, so Back finds it as it was left", () => {
    window.sessionStorage.clear();
    function List() {
      const [filter, setFilter] = useRemembered("test:filter", "all");
      return (
        <button
          onClick={() => {
            setFilter("overdue");
          }}
          type="button"
        >
          {filter}
        </button>
      );
    }
    render(<List />);
    fireEvent.click(screen.getByRole("button", { name: "all" }));
    expect(screen.getByRole("button", { name: "overdue" })).toBeTruthy();
    cleanup();
    render(<List />);
    expect(screen.getByRole("button", { name: "overdue" })).toBeTruthy();
  });
});

describe("Back names the page on show (batch 6)", () => {
  afterEach(cleanup);

  it("TEST-FE-2147 a hidden page's record heading is not taken as the page left", () => {
    render(
      <div id="shell-view">
        <section hidden>
          <h1 data-record-title="">Home</h1>
        </section>
        <section>
          <h1 id="page-title">Reservations</h1>
        </section>
      </div>,
    );
    expect(currentPageLabel()).toBe("Reservations");
  });
});
