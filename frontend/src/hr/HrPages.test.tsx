// HRIS phase 6: the four HR screens with a fake server. Sample names and salaries only.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AttendancePage } from "./AttendancePage";
import { failureText } from "./common";
import { EmployeesPage } from "./EmployeesPage";
import {
  type AttendanceDay,
  type AttendanceWeek,
  type Employee,
  type EmployeeDetail,
  type HrApi,
  type HrChoices,
  HrError,
  type LoanList,
  type OvertimeList,
  type PayrollDetail,
  type PayrollList,
  type PlaceList,
} from "./hrClient";
import { LoansPage } from "./LoansPage";
import { PayrollPage } from "./PayrollPage";

const PROPERTY = "prop-1";

const CLEANER = {
  id: "job-1",
  code: "CLEANER",
  name_en: "Cleaner",
  name_km: "អ្នកសម្អាត",
  uses_shifts: false,
};

const CARETAKER = {
  id: "job-2",
  code: "CARETAKER",
  name_en: "Property Caretaker",
  name_km: "អ្នកថែរក្សាអគារ",
  uses_shifts: true,
  days_off_per_month: 2,
};

const DARA: Employee = {
  employee_id: "emp-1",
  employee_code: "E-001",
  name_en: "Chan Dara",
  name_km: "ចាន់ ដារ៉ា",
  phone: "012 345 678",
  version: 3,
  user: null,
  hired_on: "2026-08-22",
  left_on: null,
  state: "ACTIVE",
  job_title: CLEANER,
  shift_code: "MORNING",
  usual_day_off: 7,
  pay: {
    effective_date: "2026-08-22",
    monthly_salary_usd_cents: 30_000,
    payment_method: "ABA",
    aba_account_name: "SAMPLE NAME",
    aba_account_number: "000 123 456",
  },
  telegram: [
    {
      link_id: "link-1",
      telegram_user_id: 9001,
      report_role: "CLEANER",
      linked_at: "2026-11-04T10:00:00+07:00",
    },
  ],
};

const SOK: Employee = {
  ...DARA,
  employee_id: "emp-2",
  employee_code: "E-002",
  name_en: "Sok Vanna",
  name_km: "សុខ វណ្ណា",
  state: "LEFT",
  left_on: "2026-10-31",
  telegram: [],
};

const DETAIL: EmployeeDetail = {
  ...DARA,
  can_see_salaries: true,
  history: [
    {
      event_id: "ev-1",
      event_type: "HIRED",
      effective_date: "2026-08-22",
      job_title_id: "job-1",
      job_title_en: "Cleaner",
      job_title_km: "អ្នកសម្អាត",
      shift_code: "MORNING",
      usual_day_off: 7,
      reason: "New employee",
      at: "2026-11-04T10:00:00+07:00",
      by: "Owner",
    },
  ],
  identity: null,
  documents: [],
  telegram_history: [],
};

const CHOICES: HrChoices = {
  today: "2026-11-05",
  shifts: [
    {
      code: "MORNING",
      starts_at: "06:30",
      ends_at: "15:30",
      name_en: "Morning",
      name_km: "វេនព្រឹក",
    },
  ],
  job_titles: [CLEANER, CARETAKER],
  free_users: [],
  next_employee_code: "E-003",
  pay_day: 5,
  loan_pct: 5000,
  is_owner: false,
  can_manage: true,
  can_see_salaries: true,
  can_change_salaries: true,
};

const LOANS: LoanList = {
  today: "2026-11-05",
  loan_pct: 5000,
  open_max: 1,
  can_prepare: true,
  can_approve: true,
  loans: [
    {
      loan_id: "loan-1",
      loan_number: "SL260001",
      employee_id: "emp-1",
      employee_code: "E-001",
      name_en: "Chan Dara",
      name_km: "ចាន់ ដារ៉ា",
      state: "WAITING",
      amount_usd_cents: 10_000,
      repaid_usd_cents: 0,
      owed_usd_cents: 10_000,
      repayment_plan: "NEXT_SALARY",
      monthly_repayment_usd_cents: null,
      payout_method: "CASH_USD",
      request_channel: "TELEGRAM",
      requested_on: "2026-11-04",
      reason: "School fees",
      paid_on: null,
      repayments: [],
      created_at: "2026-11-04T10:00:00+07:00",
      created_by: "Accountant",
      decision: null,
    },
  ],
};

