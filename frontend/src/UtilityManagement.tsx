import { FormEvent, useRef, useState } from "react";

import {
  MEASUREMENT_UNIT_CODES,
  measurementUnitLabel,
} from "./measurementUnits";

import {
  BatchReadingInput,
  ReadingCorrectionResult,
  UtilityApi,
  UtilityCalculation,
  UtilityClientError,
  MeterSerialNumberInUseError,
  UtilityConflictError,
  UtilityReading,
  UtilitySnapshot,
  UtilityType,
} from "./utilityClient";

export interface UtilityManagementProps {
  api: UtilityApi;
  propertyId?: string;
}

interface BatchRow {
  rowId: string;
  meterId: string;
  expectedVersion: string;
  readingDate: string;
  readingValue: string;
  evidence: string;
}

interface CorrectionDraft {
  reading: UtilityReading;
  correctedValue: string;
  reason: string;
  authorizationReference: string;
}

function emptyBatchRow(): BatchRow {
  return {
    rowId: crypto.randomUUID(),
    meterId: "",
    expectedVersion: "",
    readingDate: "",
    readingValue: "",
    evidence: "",
  };
}

export function UtilityManagement({
  api,
  propertyId = "",
}: UtilityManagementProps) {
  const [targetPropertyId, setTargetPropertyId] = useState(propertyId);
  const [unitId, setUnitId] = useState("");
  const [snapshot, setSnapshot] = useState<UtilitySnapshot | null>(null);
  const [calculation, setCalculation] = useState<UtilityCalculation | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [batchMode, setBatchMode] = useState<"ATOMIC_ALL" | "PARTIAL">(
    "PARTIAL",
  );
  const [batchRows, setBatchRows] = useState<BatchRow[]>([emptyBatchRow()]);
  const [batchResults, setBatchResults] = useState<
    { row: number; status: string; detail: string }[]
  >([]);
  const [correctionDraft, setCorrectionDraft] =
    useState<CorrectionDraft | null>(null);
  const [correctionReview, setCorrectionReview] = useState(false);
  const [correctionResult, setCorrectionResult] =
    useState<ReadingCorrectionResult | null>(null);
  const pendingKeys = useRef<
    Record<string, { payload: string; key: string } | undefined>
  >({});

  function text(data: FormData, name: string): string {
    const value = data.get(name);
    return typeof value === "string" ? value.trim() : "";
  }

  function optional(data: FormData, name: string): string | null {
    return text(data, name) || null;
  }

  function localTimestamp(value: string): string {
    return value.length === 16 ? `${value}:00+07:00` : `${value}+07:00`;
  }

  function commandKey(kind: string, payload: object): string {
    const serialized = JSON.stringify(payload);
    const existing = pendingKeys.current[kind];
    if (existing?.payload === serialized) return existing.key;
    const key = crypto.randomUUID();
    pendingKeys.current[kind] = { payload: serialized, key };
    return key;
  }

  function diagnostics(error: unknown): string {
    if (!(error instanceof UtilityClientError)) return "";
    const parts: string[] = [];
    if (error.requestId !== null) parts.push(`Reference: ${error.requestId}.`);
    if (error.fields.length > 0) {
      parts.push(`Check fields: ${error.fields.join(", ")}.`);
    }
    return parts.length === 0 ? "" : ` ${parts.join(" ")}`;
  }

  async function reload(message: string) {
    const next = await api.load(targetPropertyId, unitId);
    setSnapshot(next);
    setStatus(message);
  }

  function load(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setFailed(false);
    setCalculation(null);
    setCorrectionDraft(null);
    setCorrectionReview(false);
    setCorrectionResult(null);
    setStatus("Loading authorized Utility history…");
    void api
      .load(targetPropertyId, unitId)
      .then((value) => {
        setSnapshot(value);
        setStatus("Complete Utility history loaded.");
      })
      .catch((error: unknown) => {
        setSnapshot(null);
        setFailed(true);
        setStatus(`Utility history could not be loaded.${diagnostics(error)}`);
      })
      .finally(() => {
        setBusy(false);
      });
  }

  function complete(
    kind: string,
    payload: object,
    command: (key: string) => Promise<unknown>,
    message: string,
    form: HTMLFormElement,
  ) {
    setBusy(true);
    setFailed(false);
    setStatus("Submitting append-only Utility evidence…");
    void command(commandKey(kind, payload))
      .then(() => {
        pendingKeys.current[kind] = undefined;
        form.reset();
        return reload(message);
      })
      .catch((error: unknown) => {
        setFailed(true);
        setStatus(
          error instanceof MeterSerialNumberInUseError
            ? `${error.message} Use the serial printed on the Meter, or another Property code.${diagnostics(error)}`
            : error instanceof UtilityConflictError
              ? `Utility history changed or the command conflicts. Reload before retrying.${diagnostics(error)}`
              : `The Utility command was not completed.${diagnostics(error)}`,
        );
      })
      .finally(() => {
        setBusy(false);
      });
  }

  function install(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const installedDate = text(data, "install-date");
    const utilityType = (
      text(data, "install-type") === "WATER" ? "WATER" : "ELECTRICITY"
    ) as UtilityType;
    const payload = {
      utility_type: utilityType,
      serial_number: text(data, "install-serial"),
      measurement_unit_code: MEASUREMENT_UNIT_CODES[utilityType],
      description: optional(data, "install-description"),
      installed_date: installedDate,
      memo: optional(data, "install-memo"),
      initial_reading: {
        reading_date: installedDate,
        reading_value: text(data, "install-value"),
        source_evidence: text(data, "install-evidence"),
      },
    };
    complete(
      "install",
      payload,
      (key) => api.installMeter(unitId, payload, key),
      "Meter and installation-boundary Reading appended.",
      form,
    );
  }

  function replace(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const replacementDate = text(data, "replace-date");
    const meterId = text(data, "replace-meter-id");
    const payload = {
      expected_version: Number(data.get("replace-version")),
      failed_boundary_reading_id: text(data, "replace-boundary-reading"),
      failure_date: text(data, "replace-failure-date"),
      replacement_date: replacementDate,
      reason: text(data, "replace-reason"),
      replacement_meter: {
        serial_number: text(data, "replace-serial"),
        description: optional(data, "replace-description"),
        memo: optional(data, "replace-memo"),
      },
      replacement_initial_reading: {
        reading_date: replacementDate,
        reading_value: text(data, "replace-value"),
        source_evidence: text(data, "replace-evidence"),
      },
    };
    complete(
      "replace",
      { meterId, ...payload },
      (key) => api.replaceMeter(meterId, payload, key),
      "Replacement chain and boundary evidence appended; prior Meter history remains visible.",
      form,
    );
  }

  function record(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const meterId = text(data, "reading-meter-id");
    const payload = {
      expected_meter_version: Number(data.get("reading-meter-version")),
      reading_date: text(data, "reading-date"),
      reading_value: text(data, "reading-value"),
      source_kind: "MANUAL" as const,
      source_evidence: text(data, "reading-evidence"),
    };
    complete(
      "reading",
      { meterId, ...payload },
      (key) => api.recordReading(meterId, payload, key),
      "Validated Reading appended to Meter history.",
      form,
    );
  }

  function reviewCorrection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCorrectionReview(true);
    setFailed(false);
    setStatus(
      "Review the selected Reading correction, then confirm the append-only command.",
    );
  }

  function selectCorrection(reading: UtilityReading) {
    setCorrectionDraft({
      reading,
      correctedValue: reading.effective_value,
      reason: "",
      authorizationReference: "",
    });
    setCorrectionReview(false);
    setCorrectionResult(null);
    setFailed(false);
    setStatus(
      `Reading from ${reading.reading_date} selected for correction review.`,
    );
  }

  function updateCorrection(
    field: "correctedValue" | "reason" | "authorizationReference",
    value: string,
  ) {
    setCorrectionDraft((current) =>
      current === null ? null : { ...current, [field]: value },
    );
    setCorrectionReview(false);
  }

  async function confirmCorrection() {
    if (correctionDraft === null) return;
    const readingId = correctionDraft.reading.id;
    const payload = {
      expected_version: correctionDraft.reading.version,
      corrected_value: correctionDraft.correctedValue.trim(),
      reason: correctionDraft.reason.trim(),
      authorization_reference: correctionDraft.authorizationReference.trim(),
    };
    setBusy(true);
    setFailed(false);
    setStatus("Submitting the confirmed append-only Reading correction…");
    try {
      const result = await api.correctReading(
        readingId,
        payload,
        commandKey("correction", { readingId, ...payload }),
      );
      pendingKeys.current.correction = undefined;
      setCorrectionResult(result);
      setCorrectionDraft(null);
      setCorrectionReview(false);
      try {
        const next = await api.load(targetPropertyId, unitId);
        setSnapshot(next);
        setStatus(
          "Reading correction and server-authoritative affected-calculation evidence appended; issued lines were not rewritten.",
        );
      } catch (error: unknown) {
        setFailed(true);
        setStatus(
          `The correction completed, but refreshed Utility history could not be loaded. The server correction evidence remains below.${diagnostics(error)}`,
        );
      }
    } catch (error: unknown) {
      setFailed(true);
      setStatus(
        error instanceof UtilityConflictError
          ? `Utility history changed or the command conflicts. Reload before retrying.${diagnostics(error)}`
          : `The Utility command was not completed.${diagnostics(error)}`,
      );
    } finally {
      setBusy(false);
    }
  }

  function rate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const utilityType = (
      text(data, "rate-type") === "WATER" ? "WATER" : "ELECTRICITY"
    ) as UtilityType;
    const payload = {
      utility_type: utilityType,
      measurement_unit_code: MEASUREMENT_UNIT_CODES[utilityType],
      rate_usd_per_unit: text(data, "rate-value"),
      effective_date: text(data, "rate-effective-date"),
      notice_at: localTimestamp(text(data, "rate-notice-at")),
      notice_evidence: text(data, "rate-notice-evidence"),
      source_memo: optional(data, "rate-memo"),
    };
    complete(
      "rate",
      payload,
      (key) => api.createRate(targetPropertyId, payload, key),
      "Effective-dated Utility Rate and advance-notice evidence appended.",
      form,
    );
  }

  function preview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const sourceKind: "CONSUMPTION_PERIOD" | "ESTIMATION_CASE" =
      text(data, "preview-kind") === "ESTIMATION_CASE"
        ? "ESTIMATION_CASE"
        : "CONSUMPTION_PERIOD";
    const payload = {
      property_id: targetPropertyId,
      source_kind: sourceKind,
      source_id: text(data, "preview-source-id"),
      generation_at: localTimestamp(text(data, "preview-generation-at")),
    };
    setBusy(true);
    setFailed(false);
    setStatus("Requesting a non-persisted server calculation…");
    void api
      .preview(payload)
      .then((value) => {
        setCalculation(value);
        setStatus(
          value.status === "PENDING_FUTURE_ACTUAL_BASIS"
            ? "Preview remains pending. No charge was persisted or issued."
            : "Server preview completed. No charge was persisted or issued.",
        );
      })
      .catch((error: unknown) => {
        setCalculation(null);
        setFailed(true);
        setStatus(
          `Utility preview could not be completed.${diagnostics(error)}`,
        );
      })
      .finally(() => {
        setBusy(false);
      });
  }

  function updateBatchRow(rowId: string, field: keyof BatchRow, value: string) {
    setBatchRows((current) =>
      current.map((row) =>
        row.rowId === rowId ? { ...row, [field]: value } : row,
      ),
    );
  }

  function submitBatch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const items: BatchReadingInput[] = batchRows.map((row) => {
      const canonicalItem = {
        meter_id: row.meterId.trim(),
        reading: {
          expected_meter_version: Number(row.expectedVersion),
          reading_date: row.readingDate,
          reading_value: row.readingValue.trim(),
          source_kind: "MANUAL" as const,
          source_evidence: row.evidence.trim(),
        },
      };
      return {
        idempotency_key: commandKey(`batch-${row.rowId}`, canonicalItem),
        ...canonicalItem,
      };
    });
    const envelopeIdempotencyKey =
      batchMode === "ATOMIC_ALL"
        ? commandKey("batch-envelope", { mode: batchMode, items })
        : undefined;
    setBusy(true);
    setFailed(false);
    setBatchResults([]);
    setStatus(
      `Submitting ${String(items.length)} Reading rows in ${batchMode} mode…`,
    );
    void (async () => {
      let results: Awaited<ReturnType<UtilityApi["recordBatch"]>>;
      try {
        results = await api.recordBatch(
          targetPropertyId,
          batchMode,
          items,
          envelopeIdempotencyKey,
        );
      } catch (error: unknown) {
        setFailed(true);
        setStatus(
          `The ${batchMode} batch was not completed. In ATOMIC_ALL mode no row is retained after a failure.${diagnostics(error)}`,
        );
        setBusy(false);
        return;
      }

      setBatchResults(
        results.map((result) => ({
          row: result.index + 1,
          status: result.status,
          detail:
            result.reading?.effective_value ??
            result.error?.code ??
            "No detail",
        })),
      );
      const allItemsSucceeded =
        results.length === items.length &&
        results.every((result) => result.status === "SUCCEEDED");
      const hasFailedItems = results.some(
        (result) => result.status === "FAILED",
      );
      pendingKeys.current["batch-envelope"] = undefined;
      for (const row of batchRows)
        pendingKeys.current[`batch-${row.rowId}`] = undefined;

      try {
        await reload("Bulk Reading results are shown per row.");
      } catch (error: unknown) {
        setFailed(true);
        setStatus(
          allItemsSucceeded
            ? `The ${batchMode} batch completed successfully, but Utility history could not be refreshed.${diagnostics(error)}`
            : batchMode === "ATOMIC_ALL" && hasFailedItems
              ? `The ATOMIC_ALL batch failed and was rolled back, and Utility history also could not be refreshed.${diagnostics(error)}`
              : `The ${batchMode} batch did not return a complete successful result set, and Utility history also could not be refreshed.${diagnostics(error)}`,
        );
      } finally {
        setBusy(false);
      }
    })();
  }

  return (
    <section
      aria-labelledby="utility-management-heading"
      className="information-card"
    >
      <h3 id="utility-management-heading">Utilities</h3>
      <p>
        Manage Meter and Reading source evidence, immutable Rate history, and
        server-authoritative calculation previews. This screen never calculates
        or issues a financial charge.
      </p>
      <form className="form-stack inline-form" onSubmit={load}>
        <div className="form-field">
          <label htmlFor="utility-property-id">
            Utility Property identifier
          </label>
          <input
            id="utility-property-id"
            onChange={(event) => {
              setTargetPropertyId(event.currentTarget.value);
            }}
            required
            value={targetPropertyId}
          />
        </div>
        <div className="form-field">
          <label htmlFor="utility-unit-id">Unit identifier</label>
          <input
            id="utility-unit-id"
            onChange={(event) => {
              setUnitId(event.currentTarget.value);
            }}
            required
            value={unitId}
          />
        </div>
        <button disabled={busy} type="submit">
          Load Utility workspace
        </button>
      </form>
      {status !== null && (
        <p aria-live="polite" role={failed ? "alert" : "status"}>
          {status}
        </p>
      )}

      {snapshot !== null && (
        <div className="utility-workspace">
          <section aria-labelledby="meter-history-heading">
            <h4 id="meter-history-heading">Meter and Reading history</h4>
            {snapshot.meters.length === 0 ? (
              <p>No Meters are recorded for this Unit.</p>
            ) : (
              <ul className="record-list utility-records">
                {snapshot.meters.map((meter) => (
                  <li key={meter.id}>
                    <strong>
                      {meter.utility_type}: {meter.serial_number}
                    </strong>
                    <dl className="detail-list compact-details">
                      <div>
                        <dt>Meter</dt>
                        <dd>
                          <code>{meter.id}</code>
                        </dd>
                      </div>
                      <div>
                        <dt>Measurement unit</dt>
                        <dd>
                          {measurementUnitLabel(meter.measurement_unit_code)}
                        </dd>
                      </div>
                      <div>
                        <dt>Installed</dt>
                        <dd>{meter.installed_date}</dd>
                      </div>
                      <div>
                        <dt>Assignment</dt>
                        <dd>
                          {meter.current
                            ? "Current"
                            : `Historical; replaced ${meter.deactivated_date ?? "date unavailable"}`}
                        </dd>
                      </div>
                      <div>
                        <dt>Version</dt>
                        <dd>{meter.version}</dd>
                      </div>
                      <div>
                        <dt>Replacement link</dt>
                        <dd>
                          {meter.replacement.replacement_meter_id ??
                            meter.replacement.replaced_meter_id ??
                            "None"}
                        </dd>
                      </div>
                    </dl>
                    {(snapshot.readings[meter.id] ?? []).length === 0 ? (
                      <p>No Readings are recorded for this Meter.</p>
                    ) : (
                      <table>
                        <caption>
                          Complete Reading history for {meter.serial_number}
                        </caption>
                        <thead>
                          <tr>
                            <th>Date</th>
                            <th>Original</th>
                            <th>Effective</th>
                            <th>Validation</th>
                            <th>Evidence</th>
                            <th>Corrections</th>
                            <th>Action</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(snapshot.readings[meter.id] ?? []).map(
                            (reading) => (
                              <tr key={reading.id}>
                                <td>{reading.reading_date}</td>
                                <td>{reading.original_value}</td>
                                <td>
                                  {reading.effective_value}{" "}
                                  {measurementUnitLabel(
                                    reading.measurement_unit_code,
                                  )}
                                </td>
                                <td>
                                  {reading.validated
                                    ? `Validated by ${reading.validated_by} at ${reading.validated_at}`
                                    : "Pending validation"}
                                </td>
                                <td>{reading.source.evidence}</td>
                                <td>
                                  {reading.corrections.length === 0
                                    ? "None"
                                    : reading.corrections
                                        .map(
                                          (item) =>
                                            `${item.corrected_value}: ${item.reason}`,
                                        )
                                        .join("; ")}
                                </td>
                                <td>
                                  {reading.validated ? (
                                    <button
                                      aria-label={`Correct Reading from ${reading.reading_date} for Meter ${meter.serial_number}`}
                                      disabled={busy}
                                      onClick={() => {
                                        selectCorrection(reading);
                                      }}
                                      type="button"
                                    >
                                      Correct this Reading
                                    </button>
                                  ) : (
                                    "Correction unavailable while pending"
                                  )}
                                </td>
                              </tr>
                            ),
                          )}
                        </tbody>
                      </table>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section aria-labelledby="install-meter-heading">
            <h4 id="install-meter-heading">Install Meter</h4>
            <form className="form-stack" onSubmit={install}>
              <label>
                Utility Type
                <select name="install-type">
                  <option value="ELECTRICITY">Electricity</option>
                  <option value="WATER">Water</option>
                </select>
              </label>
              <label>
                Serial number (or a Property code such as EL-U101)
                <input name="install-serial" required />
              </label>
              <p className="panel-help">
                Electricity is measured in kWh and water in m³.
              </p>
              <label>
                Installation date
                <input name="install-date" required type="date" />
              </label>
              <label>
                Initial Reading value
                <input
                  min="0"
                  name="install-value"
                  required
                  step="0.000001"
                  type="number"
                />
              </label>
              <label>
                Boundary Reading evidence
                <textarea name="install-evidence" required />
              </label>
              <label>
                Description
                <input name="install-description" />
              </label>
              <label>
                Memo
                <input name="install-memo" />
              </label>
              <button disabled={busy} type="submit">
                Append Meter installation
              </button>
            </form>
          </section>

          <section aria-labelledby="replace-meter-heading">
            <h4 id="replace-meter-heading">Replace confirmed failed Meter</h4>
            <p>
              Replacement preserves the failed Meter and its Readings. The last
              validated failed-Meter Reading and first replacement Reading
              establish the boundary.
            </p>
            <form className="form-stack" onSubmit={replace}>
              <label>
                Failed Meter identifier
                <input name="replace-meter-id" required />
              </label>
              <label>
                Expected Meter version
                <input min="1" name="replace-version" required type="number" />
              </label>
              <label>
                Failed boundary Reading identifier
                <input name="replace-boundary-reading" required />
              </label>
              <label>
                Failure date
                <input name="replace-failure-date" required type="date" />
              </label>
              <label>
                Replacement date
                <input name="replace-date" required type="date" />
              </label>
              <label>
                Replacement serial or identity
                <input name="replace-serial" required />
              </label>
              <label>
                Replacement initial value
                <input
                  min="0"
                  name="replace-value"
                  required
                  step="0.000001"
                  type="number"
                />
              </label>
              <label>
                Replacement boundary evidence
                <textarea name="replace-evidence" required />
              </label>
              <label>
                Replacement reason
                <textarea name="replace-reason" required />
              </label>
              <label>
                Description
                <input name="replace-description" />
              </label>
              <label>
                Memo
                <input name="replace-memo" />
              </label>
              <button disabled={busy} type="submit">
                Append replacement chain
              </button>
            </form>
          </section>

          <section aria-labelledby="reading-entry-heading">
            <h4 id="reading-entry-heading">Monthly Reading entry</h4>
            <form className="form-stack" onSubmit={record}>
              <label>
                Meter identifier
                <input name="reading-meter-id" required />
              </label>
              <label>
                Expected Meter version
                <input
                  min="1"
                  name="reading-meter-version"
                  required
                  type="number"
                />
              </label>
              <label>
                Reading date
                <input name="reading-date" required type="date" />
              </label>
              <label>
                Current value
                <input
                  min="0"
                  name="reading-value"
                  required
                  step="0.000001"
                  type="number"
                />
              </label>
              <label>
                Source evidence
                <textarea name="reading-evidence" required />
              </label>
              <button disabled={busy} type="submit">
                Append validated Reading
              </button>
            </form>
          </section>

          <section aria-labelledby="bulk-reading-heading">
            <h4 id="bulk-reading-heading">Bounded bulk Reading entry</h4>
            <form className="form-stack" onSubmit={submitBatch}>
              <label>
                Batch behavior
                <select
                  onChange={(event) => {
                    setBatchMode(
                      event.currentTarget.value === "ATOMIC_ALL"
                        ? "ATOMIC_ALL"
                        : "PARTIAL",
                    );
                  }}
                  value={batchMode}
                >
                  <option value="PARTIAL">Partial with per-row results</option>
                  <option value="ATOMIC_ALL">Atomic all rows</option>
                </select>
              </label>
              {batchRows.map((row, index) => (
                <fieldset key={row.rowId}>
                  <legend>Reading row {index + 1}</legend>
                  <label>
                    Meter identifier
                    <input
                      onChange={(event) => {
                        updateBatchRow(
                          row.rowId,
                          "meterId",
                          event.currentTarget.value,
                        );
                      }}
                      required
                      value={row.meterId}
                    />
                  </label>
                  <label>
                    Expected Meter version
                    <input
                      min="1"
                      onChange={(event) => {
                        updateBatchRow(
                          row.rowId,
                          "expectedVersion",
                          event.currentTarget.value,
                        );
                      }}
                      required
                      type="number"
                      value={row.expectedVersion}
                    />
                  </label>
                  <label>
                    Reading date
                    <input
                      onChange={(event) => {
                        updateBatchRow(
                          row.rowId,
                          "readingDate",
                          event.currentTarget.value,
                        );
                      }}
                      required
                      type="date"
                      value={row.readingDate}
                    />
                  </label>
                  <label>
                    Current value
                    <input
                      min="0"
                      onChange={(event) => {
                        updateBatchRow(
                          row.rowId,
                          "readingValue",
                          event.currentTarget.value,
                        );
                      }}
                      required
                      step="0.000001"
                      type="number"
                      value={row.readingValue}
                    />
                  </label>
                  <label>
                    Source evidence
                    <input
                      onChange={(event) => {
                        updateBatchRow(
                          row.rowId,
                          "evidence",
                          event.currentTarget.value,
                        );
                      }}
                      required
                      value={row.evidence}
                    />
                  </label>
                  {batchRows.length > 1 && (
                    <button
                      onClick={() => {
                        setBatchRows((current) =>
                          current.filter((item) => item.rowId !== row.rowId),
                        );
                      }}
                      type="button"
                    >
                      Remove row
                    </button>
                  )}
                </fieldset>
              ))}
              <div className="button-row">
                <button
                  disabled={batchRows.length >= 100}
                  onClick={() => {
                    setBatchRows((current) => [...current, emptyBatchRow()]);
                  }}
                  type="button"
                >
                  Add Reading row
                </button>
                <button disabled={busy} type="submit">
                  Submit Reading batch
                </button>
              </div>
            </form>
            {batchResults.length > 0 && (
              <table>
                <caption>Reading batch item results</caption>
                <thead>
                  <tr>
                    <th>Row</th>
                    <th>Status</th>
                    <th>Server result</th>
                  </tr>
                </thead>
                <tbody>
                  {batchResults.map((result) => (
                    <tr key={result.row}>
                      <td>{result.row}</td>
                      <td>{result.status}</td>
                      <td>{result.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section aria-labelledby="correction-heading">
            <h4 id="correction-heading">Correct a Reading</h4>
            <p>
              Choose a Reading from its history row. The correction is bound to
              that server Reading and version, then requires review and explicit
              confirmation. The server records calculation impacts and never
              silently rewrites an issued Utility Invoice.
            </p>
            {correctionDraft === null ? (
              <p>
                Select “Correct this Reading” in the complete history above.
              </p>
            ) : (
              <form className="form-stack" onSubmit={reviewCorrection}>
                <div
                  aria-label="Selected Reading correction source"
                  className="correction-source"
                  role="region"
                >
                  <h5>Selected Reading</h5>
                  <dl className="detail-list compact-details">
                    <div>
                      <dt>Reading</dt>
                      <dd>
                        <code>{correctionDraft.reading.id}</code>
                      </dd>
                    </div>
                    <div>
                      <dt>Date</dt>
                      <dd>{correctionDraft.reading.reading_date}</dd>
                    </div>
                    <div>
                      <dt>Original value</dt>
                      <dd>
                        {correctionDraft.reading.original_value}{" "}
                        {measurementUnitLabel(
                          correctionDraft.reading.measurement_unit_code,
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt>Current effective value</dt>
                      <dd>
                        {correctionDraft.reading.effective_value}{" "}
                        {measurementUnitLabel(
                          correctionDraft.reading.measurement_unit_code,
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt>Expected Reading version</dt>
                      <dd>{correctionDraft.reading.version}</dd>
                    </div>
                  </dl>
                </div>
                <label>
                  Corrected value
                  <input
                    min="0"
                    onChange={(event) => {
                      updateCorrection(
                        "correctedValue",
                        event.currentTarget.value,
                      );
                    }}
                    required
                    step="0.000001"
                    type="number"
                    value={correctionDraft.correctedValue}
                  />
                </label>
                <label>
                  Correction reason
                  <textarea
                    onChange={(event) => {
                      updateCorrection("reason", event.currentTarget.value);
                    }}
                    required
                    value={correctionDraft.reason}
                  />
                </label>
                <label>
                  Authorization reference
                  <input
                    onChange={(event) => {
                      updateCorrection(
                        "authorizationReference",
                        event.currentTarget.value,
                      );
                    }}
                    required
                    value={correctionDraft.authorizationReference}
                  />
                </label>
                <button disabled={busy} type="submit">
                  Review Reading correction
                </button>
                {correctionReview && (
                  <div
                    aria-labelledby="correction-confirmation-heading"
                    className="confirmation-panel"
                    role="region"
                  >
                    <h5 id="correction-confirmation-heading">
                      Confirm Reading correction
                    </h5>
                    <p>
                      Append a correction from{" "}
                      <strong>
                        {correctionDraft.reading.effective_value}{" "}
                        {measurementUnitLabel(
                          correctionDraft.reading.measurement_unit_code,
                        )}
                      </strong>{" "}
                      to{" "}
                      <strong>
                        {correctionDraft.correctedValue}{" "}
                        {measurementUnitLabel(
                          correctionDraft.reading.measurement_unit_code,
                        )}
                      </strong>{" "}
                      for “{correctionDraft.reason}” under authorization “
                      {correctionDraft.authorizationReference}”.
                    </p>
                    <p>
                      This records append-only history. Any issued Invoice
                      remains unchanged; the server returns its
                      affected-calculation evidence separately.
                    </p>
                    <button
                      disabled={busy}
                      onClick={() => {
                        void confirmCorrection();
                      }}
                      type="button"
                    >
                      Confirm and append correction
                    </button>
                  </div>
                )}
              </form>
            )}
            {correctionResult !== null && (
              <div
                aria-labelledby="correction-result-heading"
                className="calculation-detail"
                role="region"
              >
                <h5 id="correction-result-heading">
                  Reading correction recorded
                </h5>
                <dl className="detail-list compact-details">
                  <div>
                    <dt>Reading</dt>
                    <dd>
                      <code>{correctionResult.reading.id}</code>
                    </dd>
                  </div>
                  <div>
                    <dt>Original value</dt>
                    <dd>{correctionResult.reading.original_value}</dd>
                  </div>
                  <div>
                    <dt>Previous effective value</dt>
                    <dd>{correctionResult.correction.previous_value}</dd>
                  </div>
                  <div>
                    <dt>Corrected effective value</dt>
                    <dd>{correctionResult.reading.effective_value}</dd>
                  </div>
                  <div>
                    <dt>Authorization</dt>
                    <dd>
                      {correctionResult.correction.authorization_reference}
                    </dd>
                  </div>
                </dl>
                {correctionResult.affected_calculations.length === 0 ? (
                  <p>
                    The server reported no affected calculations for this
                    correction.
                  </p>
                ) : (
                  <table>
                    <caption>
                      Server-authoritative affected calculations
                    </caption>
                    <thead>
                      <tr>
                        <th>Consumption period</th>
                        <th>Previous / corrected consumption</th>
                        <th>Billing effect</th>
                        <th>Issued Invoice evidence</th>
                      </tr>
                    </thead>
                    <tbody>
                      {correctionResult.affected_calculations.map((item) => (
                        <tr key={item.consumption_period_id}>
                          <td>
                            <code>{item.consumption_period_id}</code>
                          </td>
                          <td>
                            {item.previous_consumption_quantity} /{" "}
                            {item.corrected_consumption_quantity}
                          </td>
                          <td>{item.billing_effect_kind}</td>
                          <td>
                            {item.issued_line.invoice_line_id === null ? (
                              "No issued Invoice line"
                            ) : (
                              <dl className="compact-evidence">
                                <div>
                                  <dt>Invoice line</dt>
                                  <dd>{item.issued_line.invoice_line_id}</dd>
                                </div>
                                <div>
                                  <dt>Source Invoice</dt>
                                  <dd>{item.issued_line.source_invoice_id}</dd>
                                </div>
                                <div>
                                  <dt>Calculated difference</dt>
                                  <dd>
                                    {item.issued_line
                                      .calculated_difference_usd_cents === null
                                      ? "None"
                                      : `${String(item.issued_line.calculated_difference_usd_cents)} USD cents`}
                                  </dd>
                                </div>
                                <div>
                                  <dt>Adjustment</dt>
                                  <dd>
                                    {item.issued_line.invoice_adjustment_id ??
                                      "None; issued line not rewritten"}
                                  </dd>
                                </div>
                              </dl>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}
          </section>

          <section aria-labelledby="utility-rates-heading">
            <h4 id="utility-rates-heading">Utility Rate history</h4>
            {snapshot.rates.length === 0 ? (
              <p>No Utility Rates are recorded.</p>
            ) : (
              <table>
                <caption>
                  Complete immutable effective-dated Utility Rate history
                </caption>
                <thead>
                  <tr>
                    <th>Utility</th>
                    <th>Rate</th>
                    <th>Effective</th>
                    <th>Advance notice</th>
                    <th>Evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshot.rates.map((item) => (
                    <tr key={item.id}>
                      <td>{item.utility_type}</td>
                      <td>
                        {item.rate_usd_per_unit} USD per{" "}
                        {measurementUnitLabel(item.measurement_unit_code)}
                      </td>
                      <td>{item.effective_date}</td>
                      <td>{item.notice_at}</td>
                      <td>{item.notice_evidence}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <form className="form-stack" onSubmit={rate}>
              <label>
                Utility Type
                <select name="rate-type">
                  <option value="ELECTRICITY">Electricity</option>
                  <option value="WATER">Water</option>
                </select>
              </label>
              <p className="panel-help">
                Electricity is measured in kWh and water in m³.
              </p>
              <label>
                Rate in USD per unit
                <input
                  min="0"
                  name="rate-value"
                  required
                  step="0.000001"
                  type="number"
                />
              </label>
              <label>
                Effective date
                <input name="rate-effective-date" required type="date" />
              </label>
              <label>
                Advance-notice timestamp (Property local time)
                <input name="rate-notice-at" required type="datetime-local" />
              </label>
              <label>
                Advance-notice evidence
                <textarea name="rate-notice-evidence" required />
              </label>
              <label>
                Source memo
                <input name="rate-memo" />
              </label>
              <button disabled={busy} type="submit">
                Append Utility Rate
              </button>
            </form>
          </section>

          <section aria-labelledby="utility-preview-heading">
            <h4 id="utility-preview-heading">Utility calculation detail</h4>
            <form className="form-stack" onSubmit={preview}>
              <label>
                Source kind
                <select name="preview-kind">
                  <option value="CONSUMPTION_PERIOD">
                    Validated consumption period
                  </option>
                  <option value="ESTIMATION_CASE">
                    Confirmed broken-Meter case
                  </option>
                </select>
              </label>
              <label>
                Source identifier
                <input name="preview-source-id" required />
              </label>
              <label>
                Invoice generation timestamp (Property local time)
                <input
                  name="preview-generation-at"
                  required
                  type="datetime-local"
                />
              </label>
              <button disabled={busy} type="submit">
                Preview on server—do not issue
              </button>
            </form>
            {calculation !== null && (
              <div
                aria-label="Server Utility calculation"
                className={
                  calculation.status === "PENDING_FUTURE_ACTUAL_BASIS"
                    ? "pending-calculation"
                    : "calculation-detail"
                }
                role="region"
              >
                <h5>
                  {calculation.status === "PENDING_FUTURE_ACTUAL_BASIS"
                    ? "Pending future actual basis"
                    : "Ready server preview"}
                </h5>
                {calculation.status === "PENDING_FUTURE_ACTUAL_BASIS" && (
                  <p>
                    <strong>PENDING_FUTURE_ACTUAL_BASIS:</strong> zero complete
                    historical actual periods exist. The charge remains pending
                    until the first complete future actual period for this same
                    Unit and Utility Type is available. No comparable Unit or
                    arbitrary estimate is allowed.
                  </p>
                )}
                <dl className="detail-list">
                  <div>
                    <dt>Meter / failed Meter</dt>
                    <dd>
                      {calculation.meter_id ??
                        calculation.failed_meter_id ??
                        "Pending"}
                    </dd>
                  </div>
                  <div>
                    <dt>Start / end Readings</dt>
                    <dd>
                      {calculation.start_reading_id ?? "Pending"} /{" "}
                      {calculation.end_reading_id ?? "Pending"}
                    </dd>
                  </div>
                  <div>
                    <dt>Consumption period</dt>
                    <dd>
                      {calculation.period_start ?? "Pending"} to{" "}
                      {calculation.period_end ?? "Pending"}
                    </dd>
                  </div>
                  <div>
                    <dt>Consumption</dt>
                    <dd>{calculation.consumption_quantity ?? "Pending"}</dd>
                  </div>
                  <div>
                    <dt>Represented days</dt>
                    <dd>{calculation.represented_days ?? "Pending"}</dd>
                  </div>
                  <div>
                    <dt>Basis hierarchy</dt>
                    <dd>{calculation.basis_kind ?? "Pending future basis"}</dd>
                  </div>
                  <div>
                    <dt>Basis periods</dt>
                    <dd>
                      {calculation.basis_period_ids.length === 0
                        ? "None yet"
                        : calculation.basis_period_ids.join(", ")}
                    </dd>
                  </div>
                  <div>
                    <dt>Total basis consumption</dt>
                    <dd>{calculation.total_basis_consumption ?? "Pending"}</dd>
                  </div>
                  <div>
                    <dt>Total basis days</dt>
                    <dd>{calculation.total_basis_days ?? "Pending"}</dd>
                  </div>
                  <div>
                    <dt>Weighted daily average</dt>
                    <dd>{calculation.weighted_daily_average ?? "Pending"}</dd>
                  </div>
                  <div>
                    <dt>Generation date</dt>
                    <dd>{calculation.generation_date ?? "Pending"}</dd>
                  </div>
                  <div>
                    <dt>Selected Rate / effective date</dt>
                    <dd>
                      {calculation.rate_usd_per_unit ?? "Pending"} /{" "}
                      {calculation.rate_effective_date ?? "Pending"}
                    </dd>
                  </div>
                  <div>
                    <dt>Server line amount</dt>
                    <dd>
                      {calculation.amount_usd_cents === null
                        ? "Pending—no charge"
                        : `${String(calculation.amount_usd_cents)} USD cents`}
                    </dd>
                  </div>
                </dl>
                <p className="panel-help">
                  This is a non-persisted preview. The client performed no
                  consumption, basis, Rate, rounding, or amount calculation.
                </p>
              </div>
            )}
          </section>
        </div>
      )}
    </section>
  );
}
