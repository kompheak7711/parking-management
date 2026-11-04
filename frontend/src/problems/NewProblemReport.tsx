// V1.1 part 7 (DL-124): New Problem report from the front desk (phone, walk-in, seen by staff),
// mock-up round 32. A Unit Problem names the Unit (and a place in it, if known); a Building
// problem names the shared place and floor. "Open reports here" offers Same problem: the report
// is saved with its own number, joined to that report. Safety is always urgent.
// DL-132: "#/problems/finding:<id>" makes the report from a move-out inspection finding: the
// Unit and the text come from the finding and the source is Inspection.

import { type FormEvent, useCallback, useEffect, useState } from "react";

import { Icon } from "../shell/icons";
import { dayText } from "../shell/format";
import { hashForPage } from "../shell/navigation";
import { openPageInAddress } from "../shell/useHashPage";
import type { Language } from "../signInText";
import { isOpen, typeIcon, typeName, whereText } from "./ProblemReportsPage";
import {
  type BestTime,
  type FindingSource,
  type NewProblemReport,
  type ProblemChoices,
  type ProblemKind,
  type ProblemReport,
  type ProblemsApi,
  ProblemsError,
} from "./problemsClient";
import { pt } from "./text";

type Source = NewProblemReport["source"];

export function problemRefusal(language: Language, error: unknown): string {
  if (error instanceof ProblemsError) {
    if (error.status === 403) return pt(language, "f_right");
    if (error.status === 412) return pt(language, "f_stale");
    if (error.status === 409 || error.status === 422 || error.status === 404)
      return pt(language, "f_refused");
  }
  return pt(language, "f_failed");
}

function Missing({
  id,
  show,
  text,
}: {
  id: string;
  show: boolean;
  text: string;
}) {
  if (!show) return null;
  return (
    <p className="ui-error" id={id}>
      <Icon name="alert" small />
      <span>{text}</span>
    </p>
  );
}

function BackToList({ language }: { language: Language }) {
  return (
    <button
      className="ui-crumb"
      onClick={() => {
        openPageInAddress("problems");
      }}
      type="button"
    >
      <Icon name="back" small />
      {pt(language, "back")}
    </button>
  );
}

/** DL-132: reads the finding, then opens the form filled from it. */
export function NewProblemReportFromFinding({
  findingId,
  ...form
}: {
  findingId: string;
  language: Language;
  propertyId: string;
  api: ProblemsApi;
  reports: ProblemReport[];
  onSaved: (made: ProblemReport) => void;
}) {
  const { api, language, propertyId } = form;
  const [found, setFound] = useState<FindingSource | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const read = useCallback(() => {
    setProblem(null);
    void api
      .finding(propertyId, findingId)
      .then(setFound)
      .catch((error: unknown) => {
        setProblem(
          error instanceof ProblemsError && error.status === 422
            ? pt(language, "fi_missing")
            : problemRefusal(language, error),
        );
      });
  }, [api, findingId, language, propertyId]);
  useEffect(() => {
    read();
  }, [read]);
  if (found === null || found.report !== null || found.replaced)
    return (
      <>
        <BackToList language={language} />
        {problem !== null ? (
          <div className="ui-notice warn" role="status">
            <Icon name="alert" />
            <p>{problem}</p>
            <button className="ui-btn" onClick={read} type="button">
              {pt(language, "retry")}
            </button>
          </div>
        ) : found === null ? (
          <p className="ui-muted" role="status">
            {pt(language, "loading")}
          </p>
        ) : found.report !== null ? (
          <div className="ui-notice" role="status">
            <Icon name="info" />
            <p>
              {pt(language, "fi_has")}{" "}
              <a
                className="ui-num"
                href={hashForPage("problems", `pr:${found.report.report_id}`)}
              >
                {found.report.report_number}
              </a>
            </p>
          </div>
        ) : (
          <div className="ui-notice warn" role="status">
            <Icon name="alert" />
            <p>{pt(language, "fi_replaced")}</p>
          </div>
        )}
      </>
    );
  return <NewProblemReportForm {...form} finding={found} />;
}

