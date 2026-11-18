// DL-201, DL-243: one Joint Inspection, "#/inspections/ji:<id>". A Draft is the tablet form in
// three steps (rooms and items; keys and meters; sign). A Done or Replaced one is read only,
// with its Problem reports, photos and both signatures; a Manager can replace a Done one.
// Every change saves at once; the server checks every right and rule again.

import { PROBLEM_REPORTS } from "../leases/parking";
import "./joint.css";

import { useCallback, useEffect, useRef, useState } from "react";

import { BackLink } from "../shell/backNav";
import { Icon } from "../shell/icons";
import { PageHeader } from "../shell/layouts";
import { hashForPage } from "../shell/navigation";
import { openPageInAddress } from "../shell/useHashPage";
import { Chip, type Tone } from "../shell/ui";
import type { Language } from "../signInText";
import {
  type FileRole,
  type JointApi,
  type JointChanges,
  JointError,
  type JointFinished,
  type JointInspection,
  type JointKeys,
  type JointLine,
  type JointMeter,
  type JointResult,
} from "./jointClient";
import { SignaturePad } from "./SignaturePad";
import { dayText, jt } from "./text";

const READING = /^[0-9]{1,13}(\.[0-9]{1,6})?$/;
const KEY_NAMES = [
  "door_keys",
  "key_cards",
  "mailbox_keys",
  "other_keys",
] as const;
const RANK: Record<JointResult, number> = { GOOD: 0, BROKEN: 1, MISSING: 2 };
export const RESULT_TONE: Record<JointResult, Tone> = {
  GOOD: "ok",
  BROKEN: "warn",
  MISSING: "err",
};
export const STATUS_TONE: Record<JointInspection["status"], Tone> = {
  DRAFT: "warn",
  DONE: "ok",
  REPLACED: "neutral",
};

/** A move-out line worse than at move-in (or with no move-in record) is new. */
export function isNew(line: JointLine): boolean {
  return (
    line.result !== null &&
    line.result !== "GOOD" &&
    (line.move_in_result === null ||
      RANK[line.result] > RANK[line.move_in_result])
  );
}

function lineName(language: Language, line: JointLine): string {
  if (line.line_kind === "PLACE") return jt(language, "room_itself");
  const name =
    language === "en" ? line.item_name : (line.item_name_km ?? line.item_name);
  return name ?? "";
}

function groupName(language: Language, line: JointLine): string {
  return language === "en" ? line.group_en : (line.group_km ?? line.group_en);
}

function groups(lines: readonly JointLine[]): JointLine[][] {
  const found: JointLine[][] = [];
  for (const line of lines) {
    const last = found.at(-1);
    if (last?.[0]?.group_en === line.group_en) last.push(line);
    else found.push([line]);
  }
  return found;
}

export function readyToSign(inspection: JointInspection): boolean {
  return (
    inspection.lines.every(
      (line) =>
        line.result !== null && (line.result === "GOOD" || line.note !== null),
    ) &&
    inspection.meters.every((meter) => meter.reading !== null) &&
    KEY_NAMES.every((name) => inspection.keys[name] !== null)
  );
}

function errorText(language: Language, error: unknown): string {
  if (error instanceof JointError) {
    if (error.status === 412) return jt(language, "e_stale");
    if (error.status === 403) return jt(language, "e_forbidden");
    if (error.status === 413 || error.status === 415)
      return jt(language, "e_picture");
    if (
      (error.status === 409 || error.status === 422 || error.status === 404) &&
      error.detail !== null
    )
      return error.detail;
  }
  return jt(language, "e_other");
}

export interface JointFormProps {
  language: Language;
  propertyId: string;
  inspectionId: string;
  api: JointApi;
  may: (capability: string) => boolean;
}

