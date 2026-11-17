// DL-243: the Joint Inspection screens. TEST-FE-2290 to TEST-FE-2299.
// DL-244: the printed copy and the Unit page card. TEST-FE-2305 and TEST-FE-2306.
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { InspectionsPage } from "../inspections/InspectionsPage";
import { type ProblemsApi, reportOf } from "../problems/problemsClient";
import {
  type FileRole,
  type JointApi,
  type JointChanges,
  JointError,
  type JointInspection,
  type JointLine,
  type JointRow,
  inspectionOf,
} from "./jointClient";
import { LeaseJointCard } from "./LeaseJointCard";
import { UnitJointCard } from "./UnitJointCard";

const PROPERTY = "p-1";
const ALL = new Set([
  "units.read",
  "joint_inspections.record",
  "joint_inspections.replace",
]);
const STAFF = new Set(["units.read", "joint_inspections.record"]);

beforeEach(() => {
  window.location.hash = "#/inspections";
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  HTMLCanvasElement.prototype.toBlob = function toBlob(callback: BlobCallback) {
    callback(new Blob(["signature"], { type: "image/png" }));
  };
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.location.hash = "";
});

function line(extra: Partial<JointLine>): JointLine {
  return {
    line_id: "l-bed",
    ordinal: 1,
    line_kind: "PLACE",
    group_en: "Bedroom",
    group_km: "បន្ទប់គេង",
    item_name: null,
    item_name_km: null,
    item_type_name: null,
    item_type_name_km: null,
    quantity: null,
    result: null,
    note: null,
    tenant_caused: false,
    pet_caused: false,
    move_in_result: null,
    move_in_note: null,
    problem_report: null,
    finding_id: null,
    photos: [],
    ...extra,
  };
}

function inspection(extra: Partial<JointInspection> = {}): JointInspection {
  return {
    inspection_id: "ji-1",
    inspection_number: "JI260001",
    kind: "MOVE_IN",
    status: "DRAFT",
    version: 1,
    inspection_date: "2026-11-16",
    lease_id: "lease-1",
    lease_number: "U101L0026",
    unit_id: "u-101",
    unit_number: "U101",
    tenant_name: "Sok Dara",
    move_in_id: null,
    move_in_number: null,
    replaces: null,
    replace_reason: null,
    replaced_by: null,
    keys: {
      door_keys: null,
      key_cards: null,
      mailbox_keys: null,
      other_keys: null,
      other_keys_note: null,
    },
    move_in_keys: null,
    started_by: "Chan Staff",
    done_at: null,
    done_by: null,
    lines: [
      line({}),
      line({
        line_id: "l-bed-item",
        ordinal: 2,
        line_kind: "ITEM",
        item_name: "Bed",
        item_type_name: "Furniture",
        quantity: 1,
      }),
      line({
        line_id: "l-ac",
        ordinal: 3,
        line_kind: "BUILT_IN",
        group_en: "Built-in",
        group_km: "ភ្ជាប់ជាប់",
        item_name: "Air conditioner",
      }),
    ],
    meters: [
      {
        utility_type: "ELECTRICITY",
        serial_number: "MEL260001",
        measurement_unit_code: "KWH",
        reading: null,
        utilities_reading: null,
        move_in_reading: null,
        photo: null,
      },
    ],
    signatures: { tenant: null, staff: null },
    move_out_inspection_id: null,
    ...extra,
  };
}

function row(extra: Partial<JointRow> = {}): JointRow {
  return {
    inspection_id: "ji-1",
    inspection_number: "JI260001",
    kind: "MOVE_IN",
    status: "DONE",
    inspection_date: "2026-11-16",
    lease_id: "lease-1",
    lease_number: "U101L0026",
    unit_id: "u-101",
    unit_number: "U101",
    tenant_name: "Sok Dara",
    problems: 1,
    new_problems: null,
    marked: 3,
    lines: 3,
    replaces_number: null,
    replaced_by_number: null,
    done_at: "2026-11-16T03:00:00Z",
    ...extra,
  };
}

