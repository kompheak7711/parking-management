// DL-244 (design v1, owner OK 16/11/2026): the Unit page lists the Unit's Joint Inspections, the
// newest first, so staff see every move-in and move-out check of the room in one place. Each
// opens on Property › Inspections. The card is a help: when it cannot be read it stays away.

import "./joint.css";

import { useEffect, useState } from "react";

import { hashForPage } from "../shell/navigation";
import { Chip } from "../shell/ui";
import type { Language } from "../signInText";
import { STATUS_TONE } from "./JointInspectionForm";
import type { JointApi, JointRow } from "./jointClient";
import { dayText, jt } from "./text";

const SHOWN = 5;

export function UnitJointCard({
  language,
  propertyId,
  unitId,
  api,
}: {
  language: Language;
  propertyId: string;
  unitId: string;
  api: Pick<JointApi, "list">;
}) {
  const [rows, setRows] = useState<JointRow[] | null>(null);

  useEffect(() => {
    let live = true;
    void api
      .list(propertyId)
      .then((found) => {
        if (!live) return;
        setRows(
          found
            .filter((row) => row.unit_id === unitId)
            .sort((a, b) =>
              a.inspection_date === b.inspection_date
                ? b.inspection_number.localeCompare(a.inspection_number)
                : b.inspection_date.localeCompare(a.inspection_date),
            ),
        );
      })
      .catch(() => {
        if (live) setRows(null);
      });
    return () => {
      live = false;
    };
  }, [api, propertyId, unitId]);

  if (rows === null) return null;
  return (
    <section aria-labelledby="unit-joint" className="ui-card">
      <h2 id="unit-joint">
        {jt(language, "ji_many")}{" "}
        <span className="ui-count ui-num">{rows.length}</span>
      </h2>
      {rows.length === 0 ? (
        <p className="ui-small ui-muted">{jt(language, "none")}</p>
      ) : (
        <ul className="ui-plain">
          {rows.slice(0, SHOWN).map((row) => (
            <li className="ui-line" key={row.inspection_id}>
              <span>
                <a
                  className="ui-num"
                  href={hashForPage("inspections", `ji:${row.inspection_id}`)}
                >
                  {row.inspection_number}
                </a>{" "}
                · {jt(language, row.kind)}
                <span className="ui-sub2">
                  <span className="ui-num">{dayText(row.inspection_date)}</span>{" "}
                  · {row.tenant_name}
                  {row.status !== "DRAFT" &&
                    ` · ${
                      row.problems === 0
                        ? jt(language, "no_problems")
                        : `${jt(language, "c_problems")} ${String(row.problems)}`
                    }`}
                </span>
              </span>
              <Chip tone={STATUS_TONE[row.status]}>
                {jt(language, row.status)}
              </Chip>
            </li>
          ))}
        </ul>
      )}
      {rows.length > SHOWN && (
        <a className="ui-btn" href={hashForPage("inspections")}>
          {jt(language, "unit_all", rows.length)}
        </a>
      )}
    </section>
  );
}
