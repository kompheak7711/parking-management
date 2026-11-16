// Daily and weekly rent, phase 6 step 4a: Tenants › Short stays › Cleaning. One day's daily cleans
// and Unit checks, and today also the ones not done before. DL-242 (owner 16/11/2026): each task
// goes to a cleaner by itself (staff may change it), the cleaner reports it in the Staff bot, and
// this list only shows what happened; a Unit check with a problem is finished on the booking.

import { useCallback, useEffect, useRef, useState } from "react";

import { dayText } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { Chip } from "../shell/ui";
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

/**
 * Owner 16/11/2026 (DL-242): what happened to a task, as text. The cleaner reports in the Staff
 * bot; only a Unit check where the cleaner found a problem asks the front desk to write it on the
 * booking.
 */
function TaskState({
  language,
  task,
  mayCheck,
  cleaners,
}: {
  language: Language;
  task: CleaningTask;
  mayCheck: boolean;
  cleaners: readonly Cleaner[];
}) {
  const name = task.done_by_name ?? "—";
  if (task.status === "DONE")
    return (
      <p className="ss-state ok">
        <Icon name="check" small />
        {st(
          language,
          task.kind === "ROOM_CHECK" ? "cl_checked_by" : "cl_cleaned_by",
          name,
        )}
      </p>
    );
  if (task.status === "SKIPPED")
    return (
      <p className="ss-state">
        {st(language, "cl_not_cleaned", task.note ?? name)}
      </p>
    );
  if (task.problem_found_at !== null)
    return (
      <div className="ss-state err">
        <span>
          <Icon name="alert" small />
          {st(language, "cl_problem_by", task.problem_found_by_name ?? "—")}
        </span>
        {mayCheck && task.booking_id !== null && (
          <a
            className="ui-btn link"
            href={hashForPage("shortstays", `st:${task.booking_id}`)}
          >
            {st(language, "cl_problem_do")}
          </a>
        )}
      </div>
    );
  return (
    <p className="ss-state muted">
      {task.assigned_name === null
        ? st(language, "cl_wait_nobody")
        : cleaners.some(
              (person) =>
                person.employee_id === task.assigned_to && !person.telegram,
            )
          ? st(language, "cl_wait_no_tg", task.assigned_name)
          : st(language, "cl_wait", task.assigned_name)}
    </p>
  );
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

  const mayCheck = may("short_stays.housekeeping");
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

  const row = (task: CleaningTask) => (
    <li className={task.late ? "ss-task late" : "ss-task"} key={task.task_id}>
      {/* Owner 16/11/2026: the "Assign to" box sits top right, on the title line. */}
      <div className="ui-hrow ss-tasktitle">
        <b className="ui-num">{task.unit_number}</b>
        <span>{st(language, `cl_${task.kind}`)}</span>
        {task.late && (
          <>
            <Chip tone="err">{st(language, "cl_late_chip")}</Chip>
            <span className="ui-small ss-latedate ui-num">
              {st(language, "cl_late", dayText(task.task_on))}
            </span>
          </>
        )}
      </div>
      {/* Owner 14/11/2026 01:39: no booking number or guest name on a task. */}
      {task.status === "TO_DO" &&
        (mayAssign && cleaners.length > 0 ? (
          <label className="ss-assign ss-taskside">
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
                    : st(language, "cl_no_tg", cleanerName(language, person))}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <p className="ui-small ss-given ss-taskside">
            {task.assigned_name === null
              ? st(language, "cl_nobody_yet")
              : st(language, "cl_given", task.assigned_name)}
          </p>
        ))}
      <TaskState
        cleaners={cleaners}
        language={language}
        mayCheck={mayCheck}
        task={task}
      />
    </li>
  );

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