/** A fake server that applies each change to one inspection. */
function fakeApi(start: JointInspection, rows: JointRow[] = []) {
  let current = start;
  const saves: JointChanges[] = [];
  const files: { role: FileRole; lineId: string | undefined }[] = [];
  const bump = (next: Partial<JointInspection>) => {
    current = { ...current, ...next, version: current.version + 1 };
    return current;
  };
  const api: JointApi = {
    list: vi.fn(() => Promise.resolve(rows)),
    get: vi.fn(() => Promise.resolve(current)),
    start: vi.fn(() =>
      Promise.resolve({ ...current, inspection_id: "ji-new" }),
    ),
    save: vi.fn(
      (_property: string, seen: JointInspection, changes: JointChanges) => {
        if (seen.version !== current.version)
          return Promise.reject(new JointError(412));
        saves.push(changes);
        const lines = current.lines.map((entry) => {
          const change = changes.lines?.find(
            (item) => item.line_id === entry.line_id,
          );
          if (change === undefined) return entry;
          return {
            ...entry,
            ...(change.result === undefined ? {} : { result: change.result }),
            ...(change.note === undefined ? {} : { note: change.note }),
            ...(change.tenant_caused === undefined
              ? {}
              : { tenant_caused: change.tenant_caused }),
            ...(change.pet_caused === undefined
              ? {}
              : { pet_caused: change.pet_caused }),
          };
        });
        const meters = current.meters.map((meter) => {
          const change = changes.meters?.find(
            (item) => item.utility_type === meter.utility_type,
          );
          return change === undefined
            ? meter
            : { ...meter, reading: change.reading };
        });
        return Promise.resolve(
          bump({
            lines,
            meters,
            keys: { ...current.keys, ...changes.keys },
            signatures: { tenant: null, staff: null },
          }),
        );
      },
    ),
    addFile: vi.fn(
      (
        _property: string,
        _seen: JointInspection,
        role: FileRole,
        _file: Blob,
        lineId?: string,
      ) => {
        files.push({ role, lineId });
        const signed = {
          file_id: `f-${role}`,
          signed_at: "2026-11-16T03:10:00Z",
        };
        if (role === "TENANT_SIGNATURE")
          return Promise.resolve(
            bump({ signatures: { tenant: signed, staff: null } }),
          );
        if (role === "STAFF_SIGNATURE")
          return Promise.resolve(
            bump({
              signatures: {
                tenant: current.signatures.tenant,
                staff: { ...signed, name: "Chan Staff" },
              },
            }),
          );
        return Promise.resolve(bump({}));
      },
    ),
    removeFile: vi.fn(() => Promise.resolve()),
    fileUrl: (_property, fileId) => `/files/${fileId}`,
    pdfUrl: (_property, inspectionId) => `/copies/${inspectionId}.pdf`,
    finish: vi.fn(() => {
      current = { ...current, status: "DONE", version: current.version + 1 };
      return Promise.resolve({
        inspection: current,
        finished: {
          inspection_number: current.inspection_number,
          reports: ["UP260007"],
          damage_findings: 0,
        },
      });
    }),
  };
  return { api, saves, files, now: () => current };
}

// The Property's older move-out inspections and Unit checks: none here.
const NO_OTHER_INSPECTIONS = {
  inspections: () =>
    Promise.resolve({ as_of: "2026-11-16", move_outs: [], unit_checks: [] }),
} as unknown as ProblemsApi;

function openForm(api: JointApi, capabilities: ReadonlySet<string> = ALL) {
  window.location.hash = "#/inspections/ji%3Aji-1";
  render(
    <InspectionsPage
      api={NO_OTHER_INSPECTIONS}
      capabilities={capabilities}
      jointApi={api}
      language="en"
      propertyId={PROPERTY}
    />,
  );
}