const RUN: PayrollDetail = {
  run_id: "run-1",
  run_number: "PAY260001",
  salary_month: "2026-10-01",
  run_kind: "REGULAR",
  corrects_run_id: null,
  pay_date: "2026-11-05",
  state: "LIST_MADE",
  events: [
    {
      event_type: "LIST_MADE",
      reason: null,
      own_request_note: null,
      at: "2026-11-01T08:00:00+07:00",
      by: "App",
    },
  ],
  earnings_usd_cents: 30_000,
  deductions_usd_cents: 968,
  net_pay_usd_cents: 29_032,
  people: [
    {
      employee_id: "emp-1",
      employee_code: "E-001",
      name_en: "Chan Dara",
      name_km: "ចាន់ ដារ៉ា",
      payment_method: "ABA",
      aba_account_name: "SAMPLE NAME",
      aba_account_number: "000 123 456",
      earnings_usd_cents: 30_000,
      deductions_usd_cents: 968,
      net_pay_usd_cents: 29_032,
      lines: [
        {
          line_id: "line-1",
          component: "BASE_SALARY",
          direction: "EARNING",
          amount_usd_cents: 30_000,
          source: "LIST",
          reason: "Salary for 10/2026",
          days_worked: 31,
          days_in_month: 31,
          hours: null,
          salary_loan_id: null,
          name_en: "Salary",
          name_km: "ប្រាក់ខែ",
        },
        {
          line_id: "line-2",
          component: "DAYS_NOT_WORKED",
          direction: "DEDUCTION",
          amount_usd_cents: 968,
          source: "ATTENDANCE",
          reason: "1 day(s) absent",
          days_worked: 1,
          days_in_month: 31,
          hours: null,
          salary_loan_id: null,
          name_en: "Days not worked",
          name_km: "ថ្ងៃមិនបានធ្វើការ",
        },
      ],
      payslip: null,
    },
  ],
};

const PAYROLLS: PayrollList = {
  runs: [],
  today: "2026-11-01",
  pay_day: 5,
  next_month: "2026-10-01",
  components: [],
  can_prepare: true,
  can_approve: true,
  can_pay: true,
};

const DAY: AttendanceDay = {
  day: "2026-11-04",
  today: "2026-11-05",
  locked: false,
  can_manage: true,
  shifts: CHOICES.shifts,
  people: [
    {
      employee_id: "emp-1",
      employee_code: "E-001",
      name_en: "Chan Dara",
      name_km: "ចាន់ ដារ៉ា",
      job_en: "Property Caretaker",
      job_km: "អ្នកថែរក្សាអគារ",
      uses_shifts: true,
      planned_shift: "MORNING",
      day_off: false,
      entry_id: "en-1",
      shift_code: "MORNING",
      status: "WORKED",
      check_in_at: "2026-11-04T06:50:00+07:00",
      check_out_at: "2026-11-04T15:31:00+07:00",
      source: "QR_PHONE",
      reason: null,
      fixed: false,
      late_minutes: 20,
      no_check_out: false,
      scans: [
        {
          scan_id: "scan-1",
          direction: "IN",
          method: "PHONE",
          place_en: "Office",
          place_km: "ការិយាល័យ",
          scanned_at: "2026-11-04T06:50:00+07:00",
          distance_m: 240,
          needs_check: true,
          accepted: false,
          card_reason: null,
          card_reason_text: null,
          has_photo: false,
          scanned_by_en: null,
          scanned_by_km: null,
        },
      ],
    },
  ],
};

const WEEK: AttendanceWeek = {
  monday: "2026-11-02",
  days_off_per_week: 1,
  people: [
    {
      employee_id: "emp-1",
      employee_code: "E-001",
      name_en: "Chan Dara",
      name_km: "ចាន់ ដារ៉ា",
      uses_shifts: false,
      days: [2, 3, 4, 5, 6, 7, 8].map((date) => ({
        work_date: `2026-11-0${String(date)}`,
        works: true,
        shift_code: "MORNING" as const,
        day_off: false,
        planned: false,
      })),
    },
  ],
};

