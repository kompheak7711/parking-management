// General Ledger phase 6 step 6 part 1 (mock-up v76, app22/app26/app29/app34): Office › Ledger
// with the tabs Journal entries, Needs check, Chart of accounts and Financial statements.
// Reading needs ledger.read; setting a method's account needs ledger.accounts.manage (Owner).
// The server checks every right again and makes every number; this page only shows them.

import "../shell/screens.css";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

import { DateInput } from "../shell/DateInput";
import {
  dayText,
  momentText,
  todayInPhnomPenh,
  usdFromCents,
} from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { useHashDetail } from "../shell/useHashPage";
import { Chip, Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import {
  ACCOUNT_TYPES,
  type Account,
  type BooksCheckRow,
  type Chart,
  type Entry,
  type Journal,
  LedgerError,
  type LedgerApi,
  ledgerApi as defaultLedgerApi,
  type MethodAccount,
  type PostingProblem,
  type Report,
  type ReportName,
  type ReportQuery,
  type ReportRow,
} from "./ledgerClient";
import {
  hasLedgerText,
  type LedgerTextKey,
  lt,
  monthLabel,
  typeName,
} from "./text";

export type LedgerTab = "journal" | "needscheck" | "chart" | "statements";

/** The Chart of accounts address that opens Opening balances (#/chart/opening). */
export const OPENING = "opening";

export interface LedgerPageProps {
  language: Language;
  propertyId: string;
  /** Only the tab that is shown loads; a hidden tab waits until it is opened. */
  active: boolean;
  tab: LedgerTab;
  capabilities: ReadonlySet<string> | null;
  api?: LedgerApi;
}

export function money(cents: number | null | undefined): string {
  return cents === null || cents === undefined ? "" : usdFromCents(cents);
}

export function accountName(
  language: Language,
  account: { name_en: string; name_km: string | null },
): string {
  return language === "km" && account.name_km !== null
    ? account.name_km
    : account.name_en;
}

function refusal(language: Language, error: unknown): string {
  if (error instanceof LedgerError) {
    if (error.status === 403) return lt(language, "f_right");
    if (error.status === 404) return lt(language, "not_found");
    if (error.status === 422 && error.detail !== null)
      return lt(language, "f_refused", error.detail);
  }
  return lt(language, "f_failed");
}

export function Waiting({
  language,
  failed,
  onRetry,
}: {
  language: Language;
  failed: boolean;
  onRetry: () => void;
}) {
  if (!failed) {
    return (
      <p className="ui-muted" role="status">
        {lt(language, "loading")}
      </p>
    );
  }
  return (
    <div className="ui-notice warn" role="status">
      <Icon name="alert" />
      <p>{lt(language, "failed")}</p>
      <button className="ui-btn" onClick={onRetry} type="button">
        {lt(language, "retry")}
      </button>
    </div>
  );
}

/** Reads one thing each time the tab is opened, so it shows what others changed meanwhile. */
export function useRead<T>(
  active: boolean,
  read: (() => Promise<T>) | null,
): { data: T | null; failed: boolean; reload: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [failed, setFailed] = useState(false);
  const sequence = useRef(0);
  const reload = useCallback(() => {
    if (read === null) return;
    const operation = ++sequence.current;
    setFailed(false);
    read().then(
      (value) => {
        if (operation === sequence.current) setData(value);
      },
      () => {
        // Never keep showing an old list as if it were new: the page shows the failure instead.
        if (operation === sequence.current) {
          setData(null);
          setFailed(true);
        }
      },
    );
  }, [read]);
  useEffect(() => {
    if (active) reload();
  }, [active, reload]);
  return { data, failed, reload };
}

export function LedgerPage({
  language,
  propertyId,
  active,
  tab,
  capabilities,
  api = defaultLedgerApi,
}: LedgerPageProps) {
  const may = (capability: string) =>
    capabilities === null || capabilities.has(capability);
  if (propertyId === "") {
    return (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>{lt(language, "no_property")}</p>
      </div>
    );
  }
  if (tab === "journal")
    return (
      <JournalTab
        active={active}
        api={api}
        language={language}
        propertyId={propertyId}
      />
    );
  if (tab === "needscheck")
    return (
      <NeedsCheckTab
        active={active}
        api={api}
        canSet={may("ledger.accounts.manage")}
        canType={may("ledger.money_move")}
        language={language}
        propertyId={propertyId}
      />
    );
  if (tab === "chart")
    return (
      <ChartTab
        active={active}
        api={api}
        language={language}
        propertyId={propertyId}
      />
    );
  return (
    <StatementsTab
      active={active}
      api={api}
      language={language}
      propertyId={propertyId}
    />
  );
}

/* ---------- Journal entries ---------- */

function kindText(language: Language, kind: string, source: string): string {
  const sourceKey = `s_${source}`;
  if (kind === "AUTO" && hasLedgerText(sourceKey))
    return lt(language, sourceKey);
  const kindKey = `k_${kind}`;
  return hasLedgerText(kindKey) ? lt(language, kindKey) : kind;
}

function SourceCell({
  number,
  link,
}: {
  number: string | null;
  link: { page: "invoices" | "payments"; detail: string } | null;
}) {
  if (number === null) return <>—</>;
  if (link === null) return <span className="ui-num">{number}</span>;
  return (
    <a className="ui-num" href={hashForPage(link.page, link.detail)}>
      {number}
    </a>
  );
}

function JournalTab({
  language,
  propertyId,
  active,
  api,
}: {
  language: Language;
  propertyId: string;
  active: boolean;
  api: LedgerApi;
}) {
  const detail = useHashDetail("journal");
  const [month, setMonth] = useState("");
  const read = useCallback(
    () => api.entries(propertyId, month === "" ? undefined : month),
    [api, propertyId, month],
  );
  const { data, failed, reload } = useRead<Journal>(
    active && detail === null,
    read,
  );
  if (detail !== null) {
    return (
      <EntryDetail
        active={active}
        api={api}
        entryNumber={detail}
        language={language}
        propertyId={propertyId}
      />
    );
  }
  if (data === null)
    return <Waiting failed={failed} language={language} onRetry={reload} />;
  return (
    <section aria-labelledby="journal-title" className="ui-card pad0">
      <header className="ui-chead pad">
        <h2 id="journal-title">{lt(language, "j_title")}</h2>
      </header>
      <p className="ui-muted pad">{lt(language, "j_sub")}</p>
      <div className="ui-field pad">
        <label htmlFor="journal-month">{lt(language, "month")}</label>
        <select
          id="journal-month"
          onChange={(event) => {
            setMonth(event.target.value);
          }}
          value={month}
        >
          <option value="">{lt(language, "all_months")}</option>
          {data.months.map((value) => (
            <option key={value} value={value}>
              {monthLabel(language, value)}
            </option>
          ))}
        </select>
      </div>
      {data.entries.length === 0 ? (
        <p className="ui-muted pad">{lt(language, "j_none")}</p>
      ) : (
        <div className="ui-tablewrap">
          <table className="ui-table">
            <thead>
              <tr>
                <th scope="col">{lt(language, "no")}</th>
                <th scope="col">{lt(language, "date")}</th>
                <th scope="col">{lt(language, "what")}</th>
                <th scope="col">{lt(language, "from")}</th>
                <th className="r" scope="col">
                  {lt(language, "amount")}
                </th>
              </tr>
            </thead>
            <tbody>
              {data.entries.map((entry) => (
                <tr key={entry.entry_number}>
                  <td>
                    <a
                      className="ui-num"
                      href={hashForPage("journal", entry.entry_number)}
                    >
                      {entry.entry_number}
                    </a>
                  </td>
                  <td className="ui-num">{dayText(entry.entry_date)}</td>
                  <td>
                    {kindText(language, entry.entry_kind, entry.source_type)}
                    <span className="ui-muted ui-sub2">
                      {entry.description}
                    </span>
                  </td>
                  <td>
                    {entry.reverses !== null ? (
                      <a
                        className="ui-num"
                        href={hashForPage("journal", entry.reverses)}
                      >
                        {entry.reverses}
                      </a>
                    ) : (
                      <SourceCell
                        link={entry.source_link}
                        number={entry.source_number}
                      />
                    )}
                  </td>
                  <td className="r ui-num">{money(entry.amount_cents)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data.newest_only && data.entries.length > 0 && (
        <p className="ui-muted pad">
          {lt(language, "newest", String(data.entries.length))}
        </p>
      )}
    </section>
  );
}

function EntryDetail({
  language,
  propertyId,
  active,
  api,
  entryNumber,
}: {
  language: Language;
  propertyId: string;
  active: boolean;
  api: LedgerApi;
  entryNumber: string;
}) {
  const read = useCallback(
    () => api.entry(propertyId, entryNumber),
    [api, propertyId, entryNumber],
  );
  const [error, setError] = useState<unknown>(null);
  const guarded = useCallback(
    () =>
      read().catch((caught: unknown) => {
        setError(caught);
        throw caught;
      }),
    [read],
  );
  const { data, failed, reload } = useRead<Entry>(active, guarded);
  const back = (
    <a className="ui-crumb" href={hashForPage("journal")}>
      <Icon name="back" small />
      {lt(language, "j_title")}
    </a>
  );
  if (data === null || data.entry_number !== entryNumber) {
    if (failed && error instanceof LedgerError && error.status === 404) {
      return (
        <>
          {back}
          <p className="ui-muted">{lt(language, "not_found")}</p>
        </>
      );
    }
    return (
      <>
        {back}
        <Waiting failed={failed} language={language} onRetry={reload} />
      </>
    );
  }
  const debit = data.lines.reduce((sum, line) => sum + line.debit_cents, 0);
  const credit = data.lines.reduce((sum, line) => sum + line.credit_cents, 0);
  return (
    <>
      {back}
      <section aria-labelledby="entry-title" className="ui-card pad0">
        <header className="ui-chead pad">
          <h2 className="ui-num" id="entry-title">
            {data.entry_number}
          </h2>
          <span className="ui-actions">
            {debit === credit && (
              <Chip icon="check" tone="ok">
                {lt(language, "balanced")}
              </Chip>
            )}
            {data.reversed_by !== null && (
              <Chip tone="neutral">
                {lt(language, "rev_done", data.reversed_by)}
              </Chip>
            )}
            {data.month_closed && (
              <Chip icon="lock" tone="neutral">
                {lt(language, "closed_month")}
              </Chip>
            )}
          </span>
        </header>
        <p className="ui-muted pad">
          {kindText(language, data.entry_kind, data.source_type)} ·{" "}
          <span className="ui-num">{dayText(data.entry_date)}</span> ·{" "}
          {data.description}
        </p>
        <p className="pad">
          {lt(language, "from")}:{" "}
          {data.reverses !== null ? (
            <>
              {lt(language, "rev_of", "")}
              <a
                className="ui-num"
                href={hashForPage("journal", data.reverses)}
              >
                {data.reverses}
              </a>
            </>
          ) : (
            <SourceCell link={data.source_link} number={data.source_number} />
          )}
        </p>
        <div className="ui-tablewrap">
          <table className="ui-table">
            <thead>
              <tr>
                <th scope="col">{lt(language, "account")}</th>
                <th className="r" scope="col">
                  {lt(language, "debit")}
                </th>
                <th className="r" scope="col">
                  {lt(language, "credit")}
                </th>
              </tr>
            </thead>
            <tbody>
              {data.lines.map((line, index) => (
                <tr key={`${line.account_code}-${String(index)}`}>
                  <td>
                    <a href={hashForPage("chart", line.account_code)}>
                      <span className="ui-num">{line.account_code}</span> ·{" "}
                      {accountName(language, {
                        name_en: line.account_name_en,
                        name_km: line.account_name_km,
                      })}
                    </a>
                    {line.memo !== null && (
                      <span className="ui-muted ui-sub2">{line.memo}</span>
                    )}
                  </td>
                  <td className="r ui-num">
                    {line.debit_cents > 0 ? money(line.debit_cents) : ""}
                  </td>
                  <td className="r ui-num">
                    {line.credit_cents > 0 ? money(line.credit_cents) : ""}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row">{lt(language, "total")}</th>
                <td className="r ui-num">{money(debit)}</td>
                <td className="r ui-num">{money(credit)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
        {data.reason !== null && (
          <p className="pad">
            {lt(language, "reason")}: {data.reason}
          </p>
        )}
        <p className="ui-muted pad">
          <Icon name="lock" small /> {lt(language, "je_note")}
          {data.entry_kind === "AUTO" ? ` ${lt(language, "rev_ctl")}` : ""}
        </p>
        <p className="ui-muted pad">
          {lt(language, "posted_by")}:{" "}
          {data.posted_by_name ?? lt(language, "app")} ·{" "}
          <span className="ui-num">{momentText(data.posted_at)}</span>
          {data.approved_by_name !== null &&
            ` · ${lt(language, "approved_by")}: ${data.approved_by_name}`}
        </p>
      </section>
    </>
  );
}

/* ---------- Needs check ---------- */

const PAY_PREFIX = "No ledger account is set for the Payment Method";
const REFUND_PREFIX = "No ledger account is set for the Refund method";
// Refund paid from a riel account (migration 20270612_321, DL-161).
const TYPE_RIEL = "Type the riel paid for this Refund";
const READY = "Ready: it posts at the next run";
const RIEL_CORRECTION = "A Refund correction on a riel account cannot post yet";

/** Riel as typed: whole riel, 1 to 15 digits; commas and spaces are allowed. */
function typedRiel(typed: string): number | null {
  const value = typed.trim().replace(/[,\s]/g, "");
  if (!/^\d{1,15}$/.test(value)) return null;
  const riel = Number(value);
  return riel > 0 ? riel : null;
}

/** The problem in the screen's language; text from the database itself is never shown. */
function problemText(language: Language, problem: string): string {
  if (problem.startsWith(PAY_PREFIX))
    return lt(language, "nc_r_pay", problem.slice(PAY_PREFIX.length).trim());
  if (problem.startsWith(REFUND_PREFIX))
    return lt(
      language,
      "nc_r_refund",
      problem.slice(REFUND_PREFIX.length).trim(),
    );
  if (problem === TYPE_RIEL) return lt(language, "nc_r_riel");
  if (problem === READY) return lt(language, "nc_r_ready");
  if (problem === RIEL_CORRECTION) return lt(language, "nc_r_rcorr");
  return lt(language, "nc_r_other");
}

function problemMethod(
  problem: PostingProblem,
  methods: readonly MethodAccount[],
): MethodAccount | null {
  const kind = problem.problem.startsWith(PAY_PREFIX)
    ? "PAYMENT"
    : problem.problem.startsWith(REFUND_PREFIX)
      ? "REFUND"
      : null;
  if (kind === null) return null;
  const prefix = kind === "PAYMENT" ? PAY_PREFIX : REFUND_PREFIX;
  const name = problem.problem.slice(prefix.length).trim();
  const ofKind = methods.filter((method) => method.kind === kind);
  return (
    ofKind.find((method) => name !== "" && method.name === name) ??
    (ofKind.filter((method) => method.account_code === null).length === 1
      ? (ofKind.find((method) => method.account_code === null) ?? null)
      : null)
  );
}

interface NeedsData {
  problems: PostingProblem[];
  methods: MethodAccount[];
  chart: Chart;
}

function NeedsCheckTab({
  language,
  propertyId,
  active,
  api,
  canSet,
  canType = false,
}: {
  language: Language;
  propertyId: string;
  active: boolean;
  api: LedgerApi;
  canSet: boolean;
  /** ledger.money_move: may type the riel paid for a Refund from a riel account. */
  canType?: boolean;
}) {
  const read = useCallback(
    () =>
      Promise.all([
        api.needsCheck(propertyId),
        api.methodAccounts(propertyId),
        api.accounts(propertyId),
      ]).then(([problems, methods, chart]) => ({ problems, methods, chart })),
    [api, propertyId],
  );
  const { data, failed, reload } = useRead<NeedsData>(active, read);
  const [open, setOpen] = useState<MethodAccount | null>(null);
  const [typing, setTyping] = useState<PostingProblem | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  if (data === null)
    return <Waiting failed={failed} language={language} onRetry={reload} />;
  // A riel bank account is never a method's main account: it keeps riel only.
  const cash = data.chart.accounts.filter(
    (account) =>
      account.account_type === "ASSET" &&
      account.active &&
      account.code.startsWith("10") &&
      account.cash_kind !== "BANK_KHR",
  );
  const riel = data.chart.accounts.filter(
    (account) =>
      account.active &&
      (account.cash_kind === "CASH_KHR" || account.cash_kind === "BANK_KHR"),
  );
  return (
    <>
      {notice !== null && (
        <div className="ui-notice ok" role="status">
          <Icon name="check" />
          <p>{notice}</p>
        </div>
      )}
      <section aria-labelledby="nc-title" className="ui-card pad0">
        <header className="ui-chead pad">
          <h2 id="nc-title">
            {lt(language, "nc_title")} · {lt(language, "nc_open")}{" "}
            <span className="ui-num">{data.problems.length}</span>
          </h2>
        </header>
        <p className="ui-muted pad">{lt(language, "nc_sub")}</p>
        {data.problems.length === 0 ? (
          <p className="ui-muted pad">{lt(language, "nc_none")}</p>
        ) : (
          <div className="ui-tablewrap">
            <table className="ui-table">
              <thead>
                <tr>
                  <th scope="col">{lt(language, "nc_record")}</th>
                  <th scope="col">{lt(language, "date")}</th>
                  <th scope="col">{lt(language, "nc_reason")}</th>
                  <th scope="col">
                    <span className="ui-sr">{lt(language, "nc_set")}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.problems.map((problem) => {
                  const method = problemMethod(problem, data.methods);
                  return (
                    <tr key={problem.posting_key}>
                      <td>
                        {kindText(language, "AUTO", problem.source_type)}
                        <span className="ui-sub2">
                          <SourceCell
                            link={problem.source_link}
                            number={problem.source_number}
                          />
                        </span>
                      </td>
                      <td className="ui-num">{dayText(problem.event_date)}</td>
                      <td className="wrap">
                        {problemText(language, problem.problem)}
                      </td>
                      <td>
                        {canType && problem.problem === TYPE_RIEL && (
                          <button
                            className="ui-btn"
                            onClick={() => {
                              setNotice(null);
                              setFailure(null);
                              setTyping(problem);
                            }}
                            type="button"
                          >
                            {lt(language, "nc_riel_type")}
                          </button>
                        )}
                        {canSet && method !== null && (
                          <button
                            className="ui-btn"
                            onClick={() => {
                              setNotice(null);
                              setFailure(null);
                              setOpen(method);
                            }}
                            type="button"
                          >
                            {lt(
                              language,
                              method.kind === "REFUND" ? "nc_set_m" : "nc_set",
                            )}
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className="ui-muted pad">
          <Icon name="info" small /> {lt(language, "nc_note")}
        </p>
      </section>
      {(["PAYMENT", "REFUND"] as const).map((kind) => (
        <section
          aria-labelledby={`nc-methods-${kind}`}
          className="ui-card pad0"
          key={kind}
        >
          <header className="ui-chead pad">
            <h2 id={`nc-methods-${kind}`}>
              {lt(language, kind === "PAYMENT" ? "nc_macc" : "nc_racc")}
            </h2>
          </header>
          <p className="ui-muted pad">
            {lt(language, kind === "PAYMENT" ? "nc_macc_s" : "nc_racc_h")}
          </p>
          <div className="ui-tablewrap">
            <table className="ui-table">
              <thead>
                <tr>
                  <th scope="col">
                    {lt(
                      language,
                      kind === "PAYMENT" ? "nc_method" : "nc_rmethod",
                    )}
                  </th>
                  <th scope="col">{lt(language, "account")}</th>
                  <th scope="col">
                    <span className="ui-sr">{lt(language, "nc_change")}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.methods
                  .filter((method) => method.kind === kind)
                  .map((method) => (
                    <tr key={method.method_id}>
                      <td>{method.name}</td>
                      <td>
                        {method.account_code === null ? (
                          <Chip tone="warn">{lt(language, "nc_notset")}</Chip>
                        ) : (
                          <>
                            <span className="ui-num">
                              {method.account_code}
                            </span>{" "}
                            · {chartName(language, data.chart, method)}
                            {method.riel_account_code !== null && (
                              <span className="ui-sub2">
                                {lt(
                                  language,
                                  "nc_riel_line",
                                  `${method.riel_account_code} · ${rielName(language, data.chart, method)}`,
                                )}
                              </span>
                            )}
                            {method.effective_from !== null && (
                              <span className="ui-muted ui-sub2">
                                {lt(
                                  language,
                                  "nc_since",
                                  dayText(method.effective_from),
                                )}
                              </span>
                            )}
                          </>
                        )}
                      </td>
                      <td>
                        {canSet && (
                          <button
                            className="ui-btn"
                            onClick={() => {
                              setNotice(null);
                              setFailure(null);
                              setOpen(method);
                            }}
                            type="button"
                          >
                            {lt(
                              language,
                              method.account_code === null
                                ? "nc_set"
                                : "nc_change",
                            )}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          {!canSet && (
            <p className="ui-muted pad">{lt(language, "nc_owner_only")}</p>
          )}
        </section>
      ))}
      {typing !== null && (
        <RefundRielDialog
          busy={busy}
          failure={failure}
          language={language}
          number={typing.source_number ?? ""}
          onClose={() => {
            setTyping(null);
            setFailure(null);
          }}
          onSave={(riel) => {
            setBusy(true);
            setFailure(null);
            api
              .recordRefundRiel(propertyId, {
                refund_id: typing.source_id,
                riel_minor: riel,
              })
              .then(
                () => {
                  setBusy(false);
                  setTyping(null);
                  setNotice(
                    lt(language, "nc_rr_saved", typing.source_number ?? ""),
                  );
                  reload();
                },
                (error: unknown) => {
                  setBusy(false);
                  setFailure(refusal(language, error));
                },
              );
          }}
        />
      )}
      {open !== null && (
        <MethodAccountDialog
          busy={busy}
          cash={cash}
          earliest={data.problems.reduce<string | null>(
            (first, problem) =>
              first === null || problem.event_date < first
                ? problem.event_date
                : first,
            null,
          )}
          failure={failure}
          language={language}
          method={open}
          riel={riel}
          onClose={() => {
            setOpen(null);
            setFailure(null);
          }}
          onSave={(code, rielCode, from) => {
            setBusy(true);
            setFailure(null);
            api
              .setMethodAccount(propertyId, {
                kind: open.kind,
                method_id: open.method_id,
                account_code: code,
                effective_from: from,
                riel_account_code: rielCode,
              })
              .then(
                () => {
                  setBusy(false);
                  setOpen(null);
                  setNotice(lt(language, "nc_saved", open.name, code));
                  reload();
                },
                (error: unknown) => {
                  setBusy(false);
                  setFailure(refusal(language, error));
                },
              );
          }}
        />
      )}
    </>
  );
}

function chartName(
  language: Language,
  chart: Chart,
  method: MethodAccount,
): string {
  const account = chart.accounts.find(
    (item) => item.code === method.account_code,
  );
  if (account !== undefined) return accountName(language, account);
  return method.account_name ?? "";
}

function rielName(
  language: Language,
  chart: Chart,
  method: MethodAccount,
): string {
  const account = chart.accounts.find(
    (item) => item.code === method.riel_account_code,
  );
  if (account !== undefined) return accountName(language, account);
  return method.riel_account_name ?? "";
}

function MethodAccountDialog({
  language,
  method,
  cash,
  riel,
  earliest,
  busy,
  failure,
  onClose,
  onSave,
}: {
  language: Language;
  method: MethodAccount;
  cash: readonly Account[];
  /** Riel cash and riel bank accounts: a Payment Method may send riel to one. */
  riel: readonly Account[];
  /** The oldest record waiting in Needs check, if any. */
  earliest: string | null;
  busy: boolean;
  failure: string | null;
  onClose: () => void;
  onSave: (code: string, rielCode: string | null, from: string) => void;
}) {
  // A Refund method may go to the riel bank account too (owner 05/11/2026, DL-161).
  const choices =
    method.kind === "REFUND"
      ? [...cash, ...riel.filter((account) => account.cash_kind === "BANK_KHR")]
      : cash;
  const [code, setCode] = useState(
    method.account_code ?? choices[0]?.code ?? "",
  );
  const [rielCode, setRielCode] = useState(method.riel_account_code ?? "");
  // A method with no account yet starts on the oldest waiting record, so it can post
  // (owner test 04/11/2026: from today, older Payments kept waiting).
  const [from, setFrom] = useState(
    method.account_code === null && earliest !== null
      ? earliest
      : todayInPhnomPenh(),
  );
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (code === "" || from === "") return;
    // Refunds are paid in dollars, so only a Payment Method has a riel account.
    onSave(
      code,
      method.kind === "PAYMENT" && rielCode !== "" ? rielCode : null,
      from,
    );
  }
  return (
    <Dialog
      busy={busy}
      closeLabel={lt(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={lt(language, "save")}
      title={lt(language, "nc_acc_t", method.name)}
    >
      <div className="ui-field">
        <label htmlFor="ma-account">
          {lt(language, "account")}
          <span className="req">{lt(language, "required")}</span>
        </label>
        <select
          id="ma-account"
          onChange={(event) => {
            setCode(event.target.value);
          }}
          required
          value={code}
        >
          {choices.map((account) => (
            <option key={account.code} value={account.code}>
              {account.code} · {accountName(language, account)}
            </option>
          ))}
        </select>
      </div>
      {method.kind === "PAYMENT" && (
        <div className="ui-field">
          <label htmlFor="ma-riel">{lt(language, "nc_riel")}</label>
          <select
            aria-describedby="ma-riel-h"
            id="ma-riel"
            onChange={(event) => {
              setRielCode(event.target.value);
            }}
            value={rielCode}
          >
            <option value="">{lt(language, "nc_riel_none")}</option>
            {riel.map((account) => (
              <option key={account.code} value={account.code}>
                {account.code} · {accountName(language, account)}
              </option>
            ))}
          </select>
          <p className="ui-muted" id="ma-riel-h">
            {lt(language, "nc_riel_h")}
          </p>
        </div>
      )}
      <div className="ui-field">
        <label htmlFor="ma-from">
          {lt(language, "nc_from")}
          <span className="req">{lt(language, "required")}</span>
        </label>
        <DateInput
          calendarLabel={lt(language, "nc_from")}
          id="ma-from"
          language={language}
          onChange={setFrom}
          required
          value={from}
        />
      </div>
      <p className="ui-muted">{lt(language, "nc_acc_future")}</p>
      {failure !== null && (
        <p className="ui-error" role="alert">
          {failure}
        </p>
      )}
    </Dialog>
  );
}

function RefundRielDialog({
  language,
  number,
  busy,
  failure,
  onClose,
  onSave,
}: {
  language: Language;
  /** The Refund number. */
  number: string;
  busy: boolean;
  failure: string | null;
  onClose: () => void;
  onSave: (riel: number) => void;
}) {
  const [typed, setTyped] = useState("");
  const [bad, setBad] = useState(false);
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const riel = typedRiel(typed);
    setBad(riel === null);
    if (riel !== null) onSave(riel);
  }
  return (
    <Dialog
      busy={busy}
      closeLabel={lt(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={lt(language, "save")}
      title={lt(language, "nc_rr_t", number)}
    >
      <div className="ui-field">
        <label htmlFor="rr-riel">
          {lt(language, "nc_rr_amt")}
          <span className="req">{lt(language, "required")}</span>
        </label>
        <input
          aria-describedby="rr-riel-h"
          aria-invalid={bad}
          autoComplete="off"
          className="ui-num"
          id="rr-riel"
          inputMode="numeric"
          onChange={(event) => {
            setTyped(event.target.value);
          }}
          required
          value={typed}
        />
        <p className="ui-muted" id="rr-riel-h">
          {lt(language, "nc_rr_h")}
        </p>
      </div>
      {bad && (
        <p className="ui-error" role="alert">
          {lt(language, "nc_rr_bad")}
        </p>
      )}
      {failure !== null && (
        <p className="ui-error" role="alert">
          {failure}
        </p>
      )}
    </Dialog>
  );
}

/* ---------- Chart of accounts ---------- */

function AccountChips({
  language,
  account,
}: {
  language: Language;
  account: Account;
}) {
  return (
    <>
      {account.control_source !== null && (
        <>
          {" "}
          <Chip icon="lock" tone="neutral">
            {lt(language, "ctl")}
          </Chip>
        </>
      )}
      {account.tax_locked && (
        <>
          {" "}
          <Chip icon="lock" tone="warn">
            {lt(language, "tax")}
          </Chip>
        </>
      )}
      {!account.active && (
        <>
          {" "}
          <Chip icon="lock" tone="neutral">
            {lt(language, "off")}
          </Chip>
        </>
      )}
    </>
  );
}

function ChartTab({
  language,
  propertyId,
  active,
  api,
}: {
  language: Language;
  propertyId: string;
  active: boolean;
  api: LedgerApi;
}) {
  const detail = useHashDetail("chart");
  const read = useCallback(() => api.accounts(propertyId), [api, propertyId]);
  const { data, failed, reload } = useRead<Chart>(active, read);
  if (data === null)
    return <Waiting failed={failed} language={language} onRetry={reload} />;
  const chosen =
    detail === null
      ? undefined
      : data.accounts.find((account) => account.code === detail);
  if (chosen !== undefined) {
    return (
      <AccountDetail
        account={chosen}
        active={active}
        api={api}
        language={language}
        propertyId={propertyId}
      />
    );
  }
  return (
    <>
      <section aria-labelledby="chart-title" className="ui-card">
        <div className="ui-head">
          <div>
            <h2 id="chart-title">{lt(language, "a_title")}</h2>
            <p className="ui-muted">{lt(language, "a_sub")}</p>
          </div>
          <span className="ui-actions">
            <a className="ui-btn" href={hashForPage("chart", OPENING)}>
              <Icon name="list" small />
              {lt(language, "ob_t")}
            </a>
          </span>
        </div>
      </section>
      {ACCOUNT_TYPES.map((type) => {
        const accounts = data.accounts.filter(
          (account) => account.account_type === type,
        );
        if (accounts.length === 0) return null;
        return (
          <section
            aria-labelledby={`chart-${type}`}
            className="ui-card pad0"
            key={type}
          >
            <header className="ui-chead pad">
              <h2 id={`chart-${type}`}>{typeName(language, type)}</h2>
            </header>
            <div className="ui-tablewrap">
              <table className="ui-table">
                <thead>
                  <tr>
                    <th scope="col">{lt(language, "code")}</th>
                    <th scope="col">{lt(language, "account")}</th>
                    <th className="r" scope="col">
                      {lt(language, "balance")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {accounts.map((account) => (
                    <tr key={account.code}>
                      <td>
                        <a
                          className="ui-num"
                          href={hashForPage("chart", account.code)}
                        >
                          {account.code}
                        </a>
                      </td>
                      <td>
                        {accountName(language, account)}
                        <AccountChips account={account} language={language} />
                      </td>
                      <td className="r ui-num">
                        {money(account.balance_cents)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        );
      })}
      <p className="ui-muted">
        <Icon name="lock" small /> {lt(language, "ctl")}:{" "}
        {lt(language, "ctl_s")}
      </p>
    </>
  );
}

function AccountDetail({
  language,
  propertyId,
  active,
  api,
  account,
}: {
  language: Language;
  propertyId: string;
  active: boolean;
  api: LedgerApi;
  account: Account;
}) {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const read = useCallback(
    () =>
      api.report(propertyId, "account-detail", {
        account: account.code,
        from: from === "" ? undefined : from,
        to: to === "" ? undefined : to,
      }),
    [api, propertyId, account.code, from, to],
  );
  const { data, failed, reload } = useRead<Report>(active, read);
  const note = account.tax_locked
    ? lt(language, "tax_n")
    : !account.active
      ? lt(language, "off_n")
      : account.used
        ? lt(language, "used_n")
        : null;
  return (
    <>
      <a className="ui-crumb" href={hashForPage("chart")}>
        <Icon name="back" small />
        {lt(language, "a_title")}
      </a>
      <section aria-labelledby="account-title" className="ui-card pad0">
        <header className="ui-chead pad">
          <h2 id="account-title">
            <span className="ui-num">{account.code}</span>{" "}
            {accountName(language, account)}
          </h2>
          <span className="ui-actions">
            <AccountChips account={account} language={language} />
          </span>
        </header>
        <p className="ui-muted pad">
          {typeName(language, account.account_type)} · {lt(language, "balance")}{" "}
          <span className="ui-num">{money(account.balance_cents)}</span>
        </p>
        {note !== null && (
          <p className="ui-muted pad">
            <Icon name="lock" small /> {note}
          </p>
        )}
        <div className="ui-qa pad">
          <div className="ui-field">
            <label htmlFor="ad-from">{lt(language, "from")}</label>
            <DateInput
              calendarLabel={lt(language, "from")}
              id="ad-from"
              language={language}
              onChange={setFrom}
              value={from}
            />
          </div>
          <div className="ui-field">
            <label htmlFor="ad-to">{lt(language, "to")}</label>
            <DateInput
              calendarLabel={lt(language, "to")}
              id="ad-to"
              language={language}
              onChange={setTo}
              value={to}
            />
          </div>
        </div>
        <p className="ui-muted pad">{lt(language, "ad_sub")}</p>
        {data === null ? (
          <Waiting failed={failed} language={language} onRetry={reload} />
        ) : (
          <>
            <p className="ui-muted pad">
              {data.period} · {stateText(language, data.state)}
            </p>
            <div className="ui-tablewrap">
              <table className="ui-table">
                <thead>
                  <tr>
                    <th scope="col">{lt(language, "date")}</th>
                    <th scope="col">{lt(language, "no")}</th>
                    <th scope="col">{lt(language, "what")}</th>
                    <th className="r" scope="col">
                      {lt(language, "debit")}
                    </th>
                    <th className="r" scope="col">
                      {lt(language, "credit")}
                    </th>
                    <th className="r" scope="col">
                      {lt(language, "balance")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {[...data.rows].reverse().map((row, index) => {
                    const number =
                      typeof row.entry_number === "string"
                        ? row.entry_number
                        : null;
                    return (
                      <tr key={`${number ?? "open"}-${String(index)}`}>
                        <td className="ui-num">
                          {typeof row.entry_date === "string"
                            ? dayText(row.entry_date)
                            : ""}
                        </td>
                        <td>
                          {number === null ? (
                            ""
                          ) : (
                            <a
                              className="ui-num"
                              href={hashForPage("journal", number)}
                            >
                              {number}
                            </a>
                          )}
                        </td>
                        <td>
                          {number === null
                            ? lt(language, "ad_open")
                            : String(row.description ?? "")}
                          {typeof row.memo === "string" && row.memo !== "" && (
                            <span className="ui-muted ui-sub2">{row.memo}</span>
                          )}
                        </td>
                        <td className="r ui-num">{cellMoney(row.debit)}</td>
                        <td className="r ui-num">{cellMoney(row.credit)}</td>
                        <td className="r ui-num">
                          {cellMoney(sideBalance(account, row.balance))}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>
    </>
  );
}

/** The running balance shown on the account's normal side, like the chart. */
function sideBalance(
  account: Account,
  value: ReportRow[string] | undefined,
): number | null {
  if (typeof value !== "number") return null;
  const debitSide =
    account.account_type === "ASSET" ||
    account.account_type === "EXPENSE" ||
    account.account_type === "COST_OF_SALES";
  return debitSide ? value : -value;
}

function cellMoney(value: ReportRow[string] | undefined): string {
  return typeof value === "number" ? usdFromCents(value) : "";
}

/* ---------- Financial statements ---------- */

type StatementKey = ReportName | "books-check";

const STATEMENTS: readonly StatementKey[] = [
  "profit-and-loss",
  "balance-sheet",
  "cash-flow",
  "trial-balance",
  "customer-aging",
  "bills-aging",
  "budget",
  "books-check",
];

function statementTitle(language: Language, key: StatementKey): string {
  return lt(language, `r_${key.replace(/-/g, "_")}` as LedgerTextKey);
}

function stateText(language: Language, state: string): string {
  if (state === "Closed") return lt(language, "st_closed");
  if (state === "Open, may still change") return lt(language, "st_open");
  if (state === "As at today") return lt(language, "st_today");
  return state;
}

// Column and row words the server writes in English, in the screen's language. Words not in
// this list stay in English (DESIGN.md: statement files are English, the PDF font has no
// Khmer).
const COLUMN_KEYS: Readonly<Record<string, readonly [string, string]>> = {
  code: ["Account", "គណនី"],
  name: ["Name", "ឈ្មោះ"],
  debit: ["Debit", "ឥណពន្ធ"],
  credit: ["Credit", "ឥណទាន"],
  amount: ["Amount", "ចំនួន"],
  balance: ["Balance", "សមតុល្យ"],
  this_month: ["This month", "ខែនេះ"],
  last_month: ["Last month", "ខែមុន"],
  same_month_last_year: ["Same month last year", "ខែដដែលឆ្នាំមុន"],
  year_to_date: ["Year to date", "ពីដើមឆ្នាំដល់ឥឡូវ"],
  difference: ["Difference", "ភាពខុសគ្នា"],
  customer_name: ["Customer", "អតិថិជន"],
  unit_number: ["Unit", "បន្ទប់"],
  supplier: ["Supplier", "អ្នកផ្គត់ផ្គង់"],
  not_due: ["Not yet due", "មិនទាន់ដល់ថ្ងៃកំណត់"],
  days_1_30: ["1-30 days", "១-៣០ ថ្ងៃ"],
  days_31_60: ["31-60 days", "៣១-៦០ ថ្ងៃ"],
  days_61_90: ["61-90 days", "៦១-៩០ ថ្ងៃ"],
  over_90: ["Over 90 days", "លើស ៩០ ថ្ងៃ"],
  total: ["Total", "សរុប"],
  budget_month: ["Budget this month", "ថវិកាខែនេះ"],
  actual_month: ["Actual this month", "ជាក់ស្ដែងខែនេះ"],
  difference_month: ["Difference this month", "ភាពខុសគ្នាខែនេះ"],
  month_off: ["Marked this month", "សម្គាល់ខែនេះ"],
  budget_year: ["Budget year to date", "ថវិកាពីដើមឆ្នាំ"],
  actual_year: ["Actual year to date", "ជាក់ស្ដែងពីដើមឆ្នាំ"],
  difference_year: ["Difference year to date", "ភាពខុសគ្នាពីដើមឆ្នាំ"],
  year_off: ["Marked year to date", "សម្គាល់ពីដើមឆ្នាំ"],
};

function columnLabel(
  language: Language,
  column: { key: string; label: string },
): string {
  const known = COLUMN_KEYS[column.key];
  return known === undefined ? column.label : known[language === "en" ? 0 : 1];
}

function rowName(
  language: Language,
  row: ReportRow,
  chart: Chart | null,
  key: string,
): string {
  const code = typeof row.code === "string" ? row.code : null;
  if (code !== null && chart !== null) {
    const account = chart.accounts.find((item) => item.code === code);
    if (account !== undefined) return accountName(language, account);
  }
  const value = row[key];
  return value === null || value === undefined ? "" : String(value);
}

function StatementsTab({
  language,
  propertyId,
  active,
  api,
}: {
  language: Language;
  propertyId: string;
  active: boolean;
  api: LedgerApi;
}) {
  const today = todayInPhnomPenh();
  const [chosen, setChosen] = useState<StatementKey>("profit-and-loss");
  const [month, setMonth] = useState(`${today.slice(0, 7)}-01`);
  const [asOf, setAsOf] = useState(today);
  const [from, setFrom] = useState(`${today.slice(0, 7)}-01`);
  const [to, setTo] = useState(today);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const values: ReportQuery =
    chosen === "profit-and-loss" || chosen === "budget"
      ? { month }
      : chosen === "balance-sheet" || chosen === "trial-balance"
        ? { as_of: asOf }
        : chosen === "cash-flow"
          ? { from, to }
          : {};
  const key = JSON.stringify(values);
  const chartRead = useCallback(
    () => api.accounts(propertyId),
    [api, propertyId],
  );
  const chart = useRead<Chart>(active, chartRead);
  const read = useCallback(
    (): Promise<Report | BooksCheckRow[]> =>
      chosen === "books-check"
        ? api.booksCheck(propertyId)
        : api.report(propertyId, chosen, JSON.parse(key) as ReportQuery),
    // `key` carries the values, so a new object each render does not read again.
    [api, propertyId, chosen, key],
  );
  const { data, failed, reload } = useRead<Report | BooksCheckRow[]>(
    active,
    read,
  );
  const months: string[] = [];
  for (let back = 0; back < 24; back += 1) {
    const date = new Date(
      Date.UTC(
        Number(today.slice(0, 4)),
        Number(today.slice(5, 7)) - 1 - back,
        1,
      ),
    );
    months.push(date.toISOString().slice(0, 10));
  }

  function download(type: "xlsx" | "pdf") {
    if (chosen === "books-check") return;
    setBusy(true);
    setFailure(null);
    setNotice(null);
    api.reportFile(propertyId, chosen, values, type).then(
      (file) => {
        setBusy(false);
        const url = URL.createObjectURL(file.file);
        const link = document.createElement("a");
        link.href = url;
        link.download = file.fileName;
        document.body.append(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
        setNotice(lt(language, "x_done", file.fileName));
      },
      (error: unknown) => {
        setBusy(false);
        setFailure(refusal(language, error));
      },
    );
  }

  return (
    <>
      <section aria-labelledby="statements-title" className="ui-card">
        <div className="ui-head">
          <div>
            <h2 id="statements-title">{lt(language, "r_title")}</h2>
            <p>{lt(language, "r_sub")}</p>
          </div>
          {chosen !== "books-check" && (
            <span className="ui-actions">
              <button
                className="ui-btn"
                disabled={busy}
                onClick={() => {
                  download("xlsx");
                }}
                type="button"
              >
                <Icon name="download" small />
                {lt(language, "xlsx")}
              </button>
              <button
                className="ui-btn"
                disabled={busy}
                onClick={() => {
                  download("pdf");
                }}
                type="button"
              >
                <Icon name="download" small />
                {lt(language, "pdf")}
              </button>
            </span>
          )}
        </div>
        <div
          aria-label={lt(language, "r_title")}
          className="ui-seg"
          role="group"
        >
          {STATEMENTS.map((statement) => (
            <button
              aria-pressed={chosen === statement}
              key={statement}
              onClick={() => {
                setNotice(null);
                setFailure(null);
                setChosen(statement);
              }}
              type="button"
            >
              {statementTitle(language, statement)}
            </button>
          ))}
        </div>
        <div className="ui-qa">
          {"month" in values && (
            <div className="ui-field">
              <label htmlFor="st-month">{lt(language, "month")}</label>
              <select
                id="st-month"
                onChange={(event) => {
                  setMonth(event.target.value);
                }}
                value={month}
              >
                {months.map((value) => (
                  <option key={value} value={value}>
                    {monthLabel(language, value)}
                  </option>
                ))}
              </select>
            </div>
          )}
          {"as_of" in values && (
            <div className="ui-field">
              <label htmlFor="st-asof">{lt(language, "as_of")}</label>
              <DateInput
                calendarLabel={lt(language, "as_of")}
                id="st-asof"
                language={language}
                onChange={(value) => {
                  if (value !== "") setAsOf(value);
                }}
                value={asOf}
              />
            </div>
          )}
          {"from" in values && (
            <>
              <div className="ui-field">
                <label htmlFor="st-from">{lt(language, "from")}</label>
                <DateInput
                  calendarLabel={lt(language, "from")}
                  id="st-from"
                  language={language}
                  onChange={(value) => {
                    if (value !== "") setFrom(value);
                  }}
                  value={from}
                />
              </div>
              <div className="ui-field">
                <label htmlFor="st-to">{lt(language, "to")}</label>
                <DateInput
                  calendarLabel={lt(language, "to")}
                  id="st-to"
                  language={language}
                  onChange={(value) => {
                    if (value !== "") setTo(value);
                  }}
                  value={to}
                />
              </div>
            </>
          )}
        </div>
        {notice !== null && (
          <div className="ui-notice ok" role="status">
            <Icon name="check" />
            <p>{notice}</p>
          </div>
        )}
        {failure !== null && (
          <p className="ui-error" role="alert">
            {failure}
          </p>
        )}
      </section>
      {data === null ? (
        <Waiting failed={failed} language={language} onRetry={reload} />
      ) : Array.isArray(data) ? (
        <BooksCheck language={language} rows={data} />
      ) : (
        <Statement chart={chart.data} language={language} report={data} />
      )}
    </>
  );
}

function Statement({
  language,
  report,
  chart,
}: {
  language: Language;
  report: Report;
  chart: Chart | null;
}) {
  const nameKey = report.columns.find((column) => column.kind !== "money")?.key;
  return (
    <section aria-labelledby="statement-title" className="ui-card pad0">
      <header className="ui-chead pad">
        <h2 id="statement-title">{statementTitle(language, report.report)}</h2>
        <span className="ui-actions">
          <Chip
            icon={report.state === "Closed" ? "lock" : "clock"}
            tone={report.state === "Closed" ? "neutral" : "info"}
          >
            {stateText(language, report.state)}
          </Chip>
        </span>
      </header>
      <p className="ui-muted pad">{report.period}</p>
      {report.rows.length === 0 ? (
        <p className="ui-muted pad">{lt(language, "r_none")}</p>
      ) : (
        <div className="ui-tablewrap">
          <table className="ui-table">
            <thead>
              <tr>
                {report.columns.map((column) => (
                  <th
                    className={column.kind === "money" ? "r" : undefined}
                    key={column.key}
                    scope="col"
                  >
                    {columnLabel(language, column)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {report.rows.map((row, index) => {
                const line = row.line;
                const strong = line === "total" || line === "heading";
                return (
                  <tr key={String(index)}>
                    {report.columns.map((column) => {
                      const value = row[column.key];
                      let shown: string;
                      if (column.kind === "money") {
                        shown =
                          typeof value === "number" ? usdFromCents(value) : "";
                      } else if (
                        column.key === nameKey &&
                        column.key !== "code"
                      ) {
                        shown = rowName(language, row, chart, column.key);
                      } else if (typeof value === "boolean") {
                        shown = value ? "✓" : "";
                      } else {
                        shown =
                          value === null || value === undefined
                            ? ""
                            : column.kind === "date"
                              ? dayText(String(value))
                              : String(value);
                      }
                      return (
                        <td
                          className={
                            column.kind === "money" ? "r ui-num" : undefined
                          }
                          key={column.key}
                        >
                          {strong ? <b>{shown}</b> : shown}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="pad">
        <Chip
          icon={report.check.ok ? "check" : "alert"}
          tone={report.check.ok ? "ok" : "err"}
        >
          {lt(language, report.check.ok ? "ok" : "bad")}
        </Chip>{" "}
        {lt(language, "r_check")}: {report.check.text}
      </p>
      {language === "km" && (
        <p className="ui-muted pad">{lt(language, "r_english")}</p>
      )}
    </section>
  );
}

function BooksCheck({
  language,
  rows,
}: {
  language: Language;
  rows: readonly BooksCheckRow[];
}) {
  return (
    <section aria-labelledby="bc-title" className="ui-card pad0">
      <header className="ui-chead pad">
        <h2 id="bc-title">{lt(language, "r_books_check")}</h2>
      </header>
      <div className="ui-tablewrap">
        <table className="ui-table">
          <thead>
            <tr>
              <th scope="col">{lt(language, "r_check")}</th>
              <th className="r" scope="col">
                {lt(language, "bc_in_books")}
              </th>
              <th className="r" scope="col">
                {lt(language, "bc_in_app")}
              </th>
              <th scope="col">
                <span className="ui-sr">{lt(language, "r_check")}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const key = `bc_${row.check_code}`;
              const counts =
                row.check_code === "EVERY_RECORD_POSTED" ||
                row.check_code === "EVERY_ENTRY_BALANCED";
              return (
                <tr key={row.check_code}>
                  <td className="wrap">
                    {hasLedgerText(key) ? lt(language, key) : row.check_code}
                  </td>
                  <td className="r ui-num">
                    {counts ? "" : usdFromCents(row.in_books)}
                  </td>
                  <td className="r ui-num">
                    {counts
                      ? row.in_list === 0
                        ? ""
                        : lt(language, "bc_waiting", String(row.in_list))
                      : usdFromCents(row.in_list)}
                  </td>
                  <td>
                    <Chip
                      icon={row.ok ? "check" : "alert"}
                      tone={row.ok ? "ok" : "err"}
                    >
                      {lt(language, row.ok ? "ok" : "bad")}
                    </Chip>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
