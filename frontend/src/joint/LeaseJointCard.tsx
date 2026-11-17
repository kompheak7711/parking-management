// DL-243 (answer 5, warnings only): the Joint Inspection card on a signed Lease's page and on
// its Move-out page. It shows the move-in and move-out inspections of the Lease, starts one
// (`joint_inspections.record`) or goes on with a Draft, and warns when the move-in inspection
// is not done, or (on the Move-out page) when the move-out one is not done before the Final
// Settlement. It never stops a step.

import "./joint.css";

import { useEffect, useState } from "react";

import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { openPageInAddress } from "../shell/useHashPage";
import { Chip } from "../shell/ui";
import type { Language } from "../signInText";
import { STATUS_TONE } from "./JointInspectionForm";
import {
  type JointApi,
  JointError,
  type JointKind,
  type JointRow,
} from "./jointClient";
import { dayText, jt } from "./text";

/** The inspection in force of each kind: a Draft or the Done one (never a Replaced one). */
export function currentOf(
  rows: readonly JointRow[],
  kind: JointKind,
): { draft: JointRow | null; done: JointRow | null } {
  const mine = rows.filter((row) => row.kind === kind);
  return {
    draft: mine.find((row) => row.status === "DRAFT") ?? null,
    done: mine.find((row) => row.status === "DONE") ?? null,
  };
}

export function LeaseJointCard({
  language,
  propertyId,
  leaseId,
  api,
  may,
  kinds,
  onRows,
}: {
  language: Language;
  propertyId: string;
  leaseId: string;
  api: JointApi;
  may: (capability: string) => boolean;
  /** The Lease page shows both kinds; the Move-out page shows the move-out one. */
  kinds: readonly JointKind[];
  /** Tells the page what was read (the Move-out page uses it to hide the old form). */
  onRows?: (rows: JointRow[]) => void;
}) {
  const [rows, setRows] = useState<JointRow[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    void api
      .list(propertyId, leaseId)
      .then((found) => {
        if (!live) return;
        setRows(found);
        onRows?.(found);
      })
      .catch(() => {
        // The card is a help, not a step: when it cannot be read it stays away.
        if (live) setRows(null);
      });
    return () => {
      live = false;
    };
  }, [api, propertyId, leaseId, onRows]);

  if (rows === null) return null;
  const canStart = may("joint_inspections.record");

  const start = (kind: JointKind) => {
    setBusy(true);
    setError(null);
    void api
      .start(propertyId, { lease_id: leaseId, kind })
      .then((made) => {
        openPageInAddress("inspections", false, `ji:${made.inspection_id}`);
      })
      .catch((caught: unknown) => {
        setError(
          caught instanceof JointError && caught.detail !== null
            ? caught.detail
            : jt(language, "e_other"),
        );
      })
      .finally(() => {
        setBusy(false);
      });
  };

  const link = (row: JointRow, key: "open" | "go_on") => (
    <a
      className="ui-btn"
      href={hashForPage("inspections", `ji:${row.inspection_id}`)}
    >
      {jt(language, key, row.inspection_number)}
    </a>
  );

  return (
    <section
      aria-labelledby={`ji-lease-${leaseId}`}
      className="ui-card ji-lease"
    >
      <h2 id={`ji-lease-${leaseId}`}>{jt(language, "lease_t")}</h2>
      <ul className="ui-plain">
        {kinds.map((kind) => {
          const { draft, done } = currentOf(rows, kind);
          const missing = draft === null && done === null;
          return (
            <li className="ui-line" key={kind}>
              <span>
                <b>{jt(language, kind)}</b>
                {done !== null && (
                  <span className="ui-sub2">
                    <span className="ui-num">{done.inspection_number}</span> ·{" "}
                    {dayText(done.inspection_date)} ·{" "}
                    {done.problems === 0
                      ? jt(language, "no_problems")
                      : `${jt(language, "c_problems")} ${String(done.problems)}`}
                  </span>
                )}
                {missing && (
                  <span className="ui-sub2 warn">
                    {kind === "MOVE_IN"
                      ? jt(language, "in_missing")
                      : jt(language, "out_missing")}
                  </span>
                )}
              </span>
              <span className="ui-actions">
                {done !== null && (
                  <Chip tone={STATUS_TONE.DONE}>{jt(language, "DONE")}</Chip>
                )}
                {draft !== null ? (
                  link(draft, "go_on")
                ) : done !== null ? (
                  link(done, "open")
                ) : canStart ? (
                  <button
                    className="ui-btn primary"
                    disabled={busy}
                    onClick={() => {
                      start(kind);
                    }}
                    type="button"
                  >
                    <Icon name="plus" />
                    {jt(
                      language,
                      kind === "MOVE_IN" ? "start_in" : "start_out",
                    )}
                  </button>
                ) : null}
              </span>
            </li>
          );
        })}
      </ul>
      {!canStart && (
        <p className="ui-small ui-muted">{jt(language, "not_allowed")}</p>
      )}
      {error !== null && (
        <p className="ui-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
