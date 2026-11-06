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

  const mayClean = may("short_stays.housekeeping");
  const tasks = found?.tasks ?? [];
  const toDo = tasks.filter((task) => task.status === "TO_DO").length;

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
        <ul
          aria-label={st(language, "tab_clean")}
          className="ui-plain ss-clean"
        >
          {tasks.map((task) => {
            const due = task.task_on <= found.today;
            const open = task.status === "TO_DO" && due && mayClean;
            return (
              <li className="ui-card" key={task.task_id}>
                <div className="ui-hrow">
                  <b className="ui-num">{task.unit_number}</b>
                  <span>{st(language, `cl_${task.kind}`)}</span>
                  <Chip tone={TONES[task.status]}>
                    {st(language, `cl_${task.status}`)}
                  </Chip>
                  {task.late && (
                    <span className="ui-small ui-muted ui-num">
                      {st(language, "cl_late", dayText(task.task_on))}
                    </span>
                  )}
                </div>
                {task.booking_id !== null && (
                  <p className="ui-small">
                    <a
                      href={hashForPage("shortstays", `st:${task.booking_id}`)}
                    >
                      {task.booking_number}
                    </a>
                    {task.guest_name !== null && ` · ${task.guest_name}`}
                  </p>
                )}
                {task.note !== null && (
                  <p className="ui-small ui-muted">{task.note}</p>
                )}
                {open &&
                  task.kind === "ROOM_CHECK" &&
                  task.booking_id !== null && (
                    <div className="ui-actions">
                      <a
                        className="ui-btn primary"
                        href={hashForPage(
                          "shortstays",
                          `st:${task.booking_id}`,
                        )}
                      >
                        {st(language, "cl_room")}
                      </a>
                    </div>
                  )}
                {open && task.kind !== "ROOM_CHECK" && (
                  <div className="ui-stack">
                    {skipping === task.task_id && (
                      <div className="ui-field">
                        <label htmlFor={`ss-skip-${task.task_id}`}>
                          {st(language, "cl_reason")}
                          <span className="req">
                            {st(language, "required")}
                          </span>
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
                    <div className="ui-actions">
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
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
