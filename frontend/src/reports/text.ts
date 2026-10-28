// V1-060 B6: the words of the Reports screens in English and Khmer, from the owner's mock-up
// (round 4, i18n4.js, with column words from i18n.js to i18n3.js). Khmer needs the native check
// before the app is used. Lines marked "new" are not in the mock-up; lines marked "changed"
// say what was changed from it.

import type { Language } from "../signInText";

const TEXT = {
  // The list of reports.
  rp_sub: [
    "Every report comes from the records. USD and riel are always shown apart.",
    "របាយការណ៍នីមួយៗមកពីកំណត់ត្រា។ ដុល្លារ និងរៀល បង្ហាញដាច់ដោយឡែកជានិច្ច។",
  ],
  g_totals: ["Totals by Unit and month", "សរុបតាមបន្ទប់ និងខែ"],
  g_registers: ["Registers and lists", "បញ្ជី"],
  tag: ["Owner and Manager", "ម្ចាស់ និងអ្នកគ្រប់គ្រង"],
  open: ["Open report", "បើករបាយការណ៍"],
  // changed: "(V1-057)" left out.
  staff_note: [
    "Staff see the operational reports only. Money totals, audit and exports are for the Owner and Managers.",
    "បុគ្គលិកឃើញតែរបាយការណ៍ប្រតិបត្តិការ។ សរុបលុយ សវនកម្ម និងការនាំចេញ សម្រាប់ម្ចាស់ និងអ្នកគ្រប់គ្រង។",
  ],
  currency: [
    "Amounts in USD. Riel payments are shown with their riel amount and rate; never added to USD.",
    "ចំនួនជាដុល្លារ។ ការបង់ជារៀល បង្ហាញចំនួនរៀល និងអត្រា; មិនបូកចូលដុល្លារទេ។",
  ],
  // new
  none_allowed: [
    "Your account cannot see any report. Ask the Owner if you need one.",
    "គណនីរបស់អ្នកមិនអាចមើលរបាយការណ៍ណាមួយបានទេ។ សូមសួរម្ចាស់ ប្រសិនបើអ្នកត្រូវការ។",
  ],

  // Report names and their one-line descriptions.
  r_total_income: ["Total Income", "ចំណូលសរុប"],
  d_total_income: [
    "Invoiced amounts for each Unit, month by month",
    "ចំនួនក្នុងវិក្កយបត្រ សម្រាប់បន្ទប់នីមួយៗ តាមខែ",
  ],
  r_total_payment: ["Total Payment", "ការបង់ប្រាក់សរុប"],
  d_total_payment: [
    "Money received from each Unit, month by month",
    "ប្រាក់បានទទួលពីបន្ទប់នីមួយៗ តាមខែ",
  ],
  r_total_electricity: ["Total Electricity", "អគ្គិសនីសរុប"],
  d_total_electricity: [
    "Electricity billed for each Unit, reading period by period",
    "អគ្គិសនីគិតថ្លៃ សម្រាប់បន្ទប់នីមួយៗ តាមរយៈពេលអាន",
  ],
  r_total_water: ["Total Water", "ទឹកសរុប"],
  d_total_water: [
    "Water billed for each Unit, reading period by period",
    "ទឹកគិតថ្លៃ សម្រាប់បន្ទប់នីមួយៗ តាមរយៈពេលអាន",
  ],
  r_invoice_register: [
    "Invoice register and balances",
    "បញ្ជីវិក្កយបត្រ និងសមតុល្យ",
  ],
  d_invoice_register: [
    "Issued, paid and still owed, with overdue groups",
    "បានចេញ បានបង់ នៅជំពាក់ ជាមួយក្រុមហួសកំណត់",
  ],
  r_payments: ["Payments and allocations", "ការបង់ប្រាក់ និងការបែងចែក"],
  d_payments: [
    "Every Receipt and what it paid; money collected by month and kind",
    "បង្កាន់ដៃនីមួយៗ និងអ្វីដែលបង់; លុយទទួលតាមខែ និងប្រភេទ",
  ],
  r_utility_consumption: ["Utility consumption", "ការប្រើប្រាស់ទឹកភ្លើង"],
  d_utility_consumption: [
    "kWh and m³ per Unit and reading period, with the amounts billed",
    "kWh និង m³ តាមបន្ទប់ និងរយៈពេលអាន ជាមួយចំនួនគិតថ្លៃ",
  ],
  r_credit_ledger: ["Customer Credit ledger", "បញ្ជីឥណទានអតិថិជន"],
  d_credit_ledger: [
    "Overpayments kept as Credit and how they were used",
    "ប្រាក់បង់លើសរក្សាជាឥណទាន និងរបៀបប្រើ",
  ],
  r_deposits: [
    "Deposit liability and disposition",
    "បំណុលប្រាក់កក់ និងការចាត់ចែង",
  ],
  d_deposits: [
    "Security and Pet Deposits held, applied, kept or refunded",
    "ប្រាក់កក់សុវត្ថិភាព និងសត្វចិញ្ចឹម កាន់កាប់ បានប្រើ រក្សា ឬសងវិញ",
  ],
  r_final_settlements: ["Final Settlement register", "បញ្ជីការទូទាត់ចុងក្រោយ"],
  d_final_settlements: [
    "Charges, deposits applied or kept, refunds and open balances",
    "ថ្លៃ ប្រាក់កក់បានប្រើ ឬរក្សា ការសងវិញ និងសមតុល្យបើក",
  ],
  r_unit_occupancy: ["Unit occupancy", "ការកាន់កាប់បន្ទប់"],
  d_unit_occupancy: [
    "Every Unit: status, Customer, Lease or Reservation end",
    "បន្ទប់នីមួយៗ៖ ស្ថានភាព អតិថិជន ចុងកិច្ចសន្យា ឬការកក់",
  ],
  r_lease_dates: ["Lease dates", "កាលបរិច្ឆេទកិច្ចសន្យា"],
  // changed: the list comes earliest End Date first (the server's order).
  d_lease_dates: [
    "Start and End Dates, earliest End Date first; Leases ending within 60 days are marked",
    "ថ្ងៃចាប់ផ្តើម និងបញ្ចប់ ថ្ងៃបញ្ចប់មុនគេនៅលើ; កិច្ចសន្យាបញ្ចប់ក្នុង 60 ថ្ងៃ មានសម្គាល់",
  ],
  r_audit_activity: ["Audit activity", "សកម្មភាពសវនកម្ម"],
  d_audit_activity: [
    "Who did what, counted by day and action",
    "អ្នកណាធ្វើអ្វី រាប់តាមថ្ងៃ និងសកម្មភាព",
  ],

  // The parameter bar of a report (UI-089).
  // new
  back: ["All reports", "របាយការណ៍ទាំងអស់"],
  scope: ["Scope", "វិសាលភាព"],
  // new
  whole: ["Whole Property", "អចលនទ្រព្យទាំងមូល"],
  floor_n: ["Floor {0}", "ជាន់ទី {0}"],
  unit: ["Unit", "បន្ទប់"],
  all_units: ["All Units", "គ្រប់បន្ទប់"],
  period: ["Period", "រយៈពេល"],
  // changed: "All", as on Payments and Invoices (the mock-up said "Everything").
  p_all: ["All", "ទាំងអស់"],
  p_month: ["This month", "ខែនេះ"],
  p_last: ["Last month", "ខែមុន"],
  p_pick: ["Pick dates", "ជ្រើសថ្ងៃ"],
  from: ["From", "ពី"],
  to: ["To", "ដល់"],
  show: ["Show", "បង្ហាញ"],
  calendar: ["Calendar", "ប្រតិទិន"],
  bad_dates: [
    "Write both dates as dd/mm/yyyy, with From on or before To.",
    "សូមសរសេរថ្ងៃទាំងពីរជា dd/mm/yyyy ហើយថ្ងៃ ពី មិនក្រោយថ្ងៃ ដល់។",
  ],
  range: ["{0} to {1}", "{0} ដល់ {1}"],
  as_of: ["As of {0}", "គិតត្រឹម {0}"],
  // new
  all_dates: ["All dates", "គ្រប់កាលបរិច្ឆេទ"],
  // V1-060 B7: picked days on a Totals table widen to whole months.
  months_note: ["Totals count whole months.", "តារាងសរុបរាប់តាមខែពេញ។"],
  // new: Unit occupancy and Deposit liability show today.
  today_only: [
    "As of {0}. This report shows today, so the period does not apply.",
    "គិតត្រឹម {0}។ របាយការណ៍នេះបង្ហាញថ្ងៃនេះ ដូច្នេះរយៈពេលមិនអនុវត្តទេ។",
  ],
  // changed: .xlsx and PDF (owner, 21/10/2026), so no "CSV".
  export: ["Export", "នាំចេញ"],

  // The report page.
  summary: ["Summary", "សង្ខេប"],
  // new: the small table of a summary that splits the money by kind.
  by_type: ["By kind", "តាមប្រភេទ"],
  rows1: ["1 row", "1 ជួរ"],
  rows: ["{0} rows", "{0} ជួរ"],
  // new
  showing: ["Showing {0} of {1} rows", "បង្ហាញ {0} ក្នុងចំណោម {1} ជួរ"],
  // new
  more: ["Show more", "បង្ហាញបន្ថែម"],
  total: ["Total", "សរុប"],
  // V1-060 B7: the footer Total counts every row, also the ones not shown yet.
  total_all: ["Total, all {0} rows", "សរុប ទាំង {0} ជួរ"],
  // new
  none: ["No records for this period.", "គ្មានកំណត់ត្រាសម្រាប់រយៈពេលនេះទេ។"],
  // new
  none_now: ["No records.", "គ្មានកំណត់ត្រាទេ។"],
  // new (UI-090, DL-072 answer 11)
  generated: [
    "Generated {0} · Phnom Penh time · amounts in USD; riel shown as information only",
    "បង្កើត {0} · ម៉ោងភ្នំពេញ · ចំនួនជាដុល្លារ; រៀលបង្ហាញជាព័ត៌មានប៉ុណ្ណោះ",
  ],
  // new
  loading: ["Reading the report…", "កំពុងអានរបាយការណ៍…"],
  // new
  failed: [
    "The report could not be read just now. Check the connection and try again.",
    "មិនអាចអានរបាយការណ៍បានទេឥឡូវនេះ។ សូមពិនិត្យការតភ្ជាប់ ហើយព្យាយាមម្តងទៀត។",
  ],
  // new
  more_failed: [
    "More rows could not be read just now. Try again.",
    "មិនអាចអានជួរបន្ថែមបានទេឥឡូវនេះ។ សូមព្យាយាមម្តងទៀត។",
  ],
  // new
  not_allowed: [
    "Your account cannot see this report. Ask the Owner if you need it.",
    "គណនីរបស់អ្នកមិនអាចមើលរបាយការណ៍នេះបានទេ។ សូមសួរម្ចាស់ ប្រសិនបើអ្នកត្រូវការវា។",
  ],
  retry: ["Retry", "ព្យាយាមម្តងទៀត"],

  // Totals by Unit and month (the crosstab reports).
  year: ["Year", "ឆ្នាំ"],
  // new: the first column of a chart's table for screen readers.
  month: ["Month", "ខែ"],
  best_m: ["Highest month", "ខែខ្ពស់បំផុត"],
  best_u: ["Highest Unit", "បន្ទប់ខ្ពស់បំផុត"],
  // new
  used: ["Used", "បានប្រើ"],
  // new: money that belongs to no Unit counts only in the whole-Property table.
  no_unit: ["Not tied to a Unit", "មិនភ្ជាប់នឹងបន្ទប់"],
  estimate: ["Estimate", "ការប៉ាន់ស្មាន"],
  top5: ["Top 5 Units", "បន្ទប់ 5 ខ្ពស់បំផុត"],
  ch_total_income: ["Income by month", "ចំណូលតាមខែ"],
  ch_total_payment: ["Money received by month", "ប្រាក់ទទួលតាមខែ"],
  ch_total_electricity: [
    "Electricity billed by reading month",
    "អគ្គិសនីគិតថ្លៃតាមខែអាន",
  ],
  ch_total_water: ["Water billed by reading month", "ទឹកគិតថ្លៃតាមខែអាន"],
  // changed: a kept Deposit counts as income in the month it is kept (DL-079 answer 2).
  note_total_income: [
    "Each Invoice counts in the month it is for: Rent in its Rent month, Utilities in the month their reading period ends. Deposits held are not income; a kept Deposit counts in the month it is kept. With All Units, every Unit is added together.",
    "វិក្កយបត្រនីមួយៗរាប់ក្នុងខែដែលវាសម្រាប់៖ ថ្លៃឈ្នួលក្នុងខែឈ្នួល ទឹកភ្លើងក្នុងខែដែលរយៈពេលអានបញ្ចប់។ ប្រាក់កក់ដែលកាន់កាប់មិនមែនចំណូលទេ; ប្រាក់កក់ដែលរក្សាទុក រាប់ក្នុងខែដែលវាត្រូវបានរក្សាទុក។ ពេលជ្រើសគ្រប់បន្ទប់ បន្ទប់ទាំងអស់ត្រូវបូកបញ្ចូលគ្នា។",
  ],
  // V1-060 B7: a reversed Payment comes off in its month, so the figure that matches is the
  // Payments report's Received less reversals.
  note_total_payment: [
    "Every Receipt counts on the day the money came in, deposits included; a reversed Payment comes off in the month it is reversed. This total matches Received less reversals in the Payments report. With All Units, every Unit is added together.",
    "បង្កាន់ដៃនីមួយៗរាប់នៅថ្ងៃដែលលុយចូល រួមទាំងប្រាក់កក់; ការបង់ប្រាក់ដែលត្រូវបានត្រឡប់វិញ ត្រូវដកចេញក្នុងខែដែលវាត្រូវបានត្រឡប់។ សរុបនេះដូច «ប្រាក់ទទួល ដកការត្រឡប់វិញ» ក្នុងរបាយការណ៍ការបង់ប្រាក់។ ពេលជ្រើសគ្រប់បន្ទប់ បន្ទប់ទាំងអស់ត្រូវបូកបញ្ចូលគ្នា។",
  ],
  note_total_electricity: [
    "Each month holds the reading period that ends on the 24th of that month (October = 25/09 – 24/10), at the Rate of that period. With All Units, every Unit is added together.",
    "ខែនីមួយៗ មានរយៈពេលអានដែលបញ្ចប់នៅថ្ងៃទី 24 នៃខែនោះ (តុលា = 25/09 – 24/10) តាមអត្រានៃរយៈពេលនោះ។ ពេលជ្រើសគ្រប់បន្ទប់ បន្ទប់ទាំងអស់ត្រូវបូកបញ្ចូលគ្នា។",
  ],
  note_total_water: [
    "Each month holds the reading period that ends on the 24th of that month (October = 25/09 – 24/10), at the Rate of that period. With All Units, every Unit is added together.",
    "ខែនីមួយៗ មានរយៈពេលអានដែលបញ្ចប់នៅថ្ងៃទី 24 នៃខែនោះ (តុលា = 25/09 – 24/10) តាមអត្រានៃរយៈពេលនោះ។ ពេលជ្រើសគ្រប់បន្ទប់ បន្ទប់ទាំងអស់ត្រូវបូកបញ្ចូលគ្នា។",
  ],
  // The parts of the stacked month charts.
  s_rent: ["Rent and Services", "ថ្លៃឈ្នួល និងសេវា"],
  s_utilities: ["Utilities", "ទឹកភ្លើង"],
  s_move_out_and_damage: ["Move-out and damage", "ចាកចេញ និងខូចខាត"],
  // new
  s_other_income: [
    "Late charges and kept Deposits",
    "ថ្លៃពិន័យ និងប្រាក់កក់ដែលរក្សាទុក",
  ],
  s_paid_to_invoices: ["Paid to Invoices", "បង់ទៅវិក្កយបត្រ"],
  s_deposits: ["Deposits", "ប្រាក់កក់"],
  s_other_payment: [
    "Late charges, credit and other",
    "ថ្លៃពិន័យ ឥណទាន និងផ្សេងៗ",
  ],
  // new
  s_reading: ["From readings", "ពីអំណាន"],
  s_estimate: ["Estimates", "ការប៉ាន់ស្មាន"],
  s_other: ["Other", "ផ្សេងៗ"],

  // Columns and words of the registers.
  c_invoice: ["Invoice No.", "លេខវិក្កយបត្រ"],
  c_customer: ["Customer", "អតិថិជន"],
  c_unit: ["Unit", "បន្ទប់"],
  c_type: ["Type", "ប្រភេទ"],
  c_issued: ["Issued on", "ថ្ងៃចេញ"],
  c_due: ["Due date", "ថ្ងៃកំណត់បង់"],
  c_amount: ["Amount", "ចំនួនទឹកប្រាក់"],
  c_paid: ["Paid", "បានបង់"],
  // new: paid with Customer Credit or a Deposit, not by a Payment.
  c_other_settled: ["Settled another way", "ទូទាត់ដោយវិធីផ្សេង"],
  c_owed: ["Still owed", "នៅជំពាក់"],
  c_status: ["Status", "ស្ថានភាព"],
  c_receipt: ["Receipt", "បង្កាន់ដៃ"],
  c_received: ["Received on", "កាលបរិច្ឆេទទទួល"],
  c_method: ["Method", "វិធីបង់"],
  c_for: ["Paid for", "បង់សម្រាប់"],
  c_unalloc: ["Not allocated", "មិនទាន់បែងចែក"],
  c_period: ["Period", "រយៈពេល"],
  c_kwh: ["kWh", "kWh"],
  c_m3: ["m³", "m³"],
  c_electricity: ["Electricity", "អគ្គិសនី"],
  c_water: ["Water", "ទឹក"],
  c_origin: ["Origin", "ប្រភព"],
  // new
  c_recorded: ["Recorded on", "កត់ត្រានៅ"],
  c_credit: ["Customer Credit", "ឥណទានអតិថិជន"],
  c_used: ["Used", "បានប្រើ"],
  c_refunded: ["Refunded", "បានសងវិញ"],
  // new
  c_reversed: ["Reversed", "បានត្រឡប់វិញ"],
  c_left: ["Left", "នៅសល់"],
  c_kind: ["Kind", "ប្រភេទ"],
  c_required: ["Required", "តម្រូវ"],
  c_received_amount: ["Received", "បានទទួល"],
  c_applied: ["Applied", "បានប្រើ"],
  c_kept: ["Kept", "រក្សាទុក"],
  c_held: ["Held", "កាន់កាប់"],
  // new
  c_started: ["Started on", "ចាប់ផ្តើមនៅ"],
  // new
  c_move_out: ["Move-out date", "ថ្ងៃចាកចេញ"],
  c_closed: ["Closed on", "បិទនៅ"],
  // new
  c_deposits_applied: ["Deposits applied", "ប្រាក់កក់បានប្រើ"],
  // new
  c_credit_applied: ["Credit applied", "ឥណទានបានប្រើ"],
  // new
  c_deposits_kept: ["Deposits kept", "ប្រាក់កក់រក្សាទុក"],
  c_balance: ["Balance still owed", "សមតុល្យនៅជំពាក់"],
  c_unit_type: ["Unit Type", "ប្រភេទបន្ទប់"],
  c_rent: ["Monthly Rent", "ថ្លៃឈ្នួលប្រចាំខែ"],
  c_until: ["Until", "រហូតដល់"],
  c_lease: ["Lease", "កិច្ចសន្យា"],
  c_start: ["Start Date", "ថ្ងៃចាប់ផ្តើម"],
  c_end: ["End Date", "ថ្ងៃបញ្ចប់"],
  // new
  c_renewal: ["Renewal", "ការបន្ត"],
  c_day: ["Day", "ថ្ងៃ"],
  c_events: ["Events", "ព្រឹត្តិការណ៍"],
  c_rate: ["Rate", "អត្រា"],
  c_since: ["Since", "ចាប់ពី"],

  // Invoice register.
  s_issued: ["Issued", "បានចេញ"],
  s_paid_invoices: ["Paid to these Invoices", "បានបង់ទៅវិក្កយបត្រទាំងនេះ"],
  // new
  s_other_settled: [
    "Settled another way (Credit or Deposit)",
    "ទូទាត់ដោយវិធីផ្សេង (ឥណទាន ឬប្រាក់កក់)",
  ],
  // new
  s_invoices: ["Invoices", "វិក្កយបត្រ"],
  // new
  s_void: [
    "{0} void, listed but not added up",
    "{0} ទុកជាមោឃៈ មានក្នុងបញ្ជី តែមិនបូកចូល",
  ],
  groups: ["Overdue groups", "ក្រុមហួសកំណត់"],
  days_1_19: ["1 to 19 days", "1 ដល់ 19 ថ្ងៃ"],
  days_20_29: ["20 to 29 days", "20 ដល់ 29 ថ្ងៃ"],
  days_30_plus: ["30 days or more", "30 ថ្ងៃឡើង"],
  // new
  days_over1: ["1 day overdue", "ហួសកំណត់ 1 ថ្ងៃ"],
  // new
  days_over: ["{0} days overdue", "ហួសកំណត់ {0} ថ្ងៃ"],
  ch_invoice_register: [
    "Paid and still owed, by issue month",
    "បានបង់ និងនៅជំពាក់ តាមខែចេញ",
  ],
  st_paid: ["Paid", "បានបង់"],
  st_part: ["Part paid", "បង់បានខ្លះ"],
  st_unpaid: ["Not paid", "មិនទាន់បង់"],
  st_overdue: ["Overdue", "ហួសកំណត់"],
  st_void: ["Void", "ទុកជាមោឃៈ"],
  st_draft: ["Draft", "សេចក្តីព្រាង"],
  cat_RENT: ["Rent", "ថ្លៃឈ្នួល"],
  cat_UTILITIES: ["Utilities", "ថ្លៃទឹកភ្លើង"],
  cat_SERVICE_CHARGES: ["Services", "សេវា"],
  cat_DAMAGE_CHARGES: ["Damage", "ការខូចខាត"],
  cat_MISCELLANEOUS_CHARGES: ["Miscellaneous", "ផ្សេងៗ"],

  // Payments and allocations (DL-072 answer 10, DL-079 answer 7).
  s_received: ["Money received", "ប្រាក់បានទទួល"],
  // new
  s_payments: ["Payments", "ការបង់ប្រាក់"],
  // new
  s_where: ["Where the money went", "លុយទៅណា"],
  l_INVOICES: ["Paid to Invoices", "បង់ទៅវិក្កយបត្រ"],
  l_DEPOSITS: ["Deposits", "ប្រាក់កក់"],
  l_CREDIT: ["Customer Credit", "ឥណទានអតិថិជន"],
  l_LATE_PAYMENT_CHARGES: ["Late-payment charges", "ថ្លៃពិន័យបង់យឺត"],
  // new
  l_REFUNDED: ["Refunded from the payment", "បានសងវិញពីការបង់ប្រាក់"],
  l_NOT_ALLOCATED: ["Not allocated", "មិនទាន់បែងចែក"],
  // new: what was left of a payment that was reversed later.
  l_REVERSED_LATER: ["Reversed later", "បានត្រឡប់វិញនៅពេលក្រោយ"],
  // The parts of Paid to Invoices; Move-out charges are cleaning, damage and other one-time
  // Invoices, as on the Payments cards.
  p_rent: ["Rent", "ថ្លៃឈ្នួល"],
  p_services: ["Services", "សេវា"],
  p_utilities: ["Utilities", "ទឹកភ្លើង"],
  p_move_out: ["Move-out charges", "ថ្លៃពេលចាកចេញ"],
  // new
  of_which: ["of which {0}", "ក្នុងនោះ {0}"],
  // new
  s_reversals: ["Reversals", "ការត្រឡប់វិញ"],
  // new
  s_net: ["Received less reversals", "ប្រាក់ទទួល ដកការត្រឡប់វិញ"],
  // changed: move-out charges are on Invoices (DL-079 answer 7); "period All" added, because the
  // Invoice register counts by Invoice date and this report by the day the money came in.
  recon: [
    "Money received also holds deposits, late-payment charges and Credit that are not on an Invoice. Of this, {0} paid Invoices. Over the same records (period All), that is the Paid total in the Invoice register.",
    "ប្រាក់បានទទួល រួមមានប្រាក់កក់ ថ្លៃពិន័យ និងឥណទាន ដែលមិននៅលើវិក្កយបត្រ។ ក្នុងនោះ {0} បានបង់វិក្កយបត្រ។ សម្រាប់កំណត់ត្រាដូចគ្នា (រយៈពេល ទាំងអស់) នោះជាសរុបបានបង់ក្នុងបញ្ជីវិក្កយបត្រ។",
  ],
  // new
  riel_received: [
    "Riel received: {0}. Counted at the dollar value recorded on the day; never added to USD.",
    "រៀលបានទទួល៖ {0}។ រាប់តាមតម្លៃដុល្លារដែលបានកត់ត្រានៅថ្ងៃនោះ; មិនបូកចូលដុល្លារទេ។",
  ],
  // new
  riel_rate: ["{0} ៛ = $1.00", "{0} ៛ = $1.00"],
  // new
  reversed_on: ["Reversed {0}", "បានត្រឡប់វិញ {0}"],
  st_received: ["Received", "បានទទួល"],
  ch_payments: [
    "Money received by month and kind",
    "ប្រាក់ទទួលតាមខែ និងប្រភេទ",
  ],

  // Utility consumption.
  // new
  s_periods: ["Reading periods", "រយៈពេលអាន"],
  s_estimates: ["Estimates", "ការប៉ាន់ស្មាន"],
  // new
  not_billed: ["Not billed yet", "មិនទាន់គិតថ្លៃ"],
  ch_kwh: ["Electricity used (kWh)", "អគ្គិសនីប្រើ (kWh)"],
  ch_m3: ["Water used (m³)", "ទឹកប្រើ (m³)"],
  rates_t: ["Utility Rates", "អត្រាទឹកភ្លើង"],
  // changed: "(UI-060)" left out.
  rates_n: [
    "A Rate change needs notice before it starts; the old Rate keeps billing until then.",
    "ការប្តូរអត្រាត្រូវមានការជូនដំណឹងមុនចាប់ផ្តើម; អត្រាចាស់នៅគិតថ្លៃរហូតដល់ពេលនោះ។",
  ],

  // Customer Credit ledger.
  // new
  s_credits: ["Credits", "ឥណទាន"],
  // new
  s_left_now: ["Credit left", "ឥណទាននៅសល់"],
  // new
  ch_credit_ledger: ["Customer Credit by outcome", "ឥណទានអតិថិជនតាមលទ្ធផល"],

  // Deposit liability and disposition.
  dep_SECURITY: ["Security Deposit", "ប្រាក់កក់សុវត្ថិភាព"],
  dep_PET: ["Pet Deposit", "ប្រាក់កក់សត្វចិញ្ចឹម"],
  // new
  s_held_now: ["Held now", "កាន់កាប់ឥឡូវ"],
  // new
  s_deposit_count: ["Deposits", "ប្រាក់កក់"],
  ch_deposits: ["Deposit money by outcome", "ប្រាក់កក់តាមលទ្ធផល"],
  // new
  settled: ["Final Settlement closed", "ការទូទាត់ចុងក្រោយបានបិទ"],
  rec_lease: ["Lease", "កិច្ចសន្យា"],
  rec_reservation: ["Reservation", "ការកក់"],
  rs_SIGNED: ["Signed", "បានចុះហត្ថលេខា"],
  rs_DRAFTED: ["Draft", "សេចក្តីព្រាង"],
  rs_TERMINATED: ["Terminated", "បានបញ្ចប់មុនកំណត់"],
  // new
  rs_ENDED: ["Ended", "បានបញ្ចប់"],
  rs_CANCELLED: ["Cancelled", "បានលុបចោល"],
  rs_ACTIVE: ["Active", "កំពុងដំណើរការ"],
  rs_COMPLETED: ["Completed", "បានបញ្ចប់"],
  rs_EXPIRED: ["Expired", "ផុតកំណត់"],

  // Final Settlement register.
  // new
  st_open: ["Open", "បើក"],
  st_closed: ["Closed", "បានបិទ"],
  ch_final_settlements: ["Final Settlement totals", "សរុបការទូទាត់ចុងក្រោយ"],

  // Unit occupancy.
  u_OCCUPIED: ["Occupied", "មានអ្នកជួល"],
  u_RESERVED: ["Reserved", "បានកក់"],
  u_VACANT: ["Vacant", "ទំនេរ"],
  u_CLEANING: ["Cleaning", "កំពុងសម្អាត"],
  u_UNDER_MAINTENANCE: ["Under maintenance", "កំពុងជួសជុល"],
  u_OUT_OF_SERVICE: ["Out of service", "ឈប់ប្រើ"],
  s_occupied: ["Occupied", "មានអ្នកជួល"],
  s_reserved: ["Reserved", "បានកក់"],
  s_vacant: ["Vacant", "ទំនេរ"],
  s_not_available: ["Not available", "មិនអាចប្រើបាន"],
  // new
  s_units: ["Units", "បន្ទប់"],
  // new
  n_units1: ["1 Unit", "បន្ទប់ 1"],
  // new
  n_units: ["{0} Units", "បន្ទប់ {0}"],
  ch_unit_occupancy: ["Units by status", "បន្ទប់តាមស្ថានភាព"],

  // Lease dates.
  s_current: ["Current", "បច្ចុប្បន្ន"],
  // new
  s_ending: ["Ending within 60 days", "បញ្ចប់ក្នុង 60 ថ្ងៃ"],
  // new
  s_no_renewal: ["Ending, no renewal drafted", "ជិតបញ្ចប់ មិនទាន់ព្រាងការបន្ត"],
  s_terminated: ["Terminated", "បានបញ្ចប់មុនកំណត់"],
  in_days: ["in {0} days", "ក្នុង {0} ថ្ងៃ"],
  // new
  ended_early: ["Ended early", "បញ្ចប់មុនកំណត់"],
  // new
  drafted: ["Drafted", "បានព្រាង"],
  // new
  n_leases1: ["1 Lease", "កិច្ចសន្យា 1"],
  // new
  n_leases: ["{0} Leases", "កិច្ចសន្យា {0}"],
  // new
  ch_lease_dates: ["Leases ending by month", "កិច្ចសន្យាបញ្ចប់តាមខែ"],
  // new
  leases: ["Leases", "កិច្ចសន្យា"],

  // Audit activity.
  s_events: ["Events", "ព្រឹត្តិការណ៍"],
  by_actor: ["By person", "តាមបុគ្គល"],
  by_kind: ["By action", "តាមសកម្មភាព"],
  open_history: ["Open History", "បើកប្រវត្តិ"],
  ch_audit_activity: ["Events per day", "ព្រឹត្តិការណ៍ក្នុងមួយថ្ងៃ"],
  // V1-060 B7: when the period has more days with events than the chart shows.
  ch_audit_last: [
    "Events per day, the last {0} days with events",
    "ព្រឹត្តិការណ៍ក្នុងមួយថ្ងៃ {0} ថ្ងៃចុងក្រោយដែលមានព្រឹត្តិការណ៍",
  ],
  // new
  system: ["System", "ប្រព័ន្ធ"],

  // The export dialog (UI-021, UI-087).
  // changed: "Export" in place of "Export CSV".
  ex_title: ["Export · {0}", "នាំចេញ · {0}"],
  // new
  ex_report: ["Report", "របាយការណ៍"],
  // new
  ex_rows: ["Rows", "ជួរ"],
  // new
  ex_type: ["File type", "ប្រភេទឯកសារ"],
  // new
  ex_xlsx: ["Spreadsheet (.xlsx)", "សៀវភៅបញ្ជី (.xlsx)"],
  // new
  ex_pdf: ["PDF", "PDF"],
  ex_sens: [
    "This file has personal data (names, Units, phone numbers). Keep it inside the business and delete it when done.",
    "ឯកសារនេះមានទិន្នន័យផ្ទាល់ខ្លួន (ឈ្មោះ បន្ទប់ លេខទូរស័ព្ទ)។ រក្សាក្នុងអាជីវកម្ម និងលុបពេលរួចរាល់។",
  ],
  ex_logged: [
    "Every export is written to History with who, when and which filters. Small files are not kept; big files are kept 24 hours.",
    "ការនាំចេញនីមួយៗ សរសេរក្នុងប្រវត្តិ ជាមួយអ្នកណា ពេលណា តម្រងអ្វី។ ឯកសារតូចមិនរក្សាទុក; ឯកសារធំរក្សា 24 ម៉ោង។",
  ],
  // new
  ex_pdf_note: [
    "A PDF holds at most 5,000 rows and shows Khmer names only in the spreadsheet.",
    "PDF មានអតិបរមា 5,000 ជួរ ហើយឈ្មោះខ្មែរបង្ហាញតែក្នុងសៀវភៅបញ្ជីប៉ុណ្ណោះ។",
  ],
  ex_ok: ["Export", "នាំចេញ"],
  cancel: ["Cancel", "បោះបង់"],
  // new
  ex_saved: [
    "{0} is ready. The export is written to History.",
    "{0} រួចរាល់។ ការនាំចេញត្រូវបានសរសេរក្នុងប្រវត្តិ។",
  ],
  // new
  ex_failed: [
    "The file could not be made just now. Try again.",
    "មិនអាចបង្កើតឯកសារបានទេឥឡូវនេះ។ សូមព្យាយាមម្តងទៀត។",
  ],
  // new
  ex_refused: [
    "This file cannot be made with these choices. Choose a shorter period, or a spreadsheet instead of a PDF.",
    "មិនអាចបង្កើតឯកសារនេះជាមួយជម្រើសទាំងនេះបានទេ។ សូមជ្រើសរយៈពេលខ្លីជាងនេះ ឬសៀវភៅបញ្ជីជំនួស PDF។",
  ],
  // new
  ex_not_allowed: [
    "Your account cannot export this report.",
    "គណនីរបស់អ្នកមិនអាចនាំចេញរបាយការណ៍នេះបានទេ។",
  ],
  // new
  ex_gone: [
    "The file is no longer kept. Export it again.",
    "ឯកសារនេះលែងរក្សាទុកហើយ។ សូមនាំចេញម្តងទៀត។",
  ],
} as const satisfies Record<string, readonly [string, string]>;

