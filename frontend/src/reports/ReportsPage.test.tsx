import {
  act,
  cleanup,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ExportGoneError,
  ExportRefusedError,
  ReportsNotAllowedError,
  ReportsUnavailableError,
  type TotalsPage,
} from "../reportsClient";
import { openPageInAddress } from "../shell/useHashPage";
import type { ReportApi } from "./ReportsPage";
import {
  bodyRows,
  emptyPage,
  facts,
  headRow,
  INCOME,
  MANAGER,
  openReports,
  PROPERTY,
  SAVED,
  STAFF,
} from "./reportsTestData";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const TOTALS_NAMES = [
  "Total Income",
  "Total Payment",
  "Total Electricity",
  "Total Water",
];

/** The report names on the cards of one group of the list. */
function cardNames(group: string): (string | undefined)[] {
  return within(screen.getByRole("region", { name: group }))
    .getAllByRole("link")
    .map((card) => card.querySelector(".rp-card-name")?.textContent);
}

/** Saving a file: the object URL and the link the page clicks. */
function stubSave() {
  const createObjectURL = vi.fn(() => "blob:report");
  const revokeObjectURL = vi.fn();
  vi.stubGlobal(
    "URL",
    Object.assign(URL, { createObjectURL, revokeObjectURL }),
  );
  const click = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => undefined);
  return { createObjectURL, revokeObjectURL, click };
}

describe("Reports list", () => {
  it("TEST-FE-1030 lists every report in two groups in the owner's order, each with its line, the Owner and Manager tag on the money and audit reports, and Open report; a card opens its report", async () => {
    const page = openReports();
    expect(cardNames("Totals by Parking and month")).toEqual(TOTALS_NAMES);
    expect(cardNames("Registers and lists")).toEqual([
      "Invoice register and balances",
      "Payments and allocations",
      "Utility consumption",
      "Customer Credit ledger",
      "Deposit liability and disposition",
      "Final Settlement register",
      "Parking occupancy",
      "Lease dates",
      "Audit activity",
    ]);
    const income = screen.getByRole("link", { name: /^Total Income/ });
    expect(income).toHaveAttribute("href", "#/reports/total_income");
    expect(
      within(income).getByText(
        "Invoiced amounts for each Parking, month by month",
      ),
    ).toBeTruthy();
    expect(within(income).getByText("Owner and Manager")).toBeTruthy();
    expect(within(income).getByText("Open report")).toBeTruthy();
    expect(
      within(
        screen.getByRole("link", { name: /^Parking occupancy/ }),
      ).queryByText("Owner and Manager"),
    ).toBeNull();
    expect(screen.getAllByText("Owner and Manager")).toHaveLength(10);
    expect(screen.getAllByText("Open report")).toHaveLength(13);
    expect(
      screen.getByText(/^Staff see the operational reports only\./),
    ).toBeTruthy();
    expect(page.totals).not.toHaveBeenCalled();
    expect(page.register).not.toHaveBeenCalled();

    fireEvent.click(income);
    expect(
      await screen.findByRole("heading", { level: 2, name: "Total Income" }),
    ).toBeTruthy();
    await screen.findByRole("table", { name: "Total Income" });
    expect(page.totals).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("link", { name: "All reports" })).toHaveAttribute(
      "href",
      "#/reports",
    );
  });

  it("TEST-FE-1031 shows only the reports the account may read: Staff see Utility consumption, Parking occupancy and Lease dates; History adds Audit activity; the money right adds the Totals tables and the money registers", () => {
    openReports({ capabilities: STAFF });
    expect(
      screen.queryByRole("region", { name: "Totals by Parking and month" }),
    ).toBeNull();
    expect(cardNames("Registers and lists")).toEqual([
      "Utility consumption",
      "Parking occupancy",
      "Lease dates",
    ]);
    expect(screen.queryByText("Owner and Manager")).toBeNull();
    cleanup();

    openReports({ capabilities: new Set([...STAFF, "audit.view"]) });
    expect(cardNames("Registers and lists")).toEqual([
      "Utility consumption",
      "Parking occupancy",
      "Lease dates",
      "Audit activity",
    ]);
    cleanup();

    // Units without Leases and Reservations are not enough for Unit occupancy.
    openReports({ capabilities: new Set(["reports.read", "units.read"]) });
    expect(cardNames("Totals by Parking and month")).toEqual(TOTALS_NAMES);
    expect(cardNames("Registers and lists")).toEqual([
      "Invoice register and balances",
      "Payments and allocations",
      "Customer Credit ledger",
      "Deposit liability and disposition",
      "Final Settlement register",
    ]);
  });

  it("TEST-FE-1032 an account that may read no report sees a calm note and no cards", () => {
    openReports({ capabilities: new Set(["payments.read"]) });
    expect(screen.getByRole("note")).toHaveTextContent(
      "Your account cannot see any report. Ask the Owner if you need one.",
    );
    expect(screen.queryAllByRole("link")).toHaveLength(0);
    expect(screen.queryByRole("region")).toBeNull();
  });
});

