// HRIS phase 6 (mock-up v69, round 23): Office › Employees and payroll › Payroll. Each month's
// list goes Prepared → Checked → Approved → Paid. The Accountant adds lines and sends it; the
// Owner approves or sends it back; approval makes one ledger entry per person; then each person
// is marked paid. An approved list never changes: a correction list adds what was missed.

import { type FormEvent, useCallback, useState } from "react";

import { useRead } from "../ledger/LedgerPage";
import { monthLabel } from "../ledger/text";
import { DateInput } from "../shell/DateInput";
import { dayText, momentText } from "../shell/format";
import { Icon } from "../shell/icons";
import { openPageInAddress, useHashDetail } from "../shell/useHashPage";
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
  type HrApi,
  hrApi as defaultHrApi,
  type PayrollDetail,
  type PayrollList,
  type PayrollPerson,
  type PayrollRun,
  type PayrollState,
} from "./hrClient";
import { codeText, ht } from "./text";
import { PageHead } from "../shell/pageHead";

export interface PayrollPageProps {
  language: Language;
  propertyId: string;
  active: boolean;
  api?: HrApi;
}

const TONE: Record<PayrollState, Tone> = {
  LIST_MADE: "info",
  SENT_FOR_APPROVAL: "warn",
  SENT_BACK: "err",
  APPROVED: "ok",
};

/** The lines a person may add by hand; the rest come from the list and Attendance. */
const ADDABLE = [
  "BONUS",
  "OTHER_PLUS",
  "OTHER_MINUS",
  "OVERTIME",
  "DAYS_NOT_WORKED",
] as const;

function stateChip(language: Language, run: PayrollRun) {
  return (
    <Chip tone={TONE[run.state]}>{codeText(language, "ps_", run.state)}</Chip>
  );
}

function allPaid(run: PayrollDetail): boolean {
  return (
    run.people.length > 0 &&
    run.people.every((person) => person.payslip?.payment != null)
  );
}