describe("Joint Inspection (DL-243)", () => {
  it("TEST-FE-2290 lists Joint Inspections with their kind, problems and status, filters them and opens one", async () => {
    const { api } = fakeApi(inspection(), [
      row({}),
      row({
        inspection_id: "ji-2",
        inspection_number: "JI260002",
        kind: "MOVE_OUT",
        status: "DRAFT",
        marked: 1,
      }),
      row({
        inspection_id: "ji-3",
        inspection_number: "JI260003",
        kind: "MOVE_OUT",
        status: "DONE",
        problems: 2,
        new_problems: 1,
        replaces_number: "JI260002",
      }),
    ]);
    render(
      <InspectionsPage
        api={NO_OTHER_INSPECTIONS}
        capabilities={ALL}
        jointApi={api}
        language="en"
        propertyId={PROPERTY}
      />,
    );
    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(4);
    expect(within(table).getByText("1 of 3 marked")).toBeInTheDocument();
    expect(within(table).getByText("1 new")).toBeInTheDocument();
    expect(within(table).getByText("Replaces JI260002")).toBeInTheDocument();
    expect(api.list).toHaveBeenCalledWith(PROPERTY);
    fireEvent.change(screen.getByLabelText("Kind"), {
      target: { value: "MOVE_OUT" },
    });
    fireEvent.change(screen.getByLabelText("Status"), {
      target: { value: "DONE" },
    });
    expect(within(table).getAllByRole("row")).toHaveLength(2);
    expect(screen.getByRole("link", { name: "JI260003" })).toHaveAttribute(
      "href",
      "#/inspections/ji%3Aji-3",
    );
    // The older move-out inspections and Unit checks are listed below.
    expect(
      await screen.findByRole("heading", { name: /Move-out inspections/ }),
    ).toBeInTheDocument();
  });

  it("TEST-FE-2291 marks a line with one tap and marks a whole room Good with All good", async () => {
    const { api, saves } = fakeApi(inspection());
    openForm(api);
    const bedroom = await screen.findByRole("region", { name: "Bedroom" });
    fireEvent.click(
      within(within(bedroom).getByRole("group", { name: "Bed" })).getByRole(
        "button",
        { name: "Broken" },
      ),
    );
    await waitFor(() => {
      expect(saves).toEqual([
        { lines: [{ line_id: "l-bed-item", result: "BROKEN" }] },
      ]);
    });
    fireEvent.click(within(bedroom).getByRole("button", { name: "All good" }));
    await waitFor(() => {
      expect(saves[1]).toEqual({
        lines: [{ line_id: "l-bed", result: "GOOD" }],
      });
    });
    // A place is Good or Broken; only an item can be Missing.
    const room = within(bedroom).getByRole("group", {
      name: "The room itself",
    });
    expect(within(room).queryByRole("button", { name: "Missing" })).toBeNull();
    expect(
      within(within(bedroom).getByRole("group", { name: "Bed" })).getByRole(
        "button",
        { name: "Missing" },
      ),
    ).toBeInTheDocument();
  });

  it("TEST-FE-2292 a Broken line asks for a note, saves it on leaving the box and takes photos", async () => {
    const { api, saves, files } = fakeApi(
      inspection({
        lines: [line({ result: "BROKEN" })],
      }),
    );
    openForm(api);
    const note = await screen.findByLabelText("Note");
    expect(note).toHaveAttribute("aria-invalid", "true");
    expect(screen.getAllByText("Write what is wrong").length).toBeGreaterThan(
      0,
    );
    fireEvent.change(note, { target: { value: "  Window latch broken " } });
    fireEvent.blur(note);
    await waitFor(() => {
      expect(saves).toEqual([
        { lines: [{ line_id: "l-bed", note: "Window latch broken" }] },
      ]);
    });
    const picture = new File(["x"], "latch.jpg", { type: "image/jpeg" });
    fireEvent.change(screen.getByLabelText("Add photo"), {
      target: { files: [picture] },
    });
    await waitFor(() => {
      expect(files).toEqual([{ role: "PHOTO", lineId: "l-bed" }]);
    });
  });

  it("TEST-FE-2293 at move-out shows the move-in result, marks a worse line New since move-in and ticks Tenant caused and pet", async () => {
    const { api, saves } = fakeApi(
      inspection({
        kind: "MOVE_OUT",
        move_in_id: "ji-0",
        lines: [
          line({ move_in_result: "GOOD", result: "BROKEN", note: "Hole" }),
          line({
            line_id: "l-door",
            ordinal: 2,
            line_kind: "ITEM",
            item_name: "Door",
            move_in_result: "BROKEN",
            move_in_note: "Scratch",
            result: "BROKEN",
            note: "Scratch",
          }),
        ],
      }),
    );
    openForm(api);
    expect(await screen.findByText("At move-in: Good")).toBeInTheDocument();
    expect(
      screen.getByText("At move-in: Broken (Scratch)"),
    ).toBeInTheDocument();
    // Only the worse line can be Tenant caused.
    expect(screen.getAllByText("New since move-in")).toHaveLength(1);
    expect(
      screen.getAllByRole("checkbox", { name: "Tenant caused" }),
    ).toHaveLength(1);
    fireEvent.click(screen.getByRole("checkbox", { name: "Tenant caused" }));
    await waitFor(() => {
      expect(saves).toEqual([
        { lines: [{ line_id: "l-bed", tenant_caused: true }] },
      ]);
    });
    fireEvent.click(
      await screen.findByRole("checkbox", { name: "Caused by a pet" }),
    );
    await waitFor(() => {
      expect(saves[1]).toEqual({
        lines: [{ line_id: "l-bed", pet_caused: true }],
      });
    });
  });

  it("TEST-FE-2294 saves the keys and the meter number and warns when Utilities or the move-in keys differ", async () => {
    const { api, saves } = fakeApi(
      inspection({
        kind: "MOVE_OUT",
        move_in_id: "ji-0",
        move_in_keys: {
          door_keys: 2,
          key_cards: 1,
          mailbox_keys: 1,
          other_keys: 0,
        },
        meters: [
          {
            utility_type: "ELECTRICITY",
            serial_number: "MEL260001",
            measurement_unit_code: "KWH",
            reading: null,
            utilities_reading: "1300",
            move_in_reading: "1000.5",
            photo: null,
          },
        ],
      }),
    );
    openForm(api);
    fireEvent.click(
      await screen.findByRole("button", { name: /Keys and meters/ }),
    );
    expect(screen.getByText("Given at move-in: 2")).toBeInTheDocument();
    expect(screen.getByText("At move-in: 1000.5")).toBeInTheDocument();
    const doors = screen.getByLabelText("Door keys");
    fireEvent.change(doors, { target: { value: "1" } });
    fireEvent.blur(doors);
    await waitFor(() => {
      expect(saves).toEqual([{ keys: { door_keys: 1 } }]);
    });
    expect(
      await screen.findByText("Fewer keys than were given at move-in."),
    ).toBeInTheDocument();
    const reading = screen.getByLabelText("Meter number (KWH)");
    fireEvent.change(reading, { target: { value: "12,5" } });
    expect(
      screen.getByText("Write the number on the meter, for example 1250.5"),
    ).toBeInTheDocument();
    fireEvent.change(reading, { target: { value: "1250.5" } });
    fireEvent.blur(reading);
    await waitFor(() => {
      expect(saves[1]).toEqual({
        meters: [{ utility_type: "ELECTRICITY", reading: "1250.5" }],
      });
    });
    expect(
      await screen.findByText(
        "Utilities has 1300 for this day. Check the meter again.",
      ),
    ).toBeInTheDocument();
  });

  it("TEST-FE-2295 the tenant signs first, then the staff member, and Finish makes the Problem reports", async () => {
    const ready = inspection({
      lines: [line({ result: "BROKEN", note: "Window latch" })],
      meters: [],
      keys: {
        door_keys: 2,
        key_cards: 1,
        mailbox_keys: 1,
        other_keys: 0,
        other_keys_note: null,
      },
    });
    const { api, files } = fakeApi(ready);
    openForm(api);
    fireEvent.click(await screen.findByRole("button", { name: /Sign/ }));
    expect(screen.getByText("1 Broken")).toBeInTheDocument();
    expect(screen.getByText("The tenant signs first.")).toBeInTheDocument();
    const finish = screen.getByRole("button", { name: "Finish" });
    expect(finish).toBeDisabled();
    // An empty pad is not a signature.
    fireEvent.click(screen.getByRole("button", { name: "Save signature" }));
    expect(screen.getByText("Sign in the box first.")).toBeInTheDocument();
    const pad = screen.getByRole("img", { name: "Tenant signs here" });
    fireEvent.pointerDown(pad, { clientX: 10, clientY: 10 });
    fireEvent.pointerMove(pad, { clientX: 40, clientY: 30 });
    fireEvent.pointerUp(pad);
    fireEvent.click(screen.getByRole("button", { name: "Save signature" }));
    const staffPad = await screen.findByRole("img", {
      name: "Staff member signs here",
    });
    expect(files).toEqual([{ role: "TENANT_SIGNATURE", lineId: undefined }]);
    fireEvent.pointerDown(staffPad, { clientX: 10, clientY: 10 });
    fireEvent.pointerMove(staffPad, { clientX: 50, clientY: 20 });
    fireEvent.click(screen.getByRole("button", { name: "Save signature" }));
    await screen.findByText(/Signed by Chan Staff/);
    fireEvent.click(screen.getByRole("button", { name: "Finish" }));
    expect(
      await screen.findByText(/Problem reports made: UP260007\./),
    ).toBeInTheDocument();
    expect(screen.getByText("Done")).toBeInTheDocument();
  });

  it("TEST-FE-2296 a form not ready to sign says what is missing, and a change made elsewhere reads the form again", async () => {
    const { api } = fakeApi(inspection());
    vi.mocked(api.save).mockRejectedValueOnce(new JointError(412));
    openForm(api);
    fireEvent.click(await screen.findByRole("button", { name: /Sign/ }));
    expect(
      screen.getByText(/Before signing: mark every line/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "Tenant signs here" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Rooms and items/ }));
    const bedroom = screen.getByRole("region", { name: "Bedroom" });
    fireEvent.click(within(bedroom).getByRole("button", { name: "All good" }));
    expect(
      await screen.findByText(
        "Someone changed this inspection meanwhile. It was read again.",
      ),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledTimes(2);
    });
  });

  it("TEST-FE-2297 a done inspection is read only with its Problem reports, and only a Manager replaces it with a reason", async () => {
    const done = inspection({
      status: "DONE",
      done_at: "2026-11-16T04:00:00Z",
      done_by: "Chan Staff",
      lines: [
        line({
          result: "BROKEN",
          note: "Window latch",
          problem_report: { report_id: "r-7", report_number: "UP260007" },
        }),
      ],
      signatures: {
        tenant: { file_id: "f-t", signed_at: "2026-11-16T03:50:00Z" },
        staff: {
          file_id: "f-s",
          signed_at: "2026-11-16T03:55:00Z",
          name: "Chan Staff",
        },
      },
    });
    const { api } = fakeApi(done);
    openForm(api, STAFF);
    expect(
      await screen.findByRole("link", { name: "Problem report UP260007" }),
    ).toHaveAttribute("href", "#/problems/pr%3Ar-7");
    expect(screen.queryByRole("button", { name: "Broken" })).toBeNull();
    expect(
      screen.getByRole("img", { name: "Tenant signs here" }),
    ).toHaveAttribute("src", "/files/f-t");
    expect(screen.queryByRole("button", { name: "Replace" })).toBeNull();
    cleanup();
    openForm(api, ALL);
    fireEvent.click(await screen.findByRole("button", { name: "Replace" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Start the replacement" }),
    );
    expect(screen.getByText("Say why it is replaced.")).toBeInTheDocument();
    expect(api.start).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Why is it replaced?"), {
      target: { value: "Wrong key count" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Start the replacement" }),
    );
    await waitFor(() => {
      expect(api.start).toHaveBeenCalledWith(PROPERTY, {
        lease_id: "lease-1",
        kind: "MOVE_IN",
        replaces_id: "ji-1",
        reason: "Wrong key count",
      });
    });
    await waitFor(() => {
      expect(window.location.hash).toBe("#/inspections/ji%3Aji-new");
    });
  });

  it("TEST-FE-2298 the Lease card warns when the move-in inspection is not done and starts one; a role without the right only sees it", async () => {
    const { api } = fakeApi(inspection(), [
      row({
        kind: "MOVE_OUT",
        status: "DRAFT",
        inspection_id: "ji-5",
        inspection_number: "JI260005",
      }),
    ]);
    const may = (capability: string) => STAFF.has(capability);
    render(
      <LeaseJointCard
        api={api}
        kinds={["MOVE_IN", "MOVE_OUT"]}
        language="en"
        leaseId="lease-1"
        may={may}
        propertyId={PROPERTY}
      />,
    );
    expect(
      await screen.findByText("Move-in inspection not done"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Go on with JI260005" }),
    ).toHaveAttribute("href", "#/inspections/ji%3Aji-5");
    fireEvent.click(
      screen.getByRole("button", { name: "Start move-in inspection" }),
    );
    await waitFor(() => {
      expect(api.start).toHaveBeenCalledWith(PROPERTY, {
        lease_id: "lease-1",
        kind: "MOVE_IN",
      });
    });
    cleanup();
    render(
      <LeaseJointCard
        api={api}
        kinds={["MOVE_OUT"]}
        language="en"
        leaseId="lease-1"
        may={() => false}
        propertyId={PROPERTY}
      />,
    );
    expect(
      await screen.findByText("Your role cannot do Joint Inspections."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Start/ })).toBeNull();
  });

  it("TEST-FE-2299 reads a Problem report made by a Joint Inspection and refuses a Joint Inspection it does not understand", () => {
    const parsed = inspectionOf({
      ...inspection(),
      lines: inspection().lines,
    });
    expect(parsed.inspection_number).toBe("JI260001");
    expect(() => inspectionOf({ ...inspection(), kind: "MID_LEASE" })).toThrow(
      JointError,
    );
    const report = reportOf({
      report_id: "r-7",
      report_number: "UP260007",
      kind: "UNIT",
      status: "RECEIVED",
      state: "RECEIVED",
      late: null,
      repeat: null,
      unit_id: "u-101",
      unit_number: "U101",
      floor: null,
      customer_id: null,
      customer_name: null,
      place_item_id: null,
      place_number: null,
      place_en: null,
      place_kh: null,
      problem_place: null,
      problem_type: {
        id: "t-other",
        code: "OTHER",
        name_en: "Other",
        name_kh: null,
        icon: "wrench",
        always_urgent: false,
      },
      description:
        "Move-in Joint Inspection JI260001: Bedroom: Broken. Window latch",
      urgent: false,
      may_enter: false,
      best_time: "ANY",
      source: "JOINT_INSPECTION",
      reported_by: null,
      created_at: "2026-11-16T04:00:00Z",
      version: 1,
    });
    expect(report.source).toBe("JOINT_INSPECTION");
  });
  it("TEST-FE-2305 a done inspection opens its PDF copy to print or save, a Draft has none", async () => {
    const { api } = fakeApi(
      inspection({
        status: "DONE",
        done_at: "2026-11-16T04:00:00Z",
        done_by: "Chan Staff",
      }),
    );
    openForm(api);
    const link = await screen.findByRole("link", { name: "Print or save PDF" });
    expect(link).toHaveAttribute("href", "/copies/ji-1.pdf");
    expect(link).toHaveAttribute("target", "_blank");
    cleanup();
    openForm(fakeApi(inspection()).api);
    await waitFor(() => {
      expect(
        screen.queryByRole("link", { name: "Print or save PDF" }),
      ).toBeNull();
    });
  });

  it("TEST-FE-2306 the Unit page lists the Unit's inspections newest first and leaves out other Units", async () => {
    const list = vi.fn(() =>
      Promise.resolve([
        row(),
        row({
          inspection_id: "ji-2",
          inspection_number: "JI260002",
          unit_id: "u-999",
        }),
        row({
          inspection_id: "ji-3",
          inspection_number: "JI260003",
          inspection_date: "2026-11-20",
          kind: "MOVE_OUT",
        }),
      ]),
    );
    render(
      <UnitJointCard
        api={{ list }}
        language="en"
        propertyId={PROPERTY}
        unitId="u-101"
      />,
    );
    const newest = await screen.findByRole("link", { name: "JI260003" });
    expect(newest).toHaveAttribute("href", "#/inspections/ji%3Aji-3");
    const numbers = screen.getAllByRole("link").map((one) => one.textContent);
    expect(numbers).toEqual(["JI260003", "JI260001"]);
    expect(list).toHaveBeenCalledWith(PROPERTY);
  });
});
