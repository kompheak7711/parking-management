// HRIS phase 6: Office › Employees and payroll (Employees, Salary loans, Payroll, Attendance).
// The server checks every right, rule and amount again; this client reads and sends. Money is
// whole US cents, days are yyyy-mm-dd and times are HH:MM in Phnom Penh.

export type ShiftCode = "MORNING" | "AFTERNOON" | "NIGHT" | "OFFICE";
/** The shifts only the Property caretaker works (owner 06/11/2026). */
export type CaretakerShift = Exclude<ShiftCode, "OFFICE">;
export type ReportRole =
  | "CLEANER"
  | "TECHNICIAN"
  | "CARETAKER"
  | "METER_READER"
  | "AUTHORIZER";
export type EmployeeState = "ACTIVE" | "LEAVING" | "LEFT" | "STARTS_LATER";
export type PayMethod = "CASH_USD" | "ABA";

export interface Named {
  name_en: string;
  name_km: string;
}

export interface JobTitle extends Named {
  id: string;
  code: string;
  /** Only the Property caretaker works shifts; every other job works OFFICE hours. */
  uses_shifts?: boolean;
  /** Days off a month, taken on request (caretaker and cleaner: 2); null = a usual day off. */
  days_off_per_month?: number | null;
}

export interface Shift extends Named {
  code: ShiftCode;
  starts_at: string;
  ends_at: string;
  break_starts_at?: string | null;
  break_ends_at?: string | null;
}

export interface PayTerms {
  effective_date: string;
  monthly_salary_usd_cents: number;
  payment_method: PayMethod;
  aba_account_name: string | null;
  aba_account_number: string | null;
}

export interface TelegramLink {
  link_id: string;
  telegram_user_id: number;
  report_role: ReportRole;
  linked_at: string;
  unlinked_at?: string | null;
  unlink_reason?: string | null;
}

export interface Employee extends Named {
  employee_id: string;
  employee_code: string;
  phone: string | null;
  version: number;
  user: {
    actor_id: string;
    username: string;
    display_name: string | null;
    state: string;
  } | null;
  hired_on: string;
  left_on: string | null;
  state: EmployeeState;
  job_title: JobTitle | null;
  shift_code: ShiftCode | null;
  usual_day_off: number | null;
  /** Only with See salaries. */
  pay?: PayTerms | null;
  telegram: TelegramLink[];
}

export interface HistoryLine {
  event_id: string;
  event_type: "HIRED" | "JOB_CHANGE" | "SHIFT_CHANGE" | "LEFT";
  effective_date: string;
  job_title_id: string | null;
  job_title_en: string | null;
  job_title_km: string | null;
  shift_code: ShiftCode | null;
  usual_day_off: number | null;
  reason: string | null;
  at: string;
  by: string | null;
}

export interface EmployeeDocument {
  document_id: string;
  kind: "ID_CARD" | "CONTRACT" | "CERTIFICATE" | "OTHER";
  title: string;
  original_name: string;
  media_type: string;
  byte_size: number;
  expires_on: string | null;
  at: string;
}

export interface EmployeeDetail extends Employee {
  can_see_salaries: boolean;
  history: HistoryLine[];
  pay_history?:
    | (PayTerms & {
        pay_term_id: string;
        reason: string | null;
        at: string;
        by: string | null;
      })[]
    | null;
  identity?: {
    id_type: string;
    id_number: string | null;
    date_of_birth: string | null;
    place_of_birth?: string | null;
    nssf_number?: string | null;
    home_address: string | null;
  } | null;
  documents: EmployeeDocument[];
  telegram_history: TelegramLink[];
}

export interface HrChoices {
  today: string;
  shifts: Shift[];
  job_titles: JobTitle[];
  free_users: {
    actor_id: string;
    username: string;
    display_name: string | null;
  }[];
  next_employee_code: string;
  pay_day: number;
  loan_pct: number;
  is_owner: boolean;
  can_manage: boolean;
  can_see_salaries: boolean;
  can_change_salaries: boolean;
}

export interface StaffRequest {
  request_id: string;
  telegram_user_id: number;
  given_name: string;
  phone: string | null;
  received_at: string;
}

export interface EmployeeCard {
  works: boolean;
  left_on: string | null;
  can_replace: boolean;
  cards: { number: number; since: string; reason: string; by: string | null }[];
}

export type LoanState =
  | "WAITING"
  | "APPROVED"
  | "PAID_OUT"
  | "REPAID"
  | "REFUSED";

