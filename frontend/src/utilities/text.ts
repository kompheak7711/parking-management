// V1-058 R4: the words of the Utilities screens in English and Khmer, from the owner's
// mock-up (i18n.js, app.js). Khmer needs the native check before the app is used. Lines
// marked "new" are not in the mock-up.

import type { Language } from "../signInText";

const TEXT = {
  sub: ["Meter readings and meters", "អំណាន និងនាឡិកាស្ទង់"],
  tab_read: ["Meter readings", "អំណាននាឡិកាស្ទង់"],
  tab_meters: ["Meters", "នាឡិកាស្ទង់"],
  // new
  loading: ["Loading the meters…", "កំពុងផ្ទុកនាឡិកាស្ទង់…"],
  // new
  failed: [
    "The meters could not be read just now. Check the connection and try again.",
    "មិនអាចអាននាឡិកាស្ទង់បានទេឥឡូវនេះ។ សូមពិនិត្យការតភ្ជាប់ ហើយព្យាយាមម្តងទៀត។",
  ],
  retry: ["Retry", "ព្យាយាមម្តងទៀត"],
  // new
  no_property: [
    "Choose the Property in Settings first.",
    "សូមជ្រើសរើសអគារក្នុងការកំណត់ជាមុនសិន។",
  ],
  // new
  failed_units: [
    "The meters of {0} could not be read. Try again.",
    "មិនអាចអាននាឡិកាស្ទង់របស់ {0} បានទេ។ សូមព្យាយាមម្តងទៀត។",
  ],
  unit: ["Unit", "បន្ទប់"],
  all_units: ["All Units", "គ្រប់បន្ទប់"],
  unit_bad: [
    'No Unit "{0}". Type a Unit number such as {1}, or clear the box to see all Units.',
    'គ្មានបន្ទប់ "{0}"។ វាយលេខបន្ទប់ដូចជា {1} ឬលុបប្រអប់ ដើម្បីមើលគ្រប់បន្ទប់។',
  ],
  period: ["Month", "ខែ"],
  p_all: ["All", "ទាំងអស់"],
  p_month: ["This month", "ខែនេះ"],
  p_six: ["6 months", "6 ខែ"],
  p_pick: ["Pick a month", "ជ្រើសខែ"],
  meter_kind: ["Meter", "នាឡិកាស្ទង់"],
  ELECTRICITY: ["Electricity", "អគ្គិសនី"],
  WATER: ["Water", "ទឹក"],
  floor_all: ["All floors", "គ្រប់ជាន់"],
  floor_n: ["Floor {0}", "ជាន់ទី {0}"],
  only_missing: ["Only not read", "តែមិនទាន់អាន"],
  progress: ["{0} of {1} meters read", "បានអាន {0} ក្នុងចំណោម {1}"],
  // new (the mock-up names the date in the words)
  next_inv: [
    "Read every meter, including empty rooms. Invoices are made on {0} from these readings.",
    "អានគ្រប់នាឡិកាស្ទង់ រួមទាំងបន្ទប់ទំនេរ។ វិក្កយបត្រនឹងចេញថ្ងៃ {0} ពីអំណានទាំងនេះ។",
  ],
  all_done: [
    "All meters are read. Invoices will be made on the 25th.",
    "បានអានគ្រប់នាឡិកាស្ទង់។ វិក្កយបត្រនឹងចេញនៅថ្ងៃទី 25។",
  ],
  // new
  none_left: [
    "Every meter on this list is read.",
    "នាឡិកាស្ទង់ទាំងអស់ក្នុងបញ្ជីនេះបានអានរួច។",
  ],
  // new
  no_meters: [
    "No meters yet. Add them on the Meters tab.",
    "មិនទាន់មាននាឡិកាស្ទង់។ សូមបន្ថែមនៅផ្ទាំងនាឡិកាស្ទង់។",
  ],
  // new
  before_day: [
    "Reading day is {0}. The list to type the readings opens that day.",
    "ថ្ងៃអានគឺ {0}។ បញ្ជីសម្រាប់វាយអំណានបើកនៅថ្ងៃនោះ។",
  ],
  col_unit_meter: ["Unit · Meter", "បន្ទប់ · នាឡិកាស្ទង់"],
  col_last: ["Last reading", "អំណានចុងក្រោយ"],
  col_new: ["New reading", "អំណានថ្មី"],
  col_used: ["Used", "បានប្រើ"],
  col_result: ["Result", "លទ្ធផល"],
  save: ["Save", "រក្សាទុក"],
  saved: ["Saved", "បានរក្សាទុក"],
  // new
  saved_on: ["Saved {0}", "បានរក្សាទុក {0}"],
  not_read: ["Not read yet", "មិនទាន់អាន"],
  typed: ["Not saved yet", "មិនទាន់រក្សាទុក"],
  // new
  no_last: ["No reading yet", "មិនទាន់មានអំណាន"],
  vacant_note: ["Vacant. The Property pays.", "ទំនេរ។ អគារជាអ្នកបង់។"],
  reserved_note: ["Reserved. No Lease yet.", "បានកក់។ មិនទាន់មានកិច្ចសន្យា។"],
  // new
  other_note: ["No Lease now.", "គ្មានកិច្ចសន្យាឥឡូវនេះ។"],
  err_num: ["Enter whole numbers only.", "សូមបញ្ចូលតែលេខគត់។"],
  // changed: V1 has no "report broken" yet, so a Manager replaces the meter.
  err_lower: [
    "Lower than the last reading ({0}). Check the meter. If it is broken, a Manager replaces it on the Meters tab.",
    "ទាបជាងអំណានចុងក្រោយ ({0})។ សូមពិនិត្យនាឡិកាស្ទង់។ បើវាខូច អ្នកគ្រប់គ្រងប្តូរវានៅផ្ទាំងនាឡិកាស្ទង់។",
  ],
  warn_high: [
    "{0} is much more than usual (about {1}). Check the meter, then save again.",
    "{0} ច្រើនជាងធម្មតា (ប្រហែល {1})។ សូមពិនិត្យ រួចរក្សាទុកម្តងទៀត។",
  ],
  save_anyway: ["Save anyway", "រក្សាទុកដដែល"],
  broken: ["Broken", "ខូច"],
  rd_broken: [
    "A broken meter cannot be read. Replace it first.",
    "នាឡិកាស្ទង់ខូចមិនអាចអានបាន។ សូមប្តូរវាជាមុន។",
  ],
  replace: ["Replace meter", "ប្តូរនាឡិកាស្ទង់"],
  // new
  done_one: ["{0}: saved.", "{0}៖ បានរក្សាទុក។"],
  // new
  conflict: [
    "This meter changed while you were typing, so the list was read again. Check the reading and save again.",
    "នាឡិកាស្ទង់នេះបានផ្លាស់ប្តូរ ពេលអ្នកកំពុងវាយ ដូច្នេះបញ្ជីត្រូវបានអានម្តងទៀត។ សូមពិនិត្យអំណាន ហើយរក្សាទុកម្តងទៀត។",
  ],
  // new
  save_failed: [
    "The reading was not saved. Check the connection and try again.",
    "អំណានមិនត្រូវបានរក្សាទុកទេ។ សូមពិនិត្យការតភ្ជាប់ ហើយព្យាយាមម្តងទៀត។",
  ],
  // new
  refused: [
    "The reading was refused. It may be lower than a reading already saved, or dated before the meter was put in.",
    "អំណានត្រូវបានបដិសេធ។ វាអាចទាបជាងអំណានដែលបានរក្សាទុករួច ឬមុនថ្ងៃដាក់នាឡិកាស្ទង់។",
  ],
  // new
  not_allowed_save: [
    "You may see the readings but not save them.",
    "អ្នកអាចមើលអំណាន ប៉ុន្តែមិនអាចរក្សាទុកបានទេ។",
  ],
  rd_day: ["Reading day", "ថ្ងៃអាន"],
  rd_reading: ["Reading", "អំណាន"],
  rd_note: ["Note", "កំណត់ចំណាំ"],
  rd_none_m: ["No readings in {0}.", "គ្មានអំណានក្នុងខែ{0}។"],
  // new
  rd_none: ["No readings yet.", "មិនទាន់មានអំណាន។"],
  rd_grid_note: [
    "Each box shows the reading and, under it, the use since the reading before, in {0}.",
    "ប្រអប់នីមួយៗបង្ហាញអំណាន ហើយខាងក្រោមជាការប្រើតាំងពីអំណានមុន គិតជា {0}។",
  ],
  rd_n_new: [
    "New meter put in. First reading.",
    "ដាក់នាឡិកាស្ទង់ថ្មី។ អំណានដំបូង។",
  ],
  // new
  rd_corrected: ["Corrected from {0}.", "បានកែពី {0}។"],
  // new
  soon_meters: [
    "The new Meters list comes in the next step. Until then, the earlier forms below show and change the meters.",
    "បញ្ជីនាឡិកាស្ទង់ថ្មីនឹងមកក្នុងជំហានបន្ទាប់។ រហូតដល់ពេលនោះ ទម្រង់មុនខាងក្រោមបង្ហាញ និងប្តូរនាឡិកាស្ទង់។",
  ],
  // new
  records: ["Earlier forms", "ទម្រង់មុន"],
  // new
  records_note: [
    "Meters, rates, corrections and move-in or move-out readings, in English, until the next steps move them into this screen.",
    "នាឡិកាស្ទង់ អត្រា ការកែ និងអំណានពេលចូល ឬចេញ ជាភាសាអង់គ្លេស រហូតដល់ជំហានបន្ទាប់ផ្លាស់វាមកអេក្រង់នេះ។",
  ],
} as const satisfies Record<string, readonly [string, string]>;

export type UtilitiesTextKey = keyof typeof TEXT;

export function utt(
  language: Language,
  key: UtilitiesTextKey,
  ...values: (string | number)[]
): string {
  const text = TEXT[key][language === "en" ? 0 : 1];
  return text.replace(/\{(\d+)\}/g, (match, index: string) => {
    const value = values[Number(index)];
    return value === undefined ? match : String(value);
  });
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
};

/** "2026-11" or "2026-11-24" → "November 2026". */
export function monthText(language: Language, day: string): string {
  const month = MONTHS[language][Number(day.slice(5, 7)) - 1] ?? "";
  return `${month} ${day.slice(0, 4)}`;
}