export type ReportsTextKey = keyof typeof TEXT;

/** The words for `key`, with {0}, {1} … filled in. */
export function rpt(
  language: Language,
  key: ReportsTextKey,
  ...values: (string | number)[]
): string {
  const text = TEXT[key][language === "km" ? 1 : 0];
  return text.replace(/\{(\d+)\}/g, (match, index: string) => {
    const value = values[Number(index)];
    return value === undefined ? match : String(value);
  });
}

/** Does a text key exist? For codes that come from the server, such as a status. */
export function hasText(key: string): key is ReportsTextKey {
  return Object.prototype.hasOwnProperty.call(TEXT, key);
}

const MONTHS = {
  en: [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
  ],
  km: [
    "មករា",
    "កុម្ភៈ",
    "មីនា",
    "មេសា",
    "ឧសភា",
    "មិថុនា",
    "កក្កដា",
    "សីហា",
    "កញ្ញា",
    "តុលា",
    "វិច្ឆិកា",
    "ធ្នូ",
  ],
} as const;

/** A column head: "Jan" in English; Khmer month names are short already (mock-up). */
export function monthHead(language: Language, month: number): string {
  const name = MONTHS[language][month] ?? "";
  return language === "en" ? name.slice(0, 3) : name;
}

/** "2026-10" → "October 2026". */
export function monthName(language: Language, month: string): string {
  const name = MONTHS[language][Number(month.slice(5, 7)) - 1] ?? "";
  return `${name} ${month.slice(0, 4)}`;
}

/** "2026-10" → "Oct 26", for a chart axis. */
export function monthShort(language: Language, month: string): string {
  return `${monthHead(language, Number(month.slice(5, 7)) - 1)} ${month.slice(2, 4)}`;
}
