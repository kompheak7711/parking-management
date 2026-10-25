// V1-058 R3 Move-out M3: Record final readings (DESIGN.md "Move-out (round 3)", step Final
// readings). One line per Meter of the Unit on the hand-back day with its last reading; a reading
// already taken that day is used as it is. Saving records the new readings, then the final
// inputs that name them, then, for a person who may issue Invoices, the final Utility Invoice
// for the days since the last billed reading (BR-UTIL-021). Each request keeps one identity
// while its values stay the same, so Try again never saves anything twice.

import { FormEvent, useEffect, useRef, useState } from "react";

import type { LeaseResource } from "../leaseClient";
import { Problem } from "../leases/LeaseDialogs";
import { measurementUnitLabel } from "../measurementUnits";
import { dayText } from "../shell/format";
import { Icon } from "../shell/icons";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import { amountText, parseReading } from "../utilities/utilitiesData";
import {
  UtilityAuthorizationError,
  UtilityClientError,
  UtilityConflictError,
  type UtilityApi,
  type UtilityMeter,
  type UtilityPage,
  type UtilityReading,
} from "../utilityClient";
import {
  UtilityLeaseError,
  type EvidenceRecord,
  type UtilityLeaseApi,
} from "../utilityLeaseClient";
import { metersOn, readingProblem } from "./finalReadings";
import { mt, utilityRefusalText } from "./text";

// What the records keep, in English like every stored record.
const READING_EVIDENCE = "Final reading at the hand-back, recorded in the app";
const INPUTS_REASON = "Final readings at the hand-back";
const INPUTS_AUTHORITY =
  "Recorded in the app by the signed-in user (leases.move_out)";
const INPUTS_EVIDENCE = "Meter readings taken on the hand-back day";

type Outcome = "unknown" | "refused" | null;

interface Line {
  meter: UtilityMeter;
  last: UtilityReading | null;
  /** A reading already taken on the hand-back day (validated or not). */
  that: UtilityReading | null;
}

const MAX_PAGES = 10;

async function all<T>(
  read: (cursor?: string) => Promise<UtilityPage<T>>,
): Promise<T[]> {
  const found: T[] = [];
  let cursor: string | undefined;
  for (let count = 0; count < MAX_PAGES; count += 1) {
    const page = await read(cursor);
    found.push(...page.items);
    if (page.nextCursor === null) break;
    cursor = page.nextCursor;
  }
  return found;
}

/** The Meters of the Unit on the hand-back day, each with its last reading before that day. */
export async function loadLines(
  utilityApi: Pick<UtilityApi, "loadMeters" | "loadReadings">,
  unitId: string,
  day: string,
): Promise<Line[]> {
  const meters = metersOn(
    await all((cursor) => utilityApi.loadMeters(unitId, cursor)),
    day,
  );
  return Promise.all(
    meters.map(async (meter) => {
      // Newest first; read on until the reading before the hand-back day is found.
      const readings: UtilityReading[] = [];
      let cursor: string | undefined;
      for (let count = 0; count < MAX_PAGES; count += 1) {
        const page = await utilityApi.loadReadings(meter.id, cursor);
        readings.push(...page.items);
        if (
          page.nextCursor === null ||
          readings.some((reading) => reading.reading_date < day)
        )
          break;
        cursor = page.nextCursor;
      }
      return {
        meter,
        that: readings.find((reading) => reading.reading_date === day) ?? null,
        last:
          readings.find(
            (reading) => reading.validated && reading.reading_date < day,
          ) ?? null,
      };
    }),
  );
}

/** A refusal is an answer from 400 to 499; anything else may have been saved. */
function refusedStatus(status: number | null): boolean {
  return status !== null && status >= 400 && status < 500;
}

