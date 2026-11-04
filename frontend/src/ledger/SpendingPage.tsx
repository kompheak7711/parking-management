// General Ledger phase 6 step 6 part 2 (mock-up v76, app24/app26): Office › Ledger tabs
// Expense requests, Expenses and Supplier bills. Every role sends requests and reports
// (expenses.request); approving needs expenses.approve, and above the Expense limit
// expenses.approve_over_limit (the Owner); advances, bills and paying back need expenses.record.
// The server checks every right and every amount again and makes each journal entry.

import "../shell/screens.css";

import {
  FormEvent,
  type ReactNode,
  useCallback,
  useMemo,
  useState,
} from "react";

import { centsFromText } from "../products/productsClient";
import { DateInput } from "../shell/DateInput";
import { dayText, momentText } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { useHashDetail } from "../shell/useHashPage";
import { Chip, CountCard, Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import { LedgerError } from "./ledgerClient";
import { accountName, money, useRead, Waiting } from "./LedgerPage";
import {
  type BillPayment,
  type ExpenseRequest,
  type ExpenseRow,
  type PaidHow,
  type RequestDetail,
  type SpendAccount,
  type SpendingApi,
  spendingApi as defaultSpendingApi,
  type SpendingForm,
  type SupplierBill,
} from "./spendingClient";
import { type LedgerTextKey, lt } from "./text";

export type SpendingTab = "exreqs" | "expenses" | "bills";

export interface SpendingPageProps {
  language: Language;
  propertyId: string;
  active: boolean;
  tab: SpendingTab;
  capabilities: ReadonlySet<string> | null;
  /** The signed-in person: nobody approves their own request. */
  actorId: string | null;
  api?: SpendingApi;
}

interface Rights {
  send: boolean;
  approve: boolean;
  overLimit: boolean;
  pay: boolean;
}

function failureText(language: Language, error: unknown): string {
  if (error instanceof LedgerError) {
    if (error.status === 403) return lt(language, "f_right");
    if (error.status === 404) return lt(language, "er_not_found");
    if ((error.status === 422 || error.status === 409) && error.detail !== null)
      return lt(language, "f_refused", error.detail);
  }
  return lt(language, "f_failed");
}

function named(
  language: Language,
  code: string | null,
  en: string | null,
  km: string | null,
): string {
  if (code === null) return "—";
  if (en === null) return code;
  return `${code} · ${accountName(language, { name_en: en, name_km: km })}`;
}

export function addDays(day: string, days: number): string {
  const [year = 0, month = 1, date = 1] = day.split("-").map(Number);
  const moved = new Date(Date.UTC(year, month - 1, date + days));
  return moved.toISOString().slice(0, 10);
}

function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(to) - Date.parse(from)) / 86_400_000);
}

export function useBusy(language: Language): {
  busy: boolean;
  failure: string | null;
  run: <T>(work: () => Promise<T>, done: (value: T) => void) => void;
} {
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const run = <T,>(work: () => Promise<T>, done: (value: T) => void) => {
    setBusy(true);
    setFailure(null);
    work().then(
      (value) => {
        setBusy(false);
        done(value);
      },
      (error: unknown) => {
        setBusy(false);
        setFailure(failureText(language, error));
      },
    );
  };
  return { busy, failure, run };
}

export function SpendingPage({
  language,
  propertyId,
  active,
  tab,
  capabilities,
  actorId,
  api = defaultSpendingApi,
}: SpendingPageProps) {
  const may = (capability: string) =>
    capabilities === null || capabilities.has(capability);
  const rights: Rights = {
    send: may("expenses.request"),
    approve: may("expenses.approve"),
    overLimit: may("expenses.approve_over_limit"),
    pay: may("expenses.record"),
  };
  if (propertyId === "") {
    return (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>{lt(language, "no_property")}</p>
      </div>
    );
  }
  if (tab === "exreqs")
    return (
      <RequestsTab
        active={active}
        actorId={actorId}
        api={api}
        language={language}
        propertyId={propertyId}
        rights={rights}
      />
    );
  if (tab === "expenses")
    return (
      <ExpensesTab
        active={active}
        api={api}
        language={language}
        propertyId={propertyId}
        rights={rights}
      />
    );
  return (
    <BillsTab
      active={active}
      api={api}
      language={language}
      propertyId={propertyId}
      rights={rights}
    />
  );
}

/* ---------- shared pieces ---------- */

export function Done({ text }: { text: string | null }) {
  if (text === null) return null;
  return (
    <div className="ui-notice ok" role="status">
      <Icon name="check" />
      <p>{text}</p>
    </div>
  );
}

export function Failure({ text }: { text: string | null }) {
  if (text === null) return null;
  return (
    <p className="ui-error" role="alert">
      {text}
    </p>
  );
}

export function FieldError({ id, text }: { id: string; text: string | null }) {
  if (text === null) return null;
  return (
    <p className="ui-error" id={id}>
      {text}
    </p>
  );
}

function MoneyFrom({
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
  accounts: readonly SpendAccount[];
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
            {account.code} · {accountName(language, account)}
          </option>
        ))}
      </select>
    </div>
  );
}

export function pick(accounts: readonly SpendAccount[], code: string): string {
  return accounts.some((account) => account.code === code)
    ? code
    : (accounts[0]?.code ?? "");
}

/** The supplier's id, adding the supplier when the typed name is new. */
export async function supplierId(
  api: SpendingApi,
  propertyId: string,
  form: SpendingForm,
  typed: string,
): Promise<string | null> {
  const name = typed.trim();
  if (name === "") return null;
  const key = name.toLowerCase();
  const known = form.suppliers.find(
    (supplier) => supplier.name.trim().toLowerCase() === key,
  );
  if (known !== undefined) return known.id;
  // A supplier added on a save the app then refused is used again on the next try, not added
  // twice: the form is read again only after a save goes through.
  const added = addedSuppliers.get(form) ?? new Map<string, string>();
  addedSuppliers.set(form, added);
  const again = added.get(key);
  if (again !== undefined) return again;
  const made = await api.addSupplier(propertyId, name);
  added.set(key, made);
  return made;
}

const addedSuppliers = new WeakMap<SpendingForm, Map<string, string>>();

export function SupplierField({
  id,
  label,
  form,
  value,
  onChange,
  required = false,
  error,
  language,
}: {
  id: string;
  label: string;
  form: SpendingForm;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  error: string | null;
  language: Language;
}) {
  return (
    <div className="ui-field">
      <label htmlFor={id}>
        {label}
        {required && <span className="req">{lt(language, "required")}</span>}
      </label>
      <input
        aria-describedby={error === null ? undefined : `${id}-e`}
        autoComplete="off"
        id={id}
        list={`${id}-list`}
        onChange={(event) => {
          onChange(event.target.value);
        }}
        value={value}
      />
      <datalist id={`${id}-list`}>
        {form.suppliers
          .filter(
            (supplier, at, all) =>
              all.findIndex(
                (other) =>
                  other.name.trim().toLowerCase() ===
                  supplier.name.trim().toLowerCase(),
              ) === at,
          )
          .map((supplier) => (
            <option key={supplier.id} value={supplier.name} />
          ))}
      </datalist>
      <FieldError id={`${id}-e`} text={error} />
    </div>
  );
}

export function AmountField({
  id,
  label,
  value,
  onChange,
  error,
  language,
  riel = false,
  help,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  error: string | null;
  language: Language;
  riel?: boolean;
  help?: string;
}) {
  return (
    <div className="ui-field">
      <label htmlFor={id}>
        {label}
        <span className="req">{lt(language, "required")}</span>
      </label>
      <div className="ui-money">
        <span aria-hidden="true">{riel ? "៛" : "$"}</span>
        <input
          aria-describedby={
            [
              help === undefined ? "" : `${id}-h`,
              error === null ? "" : `${id}-e`,
            ]
              .filter(Boolean)
              .join(" ") || undefined
          }
          autoComplete="off"
          id={id}
          inputMode={riel ? "numeric" : "decimal"}
          onChange={(event) => {
            onChange(event.target.value);
          }}
          value={value}
        />
      </div>
      {help !== undefined && help !== "" && (
        <p aria-live="polite" className="ui-muted" id={`${id}-h`}>
          {help}
        </p>
      )}
      <FieldError id={`${id}-e`} text={error} />
    </div>
  );
}

/* ---------- Expense requests ---------- */

type RequestFilter = "open" | "all" | "wait" | "adv" | "late" | "owed";

function isOwed(request: ExpenseRequest): boolean {
  return request.owed_to_staff_cents > 0;
}

function isLate(request: ExpenseRequest): boolean {
  return request.advance_late || request.is_late;
}

function overLimit(request: ExpenseRequest, limit: number | null): boolean {
  return limit === null || request.amount_cents > limit;
}

function canApprove(
  request: ExpenseRequest,
  rights: Rights,
  actorId: string | null,
  limit: number | null,
): boolean {
  return (
    request.status === "WAITING" &&
    request.requested_by !== actorId &&
    (rights.overLimit || (rights.approve && !overLimit(request, limit)))
  );
}

function paidFromText(language: Language, request: ExpenseRequest): string {
  if (request.paid_how === "ADVANCE") return lt(language, "er_f_ADV");
  if (request.paid_how === "OWN_MONEY") return lt(language, "er_f_OWN");
  if (request.paid_how === "PAY_LATER") return lt(language, "er_f_LATER");
  return request.paid_from_name === null
    ? (request.paid_from_code ?? "—")
    : accountName(language, {
        name_en: request.paid_from_name,
        name_km: request.paid_from_name_km,
      });
}

function requestDay(request: ExpenseRequest): string {
  return request.spent_on ?? request.created_at.slice(0, 10);
}

