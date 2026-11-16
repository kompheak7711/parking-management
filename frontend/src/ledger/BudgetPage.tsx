// General Ledger phase 6 step 6 part 4 (mock-up v76, app26 vBudget): Office › Ledger tab Budget.
// The Accountant types the budget by month for the year (ledger.budgets.prepare) and sends it
// whole; the Owner approves it or sends it back with a reason (ledger.budgets.approve). Nobody
// approves their own; the Owner's own budget is approved at once with a note. The amounts typed
// stay on this screen until they are sent. The server checks everything again.

import "../shell/screens.css";

import { type FormEvent, type ReactNode, useCallback, useState } from "react";

import { centsFromText } from "../products/productsClient";
import { momentText } from "../shell/format";
import { Icon } from "../shell/icons";
import { Chip, Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import {
  type Budget,
  type BudgetAccount,
  type BudgetApi,
  type BudgetLine,
  type BudgetSheet,
  budgetApi as defaultBudgetApi,
} from "./budgetClient";
import { accountName, money, useRead, Waiting } from "./LedgerPage";
import { Done, Failure, FieldError, useBusy } from "./SpendingPage";
import { type LedgerTextKey, lt, monthName, monthShort } from "./text";
import { PageHead } from "../shell/pageHead";

export interface BudgetPageProps {
  language: Language;
  propertyId: string;
  active: boolean;
  capabilities: ReadonlySet<string> | null;
  actorId: string | null;
  api?: BudgetApi;
}

const MONTHS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] as const;
const GROUPS: readonly { type: string; label: LedgerTextKey }[] = [
  { type: "INCOME", label: "t_INCOME" },
  { type: "COST_OF_SALES", label: "t_COST_OF_SALES" },
  { type: "EXPENSE", label: "t_EXPENSE" },
];

/** Twelve amounts in cents for each account code. */
type Amounts = Record<string, readonly number[]>;

type Stage = "OK" | "WAIT" | "DRAFT";

function amountsOf(lines: readonly BudgetLine[]): Amounts {
  const out: Record<string, number[]> = {};
  for (const line of lines) {
    const row = (out[line.account_code] ??= MONTHS.map(() => 0));
    row[line.month_no - 1] = line.amount_cents;
  }
  return out;
}

function linesOf(amounts: Amounts): BudgetLine[] {
  return Object.entries(amounts)
    .filter(([, values]) => values.some((value) => value > 0))
    .sort(([a], [b]) => a.localeCompare(b))
    .flatMap(([code, values]) =>
      values.map((amount, index) => ({
        account_code: code,
        month_no: index + 1,
        amount_cents: amount,
      })),
    );
}

function sum(values: readonly number[]): number {
  return values.reduce((total, value) => total + value, 0);
}

function stageOf(latest: Budget | null): Stage {
  if (latest?.status === "APPROVED") return "OK";
  if (latest?.status === "DRAFT") return "WAIT";
  return "DRAFT";
}

