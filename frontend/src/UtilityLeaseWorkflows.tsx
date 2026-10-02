import { FormEvent, useRef, useState } from "react";

import {
  BaselineInput,
  EvidenceRecord,
  FinalInputItem,
  UnbilledPeriod,
  UtilityLeaseApi,
  UtilityLeaseError,
  utilityLeaseApi,
  utilityReasonText,
} from "./utilityLeaseClient";

export interface UtilityLeaseWorkflowsProps {
  propertyId: string;
  api?: UtilityLeaseApi;
}

function field(data: FormData, name: string): string {
  const value = data.get(name);
  return typeof value === "string" ? value.trim() : "";
}

function lines(value: string): string[][] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "")
    .map((line) => line.split(/[,\s]+/).filter((part) => part !== ""));
}

function baselineItems(value: string): BaselineInput["items"] {
  const rows = lines(value);
  const meters = new Set<string>();
  if (rows.length < 1 || rows.length > 20) throw new Error("items");
  return rows.map(([meter, reading, extra]) => {
    if (!meter || !reading || extra !== undefined || meters.has(meter))
      throw new Error("items");
    meters.add(meter);
    return { meter_id: meter, reading_id: reading };
  });
}

function finalItems(value: string): FinalInputItem[] {
  const rows = lines(value);
  const meters = new Set<string>();
  if (rows.length < 1 || rows.length > 20) throw new Error("items");
  return rows.map(([meter, resolution, source, extra]) => {
    if (!meter || !source || extra !== undefined || meters.has(meter))
      throw new Error("items");
    meters.add(meter);
    if (resolution === "READING")
      return { meter_id: meter, resolution, reading_id: source };
    if (resolution === "ESTIMATE")
      return { meter_id: meter, resolution, estimate_id: source };
    if (resolution === "UNRESOLVED")
      return { meter_id: meter, resolution, unresolved_reason: source };
    throw new Error("items");
  });
}

function dueDate(
  data: FormData,
  dateName: string,
  reasonName: string,
): { due_date?: string; due_date_reason?: string } {
  const date = field(data, dateName);
  const reason = field(data, reasonName);
  if (Boolean(date) !== Boolean(reason)) throw new Error("due");
  return date ? { due_date: date, due_date_reason: reason } : {};
}