function StatusChip({
  language,
  request,
}: {
  language: Language;
  request: ExpenseRequest;
}) {
  const key = `er_st_${request.status}` as LedgerTextKey;
  if (request.status === "WAITING")
    return (
      <Chip icon="clock" tone="warn">
        {lt(language, key)}
      </Chip>
    );
  if (request.status === "APPROVED")
    return (
      <Chip icon="check" tone="info">
        {lt(language, key)}
      </Chip>
    );
  if (request.status === "PAID_OUT")
    return (
      <Chip
        icon={request.advance_late ? "alert" : "payments"}
        tone={request.advance_late ? "err" : "info"}
      >
        {lt(language, key)}
      </Chip>
    );
  if (request.status === "DONE")
    return (
      <Chip icon="check" tone="ok">
        {lt(language, key)}
      </Chip>
    );
  return <Chip tone="neutral">{lt(language, key)}</Chip>;
}

function MoreChips({
  language,
  request,
}: {
  language: Language;
  request: ExpenseRequest;
}) {
  const chips = [
    request.kind === "URGENT_REPORT" && (
      <Chip key="rep" tone="neutral">
        {lt(language, "er_rep")}
      </Chip>
    ),
    request.own_spending_note !== null && (
      <Chip key="own" tone="neutral">
        {lt(language, "er_own")}
      </Chip>
    ),
    isLate(request) && (
      <Chip icon="alert" key="late" tone="err">
        {lt(language, "er_late")}
      </Chip>
    ),
    isOwed(request) && (
      <Chip key="owed" tone="warn">
        {lt(language, "er_owed")}
      </Chip>
    ),
  ].filter(Boolean);
  if (chips.length === 0) return null;
  return <span className="ui-sub2 ui-actions">{chips}</span>;
}

type RequestAction = "approve" | "advance" | "bill" | "payback" | "void";

function nextAction(
  request: ExpenseRequest,
  rights: Rights,
  actorId: string | null,
  limit: number | null,
): RequestAction | null {
  if (canApprove(request, rights, actorId, limit)) return "approve";
  if (request.status === "APPROVED" && rights.pay)
    return request.paid_how === "ADVANCE" ? "advance" : "bill";
  if (request.status === "PAID_OUT" && rights.pay) return "bill";
  if (isOwed(request) && rights.pay) return "payback";
  return null;
}

const ACTION_TEXT: Record<RequestAction, LedgerTextKey> = {
  approve: "er_approve",
  advance: "er_give",
  bill: "er_bill",
  payback: "er_payback",
  void: "er_void",
};

const ACTION_ICON = {
  approve: "check",
  advance: "payments",
  bill: "invoice",
  payback: "payments",
  void: "x",
} as const;

function waitingText(
  language: Language,
  request: ExpenseRequest,
  rights: Rights,
  actorId: string | null,
  limit: number | null,
): string {
  if (request.status === "WAITING") {
    if (request.requested_by === actorId) return lt(language, "er_n_self");
    if (overLimit(request, limit) && !rights.overLimit)
      return lt(language, "er_n_owner");
    return lt(language, "er_n_wait");
  }
  if (
    request.status === "APPROVED" ||
    request.status === "PAID_OUT" ||
    isOwed(request)
  )
    return lt(language, "er_n_acct");
  return "—";
}