export function JointInspectionForm({
  language,
  propertyId,
  inspectionId,
  api,
  may,
}: JointFormProps) {
  const [inspection, setInspection] = useState<JointInspection | null>(null);
  const [missing, setMissing] = useState(false);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [finished, setFinished] = useState<JointFinished | null>(null);
  const current = useRef<JointInspection | null>(null);
  const queue = useRef<Promise<unknown>>(Promise.resolve());

  const show = useCallback((next: JointInspection) => {
    current.current = next;
    setInspection(next);
  }, []);

  const load = useCallback(() => {
    setFailed(false);
    void api
      .get(propertyId, inspectionId)
      .then(show)
      .catch((caught: unknown) => {
        if (caught instanceof JointError && caught.status === 404)
          setMissing(true);
        else setFailed(true);
      });
  }, [api, propertyId, inspectionId, show]);

  useEffect(() => {
    load();
  }, [load]);

  /** One change at a time, each at the version the one before left. */
  const run = (
    change: (now: JointInspection) => Promise<JointInspection>,
  ): Promise<void> => {
    const next = queue.current.then(async () => {
      const now = current.current;
      if (now === null) return;
      setBusy(true);
      setError(null);
      const signed =
        now.signatures.tenant !== null || now.signatures.staff !== null;
      try {
        const saved = await change(now);
        if (
          signed &&
          saved.signatures.tenant === null &&
          saved.signatures.staff === null
        )
          setNotice(jt(language, "sign_cleared"));
        show(saved);
      } catch (caught) {
        if (
          caught instanceof JointError &&
          caught.status === 503 &&
          caught.detail?.includes("folder") === true
        )
          setError(jt(language, "e_files"));
        else setError(errorText(language, caught));
        if (caught instanceof JointError && caught.status === 412) load();
      } finally {
        setBusy(false);
      }
    });
    queue.current = next.catch(() => undefined);
    return next;
  };

  const save = (changes: JointChanges) =>
    run((now) => api.save(propertyId, now, changes));
  const addFile = (role: FileRole, file: Blob, lineId?: string) =>
    run((now) => api.addFile(propertyId, now, role, file, lineId));
  const removeFile = (fileId: string) =>
    run(async (now) => {
      await api.removeFile(propertyId, fileId);
      return api.get(propertyId, now.inspection_id);
    });

  const back = <BackLink language={language} parent="inspections" />;
  if (missing)
    return (
      <>
        {back}
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{jt(language, "missing_one")}</p>
        </div>
      </>
    );
  if (inspection === null)
    return failed ? (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>{jt(language, "failed")}</p>
        <button className="ui-btn" onClick={load} type="button">
          {jt(language, "retry")}
        </button>
      </div>
    ) : (
      <p className="ui-muted" role="status">
        {jt(language, "loading")}
      </p>
    );

  const head = (
    <PageHeader
      back={back}
      badge={
        <Chip tone={STATUS_TONE[inspection.status]}>
          {jt(language, inspection.status)}
        </Chip>
      }
      numeric
      summary={[
        `${jt(language, inspection.kind)} ${jt(language, "ji")}`,
        inspection.unit_number,
        inspection.lease_number,
        inspection.tenant_name,
        dayText(inspection.inspection_date),
      ]
        .filter(Boolean)
        .join(" · ")}
      title={inspection.inspection_number}
      actions={
        inspection.status !== "DRAFT" && (
          <a
            className="ui-btn"
            href={api.pdfUrl(propertyId, inspection.inspection_id)}
            rel="noopener"
            target="_blank"
          >
            <Icon name="print" />
            {jt(language, "print")}
          </a>
        )
      }
    />
  );

  const messages = (
    <>
      {finished !== null && (
        <div className="ui-notice ok" role="status">
          <Icon name="check" />
          <p>
            {jt(language, "finished", finished.inspection_number)}{" "}
            {finished.reports.length > 0 &&
              jt(
                language,
                "finished_reports",
                finished.reports.join(", "),
              )}{" "}
            {finished.damage_findings > 0 &&
              jt(language, "finished_findings", finished.damage_findings)}
          </p>
        </div>
      )}
      {notice !== null && (
        <div className="ui-notice info" role="status">
          <Icon name="info" />
          <p>{notice}</p>
        </div>
      )}
      {error !== null && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>{error}</p>
        </div>
      )}
    </>
  );

  if (inspection.status !== "DRAFT")
    return (
      <>
        {head}
        {messages}
        <DoneView
          api={api}
          inspection={inspection}
          language={language}
          may={may}
          propertyId={propertyId}
        />
      </>
    );

  const canRecord = may("joint_inspections.record");
  const stepNames = ["step1", "step2", "step3"] as const;
  return (
    <>
      {head}
      {inspection.replaces !== null && (
        <p className="ui-small ui-muted">
          {jt(language, "replaces", inspection.replaces.inspection_number)}
          {inspection.replace_reason !== null &&
            ` · ${inspection.replace_reason}`}
        </p>
      )}
      <nav aria-label={jt(language, "steps")} className="ji-steps">
        {stepNames.map((name, index) => (
          <button
            aria-current={step === index + 1 ? "step" : undefined}
            key={name}
            onClick={() => {
              setStep((index + 1) as 1 | 2 | 3);
            }}
            type="button"
          >
            <span className="ji-stepno">{index + 1}</span>
            {jt(language, name)}
          </button>
        ))}
        <span aria-live="polite" className="ui-small ui-muted ji-saved">
          {busy ? jt(language, "saving") : ""}
        </span>
      </nav>
      {messages}
      {!canRecord && (
        <p className="ui-small ui-muted">{jt(language, "not_allowed")}</p>
      )}
      {step === 1 && (
        <LinesStep
          api={api}
          busy={busy || !canRecord}
          inspection={inspection}
          language={language}
          onAddPhoto={(file, lineId) => addFile("PHOTO", file, lineId)}
          onRemovePhoto={removeFile}
          onSave={save}
          propertyId={propertyId}
        />
      )}
      {step === 2 && (
        <KeysStep
          api={api}
          busy={busy || !canRecord}
          inspection={inspection}
          language={language}
          onMeterPhoto={(role, file) => addFile(role, file)}
          onSave={save}
          propertyId={propertyId}
        />
      )}
      {step === 3 && (
        <SignStep
          api={api}
          busy={busy || !canRecord}
          inspection={inspection}
          language={language}
          onFinish={() =>
            run(async (now) => {
              const done = await api.finish(propertyId, now);
              setFinished(done.finished);
              setNotice(null);
              return done.inspection;
            })
          }
          onSign={(role, picture) => addFile(role, picture)}
          propertyId={propertyId}
        />
      )}
      <div className="ui-actions ji-nav">
        {step > 1 && (
          <button
            className="ui-btn"
            onClick={() => {
              setStep((step - 1) as 1 | 2);
            }}
            type="button"
          >
            {jt(language, "prev")}
          </button>
        )}
        {step < 3 && (
          <button
            className="ui-btn primary"
            onClick={() => {
              setStep((step + 1) as 2 | 3);
            }}
            type="button"
          >
            {jt(language, "next")}
          </button>
        )}
      </div>
    </>
  );
}

