// V1-058 R3 L3b: Terminate Lease and Record termination notice (DESIGN.md "Move-out (round 3)",
// Terminate Lease; Letters: the Termination notice after the day-30 letter). The ground decides
// the signed-Lease evidence the server checks (TerminationContextSource) and which Deposit is
// kept; the dialog says which before saving. The server and the database verify every rule.

import { FormEvent, useEffect, useState } from "react";

import type {
  LeaseApi,
  LeaseResource,
  TerminationContextSource,
} from "../leaseClient";
import { HowSelect, useLettersSend } from "../letters/LettersDialogs";
import type {
  LeaseWarning,
  LettersApi,
  TerminationNotice,
} from "../letters/lettersClient";
import { howRecord, type How } from "../letters/lettersData";
import { ltr } from "../letters/text";
import { addDays } from "../reservations/reservationsData";
import { DateInput, isDay } from "../shell/DateInput";
import { dayText, todayInPhnomPenh } from "../shell/format";
import { Icon } from "../shell/icons";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import {
  OutcomeNotice,
  Problem,
  useSend,
  useValuesIdentity,
} from "./LeaseDialogs";
import { lt } from "./text";

export type Ground = "EARLY" | "VIOLATION" | "RENT" | "UNPAID";
const GROUNDS: Ground[] = ["EARLY", "VIOLATION", "RENT", "UNPAID"];

// The evidence stored with the termination, in English like every stored record. A Rent
// termination reuses the notice's own provision and grounds, which the database matches exactly.
const AUTHORITY =
  "Approved in the app by the signed-in Owner or Manager (leases.terminate)";
const PROVISION: Record<Exclude<Ground, "RENT">, string> = {
  EARLY: "Signed Lease: early leaving at the Customer's request (BR-LEASE-021)",
  VIOLATION:
    "Signed Lease: Lease rules, termination after three written warnings (BR-LEASE-024)",
  UNPAID:
    "Signed Lease: Initial Rent and Security Deposit due within 5 days of the Start Date (BR-LEASE-005)",
};
const APPROVED: Record<Exclude<Ground, "RENT">, string> = {
  EARLY: "The Customer leaves before the End Date at the Customer's request",
  VIOLATION: "Lease rule violation after three written warnings",
  UNPAID: "Initial Rent or Security Deposit not paid within 5 days",
};
const PET_APPROVED = "Pet-rule violation after three written warnings";
const NO_NOTICE: Record<Exclude<Ground, "RENT">, string> = {
  EARLY: "No landlord notice: the Customer asked to leave early",
  VIOLATION:
    "No landlord notice: three written warnings were given (BR-LEASE-024)",
  UNPAID:
    "No landlord notice: the Initial obligation was not paid within 5 days (BR-LEASE-005)",
};

// DL-073: for unpaid Rent the termination notice is the third letter.
const NOTICE_PROVISION =
  "Signed Lease: Rent not paid after the day-20 warning letter and the day-30 default notice (BR-LEASE-028)";
const NOTICE_GROUNDS = "Rent unpaid after the day-30 default notice (DL-073)";
const NOTICE_TERMS = "The Lease ends on the date written in the notice";
const NOTICE_REASON = "Termination notice given";

function governing(ground: Ground, pet: boolean): string {
  if (ground === "EARLY") return "BR-LEASE-021";
  if (ground === "RENT") return "BR-LEASE-028";
  if (ground === "UNPAID") return "BR-LEASE-005";
  // Both Deposits are kept for a pet-rule termination (BR-DEP-022).
  return pet ? "BR-DEP-022" : "BR-LEASE-025";
}

/** The day a notice's period ends: its intended termination date, else the day it was given. */
export function noticeEnd(notice: TerminationNotice): string {
  return notice.intended_termination_date ?? notice.notice_date;
}

/** Notices a termination may name: current, with their recorded context. */
export function usableNotices(
  notices: TerminationNotice[],
): TerminationNotice[] {
  return notices.filter(
    (notice) =>
      notice.current_effect === "NOTICE_ONLY" && notice.context !== null,
  );
}

/** What was typed in Terminate, kept while the notice dialog is open. */
export interface TerminateDraft {
  ground: Ground | null;
  pet: boolean;
  day: string;
  ticked: string[];
  proof: string;
  memo: string;
}

export function terminateDraft(ground: Ground | null): TerminateDraft {
  return {
    ground,
    pet: false,
    day: todayInPhnomPenh(),
    ticked: [],
    proof: "",
    memo: "",
  };
}

