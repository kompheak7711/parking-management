// V1-058 R3: the words of the Reservations screens in English and Khmer, from the owner's
// mock-up (i18n). Khmer needs the native check before the app is used. Lines marked "new"
// are not in the mock-up. The words "Reservation Deposit" and "converted" are never used
// (docs/001 §89): the money is the Security Deposit from the first day.

import type { Language } from "../signInText";

const TEXT = {
  sub: [
    "{0} Reservations · a Parking held for a Customer until the Lease is signed",
    "ការកក់ {0} · ចំណតដែលរក្សាទុកសម្រាប់អតិថិជន រហូតដល់ចុះហត្ថលេខាកិច្ចសន្យា",
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
  c_active_s: ["Holding a Parking now", "កំពុងរក្សាចំណតឥឡូវនេះ"],
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
  unit: ["Parking", "ចំណត"],
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
  r_customer: ["Customer no longer wants the Parking", "អតិថិជនលែងចង់បានចំណត"],
  r_property: [
    "Property could not provide the Parking",
    "អគារមិនអាចផ្តល់ចំណតបាន",
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
    "The Customer no longer wants the Parking. Under the rules the Security Deposit is kept.",
    "អតិថិជនលែងចង់បានចំណត។ តាមវិធាន ប្រាក់កក់សុវត្ថិភាពត្រូវរក្សាទុក។",
  ],
  why_property: [
    "The Property cannot provide the Parking, and the Customer declined a later date or another Parking. Under the rules the Security Deposit is refunded.",
    "អគារមិនអាចផ្តល់ចំណតបាន ហើយអតិថិជនបដិសេធកាលបរិច្ឆេទក្រោយ ឬចំណតផ្សេង។ តាមវិធាន ប្រាក់កក់សុវត្ថិភាពត្រូវសងវិញ។",
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
    "The Parking goes back to Vacant at once. No money moves now: the deposit decision is recorded as a draft, and the Owner or a Manager confirms it.",
    "ចំណតត្រឡប់ទៅទំនេរភ្លាមៗ។ គ្មានប្រាក់ផ្លាស់ទីឥឡូវទេ៖ ការសម្រេចលើប្រាក់កក់ត្រូវកត់ត្រាជាសេចក្តីព្រាង ហើយម្ចាស់ ឬអ្នកគ្រប់គ្រងបញ្ជាក់វា។",
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
  // V1-060 B6: Make Reservation in the new design (owner 27/10/2026).
  mk_title: ["Make Reservation", "ធ្វើការកក់"],
  mk_unit: ["Parking", "ចំណត"],
  mk_choose_unit: ["Choose a vacant Parking", "ជ្រើសរើសចំណតទំនេរ"],
  mk_no_units: ["No Parking is vacant now.", "ឥឡូវនេះមិនមានចំណតទំនេរទេ។"],
  mk_customer: ["Customer", "អតិថិជន"],
  mk_choose_customer: ["Choose a Customer", "ជ្រើសរើសអតិថិជន"],
  mk_new_customer: ["New Customer", "អតិថិជនថ្មី"],
  mk_date: ["Reservation Date", "ថ្ងៃកក់"],
  mk_expires: ["Expires on", "ផុតកំណត់នៅ"],
  mk_expires_help: [
    "At most 21 days after the Reservation Date.",
    "យូរបំផុត 21 ថ្ងៃ បន្ទាប់ពីថ្ងៃកក់។",
  ],
  mk_rent: [
    "Agreed monthly Rent (USD)",
    "ថ្លៃឈ្នួលប្រចាំខែដែលបានព្រមព្រៀង (USD)",
  ],
  mk_required: ["Full Security Deposit (USD)", "ប្រាក់កក់សុវត្ថិភាពពេញ (USD)"],
  mk_required_help: ["Usually one month's Rent.", "ជាធម្មតាថ្លៃឈ្នួលមួយខែ។"],
  mk_received: ["Received now (USD)", "ទទួលបានឥឡូវនេះ (USD)"],
  mk_received_help: [
    "Suggested: 20% of the agreed Rent, {0}.",
    "ការណែនាំ៖ 20% នៃថ្លៃឈ្នួលដែលបានព្រមព្រៀង {0}។",
  ],
  mk_reason: [
    "Why less than the suggestion (needs the Manager's approval)",
    "ហេតុអ្វីតិចជាងចំនួនណែនាំ (ត្រូវការការអនុម័តពីអ្នកគ្រប់គ្រង)",
  ],
  mk_reason_default: [
    "Suggested 20% of the agreed Rent.",
    "Suggested 20% of the agreed Rent.",
  ],
  mk_reason_more: [
    "More than the suggested 20% received.",
    "More than the suggested 20% received.",
  ],
  mk_save: ["Save Reservation", "រក្សាទុកការកក់"],
  mk_err_unit: ["Choose a Parking.", "សូមជ្រើសរើសចំណត។"],
  mk_err_customer: ["Choose a Customer.", "សូមជ្រើសរើសអតិថិជន។"],
  mk_err_date: ["Type a real day.", "សូមវាយថ្ងៃដែលត្រឹមត្រូវ។"],
  mk_err_expires: [
    "Pick a day after the Reservation Date, at most 21 days later.",
    "សូមជ្រើសរើសថ្ងៃបន្ទាប់ពីថ្ងៃកក់ យូរបំផុត 21 ថ្ងៃក្រោយ។",
  ],
  mk_err_rent: [
    "Type the Rent, such as 450.00.",
    "សូមវាយថ្លៃឈ្នួល ដូចជា 450.00។",
  ],
  mk_err_required: [
    "Type the full Security Deposit; it cannot be less than what is received now.",
    "សូមវាយប្រាក់កក់សុវត្ថិភាពពេញ វាមិនអាចតិចជាងប្រាក់ដែលទទួលបានឥឡូវនេះទេ។",
  ],
  mk_err_received: [
    "Type the amount received now.",
    "សូមវាយចំនួនដែលទទួលបានឥឡូវនេះ។",
  ],
  mk_err_reason: [
    "Say why the amount is less than the suggestion.",
    "សូមប្រាប់ពីមូលហេតុដែលចំនួនតិចជាងការណែនាំ។",
  ],
  // V1-060 B7: said before any money is taken.
  mk_err_override: [
    "Less than the suggested {0} needs the Owner or a Manager. Ask one of them, or receive at least {0}.",
    "ចំនួនតិចជាងការណែនាំ {0} ត្រូវការម្ចាស់ ឬអ្នកគ្រប់គ្រង។ សូមសួរពួកគេម្នាក់ ឬទទួលយ៉ាងហោចណាស់ {0}។",
  ],
  // V1-060 B7: said before any money is taken, while this person's rights are not known.
  mk_err_rights: [
    "Your rights could not be read just now, so less than the suggested {0} cannot be checked before the money is taken. Reload the page, or receive at least {0}.",
    "មិនអាចអានសិទ្ធិរបស់អ្នកបានទេឥឡូវនេះ ដូច្នេះមិនអាចពិនិត្យចំនួនតិចជាងការណែនាំ {0} មុនពេលទទួលប្រាក់បានទេ។ សូមផ្ទុកទំព័រឡើងវិញ ឬទទួលយ៉ាងហោចណាស់ {0}។",
  ],
  mk_conflict: [
    "The Reservation was not saved: the Parking or the Customer changed meanwhile (for example, someone else reserved this Parking first). Check them, then try again.",
    "ការកក់មិនត្រូវបានរក្សាទុកទេ៖ ចំណត ឬអតិថិជនបានផ្លាស់ប្តូរក្នុងពេលនេះ (ឧទាហរណ៍ មានអ្នកផ្សេងបានកក់ចំណតនេះមុន)។ សូមពិនិត្យពួកវា រួចព្យាយាមម្តងទៀត។",
  ],
  mk_memo: [
    "Security Deposit received with the Reservation of {0}",
    "Security Deposit received with the Reservation of {0}",
  ],
  mk_loading: [
    "Reading the Parking and Customers…",
    "កំពុងអានចំណត និងអតិថិជន…",
  ],
  // new (V1-061, owner 29/10/2026, DL-110): the Unit's default Rent
  mk_rent_default: [
    "This Parking's default Rent is {0}. A higher Rent is fine.",
    "ថ្លៃឈ្នួលលំនាំដើមរបស់ចំណតនេះគឺ {0}។ ថ្លៃខ្ពស់ជាងនេះអាចធ្វើបាន។",
  ],
  mk_err_rent_below: [
    "The Rent is below this Parking's default Rent of {0}. Only a Manager or the Owner can agree a lower Rent.",
    "ថ្លៃឈ្នួលទាបជាងថ្លៃលំនាំដើម {0} របស់ចំណតនេះ។ មានតែអ្នកគ្រប់គ្រង ឬម្ចាស់ប៉ុណ្ណោះដែលអាចយល់ព្រមថ្លៃទាបជាងនេះ។",
  ],
  mk_err_rent_rights: [
    "Your rights could not be read just now, so a Rent below {0} cannot be checked before the money is taken. Reload the page, or agree at least {0}.",
    "មិនអាចអានសិទ្ធិរបស់អ្នកបានទេឥឡូវនេះ ដូច្នេះមិនអាចពិនិត្យថ្លៃទាបជាង {0} មុនពេលទទួលប្រាក់បានទេ។ សូមផ្ទុកទំព័រឡើងវិញ ឬយល់ព្រមយ៉ាងហោចណាស់ {0}។",
  ],
  mk_rent_reason: [
    "Why is the Rent below {0}?",
    "ហេតុអ្វីថ្លៃឈ្នួលទាបជាង {0}?",
  ],
  mk_err_rent_reason: [
    "Say why the Rent is lower.",
    "សូមប្រាប់ហេតុអ្វីថ្លៃឈ្នួលទាបជាង។",
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
