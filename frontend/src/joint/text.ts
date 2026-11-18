// DL-243: the words of the Joint Inspection. Khmer is new and needs the native check.

import type { Language } from "../signInText";

const TEXT = {
  ji: ["Joint Inspection", "ការត្រួតពិនិត្យរួម"],
  ji_many: ["Joint Inspections", "ការត្រួតពិនិត្យរួម"],
  ji_sub: [
    "Move-in and move-out checks of the room, signed by the tenant and staff",
    "ការត្រួតពិនិត្យបន្ទប់ពេលចូល និងចាកចេញ ដែលអ្នកជួល និងបុគ្គលិកចុះហត្ថលេខា",
  ],
  MOVE_IN: ["Move-in", "ពេលចូល"],
  MOVE_OUT: ["Move-out", "ពេលចាកចេញ"],
  DRAFT: ["Draft", "សេចក្តីព្រាង"],
  DONE: ["Done", "រួចរាល់"],
  REPLACED: ["Replaced", "បានជំនួស"],
  GOOD: ["Good", "ល្អ"],
  BROKEN: ["Broken", "ខូច"],
  MISSING: ["Missing", "បាត់"],
  all: ["All", "ទាំងអស់"],
  f_kind: ["Kind", "ប្រភេទ"],
  f_status: ["Status", "ស្ថានភាព"],
  c_no: ["Number", "លេខ"],
  c_kind: ["Kind", "ប្រភេទ"],
  c_unit: ["Parking", "ចំណត"],
  c_lease: ["Lease and tenant", "កិច្ចសន្យា និងអ្នកជួល"],
  c_date: ["Date", "កាលបរិច្ឆេទ"],
  c_problems: ["Problems", "បញ្ហា"],
  c_status: ["Status", "ស្ថានភាព"],
  none: ["No Joint Inspections yet.", "មិនទាន់មានការត្រួតពិនិត្យរួមនៅឡើយ។"],
  f_none: [
    "No Joint Inspection matches these filters.",
    "គ្មានការត្រួតពិនិត្យរួមត្រូវនឹងតម្រងទាំងនេះទេ។",
  ],
  loading: ["Loading…", "កំពុងផ្ទុក…"],
  failed: [
    "The Joint Inspections could not be read.",
    "មិនអាចអានការត្រួតពិនិត្យរួមបានទេ។",
  ],
  retry: ["Try again", "ព្យាយាមម្តងទៀត"],
  marked_of: ["{0} of {1} marked", "បានសម្គាល់ {0} ក្នុងចំណោម {1}"],
  new_n: ["{0} new", "{0} ថ្មី"],
  no_problems: ["None", "គ្មាន"],
  replaces: ["Replaces {0}", "ជំនួស {0}"],
  replaced_by: ["Replaced by {0}", "ត្រូវបានជំនួសដោយ {0}"],
  back: ["Back to Inspections", "ត្រឡប់ទៅការត្រួតពិនិត្យ"],
  // The form
  step1: ["Rooms and items", "បន្ទប់ និងរបស់របរ"],
  step2: ["Keys and meters", "កូនសោ និងនាឡិកា"],
  step3: ["Sign", "ចុះហត្ថលេខា"],
  steps: ["Steps", "ជំហាន"],
  next: ["Next", "បន្ទាប់"],
  prev: ["Back", "ថយក្រោយ"],
  all_good: ["All good", "ល្អទាំងអស់"],
  all_good_h: [
    "Mark every line not yet marked in {0} as Good",
    "សម្គាល់ជួរដែលមិនទាន់សម្គាល់ក្នុង {0} ថាល្អ",
  ],
  note: ["Note", "កំណត់ចំណាំ"],
  note_need: ["Write what is wrong", "សរសេរអ្វីដែលខុស"],
  photo_add: ["Add photo", "បន្ថែមរូបថត"],
  photo_remove: ["Remove photo", "ដករូបថតចេញ"],
  photo_n: ["Photo {0}", "រូបថត {0}"],
  photo_max: ["At most 5 photos", "រូបថតច្រើនបំផុត 5"],
  at_move_in: ["At move-in: {0}", "ពេលចូល៖ {0}"],
  at_move_in_none: ["Not checked at move-in", "មិនបានពិនិត្យពេលចូល"],
  new_since: ["New since move-in", "ថ្មីតាំងពីពេលចូល"],
  tenant_caused: ["Tenant caused", "អ្នកជួលបង្ក"],
  pet_caused: ["Caused by a pet", "បង្កដោយសត្វចិញ្ចឹម"],
  tenant_caused_h: [
    "Ticked lines become damage findings on the Move-out page. The Manager decides the charge there.",
    "ជួរដែលបានធីក ក្លាយជាការរកឃើញការខូចខាតនៅលើទំព័រចាកចេញ។ អ្នកគ្រប់គ្រងសម្រេចការគិតថ្លៃនៅទីនោះ។",
  ],
  qty: ["× {0}", "× {0}"],
  room_itself: ["The room itself", "បន្ទប់ផ្ទាល់"],
  keys: ["Keys", "កូនសោ"],
  door_keys: ["Door keys", "កូនសោទ្វារ"],
  key_cards: ["Key cards", "កាតសោ"],
  mailbox_keys: ["Mailbox keys", "កូនសោប្រអប់សំបុត្រ"],
  other_keys: ["Other", "ផ្សេងៗ"],
  other_keys_note: ["What other keys", "កូនសោផ្សេងទៀតអ្វីខ្លះ"],
  keys_given: ["Given at move-in: {0}", "បានផ្តល់ពេលចូល៖ {0}"],
  keys_short: [
    "Fewer keys than were given at move-in.",
    "កូនសោតិចជាងចំនួនដែលបានផ្តល់ពេលចូល។",
  ],
  meters: ["Meters", "នាឡិកា"],
  ELECTRICITY: ["Electricity meter", "នាឡិកាអគ្គិសនី"],
  WATER: ["Water meter", "នាឡិកាទឹក"],
  reading: ["Meter number", "លេខនាឡិកា"],
  reading_bad: [
    "Write the number on the meter, for example 1250.5",
    "សរសេរលេខលើនាឡិកា ឧទាហរណ៍ 1250.5",
  ],
  meter_photo: ["Photo of the meter", "រូបថតនាឡិកា"],
  utilities_differs: [
    "Utilities has {0} for this day. Check the meter again.",
    "ផ្នែកសេវាប្រើប្រាស់មាន {0} សម្រាប់ថ្ងៃនេះ។ សូមពិនិត្យនាឡិកាម្តងទៀត។",
  ],
  move_in_reading: ["At move-in: {0}", "ពេលចូល៖ {0}"],
  no_meters: [
    "This Parking has no meter in use.",
    "ចំណតនេះគ្មាននាឡិកាកំពុងប្រើទេ។",
  ],
  // Signing
  sign_check: [
    "Read this with the tenant before signing.",
    "សូមអានជាមួយអ្នកជួលមុនពេលចុះហត្ថលេខា។",
  ],
  sum_good: ["{0} Good", "ល្អ {0}"],
  sum_broken: ["{0} Broken", "ខូច {0}"],
  sum_missing: ["{0} Missing", "បាត់ {0}"],
  sum_caused: ["{0} the tenant caused", "អ្នកជួលបង្ក {0}"],
  not_ready: [
    "Before signing: mark every line, write a note for each problem, the keys and the meter numbers.",
    "មុនពេលចុះហត្ថលេខា៖ សម្គាល់គ្រប់ជួរ សរសេរកំណត់ចំណាំសម្រាប់បញ្ហានីមួយៗ កូនសោ និងលេខនាឡិកា។",
  ],
  tenant_sign: ["Tenant signs here", "អ្នកជួលចុះហត្ថលេខានៅទីនេះ"],
  staff_sign: ["Staff member signs here", "បុគ្គលិកចុះហត្ថលេខានៅទីនេះ"],
  tenant_first: ["The tenant signs first.", "អ្នកជួលចុះហត្ថលេខាមុន។"],
  sign_clear: ["Clear", "លុប"],
  sign_save: ["Save signature", "រក្សាហត្ថលេខា"],
  sign_again: ["Sign again", "ចុះហត្ថលេខាម្តងទៀត"],
  signed_at: ["Signed {0}", "បានចុះហត្ថលេខា {0}"],
  signed_by: ["Signed by {0}, {1}", "ចុះហត្ថលេខាដោយ {0}, {1}"],
  sign_empty: ["Sign in the box first.", "សូមចុះហត្ថលេខាក្នុងប្រអប់ជាមុន។"],
  sign_cleared: [
    "A change after signing clears both signatures. Sign again.",
    "ការកែប្រែក្រោយចុះហត្ថលេខា លុបហត្ថលេខាទាំងពីរ។ សូមចុះហត្ថលេខាម្តងទៀត។",
  ],
  finish: ["Finish", "បញ្ចប់"],
  finish_h: [
    "Finishing makes a Problem report for each new Broken or Missing line.",
    "ការបញ្ចប់ បង្កើតរបាយការណ៍បញ្ហាសម្រាប់ជួរខូច ឬបាត់ថ្មីនីមួយៗ។",
  ],
  finished: ["{0} is done.", "{0} រួចរាល់។"],
  finished_reports: [
    "Problem reports made: {0}.",
    "របាយការណ៍បញ្ហាដែលបានបង្កើត៖ {0}។",
  ],
  finished_findings: [
    "{0} damage finding(s) are on the Move-out page for the Manager.",
    "ការរកឃើញការខូចខាត {0} នៅលើទំព័រចាកចេញសម្រាប់អ្នកគ្រប់គ្រង។",
  ],
  saving: ["Saving…", "កំពុងរក្សាទុក…"],
  saved: ["Saved", "បានរក្សាទុក"],
  // Done view
  done_on: ["Done {0} by {1}", "រួចរាល់ {0} ដោយ {1}"],
  report: ["Problem report {0}", "របាយការណ៍បញ្ហា {0}"],
  finding: ["Damage finding", "ការរកឃើញការខូចខាត"],
  replace: ["Replace", "ជំនួស"],
  replace_t: ["Replace {0}", "ជំនួស {0}"],
  replace_h: [
    "A new inspection starts from what this one says. When it is signed, it takes this one's place.",
    "ការត្រួតពិនិត្យថ្មីចាប់ផ្តើមពីអ្វីដែលមួយនេះនិយាយ។ ពេលចុះហត្ថលេខា វាជំនួសមួយនេះ។",
  ],
  reason: ["Why is it replaced?", "ហេតុអ្វីបានជាជំនួស?"],
  reason_need: ["Say why it is replaced.", "សូមប្រាប់ហេតុផលនៃការជំនួស។"],
  start_replace: ["Start the replacement", "ចាប់ផ្តើមការជំនួស"],
  cancel: ["Cancel", "បោះបង់"],
  // DL-244: the Unit page card. Khmer is new and needs the native check.
  unit_all: ["See all {0} on Inspections", "មើលទាំង {0} នៅការត្រួតពិនិត្យ"],
  // DL-244: opens the PDF copy, the same file the Tenant bot sends.
  print: ["Print or save PDF", "បោះពុម្ព ឬរក្សាទុក PDF"],
  // Lease card and Move-out page
  lease_t: ["Joint Inspection", "ការត្រួតពិនិត្យរួម"],
  start_in: ["Start move-in inspection", "ចាប់ផ្តើមការត្រួតពិនិត្យពេលចូល"],
  start_out: ["Start move-out inspection", "ចាប់ផ្តើមការត្រួតពិនិត្យពេលចាកចេញ"],
  go_on: ["Go on with {0}", "បន្តជាមួយ {0}"],
  open: ["Open {0}", "បើក {0}"],
  in_missing: [
    "Move-in inspection not done",
    "មិនទាន់ធ្វើការត្រួតពិនិត្យពេលចូល",
  ],
  out_missing: [
    "Do the move-out Joint Inspection before the Final Settlement.",
    "សូមធ្វើការត្រួតពិនិត្យរួមពេលចាកចេញ មុនការទូទាត់ចុងក្រោយ។",
  ],
  out_no_move_in: [
    "There was no move-in inspection, so every problem counts as new.",
    "គ្មានការត្រួតពិនិត្យពេលចូល ដូច្នេះបញ្ហាទាំងអស់រាប់ជាថ្មី។",
  ],
  not_allowed: [
    "Your role cannot do Joint Inspections.",
    "តួនាទីរបស់អ្នកមិនអាចធ្វើការត្រួតពិនិត្យរួមបានទេ។",
  ],
  // Errors
  e_stale: [
    "Someone changed this inspection meanwhile. It was read again.",
    "មានគេកែប្រែការត្រួតពិនិត្យនេះក្នុងពេលនោះ។ វាត្រូវបានអានម្តងទៀត។",
  ],
  e_forbidden: [
    "Your role cannot do this.",
    "តួនាទីរបស់អ្នកមិនអាចធ្វើការនេះបានទេ។",
  ],
  e_picture: [
    "Use a JPG, PNG or WEBP picture of at most 10 MB.",
    "សូមប្រើរូបភាព JPG, PNG ឬ WEBP មិនលើស 10 MB។",
  ],
  e_files: [
    "The app cannot keep photos yet. Ask the Owner to set up the photos folder.",
    "កម្មវិធីមិនទាន់អាចរក្សារូបថតបានទេ។ សូមស្នើម្ចាស់ឱ្យរៀបចំថតរូបថត។",
  ],
  e_other: [
    "This was not saved. Check the connection and try again.",
    "មិនបានរក្សាទុកទេ។ សូមពិនិត្យការតភ្ជាប់ ហើយព្យាយាមម្តងទៀត។",
  ],
  missing_one: [
    "This Joint Inspection was not found.",
    "រកមិនឃើញការត្រួតពិនិត្យរួមនេះទេ។",
  ],
} as const;

export type JointTextKey = keyof typeof TEXT;

export function jt(
  language: Language,
  key: JointTextKey,
  ...values: (string | number)[]
): string {
  let words: string = TEXT[key][language === "en" ? 0 : 1];
  values.forEach((value, index) => {
    words = words.replace(`{${String(index)}}`, String(value));
  });
  return words;
}

/** "2026-11-16" as "16/11/2026", as the app writes days. */
export function dayText(day: string): string {
  return day.slice(0, 10).split("-").reverse().join("/");
}
