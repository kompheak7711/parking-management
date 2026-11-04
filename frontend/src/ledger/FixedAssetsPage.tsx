// General Ledger phase 6 step 6 part 4 (mock-up v76, app26 vFassets): Office › Ledger tab Fixed
// assets. Items of the Asset limit or more; the app makes the depreciation entry at the end of
// each month. Adding an item records an Expense on an asset account (expenses.record): the
// server adds it to the register with the years from Business rules. Other years are set after
// with ledger.fixed_assets. The server checks everything again.

import "../shell/screens.css";

import { type FormEvent, useCallback, useState } from "react";

import { centsFromText } from "../products/productsClient";
import { DateInput } from "../shell/DateInput";
import { dayText } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { Chip, Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import {
  type AssetRegister,
  type AssetsApi,
  assetsApi as defaultAssetsApi,
} from "./assetsClient";
import { accountName, money, useRead, Waiting } from "./LedgerPage";
import {
  type SpendingApi,
  type SpendingForm,
  spendingApi as defaultSpendingApi,
} from "./spendingClient";
import {
  addDays,
  AmountField,
  Done,
  Failure,
  FieldError,
  pick,
  SupplierField,
  supplierId,
  useBusy,
} from "./SpendingPage";
import { lt, monthLabel } from "./text";

export interface FixedAssetsPageProps {
  language: Language;
  propertyId: string;
  active: boolean;
  capabilities: ReadonlySet<string> | null;
  api?: AssetsApi;
  spendingApi?: SpendingApi;
}

const ASSET_ACCOUNTS = ["1520", "1530", "1510"] as const;
const PAID_FROM = ["1020", "1010", "1030"] as const;
const LATER = "LATER";

/** The last day of the month after the one of `day`: the first depreciation entry. */
function firstDepreciation(day: string): string {
  const [year = 0, month = 1] = day.split("-").map(Number);
  return new Date(Date.UTC(year, month + 1, 0)).toISOString().slice(0, 10);
}

export function FixedAssetsPage({
  language,
  propertyId,
  active,
  capabilities,
  api = defaultAssetsApi,
  spendingApi = defaultSpendingApi,
}: FixedAssetsPageProps) {
  const may = (capability: string) =>
    capabilities === null || capabilities.has(capability);
  const canAdd = may("expenses.record");
  const read = useCallback(() => api.read(propertyId), [api, propertyId]);
  const answer = useRead<AssetRegister>(active && propertyId !== "", read);
  const readForm = useCallback(
    () => spendingApi.form(propertyId),
    [spendingApi, propertyId],
  );
  const form = useRead<SpendingForm>(
    active && canAdd && propertyId !== "",
    readForm,
  );
  const [open, setOpen] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  if (propertyId === "") {
    return (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>{lt(language, "no_property")}</p>
      </div>
    );
  }
  const data = answer.data;
  return (
    <>
      <Done text={done} />
      <section aria-labelledby="fa-title" className="ui-card">
        <div className="ui-head">
          <div>
            <h2 id="fa-title">{lt(language, "fa_t")}</h2>
            <p>{lt(language, "fa_sub")}</p>
          </div>
          {canAdd && (
            <button
              className="ui-btn primary"
              disabled={form.data === null || data === null}
              onClick={() => {
                setDone(null);
                setOpen(true);
              }}
              type="button"
            >
              <Icon name="plus" small />
              {lt(language, "fa_new")}
            </button>
          )}
        </div>
      </section>
      {data === null ? (
        <Waiting
          failed={answer.failed}
          language={language}
          onRetry={answer.reload}
        />
      ) : (
        <Register data={data} language={language} />
      )}
      {open && data !== null && form.data !== null && (
        <AddAssetDialog
          api={api}
          canSetYears={may("ledger.fixed_assets")}
          data={data}
          form={form.data}
          language={language}
          onClose={() => {
            setOpen(false);
          }}
          onSaved={(text) => {
            setOpen(false);
            setDone(text);
            answer.reload();
            form.reload();
          }}
          propertyId={propertyId}
          spendingApi={spendingApi}
        />
      )}
    </>
  );
}

function Register({
  language,
  data,
}: {
  language: Language;
  data: AssetRegister;
}) {
  const items = data.assets.filter((item) => item.status !== "VOID");
  const cost = items.reduce((sum, item) => sum + item.cost_cents, 0);
  const soFar = items.reduce((sum, item) => sum + item.depreciation_cents, 0);
  const matches = soFar === data.accumulated_cents;
  const last = data.last_depreciation;
  return (
    <section aria-labelledby="fa-list" className="ui-card">
      <h2 id="fa-list">
        {lt(language, "fa_list")}{" "}
        <span className="ui-count ui-num">{items.length}</span>
      </h2>
      {items.length === 0 ? (
        <p className="ui-muted">{lt(language, "fa_none")}</p>
      ) : (
        <div className="ui-tablewrap">
          <table className="ui-table">
            <thead>
              <tr>
                <th scope="col">{lt(language, "no")}</th>
                <th scope="col">{lt(language, "fa_item")}</th>
                <th className="r" scope="col">
                  {lt(language, "fa_cost")}
                </th>
                <th className="r" scope="col">
                  {lt(language, "fa_life")}
                </th>
                <th className="r" scope="col">
                  {lt(language, "fa_mon")}
                </th>
                <th className="r" scope="col">
                  {lt(language, "fa_sofar")}
                </th>
                <th className="r" scope="col">
                  {lt(language, "fa_now")}
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td>
                    <span className="ui-num">{item.asset_number}</span>
                    <span className="ui-sub2 ui-num">
                      {dayText(item.bought_on)}
                    </span>
                  </td>
                  <td>
                    {item.item}
                    {item.unit_number !== null && (
                      <span className="ui-sub2">
                        <b>{lt(language, "er_unit")}</b> {item.unit_number}
                      </span>
                    )}
                    <span className="ui-sub2">
                      {item.account_code} ·{" "}
                      {accountName(language, {
                        name_en: item.account_name,
                        name_km: item.account_name_km,
                      })}
                    </span>
                    {item.request_number !== null && (
                      <span className="ui-sub2">
                        {lt(language, "er_from_req")}{" "}
                        <a
                          className="ui-num"
                          href={hashForPage("exreqs", item.request_number)}
                        >
                          {item.request_number}
                        </a>
                      </span>
                    )}
                  </td>
                  <td className="r ui-num">{money(item.cost_cents)}</td>
                  <td className="r">
                    {item.useful_life_years === null
                      ? lt(language, "fa_land")
                      : lt(
                          language,
                          "fa_years",
                          String(item.useful_life_years),
                        )}
                  </td>
                  <td className="r ui-num">{money(item.monthly_cents)}</td>
                  <td className="r ui-num">{money(item.depreciation_cents)}</td>
                  <td className="r ui-num">{money(item.value_cents)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th colSpan={2} scope="row">
                  {lt(language, "total")}
                </th>
                <td className="r ui-num">{money(cost)}</td>
                <td />
                <td />
                <td className="r ui-num">{money(soFar)}</td>
                <td className="r ui-num">{money(cost - soFar)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
      <p>
        {matches ? (
          <Chip icon="check" tone="ok">
            {lt(language, "ok")}
          </Chip>
        ) : (
          <Chip icon="alert" tone="err">
            {lt(language, "bad")}
          </Chip>
        )}{" "}
        {lt(language, "fa_check", money(data.accumulated_cents))}
      </p>
      <p className="ui-muted">
        <Icon name="info" small />{" "}
        {lt(language, "fa_note", money(data.asset_limit_cents ?? 0))}
        {last !== null && (
          <>
            {" "}
            <EntryLink
              language={language}
              month={monthLabel(language, last.entry_date)}
              number={last.entry_number}
            />
          </>
        )}
      </p>
    </section>
  );
}

/** "Last depreciation entry: October 2026, JE…." with the entry as a link. */
function EntryLink({
  language,
  month,
  number,
}: {
  language: Language;
  month: string;
  number: string;
}) {
  const [before = "", after = ""] = lt(
    language,
    "fa_last",
    month,
    "\u0000",
  ).split("\u0000");
  return (
    <>
      {before}
      <a className="ui-num" href={hashForPage("journal", number)}>
        {number}
      </a>
      {after}
    </>
  );
}

function AddAssetDialog({
  language,
  propertyId,
  data,
  form,
  canSetYears,
  api,
  spendingApi,
  onClose,
  onSaved,
}: {
  language: Language;
  propertyId: string;
  data: AssetRegister;
  form: SpendingForm;
  canSetYears: boolean;
  api: AssetsApi;
  spendingApi: SpendingApi;
  onClose: () => void;
  onSaved: (text: string) => void;
}) {
  const work = useBusy(language);
  const limit = data.asset_limit_cents ?? form.asset_limit_cents ?? 0;
  const accounts = ASSET_ACCOUNTS.map((code) =>
    form.accounts.find((item) => item.code === code),
  ).filter((item) => item !== undefined);
  const payFrom = PAID_FROM.map((code) =>
    form.money_accounts.find((item) => item.code === code),
  ).filter((item) => item !== undefined);
  const ruleYears = (code: string) => data.years[code] ?? null;
  const [item, setItem] = useState("");
  const [account, setAccount] = useState(pick(accounts, "1520"));
  const [unit, setUnit] = useState("");
  const [day, setDay] = useState(form.today);
  const [cost, setCost] = useState("");
  const [years, setYears] = useState(String(ruleYears(account) ?? ""));
  const [from, setFrom] = useState(pick(payFrom, "1020"));
  const [supplier, setSupplier] = useState("");
  const [errors, setErrors] = useState<Record<string, string | null>>({});
  const cents = centsFromText(cost);
  const wholeYears = /^\d+$/.test(years.trim()) ? Number(years.trim()) : null;
  const later = from === LATER;
  const hint =
    cents !== null && wholeYears !== null && wholeYears > 0 && day !== ""
      ? lt(
          language,
          "fa_new_m",
          money(Math.floor(cents / (wholeYears * 12))),
          dayText(firstDepreciation(day)),
        )
      : lt(language, "fa_new_n", money(limit));

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found: Record<string, string | null> = {};
    if (item.trim() === "") found.item = lt(language, "fa_e_name");
    if (day === "") found.day = lt(language, "er_e_date");
    if (cents === null) found.cost = lt(language, "x_e_amt");
    else if (cents < limit)
      found.cost = lt(language, "fa_e_small", money(limit));
    if (wholeYears === null || wholeYears < 1 || wholeYears > 50)
      found.years = lt(language, "fa_e_life");
    if (later && supplier.trim() === "")
      found.supplier = lt(language, "x_e_sup");
    setErrors(found);
    if (Object.keys(found).length > 0 || cents === null || wholeYears === null)
      return;
    const name = item.trim();
    work.run(async () => {
      const supplierRef = later
        ? await supplierId(spendingApi, propertyId, form, supplier)
        : null;
      const made = await spendingApi.recordExpense(propertyId, {
        expense_date: day,
        account_code: account,
        description: name,
        amount_cents: cents,
        paid_from_code: later ? null : from,
        supplier_id: supplierRef,
        bill_number: null,
        due_date: later ? addDays(day, form.bill_days) : null,
        unit_id: unit === "" ? null : unit,
      });
      const register = await api.read(propertyId);
      const added = register.assets.find((row) => row.expense_id === made);
      if (added !== undefined && added.useful_life_years !== wholeYears) {
        await api.changeLife(
          propertyId,
          added.id,
          wholeYears,
          lt(language, "fa_life_why"),
        );
      }
      const row = (await spendingApi.expenses(propertyId)).find(
        (expense) => expense.id === made,
      );
      return lt(
        language,
        "fa_saved",
        added?.asset_number ?? "",
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
      title={lt(language, "fa_new")}
    >
      <div className="ui-field">
        <label htmlFor="fa-n">
          {lt(language, "fa_item")}
          <span className="req">{lt(language, "required")}</span>
        </label>
        <input
          aria-describedby={errors.item ? "fa-n-e" : undefined}
          autoComplete="off"
          id="fa-n"
          onChange={(event) => {
            setItem(event.target.value);
          }}
          value={item}
        />
        <FieldError id="fa-n-e" text={errors.item ?? null} />
      </div>
      <div className="ui-row2">
        <div className="ui-field">
          <label htmlFor="fa-acc">{lt(language, "account")}</label>
          <select
            id="fa-acc"
            onChange={(event) => {
              const code = event.target.value;
              if (years === String(ruleYears(account) ?? "")) {
                setYears(String(ruleYears(code) ?? ""));
              }
              setAccount(code);
            }}
            value={account}
          >
            {accounts.map((choice) => (
              <option key={choice.code} value={choice.code}>
                {choice.code} · {accountName(language, choice)}
              </option>
            ))}
          </select>
        </div>
        <div className="ui-field">
          <label htmlFor="fa-u">{lt(language, "er_unit")}</label>
          <select
            id="fa-u"
            onChange={(event) => {
              setUnit(event.target.value);
            }}
            value={unit}
          >
            <option value="">{lt(language, "er_unit_none")}</option>
            {form.units.map((choice) => (
              <option key={choice.id} value={choice.id}>
                {choice.unit_number}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="ui-row2">
        <div className="ui-field">
          <label htmlFor="fa-d">
            {lt(language, "fa_date")}
            <span className="req">{lt(language, "required")}</span>
          </label>
          <DateInput
            calendarLabel={lt(language, "fa_date")}
            id="fa-d"
            language={language}
            onChange={setDay}
            required
            value={day}
          />
          <FieldError id="fa-d-e" text={errors.day ?? null} />
        </div>
        <AmountField
          error={errors.cost ?? null}
          id="fa-c"
          label={lt(language, "fa_cost")}
          language={language}
          onChange={setCost}
          value={cost}
        />
      </div>
      <div className="ui-row2">
        <div className="ui-field">
          <label htmlFor="fa-y">
            {lt(language, "fa_life")}
            <span className="req">{lt(language, "required")}</span>
          </label>
          <input
            aria-describedby={errors.years ? "fa-y-e" : undefined}
            autoComplete="off"
            className="short ui-num"
            disabled={!canSetYears}
            id="fa-y"
            inputMode="numeric"
            onChange={(event) => {
              setYears(event.target.value);
            }}
            value={years}
          />
          <FieldError id="fa-y-e" text={errors.years ?? null} />
        </div>
        <div className="ui-field">
          <label htmlFor="fa-from">{lt(language, "x_from")}</label>
          <select
            id="fa-from"
            onChange={(event) => {
              setFrom(event.target.value);
            }}
            value={from}
          >
            {payFrom.map((choice) => (
              <option key={choice.code} value={choice.code}>
                {choice.code} · {accountName(language, choice)}
              </option>
            ))}
            <option value={LATER}>{lt(language, "x_later")}</option>
          </select>
        </div>
      </div>
      {later && (
        <SupplierField
          error={errors.supplier ?? null}
          form={form}
          id="fa-sup"
          label={lt(language, "x_sup")}
          language={language}
          onChange={setSupplier}
          required
          value={supplier}
        />
      )}
      <p aria-live="polite" className="ui-muted">
        {hint}
      </p>
      <Failure text={work.failure} />
    </Dialog>
  );
}
