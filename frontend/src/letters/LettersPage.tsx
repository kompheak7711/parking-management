// V1-058 R3: the Letters tab of Leases (DESIGN.md "Letters (round 8)"). "#/letters" shows the
// Rent letters (day 20 and day 30 of unpaid Rent); "#/letters/warnings" shows the Lease rule
// warnings. A letter or a warning never ends a Lease, adds a fee or changes a Unit by itself.

import "../shell/screens.css";

import { useCallback, useEffect, useRef, useState } from "react";

import type { LeaseApi, LeaseResource } from "../leaseClient";
import { loadLeasesData } from "../leases/leasesData";
import { dayText, todayInPhnomPenh, usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { useHashDetail } from "../shell/useHashPage";
import { Chip, CountCard } from "../shell/ui";
import type { Language } from "../signInText";
import { RecordLetterDialog, RecordWarningDialog } from "./LettersDialogs";
import type { LettersApi, RentLetterEvent } from "./lettersClient";
import {
  LeaseWarnings,
  RentLetters,
  RentRow,
  dayNumber,
  howOf,
  letterDay,
  loadRentLetters,
  loadWarnings,
  nextLetter,
  warnable,
} from "./lettersData";
import { ltr, monthText } from "./text";

export interface LettersPageProps {
  language: Language;
  propertyId: string;
  /** Only the page that is shown loads; a hidden page waits until it is opened. */
  active: boolean;
  api: LettersApi;
  leaseApi: Pick<LeaseApi, "list">;
  capabilities: ReadonlySet<string> | null;
}

type Tab = "rent" | "warn";

export function LettersPage({
  language,
  propertyId,
  active,
  api,
  leaseApi,
  capabilities,
}: LettersPageProps) {
  const detail = useHashDetail("letters");
  const may = (capability: string) =>
    capabilities === null || capabilities.has(capability);
  const mayRent = may("rent_nonpayment.read");
  const mayWarn = may("leases.read");
  const tab: Tab =
    (detail === "warnings" && mayWarn) || !mayRent ? "warn" : "rent";

  const [leases, setLeases] = useState<LeaseResource[] | null>(null);
  const [rent, setRent] = useState<RentLetters | null>(null);
  const [warnings, setWarnings] = useState<LeaseWarnings | null>(null);
  const [failed, setFailed] = useState(false);
  const sequence = useRef(0);

  const load = useCallback(() => {
    if (propertyId === "") return;
    const operation = ++sequence.current;
    setFailed(false);
    void loadLeasesData(leaseApi, propertyId)
      .then(async ({ leases: found }) => {
        if (operation !== sequence.current) return;
        setLeases(found);
        if (tab === "rent") {
          const loaded = await loadRentLetters(api, propertyId, found);
          if (operation === sequence.current) setRent(loaded);
        } else {
          const loaded = await loadWarnings(api, found);
          if (operation === sequence.current) setWarnings(loaded);
        }
      })
      .catch(() => {
        if (operation === sequence.current) setFailed(true);
      });
  }, [api, leaseApi, propertyId, tab]);

  // Another Property never shows the letters of the one before.
  useEffect(() => {
    sequence.current++;
    setLeases(null);
    setRent(null);
    setWarnings(null);
  }, [propertyId]);

  // Read again each time the page or a tab is opened, so it shows what others changed.
  useEffect(() => {
    if (active) load();
  }, [active, load]);

  if (propertyId === "") {
    return (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>{ltr(language, "no_property")}</p>
      </div>
    );
  }
  if (!mayRent && !mayWarn) {
    return (
      <div className="ui-notice warn" role="status">
        <Icon name="info" />
        <p>{ltr(language, "not_allowed")}</p>
      </div>
    );
  }

  const shown = tab === "rent" ? rent : warnings;
  const businessDate = rent?.businessDate ?? todayInPhnomPenh();
  const failure = failed && (
    <div className="ui-notice warn" role="status">
      <Icon name="alert" />
      <p>{ltr(language, "failed")}</p>
      <button className="ui-btn" onClick={load} type="button">
        {ltr(language, "retry")}
      </button>
    </div>
  );

  return (
    <>
      <div className="ui-head">
        <p>
          {ltr(language, "sub")}
          {tab === "rent" && rent !== null && (
            <> · {ltr(language, "as_of", dayText(businessDate))}</>
          )}
        </p>
      </div>
      {mayRent && mayWarn && (
        <nav aria-label={ltr(language, "sub")} className="ui-subtabs">
          <a
            aria-current={tab === "rent" ? "page" : undefined}
            href={hashForPage("letters")}
          >
            {ltr(language, "tab_rent")}
          </a>
          <a
            aria-current={tab === "warn" ? "page" : undefined}
            href={hashForPage("letters", "warnings")}
          >
            {ltr(language, "tab_warn")}
          </a>
        </nav>
      )}
      {failure}
      {shown === null || leases === null ? (
        !failed && (
          <p className="ui-muted" role="status">
            {ltr(language, "loading")}
          </p>
        )
      ) : tab === "rent" && rent !== null ? (
        <RentLettersTab
          api={api}
          canOpen={may("rent_nonpayment.case_manage")}
          canRecord={may("rent_nonpayment.event_post")}
          canTerminate={may("leases.terminate")}
          data={rent}
          language={language}
          onChanged={load}
        />
      ) : (
        warnings !== null && (
          <WarningsTab
            api={api}
            canRecord={may("leases.warn")}
            data={warnings}
            language={language}
            leases={leases}
            onChanged={load}
            onRetry={load}
          />
        )
      )}
    </>
  );
}

/** One letter of a Rent month: given (with how and its number), due, or the day it falls on. */
function LetterLine({
  language,
  n,
  given,
  day,
  businessDate,
}: {
  language: Language;
  n: 20 | 30;
  given: RentLetterEvent | null;
  day: string;
  businessDate: string;
}) {
  let body;
  if (given !== null) {
    const { how } = howOf(given.communication_record);
    body = (
      <>
        <Chip icon="check" tone="ok">
          {ltr(language, "given", dayText(given.event_date))}
        </Chip>
        {(how !== null || given.notice_document_reference !== null) && (
          <span className="ui-sub2">
            {how !== null && ltr(language, `h_${how}`)}
            {how !== null && given.notice_document_reference !== null && " · "}
            {given.notice_document_reference !== null && (
              <span className="ui-nowrap">
                {given.notice_document_reference}
              </span>
            )}
          </span>
        )}
      </>
    );
  } else if (day <= businessDate) {
    body = (
      <Chip icon="alert" tone="err">
        {ltr(language, "due_since", dayText(day))}
      </Chip>
    );
  } else {
    body = (
      <span className="ui-muted">{ltr(language, "on", dayText(day))}</span>
    );
  }
  return (
    <div className="ui-letter">
      <span className="ui-letter-day">{ltr(language, "dayn", n)}</span>
      <div>{body}</div>
    </div>
  );
}

type RentCard = "due" | "w20" | "w30";

function inRentCard(row: RentRow, card: RentCard): boolean {
  const a = row.alert.assessment;
  if (card === "due") return nextLetter(row) !== null;
  if (card === "w20") return a.warning_recorded && !a.serious_default_recorded;
  return a.serious_default_recorded;
}

function RentLettersTab({
  language,
  api,
  data,
  canOpen,
  canRecord,
  canTerminate,
  onChanged,
}: {
  language: Language;
  api: LettersApi;
  data: RentLetters;
  canOpen: boolean;
  canRecord: boolean;
  canTerminate: boolean;
  onChanged: () => void;
}) {
  const [card, setCard] = useState<RentCard | "all">("all");
  const [recording, setRecording] = useState<RentRow | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const today = data.businessDate;
  const shown = data.rows.filter(
    (row) => card === "all" || inRentCard(row, card),
  );
  const late = data.rows.filter(
    (row) =>
      row.alert.assessment.thirty_day_default_eligible &&
      !row.alert.assessment.warning_recorded &&
      !row.alert.assessment.serious_default_recorded,
  );
  const unitOf = (row: RentRow) =>
    row.lease?.unit_number ?? row.alert.invoice_number;
  // Opening a case needs one capability, recording the letter on it another.
  const mayRecord = (row: RentRow) =>
    canRecord &&
    (row.alert.case_id !== null || canOpen) &&
    row.letters !== null;

  return (
    <>
      {toast !== null && (
        <div className="ui-notice ok" role="status">
          <Icon name="check" />
          <p>{toast}</p>
        </div>
      )}
      <div className="ui-kpis">
        {(
          [
            ["due", "alert", "err"],
            ["w20", "clock", "warn"],
            ["w30", "list", "warn"],
          ] as const
        ).map(([value, icon, tone]) => (
          <CountCard
            icon={icon}
            key={value}
            label={ltr(language, `c_${value}`)}
            note={ltr(language, `c_${value}_s`)}
            onPress={() => {
              setCard(card === value ? "all" : value);
            }}
            pressed={card === value}
            tone={tone}
            value={data.rows.filter((row) => inRentCard(row, value)).length}
          />
        ))}
      </div>
      {late.length > 0 && (
        <div className="ui-notice err" role="alert">
          <Icon name="alert" />
          <p>
            <b>{late.map(unitOf).join(", ")}</b> · {ltr(language, "late_open")}
          </p>
        </div>
      )}
      {data.rows
        .filter((row) => row.letters === null)
        .map((row) => (
          <div
            className="ui-notice warn"
            key={row.alert.rent_invoice_line_id}
            role="status"
          >
            <Icon name="alert" />
            <p>{ltr(language, "letters_failed", unitOf(row))}</p>
            <button className="ui-btn" onClick={onChanged} type="button">
              {ltr(language, "retry")}
            </button>
          </div>
        ))}
      <div className="ui-card pad0">
        <div className="ui-chead pad">
          <h2>{ltr(language, "cases")}</h2>
        </div>
        {card !== "all" && (
          <div className="ui-listbar">
            {ltr(language, "showing", ltr(language, `c_${card}`))}
            <button
              className="ui-btn link"
              onClick={() => {
                setCard("all");
              }}
              type="button"
            >
              {ltr(language, "show_all")}
            </button>
          </div>
        )}
        {shown.length === 0 ? (
          <p className="ui-empty">
            {ltr(language, data.rows.length === 0 ? "none" : "none_here")}
          </p>
        ) : (
          <div className="ui-tablewrap">
            <table className="ui-table">
              <thead>
                <tr>
                  <th scope="col">{ltr(language, "col_case")}</th>
                  <th scope="col">{ltr(language, "col_month")}</th>
                  <th scope="col">{ltr(language, "col_letters")}</th>
                  <th scope="col">{ltr(language, "col_next")}</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((row) => {
                  const a = row.alert.assessment;
                  const next = nextLetter(row);
                  const d30 = letterDay(row.monthStart, 30);
                  return (
                    <tr key={row.alert.rent_invoice_line_id}>
                      <td>
                        {row.lease === undefined ? (
                          <span className="ui-num">{unitOf(row)}</span>
                        ) : (
                          <a
                            className="ui-no ui-num"
                            href={hashForPage("leases", row.lease.lease_id)}
                          >
                            {row.lease.unit_number}
                          </a>
                        )}
                        {row.lease !== undefined && (
                          <span className="ui-sub2">
                            {row.lease.primary_tenant_name}
                          </span>
                        )}
                        <span className="ui-sub2 ui-num">
                          {ltr(
                            language,
                            "owed_line",
                            usdFromCents(a.remaining_rent.minor_units),
                          )}
                        </span>
                      </td>
                      <td>
                        {monthText(language, row.monthStart)}
                        <span className="ui-sub2 ui-num">
                          {row.alert.invoice_number} ·{" "}
                          {ltr(
                            language,
                            "dayn",
                            dayNumber(row.monthStart, today),
                          )}
                        </span>
                        <span className="ui-sub2 ui-num">
                          {ltr(
                            language,
                            "due_date",
                            dayText(row.alert.due_date),
                          )}
                        </span>
                      </td>
                      <td className="wrap ui-letters">
                        <LetterLine
                          businessDate={today}
                          day={letterDay(row.monthStart, 20)}
                          given={row.letters?.d20 ?? null}
                          language={language}
                          n={20}
                        />
                        <LetterLine
                          businessDate={today}
                          day={d30}
                          given={row.letters?.d30 ?? null}
                          language={language}
                          n={30}
                        />
                      </td>
                      <td className="wrap">
                        {next !== null ? (
                          mayRecord(row) ? (
                            <button
                              className="ui-btn primary"
                              onClick={() => {
                                setToast(null);
                                setRecording(row);
                              }}
                              type="button"
                            >
                              <Icon name="plus" />
                              {ltr(language, "rec")}
                            </button>
                          ) : (
                            <span className="ui-small ui-muted">
                              {ltr(language, "rec")}
                            </span>
                          )
                        ) : a.serious_default_recorded ? (
                          canTerminate && row.lease !== undefined ? (
                            <a
                              className="ui-btn ui-btn-wrap"
                              href={hashForPage("leases", row.lease.lease_id)}
                            >
                              <Icon name="x" />
                              {ltr(language, "term")}
                              <span className="ui-badge">
                                {ltr(language, "mgr_badge")}
                              </span>
                            </a>
                          ) : (
                            <span className="ui-small ui-muted">
                              {ltr(language, "no_step")}
                            </span>
                          )
                        ) : (
                          <span className="ui-small ui-muted">
                            {ltr(language, "wait30", dayText(d30))}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <div className="ui-split">
        <div className="ui-notice" role="note">
          <Icon name="info" />
          <p>{ltr(language, "how_count")}</p>
        </div>
        <div className="ui-notice" role="note">
          <Icon name="info" />
          <p>{ltr(language, "nothing")}</p>
        </div>
      </div>
      {recording !== null && (
        <RecordLetterDialog
          api={api}
          businessDate={today}
          language={language}
          onClose={(openedCase) => {
            setRecording(null);
            if (openedCase) onChanged();
          }}
          onConflict={() => {
            setRecording(null);
            setToast(ltr(language, "conflict"));
            onChanged();
          }}
          onSaved={(message) => {
            setRecording(null);
            setToast(message);
            onChanged();
          }}
          row={recording}
          unit={unitOf(recording)}
        />
      )}
    </>
  );
}

function WarningsTab({
  language,
  api,
  data,
  leases,
  canRecord,
  onChanged,
  onRetry,
}: {
  language: Language;
  api: LettersApi;
  data: LeaseWarnings;
  leases: LeaseResource[];
  canRecord: boolean;
  onChanged: () => void;
  onRetry: () => void;
}) {
  const today = todayInPhnomPenh();
  // undefined: closed; null: open with no Lease chosen yet.
  const [recording, setRecording] = useState<string | null | undefined>(
    undefined,
  );
  const [toast, setToast] = useState<string | null>(null);
  const counts = new Map(
    data.rows.map((row) => [row.lease.lease_id, row.warnings.length]),
  );
  const open = (leaseId: string | null) => {
    setToast(null);
    setRecording(leaseId);
  };

  return (
    <>
      {toast !== null && (
        <div className="ui-notice ok" role="status">
          <Icon name="check" />
          <p>{toast}</p>
        </div>
      )}
      <div className="ui-notice" role="note">
        <Icon name="info" />
        <p>{ltr(language, "lw_rule")}</p>
      </div>
      {data.failed.length > 0 && (
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>
            {ltr(
              language,
              "lw_some_failed",
              data.failed.map((lease) => lease.unit_number).join(", "),
            )}
          </p>
          <button className="ui-btn" onClick={onRetry} type="button">
            {ltr(language, "retry")}
          </button>
        </div>
      )}
      <div className="ui-card pad0">
        <div className="ui-chead pad">
          <h2>{ltr(language, "tab_warn")}</h2>
          {canRecord && (
            <button
              className="ui-btn primary"
              onClick={() => {
                open(null);
              }}
              type="button"
            >
              <Icon name="plus" />
              {ltr(language, "lw_new")}
            </button>
          )}
        </div>
        {data.rows.length === 0 ? (
          <p className="ui-empty">{ltr(language, "lw_none")}</p>
        ) : (
          <div className="ui-tablewrap">
            <table className="ui-table">
              <thead>
                <tr>
                  <th scope="col">{ltr(language, "lw_lease")}</th>
                  <th scope="col">{ltr(language, "lw_col_n")}</th>
                  <th scope="col">{ltr(language, "lw_col_last")}</th>
                  <th scope="col">{ltr(language, "lw_col_what")}</th>
                  {canRecord && (
                    <th scope="col">
                      <span className="ui-sr">{ltr(language, "lw_new")}</span>
                    </th>
                  )}
                </tr>
              </thead>
              <tbody>
                {data.rows.map(({ lease, warnings }) => {
                  const last = warnings[warnings.length - 1];
                  if (last === undefined) return null;
                  const { how } = howOf(last.communication_record);
                  return (
                    <tr key={lease.lease_id}>
                      <td>
                        <a
                          className="ui-no ui-num"
                          href={hashForPage("leases", lease.lease_id)}
                        >
                          {ltr(language, "lease_name", lease.unit_number)}
                        </a>
                        <span className="ui-sub2">
                          {lease.primary_tenant_name}
                        </span>
                      </td>
                      <td>
                        <Chip tone={warnings.length >= 3 ? "err" : "warn"}>
                          {ltr(language, "lw_n", warnings.length)}
                        </Chip>
                      </td>
                      <td className="ui-num">{dayText(last.warning_date)}</td>
                      <td className="wrap">
                        {last.violation_description}
                        <span className="ui-sub2">
                          {ltr(language, "lw_d_clause")} {last.lease_provision}
                          {how !== null && <> · {ltr(language, `h_${how}`)}</>}
                        </span>
                      </td>
                      {canRecord && (
                        <td>
                          {warnable(lease, today) && (
                            <button
                              className="ui-btn"
                              onClick={() => {
                                open(lease.lease_id);
                              }}
                              type="button"
                            >
                              <Icon name="plus" />
                              {ltr(language, "lw_new")}
                            </button>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {recording !== undefined && (
        <RecordWarningDialog
          api={api}
          counts={counts}
          language={language}
          leaseId={recording}
          leases={leases}
          onClose={() => {
            setRecording(undefined);
          }}
          onConflict={() => {
            setRecording(undefined);
            setToast(ltr(language, "conflict"));
            onChanged();
          }}
          onSaved={(message) => {
            setRecording(undefined);
            setToast(message);
            onChanged();
          }}
        />
      )}
    </>
  );
}