type Evidence =
  | { state: "loading" | "failed" }
  | {
      state: "done";
      warnings: LeaseWarning[];
      notices: TerminationNotice[];
    };

export function TerminateDialog({
  language,
  api,
  lettersApi,
  lease,
  draft,
  onRecordNotice,
  onClose,
  onSaved,
  onConflict,
}: {
  language: Language;
  api: Pick<LeaseApi, "terminate">;
  lettersApi: Pick<LettersApi, "warnings" | "notices">;
  lease: LeaseResource;
  /** The values the dialog opens with (Letters opens it on the Rent ground). */
  draft: TerminateDraft;
  onRecordNotice: (draft: TerminateDraft) => void;
  onClose: () => void;
  onSaved: (saved: LeaseResource, message: string) => void;
  onConflict: () => void;
}) {
  const today = todayInPhnomPenh();
  const [evidence, setEvidence] = useState<Evidence>({ state: "loading" });
  const [ground, setGround] = useState<Ground | null>(draft.ground);
  const [pet, setPet] = useState(draft.pet);
  const [day, setDay] = useState(draft.day);
  const [ticked, setTicked] = useState<ReadonlySet<string>>(
    new Set(draft.ticked),
  );
  const [noticeId, setNoticeId] = useState("");
  const [proof, setProof] = useState(draft.proof);
  const [memo, setMemo] = useState(draft.memo);
  const [problems, setProblems] = useState<Record<string, string>>({});
  const identity = useValuesIdentity();
  const movedIn = lease.occupancies.length > 0;
  const [attempt, setAttempt] = useState(0);
  const { busy, outcome, send } = useSend((saved) => {
    onSaved(saved, lt(language, "tg_toast", saved.unit_number, dayText(day)));
  }, onConflict);

  // The warnings and notices of this Lease, read when the dialog opens.
  useEffect(() => {
    const alive = { current: true };
    setEvidence({ state: "loading" });
    Promise.all([
      lettersApi.warnings(lease.lease_id),
      lettersApi.notices(lease.property_id, lease.lease_id),
    ])
      .then(([warnings, notices]) => {
        if (!alive.current) return;
        const usable = usableNotices(notices);
        setEvidence({ state: "done", warnings, notices: usable });
        // The notice recorded last is the one a Rent termination usually names.
        const latest = [...usable].sort((x, y) =>
          x.occurred_at.localeCompare(y.occurred_at),
        )[usable.length - 1];
        if (latest !== undefined) setNoticeId(latest.id);
      })
      .catch(() => {
        if (alive.current) setEvidence({ state: "failed" });
      });
    return () => {
      alive.current = false;
    };
  }, [lettersApi, lease.lease_id, lease.property_id, attempt]);

  const warnings = evidence.state === "done" ? evidence.warnings : [];
  const notices = evidence.state === "done" ? evidence.notices : [];
  const notice = notices.find((item) => item.id === noticeId);
  const first =
    ground === "RENT" &&
    notice !== undefined &&
    noticeEnd(notice) > (lease.start_date ?? "")
      ? noticeEnd(notice)
      : (lease.start_date ?? today);
  // The server takes any day up to today, also after the End Date (a Lease still running).
  // Leaving early must be before the End Date (BR-LEASE-021).
  const last =
    ground === "EARLY" && lease.end_date !== null && lease.end_date <= today
      ? addDays(lease.end_date, -1)
      : today;
  // An unpaid Initial obligation counts from Start Date + 5 days (BR-LEASE-005, DL-064).
  const unpaidFrom = addDays(lease.start_date ?? today, 6);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const reason = memo.trim();
    const reference = proof.trim();
    const found: Record<string, string> = {};
    if (ground === null) found.ground = lt(language, "tg_ground_e");
    // V1-060 B7: a day typed in a wrong form is not a day.
    if (!isDay(day) || day < first || day > last)
      found.day = lt(language, "tg_bad", dayText(first));
    if (
      ground === "VIOLATION" &&
      warnings.filter(
        (warning) => ticked.has(warning.id) && warning.warning_date <= day,
      ).length < 3
    )
      found.warnings = lt(language, "tg_warnings_e");
    if (ground === "RENT" && notice === undefined)
      found.notice = lt(language, "tg_notice_e");
    if (reference === "") found.proof = lt(language, "tg_evidence_e");
    if (reason === "") found.memo = lt(language, "tg_memo_e");
    setProblems(found);
    if (ground === null || Object.keys(found).length > 0) return;
    let context: TerminationContextSource;
    if (ground === "RENT") {
      const held = notice?.context ?? null;
      if (held === null || notice === undefined) return;
      context = {
        basis: "SIGNED_LEASE_OTHER",
        signed_lease_provision: notice.governing_lease_provision,
        approved_grounds: held.approved_grounds,
        management_authorization_reference: AUTHORITY,
        evidence_reference: reference,
        notice_required: true,
        notice_id: notice.id,
        notice_period_ends_on: noticeEnd(notice),
      };
    } else {
      context = {
        basis:
          ground === "EARLY"
            ? "VOLUNTARY_EARLY"
            : ground === "VIOLATION"
              ? "CUSTOMER_VIOLATION"
              : "UNPAID_INITIAL_OBLIGATION",
        signed_lease_provision: PROVISION[ground],
        approved_grounds:
          ground === "VIOLATION" && pet ? PET_APPROVED : APPROVED[ground],
        management_authorization_reference: AUTHORITY,
        evidence_reference: reference,
        notice_required: false,
        notice_exception_reason: NO_NOTICE[ground],
        ...(ground === "VIOLATION"
          ? {
              // In the order they were given.
              warning_ids: warnings
                .filter(
                  (warning) =>
                    ticked.has(warning.id) && warning.warning_date <= day,
                )
                .map((warning) => warning.id),
            }
          : {}),
      };
    }
    const source = {
      actual_termination_date: day,
      governing_event_reference: governing(ground, pet),
      reason,
      context,
    };
    const chosen = identity(JSON.stringify([lease.version, source]));
    send(() =>
      api.terminate(lease, { event_id: chosen.id, ...source }, chosen.key),
    );
  }

  // Which Deposit is kept, said before saving (DESIGN.md; BR-DEP-022, BR-DEP-023, BR-LEASE-028).
  const consequences: string[] = [];
  if (ground !== null) {
    consequences.push(
      lt(
        language,
        ground === "RENT"
          ? "tg_c1_rent"
          : ground === "UNPAID"
            ? "tg_c1_unpaid"
            : "tg_c1",
      ),
    );
    if (lease.pet_deposit_required)
      consequences.push(
        lt(language, ground === "VIOLATION" && pet ? "tg_pet_kept" : "tg_c3"),
      );
    if (ground !== "UNPAID" || movedIn)
      consequences.push(lt(language, "tg_c2"));
    consequences.push(lt(language, movedIn ? "tg_c4" : "tg_c5"));
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={lt(language, "close")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={
        busy
          ? lt(language, "saving")
          : outcome === "unknown"
            ? lt(language, "try_again")
            : lt(language, "tg_ok")
      }
      title={lt(language, "tg_t", lease.unit_number)}
    >
      {evidence.state === "failed" && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>{lt(language, "tg_load_failed")}</p>
          <button
            className="ui-btn"
            onClick={() => {
              setAttempt((count) => count + 1);
            }}
            type="button"
          >
            {lt(language, "retry")}
          </button>
        </div>
      )}
      <fieldset className="ui-radios">
        <legend>{lt(language, "tg_ground")}</legend>
        {GROUNDS.map((item) => (
          <label className="ui-chk" key={item}>
            <input
              checked={ground === item}
              disabled={item === "UNPAID" && today < unpaidFrom}
              name="terminate-ground"
              onChange={() => {
                setGround(item);
              }}
              type="radio"
            />
            <span>
              {lt(language, `tg_${item}`)}
              <small className="ui-sub2">
                {item === "UNPAID" && today < unpaidFrom
                  ? lt(language, "tg_UNPAID_wait", dayText(unpaidFrom))
                  : lt(language, `tg_${item}_s`)}
              </small>
            </span>
          </label>
        ))}
        <Problem message={problems.ground ?? null} />
      </fieldset>
      {ground === "VIOLATION" && (
        <fieldset className="ui-radios">
          <legend>{lt(language, "tg_warnings")}</legend>
          {evidence.state === "done" && warnings.length < 3 && (
            <p className="ui-small ui-muted">
              {lt(language, "tg_warnings_few", warnings.length)}
            </p>
          )}
          {warnings.map((warning) => (
            <label className="ui-chk" key={warning.id}>
              <input
                checked={ticked.has(warning.id)}
                // The server refuses a warning given after the termination date.
                disabled={warning.warning_date > day}
                onChange={(event) => {
                  const next = new Set(ticked);
                  if (event.currentTarget.checked) next.add(warning.id);
                  else next.delete(warning.id);
                  setTicked(next);
                }}
                type="checkbox"
              />
              <span>
                {lt(
                  language,
                  "tg_warning_line",
                  warning.warning_sequence,
                  dayText(warning.warning_date),
                  warning.violation_description,
                )}
              </span>
            </label>
          ))}
          <Problem message={problems.warnings ?? null} />
          {lease.pet_deposit_required && (
            <label className="ui-chk">
              <input
                checked={pet}
                onChange={(event) => {
                  setPet(event.currentTarget.checked);
                }}
                type="checkbox"
              />
              <span>{lt(language, "tg_petrule")}</span>
            </label>
          )}
        </fieldset>
      )}
      {ground === "RENT" && (
        <fieldset className="ui-radios">
          <legend>{lt(language, "tg_notice")}</legend>
          {evidence.state === "done" && notices.length === 0 && (
            <p className="ui-small ui-muted">
              {lt(language, "tg_notice_none")}
            </p>
          )}
          {notices.map((item) => (
            <label className="ui-chk" key={item.id}>
              <input
                checked={noticeId === item.id}
                name="terminate-notice"
                onChange={() => {
                  setNoticeId(item.id);
                }}
                type="radio"
              />
              <span>
                {lt(
                  language,
                  "tg_notice_line",
                  dayText(item.notice_date),
                  dayText(noticeEnd(item)),
                  item.context?.evidence_reference ?? "",
                )}
              </span>
            </label>
          ))}
          {notice !== undefined && noticeEnd(notice) > today && (
            <p className="ui-small ui-muted">
              {lt(language, "tg_notice_wait", dayText(noticeEnd(notice)))}
            </p>
          )}
          <Problem message={problems.notice ?? null} />
          {evidence.state === "done" && (
            <button
              className="ui-btn"
              onClick={() => {
                onRecordNotice({
                  ground,
                  pet,
                  day,
                  ticked: [...ticked],
                  proof,
                  memo,
                });
              }}
              type="button"
            >
              <Icon name="plus" />
              {lt(language, "nt_new")}
            </button>
          )}
        </fieldset>
      )}
      <div className="ui-field">
        <label htmlFor="terminate-day">{lt(language, "tg_date")}</label>
        <DateInput
          language={language}
          invalid={problems.day !== undefined}
          id="terminate-day"
          max={last}
          min={first}
          onChange={(value) => {
            setDay(value);
          }}
          value={day}
        />
        <p className="help">{lt(language, "tg_date_help", dayText(first))}</p>
        <Problem message={problems.day ?? null} />
      </div>
      <div className="ui-field">
        <label htmlFor="terminate-proof">
          {lt(language, "tg_evidence")}
          <span className="req">{lt(language, "required")}</span>
        </label>
        <input
          aria-invalid={problems.proof !== undefined}
          autoComplete="off"
          id="terminate-proof"
          maxLength={500}
          onChange={(event) => {
            setProof(event.currentTarget.value);
          }}
          value={proof}
        />
        <p className="help">{lt(language, "tg_evidence_help")}</p>
        <Problem message={problems.proof ?? null} />
      </div>
      <div className="ui-field">
        <label htmlFor="terminate-memo">
          {lt(language, "tg_memo")}
          <span className="req">{lt(language, "required")}</span>
        </label>
        <textarea
          aria-invalid={problems.memo !== undefined}
          id="terminate-memo"
          maxLength={500}
          onChange={(event) => {
            setMemo(event.currentTarget.value);
          }}
          rows={2}
          value={memo}
        />
        <Problem message={problems.memo ?? null} />
      </div>
      {consequences.length > 0 && (
        <div className="ui-notice warn" role="status">
          <Icon name="info" />
          <ul className="ui-small">
            {consequences.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      )}
      <p className="ui-small ui-muted">{lt(language, "tg_final")}</p>
      <OutcomeNotice
        language={language}
        outcome={outcome}
        refused="tg_refused"
      />
    </Dialog>
  );
}