function Photos({
  api,
  propertyId,
  language,
  photos,
  busy,
  max,
  onAdd,
  onRemove,
  label,
}: {
  api: JointApi;
  propertyId: string;
  language: Language;
  photos: readonly { file_id: string }[];
  busy: boolean;
  max: number;
  onAdd?: (file: File) => void;
  onRemove?: (fileId: string) => void;
  label: string;
}) {
  return (
    <div className="ji-photos">
      {photos.map((photo, index) => (
        <figure key={photo.file_id}>
          <a
            href={api.fileUrl(propertyId, photo.file_id)}
            rel="noreferrer"
            target="_blank"
          >
            <img
              alt={jt(language, "photo_n", index + 1)}
              src={api.fileUrl(propertyId, photo.file_id)}
            />
          </a>
          {onRemove !== undefined && (
            <button
              aria-label={`${jt(language, "photo_remove")} ${String(index + 1)}`}
              className="ui-btn link"
              disabled={busy}
              onClick={() => {
                onRemove(photo.file_id);
              }}
              type="button"
            >
              <Icon name="x" small />
            </button>
          )}
        </figure>
      ))}
      {onAdd !== undefined && photos.length < max && (
        <label
          className={
            busy ? "ui-btn ji-addphoto disabled" : "ui-btn ji-addphoto"
          }
        >
          <Icon name="upload" small />
          {label}
          <input
            accept="image/jpeg,image/png,image/webp"
            capture="environment"
            className="ui-sr"
            disabled={busy}
            onChange={(event) => {
              const file = event.currentTarget.files?.[0];
              event.currentTarget.value = "";
              if (file !== undefined) onAdd(file);
            }}
            type="file"
          />
        </label>
      )}
    </div>
  );
}

function NoteBox({
  id,
  language,
  value,
  busy,
  needed,
  onSave,
}: {
  id: string;
  language: Language;
  value: string | null;
  busy: boolean;
  needed: boolean;
  onSave: (note: string) => void;
}) {
  const [draft, setDraft] = useState(value ?? "");
  useEffect(() => {
    setDraft(value ?? "");
  }, [value]);
  const empty = needed && draft.trim() === "";
  return (
    <div className="ui-field ji-note">
      <label htmlFor={id}>{jt(language, "note")}</label>
      <input
        aria-describedby={empty ? `${id}-need` : undefined}
        aria-invalid={empty ? true : undefined}
        disabled={busy}
        id={id}
        maxLength={500}
        onBlur={() => {
          if (draft.trim() !== (value ?? "")) onSave(draft.trim());
        }}
        onChange={(event) => {
          setDraft(event.currentTarget.value);
        }}
        placeholder={jt(language, "note_need")}
        type="text"
        value={draft}
      />
      {empty && (
        <p className="ui-small warn" id={`${id}-need`}>
          {jt(language, "note_need")}
        </p>
      )}
    </div>
  );
}

function LinesStep({
  api,
  propertyId,
  language,
  inspection,
  busy,
  onSave,
  onAddPhoto,
  onRemovePhoto,
}: {
  api: JointApi;
  propertyId: string;
  language: Language;
  inspection: JointInspection;
  busy: boolean;
  onSave: (changes: JointChanges) => Promise<void>;
  onAddPhoto: (file: File, lineId: string) => Promise<void>;
  onRemovePhoto: (fileId: string) => Promise<void>;
}) {
  const moveOut = inspection.kind === "MOVE_OUT";
  return (
    <>
      {moveOut && inspection.move_in_id === null && (
        <p className="ui-notice info" role="note">
          <Icon name="info" />
          <span>{jt(language, "out_no_move_in")}</span>
        </p>
      )}
      {moveOut && (
        <p className="ui-small ui-muted">{jt(language, "tenant_caused_h")}</p>
      )}
      {groups(inspection.lines).map((lines) => {
        const first = lines[0];
        if (first === undefined) return null;
        const name = groupName(language, first);
        const open = lines.filter((line) => line.result === null);
        return (
          <section
            aria-label={name}
            className="ui-card ji-group"
            key={`${first.group_en}:${String(first.ordinal)}`}
          >
            <div className="ui-chead">
              <h2>{name}</h2>
              <button
                className="ui-btn"
                disabled={busy || open.length === 0}
                onClick={() => {
                  void onSave({
                    lines: open.map((line) => ({
                      line_id: line.line_id,
                      result: "GOOD",
                    })),
                  });
                }}
                title={jt(language, "all_good_h", name)}
                type="button"
              >
                <Icon name="check" small />
                {jt(language, "all_good")}
              </button>
            </div>
            <ul className="ui-plain ji-lines">
              {lines.map((line) => (
                <LineRow
                  api={api}
                  busy={busy}
                  key={line.line_id}
                  language={language}
                  line={line}
                  moveOut={moveOut}
                  onAddPhoto={onAddPhoto}
                  onRemovePhoto={onRemovePhoto}
                  onSave={onSave}
                  propertyId={propertyId}
                />
              ))}
            </ul>
          </section>
        );
      })}
    </>
  );
}

