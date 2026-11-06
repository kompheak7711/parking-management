// HRIS phase 6 (mock-up v69, DESIGN.md "Users and access, Employees, Salary loans, Payroll"):
// Office › Employees and payroll › Employees. The list (Active, Left), Add employee, New staff
// from Telegram, and one employee's page: Details, Pay details, Employment history, Documents,
// Telegram links and the Employee card. Every change adds a line; nothing is typed over or
// deleted. The server checks every right again.

import { type FormEvent, useCallback, useMemo, useState } from "react";

import { useRead } from "../ledger/LedgerPage";
import { DateInput } from "../shell/DateInput";
import { dayText, momentText } from "../shell/format";
import { Icon } from "../shell/icons";
import { openPageInAddress, useHashDetail } from "../shell/useHashPage";
import { Chip, Dialog } from "../shell/ui";
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
  shiftText,
  useHrBusy,
  Waiting,
} from "./common";
import {
  type Body,
  type Employee,
  type EmployeeCard,
  type EmployeeDetail,
  type HrApi,
  hrApi as defaultHrApi,
  type HrChoices,
  type PayMethod,
  type ReportRole,
  type CaretakerShift,
  type ShiftCode,
  type StaffRequest,
} from "./hrClient";
import { codeText, ht } from "./text";

export interface EmployeesPageProps {
  language: Language;
  propertyId: string;
  active: boolean;
  capabilities: ReadonlySet<string> | null;
  api?: HrApi;
}

const SHIFTS: readonly CaretakerShift[] = ["MORNING", "AFTERNOON", "NIGHT"];
const ROLES: readonly ReportRole[] = [
  "CLEANER",
  "TECHNICIAN",
  "CARETAKER",
  "METER_READER",
  "AUTHORIZER",
];
const WEEKDAYS = [1, 2, 3, 4, 5, 6, 7] as const;
const DOC_KINDS = ["CONTRACT", "ID_CARD", "CERTIFICATE", "OTHER"] as const;
const ID_TYPES = ["NATIONAL_ID", "PASSPORT"] as const;
/** A JSON body carries the photo as base64; the server takes at most 20 MB in all. */
const ID_PHOTO_MAX_BYTES = 15 * 1024 * 1024;
const ID_PHOTO_TYPES = ["image/jpeg", "image/png", "application/pdf"];

function usesShifts(jobs: HrChoices["job_titles"], job: string): boolean {
  return jobs.find((one) => one.id === job)?.uses_shifts === true;
}

/** Days off a month on request (owner 06/11/2026: caretaker and cleaner 2), else null. */
function monthlyDaysOff(
  jobs: HrChoices["job_titles"],
  job: string,
): number | null {
  return jobs.find((one) => one.id === job)?.days_off_per_month ?? null;
}

/** Only the caretaker sends a shift; only a job with a weekly day off sends that day. */
function jobBody(
  jobs: HrChoices["job_titles"],
  job: string,
  shift: CaretakerShift,
  dayOff: number,
): Body {
  return {
    job_title_id: job,
    ...(usesShifts(jobs, job) ? { shift_code: shift } : {}),
    ...(monthlyDaysOff(jobs, job) === null ? { usual_day_off: dayOff } : {}),
  };
}

function caretakerShift(code: ShiftCode | null): CaretakerShift {
  return code === null || code === "OFFICE" ? "MORNING" : code;
}

function base64Of(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const url = typeof reader.result === "string" ? reader.result : "";
      resolve(url.slice(url.indexOf(",") + 1));
    };
    reader.onerror = () => {
      reject(new Error("The file could not be read"));
    };
    reader.readAsDataURL(file);
  });
}

function weekdayName(language: Language, day: number | null): string {
  return day === null ? "" : codeText(language, "wd_", String(day));
}

function stateChip(language: Language, employee: Employee) {
  if (employee.state === "LEFT")
    return <Chip tone="neutral">{ht(language, "e_left")}</Chip>;
  if (employee.state === "LEAVING" && employee.left_on !== null)
    return (
      <Chip tone="warn">
        {ht(language, "e_leaves", dayText(employee.left_on))}
      </Chip>
    );
  if (employee.state === "STARTS_LATER")
    return (
      <Chip tone="info">
        {ht(language, "e_starts", dayText(employee.hired_on))}
      </Chip>
    );
  return <Chip tone="ok">{ht(language, "e_active")}</Chip>;
}

export function EmployeesPage({
  language,
  propertyId,
  active,
  capabilities,
  api = defaultHrApi,
}: EmployeesPageProps) {
  const detail = useHashDetail("employees");
  const ready = active && propertyId !== "";
  const readList = useCallback(
    () => api.employees(propertyId),
    [api, propertyId],
  );
  const readChoices = useCallback(
    () => api.choices(propertyId),
    [api, propertyId],
  );
  const list = useRead<Employee[]>(ready && detail === null, readList);
  const choices = useRead<HrChoices>(ready, readChoices);
  if (propertyId === "") return <NoProperty language={language} />;
  if (detail !== null) {
    return (
      <EmployeeView
        api={api}
        capabilities={capabilities}
        choices={choices.data}
        employeeId={detail}
        key={detail}
        language={language}
        propertyId={propertyId}
      />
    );
  }
  return (
    <EmployeeList
      api={api}
      choices={choices.data}
      language={language}
      list={list}
      onChoicesChanged={choices.reload}
      propertyId={propertyId}
    />
  );
}