const OVERTIME: OvertimeList = {
  month: "2026-11-01",
  can_request: true,
  can_approve: true,
  requests: [
    {
      request_id: "ot-1",
      overtime_number: "OT260001",
      employee_id: "emp-1",
      employee_code: "E-001",
      name_en: "Chan Dara",
      name_km: "ចាន់ ដារ៉ា",
      work_date: "2026-11-06",
      starts_at: "15:30",
      ends_at: "18:30",
      reason: "Deep clean",
      normal_hours: 3,
      night_hours: 0,
      asked_by: "Manager",
      asked_at: "2026-11-05T09:00:00+07:00",
      decision: null,
      decision_reason: null,
      decided_by: null,
      decided_at: null,
      counts: false,
    },
  ],
};

const PLACES: PlaceList = {
  is_owner: true,
  qr_distance_m: 100,
  places: [
    {
      place_id: "pl-1",
      code: "OFFICE",
      name_en: "Office",
      name_km: "ការិយាល័យ",
      latitude: null,
      longitude: null,
      pin_set_at: null,
      qr_made_at: null,
      qr_count: 0,
    },
  ],
};

const ID_DETAILS = {
  id_type: "NATIONAL_ID",
  id_number: "010101010",
  date_of_birth: "1995-04-14",
  place_of_birth: "Kandal",
  home_address: "Sample street, Phnom Penh",
};
const ID_PHOTO = {
  file_name: "id.jpg",
  media_type: "image/jpeg",
  content_base64: btoa("sample ID"),
};

/** Fill the ID details and the ID photo of the Add employee form. */
function fillId(box: HTMLElement) {
  fireEvent.change(within(box).getByLabelText(/ID card or passport number/), {
    target: { value: "010101010" },
  });
  fireEvent.change(within(box).getByLabelText(/Date of birth/), {
    target: { value: "14/04/1995" },
  });
  fireEvent.change(within(box).getByLabelText(/Place of birth/), {
    target: { value: "Kandal" },
  });
  fireEvent.change(within(box).getByLabelText(/Home address/), {
    target: { value: "Sample street, Phnom Penh" },
  });
  fireEvent.change(within(box).getByLabelText(/Photo of the ID card/), {
    target: {
      files: [new File(["sample ID"], "id.jpg", { type: "image/jpeg" })],
    },
  });
}

function fakeApi(overrides: Partial<HrApi> = {}): HrApi {
  return {
    employees: vi.fn(() => Promise.resolve([DARA, SOK])),
    employee: vi.fn(() => Promise.resolve(DETAIL)),
    choices: vi.fn(() => Promise.resolve(CHOICES)),
    addEmployee: vi.fn(() =>
      Promise.resolve({ ...DETAIL, name_en: "Keo Sophea" }),
    ),
    employeeStep: vi.fn(() => Promise.resolve(DETAIL)),
    addDocument: vi.fn(() => Promise.resolve(DETAIL)),
    documentUrl: () => "/doc",
    staffRequests: vi.fn(() => Promise.resolve([])),
    decideStaffRequest: vi.fn(() => Promise.resolve()),
    card: vi.fn(() =>
      Promise.resolve({
        works: true,
        left_on: null,
        can_replace: true,
        cards: [],
      }),
    ),
    newCard: vi.fn(() => Promise.resolve("CARD-CODE")),
    loans: vi.fn(() => Promise.resolve(LOANS)),
    addLoan: vi.fn(() => Promise.resolve()),
    decideLoan: vi.fn(() => Promise.resolve()),
    payOutLoan: vi.fn(() => Promise.resolve()),
    payrolls: vi.fn(() => Promise.resolve(PAYROLLS)),
    payroll: vi.fn(() => Promise.resolve(RUN)),
    makePayroll: vi.fn(() => Promise.resolve(RUN)),
    makeCorrection: vi.fn(() => Promise.resolve(RUN)),
    payrollStep: vi.fn(() => Promise.resolve(RUN)),
    paySalary: vi.fn(() => Promise.resolve()),
    reversePayment: vi.fn(() => Promise.resolve()),
    day: vi.fn(() => Promise.resolve(DAY)),
    week: vi.fn(() => Promise.resolve(WEEK)),
    month: vi.fn(() =>
      Promise.resolve({ month: "2026-11-01", locked: false, people: [] }),
    ),
    enterDay: vi.fn(() => Promise.resolve(DAY)),
    planDay: vi.fn(() => Promise.resolve(WEEK)),
    overtime: vi.fn(() => Promise.resolve(OVERTIME)),
    askOvertime: vi.fn(() => Promise.resolve(OVERTIME)),
    decideOvertime: vi.fn(() => Promise.resolve(OVERTIME)),
    acceptScan: vi.fn(() => Promise.resolve()),
    photoUrl: () => "/photo",
    places: vi.fn(() => Promise.resolve(PLACES)),
    setPin: vi.fn(() => Promise.resolve(PLACES)),
    newPlaceQr: vi.fn(() => Promise.resolve("QR-CODE-1")),
    ...overrides,
  };
}

