// General Ledger phase 6 step 6 (mock-up lopen, app26 vOpen26): Opening balances, opened from the
// Chart of accounts. The Owner (ledger.opening_balances) starts the books on 1 January of the first
// year, types the accounts the app does not work out, and posts one balanced entry; the control
// accounts come from the app's own lists. Once posted, the opening balances are locked. The
// server checks every right and number again.

import "../shell/screens.css";

import { type FormEvent, useCallback, useState } from "react";

import { centsFromText } from "../products/productsClient";
import { dayText, momentText } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { Chip, Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import { accountName, money, useRead, Waiting } from "./LedgerPage";
import {
  type OpeningAccount,
  type OpeningApi,
  type OpeningLine,
  type OpeningSheet,
  openingApi as defaultOpeningApi,
  type TypedLine,
} from "./openingClient";
import { Done, Failure, FieldError, useBusy } from "./SpendingPage";
import { lt } from "./text";

export interface OpeningBalancesProps {
  language: Language;
  propertyId: string;
  active: boolean;
  /** ledger.opening_balances: start the books, type the lines and post them (the Owner). */
  canEdit: boolean;
  api?: OpeningApi;
}

function totals(lines: readonly OpeningLine[]): {
  debit: number;
  credit: number;
} {
  return lines.reduce(
    (sum, line) => ({
      debit: sum.debit + line.debit_cents,
      credit: sum.credit + line.credit_cents,
    }),
    { debit: 0, credit: 0 },
  );
}

function LinesTable({
  language,
  lines,
  notes,
  footer,
}: {
  language: Language;
  lines: readonly OpeningLine[];
  notes: boolean;
  footer?: { debit: number; credit: number };
}) {
  return (
    <div className="ui-tablewrap">
      <table className="ui-table">
        <thead>
          <tr>
            <th scope="col">{lt(language, "account")}</th>
            {notes && <th scope="col">{lt(language, "ow_note")}</th>}
            <th className="r" scope="col">
              {lt(language, "debit")}
            </th>
            <th className="r" scope="col">
              {lt(language, "credit")}
            </th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line) => (
            <tr key={line.account_code}>
              <td>
                <a
                  className="ui-num"
                  href={hashForPage("chart", line.account_code)}
                >
                  {line.account_code}
                </a>{" "}
                {accountName(language, line)}
              </td>
              {notes && <td>{line.memo ?? ""}</td>}
              <td className="r ui-num">
                {line.debit_cents > 0 ? money(line.debit_cents) : ""}
              </td>
              <td className="r ui-num">
                {line.credit_cents > 0 ? money(line.credit_cents) : ""}
              </td>
            </tr>
          ))}
        </tbody>
        {footer !== undefined && (
          <tfoot>
            <tr>
              <th scope="row" colSpan={notes ? 2 : 1}>
                {lt(language, "total")}
              </th>
              <td className="r ui-num">{money(footer.debit)}</td>
              <td className="r ui-num">{money(footer.credit)}</td>
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  );
}

export function OpeningBalances({
  language,
  propertyId,
  active,
  canEdit,
  api = defaultOpeningApi,
}: OpeningBalancesProps) {
  const read = useCallback(() => api.read(propertyId), [api, propertyId]);
  const { data, failed, reload } = useRead<OpeningSheet>(active, read);
  const [done, setDone] = useState<string | null>(null);
  const crumb = (
    <a className="ui-crumb" href={hashForPage("chart")}>
      <Icon name="back" small />
      {lt(language, "a_title")}
    </a>
  );
  const head = (
    <section aria-labelledby="ob-title" className="ui-card">
      <h2 id="ob-title">{lt(language, "ob_t")}</h2>
      <p className="ui-muted">{lt(language, "ob_sub")}</p>
    </section>
  );
  if (data === null) {
    return (
      <>
        {crumb}
        {head}
        <Waiting failed={failed} language={language} onRetry={reload} />
      </>
    );
  }
  const finish = (text: string) => {
    setDone(text);
    reload();
  };
  return (
    <>
      {crumb}
      {head}
      <Done text={done} />
      {data.opening === null ? (
        <StartCard
          api={api}
          canEdit={canEdit}
          data={data}
          language={language}
          onDone={finish}
          propertyId={propertyId}
        />
      ) : data.opening.status === "POSTED" ? (
        <PostedCard data={data} language={language} />
      ) : (
        <DraftCards
          api={api}
          canEdit={canEdit}
          data={data}
          language={language}
          onDone={finish}
          propertyId={propertyId}
        />
      )}
    </>
  );
}

