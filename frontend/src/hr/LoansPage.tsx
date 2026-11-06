// HRIS phase 6 (mock-up v69, round 23): Office › Employees and payroll › Salary loans. Money
// lent to staff and taken back from the next salary or an amount each month. The Accountant
// or Manager sends a loan to the Owner; the Owner approves or refuses; then it is paid out
// with its ledger entry. The limit (business rule) and the one-open-loan rule are checked by
// the server again.

import { type FormEvent, useCallback, useState } from "react";

import { useRead } from "../ledger/LedgerPage";
import { DateInput } from "../shell/DateInput";
import { dayText, momentText } from "../shell/format";
import { Icon } from "../shell/icons";
import { Chip, Dialog, type Tone } from "../shell/ui";
import type { Language } from "../signInText";
import {
  centsOf,
  Done,
  Failure,
  Field,
  money,
  nameOf,
  NoProperty,
  ReasonField,
  useHrBusy,
  Waiting,
} from "./common";
import { ReasonDialog } from "./EmployeesPage";
import {
  type Body,
  type Employee,
  type HrApi,
  hrApi as defaultHrApi,
  type Loan,
  type LoanList,
  type LoanState,
} from "./hrClient";
import { codeText, ht } from "./text";

export interface LoansPageProps {
  language: Language;
  propertyId: string;
  active: boolean;
  api?: HrApi;
}

const TONE: Record<LoanState, Tone> = {
  WAITING: "warn",
  APPROVED: "info",
  PAID_OUT: "ok",
  REPAID: "neutral",
  REFUSED: "neutral",
};

function percent(points: number): string {
  return `${String(points / 100)}%`;
}

function repaymentText(language: Language, loan: Loan): string {
  return loan.repayment_plan === "MONTHLY_AMOUNT" &&
    loan.monthly_repayment_usd_cents !== null
    ? ht(language, "l_each", money(loan.monthly_repayment_usd_cents))
    : ht(language, "l_next");
}

