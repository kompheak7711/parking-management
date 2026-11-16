// Daily and weekly rent, phase 6 step 4a: Tenants › Short stays › Cleaning. One day's daily cleans
// and room checks, and today also the ones not done before. A housekeeper marks a clean done, or
// skipped with a reason; the room check opens the booking page, where any damage is reported.

import { useCallback, useEffect, useRef, useState } from "react";

import { dayText } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { Chip, type Tone } from "../shell/ui";
import type { Language } from "../signInText";
import {
  addDays,
  type Cleaner,
  type CleaningDay,
  type CleaningTask,
  type ShortStaysApi,
  ShortStaysError,
} from "./shortStaysClient";
import { st, type StaysTextKey } from "./text";

const TONES: Record<CleaningTask["status"], Tone> = {
  TO_DO: "warn",
  DONE: "ok",
  SKIPPED: "neutral",
};

/** A cleaner's name in the screen's language (HR keeps both). */
function cleanerName(language: Language, person: Cleaner): string {
  return language === "km" ? person.name_km : person.name;
}

function problemOf(error: unknown): StaysTextKey {
  if (!(error instanceof ShortStaysError)) return "f_failed";
  if (error.status === 403) return "f_step_right";
  if (error.status === 409) return "f_not_now";
  if (error.status === 422) return "e_skip";
  return "f_failed";
}