export function NewProblemReportForm({
  language,
  propertyId,
  api,
  reports,
  onSaved,
  finding,
}: {
  language: Language;
  propertyId: string;
  api: ProblemsApi;
  /** The list as read, for "Open reports here". */
  reports: ProblemReport[];
  onSaved: (made: ProblemReport) => void;
  /** DL-132: a report made from a move-out inspection finding. */
  finding?: FindingSource;
}) {
  const [choices, setChoices] = useState<ProblemChoices | null>(null);
  const [readFailed, setReadFailed] = useState(false);
  const [kind, setKind] = useState<ProblemKind>("UNIT");
  const [source, setSource] = useState<Source>(
    finding === undefined ? "PHONE" : "INSPECTION",
  );
  const [unitId, setUnitId] = useState(finding?.unit_id ?? "");
  const [place, setPlace] = useState("");
  const [sharedId, setSharedId] = useState("");
  const [floor, setFloor] = useState("");
  const [reportedBy, setReportedBy] = useState("");
  const [typeId, setTypeId] = useState("");
  const [description, setDescription] = useState(finding?.description ?? "");
  const [urgent, setUrgent] = useState<boolean | null>(null);
  const [mayEnter, setMayEnter] = useState(false);
  const [best, setBest] = useState<BestTime>("ANY");
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const read = useCallback(() => {
    setReadFailed(false);
    void api
      .choices(propertyId)
      .then(setChoices)
      .catch(() => {
        setReadFailed(true);
      });
  }, [api, propertyId]);
  useEffect(() => {
    read();
  }, [read]);

  const back = <BackToList language={language} />;
  if (choices === null)
    return (
      <>
        {back}
        {readFailed ? (
          <div className="ui-notice warn" role="status">
            <Icon name="alert" />
            <p>{pt(language, "failed")}</p>
            <button className="ui-btn" onClick={read} type="button">
              {pt(language, "retry")}
            </button>
          </div>
        ) : (
          <p className="ui-muted" role="status">
            {pt(language, "loading")}
          </p>
        )}
      </>
    );

  const unit = choices.units.find((entry) => entry.unit_id === unitId);
  const type = choices.types.find((entry) => entry.id === typeId);
  const always = type?.always_urgent === true;
  const isUrgent = always ? true : urgent;
  const here = reports.filter(
    (report) =>
      isOpen(report) &&
      report.kind === kind &&
      (kind === "UNIT"
        ? unitId !== "" && report.unit_id === unitId
        : sharedId !== "" && report.problem_place?.id === sharedId),
  );
  const problems = {
    unit: kind === "UNIT" && unitId === "",
    where: kind === "BUILDING" && sharedId === "",
    type: typeId === "",
    text: description.trim() === "",
    urgent: isUrgent === null,
  };

  const save = (sameAs: string | null) => {
    setChecked(true);
    setFailure(null);
    if (Object.values(problems).some(Boolean)) {
      const first = (
        [
          ["unit", "np-unit"],
          ["where", "np-where"],
          ["type", "np-type-0"],
          ["text", "np-text"],
          ["urgent", "np-urgent-y"],
        ] as const
      ).find(([key]) => problems[key]);
      if (first !== undefined) document.getElementById(first[1])?.focus();
      return;
    }
    const body: NewProblemReport = {
      kind,
      source,
      problem_type_id: typeId,
      description: description.trim(),
      urgent: isUrgent === true,
    };
    if (reportedBy.trim() !== "") body.reported_by = reportedBy.trim();
    if (kind === "UNIT") {
      body.unit_id = unitId;
      body.may_enter = mayEnter;
      body.best_time = best;
      if (place !== "") {
        const [item, number] = place.split("|");
        body.place_item_id = item;
        body.place_number = Number(number);
      }
    } else {
      body.problem_place_id = sharedId;
      if (floor.trim() !== "") body.floor = floor.trim();
    }
    if (sameAs !== null) body.same_as = sameAs;
    if (finding !== undefined) body.finding_id = finding.finding_id;
    setBusy(true);
    void api
      .add(propertyId, body)
      .then(onSaved)
      .catch((error: unknown) => {
        setBusy(false);
        setFailure(problemRefusal(language, error));
      });
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    save(null);
  };

  const yesNo = (
    name: string,
    value: boolean | null,
    set: (value: boolean) => void,
    disabled = false,
  ) => (
    <>
      <label className="ui-chk">
        <input
          checked={value === true}
          disabled={disabled || busy}
          id={`${name}-y`}
          name={name}
          onChange={() => {
            set(true);
          }}
          type="radio"
        />
        {pt(language, "yes")}
      </label>
      <label className="ui-chk">
        <input
          checked={value === false}
          disabled={disabled || busy}
          name={name}
          onChange={() => {
            set(false);
          }}
          type="radio"
        />
        {pt(language, "no")}
      </label>
    </>
  );

  return (
    <>
      {back}
      <div className="ui-head">
        <h2>{pt(language, "add_t")}</h2>
      </div>
      <form className="ui-card ui-form" noValidate onSubmit={submit}>
        {finding !== undefined && (
          <div className="ui-notice" role="note">
            <Icon name="info" />
            <p>
              {pt(
                language,
                "fi_from",
                dayText(finding.inspection_date),
                finding.ordinal,
              )}
            </p>
          </div>
        )}
        {finding === undefined && (
          <div className="ui-row2">
            <fieldset className="ui-radios">
              <legend>{pt(language, "add_kind")}</legend>
              {(["UNIT", "BUILDING"] as const).map((value) => (
                <label className="ui-chk" key={value}>
                  <input
                    checked={kind === value}
                    disabled={busy}
                    name="np-kind"
                    onChange={() => {
                      setKind(value);
                    }}
                    type="radio"
                  />
                  {pt(language, `k_${value}`)}
                  <span className="ui-muted">
                    · {pt(language, `k_${value}_s`)}
                  </span>
                </label>
              ))}
            </fieldset>
            <fieldset className="ui-radios">
              <legend>{pt(language, "add_how")}</legend>
              {(["PHONE", "WALKIN", "SEEN"] as const).map((value) => (
                <label className="ui-chk" key={value}>
                  <input
                    checked={source === value}
                    disabled={busy}
                    name="np-source"
                    onChange={() => {
                      setSource(value);
                    }}
                    type="radio"
                  />
                  {pt(language, `how_${value}`)}
                </label>
              ))}
            </fieldset>
          </div>
        )}
        {kind === "UNIT" ? (
          <div className="ui-row2">
            <div className="ui-field">
              <label htmlFor="np-unit">
                {pt(language, "add_unit")}
                <span className="req">{pt(language, "required")}</span>
              </label>
              <select
                aria-describedby={
                  checked && problems.unit ? "np-unit-err" : undefined
                }
                aria-invalid={checked && problems.unit}
                className="ui-sel"
                disabled={busy || finding !== undefined}
                id="np-unit"
                onChange={(event) => {
                  setUnitId(event.currentTarget.value);
                  setPlace("");
                }}
                value={unitId}
              >
                <option value="">{pt(language, "add_unit_pick")}</option>
                {choices.units.map((entry) => (
                  <option key={entry.unit_id} value={entry.unit_id}>
                    {entry.unit_number} ·{" "}
                    {entry.customer_name ?? pt(language, "no_lease")}
                  </option>
                ))}
              </select>
              <Missing
                id="np-unit-err"
                show={checked && problems.unit}
                text={pt(language, "e_unit")}
              />
            </div>
            <div className="ui-field">
              <label htmlFor="np-place">{pt(language, "add_place")}</label>
              <select
                className="ui-sel"
                disabled={busy || unit === undefined}
                id="np-place"
                onChange={(event) => {
                  setPlace(event.currentTarget.value);
                }}
                value={place}
              >
                <option value="">{pt(language, "add_place_any")}</option>
                {(unit?.places ?? []).map((spot) => (
                  <option
                    key={`${spot.item_id}|${String(spot.number)}`}
                    value={`${spot.item_id}|${String(spot.number)}`}
                  >
                    {language === "km" && spot.name_kh !== null
                      ? spot.name_kh
                      : spot.name_en}{" "}
                    {spot.number}
                  </option>
                ))}
              </select>
            </div>
          </div>
        ) : (
          <div className="ui-row2">
            <div className="ui-field">
              <label htmlFor="np-where">
                {pt(language, "add_where")}
                <span className="req">{pt(language, "required")}</span>
              </label>
              <select
                aria-describedby={
                  checked && problems.where ? "np-where-err" : undefined
                }
                aria-invalid={checked && problems.where}
                className="ui-sel"
                disabled={busy}
                id="np-where"
                onChange={(event) => {
                  setSharedId(event.currentTarget.value);
                }}
                value={sharedId}
              >
                <option value="">{pt(language, "add_where_pick")}</option>
                {choices.places.map((spot) => (
                  <option key={spot.id} value={spot.id}>
                    {language === "km" && spot.name_kh !== null
                      ? spot.name_kh
                      : spot.name_en}
                  </option>
                ))}
              </select>
              <Missing
                id="np-where-err"
                show={checked && problems.where}
                text={pt(language, "e_where")}
              />
            </div>
            <div className="ui-field">
              <label htmlFor="np-floor">{pt(language, "add_floor")}</label>
              <input
                autoComplete="off"
                disabled={busy}
                id="np-floor"
                maxLength={20}
                onChange={(event) => {
                  setFloor(event.currentTarget.value);
                }}
                value={floor}
              />
            </div>
          </div>
        )}
        <div className="ui-field">
          <label htmlFor="np-by">{pt(language, "add_by")}</label>
          <input
            autoComplete="off"
            disabled={busy}
            id="np-by"
            maxLength={120}
            onChange={(event) => {
              setReportedBy(event.currentTarget.value);
            }}
            value={reportedBy}
          />
        </div>
        {here.length > 0 && (
          <section aria-labelledby="np-same" className="ui-notice">
            <Icon name="info" />
            <div>
              <h3 id="np-same">{pt(language, "same_t", here.length)}</h3>
              <p className="ui-small">{pt(language, "same_s")}</p>
              <ul className="ui-plain">
                {here.map((report) => (
                  <li key={report.report_id}>
                    <b className="ui-num">{report.report_number}</b> ·{" "}
                    {typeName(language, report.problem_type)} ·{" "}
                    {whereText(language, report)} · {report.description}{" "}
                    <button
                      className="ui-btn"
                      disabled={busy}
                      onClick={() => {
                        save(report.report_id);
                      }}
                      type="button"
                    >
                      {pt(language, "same_b")}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          </section>
        )}
        <fieldset className="ui-radios">
          <legend>
            {pt(language, "add_type")}
            <span className="req">{pt(language, "required")}</span>
          </legend>
          <div className="ui-tiles">
            {choices.types.map((entry, index) => (
              <label className="ui-chk ui-tile" key={entry.id}>
                <input
                  checked={typeId === entry.id}
                  disabled={busy}
                  id={`np-type-${String(index)}`}
                  name="np-type"
                  onChange={() => {
                    setTypeId(entry.id);
                  }}
                  type="radio"
                />
                <Icon name={typeIcon(entry)} small />
                {typeName(language, entry)}
                {entry.always_urgent && (
                  <span className="ui-sub2 warn">{pt(language, "always")}</span>
                )}
              </label>
            ))}
          </div>
          <Missing
            id="np-type-err"
            show={checked && problems.type}
            text={pt(language, "e_type")}
          />
        </fieldset>
        {always && (
          <div className="ui-notice err" role="note">
            <Icon name="alert" />
            <p>{pt(language, "safety_n")}</p>
          </div>
        )}
        <div className="ui-field">
          <label htmlFor="np-text">
            {pt(language, "add_text")}
            <span className="req">{pt(language, "required")}</span>
          </label>
          <textarea
            aria-describedby={
              checked && problems.text ? "np-text-err" : undefined
            }
            aria-invalid={checked && problems.text}
            disabled={busy}
            id="np-text"
            maxLength={1000}
            onChange={(event) => {
              setDescription(event.currentTarget.value);
            }}
            placeholder={pt(language, "add_text_ph")}
            rows={3}
            value={description}
          />
          <Missing
            id="np-text-err"
            show={checked && problems.text}
            text={pt(language, "e_text")}
          />
        </div>
        <div className="ui-row2">
          <fieldset className="ui-radios">
            <legend>{pt(language, "add_urgent")}</legend>
            {yesNo("np-urgent", isUrgent, setUrgent, always)}
            <Missing
              id="np-urgent-err"
              show={checked && problems.urgent}
              text={pt(language, "e_pick")}
            />
          </fieldset>
          {kind === "UNIT" && (
            <fieldset className="ui-radios">
              <legend>{pt(language, "add_enter")}</legend>
              {yesNo("np-enter", mayEnter, setMayEnter)}
            </fieldset>
          )}
        </div>
        {kind === "UNIT" && (
          <fieldset className="ui-radios">
            <legend>{pt(language, "add_best")}</legend>
            {(["AM", "PM", "ANY"] as const).map((value) => (
              <label className="ui-chk" key={value}>
                <input
                  checked={best === value}
                  disabled={busy}
                  name="np-best"
                  onChange={() => {
                    setBest(value);
                  }}
                  type="radio"
                />
                {pt(language, `b_${value}`)}
              </label>
            ))}
          </fieldset>
        )}
        {failure !== null && (
          <div className="ui-notice err" role="alert">
            <Icon name="alert" />
            <p>{failure}</p>
          </div>
        )}
        <div className="ui-actions">
          <button
            className="ui-btn"
            disabled={busy}
            onClick={() => {
              openPageInAddress("problems");
            }}
            type="button"
          >
            {pt(language, "cancel")}
          </button>
          <button className="ui-btn primary" disabled={busy} type="submit">
            {pt(language, "add_save")}
          </button>
        </div>
      </form>
    </>
  );
}
