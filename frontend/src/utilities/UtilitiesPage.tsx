// V1-058 R4: the Utilities screen (DESIGN.md "Utilities layout"). "#/utilities" shows the
// Meter readings; "#/utilities/meters" the Meters. On reading day (the 24th, owner rule) and
// until the month ends, This month shows the list to type the readings; other periods show
// the saved readings as a list or a grid. A reading is saved for one meter at a time.

import "../shell/screens.css";

import { useCallback, useEffect, useRef, useState } from "react";

import type { LeaseApi } from "../leaseClient";
import { measurementUnitLabel } from "../measurementUnits";
import { dayText, todayInPhnomPenh } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { useHashDetail } from "../shell/useHashPage";
import { Chip } from "../shell/ui";
import type { Language } from "../signInText";
import type { UnitApi, UnitResource } from "../unitClient";
import {
  UtilityAuthorizationError,
  UtilityConflictError,
  UtilityClientError,
  type UtilityApi,
  type UtilityMeter,
  type UtilityReading,
  type UtilityType,
} from "../utilityClient";
import { monthText, utt, type UtilitiesTextKey } from "./text";
import {
  type EntryRow,
  type ReadingLine,
  type UtilitiesData,
  addMonths,
  allLines,
  amountText,
  entryRows,
  findUnit,
  isBroken,
  loadUtilitiesData,
  muchMore,
  parseReading,
  readingDayOf,
} from "./utilitiesData";

export interface UtilitiesPageProps {
  language: Language;
  propertyId: string;
  /** Only the page that is shown loads; a hidden page waits until it is opened. */
  active: boolean;
  utilityApi: UtilityApi;
  unitApi: Pick<UnitApi, "list">;
  leaseApi: Pick<LeaseApi, "list">;
  capabilities: ReadonlySet<string> | null;
  /** Today in Phnom Penh; tests pass a fixed day. */
  today?: string;
}

type Period = "month" | "six" | "all" | "pick";

const TYPES: readonly UtilityType[] = ["ELECTRICITY", "WATER"];

export function UtilitiesPage({
  language,
  propertyId,
  active,
  utilityApi,
  unitApi,
  leaseApi,
  capabilities,
  today: fixedToday,
}: UtilitiesPageProps) {
  const detail = useHashDetail("utilities");
  const tab = detail === "meters" ? "meters" : "read";
  const may = (capability: string) =>
    capabilities === null || capabilities.has(capability);
  const today = fixedToday ?? todayInPhnomPenh();

  const [data, setData] = useState<UtilitiesData | null>(null);
  const [failed, setFailed] = useState(false);
  const sequence = useRef(0);

  const load = useCallback(() => {
    if (propertyId === "") return;
    const operation = ++sequence.current;
    setFailed(false);
    void loadUtilitiesData({ unitApi, leaseApi, utilityApi }, propertyId)
      .then((loaded) => {
        if (operation === sequence.current) setData(loaded);
      })
      .catch(() => {
        if (operation === sequence.current) setFailed(true);
      });
  }, [leaseApi, propertyId, unitApi, utilityApi]);

  // Another Property never shows the meters of the one before.
  useEffect(() => {
    sequence.current++;
    setData(null);
  }, [propertyId]);

  // Read again each time the page is opened, so it shows what others saved.
  useEffect(() => {
    if (active) load();
  }, [active, load]);

  if (propertyId === "") {
    return (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>{utt(language, "no_property")}</p>
      </div>
    );
  }

  return (
    <>
      <div className="ui-head">
        <p>{utt(language, "sub")}</p>
      </div>
      <nav aria-label={utt(language, "sub")} className="ui-subtabs">
        <a
          aria-current={tab === "read" ? "page" : undefined}
          href={hashForPage("utilities")}
        >
          <Icon name="list" small />
          {utt(language, "tab_read")}
        </a>
        <a
          aria-current={tab === "meters" ? "page" : undefined}
          href={hashForPage("utilities", "meters")}
        >
          <Icon name="meter" small />
          {utt(language, "tab_meters")}
        </a>
      </nav>
      {failed && (
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{utt(language, "failed")}</p>
          <button className="ui-btn" onClick={load} type="button">
            {utt(language, "retry")}
          </button>
        </div>
      )}
      {data !== null && data.failedUnits.length > 0 && (
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{utt(language, "failed_units", data.failedUnits.join(", "))}</p>
          <button className="ui-btn" onClick={load} type="button">
            {utt(language, "retry")}
          </button>
        </div>
      )}
      {data === null ? (
        !failed && (
          <p className="ui-muted" role="status">
            {utt(language, "loading")}
          </p>
        )
      ) : tab === "read" ? (
        <ReadingsTab
          api={utilityApi}
          canSave={may("utility_readings.record")}
          data={data}
          language={language}
          onChange={(update) => {
            setData((previous) =>
              previous === null ? previous : update(previous),
            );
          }}
          onReload={load}
          today={today}
        />
      ) : (
        <div className="ui-notice" role="note">
          <Icon name="info" />
          <p>{utt(language, "soon_meters")}</p>
        </div>
      )}
    </>
  );
}

