// Telegram bots step 4c (DL-176): the readings the meter reader typed in the Staff bot wait on
// the Meter readings tab until someone who may record readings checks them (DESIGN.md: "Meter
// readings sent by Telegram go to Utilities, Check readings"). The check shows the same
// columns as the import check. Ticked readings are confirmed (saved as normal meter readings on
// the day they were read), sent back to the reader to read again, or not used.

import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { dayText } from "../shell/format";
import { Icon } from "../shell/icons";
import { Chip, Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import type {
  StaffDecision,
  StaffReading,
  StaffReadingRun,
  StaffReadingsApi,
} from "./staffReadingsClient";
import { amountText } from "./utilitiesData";
import { utt } from "./text";

export interface StaffReadingsProps {
  language: Language;
  propertyId: string;
  api: StaffReadingsApi;
  /** Read again each time the page is opened. */
  active: boolean;
  /** After readings were confirmed, so the screen shows them. */
  onSaved: () => void;
}

interface Result {
  ok: boolean;
  text: string;
}

function problemOf(
  reading: StaffReading,
): "sb_already" | "sb_lower" | "sb_high" | null {
  if (reading.already) return "sb_already";
  if (reading.flag === "LOWER") return "sb_lower";
  if (reading.flag === "HIGH") return "sb_high";
  return null;
}

function number(value: string | null): string {
  return value === null ? "—" : amountText(value);
}

export function StaffReadings({
  language,
  propertyId,
  api,
  active,
  onSaved,
}: StaffReadingsProps) {
  const [runs, setRuns] = useState<StaffReadingRun[]>([]);
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState<ReadonlySet<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const sequence = useRef(0);

  const load = useCallback(() => {
    if (propertyId === "") return;
    const operation = ++sequence.current;
    void api
      .waiting(propertyId)
      .then((found) => {
        if (operation === sequence.current) setRuns(found);
      })
      .catch(() => {
        // Without the list the tab works as before; the card shows when it can be read.
        if (operation === sequence.current) setRuns([]);
      });
  }, [api, propertyId]);

  useEffect(() => {
    if (active) load();
  }, [active, load]);

  const all = runs.flatMap((run) => run.readings);
  if (all.length === 0 && result === null) return null;

  const openCheck = () => {
    // Readings that look right are ticked; the ones to look at again are not.
    setPicked(
      new Set(
        all
          .filter((reading) => problemOf(reading) === null)
          .map((reading) => reading.proposal_id),
      ),
    );
    setResult(null);
    setOpen(true);
  };

  const decide = (decision: StaffDecision) => {
    if (busy) return;
    const ids = all
      .map((reading) => reading.proposal_id)
      .filter((id) => picked.has(id));
    if (ids.length === 0) {
      setResult({ ok: false, text: utt(language, "sb_none") });
      return;
    }
    setBusy(true);
    void api
      .decide(propertyId, ids, decision)
      .then((answer) => {
        const units = all
          .filter((reading) => picked.has(reading.proposal_id))
          .map((reading) => reading.unit);
        let text =
          decision === "ASK_AGAIN"
            ? utt(language, "sb_done_ASK_AGAIN", [...new Set(units)].join(", "))
            : utt(language, `sb_done_${decision}`, answer.done);
        if (answer.already.length > 0)
          text += ` ${utt(language, "sb_left", answer.already.join(", "))}`;
        setResult({ ok: answer.already.length === 0, text });
        setOpen(false);
        if (decision === "CONFIRMED" && answer.done > 0) onSaved();
        load();
      })
      .catch(() => {
        setResult({ ok: false, text: utt(language, "sb_failed") });
      })
      .finally(() => {
        setBusy(false);
      });
  };

  const toggle = (id: string) => {
    setPicked((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <>
      {all.length > 0 && (
        <div className="ui-notice" role="status">
          <Icon name="meter" />
          <p>{utt(language, "sb_waiting", all.length)}</p>
          <button className="ui-btn" onClick={openCheck} type="button">
            {utt(language, "sb_open")}
          </button>
        </div>
      )}
      {result !== null && !open && (
        <div
          className={result.ok ? "ui-notice" : "ui-notice warn"}
          role="status"
        >
          <Icon name={result.ok ? "check" : "alert"} />
          <p>{result.text}</p>
        </div>
      )}
      {open && (
        <Dialog
          actions={
            <>
              <button
                className="ui-btn"
                disabled={busy}
                onClick={() => {
                  decide("NOT_USED");
                }}
                type="button"
              >
                {utt(language, "sb_not_used")}
              </button>
              <button
                className="ui-btn"
                disabled={busy}
                onClick={() => {
                  decide("ASK_AGAIN");
                }}
                type="button"
              >
                {utt(language, "sb_again")}
              </button>
            </>
          }
          busy={busy}
          closeLabel={utt(language, "close")}
          onClose={() => {
            setOpen(false);
          }}
          onSubmit={(event: FormEvent<HTMLFormElement>) => {
            event.preventDefault();
            decide("CONFIRMED");
          }}
          submitLabel={utt(language, "sb_confirm")}
          title={utt(language, "sb_title")}
          wide
        >
          {result !== null && !result.ok && (
            <div className="ui-notice warn" role="alert">
              <Icon name="alert" />
              <p>{result.text}</p>
            </div>
          )}
          {runs.map((run) => (
            <div
              aria-label={utt(
                language,
                "sb_sent",
                run.sent_by,
                dayText(run.reading_date),
              )}
              className="ui-tablewrap ui-imlist"
              key={run.run_id}
              role="region"
              tabIndex={0}
            >
              <p className="ui-small">
                <b>
                  {utt(
                    language,
                    "sb_sent",
                    run.sent_by,
                    dayText(run.reading_date),
                  )}
                </b>
              </p>
              <table className="ui-table fit">
                <thead>
                  <tr>
                    <th scope="col">{utt(language, "sb_pick")}</th>
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
                  {run.readings.map((reading) => {
                    const problem = problemOf(reading);
                    const label = `${reading.unit} ${utt(language, reading.utility_type)}`;
                    return (
                      <tr
                        className={problem === null ? undefined : "ui-imbad"}
                        key={reading.proposal_id}
                      >
                        <td>
                          <input
                            aria-label={label}
                            checked={picked.has(reading.proposal_id)}
                            disabled={busy}
                            onChange={() => {
                              toggle(reading.proposal_id);
                            }}
                            type="checkbox"
                          />
                        </td>
                        <td>
                          <b>{reading.unit}</b>
                        </td>
                        <td>{utt(language, reading.utility_type)}</td>
                        <td className="r ui-num ui-muted">
                          {number(reading.last_value)}
                        </td>
                        <td className="r ui-num">
                          {number(reading.reading_value)}
                        </td>
                        <td className="wrap">
                          {problem === null ? (
                            <Chip icon="check" tone="ok">
                              {utt(language, "im_ready")}
                            </Chip>
                          ) : (
                            <span className="ui-rdmsg warn">
                              <Icon name="alert" small />{" "}
                              {utt(language, problem)}
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ))}
          <div className="ui-imnotes ui-small">
            <p>{utt(language, "sb_note")}</p>
          </div>
        </Dialog>
      )}
    </>
  );
}