export function BudgetPage({
  language,
  propertyId,
  active,
  capabilities,
  actorId,
  api = defaultBudgetApi,
}: BudgetPageProps) {
  const may = (capability: string) =>
    capabilities === null || capabilities.has(capability);
  const canPrepare = may("ledger.budgets.prepare");
  const canApprove = may("ledger.budgets.approve");
  const [year, setYear] = useState<number | null>(null);
  const read = useCallback(
    () => api.read(propertyId, year),
    [api, propertyId, year],
  );
  const answer = useRead<BudgetSheet>(active && propertyId !== "", read);
  const [typed, setTyped] = useState<Record<number, Amounts>>({});
  const [editing, setEditing] = useState<BudgetAccount | null>(null);
  const [asking, setAsking] = useState<"own" | "back" | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const work = useBusy(language);
  if (propertyId === "") {
    return (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>{lt(language, "no_property")}</p>
      </div>
    );
  }
  const data = answer.data;
  const header = (
    <section aria-labelledby="bu-title" className="ui-card">
      <PageHead>
        <div>
          <h2 id="bu-title">{lt(language, "bu_t")}</h2>
          <p>{lt(language, "bu_sub")}</p>
        </div>
      </PageHead>
    </section>
  );
  if (data === null) {
    return (
      <>
        {header}
        <Waiting
          failed={answer.failed}
          language={language}
          onRetry={answer.reload}
        />
      </>
    );
  }
  const shown = data.year;
  if (shown === null) {
    return (
      <>
        {header}
        <p className="ui-empty">{lt(language, "bu_no_year")}</p>
      </>
    );
  }
  const latest = data.budgets[0] ?? null;
  const stage = stageOf(latest);
  const closed =
    data.years.find((item) => item.fiscal_year === shown)?.status !== "OPEN";
  const editable = stage === "DRAFT" && canPrepare && !closed;
  const start =
    latest?.status === "REPLACED"
      ? amountsOf(latest.lines)
      : amountsOf(data.earlier_lines);
  const amounts: Amounts =
    stage === "DRAFT"
      ? (typed[shown] ?? start)
      : amountsOf(latest?.lines ?? []);
  const lines = linesOf(amounts);
  const mine = latest !== null && latest.created_by === actorId;
  const label = String(shown);

  const finished = (text: string) => {
    setAsking(null);
    setDone(text);
    answer.reload();
  };
  const sendNow = (note: string | null) => {
    work.run(async () => {
      await api.send(propertyId, shown, lines, note);
      return lt(language, canApprove ? "bu_done" : "bu_sent", label);
    }, finished);
  };
  const decide = (approve: boolean, note: string | null) => {
    if (latest === null) return;
    work.run(async () => {
      await api.decide(propertyId, latest.id, approve, note);
      return lt(language, approve ? "bu_done" : "bu_backed_t", label);
    }, finished);
  };

  const actions: ReactNode[] = [];
  if (editable) {
    actions.push(
      <button
        className="ui-btn primary"
        disabled={work.busy || lines.length === 0}
        key="send"
        onClick={() => {
          setDone(null);
          if (canApprove) setAsking("own");
          else sendNow(null);
        }}
        type="button"
      >
        <Icon name="forward" small />
        {lt(language, "bu_send")}
      </button>,
    );
  }
  if (stage === "WAIT" && canApprove && !mine && !closed) {
    actions.push(
      <button
        className="ui-btn"
        disabled={work.busy}
        key="back"
        onClick={() => {
          setDone(null);
          setAsking("back");
        }}
        type="button"
      >
        <Icon name="back" small />
        {lt(language, "bu_back")}
      </button>,
      <button
        className="ui-btn primary"
        disabled={work.busy}
        key="ok"
        onClick={() => {
          setDone(null);
          decide(true, null);
        }}
        type="button"
      >
        <Icon name="check" small />
        {lt(language, "bu_ok")}
      </button>,
    );
  }

  const note: string | null = closed
    ? lt(language, "bu_closed", label)
    : stage === "WAIT" && mine
      ? lt(language, "bu_self")
      : stage === "WAIT" && !canApprove
        ? lt(language, "bu_wait")
        : stage === "OK"
          ? lt(language, "bu_locked")
          : editable
            ? lt(language, "bu_edit_n")
            : null;

  return (
    <>
      <Done text={done} />
      {header}
      <section aria-labelledby="bu-for" className="ui-card">
        {data.years.length > 1 && (
          <div
            aria-label={lt(language, "bu_year")}
            className="ui-seg"
            role="group"
          >
            {data.years.map((item) => (
              <button
                aria-pressed={item.fiscal_year === shown}
                key={item.fiscal_year}
                onClick={() => {
                  setDone(null);
                  setYear(item.fiscal_year);
                }}
                type="button"
              >
                {item.fiscal_year}
              </button>
            ))}
          </div>
        )}
        <div className="ui-head">
          <h2 id="bu-for">{lt(language, "bu_for", label)}</h2>
          <StageChip language={language} stage={stage} />
          {actions.length > 0 && <div className="ui-actions">{actions}</div>}
        </div>
        <Who language={language} latest={latest} stage={stage} />
        {latest?.status === "REPLACED" && latest.decision_note !== null && (
          <div className="ui-notice warn" role="status">
            <Icon name="alert" />
            <p>
              {lt(
                language,
                "bu_backed",
                latest.approved_by_name ?? "",
                latest.decision_note,
              )}
            </p>
          </div>
        )}
        <Failure text={work.failure} />
        <BudgetTable
          accounts={data.accounts}
          amounts={amounts}
          editable={editable}
          language={language}
          onEdit={setEditing}
        />
        {note !== null && (
          <p className="ui-muted">
            <Icon name="info" small /> {note}
          </p>
        )}
      </section>
      {editing !== null && (
        <EditDialog
          account={editing}
          language={language}
          onClose={() => {
            setEditing(null);
          }}
          onSave={(values) => {
            setTyped({
              ...typed,
              [shown]: { ...amounts, [editing.code]: values },
            });
            setEditing(null);
            setDone(lt(language, "bu_saved"));
          }}
          values={amounts[editing.code] ?? MONTHS.map(() => 0)}
        />
      )}
      {asking !== null && (
        <NoteDialog
          busy={work.busy}
          failure={work.failure}
          language={language}
          onClose={() => {
            setAsking(null);
          }}
          onSend={(text) => {
            if (asking === "own") sendNow(text);
            else decide(false, text);
          }}
          own={asking === "own"}
        />
      )}
    </>
  );
}

