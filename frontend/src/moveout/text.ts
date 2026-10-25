// V1-058 R3 Move-out: the words of the Move-out list and page in English and Khmer, from the
// owner's mock-up (i18n3.js, app3.js). Khmer needs the native check before the app is used.
// Lines marked "new" are not in the mock-up.

import type { Language } from "../signInText";

const TEXT = {
  title: ["Move-out", "ការចាកចេញ"],
  sub: [
    "Leases ending, Units handed back and Final Settlements",
    "កិច្ចសន្យាជិតបញ្ចប់ បន្ទប់បានប្រគល់ និងការទូទាត់ចុងក្រោយ",
  ],
  moveout_of: ["Move-out · {0}", "ការចាកចេញ · {0}"],
  c_soon: ["Leaving soon", "ជិតចាកចេញ"],
  c_soon_s: [
    "Lease ends within 60 days, or terminated and still in",
    "កិច្ចសន្យាបញ្ចប់ក្នុង 60 ថ្ងៃ ឬបានបញ្ចប់ហើយនៅមិនទាន់ចេញ",
  ],
  c_out: ["Handed back", "បានប្រគល់បន្ទប់"],
  c_out_s: [
    "Readings, inspection and charges to finish",
    "អំណាន ការត្រួតពិនិត្យ និងថ្លៃត្រូវបញ្ចប់",
  ],
  showing: ["Showing: {0}", "កំពុងបង្ហាញ៖ {0}"],
  show_all: ["Show all", "បង្ហាញទាំងអស់"],
  n1: ["1 move-out", "ការចាកចេញ 1"],
  n: ["{0} move-outs", "ការចាកចេញ {0}"],
  none: ["Nothing here.", "គ្មានអ្វីនៅទីនេះទេ។"],
  col_unit: ["Unit", "បន្ទប់"],
  col_cust: ["Customer", "អតិថិជន"],
  col_end: ["Lease ends", "កិច្ចសន្យាបញ្ចប់"],
  col_hb: ["Handed back", "បានប្រគល់"],
  col_step: ["Step", "ជំហាន"],
  col_dep: ["Deposits held", "ប្រាក់កក់កាន់កាប់"],
  was: ["End Date was {0}", "ថ្ងៃបញ្ចប់គឺ {0}"],
  next_hb: ["Record the hand-back", "កត់ត្រាការប្រគល់បន្ទប់"],
  next_final: ["Record final readings", "កត់ត្រាអំណានចុងក្រោយ"],
  next_settle: ["Prepare the Final Settlement", "រៀបចំការទូទាត់ចុងក្រោយ"],
  in_days: ["in {0} days", "ក្នុង {0} ថ្ងៃ"],
  today: ["today", "ថ្ងៃនេះ"],
  ago: ["{0} days ago", "{0} ថ្ងៃមុន"],
  // new
  ago1: ["1 day ago", "1 ថ្ងៃមុន"],
  // new
  in1: ["in 1 day", "ក្នុង 1 ថ្ងៃ"],
  rule_note: [
    "Order of work: hand-back, final readings, inspection and charges, Final Settlement (BR-MOVEOUT-012). One Final Settlement per Lease; corrections after closure are separate records.",
    "លំដាប់ការងារ៖ ប្រគល់បន្ទប់ អំណានចុងក្រោយ ត្រួតពិនិត្យ និងថ្លៃ ការទូទាត់ចុងក្រោយ។ ការទូទាត់ចុងក្រោយតែមួយក្នុងមួយកិច្ចសន្យា; ការកែបន្ទាប់ពីបិទ ជាកំណត់ត្រាដាច់ដោយឡែក។",
  ],
  s_soon: ["Leaving soon", "ជិតចាកចេញ"],
  s_in: ["Still in the Unit", "នៅក្នុងបន្ទប់"],
  s_out: ["Handed back", "បានប្រគល់"],
  // new: terminated before anybody moved in.
  s_skip: ["Never moved in", "មិនដែលចូលស្នាក់នៅ"],
  steps_t: ["Move-out steps", "ជំហានចាកចេញ"],
  done: ["Done", "រួចរាល់"],
  todo: ["To do", "ត្រូវធ្វើ"],
  skip: ["Not needed", "មិនចាំបាច់"],
  now: ["Now", "ឥឡូវ"],
  st1_t: ["Lease ends", "កិច្ចសន្យាបញ្ចប់"],
  st1_normal: [
    "Lease End Date {0}. Normal end: the Security Deposit pays what is owed, the rest is refunded (DL-032).",
    "ថ្ងៃបញ្ចប់កិច្ចសន្យា {0}។ បញ្ចប់ធម្មតា៖ ប្រាក់កក់សុវត្ថិភាពបង់អ្វីដែលជំពាក់ នៅសល់សងវិញ។",
  ],
  // new: the termination's ground is in its reason.
  st1_term: ["Terminated as of {0}.", "បានបញ្ចប់ត្រឹម {0}។"],
  st1_reason: ["Reason: {0}", "មូលហេតុ៖ {0}"],
  st2_t: ["Hand back the Unit", "ប្រគល់បន្ទប់"],
  // new: the record keeps the keys in its evidence and the Unit status it set.
  st2_done: [
    "Handed back on {0}. Unit set to {1}.",
    "បានប្រគល់នៅ {0}។ បន្ទប់ត្រូវបានកំណត់ជា {1}។",
  ],
  st2_todo: [
    "The Customer is still in the Unit. Record the real hand-back date when the keys come back.",
    "អតិថិជននៅក្នុងបន្ទប់។ កត់ត្រាថ្ងៃប្រគល់ពិតប្រាកដ ពេលទទួលកូនសោ។",
  ],
  // new
  st2_wait: [
    "The Lease ends on {0}. Record the hand-back on or after that day; to leave earlier, end the Lease with Terminate first.",
    "កិច្ចសន្យាបញ្ចប់នៅ {0}។ កត់ត្រាការប្រគល់នៅ ឬក្រោយថ្ងៃនោះ; ដើម្បីចាកចេញមុន សូមបញ្ចប់កិច្ចសន្យាដោយ បញ្ចប់ ជាមុនសិន។",
  ],
  st2_skip: [
    "Never moved in: nothing to hand back.",
    "មិនដែលចូលស្នាក់នៅ៖ គ្មានអ្វីប្រគល់។",
  ],
  // new: a normal end also records the end of the Lease, which needs leases.terminate.
  st2_manager: [
    "A Manager records this hand-back, because it also ends the Lease at its End Date.",
    "អ្នកគ្រប់គ្រងកត់ត្រាការប្រគល់នេះ ព្រោះវាបញ្ចប់កិច្ចសន្យានៅថ្ងៃបញ្ចប់ផងដែរ។",
  ],
  // new
  st2_no_term: [
    "The termination of this Lease could not be read, so the hand-back cannot be recorded here. Open the Lease and try again later.",
    "មិនអាចអានការបញ្ចប់កិច្ចសន្យានេះបានទេ ដូច្នេះមិនអាចកត់ត្រាការប្រគល់នៅទីនេះបានទេ។ បើកកិច្ចសន្យា ហើយព្យាយាមម្តងទៀតពេលក្រោយ។",
  ],
  // new
  st2_not_allowed: [
    "Your account cannot record a hand-back.",
    "គណនីរបស់អ្នកមិនអាចកត់ត្រាការប្រគល់បានទេ។",
  ],
  // new
  renewed_note: [
    "A signed renewal continues this Lease, so the tenants stay: there is no move-out.",
    "ការបន្តដែលបានចុះហត្ថលេខា បន្តកិច្ចសន្យានេះ ដូច្នេះអ្នកជួលនៅដដែល៖ គ្មានការចាកចេញទេ។",
  ],
  // new
  not_yet_note: [
    "This Lease is not ending within 60 days, so it has no move-out yet.",
    "កិច្ចសន្យានេះមិនបញ្ចប់ក្នុង 60 ថ្ងៃទេ ដូច្នេះមិនទាន់មានការចាកចេញ។",
  ],
  st2_btn: ["Record hand-back", "កត់ត្រាការប្រគល់"],
  st2_date: ["Hand-back date", "ថ្ងៃប្រគល់បន្ទប់"],
  st2_date_help: [
    "The real date the keys came back. Not later than today.",
    "ថ្ងៃពិតដែលទទួលកូនសោ។ មិនក្រោយថ្ងៃនេះ។",
  ],
  st2_bad: ["Enter a date from {0} to today.", "បញ្ចូលថ្ងៃពី {0} ដល់ថ្ងៃនេះ។"],
  st2_keys: ["All keys returned", "បានប្រគល់កូនសោទាំងអស់"],
  st2_who: ["Who moved out", "អ្នកចាកចេញ"],
  // new
  st2_unit: ["The Unit after the hand-back", "បន្ទប់បន្ទាប់ពីប្រគល់"],
  st2_note: ["Note (optional)", "កំណត់ចំណាំ (ស្រេចចិត្ត)"],
  st2_c: [
    "The Unit leaves Occupied. Rent for the month of hand-back follows the rule shown.",
    "បន្ទប់លែងមានអ្នកស្នាក់នៅ។ ថ្លៃឈ្នួលខែប្រគល់ តាមច្បាប់បង្ហាញ។",
  ],
  // new
  st2_ends_too: [
    "This also ends the Lease on its End Date, {0}, as signed. The Security Deposit pays what is owed and the rest is refunded.",
    "នេះក៏បញ្ចប់កិច្ចសន្យានៅថ្ងៃបញ្ចប់ {0} តាមការចុះហត្ថលេខាដែរ។ ប្រាក់កក់សុវត្ថិភាពបង់អ្វីដែលជំពាក់ នៅសល់សងវិញ។",
  ],
  st2_ok: ["Record hand-back", "កត់ត្រាការប្រគល់"],
  st2_toast: [
    "Hand-back recorded. {0} is now {1}.",
    "បានកត់ត្រាការប្រគល់។ {0} ឥឡូវ {1}។",
  ],
  rent_after5: [
    "Handed back on {0}, on or after the 5th: Rent for {1} is due in full.",
    "ប្រគល់នៅ {0} ពីថ្ងៃទី 5 ឡើង៖ ថ្លៃឈ្នួល {1} ត្រូវបង់ពេញ។",
  ],
  // new: the three cases of the owner's rule (03/10/2026) in one line.
  rent_before5: [
    "Handed back on {0}, before the 5th: an unpaid Rent Invoice for {1} is voided by a Manager with a reason; a paid one is kept; a partly paid one keeps the paid part.",
    "ប្រគល់នៅ {0} មុនថ្ងៃទី 5៖ វិក្កយបត្រថ្លៃឈ្នួល {1} មិនទាន់បង់ ត្រូវលុបចោលដោយអ្នកគ្រប់គ្រងដោយមានមូលហេតុ; បានបង់ត្រូវរក្សាទុក; បានបង់ខ្លះរក្សាផ្នែកបានបង់។",
  ],
  cond_CLEANING: ["Cleaning", "កំពុងសម្អាត"],
  cond_UNDER_MAINTENANCE: ["Under maintenance", "កំពុងជួសជុល"],
  cond_OUT_OF_SERVICE: ["Out of service", "ឈប់ប្រើ"],
  st3_t: ["Final meter readings", "អំណាននាឡិកាស្ទង់ចុងក្រោយ"],
  st3_todo: [
    "Read both meters on the hand-back day. The app issues the final Utility Invoice at once (off-cycle).",
    "អាននាឡិកាស្ទង់ទាំងពីរនៅថ្ងៃប្រគល់។ កម្មវិធីចេញវិក្កយបត្រទឹកភ្លើងចុងក្រោយភ្លាម។",
  ],
  st3_wait: ["After the hand-back.", "បន្ទាប់ពីប្រគល់បន្ទប់។"],
  st4_t: ["Inspection and charges", "ការត្រួតពិនិត្យ និងថ្លៃ"],
  st4_todo: [
    "Inspect the Unit after the hand-back. Each damage charge needs an amount, a reason and evidence; it is recorded once per finding.",
    "ត្រួតពិនិត្យបន្ទប់បន្ទាប់ពីប្រគល់។ ថ្លៃខូចខាតនីមួយៗត្រូវមានចំនួន មូលហេតុ និងភស្តុតាង; កត់ត្រាម្តងក្នុងមួយការរកឃើញ។",
  ],
  st5_t: ["Final Settlement", "ការទូទាត់ចុងក្រោយ"],
  st5_wait: ["After the charges are recorded.", "បន្ទាប់ពីកត់ត្រាថ្លៃ។"],
  st5_todo: [
    "Prepare the statement. Staff prepare the draft; a Manager confirms and closes it.",
    "រៀបចំរបាយការណ៍។ បុគ្គលិករៀបចំសេចក្តីព្រាង; អ្នកគ្រប់គ្រងបញ្ជាក់ និងបិទ។",
  ],
  st6_t: ["After closure", "បន្ទាប់ពីបិទ"],
  st6_note: [
    "A closed Final Settlement is never reopened. A later charge or refund is a linked correction with a reason, confirmed by a Manager.",
    "ការទូទាត់ចុងក្រោយបានបិទ មិនបើកឡើងវិញទេ។ ថ្លៃ ឬការសងវិញក្រោយ ជាការកែភ្ជាប់ដោយមានមូលហេតុ បញ្ជាក់ដោយអ្នកគ្រប់គ្រង។",
  ],
  // new: steps 3 to 6 get their buttons in the next updates.
  later: [
    "The button for this step comes in the next update.",
    "ប៊ូតុងសម្រាប់ជំហាននេះ នឹងមកក្នុងការធ្វើបច្ចុប្បន្នភាពបន្ទាប់។",
  ],
  deps_t: ["Deposits", "ប្រាក់កក់"],
  dep_SECURITY: ["Security Deposit", "ប្រាក់កក់សុវត្ថិភាព"],
  dep_PET: ["Pet Deposit", "ប្រាក់កក់សត្វចិញ្ចឹម"],
  dep_held: ["{0} held", "កាន់កាប់ {0}"],
  // new
  dep_received: ["received {0}", "បានទទួល {0}"],
  dep_none: [
    "No Pet Deposit on this Lease.",
    "គ្មានប្រាក់កក់សត្វចិញ្ចឹមលើកិច្ចសន្យានេះ។",
  ],
  // new
  dep_hidden: [
    "Your account cannot see Deposits.",
    "គណនីរបស់អ្នកមិនអាចមើលប្រាក់កក់បានទេ។",
  ],
  // new
  dep_failed: [
    "The Deposits could not be read just now.",
    "មិនអាចអានប្រាក់កក់បានទេឥឡូវនេះ។",
  ],
  history_t: ["History", "ប្រវត្តិ"],
  h_none: ["Nothing recorded yet.", "មិនទាន់មានកំណត់ត្រា។"],
  mh_hb: [
    "Handed back on {0}; Unit set to {1}.",
    "បានប្រគល់នៅ {0}; បន្ទប់ត្រូវបានកំណត់ជា {1}។",
  ],
  // new
  mh_hb_fixed: [
    "Hand-back corrected: {0}; Unit {1}.",
    "ការប្រគល់ត្រូវបានកែ៖ {0}; បន្ទប់ {1}។",
  ],
  open_lease: ["Open Lease", "បើកកិច្ចសន្យា"],
  open_unit: ["Open Unit", "បើកបន្ទប់"],
  back: ["Move-out", "ការចាកចេញ"],
  loading: ["Reading the move-outs…", "កំពុងអានការចាកចេញ…"],
  failed: [
    "The move-outs could not be read just now. Check the connection and try again.",
    "មិនអាចអានការចាកចេញបានទេឥឡូវនេះ។ សូមពិនិត្យការតភ្ជាប់ ហើយព្យាយាមម្តងទៀត។",
  ],
  retry: ["Retry", "ព្យាយាមម្តងទៀត"],
  missing: [
    "This Lease has no move-out to show, or your account cannot see it.",
    "កិច្ចសន្យានេះគ្មានការចាកចេញត្រូវបង្ហាញ ឬគណនីរបស់អ្នកមិនអាចមើលវាបានទេ។",
  ],
  no_property: [
    "This screen needs the Property. Open Settings and load it first.",
    "អេក្រង់នេះត្រូវការអគារ។ បើកការកំណត់ ហើយផ្ទុកវាជាមុនសិន។",
  ],
  close: ["Close", "បិទ"],
  saving: ["Saving…", "កំពុងរក្សាទុក…"],
  try_again: ["Try again", "ព្យាយាមម្តងទៀត"],
  unknown: [
    "No answer came back. The hand-back may or may not be saved: press Try again to send the very same request.",
    "គ្មានចម្លើយត្រឡប់មកវិញ។ ការប្រគល់អាចរក្សាទុក ឬមិនទាន់: ចុច ព្យាយាមម្តងទៀត ដើម្បីផ្ញើសំណើដដែល។",
  ],
  refused: [
    "The hand-back was not saved. Check the date and try again, or read the Lease again.",
    "ការប្រគល់មិនត្រូវបានរក្សាទុកទេ។ ពិនិត្យថ្ងៃ ហើយព្យាយាមម្តងទៀត ឬអានកិច្ចសន្យាម្តងទៀត។",
  ],
  conflict: [
    "The Lease or the Unit changed meanwhile. The page was read again; check it and record again.",
    "កិច្ចសន្យា ឬបន្ទប់បានផ្លាស់ប្តូរ។ ទំព័រត្រូវបានអានម្តងទៀត; សូមពិនិត្យ ហើយកត់ត្រាម្តងទៀត។",
  ],
  required: ["required", "ត្រូវការ"],
  // new
  records: ["Earlier Deposit forms", "ទម្រង់ប្រាក់កក់ពីមុន"],
  // new
  records_note: [
    "In English, until the Final Settlement steps replace them.",
    "ជាភាសាអង់គ្លេស រហូតដល់ជំហានការទូទាត់ចុងក្រោយជំនួសវា។",
  ],
} as const satisfies Record<string, readonly [string, string]>;

export type MoveOutTextKey = keyof typeof TEXT;

/** The words for `key`, with {0}, {1} … filled in. */
export function mt(
  language: Language,
  key: MoveOutTextKey,
  ...values: (string | number)[]
): string {
  const text = TEXT[key][language === "km" ? 1 : 0];
  return text.replace(/\{(\d+)\}/g, (match, index: string) => {
    const value = values[Number(index)];
    return value === undefined ? match : String(value);
  });
}

export function conditionText(language: Language, condition: string): string {
  const key = `cond_${condition}`;
  return key in TEXT
    ? mt(language, key as MoveOutTextKey)
    : condition.toLowerCase().replace(/_/g, " ");
}
