// HRIS phase 6 (mock-up v69, rounds 26 and 27): Office › Employees and payroll › Attendance.
// Daily sheet, Weekly plan, Overtime, Month summary and QR places. Times come from the staff
// bot (phone QR or employee card) or are entered by hand with a reason; a fix never types over
// the old times. A month locks once its payroll is sent for approval. The server checks every
// right and rule again.

import { type FormEvent, useCallback, useState } from "react";

import { useRead } from "../ledger/LedgerPage";
import { monthLabel } from "../ledger/text";
import { DateInput } from "../shell/DateInput";
import { dayText, momentText } from "../shell/format";
import { Icon } from "../shell/icons";
import { Chip, Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import {
  addDays,
  clockOf,
  clockText,
  Done,
  Failure,
  Field,
  monthStart,
  nameOf,
  nextMonth,
  NoProperty,
  previousMonth,
  ReasonField,
  shiftChoices,
  shiftText,
  useHrBusy,
  Waiting,
  weekdayOf,
} from "./common";
import { ReasonDialog } from "./EmployeesPage";
import {
  type AttendanceDay,
  type AttendanceMonth,
  type AttendanceWeek,
  type DayLine,
  type DayStatus,
  type Employee,
  type HrApi,
  hrApi as defaultHrApi,
  type OvertimeList,
  type OvertimeRequest,
  type Place,
  type PlaceList,
  type Scan,
  type ShiftCode,
} from "./hrClient";
import { codeText, ht } from "./text";

export interface AttendancePageProps {
  language: Language;
  propertyId: string;
  active: boolean;
  api?: HrApi;
}

type View = "day" | "week" | "ot" | "month" | "places";

const VIEWS: readonly View[] = ["day", "week", "ot", "month", "places"];
const SHIFTS: readonly ShiftCode[] = [
  "MORNING",
  "AFTERNOON",
  "NIGHT",
  "OFFICE",
];
const STATUSES: readonly DayStatus[] = [
  "WORKED",
  "ABSENT",
  "LEAVE_ANNUAL",
  "LEAVE_SICK",
  "LEAVE_UNPAID",
  "DAY_OFF",
];

export function AttendancePage({
  language,
  propertyId,
  active,
  api = defaultHrApi,
}: AttendancePageProps) {
  const [view, setView] = useState<View>("day");
  if (propertyId === "") return <NoProperty language={language} />;
  const ready = active && propertyId !== "";
  return (
    <>
      <section aria-labelledby="hr-a-title" className="ui-card">
        <div className="ui-head">
          <div>
            <h2 id="hr-a-title">{ht(language, "a_title")}</h2>
            <p>{ht(language, "a_sub")}</p>
          </div>
        </div>
        <div
          aria-label={ht(language, "a_title")}
          className="ui-seg"
          role="group"
        >
          {VIEWS.map((which) => (
            <button
              aria-pressed={view === which}
              key={which}
              onClick={() => {
                setView(which);
              }}
              type="button"
            >
              {ht(language, `a_${which}` as const)}
            </button>
          ))}
        </div>
      </section>
      {view === "day" && (
        <DaySheet
          active={ready}
          api={api}
          language={language}
          propertyId={propertyId}
        />
      )}
      {view === "week" && (
        <WeekPlan
          active={ready}
          api={api}
          language={language}
          propertyId={propertyId}
        />
      )}
      {view === "ot" && (
        <Overtime
          active={ready}
          api={api}
          language={language}
          propertyId={propertyId}
        />
      )}
      {view === "month" && (
        <MonthSummary
          active={ready}
          api={api}
          language={language}
          propertyId={propertyId}
        />
      )}
      {view === "places" && (
        <Places
          active={ready}
          api={api}
          language={language}
          propertyId={propertyId}
        />
      )}
    </>
  );
}

interface PartProps {
  language: Language;
  propertyId: string;
  api: HrApi;
  active: boolean;
}

/* ---------- Daily sheet ---------- */

function statusChip(language: Language, line: DayLine, sheet: AttendanceDay) {
  if (line.status === null) {
    if (line.day_off === true)
      return <Chip tone="neutral">{ht(language, "st_DAY_OFF")}</Chip>;
    if (sheet.day > sheet.today) return null;
    const shift = sheet.shifts.find(
      (one) => one.code === (line.planned_shift ?? ""),
    );
    if (sheet.day === sheet.today && shift !== undefined) {
      const now = clockText(new Date().toISOString());
      if (now < shift.starts_at)
        return <Chip tone="neutral">{ht(language, "a_not_started")}</Chip>;
    }
    return <Chip tone="err">{ht(language, "a_no_in")}</Chip>;
  }
  if (line.status !== "WORKED") {
    const tone = line.status === "ABSENT" ? "err" : "info";
    return <Chip tone={tone}>{codeText(language, "st_", line.status)}</Chip>;
  }
  if (line.no_check_out === true)
    return <Chip tone="warn">{ht(language, "a_no_out")}</Chip>;
  if (line.check_out_at === null && sheet.day === sheet.today)
    return <Chip tone="info">{ht(language, "a_on_shift")}</Chip>;
  if (line.late_minutes !== null && line.late_minutes > 0)
    return <Chip tone="warn">{ht(language, "a_late", line.late_minutes)}</Chip>;
  return <Chip tone="ok">{ht(language, "a_present")}</Chip>;
}

function DaySheet({ language, propertyId, api, active }: PartProps) {
  const [day, setDay] = useState<string | null>(null);
  const [shift, setShift] = useState<ShiftCode | "ALL">("ALL");
  const [editing, setEditing] = useState<DayLine | null>(null);
  const [accepting, setAccepting] = useState<{
    line: DayLine;
    scan: Scan;
  } | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const read = useCallback(
    () => api.day(propertyId, day),
    [api, propertyId, day],
  );
  const answer = useRead<AttendanceDay>(active, read);
  const sheet = answer.data;
  if (sheet === null)
    return (
      <Waiting
        failed={answer.failed}
        language={language}
        onRetry={answer.reload}
      />
    );
  const people = sheet.people.filter(
    (line) =>
      shift === "ALL" || (line.shift_code ?? line.planned_shift) === shift,
  );
  const canFix = sheet.can_manage && !sheet.locked;
  const move = (days: number) => {
    setDone(null);
    setDay(addDays(sheet.day, days));
  };
  return (
    <>
      <Done text={done} />
      <section aria-labelledby="hr-ad" className="ui-card pad0">
        <div className="ui-filters">
          <h2 id="hr-ad">
            {ht(language, "a_day")} ·{" "}
            <span className="ui-num">
              {codeText(language, "wd_", String(weekdayOf(sheet.day)))}{" "}
              {dayText(sheet.day)}
            </span>
            {sheet.day === sheet.today && ` (${ht(language, "a_today")})`}
          </h2>
          <span className="ui-actions">
            <button
              className="ui-btn"
              onClick={() => {
                move(-1);
              }}
              type="button"
            >
              {ht(language, "a_day_before")}
            </button>
            <button
              className="ui-btn"
              disabled={sheet.day >= sheet.today}
              onClick={() => {
                move(1);
              }}
              type="button"
            >
              {ht(language, "a_next_day")}
            </button>
          </span>
          <div
            aria-label={ht(language, "a_shift")}
            className="ui-seg"
            role="group"
          >
            {(["ALL", ...SHIFTS] as const).map((code) => (
              <button
                aria-pressed={shift === code}
                key={code}
                onClick={() => {
                  setShift(code);
                }}
                type="button"
              >
                {code === "ALL"
                  ? ht(language, "a_all_shifts")
                  : shiftText(language, code)}
              </button>
            ))}
          </div>
          {sheet.locked && (
            <Chip icon="lock" tone="neutral">
              {ht(language, "a_locked")}
            </Chip>
          )}
        </div>
        {sheet.locked && (
          <p className="ui-notice warn">
            {ht(language, "p_locked_month", monthLabel(language, sheet.day))}
          </p>
        )}
        {people.length === 0 ? (
          <p className="ui-empty">{ht(language, "a_nobody")}</p>
        ) : (
          <div className="ui-tablewrap">
            <table className="ui-table">
              <thead>
                <tr>
                  <th scope="col">{ht(language, "e_name")}</th>
                  <th scope="col">{ht(language, "a_shift")}</th>
                  <th scope="col">{ht(language, "a_in")}</th>
                  <th scope="col">{ht(language, "a_out")}</th>
                  <th scope="col">{ht(language, "a_status")}</th>
                  <th scope="col">
                    <span className="ui-sr">{ht(language, "a_edit")}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {people.map((line) => (
                  <tr key={line.employee_id}>
                    <td>
                      {nameOf(language, line)}
                      <span className="ui-sub2">
                        {language === "km" && line.job_km !== null
                          ? line.job_km
                          : (line.job_en ?? "")}
                      </span>
                    </td>
                    <td>
                      {shiftText(
                        language,
                        line.shift_code ?? line.planned_shift,
                      )}
                    </td>
                    <td className="ui-num">{clockText(line.check_in_at)}</td>
                    <td className="ui-num">{clockText(line.check_out_at)}</td>
                    <td>
                      {statusChip(language, line, sheet)}
                      {line.source !== null && (
                        <span className="ui-sub2">
                          {codeText(language, "src_", line.source)}
                        </span>
                      )}
                      {line.fixed && line.reason !== null && (
                        <span className="ui-sub2 ui-muted">
                          {ht(language, "a_fixed_short", line.reason)}
                        </span>
                      )}
                      <ScanLines
                        api={api}
                        canAccept={sheet.can_manage}
                        language={language}
                        line={line}
                        onAccept={(scan) => {
                          setDone(null);
                          setAccepting({ line, scan });
                        }}
                        propertyId={propertyId}
                      />
                    </td>
                    <td>
                      {canFix && (
                        <button
                          className="ui-btn link"
                          onClick={() => {
                            setDone(null);
                            setEditing(line);
                          }}
                          type="button"
                        >
                          {ht(language, "a_edit")}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="ui-tfoot ui-muted">
          {ht(language, "a_night_note")} {ht(language, "a_how")}
        </p>
      </section>
      {editing !== null && (
        <EditTimesDialog
          api={api}
          day={sheet.day}
          language={language}
          line={editing}
          onClose={() => {
            setEditing(null);
          }}
          onSaved={(text) => {
            setEditing(null);
            setDone(text);
            answer.reload();
          }}
          propertyId={propertyId}
        />
      )}
      {accepting !== null && (
        <ReasonDialog
          language={language}
          note={ht(language, "a_accept_note")}
          onClose={() => {
            setAccepting(null);
          }}
          onSave={(note) =>
            api
              .acceptScan(propertyId, accepting.scan.scan_id, note)
              .then(() =>
                ht(
                  language,
                  "a_accepted",
                  nameOf(language, accepting.line),
                  clockText(accepting.scan.scanned_at),
                ),
              )
          }
          onSaved={(text) => {
            setAccepting(null);
            setDone(text);
            answer.reload();
          }}
          optional
          submitLabel={ht(language, "a_accept")}
          title={ht(language, "a_accept_t", nameOf(language, accepting.line))}
        />
      )}
    </>
  );
}

function ScanLines({
  language,
  propertyId,
  api,
  line,
  canAccept,
  onAccept,
}: {
  language: Language;
  propertyId: string;
  api: HrApi;
  line: DayLine;
  canAccept: boolean;
  onAccept: (scan: Scan) => void;
}) {
  if (line.scans.length === 0) return null;
  return (
    <ul className="ui-plain ui-small">
      {line.scans.map((scan) => {
        const place =
          language === "km" && scan.place_km !== null
            ? scan.place_km
            : (scan.place_en ?? "");
        const by =
          language === "km" && scan.scanned_by_km !== null
            ? scan.scanned_by_km
            : scan.scanned_by_en;
        return (
          <li key={scan.scan_id}>
            <span className="ui-num">{clockText(scan.scanned_at)}</span>{" "}
            {ht(language, scan.direction === "IN" ? "a_in" : "a_out")} ·{" "}
            {codeText(
              language,
              "src_",
              scan.method === "PHONE" ? "QR_PHONE" : "QR_CARD",
            )}
            {place !== "" && ` · ${place}`}
            {scan.distance_m !== null &&
              ` · ${ht(language, "a_distance", scan.distance_m)}`}
            {scan.card_reason !== null &&
              ` · ${codeText(language, "cr_", scan.card_reason)}`}
            {scan.card_reason_text !== null && ` (${scan.card_reason_text})`}
            {by !== null && ` · ${ht(language, "a_scanned_by", by)}`}{" "}
            {scan.has_photo && (
              <a
                className="ui-btn link"
                href={api.photoUrl(propertyId, scan.scan_id)}
                rel="noopener"
                target="_blank"
              >
                {ht(language, "a_open_photo")}
              </a>
            )}
            {scan.needs_check && !scan.accepted && (
              <>
                {" "}
                <Chip tone="warn">{ht(language, "a_needs_check")}</Chip>
                {canAccept && (
                  <button
                    className="ui-btn link"
                    onClick={() => {
                      onAccept(scan);
                    }}
                    type="button"
                  >
                    {ht(language, "a_accept")}
                  </button>
                )}
              </>
            )}
            {scan.accepted && (
              <>
                {" "}
                <Chip tone="ok">{ht(language, "a_accepted_chip")}</Chip>
              </>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function EditTimesDialog({
  language,
  propertyId,
  api,
  day,
  line,
  onSaved,
  onClose,
}: {
  language: Language;
  propertyId: string;
  api: HrApi;
  day: string;
  line: DayLine;
  onSaved: (text: string) => void;
  onClose: () => void;
}) {
  const [status, setStatus] = useState<DayStatus>(line.status ?? "WORKED");
  const choices = shiftChoices(line.uses_shifts);
  const [shift, setShift] = useState<ShiftCode>(() => {
    const known = line.shift_code ?? line.planned_shift;
    return known !== null && choices.includes(known)
      ? known
      : (choices[0] ?? "OFFICE");
  });
  const [checkIn, setCheckIn] = useState(clockText(line.check_in_at));
  const [checkOut, setCheckOut] = useState(clockText(line.check_out_at));
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { busy, failure, run } = useHrBusy(language);
  const worked = status === "WORKED";
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const inAt = checkIn.trim() === "" ? null : clockOf(checkIn);
    const outAt = checkOut.trim() === "" ? null : clockOf(checkOut);
    if (
      worked &&
      (inAt === null || (checkOut.trim() !== "" && outAt === null))
    ) {
      setError(ht(language, "time_bad"));
      return;
    }
    if (reason.trim() === "") {
      setError(ht(language, "say_why"));
      return;
    }
    setError(null);
    run(
      () =>
        api.enterDay(propertyId, {
          employee_id: line.employee_id,
          work_date: day,
          status,
          ...(worked ? { shift_code: shift, check_in: inAt } : {}),
          ...(worked && outAt !== null ? { check_out: outAt } : {}),
          reason: reason.trim(),
        }),
      () => {
        onSaved(ht(language, "a_saved", nameOf(language, line)));
      },
    );
  };
  return (
    <Dialog
      busy={busy}
      closeLabel={ht(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={ht(language, "save")}
      title={ht(language, "a_edit_t", nameOf(language, line), dayText(day))}
    >
      <Field id="hr-et-st" label={ht(language, "a_status")}>
        <select
          id="hr-et-st"
          onChange={(event) => {
            setStatus(event.target.value as DayStatus);
          }}
          value={status}
        >
          {STATUSES.map((code) => (
            <option key={code} value={code}>
              {codeText(language, "st_", code)}
            </option>
          ))}
        </select>
      </Field>
      {worked && (
        <>
          <Field id="hr-et-sh" label={ht(language, "a_shift")}>
            <select
              id="hr-et-sh"
              onChange={(event) => {
                setShift(event.target.value as ShiftCode);
              }}
              value={shift}
            >
              {choices.map((code) => (
                <option key={code} value={code}>
                  {shiftText(language, code)}
                </option>
              ))}
            </select>
          </Field>
          <div className="ui-row2">
            <Field
              id="hr-et-in"
              label={ht(language, "a_in")}
              help={ht(language, "time_bad")}
            >
              <input
                id="hr-et-in"
                inputMode="numeric"
                onChange={(event) => {
                  setCheckIn(event.target.value);
                }}
                placeholder="07:05"
                value={checkIn}
              />
            </Field>
            <Field
              id="hr-et-out"
              label={ht(language, "a_out")}
              note={ht(language, "optional")}
            >
              <input
                id="hr-et-out"
                inputMode="numeric"
                onChange={(event) => {
                  setCheckOut(event.target.value);
                }}
                placeholder="15:30"
                value={checkOut}
              />
            </Field>
          </div>
          <p className="ui-muted ui-small">{ht(language, "a_worked_note")}</p>
        </>
      )}
      <ReasonField
        id="hr-et-why"
        language={language}
        onChange={setReason}
        value={reason}
      />
      <p className="ui-muted ui-small">{ht(language, "a_old_kept")}</p>
      <Failure text={error ?? failure} />
    </Dialog>
  );
}

/* ---------- Weekly plan ---------- */

function WeekPlan({ language, propertyId, api, active }: PartProps) {
  const [monday, setMonday] = useState<string | null>(null);
  const [planning, setPlanning] = useState<{
    person: AttendanceWeek["people"][number];
    day: AttendanceWeek["people"][number]["days"][number];
  } | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const read = useCallback(
    () => api.week(propertyId, monday),
    [api, propertyId, monday],
  );
  const answer = useRead<AttendanceWeek>(active, read);
  const readDay = useCallback(
    () => api.day(propertyId, null),
    [api, propertyId],
  );
  const today = useRead<AttendanceDay>(active, readDay);
  const week = answer.data;
  if (week === null)
    return (
      <Waiting
        failed={answer.failed}
        language={language}
        onRetry={answer.reload}
      />
    );
  const todayDay = today.data?.today ?? "";
  const canPlan = today.data?.can_manage === true;
  const days = [0, 1, 2, 3, 4, 5, 6].map((offset) =>
    addDays(week.monday, offset),
  );
  return (
    <>
      <Done text={done} />
      <section aria-labelledby="hr-aw" className="ui-card pad0">
        <div className="ui-filters">
          <h2 id="hr-aw">
            {ht(language, "a_week")} ·{" "}
            <span className="ui-num">
              {dayText(week.monday)} – {dayText(addDays(week.monday, 6))}
            </span>
          </h2>
          <span className="ui-actions">
            <button
              className="ui-btn"
              onClick={() => {
                setDone(null);
                setMonday(addDays(week.monday, -7));
              }}
              type="button"
            >
              {ht(language, "a_week_before")}
            </button>
            <button
              className="ui-btn"
              onClick={() => {
                setDone(null);
                setMonday(addDays(week.monday, 7));
              }}
              type="button"
            >
              {ht(language, "a_next_week")}
            </button>
          </span>
        </div>
        {week.people.length === 0 ? (
          <p className="ui-empty">{ht(language, "a_nobody")}</p>
        ) : (
          <div className="ui-tablewrap">
            <table className="ui-table">
              <thead>
                <tr>
                  <th scope="col">{ht(language, "e_name")}</th>
                  {days.map((day) => (
                    <th key={day} scope="col">
                      {codeText(language, "wds_", String(weekdayOf(day)))}
                      <span className="ui-sub2 ui-num">
                        {dayText(day).slice(0, 5)}
                      </span>
                    </th>
                  ))}
                  <th scope="col">{ht(language, "a_days_off")}</th>
                </tr>
              </thead>
              <tbody>
                {week.people.map((person) => {
                  const off = person.days.filter(
                    (one) => one.works && one.day_off === true,
                  ).length;
                  return (
                    <tr key={person.employee_id}>
                      <th scope="row">
                        {nameOf(language, person)}
                        <span className="ui-sub2 ui-num">
                          {person.employee_code}
                        </span>
                      </th>
                      {person.days.map((one) => {
                        const words = !one.works
                          ? ht(language, "a_not_working")
                          : one.day_off === true
                            ? ht(language, "a_off")
                            : one.shift_code === null
                              ? ""
                              : codeText(language, "shs_", one.shift_code);
                        const changeable =
                          canPlan &&
                          one.works &&
                          one.work_date >= todayDay &&
                          todayDay !== "";
                        return (
                          <td key={one.work_date}>
                            {changeable ? (
                              <button
                                aria-label={ht(
                                  language,
                                  "a_plan_t",
                                  nameOf(language, person),
                                  dayText(one.work_date),
                                )}
                                className="ui-btn link"
                                onClick={() => {
                                  setDone(null);
                                  setPlanning({ person, day: one });
                                }}
                                type="button"
                              >
                                {words}
                              </button>
                            ) : (
                              <span className={one.works ? "" : "ui-muted"}>
                                {words}
                              </span>
                            )}
                            {one.planned === true && (
                              <span className="ui-sub2 ui-muted">✎</span>
                            )}
                          </td>
                        );
                      })}
                      <td>
                        {person.days_off_per_month === undefined ||
                        person.days_off_per_month === null ? (
                          <>
                            <span className="ui-num">{off}</span>{" "}
                            {off < week.days_off_per_week && (
                              <Chip tone="warn">
                                {ht(
                                  language,
                                  "a_fewer_off",
                                  week.days_off_per_week,
                                )}
                              </Chip>
                            )}
                          </>
                        ) : (
                          // Owner 06/11/2026: days off a month on request, no weekly day off.
                          (person.month_days_off ?? []).map((month) => (
                            <span className="ui-sub2" key={month.month}>
                              <Chip
                                tone={
                                  month.planned >
                                  (person.days_off_per_month ?? 0)
                                    ? "warn"
                                    : "neutral"
                                }
                              >
                                {ht(
                                  language,
                                  "a_month_off",
                                  monthLabel(language, month.month),
                                  month.planned,
                                  person.days_off_per_month ?? 0,
                                )}
                              </Chip>
                            </span>
                          ))
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className="ui-tfoot ui-muted">
          {ht(language, "a_past_note", week.days_off_per_week)}
        </p>
      </section>
      {planning !== null && (
        <PlanDialog
          api={api}
          day={planning.day}
          language={language}
          onClose={() => {
            setPlanning(null);
          }}
          onSaved={(text) => {
            setPlanning(null);
            setDone(text);
            answer.reload();
          }}
          person={planning.person}
          propertyId={propertyId}
        />
      )}
    </>
  );
}

function PlanDialog({
  language,
  propertyId,
  api,
  person,
  day,
  onSaved,
  onClose,
}: {
  language: Language;
  propertyId: string;
  api: HrApi;
  person: AttendanceWeek["people"][number];
  day: AttendanceWeek["people"][number]["days"][number];
  onSaved: (text: string) => void;
  onClose: () => void;
}) {
  const choices = shiftChoices(person.uses_shifts);
  const [shift, setShift] = useState<ShiftCode | "OFF">(() =>
    day.day_off === true
      ? "OFF"
      : day.shift_code !== null && choices.includes(day.shift_code)
        ? day.shift_code
        : (choices[0] ?? "OFFICE"),
  );
  const [reason, setReason] = useState("");
  const { busy, failure, run } = useHrBusy(language);
  return (
    <Dialog
      busy={busy}
      closeLabel={ht(language, "cancel")}
      onClose={onClose}
      onSubmit={(event) => {
        event.preventDefault();
        run(
          () =>
            api.planDay(propertyId, {
              employee_id: person.employee_id,
              work_date: day.work_date,
              shift_code: shift === "OFF" ? null : shift,
              ...(reason.trim() === "" ? {} : { reason: reason.trim() }),
            }),
          () => {
            onSaved(ht(language, "a_plan_saved"));
          },
        );
      }}
      submitLabel={ht(language, "save")}
      title={ht(
        language,
        "a_plan_t",
        nameOf(language, person),
        dayText(day.work_date),
      )}
    >
      <fieldset className="ui-field">
        <legend>{ht(language, "a_shift")}</legend>
        <div className="ui-radios">
          {[...choices, "OFF" as const].map((code) => (
            <label className="ui-chk" key={code}>
              <input
                checked={shift === code}
                name="hr-plan-shift"
                onChange={() => {
                  setShift(code);
                }}
                type="radio"
              />
              {code === "OFF"
                ? ht(language, "a_off")
                : shiftText(language, code)}
            </label>
          ))}
        </div>
      </fieldset>
      <ReasonField
        id="hr-plan-why"
        language={language}
        onChange={setReason}
        optional
        value={reason}
      />
      <Failure text={failure} />
    </Dialog>
  );
}

/* ---------- Overtime ---------- */

function Overtime({ language, propertyId, api, active }: PartProps) {
  const [month, setMonth] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [refusing, setRefusing] = useState<OvertimeRequest | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const read = useCallback(
    () => api.overtime(propertyId, month),
    [api, propertyId, month],
  );
  const answer = useRead<OvertimeList>(active, read);
  const readPeople = useCallback(
    () => api.employees(propertyId),
    [api, propertyId],
  );
  const people = useRead<Employee[]>(
    active && answer.data?.can_request === true,
    readPeople,
  );
  const approving = useHrBusy(language);
  const list = answer.data;
  if (list === null)
    return (
      <Waiting
        failed={answer.failed}
        language={language}
        onRetry={answer.reload}
      />
    );
  return (
    <>
      <Done text={done} />
      <section aria-labelledby="hr-ao" className="ui-card pad0">
        <div className="ui-filters">
          <h2 id="hr-ao">
            {ht(language, "ot_title")} · {monthLabel(language, list.month)}
          </h2>
          <span className="ui-actions">
            <button
              className="ui-btn"
              onClick={() => {
                setDone(null);
                setMonth(previousMonth(list.month));
              }}
              type="button"
            >
              <Icon name="back" small />
              <span className="ui-sr">
                {monthLabel(language, previousMonth(list.month))}
              </span>
            </button>
            <button
              className="ui-btn"
              onClick={() => {
                setDone(null);
                setMonth(nextMonth(list.month));
              }}
              type="button"
            >
              <Icon name="forward" small />
              <span className="ui-sr">
                {monthLabel(language, nextMonth(list.month))}
              </span>
            </button>
            {list.can_request && (
              <button
                className="ui-btn primary"
                disabled={people.data === null}
                onClick={() => {
                  setDone(null);
                  setAsking(true);
                }}
                type="button"
              >
                <Icon name="plus" small />
                {ht(language, "ot_request")}
              </button>
            )}
          </span>
        </div>
        <p className="ui-muted ui-small">{ht(language, "ot_ask_note")}</p>
        <Failure text={approving.failure} />
        {list.requests.length === 0 ? (
          <p className="ui-empty">{ht(language, "ot_none")}</p>
        ) : (
          <div className="ui-tablewrap">
            <table className="ui-table">
              <thead>
                <tr>
                  <th scope="col">{ht(language, "e_name")}</th>
                  <th scope="col">{ht(language, "ot_when")}</th>
                  <th scope="col">{ht(language, "ot_hours")}</th>
                  <th scope="col">{ht(language, "reason")}</th>
                  <th scope="col">{ht(language, "a_status")}</th>
                </tr>
              </thead>
              <tbody>
                {list.requests.map((one) => (
                  <tr key={one.request_id}>
                    <td>
                      {nameOf(language, one)}
                      <span className="ui-sub2 ui-num">
                        {one.overtime_number}
                      </span>
                    </td>
                    <td className="ui-num">
                      {dayText(one.work_date)}
                      <span className="ui-sub2">
                        {one.starts_at}–{one.ends_at}
                      </span>
                    </td>
                    <td className="ui-num">
                      {ht(language, "ot_h", one.normal_hours)}
                      {one.night_hours > 0 && (
                        <span className="ui-sub2">
                          {ht(language, "ot_night_h", one.night_hours)}
                        </span>
                      )}
                    </td>
                    <td>
                      {one.reason}
                      <span className="ui-sub2 ui-muted">
                        {ht(
                          language,
                          "ot_asked",
                          one.asked_by ?? "",
                          momentText(one.asked_at),
                        )}
                      </span>
                    </td>
                    <td>
                      {one.decision === null ? (
                        <>
                          <Chip tone="warn">{ht(language, "ot_waiting")}</Chip>
                          {list.can_approve && (
                            <span className="ui-actions">
                              <button
                                className="ui-btn primary"
                                disabled={approving.busy}
                                onClick={() => {
                                  setDone(null);
                                  approving.run(
                                    () =>
                                      api.decideOvertime(
                                        propertyId,
                                        one.request_id,
                                        {
                                          decision: "APPROVED",
                                        },
                                      ),
                                    () => {
                                      setDone(
                                        ht(
                                          language,
                                          "ot_approved",
                                          one.overtime_number,
                                          nameOf(language, one),
                                        ),
                                      );
                                      answer.reload();
                                    },
                                  );
                                }}
                                type="button"
                              >
                                {ht(language, "approve")}
                              </button>
                              <button
                                className="ui-btn"
                                onClick={() => {
                                  setDone(null);
                                  setRefusing(one);
                                }}
                                type="button"
                              >
                                {ht(language, "refuse")}
                              </button>
                            </span>
                          )}
                        </>
                      ) : (
                        <>
                          <Chip
                            tone={
                              one.decision === "APPROVED" ? "ok" : "neutral"
                            }
                          >
                            {ht(
                              language,
                              one.decision === "APPROVED"
                                ? "ot_approved_chip"
                                : "ot_refused",
                            )}
                          </Chip>
                          <span className="ui-sub2 ui-muted">
                            {ht(
                              language,
                              "by",
                              one.decided_by ?? "",
                              momentText(one.decided_at),
                            )}
                            {one.decision_reason !== null &&
                              ` · ${one.decision_reason}`}
                          </span>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {asking && people.data !== null && (
        <AskOvertimeDialog
          api={api}
          language={language}
          onClose={() => {
            setAsking(false);
          }}
          onSaved={(text) => {
            setAsking(false);
            setDone(text);
            answer.reload();
          }}
          people={people.data.filter((person) => person.state !== "LEFT")}
          propertyId={propertyId}
        />
      )}
      {refusing !== null && (
        <ReasonDialog
          language={language}
          onClose={() => {
            setRefusing(null);
          }}
          onSave={(reason) =>
            api
              .decideOvertime(propertyId, refusing.request_id, {
                decision: "REFUSED",
                reason,
              })
              .then(() =>
                ht(
                  language,
                  "ot_refused_msg",
                  refusing.overtime_number,
                  nameOf(language, refusing),
                ),
              )
          }
          onSaved={(text) => {
            setRefusing(null);
            setDone(text);
            answer.reload();
          }}
          submitLabel={ht(language, "refuse")}
          title={ht(language, "ot_refuse_t", refusing.overtime_number)}
        />
      )}
    </>
  );
}

function AskOvertimeDialog({
  language,
  propertyId,
  api,
  people,
  onSaved,
  onClose,
}: {
  language: Language;
  propertyId: string;
  api: HrApi;
  people: Employee[];
  onSaved: (text: string) => void;
  onClose: () => void;
}) {
  const [employee, setEmployee] = useState(people[0]?.employee_id ?? "");
  const [day, setDay] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { busy, failure, run } = useHrBusy(language);
  const person = people.find((one) => one.employee_id === employee) ?? null;
  return (
    <Dialog
      busy={busy}
      closeLabel={ht(language, "cancel")}
      onClose={onClose}
      onSubmit={(event) => {
        event.preventDefault();
        const starts = clockOf(from);
        const ends = clockOf(to);
        if (person === null) return;
        if (day === "") {
          setError(ht(language, "day_bad"));
          return;
        }
        if (starts === null || ends === null) {
          setError(ht(language, "time_bad"));
          return;
        }
        if (reason.trim() === "") {
          setError(ht(language, "say_why"));
          return;
        }
        setError(null);
        run(
          () =>
            api.askOvertime(propertyId, {
              employee_id: person.employee_id,
              work_date: day,
              starts_at: starts,
              ends_at: ends,
              reason: reason.trim(),
            }),
          () => {
            onSaved(ht(language, "ot_sent_for", nameOf(language, person)));
          },
        );
      }}
      submitLabel={ht(language, "ot_send")}
      title={ht(language, "ot_request")}
    >
      <Field id="hr-ot-emp" label={ht(language, "e_name")}>
        <select
          id="hr-ot-emp"
          onChange={(event) => {
            setEmployee(event.target.value);
          }}
          value={employee}
        >
          {people.map((one) => (
            <option key={one.employee_id} value={one.employee_id}>
              {nameOf(language, one)} · {one.employee_code}
            </option>
          ))}
        </select>
      </Field>
      <Field
        id="hr-ot-day"
        label={ht(language, "ot_when")}
        note={ht(language, "required")}
      >
        <DateInput
          id="hr-ot-day"
          language={language}
          onChange={setDay}
          value={day}
        />
      </Field>
      <div className="ui-row2">
        <Field
          id="hr-ot-from"
          label={ht(language, "ot_from")}
          note={ht(language, "required")}
        >
          <input
            id="hr-ot-from"
            inputMode="numeric"
            onChange={(event) => {
              setFrom(event.target.value);
            }}
            placeholder="15:30"
            value={from}
          />
        </Field>
        <Field
          id="hr-ot-to"
          label={ht(language, "ot_to")}
          note={ht(language, "required")}
        >
          <input
            id="hr-ot-to"
            inputMode="numeric"
            onChange={(event) => {
              setTo(event.target.value);
            }}
            placeholder="18:30"
            value={to}
          />
        </Field>
      </div>
      <ReasonField
        id="hr-ot-why"
        language={language}
        onChange={setReason}
        value={reason}
      />
      <p className="ui-muted ui-small">{ht(language, "ot_ask_note")}</p>
      <Failure text={error ?? failure} />
    </Dialog>
  );
}

/* ---------- Month summary ---------- */

function MonthSummary({ language, propertyId, api, active }: PartProps) {
  const [month, setMonth] = useState<string | null>(null);
  const read = useCallback(
    () => api.month(propertyId, month),
    [api, propertyId, month],
  );
  const answer = useRead<AttendanceMonth>(active, read);
  const data = answer.data;
  if (data === null)
    return (
      <Waiting
        failed={answer.failed}
        language={language}
        onRetry={answer.reload}
      />
    );
  const shown = monthStart(data.month);
  return (
    <section aria-labelledby="hr-am" className="ui-card pad0">
      <div className="ui-filters">
        <h2 id="hr-am">
          {ht(language, "m_title", monthLabel(language, shown))}
        </h2>
        <span className="ui-actions">
          <button
            className="ui-btn"
            onClick={() => {
              setMonth(previousMonth(shown));
            }}
            type="button"
          >
            <Icon name="back" small />
            <span className="ui-sr">
              {monthLabel(language, previousMonth(shown))}
            </span>
          </button>
          <button
            className="ui-btn"
            onClick={() => {
              setMonth(nextMonth(shown));
            }}
            type="button"
          >
            <Icon name="forward" small />
            <span className="ui-sr">
              {monthLabel(language, nextMonth(shown))}
            </span>
          </button>
        </span>
        {data.locked && (
          <Chip icon="lock" tone="neutral">
            {ht(language, "a_locked")}
          </Chip>
        )}
      </div>
      {data.locked && (
        <p className="ui-notice warn">{ht(language, "m_locked")}</p>
      )}
      {data.people.length === 0 ? (
        <p className="ui-empty">{ht(language, "a_nobody")}</p>
      ) : (
        <div className="ui-tablewrap">
          <table className="ui-table">
            <thead>
              <tr>
                <th scope="col">{ht(language, "e_name")}</th>
                <th className="r" scope="col">
                  {ht(language, "m_worked")}
                </th>
                <th className="r" scope="col">
                  {ht(language, "m_late")}
                </th>
                <th className="r" scope="col">
                  {ht(language, "m_absent")}
                </th>
                <th className="r" scope="col">
                  {ht(language, "m_leave")}
                </th>
                <th className="r" scope="col">
                  {ht(language, "a_days_off")}
                </th>
                <th className="r" scope="col">
                  {ht(language, "m_no_entry")}
                </th>
                <th className="r" scope="col">
                  {ht(language, "a_no_out")}
                </th>
                <th className="r" scope="col">
                  {ht(language, "m_ot", "")}
                </th>
              </tr>
            </thead>
            <tbody>
              {data.people.map((line) => (
                <tr key={line.employee_id}>
                  <th scope="row">
                    {nameOf(language, line)}
                    <span className="ui-sub2 ui-num">{line.employee_code}</span>
                  </th>
                  <td className="r ui-num">{line.days_worked}</td>
                  <td className="r ui-num">{line.times_late}</td>
                  <td className="r ui-num">{line.days_absent}</td>
                  <td className="r ui-num">
                    {line.leave_annual + line.leave_sick + line.leave_unpaid}
                  </td>
                  <td className="r ui-num">{line.days_off}</td>
                  <td className="r ui-num">{line.no_entry}</td>
                  <td className="r ui-num">{line.no_check_out}</td>
                  <td className="r ui-num">
                    {ht(language, "ot_h", line.overtime_hours)}
                    {line.overtime_night_hours > 0 && (
                      <span className="ui-sub2">
                        {ht(language, "ot_night_h", line.overtime_night_hours)}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="ui-tfoot ui-muted">{ht(language, "m_note")}</p>
    </section>
  );
}

/* ---------- QR places ---------- */

function Places({ language, propertyId, api, active }: PartProps) {
  const read = useCallback(() => api.places(propertyId), [api, propertyId]);
  const answer = useRead<PlaceList>(active, read);
  const [pinning, setPinning] = useState<Place | null>(null);
  const [replacing, setReplacing] = useState<Place | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [code, setCode] = useState<string | null>(null);
  const data = answer.data;
  if (data === null)
    return (
      <Waiting
        failed={answer.failed}
        language={language}
        onRetry={answer.reload}
      />
    );
  return (
    <>
      <Done text={done} />
      {code !== null && (
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{code}</p>
        </div>
      )}
      <section aria-labelledby="hr-aq" className="ui-card pad0">
        <div className="ui-filters">
          <h2 id="hr-aq">{ht(language, "a_places")}</h2>
        </div>
        <p className="ui-muted ui-small">
          {ht(language, "q_note", ht(language, "q_metres", data.qr_distance_m))}
          {!data.is_owner && ` ${ht(language, "q_owner_only")}`}
        </p>
        {data.places.length === 0 ? (
          <p className="ui-empty">{ht(language, "q_none")}</p>
        ) : (
          <div className="ui-tablewrap">
            <table className="ui-table">
              <thead>
                <tr>
                  <th scope="col">{ht(language, "q_place")}</th>
                  <th scope="col">{ht(language, "q_pin")}</th>
                  <th scope="col">{ht(language, "q_in_use")}</th>
                </tr>
              </thead>
              <tbody>
                {data.places.map((place) => (
                  <tr key={place.place_id}>
                    <td>
                      {nameOf(language, place)}
                      <span className="ui-sub2 ui-num">{place.code}</span>
                    </td>
                    <td>
                      {place.latitude === null || place.longitude === null ? (
                        <Chip tone="warn">{ht(language, "q_no_pin")}</Chip>
                      ) : (
                        <span className="ui-num">
                          {place.latitude}, {place.longitude}
                        </span>
                      )}
                      {data.is_owner && (
                        <button
                          className="ui-btn link"
                          onClick={() => {
                            setDone(null);
                            setCode(null);
                            setPinning(place);
                          }}
                          type="button"
                        >
                          {ht(language, "q_set_pin")}
                        </button>
                      )}
                    </td>
                    <td>
                      {place.qr_made_at === null ? (
                        <span className="ui-muted">
                          {ht(language, "q_no_qr")}
                        </span>
                      ) : (
                        <span className="ui-num">
                          {ht(
                            language,
                            "q_since",
                            `#${String(place.qr_count)}`,
                            dayText(place.qr_made_at),
                          )}
                        </span>
                      )}
                      {data.is_owner && (
                        <button
                          className="ui-btn link"
                          onClick={() => {
                            setDone(null);
                            setCode(null);
                            setReplacing(place);
                          }}
                          type="button"
                        >
                          {ht(
                            language,
                            place.qr_made_at === null ? "q_make" : "q_replace",
                          )}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {pinning !== null && (
        <PinDialog
          api={api}
          language={language}
          onClose={() => {
            setPinning(null);
          }}
          onSaved={(text) => {
            setPinning(null);
            setDone(text);
            answer.reload();
          }}
          place={pinning}
          propertyId={propertyId}
        />
      )}
      {replacing !== null && (
        <ReasonDialog
          language={language}
          note={ht(language, "q_replace_note")}
          onClose={() => {
            setReplacing(null);
          }}
          onSave={(reason) =>
            api
              .newPlaceQr(propertyId, replacing.place_id, reason ?? "")
              .then((made) => {
                setCode(
                  ht(language, "q_new_code", nameOf(language, replacing), made),
                );
                return ht(language, "e_saved", nameOf(language, replacing));
              })
          }
          onSaved={(text) => {
            setReplacing(null);
            setDone(text);
            answer.reload();
          }}
          optional={replacing.qr_made_at === null}
          submitLabel={ht(
            language,
            replacing.qr_made_at === null ? "q_make" : "q_replace",
          )}
          title={ht(language, "q_replace_t", nameOf(language, replacing))}
        />
      )}
    </>
  );
}

function PinDialog({
  language,
  propertyId,
  api,
  place,
  onSaved,
  onClose,
}: {
  language: Language;
  propertyId: string;
  api: HrApi;
  place: Place;
  onSaved: (text: string) => void;
  onClose: () => void;
}) {
  const [pin, setPin] = useState(
    place.latitude === null || place.longitude === null
      ? ""
      : `${String(place.latitude)}, ${String(place.longitude)}`,
  );
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { busy, failure, run } = useHrBusy(language);
  return (
    <Dialog
      busy={busy}
      closeLabel={ht(language, "cancel")}
      onClose={onClose}
      onSubmit={(event) => {
        event.preventDefault();
        const match =
          /^\s*(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*$/.exec(pin);
        const latitude = match === null ? NaN : Number(match[1]);
        const longitude = match === null ? NaN : Number(match[2]);
        if (
          Number.isNaN(latitude) ||
          Number.isNaN(longitude) ||
          Math.abs(latitude) > 90 ||
          Math.abs(longitude) > 180
        ) {
          setError(ht(language, "q_pin_bad"));
          return;
        }
        setError(null);
        run(
          () =>
            api.setPin(propertyId, place.place_id, {
              latitude,
              longitude,
              ...(reason.trim() === "" ? {} : { reason: reason.trim() }),
            }),
          () => {
            onSaved(ht(language, "q_pin_saved", nameOf(language, place)));
          },
        );
      }}
      submitLabel={ht(language, "save")}
      title={ht(language, "q_set_pin_t", nameOf(language, place))}
    >
      <Field
        id="hr-pin"
        label={ht(language, "q_pin")}
        help={ht(language, "q_pin_help")}
      >
        <input
          id="hr-pin"
          inputMode="decimal"
          onChange={(event) => {
            setPin(event.target.value);
          }}
          placeholder="11.6045, 104.8902"
          value={pin}
        />
      </Field>
      <ReasonField
        id="hr-pin-why"
        language={language}
        onChange={setReason}
        optional
        value={reason}
      />
      <Failure text={error ?? failure} />
    </Dialog>
  );
}