export interface Loan extends Named {
  loan_id: string;
  loan_number: string;
  employee_id: string;
  employee_code: string;
  state: LoanState;
  amount_usd_cents: number;
  repaid_usd_cents: number;
  owed_usd_cents: number;
  repayment_plan: "NEXT_SALARY" | "MONTHLY_AMOUNT";
  monthly_repayment_usd_cents: number | null;
  payout_method: "CASH_USD" | "ABA_JOINT";
  request_channel: "APP" | "TELEGRAM";
  requested_on: string;
  reason: string;
  paid_on: string | null;
  /** Taken back in approved payrolls, oldest first. */
  repayments: {
    run_number: string;
    salary_month: string;
    amount_usd_cents: number;
  }[];
  created_at: string;
  created_by: string | null;
  decision: {
    decision: "APPROVED" | "REFUSED";
    reason: string | null;
    own_request_note: string | null;
    at: string;
    by: string | null;
  } | null;
}

export interface LoanList {
  loans: Loan[];
  today: string;
  loan_pct: number;
  open_max: number;
  can_prepare: boolean;
  can_approve: boolean;
}

export type PayrollState =
  | "LIST_MADE"
  | "SENT_FOR_APPROVAL"
  | "SENT_BACK"
  | "APPROVED";

export interface PayrollEvent {
  event_type: PayrollState;
  reason: string | null;
  own_request_note: string | null;
  at: string;
  by: string | null;
}

export interface PayrollRun {
  run_id: string;
  run_number: string;
  salary_month: string;
  run_kind: "REGULAR" | "CORRECTION";
  corrects_run_id: string | null;
  pay_date: string;
  state: PayrollState;
  events: PayrollEvent[];
  earnings_usd_cents: number;
  deductions_usd_cents: number;
  net_pay_usd_cents: number;
}

export interface SalaryComponent extends Named {
  code: string;
  direction: "EARNING" | "DEDUCTION";
  in_use: boolean;
}

export interface PayrollList {
  runs: PayrollRun[];
  today: string;
  pay_day: number;
  next_month: string;
  components: SalaryComponent[];
  can_prepare: boolean;
  can_approve: boolean;
  can_pay: boolean;
}

export interface PayrollLine extends Named {
  line_id: string;
  component: string;
  direction: "EARNING" | "DEDUCTION";
  amount_usd_cents: number;
  source: "LIST" | "ATTENDANCE" | "MANUAL";
  reason: string | null;
  days_worked: number | null;
  days_in_month: number | null;
  hours: number | null;
  salary_loan_id: string | null;
}

export interface Payslip {
  payslip_id: string;
  entry_id: string | null;
  earnings_usd_cents: number;
  deductions_usd_cents: number;
  net_pay_usd_cents: number;
  payment: {
    payment_id: string;
    paid_on: string;
    method: "CASH_USD" | "ABA_JOINT";
    amount_usd_cents: number;
    bank_reference: string | null;
    own_request_note: string | null;
  } | null;
}

export interface PayrollPerson extends Named {
  employee_id: string;
  employee_code: string;
  payment_method: PayMethod | null;
  aba_account_name: string | null;
  aba_account_number: string | null;
  lines: PayrollLine[];
  earnings_usd_cents: number;
  deductions_usd_cents: number;
  net_pay_usd_cents: number;
  payslip: Payslip | null;
}

export interface PayrollDetail extends PayrollRun {
  people: PayrollPerson[];
}

export type DayStatus =
  | "WORKED"
  | "ABSENT"
  | "LEAVE_ANNUAL"
  | "LEAVE_SICK"
  | "LEAVE_UNPAID"
  | "DAY_OFF";

export interface Scan {
  scan_id: string;
  direction: "IN" | "OUT";
  method: "PHONE" | "CARD";
  place_en: string | null;
  place_km: string | null;
  scanned_at: string;
  distance_m: number | null;
  needs_check: boolean;
  accepted: boolean;
  card_reason: string | null;
  card_reason_text: string | null;
  has_photo: boolean;
  scanned_by_en: string | null;
  scanned_by_km: string | null;
}