function StageChip({ language, stage }: { language: Language; stage: Stage }) {
  if (stage === "OK")
    return (
      <Chip icon="check" tone="ok">
        {lt(language, "bu_st_OK")}
      </Chip>
    );
  if (stage === "WAIT")
    return (
      <Chip icon="clock" tone="warn">
        {lt(language, "bu_st_WAIT")}
      </Chip>
    );
  return <Chip tone="neutral">{lt(language, "bu_st_DRAFT")}</Chip>;
}

function Who({
  language,
  latest,
  stage,
}: {
  language: Language;
  latest: Budget | null;
  stage: Stage;
}) {
  if (latest === null) return null;
  const by = latest.created_by_name ?? "";
  const at = momentText(latest.created_at);
  return (
    <p className="ui-muted">
      {stage === "OK"
        ? lt(
            language,
            "bu_who_ok",
            by,
            at,
            latest.approved_by_name ?? by,
            momentText(latest.approved_at),
          )
        : lt(language, "bu_who", by, at)}
    </p>
  );
}

function BudgetTable({
  language,
  accounts,
  amounts,
  editable,
  onEdit,
}: {
  language: Language;
  accounts: readonly BudgetAccount[];
  amounts: Amounts;
  editable: boolean;
  onEdit: (account: BudgetAccount) => void;
}) {
  const zero = MONTHS.map(() => 0);
  const of = (code: string) => amounts[code] ?? zero;
  const rowsOf = (type: string) =>
    accounts.filter(
      (account) =>
        account.account_type === type &&
        (editable || of(account.code).some((value) => value > 0)),
    );
  const totals = (type: string) =>
    MONTHS.map((_, index) =>
      sum(rowsOf(type).map((account) => of(account.code)[index] ?? 0)),
    );
  const income = totals("INCOME");
  const cost = totals("COST_OF_SALES");
  const spend = totals("EXPENSE");
  const profit = income.map(
    (value, index) => value - (cost[index] ?? 0) - (spend[index] ?? 0),
  );
  const totalRow = (key: LedgerTextKey, values: readonly number[]) => (
    <tr key={key}>
      <th scope="row">
        <b>{lt(language, key)}</b>
      </th>
      {values.map((value, index) => (
        <td className="r ui-num" key={MONTHS[index]}>
          <b>{money(value)}</b>
        </td>
      ))}
      <td className="r ui-num">
        <b>{money(sum(values))}</b>
      </td>
    </tr>
  );
  return (
    <div className="ui-tablewrap">
      <table className="ui-table">
        <thead>
          <tr>
            <th scope="col">{lt(language, "account")}</th>
            {MONTHS.map((month) => (
              <th className="r" key={month} scope="col">
                {monthShort(language, month)}
              </th>
            ))}
            <th className="r" scope="col">
              {lt(language, "bu_year")}
            </th>
          </tr>
        </thead>
        <tbody>
          {GROUPS.flatMap((group) => {
            const rows = rowsOf(group.type);
            if (rows.length === 0 && group.type === "COST_OF_SALES") return [];
            const out = [
              <tr key={`g-${group.type}`}>
                <th colSpan={14} scope="colgroup">
                  {lt(language, group.label)}
                </th>
              </tr>,
              ...rows.map((account) => {
                const values = of(account.code);
                const name = `${account.code} · ${accountName(language, account)}`;
                return (
                  <tr key={account.code}>
                    <th scope="row">
                      {editable ? (
                        <button
                          className="ui-btn link"
                          onClick={() => {
                            onEdit(account);
                          }}
                          type="button"
                        >
                          {name}
                        </button>
                      ) : (
                        name
                      )}
                    </th>
                    {values.map((value, index) => (
                      <td className="r ui-num" key={MONTHS[index]}>
                        {money(value)}
                      </td>
                    ))}
                    <td className="r ui-num">
                      <b>{money(sum(values))}</b>
                    </td>
                  </tr>
                );
              }),
            ];
            if (group.type === "INCOME") out.push(totalRow("bu_ti", income));
            if (group.type === "EXPENSE") {
              out.push(totalRow("bu_tx", spend), totalRow("bu_pr", profit));
            }
            return out;
          })}
        </tbody>
      </table>
    </div>
  );
}

