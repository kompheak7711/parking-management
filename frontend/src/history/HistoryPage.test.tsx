import { StrictMode } from "react";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ExportRefusedError } from "../reportsClient";
import type {
  HistoryApi,
  HistoryEvent,
  HistoryPage as Page,
} from "./historyClient";
import { HistoryNotAllowedError } from "./historyClient";
import { type HistoryExportApi, HistoryPage } from "./HistoryPage";
import { actionText, kindOf } from "./text";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const ME = "11111111-aaaa-4aaa-8aaa-111111111111";
const DARA = "22222222-bbbb-4bbb-8bbb-222222222222";
const GONE = "33333333-cccc-4ccc-8ccc-333333333333";
const UNIT = "44444444-dddd-4ddd-8ddd-444444444444";

function event(extra: Partial<HistoryEvent>): HistoryEvent {
  return {
    event_id: "e1",
    actor_id: DARA,
    action: "invoice.created",
    resource_type: "invoice",
    resource_id: "55555555-eeee-4eee-8eee-555555555555",
    occurred_at: "2026-10-25T03:15:00Z",
    business_date: "2026-10-25",
    reason: "",
    outcome: "succeeded",
    source: "api",
    linked_source_event_id: null,
    ...extra,
  };
}

const FIRST: Page = {
  events: [
    event({}),
    event({
      event_id: "e2",
      actor_id: ME,
      action: "unit.status_changed",
      resource_type: "unit",
      resource_id: UNIT,
      reason: "Repair done",
      occurred_at: "2026-10-24T10:00:00Z",
    }),
    event({
      event_id: "e3",
      actor_id: GONE,
      action: "final_settlement.correction.confirmed",
      resource_type: "settlement_correction",
      outcome: "refused",
    }),
  ],
  nextCursor: "c2",
};

function setup(
  search: HistoryApi["search"] = vi.fn(() => Promise.resolve(FIRST)),
  capabilities: ReadonlySet<string> | null = null,
  namesRead = true,
) {
  const api = { search: vi.fn(search) };
  const people = vi.fn(() =>
    namesRead
      ? Promise.resolve([
          { user_id: ME, display_name: "Kompheak" },
          { user_id: DARA, display_name: "Chan Dara" },
        ])
      : Promise.reject(new Error("not allowed")),
  );
  const units = {
    list: vi.fn(() =>
      Promise.resolve({
        items: [{ unit_id: UNIT, unit_number: "U203" }],
        next_cursor: null,
        can_manage: true,
      } as never),
    ),
  };
  const exporter = {
    exportAudit: vi.fn(() =>
      Promise.resolve({
        kind: "file" as const,
        exportId: "x1",
        fileName: "history.xlsx",
        sha256: "abc",
        rowCount: 3,
        file: new Blob(["x"]),
      }),
    ),
    download: vi.fn<HistoryExportApi["download"]>(),
  };
  const view = render(
    <HistoryPage
      active
      api={api}
      capabilities={capabilities}
      exporter={exporter}
      language="en"
      me={{ id: ME, name: "Kompheak" }}
      people={people}
      propertyId="property-1"
      today="2026-10-25"
      units={units}
    />,
  );
  return { api, people, units, exporter, view };
}

const rows = () =>
  within(screen.getByRole("table"))
    .getAllByRole("row")
    .slice(1)
    .map((row) =>
      within(row)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    );