function LineRow({
  api,
  propertyId,
  language,
  line,
  moveOut,
  busy,
  onSave,
  onAddPhoto,
  onRemovePhoto,
}: {
  api: JointApi;
  propertyId: string;
  language: Language;
  line: JointLine;
  moveOut: boolean;
  busy: boolean;
  onSave: (changes: JointChanges) => Promise<void>;
  onAddPhoto: (file: File, lineId: string) => Promise<void>;
  onRemovePhoto: (fileId: string) => Promise<void>;
}) {
  const results: JointResult[] =
    line.line_kind === "ITEM"
      ? ["GOOD", "BROKEN", "MISSING"]
      : ["GOOD", "BROKEN"];
  const name = lineName(language, line);
  const problem = line.result !== null && line.result !== "GOOD";
  const fresh = moveOut && isNew(line);
  const type =
    language === "en"
      ? line.item_type_name
      : (line.item_type_name_km ?? line.item_type_name);
  return (
    <li className={problem ? "ji-line problem" : "ji-line"}>
      <div className="ji-linehead">
        <div className="ji-linename">
          <b>{name}</b>
          {type !== null && type !== name && (
            <span className="ui-sub2">{type}</span>
          )}
          {line.quantity !== null && line.quantity > 1 && (
            <span className="ui-num ui-muted">
              {" "}
              {jt(language, "qty", line.quantity)}
            </span>
          )}
          {moveOut && (
            <span className="ui-sub2">
              {line.move_in_result === null
                ? jt(language, "at_move_in_none")
                : jt(
                    language,
                    "at_move_in",
                    jt(language, line.move_in_result) +
                      (line.move_in_note === null
                        ? ""
                        : ` (${line.move_in_note})`),
                  )}
            </span>
          )}
          {fresh && <Chip tone="warn">{jt(language, "new_since")}</Chip>}
        </div>
        <div aria-label={name} className="ui-seg ji-results" role="group">
          {results.map((result) => (
            <button
              aria-pressed={line.result === result}
              className={`ji-${result.toLowerCase()}`}
              disabled={busy}
              key={result}
              onClick={() => {
                if (line.result !== result)
                  void onSave({
                    lines: [{ line_id: line.line_id, result }],
                  });
              }}
              type="button"
            >
              {jt(language, result)}
            </button>
          ))}
        </div>
      </div>
      {problem && (
        <div className="ji-linemore">
          <NoteBox
            busy={busy}
            id={`ji-note-${line.line_id}`}
            language={language}
            needed
            onSave={(note) => {
              void onSave({ lines: [{ line_id: line.line_id, note }] });
            }}
            value={line.note}
          />
          <Photos
            api={api}
            busy={busy}
            label={jt(language, "photo_add")}
            language={language}
            max={5}
            onAdd={(file) => {
              void onAddPhoto(file, line.line_id);
            }}
            onRemove={(fileId) => {
              void onRemovePhoto(fileId);
            }}
            photos={line.photos}
            propertyId={propertyId}
          />
          {fresh && (
            <div className="ji-ticks">
              <label className="ui-chk">
                <input
                  checked={line.tenant_caused}
                  disabled={busy}
                  onChange={(event) => {
                    void onSave({
                      lines: [
                        {
                          line_id: line.line_id,
                          tenant_caused: event.currentTarget.checked,
                        },
                      ],
                    });
                  }}
                  type="checkbox"
                />
                {jt(language, "tenant_caused")}
              </label>
              {line.tenant_caused && (
                <label className="ui-chk">
                  <input
                    checked={line.pet_caused}
                    disabled={busy}
                    onChange={(event) => {
                      void onSave({
                        lines: [
                          {
                            line_id: line.line_id,
                            pet_caused: event.currentTarget.checked,
                          },
                        ],
                      });
                    }}
                    type="checkbox"
                  />
                  {jt(language, "pet_caused")}
                </label>
              )}
            </div>
          )}
        </div>
      )}
    </li>
  );
}