/* ---------- Before the books start ---------- */

function StartCard({
  language,
  propertyId,
  data,
  canEdit,
  api,
  onDone,
}: {
  language: Language;
  propertyId: string;
  data: OpeningSheet;
  canEdit: boolean;
  api: OpeningApi;
  onDone: (text: string) => void;
}) {
  const [year, setYear] = useState(
    String(data.first_year ?? Number(data.today.slice(0, 4)) + 1),
  );
  const [error, setError] = useState<string | null>(null);
  const { busy, failure, run } = useBusy(language);
  const typed = /^\d{4}$/.test(year.trim()) ? Number(year.trim()) : null;
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (typed === null || typed < 2000 || typed > 2100) {
      setError(lt(language, "ob_e_year"));
      return;
    }
    setError(null);
    run(
      () => api.begin(propertyId, typed),
      () => {
        onDone(lt(language, "ob_started", `01/01/${String(typed)}`));
      },
    );
  };
  return (
    <section aria-labelledby="ob-start" className="ui-card">
      <h2 id="ob-start">{lt(language, "ob_start")}</h2>
      <p>{lt(language, "ob_none")}</p>
      {canEdit ? (
        <form noValidate onSubmit={submit}>
          <div className="ui-field">
            <label htmlFor="ob-year">
              {lt(language, "ob_year")}
              <span className="req">{lt(language, "required")}</span>
            </label>
            <input
              aria-describedby="ob-year-n"
              aria-invalid={error !== null}
              id="ob-year"
              inputMode="numeric"
              onChange={(event) => {
                setYear(event.target.value);
              }}
              value={year}
            />
            {typed !== null && (
              <p className="ui-muted" id="ob-year-n">
                {lt(language, "ob_year_n", String(typed), String(typed - 1))}
              </p>
            )}
            <FieldError id="ob-year-e" text={error} />
          </div>
          <Failure text={failure} />
          <button className="ui-btn primary" disabled={busy} type="submit">
            <Icon name="check" small />
            {lt(language, "ob_start")}
          </button>
        </form>
      ) : (
        <p className="ui-muted">
          <Icon name="lock" small /> {lt(language, "ob_owner")}
        </p>
      )}
    </section>
  );
}

/* ---------- Started, not posted ---------- */