describe("History", () => {
  it("TEST-FE-958 opens on the last 7 days with one search; shows when, who, the kind, what happened with the reason, and links the record; Show more reads the next page", async () => {
    const { api } = setup();
    await screen.findByRole("table");
    expect(api.search).toHaveBeenCalledTimes(1);
    expect(api.search).toHaveBeenCalledWith("property-1", {
      from: "2026-10-19",
    });
    await waitFor(() => {
      expect(rows()[1]?.[4]).toBe("U203");
    });
    expect(rows()).toEqual([
      [
        "25/10/2026 10:15",
        "Chan Dara",
        "Invoice",
        "Invoice created",
        "55555555",
      ],
      [
        "24/10/2026 17:00",
        "Kompheak (you)",
        "Unit",
        "Unit status changedReason: Repair done",
        "U203",
      ],
      [
        "25/10/2026 10:15",
        "A user (33333333)",
        "Final Settlement",
        "Final settlement correction confirmed Refused",
        "55555555",
      ],
    ]);
    expect(
      screen.getByRole("link", { name: "Unit U203" }).getAttribute("href"),
    ).toBe(`#/units/${UNIT}`);
    expect(
      screen
        .getByRole("link", { name: "Invoice 55555555" })
        .getAttribute("href"),
    ).toBe("#/invoices/inv%3A55555555-eeee-4eee-8eee-555555555555");
    expect(
      screen.queryByRole("link", { name: "Final Settlement 55555555" }),
    ).toBeNull();
    expect(screen.getByText(/^3 events/)).toBeTruthy();

    api.search.mockResolvedValueOnce({
      events: [
        event({
          event_id: "e4",
          action: "customer.created",
          resource_type: "customer",
        }),
      ],
      nextCursor: null,
    });
    fireEvent.click(screen.getByRole("button", { name: "Show more" }));
    await screen.findByText(/^4 events/);
    expect(api.search).toHaveBeenLastCalledWith("property-1", {
      from: "2026-10-19",
      cursor: "c2",
    });
    expect(screen.queryByRole("button", { name: "Show more" })).toBeNull();

    // Show more, then a new search before it answers: Show more works again after.
    let answerMore: (page: Page) => void = () => undefined;
    api.search
      .mockResolvedValueOnce(FIRST)
      .mockImplementationOnce(
        () =>
          new Promise<Page>((resolve) => {
            answerMore = resolve;
          }),
      )
      .mockResolvedValueOnce(FIRST);
    fireEvent.click(screen.getByRole("button", { name: "Today" }));
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    await screen.findByText(/^3 events/);
    expect(api.search).toHaveBeenLastCalledWith("property-1", {
      from: "2026-10-25",
    });
    fireEvent.click(screen.getByRole("button", { name: "Show more" }));
    fireEvent.click(screen.getByRole("button", { name: "All" }));
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    await screen.findByText(/^3 events/);
    expect(api.search).toHaveBeenLastCalledWith("property-1", {});
    answerMore({ events: [], nextCursor: null });
    expect(
      screen.getByRole<HTMLButtonElement>("button", { name: "Show more" })
        .disabled,
    ).toBe(false);
    expect(actionText("lease.move_out.final_inputs.record")).toBe(
      "Lease move out final inputs record",
    );
    expect(kindOf("unit_cleaning_rate")).toBe("unit");
    expect(kindOf("ServiceRate")).toBe("setting");
    expect(kindOf("something_new")).toBe("other");
  });

  it("TEST-FE-959 Search sends the period, the person and the Unit; Export audit sends the same filters and saves the file; a refused export says why; no audit.export hides it", async () => {
    const createObjectURL = vi.fn(() => "blob:x");
    vi.stubGlobal(
      "URL",
      Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() }),
    );
    const { api, exporter } = setup();
    await screen.findByRole("table");
    await waitFor(() => {
      expect(
        within(screen.getByLabelText("Who")).getAllByRole("option").length,
      ).toBe(3);
    });
    fireEvent.click(screen.getByRole("button", { name: "30 days" }));
    fireEvent.change(screen.getByLabelText("Who"), {
      target: { value: DARA },
    });
    await waitFor(() => {
      expect(
        within(screen.getByLabelText("Unit")).getAllByRole("option").length,
      ).toBe(2);
    });
    fireEvent.change(screen.getByLabelText("Unit"), {
      target: { value: UNIT },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => {
      expect(api.search).toHaveBeenLastCalledWith("property-1", {
        from: "2026-09-26",
        actorId: DARA,
        unitId: UNIT,
      });
    });
    await screen.findByRole("table");
    fireEvent.click(
      screen.getByRole("button", {
        name: "Export audit · Spreadsheet (.xlsx)",
      }),
    );
    expect(
      await screen.findByText(
        "history.xlsx is ready. Its fingerprint is written to History.",
      ),
    ).toBeTruthy();
    expect(exporter.exportAudit).toHaveBeenCalledWith("property-1", {
      fileType: "xlsx",
      from: "2026-09-26",
      to: "2026-10-25",
      actorId: DARA,
      unitId: UNIT,
    });
    expect(createObjectURL).toHaveBeenCalled();
    // A big file is made as a job and fetched.
    exporter.exportAudit.mockResolvedValueOnce({
      kind: "job",
      exportId: "x2",
      fileName: "history.pdf",
      sha256: "def",
      rowCount: 900,
      expiresAt: "2026-10-26T00:00:00Z",
    } as never);
    exporter.download.mockResolvedValueOnce({
      fileName: "history.pdf",
      sha256: "def",
      file: new Blob(["y"]),
    } as never);
    fireEvent.click(screen.getByRole("button", { name: "Export audit · PDF" }));
    expect(
      await screen.findByText(
        "history.pdf is ready. Its fingerprint is written to History.",
      ),
    ).toBeTruthy();
    expect(exporter.download).toHaveBeenCalledWith("property-1", "x2");
    exporter.exportAudit.mockRejectedValueOnce(new ExportRefusedError());
    fireEvent.click(screen.getByRole("button", { name: "Export audit · PDF" }));
    expect(
      await screen.findByText(
        "This file cannot be made with these choices. Choose fewer days, or a spreadsheet instead of a PDF.",
      ),
    ).toBeTruthy();
    cleanup();

    setup(undefined, new Set(["audit.view"]));
    await screen.findByRole("table");
    expect(screen.queryByRole("button", { name: /Export audit/ })).toBeNull();
  });

  it("TEST-FE-960 no right says so; a failed read offers Retry; no events says so; names that cannot be read show a short id", async () => {
    setup(() => Promise.reject(new HistoryNotAllowedError()));
    expect(
      await screen.findByText(
        "Your account cannot see History. Use the menu to open your work.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    cleanup();

    let fail = true;
    setup(() =>
      fail
        ? Promise.reject(new Error("down"))
        : Promise.resolve({ events: [], nextCursor: null }),
    );
    const retry = await screen.findByRole("button", { name: "Retry" });
    fail = false;
    fireEvent.click(retry);
    expect(await screen.findByText("No events match.")).toBeTruthy();
    cleanup();

    setup(undefined, null, false);
    await screen.findByRole("table");
    expect(rows()[0]?.[1]).toBe("A user (22222222)");
    expect(rows()[1]?.[1]).toBe("Kompheak (you)");
    cleanup();

    // React's StrictMode runs effects twice: still one search, and the list shows.
    const once = vi.fn(() => Promise.resolve(FIRST));
    render(
      <StrictMode>
        <HistoryPage
          active
          api={{ search: once }}
          capabilities={null}
          exporter={{ exportAudit: vi.fn(), download: vi.fn() }}
          language="en"
          me={{ id: ME, name: "Kompheak" }}
          people={() => Promise.resolve([])}
          propertyId="property-1"
          today="2026-10-25"
          units={{ list: vi.fn(() => Promise.reject(new Error("x"))) }}
        />
      </StrictMode>,
    );
    await screen.findByRole("table");
    expect(once).toHaveBeenCalledTimes(1);
  });
});
