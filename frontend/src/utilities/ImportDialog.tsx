// V1-058 R4c: import the readings of reading day from a spreadsheet (DESIGN.md "Import from a
// spreadsheet"). The server reads the file and saves nothing; the screen checks each reading
// the same way as a typed one, and "Confirm readings" saves through the batch route, where
// every reading is checked again.

import { type FormEvent, useRef, useState } from "react";

import { dayText } from "../shell/format";
import { Icon } from "../shell/icons";
import { Chip, Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import type { UnitResource } from "../unitClient";
import {
  UtilityAuthorizationError,
  UtilityClientError,
  UtilityConflictError,
  type BatchReadingInput,
  type BatchReadingResult,
  type ReadingSheet,
  type ReadingSheetProblem,
  type UtilityApi,
  type UtilityMeter,
  type UtilityType,
} from "../utilityClient";
import { utt, type UtilitiesTextKey } from "./text";
import {
  type UtilitiesData,
  amountText,
  findUnit,
  isBroken,
  muchLess,
  muchMore,
  parseReading,
  readingLines,
  usualUse,
  withReading,
} from "./utilitiesData";

// The server takes at most this many readings in one batch.
const BATCH_SIZE = 100;
// The server reads files up to 2 MB.
const MAX_FILE_BYTES = 2 * 1024 * 1024;

const TYPES: readonly UtilityType[] = ["ELECTRICITY", "WATER"];

const PROBLEM_TEXT: Record<ReadingSheetProblem, UtilitiesTextKey> = {
  FILE_TYPE: "im_e_type",
  UNREADABLE: "im_e_read",
  COLUMNS: "im_e_columns",
  TOO_MANY_ROWS: "im_e_rows",
  EMPTY: "im_e_empty_file",
};

/** One line of Check readings: one reading of the file, or a row that names no Unit. */
export interface ImportLine {
  key: string;
  unitText: string;
  unit: UnitResource | null;
  type: UtilityType | null;
  meter: UtilityMeter | null;
  previous: string | null;
  current: string;
  value: number | null;
  /** Why it cannot be confirmed; null when it is ready. */
  problem: string | null;
  /** A ready reading that is much more than usual. */
  warning: string | null;
  /** The key of this reading's save, kept for a retry. */
  idempotencyKey: string;
}

/** What the import did, shown on the readings screen after the dialog closes. */
export interface ImportResult {
  ok: boolean;
  text: string;
  notConfirmed: string[];
}

export function importLines(
  language: Language,
  data: UtilitiesData,
  sheet: ReadingSheet,
  readingDay: string,
): ImportLine[] {
  const lines: ImportLine[] = [];
  // A Unit on more than one row: nobody knows which row is right, so none is confirmed.
  const rowsOf = new Map<string, number[]>();
  for (const row of sheet.rows) {
    const found = findUnit(data.units, row.unit);
    if (found)
      rowsOf.set(found.unit_id, [
        ...(rowsOf.get(found.unit_id) ?? []),
        row.row,
      ]);
  }
  const line = (
    fields: Partial<ImportLine> & Pick<ImportLine, "key" | "unitText">,
  ): ImportLine => ({
    unit: null,
    type: null,
    meter: null,
    previous: null,
    current: "",
    value: null,
    problem: null,
    warning: null,
    idempotencyKey: crypto.randomUUID(),
    ...fields,
  });
  for (const row of sheet.rows) {
    const unit = findUnit(data.units, row.unit);
    const both = [row.electricity, row.water].filter(Boolean).join(" · ");
    if (unit === null || unit === undefined) {
      lines.push(
        line({
          key: `row-${String(row.row)}`,
          unitText: row.unit,
          current: both,
          problem:
            unit === null
              ? utt(language, "im_e_no_unit", row.row)
              : utt(language, "im_e_unit", row.unit),
        }),
      );
      continue;
    }
    const rows = rowsOf.get(unit.unit_id) ?? [];
    if (rows.length > 1) {
      lines.push(
        line({
          key: `row-${String(row.row)}`,
          unitText: unit.unit_number,
          unit,
          current: both,
          problem: utt(
            language,
            "im_e_twice",
            unit.unit_number,
            rows.join(", "),
          ),
        }),
      );
      continue;
    }
    for (const type of TYPES) {
      const typed = type === "ELECTRICITY" ? row.electricity : row.water;
      const meter = data.meters.find(
        (item) =>
          item.current &&
          item.unit_id === unit.unit_id &&
          item.utility_type === type,
      );
      const key = `${unit.unit_id}-${type}`;
      if (meter === undefined) {
        if (typed !== "")
          lines.push(
            line({
              key,
              unitText: unit.unit_number,
              unit,
              type,
              current: typed,
              problem: utt(
                language,
                "im_e_no_meter",
                utt(language, type).toLowerCase(),
              ),
            }),
          );
        continue;
      }
      const list = data.readings.get(meter.id) ?? [];
      const saved = list.find((reading) => reading.reading_date >= readingDay);
      // Previous is the last reading before this reading day, the same as the typing list.
      const earlier = list.filter(
        (reading) => reading.reading_date < readingDay,
      );
      const last = earlier[0];
      const value = parseReading(typed);
      const previous = last === undefined ? null : last.effective_value;
      let problem: string | null = null;
      let warning: string | null = null;
      if (isBroken(meter)) problem = utt(language, "im_e_broken");
      else if (saved !== undefined)
        problem = utt(
          language,
          "im_e_saved",
          amountText(saved.effective_value),
        );
      else if (typed === "") problem = utt(language, "im_e_empty");
      else if (value === null) problem = utt(language, "im_e_number");
      else if (previous !== null && value < Number(previous))
        problem = utt(language, "im_e_lower");
      else if (previous !== null) {
        const usual = usualUse(readingLines(meter, earlier));
        const use = value - Number(previous);
        if (muchMore(use, usual))
          warning = utt(language, "im_w_high", amountText(usual ?? 0));
        else if (muchLess(use, usual, unit.status === "OCCUPIED"))
          warning = utt(language, "im_w_low", amountText(usual ?? 0));
      }
      lines.push(
        line({
          key,
          unitText: unit.unit_number,
          unit,
          type,
          meter,
          previous,
          current: typed,
          value,
          problem,
          warning,
        }),
      );
    }
  }
  // Lines that need fixing come first, then by Unit and type.
  return lines.sort(
    (left, right) =>
      Number(right.problem !== null) - Number(left.problem !== null) ||
      left.unitText.localeCompare(right.unitText, undefined, {
        numeric: true,
      }) ||
      (left.type ?? "").localeCompare(right.type ?? ""),
  );
}

function lineName(language: Language, line: ImportLine): string {
  return line.type === null
    ? line.unitText
    : `${line.unitText} ${utt(language, line.type)}`;
}

function readAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const url = typeof reader.result === "string" ? reader.result : "";
      resolve(url.slice(url.indexOf(",") + 1));
    };
    reader.onerror = () => {
      reject(new Error("The file could not be read."));
    };
    reader.readAsDataURL(file);
  });
}