function DraftCards({
  language,
  propertyId,
  data,
  canEdit,
  api,
  onDone,
}: {
  language: Language;
  propertyId: string;
  data: OpeningSheet;
  canEdit: boolean;
  api: OpeningApi;
  onDone: (text: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [posting, setPosting] = useState(false);
  const opening = data.opening;
  if (opening === null) return null;
  const all = totals([...data.typed, ...data.worked_out]);
  const off = all.debit - all.credit;
  const balanced = off === 0 && all.debit > 0;
  const canPost = canEdit && balanced && data.needs_check === 0;
  return (
    <>
      <section aria-labelledby="ob-typed" className="ui-card pad0">
        <header className="ui-chead pad">
          <div>
            <h2 id="ob-typed">
              {lt(language, "ob_on", dayText(opening.start_date))}{" "}
              <Chip icon="clock" tone="neutral">
                {lt(language, "ob_draft")}
              </Chip>
            </h2>
            <p className="ui-muted">
              <strong>{lt(language, "ob_typed_t")}.</strong>{" "}
              {lt(language, "ob_typed_s")}
            </p>
          </div>
          {canEdit && (
            <span className="ui-actions">
              <button
                className="ui-btn"
                onClick={() => {
                  setEditing(true);
                }}
                type="button"
              >
                <Icon name="list" small />
                {lt(language, "ob_type")}
              </button>
            </span>
          )}
        </header>
        {data.typed.length === 0 ? (
          <p className="pad ui-muted">{lt(language, "ob_typed_none")}</p>
        ) : (
          <LinesTable language={language} lines={data.typed} notes />
        )}
      </section>
      <section aria-labelledby="ob-worked" className="ui-card pad0">
        <header className="ui-chead pad">
          <div>
            <h2 id="ob-worked">{lt(language, "ob_worked_t")}</h2>
            <p className="ui-muted">{lt(language, "ob_worked_s")}</p>
          </div>
        </header>
        {data.worked_out.length === 0 ? (
          <p className="pad ui-muted">{lt(language, "ob_worked_none")}</p>
        ) : (
          <LinesTable
            language={language}
            lines={data.worked_out}
            notes={false}
          />
        )}
      </section>
      <section aria-labelledby="ob-sum" className="ui-card">
        <h2 id="ob-sum">{lt(language, "total")}</h2>
        <p>
          {lt(language, "debit")}{" "}
          <span className="ui-num">{money(all.debit)}</span> ·{" "}
          {lt(language, "credit")}{" "}
          <span className="ui-num">{money(all.credit)}</span>{" "}
          {balanced && (
            <Chip icon="check" tone="ok">
              {lt(language, "balanced")}
            </Chip>
          )}
        </p>
        {off !== 0 && (
          <p className="ui-error" role="status">
            {lt(language, "ob_off", money(Math.abs(off)))}
          </p>
        )}
        {all.debit === 0 && all.credit === 0 && (
          <p className="ui-muted" role="status">
            {lt(language, "ob_empty")}
          </p>
        )}
        {data.needs_check > 0 && (
          <p className="ui-error" role="status">
            {lt(language, "ob_nc", String(data.needs_check))}{" "}
            <a href={hashForPage("needscheck")}>{lt(language, "nc_title")}</a>
          </p>
        )}
        {canEdit ? (
          <button
            className="ui-btn primary"
            disabled={!canPost}
            onClick={() => {
              setPosting(true);
            }}
            type="button"
          >
            <Icon name="lock" small />
            {lt(language, "ob_post")}
          </button>
        ) : (
          <p className="ui-muted">
            <Icon name="lock" small /> {lt(language, "ob_owner")}
          </p>
        )}
      </section>
      {editing && (
        <TypeDialog
          accounts={data.accounts}
          api={api}
          language={language}
          lines={data.typed}
          onClose={() => {
            setEditing(false);
          }}
          onSaved={() => {
            setEditing(false);
            onDone(lt(language, "ob_saved"));
          }}
          propertyId={propertyId}
        />
      )}
      {posting && (
        <PostDialog
          api={api}
          day={dayText(opening.start_date)}
          language={language}
          onClose={() => {
            setPosting(false);
          }}
          onPosted={() => {
            setPosting(false);
            onDone(lt(language, "ob_posted"));
          }}
          propertyId={propertyId}
        />
      )}
    </>
  );
}

interface Row {
  key: number;
  code: string;
  debit: string;
  credit: string;
  memo: string;
}

function amountText(cents: number): string {
  return cents > 0 ? (cents / 100).toFixed(2) : "";
}

function TypeDialog({
  language,
  propertyId,
  accounts,
  lines,
  api,
  onClose,
  onSaved,
}: {
  language: Language;
  propertyId: string;
  accounts: readonly OpeningAccount[];
  lines: readonly OpeningLine[];
  api: OpeningApi;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [rows, setRows] = useState<Row[]>(() =>
    lines.length === 0
      ? [{ key: 0, code: "", debit: "", credit: "", memo: "" }]
      : lines.map((line, index) => ({
          key: index,
          code: line.account_code,
          debit: amountText(line.debit_cents),
          credit: amountText(line.credit_cents),
          memo: line.memo ?? "",
        })),
  );
  const [errors, setErrors] = useState<Record<number, string>>({});
  const [error, setError] = useState<string | null>(null);
  const { busy, failure, run } = useBusy(language);
  const change = (key: number, patch: Partial<Row>) => {
    setRows((now) =>
      now.map((row) => (row.key === key ? { ...row, ...patch } : row)),
    );
  };
  const nextKey = rows.reduce((top, row) => Math.max(top, row.key), -1) + 1;
  const debitSum = rows.reduce(
    (sum, row) => sum + (centsFromText(row.debit) ?? 0),
    0,
  );
  const creditSum = rows.reduce(
    (sum, row) => sum + (centsFromText(row.credit) ?? 0),
    0,
  );
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const found: Record<number, string> = {};
    const seen = new Set<string>();
    const out: TypedLine[] = [];
    for (const row of rows) {
      const debit = row.debit.trim() === "" ? 0 : centsFromText(row.debit);
      const credit = row.credit.trim() === "" ? 0 : centsFromText(row.credit);
      if (row.code === "") {
        found[row.key] = lt(language, "ob_e_acct");
      } else if (seen.has(row.code)) {
        found[row.key] = lt(language, "ob_e_twice");
      } else if (
        debit === null ||
        credit === null ||
        debit > 0 === credit > 0
      ) {
        found[row.key] = lt(language, "ob_e_one");
      } else {
        out.push({
          account_code: row.code,
          debit_cents: debit,
          credit_cents: credit,
          memo: row.memo.trim() === "" ? null : row.memo.trim(),
        });
      }
      seen.add(row.code);
    }
    setErrors(found);
    if (rows.length === 0) {
      setError(lt(language, "ob_e_lines"));
      return;
    }
    setError(null);
    if (Object.keys(found).length > 0) return;
    run(
      () => api.setLines(propertyId, out),
      () => {
        onSaved();
      },
    );
  };
  return (
    <Dialog
      busy={busy}
      closeLabel={lt(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={lt(language, "save")}
      title={lt(language, "ob_type")}
      wide
    >
      <p className="ui-muted">{lt(language, "ob_typed_s")}</p>
      {rows.map((row, index) => {
        const id = `ob-row-${String(row.key)}`;
        const chosen = accounts.find((account) => account.code === row.code);
        const label =
          chosen === undefined
            ? String(index + 1)
            : `${chosen.code} · ${accountName(language, chosen)}`;
        return (
          <fieldset className="ui-field" key={row.key}>
            <legend className="ui-sr">{label}</legend>
            <div className="ui-row2">
              <div className="ui-field">
                <label htmlFor={`${id}-a`}>{lt(language, "account")}</label>
                <select
                  id={`${id}-a`}
                  onChange={(event) => {
                    change(row.key, { code: event.target.value });
                  }}
                  value={row.code}
                >
                  <option value="">{lt(language, "ob_pick")}</option>
                  {accounts.map((account) => (
                    <option key={account.code} value={account.code}>
                      {account.code} · {accountName(language, account)}
                    </option>
                  ))}
                </select>
              </div>
              <div className="ui-field">
                <label htmlFor={`${id}-m`}>{lt(language, "ow_note")}</label>
                <input
                  autoComplete="off"
                  id={`${id}-m`}
                  maxLength={500}
                  onChange={(event) => {
                    change(row.key, { memo: event.target.value });
                  }}
                  value={row.memo}
                />
              </div>
            </div>
            <div className="ui-row2">
              <div className="ui-field">
                <label htmlFor={`${id}-d`}>{lt(language, "debit")}</label>
                <div className="ui-money">
                  <span aria-hidden="true">$</span>
                  <input
                    autoComplete="off"
                    id={`${id}-d`}
                    inputMode="decimal"
                    onChange={(event) => {
                      change(row.key, { debit: event.target.value });
                    }}
                    value={row.debit}
                  />
                </div>
              </div>
              <div className="ui-field">
                <label htmlFor={`${id}-c`}>{lt(language, "credit")}</label>
                <div className="ui-money">
                  <span aria-hidden="true">$</span>
                  <input
                    autoComplete="off"
                    id={`${id}-c`}
                    inputMode="decimal"
                    onChange={(event) => {
                      change(row.key, { credit: event.target.value });
                    }}
                    value={row.credit}
                  />
                </div>
              </div>
            </div>
            <FieldError id={`${id}-e`} text={errors[row.key] ?? null} />
            <button
              className="ui-btn"
              onClick={() => {
                setRows((now) => now.filter((item) => item.key !== row.key));
              }}
              type="button"
            >
              <Icon name="x" small />
              {lt(language, "ob_remove", label)}
            </button>
          </fieldset>
        );
      })}
      <button
        className="ui-btn"
        onClick={() => {
          setRows((now) => [
            ...now,
            { key: nextKey, code: "", debit: "", credit: "", memo: "" },
          ]);
        }}
        type="button"
      >
        <Icon name="plus" small />
        {lt(language, "ob_add")}
      </button>
      <p>
        {lt(language, "total")}: {lt(language, "debit")}{" "}
        <span className="ui-num">{money(debitSum)}</span> ·{" "}
        {lt(language, "credit")}{" "}
        <span className="ui-num">{money(creditSum)}</span>
      </p>
      <FieldError id="ob-lines-e" text={error} />
      <Failure text={failure} />
    </Dialog>
  );
}

function PostDialog({
  language,
  propertyId,
  day,
  api,
  onClose,
  onPosted,
}: {
  language: Language;
  propertyId: string;
  day: string;
  api: OpeningApi;
  onClose: () => void;
  onPosted: () => void;
}) {
  const { busy, failure, run } = useBusy(language);
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    run(
      () => api.post(propertyId),
      () => {
        onPosted();
      },
    );
  };
  return (
    <Dialog
      busy={busy}
      closeLabel={lt(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={lt(language, "ob_post")}
      title={lt(language, "ob_post")}
    >
      <p>{lt(language, "ob_post_n", day)}</p>
      <Failure text={failure} />
    </Dialog>
  );
}

/* ---------- Posted and locked (the mock-up's view) ---------- */

function PostedCard({
  language,
  data,
}: {
  language: Language;
  data: OpeningSheet;
}) {
  const opening = data.opening;
  if (opening === null) return null;
  const sum = totals(data.posted);
  return (
    <section aria-labelledby="ob-posted" className="ui-card pad0">
      <header className="ui-chead pad">
        <h2 id="ob-posted">
          {lt(language, "ob_on", dayText(opening.start_date))}{" "}
          <Chip icon="lock" tone="neutral">
            {lt(language, "ob_locked")}
          </Chip>
        </h2>
      </header>
      <LinesTable footer={sum} language={language} lines={data.posted} notes />
      <div className="pad">
        <p>
          {sum.debit === sum.credit && (
            <Chip icon="check" tone="ok">
              {lt(language, "balanced")}
            </Chip>
          )}{" "}
          {opening.entry_number !== null && (
            <a
              className="ui-num"
              href={hashForPage("journal", opening.entry_number)}
            >
              {lt(language, "ob_entry", opening.entry_number)}
            </a>
          )}
        </p>
        {opening.posted_by_name !== null && (
          <p className="ui-muted">
            {lt(
              language,
              "ob_by",
              opening.posted_by_name,
              momentText(opening.posted_at),
            )}
          </p>
        )}
        <p className="ui-muted">
          <Icon name="lock" small /> {lt(language, "ob_note")}
        </p>
      </div>
    </section>
  );
}