export interface DayLine extends Named {
  employee_id: string;
  employee_code: string;
  job_en: string | null;
  job_km: string | null;
  uses_shifts?: boolean;
  planned_shift: ShiftCode | null;
  day_off: boolean | null;
  entry_id: string | null;
  shift_code: ShiftCode | null;
  status: DayStatus | null;
  check_in_at: string | null;
  check_out_at: string | null;
  source: "MANUAL" | "QR_PHONE" | "QR_CARD" | null;
  reason: string | null;
  fixed: boolean;
  late_minutes: number | null;
  no_check_out: boolean | null;
  scans: Scan[];
}

export interface AttendanceDay {
  day: string;
  today: string;
  locked: boolean;
  can_manage: boolean;
  shifts: Shift[];
  people: DayLine[];
}

export interface AttendanceWeek {
  monday: string;
  days_off_per_week: number;
  people: (Named & {
    employee_id: string;
    employee_code: string;
    uses_shifts?: boolean;
    /** Days off a month on request; null = a usual day off each week. */
    days_off_per_month?: number | null;
    /** Planned days off in each month the week touches (yyyy-mm-01). */
    month_days_off?: { month: string; planned: number }[];
    days: {
      work_date: string;
      works: boolean;
      shift_code: ShiftCode | null;
      day_off: boolean | null;
      planned: boolean | null;
    }[];
  })[];
}

export interface MonthLine extends Named {
  employee_id: string;
  employee_code: string;
  days_worked: number;
  times_late: number;
  days_absent: number;
  leave_annual: number;
  leave_sick: number;
  leave_unpaid: number;
  days_off: number;
  no_entry: number;
  no_check_out: number;
  overtime_hours: number;
  overtime_night_hours: number;
}

export interface AttendanceMonth {
  month: string;
  locked: boolean;
  people: MonthLine[];
}

export interface OvertimeRequest extends Named {
  request_id: string;
  overtime_number: string;
  employee_id: string;
  employee_code: string;
  work_date: string;
  starts_at: string;
  ends_at: string;
  reason: string;
  normal_hours: number;
  night_hours: number;
  asked_by: string | null;
  asked_at: string;
  decision: "APPROVED" | "REFUSED" | null;
  decision_reason: string | null;
  decided_by: string | null;
  decided_at: string | null;
  counts: boolean;
}

export interface OvertimeList {
  month: string;
  can_request: boolean;
  can_approve: boolean;
  requests: OvertimeRequest[];
}

export interface Place extends Named {
  place_id: string;
  code: string;
  latitude: number | null;
  longitude: number | null;
  pin_set_at: string | null;
  qr_made_at: string | null;
  qr_count: number;
}

export interface PlaceList {
  is_owner: boolean;
  qr_distance_m: number;
  places: Place[];
}

export type Body = Record<string, unknown>;

export interface HrApi {
  employees: (propertyId: string) => Promise<Employee[]>;
  employee: (propertyId: string, employeeId: string) => Promise<EmployeeDetail>;
  choices: (propertyId: string) => Promise<HrChoices>;
  addEmployee: (propertyId: string, body: Body) => Promise<EmployeeDetail>;
  employeeStep: (
    propertyId: string,
    employee: { employee_id: string; version: number },
    body: Body,
  ) => Promise<EmployeeDetail>;
  addDocument: (
    propertyId: string,
    employeeId: string,
    file: File,
    form: { kind: string; title: string; expires_on?: string },
  ) => Promise<EmployeeDetail>;
  documentUrl: (propertyId: string, documentId: string) => string;
  staffRequests: (propertyId: string) => Promise<StaffRequest[]>;
  decideStaffRequest: (
    propertyId: string,
    requestId: string,
    body: Body,
  ) => Promise<void>;
  card: (propertyId: string, employeeId: string) => Promise<EmployeeCard>;
  newCard: (
    propertyId: string,
    employeeId: string,
    reason: string,
  ) => Promise<string>;
  loans: (propertyId: string) => Promise<LoanList>;
  addLoan: (propertyId: string, body: Body) => Promise<void>;
  decideLoan: (propertyId: string, loanId: string, body: Body) => Promise<void>;
  payOutLoan: (
    propertyId: string,
    loanId: string,
    paidOn: string,
  ) => Promise<void>;
  payrolls: (propertyId: string) => Promise<PayrollList>;
  payroll: (propertyId: string, runId: string) => Promise<PayrollDetail>;
  makePayroll: (propertyId: string, month: string) => Promise<PayrollDetail>;
  makeCorrection: (
    propertyId: string,
    runId: string,
    reason: string,
  ) => Promise<PayrollDetail>;
  payrollStep: (
    propertyId: string,
    runId: string,
    body: Body,
  ) => Promise<PayrollDetail>;
  paySalary: (
    propertyId: string,
    payslipId: string,
    body: Body,
  ) => Promise<void>;
  reversePayment: (
    propertyId: string,
    paymentId: string,
    reason: string,
  ) => Promise<void>;
  day: (propertyId: string, day: string | null) => Promise<AttendanceDay>;
  week: (propertyId: string, monday: string | null) => Promise<AttendanceWeek>;
  month: (propertyId: string, month: string | null) => Promise<AttendanceMonth>;
  enterDay: (propertyId: string, body: Body) => Promise<AttendanceDay>;
  planDay: (propertyId: string, body: Body) => Promise<AttendanceWeek>;
  overtime: (propertyId: string, month: string | null) => Promise<OvertimeList>;
  askOvertime: (propertyId: string, body: Body) => Promise<OvertimeList>;
  decideOvertime: (
    propertyId: string,
    requestId: string,
    body: Body,
  ) => Promise<OvertimeList>;
  acceptScan: (
    propertyId: string,
    scanId: string,
    note: string | null,
  ) => Promise<void>;
  photoUrl: (propertyId: string, scanId: string) => string;
  places: (propertyId: string) => Promise<PlaceList>;
  setPin: (
    propertyId: string,
    placeId: string,
    body: Body,
  ) => Promise<PlaceList>;
  newPlaceQr: (
    propertyId: string,
    placeId: string,
    reason: string,
  ) => Promise<string>;
}