export function UtilityLeaseWorkflows({
  propertyId,
  api = utilityLeaseApi,
}: UtilityLeaseWorkflowsProps) {
  const [leaseId, setLeaseId] = useState("");
  const [catchUpPeriod, setCatchUpPeriod] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [shown, setShown] = useState<{
    title: string;
    data: EvidenceRecord;
  } | null>(null);
  const [unbilled, setUnbilled] = useState<UnbilledPeriod[] | null>(null);
  // A retry of an unchanged form reuses its identities so a lost reply is replayed, not repeated.
  const attempts = useRef(
    new Map<string, { signature: string; key: string; id: string }>(),
  );

  function attempt(name: string, signature: string) {
    const known = attempts.current.get(name);
    if (known?.signature === signature) return known;
    const fresh = {
      signature,
      key: crypto.randomUUID(),
      id: crypto.randomUUID(),
    };
    attempts.current.set(name, fresh);
    return fresh;
  }

  function fail(error: unknown) {
    setFailed(true);
    setNotice(
      error instanceof UtilityLeaseError
        ? utilityReasonText(error.code) +
            (error.requestId === null
              ? ""
              : ` Support request ID: ${error.requestId}.`)
        : "The Utility request could not be completed.",
    );
  }

  function run(
    title: string,
    task: () => Promise<EvidenceRecord>,
    done?: () => void,
  ) {
    setBusy(true);
    setFailed(false);
    setNotice(null);
    void task()
      .then((data) => {
        done?.();
        setShown({ title, data });
        setNotice(`${title}: done.`);
      })
      .catch(fail)
      .finally(() => {
        setBusy(false);
      });
  }

  function invalid(message: string) {
    setFailed(true);
    setNotice(message);
  }

  function ready(): boolean {
    if (!propertyId || !leaseId) {
      invalid("Enter the Lease identifier first.");
      return false;
    }
    return true;
  }

  function command(
    event: FormEvent<HTMLFormElement>,
    name: string,
    confirmation: string,
    build: (
      data: FormData,
      retry: { key: string; id: string },
    ) => { signature: unknown; send: () => Promise<EvidenceRecord> },
    title: string,
  ) {
    event.preventDefault();
    if (!ready()) return;
    const data = new FormData(event.currentTarget);
    let prepared: ReturnType<typeof build>;
    try {
      const probe = { key: "", id: "" };
      const signature = JSON.stringify([
        propertyId,
        leaseId,
        build(data, probe).signature,
      ]);
      const retry = attempt(name, signature);
      prepared = build(data, retry);
    } catch {
      invalid(
        "Check the entered values. Items need one line each, and a Due Date needs its reason.",
      );
      return;
    }
    if (!window.confirm(confirmation)) return;
    run(title, prepared.send, () => {
      attempts.current.delete(name);
    });
  }

  function recordBaseline(event: FormEvent<HTMLFormElement>) {
    command(
      event,
      "baseline",
      "Record this Utility baseline? It references existing Readings and creates no Reading or charge.",
      (data, retry) => {
        const supersedes = field(data, "baseline-supersedes");
        const input: BaselineInput = {
          event_id: retry.id,
          ...(supersedes ? { supersedes_event_id: supersedes } : {}),
          baseline_date: field(data, "baseline-date"),
          reason: field(data, "baseline-reason"),
          evidence_reference: field(data, "baseline-evidence"),
          items: baselineItems(field(data, "baseline-items")),
        };
        if (!input.baseline_date || !input.reason || !input.evidence_reference)
          throw new Error("required");
        return {
          signature: { ...input, event_id: "" },
          send: () => api.recordBaseline(propertyId, leaseId, input, retry.key),
        };
      },
      "Recorded Utility baseline",
    );
  }

  function recordFinalInputs(event: FormEvent<HTMLFormElement>) {
    command(
      event,
      "final-inputs",
      "Record these final Utility inputs for the departure? They reference existing Readings or estimates and create no Reading or charge.",
      (data, retry) => {
        const supersedes = field(data, "final-supersedes");
        const input = {
          event_id: retry.id,
          move_out_event_id: field(data, "final-move-out"),
          ...(supersedes ? { supersedes_event_id: supersedes } : {}),
          reason: field(data, "final-reason"),
          authorization_reference: field(data, "final-authorization"),
          evidence_reference: field(data, "final-evidence"),
          items: finalItems(field(data, "final-items")),
        };
        if (
          !input.move_out_event_id ||
          !input.reason ||
          !input.authorization_reference ||
          !input.evidence_reference
        )
          throw new Error("required");
        return {
          signature: { ...input, event_id: "" },
          send: () =>
            api.recordFinalInputs(propertyId, leaseId, input, retry.key),
        };
      },
      "Recorded final Utility inputs",
    );
  }

  function createFinal(event: FormEvent<HTMLFormElement>) {
    command(
      event,
      "final-invoice",
      "Create the final Utility Invoice from the current final inputs? This bills the Customer and cannot be edited afterwards.",
      (data, retry) => {
        const input = {
          invoice_id: retry.id,
          final_input_event_id: field(data, "invoice-event"),
          ...dueDate(data, "invoice-due", "invoice-due-reason"),
        };
        if (!input.final_input_event_id) throw new Error("required");
        return {
          signature: { ...input, invoice_id: "" },
          send: () =>
            api.createFinalInvoice(propertyId, leaseId, input, retry.key),
        };
      },
      "Created final Utility Invoice",
    );
  }

  function createCatchUp(event: FormEvent<HTMLFormElement>) {
    command(
      event,
      "catch-up",
      "Create the catch-up Utility Invoice for this period? This bills the Customer and cannot be edited afterwards.",
      (data, retry) => {
        const input = {
          invoice_id: retry.id,
          consumption_period_id: field(data, "catch-up-period"),
          ...dueDate(data, "catch-up-due", "catch-up-due-reason"),
        };
        if (!input.consumption_period_id) throw new Error("required");
        return {
          signature: { ...input, invoice_id: "" },
          send: () =>
            api.createCatchUpInvoice(propertyId, leaseId, input, retry.key),
        };
      },
      "Created catch-up Utility Invoice",
    );
  }

  function loadUnbilled() {
    if (!propertyId) {
      invalid("Select a Property first.");
      return;
    }
    setBusy(true);
    setFailed(false);
    setNotice(null);
    void api
      .listUnbilled(propertyId)
      .then((page) => {
        setUnbilled(page.items);
        setNotice(
          page.items.length === 0
            ? "No unbilled Utility periods."
            : `${String(page.items.length)} unbilled Utility period(s) loaded.`,
        );
      })
      .catch(fail)
      .finally(() => {
        setBusy(false);
      });
  }

  if (!propertyId)
    return (
      <section aria-labelledby="utility-lease-heading" className="panel">
        <h3 id="utility-lease-heading">Lease Utility records</h3>
        <p>Select an authorized Property to use Lease Utility records.</p>
      </section>
    );
  return (
    <section aria-labelledby="utility-lease-heading" className="panel">
      <h3 id="utility-lease-heading">Lease Utility records</h3>
      <p>
        Baselines, final inputs and Invoices for a Lease reference existing
        Readings. Nothing here creates a Reading or changes history; each
        command asks for confirmation and a retry of an unchanged form is
        replayed, not repeated.
      </p>
      <p role={failed ? "alert" : "status"}>{notice}</p>
      <label>
        Utility Lease identifier
        <input
          maxLength={64}
          onChange={(event) => {
            setLeaseId(event.target.value.trim());
          }}
          value={leaseId}
        />
      </label>

      <form className="form-stack" onSubmit={recordBaseline}>
        <h4>Utility baseline</h4>
        <p>
          For a signed Lease with no Occupancy yet: one validated Reading per
          Meter dated on the baseline date, on or before the Lease Start Date.
        </p>
        <label>
          Baseline date
          <input name="baseline-date" required type="date" />
        </label>
        <label>
          Baseline reason
          <input maxLength={500} name="baseline-reason" required />
        </label>
        <label>
          Baseline evidence reference
          <input maxLength={500} name="baseline-evidence" required />
        </label>
        <label>
          Baseline items (one per line: Meter ID, Reading ID)
          <textarea name="baseline-items" required rows={3} />
        </label>
        <label>
          Superseded baseline event (optional)
          <input name="baseline-supersedes" />
        </label>
        <button disabled={busy} type="submit">
          Record Utility baseline
        </button>
        <button
          disabled={busy || !leaseId}
          onClick={() => {
            run("Baseline history", () =>
              api.readBaseline(propertyId, leaseId),
            );
          }}
          type="button"
        >
          Load baseline history
        </button>
      </form>

      <form className="form-stack" onSubmit={recordFinalInputs}>
        <h4>Final Utility inputs for a departure</h4>
        <p>
          One line per Meter: Meter ID, READING, Reading ID; Meter ID, ESTIMATE,
          estimate ID; or Meter ID, UNRESOLVED, reason code. An unresolved item
          blocks the final Invoice until a successor input resolves it.
        </p>
        <label>
          Move-out event identifier
          <input name="final-move-out" required />
        </label>
        <label>
          Final input reason
          <input maxLength={500} name="final-reason" required />
        </label>
        <label>
          Final input authorization reference
          <input maxLength={500} name="final-authorization" required />
        </label>
        <label>
          Final input evidence reference
          <input maxLength={500} name="final-evidence" required />
        </label>
        <label>
          Final input items (Meter ID, resolution, source)
          <textarea name="final-items" required rows={3} />
        </label>
        <label>
          Superseded final input event (optional)
          <input name="final-supersedes" />
        </label>
        <button disabled={busy} type="submit">
          Record final Utility inputs
        </button>
        <button
          disabled={busy || !leaseId}
          onClick={() => {
            run("Final input history", () =>
              api.readFinalInputs(propertyId, leaseId),
            );
          }}
          type="button"
        >
          Load final input history
        </button>
      </form>

      <form className="form-stack" onSubmit={createFinal}>
        <h4>Final Utility Invoice</h4>
        <p>
          Bills the final Readings and every unbilled period of the departed
          Lease in one Invoice, from the current final input event.
        </p>
        <label>
          Final input event identifier
          <input name="invoice-event" required />
        </label>
        <label>
          Final Invoice Due Date (optional)
          <input name="invoice-due" type="date" />
        </label>
        <label>
          Final Invoice Due Date reason
          <input maxLength={500} name="invoice-due-reason" />
        </label>
        <button disabled={busy} type="submit">
          Create final Utility Invoice
        </button>
      </form>

      <section aria-label="Unbilled Utility periods">
        <h4>Unbilled Utility periods</h4>
        <p>
          Finalized periods that no run will pick up. A late period is billed
          only by an explicit catch-up.
        </p>
        <button disabled={busy} onClick={loadUnbilled} type="button">
          Load unbilled Utility periods
        </button>
        {unbilled !== null &&
          (unbilled.length === 0 ? (
            <p>No unbilled Utility periods.</p>
          ) : (
            <table>
              <caption>Unbilled Utility periods</caption>
              <thead>
                <tr>
                  {[
                    "Period",
                    "Type",
                    "From",
                    "To",
                    "Consumption",
                    "Lease",
                    "Why unbilled",
                    "Action",
                  ].map((label) => (
                    <th key={label} scope="col">
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {unbilled.map((row) => (
                  <tr key={row.period_id}>
                    <td>{row.period_id}</td>
                    <td>{row.utility_type}</td>
                    <td>{row.start_date}</td>
                    <td>{row.end_date}</td>
                    <td>{row.consumption_quantity}</td>
                    <td>{row.lease_id ?? "None"}</td>
                    <td>
                      {row.gap_reason === "LATE_AFTER_SUCCEEDED_RUN"
                        ? "Finalized after its run succeeded"
                        : "Skipped: Customer had not moved in"}
                    </td>
                    <td>
                      {row.can_catch_up && row.lease_id !== null ? (
                        <button
                          onClick={() => {
                            setLeaseId(row.lease_id ?? "");
                            setCatchUpPeriod(row.period_id);
                            setNotice(
                              "Catch-up period selected. Review it and create the catch-up Invoice.",
                            );
                          }}
                          type="button"
                        >
                          {`Select period ${row.period_id} for catch-up`}
                        </button>
                      ) : (
                        "Not yet eligible"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ))}
      </section>

      <form className="form-stack" onSubmit={createCatchUp}>
        <h4>Catch-up Utility Invoice</h4>
        <label>
          Catch-up period identifier
          <input
            name="catch-up-period"
            onChange={(event) => {
              setCatchUpPeriod(event.target.value.trim());
            }}
            required
            value={catchUpPeriod}
          />
        </label>
        <label>
          Catch-up Due Date (optional)
          <input name="catch-up-due" type="date" />
        </label>
        <label>
          Catch-up Due Date reason
          <input maxLength={500} name="catch-up-due-reason" />
        </label>
        <button disabled={busy} type="submit">
          Create catch-up Utility Invoice
        </button>
      </form>

      {shown !== null && (
        <section aria-label="Utility evidence">
          <h4>{shown.title}</h4>
          <pre>{JSON.stringify(shown.data, null, 2)}</pre>
        </section>
      )}
    </section>
  );
}