function KeyBox({
  name,
  language,
  value,
  given,
  busy,
  onSave,
}: {
  name: (typeof KEY_NAMES)[number];
  language: Language;
  value: number | null;
  given: number | null | undefined;
  busy: boolean;
  onSave: (count: number | null) => void;
}) {
  const [draft, setDraft] = useState(value === null ? "" : String(value));
  useEffect(() => {
    setDraft(value === null ? "" : String(value));
  }, [value]);
  const id = `ji-key-${name}`;
  return (
    <div className="ui-field">
      <label htmlFor={id}>{jt(language, name)}</label>
      <input
        className="ui-num"
        disabled={busy}
        id={id}
        inputMode="numeric"
        max={99}
        min={0}
        onBlur={() => {
          const trimmed = draft.trim();
          const count = trimmed === "" ? null : Number(trimmed);
          if (
            count !== null &&
            (!Number.isInteger(count) || count < 0 || count > 99)
          ) {
            setDraft(value === null ? "" : String(value));
            return;
          }
          if (count !== value) onSave(count);
        }}
        onChange={(event) => {
          setDraft(event.currentTarget.value);
        }}
        type="number"
        value={draft}
      />
      {given !== undefined && given !== null && (
        <p className="help">{jt(language, "keys_given", given)}</p>
      )}
    </div>
  );
}

function MeterBox({
  api,
  propertyId,
  language,
  meter,
  busy,
  onSave,
  onPhoto,
}: {
  api: JointApi;
  propertyId: string;
  language: Language;
  meter: JointMeter;
  busy: boolean;
  onSave: (reading: string | null) => void;
  onPhoto: (file: File) => void;
}) {
  const [draft, setDraft] = useState(meter.reading ?? "");
  useEffect(() => {
    setDraft(meter.reading ?? "");
  }, [meter.reading]);
  const id = `ji-meter-${meter.utility_type}`;
  const bad = draft.trim() !== "" && !READING.test(draft.trim());
  const differs =
    meter.reading !== null &&
    meter.utilities_reading !== null &&
    Number(meter.reading) !== Number(meter.utilities_reading);
  return (
    <div className="ui-card ji-meter">
      <h3>
        {jt(language, meter.utility_type)}{" "}
        <span className="ui-num ui-muted">{meter.serial_number}</span>
      </h3>
      <div className="ui-field">
        <label htmlFor={id}>
          {jt(language, "reading")} ({meter.measurement_unit_code})
        </label>
        <input
          aria-describedby={bad ? `${id}-bad` : undefined}
          aria-invalid={bad ? true : undefined}
          className="ui-num"
          disabled={busy}
          id={id}
          inputMode="decimal"
          onBlur={() => {
            const trimmed = draft.trim();
            if (trimmed !== "" && !READING.test(trimmed)) return;
            const reading = trimmed === "" ? null : trimmed;
            if (reading !== meter.reading) onSave(reading);
          }}
          onChange={(event) => {
            setDraft(event.currentTarget.value);
          }}
          type="text"
          value={draft}
        />
        {bad && (
          <p className="ui-error" id={`${id}-bad`}>
            {jt(language, "reading_bad")}
          </p>
        )}
        {meter.move_in_reading !== null && (
          <p className="help">
            {jt(language, "move_in_reading", meter.move_in_reading)}
          </p>
        )}
      </div>
      {differs && (
        <p className="ui-notice warn" role="status">
          <Icon name="alert" />
          <span>
            {jt(language, "utilities_differs", meter.utilities_reading ?? "")}
          </span>
        </p>
      )}
      <Photos
        api={api}
        busy={busy}
        label={jt(language, "meter_photo")}
        language={language}
        max={1}
        onAdd={onPhoto}
        photos={meter.photo === null ? [] : [meter.photo]}
        propertyId={propertyId}
      />
    </div>
  );
}

function KeysStep({
  api,
  propertyId,
  language,
  inspection,
  busy,
  onSave,
  onMeterPhoto,
}: {
  api: JointApi;
  propertyId: string;
  language: Language;
  inspection: JointInspection;
  busy: boolean;
  onSave: (changes: JointChanges) => Promise<void>;
  onMeterPhoto: (role: FileRole, file: File) => Promise<void>;
}) {
  const given = inspection.move_in_keys;
  const short =
    inspection.kind === "MOVE_OUT" &&
    given !== null &&
    KEY_NAMES.some((name) => {
      const now = inspection.keys[name];
      const before = given[name];
      return now !== null && before !== null && now < before;
    });
  const [otherNote, setOtherNote] = useState(
    inspection.keys.other_keys_note ?? "",
  );
  useEffect(() => {
    setOtherNote(inspection.keys.other_keys_note ?? "");
  }, [inspection.keys.other_keys_note]);
  const saveKey = (keys: Partial<JointKeys>) => {
    void onSave({ keys });
  };
  return (
    <>
      <section aria-labelledby="ji-keys" className="ui-card">
        <h2 id="ji-keys">{jt(language, "keys")}</h2>
        <div className="ji-keys">
          {KEY_NAMES.map((name) => (
            <KeyBox
              busy={busy}
              given={given?.[name]}
              key={name}
              language={language}
              name={name}
              onSave={(count) => {
                saveKey({ [name]: count });
              }}
              value={inspection.keys[name]}
            />
          ))}
        </div>
        {(inspection.keys.other_keys ?? 0) > 0 && (
          <div className="ui-field">
            <label htmlFor="ji-key-note">
              {jt(language, "other_keys_note")}
            </label>
            <input
              disabled={busy}
              id="ji-key-note"
              maxLength={200}
              onBlur={() => {
                if (
                  otherNote.trim() !== (inspection.keys.other_keys_note ?? "")
                )
                  saveKey({ other_keys_note: otherNote.trim() });
              }}
              onChange={(event) => {
                setOtherNote(event.currentTarget.value);
              }}
              type="text"
              value={otherNote}
            />
          </div>
        )}
        {short && (
          <p className="ui-notice warn" role="status">
            <Icon name="alert" />
            <span>{jt(language, "keys_short")}</span>
          </p>
        )}
      </section>
      <section aria-labelledby="ji-meters" className="ui-stack">
        <h2 className="ui-sr" id="ji-meters">
          {jt(language, "meters")}
        </h2>
        {inspection.meters.length === 0 ? (
          <p className="ui-muted">{jt(language, "no_meters")}</p>
        ) : (
          inspection.meters.map((meter) => (
            <MeterBox
              api={api}
              busy={busy}
              key={meter.utility_type}
              language={language}
              meter={meter}
              onPhoto={(file) => {
                void onMeterPhoto(meter.utility_type, file);
              }}
              onSave={(reading) => {
                void onSave({
                  meters: [{ utility_type: meter.utility_type, reading }],
                });
              }}
              propertyId={propertyId}
            />
          ))
        )}
      </section>
    </>
  );
}

