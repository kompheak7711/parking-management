// V1-058 R6: the words of Home in English and Khmer, from the owner's mock-up (i18n.js,
// i18n10.js). Khmer needs the native check before the app is used. Lines marked "new" are not
// in the mock-up.

import type { Language } from "../signInText";
import { singular } from "../shell/plural";

const TEXT = {
  as_of: ["As of {0}", "គិតត្រឹមម៉ោង {0}"],
  // UI v81 round 2: the head line "CHETANA Residence · Tuesday 03/11/2026 · As of 10:30".
  property: ["CHETANA Residence", "CHETANA Residence"],
  qa_record: ["Receive payment", "ទទួលការបង់ប្រាក់"],
  qa_readings: ["Enter meter readings", "បញ្ចូលអំណាននាឡិកាស្ទង់"],
  // new
  loading: ["Loading Home…", "កំពុងផ្ទុកទំព័រដើម…"],
  // new
  failed: [
    "Home could not be loaded. Check the connection and try again.",
    "មិនអាចអានទំព័រដើមបានទេឥឡូវនេះ។ សូមពិនិត្យការតភ្ជាប់ ហើយព្យាយាមម្តងទៀត។",
  ],
  // new
  not_allowed: [
    "Your account cannot see the Home numbers. Use the menu to open your work.",
    "គណនីរបស់អ្នកមិនអាចមើលលេខទំព័រដើមបានទេ។ សូមប្រើម៉ឺនុយ ដើម្បីបើកការងាររបស់អ្នក។",
  ],
  retry: ["Retry", "ព្យាយាមម្តងទៀត"],

  // UI v81 round 2 (design v81 i18n25): the card names of the design.
  // Owner 12/11/2026: the Occupancy card is a Vacant card (vacant Units only).
  k_vac: ["Vacant Units", "បន្ទប់ទំនេរ"], // new
  k_vac_s: ["{0} Units · {1} reserved", "បន្ទប់ {0} · បានកក់ {1}"], // new
  // Owner 14/11/2026: "Unpaid", the same word as the Invoices card it opens ("Total unpaid").
  k_pend: ["Unpaid", "ប្រាក់មិនទាន់បង់"],
  k_paid: ["Paid this month", "បានបង់ខែនេះ"],
  k_over: ["Overdue", "ហួសកំណត់"],
  n_lease: ["Leases ending soon", "កិច្ចសន្យាជិតផុតកំណត់"],
  n_lease_s: ["End before {0}", "ផុតកំណត់មុន {0}"],
  n_appr: ["Approvals", "រង់ចាំការអនុម័ត"],
  // "Refunds pending" is the approved word for money out (docs/ui-audit/04_GLOSSARY.md).
  // Owner 14/11/2026: the Approvals note says only the money going out.
  n_appr_m: ["Refunds pending {0}", "ការសងប្រាក់កំពុងរង់ចាំ {0}"],
  // Home screen review (owner 14/11/2026): shorter English names so each fits one line.
  n_read: ["Missing readings", "អំណានដែលខ្វះ"],
  n_letters: ["Notices due", "លិខិតត្រូវផ្តល់"],
  // DL-131 (mock-up round 32 A10); Khmer is new and needs the native check.
  n_problems: ["Problem reports", "របាយការណ៍បញ្ហា"],
  // Design v81 i18n13 (Viewing requests waiting on Home). Khmer from the design.
  n_vr: ["Viewing requests", "សំណើមើលបន្ទប់កំពុងរង់ចាំ"],
  // Owner 14/11/2026: a note says only the parts above 0.
  n_vr_late: ["{0} late", "{0} យឺត"],
  n_vr_week: ["{0} visits this week", "{0} ការមកមើលសប្តាហ៍នេះ"],
  n_problems_urgent: ["{0} urgent", "{0} បន្ទាន់"],
  n_problems_late: ["{0} late", "{0} យឺត"],
  n_costs: ["Repair costs to check", "ថ្លៃជួសជុលត្រូវពិនិត្យ"],
  // UI v81 round 4 (owner 08/11/2026): the Birthdays card (design i18n).
  n_bday: ["Birthdays", "ថ្ងៃកំណើត"],
  n_week_s: ["Today to {0}", "ថ្ងៃនេះ ដល់ {0}"],
  // Owner 12/11/2026: two Short stays cards, and Low stock in place of Paid on time. Khmer is
  // new and needs the native check.
  n_ssb: ["Bookings", "ការកក់ស្នាក់នៅខ្លី"], // new
  n_ssb_s: ["{0} arrive today", "{0} មកដល់ថ្ងៃនេះ"], // new
  n_ssb_s1: ["1 arrives today", "1 មកដល់ថ្ងៃនេះ"], // new
  n_ssin: ["Checked in", "ភ្ញៀវស្នាក់នៅខ្លីបានចូល"], // new
  n_ssin_s: ["{0} check out today", "{0} ចេញថ្ងៃនេះ"], // new
  n_ssin_s1: ["1 checks out today", "1 ចេញថ្ងៃនេះ"], // new
  n_low: ["Low stock", "ស្តុកតិច"],

  todo_t: ["Tasks", "ការងារត្រូវធ្វើ"],
  g_overdue: ["Overdue", "ហួសកំណត់"],
  g_today: ["Today", "ថ្ងៃនេះ"],
  g_this_week: ["This week", "សប្តាហ៍នេះ"],
  g_later: ["Later", "ពេលក្រោយ"],
  g_over_none: ["Nothing is overdue.", "គ្មានអ្វីហួសកំណត់ទេ។"],
  g_none: ["Nothing here.", "គ្មានអ្វីទេ។"],
  show_more: ["Show {0}", "បង្ហាញ {0}"],
  show_less: ["Hide", "លាក់"],
  // UI v81 round 3 (owner 07/11/2026 17:30): the Tasks are four cards, one list open at a time.
  tk_oldest: ["Oldest: {0}", "ចាស់បំផុត៖ {0}"], // new (UI v81 round 3)
  tk_next: ["Next: {0}", "បន្ទាប់៖ {0}"], // new (UI v81 round 3)

  r_over: ["{0}: {1} not paid", "{0}៖ {1} មិនទាន់បង់"],
  // new
  r_over_d: ["{0} · {1} · Initial Rent", "{0} · {1} · ថ្លៃឈ្នួលដំបូង"],
  r_resv: ["Reservation for {0} ends", "ការកក់ {0} ផុតកំណត់"],
  r_read: ["Meter reading day", "ថ្ងៃអាននាឡិកាស្ទង់"],
  // new
  r_read_d: [
    "{0} meters not read yet. Invoices go out the next day.",
    "នាឡិកាស្ទង់ {0} មិនទាន់អាន។ វិក្កយបត្រចេញនៅថ្ងៃបន្ទាប់។",
  ],
  r_lease: ["Lease for {0} ends", "កិច្ចសន្យា {0} ផុតកំណត់"],
  r_lease_d: ["{0}. Ask about renewing.", "{0}។ សួរអំពីការបន្ត។"],
  r_appr: ["{0} pending approval", "{0} រង់ចាំការអនុម័ត"],
  r_letter: ["{0} due: {1}", "{0} ត្រូវផ្តល់៖ {1}"],
  // new
  r_letter_d: ["{0} · {1} still owed", "{0} · {1} នៅជំពាក់"],
  day20: ["Rent notice", "លិខិតជូនដំណឹងថ្លៃឈ្នួល"],
  day30: ["Termination letter", "លិខិតបញ្ចប់កិច្ចសន្យា"],
  r_depdec: [
    "Deposit pending a decision: {0}",
    "ប្រាក់កក់រង់ចាំការសម្រេច៖ {0}",
  ],
  // new
  r_settle: ["Final Settlement still open: {0}", "ការទូទាត់ចុងក្រោយនៅបើក៖ {0}"],
  // new
  r_refund: ["Deposit refund due: {0}", "ត្រូវសងប្រាក់កក់វិញ៖ {0}"],
  // new
  r_refund_d: ["{0} · {1} held", "{0} · កាន់កាប់ {1}"],
  // new
  dk_REFUND: ["Refund", "ការសងប្រាក់វិញ"],
  // new
  dk_DEPOSIT_FORFEITURE: ["Deposit kept", "ការរក្សាប្រាក់កក់"],
  // new
  dk_PAYMENT_MOVE: ["Payment move", "ការផ្លាស់ការបង់ប្រាក់"],
  // new
  dk_FINAL_SETTLEMENT: ["Final Settlement", "ការទូទាត់ចុងក្រោយ"],
  // new
  dk_SETTLEMENT_CORRECTION: ["Settlement correction", "ការកែការទូទាត់"],
  // new
  dk_other: ["A draft", "សេចក្តីព្រាង"],
  // new
  r_appr_d: ["Prepared on {0}", "រៀបចំថ្ងៃ {0}"],

  rel_today: ["today", "ថ្ងៃនេះ"],
  rel_tomorrow: ["tomorrow", "ថ្ងៃស្អែក"],
  rel_in: ["in {0} days", "ក្នុង {0} ថ្ងៃទៀត"],
  rel_ago: ["{0} days ago", "{0} ថ្ងៃមុន"],
  rel_yesterday: ["yesterday", "ម្សិលមិញ"],
  rel_late: ["{0} days late", "យឺត {0} ថ្ងៃ"],
  rel_late1: ["1 day late", "យឺត 1 ថ្ងៃ"],

  job_bill: [
    "Rent and Utility Invoices made on {0}",
    "វិក្កយបត្រថ្លៃឈ្នួល និងទឹកភ្លើង ចេញថ្ងៃ {0}",
  ],
  // new
  job_bill_none: [
    "No billing run has finished yet",
    "មិនទាន់មានការចេញវិក្កយបត្របានបញ្ចប់នៅឡើយ",
  ],
  job_rate: [
    "ABA exchange rate updated on {0}",
    "អត្រាប្តូរប្រាក់ ABA ធ្វើបច្ចុប្បន្នភាពថ្ងៃ {0}",
  ],
  // new
  job_rate_none: [
    "The ABA exchange rate has not been loaded yet.",
    "មិនទាន់អានអត្រាប្តូរប្រាក់ ABA នៅឡើយ",
  ],
  job_next: ["Next Invoices: {0}", "វិក្កយបត្របន្ទាប់៖ {0}"],
  tip_inv: ["Open Invoice", "បើកវិក្កយបត្រ"],
  tip_resv: ["Open Reservation", "បើកការកក់"],
  tip_read: ["Open meter readings", "បើកអំណាននាឡិកាស្ទង់"],
  tip_lease: ["Open Lease", "បើកកិច្ចសន្យា"],
  tip_appr: ["Open the draft", "បើកសេចក្តីព្រាង"],
  tip_letter: ["Open Notices", "បើកលិខិត"],
  // UI v81 (design v81 Home): the Owner's money box and Attendance. Owner 12/11/2026: the box
  // is named "Financial summary" and no longer says "Only the Owner sees this".
  om_t: ["Financial summary", "សង្ខេបហិរញ្ញវត្ថុ"], // new
  om_cash: ["Cash & bank", "សាច់ប្រាក់ និងធនាគារថ្ងៃនេះ"], // new
  om_over: ["30+ days late", "ជំពាក់លើស ៣០ ថ្ងៃ"], // new
  om_spent: ["Spent this month", "ចំណាយខែនេះ"], // new
  om_spent_s: ["Budget {0}", "ថវិកា {0}"], // new
  om_nobudget: ["No budget for this month", "គ្មានថវិកាសម្រាប់ខែនេះ"], // new
  om_profit: ["Profit this year", "ចំណេញឆ្នាំនេះ"], // new
  // Owner 12/11/2026: Attendance is a card like the others, named "Attendance".
  at_t: ["Attendance", "វត្តមាន"],
  at_n: [
    "Needs check {0} · No check-out {1}",
    "ត្រូវពិនិត្យ {0} · គ្មានការចុះចេញ {1}",
  ], // new
} as const satisfies Record<string, readonly [string, string]>;

export type HomeTextKey = keyof typeof TEXT;

export function hmt(
  language: Language,
  key: HomeTextKey,
  ...values: (string | number)[]
): string {
  const text = TEXT[key][language === "en" ? 0 : 1];
  return singular(
    text.replace(/\{(\d+)\}/g, (match, index: string) => {
      const value = values[Number(index)];
      return value === undefined ? match : String(value);
    }),
  );
}

const WEEKDAYS = {
  en: [
    "Sunday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
  ],
  km: [
    "ថ្ងៃអាទិត្យ",
    "ថ្ងៃច័ន្ទ",
    "ថ្ងៃអង្គារ",
    "ថ្ងៃពុធ",
    "ថ្ងៃព្រហស្បតិ៍",
    "ថ្ងៃសុក្រ",
    "ថ្ងៃសៅរ៍",
  ],
};

/** "2026-11-03" → "Tuesday". */
export function weekdayText(language: Language, day: string): string {
  const date = new Date(`${day.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return "";
  return WEEKDAYS[language][date.getUTCDay()] ?? "";
}