function EmployeeList({
  language,
  propertyId,
  api,
  list,
  choices,
  onChoicesChanged,
}: {
  language: Language;
  propertyId: string;
  api: HrApi;
  list: { data: Employee[] | null; failed: boolean; reload: () => void };
  choices: HrChoices | null;
  onChoicesChanged: () => void;
}) {
  const [view, setView] = useState<"active" | "left">("active");
  const [adding, setAdding] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const canManage = choices?.can_manage === true;
  const readRequests = useCallback(
    () => api.staffRequests(propertyId),
    [api, propertyId],
  );
  const requests = useRead<StaffRequest[]>(canManage, readRequests);
  const people = (list.data ?? []).filter((person) =>
    view === "left" ? person.state === "LEFT" : person.state !== "LEFT",
  );
  return (
    <>
      <Done text={done} />
      <section aria-labelledby="hr-e-title" className="ui-card">
        <div className="ui-head">
          <div>
            <h2 id="hr-e-title">{ht(language, "e_title")}</h2>
            <p>{ht(language, "e_sub")}</p>
          </div>
          {canManage && (
            <button
              className="ui-btn primary"
              onClick={() => {
                setDone(null);
                setAdding(true);
              }}
              type="button"
            >
              <Icon name="userplus" small />
              {ht(language, "e_add")}
            </button>
          )}
        </div>
      </section>
      {canManage &&
        requests.data !== null &&
        requests.data.length > 0 &&
        list.data !== null && (
          <StaffRequests
            api={api}
            choices={choices}
            employees={list.data}
            language={language}
            onDone={(text) => {
              setDone(text);
              requests.reload();
              list.reload();
            }}
            propertyId={propertyId}
            requests={requests.data}
          />
        )}
      <section aria-labelledby="hr-e-list" className="ui-card pad0">
        <div className="ui-filters">
          <h2 className="ui-sr" id="hr-e-list">
            {ht(language, "e_title")}
          </h2>
          <div
            aria-label={ht(language, "e_title")}
            className="ui-seg"
            role="group"
          >
            {(["active", "left"] as const).map((which) => (
              <button
                aria-pressed={view === which}
                key={which}
                onClick={() => {
                  setView(which);
                }}
                type="button"
              >
                {ht(language, which === "active" ? "e_active" : "e_left")}
              </button>
            ))}
          </div>
        </div>
        {list.data === null ? (
          <Waiting
            failed={list.failed}
            language={language}
            onRetry={list.reload}
          />
        ) : people.length === 0 ? (
          <p className="ui-empty">{ht(language, "e_none")}</p>
        ) : (
          <div className="ui-tablewrap">
            <table className="ui-table">
              <thead>
                <tr>
                  <th scope="col">{ht(language, "e_name")}</th>
                  <th scope="col">{ht(language, "e_job")}</th>
                  <th scope="col">{ht(language, "e_shift")}</th>
                  <th scope="col">{ht(language, "e_start")}</th>
                  <th scope="col">{ht(language, "e_telegram")}</th>
                  {people.some((person) => person.pay !== undefined) && (
                    <th className="r" scope="col">
                      {ht(language, "e_salary")}
                    </th>
                  )}
                </tr>
              </thead>
              <tbody>
                {people.map((person) => (
                  <tr
                    className="ui-row"
                    key={person.employee_id}
                    onClick={() => {
                      openPageInAddress("employees", false, person.employee_id);
                    }}
                  >
                    <td>
                      <button
                        className="ui-btn link"
                        onClick={(event) => {
                          event.stopPropagation();
                          openPageInAddress(
                            "employees",
                            false,
                            person.employee_id,
                          );
                        }}
                        type="button"
                      >
                        {nameOf(language, person)}
                      </button>
                      <span className="ui-sub2 ui-num">
                        {person.employee_code}
                      </span>
                    </td>
                    <td>
                      {person.job_title === null
                        ? ""
                        : nameOf(language, person.job_title)}
                    </td>
                    <td>{shiftText(language, person.shift_code)}</td>
                    <td>
                      <span className="ui-num">{dayText(person.hired_on)}</span>
                      <span className="ui-sub2">
                        {stateChip(language, person)}
                      </span>
                    </td>
                    <td>
                      {person.telegram.length > 0 ? (
                        <Chip tone="ok">{ht(language, "e_tg_linked")}</Chip>
                      ) : (
                        <Chip tone="neutral">{ht(language, "e_tg_none")}</Chip>
                      )}
                    </td>
                    {people.some((one) => one.pay !== undefined) && (
                      <td className="r ui-num">
                        {person.pay === null || person.pay === undefined
                          ? ""
                          : money(person.pay.monthly_salary_usd_cents)}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="ui-tfoot ui-muted">{ht(language, "e_never")}</p>
      </section>
      {adding && choices !== null && (
        <AddEmployeeDialog
          api={api}
          choices={choices}
          language={language}
          onClose={() => {
            setAdding(false);
          }}
          onSaved={(made) => {
            setAdding(false);
            setDone(ht(language, "e_added", nameOf(language, made)));
            list.reload();
            onChoicesChanged();
          }}
          propertyId={propertyId}
        />
      )}
    </>
  );
}

/* ---------- Add employee ---------- */

function AddEmployeeDialog({
  language,
  propertyId,
  api,
  choices,
  onClose,
  onSaved,
}: {
  language: Language;
  propertyId: string;
  api: HrApi;
  choices: HrChoices;
  onClose: () => void;
  onSaved: (made: EmployeeDetail) => void;
}) {
  const [nameEn, setNameEn] = useState("");
  const [nameKm, setNameKm] = useState("");
  const [phone, setPhone] = useState("");
  const [job, setJob] = useState(choices.job_titles[0]?.id ?? "");
  const [shift, setShift] = useState<CaretakerShift>("MORNING");
  const [dayOff, setDayOff] = useState(7);
  const [start, setStart] = useState(choices.today);
  const [idType, setIdType] =
    useState<(typeof ID_TYPES)[number]>("NATIONAL_ID");
  const [idNumber, setIdNumber] = useState("");
  const [birth, setBirth] = useState("");
  const [birthPlace, setBirthPlace] = useState("");
  const [address, setAddress] = useState("");
  const [photo, setPhoto] = useState<File | null>(null);
  const [hireAgain, setHireAgain] = useState(false);
  const [user, setUser] = useState("");
  const [salary, setSalary] = useState("");
  const [method, setMethod] = useState<PayMethod>("CASH_USD");
  const [abaName, setAbaName] = useState("");
  const [abaNumber, setAbaNumber] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { busy, failure, run } = useHrBusy(language);
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    if (nameEn.trim() === "" || nameKm.trim() === "" || job === "") {
      setError(ht(language, "required"));
      return;
    }
    if (start === "") {
      setError(ht(language, "day_bad"));
      return;
    }
    if (
      idNumber.trim() === "" ||
      birth === "" ||
      birthPlace.trim() === "" ||
      address.trim() === "" ||
      photo === null
    ) {
      setError(ht(language, "e_id_need"));
      return;
    }
    if (photo.size > ID_PHOTO_MAX_BYTES) {
      setError(ht(language, "e_id_photo_big"));
      return;
    }
    if (!ID_PHOTO_TYPES.includes(photo.type)) {
      setError(ht(language, "e_id_photo_note"));
      return;
    }
    const idPhoto = photo;
    const body: Body = {
      name_en: nameEn.trim(),
      name_km: nameKm.trim(),
      ...jobBody(choices.job_titles, job, shift, dayOff),
      start_date: start,
      identity: {
        id_type: idType,
        id_number: idNumber.trim(),
        date_of_birth: birth,
        place_of_birth: birthPlace.trim(),
        home_address: address.trim(),
      },
    };
    if (hireAgain) body.hire_again = true;
    if (phone.trim() !== "") body.phone = phone.trim();
    if (user !== "") body.user_actor_id = user;
    if (choices.can_change_salaries && salary.trim() !== "") {
      const cents = centsOf(salary);
      if (cents === null) {
        setError(ht(language, "amount_bad"));
        return;
      }
      body.pay = {
        monthly_salary_usd_cents: cents,
        payment_method: method,
        ...(method === "ABA"
          ? {
              aba_account_name: abaName.trim(),
              aba_account_number: abaNumber.trim(),
            }
          : {}),
      };
    }
    run(async () => {
      body.id_photo = {
        file_name: idPhoto.name,
        media_type: idPhoto.type,
        content_base64: await base64Of(idPhoto),
      };
      return api.addEmployee(propertyId, body);
    }, onSaved);
  };
  return (
    <Dialog
      busy={busy}
      closeLabel={ht(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={ht(language, "e_add")}
      title={ht(language, "e_add_t")}
    >
      {choices.job_titles.length === 0 && (
        <p className="ui-notice warn">{ht(language, "e_no_jobs")}</p>
      )}
      <Field
        id="hr-ae-en"
        label={ht(language, "e_name_en")}
        note={ht(language, "required")}
      >
        <input
          id="hr-ae-en"
          maxLength={120}
          onChange={(event) => {
            setNameEn(event.target.value);
          }}
          value={nameEn}
        />
      </Field>
      <Field
        id="hr-ae-km"
        label={ht(language, "e_name_km")}
        note={ht(language, "required")}
      >
        <input
          id="hr-ae-km"
          lang="km"
          maxLength={120}
          onChange={(event) => {
            setNameKm(event.target.value);
          }}
          value={nameKm}
        />
      </Field>
      <Field
        id="hr-ae-ph"
        label={ht(language, "e_phone")}
        note={ht(language, "optional")}
      >
        <input
          id="hr-ae-ph"
          inputMode="tel"
          maxLength={30}
          onChange={(event) => {
            setPhone(event.target.value);
          }}
          value={phone}
        />
      </Field>
      <JobFields
        dayOff={dayOff}
        job={job}
        jobs={choices.job_titles}
        language={language}
        prefix="hr-ae"
        setDayOff={setDayOff}
        setJob={setJob}
        setShift={setShift}
        shift={shift}
      />
      <Field
        id="hr-ae-start"
        label={ht(language, "e_start")}
        note={ht(language, "required")}
      >
        <DateInput
          id="hr-ae-start"
          language={language}
          onChange={setStart}
          value={start}
        />
      </Field>
      <h4>{ht(language, "e_id_head")}</h4>
      <Field
        id="hr-ae-idt"
        label={ht(language, "e_id_type")}
        note={ht(language, "required")}
      >
        <select
          id="hr-ae-idt"
          onChange={(event) => {
            setIdType(event.target.value as (typeof ID_TYPES)[number]);
          }}
          value={idType}
        >
          {ID_TYPES.map((code) => (
            <option key={code} value={code}>
              {codeText(language, "id_", code)}
            </option>
          ))}
        </select>
      </Field>
      <Field
        id="hr-ae-idn"
        label={ht(language, "e_id_number")}
        note={ht(language, "required")}
      >
        <input
          id="hr-ae-idn"
          maxLength={40}
          onChange={(event) => {
            setIdNumber(event.target.value);
            setHireAgain(false);
          }}
          value={idNumber}
        />
      </Field>
      <Field
        id="hr-ae-dob"
        label={ht(language, "e_birth")}
        note={ht(language, "required")}
      >
        <DateInput
          id="hr-ae-dob"
          language={language}
          onChange={setBirth}
          value={birth}
        />
      </Field>
      <Field
        id="hr-ae-pob"
        label={ht(language, "e_birth_place")}
        note={ht(language, "required")}
      >
        <input
          id="hr-ae-pob"
          maxLength={200}
          onChange={(event) => {
            setBirthPlace(event.target.value);
          }}
          value={birthPlace}
        />
      </Field>
      <Field
        id="hr-ae-addr"
        label={ht(language, "e_address")}
        note={ht(language, "required")}
      >
        <textarea
          id="hr-ae-addr"
          maxLength={300}
          onChange={(event) => {
            setAddress(event.target.value);
          }}
          rows={2}
          value={address}
        />
      </Field>
      <Field
        id="hr-ae-photo"
        label={ht(language, "e_id_photo")}
        note={ht(language, "required")}
        help={ht(language, "e_id_photo_note")}
      >
        <input
          accept="image/jpeg,image/png,application/pdf"
          id="hr-ae-photo"
          onChange={(event) => {
            setPhoto(event.target.files?.[0] ?? null);
          }}
          type="file"
        />
      </Field>
      <Field
        id="hr-ae-user"
        label={ht(language, "e_signin")}
        note={ht(language, "optional")}
      >
        <select
          id="hr-ae-user"
          onChange={(event) => {
            setUser(event.target.value);
          }}
          value={user}
        >
          <option value="">{ht(language, "e_no_signin")}</option>
          {choices.free_users.map((one) => (
            <option key={one.actor_id} value={one.actor_id}>
              {one.display_name === null
                ? one.username
                : `${one.display_name} (${one.username})`}
            </option>
          ))}
        </select>
      </Field>
      {choices.can_change_salaries ? (
        <>
          <h4>{ht(language, "e_pay")}</h4>
          <p className="ui-muted ui-small">{ht(language, "e_pay_first")}</p>
          <PayFields
            abaName={abaName}
            abaNumber={abaNumber}
            language={language}
            method={method}
            prefix="hr-ae"
            salary={salary}
            setAbaName={setAbaName}
            setAbaNumber={setAbaNumber}
            setMethod={setMethod}
            setSalary={setSalary}
          />
        </>
      ) : (
        <p className="ui-muted ui-small">{ht(language, "e_pay_later")}</p>
      )}
      {(hireAgain || (failure ?? "").includes("Hire again?")) && (
        <label className="ui-chk">
          <input
            checked={hireAgain}
            id="hr-ae-again"
            onChange={(event) => {
              setHireAgain(event.target.checked);
            }}
            type="checkbox"
          />
          {ht(language, "e_hire_again")}
        </label>
      )}
      <Failure text={error ?? failure} />
    </Dialog>
  );
}

function JobFields({
  language,
  prefix,
  jobs,
  job,
  setJob,
  shift,
  setShift,
  dayOff,
  setDayOff,
}: {
  language: Language;
  prefix: string;
  jobs: HrChoices["job_titles"];
  job: string;
  setJob: (value: string) => void;
  shift: CaretakerShift;
  setShift: (value: CaretakerShift) => void;
  dayOff: number;
  setDayOff: (value: number) => void;
}) {
  const shifts = usesShifts(jobs, job);
  const monthly = monthlyDaysOff(jobs, job);
  return (
    <>
      <Field
        id={`${prefix}-job`}
        label={ht(language, "e_job")}
        note={ht(language, "required")}
      >
        <select
          id={`${prefix}-job`}
          onChange={(event) => {
            setJob(event.target.value);
          }}
          value={job}
        >
          {jobs.map((one) => (
            <option key={one.id} value={one.id}>
              {nameOf(language, one)}
            </option>
          ))}
        </select>
      </Field>
      {shifts ? (
        <Field
          id={`${prefix}-shift`}
          label={ht(language, "e_shift")}
          note={ht(language, "required")}
        >
          <select
            id={`${prefix}-shift`}
            onChange={(event) => {
              setShift(event.target.value as CaretakerShift);
            }}
            value={shift}
          >
            {SHIFTS.map((code) => (
              <option key={code} value={code}>
                {shiftText(language, code)}
              </option>
            ))}
          </select>
        </Field>
      ) : (
        <p className="ui-muted ui-small">{ht(language, "e_office_hours")}</p>
      )}
      {monthly !== null ? (
        <p className="ui-muted ui-small">
          {ht(language, "e_monthly_off", monthly)}
        </p>
      ) : (
        <>
          <Field
            id={`${prefix}-off`}
            label={ht(language, "e_dayoff")}
            note={ht(language, "required")}
          >
            <select
              id={`${prefix}-off`}
              onChange={(event) => {
                setDayOff(Number(event.target.value));
              }}
              value={dayOff}
            >
              {WEEKDAYS.map((day) => (
                <option key={day} value={day}>
                  {weekdayName(language, day)}
                </option>
              ))}
            </select>
          </Field>
        </>
      )}
    </>
  );
}

function PayFields({
  language,
  prefix,
  salary,
  setSalary,
  method,
  setMethod,
  abaName,
  setAbaName,
  abaNumber,
  setAbaNumber,
}: {
  language: Language;
  prefix: string;
  salary: string;
  setSalary: (value: string) => void;
  method: PayMethod;
  setMethod: (value: PayMethod) => void;
  abaName: string;
  setAbaName: (value: string) => void;
  abaNumber: string;
  setAbaNumber: (value: string) => void;
}) {
  return (
    <>
      <Field id={`${prefix}-sal`} label={ht(language, "e_salary")}>
        <div className="ui-money">
          <span aria-hidden="true">$</span>
          <input
            autoComplete="off"
            id={`${prefix}-sal`}
            inputMode="decimal"
            onChange={(event) => {
              setSalary(event.target.value);
            }}
            value={salary}
          />
        </div>
      </Field>
      <Field id={`${prefix}-met`} label={ht(language, "e_method")}>
        <select
          id={`${prefix}-met`}
          onChange={(event) => {
            setMethod(event.target.value as PayMethod);
          }}
          value={method}
        >
          {(["CASH_USD", "ABA"] as const).map((code) => (
            <option key={code} value={code}>
              {codeText(language, "pm_", code)}
            </option>
          ))}
        </select>
      </Field>
      {method === "ABA" && (
        <>
          <Field
            id={`${prefix}-abn`}
            label={ht(language, "e_aba_name")}
            note={ht(language, "required")}
          >
            <input
              id={`${prefix}-abn`}
              maxLength={120}
              onChange={(event) => {
                setAbaName(event.target.value);
              }}
              value={abaName}
            />
          </Field>
          <Field
            id={`${prefix}-abc`}
            label={ht(language, "e_aba_number")}
            note={ht(language, "required")}
          >
            <input
              id={`${prefix}-abc`}
              inputMode="numeric"
              maxLength={60}
              onChange={(event) => {
                setAbaNumber(event.target.value);
              }}
              value={abaNumber}
            />
          </Field>
        </>
      )}
    </>
  );
}

/* ---------- New staff from Telegram ---------- */

function StaffRequests({
  language,
  propertyId,
  api,
  requests,
  employees,
  choices,
  onDone,
}: {
  language: Language;
  propertyId: string;
  api: HrApi;
  requests: StaffRequest[];
  employees: Employee[];
  choices: HrChoices | null;
  onDone: (text: string) => void;
}) {
  const [linking, setLinking] = useState<StaffRequest | null>(null);
  const [refusing, setRefusing] = useState<StaffRequest | null>(null);
  return (
    <section aria-labelledby="hr-sr" className="ui-card">
      <h2 id="hr-sr">
        {ht(language, "sr_title")}{" "}
        <span className="ui-count ui-num">{requests.length}</span>
      </h2>
      <p className="ui-muted">{ht(language, "sr_sub")}</p>
      <ul className="ui-ulist">
        {requests.map((one) => (
          <li key={one.request_id}>
            <span>
              {ht(
                language,
                "sr_asked",
                one.given_name,
                one.phone ?? String(one.telegram_user_id),
                momentText(one.received_at),
              )}
            </span>
            <span className="ui-actions">
              <button
                className="ui-btn primary"
                onClick={() => {
                  setLinking(one);
                }}
                type="button"
              >
                {ht(language, "sr_link")}
              </button>
              <button
                className="ui-btn"
                onClick={() => {
                  setRefusing(one);
                }}
                type="button"
              >
                {ht(language, "sr_refuse")}
              </button>
            </span>
          </li>
        ))}
      </ul>
      {linking !== null && (
        <LinkRequestDialog
          api={api}
          employees={employees.filter((person) => person.state !== "LEFT")}
          isOwner={choices?.is_owner === true}
          language={language}
          onClose={() => {
            setLinking(null);
          }}
          onSaved={(text) => {
            setLinking(null);
            onDone(text);
          }}
          propertyId={propertyId}
          request={linking}
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
              .decideStaffRequest(propertyId, refusing.request_id, {
                decision: "REFUSED",
                reason,
              })
              .then(() => ht(language, "sr_refused", refusing.given_name))
          }
          onSaved={(text) => {
            setRefusing(null);
            onDone(text);
          }}
          submitLabel={ht(language, "sr_refuse")}
          title={ht(language, "sr_refuse_t", refusing.given_name)}
        />
      )}
    </section>
  );
}

function LinkRequestDialog({
  language,
  propertyId,
  api,
  request,
  employees,
  isOwner,
  onClose,
  onSaved,
}: {
  language: Language;
  propertyId: string;
  api: HrApi;
  request: StaffRequest;
  employees: Employee[];
  isOwner: boolean;
  onClose: () => void;
  onSaved: (text: string) => void;
}) {
  const [employee, setEmployee] = useState(employees[0]?.employee_id ?? "");
  const [roles, setRoles] = useState<ReportRole[]>([]);
  const [error, setError] = useState<string | null>(null);
  const { busy, failure, run } = useHrBusy(language);
  const chosen =
    employees.find((person) => person.employee_id === employee) ?? null;
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (chosen === null || roles.length === 0) {
      setError(ht(language, "sr_roles"));
      return;
    }
    run(
      () =>
        api.decideStaffRequest(propertyId, request.request_id, {
          decision: "LINKED",
          employee_id: chosen.employee_id,
          roles,
        }),
      () => {
        onSaved(ht(language, "e_tg_linked_to", nameOf(language, chosen)));
      },
    );
  };
  return (
    <Dialog
      busy={busy}
      closeLabel={ht(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={ht(language, "sr_link")}
      title={ht(language, "sr_link_t", request.given_name)}
    >
      <Field
        id="hr-sr-emp"
        label={ht(language, "e_title")}
        help={ht(language, "sr_not_listed")}
      >
        <select
          id="hr-sr-emp"
          onChange={(event) => {
            setEmployee(event.target.value);
          }}
          value={employee}
        >
          {employees.map((person) => (
            <option key={person.employee_id} value={person.employee_id}>
              {nameOf(language, person)} · {person.employee_code}
            </option>
          ))}
        </select>
      </Field>
      <fieldset className="ui-field">
        <legend>{ht(language, "e_tg_role")}</legend>
        {ROLES.filter((role) => role !== "AUTHORIZER" || isOwner).map(
          (role) => (
            <label className="ui-chk" key={role}>
              <input
                checked={roles.includes(role)}
                onChange={(event) => {
                  setRoles((now) =>
                    event.target.checked
                      ? [...now, role]
                      : now.filter((one) => one !== role),
                  );
                }}
                type="checkbox"
              />
              {codeText(language, "rr_", role)}
            </label>
          ),
        )}
        {!isOwner && (
          <p className="ui-muted ui-small">{ht(language, "e_tg_owner_only")}</p>
        )}
      </fieldset>
      <Failure text={error ?? failure} />
    </Dialog>
  );
}

/** A dialog that asks only for a reason, for steps such as Refuse or Remove. */
export function ReasonDialog({
  language,
  title,
  note,
  submitLabel,
  optional = false,
  onSave,
  onSaved,
  onClose,
}: {
  language: Language;
  title: string;
  note?: string;
  submitLabel: string;
  optional?: boolean;
  onSave: (reason: string | null) => Promise<string>;
  onSaved: (text: string) => void;
  onClose: () => void;
}) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { busy, failure, run } = useHrBusy(language);
  return (
    <Dialog
      busy={busy}
      closeLabel={ht(language, "cancel")}
      onClose={onClose}
      onSubmit={(event) => {
        event.preventDefault();
        if (!optional && reason.trim() === "") {
          setError(ht(language, "say_why"));
          return;
        }
        setError(null);
        run(() => onSave(reason.trim() === "" ? null : reason.trim()), onSaved);
      }}
      submitLabel={submitLabel}
      title={title}
    >
      {note !== undefined && <p>{note}</p>}
      <ReasonField
        id="hr-reason"
        language={language}
        onChange={setReason}
        optional={optional}
        value={reason}
      />
      <Failure text={error ?? failure} />
    </Dialog>
  );
}

/* ---------- One employee ---------- */

type Opened =
  | null
  | "details"
  | "job"
  | "pay"
  | "identity"
  | "leave"
  | "file"
  | "card"
  | { unlink: string }
  | { remove: string };

function EmployeeView({
  language,
  propertyId,
  api,
  employeeId,
  capabilities,
  choices,
}: {
  language: Language;
  propertyId: string;
  api: HrApi;
  employeeId: string;
  capabilities: ReadonlySet<string> | null;
  choices: HrChoices | null;
}) {
  const read = useCallback(
    () => api.employee(propertyId, employeeId),
    [api, propertyId, employeeId],
  );
  const answer = useRead<EmployeeDetail>(true, read);
  const readCard = useCallback(
    () => api.card(propertyId, employeeId),
    [api, propertyId, employeeId],
  );
  const card = useRead<EmployeeCard>(true, readCard);
  const [opened, setOpened] = useState<Opened>(null);
  const [done, setDone] = useState<string | null>(null);
  const [newCode, setNewCode] = useState<string | null>(null);
  const may = (right: string) =>
    capabilities === null || capabilities.has(right);
  const canManage = choices?.can_manage ?? may("hr.employees.manage");
  const canPay = choices?.can_change_salaries ?? may("hr.salaries.manage");
  const back = (
    <button
      className="ui-crumb"
      onClick={() => {
        openPageInAddress("employees");
      }}
      type="button"
    >
      <Icon name="back" small />
      {ht(language, "e_back")}
    </button>
  );
  const person = answer.data;
  if (person === null) {
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
  const name = nameOf(language, person);
  const working = person.state !== "LEFT";
  const saved = (text: string) => (value?: EmployeeDetail) => {
    setOpened(null);
    setDone(
      text.replace(
        "{name}",
        value === undefined ? name : nameOf(language, value),
      ),
    );
    answer.reload();
  };
  const step = (body: Body) => api.employeeStep(propertyId, person, body);
  return (
    <>
      {back}
      <Done text={done} />
      {newCode !== null && (
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{ht(language, "c_new_code", newCode)}</p>
        </div>
      )}
      <section aria-labelledby="hr-ed-title" className="ui-card">
        <div className="ui-head">
          <div>
            <h2 id="hr-ed-title">
              {name}{" "}
              <span className="ui-sub2 ui-num">{person.employee_code}</span>
            </h2>
            <p>{stateChip(language, person)}</p>
          </div>
          {canManage && working && (
            <div className="ui-actions">
              <button
                className="ui-btn"
                onClick={() => {
                  setOpened("job");
                }}
                type="button"
              >
                {ht(language, "e_change")}
              </button>
              {person.left_on === null && (
                <button
                  className="ui-btn"
                  onClick={() => {
                    setOpened("leave");
                  }}
                  type="button"
                >
                  {ht(language, "e_set_end")}
                </button>
              )}
            </div>
          )}
        </div>
      </section>
      <div className="ui-split">
        <div className="ui-stack">
          <section aria-labelledby="hr-ed-det" className="ui-card">
            <div className="ui-chead">
              <h2 id="hr-ed-det">{ht(language, "e_details")}</h2>
              {canManage && (
                <button
                  className="ui-btn link"
                  onClick={() => {
                    setOpened("details");
                  }}
                  type="button"
                >
                  {ht(language, "e_edit")}
                </button>
              )}
            </div>
            <dl className="ui-kv">
              <dt>{ht(language, "e_name_en")}</dt>
              <dd>{person.name_en}</dd>
              <dt>{ht(language, "e_name_km")}</dt>
              <dd lang="km">{person.name_km}</dd>
              <dt>{ht(language, "e_phone")}</dt>
              <dd>{person.phone ?? ""}</dd>
              <dt>{ht(language, "e_job")}</dt>
              <dd>
                {person.job_title === null
                  ? ""
                  : nameOf(language, person.job_title)}
              </dd>
              <dt>{ht(language, "e_shift")}</dt>
              <dd>{shiftText(language, person.shift_code)}</dd>
              <dt>{ht(language, "e_dayoff")}</dt>
              <dd>{weekdayName(language, person.usual_day_off)}</dd>
              <dt>{ht(language, "e_start")}</dt>
              <dd className="ui-num">{dayText(person.hired_on)}</dd>
              {person.left_on !== null && (
                <>
                  <dt>{ht(language, "e_end")}</dt>
                  <dd className="ui-num">{dayText(person.left_on)}</dd>
                </>
              )}
              <dt>{ht(language, "e_signin")}</dt>
              <dd>
                {person.user === null
                  ? ht(language, "e_no_signin")
                  : (person.user.display_name ?? person.user.username)}
              </dd>
            </dl>
          </section>
          <PayCard
            canChange={canPay && working}
            language={language}
            onOpen={(which) => {
              setOpened(which);
            }}
            person={person}
          />
          <TelegramCard
            canManage={canManage}
            language={language}
            onUnlink={(linkId) => {
              setOpened({ unlink: linkId });
            }}
            person={person}
          />
        </div>
        <div className="ui-stack">
          <HistoryCard language={language} person={person} />
          <DocumentsCard
            api={api}
            canManage={canManage}
            canRemoveId={canPay}
            language={language}
            onAdd={() => {
              setOpened("file");
            }}
            onRemove={(documentId) => {
              setOpened({ remove: documentId });
            }}
            person={person}
            propertyId={propertyId}
          />
          <CardBox
            card={card}
            language={language}
            onReplace={() => {
              setOpened("card");
            }}
          />
        </div>
      </div>
      {opened === "details" && (
        <DetailsDialog
          choices={choices}
          language={language}
          onClose={() => {
            setOpened(null);
          }}
          onSave={step}
          onSaved={saved(ht(language, "e_saved", "{name}"))}
          person={person}
        />
      )}
      {opened === "job" && choices !== null && (
        <JobDialog
          choices={choices}
          language={language}
          onClose={() => {
            setOpened(null);
          }}
          onSave={step}
          onSaved={saved(ht(language, "e_changed", "{name}"))}
          person={person}
        />
      )}
      {opened === "pay" && choices !== null && (
        <PayDialog
          language={language}
          onClose={() => {
            setOpened(null);
          }}
          onSave={step}
          onSaved={saved(ht(language, "e_changed", "{name}"))}
          person={person}
          today={choices.today}
        />
      )}
      {opened === "identity" && (
        <IdentityDialog
          language={language}
          onClose={() => {
            setOpened(null);
          }}
          onSave={step}
          onSaved={saved(ht(language, "e_saved", "{name}"))}
          person={person}
        />
      )}
      {opened === "leave" && (
        <LeaveDialog
          language={language}
          onClose={() => {
            setOpened(null);
          }}
          onSave={step}
          onSaved={(value, day) => {
            saved(ht(language, "e_leaves_on", "{name}", dayText(day)))(value);
          }}
          person={person}
          today={choices?.today ?? person.hired_on}
        />
      )}
      {opened === "file" && (
        <FileDialog
          api={api}
          language={language}
          onClose={() => {
            setOpened(null);
          }}
          onSaved={(value, title) => {
            saved(ht(language, "e_added_thing", title))(value);
          }}
          person={person}
          propertyId={propertyId}
        />
      )}
      {opened === "card" && (
        <ReasonDialog
          language={language}
          note={ht(language, "c_replace_note")}
          onClose={() => {
            setOpened(null);
          }}
          onSave={(reason) =>
            api
              .newCard(propertyId, person.employee_id, reason ?? "")
              .then((code) => {
                setNewCode(code);
                return ht(language, "e_saved", ht(language, "c_title"));
              })
          }
          onSaved={(text) => {
            setOpened(null);
            setDone(text);
            card.reload();
          }}
          submitLabel={ht(language, "c_replace")}
          title={ht(language, "c_replace_t", name)}
        />
      )}
      {opened !== null && typeof opened === "object" && "unlink" in opened && (
        <ReasonDialog
          language={language}
          onClose={() => {
            setOpened(null);
          }}
          onSave={(reason) =>
            step({
              step: "TELEGRAM_UNLINK",
              link_id: opened.unlink,
              reason,
            }).then(() => ht(language, "e_tg_unlinked", name))
          }
          onSaved={(text) => {
            setOpened(null);
            setDone(text);
            answer.reload();
          }}
          submitLabel={ht(language, "e_tg_unlink")}
          title={ht(language, "e_tg_unlink")}
        />
      )}
      {opened !== null && typeof opened === "object" && "remove" in opened && (
        <ReasonDialog
          language={language}
          onClose={() => {
            setOpened(null);
          }}
          onSave={(reason) =>
            step({
              step: "DOCUMENT_REMOVE",
              document_id: opened.remove,
              reason,
            }).then(() =>
              ht(
                language,
                "e_doc_removed",
                person.documents.find(
                  (one) => one.document_id === opened.remove,
                )?.title ?? "",
              ),
            )
          }
          onSaved={(text) => {
            setOpened(null);
            setDone(text);
            answer.reload();
          }}
          submitLabel={ht(language, "e_doc_remove")}
          title={ht(language, "e_doc_remove")}
        />
      )}
    </>
  );
}

function PayCard({
  language,
  person,
  canChange,
  onOpen,
}: {
  language: Language;
  person: EmployeeDetail;
  canChange: boolean;
  onOpen: (which: "pay" | "identity") => void;
}) {
  if (!person.can_see_salaries) {
    return (
      <section aria-labelledby="hr-ed-pay" className="ui-card">
        <h2 id="hr-ed-pay">{ht(language, "e_pay")}</h2>
        <p className="ui-muted">
          <Icon name="lock" small /> {ht(language, "e_pay_hidden")}
        </p>
      </section>
    );
  }
  const pay = person.pay ?? null;
  const identity = person.identity ?? null;
  return (
    <section aria-labelledby="hr-ed-pay" className="ui-card">
      <div className="ui-chead">
        <h2 id="hr-ed-pay">{ht(language, "e_pay")}</h2>
        {canChange && (
          <span className="ui-actions">
            <button
              className="ui-btn link"
              onClick={() => {
                onOpen("pay");
              }}
              type="button"
            >
              {ht(language, "e_change_pay")}
            </button>
            <button
              className="ui-btn link"
              onClick={() => {
                onOpen("identity");
              }}
              type="button"
            >
              {ht(language, "e_change_id")}
            </button>
          </span>
        )}
      </div>
      {pay === null ? (
        <p className="ui-muted">{ht(language, "e_pay_none")}</p>
      ) : (
        <dl className="ui-kv">
          <dt>{ht(language, "e_salary")}</dt>
          <dd className="ui-num">
            {ht(language, "per_month", money(pay.monthly_salary_usd_cents))}
          </dd>
          <dd className="note">
            {ht(language, "e_from")} {dayText(pay.effective_date)}
          </dd>
          <dt>{ht(language, "e_method")}</dt>
          <dd>{codeText(language, "pm_", pay.payment_method)}</dd>
          {pay.payment_method === "ABA" && (
            <>
              <dt>{ht(language, "e_aba_name")}</dt>
              <dd>{pay.aba_account_name ?? ""}</dd>
              <dt>{ht(language, "e_aba_number")}</dt>
              <dd className="ui-num">{pay.aba_account_number ?? ""}</dd>
            </>
          )}
        </dl>
      )}
      {identity !== null && (
        <dl className="ui-kv">
          <dt>{ht(language, "e_id_type")}</dt>
          <dd>{codeText(language, "id_", identity.id_type)}</dd>
          <dt>{ht(language, "e_id")}</dt>
          <dd className="ui-num">{identity.id_number ?? ""}</dd>
          <dt>{ht(language, "e_birth")}</dt>
          <dd className="ui-num">{dayText(identity.date_of_birth)}</dd>
          <dt>{ht(language, "e_birth_place")}</dt>
          <dd>{identity.place_of_birth ?? ""}</dd>
          <dt>{ht(language, "e_address")}</dt>
          <dd>{identity.home_address ?? ""}</dd>
        </dl>
      )}
    </section>
  );
}

function TelegramCard({
  language,
  person,
  canManage,
  onUnlink,
}: {
  language: Language;
  person: EmployeeDetail;
  canManage: boolean;
  onUnlink: (linkId: string) => void;
}) {
  return (
    <section aria-labelledby="hr-ed-tg" className="ui-card">
      <h2 id="hr-ed-tg">{ht(language, "e_telegram")}</h2>
      {person.telegram.length === 0 ? (
        <p className="ui-muted">{ht(language, "e_tg_none")}</p>
      ) : (
        <ul className="ui-ulist">
          {person.telegram.map((link) => (
            <li key={link.link_id}>
              <span>
                {codeText(language, "rr_", link.report_role)}
                <span className="ui-sub2 ui-num">
                  {link.telegram_user_id} ·{" "}
                  {ht(language, "e_tg_since", momentText(link.linked_at))}
                </span>
              </span>
              {canManage && (
                <button
                  className="ui-btn link"
                  onClick={() => {
                    onUnlink(link.link_id);
                  }}
                  type="button"
                >
                  {ht(language, "e_tg_unlink")}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function HistoryCard({
  language,
  person,
}: {
  language: Language;
  person: EmployeeDetail;
}) {
  const lines = useMemo(() => {
    const rows: {
      key: string;
      day: string;
      what: string;
      detail: string;
      why: string;
      by: string;
    }[] = person.history.map((line) => ({
      key: line.event_id,
      day: line.effective_date,
      what: codeText(language, "ev_", line.event_type),
      detail:
        line.event_type === "LEFT"
          ? ""
          : [
              language === "km" && line.job_title_km !== null
                ? line.job_title_km
                : (line.job_title_en ?? ""),
              shiftText(language, line.shift_code),
            ]
              .filter(Boolean)
              .join(" · "),
      why: line.reason ?? "",
      by: ht(language, "by", line.by ?? "", momentText(line.at)),
    }));
    for (const pay of person.pay_history ?? []) {
      rows.push({
        key: pay.pay_term_id,
        day: pay.effective_date,
        what: ht(language, "ev_PAY"),
        detail: `${money(pay.monthly_salary_usd_cents)} · ${codeText(language, "pm_", pay.payment_method)}`,
        why: pay.reason ?? "",
        by: ht(language, "by", pay.by ?? "", momentText(pay.at)),
      });
    }
    return rows.sort((a, b) => (a.day < b.day ? 1 : a.day > b.day ? -1 : 0));
  }, [language, person]);
  return (
    <section aria-labelledby="hr-ed-hist" className="ui-card">
      <h2 id="hr-ed-hist">{ht(language, "e_history")}</h2>
      <ul className="ui-timeline">
        {lines.map((line) => (
          <li key={line.key}>
            <strong>
              <span className="ui-num">{dayText(line.day)}</span> · {line.what}
            </strong>
            {line.detail !== "" && (
              <span className="ui-sub2">{line.detail}</span>
            )}
            {line.why !== "" && <span className="ui-sub2">{line.why}</span>}
            <span className="ui-sub2 ui-muted">{line.by}</span>
          </li>
        ))}
      </ul>
      <p className="ui-muted ui-small">{ht(language, "e_history_note")}</p>
    </section>
  );
}

function DocumentsCard({
  language,
  propertyId,
  api,
  person,
  canManage,
  canRemoveId,
  onAdd,
  onRemove,
}: {
  language: Language;
  propertyId: string;
  api: HrApi;
  person: EmployeeDetail;
  canManage: boolean;
  canRemoveId: boolean;
  onAdd: () => void;
  onRemove: (documentId: string) => void;
}) {
  return (
    <section aria-labelledby="hr-ed-docs" className="ui-card">
      <div className="ui-chead">
        <h2 id="hr-ed-docs">{ht(language, "e_docs")}</h2>
        {canManage && (
          <button className="ui-btn" onClick={onAdd} type="button">
            <Icon name="upload" small />
            {ht(language, "e_add_file")}
          </button>
        )}
      </div>
      {person.documents.length === 0 ? (
        <p className="ui-muted">{ht(language, "e_doc_none")}</p>
      ) : (
        <ul className="ui-ulist">
          {person.documents.map((doc) => (
            <li key={doc.document_id}>
              <span>
                {doc.title}
                <span className="ui-sub2">
                  {codeText(language, "dk_", doc.kind)} · {doc.original_name}
                  {doc.expires_on !== null &&
                    ` · ${ht(language, "e_doc_expires")} ${dayText(doc.expires_on)}`}
                </span>
              </span>
              <span className="ui-actions">
                <a
                  className="ui-btn link"
                  href={api.documentUrl(propertyId, doc.document_id)}
                  rel="noopener"
                  target="_blank"
                >
                  {ht(language, "e_doc_open")}
                </a>
                {canManage && (doc.kind !== "ID_CARD" || canRemoveId) && (
                  <button
                    className="ui-btn link"
                    onClick={() => {
                      onRemove(doc.document_id);
                    }}
                    type="button"
                  >
                    {ht(language, "e_doc_remove")}
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="ui-muted ui-small">{ht(language, "e_docs_note")}</p>
    </section>
  );
}

function CardBox({
  language,
  card,
  onReplace,
}: {
  language: Language;
  card: { data: EmployeeCard | null; failed: boolean; reload: () => void };
  onReplace: () => void;
}) {
  const data = card.data;
  return (
    <section aria-labelledby="hr-ed-card" className="ui-card">
      <h2 id="hr-ed-card">{ht(language, "c_title")}</h2>
      {data === null ? (
        <Waiting
          failed={card.failed}
          language={language}
          onRetry={card.reload}
        />
      ) : (
        <>
          {data.cards.length === 0 ? (
            <p className="ui-muted">{ht(language, "c_none")}</p>
          ) : (
            <ul className="ui-ulist">
              {data.cards.map((one, index) => (
                <li key={one.number}>
                  <span>
                    {ht(language, "c_card", one.number, dayText(one.since))}
                    {index > 0 && <span className="ui-sub2">{one.reason}</span>}
                  </span>
                  {index === 0 && data.works ? (
                    <Chip tone="ok">{ht(language, "c_works")}</Chip>
                  ) : (
                    <Chip tone="neutral">{ht(language, "c_stopped")}</Chip>
                  )}
                </li>
              ))}
            </ul>
          )}
          {!data.works && data.left_on !== null && (
            <p className="ui-muted">
              {ht(language, "c_stopped_left", dayText(data.left_on))}
            </p>
          )}
          {data.can_replace && data.works && (
            <button className="ui-btn" onClick={onReplace} type="button">
              {ht(language, data.cards.length === 0 ? "c_make" : "c_replace")}
            </button>
          )}
          <p className="ui-muted ui-small">{ht(language, "c_note")}</p>
        </>
      )}
    </section>
  );
}

/* ---------- Change dialogs ---------- */

type Save = (body: Body) => Promise<EmployeeDetail>;

function DetailsDialog({
  language,
  person,
  choices,
  onSave,
  onSaved,
  onClose,
}: {
  language: Language;
  person: EmployeeDetail;
  choices: HrChoices | null;
  onSave: Save;
  onSaved: (value: EmployeeDetail) => void;
  onClose: () => void;
}) {
  const [nameEn, setNameEn] = useState(person.name_en);
  const [nameKm, setNameKm] = useState(person.name_km);
  const [phone, setPhone] = useState(person.phone ?? "");
  const [user, setUser] = useState(person.user?.actor_id ?? "");
  const [reason, setReason] = useState("");
  const { busy, failure, run } = useHrBusy(language);
  const users = [
    ...(person.user === null
      ? []
      : [
          {
            actor_id: person.user.actor_id,
            username: person.user.username,
            display_name: person.user.display_name,
          },
        ]),
    ...(choices?.free_users ?? []),
  ];
  return (
    <Dialog
      busy={busy}
      closeLabel={ht(language, "cancel")}
      onClose={onClose}
      onSubmit={(event) => {
        event.preventDefault();
        const body: Body = {
          step: "DETAILS",
          name_en: nameEn.trim(),
          name_km: nameKm.trim(),
        };
        if (phone.trim() !== "") body.phone = phone.trim();
        if (user !== "" && user !== person.user?.actor_id)
          body.user_actor_id = user;
        if (reason.trim() !== "") body.reason = reason.trim();
        run(() => onSave(body), onSaved);
      }}
      submitLabel={ht(language, "save")}
      title={ht(language, "e_edit")}
    >
      <Field id="hr-dd-en" label={ht(language, "e_name_en")}>
        <input
          id="hr-dd-en"
          maxLength={120}
          onChange={(event) => {
            setNameEn(event.target.value);
          }}
          required
          value={nameEn}
        />
      </Field>
      <Field id="hr-dd-km" label={ht(language, "e_name_km")}>
        <input
          id="hr-dd-km"
          lang="km"
          maxLength={120}
          onChange={(event) => {
            setNameKm(event.target.value);
          }}
          required
          value={nameKm}
        />
      </Field>
      <Field id="hr-dd-ph" label={ht(language, "e_phone")}>
        <input
          id="hr-dd-ph"
          inputMode="tel"
          maxLength={30}
          onChange={(event) => {
            setPhone(event.target.value);
          }}
          value={phone}
        />
      </Field>
      <Field id="hr-dd-user" label={ht(language, "e_signin")}>
        <select
          disabled={person.user !== null}
          id="hr-dd-user"
          onChange={(event) => {
            setUser(event.target.value);
          }}
          value={user}
        >
          <option value="">{ht(language, "e_no_signin")}</option>
          {users.map((one) => (
            <option key={one.actor_id} value={one.actor_id}>
              {one.display_name === null
                ? one.username
                : `${one.display_name} (${one.username})`}
            </option>
          ))}
        </select>
      </Field>
      <ReasonField
        id="hr-dd-why"
        language={language}
        onChange={setReason}
        optional
        value={reason}
      />
      <Failure text={failure} />
    </Dialog>
  );
}

function JobDialog({
  language,
  person,
  choices,
  onSave,
  onSaved,
  onClose,
}: {
  language: Language;
  person: EmployeeDetail;
  choices: HrChoices;
  onSave: Save;
  onSaved: (value: EmployeeDetail) => void;
  onClose: () => void;
}) {
  const [job, setJob] = useState(
    person.job_title?.id ?? choices.job_titles[0]?.id ?? "",
  );
  const [shift, setShift] = useState<CaretakerShift>(
    caretakerShift(person.shift_code),
  );
  const [dayOff, setDayOff] = useState(person.usual_day_off ?? 7);
  const [from, setFrom] = useState(choices.today);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { busy, failure, run } = useHrBusy(language);
  return (
    <Dialog
      busy={busy}
      closeLabel={ht(language, "cancel")}
      onClose={onClose}
      onSubmit={(event) => {
        event.preventDefault();
        if (from === "") {
          setError(ht(language, "day_bad"));
          return;
        }
        if (reason.trim() === "") {
          setError(ht(language, "say_why"));
          return;
        }
        setError(null);
        run(
          () =>
            onSave({
              step: "JOB",
              ...jobBody(choices.job_titles, job, shift, dayOff),
              effective_date: from,
              reason: reason.trim(),
            }),
          onSaved,
        );
      }}
      submitLabel={ht(language, "save")}
      title={ht(language, "e_change_job_t", nameOf(language, person))}
    >
      <JobFields
        dayOff={dayOff}
        job={job}
        jobs={choices.job_titles}
        language={language}
        prefix="hr-jd"
        setDayOff={setDayOff}
        setJob={setJob}
        setShift={setShift}
        shift={shift}
      />
      <Field
        id="hr-jd-from"
        label={ht(language, "e_from")}
        note={ht(language, "required")}
      >
        <DateInput
          id="hr-jd-from"
          language={language}
          onChange={setFrom}
          value={from}
        />
      </Field>
      <ReasonField
        id="hr-jd-why"
        language={language}
        onChange={setReason}
        value={reason}
      />
      <p className="ui-muted ui-small">{ht(language, "e_history_note")}</p>
      <Failure text={error ?? failure} />
    </Dialog>
  );
}

function PayDialog({
  language,
  person,
  today,
  onSave,
  onSaved,
  onClose,
}: {
  language: Language;
  person: EmployeeDetail;
  today: string;
  onSave: Save;
  onSaved: (value: EmployeeDetail) => void;
  onClose: () => void;
}) {
  const pay = person.pay ?? null;
  const [salary, setSalary] = useState(
    pay === null ? "" : (pay.monthly_salary_usd_cents / 100).toFixed(2),
  );
  const [method, setMethod] = useState<PayMethod>(
    pay?.payment_method ?? "CASH_USD",
  );
  const [abaName, setAbaName] = useState(pay?.aba_account_name ?? "");
  const [abaNumber, setAbaNumber] = useState(pay?.aba_account_number ?? "");
  const [from, setFrom] = useState(
    today < person.hired_on ? person.hired_on : today,
  );
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { busy, failure, run } = useHrBusy(language);
  return (
    <Dialog
      busy={busy}
      closeLabel={ht(language, "cancel")}
      onClose={onClose}
      onSubmit={(event) => {
        event.preventDefault();
        const cents = centsOf(salary);
        if (cents === null) {
          setError(ht(language, "amount_bad"));
          return;
        }
        if (from === "") {
          setError(ht(language, "day_bad"));
          return;
        }
        if (reason.trim() === "") {
          setError(ht(language, "say_why"));
          return;
        }
        setError(null);
        run(
          () =>
            onSave({
              step: "PAY",
              monthly_salary_usd_cents: cents,
              payment_method: method,
              ...(method === "ABA"
                ? {
                    aba_account_name: abaName.trim(),
                    aba_account_number: abaNumber.trim(),
                  }
                : {}),
              effective_date: from,
              reason: reason.trim(),
            }),
          onSaved,
        );
      }}
      submitLabel={ht(language, "save")}
      title={ht(language, "e_change_t", nameOf(language, person))}
    >
      <PayFields
        abaName={abaName}
        abaNumber={abaNumber}
        language={language}
        method={method}
        prefix="hr-pd"
        salary={salary}
        setAbaName={setAbaName}
        setAbaNumber={setAbaNumber}
        setMethod={setMethod}
        setSalary={setSalary}
      />
      <Field
        id="hr-pd-from"
        label={ht(language, "e_from")}
        note={ht(language, "required")}
      >
        <DateInput
          id="hr-pd-from"
          language={language}
          onChange={setFrom}
          value={from}
        />
      </Field>
      <ReasonField
        id="hr-pd-why"
        language={language}
        onChange={setReason}
        value={reason}
      />
      <Failure text={error ?? failure} />
    </Dialog>
  );
}

function IdentityDialog({
  language,
  person,
  onSave,
  onSaved,
  onClose,
}: {
  language: Language;
  person: EmployeeDetail;
  onSave: Save;
  onSaved: (value: EmployeeDetail) => void;
  onClose: () => void;
}) {
  const identity = person.identity ?? null;
  const [type, setType] = useState(identity?.id_type ?? "NATIONAL_ID");
  const [number, setNumber] = useState(identity?.id_number ?? "");
  const [birth, setBirth] = useState(identity?.date_of_birth ?? "");
  const [birthPlace, setBirthPlace] = useState(identity?.place_of_birth ?? "");
  const [address, setAddress] = useState(identity?.home_address ?? "");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { busy, failure, run } = useHrBusy(language);
  return (
    <Dialog
      busy={busy}
      closeLabel={ht(language, "cancel")}
      onClose={onClose}
      onSubmit={(event) => {
        event.preventDefault();
        if (reason.trim() === "") {
          setError(ht(language, "say_why"));
          return;
        }
        setError(null);
        const body: Body = {
          step: "IDENTITY",
          id_type: type,
          reason: reason.trim(),
        };
        if (number.trim() !== "") body.id_number = number.trim();
        if (birth !== "") body.date_of_birth = birth;
        if (birthPlace.trim() !== "") body.place_of_birth = birthPlace.trim();
        if (address.trim() !== "") body.home_address = address.trim();
        run(() => onSave(body), onSaved);
      }}
      submitLabel={ht(language, "save")}
      title={ht(language, "e_change_id")}
    >
      <Field id="hr-id-type" label={ht(language, "e_id_type")}>
        <select
          id="hr-id-type"
          onChange={(event) => {
            setType(event.target.value);
          }}
          value={type}
        >
          {(["NATIONAL_ID", "PASSPORT", "OTHER"] as const).map((code) => (
            <option key={code} value={code}>
              {codeText(language, "id_", code)}
            </option>
          ))}
        </select>
      </Field>
      <Field
        id="hr-id-no"
        label={ht(language, "e_id")}
        note={ht(language, "optional")}
      >
        <input
          id="hr-id-no"
          maxLength={60}
          onChange={(event) => {
            setNumber(event.target.value);
          }}
          value={number}
        />
      </Field>
      <Field
        id="hr-id-dob"
        label={ht(language, "e_birth")}
        note={ht(language, "optional")}
      >
        <DateInput
          id="hr-id-dob"
          language={language}
          onChange={setBirth}
          value={birth}
        />
      </Field>
      <Field
        id="hr-id-pob"
        label={ht(language, "e_birth_place")}
        note={ht(language, "optional")}
      >
        <input
          id="hr-id-pob"
          maxLength={200}
          onChange={(event) => {
            setBirthPlace(event.target.value);
          }}
          value={birthPlace}
        />
      </Field>
      <Field
        id="hr-id-addr"
        label={ht(language, "e_address")}
        note={ht(language, "optional")}
      >
        <textarea
          id="hr-id-addr"
          maxLength={500}
          onChange={(event) => {
            setAddress(event.target.value);
          }}
          rows={2}
          value={address}
        />
      </Field>
      <ReasonField
        id="hr-id-why"
        language={language}
        onChange={setReason}
        value={reason}
      />
      <Failure text={error ?? failure} />
    </Dialog>
  );
}

function LeaveDialog({
  language,
  person,
  today,
  onSave,
  onSaved,
  onClose,
}: {
  language: Language;
  person: EmployeeDetail;
  today: string;
  onSave: Save;
  onSaved: (value: EmployeeDetail, day: string) => void;
  onClose: () => void;
}) {
  const [day, setDay] = useState(today);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { busy, failure, run } = useHrBusy(language);
  return (
    <Dialog
      busy={busy}
      closeLabel={ht(language, "cancel")}
      onClose={onClose}
      onSubmit={(event) => {
        event.preventDefault();
        if (day === "") {
          setError(ht(language, "day_bad"));
          return;
        }
        if (reason.trim() === "") {
          setError(ht(language, "say_why"));
          return;
        }
        setError(null);
        run(
          () =>
            onSave({
              step: "LEAVE",
              effective_date: day,
              reason: reason.trim(),
            }),
          (value) => {
            onSaved(value, day);
          },
        );
      }}
      submitLabel={ht(language, "e_set_end")}
      title={ht(language, "e_set_end_t", nameOf(language, person))}
    >
      <Field
        id="hr-lv-day"
        label={ht(language, "e_end")}
        note={ht(language, "required")}
      >
        <DateInput
          id="hr-lv-day"
          language={language}
          min={person.hired_on}
          onChange={setDay}
          value={day}
        />
      </Field>
      <p>{ht(language, "e_end_note")}</p>
      {person.user !== null && (
        <p className="ui-muted">
          {ht(
            language,
            "e_end_signin",
            person.user.display_name ?? person.user.username,
          )}
        </p>
      )}
      <ReasonField
        id="hr-lv-why"
        language={language}
        onChange={setReason}
        value={reason}
      />
      <Failure text={error ?? failure} />
    </Dialog>
  );
}

function FileDialog({
  language,
  propertyId,
  api,
  person,
  onSaved,
  onClose,
}: {
  language: Language;
  propertyId: string;
  api: HrApi;
  person: EmployeeDetail;
  onSaved: (value: EmployeeDetail, title: string) => void;
  onClose: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState<(typeof DOC_KINDS)[number]>("CONTRACT");
  const [title, setTitle] = useState("");
  const [expires, setExpires] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { busy, failure, run } = useHrBusy(language);
  return (
    <Dialog
      busy={busy}
      closeLabel={ht(language, "cancel")}
      onClose={onClose}
      onSubmit={(event) => {
        event.preventDefault();
        const named =
          title.trim() === "" ? codeText(language, "dk_", kind) : title.trim();
        if (file === null) {
          setError(ht(language, "e_doc_types"));
          return;
        }
        setError(null);
        run(
          () =>
            api.addDocument(propertyId, person.employee_id, file, {
              kind,
              title: named,
              ...(expires === "" ? {} : { expires_on: expires }),
            }),
          (value) => {
            onSaved(value, named);
          },
        );
      }}
      submitLabel={ht(language, "e_add_file")}
      title={ht(language, "e_add_file")}
    >
      <Field id="hr-fd-kind" label={ht(language, "e_doc_kind")}>
        <select
          id="hr-fd-kind"
          onChange={(event) => {
            setKind(event.target.value as (typeof DOC_KINDS)[number]);
          }}
          value={kind}
        >
          {DOC_KINDS.map((code) => (
            <option key={code} value={code}>
              {codeText(language, "dk_", code)}
            </option>
          ))}
        </select>
      </Field>
      <Field
        id="hr-fd-title"
        label={ht(language, "e_doc_title")}
        note={ht(language, "optional")}
      >
        <input
          id="hr-fd-title"
          maxLength={120}
          onChange={(event) => {
            setTitle(event.target.value);
          }}
          value={title}
        />
      </Field>
      <Field
        id="hr-fd-file"
        label={ht(language, "e_file")}
        help={ht(language, "e_doc_types")}
        note={ht(language, "required")}
      >
        <input
          accept="image/jpeg,image/png,application/pdf"
          id="hr-fd-file"
          onChange={(event) => {
            setFile(event.target.files?.[0] ?? null);
          }}
          type="file"
        />
      </Field>
      <Field
        id="hr-fd-exp"
        label={ht(language, "e_doc_expires")}
        note={ht(language, "optional")}
      >
        <DateInput
          id="hr-fd-exp"
          language={language}
          onChange={setExpires}
          value={expires}
        />
      </Field>
      <p className="ui-muted ui-small">{ht(language, "e_docs_note")}</p>
      <Failure text={error ?? failure} />
    </Dialog>
  );
}