function centsText(cents: number): string {
  return (cents / 100).toFixed(2);
}

function EditDialog({
  language,
  account,
  values,
  onClose,
  onSave,
}: {
  language: Language;
  account: BudgetAccount;
  values: readonly number[];
  onClose: () => void;
  onSave: (values: readonly number[]) => void;
}) {
  const [same, setSame] = useState("");
  const [months, setMonths] = useState(values.map(centsText));
  const [errors, setErrors] = useState<readonly boolean[]>([]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cents = months.map((value) =>
      value.trim() === "" ? 0 : centsFromText(value),
    );
    const found = cents.map((value) => value === null || value < 0);
    setErrors(found);
    if (found.some(Boolean)) return;
    onSave(cents.map((value) => value ?? 0));
  }

  return (
    <Dialog
      closeLabel={lt(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={lt(language, "save")}
      title={lt(language, "bu_edit_t", accountName(language, account))}
    >
      <div className="ui-row2">
        <div className="ui-field">
          <label htmlFor="bu-all">{lt(language, "bu_same")}</label>
          <div className="ui-money">
            <span aria-hidden="true">$</span>
            <input
              autoComplete="off"
              id="bu-all"
              inputMode="decimal"
              onChange={(event) => {
                setSame(event.target.value);
              }}
              value={same}
            />
          </div>
        </div>
        <div className="ui-field">
          <span aria-hidden="true">&nbsp;</span>
          <button
            className="ui-btn"
            onClick={() => {
              if (same.trim() !== "") setMonths(MONTHS.map(() => same));
            }}
            type="button"
          >
            {lt(language, "bu_fill")}
          </button>
        </div>
      </div>
      <div className="ui-row2">
        {MONTHS.map((month, index) => (
          <div className="ui-field" key={month}>
            <label htmlFor={`bu-${String(month)}`}>
              {monthName(language, month)}
            </label>
            <div className="ui-money">
              <span aria-hidden="true">$</span>
              <input
                aria-describedby={
                  errors[index] === true ? `bu-${String(month)}-e` : undefined
                }
                autoComplete="off"
                id={`bu-${String(month)}`}
                inputMode="decimal"
                onChange={(event) => {
                  const next = [...months];
                  next[index] = event.target.value;
                  setMonths(next);
                }}
                value={months[index] ?? ""}
              />
            </div>
            <FieldError
              id={`bu-${String(month)}-e`}
              text={errors[index] === true ? lt(language, "bu_e_amt") : null}
            />
          </div>
        ))}
      </div>
    </Dialog>
  );
}

function NoteDialog({
  language,
  own,
  busy,
  failure,
  onClose,
  onSend,
}: {
  language: Language;
  own: boolean;
  busy: boolean;
  failure: string | null;
  onClose: () => void;
  onSend: (text: string) => void;
}) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (text.trim() === "") {
      setError(lt(language, own ? "bu_e_note" : "br_e_reason"));
      return;
    }
    setError(null);
    onSend(text.trim());
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={lt(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={lt(language, own ? "bu_send" : "bu_back")}
      title={lt(language, own ? "bu_send" : "bu_back")}
    >
      {own && <p>{lt(language, "bu_own_n")}</p>}
      <div className="ui-field">
        <label htmlFor="bu-note">
          {lt(language, own ? "ow_note" : "reason")}
          <span className="req">{lt(language, "required")}</span>
        </label>
        <input
          aria-describedby={error === null ? undefined : "bu-note-e"}
          autoComplete="off"
          id="bu-note"
          onChange={(event) => {
            setText(event.target.value);
          }}
          value={text}
        />
        <FieldError id="bu-note-e" text={error} />
      </div>
      <Failure text={failure} />
    </Dialog>
  );
}
