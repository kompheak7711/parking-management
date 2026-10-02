import { StrictMode } from "react";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LeaseEnforcementManagement } from "./LeaseEnforcementManagement";
import { createEnforcementClient } from "./leaseEnforcementClient";
import { createFinancialTransport } from "./financialClient";
import {
  createFinancialRecovery,
  decodeFinancialIntent,
} from "./financialRecovery";
import { financialObject, type FinancialObject } from "./financialContracts";
import { parseFinancialJson, stringifyFinancialJson } from "./financialJson";
import {
  ENFORCEMENT_CAPABILITIES,
  enforcementValue,
  type EnforcementRead,
} from "./leaseEnforcementContract";
import type { EnforcementServices } from "./leaseEnforcementUi";
import {
  ids,
  memory,
  readData,
  additionalRentSource,
  warningRecord,
  eventRecord,
  caseRecord,
  warningBody,
  rentMinor,
} from "./test/leaseEnforcementFixtures";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
function deferred() {
  let release!: () => void;
  const promise = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { promise, release };
}
function harness(allow: string[] = [...ENFORCEMENT_CAPABILITIES]) {
  const saved = memory(),
    originals = new Map<string, { body: string; envelope: FinancialObject }>();
  const state = {
    allow,
    voided: false,
    caseExists: false,
    hasSecondSource: false,
    loseNext: false,
    deny: false,
    rejectValidation: false,
    block: null as null | { phase: "post" | "reads"; promise: Promise<void> },
    warnings: [] as FinancialObject[],
    events: [] as FinancialObject[],
  };
  const calls: {
    url: string;
    method: string;
    body: string | null;
    key: string | null;
    property: string | null;
    actor: string | null;
    signal: AbortSignal | null | undefined;
  }[] = [];
  const fetcher: typeof fetch = async (supplied, init) => {
    if (typeof supplied !== "string") throw new Error("Finite route required");
    const url = new URL(supplied, "https://synthetic.invalid"),
      headers = new Headers(init?.headers),
      key = headers.get("Idempotency-Key"),
      requestId = headers.get("X-Request-ID"),
      prop = headers.get("X-Financial-Property-ID"),
      actor = headers.get("X-Billing-Actor-ID"),
      method = init?.method ?? "",
      body = typeof init?.body === "string" ? init.body : null;
    calls.push({
      url: supplied,
      method,
      body,
      key,
      property: prop,
      actor,
      signal: init?.signal,
    });
    if (state.block?.phase === (method === "POST" ? "post" : "reads"))
      await state.block.promise;
    const respond = (envelope: FinancialObject, status = 200) =>
      new Response(stringifyFinancialJson(envelope), {
        status,
        headers: {
          "Content-Type": "application/json",
          "X-Request-ID": requestId ?? "",
        },
      });
    if (method === "POST") {
      if (state.rejectValidation)
        return respond(
          {
            error: { code: "VALIDATION_ERROR" },
            meta: { request_id: requestId },
          },
          422,
        );
      if (state.deny)
        return respond(
          { error: { code: "FORBIDDEN" }, meta: { request_id: requestId } },
          403,
        );
      if (!key || !body || !prop || actor !== ids.actor)
        throw new Error("Missing command scope");
      const previous = originals.get(key);
      if (previous && previous.body !== body)
        return respond(
          {
            error: { code: "IDEMPOTENCY_KEY_REUSED" },
            meta: { request_id: requestId, property_id: prop },
          },
          409,
        );
      if (previous) return respond(previous.envelope, 201);
      const command = financialObject(parseFinancialJson(body));
      let data: FinancialObject;
      if (url.pathname.endsWith("/violation-warnings")) {
        data = warningRecord(command);
        state.warnings.push(data);
      } else if (url.pathname.endsWith("/rent-nonpayment-cases")) {
        state.caseExists = true;
        data = caseRecord();
      } else {
        data = eventRecord(command, true, state.voided);
        state.events.push(eventRecord(command, false, state.voided));
      }
      const envelope = {
        data,
        meta: { request_id: requestId, property_id: prop },
      };
      originals.set(key, { body, envelope });
      if (state.loseNext) {
        state.loseNext = false;
        throw new Error("Synthetic lost response");
      }
      return respond(envelope, 201);
    }
    let input: EnforcementRead;
    const limit = Number(url.searchParams.get("limit") ?? 50),
      offset = Number(url.searchParams.get("offset") ?? 0);
    if (url.pathname.endsWith("/lease-enforcement-workspaces"))
      input = { kind: "workspaces", limit };
    else if (url.pathname.endsWith("/lease-enforcement-leases"))
      input = {
        kind: "leases",
        purpose:
          url.searchParams.get("purpose") === "WARNINGS"
            ? "WARNINGS"
            : "NONPAYMENT",
        limit,
      };
    else if (url.pathname.endsWith("/rent-nonpayment-alerts"))
      input = { kind: "alerts", limit };
    else if (url.pathname.endsWith("/initial-rent-unpaid-alerts"))
      input = { kind: "initialRentAlerts", limit };
    else if (url.pathname.endsWith("/violation-warning-context"))
      input = { kind: "warningContext", leaseId: ids.lease };
    else if (url.pathname.endsWith("/violation-warnings"))
      input = { kind: "warnings", leaseId: ids.lease, limit, offset };
    else if (url.pathname.endsWith("/rent-nonpayment-sources"))
      input = { kind: "sources", leaseId: ids.lease, limit };
    else if (url.pathname.endsWith("/rent-nonpayment-action-cases"))
      input = { kind: "actionCases", leaseId: ids.lease, limit };
    else if (url.pathname.endsWith("/rent-nonpayment-cases"))
      input = { kind: "cases", leaseId: ids.lease, limit, offset };
    else if (url.pathname.endsWith("/events"))
      input = { kind: "events", caseId: ids.case, limit, offset };
    else if (url.pathname.endsWith("/action-context"))
      input = { kind: "eventContext", caseId: ids.case };
    else if (url.pathname.endsWith(ids.case))
      input = { kind: "case", caseId: ids.case };
    else throw new Error(`Unexpected synthetic read ${supplied}`);
    const data = readData(input, state.voided, state.allow);
    if (input.kind === "warnings") {
      data.items = state.warnings.slice(offset, offset + limit);
      data.total = state.warnings.length;
    }
    if (input.kind === "events") {
      data.items = state.events.slice(offset, offset + limit);
      data.total = state.events.length;
    }
    if (input.kind === "warningContext")
      data.suggested_sequence = state.warnings.length + 1;
    if (input.kind === "sources" && state.caseExists)
      data.items = state.hasSecondSource ? [additionalRentSource()] : [];
    if (
      (input.kind === "cases" || input.kind === "actionCases") &&
      !state.caseExists
    ) {
      data.items = [];
      if (input.kind === "cases") data.total = 0;
    }
    if (input.kind === "workspaces" && state.allow.length === 0)
      data.items = [];
    return respond({
      data,
      meta: {
        request_id: requestId,
        ...(input.kind === "workspaces"
          ? { actor_id: actor }
          : { property_id: prop }),
      },
    });
  };
  const services: EnforcementServices = {
    reads: createEnforcementClient(fetcher),
    recovery: createFinancialRecovery(
      saved.store,
      createFinancialTransport(fetcher, () => "synthetic-csrf"),
      () => "synthetic-csrf",
      saved.attempts,
    ),
  };
  return { ...saved, state, calls, originals, services };
}
async function selectProperty() {
  await screen.findByRole("option", { name: "Synthetic River Property" });
  fireEvent.change(screen.getByLabelText("Lease enforcement Property"), {
    target: { value: ids.property },
  });
  await screen.findByText("No unresolved financial action.");
}
async function selectLease(purpose: "general warnings" | "Rent nonpayment") {
  const picker = screen.getByLabelText(`Lease for ${purpose}`);
  await waitFor(() => {
    expect(
      within(picker).getByRole("option", { name: /SYNTHETIC-A1/ }),
    ).toBeInTheDocument();
  });
  fireEvent.change(picker, { target: { value: ids.lease } });
}
async function warningForm() {
  const form = await screen.findByRole("form", {
    name: "Record Lease warning",
  });
  for (const [label, value] of [
    ["Violation date", warningBody.violation_date],
    ["Violation description", warningBody.violation_description],
    ["Lease provision", warningBody.lease_provision],
    ["Communication record", warningBody.communication_record],
    ["Reason for recording warning", warningBody.reason],
  ]) {
    fireEvent.change(within(form).getByLabelText(enforcementValue(label)), {
      target: { value },
    });
  }
  return form;
}
describe("Lease enforcement staff workflows", () => {
  it("TEST-FE-605 permits warning-only staff to confirm a complete warning without reading history or creating a case", async () => {
    const h = harness(["leases.warn"]);
    render(
      <StrictMode>
        <LeaseEnforcementManagement actorId={ids.actor} services={h.services} />
      </StrictMode>,
    );
    await selectProperty();
    await selectLease("general warnings");
    const form = await warningForm();
    expect(
      h.calls.some(
        (call) =>
          call.method === "GET" && call.url.includes("/violation-warnings"),
      ),
    ).toBe(false);
    fireEvent.click(
      within(form).getByRole("button", { name: "Review Lease warning" }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText(enforcementValue(warningBody.lease_provision)),
    ).toBeInTheDocument();
    expect(h.calls.some((call) => call.method === "POST")).toBe(false);
    const confirm = within(dialog).getByRole("button", {
      name: "Record Lease violation warning",
    });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    await screen.findByRole("region", {
      name: "Original confirmed enforcement action",
    });
    expect(h.calls.filter((call) => call.method === "POST")).toHaveLength(1);
    expect(h.state.warnings).toHaveLength(1);
    expect(h.state.caseExists).toBe(false);
    expect(h.records.size).toBe(0);
  });
  it("TEST-FE-606 exposes warning history to read-only staff without command forms", async () => {
    const h = harness(["leases.read"]);
    h.state.warnings = [warningRecord()];
    render(
      <LeaseEnforcementManagement actorId={ids.actor} services={h.services} />,
    );
    await selectProperty();
    await selectLease("general warnings");
    await screen.findByText(
      enforcementValue(warningBody.violation_description),
    );
    expect(
      screen.queryByRole("form", { name: "Record Lease warning" }),
    ).not.toBeInTheDocument();
    expect(h.calls.every((call) => call.method === "GET")).toBe(true);
    expect(
      h.calls.some((call) => call.url.includes("violation-warning-context")),
    ).toBe(false);
  });
  it("TEST-FE-607 keeps event-only authority separate and allows referenced follow-up at current zero after VOID", async () => {
    const h = harness(["rent_nonpayment.event_post"]);
    h.state.caseExists = true;
    h.state.voided = true;
    render(
      <LeaseEnforcementManagement actorId={ids.actor} services={h.services} />,
    );
    await selectProperty();
    await selectLease("Rent nonpayment");
    const picker = screen.getByLabelText("Rent case available for an event");
    await waitFor(() => {
      expect(within(picker).getAllByRole("option")).toHaveLength(2);
    });
    fireEvent.change(picker, { target: { value: ids.case } });
    const form = await screen.findByRole("form", {
      name: "Record Rent nonpayment event",
    });
    expect(
      screen.getByRole("option", { name: /20-day Warning Notice.*ineligible/ }),
    ).toBeDisabled();
    expect(
      screen.getByRole("option", { name: /Cure.*ineligible/ }),
    ).toBeDisabled();
    fireEvent.change(within(form).getByLabelText("Nonpayment event"), {
      target: { value: "AUTHORIZED_FOLLOW_UP" },
    });
    fireEvent.change(within(form).getByLabelText("Authorization reference"), {
      target: { value: "SYNTHETIC-APPROVAL" },
    });
    fireEvent.change(
      within(form).getByLabelText("Reason for nonpayment event"),
      { target: { value: "Synthetic follow-up after VOID" } },
    );
    fireEvent.click(
      within(form).getByRole("button", { name: "Review nonpayment event" }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("SYNTHETIC-APPROVAL")).toBeInTheDocument();
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "Record Rent nonpayment event",
      }),
    );
    await screen.findByRole("region", {
      name: "Original confirmed enforcement action",
    });
    await waitFor(() => {
      expect(
        screen.getByRole("region", { name: "Current case after confirmation" }),
      ).toHaveTextContent("VOID");
    });
    expect(h.state.events[0]?.remaining_rent_usd_cents).toBe(0);
    expect(
      h.calls.some(
        (call) =>
          call.method === "GET" &&
          (call.url.includes("/events") ||
            call.url.endsWith(ids.case) ||
            call.url.includes("/rent-nonpayment-alerts")),
      ),
    ).toBe(false);
    const posted = h.calls.find((call) => call.method === "POST");
    expect(posted?.body).not.toContain("remaining_rent");
    expect(posted?.body).not.toContain("event_date");
  });
  it("TEST-FE-608 recovers a lost opening after source removal and preserves original assessment separately from current VOID zero", async () => {
    const h = harness(["rent_nonpayment.read", "rent_nonpayment.case_manage"]);
    h.state.loseNext = true;
    render(
      <LeaseEnforcementManagement actorId={ids.actor} services={h.services} />,
    );
    await selectProperty();
    await selectLease("Rent nonpayment");
    const picker = screen.getByLabelText("Issued Rent line without a case");
    await waitFor(() => {
      expect(within(picker).getAllByRole("option")).toHaveLength(2);
    });
    fireEvent.change(picker, { target: { value: ids.rent } });
    fireEvent.change(screen.getByLabelText("Reason for opening case"), {
      target: { value: "Synthetic case investigation" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Review Rent case opening" }),
    );
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Open Rent nonpayment case",
      }),
    );
    await screen.findByRole("button", { name: "Review original action" });
    expect(h.records.size).toBe(1);
    const original = h.records.get(ids.actor);
    if (!original) throw new Error();
    h.state.voided = true;
    fireEvent.click(
      screen.getByRole("button", {
        name: "Refresh enforcement records and recovery",
      }),
    );
    await screen.findByText(
      "No applicable Rent lines without a case on this page.",
    );
    expect(h.records.get(ids.actor)).toEqual(original);
    fireEvent.click(
      screen.getByRole("button", { name: "Review original action" }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText("Synthetic case investigation"),
    ).toBeInTheDocument();
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "Send original enforcement action again",
      }),
    );
    const outcome = await screen.findByRole("region", {
      name: "Original confirmed enforcement action",
    });
    await waitFor(() => {
      expect(
        within(outcome).getByRole("region", {
          name: "Current case after confirmation",
        }),
      ).toHaveTextContent("VOID");
    });
    expect(
      within(outcome).getByRole("region", {
        name: "Original recorded assessment",
      }),
    ).toHaveTextContent("USD 800.00");
    expect(
      within(outcome).getByRole("region", {
        name: "Current case after confirmation",
      }),
    ).toHaveTextContent("USD 0.00");
    const posts = h.calls.filter((call) => call.method === "POST");
    expect(posts).toHaveLength(2);
    expect(posts[1]?.body).toBe(posts[0]?.body);
    expect(posts[1]?.key).toBe(posts[0]?.key);
    expect(h.records.size).toBe(0);
    expect(h.originals.size).toBe(1);
  });
  it("TEST-FE-609 preserves an original command after fresh server permission revocation", async () => {
    const h = harness(["leases.warn"]);
    h.state.loseNext = true;
    render(
      <LeaseEnforcementManagement actorId={ids.actor} services={h.services} />,
    );
    await selectProperty();
    await selectLease("general warnings");
    fireEvent.click(
      within(await warningForm()).getByRole("button", {
        name: "Review Lease warning",
      }),
    );
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Record Lease violation warning",
      }),
    );
    await screen.findByRole("button", { name: "Review original action" });
    const original = h.records.get(ids.actor);
    h.state.deny = true;
    fireEvent.click(
      screen.getByRole("button", { name: "Review original action" }),
    );
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Send original enforcement action again",
      }),
    );
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(h.records.get(ids.actor)).toEqual(original);
    expect(h.state.warnings).toHaveLength(1);
  });
  it("TEST-FE-610 prevents unsaved draft loss on Property changes and restores confirmation focus on Escape", async () => {
    const h = harness(["leases.warn"]),
      dirty = vi.fn();
    vi.spyOn(window, "confirm").mockReturnValue(false);
    render(
      <LeaseEnforcementManagement
        actorId={ids.actor}
        services={h.services}
        onDirtyStateChange={dirty}
      />,
    );
    await selectProperty();
    await selectLease("general warnings");
    const form = await warningForm();
    await waitFor(() => {
      expect(dirty).toHaveBeenLastCalledWith(true);
    });
    fireEvent.change(screen.getByLabelText("Lease enforcement Property"), {
      target: { value: "" },
    });
    expect(screen.getByLabelText("Lease enforcement Property")).toHaveValue(
      ids.property,
    );
    const opener = within(form).getByRole("button", {
      name: "Review Lease warning",
    });
    opener.focus();
    fireEvent.click(opener);
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
    expect(
      within(dialog).getByRole("button", {
        name: "Record Lease violation warning",
      }),
    ).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(opener).toHaveFocus();
    expect(h.calls.some((call) => call.method === "POST")).toBe(false);
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });
  it("TEST-FE-611 invalidates a late command on workspace exit without clearing saved recovery or exposing success", async () => {
    const h = harness(["leases.warn"]),
      barrier = deferred();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(
      <LeaseEnforcementManagement actorId={ids.actor} services={h.services} />,
    );
    await selectProperty();
    await selectLease("general warnings");
    fireEvent.click(
      within(await warningForm()).getByRole("button", {
        name: "Review Lease warning",
      }),
    );
    h.state.block = { phase: "post", promise: barrier.promise };
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Record Lease violation warning",
      }),
    );
    await waitFor(() => {
      expect(h.calls.filter((call) => call.method === "POST")).toHaveLength(1);
    });
    fireEvent.change(screen.getByLabelText("Lease enforcement Property"), {
      target: { value: "" },
    });
    await act(async () => {
      barrier.release();
      await barrier.promise;
    });
    expect(
      screen.queryByRole("region", {
        name: "Original confirmed enforcement action",
      }),
    ).not.toBeInTheDocument();
    expect(h.records.size).toBe(1);
    expect(
      h.calls.find((call) => call.method === "POST")?.signal?.aborted,
    ).toBe(true);
  });
  it("TEST-FE-612 remounts discovery on actor change and suppresses old Lease evidence", async () => {
    const h = harness(["leases.read"]);
    h.state.warnings = [warningRecord()];
    const view = render(
      <LeaseEnforcementManagement actorId={ids.actor} services={h.services} />,
    );
    await selectProperty();
    await selectLease("general warnings");
    await screen.findByText(
      enforcementValue(warningBody.violation_description),
    );
    const barrier = deferred();
    h.state.block = { phase: "reads", promise: barrier.promise };
    view.rerender(
      <LeaseEnforcementManagement actorId={ids.other} services={h.services} />,
    );
    expect(
      screen.queryByText(enforcementValue(warningBody.violation_description)),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("Lease enforcement Property")).toHaveValue("");
    await act(async () => {
      barrier.release();
      await barrier.promise;
    });
    expect(h.calls.at(-1)?.actor).toBe(ids.other);
  });
  it("TEST-FE-613 shares recovery navigation without dispatching another workflow or leaking its actor", async () => {
    const h = harness(["leases.warn"]);
    const original = {
      namespace: "property-rental.financial-command",
      version: 1,
      actorId: ids.actor,
      propertyId: ids.property,
      key: ids.key,
      operation: "creditReverse",
      target: { id: ids.credit },
      wireBody: '{"reason":"Synthetic reversal"}',
    };
    h.records.set(ids.actor, {
      requestKey: ids.key,
      plaintext: stringifyFinancialJson(original),
    });
    render(
      <LeaseEnforcementManagement actorId={ids.actor} services={h.services} />,
    );
    await screen.findByRole("option", { name: "Synthetic River Property" });
    fireEvent.change(screen.getByLabelText("Lease enforcement Property"), {
      target: { value: ids.property },
    });
    expect(
      await screen.findByRole("link", {
        name: "Review this saved action in Financial records",
      }),
    ).toHaveAttribute("href", "#financial-management-heading");
    expect(
      screen.queryByRole("button", { name: "Review original action" }),
    ).not.toBeInTheDocument();
    expect(h.calls.every((call) => call.method === "GET")).toBe(true);
    const stored = h.records.get(ids.actor);
    if (!stored) throw new Error();
    expect(decodeFinancialIntent(stored, ids.actor)?.operation).toBe(
      "creditReverse",
    );
    expect(rentMinor(caseRecord())).toBe(80000);
  });
});

