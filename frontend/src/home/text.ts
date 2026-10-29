// V1-058 R6: the words of Home in English and Khmer, from the owner's mock-up (i18n.js,
// i18n10.js). Khmer needs the native check before the app is used. Lines marked "new" are not
// in the mock-up.

import type { Language } from "../signInText";

const TEXT = {
  as_of: ["As of {0}", "គិតត្រឹមម៉ោង {0}"],
  qa_record: ["Receive payment", "ទទួលការបង់ប្រាក់"],
  qa_readings: ["Enter meter readings", "បញ្ចូលអំណាននាឡិកាស្ទង់"],
  // new
  loading: ["Loading Home…", "កំពុងផ្ទុកទំព័រដើម…"],
  // new
  failed: [
    "Home could not be read just now. Check the connection and try again.",
    "មិនអាចអានទំព័រដើមបានទេឥឡូវនេះ។ សូមពិនិត្យការតភ្ជាប់ ហើយព្យាយាមម្តងទៀត។",
  ],
  // new
  not_allowed: [
    "Your account cannot see the Home numbers. Use the menu to open your work.",
    "គណនីរបស់អ្នកមិនអាចមើលលេខទំព័រដើមបានទេ។ សូមប្រើម៉ឺនុយ ដើម្បីបើកការងាររបស់អ្នក។",
  ],
  retry: ["Retry", "ព្យាយាមម្តងទៀត"],

  k_occ: ["Parking occupied", "ចំណតមានអ្នកជួល"],
  k_occ_s: ["{0} reserved · {1} vacant", "បានកក់ {0} · ទំនេរ {1}"],
  k_pend: ["Pending payment", "ប្រាក់មិនទាន់បង់"],
  k_pend_s: ["{0} Invoices not fully paid", "វិក្កយបត្រ {0} មិនទាន់បង់គ្រប់"],
  // new
  k_pend_s1: ["1 Invoice not fully paid", "វិក្កយបត្រ 1 មិនទាន់បង់គ្រប់"],
  k_paid: ["Paid for {0}", "បានបង់សម្រាប់ខែ{0}"],
  k_paid_s: ["{0}% of {1} billed", "{0}% នៃ {1} ដែលបានចេញ"],
  // new
  k_paid_none: [
    "Nothing billed for this month yet",
    "មិនទាន់មានវិក្កយបត្រសម្រាប់ខែនេះ",
  ],
  // new
  k_paid_recv: [
    "Received this month · {0} payments",
    "បានទទួលខែនេះ · ការបង់ប្រាក់ {0}",
  ],
  // new
  k_paid_recv1: [
    "Received this month · 1 payment",
    "បានទទួលខែនេះ · ការបង់ប្រាក់ 1",
  ],
  k_over: ["Overdue", "ហួសកំណត់"],
  k_over_s: [
    "{0} Invoices past the due date",
    "វិក្កយបត្រ {0} ហួសថ្ងៃកំណត់បង់",
  ],
  // new
  k_over_s1: ["1 Invoice past the due date", "វិក្កយបត្រ 1 ហួសថ្ងៃកំណត់បង់"],
  n_lease: ["Lease renewal", "ការបន្តកិច្ចសន្យា"],
  n_lease_s: ["End before {0}", "ផុតកំណត់មុន {0}"],
  n_appr: ["Waiting for approval", "រង់ចាំការអនុម័ត"],
  n_appr_s: [
    "{0} to confirm · {1} money out",
    "{0} ត្រូវបញ្ជាក់ · ប្រាក់ចេញ {1}",
  ],
  // new
  n_appr_c: ["{0} to confirm", "{0} ត្រូវបញ្ជាក់"],
  n_read: ["Meter readings missing", "អំណានដែលខ្វះ"],
  n_read_s: ["Reading day {0}", "ថ្ងៃអាន {0}"],
  n_letters: ["Letters due", "លិខិតត្រូវផ្តល់"],
  n_letters_s: ["Day-20 and day-30 letters", "លិខិតថ្ងៃទី២០ និងថ្ងៃទី៣០"],

  todo_t: ["What to do", "អ្វីដែលត្រូវធ្វើ"],
  todo_sum: [
    "{0} overdue, {1} for today, {2} this week. Do them from the top down.",
    "ហួសកំណត់ {0} · ថ្ងៃនេះ {1} · សប្តាហ៍នេះ {2}។ ធ្វើពីលើចុះក្រោម។",
  ],
  g_overdue: ["Overdue", "ហួសកំណត់"],
  g_today: ["Today", "ថ្ងៃនេះ"],
  g_this_week: ["This week", "សប្តាហ៍នេះ"],
  g_later: ["Later", "ពេលក្រោយ"],
  g_over_none: ["Nothing is overdue.", "គ្មានអ្វីហួសកំណត់ទេ។"],
  g_none: ["Nothing here.", "គ្មានអ្វីទេ។"],
  show_more: ["Show {0}", "បង្ហាញ {0}"],
  show_less: ["Hide", "លាក់"],

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
  r_appr: ["{0} waiting for approval", "{0} រង់ចាំការអនុម័ត"],
  r_letter: ["{0} letter due: {1}", "លិខិត{0} ត្រូវផ្តល់៖ {1}"],
  // new
  r_letter_d: ["{0} · {1} still owed", "{0} · {1} នៅជំពាក់"],
  day20: ["Day 20", "ថ្ងៃទី២០"],
  day30: ["Day 30", "ថ្ងៃទី៣០"],
  r_depdec: [
    "Deposit waiting for a decision: {0}",
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
    "The ABA exchange rate has not been read yet",
    "មិនទាន់អានអត្រាប្តូរប្រាក់ ABA នៅឡើយ",
  ],
  job_next: ["Next Invoices: {0}", "វិក្កយបត្របន្ទាប់៖ {0}"],
  tip_inv: ["Open Invoice", "បើកវិក្កយបត្រ"],
  tip_resv: ["Open Reservation", "បើកការកក់"],
  tip_read: ["Open meter readings", "បើកអំណាននាឡិកាស្ទង់"],
  tip_lease: ["Open Lease", "បើកកិច្ចសន្យា"],
  tip_appr: ["Open the draft", "បើកសេចក្តីព្រាង"],
  tip_letter: ["Open Letters", "បើកលិខិត"],
} as const satisfies Record<string, readonly [string, string]>;

export type HomeTextKey = keyof typeof TEXT;

export function hmt(
  language: Language,
  key: HomeTextKey,
  ...values: (string | number)[]
): string {
  const text = TEXT[key][language === "en" ? 0 : 1];
  return text.replace(/\{(\d+)\}/g, (match, index: string) => {
    const value = values[Number(index)];
    return value === undefined ? match : String(value);
  });
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
