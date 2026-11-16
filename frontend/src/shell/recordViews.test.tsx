// UI v81 (owner 07/11/2026): a long list on a record shows the latest 5 and opens a full page.
// TEST-FE-1905.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  LatestNote,
  RecordViewPage,
  ViewAllButton,
  latestOf,
  useHashView,
} from "./recordViews";

afterEach(() => {
  cleanup();
});

const EVENTS = Array.from(
  { length: 8 },
  (_, index) => `Event ${String(8 - index)}`,
);

function Lease() {
  const view = useHashView();
  if (view === "history")
    return (
      <RecordViewPage
        language="en"
        parent="leases"
        parentDetail="lease-1"
        recordName="Lease · U406"
        title="History · Lease · U406"
      >
        <ol>
          {EVENTS.map((event) => (
            <li key={event}>{event}</li>
          ))}
        </ol>
      </RecordViewPage>
    );
  return (
    <section>
      <h2 data-record-title="">Lease · U406</h2>
      <LatestNote language="en" shown={5} total={EVENTS.length} />
      <ol aria-label="History">
        {latestOf(EVENTS).map((event) => (
          <li key={event}>{event}</li>
        ))}
      </ol>
      <ViewAllButton label="History" total={EVENTS.length} view="history" />
    </section>
  );
}

describe("Record views (UI v81)", () => {
  it("TEST-FE-1905 the History card shows the latest 5 of 8; History opens the full page; Back names the record", async () => {
    window.history.replaceState(null, "", "#/leases/lease-1");
    render(<Lease />);
    expect(screen.getByText("Latest 5 of 8")).toBeTruthy();
    expect(screen.getByRole("list", { name: "History" }).children).toHaveLength(
      5,
    );
    fireEvent.click(screen.getByRole("button", { name: /^History\s*\(8\)$/ }));
    expect(window.location.hash).toBe("#/leases/lease-1?view=history");
    expect(
      await screen.findByRole("heading", { name: "History · Lease · U406" }),
    ).toBeTruthy();
    expect(screen.getAllByRole("listitem")).toHaveLength(8);
    expect(
      screen.getByRole("button", { name: "Back to Lease · U406" }),
    ).toBeTruthy();
  });
});