/** The Unit box: type "U302", "u302" or "302", or pick from the list; empty is All Units. */
function UnitBox({
  language,
  units,
  customers,
  unit,
  onUnit,
}: {
  language: Language;
  units: readonly UnitResource[];
  customers: ReadonlyMap<string, string>;
  unit: UnitResource | null;
  onUnit: (unit: UnitResource | null) => void;
}) {
  const [typed, setTyped] = useState(unit?.unit_number ?? "");
  const [bad, setBad] = useState<string | null>(null);
  const commit = (value: string) => {
    const found = findUnit(units, value);
    if (found === undefined) {
      setBad(value.trim());
      return;
    }
    setBad(null);
    setTyped(found?.unit_number ?? "");
    onUnit(found);
  };
  return (
    <form
      className="ui-combo"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        commit(typed);
      }}
    >
      <label htmlFor="ut-unit">{utt(language, "unit")}</label>
      <input
        aria-describedby={bad === null ? undefined : "ut-unit-err"}
        aria-invalid={bad === null ? undefined : true}
        autoComplete="off"
        className="ui-search"
        id="ut-unit"
        list="ut-units"
        onBlur={() => {
          commit(typed);
        }}
        onChange={(event) => {
          const value = event.currentTarget.value;
          setTyped(value);
          // Picking from the list fills the whole number: use it at once. A number that is
          // still the start of another one ("U10" of "U101") waits for Enter or leaving the box.
          const found = findUnit(units, value);
          const longer =
            found !== undefined &&
            found !== null &&
            units.some(
              (item) =>
                item !== found &&
                item.unit_number.startsWith(found.unit_number),
            );
          if (found !== undefined && found !== null && !longer) {
            setBad(null);
            onUnit(found);
          }
        }}
        placeholder={utt(language, "all_units")}
        spellCheck={false}
        value={typed}
      />
      <datalist id="ut-units">
        {units.map((item) => (
          <option key={item.unit_id} value={item.unit_number}>
            {customers.get(item.unit_id) ?? ""}
          </option>
        ))}
      </datalist>
      {(unit !== null || bad !== null) && (
        <button
          aria-label={utt(language, "all_units")}
          className="ui-btn"
          onClick={() => {
            setTyped("");
            setBad(null);
            onUnit(null);
          }}
          title={utt(language, "all_units")}
          type="button"
        >
          <Icon name="x" />
        </button>
      )}
      {bad !== null && (
        <p className="ui-error" id="ut-unit-err" role="alert">
          <Icon name="alert" small />
          {utt(language, "unit_bad", bad, units[0]?.unit_number ?? "U101")}
        </p>
      )}
    </form>
  );
}

function whoText(
  language: Language,
  data: UtilitiesData,
  unit: UnitResource,
): { text: string; muted: boolean } {
  const name = data.customers.get(unit.unit_id);
  if (name !== undefined) return { text: name, muted: false };
  const key: UtilitiesTextKey =
    unit.status === "VACANT"
      ? "vacant_note"
      : unit.status === "RESERVED"
        ? "reserved_note"
        : "other_note";
  return { text: utt(language, key), muted: true };
}