export function FinalReadingsDialog({
  language,
  lease,
  moveOutEventId,
  inputsEventId,
  supersedesEventId,
  day,
  mayIssue,
  utilityApi,
  utilityLeaseApi,
  onClose,
  onSaved,
  onConflict,
}: {
  language: Language;
  lease: LeaseResource;
  moveOutEventId: string;
  /** Final inputs already recorded for this hand-back: only the Invoice is left to issue. */
  inputsEventId: string | null;
  /** Earlier final inputs of the Lease (a hand-back that was corrected): the new ones replace them. */
  supersedesEventId: string | null;
  /** The hand-back day. */
  day: string;
  /** invoices.issue and utility.calculate: the Invoice is issued at once. */
  mayIssue: boolean;
  utilityApi: Pick<UtilityApi, "loadMeters" | "loadReadings" | "recordReading">;
  utilityLeaseApi: Pick<
    UtilityLeaseApi,
    "recordFinalInputs" | "createFinalInvoice"
  >;
  onClose: () => void;
  onSaved: (invoice: EvidenceRecord | null) => void;
  onConflict: () => void;
}) {
  const invoiceOnly = inputsEventId !== null;
  const [lines, setLines] = useState<Line[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [values, setValues] = useState<Record<string, string>>({});
  const [bad, setBad] = useState<ReadonlySet<string>>(new Set());
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>(null);
  const [refusal, setRefusal] = useState<string | null>(null);
  const [inputsSaved, setInputsSaved] = useState(invoiceOnly);
  // Kept for the life of the dialog: what was saved, and one identity per set of values.
  const saved = useRef(new Map<string, string>());
  const inputs = useRef<string | null>(inputsEventId);
  const identities = useRef(
    new Map<string, { fingerprint: string; id: string; key: string }>(),
  );
  const identity = (name: string, fingerprint: string) => {
    const kept = identities.current.get(name);
    if (kept?.fingerprint === fingerprint) return kept;
    const made = {
      fingerprint,
      id: crypto.randomUUID(),
      key: crypto.randomUUID(),
    };
    identities.current.set(name, made);
    return made;
  };

  useEffect(() => {
    // Only the Invoice is left: the readings are already named by the final inputs.
    if (invoiceOnly) return;
    let live = true;
    loadLines(utilityApi, lease.unit_id, day)
      .then((found) => {
        if (live) setLines(found);
      })
      .catch(() => {
        if (live) setFailed(true);
      });
    return () => {
      live = false;
    };
  }, [utilityApi, lease.unit_id, day, invoiceOnly]);

  const open = (lines ?? []).filter(
    (line) => line.that === null && !saved.current.has(line.meter.id),
  );
  const unchecked = (lines ?? []).filter(
    (line) => line.that !== null && !line.that.validated,
  );

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (!invoiceOnly) {
      if (lines === null || lines.length === 0) return;
      if (unchecked.length > 0) {
        setProblem(mt(language, "st3_unchecked_problem"));
        return;
      }
      const wrong = new Set(
        open
          .filter((line) =>
            readingProblem(
              values[line.meter.id] ?? "",
              line.last?.effective_value ?? null,
            ),
          )
          .map((line) => line.meter.id),
      );
      setBad(wrong);
      if (wrong.size > 0) {
        setProblem(mt(language, "st3_bad"));
        return;
      }
    }
    setProblem(null);
    setBusy(true);
    setOutcome(null);
    setRefusal(null);
    void (async () => {
      if (inputs.current === null && lines !== null) {
        for (const line of open) {
          const value = String(parseReading(values[line.meter.id] ?? ""));
          const source = {
            expected_meter_version: line.meter.version,
            reading_date: day,
            reading_value: value,
            source_kind: "MANUAL" as const,
            source_evidence: READING_EVIDENCE,
          };
          const chosen = identity(line.meter.id, JSON.stringify(source));
          const reading = await utilityApi.recordReading(
            line.meter.id,
            source,
            chosen.key,
          );
          saved.current.set(line.meter.id, reading.id);
        }
        const items = lines.map((line) => ({
          meter_id: line.meter.id,
          resolution: "READING" as const,
          reading_id: line.that?.id ?? saved.current.get(line.meter.id) ?? "",
        }));
        const source = {
          move_out_event_id: moveOutEventId,
          ...(supersedesEventId === null
            ? {}
            : { supersedes_event_id: supersedesEventId }),
          reason: INPUTS_REASON,
          authorization_reference: INPUTS_AUTHORITY,
          evidence_reference: INPUTS_EVIDENCE,
          items,
        };
        const chosen = identity("inputs", JSON.stringify(source));
        await utilityLeaseApi.recordFinalInputs(
          lease.property_id,
          lease.lease_id,
          { event_id: chosen.id, ...source },
          chosen.key,
        );
        inputs.current = chosen.id;
        setInputsSaved(true);
      }
      if (!mayIssue || inputs.current === null) return null;
      const chosen = identity("invoice", inputs.current);
      return utilityLeaseApi.createFinalInvoice(
        lease.property_id,
        lease.lease_id,
        { invoice_id: chosen.id, final_input_event_id: inputs.current },
        chosen.key,
      );
    })()
      .then(onSaved)
      .catch((error: unknown) => {
        if (
          error instanceof UtilityConflictError ||
          (error instanceof UtilityLeaseError &&
            error.status === 409 &&
            (error.code === "CONFLICT" ||
              error.code === "IDEMPOTENCY_KEY_REUSED"))
        ) {
          onConflict();
          return;
        }
        if (error instanceof UtilityLeaseError && refusedStatus(error.status)) {
          setOutcome("refused");
          setRefusal(utilityRefusalText(language, error.code));
          return;
        }
        // Only a clear refusal says "not saved"; no answer may have saved a step.
        setOutcome(
          error instanceof UtilityAuthorizationError ||
            (error instanceof UtilityClientError && refusedStatus(error.status))
            ? "refused"
            : "unknown",
        );
      })
      .finally(() => {
        setBusy(false);
      });
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={mt(language, "close")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={
        busy
          ? mt(language, "saving")
          : outcome === "unknown"
            ? mt(language, "try_again")
            : inputsSaved
              ? mt(language, "st3_issue_btn")
              : mt(language, mayIssue ? "st3_ok" : "st3_ok_only")
      }
      title={`${mt(language, invoiceOnly ? "st3_issue_btn" : "st3_btn")} · ${lease.unit_number}`}
    >
      {outcome !== null && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>
            {refusal ??
              mt(language, outcome === "unknown" ? "c_unknown" : "c_refused")}
          </p>
        </div>
      )}
      {invoiceOnly ? (
        <p>{mt(language, "st3_issue_text", dayText(day))}</p>
      ) : failed ? (
        <p className="ui-muted" role="status">
          {mt(language, "st3_meters_failed")}
        </p>
      ) : lines === null ? (
        <p className="ui-muted" role="status">
          {mt(language, "st3_loading")}
        </p>
      ) : lines.length === 0 ? (
        <p role="status">{mt(language, "st3_no_meters", dayText(day))}</p>
      ) : (
        lines.map((line) => {
          const id = `fr-${line.meter.id}`;
          const help = `${id}-help`;
          const unit = measurementUnitLabel(line.meter.measurement_unit_code);
          const taken =
            line.that?.effective_value ??
            (saved.current.has(line.meter.id)
              ? (values[line.meter.id] ?? "")
              : null);
          const name = (
            <>
              <Icon
                name={
                  line.meter.utility_type === "ELECTRICITY" ? "zap" : "drop"
                }
                small
              />{" "}
              {mt(language, `k_${line.meter.utility_type}`)} ·{" "}
              <span className="ui-num">{line.meter.serial_number}</span>
            </>
          );
          return (
            <div className="ui-field" key={line.meter.id}>
              {taken === null ? (
                <label htmlFor={id}>
                  {name}
                  <span className="req">{mt(language, "required")}</span>
                </label>
              ) : (
                <p className="ui-flabel">{name}</p>
              )}
              <p className="help" id={help}>
                {line.last === null
                  ? mt(language, "st3_no_last")
                  : mt(
                      language,
                      "st3_last",
                      `${amountText(line.last.effective_value)} ${unit}`,
                      dayText(line.last.reading_date),
                    )}
              </p>
              {taken !== null ? (
                <p className="ui-num">
                  {mt(
                    language,
                    line.that !== null && !line.that.validated
                      ? "st3_unchecked"
                      : "st3_taken",
                    `${amountText(taken)} ${unit}`,
                    dayText(day),
                  )}
                </p>
              ) : (
                <input
                  aria-describedby={help}
                  aria-invalid={bad.has(line.meter.id)}
                  aria-required="true"
                  autoComplete="off"
                  className="ui-num"
                  id={id}
                  inputMode="numeric"
                  onChange={(event) => {
                    setValues((current) => ({
                      ...current,
                      [line.meter.id]: event.target.value,
                    }));
                    setBad((current) => {
                      const next = new Set(current);
                      next.delete(line.meter.id);
                      return next;
                    });
                    setProblem(null);
                  }}
                  placeholder={
                    line.last === null
                      ? ""
                      : amountText(line.last.effective_value)
                  }
                  value={values[line.meter.id] ?? ""}
                />
              )}
            </div>
          );
        })
      )}
      <Problem message={problem} />
      <p className="ui-small ui-muted">
        {mt(language, mayIssue ? "st3_note" : "st3_note_only")}
      </p>
    </Dialog>
  );
}