export class HrError extends Error {
  /** The HTTP status when the server answered (403, 404, 409, 412, 422) and its words. */
  constructor(
    readonly status: number | null = null,
    readonly detail: string | null = null,
  ) {
    super(detail ?? "The command was not completed.");
    this.name = "HrError";
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function csrfToken(): string {
  const prefix = "__Host-prm_csrf=";
  const entry = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  if (entry === undefined) throw new HrError();
  const token = decodeURIComponent(entry.slice(prefix.length));
  if (token === "") throw new HrError();
  return token;
}

async function request(
  path: string,
  init: RequestInit = { method: "GET" },
): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(path, { credentials: "include", ...init });
  } catch {
    throw new HrError();
  }
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const detail =
      isObject(payload) && typeof payload.detail === "string"
        ? payload.detail
        : null;
    throw new HrError(response.status, detail);
  }
  if (!isObject(payload) || !("data" in payload)) throw new HrError();
  return payload.data;
}

function post(body: unknown, version?: number): RequestInit {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-CSRF-Token": csrfToken(),
  };
  if (version !== undefined) headers["If-Match"] = `"${String(version)}"`;
  return { method: "POST", headers, body: JSON.stringify(body) };
}

// The server shapes each answer (backend hr_api.py); this checks only that it is an object.
// eslint-disable-next-line @typescript-eslint/no-unnecessary-type-parameters
function object<T>(value: unknown): T {
  if (!isObject(value)) throw new HrError();
  return value as T;
}

function array<T>(value: unknown): T[] {
  if (!Array.isArray(value)) throw new HrError();
  return value as T[];
}

function query(name: string, value: string | null): string {
  return value === null ? "" : `?${name}=${encodeURIComponent(value)}`;
}

const base = (propertyId: string) =>
  `/api/v1/properties/${encodeURIComponent(propertyId)}/hr`;
const id = encodeURIComponent;

