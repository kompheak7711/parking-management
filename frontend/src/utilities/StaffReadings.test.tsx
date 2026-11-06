import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { StaffReadings } from "./StaffReadings";
import {
  type StaffDecision,
  type StaffReadingRun,
  type StaffReadingsApi,
  staffReadingsApi,
} from "./staffReadingsClient";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const PROPERTY = "11111111-1111-4111-8111-111111111111";

function runs(): StaffReadingRun[] {
  return [
    {
      run_id: "run-1",
      reading_date: "2026-11-24",
      sent_at: "2026-11-24T02:10:00Z",
      sent_by: "Son Sokhen",
      readings: [
        {
          proposal_id: "p-1",
          unit_id: "u-1",
          unit: "A101",
          utility_type: "ELECTRICITY",
          reading_value: "4236",
          last_value: "4120",
          last_date: "2026-10-24",
          flag: null,
          already: false,
        },
        {
          proposal_id: "p-2",
          unit_id: "u-3",
          unit: "A103",
          utility_type: "ELECTRICITY",
          reading_value: "5198",
          last_value: "5210",
          last_date: "2026-10-24",
          flag: "LOWER",
          already: false,
        },
        {
          proposal_id: "p-3",
          unit_id: "u-3",
          unit: "A103",
          utility_type: "WATER",
          reading_value: "709",
          last_value: null,
          last_date: null,
          flag: null,
          already: true,
        },
      ],
    },
  ];
}

function fakeApi(found: StaffReadingRun[]) {
  const calls: [string[], StaffDecision][] = [];
  let waiting = found;
  const api: StaffReadingsApi = {
    waiting: vi.fn(() => Promise.resolve(waiting)),
    decide: vi.fn(
      (_property: string, ids: string[], decision: StaffDecision) => {
        calls.push([ids, decision]);
        const already =
          decision === "CONFIRMED" && ids.includes("p-3") ? ["A103"] : [];
        waiting = waiting
          .map((run) => ({
            ...run,
            readings: run.readings.filter(
              (reading) =>
                !ids.includes(reading.proposal_id) ||
                already.includes(reading.unit),
            ),
          }))
          .filter((run) => run.readings.length > 0);
        return Promise.resolve({
          decision,
          done: ids.length - (already.length > 0 ? 1 : 0),
          already,
        });
      },
    ),
  };
  return { api, calls };
}