function ReadingsTab({
  language,
  api,
  data,
  today,
  canSave,
  onChange,
  onReload,
}: {
  language: Language;
  api: UtilityApi;
  data: UtilitiesData;
  today: string;
  canSave: boolean;
  onChange: (update: (data: UtilitiesData) => UtilitiesData) => void;
  onReload: () => void;
}) {
  const [unit, setUnit] = useState<UnitResource | null>(null);
  const [period, setPeriod] = useState<Period>("month");
  const [pick, setPick] = useState(today.slice(0, 7));
  const [type, setType] = useState<UtilityType>("ELECTRICITY");
  const [floor, setFloor] = useState("all");
  const [onlyMissing, setOnlyMissing] = useState(false);
  const [toast, setToast] = useState<{ ok: boolean; text: string } | null>(
    null,
  );

  const readingDay = readingDayOf(today);
  const entry = period === "month" && today >= readingDay;
  const working = (row: EntryRow) => !isBroken(row.meter);
  const counts = new Map(
    TYPES.map((kind) => {
      const rows = entryRows(data, kind, readingDay).filter(working);
      return [
        kind,
        [rows.filter((row) => row.saved !== null).length, rows.length],
      ];
    }),
  );
  const floors = [...new Set(data.units.map((item) => item.floor))].sort(
    (left, right) => left.localeCompare(right, undefined, { numeric: true }),
  );
  const months = [
    ...new Set([
      today.slice(0, 7),
      ...allLines(data, type, null).map((line) =>
        line.reading.reading_date.slice(0, 7),
      ),
    ]),
  ].sort((left, right) => right.localeCompare(left));

  return (
    <>
      <div className="ui-filters">
        <UnitBox
          customers={data.customers}
          language={language}
          onUnit={setUnit}
          unit={unit}
          units={data.units}
        />
        <div
          aria-label={utt(language, "period")}
          className="ui-seg"
          role="group"
        >
          {(
            [
              ["all", "p_all"],
              ["month", "p_month"],
              ["six", "p_six"],
              ["pick", "p_pick"],
            ] as const
          ).map(([value, key]) => (
            <button
              aria-pressed={period === value}
              key={value}
              onClick={() => {
                setPeriod(value);
              }}
              type="button"
            >
              {utt(language, key)}
            </button>
          ))}
        </div>
        {period === "pick" && (
          <>
            <label className="ui-sr" htmlFor="ut-month">
              {utt(language, "period")}
            </label>
            <select
              className="ui-sel"
              id="ut-month"
              onChange={(event) => {
                setPick(event.currentTarget.value);
              }}
              value={pick}
            >
              {months.map((month) => (
                <option key={month} value={month}>
                  {monthText(language, month)}
                </option>
              ))}
            </select>
          </>
        )}
        <div
          aria-label={utt(language, "meter_kind")}
          className="ui-seg"
          role="group"
        >
          {TYPES.map((kind) => {
            const [read, all] = counts.get(kind) ?? [0, 0];
            return (
              <button
                aria-pressed={type === kind}
                key={kind}
                onClick={() => {
                  setType(kind);
                }}
                type="button"
              >
                <Icon name={kind === "ELECTRICITY" ? "zap" : "drop"} small />{" "}
                {utt(language, kind)}
                {entry && (
                  <span className="ui-num ui-muted">
                    {" "}
                    {read}/{all}
                  </span>
                )}
              </button>
            );
          })}
        </div>
        {entry && (
          <>
            <label className="ui-sr" htmlFor="ut-floor">
              {utt(language, "floor_all")}
            </label>
            <select
              className="ui-sel"
              id="ut-floor"
              onChange={(event) => {
                setFloor(event.currentTarget.value);
              }}
              value={floor}
            >
              <option value="all">{utt(language, "floor_all")}</option>
              {floors.map((value) => (
                <option key={value} value={value}>
                  {utt(language, "floor_n", value)}
                </option>
              ))}
            </select>
            <label className="ui-chk">
              <input
                checked={onlyMissing}
                onChange={(event) => {
                  setOnlyMissing(event.currentTarget.checked);
                }}
                type="checkbox"
              />
              {utt(language, "only_missing")}
            </label>
          </>
        )}
      </div>
      {toast !== null && (
        <div className={`ui-notice ${toast.ok ? "ok" : "warn"}`} role="status">
          <Icon name={toast.ok ? "check" : "alert"} />
          <p>{toast.text}</p>
        </div>
      )}
      {entry ? (
        <EntryList
          api={api}
          canSave={canSave}
          counts={counts}
          data={data}
          floor={floor}
          language={language}
          onChange={onChange}
          onlyMissing={onlyMissing}
          onReload={onReload}
          onToast={setToast}
          readingDay={readingDay}
          today={today}
          type={type}
          unit={unit}
        />
      ) : (
        <>
          {period === "month" && (
            <div className="ui-notice" role="note">
              <Icon name="info" />
              <p>{utt(language, "before_day", dayText(readingDay))}</p>
            </div>
          )}
          <SavedReadings
            data={data}
            language={language}
            month={
              period === "month"
                ? today.slice(0, 7)
                : period === "pick"
                  ? pick
                  : null
            }
            since={period === "six" ? addMonths(today, -6) : null}
            type={type}
            unit={unit}
          />
        </>
      )}
    </>
  );
}