describe("Lease enforcement draft lifetime", () => {
  it.each(["rejected", "blocked", "pending"] as const)(
    "TEST-FE-622 retains warning input and dirty state through a %s attempt and delayed context refresh",
    async (result) => {
      const h = harness(["leases.warn"]),
        dirty = vi.fn(),
        reads = deferred();
      if (result === "rejected") h.state.rejectValidation = true;
      if (result === "pending") h.state.loseNext = true;
      if (result === "blocked")
        vi.spyOn(h.services.recovery, "submit").mockResolvedValue({
          kind: "blocked",
          state: { kind: "unavailable" },
        });
      vi.spyOn(window, "confirm").mockReturnValue(false);
      render(
        <LeaseEnforcementManagement
          actorId={ids.actor}
          services={h.services}
          onDirtyStateChange={dirty}
        />,
      );
      await selectProperty();
      await selectLease("general warnings");
      const form = await warningForm();
      fireEvent.change(within(form).getByLabelText("Warning sequence"), {
        target: { value: "7" },
      });
      fireEvent.click(
        within(form).getByRole("button", { name: "Review Lease warning" }),
      );
      h.state.block = { phase: "reads", promise: reads.promise };
      fireEvent.click(
        within(await screen.findByRole("dialog")).getByRole("button", {
          name: "Record Lease violation warning",
        }),
      );
      try {
        await waitFor(() => {
          expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
        });
        expect(form).toBeInTheDocument();
        expect(within(form).getByLabelText("Warning sequence")).toHaveValue(
          "7",
        );
        expect(
          within(form).getByLabelText("Violation description"),
        ).toHaveValue(enforcementValue(warningBody.violation_description));
        expect(
          within(form).getByRole("button", { name: "Review Lease warning" }),
        ).toBeDisabled();
        expect(dirty).toHaveBeenLastCalledWith(true);
        fireEvent.change(screen.getByLabelText("Lease enforcement Property"), {
          target: { value: "" },
        });
        expect(window.confirm).toHaveBeenCalled();
        expect(screen.getByLabelText("Lease enforcement Property")).toHaveValue(
          ids.property,
        );
      } finally {
        h.state.block = null;
        await act(async () => {
          reads.release();
          await reads.promise;
        });
      }
      expect(within(form).getByLabelText("Warning sequence")).toHaveValue("7");
      expect(
        within(form).getByLabelText("Reason for recording warning"),
      ).toHaveValue(enforcementValue(warningBody.reason));
      expect(h.state.warnings).toHaveLength(result === "pending" ? 1 : 0);
      expect(h.records.size).toBe(result === "pending" ? 1 : 0);
    },
  );
  it("TEST-FE-623 retains a rejected Rent opening and its selected source", async () => {
    const h = harness(["rent_nonpayment.case_manage"]);
    h.state.rejectValidation = true;
    render(
      <LeaseEnforcementManagement actorId={ids.actor} services={h.services} />,
    );
    await selectProperty();
    await selectLease("Rent nonpayment");
    const picker = screen.getByLabelText("Issued Rent line without a case");
    await waitFor(() => {
      expect(within(picker).getAllByRole("option")).toHaveLength(2);
    });
    fireEvent.change(picker, { target: { value: ids.rent } });
    fireEvent.change(screen.getByLabelText("Reason for opening case"), {
      target: { value: "Keep this investigation draft" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Review Rent case opening" }),
    );
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Open Rent nonpayment case",
      }),
    );
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Review Rent case opening" }),
      ).toBeEnabled();
    });
    expect(
      screen.getByLabelText("Issued Rent line without a case"),
    ).toHaveValue(ids.rent);
    expect(screen.getByLabelText("Reason for opening case")).toHaveValue(
      "Keep this investigation draft",
    );
    expect(h.state.caseExists).toBe(false);
    expect(h.records.size).toBe(0);
  });
  it.each([true, false])(
    "TEST-FE-624 retains unrelated opening input and resets only a recorded event (rejected=%s)",
    async (rejected) => {
      const h = harness([
          "rent_nonpayment.case_manage",
          "rent_nonpayment.event_post",
        ]),
        dirty = vi.fn(),
        reads = deferred();
      h.state.caseExists = true;
      h.state.hasSecondSource = true;
      h.state.rejectValidation = rejected;
      render(
        <LeaseEnforcementManagement
          actorId={ids.actor}
          services={h.services}
          onDirtyStateChange={dirty}
        />,
      );
      await selectProperty();
      await selectLease("Rent nonpayment");
      const picker = screen.getByLabelText("Rent case available for an event");
      await waitFor(() => {
        expect(within(picker).getAllByRole("option")).toHaveLength(2);
      });
      fireEvent.change(picker, { target: { value: ids.case } });
      const form = await screen.findByRole("form", {
        name: "Record Rent nonpayment event",
      });
      const sourcePicker = screen.getByLabelText(
        "Issued Rent line without a case",
      );
      await waitFor(() => {
        expect(
          within(sourcePicker).getByRole("option", {
            name: /SYNTHETIC-RENT-054-SECOND/,
          }),
        ).toBeInTheDocument();
      });
      fireEvent.change(sourcePicker, { target: { value: ids.secondRent } });
      expect(screen.getByLabelText("Reason for opening case")).toBeEnabled();
      fireEvent.change(screen.getByLabelText("Reason for opening case"), {
        target: { value: "Unrelated new case draft" },
      });
      fireEvent.change(within(form).getByLabelText("Nonpayment event"), {
        target: { value: "AUTHORIZED_FOLLOW_UP" },
      });
      fireEvent.change(within(form).getByLabelText("Authorization reference"), {
        target: { value: "SYNTHETIC-AUTHORIZATION" },
      });
      fireEvent.change(
        within(form).getByLabelText("Reason for nonpayment event"),
        { target: { value: "Retain rejected event draft" } },
      );
      fireEvent.click(
        within(form).getByRole("button", { name: "Review nonpayment event" }),
      );
      h.state.block = { phase: "reads", promise: reads.promise };
      fireEvent.click(
        within(await screen.findByRole("dialog")).getByRole("button", {
          name: "Record Rent nonpayment event",
        }),
      );
      try {
        await waitFor(() => {
          expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
        });
        expect(form).toBeInTheDocument();
        expect(screen.getByLabelText("Reason for opening case")).toHaveValue(
          "Unrelated new case draft",
        );
        expect(
          within(form).getByLabelText("Reason for nonpayment event"),
        ).toHaveValue(rejected ? "Retain rejected event draft" : "");
        expect(
          within(form).getByRole("button", {
            name: "Review nonpayment event",
            hidden: true,
          }),
        ).toBeDisabled();
        expect(dirty).toHaveBeenLastCalledWith(true);
      } finally {
        h.state.block = null;
        await act(async () => {
          reads.release();
          await reads.promise;
        });
      }
      expect(
        screen.getByLabelText("Rent case available for an event"),
      ).toHaveValue(ids.case);
      expect(screen.getByLabelText("Reason for opening case")).toHaveValue(
        "Unrelated new case draft",
      );
      expect(within(form).getByLabelText("Nonpayment event")).toHaveValue(
        rejected ? "AUTHORIZED_FOLLOW_UP" : "",
      );
      expect(h.state.events).toHaveLength(rejected ? 0 : 1);
      expect(h.records.size).toBe(0);
    },
  );
  it("TEST-FE-625 clears a recorded warning and uses the fresh next sequence", async () => {
    const h = harness(["leases.warn"]),
      dirty = vi.fn();
    render(
      <LeaseEnforcementManagement
        actorId={ids.actor}
        services={h.services}
        onDirtyStateChange={dirty}
      />,
    );
    await selectProperty();
    await selectLease("general warnings");
    fireEvent.click(
      within(await warningForm()).getByRole("button", {
        name: "Review Lease warning",
      }),
    );
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Record Lease violation warning",
      }),
    );
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByLabelText("Warning sequence")).toHaveValue("2");
    });
    expect(screen.getByLabelText("Violation description")).toHaveValue("");
    expect(screen.getByLabelText("Reason for recording warning")).toHaveValue(
      "",
    );
    expect(dirty).toHaveBeenLastCalledWith(false);
    expect(h.state.warnings).toHaveLength(1);
  });
});