describe("Staff bot readings in Utilities", () => {
  it("TEST-FE-1517 readings from the Staff bot show a card; Check readings lists them with the previous and current reading, ticks only the ones that look right, and Confirm saves them", async () => {
    const { api, calls } = fakeApi(runs());
    const onSaved = vi.fn();
    render(
      <StaffReadings
        active
        api={api}
        language="en"
        onSaved={onSaved}
        propertyId={PROPERTY}
      />,
    );
    expect(
      await screen.findByText(
        "3 readings from the Staff bot wait for your check.",
      ),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Check readings" }));
    const dialog = screen.getByRole("dialog", {
      name: "Readings from the Staff bot",
    });
    const region = within(dialog).getByRole("region", {
      name: "Sent by Son Sokhen, read on 24/11/2026",
    });
    const rows = within(region).getAllByRole("row");
    expect(rows).toHaveLength(4);
    const row = (index: number) => {
      const found = rows[index];
      if (found === undefined) throw new Error("no row");
      return within(found);
    };
    expect(row(1).getByText("4,120")).toBeTruthy();
    expect(row(1).getByText("4,236")).toBeTruthy();
    expect(row(1).getByText("Ready")).toBeTruthy();
    expect(row(2).getByText(/Lower than previous/)).toBeTruthy();
    expect(row(3).getByText(/already saved for that day/)).toBeTruthy();
    const box = (name: string): HTMLInputElement => {
      const found = within(dialog).getByRole("checkbox", { name });
      if (!(found instanceof HTMLInputElement)) throw new Error("no box");
      return found;
    };
    expect(box("A101 Electricity").checked).toBe(true);
    expect(box("A103 Electricity").checked).toBe(false);
    expect(box("A103 Water").checked).toBe(false);
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Confirm readings" }),
    );
    await waitFor(() => {
      expect(calls).toEqual([[["p-1"], "CONFIRMED"]]);
    });
    expect(
      await screen.findByText("1 readings confirmed and saved."),
    ).toBeTruthy();
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(
      await screen.findByText(
        "2 readings from the Staff bot wait for your check.",
      ),
    ).toBeTruthy();
  });

  it("TEST-FE-1518 Ask to read again names the Units, a reading already saved that day is left waiting, Don't use closes it, and nothing ticked is refused on the screen", async () => {
    const { api, calls } = fakeApi(runs());
    render(
      <StaffReadings
        active
        api={api}
        language="en"
        onSaved={vi.fn()}
        propertyId={PROPERTY}
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Check readings" }),
    );
    let dialog = screen.getByRole("dialog");
    fireEvent.click(
      within(dialog).getByRole("checkbox", { name: "A101 Electricity" }),
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Ask to read again" }),
    );
    expect(within(dialog).getByText("Tick at least one reading.")).toBeTruthy();
    expect(calls).toEqual([]);
    fireEvent.click(
      within(dialog).getByRole("checkbox", { name: "A103 Electricity" }),
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Ask to read again" }),
    );
    expect(
      await screen.findByText("The meter reader was asked to read A103 again."),
    ).toBeTruthy();

    fireEvent.click(
      await screen.findByRole("button", { name: "Check readings" }),
    );
    dialog = screen.getByRole("dialog");
    fireEvent.click(
      within(dialog).getByRole("checkbox", { name: "A103 Water" }),
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Confirm readings" }),
    );
    expect(
      await screen.findByText(
        /Not saved, a reading for that day is already there: A103/,
      ),
    ).toBeTruthy();
    fireEvent.click(
      await screen.findByRole("button", { name: "Check readings" }),
    );
    dialog = screen.getByRole("dialog");
    fireEvent.click(
      within(dialog).getByRole("checkbox", { name: "A103 Water" }),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Don't use" }));
    expect(await screen.findByText("1 readings not used.")).toBeTruthy();
    expect(calls).toEqual([
      [["p-2"], "ASK_AGAIN"],
      [["p-1", "p-3"], "CONFIRMED"],
      [["p-3"], "NOT_USED"],
    ]);
    expect(screen.queryByRole("button", { name: "Check readings" })).toBeNull();
  });

  it("TEST-FE-1519 nothing shows when no reading waits or the list cannot be read, and the client sends the answer with the CSRF token and refuses a list of the wrong shape", async () => {
    const empty = fakeApi([]);
    const { container } = render(
      <StaffReadings
        active
        api={empty.api}
        language="km"
        onSaved={vi.fn()}
        propertyId={PROPERTY}
      />,
    );
    await waitFor(() => {
      expect(empty.api.waiting).toHaveBeenCalledTimes(1);
    });
    expect(container.textContent).toBe("");
    cleanup();
    const broken: StaffReadingsApi = {
      waiting: () => Promise.reject(new Error("offline")),
      decide: vi.fn(),
    };
    const second = render(
      <StaffReadings
        active
        api={broken}
        language="en"
        onSaved={vi.fn()}
        propertyId={PROPERTY}
      />,
    );
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(second.container.textContent).toBe("");

    Object.defineProperty(document, "cookie", {
      configurable: true,
      value: "__Host-prm_csrf=meters-token",
      writable: true,
    });
    const fetched: [string, RequestInit | undefined][] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        fetched.push([url, init]);
        const data = url.endsWith("/decisions")
          ? { decision: "NOT_USED", done: 2, already: [] }
          : runs();
        return Promise.resolve(
          new Response(JSON.stringify({ data }), { status: 200 }),
        );
      }),
    );
    expect(
      (await staffReadingsApi.waiting(PROPERTY))[0]?.readings,
    ).toHaveLength(3);
    expect(
      await staffReadingsApi.decide(PROPERTY, ["p-1", "p-2"], "NOT_USED"),
    ).toEqual({
      decision: "NOT_USED",
      done: 2,
      already: [],
    });
    expect(fetched[0]?.[0]).toBe(
      `/api/v1/properties/${PROPERTY}/staff-meter-readings`,
    );
    const sent = fetched[1];
    if (sent === undefined) throw new Error("not sent");
    const [url, init] = sent;
    expect(url).toBe(
      `/api/v1/properties/${PROPERTY}/staff-meter-readings/decisions`,
    );
    expect(init?.method).toBe("POST");
    expect((init?.headers as Record<string, string>)["X-CSRF-Token"]).toBe(
      "meters-token",
    );
    expect(typeof init?.body).toBe("string");
    expect(JSON.parse(init?.body as string)).toEqual({
      proposal_ids: ["p-1", "p-2"],
      decision: "NOT_USED",
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(JSON.stringify({ data: [{ run_id: 1 }] }), {
            status: 200,
          }),
        ),
      ),
    );
    await expect(staffReadingsApi.waiting(PROPERTY)).rejects.toThrow(
      "The staff readings command was not completed.",
    );
  });
});
