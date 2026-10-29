// V1-058 R4b: the Meters tab of Utilities (DESIGN.md "Utilities layout", "Meter dialogs").
// "#/utilities/meters" lists every meter, current and replaced; "#/utilities/meter:<id>"
// opens one meter with its readings. Add meter, Report broken (V1-060 B6, DL-104) and Replace
// meter need utility_meters.manage (Owner and Manager by default) and are hidden from others.
// A meter is never deleted.

import { useRef, useState, type FormEvent, type ReactNode } from "react";

import {
  MEASUREMENT_UNIT_CODES,
  measurementUnitLabel,
} from "../measurementUnits";
import { DateInput, isDay } from "../shell/DateInput";
import { dayText } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { Chip, CountCard, Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import type { UnitResource } from "../unitClient";
import {
  MeterSerialNumberInUseError,
  UtilityAuthorizationError,
  UtilityClientError,
  UtilityConflictError,
  type MeterFailureReportInput,
  type MeterInstallInput,
  type MeterReplaceInput,
  type UtilityApi,
  type UtilityMeter,
  type UtilityReading,
  type UtilityType,
} from "../utilityClient";
import { utt } from "./text";
import { UnitBox, whoText } from "./UnitBox";
import {
  type MeterState,
  type UtilitiesData,
  addMonths,
  amountText,
  meterState,
  parseReading,
  readingDayOf,
  readingLines,
} from "./utilitiesData";

type Card = "ELECTRICITY" | "WATER" | "broken" | "all";
type StatusFilter = "all" | MeterState;

const RANK: Record<MeterState, number> = { broken: 0, working: 1, replaced: 2 };

/** The next reading day on or after today: meters broken now must be replaced by then. */
function nextReadingDay(today: string): string {
  const day = readingDayOf(today);
  return today <= day ? day : addMonths(day, 1);
}

function StateChip({
  language,
  meter,
}: {
  language: Language;
  meter: UtilityMeter;
}) {
  const state = meterState(meter);
  if (state === "broken")
    return (
      <Chip icon="alert" tone="err">
        {utt(language, "mt_broken_since", dayText(meter.failure_date))}
      </Chip>
    );
  if (state === "replaced")
    return (
      <Chip tone="neutral">
        {utt(
          language,
          "mt_replaced_on",
          dayText(meter.replacement.replacement_date ?? meter.deactivated_date),
        )}
      </Chip>
    );
  return (
    <Chip icon="check" tone="ok">
      {utt(language, "mt_st_ok")}
    </Chip>
  );
}

function ManagerButton({
  language,
  icon,
  label,
  onClick,
  primary = false,
}: {
  language: Language;
  icon: "plus" | "swap" | "alert";
  label: string;
  onClick: () => void;
  primary?: boolean;
}) {
  return (
    <button
      className={`ui-btn${primary ? " primary" : ""}`}
      onClick={onClick}
      type="button"
    >
      <Icon name={icon} />
      {label}
      <span className="ui-badge">{utt(language, "manager")}</span>
    </button>
  );
}

export function MetersTab({
  language,
  api,
  data,
  today,
  canManage,
  onReload,
}: {
  language: Language;
  api: UtilityApi;
  data: UtilitiesData;
  today: string;
  canManage: boolean;
  onReload: () => void;
}) {
  const [unit, setUnit] = useState<UnitResource | null>(null);
  const [card, setCard] = useState<Card>("all");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [adding, setAdding] = useState(false);
  const [toast, setToast] = useState<{ ok: boolean; text: string } | null>(
    null,
  );
  const units = new Map(data.units.map((item) => [item.unit_id, item]));
  const inUse = data.meters.filter((meter) => meter.current);
  const broken = (type?: UtilityType) =>
    inUse.filter(
      (meter) =>
        meterState(meter) === "broken" &&
        (type === undefined || meter.utility_type === type),
    ).length;
  const passes = (meter: UtilityMeter) =>
    (card === "all" ||
      (card === "broken"
        ? meterState(meter) === "broken"
        : meter.current && meter.utility_type === card)) &&
    (status === "all" || meterState(meter) === status) &&
    (unit === null || meter.unit_id === unit.unit_id);
  const unitNumber = (meter: UtilityMeter) =>
    units.get(meter.unit_id)?.unit_number ?? "";
  const rows = data.meters.filter(passes).sort(
    (left, right) =>
      RANK[meterState(left)] - RANK[meterState(right)] ||
      unitNumber(left).localeCompare(unitNumber(right), undefined, {
        numeric: true,
      }) ||
      left.utility_type.localeCompare(right.utility_type),
  );
  const cardName = (value: Card) =>
    value === "ELECTRICITY"
      ? utt(language, "mt_c_el")
      : value === "WATER"
        ? utt(language, "mt_c_wa")
        : utt(language, "mt_c_broken");

  return (
    <>
      {canManage && (
        <div className="ui-actions">
          <ManagerButton
            icon="plus"
            label={utt(language, "mt_add")}
            language={language}
            onClick={() => {
              setToast(null);
              setAdding(true);
            }}
            primary
          />
        </div>
      )}
      <div className="ui-filters">
        <UnitBox
          customers={data.customers}
          language={language}
          onUnit={setUnit}
          unit={unit}
          units={data.units}
        />
        <label className="ui-sr" htmlFor="mt-status">
          {utt(language, "col_status")}
        </label>
        <select
          className="ui-sel"
          id="mt-status"
          onChange={(event) => {
            setStatus(event.currentTarget.value as StatusFilter);
          }}
          value={status}
        >
          <option value="all">{utt(language, "mt_f_all")}</option>
          <option value="working">{utt(language, "mt_f_working")}</option>
          <option value="broken">{utt(language, "mt_f_broken")}</option>
          <option value="replaced">{utt(language, "mt_f_replaced")}</option>
        </select>
      </div>
      {toast !== null && (
        <div className={`ui-notice ${toast.ok ? "ok" : "warn"}`} role="status">
          <Icon name={toast.ok ? "check" : "alert"} />
          <p>{toast.text}</p>
        </div>
      )}
      <div className="ui-kpis">
        {(["ELECTRICITY", "WATER"] as const).map((type) => (
          <CountCard
            icon={type === "ELECTRICITY" ? "zap" : "drop"}
            key={type}
            label={cardName(type)}
            note={`${utt(language, "mt_c_inuse")} · ${
              broken(type) > 0
                ? utt(language, "mt_c_nbroken", broken(type))
                : utt(language, "mt_c_allok")
            }`}
            onPress={() => {
              setCard(card === type ? "all" : type);
            }}
            pressed={card === type}
            tone="info"
            value={inUse.filter((meter) => meter.utility_type === type).length}
          />
        ))}
        <CountCard
          icon="alert"
          label={cardName("broken")}
          note={
            broken() > 0
              ? utt(language, "mt_c_before", dayText(nextReadingDay(today)))
              : utt(language, "mt_c_none")
          }
          onPress={() => {
            setCard(card === "broken" ? "all" : "broken");
          }}
          pressed={card === "broken"}
          tone="err"
          value={broken()}
        />
      </div>
      <div className="ui-card pad0">
        {card !== "all" && (
          <div className="ui-listbar">
            {utt(language, "ic_showing", cardName(card))}
            <button
              className="ui-btn link"
              onClick={() => {
                setCard("all");
              }}
              type="button"
            >
              {utt(language, "pc_clear")}
            </button>
          </div>
        )}
        {rows.length === 0 ? (
          <p className="ui-empty">{utt(language, "mt_none")}</p>
        ) : (
          <>
            <div className="ui-tablewrap">
              <table className="ui-table ui-meters">
                <thead>
                  <tr>
                    <th scope="col">{utt(language, "meter_kind")}</th>
                    <th className="ui-wide" scope="col">
                      {utt(language, "col_type")}
                    </th>
                    <th className="ui-wide" scope="col">
                      {utt(language, "mt_installed")}
                    </th>
                    <th className="r" scope="col">
                      {utt(language, "mt_last")}
                    </th>
                    <th scope="col">{utt(language, "col_status")}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((meter) => {
                    const owner = units.get(meter.unit_id);
                    const last = data.readings.get(meter.id)?.[0];
                    const who =
                      owner === undefined
                        ? null
                        : whoText(language, data, owner);
                    return (
                      <tr key={meter.id}>
                        <td>
                          <a
                            className="ui-no ui-num"
                            href={hashForPage("utilities", `meter:${meter.id}`)}
                          >
                            {meter.serial_number}
                          </a>
                          <span className="ui-sub2">
                            {owner?.unit_number ?? "—"}
                            {who !== null && !who.muted && ` · ${who.text}`}
                          </span>
                        </td>
                        <td className="ui-wide">
                          <Icon
                            name={
                              meter.utility_type === "ELECTRICITY"
                                ? "zap"
                                : "drop"
                            }
                            small
                          />{" "}
                          {utt(language, meter.utility_type)}
                        </td>
                        <td className="ui-num ui-wide">
                          {dayText(meter.installed_date)}
                        </td>
                        <td className="r">
                          {last === undefined ? (
                            "—"
                          ) : (
                            <>
                              <span className="ui-num">
                                {amountText(last.effective_value)}{" "}
                                {measurementUnitLabel(
                                  meter.measurement_unit_code,
                                )}
                              </span>
                              <span className="ui-sub2 ui-num">
                                {dayText(last.reading_date)}
                              </span>
                            </>
                          )}
                        </td>
                        <td>
                          <StateChip language={language} meter={meter} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="ui-tfoot">
              {utt(language, "mt_showing", rows.length)}
            </p>
          </>
        )}
      </div>
      <div className="ui-notice" role="note">
        <Icon name="info" />
        <p>{utt(language, "mt_keep")}</p>
      </div>
      {adding && (
        <AddMeterDialog
          api={api}
          data={data}
          language={language}
          onClose={(unsure) => {
            setAdding(false);
            // After a lost answer the meter may have been added: read the list again.
            if (unsure) onReload();
          }}
          onConflict={() => {
            setAdding(false);
            setToast({ ok: false, text: utt(language, "m_conflict") });
            onReload();
          }}
          onSaved={(text) => {
            setAdding(false);
            setToast({ ok: true, text });
            onReload();
          }}
          today={today}
        />
      )}
    </>
  );
}

/** One meter: its facts, its replacement chain and every reading, newest first. */
export function MeterDetail({
  language,
  api,
  data,
  meterId,
  today,
  canManage,
  loading,
  onReload,
}: {
  language: Language;
  api: UtilityApi;
  data: UtilitiesData;
  meterId: string;
  /** The list is being read again, such as just after a replace. */
  loading: boolean;
  today: string;
  canManage: boolean;
  onReload: () => void;
}) {
  const [replacing, setReplacing] = useState(false);
  const [reporting, setReporting] = useState(false);
  const [toast, setToast] = useState<{ ok: boolean; text: string } | null>(
    null,
  );
  const back = (
    <a className="ui-crumb" href={hashForPage("utilities", "meters")}>
      <Icon name="back" small />
      {utt(language, "back")}
    </a>
  );
  const meter = data.meters.find((item) => item.id === meterId);
  if (meter === undefined) {
    // A meter just added or put in by a replace shows once the list is read again.
    if (loading)
      return (
        <>
          {back}
          <p className="ui-muted" role="status">
            {utt(language, "loading")}
          </p>
        </>
      );
    return (
      <>
        {back}
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{utt(language, "mt_not_found")}</p>
        </div>
      </>
    );
  }
  const owner = data.units.find((item) => item.unit_id === meter.unit_id);
  const who = owner === undefined ? null : whoText(language, data, owner);
  const readings = data.readings.get(meter.id) ?? [];
  const lines = readingLines(meter, readings);
  const label = measurementUnitLabel(meter.measurement_unit_code);
  const serialOf = (id: string | null) =>
    data.meters.find((item) => item.id === id)?.serial_number ?? "—";
  const meterLink = (id: string | null) =>
    id === null ? (
      "—"
    ) : (
      <a
        className="ui-no ui-num"
        href={hashForPage("utilities", `meter:${id}`)}
      >
        {serialOf(id)}
      </a>
    );
  const before = data.meters.find(
    (item) => item.replacement.replacement_meter_id === meter.id,
  );
  const facts: [string, ReactNode][] = [
    [
      utt(language, "unit"),
      `${owner?.unit_number ?? "—"}${who !== null && !who.muted ? ` · ${who.text}` : ""}`,
    ],
    [utt(language, "col_type"), utt(language, meter.utility_type)],
    [utt(language, "mt_serial"), meter.serial_number],
    [utt(language, "mt_installed"), dayText(meter.installed_date)],
  ];
  if (meter.failure_date !== null)
    facts.push([utt(language, "mt_failed"), dayText(meter.failure_date)]);
  const report = meter.failure_report ?? null;
  if (report !== null) facts.push([utt(language, "mt_wrong"), report.reason]);
  if (meter.replacement.replacement_meter_id !== null)
    facts.push([
      utt(language, "mt_new_meter"),
      <>
        {meterLink(meter.replacement.replacement_meter_id)} ·{" "}
        {dayText(meter.replacement.replacement_date)}
      </>,
    ]);
  if (before !== undefined)
    facts.push([
      utt(language, "mt_old_meter"),
      <>
        {meterLink(before.id)} · {dayText(before.replacement.replacement_date)}
      </>,
    ]);

  return (
    <>
      {back}
      <div className="ui-hrow">
        <h2 className="ui-num">{meter.serial_number}</h2>
        <StateChip language={language} meter={meter} />
        {canManage && meter.current && readings.length > 0 && (
          <div className="ui-actions">
            {meterState(meter) === "working" && (
              <ManagerButton
                icon="alert"
                label={utt(language, "mt_report")}
                language={language}
                onClick={() => {
                  setToast(null);
                  setReporting(true);
                }}
              />
            )}
            <ManagerButton
              icon="swap"
              label={utt(language, "replace")}
              language={language}
              onClick={() => {
                setToast(null);
                setReplacing(true);
              }}
              primary={meterState(meter) === "broken"}
            />
          </div>
        )}
      </div>
      {toast !== null && (
        <div className={`ui-notice ${toast.ok ? "ok" : "warn"}`} role="status">
          <Icon name={toast.ok ? "check" : "alert"} />
          <p>{toast.text}</p>
        </div>
      )}
      {meterState(meter) === "broken" && (
        <div className="ui-notice err" role="note">
          <Icon name="alert" />
          <p>{utt(language, "rd_broken")}</p>
        </div>
      )}
      {canManage && meter.current && readings.length === 0 && (
        <div className="ui-notice warn" role="note">
          <Icon name="info" />
          <p>{utt(language, "mt_no_reading")}</p>
        </div>
      )}
      <div className="ui-stack">
        <section className="ui-card" aria-labelledby="mt-facts">
          <h2 id="mt-facts">{utt(language, "mt_facts")}</h2>
          <dl className="ui-kv">
            {facts.map(([term, value], index) => (
              <div key={index} style={{ display: "contents" }}>
                <dt>{term}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
        </section>
        <section className="ui-card pad0" aria-labelledby="mt-reads">
          <div className="ui-chead pad">
            <h2 id="mt-reads">{utt(language, "mt_reads")}</h2>
          </div>
          {lines.length === 0 ? (
            <p className="ui-empty">{utt(language, "rd_none")}</p>
          ) : (
            <div className="ui-tablewrap">
              <table className="ui-table fit">
                <thead>
                  <tr>
                    <th scope="col">{utt(language, "rd_day")}</th>
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
                  {lines.map((line) => (
                    <tr key={line.reading.id}>
                      <td className="ui-num">
                        {dayText(line.reading.reading_date)}
                      </td>
                      <td className="r ui-num">
                        {amountText(line.reading.effective_value)}
                      </td>
                      <td className="r ui-num">
                        {line.use === null
                          ? "—"
                          : `${amountText(line.use)} ${label}`}
                      </td>
                      <td className="wrap ui-small">
                        {line.use === null && utt(language, "rd_n_new")}
                        {line.reading.corrections.length > 0 &&
                          ` ${utt(language, "rd_corrected", amountText(line.reading.original_value))}`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
      {reporting && (
        <ReportBrokenDialog
          api={api}
          language={language}
          meter={meter}
          onClose={(unsure) => {
            setReporting(false);
            if (unsure) onReload();
          }}
          onConflict={() => {
            setReporting(false);
            setToast({ ok: false, text: utt(language, "m_conflict") });
            onReload();
          }}
          onSaved={(reported) => {
            setReporting(false);
            setToast({
              ok: true,
              text: utt(
                language,
                "mt_report_done",
                reported.serial_number,
                dayText(reported.failure_date),
              ),
            });
            onReload();
          }}
          readings={readings}
          today={today}
        />
      )}
      {replacing && (
        <ReplaceMeterDialog
          api={api}
          data={data}
          language={language}
          meter={meter}
          onClose={(unsure) => {
            setReplacing(false);
            if (unsure) onReload();
          }}
          onConflict={() => {
            setReplacing(false);
            setToast({ ok: false, text: utt(language, "m_conflict") });
            onReload();
          }}
          onSaved={(replacement) => {
            setReplacing(false);
            onReload();
            // The new meter's page shows the result.
            window.location.hash = hashForPage(
              "utilities",
              `meter:${replacement.id}`,
            );
          }}
          today={today}
        />
      )}
    </>
  );
}

type Outcome = "unknown" | "refused" | null;

/** Sends a meter command once per set of values; the same values keep their key. */
function useMeterSend() {
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>(null);
  const kept = useRef<{ fingerprint: string; key: string } | null>(null);
  function keyFor(fingerprint: string): string {
    if (kept.current?.fingerprint !== fingerprint)
      kept.current = { fingerprint, key: crypto.randomUUID() };
    return kept.current.key;
  }
  function send<T>(
    fingerprint: string,
    request: (key: string) => Promise<T>,
    handlers: {
      onSaved: (value: T) => void;
      onConflict: () => void;
      /** Only a command that sends a serial; otherwise it is a conflict. */
      onSerialUsed?: () => void;
    },
  ) {
    setBusy(true);
    setOutcome(null);
    void request(keyFor(fingerprint))
      .then(handlers.onSaved)
      .catch((error: unknown) => {
        if (
          error instanceof MeterSerialNumberInUseError &&
          handlers.onSerialUsed !== undefined
        ) {
          handlers.onSerialUsed();
          return;
        }
        if (error instanceof UtilityConflictError) {
          handlers.onConflict();
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
  return { busy, outcome, send };
}

function FieldError({ id, text }: { id: string; text: string | undefined }) {
  if (text === undefined) return null;
  return (
    <p className="ui-error" id={`${id}-err`}>
      <Icon name="alert" small />
      <span>{text}</span>
    </p>
  );
}

/** After a refused submit the cursor goes to the first field with an error. */
function focusFirstError(
  fields: readonly (readonly [string, string])[],
  problems: Record<string, string>,
) {
  const first = fields.find(([key]) => problems[key] !== undefined);
  if (first === undefined) return;
  requestAnimationFrame(() => {
    document.getElementById(first[1])?.focus();
  });
}

function OutcomeLine({
  language,
  outcome,
}: {
  language: Language;
  outcome: Outcome;
}) {
  if (outcome === null) return null;
  return (
    <div className="ui-notice warn" role="alert">
      <Icon name="alert" />
      <p>{utt(language, outcome === "unknown" ? "unknown" : "m_refused")}</p>
    </div>
  );
}

export function AddMeterDialog({
  language,
  api,
  data,
  today,
  preset,
  onClose,
  onSaved,
  onConflict,
}: {
  language: Language;
  api: Pick<UtilityApi, "installMeter">;
  data: Pick<UtilitiesData, "units" | "meters">;
  today: string;
  /** V1-061: the Unit page opens it for its own Unit and the kind it lacks. */
  preset?: { unitId: string; type: UtilityType };
  /** True when the last try got no answer, so it may have been saved. */
  onClose: (unsure: boolean) => void;
  onSaved: (message: string) => void;
  onConflict: () => void;
}) {
  const [unitId, setUnitId] = useState(preset?.unitId ?? "");
  const [type, setType] = useState<UtilityType>(preset?.type ?? "ELECTRICITY");
  const [serial, setSerial] = useState("");
  const [installed, setInstalled] = useState(today);
  const [first, setFirst] = useState("0");
  const [problems, setProblems] = useState<Record<string, string>>({});
  const { busy, outcome, send } = useMeterSend();
  const unit = data.units.find((item) => item.unit_id === unitId);
  const code = `${type === "ELECTRICITY" ? "EL" : "WA"}-${unit?.unit_number ?? data.units[0]?.unit_number ?? "U101"}`;
  // V1-060 B6 (owner, 28/10/2026): only Units without a current meter of this kind are offered;
  // a broken meter is changed with Replace meter on its page.
  const hasMeter = (id: string, kind: UtilityType) =>
    data.meters.some(
      (meter) =>
        meter.current && meter.unit_id === id && meter.utility_type === kind,
    );
  const free = data.units.filter((item) => !hasMeter(item.unit_id, type));

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found: Record<string, string> = {};
    const working = data.meters.find(
      (meter) =>
        meter.current &&
        meter.unit_id === unitId &&
        meter.utility_type === type,
    );
    if (unit === undefined) found.unit = utt(language, "mt_e_unit");
    else if (working !== undefined)
      found.unit = utt(
        language,
        "mt_e_have",
        unit.unit_number,
        utt(language, type).toLowerCase(),
        working.serial_number,
      );
    if (serial.trim() === "") found.serial = utt(language, "mt_e_serial");
    // V1-060 B7: a date box passes on what is typed until it is a whole day.
    if (!isDay(installed)) found.installed = utt(language, "mt_e_date");
    else if (installed > today) found.installed = utt(language, "mt_e_future");
    const value = parseReading(first);
    if (value === null) found.first = utt(language, "err_num");
    setProblems(found);
    focusFirstError(
      [
        ["unit", "add-unit"],
        ["serial", "add-serial"],
        ["installed", "add-day"],
        ["first", "add-first"],
      ],
      found,
    );
    if (Object.keys(found).length > 0 || unit === undefined || value === null)
      return;
    const input: MeterInstallInput = {
      utility_type: type,
      serial_number: serial.trim(),
      measurement_unit_code: MEASUREMENT_UNIT_CODES[type],
      description: null,
      installed_date: installed,
      memo: null,
      initial_reading: {
        reading_date: installed,
        reading_value: String(value),
        source_evidence: "Typed in the Add meter dialog",
      },
    };
    send(
      JSON.stringify([unitId, input]),
      (key) => api.installMeter(unitId, input, key),
      {
        onSaved: (meter) => {
          onSaved(
            utt(language, "mt_add_done", meter.serial_number, unit.unit_number),
          );
        },
        onConflict,
        onSerialUsed: () => {
          setProblems({ serial: utt(language, "mt_e_used", serial.trim()) });
        },
      },
    );
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={utt(language, "close")}
      onClose={() => {
        onClose(outcome === "unknown");
      }}
      onSubmit={submit}
      submitLabel={
        busy
          ? utt(language, "saving")
          : outcome === "unknown"
            ? utt(language, "try_again")
            : utt(language, "mt_add")
      }
      title={utt(language, "mt_add")}
    >
      <p className="ui-small">{utt(language, "mt_add_intro")}</p>
      <OutcomeLine language={language} outcome={outcome} />
      <fieldset className="ui-radios">
        <legend>{utt(language, "col_type")}</legend>
        {(["ELECTRICITY", "WATER"] as const).map((kind) => (
          <label className="ui-chk" key={kind}>
            <input
              checked={type === kind}
              name="add-type"
              onChange={() => {
                setType(kind);
                // A Unit that already has this kind of meter is no longer offered.
                if (unitId !== "" && hasMeter(unitId, kind)) setUnitId("");
              }}
              type="radio"
            />
            {utt(language, kind)}
          </label>
        ))}
      </fieldset>
      <div className="ui-field">
        <label htmlFor="add-unit">
          {utt(language, "unit")}
          <span className="req">{utt(language, "required")}</span>
        </label>
        <select
          aria-describedby={
            problems.unit === undefined
              ? free.length === 0
                ? "add-unit-none"
                : undefined
              : "add-unit-err"
          }
          aria-invalid={problems.unit !== undefined}
          id="add-unit"
          onChange={(event) => {
            setUnitId(event.currentTarget.value);
          }}
          value={unitId}
        >
          <option value="">{utt(language, "mt_pick_unit")}</option>
          {free.map((item) => (
            <option key={item.unit_id} value={item.unit_id}>
              {item.unit_number}
            </option>
          ))}
        </select>
        {free.length === 0 && (
          <p className="help" id="add-unit-none">
            {utt(language, "mt_none_free", utt(language, type).toLowerCase())}
          </p>
        )}
        <FieldError id="add-unit" text={problems.unit} />
      </div>
      <div className="ui-field">
        <label htmlFor="add-serial">
          {utt(language, "mt_serial")}
          <span className="req">{utt(language, "required")}</span>
        </label>
        <input
          aria-describedby={
            problems.serial === undefined ? undefined : "add-serial-err"
          }
          aria-invalid={problems.serial !== undefined}
          autoComplete="off"
          id="add-serial"
          maxLength={200}
          onChange={(event) => {
            setSerial(event.currentTarget.value);
          }}
          value={serial}
        />
        <p className="help">{utt(language, "mt_serial_help", code)}</p>
        <FieldError id="add-serial" text={problems.serial} />
      </div>
      <div className="ui-field">
        <label htmlFor="add-day">{utt(language, "mt_installed")}</label>
        <DateInput
          language={language}
          describedBy={
            problems.installed === undefined ? undefined : "add-day-err"
          }
          invalid={problems.installed !== undefined}
          id="add-day"
          max={today}
          onChange={(value) => {
            setInstalled(value);
          }}
          value={installed}
        />
        <FieldError id="add-day" text={problems.installed} />
      </div>
      <div className="ui-field">
        <label htmlFor="add-first">{utt(language, "mt_new_start")}</label>
        <input
          aria-describedby={
            problems.first === undefined ? undefined : "add-first-err"
          }
          aria-invalid={problems.first !== undefined}
          autoComplete="off"
          id="add-first"
          inputMode="numeric"
          onChange={(event) => {
            setFirst(event.currentTarget.value);
          }}
          value={first}
        />
        <p className="help">{utt(language, "mt_start_help")}</p>
        <FieldError id="add-first" text={problems.first} />
      </div>
    </Dialog>
  );
}

/** V1-060 B6 (DL-104): the day the meter was found broken and what is wrong, both required. */
function ReportBrokenDialog({
  language,
  api,
  meter,
  readings,
  today,
  onClose,
  onSaved,
  onConflict,
}: {
  language: Language;
  api: UtilityApi;
  meter: UtilityMeter;
  readings: readonly UtilityReading[];
  today: string;
  onClose: (unsure: boolean) => void;
  onSaved: (reported: UtilityMeter) => void;
  onConflict: () => void;
}) {
  // The server refuses a day before the meter was put in or before its newest reading.
  const latest = readings.reduce(
    (day, reading) => (reading.reading_date > day ? reading.reading_date : day),
    meter.installed_date,
  );
  const [found, setFound] = useState(today);
  const [reason, setReason] = useState("");
  const [problems, setProblems] = useState<Record<string, string>>({});
  const { busy, outcome, send } = useMeterSend();

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const problem: Record<string, string> = {};
    if (!isDay(found)) problem.found = utt(language, "mt_e_date");
    else if (found > today) problem.found = utt(language, "mt_e_future");
    else if (found < latest)
      problem.found = utt(language, "mt_e_before", dayText(latest));
    if (reason.trim() === "") problem.reason = utt(language, "mt_e_why");
    setProblems(problem);
    focusFirstError(
      [
        ["found", "rb-found"],
        ["reason", "rb-why"],
      ],
      problem,
    );
    if (Object.keys(problem).length > 0) return;
    const input: MeterFailureReportInput = {
      expected_version: meter.version,
      failure_date: found,
      reason: reason.trim(),
    };
    send(
      JSON.stringify([meter.id, input]),
      (key) => api.reportBroken(meter.id, input, key),
      { onSaved, onConflict },
    );
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={utt(language, "close")}
      onClose={() => {
        onClose(outcome === "unknown");
      }}
      onSubmit={submit}
      submitLabel={
        busy
          ? utt(language, "saving")
          : outcome === "unknown"
            ? utt(language, "try_again")
            : utt(language, "mt_report")
      }
      title={utt(language, "mt_report_t", meter.serial_number)}
    >
      <OutcomeLine language={language} outcome={outcome} />
      <div className="ui-field">
        <label htmlFor="rb-found">
          {utt(language, "mt_found")}
          <span className="req">{utt(language, "required")}</span>
        </label>
        <DateInput
          language={language}
          describedBy={
            problems.found === undefined ? undefined : "rb-found-err"
          }
          invalid={problems.found !== undefined}
          id="rb-found"
          max={today}
          min={latest}
          onChange={(value) => {
            setFound(value);
          }}
          value={found}
        />
        <p className="help">
          {utt(language, "mt_found_help", dayText(latest))}
        </p>
        <FieldError id="rb-found" text={problems.found} />
      </div>
      <div className="ui-field">
        <label htmlFor="rb-why">
          {utt(language, "mt_wrong")}
          <span className="req">{utt(language, "required")}</span>
        </label>
        <textarea
          aria-describedby={
            problems.reason === undefined ? undefined : "rb-why-err"
          }
          aria-invalid={problems.reason !== undefined}
          id="rb-why"
          maxLength={500}
          onChange={(event) => {
            setReason(event.currentTarget.value);
          }}
          rows={2}
          value={reason}
        />
        <p className="help">{utt(language, "mt_wrong_help")}</p>
        <FieldError id="rb-why" text={problems.reason} />
      </div>
      <div className="ui-notice warn" role="note">
        <Icon name="alert" />
        <p>{utt(language, "mt_report_c", meter.serial_number)}</p>
      </div>
    </Dialog>
  );
}

function ReplaceMeterDialog({
  language,
  api,
  data,
  meter,
  today,
  onClose,
  onSaved,
  onConflict,
}: {
  language: Language;
  api: UtilityApi;
  data: UtilitiesData;
  meter: UtilityMeter;
  today: string;
  onClose: (unsure: boolean) => void;
  onSaved: (replacement: UtilityMeter) => void;
  onConflict: () => void;
}) {
  // The server takes the boundary from checked (validated) readings only, newest first, and
  // the larger id first on the same day.
  const readings = (data.readings.get(meter.id) ?? [])
    .filter((reading) => reading.validated)
    .sort(
      (left, right) =>
        right.reading_date.localeCompare(left.reading_date) ||
        right.id.localeCompare(left.id),
    );
  const lastGood = readings[0];
  const [found, setFound] = useState(meter.failure_date ?? "");
  const [putIn, setPutIn] = useState(today);
  const [serial, setSerial] = useState("");
  const [first, setFirst] = useState("0");
  const [reason, setReason] = useState("");
  const [problems, setProblems] = useState<Record<string, string>>({});
  const { busy, outcome, send } = useMeterSend();
  const owner = data.units.find((item) => item.unit_id === meter.unit_id);
  const code = `${meter.utility_type === "ELECTRICITY" ? "EL" : "WA"}-${owner?.unit_number ?? "U101"}`;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const problem: Record<string, string> = {};
    if (!isDay(found)) problem.found = utt(language, "mt_e_date");
    else if (found > today) problem.found = utt(language, "mt_e_future");
    else if (lastGood !== undefined && found < lastGood.reading_date)
      problem.found = utt(
        language,
        "mt_e_before",
        dayText(lastGood.reading_date),
      );
    if (!isDay(putIn)) problem.putIn = utt(language, "mt_e_date");
    else if (putIn > today) problem.putIn = utt(language, "mt_e_future");
    else if (isDay(found) && putIn <= found)
      problem.putIn = utt(language, "mt_e_after");
    if (serial.trim() === "") problem.serial = utt(language, "mt_e_serial");
    const value = parseReading(first);
    if (value === null) problem.first = utt(language, "err_num");
    if (reason.trim() === "") problem.reason = utt(language, "mt_e_why");
    setProblems(problem);
    focusFirstError(
      [
        ["found", "rp-found"],
        ["putIn", "rp-day"],
        ["serial", "rp-serial"],
        ["first", "rp-first"],
        ["reason", "rp-why"],
      ],
      problem,
    );
    // The last good reading is the newest one on or before the day it was found broken.
    const boundary = readings.find((reading) => reading.reading_date <= found);
    if (
      Object.keys(problem).length > 0 ||
      value === null ||
      boundary === undefined
    )
      return;
    const input: MeterReplaceInput = {
      expected_version: meter.version,
      failed_boundary_reading_id: boundary.id,
      failure_date: found,
      replacement_date: putIn,
      reason: reason.trim(),
      replacement_meter: {
        serial_number: serial.trim(),
        description: null,
        memo: null,
      },
      replacement_initial_reading: {
        reading_date: putIn,
        reading_value: String(value),
        source_evidence: "Typed in the Replace meter dialog",
      },
    };
    send(
      JSON.stringify([meter.id, input]),
      (key) => api.replaceMeter(meter.id, input, key),
      {
        onSaved,
        onConflict,
        onSerialUsed: () => {
          setProblems({ serial: utt(language, "mt_e_used", serial.trim()) });
        },
      },
    );
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={utt(language, "close")}
      onClose={() => {
        onClose(outcome === "unknown");
      }}
      onSubmit={submit}
      submitLabel={
        busy
          ? utt(language, "saving")
          : outcome === "unknown"
            ? utt(language, "try_again")
            : utt(language, "replace")
      }
      title={utt(language, "mt_replace_t", meter.serial_number)}
    >
      <OutcomeLine language={language} outcome={outcome} />
      <div className="ui-field">
        <label htmlFor="rp-found">
          {utt(language, "mt_found")}
          <span className="req">{utt(language, "required")}</span>
        </label>
        <DateInput
          language={language}
          describedBy={
            problems.found === undefined ? undefined : "rp-found-err"
          }
          // DL-104: a meter reported broken keeps that day; the server refuses another.
          disabled={meter.failure_date !== null}
          invalid={problems.found !== undefined}
          id="rp-found"
          max={today}
          min={lastGood?.reading_date}
          onChange={(value) => {
            setFound(value);
          }}
          value={found}
        />
        {meter.failure_date !== null ? (
          <p className="help">{utt(language, "mt_found_kept")}</p>
        ) : (
          lastGood !== undefined && (
            <p className="help">
              {utt(language, "mt_found_help", dayText(lastGood.reading_date))}
            </p>
          )
        )}
        <FieldError id="rp-found" text={problems.found} />
      </div>
      <div className="ui-field">
        <label htmlFor="rp-day">{utt(language, "mt_new_day")}</label>
        <DateInput
          language={language}
          describedBy={problems.putIn === undefined ? undefined : "rp-day-err"}
          invalid={problems.putIn !== undefined}
          id="rp-day"
          max={today}
          onChange={(value) => {
            setPutIn(value);
          }}
          value={putIn}
        />
        <FieldError id="rp-day" text={problems.putIn} />
      </div>
      <div className="ui-field">
        <label htmlFor="rp-serial">
          {utt(language, "mt_new_serial")}
          <span className="req">{utt(language, "required")}</span>
        </label>
        <input
          aria-describedby={
            problems.serial === undefined ? undefined : "rp-serial-err"
          }
          aria-invalid={problems.serial !== undefined}
          autoComplete="off"
          id="rp-serial"
          maxLength={200}
          onChange={(event) => {
            setSerial(event.currentTarget.value);
          }}
          value={serial}
        />
        <p className="help">{utt(language, "mt_serial_help", code)}</p>
        <FieldError id="rp-serial" text={problems.serial} />
      </div>
      <div className="ui-field">
        <label htmlFor="rp-first">{utt(language, "mt_new_start")}</label>
        <input
          aria-describedby={
            problems.first === undefined ? undefined : "rp-first-err"
          }
          aria-invalid={problems.first !== undefined}
          autoComplete="off"
          id="rp-first"
          inputMode="numeric"
          onChange={(event) => {
            setFirst(event.currentTarget.value);
          }}
          value={first}
        />
        <p className="help">{utt(language, "mt_start_help")}</p>
        <FieldError id="rp-first" text={problems.first} />
      </div>
      <div className="ui-field">
        <label htmlFor="rp-why">
          {utt(language, "mt_why")}
          <span className="req">{utt(language, "required")}</span>
        </label>
        <textarea
          aria-describedby={
            problems.reason === undefined ? undefined : "rp-why-err"
          }
          aria-invalid={problems.reason !== undefined}
          id="rp-why"
          maxLength={500}
          onChange={(event) => {
            setReason(event.currentTarget.value);
          }}
          rows={2}
          value={reason}
        />
        <p className="help">{utt(language, "mt_why_help")}</p>
        <FieldError id="rp-why" text={problems.reason} />
      </div>
      <div className="ui-notice" role="note">
        <Icon name="info" />
        <p>{utt(language, "mt_replace_c", meter.serial_number)}</p>
      </div>
    </Dialog>
  );
}
