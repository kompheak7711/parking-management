// V1-058 R3: the words of the Reservations screens in English and Khmer, from the owner's
// mock-up (i18n). Khmer needs the native check before the app is used. Lines marked "new"
// are not in the mock-up. The words "Reservation Deposit" and "converted" are never used
// (docs/001 §89): the money is the Security Deposit from the first day.

import type { Language } from "../signInText";

const TEXT = {
  sub: [
    "{0} Reservations · a Unit held for a Customer until the Lease is signed",
    "ការកក់ {0} · បន្ទប់ដែលរក្សាទុកសម្រាប់អតិថិជន រហូតដល់ចុះហត្ថលេខាកិច្ចសន្យា",
  ],
  make: ["Make Reservation", "ធ្វើការកក់"],
  loading: ["Loading the Reservations…", "កំពុងផ្ទុកការកក់…"],
  // new
  failed: [
    "The Reservations could not be read. Retry when the service is available.",
    "មិនអាចអានការកក់បានទេ។ សូមព្យាយាមម្តងទៀតពេលសេវាអាចប្រើបាន។",
  ],
  retry: ["Retry", "ព្យាយាមម្តងទៀត"],
  // new
  no_property: [
    "The Property is not known yet, so the Reservations cannot be shown.",
    "មិនទាន់ស្គាល់អគារ ដូច្នេះមិនអាចបង្ហាញការកក់បានទេ។",
  ],
  c_active: ["Active", "កំពុងដំណើរការ"],
  c_active_s: ["Holding a Unit now", "កំពុងរក្សាបន្ទប់ឥឡូវនេះ"],
  c_ending: ["Ending within 7 days", "ផុតកំណត់ក្នុង 7 ថ្ងៃ"],
  c_ending_s: [
    "Sign the Lease or extend soon",
    "ចុះហត្ថលេខាកិច្ចសន្យា ឬពន្យារឆាប់ៗ",
  ],
  c_completed: ["Completed", "បានបញ្ចប់"],
  c_completed_s: ["The Lease was signed", "កិច្ចសន្យាត្រូវបានចុះហត្ថលេខា"],
  c_cancelled: ["Cancelled", "បានលុបចោល"],
  c_cancelled_s: ["Cancelled or expired", "បានលុបចោល ឬផុតកំណត់"],
  showing: ["Showing: {0}.", "កំពុងបង្ហាញ៖ {0}។"],
  show_all: ["Show all", "បង្ហាញទាំងអស់"],
  unit: ["Unit", "បន្ទប់"],
  customer: ["Customer", "អតិថិជន"],
  reserved_on: ["Reserved on", "កក់នៅ"],
  expires: ["Expires", "ផុតកំណត់"],
  deposit: ["Deposit received", "ប្រាក់កក់បានទទួល"],
  status: ["Status", "ស្ថានភាព"],
  result: ["Result", "លទ្ធផល"],
  extended_once: ["extended once", "បានពន្យារម្តង"],
  days_left: ["{0} days left", "នៅសល់ {0} ថ្ងៃ"],
  day_left: ["1 day left", "នៅសល់ 1 ថ្ងៃ"],
  last_day: ["last day today", "ថ្ងៃចុងក្រោយគឺថ្ងៃនេះ"],
  of: ["of {0}", "នៃ {0}"],
  s_ACTIVE: ["Active", "កំពុងដំណើរការ"],
  s_COMPLETED: ["Completed", "បានបញ្ចប់"],
  s_CANCELLED: ["Cancelled", "បានលុបចោល"],
  r_lease: ["Lease signed", "បានចុះហត្ថលេខាកិច្ចសន្យា"],
  r_expired: ["Expired", "ផុតកំណត់"],
  r_customer: ["Customer no longer wants the Unit", "អតិថិជនលែងចង់បានបន្ទប់"],
  r_property: [
    "Property could not provide the Unit",
    "អគារមិនអាចផ្តល់បន្ទប់បាន",
  ],
  none: ["No Reservations match.", "គ្មានការកក់ត្រូវនឹងការជ្រើសរើសទេ។"],
  n1: ["1 Reservation", "ការកក់ 1"],
  n: ["{0} Reservations", "ការកក់ {0}"],
  back: ["Back", "ត្រឡប់ក្រោយ"],
  // new
  missing: [
    "This Reservation was not found, or your account cannot open it.",
    "រកមិនឃើញការកក់នេះ ឬគណនីរបស់អ្នកមិនអាចបើកវាបានទេ។",
  ],
  title: ["Reservation · {0}", "ការកក់ · {0}"],
  head_sub: [
    "{0} · reserved on {1} · expires {2}",
    "{0} · កក់នៅ {1} · ផុតកំណត់ {2}",
  ],
  new_lease: ["New Lease from Reservation", "កិច្ចសន្យាថ្មីពីការកក់"],
  open_lease: ["Open the Lease", "បើកកិច្ចសន្យា"],
  extend: ["Extend", "ពន្យារ"],
  cancel_res: ["Cancel Reservation", "លុបចោលការកក់"],
  manager: ["Manager", "អ្នកគ្រប់គ្រង"],
  ending_warn: [
    "{0}. Sign the Lease or extend the Reservation before it expires.",
    "{0}។ សូមចុះហត្ថលេខាកិច្ចសន្យា ឬពន្យារការកក់ មុនពេលវាផុតកំណត់។",
  ],
  facts: ["Reservation", "ការកក់"],
  original: ["Original expiration", "ការផុតកំណត់ដើម"],
  agreed: ["Agreed Rent", "ថ្លៃជួលដែលបានព្រមព្រៀង"],
  agreed_note: [
    "used only for the deposit suggestion",
    "ប្រើសម្រាប់ការណែនាំប្រាក់កក់ប៉ុណ្ណោះ",
  ],
  no_extend_used: [
    "It cannot be extended again: a Reservation is extended once only.",
    "មិនអាចពន្យារម្តងទៀតបានទេ៖ ការកក់អាចពន្យារបានតែម្តងប៉ុណ្ណោះ។",
  ],
  extension: ["Extension", "ការពន្យារ"],
  was: ["Was", "ពីមុន"],
  new_exp: ["New expiration", "ការផុតកំណត់ថ្មី"],
  approved_on: ["Approved on", "បានអនុម័តនៅ"],
  memo: ["Memo", "កំណត់ចំណាំ"],
  cancellation: ["Cancellation", "ការលុបចោល"],
  expired_card: ["Expired", "ផុតកំណត់"],
  reason: ["Reason", "មូលហេតុ"],
  responsibility: ["Responsibility", "ការទទួលខុសត្រូវ"],
  resp_CUSTOMER: ["Customer", "អតិថិជន"],
  resp_PROPERTY: ["Property", "អគារ"],
  when: ["When", "ពេល"],
  offered: ["What was offered", "អ្វីដែលបានផ្តល់ជូន"],
  security: ["Security Deposit", "ប្រាក់កក់សុវត្ថិភាព"],
  suggested: ["Suggested", "ការណែនាំ"],
  suggested_note: [
    "20% of the agreed Rent, not a minimum",
    "20% នៃថ្លៃជួលដែលបានព្រមព្រៀង មិនមែនជាអប្បបរមាទេ",
  ],
  accepted: ["Accepted", "បានទទួលយក"],
  same: ["same as the suggestion", "ដូចការណែនាំ"],
  different: ["different amount approved", "ចំនួនផ្សេងដែលបានអនុម័ត"],
  received: ["Received", "បានទទួល"],
  receipt_line: ["{0} on {1}", "{0} នៅ {1}"],
  m_continues: [
    "This money is already the Security Deposit and continues into the Lease.",
    "ប្រាក់នេះជាប្រាក់កក់សុវត្ថិភាពរួចហើយ ហើយបន្តទៅកិច្ចសន្យា។",
  ],
  m_keep_wait: [
    "Under the rules the Security Deposit is kept. Nothing has moved yet: someone records the decision as a draft, and it takes effect when the Owner or a Manager confirms it.",
    "តាមវិធាន ប្រាក់កក់សុវត្ថិភាពត្រូវរក្សាទុក។ មិនទាន់មានអ្វីផ្លាស់ប្តូរទេ៖ នរណាម្នាក់កត់ត្រាការសម្រេចជាសេចក្តីព្រាង ហើយវាមានប្រសិទ្ធភាពនៅពេលម្ចាស់ ឬអ្នកគ្រប់គ្រងបញ្ជាក់។",
  ],
  m_refund_wait: [
    "Under the rules the Security Deposit is refunded. Nothing has moved yet: someone records a Refund draft, and it takes effect when the Owner or a Manager confirms it.",
    "តាមវិធាន ប្រាក់កក់សុវត្ថិភាពត្រូវសងវិញ។ មិនទាន់មានអ្វីផ្លាស់ប្តូរទេ៖ នរណាម្នាក់កត់ត្រាសេចក្តីព្រាងសងប្រាក់ ហើយវាមានប្រសិទ្ធភាពនៅពេលម្ចាស់ ឬអ្នកគ្រប់គ្រងបញ្ជាក់។",
  ],
  m_kept: [
    "The Security Deposit was kept, with a forfeiture record.",
    "ប្រាក់កក់សុវត្ថិភាពត្រូវបានរក្សាទុក ជាមួយកំណត់ត្រារឹបអូស។",
  ],
  m_refunded: [
    "The Security Deposit was refunded.",
    "ប្រាក់កក់សុវត្ថិភាពត្រូវបានសងវិញ។",
  ],
  m_none: ["No deposit money was received.", "មិនបានទទួលប្រាក់កក់ទេ។"],
  history: ["History", "ប្រវត្តិ"],
  h_reserved: ["Reservation made for {0}.", "បានកក់សម្រាប់ {0}។"],
  h_receipt: ["Deposit received: {0}.", "បានទទួលប្រាក់កក់៖ {0}។"],
  h_extended: ["Extended to {0}.", "បានពន្យាររហូតដល់ {0}។"],
  h_cancelled: ["Cancelled: {0}.", "បានលុបចោល៖ {0}។"],
  h_expired: ["Expired.", "ផុតកំណត់។"],
  h_kept: ["Security Deposit kept: {0}.", "បានរក្សាប្រាក់កក់សុវត្ថិភាព៖ {0}។"],
  h_refund: [
    "Security Deposit refunded: {0}.",
    "បានសងប្រាក់កក់សុវត្ថិភាព៖ {0}។",
  ],
  // Extend and Cancel
  extend_title: ["Extend · {0}", "ពន្យារ · {0}"],
  extend_note: [
    "A Reservation is extended once only, by at most 14 days after its current expiration.",
    "ការកក់អាចពន្យារបានតែម្តង មិនលើសពី 14 ថ្ងៃបន្ទាប់ពីថ្ងៃផុតកំណត់បច្ចុប្បន្ន។",
  ],
  latest: ["Latest possible date: {0}", "កាលបរិច្ឆេទចុងក្រោយបំផុត៖ {0}"],
  new_date: ["New expiration date", "កាលបរិច្ឆេទផុតកំណត់ថ្មី"],
  e_date: [
    "Pick a date after {0} and not later than {1}.",
    "សូមជ្រើសកាលបរិច្ឆេទក្រោយ {0} និងមិនលើស {1}។",
  ],
  memo_optional: ["Memo (optional)", "កំណត់ចំណាំ (ជម្រើស)"],
  save_extend: ["Extend", "ពន្យារ"],
  cancel_title: ["Cancel Reservation · {0}", "លុបចោលការកក់ · {0}"],
  why: ["Why is it cancelled?", "ហេតុអ្វីលុបចោល?"],
  why_customer: [
    "The Customer no longer wants the Unit. Under the rules the Security Deposit is kept.",
    "អតិថិជនលែងចង់បានបន្ទប់។ តាមវិធាន ប្រាក់កក់សុវត្ថិភាពត្រូវរក្សាទុក។",
  ],
  why_property: [
    "The Property cannot provide the Unit, and the Customer declined a later date or another Unit. Under the rules the Security Deposit is refunded.",
    "អគារមិនអាចផ្តល់បន្ទប់បាន ហើយអតិថិជនបដិសេធកាលបរិច្ឆេទក្រោយ ឬបន្ទប់ផ្សេង។ តាមវិធាន ប្រាក់កក់សុវត្ថិភាពត្រូវសងវិញ។",
  ],
  e_why: ["Choose why.", "សូមជ្រើសរើសមូលហេតុ។"],
  memo_req: ["Memo", "កំណត់ចំណាំ"],
  required: ["required", "ត្រូវតែបំពេញ"],
  e_memo: ["Enter a memo.", "សូមបញ្ចូលកំណត់ចំណាំ។"],
  offered_help: [
    "For example: offered U305 from 1 December; the Customer declined.",
    "ឧទាហរណ៍៖ បានផ្តល់ U305 ចាប់ពី 1 ធ្នូ អតិថិជនបានបដិសេធ។",
  ],
  e_offered: [
    "Say what was offered to the Customer.",
    "សូមប្រាប់អ្វីដែលបានផ្តល់ជូនអតិថិជន។",
  ],
  cancel_effects: [
    "The Unit goes back to Vacant at once. No money moves now: the deposit decision is recorded as a draft, and the Owner or a Manager confirms it.",
    "បន្ទប់ត្រឡប់ទៅទំនេរភ្លាមៗ។ គ្មានប្រាក់ផ្លាស់ទីឥឡូវទេ៖ ការសម្រេចលើប្រាក់កក់ត្រូវកត់ត្រាជាសេចក្តីព្រាង ហើយម្ចាស់ ឬអ្នកគ្រប់គ្រងបញ្ជាក់វា។",
  ],
  deposit_now: [
    "Security Deposit received: {0}",
    "ប្រាក់កក់សុវត្ថិភាពដែលបានទទួល៖ {0}",
  ],
  left_now: ["Now: {0}.", "ឥឡូវ៖ {0}។"],
  load_failed: [
    "The Reservation could not be read just now. Check the connection and try again.",
    "មិនអាចអានការកក់បានទេឥឡូវនេះ។ សូមពិនិត្យការតភ្ជាប់ ហើយព្យាយាមម្តងទៀត។",
  ],
  keep: ["Keep the Reservation", "រក្សាការកក់"],
  close: ["Close", "បិទ"],
  saving: ["Saving…", "កំពុងរក្សាទុក…"],
  try_again: ["Try again", "ព្យាយាមម្តងទៀត"],
  unknown: [
    "We could not tell whether this was saved. “Try again” sends the very same request; it is never saved twice.",
    "យើងមិនអាចដឹងថាវាត្រូវបានរក្សាទុកឬអត់ទេ។ “ព្យាយាមម្តងទៀត” ផ្ញើសំណើដដែល វាមិនត្រូវបានរក្សាទុកពីរដងទេ។",
  ],
  refused: [
    "It was not saved. Check the details and try again.",
    "មិនបានរក្សាទុកទេ។ សូមពិនិត្យព័ត៌មាន ហើយព្យាយាមម្តងទៀត។",
  ],
  conflict: [
    "Someone else changed this Reservation first. The page now shows the newest details; check them and try again.",
    "មានអ្នកផ្សេងបានកែការកក់នេះមុន។ ទំព័រនេះបង្ហាញព័ត៌មានថ្មីបំផុតហើយ សូមពិនិត្យ ហើយព្យាយាមម្តងទៀត។",
  ],
  saved_extend: [
    "The Reservation now expires on {0}.",
    "ការកក់ឥឡូវផុតកំណត់នៅ {0}។",
  ],
  saved_cancel: ["The Reservation was cancelled.", "ការកក់ត្រូវបានលុបចោល។"],
  // new
  records: ["Earlier Reservation form", "ទម្រង់ការកក់ពីមុន"],
  // new
  records_note: [
    "In English. Make Reservation stays here until it moves into the new design with Payments (step R5), because it receives the deposit.",
    "ជាភាសាអង់គ្លេស។ ការធ្វើការកក់នៅទីនេះ រហូតដល់វាផ្លាស់ទៅរចនាថ្មីជាមួយការបង់ប្រាក់ (ជំហាន R5) ព្រោះវាទទួលប្រាក់កក់។",
  ],
} as const;

export type ReservationTextKey = keyof typeof TEXT;

/** The text in the chosen language, with {0}, {1} filled in. */
export function rt(
  language: Language,
  key: ReservationTextKey,
  ...values: (string | number)[]
): string {
  return TEXT[key][language === "en" ? 0 : 1].replace(/\{(\d)\}/g, (_, n) =>
    String(values[Number(n)] ?? ""),
  );
}
