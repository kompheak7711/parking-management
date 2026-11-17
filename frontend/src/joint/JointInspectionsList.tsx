// DL-243: the Joint Inspections section of Property › Inspections (design picture 6): Number,
// Kind, Unit, Lease and tenant, Date, Problems and Status, with Move-in/Move-out and
// Draft/Done/Replaced filters. On a phone each inspection is a card. Display only.

import "./joint.css";

import { useCallback, useEffect, useRef, useState } from "react";

import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { openPageInAddress } from "../shell/useHashPage";
import { Chip } from "../shell/ui";
import type { Language } from "../signInText";
import { STATUS_TONE } from "./JointInspectionForm";
import type { JointApi, JointKind, JointRow, JointStatus } from "./jointClient";
import { dayText, jt } from "./text";

export function JointInspectionsList({
  language,
  propertyId,
  api,
  active,
}: {
  language: Language;
  propertyId: string;
  api: JointApi;
  active: boolean;
}) {
  const [rows, setRows] = useState<JointRow[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [kind, setKind] = useState<JointKind | "">("");
  const [status, setStatus] = useState<JointStatus | "">("");
  const sequence = useRef(0);

  const load = useCallback(() => {
    if (propertyId === "") return;
    const operation = ++sequence.current;
    setFailed(false);
    void api
      .list(propertyId)
      .then((found) => {
        if (operation === sequence.current) setRows(found);
      })
      .catch(() => {
        if (operation === sequence.current) setFailed(true);
      });
  }, [api, propertyId]);

  // Read again each time the page is opened, so it shows what others did meanwhile.
  useEffect(() => {
    if (active) load();
  }, [active, load]);

  const shown = (rows ?? []).filter(
    (row) =>
      (kind === "" || row.kind === kind) &&
      (status === "" || row.status === status),
  );
  const filtering = kind !== "" || status !== "";

  return (
    <section aria-labelledby="ji-list-t" className="ui-stack">
      <h2 id="ji-list-t">{jt(language, "ji_many")}</h2>
      <div className="ui-filters">
        <label className="ui-sr" htmlFor="ji-f-kind">
          {jt(language, "f_kind")}
        </label>
        <select
          className="ui-sel"
          id="ji-f-kind"
          onChange={(event) => {
            setKind(event.currentTarget.value as JointKind | "");
          }}
          value={kind}
        >
          <option value="">
            {jt(language, "f_kind")}: {jt(language, "all")}
          </option>
          <option value="MOVE_IN">{jt(language, "MOVE_IN")}</option>
          <option value="MOVE_OUT">{jt(language, "MOVE_OUT")}</option>
        </select>
        <label className="ui-sr" htmlFor="ji-f-status">
          {jt(language, "f_status")}
        </label>
        <select
          className="ui-sel"
          id="ji-f-status"
          onChange={(event) => {
            setStatus(event.currentTarget.value as JointStatus | "");
          }}
          value={status}
        >
          <option value="">
            {jt(language, "f_status")}: {jt(language, "all")}
          </option>
          <option value="DRAFT">{jt(language, "DRAFT")}</option>
          <option value="DONE">{jt(language, "DONE")}</option>
          <option value="REPLACED">{jt(language, "REPLACED")}</option>
        </select>
      </div>
      {failed && (
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{jt(language, "failed")}</p>
          <button className="ui-btn" onClick={load} type="button">
            {jt(language, "retry")}
          </button>
        </div>
      )}
      <div className="ui-card pad0">
        {rows === null ? (
          !failed && (
            <p className="ui-muted ui-empty" role="status">
              {jt(language, "loading")}
            </p>
          )
        ) : shown.length === 0 ? (
          <p className="ui-empty">
            {jt(language, filtering ? "f_none" : "none")}
          </p>
        ) : (
          <div className="ui-tablewrap">
            <table className="ui-table ui-pcards">
              <thead>
                <tr>
                  <th scope="col">{jt(language, "c_no")}</th>
                  <th scope="col">{jt(language, "c_kind")}</th>
                  <th scope="col">{jt(language, "c_unit")}</th>
                  <th scope="col">{jt(language, "c_lease")}</th>
                  <th scope="col">{jt(language, "c_date")}</th>
                  <th scope="col">{jt(language, "c_problems")}</th>
                  <th scope="col">{jt(language, "c_status")}</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((row) => (
                  <tr
                    className="ui-row"
                    key={row.inspection_id}
                    onClick={() => {
                      openPageInAddress(
                        "inspections",
                        false,
                        `ji:${row.inspection_id}`,
                      );
                    }}
                  >
                    <td>
                      <a
                        className="ui-no ui-num"
                        href={hashForPage(
                          "inspections",
                          `ji:${row.inspection_id}`,
                        )}
                        onClick={(event) => {
                          event.stopPropagation();
                        }}
                      >
                        {row.inspection_number}
                      </a>
                      {row.replaces_number !== null && (
                        <span className="ui-sub2">
                          {jt(language, "replaces", row.replaces_number)}
                        </span>
                      )}
                    </td>
                    <td>{jt(language, row.kind)}</td>
                    <td className="ui-num">{row.unit_number}</td>
                    <td className="pc-full">
                      {row.lease_number !== null && (
                        <span className="ui-num">{row.lease_number} · </span>
                      )}
                      {row.tenant_name}
                    </td>
                    <td className="ui-num">{dayText(row.inspection_date)}</td>
                    <td>
                      {row.status === "DRAFT" ? (
                        <span className="ui-muted">
                          {jt(language, "marked_of", row.marked, row.lines)}
                        </span>
                      ) : row.problems === 0 ? (
                        <span className="ui-muted">
                          {jt(language, "no_problems")}
                        </span>
                      ) : (
                        <>
                          <span className="ui-num">{row.problems}</span>
                          {row.kind === "MOVE_OUT" &&
                            row.new_problems !== null &&
                            row.new_problems > 0 && (
                              <span className="ui-sub2">
                                {jt(language, "new_n", row.new_problems)}
                              </span>
                            )}
                        </>
                      )}
                    </td>
                    <td className="pc-end">
                      <Chip tone={STATUS_TONE[row.status]}>
                        {jt(language, row.status)}
                      </Chip>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
