// General Ledger phase 6 step 6 part 3 (mock-up v76, app26 and app29): Office › Ledger tab
// Bank and cash. At each month end the bank book is matched to the ABA statement
// (ledger.reconcile) and the cash is counted (ledger.cash_count); Month-end close checks both.
// Move money (ledger.money_move), Top up petty cash (ledger.petty_cash) and Owner money
// (ledger.owner_money, the Owner) start here. The server checks every right and every amount
// again and makes each journal entry.

import "../shell/screens.css";

import { FormEvent, useCallback, useState } from "react";

import { centsFromText } from "../products/productsClient";
import { DateInput } from "../shell/DateInput";
import { dayText, momentText } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { Chip, Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import {
  type BankBook,
  type BankCash,
  type CashApi,
  cashApi as defaultCashApi,
  type CashBook,
  type CashMonth,
  type MoneyAccount,
} from "./cashClient";
import { accountName, money, useRead, Waiting } from "./LedgerPage";
import {
  AmountField,
  Done,
  Failure,
  FieldError,
  useBusy,
} from "./SpendingPage";
import { lt, monthLabel } from "./text";

export interface BankCashPageProps {
  language: Language;
  propertyId: string;
  active: boolean;
  capabilities: ReadonlySet<string> | null;
  api?: CashApi;
}

type Opened = "move" | "owner" | "topup" | null;

/** "410,000 ៛" */
function riel(amount: number): string {
  return `${Math.round(amount).toLocaleString("en-US")} ៛`;
}

/** Whole riel typed with or without commas; null when it is not a whole number. */
function rielFromText(value: string): number | null {
  const plain = value.replace(/[,\s]/g, "");
  return /^\d{1,15}$/.test(plain) ? Number(plain) : null;
}

/** What riel is worth in cents at a rate of riel for one dollar. */
function rielCents(amount: number, rate: number): number {
  return Math.round((amount * 100) / rate);
}

function EntryLink({ number }: { number: string | null }) {
  if (number === null) return <>—</>;
  return (
    <a className="ui-num" href={hashForPage("journal", number)}>
      {number}
    </a>
  );
}

function named(language: Language, account: MoneyAccount): string {
  return `${account.code} · ${accountName(language, account)}`;
}

export function BankCashPage({
  language,
  propertyId,
  active,
  capabilities,
  api = defaultCashApi,
}: BankCashPageProps) {
  const may = (capability: string) =>
    capabilities === null || capabilities.has(capability);
  const [month, setMonth] = useState<string | null>(null);
  const [view, setView] = useState<"bank" | "cash">("bank");
  const [opened, setOpened] = useState<Opened>(null);
  const [done, setDone] = useState<string | null>(null);
  const read = useCallback(
    () => api.read(propertyId, month),
    [api, propertyId, month],
  );
  const answer = useRead<BankCash>(active && propertyId !== "", read);
  if (propertyId === "") {
    return (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>{lt(language, "no_property")}</p>
      </div>
    );
  }
  const data = answer.data;
  const chosen = data?.month ?? null;
  const saved = (text: string) => {
    setOpened(null);
    setDone(text);
    answer.reload();
  };
  const open = (which: Opened) => {
    setDone(null);
    setOpened(which);
  };
  return (
    <>
      <Done text={done} />
      <section aria-labelledby="bc-title" className="ui-card">
        <div className="ui-head">
          <div>
            <h2 id="bc-title">{lt(language, "bc_t")}</h2>
            <p>{lt(language, "bc_sub")}</p>
          </div>
          <span className="ui-actions">
            {may("ledger.money_move") && (
              <button
                className="ui-btn"
                disabled={data === null}
                onClick={() => {
                  open("move");
                }}
                type="button"
              >
                <Icon name="swap" small />
                {lt(language, "mm_t")}
              </button>
            )}
            {may("ledger.petty_cash") && data?.petty !== null && (
              <button
                className="ui-btn"
                disabled={data === null}
                onClick={() => {
                  open("topup");
                }}
                type="button"
              >
                <Icon name="plus" small />
                {lt(language, "pt_t")}
              </button>
            )}
            {may("ledger.owner_money") && (
              <button
                className="ui-btn"
                disabled={data === null}
                onClick={() => {
                  open("owner");
                }}
                type="button"
              >
                <Icon name="customers" small />
                {lt(language, "ow_t")}
              </button>
            )}
          </span>
        </div>
      </section>
      {data === null ? (
        <Waiting
          failed={answer.failed}
          language={language}
          onRetry={answer.reload}
        />
      ) : (
        <>
          <div className="ui-split">
            {data.petty !== null && (
              <PettyCard language={language} petty={data.petty} />
            )}
            {data.riel !== null && (
              <RielCard language={language} riel={data.riel} />
            )}
            {data.riel_bank !== null && (
              <RielCard bank language={language} riel={data.riel_bank} />
            )}
          </div>
          <section aria-label={lt(language, "bc_t")} className="ui-card">
            <div
              aria-label={lt(language, "bc_t")}
              className="ui-seg"
              role="group"
            >
              {(["bank", "cash"] as const).map((which) => (
                <button
                  aria-pressed={view === which}
                  key={which}
                  onClick={() => {
                    setView(which);
                  }}
                  type="button"
                >
                  {lt(language, which === "bank" ? "bc_bank" : "bc_cash")}
                </button>
              ))}
            </div>
            {chosen === null ? (
              <p className="ui-empty">{lt(language, "bc_no_month")}</p>
            ) : (
              <>
                <div className="ui-field">
                  <label htmlFor="bc-month">{lt(language, "month")}</label>
                  <select
                    id="bc-month"
                    onChange={(event) => {
                      setDone(null);
                      setMonth(event.target.value);
                    }}
                    value={chosen.starts_on}
                  >
                    {data.months.map((item) => (
                      <option key={item.id} value={item.starts_on}>
                        {monthLabel(language, item.starts_on)}
                      </option>
                    ))}
                  </select>
                </div>
                {view === "bank" ? (
                  data.banks.length === 0 ? (
                    <p className="ui-empty">{lt(language, "bc_no_bank")}</p>
                  ) : (
                    data.banks.map((bank) => (
                      <BankPart
                        api={api}
                        bank={bank}
                        canMatch={may("ledger.reconcile")}
                        key={`${chosen.id}:${bank.code}`}
                        language={language}
                        month={chosen}
                        onDone={saved}
                        propertyId={propertyId}
                        showCode={data.banks.length > 1}
                      />
                    ))
                  )
                ) : (
                  <CashPart
                    api={api}
                    canCount={may("ledger.cash_count")}
                    cash={data.cash}
                    key={chosen.id}
                    language={language}
                    month={chosen}
                    onDone={saved}
                    propertyId={propertyId}
                    rate={data.rate}
                  />
                )}
              </>
            )}
          </section>
          {opened === "move" && (
            <MoveDialog
              api={api}
              data={data}
              language={language}
              onClose={() => {
                setOpened(null);
              }}
              onSaved={saved}
              propertyId={propertyId}
            />
          )}
          {opened === "topup" && data.petty !== null && (
            <TopUpDialog
              api={api}
              data={data}
              language={language}
              onClose={() => {
                setOpened(null);
              }}
              onSaved={saved}
              petty={data.petty}
              propertyId={propertyId}
            />
          )}
          {opened === "owner" && (
            <OwnerDialog
              api={api}
              data={data}
              language={language}
              onClose={() => {
                setOpened(null);
              }}
              onSaved={saved}
              propertyId={propertyId}
            />
          )}
        </>
      )}
    </>
  );
}

/* ---------- Petty cash and Riel cash ---------- */

function PettyCard({
  language,
  petty,
}: {
  language: Language;
  petty: NonNullable<BankCash["petty"]>;
}) {
  const room =
    petty.float_cents === null
      ? null
      : Math.max(0, petty.float_cents - petty.balance_cents);
  const waiting = petty.waiting.reduce((sum, row) => sum + row.amount_cents, 0);
  return (
    <section aria-labelledby="pc-title" className="ui-card">
      <h2 id="pc-title">{lt(language, "pt_card")}</h2>
      <dl className="ui-kv">
        <dt>{lt(language, "pt_float")}</dt>
        <dd className="ui-num">
          {petty.float_cents === null ? "—" : money(petty.float_cents)}
        </dd>
        <dt>{lt(language, "pt_bal")}</dt>
        <dd className="ui-num">{money(petty.balance_cents)}</dd>
        <dt>{lt(language, "pt_gap")}</dt>
        <dd className="ui-num">{room === null ? "—" : money(room)}</dd>
      </dl>
      {petty.waiting.length === 0 ? (
        <p className="ui-muted">{lt(language, "pt_open0")}</p>
      ) : (
        <p>
          {lt(
            language,
            "pt_open",
            String(petty.waiting.length),
            money(waiting),
          )}
          :{" "}
          {petty.waiting.map((row, index) => (
            <span key={row.request_number}>
              {index > 0 && ", "}
              <a
                className="ui-num"
                href={hashForPage("exreqs", row.request_number)}
              >
                {row.request_number}
              </a>
            </span>
          ))}
        </p>
      )}
      <p className="ui-muted">
        <Icon name="info" small /> {lt(language, "pt_n")}
      </p>
    </section>
  );
}

function RielCard({
  language,
  riel: held,
  bank = false,
}: {
  language: Language;
  riel: NonNullable<BankCash["riel"]>;
  /** The riel bank account rather than riel cash (owner 04/11/2026). */
  bank?: boolean;
}) {
  const titleId = bank ? "khb-title" : "kh-title";
  return (
    <section aria-labelledby={titleId} className="ui-card">
      <h2 id={titleId}>{lt(language, bank ? "kh_bt" : "kh_t")}</h2>
      <dl className="ui-kv">
        <dt>{lt(language, "kh_q")}</dt>
        <dd className="ui-num">{riel(held.held_riel)}</dd>
        <dt>
          {bank ? lt(language, "kh_bb", held.code) : lt(language, "kh_b")}
        </dt>
        <dd className="ui-num">{money(held.book_cents)}</dd>
        <dt>{lt(language, "kh_last")}</dt>
        <dd>
          {held.last_month_end === null ? (
            "—"
          ) : (
            <>
              {monthLabel(language, held.last_month_end)} ·{" "}
              <EntryLink number={held.last_entry_number} />
            </>
          )}
        </dd>
      </dl>
      <p className="ui-muted">
        <Icon name="info" small /> {lt(language, bank ? "kh_bn" : "kh_n")}
      </p>
    </section>
  );
}

/* ---------- Bank reconciliation ---------- */

function lineCents(line: BankBook["lines"][number]): number {
  return line.debit_cents - line.credit_cents;
}

/** A riel bank line in riel: money in adds, money out takes away. */
function lineRiel(line: BankBook["lines"][number]): number {
  const amount = line.riel_minor ?? 0;
  return line.debit_cents > 0 ? amount : -amount;
}

function BankPart({
  language,
  propertyId,
  bank,
  month,
  canMatch,
  showCode,
  api,
  onDone,
}: {
  language: Language;
  propertyId: string;
  bank: BankBook;
  month: CashMonth;
  canMatch: boolean;
  showCode: boolean;
  api: CashApi;
  onDone: (text: string) => void;
}) {
  const end = dayText(month.ends_on);
  const work = useBusy(language);
  // The riel bank account (owner 04/11/2026) is matched in riel, the dollar bank in dollars.
  const inRiel = bank.cash_kind === "BANK_KHR";
  const book = inRiel ? (bank.riel_held ?? 0) : bank.book_cents;
  const show = (amount: number) => (inRiel ? riel(amount) : money(amount));
  const amountOf = (line: BankBook["lines"][number]) =>
    inRiel ? lineRiel(line) : lineCents(line);
  const [statement, setStatement] = useState(
    inRiel ? String(book) : (book / 100).toFixed(2),
  );
  const [notYet, setNotYet] = useState<ReadonlySet<string>>(new Set());
  const heading = showCode ? (
    <h3>
      {bank.code} · {accountName(language, bank)}
    </h3>
  ) : null;
  if (bank.match !== null && bank.match.status === "MATCHED") {
    return (
      <div>
        {heading}
        <p>
          <Chip icon="check" tone="ok">
            {lt(language, "bk_done")}
          </Chip>{" "}
          <span className="ui-muted">
            {lt(
              language,
              "bk_done_by",
              bank.match.by_name ?? lt(language, "by_unknown"),
              momentText(bank.match.at),
            )}
          </span>
        </p>
        <dl className="ui-kv">
          <dt>{lt(language, "bk_stmt", end)}</dt>
          <dd className="ui-num">
            {inRiel
              ? riel(bank.match.statement_riel ?? 0)
              : money(bank.match.statement_balance_cents)}
          </dd>
          <dt>{lt(language, "bk_book", end, bank.code)}</dt>
          <dd className="ui-num">{show(book)}</dd>
          {inRiel && (
            <>
              <dt>{lt(language, "bk_worth", end)}</dt>
              <dd className="ui-num">{money(bank.book_cents)}</dd>
            </>
          )}
        </dl>
      </div>
    );
  }
  if (month.status !== "OPEN") {
    return (
      <div>
        {heading}
        <p className="ui-muted">{lt(language, "bc_closed")}</p>
      </div>
    );
  }
  const typed = inRiel ? rielFromText(statement) : centsFromText(statement);
  const less = bank.lines
    .filter((line) => notYet.has(line.line_id))
    .reduce((sum, line) => sum + amountOf(line), 0);
  const after = book - less;
  const difference = typed === null ? null : after - typed;
  const matches = difference === 0;
  const fieldId = `bk-s-${bank.code}`;

  function mark() {
    if (typed === null) return;
    work.run(
      () =>
        api.matchBank(propertyId, {
          account_code: bank.code,
          period_id: month.id,
          statement_balance_cents: inRiel ? null : typed,
          statement_riel: inRiel ? typed : null,
          lines: bank.lines
            .filter((line) => !notYet.has(line.line_id))
            .map((line) => ({ line_id: line.line_id })),
        }),
      () => {
        onDone(lt(language, "bk_saved", monthLabel(language, month.starts_on)));
      },
    );
  }

  return (
    <div>
      {heading}
      <div className="ui-field">
        <label htmlFor={fieldId}>{lt(language, "bk_stmt", end)}</label>
        <div className="ui-money">
          <span aria-hidden="true">{inRiel ? "៛" : "$"}</span>
          <input
            aria-describedby={`${fieldId}-h`}
            autoComplete="off"
            disabled={!canMatch}
            id={fieldId}
            inputMode="decimal"
            onChange={(event) => {
              setStatement(event.target.value);
            }}
            value={statement}
          />
        </div>
        <p className="ui-muted" id={`${fieldId}-h`}>
          {lt(language, inRiel ? "bk_stmt_hr" : "bk_stmt_h")}
        </p>
        <FieldError
          id={`${fieldId}-e`}
          text={
            typed === null
              ? lt(language, inRiel ? "bk_e_stmt_r" : "bk_e_stmt")
              : null
          }
        />
      </div>
      <h3>{lt(language, "bk_in_book")}</h3>
      {bank.lines.length === 0 ? (
        <p className="ui-muted">{lt(language, "bk_none")}</p>
      ) : (
        <>
          <p className="ui-muted">{lt(language, "bk_tick")}</p>
          <div className="ui-tablewrap">
            <table className="ui-table">
              <thead>
                <tr>
                  <th scope="col">{lt(language, "bk_not_yet")}</th>
                  <th scope="col">{lt(language, "what")}</th>
                  <th className="r" scope="col">
                    {lt(language, "amount")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {bank.lines.map((line) => (
                  <tr key={line.line_id}>
                    <td>
                      <input
                        aria-label={`${lt(language, "bk_not_yet")}: ${line.entry_number}`}
                        checked={notYet.has(line.line_id)}
                        disabled={!canMatch}
                        onChange={(event) => {
                          const next = new Set(notYet);
                          if (event.target.checked) next.add(line.line_id);
                          else next.delete(line.line_id);
                          setNotYet(next);
                        }}
                        type="checkbox"
                      />
                    </td>
                    <td>
                      <b>{line.memo ?? line.description}</b>
                      <span className="ui-sub2">
                        <span className="ui-num">
                          {dayText(line.entry_date)}
                        </span>{" "}
                        · {lt(language, "er_s_entry", "")}
                        <EntryLink number={line.entry_number} />
                      </span>
                    </td>
                    <td className="r ui-num">{show(amountOf(line))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <h3>{lt(language, "bk_in_stmt")}</h3>
      <p className="ui-muted">
        {lt(language, "bk_fee_how", bank.code)}{" "}
        <a href={hashForPage("expenses")}>{lt(language, "bk_go_x")}</a>
      </p>
      <h3>{lt(language, "bk_sum")}</h3>
      <div className="ui-tablewrap">
        <table className="ui-table">
          <thead>
            <tr>
              <th scope="col">{lt(language, "what")}</th>
              <th className="r" scope="col">
                {lt(language, "amount")}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>{lt(language, "bk_book", end, bank.code)}</td>
              <td className="r ui-num">{show(book)}</td>
            </tr>
            <tr>
              <td>{lt(language, "bk_less_tr")}</td>
              <td className="r ui-num">{show(-less)}</td>
            </tr>
            <tr>
              <td>
                <b>{lt(language, "bk_adj")}</b>
              </td>
              <td className="r ui-num">
                <b>{show(after)}</b>
              </td>
            </tr>
            <tr>
              <td>{lt(language, "bk_stmt", end)}</td>
              <td className="r ui-num">{typed === null ? "—" : show(typed)}</td>
            </tr>
          </tbody>
          <tfoot>
            <tr>
              <th scope="row">{lt(language, "bk_diff")}</th>
              <td className="r ui-num">
                {difference === null ? "—" : show(difference)}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
      <p aria-live="polite">
        {matches ? (
          <Chip icon="check" tone="ok">
            {lt(language, "bk_ok")}
          </Chip>
        ) : (
          <Chip icon="alert" tone="err">
            {lt(language, "bk_bad")}
          </Chip>
        )}{" "}
        <span className="ui-muted">
          {lt(language, matches ? "bk_ok_n" : "bk_bad_n")}
        </span>
      </p>
      <Failure text={work.failure} />
      {canMatch && (
        <button
          className="ui-btn primary"
          disabled={!matches || work.busy}
          onClick={mark}
          type="button"
        >
          <Icon name="check" small />
          {lt(language, "bk_mark")}
        </button>
      )}
    </div>
  );
}

/* ---------- Cash count ---------- */

function CashPart({
  language,
  propertyId,
  cash,
  month,
  rate,
  canCount,
  api,
  onDone,
}: {
  language: Language;
  propertyId: string;
  cash: CashBook[];
  month: CashMonth;
  rate: BankCash["rate"];
  canCount: boolean;
  api: CashApi;
  onDone: (text: string) => void;
}) {
  const end = dayText(month.ends_on);
  const work = useBusy(language);
  const [typed, setTyped] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [reasonError, setReasonError] = useState<string | null>(null);
  const open = cash.filter((account) => account.count === null);

  /** What the typed count is worth in cents, or null when it is not a number yet. */
  function worth(account: CashBook): number | null {
    const value = (typed[account.code] ?? "").trim();
    if (value === "") return null;
    if (account.cash_kind === "CASH_KHR") {
      const amount = rielFromText(value);
      return amount === null || rate === null
        ? null
        : rielCents(amount, rate.khr_per_usd);
    }
    return centsFromText(value);
  }

  if (open.length === 0) {
    const first = cash.find((account) => account.count !== null)?.count;
    const notes = [
      ...new Set(
        cash
          .map((account) => account.count?.note ?? null)
          .filter((note): note is string => note !== null),
      ),
    ];
    const entries = cash
      .map((account) => account.count?.entry_number ?? null)
      .filter((number): number is string => number !== null);
    return (
      <div>
        <p>
          <Chip icon="check" tone="ok">
            {lt(language, "cc_done")}
          </Chip>{" "}
          {first !== undefined && first !== null && (
            <span className="ui-muted">
              {lt(
                language,
                "bk_done_by",
                first.by_name ?? lt(language, "by_unknown"),
                momentText(first.at),
              )}
            </span>
          )}{" "}
          {entries.map((number) => (
            <span key={number}>
              {lt(language, "er_s_entry", "")}
              <EntryLink number={number} />{" "}
            </span>
          ))}
        </p>
        <CountTable cash={cash} end={end} language={language} />
        {notes.map((note) => (
          <p className="ui-muted" key={note}>
            {lt(language, "reason")}: {note}
          </p>
        ))}
      </div>
    );
  }
  if (month.status !== "OPEN") {
    return <p className="ui-muted">{lt(language, "bc_closed")}</p>;
  }

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      open.some((account) => account.cash_kind === "CASH_KHR") &&
      rate === null
    ) {
      setError(lt(language, "cc_e_rate"));
      return;
    }
    const values = open.map((account) => [account, worth(account)] as const);
    if (values.some(([, value]) => value === null)) {
      setError(lt(language, "cc_e_all"));
      return;
    }
    setError(null);
    const differs = values.some(
      ([account, value]) => value !== account.book_cents,
    );
    if (differs && reason.trim() === "") {
      setReasonError(lt(language, "br_e_reason"));
      return;
    }
    setReasonError(null);
    work.run(
      async () => {
        for (const [account, value] of values) {
          const khr = account.cash_kind === "CASH_KHR";
          await api.countCash(propertyId, {
            account_code: account.code,
            counted_on: month.ends_on,
            counted_cents: khr ? null : value,
            counted_riel: khr ? rielFromText(typed[account.code] ?? "") : null,
            exchange_rate_record_id: khr ? (rate?.id ?? null) : null,
            reason: value === account.book_cents ? null : reason.trim(),
          });
        }
      },
      () => {
        onDone(lt(language, "cc_saved", monthLabel(language, month.starts_on)));
      },
    );
  }

  return (
    <form noValidate onSubmit={save}>
      <p className="ui-muted">
        {lt(language, "cc_sub", monthLabel(language, month.starts_on))}
      </p>
      <div className="ui-tablewrap">
        <table className="ui-table">
          <thead>
            <tr>
              <th scope="col">{lt(language, "cc_box")}</th>
              <th className="r" scope="col">
                {lt(language, "cc_book", end)}
              </th>
              <th scope="col">{lt(language, "cc_counted")}</th>
              <th className="r" scope="col">
                {lt(language, "bk_diff")}
              </th>
            </tr>
          </thead>
          <tbody>
            {cash.map((account) => {
              const khr = account.cash_kind === "CASH_KHR";
              const value = worth(account);
              const id = `cc-${account.code}`;
              return (
                <tr key={account.code}>
                  <td>
                    <b>
                      {account.code} · {accountName(language, account)}
                    </b>
                    <span className="ui-sub2">
                      {lt(language, khr ? "cc_khr_n" : "cc_usd_n")}
                    </span>
                  </td>
                  <td className="r ui-num">
                    {money(account.book_cents)}
                    {khr && rate !== null && (
                      <span className="ui-sub2">
                        {lt(
                          language,
                          "cc_about",
                          riel((account.book_cents * rate.khr_per_usd) / 100),
                        )}
                      </span>
                    )}
                  </td>
                  <td>
                    {account.count !== null ? (
                      <span className="ui-num">
                        {account.count.counted_riel !== null
                          ? riel(account.count.counted_riel)
                          : money(account.count.counted_cents)}
                      </span>
                    ) : (
                      <>
                        <label className="ui-sr" htmlFor={id}>
                          {lt(language, "cc_counted")} {account.code}
                        </label>
                        <div className="ui-money">
                          <span aria-hidden="true">{khr ? "៛" : "$"}</span>
                          <input
                            autoComplete="off"
                            disabled={!canCount}
                            id={id}
                            inputMode={khr ? "numeric" : "decimal"}
                            onChange={(event) => {
                              setTyped({
                                ...typed,
                                [account.code]: event.target.value,
                              });
                            }}
                            value={typed[account.code] ?? ""}
                          />
                        </div>
                      </>
                    )}
                  </td>
                  <td aria-live="polite" className="r ui-num">
                    {account.count !== null
                      ? money(
                          account.count.counted_cents -
                            account.count.book_cents,
                        )
                      : value === null
                        ? "—"
                        : money(value - account.book_cents)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <FieldError id="cc-e1" text={error} />
      <div className="ui-field">
        <label htmlFor="cc-r">{lt(language, "cc_why")}</label>
        <p className="ui-muted" id="cc-rh">
          {lt(language, "cc_why_h")}
        </p>
        <textarea
          aria-describedby="cc-rh"
          disabled={!canCount}
          id="cc-r"
          onChange={(event) => {
            setReason(event.target.value);
          }}
          rows={2}
          value={reason}
        />
        <FieldError id="cc-e2" text={reasonError} />
      </div>
      <Failure text={work.failure} />
      {canCount ? (
        <button className="ui-btn primary" disabled={work.busy} type="submit">
          <Icon name="check" small />
          {lt(language, "cc_save")}
        </button>
      ) : (
        <p className="ui-muted">{lt(language, "f_right")}</p>
      )}
    </form>
  );
}

function CountTable({
  language,
  cash,
  end,
}: {
  language: Language;
  cash: CashBook[];
  end: string;
}) {
  return (
    <div className="ui-tablewrap">
      <table className="ui-table">
        <thead>
          <tr>
            <th scope="col">{lt(language, "cc_box")}</th>
            <th className="r" scope="col">
              {lt(language, "cc_book", end)}
            </th>
            <th className="r" scope="col">
              {lt(language, "cc_counted")}
            </th>
            <th className="r" scope="col">
              {lt(language, "bk_diff")}
            </th>
          </tr>
        </thead>
        <tbody>
          {cash.map((account) =>
            account.count === null ? null : (
              <tr key={account.code}>
                <td>
                  {account.code} · {accountName(language, account)}
                </td>
                <td className="r ui-num">{money(account.count.book_cents)}</td>
                <td className="r ui-num">
                  {money(account.count.counted_cents)}
                  {account.count.counted_riel !== null && (
                    <span className="ui-sub2">
                      {riel(account.count.counted_riel)}
                    </span>
                  )}
                </td>
                <td className="r ui-num">
                  {money(
                    account.count.counted_cents - account.count.book_cents,
                  )}
                </td>
              </tr>
            ),
          )}
        </tbody>
      </table>
    </div>
  );
}

/* ---------- Move money, Top up petty cash, Owner money ---------- */

function DayField({
  language,
  id,
  value,
  onChange,
}: {
  language: Language;
  id: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="ui-field">
      <label htmlFor={id}>
        {lt(language, "date")}
        <span className="req">{lt(language, "required")}</span>
      </label>
      <DateInput
        calendarLabel={lt(language, "date")}
        id={id}
        language={language}
        onChange={onChange}
        required
        value={value}
      />
    </div>
  );
}

function AccountSelect({
  language,
  id,
  label,
  accounts,
  value,
  onChange,
}: {
  language: Language;
  id: string;
  label: string;
  accounts: readonly MoneyAccount[];
  value: string;
  onChange: (code: string) => void;
}) {
  return (
    <div className="ui-field">
      <label htmlFor={id}>{label}</label>
      <select
        id={id}
        onChange={(event) => {
          onChange(event.target.value);
        }}
        value={value}
      >
        {accounts.map((account) => (
          <option key={account.code} value={account.code}>
            {named(language, account)}
          </option>
        ))}
      </select>
    </div>
  );
}

function pickCode(accounts: readonly MoneyAccount[], code: string): string {
  return accounts.some((account) => account.code === code)
    ? code
    : (accounts[0]?.code ?? "");
}

function balanceOf(data: BankCash, code: string): number {
  return (
    data.money_accounts.find((account) => account.code === code)
      ?.balance_cents ?? 0
  );
}

function MoveDialog({
  language,
  propertyId,
  data,
  api,
  onClose,
  onSaved,
}: {
  language: Language;
  propertyId: string;
  data: BankCash;
  api: CashApi;
  onClose: () => void;
  onSaved: (text: string) => void;
}) {
  const accounts = data.money_accounts.filter(
    (account) => account.cash_kind !== "PETTY",
  );
  const kindOf = (code: string) =>
    accounts.find((account) => account.code === code)?.cash_kind ?? "";
  const work = useBusy(language);
  const [from, setFrom] = useState(pickCode(accounts, "1010"));
  const [to, setTo] = useState(pickCode(accounts, "1020"));
  const [day, setDay] = useState(data.today);
  const [amount, setAmount] = useState("");
  const [rielText, setRielText] = useState("");
  const [rateText, setRateText] = useState(
    data.rate === null ? "" : String(data.rate.khr_per_usd),
  );
  const [error, setError] = useState<string | null>(null);
  // Riel cash and the riel bank account both take riel (owner 04/11/2026).
  const isRiel = (kind: string) => kind === "CASH_KHR" || kind === "BANK_KHR";
  const out = isRiel(kindOf(from));
  const into = isRiel(kindOf(to));
  const rielAmount = rielFromText(rielText);
  const rate = Number(rateText.replace(/[,\s]/g, ""));
  const held = kindOf(from) === "BANK_KHR" ? data.riel_bank : data.riel;
  const bookShare =
    out && rielAmount !== null && held !== null && held.held_riel > 0
      ? Math.round((held.book_cents * rielAmount) / held.held_riel)
      : 0;
  const got =
    out && rielAmount !== null && rate > 0 ? rielCents(rielAmount, rate) : 0;
  const gain = got - bookShare;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (from === to) {
      setError(lt(language, "mm_e_same"));
      return;
    }
    if ((out || into) && data.rate === null) {
      setError(lt(language, "er_no_rate"));
      return;
    }
    if (day === "") return;
    let body;
    if (out) {
      if (rielAmount === null || rielAmount <= 0 || !(rate > 0)) {
        setError(lt(language, "mm_e_riel"));
        return;
      }
      if (held === null || rielAmount > held.held_riel || bookShare < 1) {
        setError(lt(language, "mm_e_bal"));
        return;
      }
      body = {
        amount_cents: bookShare,
        received_cents: got,
        riel_amount_minor: rielAmount,
      };
    } else {
      const cents = centsFromText(amount);
      if (cents === null || cents <= 0) {
        setError(lt(language, "x_e_amt"));
        return;
      }
      if (cents > balanceOf(data, from)) {
        setError(lt(language, "mm_e_bal"));
        return;
      }
      if (into && (rielAmount === null || rielAmount <= 0)) {
        setError(lt(language, "mm_e_riel"));
        return;
      }
      body = {
        amount_cents: cents,
        received_cents: null,
        riel_amount_minor: into ? rielAmount : null,
      };
    }
    setError(null);
    work.run(async () => {
      const made = await api.moveMoney(propertyId, {
        moved_on: day,
        from_code: from,
        to_code: to,
        ...body,
        exchange_rate_record_id: out || into ? (data.rate?.id ?? null) : null,
      });
      return lt(
        language,
        "mm_done",
        await api.entryOf(propertyId, "money-move", made),
      );
    }, onSaved);
  }

  return (
    <Dialog
      busy={work.busy}
      closeLabel={lt(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={lt(language, "mm_ok")}
      title={lt(language, "mm_t")}
    >
      <div className="ui-row2">
        <AccountSelect
          accounts={accounts}
          id="mm-from"
          label={lt(language, "mm_from")}
          language={language}
          onChange={setFrom}
          value={from}
        />
        <AccountSelect
          accounts={accounts}
          id="mm-to"
          label={lt(language, "mm_to")}
          language={language}
          onChange={setTo}
          value={to}
        />
      </div>
      <div className="ui-row2">
        <DayField
          id="mm-day"
          language={language}
          onChange={setDay}
          value={day}
        />
        {!out && (
          <AmountField
            error={null}
            id="mm-amount"
            label={lt(language, "amount")}
            language={language}
            onChange={setAmount}
            value={amount}
          />
        )}
      </div>
      {out && (
        <div className="ui-row2">
          <AmountField
            error={null}
            id="mm-riel"
            label={lt(language, "mm_riel")}
            language={language}
            onChange={setRielText}
            riel
            value={rielText}
          />
          <div className="ui-field">
            <label htmlFor="mm-rate">{lt(language, "mm_rate")}</label>
            <input
              aria-describedby="mm-rate-h"
              autoComplete="off"
              className="ui-num"
              id="mm-rate"
              inputMode="numeric"
              onChange={(event) => {
                setRateText(event.target.value);
              }}
              value={rateText}
            />
            <p className="ui-muted" id="mm-rate-h">
              {lt(language, "mm_rate_h")}
            </p>
          </div>
        </div>
      )}
      {into && (
        <AmountField
          error={null}
          help={lt(language, "mm_riel_in_h")}
          id="mm-riel-in"
          label={lt(language, "mm_riel_in")}
          language={language}
          onChange={setRielText}
          riel
          value={rielText}
        />
      )}
      {out && rielAmount !== null && rielAmount > 0 && (
        <p aria-live="polite">
          {lt(
            language,
            "mm_prev",
            money(got),
            money(bookShare),
            gain >= 0
              ? lt(language, "mm_gain", money(gain))
              : lt(language, "mm_loss", money(-gain)),
          )}
        </p>
      )}
      <FieldError id="mm-e" text={error} />
      <p className="ui-muted">
        <Icon name="info" small /> {lt(language, "mm_n")}
      </p>
      <Failure text={work.failure} />
    </Dialog>
  );
}

function TopUpDialog({
  language,
  propertyId,
  data,
  petty,
  api,
  onClose,
  onSaved,
}: {
  language: Language;
  propertyId: string;
  data: BankCash;
  petty: NonNullable<BankCash["petty"]>;
  api: CashApi;
  onClose: () => void;
  onSaved: (text: string) => void;
}) {
  const accounts = data.money_accounts.filter(
    (account) =>
      account.cash_kind === "CASH_USD" || account.cash_kind === "BANK",
  );
  const room =
    petty.float_cents === null
      ? 0
      : Math.max(0, petty.float_cents - petty.balance_cents);
  const work = useBusy(language);
  const [from, setFrom] = useState(pickCode(accounts, "1010"));
  const [day, setDay] = useState(data.today);
  const [amount, setAmount] = useState((room / 100).toFixed(2));
  const [error, setError] = useState<string | null>(null);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cents = centsFromText(amount);
    if (cents === null || cents <= 0) {
      setError(lt(language, "x_e_amt"));
      return;
    }
    if (cents > room || cents > balanceOf(data, from)) {
      setError(lt(language, "pt_e_max"));
      return;
    }
    if (day === "") return;
    setError(null);
    work.run(async () => {
      const made = await api.topUp(propertyId, {
        topped_up_on: day,
        from_code: from,
        amount_cents: cents,
      });
      return lt(
        language,
        "pt_done",
        money(cents),
        await api.entryOf(propertyId, "petty-cash-top-up", made),
      );
    }, onSaved);
  }

  return (
    <Dialog
      busy={work.busy}
      closeLabel={lt(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={lt(language, "pt_ok")}
      title={lt(language, "pt_t")}
    >
      <p>
        {lt(
          language,
          "pt_now",
          petty.float_cents === null ? "—" : money(petty.float_cents),
          money(petty.balance_cents),
          money(room),
        )}
      </p>
      <div className="ui-row2">
        <AccountSelect
          accounts={accounts}
          id="pt-from"
          label={lt(language, "mm_from")}
          language={language}
          onChange={setFrom}
          value={from}
        />
        <DayField
          id="pt-day"
          language={language}
          onChange={setDay}
          value={day}
        />
      </div>
      <AmountField
        error={error}
        id="pt-amount"
        label={lt(language, "amount")}
        language={language}
        onChange={setAmount}
        value={amount}
      />
      <Failure text={work.failure} />
    </Dialog>
  );
}

function OwnerDialog({
  language,
  propertyId,
  data,
  api,
  onClose,
  onSaved,
}: {
  language: Language;
  propertyId: string;
  data: BankCash;
  api: CashApi;
  onClose: () => void;
  onSaved: (text: string) => void;
}) {
  const accounts = ["1020", "1010"]
    .map((code) => data.money_accounts.find((account) => account.code === code))
    .filter((account): account is MoneyAccount => account !== undefined);
  const work = useBusy(language);
  const [direction, setDirection] = useState<"IN" | "OUT">("IN");
  const [account, setAccount] = useState(pickCode(accounts, "1020"));
  const [day, setDay] = useState(data.today);
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [noteError, setNoteError] = useState<string | null>(null);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cents = centsFromText(amount);
    if (cents === null || cents <= 0) {
      setError(lt(language, "x_e_amt"));
      return;
    }
    if (direction === "OUT" && cents > balanceOf(data, account)) {
      setError(lt(language, "mm_e_bal"));
      return;
    }
    setError(null);
    if (note.trim() === "") {
      setNoteError(lt(language, "br_e_reason"));
      return;
    }
    setNoteError(null);
    if (day === "") return;
    work.run(async () => {
      const made = await api.ownerMoney(propertyId, {
        direction,
        moved_on: day,
        account_code: account,
        amount_cents: cents,
        note: note.trim(),
      });
      return lt(
        language,
        direction === "IN" ? "ow_done_in" : "ow_done_out",
        money(cents),
        await api.entryOf(propertyId, "owner-money", made),
      );
    }, onSaved);
  }

  return (
    <Dialog
      busy={work.busy}
      closeLabel={lt(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={lt(language, "ow_ok")}
      title={lt(language, "ow_t")}
    >
      <fieldset className="ui-radios">
        <legend>{lt(language, "ow_dir")}</legend>
        {(["IN", "OUT"] as const).map((value) => (
          <label className="ui-chk" key={value}>
            <input
              checked={direction === value}
              name="ow-dir"
              onChange={() => {
                setDirection(value);
              }}
              type="radio"
            />
            <span>
              {lt(language, value === "IN" ? "ow_in" : "ow_out")}
              <small>
                {lt(language, value === "IN" ? "ow_in_s" : "ow_out_s")}
              </small>
            </span>
          </label>
        ))}
      </fieldset>
      <div className="ui-row2">
        <AccountSelect
          accounts={accounts}
          id="ow-acc"
          label={lt(language, "ow_acc")}
          language={language}
          onChange={setAccount}
          value={account}
        />
        <DayField
          id="ow-day"
          language={language}
          onChange={setDay}
          value={day}
        />
      </div>
      <AmountField
        error={error}
        id="ow-amount"
        label={lt(language, "amount")}
        language={language}
        onChange={setAmount}
        value={amount}
      />
      <div className="ui-field">
        <label htmlFor="ow-note">
          {lt(language, "ow_note")}
          <span className="req">{lt(language, "required")}</span>
        </label>
        <input
          aria-describedby={noteError === null ? undefined : "ow-note-e"}
          autoComplete="off"
          id="ow-note"
          onChange={(event) => {
            setNote(event.target.value);
          }}
          value={note}
        />
        <FieldError id="ow-note-e" text={noteError} />
      </div>
      <p className="ui-muted">
        <Icon name="lock" small /> {lt(language, "ow_n")}
      </p>
      <Failure text={work.failure} />
    </Dialog>
  );
}