describe("Report states", () => {
  it("TEST-FE-1033 a report the account may not read says so, with no parameter bar and no request; All reports goes back to the list", async () => {
    const page = openReports({
      hash: "#/reports/total_income",
      capabilities: STAFF,
    });
    expect(
      screen.getByRole("heading", { level: 2, name: "Total Income" }),
    ).toBeTruthy();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Your account cannot see this report. Ask the Owner if you need it.",
    );
    expect(screen.queryByRole("group", { name: "Period" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Export" })).toBeNull();
    expect(page.totals).not.toHaveBeenCalled();
    expect(page.register).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("link", { name: "All reports" }));
    expect(
      await screen.findByRole("region", { name: "Registers and lists" }),
    ).toBeTruthy();
    expect(cardNames("Registers and lists")).toEqual([
      "Utility consumption",
      "Parking occupancy",
      "Lease dates",
    ]);
  });

  it("TEST-FE-1034 when the server refuses the report (403) the page says calmly that the account cannot see it, without Retry or the parameter bar", async () => {
    openReports({
      hash: "#/reports/payments",
      register: () => Promise.reject(new ReportsNotAllowedError()),
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Your account cannot see this report. Ask the Owner if you need it.",
    );
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    expect(screen.queryByRole("group", { name: "Period" })).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("TEST-FE-1035 a report that cannot be read offers Retry, which reads it again; Export waits for the report", async () => {
    const totals = vi
      .fn<ReportApi["totals"]>()
      .mockRejectedValueOnce(new ReportsUnavailableError())
      .mockResolvedValue(INCOME);
    const page = openReports({
      hash: "#/reports/total_income",
      capabilities: MANAGER,
      totals,
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The report could not be read just now. Check the connection and try again.",
    );
    expect(screen.getByRole("button", { name: "Export" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByRole("table", { name: "Total Income" });
    expect(page.totals).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("button", { name: "Export" })).toBeEnabled();
  });

  it("TEST-FE-1036 a report with no records says so with the Generated line and no Summary; a report of today says No records", async () => {
    openReports({
      hash: "#/reports/total_income",
      totals: () => Promise.resolve({ ...INCOME, years: [] }),
    });
    const empty = await screen.findByRole("region", { name: "Total Income" });
    expect(within(empty).getByText("No records for this period.")).toBeTruthy();
    expect(
      within(empty).getByText(
        "Generated 28/10/2026, 10:30 · Phnom Penh time · amounts in USD; riel shown as information only",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Summary" })).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
    cleanup();

    openReports({
      hash: "#/reports/deposits",
      register: (_property, name) => Promise.resolve(emptyPage(name)),
    });
    expect(await screen.findByText("No records.")).toBeTruthy();
    expect(screen.queryByText("No records for this period.")).toBeNull();
  });

  it("TEST-FE-1037 while the report is read the page says so and Export waits", async () => {
    let answer: (page: TotalsPage) => void = () => undefined;
    openReports({
      hash: "#/reports/total_income",
      capabilities: MANAGER,
      totals: () =>
        new Promise((resolve) => {
          answer = resolve;
        }),
    });
    expect(screen.getByText("Reading the report…")).toHaveAttribute(
      "role",
      "status",
    );
    expect(screen.getByRole("button", { name: "Export" })).toBeDisabled();
    expect(screen.queryByRole("table")).toBeNull();

    act(() => {
      answer(INCOME);
    });
    await screen.findByRole("table", { name: "Total Income" });
    expect(screen.queryByText("Reading the report…")).toBeNull();
    expect(screen.getByRole("button", { name: "Export" })).toBeEnabled();
  });
});

describe("Export", () => {
  it("TEST-FE-1052 Export shows the report, scope, period and rows, warns about personal data and History, and sends the chosen PDF with the floor and period; the file is saved", async () => {
    const save = stubSave();
    const file = new Blob(["pdf"]);
    const page = openReports({
      hash: "#/reports/invoice_register",
      capabilities: MANAGER,
      exportFile: () =>
        Promise.resolve({ ...SAVED, fileName: "invoice-register.pdf", file }),
    });
    await screen.findByRole("table", { name: "Invoice register and balances" });
    const scope = screen.getByRole("combobox", { name: "Scope" });
    await waitFor(() => {
      expect(within(scope).getAllByRole("option")).toHaveLength(3);
    });
    fireEvent.change(scope, { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "This month" }));
    await waitFor(() => {
      expect(page.register).toHaveBeenLastCalledWith(
        PROPERTY,
        "invoice_register",
        { floor: "2", from: "2026-10-01", to: "2026-10-28", limit: 200 },
      );
    });
    await screen.findByRole("table", { name: "Invoice register and balances" });

    fireEvent.click(screen.getByRole("button", { name: "Export" }));
    const dialog = screen.getByRole("dialog", {
      name: "Export · Invoice register and balances",
    });
    expect(facts(dialog)).toEqual([
      ["Report", "Invoice register and balances"],
      ["Scope", "Floor 2"],
      ["Period", "01/10/2026 to 28/10/2026"],
      ["Rows", "5"],
    ]);
    expect(
      within(dialog).getByRole("radio", { name: "Spreadsheet (.xlsx)" }),
    ).toBeChecked();
    expect(
      within(dialog).getByText(
        "This file has personal data (names, Parking, phone numbers). Keep it inside the business and delete it when done.",
      ),
    ).toBeTruthy();
    expect(
      within(dialog).getByText(/^Every export is written to History/),
    ).toBeTruthy();
    expect(
      within(dialog).queryByText(/^A PDF holds at most 5,000 rows/),
    ).toBeNull();
    fireEvent.click(within(dialog).getByRole("radio", { name: "PDF" }));
    expect(
      within(dialog).getByText(/^A PDF holds at most 5,000 rows/),
    ).toBeTruthy();

    fireEvent.click(within(dialog).getByRole("button", { name: "Export" }));
    expect(
      await screen.findByText(
        "invoice-register.pdf is ready. The export is written to History.",
      ),
    ).toBeTruthy();
    expect(page.exportFile).toHaveBeenCalledTimes(1);
    expect(page.exportFile).toHaveBeenCalledWith(PROPERTY, {
      report: "invoice_register",
      fileType: "pdf",
      floor: "2",
      from: "2026-10-01",
      to: "2026-10-28",
    });
    expect(page.download).not.toHaveBeenCalled();
    expect(save.createObjectURL).toHaveBeenCalledWith(file);
    expect(save.click).toHaveBeenCalledTimes(1);
    expect((save.click.mock.contexts[0] as HTMLAnchorElement).download).toBe(
      "invoice-register.pdf",
    );
    expect(save.revokeObjectURL).toHaveBeenCalledWith("blob:report");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("TEST-FE-1053 a Totals export sends the Parking and the period, has no Rows line, and fetches a big file from its export job", async () => {
    const save = stubSave();
    const page = openReports({
      hash: "#/reports/total_payment",
      capabilities: MANAGER,
      exportFile: () =>
        Promise.resolve({
          kind: "job",
          exportId: "export-9",
          fileName: "total-payment.xlsx",
          sha256: "def",
          rowCount: 1500,
          expiresAt: "2026-10-29T03:30:00Z",
        }),
      download: () =>
        Promise.resolve({
          fileName: "total-payment.xlsx",
          sha256: "def",
          file: new Blob(["xlsx"]),
        }),
    });
    await screen.findByRole("table", { name: "Total Payment" });
    const unit = screen.getByRole("combobox", { name: "Parking" });
    await waitFor(() => {
      expect(
        within(unit)
          .getAllByRole("option")
          .map((option) => option.textContent),
      ).toEqual(["All Parking", "U101", "U203", "U204"]);
    });
    fireEvent.change(unit, { target: { value: "unit-203" } });
    fireEvent.click(screen.getByRole("button", { name: "Last month" }));
    await waitFor(() => {
      expect(page.totals).toHaveBeenLastCalledWith(PROPERTY, "total_payment", {
        unitId: "unit-203",
        from: "2026-09-01",
        to: "2026-09-30",
      });
    });
    await screen.findByRole("table", { name: "Total Payment" });

    fireEvent.click(screen.getByRole("button", { name: "Export" }));
    const dialog = screen.getByRole("dialog", {
      name: "Export · Total Payment",
    });
    expect(facts(dialog)).toEqual([
      ["Report", "Total Payment"],
      ["Scope", "U203"],
      ["Period", "01/09/2026 to 30/09/2026"],
    ]);
    fireEvent.click(within(dialog).getByRole("button", { name: "Export" }));
    expect(
      await screen.findByText(
        "total-payment.xlsx is ready. The export is written to History.",
      ),
    ).toBeTruthy();
    expect(page.exportFile).toHaveBeenCalledWith(PROPERTY, {
      report: "total_payment",
      fileType: "xlsx",
      unitId: "unit-203",
      from: "2026-09-01",
      to: "2026-09-30",
    });
    expect(page.download).toHaveBeenCalledWith(PROPERTY, "export-9");
    expect(save.click).toHaveBeenCalledTimes(1);
    expect((save.click.mock.contexts[0] as HTMLAnchorElement).download).toBe(
      "total-payment.xlsx",
    );
  });

  it("TEST-FE-1054 an export that cannot be made says why and keeps the dialog open: refused, not allowed, no longer kept, or not made just now; Cancel closes it", async () => {
    stubSave();
    const exportFile = vi
      .fn<ReportApi["exportFile"]>()
      .mockRejectedValueOnce(new ExportRefusedError())
      .mockRejectedValueOnce(new ReportsNotAllowedError())
      .mockResolvedValueOnce({
        kind: "job",
        exportId: "export-2",
        fileName: "deposits.xlsx",
        sha256: "def",
        rowCount: 3,
        expiresAt: "2026-10-29T03:30:00Z",
      })
      .mockRejectedValueOnce(new Error("offline"));
    const download = vi
      .fn<ReportApi["download"]>()
      .mockRejectedValueOnce(new ExportGoneError());
    const page = openReports({
      hash: "#/reports/deposits",
      capabilities: MANAGER,
      exportFile,
      download,
    });
    await screen.findByRole("table", {
      name: "Deposit liability and disposition",
    });
    fireEvent.click(screen.getByRole("button", { name: "Export" }));
    const dialog = screen.getByRole("dialog", {
      name: "Export · Deposit liability and disposition",
    });
    expect(facts(dialog)).toEqual([
      ["Report", "Deposit liability and disposition"],
      ["Scope", "Whole Property"],
      ["Period", "As of 28/10/2026"],
      ["Rows", "3"],
    ]);
    const send = () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "Export" }));
    };
    const says = async (text: string) => {
      await waitFor(() => {
        expect(within(dialog).getByRole("alert")).toHaveTextContent(text);
      });
    };

    send();
    await says(
      "This file cannot be made with these choices. Choose a shorter period, or a spreadsheet instead of a PDF.",
    );
    expect(
      within(dialog).getByRole("button", { name: "Export" }),
    ).toBeEnabled();
    send();
    await says("Your account cannot export this report.");
    send();
    await says("The file is no longer kept. Export it again.");
    expect(page.download).toHaveBeenCalledWith(PROPERTY, "export-2");
    send();
    await says("The file could not be made just now. Try again.");
    // Deposit liability shows today: no period and no floor are sent.
    expect(page.exportFile).toHaveBeenLastCalledWith(PROPERTY, {
      report: "deposits",
      fileType: "xlsx",
    });
    expect(screen.queryByText(/is ready/)).toBeNull();

    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("TEST-FE-1055 Export shows only with the export right and the report's own read right", async () => {
    openReports({
      hash: "#/reports/total_income",
      capabilities: new Set(["reports.read"]),
    });
    await screen.findByRole("table", { name: "Total Income" });
    expect(screen.queryByRole("button", { name: "Export" })).toBeNull();
    cleanup();

    openReports({
      hash: "#/reports/total_income",
      capabilities: new Set(["reports.read", "data.export"]),
    });
    await screen.findByRole("table", { name: "Total Income" });
    expect(screen.getByRole("button", { name: "Export" })).toBeEnabled();
    cleanup();

    // Staff with the export right export the reports they may read.
    openReports({
      hash: "#/reports/unit_occupancy",
      capabilities: new Set([...STAFF, "data.export"]),
    });
    await screen.findByRole("table", { name: "Parking occupancy" });
    expect(screen.getByRole("button", { name: "Export" })).toBeEnabled();
  });
});

describe("Language and parameters", () => {
  it("TEST-FE-1056 the page follows the language switch: the list and a Totals table in Khmer, with the same numbers and no new request", async () => {
    openReports({ language: "km" });
    expect(
      screen.getByRole("region", { name: "សរុបតាមចំណត និងខែ" }),
    ).toBeTruthy();
    expect(cardNames("សរុបតាមចំណត និងខែ")[0]).toBe("ចំណូលសរុប");
    expect(screen.getAllByText("បើករបាយការណ៍")).toHaveLength(13);
    cleanup();

    const page = openReports({ hash: "#/reports/total_income" });
    await screen.findByRole("table", { name: "Total Income" });
    page.rerender({ language: "km" });
    expect(
      screen.getByRole("heading", { level: 2, name: "ចំណូលសរុប" }),
    ).toBeTruthy();
    expect(screen.getByRole("link", { name: "របាយការណ៍ទាំងអស់" })).toBeTruthy();
    const table = screen.getByRole("table", { name: "ចំណូលសរុប" });
    expect(headRow(table)).toEqual([
      "ឆ្នាំ",
      "មករា",
      "កុម្ភៈ",
      "មីនា",
      "មេសា",
      "ឧសភា",
      "មិថុនា",
      "កក្កដា",
      "សីហា",
      "កញ្ញា",
      "តុលា",
      "វិច្ឆិកា",
      "ធ្នូ",
      "សរុប",
    ]);
    expect(bodyRows(table)[0]?.slice(0, 3)).toEqual([
      "2026",
      "$1,000.00",
      "$1,000.00",
    ]);
    expect(screen.getByRole("region", { name: "សង្ខេប" })).toBeTruthy();
    expect(
      within(screen.getByRole("group", { name: "រយៈពេល" }))
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual(["ទាំងអស់", "ខែនេះ", "ខែមុន", "ជ្រើសថ្ងៃ"]);
    expect(
      screen.getByText(
        "បង្កើត 28/10/2026, 10:30 · ម៉ោងភ្នំពេញ · ចំនួនជាដុល្លារ; រៀលបង្ហាញជាព័ត៌មានប៉ុណ្ណោះ",
      ),
    ).toBeTruthy();
    expect(page.totals).toHaveBeenCalledTimes(1);

    page.rerender({ language: "en" });
    expect(screen.getByRole("table", { name: "Total Income" })).toBeTruthy();
    expect(page.totals).toHaveBeenCalledTimes(1);
  });

  it("TEST-FE-1059 the scope and period stay the same from one report to the next while the page is open; another Property starts again from the whole Property and all dates", async () => {
    const page = openReports({ hash: "#/reports/invoice_register" });
    await screen.findByRole("table", { name: "Invoice register and balances" });
    const scope = screen.getByRole("combobox", { name: "Scope" });
    await waitFor(() => {
      expect(within(scope).getAllByRole("option")).toHaveLength(3);
    });
    fireEvent.change(scope, { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Last month" }));
    await waitFor(() => {
      expect(page.register).toHaveBeenLastCalledWith(
        PROPERTY,
        "invoice_register",
        { floor: "2", from: "2026-09-01", to: "2026-09-30", limit: 200 },
      );
    });

    act(() => {
      openPageInAddress("reports", false, "payments");
    });
    await screen.findByRole("table", { name: "Payments and allocations" });
    expect(page.register).toHaveBeenLastCalledWith(PROPERTY, "payments", {
      floor: "2",
      from: "2026-09-01",
      to: "2026-09-30",
      limit: 200,
    });
    expect(screen.getByRole("combobox", { name: "Scope" })).toHaveValue("2");
    expect(screen.getByRole("button", { name: "Last month" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    const before = page.register.mock.calls.length;
    page.rerender({ propertyId: "property-2" });
    await screen.findByRole("table", { name: "Payments and allocations" });
    expect(page.register.mock.calls.slice(before)).toEqual([
      ["property-2", "payments", { limit: 200 }],
    ]);
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("combobox", { name: "Scope" })).toHaveValue("");
    await waitFor(() => {
      expect(page.units.list).toHaveBeenCalledWith("property-2", {});
    });
  });
});
