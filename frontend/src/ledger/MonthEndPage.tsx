// General Ledger phase 6 step 6 part 4 (mock-up v76, app22 and app26): Office › Ledger tab
// Month-end close. The app checks each line itself; a month closes only when every line is
// green, in order and after its last day (ledger.close). After December the year is closed and
// its profit moves to 3900. The server checks everything again.

import "../shell/screens.css";

import { type ReactNode, useCallback, useState } from "react";

import { dayText, momentText } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage, type PageId } from "../shell/navigation";
import { Chip, Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import { accountName, money, useRead, Waiting } from "./LedgerPage";
import {
  type CloseCheck,
  type LedgerMonth,
  type LedgerYear,
  type MonthEnd,
  type MonthEndApi,
  monthEndApi as defaultMonthEndApi,
} from "./monthEndClient";
import { Done, Failure, useBusy } from "./SpendingPage";
import { type LedgerTextKey, lt, monthLabel } from "./text";
import { PageHead } from "../shell/pageHead";

export interface MonthEndPageProps {
  language: Language;
  propertyId: string;
  active: boolean;
  capabilities: ReadonlySet<string> | null;
  api?: MonthEndApi;
}

interface Line {
  title: LedgerTextKey;
  detail: ReactNode;
  go: PageId | null;
}

function EntryText({
  language,
  number,
}: {
  language: Language;
  number: string;
}) {
  return (
    <>
      {lt(language, "er_s_entry", "")}
      <a className="ui-num" href={hashForPage("journal", number)}>
        {number}
      </a>
    </>
  );
}

function lineOf(language: Language, data: MonthEnd, check: CloseCheck): Line {
  const end = dayText(data.month?.ends_on ?? null);
  const n = String(check.open_items);
  switch (check.code) {
    case "BOOKS_CHECK":
      return {
        title: "cl_books",
        detail: lt(language, "cl_books_d"),
        go: "statements",
      };
    case "NOTHING_WAITING":
      return {
        title: "cl_wait",
        detail: lt(language, check.ok ? "cl_wait_0" : "cl_wait_n", n),
        go: "exreqs",
      };
    case "NO_LATE_ADVANCE":
      return {
        title: "cl_late",
        detail: lt(language, check.ok ? "cl_late_0" : "cl_late_n", n),
        go: "exreqs",
      };
    case "BANK_MATCHED":
      return {
        title: "cl_bank",
        detail: lt(language, check.ok ? "cl_done_n" : "cl_bank_n", end),
        go: "bankcash",
      };
    case "CASH_COUNTED":
      return {
        title: "cl_cash",
        detail: lt(language, check.ok ? "cl_done_n" : "cl_cash_n", end),
        go: "bankcash",
      };
    case "DEPRECIATION_DONE":
      return {
        title: "cl_dep",
        detail: !check.ok ? (
          lt(language, "cl_dep_n")
        ) : data.depreciation_entry !== null ? (
          <EntryText language={language} number={data.depreciation_entry} />
        ) : (
          lt(language, "cl_dep_0")
        ),
        go: "fassets",
      };
    case "RIEL_VALUED":
      return {
        title: "cl_fx",
        detail: !check.ok ? (
          lt(language, "cl_fx_n", end)
        ) : data.riel?.entry_number !== null &&
          data.riel?.entry_number !== undefined ? (
          <EntryText language={language} number={data.riel.entry_number} />
        ) : (
          lt(language, "cl_fx_0")
        ),
        go: "bankcash",
      };
    case "PAYROLL_APPROVED":
      return { title: "cl_pay", detail: lt(language, "cl_pay_none"), go: null };
    default:
      return { title: "cl_books", detail: check.code, go: null };
  }
}

export function MonthEndPage({
  language,
  propertyId,
  active,
  capabilities,
  api = defaultMonthEndApi,
}: MonthEndPageProps) {
  const canClose = capabilities === null || capabilities.has("ledger.close");
  const read = useCallback(() => api.read(propertyId, null), [api, propertyId]);
  const answer = useRead<MonthEnd>(active && propertyId !== "", read);
  const [done, setDone] = useState<string | null>(null);
  const [closing, setClosing] = useState<LedgerMonth | null>(null);
  const [year, setYear] = useState<LedgerYear | null>(null);
  if (propertyId === "") {
    return (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>{lt(language, "no_property")}</p>
      </div>
    );
  }
  const data = answer.data;
  const finished = (text: string) => {
    setClosing(null);
    setYear(null);
    setDone(text);
    answer.reload();
  };
  return (
    <>
      <Done text={done} />
      <section aria-labelledby="cl-title" className="ui-card">
        <PageHead>
          <div>
            <h2 id="cl-title">{lt(language, "gl_c_t")}</h2>
            <p>{lt(language, "cl_head")}</p>
          </div>
        </PageHead>
      </section>
      {data === null ? (
        <Waiting
          failed={answer.failed}
          language={language}
          onRetry={answer.reload}
        />
      ) : (
        <>
          <NextMonth
            canClose={canClose}
            data={data}
            language={language}
            onClose={(month) => {
              setDone(null);
              setClosing(month);
            }}
          />
          <RielAtMonthEnd data={data} language={language} />
          <MonthsTable data={data} language={language} />
          <YearsTable
            canClose={canClose}
            data={data}
            language={language}
            onClose={(item) => {
              setDone(null);
              setYear(item);
            }}
          />
          {closing !== null && (
            <CloseMonthDialog
              api={api}
              language={language}
              month={closing}
              onClose={() => {
                setClosing(null);
              }}
              onDone={finished}
              propertyId={propertyId}
            />
          )}
          {year !== null && (
            <CloseYearDialog
              api={api}
              language={language}
              onClose={() => {
                setYear(null);
              }}
              onDone={finished}
              propertyId={propertyId}
              year={year}
            />
          )}
        </>
      )}
    </>
  );
}

function NextMonth({
  language,
  data,
  canClose,
  onClose,
}: {
  language: Language;
  data: MonthEnd;
  canClose: boolean;
  onClose: (month: LedgerMonth) => void;
}) {
  const month = data.month;
  if (month === null) {
    const now = data.months.find(
      (item) => item.starts_on <= data.today && data.today <= item.ends_on,
    );
    return (
      <section className="ui-card">
        <p>
          {now === undefined
            ? lt(language, "cl_none_yet")
            : lt(
                language,
                "cl_none",
                monthLabel(language, now.starts_on),
                dayText(now.ends_on),
              )}
        </p>
      </section>
    );
  }
  const lines = data.checks.map((check) => ({
    check,
    line: lineOf(language, data, check),
  }));
  const bad = data.checks.filter((check) => !check.ok).length;
  const name = monthLabel(language, month.starts_on);
  return (
    <section aria-labelledby="cl-next" className="ui-card">
      <div className="ui-head">
        <h2 id="cl-next">{lt(language, "cl_next", name)}</h2>
        {bad > 0 ? (
          <Chip icon="alert" tone="err">
            {lt(language, "cl_bad_n", String(bad))}
          </Chip>
        ) : (
          <Chip icon="check" tone="ok">
            {lt(language, "cl_all_ok")}
          </Chip>
        )}
      </div>
      <p className="ui-muted">{lt(language, "cl_sub")}</p>
      <div className="ui-tablewrap">
        <table className="ui-table">
          <tbody>
            {lines.map(({ check, line }) => (
              <tr key={check.code}>
                <td>
                  {check.ok ? (
                    <Chip icon="check" tone="ok">
                      {lt(language, "cl_ok")}
                    </Chip>
                  ) : (
                    <Chip icon="alert" tone="err">
                      {lt(language, "cl_bad")}
                    </Chip>
                  )}
                </td>
                <td>
                  <b>{lt(language, line.title)}</b>
                  <span className="ui-sub2">{line.detail}</span>
                </td>
                <td className="r">
                  {!check.ok && line.go !== null && (
                    <a className="ui-btn" href={hashForPage(line.go)}>
                      {lt(language, "cl_fix")}
                    </a>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {canClose ? (
        <>
          <button
            className="ui-btn primary"
            disabled={bad > 0}
            onClick={() => {
              onClose(month);
            }}
            type="button"
          >
            <Icon name="lock" small />
            {lt(language, "cl_btn", name)}
          </button>
          {bad > 0 && <p className="ui-muted">{lt(language, "cl_btn_n")}</p>}
        </>
      ) : (
        <p className="ui-muted">{lt(language, "cl_owner")}</p>
      )}
    </section>
  );
}

/** Each riel account's valuation in the chosen month (owner 05/11/2026: month end shows riel). */
function RielAtMonthEnd({
  language,
  data,
}: {
  language: Language;
  data: MonthEnd;
}) {
  if (data.month === null || data.riel_accounts.length === 0) return null;
  return (
    <section aria-labelledby="cl-riel" className="ui-card pad0">
      <header className="ui-chead pad">
        <h2 id="cl-riel">
          {lt(language, "cl_rt")} · {dayText(data.month.ends_on)}
        </h2>
      </header>
      <p className="ui-muted pad">{lt(language, "cl_rs")}</p>
      <div className="ui-tablewrap">
        <table className="ui-table">
          <thead>
            <tr>
              <th scope="col">{lt(language, "account")}</th>
              <th className="r" scope="col">
                {lt(language, "cl_rheld")}
              </th>
              <th className="r" scope="col">
                {lt(language, "cl_rrate")}
              </th>
              <th className="r" scope="col">
                {lt(language, "cl_rbefore")}
              </th>
              <th className="r" scope="col">
                {lt(language, "cl_rafter")}
              </th>
              <th className="r" scope="col">
                {lt(language, "cl_rgain")}
              </th>
            </tr>
          </thead>
          <tbody>
            {data.riel_accounts.map((item) => (
              <tr key={item.code}>
                <td>
                  <span className="ui-num">{item.code}</span> ·{" "}
                  {accountName(language, item)}
                  {item.entry_number !== null && (
                    <span className="ui-sub2">
                      <EntryText
                        language={language}
                        number={item.entry_number}
                      />
                    </span>
                  )}
                </td>
                <td className="r ui-num">
                  {item.riel_held.toLocaleString("en-US")} ៛
                </td>
                <td className="r ui-num">
                  {item.khr_per_usd.toLocaleString("en-US")}
                </td>
                <td className="r ui-num">{money(item.before_cents)}</td>
                <td className="r ui-num">{money(item.after_cents)}</td>
                <td className="r ui-num">{money(item.gain_cents)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function MonthsTable({
  language,
  data,
}: {
  language: Language;
  data: MonthEnd;
}) {
  return (
    <section aria-labelledby="cl-months" className="ui-card">
      <h2 id="cl-months">{lt(language, "cl_months")}</h2>
      <div className="ui-tablewrap">
        <table className="ui-table">
          <thead>
            <tr>
              <th scope="col">{lt(language, "month")}</th>
              <th scope="col">{lt(language, "col_status")}</th>
              <th scope="col">{lt(language, "br_by")}</th>
            </tr>
          </thead>
          <tbody>
            {data.months.map((month) => (
              <tr key={month.id}>
                <td>{monthLabel(language, month.starts_on)}</td>
                <td>
                  {month.status === "CLOSED" ? (
                    <Chip icon="lock" tone="neutral">
                      {lt(language, "gl_c_closed")}
                    </Chip>
                  ) : month.id === data.month?.id ? (
                    <Chip icon="clock" tone="warn">
                      {lt(language, "cl_now")}
                    </Chip>
                  ) : (
                    <Chip tone="ok">{lt(language, "gl_c_open")}</Chip>
                  )}
                </td>
                <td>
                  {month.status === "CLOSED"
                    ? lt(
                        language,
                        "gl_c_by",
                        month.closed_by_name ?? lt(language, "by_unknown"),
                        momentText(month.closed_at),
                      )
                    : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="ui-muted">
        <Icon name="info" small /> {lt(language, "gl_c_sub")}
      </p>
    </section>
  );
}

function YearsTable({
  language,
  data,
  canClose,
  onClose,
}: {
  language: Language;
  data: MonthEnd;
  canClose: boolean;
  onClose: (year: LedgerYear) => void;
}) {
  return (
    <section aria-labelledby="cl-years" className="ui-card">
      <h2 id="cl-years">{lt(language, "ye_t")}</h2>
      <p className="ui-muted">{lt(language, "ye_sub")}</p>
      <div className="ui-tablewrap">
        <table className="ui-table">
          <thead>
            <tr>
              <th scope="col">{lt(language, "ye_year")}</th>
              <th scope="col">{lt(language, "col_status")}</th>
              <th className="r" scope="col">
                {lt(language, "ye_profit")}
              </th>
              <th scope="col">{lt(language, "gl_src")}</th>
            </tr>
          </thead>
          <tbody>
            {data.years.map((item) => {
              const label = String(item.fiscal_year);
              return (
                <tr key={item.id}>
                  <td className="ui-num">{label}</td>
                  <td>
                    {item.status === "CLOSED" ? (
                      <Chip icon="lock" tone="neutral">
                        {lt(language, "ye_closed")}
                      </Chip>
                    ) : (
                      <Chip tone="ok">{lt(language, "gl_c_open")}</Chip>
                    )}
                  </td>
                  <td className="r ui-num">
                    {item.profit_cents === null
                      ? "—"
                      : money(item.profit_cents)}
                  </td>
                  <td>
                    {item.entry_number !== null ? (
                      <a
                        className="ui-num"
                        href={hashForPage("journal", item.entry_number)}
                      >
                        {item.entry_number}
                      </a>
                    ) : item.status !== "CLOSED" &&
                      item.december_closed &&
                      canClose ? (
                      <button
                        className="ui-btn"
                        onClick={() => {
                          onClose(item);
                        }}
                        type="button"
                      >
                        <Icon name="lock" small />
                        {lt(language, "ye_btn")}
                      </button>
                    ) : (
                      <span className="ui-muted">
                        {lt(language, "ye_wait", label)}
                      </span>
                    )}
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

function CloseMonthDialog({
  language,
  propertyId,
  month,
  api,
  onClose,
  onDone,
}: {
  language: Language;
  propertyId: string;
  month: LedgerMonth;
  api: MonthEndApi;
  onClose: () => void;
  onDone: (text: string) => void;
}) {
  const work = useBusy(language);
  const name = monthLabel(language, month.starts_on);
  return (
    <Dialog
      busy={work.busy}
      closeLabel={lt(language, "cancel")}
      onClose={onClose}
      onSubmit={(event) => {
        event.preventDefault();
        work.run(
          () => api.closeMonth(propertyId, month.id),
          (closed) => {
            onDone(lt(language, closed ? "gl_c_done" : "cl_not_closed", name));
          },
        );
      }}
      submitLabel={lt(language, "gl_c_btn")}
      title={lt(language, "cl_btn", name)}
    >
      <p>{lt(language, "cl_conf", name)}</p>
      <Failure text={work.failure} />
    </Dialog>
  );
}

function CloseYearDialog({
  language,
  propertyId,
  year,
  api,
  onClose,
  onDone,
}: {
  language: Language;
  propertyId: string;
  year: LedgerYear;
  api: MonthEndApi;
  onClose: () => void;
  onDone: (text: string) => void;
}) {
  const work = useBusy(language);
  const label = String(year.fiscal_year);
  return (
    <Dialog
      busy={work.busy}
      closeLabel={lt(language, "cancel")}
      onClose={onClose}
      onSubmit={(event) => {
        event.preventDefault();
        work.run(
          async () => {
            await api.closeYear(propertyId, year.id);
            const again = await api.read(propertyId, null);
            return (
              again.years.find((item) => item.id === year.id)?.entry_number ??
              ""
            );
          },
          (entry) => {
            onDone(lt(language, "ye_done", label, entry));
          },
        );
      }}
      submitLabel={lt(language, "ye_btn")}
      title={`${lt(language, "ye_btn")} ${label}`}
    >
      <p>{lt(language, "ye_conf_n")}</p>
      <Failure text={work.failure} />
    </Dialog>
  );
}