export function CleaningList({
  language,
  propertyId,
  api,
  may,
  today,
}: {
  language: Language;
  propertyId: string;
  api: ShortStaysApi;
  may: (capability: string) => boolean;
  today: string;
}) {
  const [day, setDay] = useState(today);
  const [found, setFound] = useState<CleaningDay | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<StaysTextKey | null>(null);
  const [skipping, setSkipping] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  // DL-236: all tasks, or only those given to the person reading ("My tasks").
  const sequence = useRef(0);

  const load = useCallback(() => {
    const operation = ++sequence.current;
    setFailed(false);
    void api
      .cleaning(propertyId, day)
      .then((answer) => {
        if (operation === sequence.current) setFound(answer);
      })
      .catch(() => {
        if (operation === sequence.current) setFailed(true);
      });
  }, [api, propertyId, day]);

  useEffect(() => {
    load();
  }, [load]);

  const finish = (task: CleaningTask, skip: boolean) => {
    if (skip && reason.trim() === "") {
      setProblem("e_skip");
      return;
    }
    const operation = ++sequence.current;
    setBusy(true);
    setProblem(null);
    void api
      .finishTask(propertyId, task.task_id, {
        skip,
        ...(skip ? { note: reason.trim() } : {}),
      })
      .then(() => {
        if (operation !== sequence.current) return;
        setSkipping(null);
        setReason("");
        load();
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        setProblem(problemOf(error));
        load();
      })
      .finally(() => {
        setBusy(false);
      });
  };

  // DL-236: the front desk gives a task to one person, or to nobody.
  const assign = (task: CleaningTask, employeeId: string | null) => {
    const operation = ++sequence.current;
    setBusy(true);
    setProblem(null);
    void api
      .assignTask(propertyId, task.task_id, employeeId)
      .then((answer) => {
        if (operation === sequence.current) setFound(answer);
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        setProblem(problemOf(error));
        load();
      })
      .finally(() => {
        setBusy(false);
      });
  };

  const mayClean = may("short_stays.housekeeping");
  const mayAssign = may("short_stays.desk");
  const cleaners = found?.cleaners ?? [];
  // Owner card 14/11/2026: the cleaners see their tasks in the Staff bot, so there is no
  // "My tasks" here.
  const tasks = found?.tasks ?? [];
  const toDo = tasks.filter((task) => task.status === "TO_DO").length;

  // Owner 13/11/2026: one short row per task; late first, then the rest to do; done and skipped
  // folded under the list.
  const open = tasks
    .filter((task) => task.status === "TO_DO")
    .sort((a, b) => Number(b.late) - Number(a.late));
  const finished = tasks.filter((task) => task.status !== "TO_DO");

  const row = (task: CleaningTask) => {
    const due = found !== null && task.task_on <= found.today;
    const doable = task.status === "TO_DO" && due && mayClean;
    return (
      <li className={task.late ? "ss-task late" : "ss-task"} key={task.task_id}>
        <div className="ss-taskwhat">
          <div className="ui-hrow">
            <b className="ui-num">{task.unit_number}</b>
            <span>{st(language, `cl_${task.kind}`)}</span>
            {task.late ? (
              <Chip tone="err">{st(language, "cl_late_chip")}</Chip>
            ) : (
              <Chip tone={TONES[task.status]}>
                {st(language, `cl_${task.status}`)}
              </Chip>
            )}
            {task.late && (
              <span className="ui-small ss-latedate ui-num">
                {st(language, "cl_late", dayText(task.task_on))}
              </span>
            )}
          </div>
          {/* Owner 14/11/2026 01:39: no booking number or guest name on a task. */}
          {task.note !== null && (
            <p className="ui-small ui-muted">{task.note}</p>
          )}
          {task.status !== "TO_DO" && task.done_by_name !== null && (
            <p className="ui-small ui-muted">
              {st(
                language,
                task.status === "DONE" ? "cl_done_by" : "cl_not_by",
                task.done_by_name,
              )}
            </p>
          )}
          {task.status === "TO_DO" &&
            (mayAssign && cleaners.length > 0 ? (
              <label className="ss-assign">
                <span className="ui-small">{st(language, "cl_assign")}</span>
                <select
                  disabled={busy}
                  onChange={(event) => {
                    const chosen = event.currentTarget.value;
                    assign(task, chosen === "" ? null : chosen);
                  }}
                  value={task.assigned_to ?? ""}
                >
                  <option value="">{st(language, "cl_nobody")}</option>
                  {/* A person who lost the right keeps the task until it is moved. */}
                  {task.assigned_to !== null &&
                    !cleaners.some(
                      (person) => person.employee_id === task.assigned_to,
                    ) && (
                      <option value={task.assigned_to}>
                        {task.assigned_name ?? task.assigned_to}
                      </option>
                    )}
                  {cleaners.map((person) => (
                    <option key={person.employee_id} value={person.employee_id}>
                      {person.telegram
                        ? cleanerName(language, person)
                        : st(
                            language,
                            "cl_no_tg",
                            cleanerName(language, person),
                          )}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <p className="ui-small ss-given">
                {task.assigned_name === null
                  ? st(language, "cl_nobody_yet")
                  : st(language, "cl_given", task.assigned_name)}
              </p>
            ))}
          {doable && skipping === task.task_id && (
            <div className="ui-field">
              <label htmlFor={`ss-skip-${task.task_id}`}>
                {st(language, "cl_reason")}
                <span className="req">{st(language, "required")}</span>
              </label>
              <input
                autoComplete="off"
                disabled={busy}
                id={`ss-skip-${task.task_id}`}
                maxLength={500}
                onChange={(event) => {
                  setReason(event.currentTarget.value);
                }}
                value={reason}
              />
            </div>
          )}
        </div>
        {doable && task.kind === "ROOM_CHECK" && task.booking_id !== null && (
          <div className="ss-taskdo">
            <a
              className="ui-btn primary"
              href={hashForPage("shortstays", `st:${task.booking_id}`)}
            >
              {st(language, "cl_room")}
            </a>
          </div>
        )}
        {doable && task.kind !== "ROOM_CHECK" && (
          <div className="ss-taskdo">
            <button
              className="ui-btn primary"
              disabled={busy}
              onClick={() => {
                finish(task, false);
              }}
              type="button"
            >
              <Icon name="check" small />
              {st(language, "cl_done_b")}
            </button>
            <button
              className="ui-btn"
              disabled={busy}
              onClick={() => {
                if (skipping === task.task_id) {
                  finish(task, true);
                } else {
                  setSkipping(task.task_id);
                  setReason("");
                  setProblem(null);
                }
              }}
              type="button"
            >
              {st(language, "cl_skip")}
            </button>
          </div>
        )}
      </li>
    );
  };

  return (
    <>
      <div className="ui-filters">
        <div className="ui-seg" role="group">
          <button
            onClick={() => {
              setDay(addDays(day, -1));
            }}
            type="button"
          >
            <Icon name="back" small />
            {st(language, "cl_prev")}
          </button>
          <button
            disabled={day === today}
            onClick={() => {
              setDay(today);
            }}
            type="button"
          >
            {st(language, "this_week")}
          </button>
          <button
            onClick={() => {
              setDay(addDays(day, 1));
            }}
            type="button"
          >
            {st(language, "cl_next")}
            <Icon name="forward" small />
          </button>
        </div>
        <span className="ui-muted ui-num">{dayText(day)}</span>
        {found !== null && toDo > 0 && (
          <Chip tone="warn">{st(language, "cl_count", toDo)}</Chip>
        )}
      </div>
      {problem !== null && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>{st(language, problem)}</p>
        </div>
      )}
      {failed ? (
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{st(language, "failed")}</p>
          <button className="ui-btn" onClick={load} type="button">
            {st(language, "retry")}
          </button>
        </div>
      ) : found === null ? (
        <p className="ui-muted" role="status">
          {st(language, "loading")}
        </p>
      ) : tasks.length === 0 ? (
        <p className="ui-empty">{st(language, "cl_none")}</p>
      ) : (
        <>
          {open.length > 0 && (
            <div className="ui-card pad0">
              <ul aria-label={st(language, "tab_clean")} className="ss-tasks">
                {open.map(row)}
              </ul>
            </div>
          )}
          {open.length === 0 && (
            <p className="ui-empty">{st(language, "cl_all_done")}</p>
          )}
          {finished.length > 0 && (
            <details className="ui-card pad0 ss-taskdone">
              <summary>{st(language, "cl_finished", finished.length)}</summary>
              <ul
                aria-label={st(language, "cl_finished_list")}
                className="ss-tasks"
              >
                {finished.map(row)}
              </ul>
            </details>
          )}
        </>
      )}
    </>
  );
}