export const hrApi: HrApi = {
  employees: async (p) =>
    array<Employee>(await request(`${base(p)}/employees`)),
  employee: async (p, e) =>
    object<EmployeeDetail>(await request(`${base(p)}/employees/${id(e)}`)),
  choices: async (p) => object<HrChoices>(await request(`${base(p)}/choices`)),
  addEmployee: async (p, body) =>
    object<EmployeeDetail>(await request(`${base(p)}/employees`, post(body))),
  employeeStep: async (p, employee, body) =>
    object<EmployeeDetail>(
      await request(
        `${base(p)}/employees/${id(employee.employee_id)}/steps`,
        post(body, employee.version),
      ),
    ),
  addDocument: async (p, e, file, form) => {
    const params = new URLSearchParams({
      kind: form.kind,
      title: form.title,
      file_name: file.name,
    });
    if (form.expires_on !== undefined && form.expires_on !== "")
      params.set("expires_on", form.expires_on);
    return object<EmployeeDetail>(
      await request(
        `${base(p)}/employees/${id(e)}/documents?${params.toString()}`,
        {
          method: "POST",
          headers: { "Content-Type": file.type, "X-CSRF-Token": csrfToken() },
          body: file,
        },
      ),
    );
  },
  documentUrl: (p, d) => `${base(p)}/documents/${id(d)}/file`,
  staffRequests: async (p) =>
    array<StaffRequest>(await request(`${base(p)}/staff-requests`)),
  decideStaffRequest: async (p, r, body) => {
    await request(`${base(p)}/staff-requests/${id(r)}/decision`, post(body));
  },
  card: async (p, e) =>
    object<EmployeeCard>(await request(`${base(p)}/employees/${id(e)}/card`)),
  newCard: async (p, e, reason) => {
    const made = object<{ code: string }>(
      await request(`${base(p)}/employees/${id(e)}/card-qr`, post({ reason })),
    );
    return made.code;
  },
  loans: async (p) => object<LoanList>(await request(`${base(p)}/loans`)),
  addLoan: async (p, body) => {
    await request(`${base(p)}/loans`, post(body));
  },
  decideLoan: async (p, l, body) => {
    await request(`${base(p)}/loans/${id(l)}/decision`, post(body));
  },
  payOutLoan: async (p, l, paidOn) => {
    await request(
      `${base(p)}/loans/${id(l)}/pay-out`,
      post({ paid_on: paidOn }),
    );
  },
  payrolls: async (p) =>
    object<PayrollList>(await request(`${base(p)}/payrolls`)),
  payroll: async (p, r) =>
    object<PayrollDetail>(await request(`${base(p)}/payrolls/${id(r)}`)),
  makePayroll: async (p, month) =>
    object<PayrollDetail>(
      await request(`${base(p)}/payrolls`, post({ salary_month: month })),
    ),
  makeCorrection: async (p, r, reason) =>
    object<PayrollDetail>(
      await request(
        `${base(p)}/payrolls/${id(r)}/correction`,
        post({ reason }),
      ),
    ),
  payrollStep: async (p, r, body) =>
    object<PayrollDetail>(
      await request(`${base(p)}/payrolls/${id(r)}/steps`, post(body)),
    ),
  paySalary: async (p, s, body) => {
    await request(`${base(p)}/payslips/${id(s)}/payment`, post(body));
  },
  reversePayment: async (p, payment, reason) => {
    await request(
      `${base(p)}/salary-payments/${id(payment)}/reversal`,
      post({ reason }),
    );
  },
  day: async (p, day) =>
    object<AttendanceDay>(
      await request(`${base(p)}/attendance/day${query("day", day)}`),
    ),
  week: async (p, monday) =>
    object<AttendanceWeek>(
      await request(`${base(p)}/attendance/week${query("monday", monday)}`),
    ),
  month: async (p, month) =>
    object<AttendanceMonth>(
      await request(`${base(p)}/attendance/month${query("month", month)}`),
    ),
  enterDay: async (p, body) =>
    object<AttendanceDay>(
      await request(`${base(p)}/attendance/entries`, post(body)),
    ),
  planDay: async (p, body) =>
    object<AttendanceWeek>(
      await request(`${base(p)}/attendance/plan`, post(body)),
    ),
  overtime: async (p, month) =>
    object<OvertimeList>(
      await request(`${base(p)}/overtime${query("month", month)}`),
    ),
  askOvertime: async (p, body) =>
    object<OvertimeList>(await request(`${base(p)}/overtime`, post(body))),
  decideOvertime: async (p, r, body) =>
    object<OvertimeList>(
      await request(`${base(p)}/overtime/${id(r)}/decision`, post(body)),
    ),
  acceptScan: async (p, s, note) => {
    await request(
      `${base(p)}/attendance/scans/${id(s)}/acceptance`,
      post(note === null ? {} : { note }),
    );
  },
  photoUrl: (p, s) => `${base(p)}/attendance/scans/${id(s)}/photo`,
  places: async (p) =>
    object<PlaceList>(await request(`${base(p)}/attendance/places`)),
  setPin: async (p, place, body) =>
    object<PlaceList>(
      await request(
        `${base(p)}/attendance/places/${id(place)}/pin`,
        post(body),
      ),
    ),
  newPlaceQr: async (p, place, reason) => {
    const made = object<{ code: string }>(
      await request(
        `${base(p)}/attendance/places/${id(place)}/qr`,
        post({ reason }),
      ),
    );
    return made.code;
  },
};