/** Reading day: one line for each meter, with a box for the new reading. */
function EntryList({
  language,
  api,
  data,
  type,
  unit,
  floor,
  onlyMissing,
  readingDay,
  today,
  counts,
  canSave,
  onChange,
  onReload,
  onToast,
}: {
  language: Language;
  api: UtilityApi;
  data: UtilitiesData;
  type: UtilityType;
  unit: UnitResource | null;
  floor: string;
  onlyMissing: boolean;
  readingDay: string;
  today: string;
  counts: ReadonlyMap<UtilityType, number[]>;
  canSave: boolean;
  onChange: (update: (data: UtilitiesData) => UtilitiesData) => void;
  onReload: () => void;
  onToast: (toast: { ok: boolean; text: string } | null) => void;
}) {
  // The meter just saved; the cursor moves on from it once the list shows the save.
  const [after, setAfter] = useState<string | null>(null);
  const rows = entryRows(data, type, readingDay).filter(
    (row) =>
      (unit === null || row.unit.unit_id === unit.unit_id) &&
      (floor === "all" || row.unit.floor === floor) &&
      (!onlyMissing || row.saved === null),
  );
  let read = 0;
  let all = 0;
  for (const [done, total] of counts.values()) {
    read += done ?? 0;
    all += total ?? 0;
  }
  const percent = all === 0 ? 0 : Math.round((read * 100) / all);

  // After a save the cursor goes to the next meter that still needs a reading, or to the
  // count when none is left.
  const order = entryRows(data, type, readingDay).map((row) => row.meter.id);
  useEffect(() => {
    if (after === null) return;
    const from = order.indexOf(after);
    const open = rows.filter(
      (row) => row.saved === null && !isBroken(row.meter),
    );
    const next =
      open.find((row) => order.indexOf(row.meter.id) > from) ?? open[0];
    document
      .getElementById(
        next === undefined ? "ut-progress" : `rd-${next.meter.id}`,
      )
      ?.focus();
    setAfter(null);
  }, [after, order, rows]);

  function saved(row: EntryRow, reading: UtilityReading) {
    // Applied to the newest data, so two saves that finish close together both stay, and a
    // save that ends after the list was read again is not counted twice.
    onChange((current) => {
      const list = current.readings.get(reading.meter_id) ?? [];
      if (list.some((item) => item.id === reading.id)) return current;
      const readings = new Map(current.readings);
      readings.set(reading.meter_id, [reading, ...list]);
      return {
        ...current,
        meters: current.meters.map(
          (item): UtilityMeter =>
            item.id === reading.meter_id
              ? { ...item, version: item.version + 1 }
              : item,
        ),
        readings,
      };
    });
    onToast({
      ok: true,
      text: utt(
        language,
        "done_one",
        `${row.unit.unit_number} ${row.meter.serial_number}`,
      ),
    });
    setAfter(row.meter.id);
  }

  return (
    <>
      <div className="ui-card">
        <div className="ui-progline">
          <b id="ut-progress" tabIndex={-1}>
            {utt(language, "progress", read, all)}
          </b>
          <div
            aria-label={utt(language, "progress", read, all)}
            aria-valuemax={all}
            aria-valuemin={0}
            aria-valuenow={read}
            className="ui-progress"
            role="progressbar"
          >
            <span style={{ width: `${String(percent)}%` }} />
          </div>
          <span className="ui-num ui-muted">{percent}%</span>
        </div>
        {all > 0 && read === all && data.failedUnits.length === 0 ? (
          <div className="ui-notice ok" role="status">
            <Icon name="check" />
            <p>{utt(language, "all_done")}</p>
          </div>
        ) : (
          <p className="ui-small ui-muted">
            {utt(language, "next_inv", dayText(`${readingDay.slice(0, 8)}25`))}
          </p>
        )}
        {!canSave && (
          <p className="ui-small ui-muted">
            {utt(language, "not_allowed_save")}
          </p>
        )}
      </div>
      <div className="ui-card pad0">
        {rows.length === 0 ? (
          <p className="ui-empty">
            {utt(
              language,
              data.meters.length === 0 ? "no_meters" : "none_left",
            )}
          </p>
        ) : (
          <div className="ui-tablewrap">
            <table className="ui-table ui-entry">
              <thead>
                <tr>
                  <th scope="col">{utt(language, "col_unit_meter")}</th>
                  <th className="r ui-rdlast" scope="col">
                    {utt(language, "col_last")}
                  </th>
                  <th scope="col">{utt(language, "col_new")}</th>
                  <th className="r ui-rdused" scope="col">
                    {utt(language, "col_used")}
                  </th>
                  <th className="ui-rdres" scope="col">
                    {utt(language, "col_result")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <EntryLine
                    api={api}
                    canSave={canSave}
                    data={data}
                    key={row.meter.id}
                    language={language}
                    onConflict={() => {
                      onToast({ ok: false, text: utt(language, "conflict") });
                      onReload();
                    }}
                    onStart={() => {
                      onToast(null);
                    }}
                    onSaved={(reading) => {
                      saved(row, reading);
                    }}
                    row={row}
                    today={today}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}

type LineMessage =
  | {
      kind: "err";
      key: "err_num" | "save_failed" | "refused" | "not_allowed_save";
    }
  | { kind: "lower"; last: string }
  | { kind: "warn"; use: string; usual: string };

function EntryLine({
  language,
  api,
  data,
  row,
  today,
  canSave,
  onStart,
  onSaved,
  onConflict,
}: {
  language: Language;
  api: UtilityApi;
  data: UtilitiesData;
  row: EntryRow;
  today: string;
  canSave: boolean;
  /** A new save clears the message of the one before. */
  onStart: () => void;
  onSaved: (reading: UtilityReading) => void;
  onConflict: () => void;
}) {
  const [typed, setTyped] = useState("");
  const [message, setMessage] = useState<LineMessage | null>(null);
  const [busy, setBusy] = useState(false);
  const keys = useRef<{ fingerprint: string; key: string } | null>(null);
  const label = measurementUnitLabel(row.meter.measurement_unit_code);
  const last = row.last === null ? null : Number(row.last.effective_value);
  const value = parseReading(typed);
  const who = whoText(language, data, row.unit);
  const id = row.meter.id;

  function save(force: boolean) {
    if (value === null) {
      setMessage({ kind: "err", key: "err_num" });
      return;
    }
    if (last !== null && value < last) {
      setMessage({ kind: "lower", last: amountText(last) });
      return;
    }
    if (!force && last !== null && muchMore(value - last, row.usual)) {
      setMessage({
        kind: "warn",
        use: `${amountText(value - last)} ${label}`,
        usual: `${amountText(row.usual ?? 0)} ${label}`,
      });
      return;
    }
    // The same reading sent again (after a lost answer) keeps its key, so it is saved once.
    const fingerprint = `${id}|${String(row.meter.version)}|${String(value)}|${today}`;
    if (keys.current?.fingerprint !== fingerprint)
      keys.current = { fingerprint, key: crypto.randomUUID() };
    onStart();
    setBusy(true);
    setMessage(null);
    void api
      .recordReading(
        id,
        {
          expected_meter_version: row.meter.version,
          reading_date: today,
          reading_value: String(value),
          source_kind: "MANUAL",
          source_evidence: "Typed on the Meter readings screen",
        },
        keys.current.key,
      )
      .then((reading) => {
        setTyped("");
        onSaved(reading);
      })
      .catch((error: unknown) => {
        if (error instanceof UtilityConflictError) {
          onConflict();
          return;
        }
        setMessage({
          kind: "err",
          key:
            error instanceof UtilityAuthorizationError
              ? "not_allowed_save"
              : error instanceof UtilityClientError && error.requestId !== null
                ? "refused"
                : "save_failed",
        });
      })
      .finally(() => {
        setBusy(false);
      });
  }

  const unitCell = (
    <td>
      <b>{row.unit.unit_number}</b>{" "}
      <span className="ui-small ui-muted ui-num ui-nowrap">
        {row.meter.serial_number}
      </span>
      <span className={`ui-sub2${who.muted ? " ui-muted" : ""}`}>
        {who.text}
      </span>
      {/* On a phone the Last reading column folds in here. */}
      <span className="ui-sub2 ui-num ui-rdlast-inline">
        {utt(language, "col_last")}:{" "}
        {row.last === null
          ? utt(language, "no_last")
          : `${amountText(row.last.effective_value)} · ${dayText(row.last.reading_date)}`}
      </span>
    </td>
  );
  const lastCell = (
    <td className="r ui-num ui-rdlast">
      {row.last === null ? (
        <span className="ui-muted">{utt(language, "no_last")}</span>
      ) : (
        <>
          {amountText(row.last.effective_value)}
          <span className="ui-sub2">{dayText(row.last.reading_date)}</span>
        </>
      )}
    </td>
  );

  if (row.saved !== null) {
    const use = last === null ? null : Number(row.saved.effective_value) - last;
    return (
      <tr>
        {unitCell}
        {lastCell}
        <td>
          <b className="ui-num">{amountText(row.saved.effective_value)}</b>
        </td>
        <td className="r ui-num ui-rdused">
          {use === null ? "—" : `${amountText(use)} ${label}`}
        </td>
        <td className="ui-rdres">
          <Chip icon="check" tone="ok">
            {row.saved.reading_date === today
              ? utt(language, "saved")
              : utt(language, "saved_on", dayText(row.saved.reading_date))}
          </Chip>
        </td>
      </tr>
    );
  }
  if (isBroken(row.meter)) {
    return (
      <tr>
        {unitCell}
        {lastCell}
        <td>
          <span className="ui-muted">—</span>
        </td>
        <td className="r ui-rdused">
          <span className="ui-muted">—</span>
        </td>
        <td className="wrap ui-rdres">
          <div className="ui-rdcell">
            <Chip icon="alert" tone="err">
              {utt(language, "broken")}
            </Chip>
            <span className="ui-small">{utt(language, "rd_broken")}</span>
            <a className="ui-btn" href={hashForPage("utilities", "meters")}>
              <Icon name="swap" small />
              {utt(language, "replace")}
            </a>
          </div>
        </td>
      </tr>
    );
  }
  const messageText =
    message === null
      ? null
      : message.kind === "lower"
        ? utt(language, "err_lower", message.last)
        : message.kind === "warn"
          ? utt(language, "warn_high", message.use, message.usual)
          : utt(language, message.key);
  return (
    <tr>
      {unitCell}
      {lastCell}
      <td>
        <input
          aria-describedby={message === null ? undefined : `rm-${id}`}
          aria-invalid={
            message === null || message.kind === "warn" ? undefined : true
          }
          aria-label={`${utt(language, "col_new")} ${row.unit.unit_number} ${row.meter.serial_number}`}
          autoComplete="off"
          className="ui-rdinput"
          disabled={!canSave || busy}
          id={`rd-${id}`}
          inputMode="numeric"
          onChange={(event) => {
            setTyped(event.currentTarget.value);
            setMessage(null);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              save(false);
            }
          }}
          value={typed}
        />
      </td>
      <td className="r ui-num ui-rdused">
        {value !== null && last !== null && value >= last ? (
          `${amountText(value - last)} ${label}`
        ) : (
          <span className="ui-muted">—</span>
        )}
      </td>
      <td className="wrap ui-rdres">
        <div className="ui-rdcell">
          {messageText !== null ? (
            <p
              className={`ui-rdmsg ${message?.kind === "warn" ? "warn" : "err"}`}
              id={`rm-${id}`}
              role={message?.kind === "warn" ? "status" : "alert"}
            >
              {messageText}
            </p>
          ) : (
            <span className="ui-small ui-muted">
              {utt(language, typed === "" ? "not_read" : "typed")}
            </span>
          )}
          {canSave && (
            <button
              className="ui-btn"
              aria-label={`${utt(language, "save")} ${row.unit.unit_number} ${row.meter.serial_number}`}
              disabled={busy}
              onClick={() => {
                save(false);
              }}
              type="button"
            >
              {utt(language, "save")}
            </button>
          )}
          {canSave && message?.kind === "warn" && (
            <button
              className="ui-btn"
              aria-label={`${utt(language, "save_anyway")} ${row.unit.unit_number} ${row.meter.serial_number}`}
              disabled={busy}
              onClick={() => {
                save(true);
              }}
              type="button"
            >
              {utt(language, "save_anyway")}
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}

/** Saved readings: one month as a list, several months as a grid, or one Unit over time. */
function SavedReadings({
  language,
  data,
  type,
  unit,
  month,
  since,
}: {
  language: Language;
  data: UtilitiesData;
  type: UtilityType;
  unit: UnitResource | null;
  /** "2026-10": that month only. */
  month: string | null;
  /** "2026-04-25": from that day on; null with no month means all. */
  since: string | null;
}) {
  const label = measurementUnitLabel(type === "ELECTRICITY" ? "KWH" : "M3");
  const units = new Map(data.units.map((item) => [item.unit_id, item]));
  const lines = allLines(data, type, unit?.unit_id ?? null).filter(
    (line) =>
      (month === null || line.reading.reading_date.startsWith(month)) &&
      (since === null || line.reading.reading_date >= since),
  );
  const useText = (line: ReadingLine) =>
    line.use === null
      ? "—"
      : `${amountText(line.use)} ${measurementUnitLabel(line.meter.measurement_unit_code)}`;
  const noteOf = (line: ReadingLine) => {
    const notes: string[] = [];
    if (line.use === null) notes.push(utt(language, "rd_n_new"));
    if (line.reading.corrections.length > 0)
      notes.push(
        utt(language, "rd_corrected", amountText(line.reading.original_value)),
      );
    return notes.join(" ");
  };

  if (lines.length === 0) {
    return (
      <div className="ui-card">
        <p className="ui-empty">
          {month === null
            ? utt(language, "rd_none")
            : utt(language, "rd_none_m", monthText(language, month))}
        </p>
      </div>
    );
  }

  if (unit !== null || month !== null) {
    const sorted =
      unit !== null
        ? lines
        : [...lines].sort(
            (left, right) =>
              (units.get(left.meter.unit_id)?.unit_number ?? "").localeCompare(
                units.get(right.meter.unit_id)?.unit_number ?? "",
                undefined,
                { numeric: true },
              ) ||
              left.reading.reading_date.localeCompare(
                right.reading.reading_date,
              ),
          );
    return (
      <div className="ui-card pad0">
        <div className="ui-tablewrap">
          <table className="ui-table">
            <thead>
              <tr>
                {unit !== null ? (
                  <>
                    <th scope="col">{utt(language, "rd_day")}</th>
                    <th scope="col">{utt(language, "meter_kind")}</th>
                  </>
                ) : (
                  <>
                    <th scope="col">{utt(language, "col_unit_meter")}</th>
                    <th scope="col">{utt(language, "rd_day")}</th>
                  </>
                )}
                <th className="r" scope="col">
                  {utt(language, "rd_reading")}
                </th>
                <th className="r" scope="col">
                  {utt(language, "col_used")}
                </th>
                <th scope="col">{utt(language, "rd_note")}</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((line) => {
                const owner = units.get(line.meter.unit_id);
                const who =
                  owner === undefined ? null : whoText(language, data, owner);
                return (
                  <tr key={line.reading.id}>
                    {unit !== null ? (
                      <>
                        <td className="ui-num">
                          {dayText(line.reading.reading_date)}
                        </td>
                        <td className="ui-num">{line.meter.serial_number}</td>
                      </>
                    ) : (
                      <>
                        <td>
                          <b>{owner?.unit_number ?? "—"}</b>{" "}
                          <span className="ui-small ui-muted ui-num ui-nowrap">
                            {line.meter.serial_number}
                          </span>
                          {who !== null && (
                            <span
                              className={`ui-sub2${who.muted ? " ui-muted" : ""}`}
                            >
                              {who.text}
                            </span>
                          )}
                        </td>
                        <td className="ui-num">
                          {dayText(line.reading.reading_date)}
                        </td>
                      </>
                    )}
                    <td className="r ui-num">
                      {amountText(line.reading.effective_value)}
                    </td>
                    <td className="r ui-num">{useText(line)}</td>
                    <td className="wrap ui-small">{noteOf(line)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  // Several months: Units down the side, one column for each reading month, newest first.
  // Readings may be typed from the 24th to the month end, so a month's column holds each
  // Unit's newest reading of that month, whatever its day.
  const days = [
    ...new Set(lines.map((line) => line.reading.reading_date.slice(0, 7))),
  ].sort((left, right) => right.localeCompare(left));
  const at = new Map<string, ReadingLine>();
  for (const line of lines) {
    const key = `${line.meter.unit_id}|${line.reading.reading_date.slice(0, 7)}`;
    const kept = at.get(key);
    // Lines come newest first; on the same day the current meter wins over the old one.
    if (
      kept === undefined ||
      (kept.reading.reading_date === line.reading.reading_date &&
        line.meter.current &&
        !kept.meter.current)
    )
      at.set(key, line);
  }
  const rows = data.units.filter((item) =>
    lines.some((line) => line.meter.unit_id === item.unit_id),
  );
  return (
    <div className="ui-card pad0">
      <div className="ui-tablewrap">
        <table className="ui-table ui-grid">
          <thead>
            <tr>
              <th scope="col">{utt(language, "unit")}</th>
              {days.map((day) => (
                <th className="r ui-num" key={day} scope="col">
                  {monthText(language, day)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((item) => {
              const who = whoText(language, data, item);
              return (
                <tr key={item.unit_id}>
                  <th scope="row">
                    <b>{item.unit_number}</b>
                    <span className={`ui-sub2${who.muted ? " ui-muted" : ""}`}>
                      {who.muted ? "—" : who.text}
                    </span>
                  </th>
                  {days.map((day) => {
                    const line = at.get(`${item.unit_id}|${day}`);
                    return (
                      <td className="r" key={day}>
                        {line === undefined ? (
                          <span className="ui-muted">—</span>
                        ) : (
                          <>
                            <b className="ui-num">
                              {amountText(line.reading.effective_value)}
                            </b>
                            {line.use !== null && (
                              <span className="ui-sub2 ui-num">
                                {amountText(line.use)} {label}
                              </span>
                            )}
                          </>
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="ui-tfoot">{utt(language, "rd_grid_note", label)}</p>
    </div>
  );
}