export function PayrollPage({
  language,
  propertyId,
  active,
  api = defaultHrApi,
}: PayrollPageProps) {
  const detail = useHashDetail("payroll");
  const ready = active && propertyId !== "";
  const read = useCallback(() => api.payrolls(propertyId), [api, propertyId]);
  const list = useRead<PayrollList>(ready, read);
  const [done, setDone] = useState<string | null>(null);
  if (propertyId === "") return <NoProperty language={language} />;
  if (detail !== null) {
    return (
      <RunView
        api={api}
        key={detail}
        language={language}
        list={list.data}
        onListChanged={list.reload}
        propertyId={propertyId}
        runId={detail}
      />
    );
  }
  const data = list.data;
  const hasNext =
    data?.runs.some(
      (run) =>
        run.salary_month === data.next_month && run.run_kind === "REGULAR",
    ) === true;
  return (
    <>
      <Done text={done} />
      <section aria-labelledby="hr-p-title" className="ui-card">
        <PageHead>
          <div>
            <h2 id="hr-p-title">{ht(language, "p_title")}</h2>
            <p>{ht(language, "p_sub")}</p>
          </div>
          {data !== null && data.can_prepare && !hasNext && (
            <MakeButton
              api={api}
              language={language}
              month={data.next_month}
              onMade={(run) => {
                setDone(null);
                list.reload();
                openPageInAddress("payroll", false, run.run_id);
              }}
              propertyId={propertyId}
            />
          )}
        </PageHead>
        {data !== null && (
          <>
            <p className="ui-muted ui-small">
              {ht(language, "p_rule", data.pay_day)}
            </p>
            <p className="ui-muted ui-small">{ht(language, "p_tax_off")}</p>
          </>
        )}
      </section>
      <section aria-labelledby="hr-p-list" className="ui-card pad0">
        <h2 className="ui-sr" id="hr-p-list">
          {ht(language, "p_title")}
        </h2>
        {data === null ? (
          <Waiting
            failed={list.failed}
            language={language}
            onRetry={list.reload}
          />
        ) : data.runs.length === 0 ? (
          <p className="ui-empty">{ht(language, "p_none")}</p>
        ) : (
          <div className="ui-tablewrap">
            <table className="ui-table">
              <thead>
                <tr>
                  <th scope="col">{ht(language, "p_title")}</th>
                  <th scope="col">{ht(language, "p_period")}</th>
                  <th scope="col">{ht(language, "a_status")}</th>
                  <th className="r" scope="col">
                    {ht(language, "p_net")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.runs.map((run) => (
                  <tr
                    className="ui-row"
                    key={run.run_id}
                    onClick={() => {
                      openPageInAddress("payroll", false, run.run_id);
                    }}
                  >
                    <td>
                      <button
                        className="ui-btn link"
                        onClick={(event) => {
                          event.stopPropagation();
                          openPageInAddress("payroll", false, run.run_id);
                        }}
                        type="button"
                      >
                        {run.run_number}
                      </button>
                      {run.run_kind === "CORRECTION" && (
                        <span className="ui-sub2">
                          {ht(language, "p_correction")}
                        </span>
                      )}
                    </td>
                    <td>
                      {monthLabel(language, run.salary_month)}
                      <span className="ui-sub2 ui-num">
                        {ht(language, "p_pay_on", dayText(run.pay_date))}
                      </span>
                    </td>
                    <td>{stateChip(language, run)}</td>
                    <td className="r ui-num">{money(run.net_pay_usd_cents)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}

function MakeButton({
  language,
  propertyId,
  api,
  month,
  onMade,
}: {
  language: Language;
  propertyId: string;
  api: HrApi;
  month: string;
  onMade: (run: PayrollDetail) => void;
}) {
  const { busy, failure, run } = useHrBusy(language);
  return (
    <div>
      <button
        className="ui-btn primary"
        disabled={busy}
        onClick={() => {
          run(() => api.makePayroll(propertyId, month), onMade);
        }}
        type="button"
      >
        <Icon name="plus" small />
        {ht(language, "p_make", monthLabel(language, month))}
      </button>
      <Failure text={failure} />
    </div>
  );
}

type Opened =
  | null
  | "line"
  | "send"
  | "approve"
  | "back"
  | "correction"
  | { pay: PayrollPerson }
  | { undo: PayrollPerson }
  | { slip: PayrollPerson }
  | { remove: { person: PayrollPerson; lineId: string } };

function RunView({
  language,
  propertyId,
  api,
  runId,
  list,
  onListChanged,
}: {
  language: Language;
  propertyId: string;
  api: HrApi;
  runId: string;
  list: PayrollList | null;
  onListChanged: () => void;
}) {
  const read = useCallback(
    () => api.payroll(propertyId, runId),
    [api, propertyId, runId],
  );
  const answer = useRead<PayrollDetail>(true, read);
  const [opened, setOpened] = useState<Opened>(null);
  const [done, setDone] = useState<string | null>(null);
  const sending = useHrBusy(language);
  const back = (
    <button
      className="ui-crumb"
      onClick={() => {
        openPageInAddress("payroll");
      }}
      type="button"
    >
      <Icon name="back" small />
      {ht(language, "p_back")}
    </button>
  );
  const run = answer.data;
  if (run === null) {
    return (
      <>
        {back}
        <Waiting
          failed={answer.failed}
          language={language}
          onRetry={answer.reload}
        />
      </>
    );
  }
  const canPrepare = list?.can_prepare === true;
  const canApprove = list?.can_approve === true;
  const canPay = list?.can_pay === true;
  const open = run.state === "LIST_MADE" || run.state === "SENT_BACK";
  const finish = (text: string) => {
    setOpened(null);
    setDone(text);
    answer.reload();
    onListChanged();
  };
  const unpaid = run.people.filter(
    (person) => person.payslip?.payment == null,
  ).length;
  const steps: {
    key: string;
    label: string;
    doneAt: string | null;
    now: boolean;
  }[] = [
    {
      key: "made",
      label: ht(language, "ps_LIST_MADE"),
      doneAt:
        run.events.find((event) => event.event_type === "LIST_MADE")?.at ??
        null,
      now: open,
    },
    {
      key: "checked",
      label: ht(language, "ps_SENT_FOR_APPROVAL"),
      doneAt: open
        ? null
        : ([...run.events]
            .reverse()
            .find((event) => event.event_type === "SENT_FOR_APPROVAL")?.at ??
          null),
      now: run.state === "SENT_FOR_APPROVAL",
    },
    {
      key: "approved",
      label: ht(language, "ps_APPROVED"),
      doneAt:
        run.events.find((event) => event.event_type === "APPROVED")?.at ?? null,
      now: run.state === "APPROVED" && !allPaid(run),
    },
    {
      key: "paid",
      label: ht(language, "ps_PAID"),
      doneAt: allPaid(run) ? "" : null,
      now: false,
    },
  ];
  return (
    <>
      {back}
      <Done text={done} />
      <section aria-labelledby="hr-pr-title" className="ui-card">
        <PageHead>
          <div>
            <h2 id="hr-pr-title">
              {ht(language, "p_for", monthLabel(language, run.salary_month))}{" "}
              <span className="ui-sub2 ui-num">{run.run_number}</span>
            </h2>
            <p>
              {stateChip(language, run)}{" "}
              {ht(language, "p_pay_on", dayText(run.pay_date))}
              {run.run_kind === "CORRECTION" &&
                ` · ${ht(language, "p_correction")}`}
            </p>
          </div>
          <div className="ui-actions">
            {open && canPrepare && (
              <>
                <button
                  className="ui-btn"
                  onClick={() => {
                    setDone(null);
                    setOpened("line");
                  }}
                  type="button"
                >
                  <Icon name="plus" small />
                  {ht(language, "p_add_line")}
                </button>
                <button
                  className="ui-btn primary"
                  disabled={sending.busy}
                  onClick={() => {
                    setDone(null);
                    sending.run(
                      () =>
                        api.payrollStep(propertyId, run.run_id, {
                          step: "SEND",
                        }),
                      () => {
                        finish(ht(language, "p_sent"));
                      },
                    );
                  }}
                  type="button"
                >
                  {ht(language, "p_send")}
                </button>
              </>
            )}
            {run.state === "SENT_FOR_APPROVAL" && canApprove && (
              <>
                <button
                  className="ui-btn primary"
                  onClick={() => {
                    setDone(null);
                    setOpened("approve");
                  }}
                  type="button"
                >
                  {ht(language, "p_approve")}
                </button>
                <button
                  className="ui-btn"
                  onClick={() => {
                    setDone(null);
                    setOpened("back");
                  }}
                  type="button"
                >
                  {ht(language, "p_send_back")}
                </button>
              </>
            )}
            {run.state === "APPROVED" && canPrepare && (
              <button
                className="ui-btn"
                onClick={() => {
                  setDone(null);
                  setOpened("correction");
                }}
                type="button"
              >
                {ht(language, "p_make_correction")}
              </button>
            )}
          </div>
        </PageHead>
        <Failure text={sending.failure} />
        <ol aria-label={ht(language, "a_status")} className="ui-msteps">
          {steps.map((step, index) => (
            <li
              aria-current={step.now ? "step" : undefined}
              className="ui-mstep"
              key={step.key}
            >
              <span
                aria-hidden="true"
                className={`ui-mark${step.doneAt !== null ? " done" : ""}${step.now ? " now" : ""}`}
              >
                {step.doneAt !== null ? <Icon name="check" small /> : index + 1}
              </span>
              <div>
                <strong>{step.label}</strong>
                {step.doneAt !== null && step.doneAt !== "" && (
                  <span className="ui-sub2 ui-num">
                    {momentText(step.doneAt)}
                  </span>
                )}
              </div>
            </li>
          ))}
        </ol>
        {run.events
          .filter(
            (event) => event.reason !== null || event.own_request_note !== null,
          )
          .map((event) => (
            <p className="ui-muted ui-small" key={event.at}>
              {codeText(language, "ps_", event.event_type)} ·{" "}
              {ht(language, "by", event.by ?? "", momentText(event.at))}:{" "}
              {event.reason ?? event.own_request_note}
            </p>
          ))}
        {run.state === "APPROVED" && (
          <p className="ui-muted ui-small">
            {ht(language, "p_correction_note")}
          </p>
        )}
      </section>
      {run.state === "APPROVED" && (
        <section aria-labelledby="hr-pr-paylist" className="ui-card">
          <h2 id="hr-pr-paylist">
            {ht(language, "p_pay_list", monthLabel(language, run.salary_month))}
          </h2>
          <p>{ht(language, "p_pay_note")}</p>
          {unpaid > 0 && (
            <Chip tone="warn">{ht(language, "p_not_paid_n", unpaid)}</Chip>
          )}
        </section>
      )}
      <section aria-labelledby="hr-pr-people" className="ui-card pad0">
        <h2 className="ui-sr" id="hr-pr-people">
          {ht(language, "p_people")}
        </h2>
        <div className="ui-tablewrap">
          <table className="ui-table">
            <thead>
              <tr>
                <th scope="col">{ht(language, "e_name")}</th>
                <th scope="col">{ht(language, "p_lines")}</th>
                <th className="r" scope="col">
                  {ht(language, "p_net")}
                </th>
                <th scope="col">{ht(language, "e_method")}</th>
                <th scope="col">
                  <span className="ui-sr">{ht(language, "p_payslip")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {run.people.map((person) => {
                const payment = person.payslip?.payment ?? null;
                return (
                  <tr key={person.employee_id}>
                    <td>
                      {nameOf(language, person)}
                      <span className="ui-sub2 ui-num">
                        {person.employee_code}
                      </span>
                    </td>
                    <td>
                      <ul className="ui-plain">
                        {person.lines.map((line) => (
                          <li key={line.line_id}>
                            {line.source === "ATTENDANCE" && (
                              <span
                                aria-label={ht(language, "p_from_att")}
                                role="img"
                              >
                                <Icon name="clock" small />
                              </span>
                            )}{" "}
                            {nameOf(language, line)}{" "}
                            <span className="ui-num">
                              {line.direction === "DEDUCTION" ? "-" : ""}
                              {money(line.amount_usd_cents)}
                            </span>
                            {line.days_worked !== null &&
                              line.days_in_month !== null &&
                              line.component === "BASE_SALARY" && (
                                <span className="ui-muted ui-num">
                                  {" "}
                                  · {ht(language, "p_days_worked")}{" "}
                                  {line.days_worked}/{line.days_in_month}
                                </span>
                              )}
                            {line.reason !== null &&
                              line.source === "MANUAL" && (
                                <span className="ui-sub2">{line.reason}</span>
                              )}
                            {open && canPrepare && line.source === "MANUAL" && (
                              <button
                                className="ui-btn link"
                                onClick={() => {
                                  setDone(null);
                                  setOpened({
                                    remove: { person, lineId: line.line_id },
                                  });
                                }}
                                type="button"
                              >
                                {ht(language, "p_remove_line")}
                              </button>
                            )}
                          </li>
                        ))}
                      </ul>
                    </td>
                    <td className="r ui-num">
                      <strong>{money(person.net_pay_usd_cents)}</strong>
                    </td>
                    <td>
                      {person.payment_method === null
                        ? ""
                        : codeText(language, "pm_", person.payment_method)}
                      {person.payment_method === "ABA" &&
                        person.aba_account_number !== null && (
                          <span className="ui-sub2 ui-num">
                            {person.aba_account_number}
                          </span>
                        )}
                    </td>
                    <td>
                      <span className="ui-actions">
                        {person.payslip !== null && (
                          <button
                            className="ui-btn link"
                            onClick={() => {
                              setOpened({ slip: person });
                            }}
                            type="button"
                          >
                            {ht(language, "p_payslip")}
                          </button>
                        )}
                        {run.state === "APPROVED" && payment === null && (
                          <>
                            <Chip tone="warn">
                              {ht(language, "p_not_paid")}
                            </Chip>
                            {canPay && person.payslip !== null && (
                              <button
                                className="ui-btn primary"
                                onClick={() => {
                                  setDone(null);
                                  setOpened({ pay: person });
                                }}
                                type="button"
                              >
                                {ht(language, "p_mark_paid")}
                              </button>
                            )}
                          </>
                        )}
                        {payment !== null && (
                          <>
                            <Chip tone="ok">
                              {ht(language, "p_paid", dayText(payment.paid_on))}
                            </Chip>
                            {canPay && (
                              <button
                                className="ui-btn link"
                                onClick={() => {
                                  setDone(null);
                                  setOpened({ undo: person });
                                }}
                                type="button"
                              >
                                {ht(language, "p_reverse")}
                              </button>
                            )}
                          </>
                        )}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row">{ht(language, "p_net")}</th>
                <td />
                <td className="r ui-num">
                  <strong>{money(run.net_pay_usd_cents)}</strong>
                </td>
                <td colSpan={2} />
              </tr>
            </tfoot>
          </table>
        </div>
        <p className="ui-tfoot ui-muted">{ht(language, "p_clock_note")}</p>
      </section>
      {opened === "line" && (
        <AddLineDialog
          api={api}
          language={language}
          onClose={() => {
            setOpened(null);
          }}
          onSaved={finish}
          propertyId={propertyId}
          run={run}
        />
      )}
      {opened === "approve" && (
        <ApproveDialog
          api={api}
          language={language}
          onClose={() => {
            setOpened(null);
          }}
          onSaved={finish}
          propertyId={propertyId}
          run={run}
        />
      )}
      {opened === "back" && (
        <ReasonDialog
          language={language}
          onClose={() => {
            setOpened(null);
          }}
          onSave={(reason) =>
            api
              .payrollStep(propertyId, run.run_id, {
                step: "SEND_BACK",
                reason,
              })
              .then(() => ht(language, "p_sent_back"))
          }
          onSaved={finish}
          submitLabel={ht(language, "p_send_back")}
          title={ht(language, "p_send_back")}
        />
      )}
      {opened === "correction" && (
        <ReasonDialog
          language={language}
          note={ht(language, "p_correction_note")}
          onClose={() => {
            setOpened(null);
          }}
          onSave={(reason) =>
            api
              .makeCorrection(propertyId, run.run_id, reason ?? "")
              .then((made) => {
                openPageInAddress("payroll", false, made.run_id);
                return ht(language, "e_added_thing", made.run_number);
              })
          }
          onSaved={(text) => {
            setOpened(null);
            setDone(text);
            onListChanged();
          }}
          submitLabel={ht(language, "p_make_correction")}
          title={ht(language, "p_make_correction")}
        />
      )}
      {opened !== null && typeof opened === "object" && "remove" in opened && (
        <ReasonDialog
          language={language}
          onClose={() => {
            setOpened(null);
          }}
          onSave={(reason) =>
            api
              .payrollStep(propertyId, run.run_id, {
                step: "REMOVE_LINE",
                line_id: opened.remove.lineId,
                reason,
              })
              .then(() => ht(language, "p_line_removed"))
          }
          onSaved={finish}
          submitLabel={ht(language, "p_remove_line")}
          title={`${ht(language, "p_remove_line")} · ${nameOf(language, opened.remove.person)}`}
        />
      )}
      {opened !== null && typeof opened === "object" && "pay" in opened && (
        <MarkPaidDialog
          api={api}
          language={language}
          onClose={() => {
            setOpened(null);
          }}
          onSaved={finish}
          person={opened.pay}
          propertyId={propertyId}
          today={list?.today ?? run.pay_date}
        />
      )}
      {opened !== null && typeof opened === "object" && "undo" in opened && (
        <ReasonDialog
          language={language}
          note={ht(language, "p_reverse_note")}
          onClose={() => {
            setOpened(null);
          }}
          onSave={(reason) => {
            const payment = opened.undo.payslip?.payment;
            if (payment == null) return Promise.reject(new Error("no payment"));
            return api
              .reversePayment(propertyId, payment.payment_id, reason ?? "")
              .then(() =>
                ht(language, "p_reversed", nameOf(language, opened.undo)),
              );
          }}
          onSaved={finish}
          submitLabel={ht(language, "p_reverse")}
          title={ht(language, "p_reverse_t", nameOf(language, opened.undo))}
        />
      )}
      {opened !== null && typeof opened === "object" && "slip" in opened && (
        <PayslipDialog
          language={language}
          onClose={() => {
            setOpened(null);
          }}
          person={opened.slip}
          run={run}
        />
      )}
    </>
  );
}

function AddLineDialog({
  language,
  propertyId,
  api,
  run,
  onSaved,
  onClose,
}: {
  language: Language;
  propertyId: string;
  api: HrApi;
  run: PayrollDetail;
  onSaved: (text: string) => void;
  onClose: () => void;
}) {
  const [employee, setEmployee] = useState(run.people[0]?.employee_id ?? "");
  const [component, setComponent] = useState<(typeof ADDABLE)[number]>("BONUS");
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { busy, failure, run: go } = useHrBusy(language);
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const cents = centsOf(amount);
    if (cents === null) {
      setError(ht(language, "amount_bad"));
      return;
    }
    if (reason.trim() === "") {
      setError(ht(language, "say_why"));
      return;
    }
    setError(null);
    const body: Body = {
      step: "ADD_LINE",
      employee_id: employee,
      component,
      amount_usd_cents: cents,
      reason: reason.trim(),
    };
    go(
      () => api.payrollStep(propertyId, run.run_id, body),
      () => {
        onSaved(ht(language, "p_line_added"));
      },
    );
  };
  return (
    <Dialog
      busy={busy}
      closeLabel={ht(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={ht(language, "p_add_line")}
      title={ht(language, "p_add_line")}
    >
      <Field id="hr-pl-emp" label={ht(language, "e_name")}>
        <select
          id="hr-pl-emp"
          onChange={(event) => {
            setEmployee(event.target.value);
          }}
          value={employee}
        >
          {run.people.map((person) => (
            <option key={person.employee_id} value={person.employee_id}>
              {nameOf(language, person)} · {person.employee_code}
            </option>
          ))}
        </select>
      </Field>
      <Field id="hr-pl-kind" label={ht(language, "p_component")}>
        <select
          id="hr-pl-kind"
          onChange={(event) => {
            setComponent(event.target.value as (typeof ADDABLE)[number]);
          }}
          value={component}
        >
          {ADDABLE.map((code) => (
            <option key={code} value={code}>
              {codeText(language, "pc_", code)}
            </option>
          ))}
        </select>
      </Field>
      <Field
        id="hr-pl-amt"
        label={ht(language, "p_amount")}
        note={ht(language, "required")}
      >
        <div className="ui-money">
          <span aria-hidden="true">$</span>
          <input
            autoComplete="off"
            id="hr-pl-amt"
            inputMode="decimal"
            onChange={(event) => {
              setAmount(event.target.value);
            }}
            value={amount}
          />
        </div>
      </Field>
      <ReasonField
        id="hr-pl-why"
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
  run,
  onSaved,
  onClose,
}: {
  language: Language;
  propertyId: string;
  api: HrApi;
  run: PayrollDetail;
  onSaved: (text: string) => void;
  onClose: () => void;
}) {
  const [note, setNote] = useState("");
  const { busy, failure, run: go } = useHrBusy(language);
  return (
    <Dialog
      busy={busy}
      closeLabel={ht(language, "cancel")}
      onClose={onClose}
      onSubmit={(event) => {
        event.preventDefault();
        const body: Body = { step: "APPROVE" };
        if (note.trim() !== "") body.own_request_note = note.trim();
        go(
          () => api.payrollStep(propertyId, run.run_id, body),
          () => {
            onSaved(ht(language, "p_approved", run.run_number));
          },
        );
      }}
      submitLabel={ht(language, "p_approve")}
      title={ht(language, "p_approve_t", run.run_number)}
    >
      <p>
        {ht(
          language,
          "p_approve_note",
          run.people.length,
          money(run.net_pay_usd_cents),
          dayText(run.pay_date),
        )}
      </p>
      <ReasonField
        id="hr-pa-note"
        label={ht(language, "p_own_checked")}
        language={language}
        onChange={setNote}
        optional
        value={note}
      />
      <Failure text={failure} />
    </Dialog>
  );
}

function MarkPaidDialog({
  language,
  propertyId,
  api,
  person,
  today,
  onSaved,
  onClose,
}: {
  language: Language;
  propertyId: string;
  api: HrApi;
  person: PayrollPerson;
  today: string;
  onSaved: (text: string) => void;
  onClose: () => void;
}) {
  const [day, setDay] = useState(today);
  const [method, setMethod] = useState<"CASH_USD" | "ABA_JOINT">(
    person.payment_method === "ABA" ? "ABA_JOINT" : "CASH_USD",
  );
  const [reference, setReference] = useState("");
  const { busy, failure, run } = useHrBusy(language);
  const slip = person.payslip;
  return (
    <Dialog
      busy={busy}
      closeLabel={ht(language, "cancel")}
      onClose={onClose}
      onSubmit={(event) => {
        event.preventDefault();
        if (slip === null) return;
        const body: Body = { paid_on: day, method };
        if (reference.trim() !== "") body.bank_reference = reference.trim();
        run(
          () => api.paySalary(propertyId, slip.payslip_id, body),
          () => {
            onSaved(ht(language, "p_marked", nameOf(language, person)));
          },
        );
      }}
      submitLabel={ht(language, "p_mark_paid")}
      title={ht(language, "p_mark_paid_t", nameOf(language, person))}
    >
      <p>
        {ht(
          language,
          "p_to",
          money(person.net_pay_usd_cents),
          person.payment_method === "ABA" && person.aba_account_number !== null
            ? `${person.aba_account_name ?? ""} ${person.aba_account_number}`
            : nameOf(language, person),
        )}
      </p>
      <Field
        id="hr-mp-day"
        label={ht(language, "l_paid_on")}
        note={ht(language, "required")}
      >
        <DateInput
          id="hr-mp-day"
          language={language}
          max={today}
          onChange={setDay}
          value={day}
        />
      </Field>
      <Field id="hr-mp-met" label={ht(language, "l_payout_method")}>
        <select
          id="hr-mp-met"
          onChange={(event) => {
            setMethod(event.target.value as "CASH_USD" | "ABA_JOINT");
          }}
          value={method}
        >
          {(["ABA_JOINT", "CASH_USD"] as const).map((code) => (
            <option key={code} value={code}>
              {codeText(language, "pm_", code)}
            </option>
          ))}
        </select>
      </Field>
      {method === "ABA_JOINT" && (
        <Field
          id="hr-mp-ref"
          label={ht(language, "p_bank_ref")}
          note={ht(language, "optional")}
        >
          <input
            id="hr-mp-ref"
            maxLength={60}
            onChange={(event) => {
              setReference(event.target.value);
            }}
            value={reference}
          />
        </Field>
      )}
      <Failure text={failure} />
    </Dialog>
  );
}

function PayslipDialog({
  language,
  run,
  person,
  onClose,
}: {
  language: Language;
  run: PayrollDetail;
  person: PayrollPerson;
  onClose: () => void;
}) {
  const earnings = person.lines.filter((line) => line.direction === "EARNING");
  const deductions = person.lines.filter(
    (line) => line.direction === "DEDUCTION",
  );
  const table = (lines: typeof earnings, label: string, total: number) => (
    <table className="ui-table">
      <thead>
        <tr>
          <th scope="col">{label}</th>
          <th className="r" scope="col">
            {ht(language, "p_amount")}
          </th>
        </tr>
      </thead>
      <tbody>
        {lines.map((line) => (
          <tr key={line.line_id}>
            <td>
              {nameOf(language, line)}
              {line.reason !== null && (
                <span className="ui-sub2">{line.reason}</span>
              )}
            </td>
            <td className="r ui-num">{money(line.amount_usd_cents)}</td>
          </tr>
        ))}
      </tbody>
      <tfoot>
        <tr>
          <th scope="row">{label}</th>
          <td className="r ui-num">
            <strong>{money(total)}</strong>
          </td>
        </tr>
      </tfoot>
    </table>
  );
  return (
    <Dialog
      closeLabel={ht(language, "close")}
      onClose={onClose}
      title={ht(
        language,
        "p_payslip_t",
        nameOf(language, person),
        monthLabel(language, run.salary_month),
      )}
    >
      {table(earnings, ht(language, "p_earnings"), person.earnings_usd_cents)}
      {deductions.length > 0 &&
        table(
          deductions,
          ht(language, "p_deductions"),
          person.deductions_usd_cents,
        )}
      <p>
        <strong>
          {ht(language, "p_net")}:{" "}
          <span className="ui-num">{money(person.net_pay_usd_cents)}</span>
        </strong>
      </p>
      <p className="ui-muted ui-small">{ht(language, "p_payslip_bot")}</p>
    </Dialog>
  );
}
