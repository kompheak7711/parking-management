// V1-058 R3: the words of the Letters screen in English and Khmer, from the owner's mock-up
// (i18n10.js, app10.js). Khmer needs the native check before the app is used. Lines marked
// "new" are not in the mock-up.

import type { Language } from "../signInText";

const TEXT = {
  sub: [
    "Rent letters on day 20 and day 30, and Lease rule warnings",
    "លិខិតថ្លៃឈ្នួលថ្ងៃទី២០ និងថ្ងៃទី៣០ និងការព្រមានអំពីវិន័យកិច្ចសន្យា",
  ],
  // new
  as_of: ["as of {0}", "គិតត្រឹម {0}"],
  tab_rent: ["Rent letters", "លិខិតថ្លៃឈ្នួល"],
  tab_warn: ["Lease rule warnings", "ការព្រមានវិន័យកិច្ចសន្យា"],
  // new
  loading: ["Loading the letters…", "កំពុងផ្ទុកលិខិត…"],
  // new
  failed: [
    "The letters could not be read just now. Check the connection and try again.",
    "មិនអាចអានលិខិតបានទេឥឡូវនេះ។ សូមពិនិត្យការតភ្ជាប់ ហើយព្យាយាមម្តងទៀត។",
  ],
  retry: ["Retry", "ព្យាយាមម្តងទៀត"],
  // new
  no_property: [
    "Choose the Property in Settings first.",
    "សូមជ្រើសរើសអគារក្នុងការកំណត់ជាមុនសិន។",
  ],
  // new
  not_allowed: [
    "You are not allowed to see this list.",
    "អ្នកមិនត្រូវបានអនុញ្ញាតឱ្យមើលបញ្ជីនេះទេ។",
  ],
  c_due: ["Letters due", "លិខិតត្រូវផ្តល់"],
  c_due_s: ["Day 20 or day 30 passed", "ថ្ងៃទី២០ ឬទី៣០ បានកន្លង"],
  c_w20: ["Day-20 letter given", "បានផ្តល់លិខិតថ្ងៃទី២០"],
  c_w20_s: ["Waiting for day 30", "រង់ចាំថ្ងៃទី៣០"],
  c_w30: ["Day-30 letter given", "បានផ្តល់លិខិតថ្ងៃទី៣០"],
  c_w30_s: ["Termination may follow", "អាចបញ្ចប់កិច្ចសន្យាបន្ទាប់"],
  // new
  showing: ["Showing: {0}", "កំពុងបង្ហាញ៖ {0}"],
  // new
  show_all: ["Show all", "បង្ហាញទាំងអស់"],
  late_open: [
    "Day 20 and day 30 have both passed and no letter is recorded yet.",
    "ថ្ងៃទី២០ និងទី៣០ បានកន្លងទាំងពីរ ហើយមិនទាន់កត់ត្រាលិខិតទេ។",
  ],
  cases: ["Unpaid Rent after day 20", "ថ្លៃឈ្នួលមិនទាន់បង់ក្រោយថ្ងៃទី២០"],
  col_case: ["Unit and Customer", "បន្ទប់ និងអតិថិជន"],
  col_month: ["Rent month", "ខែថ្លៃឈ្នួល"],
  col_20: ["Day-20 letter", "លិខិតថ្ងៃទី២០"],
  col_30: ["Day-30 letter", "លិខិតថ្ងៃទី៣០"],
  col_next: ["Next step", "ជំហានបន្ទាប់"],
  // new: the mock-up's two letter columns share one, so the table fits an iPad
  col_letters: ["Letters", "លិខិត"],
  dayn: ["Day {0}", "ថ្ងៃទី {0}"],
  due_date: ["Due Date {0}", "ថ្ងៃផុតកំណត់ {0}"],
  // new: the mock-up's "Rent still owed" column, as a line under the Customer
  owed_line: ["{0} Rent owed", "ថ្លៃឈ្នួលជំពាក់ {0}"],
  given: ["Given {0}", "បានផ្តល់ {0}"],
  due_since: ["Due since {0}", "ត្រូវផ្តល់តាំងពី {0}"],
  on: ["On {0}", "នៅ {0}"],
  rec: ["Record letter", "កត់ត្រាលិខិត"],
  wait30: ["Wait for day 30 ({0})", "រង់ចាំថ្ងៃទី៣០ ({0})"],
  term: ["Termination notice", "លិខិតបញ្ចប់កិច្ចសន្យា"],
  mgr_badge: ["MANAGER", "អ្នកគ្រប់គ្រង"],
  // new
  no_step: ["Nothing to do now", "គ្មានអ្វីត្រូវធ្វើឥឡូវ"],
  none: [
    "No Rent is unpaid on day 20. No letters are due.",
    "គ្មានថ្លៃឈ្នួលមិនទាន់បង់នៅថ្ងៃទី២០ទេ។ គ្មានលិខិតត្រូវផ្តល់ទេ។",
  ],
  // new
  none_here: ["No letters here.", "គ្មានលិខិតនៅទីនេះទេ។"],
  how_count: [
    "Day 1 is the 1st of the Rent month. November Rent gives the day-20 letter on 20/11 and the day-30 letter on 30/11. Only unpaid Rent counts, not Trash or Utilities. The Invoice Due Date is a different date: it starts the late-payment charge.",
    "ថ្ងៃទី១ គឺថ្ងៃទី១ នៃខែថ្លៃឈ្នួល។ ថ្លៃឈ្នួលខែវិច្ឆិកា ផ្តល់លិខិតថ្ងៃទី២០ នៅ 20/11 និងលិខិតថ្ងៃទី៣០ នៅ 30/11។ គិតតែថ្លៃឈ្នួលមិនទាន់បង់ មិនគិតសំរាម ឬទឹកភ្លើងទេ។ ថ្ងៃផុតកំណត់វិក្កយបត្រ ជាថ្ងៃផ្សេង៖ វាចាប់ផ្តើមថ្លៃពិន័យបង់យឺត។",
  ],
  nothing: [
    "A letter never ends the Lease, adds a fee or changes the Unit by itself. The Owner or a Manager decides each next step.",
    "លិខិតមិនបញ្ចប់កិច្ចសន្យា បន្ថែមថ្លៃ ឬប្តូរបន្ទប់ដោយខ្លួនឯងទេ។ ម្ចាស់ ឬអ្នកគ្រប់គ្រងសម្រេចជំហានបន្ទាប់នីមួយៗ។",
  ],
  // new
  letters_failed: [
    "The letters of {0} could not be read. Retry before recording one.",
    "មិនអាចអានលិខិតរបស់ {0} បានទេ។ សូមព្យាយាមម្តងទៀត មុនកត់ត្រា។",
  ],
  d_t: ["Record a Rent letter · {0}", "កត់ត្រាលិខិតថ្លៃឈ្នួល · {0}"],
  customer: ["Customer", "អតិថិជន"],
  d_owed: ["Rent still owed today", "ថ្លៃឈ្នួលនៅជំពាក់ថ្ងៃនេះ"],
  d_owed_note: [
    "Only the Rent line counts. Day 1 is {0}.",
    "គិតតែជួរថ្លៃឈ្នួល។ ថ្ងៃទី១ គឺ {0}។",
  ],
  d_which: ["Which letter", "លិខិតមួយណា"],
  d_20: ["Day-20 warning letter", "លិខិតព្រមានថ្ងៃទី២០"],
  d_30: ["Day-30 default notice", "លិខិតជូនដំណឹងខកខានថ្ងៃទី៣០"],
  d_given: ["already recorded", "បានកត់ត្រារួច"],
  d_date: ["Date given", "ថ្ងៃផ្តល់"],
  // new
  d_date_today: [
    "Today, {0}. The app records the day the letter is recorded, so record it on the day it is given.",
    "ថ្ងៃនេះ {0}។ កម្មវិធីកត់ត្រាថ្ងៃដែលកត់ត្រាលិខិត ដូច្នេះសូមកត់ត្រានៅថ្ងៃដែលផ្តល់។",
  ],
  d_how: ["How it was given", "របៀបផ្តល់"],
  d_how_e: ["Choose how it was given.", "សូមជ្រើសរបៀបផ្តល់។"],
  h_HAND: ["Handed to the tenant", "ប្រគល់ដល់អ្នកជួល"],
  h_DOOR: ["Left at the Unit with a witness", "ទុកនៅបន្ទប់ ដោយមានសាក្សី"],
  // new (owner 2026-10-25)
  h_EMAIL: ["Sent by email", "ផ្ញើតាមអ៊ីមែល"],
  h_TG: ["Sent by Telegram", "ផ្ញើតាម Telegram"],
  // new (owner 2026-10-25)
  h_WA: ["Sent by WhatsApp", "ផ្ញើតាម WhatsApp"],
  h_OTHER: ["Other", "ផ្សេងទៀត"],
  d_detail: ["Details", "ព័ត៌មានលម្អិត"],
  d_detail_h: [
    "For example: the tenant signed our copy; or the witness's name.",
    "ឧទាហរណ៍៖ អ្នកជួលបានចុះហត្ថលេខាលើច្បាប់ចម្លងយើង ឬឈ្មោះសាក្សី។",
  ],
  d_detail_e: ["Write the details.", "សូមសរសេរព័ត៌មានលម្អិត។"],
  d_no: ["Letter number", "លេខលិខិត"],
  d_no_ph: [
    "The number written on the paper letter",
    "លេខដែលសរសេរលើលិខិតក្រដាស",
  ],
  // new
  d_no_e: [
    "Write the letter number. The day-20 letter needs one.",
    "សូមសរសេរលេខលិខិត។ លិខិតថ្ងៃទី២០ ត្រូវការលេខ។",
  ],
  // new
  d_which_e: ["Choose the letter.", "សូមជ្រើសលិខិត។"],
  required: ["Required", "ត្រូវការ"],
  optional: ["Optional", "ស្រេចចិត្ត"],
  close: ["Cancel", "បោះបង់"],
  // new
  saving: ["Saving…", "កំពុងរក្សាទុក…"],
  // new
  try_again: ["Try again", "ព្យាយាមម្តងទៀត"],
  d_save: ["Record letter", "កត់ត្រាលិខិត"],
  d_toast: ["{0} recorded for {1}.", "បានកត់ត្រា {0} សម្រាប់ {1}។"],
  // new
  unknown: [
    "No answer came back, so it is not known whether it was saved. Press Try again: the same request is sent and it is saved only once.",
    "មិនមានចម្លើយត្រឡប់មកវិញ ដូច្នេះមិនដឹងថាបានរក្សាទុកឬអត់។ សូមចុច ព្យាយាមម្តងទៀត៖ សំណើដដែលត្រូវបានផ្ញើ ហើយរក្សាទុកតែម្តង។",
  ],
  // new
  refused: [
    "It was not saved. Check the values; if they look right, a rule or your access stopped it.",
    "មិនបានរក្សាទុកទេ។ សូមពិនិត្យតម្លៃ។ បើត្រឹមត្រូវ ច្បាប់ ឬសិទ្ធិរបស់អ្នកបានបញ្ឈប់វា។",
  ],
  // new
  conflict: [
    "Somebody changed this meanwhile. The list was read again; check it and try once more.",
    "មាននរណាម្នាក់បានប្តូរវាក្នុងពេលនេះ។ បញ្ជីត្រូវបានអានម្តងទៀត។ សូមពិនិត្យ ហើយព្យាយាមម្តងទៀត។",
  ],
  lw_rule: [
    "Three written warnings about the same or a repeated breach come before ending a Lease for a rule breach. Three warnings count even when they are about different breaches. A serious breach (a crime, or danger to people or the building) may end it at once.",
    "ការព្រមានជាលាយលក្ខណ៍អក្សរបីដង អំពីការរំលោភដដែល ឬម្តងហើយម្តងទៀត ត្រូវមានមុនបញ្ចប់កិច្ចសន្យាដោយសារការរំលោភវិន័យ។ ការព្រមានបីដងរាប់ ទោះបីអំពីការរំលោភខុសគ្នាក៏ដោយ។ ការរំលោភធ្ងន់ធ្ងរ (បទល្មើស ឬគ្រោះថ្នាក់ដល់មនុស្ស ឬអគារ) អាចបញ្ចប់វាភ្លាម។",
  ],
  lw_lease: ["Lease", "កិច្ចសន្យា"],
  lw_col_n: ["Warnings", "ការព្រមាន"],
  lw_col_last: ["Last warning", "ការព្រមានចុងក្រោយ"],
  lw_col_what: ["Breach", "ការរំលោភ"],
  lw_n: ["{0} of 3", "{0} ក្នុង ៣"],
  lw_new: ["Record warning", "កត់ត្រាការព្រមាន"],
  lw_none: [
    "No Lease rule warnings recorded.",
    "គ្មានការព្រមានវិន័យកិច្ចសន្យាដែលបានកត់ត្រាទេ។",
  ],
  // new
  lw_some_failed: [
    "The warnings of {0} could not be read. Retry to see them.",
    "មិនអាចអានការព្រមានរបស់ {0} បានទេ។ សូមព្យាយាមម្តងទៀត។",
  ],
  lw_d_t: ["Record a Lease rule warning", "កត់ត្រាការព្រមានវិន័យកិច្ចសន្យា"],
  lw_d_vdate: ["Date of the breach", "ថ្ងៃនៃការរំលោភ"],
  lw_d_wdate: ["Date the warning was given", "ថ្ងៃផ្តល់ការព្រមាន"],
  // new
  lw_d_date_e: [
    "The breach comes first, then the warning; neither after today.",
    "ការរំលោភមកមុន បន្ទាប់មកការព្រមាន។ មិនក្រោយថ្ងៃនេះទេ។",
  ],
  lw_d_what: ["What happened", "អ្វីបានកើតឡើង"],
  lw_d_what_e: ["Write what happened.", "សូមសរសេរអ្វីដែលបានកើតឡើង។"],
  lw_d_clause: ["Lease article", "មាត្រាកិច្ចសន្យា"],
  lw_d_clause_e: [
    "Write the Lease article, for example 11.3.",
    "សូមសរសេរមាត្រាកិច្ចសន្យា ឧទាហរណ៍ 11.3។",
  ],
  lw_d_note: [
    "A warning adds no fee and does not end the Lease. Warning {0} of 3 for this Lease.",
    "ការព្រមានមិនបន្ថែមថ្លៃ ហើយមិនបញ្ចប់កិច្ចសន្យាទេ។ ការព្រមានទី {0} ក្នុង ៣ សម្រាប់កិច្ចសន្យានេះ។",
  ],
  // new
  lw_d_no_lease: [
    "No Lease has a recorded move-in, so there is nobody to warn.",
    "គ្មានកិច្ចសន្យាណាមានការចូលនៅដែលបានកត់ត្រាទេ ដូច្នេះគ្មាននរណាត្រូវព្រមាន។",
  ],
  // new
  lw_d_ctx_failed: [
    "The next warning number could not be read. Close and try again.",
    "មិនអាចអានលេខការព្រមានបន្ទាប់បានទេ។ សូមបិទ ហើយព្យាយាមម្តងទៀត។",
  ],
  lw_toast: [
    "Warning {0} recorded for {1}.",
    "បានកត់ត្រាការព្រមានទី {0} សម្រាប់ {1}។",
  ],
  // new
  lease_name: ["Lease · {0}", "កិច្ចសន្យា · {0}"],
  // new
  records: ["Earlier letter forms", "ទម្រង់លិខិតពីមុន"],
  // new
  records_note: [
    "In English until the next steps replace them",
    "ជាភាសាអង់គ្លេស រហូតដល់ជំហានបន្ទាប់ជំនួសវា",
  ],
} as const;

export type LettersTextKey = keyof typeof TEXT;

/** The text in the chosen language, with {0}, {1} filled in. */
export function ltr(
  language: Language,
  key: LettersTextKey,
  ...values: (string | number)[]
): string {
  return TEXT[key][language === "en" ? 0 : 1].replace(/\{(\d)\}/g, (_, n) =>
    String(values[Number(n)] ?? ""),
  );
}

/** The English words stored with a record, so History reads the same for everyone. */
export function storedText(key: LettersTextKey): string {
  return TEXT[key][0];
}

const MONTHS: Record<Language, string[]> = {
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
};

/** "2026-11-01" → "November 2026". */
export function monthText(language: Language, day: string): string {
  const month = MONTHS[language][Number(day.slice(5, 7)) - 1] ?? "";
  return `${month} ${day.slice(0, 4)}`;
}