export function ImportDialog({
  language,
  api,
  data,
  propertyId,
  today,
  readingDay,
  onChange,
  onClose,
}: {
  language: Language;
  api: UtilityApi;
  data: UtilitiesData;
  propertyId: string;
  today: string;
  readingDay: string;
  onChange: (update: (data: UtilitiesData) => UtilitiesData) => void;
  /** With the result after Confirm; null when closed without one. */
  onClose: (result: ImportResult | null, reload: boolean) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [blankProblem, setBlankProblem] = useState(false);
  const [busy, setBusy] = useState(false);
  const [checked, setChecked] = useState<{
    fileName: string;
    lines: ImportLine[];
  } | null>(null);
  const [how, setHow] = useState<"ready" | "all">("ready");
  const [outcome, setOutcome] = useState<"refused" | "unknown" | null>(null);
  // The keys of each batch stay the same on a retry, so a batch is saved only once.
  const batchKeys = useRef(new Map<string, string>());
  const results = useRef(new Map<string, BatchReadingResult>());
  // Once a batch saved readings or the meters changed, the screen reads them again on close.
  const changed = useRef(false);

  function downloadBlank() {
    setBlankProblem(false);
    void api
      .blankSheet(
        propertyId,
        data.units.map((unit) => unit.unit_number),
      )
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `meter-readings-${today}.xlsx`;
        document.body.append(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
      })
      .catch(() => {
        setBlankProblem(true);
      });
  }

  function check(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (file === null) {
      setProblem(utt(language, "im_e_none"));
      document.getElementById("im-file")?.focus();
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      setProblem(utt(language, "im_e_big"));
      return;
    }
    setProblem(null);
    setBusy(true);
    void readAsBase64(file)
      .then((content) => api.readSheet(propertyId, file.name, content))
      .then((sheet) => {
        if (sheet.problem !== null) {
          setProblem(utt(language, PROBLEM_TEXT[sheet.problem]));
          return;
        }
        setChecked({
          fileName: file.name,
          lines: importLines(language, data, sheet, readingDay),
        });
      })
      .catch((error: unknown) => {
        setProblem(
          utt(
            language,
            error instanceof UtilityAuthorizationError
              ? "im_e_allowed"
              : error instanceof UtilityClientError
                ? "im_e_failed"
                : "im_e_read",
          ),
        );
      })
      .finally(() => {
        setBusy(false);
      });
  }

  /** Lines that need fixing, as "U101 Water: Lower than previous". */
  function badNames(lines: readonly ImportLine[]): string[] {
    return lines
      .filter((line) => line.problem !== null)
      .map((line) => `${lineName(language, line)}: ${line.problem ?? ""}`);
  }

  /** What the saves did so far: the file, how many were confirmed and every one that was not. */
  function summary(
    fileName: string,
    lines: readonly ImportLine[],
  ): ImportResult {
    const notConfirmed = badNames(lines);
    let count = 0;
    for (const line of lines) {
      if (line.problem !== null) continue;
      const answer = results.current.get(line.idempotencyKey);
      if (answer?.status === "SUCCEEDED") {
        count += 1;
        continue;
      }
      const code = answer?.error?.code;
      notConfirmed.push(
        `${lineName(language, line)}: ${utt(
          language,
          code === "CONFLICT"
            ? "im_r_conflict"
            : code === "VALIDATION_ERROR"
              ? "im_r_refused"
              : "im_r_failed",
        )}`,
      );
    }
    return {
      ok: count > 0,
      text:
        count > 0
          ? utt(language, "im_done", count, fileName)
          : utt(language, "im_none", fileName),
      notConfirmed,
    };
  }

  const savedSome = () =>
    [...results.current.values()].some(
      (answer) => answer.status === "SUCCEEDED",
    );

  function confirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (checked === null) return;
    const ready = checked.lines.filter((line) => line.problem === null);
    const bad = checked.lines.filter((line) => line.problem !== null);
    if (ready.length === 0 || (how === "all" && bad.length > 0)) {
      onClose(
        {
          ok: false,
          text: utt(language, "im_none", checked.fileName),
          notConfirmed: badNames(checked.lines),
        },
        false,
      );
      return;
    }
    if (how === "all" && ready.length > BATCH_SIZE) {
      setProblem(utt(language, "im_e_atomic_big"));
      return;
    }
    setProblem(null);
    setOutcome(null);
    setBusy(true);
    const mode = how === "all" ? "ATOMIC_ALL" : "PARTIAL";
    const batches: ImportLine[][] = [];
    for (let start = 0; start < ready.length; start += BATCH_SIZE) {
      batches.push(ready.slice(start, start + BATCH_SIZE));
    }
    void (async () => {
      for (const batch of batches) {
        // A batch saved before a lost answer is not sent again.
        if (batch.every((line) => results.current.has(line.idempotencyKey)))
          continue;
        const items: BatchReadingInput[] = batch.map((line) => ({
          idempotency_key: line.idempotencyKey,
          meter_id: line.meter?.id ?? "",
          reading: {
            expected_meter_version: line.meter?.version ?? 1,
            reading_date: today,
            reading_value: String(line.value ?? 0),
            source_kind: "MANUAL",
            source_evidence: `Imported from ${checked.fileName}`.slice(0, 500),
          },
        }));
        // The mode is part of the request, so another mode never reuses a key.
        const id = `${mode}:${batch.map((line) => line.idempotencyKey).join(",")}`;
        let key = batchKeys.current.get(id);
        if (key === undefined) {
          key = crypto.randomUUID();
          batchKeys.current.set(id, key);
        }
        const answers = await api.recordBatch(propertyId, mode, items, key);
        for (const answer of answers) {
          results.current.set(answer.idempotency_key, answer);
          const reading = answer.reading;
          if (answer.status === "SUCCEEDED" && reading !== null)
            onChange((current) => withReading(current, reading));
          else changed.current = true;
        }
      }
    })()
      .then(() => {
        onClose(summary(checked.fileName, checked.lines), changed.current);
      })
      .catch((error: unknown) => {
        if (error instanceof UtilityConflictError) {
          // An earlier batch may have saved readings; the result still names them.
          onClose(
            savedSome()
              ? summary(checked.fileName, checked.lines)
              : {
                  ok: false,
                  text: utt(language, "im_e_changed"),
                  notConfirmed: [],
                },
            true,
          );
          return;
        }
        // A server answer means it was refused; no answer means it may have been saved.
        setOutcome(
          error instanceof UtilityAuthorizationError ||
            (error instanceof UtilityClientError && error.requestId !== null)
            ? "refused"
            : "unknown",
        );
      })
      .finally(() => {
        setBusy(false);
      });
  }

  const closeWithoutResult = () => {
    // After a lost answer some readings may be saved, so the screen reads them again; readings
    // an earlier batch saved are still named.
    onClose(
      checked !== null && savedSome()
        ? summary(checked.fileName, checked.lines)
        : null,
      outcome === "unknown" || results.current.size > 0,
    );
  };

  if (checked === null) {
    return (
      <Dialog
        busy={busy}
        closeLabel={utt(language, "close")}
        onClose={closeWithoutResult}
        onSubmit={check}
        submitLabel={utt(language, busy ? "checking" : "im_check")}
        title={utt(language, "im_t")}
      >
        <p className="ui-small">
          {utt(language, "im_intro", dayText(readingDay))}{" "}
          {utt(language, "im_cols")}
        </p>
        <div className="ui-imblank">
          <button className="ui-btn" onClick={downloadBlank} type="button">
            <Icon name="download" small />
            {utt(language, "im_blank")}
          </button>
          <span className="ui-small ui-muted">
            {utt(language, "im_blank_s")}
          </span>
        </div>
        {blankProblem && (
          <p className="ui-error" role="alert">
            <Icon name="alert" small />
            <span>{utt(language, "im_blank_failed")}</span>
          </p>
        )}
        <div className="ui-field">
          <label htmlFor="im-file">{utt(language, "im_file")}</label>
          <input
            accept=".xlsx,.csv"
            aria-describedby={problem === null ? undefined : "im-file-err"}
            aria-invalid={problem !== null}
            id="im-file"
            onChange={(event) => {
              setFile(event.currentTarget.files?.[0] ?? null);
              setProblem(null);
            }}
            type="file"
          />
          {problem !== null && (
            <p className="ui-error" id="im-file-err" role="alert">
              <Icon name="alert" small />
              <span>{problem}</span>
            </p>
          )}
        </div>
      </Dialog>
    );
  }

  const ready = checked.lines.filter((line) => line.problem === null).length;
  const bad = checked.lines.length - ready;
  return (
    <Dialog
      busy={busy}
      closeLabel={utt(language, "close")}
      onClose={closeWithoutResult}
      onSubmit={confirm}
      submitLabel={utt(
        language,
        busy ? "saving" : outcome === "unknown" ? "try_again" : "im_save",
      )}
      title={utt(language, "im_t2")}
      wide
    >
      <p>
        <b>{checked.fileName}</b>:{" "}
        {utt(language, "im_sum", checked.lines.length, ready, bad)}
      </p>
      {outcome !== null && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>
            {utt(language, outcome === "unknown" ? "unknown" : "m_refused")}
          </p>
        </div>
      )}
      {problem !== null && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>{problem}</p>
        </div>
      )}
      <div
        aria-label={utt(language, "im_t2")}
        className="ui-tablewrap ui-imlist"
        role="region"
        tabIndex={0}
      >
        <table className="ui-table fit">
          <thead>
            <tr>
              <th scope="col">{utt(language, "unit")}</th>
              <th scope="col">{utt(language, "meter_kind")}</th>
              <th className="r" scope="col">
                {utt(language, "im_prev")}
              </th>
              <th className="r" scope="col">
                {utt(language, "im_cur")}
              </th>
              <th scope="col">{utt(language, "im_result")}</th>
            </tr>
          </thead>
          <tbody>
            {checked.lines.map((line) => (
              <tr
                className={line.problem === null ? undefined : "ui-imbad"}
                key={line.key}
              >
                <td>
                  <b>{line.unitText === "" ? "—" : line.unitText}</b>
                </td>
                <td>{line.type === null ? "—" : utt(language, line.type)}</td>
                <td className="r ui-num ui-muted">
                  {line.previous === null ? "—" : amountText(line.previous)}
                </td>
                <td className="r ui-num">
                  {line.value !== null
                    ? amountText(line.value)
                    : line.current === ""
                      ? "—"
                      : line.current}
                </td>
                <td className="wrap">
                  {line.problem !== null ? (
                    <span className="ui-rdmsg err">
                      <Icon name="alert" small /> {line.problem}
                    </span>
                  ) : (
                    <>
                      <Chip icon="check" tone="ok">
                        {utt(language, "im_ready")}
                      </Chip>
                      {line.warning !== null && (
                        <span className="ui-rdmsg warn">{line.warning}</span>
                      )}
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <fieldset className="ui-radios">
        <legend>{utt(language, "im_how")}</legend>
        <label className="ui-chk">
          <input
            checked={how === "ready"}
            disabled={busy || outcome === "unknown"}
            name="im-how"
            onChange={() => {
              setHow("ready");
            }}
            type="radio"
          />
          {utt(language, "im_good", ready, bad)}
        </label>
        <label className="ui-chk">
          <input
            checked={how === "all"}
            disabled={busy || outcome === "unknown"}
            name="im-how"
            onChange={() => {
              setHow("all");
            }}
            type="radio"
          />
          {utt(language, "im_all")}
        </label>
      </fieldset>
      <div className="ui-imnotes ui-small">
        <p>{utt(language, "im_note")}</p>
        <p className="ui-muted">{utt(language, "im_who")}</p>
        <p className="ui-muted">{utt(language, "im_photo")}</p>
      </div>
    </Dialog>
  );
}