export function RecordNoticeDialog({
  language,
  lettersApi,
  lease,
  onClose,
  onSaved,
  onConflict,
}: {
  language: Language;
  lettersApi: Pick<LettersApi, "recordNotice">;
  lease: LeaseResource;
  onClose: () => void;
  onSaved: (message: string) => void;
  onConflict: () => void;
}) {
  const today = todayInPhnomPenh();
  const [given, setGiven] = useState(today);
  const [ends, setEnds] = useState(addDays(today, 30));
  const [number, setNumber] = useState("");
  // The letter text follows the end date until somebody writes their own.
  const [written, setWritten] = useState<string | null>(null);
  const text =
    written ??
    lt(language, "nt_text_default", lease.unit_number, dayText(ends));
  const [how, setHow] = useState<How | "">("");
  const [details, setDetails] = useState("");
  const [problems, setProblems] = useState<Record<string, string>>({});
  const identity = useValuesIdentity();
  const { busy, outcome, send } = useLettersSend(() => {
    onSaved(lt(language, "nt_toast", lease.unit_number));
  }, onConflict);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const reference = number.trim();
    const words = text.trim();
    const detail = details.trim();
    const found: Record<string, string> = {};
    if (!isDay(given) || !isDay(ends) || given > today || ends < given)
      found.dates = lt(language, "nt_dates_e");
    if (reference === "") found.number = lt(language, "nt_number_e");
    if (words === "") found.text = lt(language, "nt_text_e");
    if (how === "") found.how = lt(language, "nt_how_e");
    if (detail === "") found.details = lt(language, "nt_details_e");
    setProblems(found);
    if (how === "" || Object.keys(found).length > 0) return;
    const source = {
      expected_lease_version: lease.version,
      notice_date: given,
      intended_termination_date: ends,
      notice_text: words,
      governing_lease_provision: NOTICE_PROVISION,
      approved_grounds: NOTICE_GROUNDS,
      notice_period_terms: NOTICE_TERMS,
      evidence_reference: reference,
      communication_record: howRecord(how, detail),
      authorization_reference: AUTHORITY,
      reason: NOTICE_REASON,
    };
    // Try again sends the same notice id and key; changed values get new ones.
    const chosen = identity(JSON.stringify(source));
    send(() =>
      lettersApi.recordNotice(
        lease.property_id,
        lease.lease_id,
        { notice_id: chosen.id, ...source },
        chosen.key,
      ),
    );
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={lt(language, "close")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={
        busy
          ? lt(language, "saving")
          : outcome === "unknown"
            ? lt(language, "try_again")
            : lt(language, "nt_new")
      }
      title={lt(language, "nt_t", lease.unit_number)}
    >
      <p className="ui-small">{lt(language, "nt_note")}</p>
      <div className="ui-field">
        <label htmlFor="notice-given">{lt(language, "nt_date")}</label>
        <DateInput
          language={language}
          invalid={problems.dates !== undefined}
          id="notice-given"
          max={today}
          min={lease.start_date ?? undefined}
          onChange={(value) => {
            setGiven(value);
          }}
          value={given}
        />
      </div>
      <div className="ui-field">
        <label htmlFor="notice-ends">{lt(language, "nt_ends")}</label>
        <DateInput
          language={language}
          invalid={problems.dates !== undefined}
          id="notice-ends"
          min={given}
          onChange={(value) => {
            setEnds(value);
          }}
          value={ends}
        />
        <p className="help">{lt(language, "nt_ends_help")}</p>
        <Problem message={problems.dates ?? null} />
      </div>
      <div className="ui-field">
        <label htmlFor="notice-number">
          {lt(language, "nt_number")}
          <span className="req">{lt(language, "required")}</span>
        </label>
        <input
          aria-invalid={problems.number !== undefined}
          autoComplete="off"
          id="notice-number"
          maxLength={500}
          onChange={(event) => {
            setNumber(event.currentTarget.value);
          }}
          value={number}
        />
        <Problem message={problems.number ?? null} />
      </div>
      <div className="ui-field">
        <label htmlFor="notice-text">
          {lt(language, "nt_text")}
          <span className="req">{lt(language, "required")}</span>
        </label>
        <textarea
          aria-invalid={problems.text !== undefined}
          id="notice-text"
          maxLength={5000}
          onChange={(event) => {
            setWritten(event.currentTarget.value);
          }}
          rows={3}
          value={text}
        />
        <Problem message={problems.text ?? null} />
      </div>
      <div className="ui-field">
        <label htmlFor="notice-how">
          {ltr(language, "d_how")}
          <span className="req">{lt(language, "required")}</span>
        </label>
        <HowSelect
          id="notice-how"
          invalid={problems.how !== undefined}
          language={language}
          onChange={setHow}
          value={how}
        />
        <Problem message={problems.how ?? null} />
      </div>
      <div className="ui-field">
        <label htmlFor="notice-details">
          {lt(language, "nt_details")}
          <span className="req">{lt(language, "required")}</span>
        </label>
        <input
          aria-invalid={problems.details !== undefined}
          autoComplete="off"
          id="notice-details"
          maxLength={1900}
          onChange={(event) => {
            setDetails(event.currentTarget.value);
          }}
          value={details}
        />
        <Problem message={problems.details ?? null} />
      </div>
      <OutcomeNotice language={language} outcome={outcome} />
    </Dialog>
  );
}