function RequestsTab({
  language,
  propertyId,
  active,
  rights,
  actorId,
  api,
}: {
  language: Language;
  propertyId: string;
  active: boolean;
  rights: Rights;
  actorId: string | null;
  api: SpendingApi;
}) {
  const detail = useHashDetail("exreqs");
  const readList = useCallback(
    () => api.requests(propertyId),
    [api, propertyId],
  );
  const readForm = useCallback(() => api.form(propertyId), [api, propertyId]);
  const list = useRead<ExpenseRequest[]>(active && detail === null, readList);
  const form = useRead<SpendingForm>(active, readForm);
  const [filter, setFilter] = useState<RequestFilter>("open");
  const [dialog, setDialog] = useState<
    | { kind: "new"; urgent: boolean }
    | { kind: RequestAction; request: ExpenseRequest }
    | null
  >(null);
  const [done, setDone] = useState<string | null>(null);

  const finished = (text: string, number?: string) => {
    setDialog(null);
    setDone(text);
    if (number !== undefined)
      window.location.hash = hashForPage("exreqs", number);
    list.reload();
    form.reload();
  };

  const formData = form.data;
  const dialogs =
    dialog === null || formData === null ? null : dialog.kind === "new" ? (
      <RequestDialog
        api={api}
        form={formData}
        language={language}
        onClose={() => {
          setDialog(null);
        }}
        onSent={(number) => {
          finished(lt(language, "er_sent", number), number);
        }}
        propertyId={propertyId}
        urgent={dialog.urgent}
      />
    ) : (
      <ActionDialog
        action={dialog.kind}
        api={api}
        form={formData}
        language={language}
        onClose={() => {
          setDialog(null);
        }}
        onDone={(text) => {
          finished(text);
        }}
        propertyId={propertyId}
        request={dialog.request}
      />
    );

  if (detail !== null) {
    return (
      <>
        <Done text={done} />
        <RequestDetailView
          actorId={actorId}
          active={active}
          api={api}
          form={formData}
          key={`${detail}-${done ?? ""}`}
          language={language}
          number={detail}
          onAction={(kind, request) => {
            setDone(null);
            setDialog({ kind, request });
          }}
          propertyId={propertyId}
          rights={rights}
        />
        {dialogs}
      </>
    );
  }

  const limit = formData?.expense_limit_cents ?? null;
  const days = formData?.report_days ?? 3;
  const rows = list.data;
  const header = (
    <div className="ui-head">
      <div>
        <h2>{lt(language, "er_t")}</h2>
        <p>{lt(language, "er_sub")}</p>
      </div>
      {rights.send && (
        <span className="ui-actions">
          <button
            className="ui-btn"
            disabled={formData === null}
            onClick={() => {
              setDone(null);
              setDialog({ kind: "new", urgent: true });
            }}
            type="button"
          >
            <Icon name="plus" small />
            {lt(language, "er_new_rep")}
          </button>
          <button
            className="ui-btn primary"
            disabled={formData === null}
            onClick={() => {
              setDone(null);
              setDialog({ kind: "new", urgent: false });
            }}
            type="button"
          >
            <Icon name="plus" small />
            {lt(language, "er_new")}
          </button>
        </span>
      )}
    </div>
  );
  const abilities: string[] = [];
  if (rights.overLimit) abilities.push(lt(language, "er_can_all"));
  else if (rights.approve)
    abilities.push(lt(language, "er_can_lim", money(limit)));
  if (rights.pay) abilities.push(lt(language, "er_can_pay"));
  if (abilities.length === 0) abilities.push(lt(language, "er_can_send"));
  const seesAll = rights.approve || rights.overLimit || rights.pay;

  if (rows === null) {
    return (
      <section aria-labelledby="er-title" className="ui-card">
        {header}
        <Waiting
          failed={list.failed}
          language={language}
          onRetry={list.reload}
        />
      </section>
    );
  }
  const sets: Record<RequestFilter, ExpenseRequest[]> = {
    wait: rows.filter((row) => row.status === "WAITING"),
    adv: rows.filter((row) => row.status === "PAID_OUT"),
    late: rows.filter(isLate),
    owed: rows.filter(isOwed),
    open: rows.filter(
      (row) =>
        row.status === "WAITING" ||
        row.status === "APPROVED" ||
        row.status === "PAID_OUT" ||
        isOwed(row),
    ),
    all: rows,
  };
  const sum = (
    items: ExpenseRequest[],
    value: (row: ExpenseRequest) => number,
  ) => items.reduce((total, row) => total + value(row), 0);
  const forYou = sets.wait.filter((row) =>
    canApprove(row, rights, actorId, limit),
  ).length;
  const shown = sets[filter];
  const listTitle: Record<RequestFilter, LedgerTextKey> = {
    all: "er_c_all",
    open: "er_list_open",
    wait: "er_c_wait",
    adv: "er_c_adv",
    late: "er_c_late",
    owed: "er_c_owed",
  };
  const choose = (next: RequestFilter) => {
    setFilter(filter === next ? "open" : next);
  };
  return (
    <>
      <Done text={done} />
      <section aria-labelledby="er-title" className="ui-card">
        {header}
        <div className="ui-notice info" role="status">
          <Icon name="customers" />
          <p>
            {abilities.join(" ")}
            {!seesAll && (
              <>
                <br />
                {lt(language, "er_own_only")}
              </>
            )}
          </p>
        </div>
      </section>
      <section aria-labelledby="er-open" className="ui-card">
        <div className="ui-chead">
          <h2 id="er-open">{lt(language, "er_open_t")}</h2>
          {filter !== "open" && (
            <button
              className="ui-btn link"
              onClick={() => {
                setFilter("open");
              }}
              type="button"
            >
              {lt(language, "er_c_open")}
            </button>
          )}
        </div>
        <div className="ui-kpis">
          <CountCard
            icon="clock"
            label={lt(language, "er_c_wait")}
            note={
              money(sum(sets.wait, (row) => row.amount_cents)) +
              (forYou > 0
                ? ` · ${lt(language, "er_for_you", String(forYou))}`
                : "")
            }
            onPress={() => {
              choose("wait");
            }}
            pressed={filter === "wait"}
            tone="warn"
            value={sets.wait.length}
          />
          <CountCard
            icon="payments"
            label={lt(language, "er_c_adv")}
            note={lt(language, "er_c_n", String(sets.adv.length))}
            onPress={() => {
              choose("adv");
            }}
            pressed={filter === "adv"}
            tone="info"
            value={sets.adv.length}
            valueText={money(sum(sets.adv, (row) => row.amount_cents))}
          />
          <CountCard
            icon="alert"
            label={lt(language, "er_c_late")}
            note={lt(language, "er_c_late_s", String(days))}
            onPress={() => {
              choose("late");
            }}
            pressed={filter === "late"}
            tone="err"
            value={sets.late.length}
          />
          <CountCard
            icon="customers"
            label={lt(language, "er_c_owed")}
            note={lt(language, "er_c_owed_s")}
            onPress={() => {
              choose("owed");
            }}
            pressed={filter === "owed"}
            tone="brand"
            value={sets.owed.length}
            valueText={money(sum(sets.owed, (row) => row.owed_to_staff_cents))}
          />
        </div>
      </section>
      <section aria-labelledby="er-list" className="ui-card pad0">
        <div className="ui-chead pad">
          <h2 id="er-list">
            {lt(language, listTitle[filter])}{" "}
            <span className="ui-count ui-num">{shown.length}</span>
          </h2>
          {filter !== "all" && (
            <button
              className="ui-btn link"
              onClick={() => {
                setFilter("all");
              }}
              type="button"
            >
              {lt(language, "er_c_all")}
            </button>
          )}
        </div>
        {shown.length === 0 ? (
          <p className="ui-empty pad">{lt(language, "er_none")}</p>
        ) : (
          <div className="ui-tablewrap">
            <table className="ui-table">
              <thead>
                <tr>
                  <th scope="col">{lt(language, "er_no")}</th>
                  <th scope="col">{lt(language, "er_for")}</th>
                  <th className="r" scope="col">
                    {lt(language, "er_amt")}
                  </th>
                  <th scope="col">{lt(language, "er_from")}</th>
                  <th scope="col">{lt(language, "col_status")}</th>
                  <th scope="col">{lt(language, "er_next")}</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((row) => {
                  const action = nextAction(row, rights, actorId, limit);
                  return (
                    <tr key={row.id}>
                      <td>
                        <a
                          className="ui-num"
                          href={hashForPage("exreqs", row.request_number)}
                        >
                          {row.request_number}
                        </a>
                        <span className="ui-sub2 ui-num">
                          {dayText(requestDay(row))}
                        </span>
                        <span className="ui-sub2">
                          {row.requested_by_name ?? lt(language, "by_unknown")}
                        </span>
                      </td>
                      <td>
                        {accountName(language, {
                          name_en: row.account_name,
                          name_km: row.account_name_km,
                        })}
                        {row.unit_number !== null && (
                          <span className="ui-sub2">
                            <b>{lt(language, "er_unit")}</b> {row.unit_number}
                          </span>
                        )}
                        <span className="ui-sub2">{row.description}</span>
                      </td>
                      <td className="r ui-num">
                        {money(row.amount_cents)}
                        {row.original_currency === "KHR" &&
                          row.original_amount_minor !== null && (
                            <span className="ui-sub2">
                              {row.original_amount_minor.toLocaleString(
                                "en-US",
                              )}{" "}
                              ៛
                            </span>
                          )}
                      </td>
                      <td>{paidFromText(language, row)}</td>
                      <td>
                        <StatusChip language={language} request={row} />
                        <MoreChips language={language} request={row} />
                      </td>
                      <td>
                        {action === null ? (
                          <span className="ui-muted">
                            {waitingText(language, row, rights, actorId, limit)}
                          </span>
                        ) : (
                          <button
                            className="ui-btn primary"
                            disabled={formData === null}
                            onClick={() => {
                              setDone(null);
                              setDialog({ kind: action, request: row });
                            }}
                            type="button"
                          >
                            <Icon name={ACTION_ICON[action]} small />
                            {lt(language, ACTION_TEXT[action])}
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
          <Icon name="info" small /> {lt(language, "gl_x_limit", money(limit))}{" "}
          {lt(language, "er_due_n", String(days))}
        </p>
      </section>
      {dialogs}
    </>
  );
}

function stepText(
  language: Language,
  detail: RequestDetail,
  step: RequestDetail["steps"][number],
): string {
  const who = step.by_name ?? lt(language, "by_unknown");
  if (step.step === "SUBMITTED") return lt(language, "er_s_sent", who);
  if (step.step === "APPROVED") return lt(language, "er_s_ok", who);
  if (step.step === "REFUSED") return lt(language, "er_st_REFUSED");
  if (step.step === "VOID")
    return lt(
      language,
      "er_s_void",
      who,
      step.note ?? detail.void_reason ?? "",
    );
  if (step.step === "DONE") return lt(language, "er_st_DONE");
  return step.step;
}

function RequestDetailView({
  language,
  propertyId,
  active,
  number,
  rights,
  actorId,
  form,
  api,
  onAction,
}: {
  language: Language;
  propertyId: string;
  active: boolean;
  number: string;
  rights: Rights;
  actorId: string | null;
  form: SpendingForm | null;
  api: SpendingApi;
  onAction: (kind: RequestAction, request: ExpenseRequest) => void;
}) {
  const [error, setError] = useState<unknown>(null);
  const read = useCallback(
    () =>
      api.request(propertyId, number).catch((caught: unknown) => {
        setError(caught);
        throw caught;
      }),
    [api, propertyId, number],
  );
  const { data, failed, reload } = useRead<RequestDetail>(active, read);
  const back = (
    <a className="ui-crumb" href={hashForPage("exreqs")}>
      <Icon name="back" small />
      {lt(language, "er_t")}
    </a>
  );
  if (data === null || data.request_number !== number) {
    if (failed && error instanceof LedgerError && error.status === 404) {
      return (
        <>
          {back}
          <p className="ui-muted">{lt(language, "er_not_found")}</p>
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
  const limit = form?.expense_limit_cents ?? null;
  const days = form?.report_days ?? 3;
  const actions: RequestAction[] = [];
  if (canApprove(data, rights, actorId, limit)) actions.push("approve");
  if (data.status === "APPROVED" && rights.pay)
    actions.push(data.paid_how === "ADVANCE" ? "advance" : "bill");
  if (data.status === "PAID_OUT" && rights.pay) actions.push("bill");
  if (isOwed(data) && rights.pay) actions.push("payback");
  if (
    (data.status === "WAITING" || data.status === "APPROVED") &&
    (rights.approve || rights.overLimit || data.requested_by === actorId)
  )
    actions.push("void");
  const due = data.spent_on === null ? null : addDays(data.spent_on, days);
  const forName = named(
    language,
    data.account_code,
    data.account_name,
    data.account_name_km,
  );
  const need = overLimit(data, limit)
    ? lt(language, "er_who_own", money(limit))
    : lt(language, "er_who_acct", money(limit));
  const waitNote =
    data.status !== "WAITING" || canApprove(data, rights, actorId, limit)
      ? null
      : data.requested_by === actorId
        ? lt(language, "er_wait_self")
        : overLimit(data, limit)
          ? lt(language, "er_wait_own", money(limit))
          : lt(language, "er_wait_any");
  const entryLink = (entry: string | null) =>
    entry === null ? null : (
      <a className="ui-num" href={hashForPage("journal", entry)}>
        {lt(language, "er_s_entry", entry)}
      </a>
    );
  const advance = data.advance;
  const fromName = (code: string | null) => {
    const account = form?.money_accounts.find((item) => item.code === code);
    return account === undefined
      ? (code ?? "—")
      : `${account.code} · ${accountName(language, account)}`;
  };
  return (
    <>
      {back}
      <div className="ui-head">
        <div>
          <div className="ui-hrow">
            <h2 className="ui-num">{data.request_number}</h2>
            <StatusChip language={language} request={data} />
            <MoreChips language={language} request={data} />
          </div>
          <p>
            {lt(language, data.kind === "URGENT_REPORT" ? "er_rep" : "er_req")}{" "}
            · <span className="ui-num">{dayText(requestDay(data))}</span> ·{" "}
            {data.requested_by_name ?? lt(language, "by_unknown")}
          </p>
        </div>
        {actions.length > 0 && (
          <span className="ui-actions">
            {actions
              .slice()
              .reverse()
              .map((action) => (
                <button
                  className={action === "void" ? "ui-btn" : "ui-btn primary"}
                  disabled={form === null}
                  key={action}
                  onClick={() => {
                    onAction(action, data);
                  }}
                  type="button"
                >
                  <Icon name={ACTION_ICON[action]} small />
                  {lt(language, ACTION_TEXT[action])}
                </button>
              ))}
          </span>
        )}
      </div>
      <div className="ui-split">
        <section aria-labelledby="er-details" className="ui-card">
          <h2 id="er-details">{lt(language, "er_details")}</h2>
          <dl className="ui-kv">
            <dt>{lt(language, "er_urgent")}</dt>
            <dd>
              {lt(
                language,
                data.kind === "URGENT_REPORT" ? "er_u_yes" : "er_u_no",
              )}
            </dd>
            <dt>
              {lt(
                language,
                data.kind === "URGENT_REPORT" ? "er_date_spent" : "er_date",
              )}
            </dt>
            <dd className="ui-num">{dayText(requestDay(data))}</dd>
            <dt>{lt(language, "er_for")}</dt>
            <dd>{forName}</dd>
            <dt>{lt(language, "er_why")}</dt>
            <dd>
              {data.description}
              {data.reason !== data.description && (
                <span className="ui-sub2">{data.reason}</span>
              )}
            </dd>
            <dt>{lt(language, "er_amt")}</dt>
            <dd className="ui-num">
              {money(data.amount_cents)}
              {data.original_currency === "KHR" &&
                data.original_amount_minor !== null && (
                  <span className="ui-sub2">
                    {data.original_amount_minor.toLocaleString("en-US")} ៛
                  </span>
                )}
            </dd>
            <dt>{lt(language, "er_sup_s")}</dt>
            <dd>{data.supplier_name ?? "—"}</dd>
            {data.account_code === "6050" && (
              <>
                <dt>{lt(language, "er_unit")}</dt>
                <dd>{data.unit_number ?? "—"}</dd>
              </>
            )}
            <dt>{lt(language, "er_from")}</dt>
            <dd>{paidFromText(language, data)}</dd>
            <dt>{lt(language, "er_need")}</dt>
            <dd>{need}</dd>
          </dl>
          {waitNote !== null && (
            <p className="ui-muted">
              <Icon name="clock" small /> {waitNote}
            </p>
          )}
          {actions.length === 0 &&
            data.status !== "DONE" &&
            data.status !== "VOID" &&
            !rights.pay && (
              <p className="ui-muted">
                <Icon name="info" small /> {lt(language, "er_cant")}
              </p>
            )}
        </section>
        <section aria-labelledby="er-steps" className="ui-card">
          <h2 id="er-steps">{lt(language, "er_steps")}</h2>
          <ol className="ui-timeline">
            {data.steps
              .filter(
                (step) => step.step !== "PAID_OUT" && step.step !== "BILL_BACK",
              )
              .map((step) => (
                <li key={`${step.step}-${step.at}`}>
                  <div>
                    <b>{stepText(language, data, step)}</b>
                    <small className="ui-num">{momentText(step.at)}</small>
                    {step.step === "SUBMITTED" &&
                      data.is_late &&
                      due !== null && (
                        <small>
                          <Chip icon="alert" tone="err">
                            {lt(language, "er_late")}
                          </Chip>{" "}
                          {lt(
                            language,
                            "er_late_n",
                            dayText(due),
                            String(days),
                          )}
                        </small>
                      )}
                    {step.step === "APPROVED" &&
                      data.own_spending_note !== null && (
                        <small>{lt(language, "er_own_n")}</small>
                      )}
                  </div>
                </li>
              ))}
            {advance !== null && (
              <li>
                <div>
                  <b>
                    {lt(
                      language,
                      "er_s_adv",
                      money(advance.amount_cents),
                      advance.by_name ?? lt(language, "by_unknown"),
                      fromName(advance.from_code),
                    )}
                  </b>
                  <small className="ui-num">{dayText(advance.paid_on)}</small>
                  {entryLink(advance.entry_number)}
                </div>
              </li>
            )}
            {data.expenses.map((expense) => {
              const change =
                advance === null
                  ? 0
                  : advance.amount_cents - expense.amount_cents;
              return (
                <li key={expense.expense_number}>
                  <div>
                    <b>
                      {lt(
                        language,
                        "er_s_bill",
                        money(expense.amount_cents),
                        expense.by_name ?? lt(language, "by_unknown"),
                      )}
                    </b>
                    <small className="ui-num">
                      {dayText(expense.expense_date)} · {expense.expense_number}
                    </small>
                    {change > 0 && (
                      <small>
                        {lt(language, "er_s_change", money(change))}
                      </small>
                    )}
                    {change < 0 && data.paid_how === "ADVANCE" && (
                      <small>
                        {lt(language, "er_s_extra", money(-change))}
                      </small>
                    )}
                    {entryLink(expense.entry_number)}
                  </div>
                </li>
              );
            })}
            {data.paybacks.map((payback) => (
              <li key={`${payback.paid_on}-${payback.entry_number ?? ""}`}>
                <div>
                  <b>
                    {lt(
                      language,
                      "er_s_back",
                      money(payback.amount_cents),
                      data.requested_by_name ?? lt(language, "by_unknown"),
                      payback.by_name ?? lt(language, "by_unknown"),
                    )}
                  </b>
                  <small className="ui-num">{dayText(payback.paid_on)}</small>
                  {entryLink(payback.entry_number)}
                </div>
              </li>
            ))}
          </ol>
          {data.status === "PAID_OUT" && (
            <p className="ui-muted">
              <Icon name="clock" small />{" "}
              {lt(language, "er_give_n", String(days))}
            </p>
          )}
        </section>
      </div>
    </>
  );
}

const REQUEST_FROM = ["ADV", "1030", "1010", "1011", "1020", "LATER"] as const;
const REPORT_FROM = ["OWN", "1030"] as const;

function RequestDialog({
  language,
  propertyId,
  form,
  urgent: startUrgent,
  api,
  onClose,
  onSent,
}: {
  language: Language;
  propertyId: string;
  form: SpendingForm;
  urgent: boolean;
  api: SpendingApi;
  onClose: () => void;
  onSent: (number: string) => void;
}) {
  const [urgent, setUrgent] = useState(startUrgent);
  const [day, setDay] = useState(form.today);
  const [account, setAccount] = useState(pick(form.accounts, "6050"));
  const [unit, setUnit] = useState("");
  const [why, setWhy] = useState("");
  const [currency, setCurrency] = useState<"USD" | "KHR">("USD");
  const [amount, setAmount] = useState("");
  const [supplier, setSupplier] = useState("");
  const [from, setFrom] = useState<string>(startUrgent ? "OWN" : "ADV");
  const [errors, setErrors] = useState<Record<string, string | null>>({});
  const work = useBusy(language);

  const choices: readonly string[] = urgent ? REPORT_FROM : REQUEST_FROM;
  const fromChoices = choices.filter(
    (code) =>
      code === "ADV" ||
      code === "OWN" ||
      code === "LATER" ||
      form.money_accounts.some((item) => item.code === code),
  );
  const chosenFrom = fromChoices.includes(from) ? from : (fromChoices[0] ?? "");
  const rate = form.rate;
  const cents = useMemo(() => {
    if (currency === "USD") return centsFromText(amount);
    const riel = amount.trim().replace(/[,\s]/g, "");
    if (!/^\d{1,12}$/.test(riel) || rate === null) return null;
    const value = Math.round((Number(riel) * 100) / rate.khr_per_usd);
    return value > 0 ? value : null;
  }, [amount, currency, rate]);
  const limit = form.expense_limit_cents;
  const help = [
    currency === "KHR" && cents !== null && rate !== null
      ? lt(
          language,
          "er_rate",
          money(cents),
          rate.khr_per_usd.toLocaleString("en-US"),
        )
      : "",
    cents === null
      ? ""
      : limit === null || cents > limit
        ? lt(language, "er_who_own", money(limit))
        : lt(language, "er_who_acct", money(limit)),
  ]
    .filter(Boolean)
    .join(" ");
  const late =
    urgent && day !== "" && addDays(day, form.report_days) < form.today;
  const chosenAccount = form.accounts.find((item) => item.code === account);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found: Record<string, string | null> = {};
    if (day === "" || day > form.today) found.day = lt(language, "er_e_date");
    if (why.trim() === "") found.why = lt(language, "er_e_why");
    if (currency === "KHR" && rate === null)
      found.amount = lt(language, "er_no_rate");
    else if (cents === null) found.amount = lt(language, "er_e_amt");
    if (
      cents !== null &&
      chosenAccount?.account_type === "EXPENSE" &&
      form.asset_limit_cents !== null &&
      cents >= form.asset_limit_cents
    )
      found.account = lt(language, "er_asset_h", money(form.asset_limit_cents));
    setErrors(found);
    if (Object.values(found).some((value) => value !== null) || cents === null)
      return;
    let paidHow: PaidHow = "CASH";
    let paidFrom: string | null = chosenFrom;
    if (chosenFrom === "ADV") [paidHow, paidFrom] = ["ADVANCE", null];
    if (chosenFrom === "OWN") [paidHow, paidFrom] = ["OWN_MONEY", null];
    if (chosenFrom === "LATER") [paidHow, paidFrom] = ["PAY_LATER", null];
    const riel = Number(amount.trim().replace(/[,\s]/g, ""));
    work.run(async () => {
      const supplierRef = await supplierId(api, propertyId, form, supplier);
      const made = await api.submitRequest(propertyId, {
        kind: urgent ? "URGENT_REPORT" : "REQUEST",
        account_code: account,
        description: why.trim(),
        reason: why.trim(),
        amount_cents: cents,
        currency,
        original_amount_minor: currency === "KHR" ? riel : null,
        exchange_rate_record_id: currency === "KHR" ? (rate?.id ?? null) : null,
        supplier_id: supplierRef,
        unit_id: account === "6050" && unit !== "" ? unit : null,
        spent_on: urgent ? day : null,
        paid_how: paidHow,
        paid_from_code: paidFrom,
      });
      const rows = await api.requests(propertyId);
      return rows.find((row) => row.id === made)?.request_number ?? "";
    }, onSent);
  }

  const fromLabel = (code: string) => {
    if (code === "ADV") return lt(language, "er_f_ADV");
    if (code === "OWN") return lt(language, "er_f_OWN");
    if (code === "LATER") return lt(language, "er_f_LATER");
    const item = form.money_accounts.find((money) => money.code === code);
    return item === undefined
      ? code
      : `${code} · ${accountName(language, item)}`;
  };

  return (
    <Dialog
      busy={work.busy}
      closeLabel={lt(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={lt(language, "er_send")}
      title={lt(language, urgent ? "er_new_rep" : "er_new")}
    >
      <fieldset className="ui-radios">
        <legend>{lt(language, "er_urgent")}</legend>
        {[false, true].map((value) => (
          <label className="ui-chk" key={String(value)}>
            <input
              checked={urgent === value}
              name="er-urgent"
              onChange={() => {
                setUrgent(value);
              }}
              type="radio"
            />
            <span>{lt(language, value ? "er_u_yes" : "er_u_no")}</span>
          </label>
        ))}
      </fieldset>
      <div className="ui-field">
        <label htmlFor="er-day">
          {lt(language, urgent ? "er_date_spent" : "er_date")}
          <span className="req">{lt(language, "required")}</span>
        </label>
        <DateInput
          calendarLabel={lt(language, urgent ? "er_date_spent" : "er_date")}
          id="er-day"
          language={language}
          onChange={setDay}
          required
          value={day}
        />
        <FieldError id="er-day-e" text={errors.day ?? null} />
      </div>
      {late && (
        <p className="ui-muted">
          <Chip icon="alert" tone="err">
            {lt(language, "er_late")}
          </Chip>{" "}
          {lt(
            language,
            "er_late_n",
            dayText(addDays(day, form.report_days)),
            String(form.report_days),
          )}
        </p>
      )}
      <div className="ui-field">
        <label htmlFor="er-for">{lt(language, "er_for")}</label>
        <select
          id="er-for"
          onChange={(event) => {
            setAccount(event.target.value);
          }}
          value={account}
        >
          <optgroup label={lt(language, "t_expenses")}>
            {form.accounts
              .filter((item) => item.account_type !== "ASSET")
              .map((item) => (
                <option key={item.code} value={item.code}>
                  {item.code} · {accountName(language, item)}
                </option>
              ))}
          </optgroup>
          <optgroup label={lt(language, "t_assets")}>
            {form.accounts
              .filter((item) => item.account_type === "ASSET")
              .map((item) => (
                <option key={item.code} value={item.code}>
                  {item.code} · {accountName(language, item)}
                </option>
              ))}
          </optgroup>
        </select>
        <FieldError id="er-for-e" text={errors.account ?? null} />
      </div>
      {account === "6050" && (
        <div className="ui-field">
          <label htmlFor="er-unit">{lt(language, "er_unit")}</label>
          <p className="ui-muted" id="er-unit-h">
            {lt(language, "er_unit_h")}
          </p>
          <select
            aria-describedby="er-unit-h"
            id="er-unit"
            onChange={(event) => {
              setUnit(event.target.value);
            }}
            value={unit}
          >
            <option value="">{lt(language, "er_unit_none")}</option>
            {form.units.map((item) => (
              <option key={item.id} value={item.id}>
                {item.unit_number}
              </option>
            ))}
          </select>
        </div>
      )}
      <div className="ui-field">
        <label htmlFor="er-why">
          {lt(language, "er_why")}
          <span className="req">{lt(language, "required")}</span>
        </label>
        <textarea
          id="er-why"
          onChange={(event) => {
            setWhy(event.target.value);
          }}
          rows={2}
          value={why}
        />
        <FieldError id="er-why-e" text={errors.why ?? null} />
      </div>
      <div className="ui-row2">
        <div className="ui-field">
          <label htmlFor="er-cur">{lt(language, "er_cur")}</label>
          <select
            id="er-cur"
            onChange={(event) => {
              setCurrency(event.target.value === "KHR" ? "KHR" : "USD");
            }}
            value={currency}
          >
            <option value="USD">USD $</option>
            <option value="KHR">KHR ៛</option>
          </select>
        </div>
        <AmountField
          error={errors.amount ?? null}
          help={help}
          id="er-amount"
          label={lt(language, "er_amt")}
          language={language}
          onChange={setAmount}
          riel={currency === "KHR"}
          value={amount}
        />
      </div>
      <SupplierField
        error={null}
        form={form}
        id="er-sup"
        label={lt(language, "er_sup")}
        language={language}
        onChange={setSupplier}
        value={supplier}
      />
      <div className="ui-field">
        <label htmlFor="er-from">{lt(language, "er_from")}</label>
        <select
          id="er-from"
          onChange={(event) => {
            setFrom(event.target.value);
          }}
          value={chosenFrom}
        >
          {fromChoices.map((code) => (
            <option key={code} value={code}>
              {fromLabel(code)}
            </option>
          ))}
        </select>
      </div>
      {urgent && (
        <p className="ui-muted">
          <Icon name="clock" small />{" "}
          {lt(language, "er_due_n", String(form.report_days))}
        </p>
      )}
      <Failure text={work.failure} />
    </Dialog>
  );
}

function ActionDialog({
  language,
  propertyId,
  form,
  request,
  action,
  api,
  onClose,
  onDone,
}: {
  language: Language;
  propertyId: string;
  form: SpendingForm;
  request: ExpenseRequest;
  action: RequestAction;
  api: SpendingApi;
  onClose: () => void;
  onDone: (text: string) => void;
}) {
  const work = useBusy(language);
  const [reason, setReason] = useState("");
  const [reasonError, setReasonError] = useState<string | null>(null);
  const [from, setFrom] = useState(
    pick(form.money_accounts, action === "payback" ? "1010" : "1030"),
  );
  const [amount, setAmount] = useState((request.amount_cents / 100).toFixed(2));
  const [amountError, setAmountError] = useState<string | null>(null);
  const [reference, setReference] = useState("");
  const forName = accountName(language, {
    name_en: request.account_name,
    name_km: request.account_name_km,
  });
  const who = request.requested_by_name ?? lt(language, "by_unknown");
  const said = lt(
    language,
    "er_ok_n",
    money(request.amount_cents),
    forName,
    who,
  );
  const advanced = request.status === "PAID_OUT" ? request.amount_cents : null;
  const spent = centsFromText(amount);

  let title = "";
  let label = "";
  let body: ReactNode = null;
  let send: (() => Promise<string>) | null = null;
  const after = async () => api.request(propertyId, request.request_number);

  if (action === "approve") {
    title = lt(language, "er_ok_t", request.request_number);
    label = lt(language, "er_approve");
    body = (
      <>
        <p>{said}</p>
        {request.kind === "URGENT_REPORT" && (
          <p className="ui-muted">
            <Icon name="info" small /> {lt(language, "er_ok_post")}
          </p>
        )}
      </>
    );
    send = async () => {
      await api.decide(propertyId, request.id, true, null);
      return lt(language, "er_ok_done", request.request_number);
    };
  } else if (action === "void") {
    title = lt(language, "er_void_t", request.request_number);
    label = lt(language, "er_void");
    body = (
      <>
        <p>{lt(language, "er_void_n")}</p>
        <div className="ui-field">
          <label htmlFor="ev-reason">
            {lt(language, "reason")}
            <span className="req">{lt(language, "required")}</span>
          </label>
          <input
            autoComplete="off"
            id="ev-reason"
            onChange={(event) => {
              setReason(event.target.value);
            }}
            value={reason}
          />
          <FieldError id="ev-reason-e" text={reasonError} />
        </div>
      </>
    );
    send = async () => {
      await api.voidRequest(propertyId, request.id, reason.trim());
      return lt(language, "er_void_done", request.request_number);
    };
  } else if (action === "advance") {
    title = lt(language, "er_give_t", request.request_number);
    label = lt(language, "er_give");
    body = (
      <>
        <p>{said}</p>
        <MoneyFrom
          accounts={form.money_accounts}
          id="eg-from"
          label={lt(language, "er_give_from")}
          language={language}
          onChange={setFrom}
          value={from}
        />
        <p className="ui-muted">
          <Icon name="clock" small />{" "}
          {lt(language, "er_give_n", String(form.report_days))}
        </p>
      </>
    );
    send = async () => {
      await api.giveAdvance(propertyId, request.id, from, form.today);
      const read = await after();
      return lt(language, "er_give_done", read.advance?.entry_number ?? "");
    };
  } else if (action === "bill") {
    title = lt(language, "er_bill_t", request.request_number);
    label = lt(language, "er_bill");
    const change = advanced === null || spent === null ? 0 : advanced - spent;
    body = (
      <>
        <p>
          {advanced === null
            ? `${lt(language, "er_from")}: ${paidFromText(language, request)}`
            : lt(language, "er_bill_adv", money(advanced))}
        </p>
        <div className="ui-row2">
          <AmountField
            error={amountError}
            help={
              change > 0
                ? lt(language, "er_s_change", money(change))
                : change < 0
                  ? lt(language, "er_s_extra", money(-change))
                  : ""
            }
            id="eb-amount"
            label={lt(language, "er_bill_amt")}
            language={language}
            onChange={setAmount}
            value={amount}
          />
          <div className="ui-field">
            <label htmlFor="eb-ref">{lt(language, "er_bill_ref")}</label>
            <input
              autoComplete="off"
              id="eb-ref"
              onChange={(event) => {
                setReference(event.target.value);
              }}
              value={reference}
            />
          </div>
        </div>
      </>
    );
    send = async () => {
      await api.recordBill(propertyId, request.id, {
        spent_cents: spent ?? 0,
        spent_on: form.today,
        bill_number: reference.trim() === "" ? null : reference.trim(),
        supplier_id: null,
        due_date: null,
      });
      const last = (await after()).expenses.at(-1);
      return lt(
        language,
        "er_bill_done",
        last?.expense_number ?? "",
        last?.entry_number ?? "",
      );
    };
  } else {
    title = lt(language, "er_back_t", who);
    label = lt(language, "er_payback");
    body = (
      <>
        <p>
          {lt(
            language,
            "er_owed_line",
            who,
            money(request.owed_to_staff_cents),
          )}{" "}
          · {request.request_number}
        </p>
        <MoneyFrom
          accounts={form.money_accounts}
          id="ep-from"
          label={lt(language, "er_back_from")}
          language={language}
          onChange={setFrom}
          value={from}
        />
      </>
    );
    send = async () => {
      await api.payBack(propertyId, request.id, from, form.today);
      const last = (await after()).paybacks.at(-1);
      return lt(language, "er_back_done", last?.entry_number ?? "");
    };
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (action === "void" && reason.trim() === "") {
      setReasonError(lt(language, "er_e_why"));
      return;
    }
    if (action === "bill" && spent === null) {
      setAmountError(lt(language, "er_e_amt"));
      return;
    }
    if (send === null) return;
    work.run(send, onDone);
  }

  return (
    <Dialog
      busy={work.busy}
      closeLabel={lt(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={label}
      title={title}
    >
      {body}
      <Failure text={work.failure} />
    </Dialog>
  );
}

/* ---------- Expenses ---------- */

function ExpensesTab({
  language,
  propertyId,
  active,
  rights,
  api,
}: {
  language: Language;
  propertyId: string;
  active: boolean;
  rights: Rights;
  api: SpendingApi;
}) {
  const readList = useCallback(
    () => api.expenses(propertyId),
    [api, propertyId],
  );
  const readForm = useCallback(() => api.form(propertyId), [api, propertyId]);
  const list = useRead<ExpenseRow[]>(active, readList);
  const form = useRead<SpendingForm>(active, readForm);
  const [open, setOpen] = useState(false);
  const [voiding, setVoiding] = useState<ExpenseRow | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const formData = form.data;
  const rows = list.data;
  return (
    <>
      <Done text={done} />
      <section aria-labelledby="ex-title" className="ui-card pad0">
        <div className="ui-head pad">
          <div>
            <h2 id="ex-title">{lt(language, "x_title")}</h2>
            <p>{lt(language, "x_sub")}</p>
          </div>
          {rights.pay && (
            <span className="ui-actions">
              <button
                className="ui-btn primary"
                disabled={formData === null}
                onClick={() => {
                  setDone(null);
                  setOpen(true);
                }}
                type="button"
              >
                <Icon name="plus" small />
                {lt(language, "x_new")}
              </button>
            </span>
          )}
        </div>
        {rows === null ? (
          <div className="pad">
            <Waiting
              failed={list.failed}
              language={language}
              onRetry={list.reload}
            />
          </div>
        ) : rows.length === 0 ? (
          <p className="ui-empty pad">{lt(language, "x_none")}</p>
        ) : (
          <div className="ui-tablewrap">
            <table className="ui-table">
              <thead>
                <tr>
                  <th scope="col">{lt(language, "no")}</th>
                  <th scope="col">{lt(language, "date")}</th>
                  <th scope="col">{lt(language, "x_sup")}</th>
                  <th scope="col">{lt(language, "x_for")}</th>
                  <th className="r" scope="col">
                    {lt(language, "amount")}
                  </th>
                  <th scope="col">{lt(language, "x_from")}</th>
                  <th scope="col">{lt(language, "col_status")}</th>
                  {rights.pay && <th scope="col">{lt(language, "x39_act")}</th>}
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, 80).map((row) => (
                  <tr key={row.id}>
                    <td>
                      {row.entry_number === null ? (
                        <span className="ui-num">{row.expense_number}</span>
                      ) : (
                        <a
                          className="ui-num"
                          href={hashForPage("journal", row.entry_number)}
                        >
                          {row.expense_number}
                        </a>
                      )}
                    </td>
                    <td className="ui-num">{dayText(row.expense_date)}</td>
                    <td>{row.supplier_name ?? "—"}</td>
                    <td>
                      {named(
                        language,
                        row.account_code,
                        row.account_name,
                        row.account_name_km,
                      )}
                      {row.unit_number !== null && (
                        <span className="ui-sub2">
                          <b>{lt(language, "er_unit")}</b> {row.unit_number}
                        </span>
                      )}
                      <span className="ui-sub2">
                        {row.bill_number ?? row.description}
                      </span>
                      {row.request_number !== null && (
                        <span className="ui-sub2">
                          {lt(language, "er_from_req")}{" "}
                          <a
                            className="ui-num"
                            href={hashForPage("exreqs", row.request_number)}
                          >
                            {row.request_number}
                          </a>
                        </span>
                      )}
                    </td>
                    <td className="r ui-num">{money(row.amount_cents)}</td>
                    <td>
                      {row.paid_from_code === null
                        ? lt(language, "x_later")
                        : named(
                            language,
                            row.paid_from_code,
                            row.paid_from_name,
                            row.paid_from_name_km,
                          )}
                    </td>
                    <td>
                      {row.status === "VOID" ? (
                        <>
                          <Chip tone="neutral">
                            {lt(language, "x_st_VOID")}
                          </Chip>
                          {row.void_reason !== null && (
                            <span className="ui-sub2">
                              {lt(
                                language,
                                "x39_void_s",
                                row.voided_by_name ?? "",
                                momentText(row.voided_at),
                                row.void_reason,
                              )}
                            </span>
                          )}
                        </>
                      ) : (
                        <Chip icon="check" tone="ok">
                          {lt(language, "x_st_POSTED")}
                        </Chip>
                      )}
                    </td>
                    {rights.pay && (
                      <td>
                        {row.status === "POSTED" &&
                          row.entry_number !== null &&
                          (row.bill_has_payments ? (
                            <span className="ui-muted">
                              {lt(
                                language,
                                "x39_paid_first",
                                row.supplier_bill_number ?? "",
                              )}
                            </span>
                          ) : (
                            <button
                              className="ui-btn"
                              onClick={() => {
                                setDone(null);
                                setVoiding(row);
                              }}
                              type="button"
                            >
                              <Icon name="x" small />
                              {lt(language, "x39_void")}
                            </button>
                          ))}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="ui-muted pad">
          <Icon name="info" small />{" "}
          {lt(language, "gl_x_limit", money(formData?.expense_limit_cents))}
        </p>
      </section>
      {voiding !== null && (
        <VoidExpenseDialog
          api={api}
          expense={voiding}
          language={language}
          onClose={() => {
            setVoiding(null);
          }}
          onDone={(text) => {
            setVoiding(null);
            setDone(text);
            list.reload();
          }}
          propertyId={propertyId}
        />
      )}
      {open && formData !== null && (
        <ExpenseDialog
          api={api}
          form={formData}
          language={language}
          onClose={() => {
            setOpen(false);
          }}
          onSaved={(text) => {
            setOpen(false);
            setDone(text);
            list.reload();
            form.reload();
          }}
          pay="now"
          propertyId={propertyId}
        />
      )}
    </>
  );
}

/** The lines of an entry, as "1020 · debit $10.00". */
function EntryLines({
  language,
  lines,
}: {
  language: Language;
  lines: readonly { code: string; debit: number; credit: number }[];
}) {
  return (
    <>
      <p>{lt(language, "ent39")}</p>
      <ul>
        {lines.map((line) => (
          <li key={`${line.code}-${String(line.debit)}`}>
            <span className="ui-num">{line.code}</span> ·{" "}
            {line.debit > 0
              ? lt(language, "wo_dr", money(line.debit))
              : lt(language, "wo_cr", money(line.credit))}
          </li>
        ))}
      </ul>
    </>
  );
}

/** Asks for a reason, then calls `send` with it (Void expense, Reverse payment). */
function ReasonField({
  language,
  value,
  error,
  onChange,
}: {
  language: Language;
  value: string;
  error: string | null;
  onChange: (value: string) => void;
}) {
  return (
    <div className="ui-field">
      <label htmlFor="rv-reason">
        {lt(language, "reason")}
        <span className="req">{lt(language, "required")}</span>
      </label>
      <input
        aria-describedby={error === null ? undefined : "rv-reason-e"}
        autoComplete="off"
        id="rv-reason"
        maxLength={160}
        onChange={(event) => {
          onChange(event.target.value);
        }}
        value={value}
      />
      <FieldError id="rv-reason-e" text={error} />
    </div>
  );
}

/** Void an Expense (mock-up v77): a reversing entry today; the row stays as Void. */
function VoidExpenseDialog({
  language,
  propertyId,
  expense,
  api,
  onClose,
  onDone,
}: {
  language: Language;
  propertyId: string;
  expense: ExpenseRow;
  api: SpendingApi;
  onClose: () => void;
  onDone: (text: string) => void;
}) {
  const work = useBusy(language);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const from = expense.paid_from_code ?? "2010";
  const fromText =
    expense.paid_from_code === null
      ? lt(language, "x_later")
      : named(
          language,
          expense.paid_from_code,
          expense.paid_from_name,
          expense.paid_from_name_km,
        );

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const why = reason.trim();
    if (why === "") {
      setError(lt(language, "br_e_reason"));
      return;
    }
    setError(null);
    work.run(async () => {
      await api.voidExpense(propertyId, expense.id, why);
      const row = (await api.expenses(propertyId)).find(
        (item) => item.id === expense.id,
      );
      return lt(
        language,
        "x39_void_done",
        expense.expense_number,
        row?.void_entry_number ?? "",
      );
    }, onDone);
  }

  return (
    <Dialog
      busy={work.busy}
      closeLabel={lt(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={lt(language, "x39_void")}
      title={lt(language, "x39_void_t", expense.expense_number)}
    >
      <p>
        {lt(
          language,
          "x39_void_b",
          expense.supplier_name ?? "—",
          money(expense.amount_cents),
          fromText,
        )}
      </p>
      <ReasonField
        error={error}
        language={language}
        onChange={setReason}
        value={reason}
      />
      <EntryLines
        language={language}
        lines={[
          { code: from, debit: expense.amount_cents, credit: 0 },
          {
            code: expense.account_code,
            debit: 0,
            credit: expense.amount_cents,
          },
        ]}
      />
      {expense.supplier_bill_number !== null && (
        <p>
          <Icon name="info" small />{" "}
          {lt(language, "x39_void_bill", expense.supplier_bill_number)}
        </p>
      )}
      <p className="ui-muted">
        <Icon name="info" small /> {lt(language, "x39_void_n")}
      </p>
      <Failure text={work.failure} />
    </Dialog>
  );
}

/** Reverse a bill payment (mock-up v77): DR the paid-from account, CR 2010. */
function ReversePaymentDialog({
  language,
  propertyId,
  bill,
  payment,
  api,
  onClose,
  onDone,
}: {
  language: Language;
  propertyId: string;
  bill: SupplierBill;
  payment: BillPayment;
  api: SpendingApi;
  onClose: () => void;
  onDone: (text: string) => void;
}) {
  const work = useBusy(language);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const why = reason.trim();
    if (why === "") {
      setError(lt(language, "br_e_reason"));
      return;
    }
    setError(null);
    work.run(async () => {
      await api.reverseBillPayment(propertyId, payment.id, why);
      const again = (await api.bills(propertyId))
        .find((item) => item.id === bill.id)
        ?.payments.find((item) => item.id === payment.id);
      return lt(
        language,
        "sb39_rev_done",
        bill.bill_number,
        again?.reversal_entry_number ?? "",
      );
    }, onDone);
  }

  return (
    <Dialog
      busy={work.busy}
      closeLabel={lt(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={lt(language, "sb39_rev")}
      title={lt(language, "sb39_rev_t", bill.bill_number)}
    >
      <p>
        {lt(
          language,
          "sb39_rev_b",
          money(payment.amount_cents),
          dayText(payment.paid_on),
          named(
            language,
            payment.paid_from_code,
            payment.paid_from_name,
            payment.paid_from_name_km,
          ),
          bill.supplier_name,
        )}
      </p>
      <ReasonField
        error={error}
        language={language}
        onChange={setReason}
        value={reason}
      />
      <EntryLines
        language={language}
        lines={[
          {
            code: payment.paid_from_code,
            debit: payment.amount_cents,
            credit: 0,
          },
          { code: "2010", debit: 0, credit: payment.amount_cents },
        ]}
      />
      <p className="ui-muted">
        <Icon name="info" small /> {lt(language, "sb39_rev_n")}
      </p>
      <Failure text={work.failure} />
    </Dialog>
  );
}

/** Record a bill (Expenses) or Add supplier bill (Supplier bills, paid later). */
function ExpenseDialog({
  language,
  propertyId,
  form,
  pay,
  api,
  onClose,
  onSaved,
}: {
  language: Language;
  propertyId: string;
  form: SpendingForm;
  pay: "now" | "later";
  api: SpendingApi;
  onClose: () => void;
  onSaved: (text: string) => void;
}) {
  const work = useBusy(language);
  const [day, setDay] = useState(form.today);
  const [due, setDue] = useState(addDays(form.today, form.bill_days));
  const [amount, setAmount] = useState("");
  const [supplier, setSupplier] = useState("");
  const accounts = form.accounts.filter((item) =>
    pay === "now"
      ? item.account_type !== "ASSET"
      : item.account_type !== "ASSET" ||
        item.code === "1200" ||
        item.code === "1300",
  );
  const [account, setAccount] = useState(pick(accounts, "6010"));
  const [from, setFrom] = useState(pick(form.money_accounts, "1020"));
  const [reference, setReference] = useState("");
  const [errors, setErrors] = useState<Record<string, string | null>>({});
  const cents = centsFromText(amount);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found: Record<string, string | null> = {};
    if (day === "") found.day = lt(language, "er_e_date");
    if (cents === null) found.amount = lt(language, "x_e_amt");
    if (supplier.trim() === "") found.supplier = lt(language, "x_e_sup");
    const later = pay === "later" || from === "LATER";
    if (later && (due === "" || due < day))
      found.due = lt(language, "sb_e_due");
    setErrors(found);
    if (Object.keys(found).length > 0 || cents === null) return;
    const chosen = accounts.find((item) => item.code === account);
    const description =
      reference.trim() !== ""
        ? reference.trim()
        : `${supplier.trim()} · ${chosen === undefined ? account : chosen.name_en}`;
    work.run(async () => {
      const supplierRef = await supplierId(api, propertyId, form, supplier);
      const made = await api.recordExpense(propertyId, {
        expense_date: day,
        account_code: account,
        description,
        amount_cents: cents,
        paid_from_code: later ? null : from,
        supplier_id: supplierRef,
        bill_number: reference.trim() === "" ? null : reference.trim(),
        due_date: later && pay === "later" ? due : null,
        unit_id: null,
      });
      const row = (await api.expenses(propertyId)).find(
        (item) => item.id === made,
      );
      return pay === "later"
        ? lt(
            language,
            "sb_saved",
            row?.supplier_bill_number ?? "",
            row?.entry_number ?? "",
          )
        : lt(
            language,
            "x_saved",
            row?.expense_number ?? "",
            row?.entry_number ?? "",
          );
    }, onSaved);
  }

  return (
    <Dialog
      busy={work.busy}
      closeLabel={lt(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={lt(language, "save")}
      title={lt(language, pay === "now" ? "x_new" : "sb_new")}
    >
      {pay === "later" && (
        <SupplierField
          error={errors.supplier ?? null}
          form={form}
          id="xp-sup"
          label={lt(language, "x_sup")}
          language={language}
          onChange={setSupplier}
          required
          value={supplier}
        />
      )}
      <div className="ui-row2">
        <div className="ui-field">
          <label htmlFor="xp-day">
            {lt(language, pay === "now" ? "date" : "sb_date")}
            <span className="req">{lt(language, "required")}</span>
          </label>
          <DateInput
            calendarLabel={lt(language, "date")}
            id="xp-day"
            language={language}
            onChange={(value) => {
              setDay(value);
              if (value !== "") setDue(addDays(value, form.bill_days));
            }}
            required
            value={day}
          />
          <FieldError id="xp-day-e" text={errors.day ?? null} />
        </div>
        {pay === "now" ? (
          <AmountField
            error={errors.amount ?? null}
            id="xp-amount"
            label={lt(language, "amount")}
            language={language}
            onChange={setAmount}
            value={amount}
          />
        ) : (
          <div className="ui-field">
            <label htmlFor="xp-due">
              {lt(language, "sb_due")}
              <span className="req">{lt(language, "required")}</span>
            </label>
            <DateInput
              calendarLabel={lt(language, "sb_due")}
              id="xp-due"
              language={language}
              onChange={setDue}
              required
              value={due}
            />
            <FieldError id="xp-due-e" text={errors.due ?? null} />
          </div>
        )}
      </div>
      {pay === "now" && (
        <SupplierField
          error={errors.supplier ?? null}
          form={form}
          id="xp-sup"
          label={lt(language, "x_sup")}
          language={language}
          onChange={setSupplier}
          required
          value={supplier}
        />
      )}
      <div className="ui-field">
        <label htmlFor="xp-for">{lt(language, "x_for")}</label>
        <select
          id="xp-for"
          onChange={(event) => {
            setAccount(event.target.value);
          }}
          value={account}
        >
          <optgroup label={lt(language, "t_expenses")}>
            {accounts
              .filter((item) => item.account_type !== "ASSET")
              .map((item) => (
                <option key={item.code} value={item.code}>
                  {item.code} · {accountName(language, item)}
                </option>
              ))}
          </optgroup>
          {pay === "later" && (
            <optgroup label={lt(language, "t_assets")}>
              {accounts
                .filter((item) => item.account_type === "ASSET")
                .map((item) => (
                  <option key={item.code} value={item.code}>
                    {item.code} · {accountName(language, item)}
                  </option>
                ))}
            </optgroup>
          )}
        </select>
      </div>
      {pay === "now" ? (
        <>
          <div className="ui-field">
            <label htmlFor="xp-from">{lt(language, "x_from")}</label>
            <select
              id="xp-from"
              onChange={(event) => {
                setFrom(event.target.value);
              }}
              value={from}
            >
              {form.money_accounts.map((item) => (
                <option key={item.code} value={item.code}>
                  {item.code} · {accountName(language, item)}
                </option>
              ))}
              <option value="LATER">{lt(language, "x_later")}</option>
            </select>
          </div>
          <div className="ui-field">
            <label htmlFor="xp-ref">{lt(language, "x_ref")}</label>
            <input
              autoComplete="off"
              id="xp-ref"
              onChange={(event) => {
                setReference(event.target.value);
              }}
              value={reference}
            />
          </div>
        </>
      ) : (
        <div className="ui-row2">
          <AmountField
            error={errors.amount ?? null}
            id="xp-amount"
            label={lt(language, "amount")}
            language={language}
            onChange={setAmount}
            value={amount}
          />
          <div className="ui-field">
            <label htmlFor="xp-ref">{lt(language, "sb_ref")}</label>
            <input
              autoComplete="off"
              id="xp-ref"
              onChange={(event) => {
                setReference(event.target.value);
              }}
              value={reference}
            />
          </div>
        </div>
      )}
      <p className="ui-muted">
        <Icon name="info" small />{" "}
        {pay === "now"
          ? lt(language, "x_sub").split(". ").slice(1, 3).join(". ") + "."
          : lt(language, "sb_new_n", money(form.asset_limit_cents))}
      </p>
      <Failure text={work.failure} />
    </Dialog>
  );
}

/* ---------- Supplier bills ---------- */

type BillFilter = "open" | "late" | "paid";

function BillsTab({
  language,
  propertyId,
  active,
  rights,
  api,
}: {
  language: Language;
  propertyId: string;
  active: boolean;
  rights: Rights;
  api: SpendingApi;
}) {
  const readList = useCallback(() => api.bills(propertyId), [api, propertyId]);
  const readForm = useCallback(() => api.form(propertyId), [api, propertyId]);
  const list = useRead<SupplierBill[]>(active, readList);
  const form = useRead<SpendingForm>(active, readForm);
  const [filter, setFilter] = useState<BillFilter>("open");
  const [adding, setAdding] = useState(false);
  const [paying, setPaying] = useState<SupplierBill | null>(null);
  const [reversing, setReversing] = useState<{
    bill: SupplierBill;
    payment: BillPayment;
  } | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const formData = form.data;
  const today = formData?.today ?? "";
  const rows = list.data;
  const lateDays = (bill: SupplierBill) =>
    today === "" ? 0 : daysBetween(bill.due_date, today);
  const header = (
    <div className="ui-head">
      <div>
        <h2 id="sb-title">{lt(language, "sb_t")}</h2>
        <p>{lt(language, "sb_sub")}</p>
      </div>
      {rights.pay && (
        <span className="ui-actions">
          <button
            className="ui-btn primary"
            disabled={formData === null}
            onClick={() => {
              setDone(null);
              setAdding(true);
            }}
            type="button"
          >
            <Icon name="plus" small />
            {lt(language, "sb_new")}
          </button>
        </span>
      )}
    </div>
  );
  const reloadAll = (text: string) => {
    setAdding(false);
    setPaying(null);
    setReversing(null);
    setDone(text);
    list.reload();
    form.reload();
  };
  const dialogs = (
    <>
      {adding && formData !== null && (
        <ExpenseDialog
          api={api}
          form={formData}
          language={language}
          onClose={() => {
            setAdding(false);
          }}
          onSaved={reloadAll}
          pay="later"
          propertyId={propertyId}
        />
      )}
      {reversing !== null && (
        <ReversePaymentDialog
          api={api}
          bill={reversing.bill}
          language={language}
          onClose={() => {
            setReversing(null);
          }}
          onDone={reloadAll}
          payment={reversing.payment}
          propertyId={propertyId}
        />
      )}
      {paying !== null && formData !== null && (
        <PayBillDialog
          api={api}
          bill={paying}
          form={formData}
          language={language}
          onClose={() => {
            setPaying(null);
          }}
          onPaid={reloadAll}
          propertyId={propertyId}
        />
      )}
    </>
  );
  if (rows === null) {
    return (
      <section aria-labelledby="sb-title" className="ui-card">
        {header}
        <Waiting
          failed={list.failed}
          language={language}
          onRetry={list.reload}
        />
      </section>
    );
  }
  const live = rows.filter((bill) => bill.status !== "VOID");
  const sets: Record<BillFilter, SupplierBill[]> = {
    open: live.filter((bill) => bill.still_to_pay_cents > 0),
    late: live.filter(
      (bill) => bill.still_to_pay_cents > 0 && lateDays(bill) > 0,
    ),
    paid: live.filter((bill) => bill.still_to_pay_cents <= 0),
  };
  const left = (items: SupplierBill[]) =>
    items.reduce((total, bill) => total + bill.still_to_pay_cents, 0);
  const shown = sets[filter]
    .slice()
    .sort((a, b) =>
      filter === "paid"
        ? b.bill_date.localeCompare(a.bill_date)
        : a.due_date.localeCompare(b.due_date),
    );
  const listTitle: Record<BillFilter, LedgerTextKey> = {
    open: "sb_l_open",
    late: "sb_l_late",
    paid: "sb_l_paid",
  };
  return (
    <>
      <Done text={done} />
      <section aria-labelledby="sb-title" className="ui-card">
        {header}
        <div className="ui-kpis">
          <CountCard
            icon="invoice"
            label={lt(language, "sb_c_open")}
            note={lt(language, "sb_c_n", String(sets.open.length))}
            onPress={() => {
              setFilter("open");
            }}
            pressed={filter === "open"}
            tone="warn"
            value={sets.open.length}
            valueText={money(left(sets.open))}
          />
          <CountCard
            icon="alert"
            label={lt(language, "sb_c_late")}
            note={lt(language, "sb_c_n", String(sets.late.length))}
            onPress={() => {
              setFilter(filter === "late" ? "open" : "late");
            }}
            pressed={filter === "late"}
            tone="err"
            value={sets.late.length}
            valueText={money(left(sets.late))}
          />
          <CountCard
            icon="check"
            label={lt(language, "sb_c_paid")}
            note={lt(language, "sb_c_paid_s")}
            onPress={() => {
              setFilter(filter === "paid" ? "open" : "paid");
            }}
            pressed={filter === "paid"}
            tone="ok"
            value={sets.paid.length}
          />
        </div>
      </section>
      <section aria-labelledby="sb-list" className="ui-card pad0">
        <h2 className="pad" id="sb-list">
          {lt(language, listTitle[filter])}{" "}
          <span className="ui-count ui-num">{shown.length}</span>
        </h2>
        {shown.length === 0 ? (
          <p className="ui-empty pad">{lt(language, "sb_none")}</p>
        ) : (
          <div className="ui-tablewrap">
            <table className="ui-table">
              <thead>
                <tr>
                  <th scope="col">{lt(language, "no")}</th>
                  <th scope="col">{lt(language, "x_sup")}</th>
                  <th scope="col">{lt(language, "sb_due")}</th>
                  <th className="r" scope="col">
                    {lt(language, "amount")}
                  </th>
                  <th className="r" scope="col">
                    {lt(language, "sb_left")}
                  </th>
                  <th scope="col">{lt(language, "col_status")}</th>
                  <th scope="col">
                    <span className="ui-sr">{lt(language, "sb_pay")}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {shown.map((bill) => {
                  const late = lateDays(bill);
                  const unpaid = bill.still_to_pay_cents > 0;
                  return (
                    <tr key={bill.id}>
                      <td>
                        <span className="ui-num">{bill.bill_number}</span>
                        <span className="ui-sub2 ui-num">
                          {dayText(bill.bill_date)}
                        </span>
                      </td>
                      <td>
                        {bill.supplier_name}
                        {bill.account_name !== null && (
                          <span className="ui-sub2">
                            {accountName(language, {
                              name_en: bill.account_name,
                              name_km: bill.account_name_km,
                            })}
                          </span>
                        )}
                        {bill.supplier_reference !== null && (
                          <span className="ui-sub2">
                            {bill.supplier_reference}
                          </span>
                        )}
                        {bill.entry_number !== null && (
                          <span className="ui-sub2">
                            <a
                              className="ui-num"
                              href={hashForPage("journal", bill.entry_number)}
                            >
                              {lt(language, "er_s_entry", bill.entry_number)}
                            </a>
                          </span>
                        )}
                        {bill.payments.map((payment) => {
                          const paidText = lt(
                            language,
                            "sb39_paid",
                            money(payment.amount_cents),
                            dayText(payment.paid_on),
                            named(
                              language,
                              payment.paid_from_code,
                              payment.paid_from_name,
                              payment.paid_from_name_km,
                            ),
                          );
                          const entry = payment.reversed
                            ? payment.reversal_entry_number
                            : payment.entry_number;
                          return (
                            <span className="ui-sub2" key={payment.id}>
                              {payment.reversed ? (
                                <>
                                  <s>{paidText}</s> ·{" "}
                                  {lt(
                                    language,
                                    "sb39_reved",
                                    payment.reversed_by_name ?? "",
                                    momentText(payment.reversed_at),
                                    payment.reversal_reason ?? "",
                                  )}
                                </>
                              ) : (
                                paidText
                              )}
                              {entry !== null && (
                                <>
                                  {" · "}
                                  <a
                                    className="ui-num"
                                    href={hashForPage("journal", entry)}
                                  >
                                    {entry}
                                  </a>
                                </>
                              )}
                              {!payment.reversed && rights.pay && (
                                <>
                                  {" "}
                                  <button
                                    className="ui-btn"
                                    onClick={() => {
                                      setDone(null);
                                      setReversing({ bill, payment });
                                    }}
                                    type="button"
                                  >
                                    <Icon name="swap" small />
                                    {lt(language, "sb39_rev")}
                                  </button>
                                </>
                              )}
                            </span>
                          );
                        })}
                      </td>
                      <td className="ui-num">{dayText(bill.due_date)}</td>
                      <td className="r ui-num">{money(bill.amount_cents)}</td>
                      <td className="r ui-num">
                        {money(Math.max(bill.still_to_pay_cents, 0))}
                      </td>
                      <td>
                        {!unpaid ? (
                          <Chip icon="check" tone="ok">
                            {lt(language, "sb_st_paid")}
                          </Chip>
                        ) : late > 0 ? (
                          <Chip icon="alert" tone="err">
                            {lt(language, "sb_st_late", String(late))}
                          </Chip>
                        ) : (
                          <Chip icon="clock" tone="info">
                            {lt(language, "sb_st_open")}
                          </Chip>
                        )}
                      </td>
                      <td>
                        {unpaid && rights.pay && (
                          <button
                            className="ui-btn"
                            disabled={formData === null}
                            onClick={() => {
                              setDone(null);
                              setPaying(bill);
                            }}
                            type="button"
                          >
                            <Icon name="payments" small />
                            {lt(language, "sb_pay")}
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
          <Icon name="info" small /> {lt(language, "sb_note")}
        </p>
      </section>
      {dialogs}
    </>
  );
}

function PayBillDialog({
  language,
  propertyId,
  form,
  bill,
  api,
  onClose,
  onPaid,
}: {
  language: Language;
  propertyId: string;
  form: SpendingForm;
  bill: SupplierBill;
  api: SpendingApi;
  onClose: () => void;
  onPaid: (text: string) => void;
}) {
  const work = useBusy(language);
  const [day, setDay] = useState(form.today);
  const [amount, setAmount] = useState(
    (bill.still_to_pay_cents / 100).toFixed(2),
  );
  const [from, setFrom] = useState(pick(form.money_accounts, "1020"));
  const [error, setError] = useState<string | null>(null);
  const cents = centsFromText(amount);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (cents === null || cents <= 0) {
      setError(lt(language, "x_e_amt"));
      return;
    }
    if (cents > bill.still_to_pay_cents) {
      setError(lt(language, "sb_e_more", money(bill.still_to_pay_cents)));
      return;
    }
    if (day === "") return;
    setError(null);
    work.run(async () => {
      const made = await api.payBill(propertyId, bill.id, {
        from_code: from,
        paid_on: day,
        amount_cents: cents,
      });
      const paid = (await api.bills(propertyId))
        .find((item) => item.id === bill.id)
        ?.payments.find((payment) => payment.id === made);
      return lt(
        language,
        "sb_paid",
        bill.bill_number,
        paid?.entry_number ?? "",
      );
    }, onPaid);
  }

  return (
    <Dialog
      busy={work.busy}
      closeLabel={lt(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={lt(language, "sb_pay")}
      title={lt(language, "sb_pay_t", bill.bill_number)}
    >
      <p>
        {bill.supplier_name} · {lt(language, "sb_left")}{" "}
        {money(bill.still_to_pay_cents)}
      </p>
      <div className="ui-row2">
        <div className="ui-field">
          <label htmlFor="sp-day">
            {lt(language, "date")}
            <span className="req">{lt(language, "required")}</span>
          </label>
          <DateInput
            calendarLabel={lt(language, "date")}
            id="sp-day"
            language={language}
            onChange={setDay}
            required
            value={day}
          />
        </div>
        <AmountField
          error={error}
          id="sp-amount"
          label={lt(language, "amount")}
          language={language}
          onChange={setAmount}
          value={amount}
        />
      </div>
      <MoneyFrom
        accounts={form.money_accounts}
        id="sp-from"
        label={lt(language, "x_from")}
        language={language}
        onChange={setFrom}
        value={from}
      />
      <Failure text={work.failure} />
    </Dialog>
  );
}