function Summary({
  language,
  inspection,
}: {
  language: Language;
  inspection: JointInspection;
}) {
  const count = (result: JointResult) =>
    inspection.lines.filter((line) => line.result === result).length;
  const caused = inspection.lines.filter((line) => line.tenant_caused).length;
  return (
    <p className="ji-summary">
      <Chip tone="ok">{jt(language, "sum_good", count("GOOD"))}</Chip>{" "}
      <Chip tone="warn">{jt(language, "sum_broken", count("BROKEN"))}</Chip>{" "}
      <Chip tone="err">{jt(language, "sum_missing", count("MISSING"))}</Chip>{" "}
      {inspection.kind === "MOVE_OUT" && caused > 0 && (
        <Chip tone="info">{jt(language, "sum_caused", caused)}</Chip>
      )}
    </p>
  );
}

function SignStep({
  api,
  propertyId,
  language,
  inspection,
  busy,
  onSign,
  onFinish,
}: {
  api: JointApi;
  propertyId: string;
  language: Language;
  inspection: JointInspection;
  busy: boolean;
  onSign: (role: FileRole, picture: Blob) => Promise<void>;
  onFinish: () => Promise<void>;
}) {
  const ready = readyToSign(inspection);
  const problems = inspection.lines.filter(
    (line) => line.result !== null && line.result !== "GOOD",
  );
  const { tenant, staff } = inspection.signatures;
  const [againTenant, setAgainTenant] = useState(false);
  const [againStaff, setAgainStaff] = useState(false);
  return (
    <>
      <section aria-labelledby="ji-check" className="ui-card">
        <h2 id="ji-check">{jt(language, "sign_check")}</h2>
        <Summary inspection={inspection} language={language} />
        {problems.length > 0 && (
          <ul className="ui-plain ji-problems">
            {problems.map((line) => (
              <li key={line.line_id}>
                <Chip tone={RESULT_TONE[line.result ?? "GOOD"]}>
                  {jt(language, line.result ?? "GOOD")}
                </Chip>{" "}
                {groupName(language, line)} · {lineName(language, line)}
                {line.note !== null && (
                  <span className="ui-sub2">{line.note}</span>
                )}
                {line.tenant_caused && (
                  <span className="ui-sub2">
                    {jt(language, "tenant_caused")}
                    {line.pet_caused && ` · ${jt(language, "pet_caused")}`}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
        <p className="ui-small">
          {jt(language, "keys")}:{" "}
          {KEY_NAMES.map(
            (name) =>
              `${jt(language, name)} ${String(inspection.keys[name] ?? "–")}`,
          ).join(" · ")}
        </p>
        {inspection.meters.map((meter) => (
          <p className="ui-small" key={meter.utility_type}>
            {jt(language, meter.utility_type)}:{" "}
            <span className="ui-num">
              {meter.reading ?? "–"} {meter.measurement_unit_code}
            </span>
          </p>
        ))}
      </section>
      {!ready ? (
        <p className="ui-notice warn" role="status">
          <Icon name="alert" />
          <span>{jt(language, "not_ready")}</span>
        </p>
      ) : (
        <section className="ui-card ji-signs">
          {tenant !== null && !againTenant ? (
            <Signed
              api={api}
              fileId={tenant.file_id}
              label={jt(language, "tenant_sign")}
              language={language}
              note={jt(language, "signed_at", timeText(tenant.signed_at))}
              onAgain={
                busy
                  ? undefined
                  : () => {
                      setAgainTenant(true);
                    }
              }
              propertyId={propertyId}
            />
          ) : (
            <SignaturePad
              busy={busy}
              label={jt(language, "tenant_sign")}
              language={language}
              onSave={(picture) => {
                void onSign("TENANT_SIGNATURE", picture).then(() => {
                  setAgainTenant(false);
                });
              }}
            />
          )}
          {tenant === null ? (
            <p className="ui-small ui-muted">{jt(language, "tenant_first")}</p>
          ) : staff !== null && !againStaff ? (
            <Signed
              api={api}
              fileId={staff.file_id}
              label={jt(language, "staff_sign")}
              language={language}
              note={jt(
                language,
                "signed_by",
                staff.name ?? "",
                timeText(staff.signed_at),
              )}
              onAgain={
                busy
                  ? undefined
                  : () => {
                      setAgainStaff(true);
                    }
              }
              propertyId={propertyId}
            />
          ) : (
            <SignaturePad
              busy={busy}
              label={jt(language, "staff_sign")}
              language={language}
              onSave={(picture) => {
                void onSign("STAFF_SIGNATURE", picture).then(() => {
                  setAgainStaff(false);
                });
              }}
            />
          )}
        </section>
      )}
      <div className="ui-actions">
        <button
          className="ui-btn primary"
          disabled={busy || !ready || tenant === null || staff === null}
          onClick={() => {
            void onFinish();
          }}
          type="button"
        >
          <Icon name="check" />
          {jt(language, "finish")}
        </button>
        <span className="ui-small ui-muted">{jt(language, "finish_h")}</span>
      </div>
    </>
  );
}

function timeText(at: string): string {
  const moment = new Date(at);
  if (Number.isNaN(moment.getTime())) return at;
  const day = `${String(moment.getDate()).padStart(2, "0")}/${String(
    moment.getMonth() + 1,
  ).padStart(2, "0")}/${String(moment.getFullYear())}`;
  const time = `${String(moment.getHours()).padStart(2, "0")}:${String(
    moment.getMinutes(),
  ).padStart(2, "0")}`;
  return `${day} ${time}`;
}

function Signed({
  api,
  propertyId,
  fileId,
  label,
  note,
  language,
  onAgain,
}: {
  api: JointApi;
  propertyId: string;
  fileId: string;
  label: string;
  note: string;
  language: Language;
  onAgain?: () => void;
}) {
  return (
    <figure className="ji-signed">
      <figcaption className="ui-flabel">{label}</figcaption>
      <img alt={label} src={api.fileUrl(propertyId, fileId)} />
      <p className="ui-small ui-muted">{note}</p>
      {onAgain !== undefined && (
        <button className="ui-btn link" onClick={onAgain} type="button">
          {jt(language, "sign_again")}
        </button>
      )}
    </figure>
  );
}

function DoneView({
  api,
  propertyId,
  language,
  inspection,
  may,
}: {
  api: JointApi;
  propertyId: string;
  language: Language;
  inspection: JointInspection;
  may: (capability: string) => boolean;
}) {
  const [replacing, setReplacing] = useState(false);
  const [reason, setReason] = useState("");
  const [tried, setTried] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const moveOut = inspection.kind === "MOVE_OUT";
  const { tenant, staff } = inspection.signatures;
  return (
    <>
      {inspection.replaced_by !== null && (
        <p className="ui-notice info" role="status">
          <Icon name="info" />
          <span>
            {jt(language, "replaced_by", "")}
            <a
              className="ui-num"
              href={hashForPage(
                "inspections",
                `ji:${inspection.replaced_by.inspection_id}`,
              )}
            >
              {inspection.replaced_by.inspection_number}
            </a>
          </span>
        </p>
      )}
      <p className="ui-small ui-muted">
        {inspection.done_at !== null &&
          jt(
            language,
            "done_on",
            timeText(inspection.done_at),
            inspection.done_by ?? "",
          )}
        {inspection.replaces !== null &&
          ` · ${jt(language, "replaces", inspection.replaces.inspection_number)}`}
        {inspection.replace_reason !== null &&
          ` · ${inspection.replace_reason}`}
      </p>
      <Summary inspection={inspection} language={language} />
      {groups(inspection.lines).map((lines) => {
        const first = lines[0];
        if (first === undefined) return null;
        const name = groupName(language, first);
        return (
          <section
            aria-label={name}
            className="ui-card ji-group"
            key={`${first.group_en}:${String(first.ordinal)}`}
          >
            <h2>{name}</h2>
            <ul className="ui-plain ji-lines">
              {lines.map((line) => (
                <li className="ji-line" key={line.line_id}>
                  <div className="ji-linehead">
                    <div className="ji-linename">
                      <b>{lineName(language, line)}</b>
                      {line.quantity !== null && line.quantity > 1 && (
                        <span className="ui-num ui-muted">
                          {" "}
                          {jt(language, "qty", line.quantity)}
                        </span>
                      )}
                      {moveOut && line.move_in_result !== null && (
                        <span className="ui-sub2">
                          {jt(
                            language,
                            "at_move_in",
                            jt(language, line.move_in_result),
                          )}
                        </span>
                      )}
                      {line.note !== null && (
                        <span className="ui-sub2">{line.note}</span>
                      )}
                    </div>
                    <div className="ji-done-marks">
                      {line.result !== null && (
                        <Chip tone={RESULT_TONE[line.result]}>
                          {jt(language, line.result)}
                        </Chip>
                      )}
                      {moveOut && isNew(line) && (
                        <Chip tone="warn">{jt(language, "new_since")}</Chip>
                      )}
                      {line.tenant_caused && (
                        <Chip tone="info">
                          {jt(language, "tenant_caused")}
                          {line.pet_caused &&
                            ` · ${jt(language, "pet_caused")}`}
                        </Chip>
                      )}
                      {/* Parking Step 6: no Problem reports page on Parking (PROBLEM_REPORTS). */}
                      {PROBLEM_REPORTS && line.problem_report !== null && (
                        <a
                          className="ui-num"
                          href={hashForPage(
                            "problems",
                            `pr:${line.problem_report.report_id}`,
                          )}
                        >
                          {jt(
                            language,
                            "report",
                            line.problem_report.report_number,
                          )}
                        </a>
                      )}
                    </div>
                  </div>
                  {line.photos.length > 0 && (
                    <Photos
                      api={api}
                      busy
                      label=""
                      language={language}
                      max={0}
                      photos={line.photos}
                      propertyId={propertyId}
                    />
                  )}
                </li>
              ))}
            </ul>
          </section>
        );
      })}
      <section aria-labelledby="ji-done-keys" className="ui-card">
        <h2 id="ji-done-keys">
          {jt(language, "keys")} · {jt(language, "meters")}
        </h2>
        <p>
          {KEY_NAMES.map(
            (name) =>
              `${jt(language, name)} ${String(inspection.keys[name] ?? "–")}`,
          ).join(" · ")}
          {inspection.keys.other_keys_note !== null &&
            ` (${inspection.keys.other_keys_note})`}
        </p>
        {inspection.meters.map((meter) => (
          <div key={meter.utility_type}>
            <p>
              {jt(language, meter.utility_type)}{" "}
              <span className="ui-num">
                {meter.serial_number}: {meter.reading ?? "–"}{" "}
                {meter.measurement_unit_code}
              </span>
            </p>
            {meter.photo !== null && (
              <Photos
                api={api}
                busy
                label=""
                language={language}
                max={0}
                photos={[meter.photo]}
                propertyId={propertyId}
              />
            )}
          </div>
        ))}
      </section>
      <section className="ui-card ji-signs">
        {tenant !== null && (
          <Signed
            api={api}
            fileId={tenant.file_id}
            label={jt(language, "tenant_sign")}
            language={language}
            note={jt(language, "signed_at", timeText(tenant.signed_at))}
            propertyId={propertyId}
          />
        )}
        {staff !== null && (
          <Signed
            api={api}
            fileId={staff.file_id}
            label={jt(language, "staff_sign")}
            language={language}
            note={jt(
              language,
              "signed_by",
              staff.name ?? "",
              timeText(staff.signed_at),
            )}
            propertyId={propertyId}
          />
        )}
      </section>
      {inspection.status === "DONE" && may("joint_inspections.replace") && (
        <section aria-labelledby="ji-replace" className="ui-card ji-noprint">
          <h2 id="ji-replace">
            {jt(language, "replace_t", inspection.inspection_number)}
          </h2>
          <p className="ui-small ui-muted">{jt(language, "replace_h")}</p>
          {!replacing ? (
            <button
              className="ui-btn"
              onClick={() => {
                setReplacing(true);
              }}
              type="button"
            >
              {jt(language, "replace")}
            </button>
          ) : (
            <form
              noValidate
              onSubmit={(event) => {
                event.preventDefault();
                setTried(true);
                if (reason.trim() === "") return;
                setBusy(true);
                setError(null);
                void api
                  .start(propertyId, {
                    lease_id: inspection.lease_id,
                    kind: inspection.kind,
                    replaces_id: inspection.inspection_id,
                    reason: reason.trim(),
                  })
                  .then((made) => {
                    openPageInAddress(
                      "inspections",
                      false,
                      `ji:${made.inspection_id}`,
                    );
                  })
                  .catch((caught: unknown) => {
                    setError(errorText(language, caught));
                  })
                  .finally(() => {
                    setBusy(false);
                  });
              }}
            >
              <div className="ui-field">
                <label htmlFor="ji-reason">{jt(language, "reason")}</label>
                <input
                  aria-describedby={
                    tried && reason.trim() === "" ? "ji-reason-need" : undefined
                  }
                  aria-invalid={
                    tried && reason.trim() === "" ? true : undefined
                  }
                  id="ji-reason"
                  maxLength={500}
                  onChange={(event) => {
                    setReason(event.currentTarget.value);
                  }}
                  type="text"
                  value={reason}
                />
                {tried && reason.trim() === "" && (
                  <p className="ui-error" id="ji-reason-need">
                    {jt(language, "reason_need")}
                  </p>
                )}
              </div>
              {error !== null && (
                <p className="ui-error" role="alert">
                  {error}
                </p>
              )}
              <div className="ui-actions">
                <button
                  className="ui-btn primary"
                  disabled={busy}
                  type="submit"
                >
                  {jt(language, "start_replace")}
                </button>
                <button
                  className="ui-btn"
                  onClick={() => {
                    setReplacing(false);
                  }}
                  type="button"
                >
                  {jt(language, "cancel")}
                </button>
              </div>
            </form>
          )}
        </section>
      )}
    </>
  );
}