export function LoansPage({
  language,
  propertyId,
  active,
  api = defaultHrApi,
}: LoansPageProps) {
  const ready = active && propertyId !== "";
  const read = useCallback(() => api.loans(propertyId), [api, propertyId]);
  const answer = useRead<LoanList>(ready, read);
  const readPeople = useCallback(
    () => api.employees(propertyId),
    [api, propertyId],
  );
  const people = useRead<Employee[]>(
    ready && answer.data?.can_prepare === true,
    readPeople,
  );
  const [adding, setAdding] = useState(false);
  const [approving, setApproving] = useState<Loan | null>(null);
  const [refusing, setRefusing] = useState<Loan | null>(null);
  const [paying, setPaying] = useState<Loan | null>(null);
  const [done, setDone] = useState<string | null>(null);
  if (propertyId === "") return <NoProperty language={language} />;
  const data = answer.data;
  const finish = (text: string) => {
    setAdding(false);
    setApproving(null);
    setRefusing(null);
    setPaying(null);
    setDone(text);
    answer.reload();
  };
  return (
    <>
      <Done text={done} />
      <section aria-labelledby="hr-l-title" className="ui-card">
        <div className="ui-head">
          <div>
            <h2 id="hr-l-title">{ht(language, "l_title")}</h2>
            <p>{ht(language, "l_sub")}</p>
          </div>
          {data?.can_prepare === true && (
            <button
              className="ui-btn primary"
              disabled={people.data === null}
              onClick={() => {
                setDone(null);
                setAdding(true);
              }}
              type="button"
            >
              <Icon name="plus" small />
              {ht(language, "l_new")}
            </button>
          )}
        </div>
        {data !== null && (
          <p className="ui-muted ui-small">
            {ht(language, "l_rule", percent(data.loan_pct), data.open_max)}
          </p>
        )}
      </section>
      <section aria-labelledby="hr-l-list" className="ui-card pad0">
        <h2 className="ui-sr" id="hr-l-list">
          {ht(language, "l_title")}
        </h2>
        {data === null ? (
          <Waiting
            failed={answer.failed}
            language={language}
            onRetry={answer.reload}
          />
        ) : data.loans.length === 0 ? (
          <p className="ui-empty">{ht(language, "l_none")}</p>
        ) : (
          <div className="ui-tablewrap">
            <table className="ui-table">
              <thead>
                <tr>
                  <th scope="col">{ht(language, "l_number")}</th>
                  <th scope="col">{ht(language, "e_name")}</th>
                  <th className="r" scope="col">
                    {ht(language, "l_amount")}
                  </th>
                  <th scope="col">{ht(language, "l_repayment")}</th>
                  <th className="r" scope="col">
                    {ht(language, "l_left_owed")}
                  </th>
                  <th scope="col">{ht(language, "a_status")}</th>
                  <th scope="col">
                    <span className="ui-sr">{ht(language, "a_status")}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.loans.map((loan) => (
                  <tr key={loan.loan_id}>
                    <td>
                      <span className="ui-num">{loan.loan_number}</span>
                      <span className="ui-sub2 ui-num">
                        {dayText(loan.requested_on)}
                      </span>
                    </td>
                    <td>
                      {nameOf(language, loan)}
                      <span className="ui-sub2">{loan.reason}</span>
                      {loan.request_channel === "TELEGRAM" && (
                        <span className="ui-sub2">
                          {ht(language, "l_telegram")}
                        </span>
                      )}
                    </td>
                    <td className="r ui-num">{money(loan.amount_usd_cents)}</td>
                    <td>{repaymentText(language, loan)}</td>
                    <td className="r ui-num">
                      {loan.state === "PAID_OUT"
                        ? money(loan.owed_usd_cents)
                        : ""}
                    </td>
                    <td>
                      <Chip tone={TONE[loan.state]}>
                        {codeText(language, "ls_", loan.state)}
                      </Chip>
                      {loan.decision !== null && (
                        <span className="ui-sub2 ui-muted">
                          {ht(
                            language,
                            "by",
                            loan.decision.by ?? "",
                            momentText(loan.decision.at),
                          )}
                          {loan.decision.reason !== null &&
                            ` · ${loan.decision.reason}`}
                        </span>
                      )}
                      {loan.paid_on !== null && (
                        <span className="ui-sub2 ui-num">
                          {ht(language, "l_paid_on")} {dayText(loan.paid_on)}
                        </span>
                      )}
                    </td>
                    <td>
                      <span className="ui-actions">
                        {loan.state === "WAITING" && data.can_approve && (
                          <>
                            <button
                              className="ui-btn primary"
                              onClick={() => {
                                setDone(null);
                                setApproving(loan);
                              }}
                              type="button"
                            >
                              {ht(language, "approve")}
                            </button>
                            <button
                              className="ui-btn"
                              onClick={() => {
                                setDone(null);
                                setRefusing(loan);
                              }}
                              type="button"
                            >
                              {ht(language, "refuse")}
                            </button>
                          </>
                        )}
                        {loan.state === "APPROVED" && data.can_prepare && (
                          <button
                            className="ui-btn"
                            onClick={() => {
                              setDone(null);
                              setPaying(loan);
                            }}
                            type="button"
                          >
                            {ht(language, "l_payout")}
                          </button>
                        )}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {adding && data !== null && people.data !== null && (
        <NewLoanDialog
          api={api}
          data={data}
          language={language}
          onClose={() => {
            setAdding(false);
          }}
          onSaved={finish}
          people={people.data.filter((person) => person.state !== "LEFT")}
          propertyId={propertyId}
        />
      )}
      {approving !== null && (
        <ApproveDialog
          api={api}
          language={language}
          loan={approving}
          onClose={() => {
            setApproving(null);
          }}
          onSaved={finish}
          propertyId={propertyId}
        />
      )}
      {refusing !== null && (
        <ReasonDialog
          language={language}
          onClose={() => {
            setRefusing(null);
          }}
          onSave={(reason) =>
            api
              .decideLoan(propertyId, refusing.loan_id, {
                decision: "REFUSED",
                reason,
              })
              .then(() => ht(language, "l_refused", refusing.loan_number))
          }
          onSaved={finish}
          submitLabel={ht(language, "refuse")}
          title={ht(language, "ot_refuse_t", refusing.loan_number)}
        />
      )}
      {paying !== null && data !== null && (
        <PayOutDialog
          api={api}
          language={language}
          loan={paying}
          onClose={() => {
            setPaying(null);
          }}
          onSaved={finish}
          propertyId={propertyId}
          today={data.today}
        />
      )}
    </>
  );
}

function NewLoanDialog({
  language,
  propertyId,
  api,
  data,
  people,
  onSaved,
  onClose,
}: {
  language: Language;
  propertyId: string;
  api: HrApi;
  data: LoanList;
  people: Employee[];
  onSaved: (text: string) => void;
  onClose: () => void;
}) {
  const [employee, setEmployee] = useState(people[0]?.employee_id ?? "");
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState<"CASH_USD" | "ABA_JOINT">("CASH_USD");
  const [plan, setPlan] = useState<"NEXT_SALARY" | "MONTHLY_AMOUNT">(
    "NEXT_SALARY",
  );
  const [monthly, setMonthly] = useState("");
  const [telegram, setTelegram] = useState(false);
  const [asked, setAsked] = useState(data.today);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { busy, failure, run } = useHrBusy(language);
  const person = people.find((one) => one.employee_id === employee) ?? null;
  const salary = person?.pay?.monthly_salary_usd_cents ?? null;
  const limit =
    salary === null ? null : Math.floor((salary * data.loan_pct) / 10000);
  const cents = centsOf(amount);
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (person === null) return;
    if (cents === null) {
      setError(ht(language, "amount_bad"));
      return;
    }
    if (reason.trim() === "") {
      setError(ht(language, "say_why"));
      return;
    }
    const body: Body = {
      employee_id: person.employee_id,
      amount_usd_cents: cents,
      payout_method: method,
      repayment_plan: plan,
      request_channel: telegram ? "TELEGRAM" : "APP",
      requested_on: asked,
      reason: reason.trim(),
    };
    if (plan === "MONTHLY_AMOUNT") {
      const each = centsOf(monthly);
      if (each === null) {
        setError(ht(language, "amount_bad"));
        return;
      }
      body.monthly_repayment_usd_cents = each;
    }
    setError(null);
    run(
      () => api.addLoan(propertyId, body),
      () => {
        onSaved(ht(language, "l_sent_for", nameOf(language, person)));
      },
    );
  };
  return (
    <Dialog
      busy={busy}
      closeLabel={ht(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={ht(language, "l_send")}
      title={ht(language, "l_new")}
    >
      <Field id="hr-nl-emp" label={ht(language, "e_name")}>
        <select
          id="hr-nl-emp"
          onChange={(event) => {
            setEmployee(event.target.value);
          }}
          value={employee}
        >
          {people.map((one) => (
            <option key={one.employee_id} value={one.employee_id}>
              {nameOf(language, one)} · {one.employee_code}
            </option>
          ))}
        </select>
      </Field>
      <Field
        id="hr-nl-amt"
        label={ht(language, "l_amount")}
        note={ht(language, "required")}
        help={
          limit === null
            ? undefined
            : `${ht(language, "l_limit")} ${money(limit)}`
        }
      >
        <div className="ui-money">
          <span aria-hidden="true">$</span>
          <input
            autoComplete="off"
            id="hr-nl-amt"
            inputMode="decimal"
            onChange={(event) => {
              setAmount(event.target.value);
            }}
            value={amount}
          />
        </div>
      </Field>
      {cents !== null && limit !== null && (
        <p>
          {cents <= limit ? (
            <Chip tone="ok">{ht(language, "l_within", money(limit))}</Chip>
          ) : (
            <Chip tone="err">{ht(language, "l_over", money(limit))}</Chip>
          )}
        </p>
      )}
      <Field id="hr-nl-met" label={ht(language, "l_payout_method")}>
        <select
          id="hr-nl-met"
          onChange={(event) => {
            setMethod(event.target.value as "CASH_USD" | "ABA_JOINT");
          }}
          value={method}
        >
          {(["CASH_USD", "ABA_JOINT"] as const).map((code) => (
            <option key={code} value={code}>
              {codeText(language, "pm_", code)}
            </option>
          ))}
        </select>
      </Field>
      <fieldset className="ui-field">
        <legend>{ht(language, "l_repayment")}</legend>
        <div className="ui-radios">
          {(["NEXT_SALARY", "MONTHLY_AMOUNT"] as const).map((code) => (
            <label className="ui-chk" key={code}>
              <input
                checked={plan === code}
                name="hr-nl-plan"
                onChange={() => {
                  setPlan(code);
                }}
                type="radio"
              />
              {ht(language, code === "NEXT_SALARY" ? "l_next" : "l_monthly")}
            </label>
          ))}
        </div>
      </fieldset>
      {plan === "MONTHLY_AMOUNT" && (
        <Field
          id="hr-nl-each"
          label={ht(language, "l_monthly_amount")}
          note={ht(language, "required")}
        >
          <div className="ui-money">
            <span aria-hidden="true">$</span>
            <input
              autoComplete="off"
              id="hr-nl-each"
              inputMode="decimal"
              onChange={(event) => {
                setMonthly(event.target.value);
              }}
              value={monthly}
            />
          </div>
        </Field>
      )}
      <label className="ui-chk">
        <input
          checked={telegram}
          onChange={(event) => {
            setTelegram(event.target.checked);
          }}
          type="checkbox"
        />
        {ht(language, "l_telegram")}
      </label>
      <Field id="hr-nl-day" label={ht(language, "e_from")}>
        <DateInput
          id="hr-nl-day"
          language={language}
          max={data.today}
          onChange={setAsked}
          value={asked}
        />
      </Field>
      <ReasonField
        id="hr-nl-why"
        language={language}
        onChange={setReason}
        value={reason}
      />
      <Failure text={error ?? failure} />
    </Dialog>
  );
}

function ApproveDialog({
  language,
  propertyId,
  api,
  loan,
  onSaved,
  onClose,
}: {
  language: Language;
  propertyId: string;
  api: HrApi;
  loan: Loan;
  onSaved: (text: string) => void;
  onClose: () => void;
}) {
  const [note, setNote] = useState("");
  const { busy, failure, run } = useHrBusy(language);
  return (
    <Dialog
      busy={busy}
      closeLabel={ht(language, "cancel")}
      onClose={onClose}
      onSubmit={(event) => {
        event.preventDefault();
        const body: Body = { decision: "APPROVED" };
        if (note.trim() !== "") body.own_request_note = note.trim();
        run(
          () => api.decideLoan(propertyId, loan.loan_id, body),
          () => {
            onSaved(ht(language, "l_approved", loan.loan_number));
          },
        );
      }}
      submitLabel={ht(language, "approve")}
      title={ht(language, "l_approve_t", loan.loan_number)}
    >
      <p>
        {ht(
          language,
          "l_borrows",
          nameOf(language, loan),
          money(loan.amount_usd_cents),
          repaymentText(language, loan),
        )}
      </p>
      <p className="ui-muted">{loan.reason}</p>
      <ReasonField
        id="hr-la-note"
        label={ht(language, "l_owner_note")}
        language={language}
        onChange={setNote}
        optional
        value={note}
      />
      <Failure text={failure} />
    </Dialog>
  );
}

function PayOutDialog({
  language,
  propertyId,
  api,
  loan,
  today,
  onSaved,
  onClose,
}: {
  language: Language;
  propertyId: string;
  api: HrApi;
  loan: Loan;
  today: string;
  onSaved: (text: string) => void;
  onClose: () => void;
}) {
  const [day, setDay] = useState(today);
  const { busy, failure, run } = useHrBusy(language);
  return (
    <Dialog
      busy={busy}
      closeLabel={ht(language, "cancel")}
      onClose={onClose}
      onSubmit={(event) => {
        event.preventDefault();
        run(
          () => api.payOutLoan(propertyId, loan.loan_id, day),
          () => {
            onSaved(ht(language, "l_paid_out", loan.loan_number));
          },
        );
      }}
      submitLabel={ht(language, "l_payout")}
      title={ht(language, "l_payout_t", loan.loan_number)}
    >
      <p>
        {ht(
          language,
          "p_to",
          money(loan.amount_usd_cents),
          nameOf(language, loan),
        )}{" "}
        {codeText(language, "pm_", loan.payout_method)}
      </p>
      <Field
        id="hr-lp-day"
        label={ht(language, "l_paid_on")}
        note={ht(language, "required")}
      >
        <DateInput
          id="hr-lp-day"
          language={language}
          max={today}
          onChange={setDay}
          value={day}
        />
      </Field>
      <Failure text={failure} />
    </Dialog>
  );
}