beforeEach(() => {
  window.history.replaceState(null, "", "#/home");
});

afterEach(() => {
  cleanup();
});

function dialog(): HTMLElement {
  return screen.getByRole("dialog");
}

describe("HRIS phase 6 screens", () => {
  it("TEST-FE-1299 lists working employees with their Telegram link and salary, and Left on its own tab", async () => {
    render(
      <EmployeesPage
        active
        api={fakeApi()}
        capabilities={null}
        language="en"
        propertyId={PROPERTY}
      />,
    );
    const table = await screen.findByRole("table");
    expect(within(table).getByText("Chan Dara")).toBeInTheDocument();
    expect(within(table).queryByText("Sok Vanna")).toBeNull();
    expect(within(table).getByText("Telegram linked")).toBeInTheDocument();
    expect(within(table).getByText("$300.00")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Left" }));
    expect(
      within(screen.getByRole("table")).getByText("Sok Vanna"),
    ).toBeInTheDocument();
  });

  it("TEST-FE-1300 adds an employee with the salary in whole cents and says it was added", async () => {
    const api = fakeApi();
    render(
      <EmployeesPage
        active
        api={api}
        capabilities={null}
        language="en"
        propertyId={PROPERTY}
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Add employee" }),
    );
    const box = dialog();
    fireEvent.change(within(box).getByLabelText(/Name in English/), {
      target: { value: "Keo Sophea" },
    });
    fireEvent.change(within(box).getByLabelText(/Name in Khmer/), {
      target: { value: "កែវ សុភា" },
    });
    fireEvent.change(within(box).getByLabelText("Salary"), {
      target: { value: "285.50" },
    });
    fillId(box);
    fireEvent.click(within(box).getByRole("button", { name: "Add employee" }));
    await screen.findByText("Employee Keo Sophea added.");
    expect(api.addEmployee).toHaveBeenCalledWith(PROPERTY, {
      name_en: "Keo Sophea",
      name_km: "កែវ សុភា",
      job_title_id: "job-1",
      usual_day_off: 7,
      start_date: "2026-11-05",
      identity: ID_DETAILS,
      id_photo: ID_PHOTO,
      pay: { monthly_salary_usd_cents: 28_550, payment_method: "CASH_USD" },
    });
  });

  it("TEST-FE-1301 an employee page hides pay without See salaries, and Set end date needs a reason", async () => {
    window.history.replaceState(null, "", "#/employees/emp-1");
    const api = fakeApi({
      employee: vi.fn(() =>
        Promise.resolve({ ...DETAIL, can_see_salaries: false, pay: undefined }),
      ),
    });
    render(
      <EmployeesPage
        active
        api={api}
        capabilities={null}
        language="en"
        propertyId={PROPERTY}
      />,
    );
    await screen.findByText(/Only people with See salaries/);
    fireEvent.click(screen.getByRole("button", { name: "Set end date" }));
    const box = dialog();
    fireEvent.click(within(box).getByRole("button", { name: "Set end date" }));
    expect(within(box).getByText("Say why.")).toBeInTheDocument();
    expect(api.employeeStep).not.toHaveBeenCalled();
    fireEvent.change(within(box).getByLabelText(/Reason/), {
      target: { value: "Moves away" },
    });
    fireEvent.click(within(box).getByRole("button", { name: "Set end date" }));
    await screen.findByText("Chan Dara leaves on 05/11/2026.");
    expect(api.employeeStep).toHaveBeenCalledWith(
      PROPERTY,
      expect.objectContaining({ employee_id: "emp-1", version: 3 }),
      { step: "LEAVE", effective_date: "2026-11-05", reason: "Moves away" },
    );
  });

  it("TEST-FE-1302 links a Telegram request to an employee with the ticked roles; only the Owner sees Authorizer", async () => {
    const api = fakeApi({
      staffRequests: vi.fn(() =>
        Promise.resolve([
          {
            request_id: "req-1",
            telegram_user_id: 9002,
            given_name: "New Person",
            phone: "099 000 111",
            received_at: "2026-11-04T10:00:00+07:00",
          },
        ]),
      ),
    });
    render(
      <EmployeesPage
        active
        api={api}
        capabilities={null}
        language="en"
        propertyId={PROPERTY}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Link" }));
    const box = dialog();
    expect(
      within(box).queryByLabelText("Authorizer (approves reports)"),
    ).toBeNull();
    fireEvent.click(within(box).getByRole("button", { name: "Link" }));
    expect(within(box).getByText("Tick one or more.")).toBeInTheDocument();
    fireEvent.click(within(box).getByLabelText("Cleaner reports"));
    fireEvent.click(within(box).getByRole("button", { name: "Link" }));
    await screen.findByText("Chan Dara is linked to Telegram.");
    expect(api.decideStaffRequest).toHaveBeenCalledWith(PROPERTY, "req-1", {
      decision: "LINKED",
      employee_id: "emp-1",
      roles: ["CLEANER"],
    });
  });

  it("TEST-FE-1303 a new salary loan shows the limit, and a refusal needs a reason", async () => {
    const api = fakeApi();
    render(<LoansPage active api={api} language="en" propertyId={PROPERTY} />);
    expect(await screen.findByText("Waits for the Owner")).toBeInTheDocument();
    expect(screen.getByText("Asked in Telegram")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refuse" }));
    let box = dialog();
    fireEvent.click(within(box).getByRole("button", { name: "Refuse" }));
    expect(within(box).getByText("Say why.")).toBeInTheDocument();
    fireEvent.click(within(box).getByRole("button", { name: "Cancel" }));
    await waitFor(() => {
      expect(api.employees).toHaveBeenCalled();
    });
    fireEvent.click(screen.getByRole("button", { name: "New salary loan" }));
    box = dialog();
    fireEvent.change(within(box).getByLabelText(/Amount/), {
      target: { value: "200" },
    });
    expect(within(box).getByText("Over the limit $150.00")).toBeInTheDocument();
    fireEvent.change(within(box).getByLabelText(/Amount/), {
      target: { value: "120" },
    });
    expect(within(box).getByText("Within limit $150.00")).toBeInTheDocument();
    fireEvent.change(within(box).getByLabelText(/Reason/), {
      target: { value: "Rent" },
    });
    fireEvent.click(
      within(box).getByRole("button", { name: "Send to the Owner" }),
    );
    await screen.findByText("Salary loan for Chan Dara sent to the Owner.");
    expect(api.addLoan).toHaveBeenCalledWith(PROPERTY, {
      employee_id: "emp-1",
      amount_usd_cents: 12_000,
      payout_method: "CASH_USD",
      repayment_plan: "NEXT_SALARY",
      request_channel: "APP",
      requested_on: "2026-11-05",
      reason: "Rent",
    });
  });

  it("TEST-FE-1304 makes the month's payroll, adds a line and sends it to the Owner", async () => {
    const api = fakeApi();
    render(
      <PayrollPage active api={api} language="en" propertyId={PROPERTY} />,
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Make the list for October 2026",
      }),
    );
    await screen.findByText(/Salaries for October 2026/);
    expect(api.makePayroll).toHaveBeenCalledWith(PROPERTY, "2026-10-01");
    expect(
      screen.getByRole("img", { name: "From attendance" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add a line" }));
    const box = dialog();
    fireEvent.change(within(box).getByLabelText(/Amount/), {
      target: { value: "20" },
    });
    fireEvent.change(within(box).getByLabelText(/Reason/), {
      target: { value: "Extra work" },
    });
    fireEvent.click(within(box).getByRole("button", { name: "Add a line" }));
    await screen.findByText("Line added.");
    expect(api.payrollStep).toHaveBeenCalledWith(PROPERTY, "run-1", {
      step: "ADD_LINE",
      employee_id: "emp-1",
      component: "BONUS",
      amount_usd_cents: 2_000,
      reason: "Extra work",
    });
    fireEvent.click(screen.getByRole("button", { name: "Send to the Owner" }));
    await screen.findByText("Sent to the Owner.");
    expect(api.payrollStep).toHaveBeenLastCalledWith(PROPERTY, "run-1", {
      step: "SEND",
    });
  });

  it("TEST-FE-1305 an approved payroll marks each person paid from the joint ABA account", async () => {
    window.history.replaceState(null, "", "#/payroll/run-1");
    const approved: PayrollDetail = {
      ...RUN,
      state: "APPROVED",
      people: RUN.people.map((person) => ({
        ...person,
        payslip: {
          payslip_id: "slip-1",
          entry_id: "je-1",
          earnings_usd_cents: 30_000,
          deductions_usd_cents: 968,
          net_pay_usd_cents: 29_032,
          payment: null,
        },
      })),
    };
    const api = fakeApi({ payroll: vi.fn(() => Promise.resolve(approved)) });
    render(
      <PayrollPage active api={api} language="en" propertyId={PROPERTY} />,
    );
    expect(
      await screen.findByText("1 people not marked paid yet"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add a line" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Mark paid" }));
    const box = dialog();
    expect(
      within(box).getByText(/\$290\.32 to SAMPLE NAME 000 123 456/),
    ).toBeInTheDocument();
    fireEvent.change(within(box).getByLabelText(/ABA reference/), {
      target: { value: "T-55" },
    });
    fireEvent.click(within(box).getByRole("button", { name: "Mark paid" }));
    await screen.findByText("Chan Dara marked paid.");
    expect(api.paySalary).toHaveBeenCalledWith(PROPERTY, "slip-1", {
      paid_on: "2026-11-01",
      method: "ABA_JOINT",
      bank_reference: "T-55",
    });
  });

  it("TEST-FE-1306 the daily sheet shows Late and Needs check, accepts a scan and fixes times with a reason", async () => {
    const api = fakeApi();
    render(
      <AttendancePage active api={api} language="en" propertyId={PROPERTY} />,
    );
    expect(await screen.findByText("Late 20 min")).toBeInTheDocument();
    expect(screen.getByText("Needs check")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Accept" }));
    fireEvent.click(within(dialog()).getByRole("button", { name: "Accept" }));
    await screen.findByText("Accepted: Chan Dara, 06:50.");
    expect(api.acceptScan).toHaveBeenCalledWith(PROPERTY, "scan-1", null);
    fireEvent.click(screen.getByRole("button", { name: "Edit times" }));
    const box = dialog();
    fireEvent.change(within(box).getByLabelText("Check-in"), {
      target: { value: "6:3o" },
    });
    fireEvent.change(within(box).getByLabelText(/Reason/), {
      target: { value: "Phone late" },
    });
    fireEvent.click(within(box).getByRole("button", { name: "Save" }));
    expect(
      within(box).getByText("Type the time like 07:05.", {
        selector: ".ui-error",
      }),
    ).toBeInTheDocument();
    fireEvent.change(within(box).getByLabelText("Check-in"), {
      target: { value: "6:30" },
    });
    fireEvent.click(within(box).getByRole("button", { name: "Save" }));
    await screen.findByText("Attendance fixed for Chan Dara.");
    expect(api.enterDay).toHaveBeenCalledWith(PROPERTY, {
      employee_id: "emp-1",
      work_date: "2026-11-04",
      status: "WORKED",
      shift_code: "MORNING",
      check_in: "06:30",
      check_out: "15:31",
      reason: "Phone late",
    });
  });

  it("TEST-FE-1307 the weekly plan warns about too few days off and plans a coming day off", async () => {
    const api = fakeApi();
    render(
      <AttendancePage active api={api} language="en" propertyId={PROPERTY} />,
    );
    await screen.findByText("Late 20 min");
    fireEvent.click(screen.getByRole("button", { name: "Weekly plan" }));
    expect(await screen.findByText("Fewer than 1 day off")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Plan · Chan Dara · 04/11/2026" }),
    ).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "Plan · Chan Dara · 08/11/2026" }),
    );
    const box = dialog();
    fireEvent.click(within(box).getByLabelText("Day off"));
    fireEvent.click(within(box).getByRole("button", { name: "Save" }));
    await screen.findByText("Plan saved.");
    expect(api.planDay).toHaveBeenCalledWith(PROPERTY, {
      employee_id: "emp-1",
      work_date: "2026-11-08",
      shift_code: null,
    });
  });

  it("TEST-FE-1400 Add employee needs the ID details and photo; only the caretaker picks a shift", async () => {
    const api = fakeApi();
    render(
      <EmployeesPage
        active
        api={api}
        capabilities={null}
        language="en"
        propertyId={PROPERTY}
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Add employee" }),
    );
    const box = dialog();
    fireEvent.change(within(box).getByLabelText(/Name in English/), {
      target: { value: "Sok Mara" },
    });
    fireEvent.change(within(box).getByLabelText(/Name in Khmer/), {
      target: { value: "សុខ ម៉ារ៉ា" },
    });
    // A cleaner works office hours with a usual day off, and picks no shift.
    expect(within(box).getByText(/Office hours: 7:00 to 11:00/)).toBeVisible();
    expect(within(box).queryByLabelText(/Usual shift/)).toBeNull();
    fireEvent.click(within(box).getByRole("button", { name: "Add employee" }));
    expect(
      await within(box).findByText(/Enter the ID type and number/),
    ).toBeVisible();
    expect(api.addEmployee).not.toHaveBeenCalled();
    // The Property caretaker picks a shift and has no usual day off.
    fireEvent.change(within(box).getByLabelText(/^Job/), {
      target: { value: "job-2" },
    });
    expect(within(box).queryByLabelText(/Usual day off/)).toBeNull();
    expect(within(box).getByText(/2 days off a month/)).toBeVisible();
    fireEvent.change(within(box).getByLabelText(/Usual shift/), {
      target: { value: "NIGHT" },
    });
    fireEvent.change(within(box).getByLabelText(/ID type/), {
      target: { value: "PASSPORT" },
    });
    fillId(box);
    fireEvent.click(within(box).getByRole("button", { name: "Add employee" }));
    await screen.findByText("Employee Keo Sophea added.");
    expect(api.addEmployee).toHaveBeenCalledWith(PROPERTY, {
      name_en: "Sok Mara",
      name_km: "សុខ ម៉ារ៉ា",
      job_title_id: "job-2",
      shift_code: "NIGHT",
      start_date: "2026-11-05",
      identity: { ...ID_DETAILS, id_type: "PASSPORT" },
      id_photo: ID_PHOTO,
    });
  });

  it("TEST-FE-1402 Add employee asks Hire again when the ID number belonged to a leaver", async () => {
    const api = fakeApi();
    vi.mocked(api.addEmployee).mockRejectedValueOnce(
      new HrError(
        422,
        "This ID number belonged to E-003 Sok Mara, who left on 30/06/2026. Hire again?",
      ),
    );
    render(
      <EmployeesPage
        active
        api={api}
        capabilities={null}
        language="en"
        propertyId={PROPERTY}
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Add employee" }),
    );
    const box = dialog();
    fireEvent.change(within(box).getByLabelText(/Name in English/), {
      target: { value: "Sok Mara" },
    });
    fireEvent.change(within(box).getByLabelText(/Name in Khmer/), {
      target: { value: "សុខ ម៉ារ៉ា" },
    });
    fillId(box);
    expect(within(box).queryByLabelText(/Hire again/)).toBeNull();
    fireEvent.click(within(box).getByRole("button", { name: "Add employee" }));
    expect(
      await within(box).findByText(/who left on 30\/06\/2026/),
    ).toBeVisible();
    fireEvent.click(within(box).getByLabelText(/Hire again/));
    fireEvent.click(within(box).getByRole("button", { name: "Add employee" }));
    await screen.findByText("Employee Keo Sophea added.");
    expect(api.addEmployee).toHaveBeenLastCalledWith(
      PROPERTY,
      expect.objectContaining({ hire_again: true }),
    );
  });

  it("TEST-FE-1401 the weekly plan counts the caretaker's days off a month; office staff plan office hours only", async () => {
    const [first] = WEEK.people;
    if (first === undefined) throw new Error("The sample week has a person");
    const week: AttendanceWeek = {
      ...WEEK,
      people: [
        {
          ...first,
          employee_id: "emp-3",
          employee_code: "E-003",
          name_en: "Sample Caretaker",
          name_km: "គំរូ អ្នកថែរក្សា",
          uses_shifts: true,
          days_off_per_month: 2,
          month_days_off: [{ month: "2026-11-01", planned: 3 }],
        },
        {
          ...first,
          employee_id: "emp-2",
          employee_code: "E-002",
          name_en: "Lim Sokha",
          name_km: "លឹម សុខា",
          uses_shifts: false,
          days: first.days.map((one) => ({
            ...one,
            shift_code: "OFFICE" as const,
          })),
        },
      ],
    };
    const api = fakeApi({ week: vi.fn(() => Promise.resolve(week)) });
    render(
      <AttendancePage active api={api} language="en" propertyId={PROPERTY} />,
    );
    await screen.findByText("Late 20 min");
    fireEvent.click(screen.getByRole("button", { name: "Weekly plan" }));
    // Owner 06/11/2026: the caretaker takes 2 days off a month on request, with no weekly
    // warning; the screen shows each month's count against the 2.
    expect(await screen.findAllByText("Fewer than 1 day off")).toHaveLength(1);
    const caretakerRow = screen.getByRole("row", { name: /Sample Caretaker/ });
    expect(within(caretakerRow).queryByText("Fewer than 1 day off")).toBeNull();
    expect(within(caretakerRow).getByText(/3 of 2 days off/)).toBeVisible();
    fireEvent.click(
      screen.getByRole("button", { name: "Plan · Lim Sokha · 08/11/2026" }),
    );
    const box = dialog();
    expect(
      within(box).getByLabelText("Office hours 7:00-11:00, 13:00-17:00"),
    ).toBeChecked();
    expect(within(box).queryByLabelText("Morning shift")).toBeNull();
  });

  it("TEST-FE-1308 approves overtime, and a new place QR is shown once after it is made", async () => {
    const api = fakeApi();
    render(
      <AttendancePage active api={api} language="en" propertyId={PROPERTY} />,
    );
    await screen.findByText("Late 20 min");
    fireEvent.click(screen.getByRole("button", { name: "Overtime" }));
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    await screen.findByText("Overtime OT260001 approved for Chan Dara.");
    expect(api.decideOvertime).toHaveBeenCalledWith(PROPERTY, "ot-1", {
      decision: "APPROVED",
    });
    fireEvent.click(screen.getByRole("button", { name: "QR places" }));
    fireEvent.click(await screen.findByRole("button", { name: "Set pin" }));
    let box = dialog();
    fireEvent.change(within(box).getByLabelText("Map pin"), {
      target: { value: "11.6 104.8" },
    });
    fireEvent.click(within(box).getByRole("button", { name: "Save" }));
    expect(
      within(box).getByText(/Type two numbers with a comma/),
    ).toBeInTheDocument();
    fireEvent.change(within(box).getByLabelText("Map pin"), {
      target: { value: "11.6045, 104.8902" },
    });
    fireEvent.click(within(box).getByRole("button", { name: "Save" }));
    await screen.findByText("Pin saved for Office.");
    expect(api.setPin).toHaveBeenCalledWith(PROPERTY, "pl-1", {
      latitude: 11.6045,
      longitude: 104.8902,
    });
    fireEvent.click(screen.getByRole("button", { name: "Make QR" }));
    box = dialog();
    fireEvent.click(within(box).getByRole("button", { name: "Make QR" }));
    expect(
      await screen.findByText(/the new QR code is QR-CODE-1/),
    ).toBeInTheDocument();
  });

  it("TEST-FE-1309 says why a command was refused: no right, someone else's change, or the server's words", () => {
    expect(failureText("en", new HrError(403, "x"))).toBe(
      "You do not have the right to do this.",
    );
    expect(failureText("en", new HrError(412, null))).toBe(
      "Someone else changed this. Open it again.",
    );
    expect(failureText("en", new HrError(422, "Say why"))).toBe(
      "The app refused this: Say why",
    );
    expect(failureText("en", new HrError(503, "down"))).toBe(
      "This was not saved. Try again.",
    );
    expect(failureText("en", new Error("x"))).toBe(
      "This was not saved. Try again.",
    );
  });
});