describe("Lease enforcement preserved draft recovery", () => {
  it("TEST-FE-626 refreshes a pending draft without discard and clears it only after exact replay succeeds", async () => {
    const h = harness(["leases.warn"]);
    h.state.loseNext = true;
    const discard = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(
      <LeaseEnforcementManagement actorId={ids.actor} services={h.services} />,
    );
    await selectProperty();
    await selectLease("general warnings");
    fireEvent.click(
      within(await warningForm()).getByRole("button", {
        name: "Review Lease warning",
      }),
    );
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Record Lease violation warning",
      }),
    );
    await screen.findByRole("button", { name: "Review original action" });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(screen.getByLabelText("Reason for recording warning")).toHaveValue(
      enforcementValue(warningBody.reason),
    );
    const before = h.calls.length;
    fireEvent.click(
      screen.getByRole("button", {
        name: "Refresh enforcement records and recovery",
      }),
    );
    await waitFor(() => {
      expect(h.calls.length).toBeGreaterThan(before);
    });
    expect(discard).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Reason for recording warning")).toHaveValue(
      enforcementValue(warningBody.reason),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Review original action" }),
    );
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Send original enforcement action again",
      }),
    );
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByLabelText("Warning sequence")).toHaveValue("2");
    });
    expect(screen.getByLabelText("Reason for recording warning")).toHaveValue(
      "",
    );
    const posts = h.calls.filter((c) => c.method === "POST");
    expect(posts).toHaveLength(2);
    expect(posts[1]?.key).toBe(posts[0]?.key);
    expect(posts[1]?.body).toBe(posts[0]?.body);
    expect(h.state.warnings).toHaveLength(1);
    expect(h.records.size).toBe(0);
  });
  it("TEST-FE-627 preserves a blocked new draft when a different pending command is confirmed", async () => {
    const h = harness(["leases.warn"]),
      dirty = vi.fn();
    render(
      <LeaseEnforcementManagement
        actorId={ids.actor}
        services={h.services}
        onDirtyStateChange={dirty}
      />,
    );
    await selectProperty();
    await selectLease("general warnings");
    fireEvent.click(
      within(await warningForm()).getByRole("button", {
        name: "Review Lease warning",
      }),
    );
    // Another tab stores and sends a different warning after this tab opened confirmation.
    h.state.loseNext = true;
    const prior = await h.services.recovery.submit(
      {
        actorId: ids.actor,
        propertyId: ids.property,
        signal: new AbortController().signal,
      },
      {
        operation: "leaseWarningRecord",
        target: { id: ids.lease },
        body: {
          ...warningBody,
          reason: "Other tab reason",
          violation_description: "Other tab violation",
        },
      },
    );
    expect(prior.kind).toBe("pending");
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Record Lease violation warning",
      }),
    );
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(h.calls.filter((c) => c.method === "POST")).toHaveLength(1);
    expect(screen.getByLabelText("Reason for recording warning")).toHaveValue(
      enforcementValue(warningBody.reason),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Review original action" }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Other tab violation")).toBeInTheDocument();
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "Send original enforcement action again",
      }),
    );
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Review Lease warning" }),
      ).toBeEnabled();
    });
    expect(screen.getByLabelText("Reason for recording warning")).toHaveValue(
      enforcementValue(warningBody.reason),
    );
    expect(screen.getByLabelText("Violation description")).toHaveValue(
      enforcementValue(warningBody.violation_description),
    );
    expect(dirty).toHaveBeenLastCalledWith(true);
    const posts = h.calls.filter((c) => c.method === "POST");
    expect(posts).toHaveLength(2);
    expect(posts[1]?.key).toBe(posts[0]?.key);
    expect(posts[1]?.body).toBe(posts[0]?.body);
    expect(h.state.warnings).toHaveLength(1);
    expect(h.records.size).toBe(0);
  });
  it("TEST-FE-649 lists unpaid Initial Rent alerts read-only and selects the Lease without opening a case", async () => {
    const h = harness(["rent_nonpayment.read"]);
    render(
      <LeaseEnforcementManagement actorId={ids.actor} services={h.services} />,
    );
    await selectProperty();
    const alerts = await screen.findByRole("region", {
      name: "Unpaid Initial Rent alerts",
    });
    await within(alerts).findByText("INV-INITIAL-1");
    expect(within(alerts).getByText("USD 310.00")).toBeInTheDocument();
    expect(within(alerts).getByText("2026-09-06")).toBeInTheDocument();
    expect(alerts).toHaveTextContent("does not open a case");
    fireEvent.click(
      within(alerts).getByRole("button", { name: "Review this Lease" }),
    );
    await waitFor(() => {
      expect(screen.getByLabelText("Lease for Rent nonpayment")).toHaveValue(
        ids.lease,
      );
    });
    expect(h.calls.some((call) => call.method === "POST")).toBe(false);
    expect(
      h.calls.some((call) => call.url.includes("/initial-rent-unpaid-alerts")),
    ).toBe(true);
  });
  it("TEST-FE-650 hides the Initial Rent alerts without Rent nonpayment read authority", async () => {
    const h = harness(["rent_nonpayment.event_post"]);
    render(
      <LeaseEnforcementManagement actorId={ids.actor} services={h.services} />,
    );
    await selectProperty();
    expect(
      screen.queryByRole("region", { name: "Unpaid Initial Rent alerts" }),
    ).not.toBeInTheDocument();
    expect(
      h.calls.some((call) => call.url.includes("/initial-rent-unpaid-alerts")),
    ).toBe(false);
  });
});
