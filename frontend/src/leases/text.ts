// V1-058 R3: the words of the Leases screens in English and Khmer, from the owner's mock-up
// (i18n2.js). Khmer needs the native check before the app is used. Lines marked "new" are not
// in the mock-up.

import type { Language } from "../signInText";

const TEXT = {
  sub: [
    "Every Lease, drafted, signed or ended",
    "កិច្ចសន្យាទាំងអស់ ព្រាង បានចុះហត្ថលេខា ឬបានបញ្ចប់",
  ],
  // new
  loading: ["Loading the Leases…", "កំពុងផ្ទុកកិច្ចសន្យា…"],
  // new
  failed: [
    "The Leases could not be read just now. Check the connection and try again.",
    "មិនអាចអានកិច្ចសន្យាបានទេឥឡូវនេះ។ សូមពិនិត្យការតភ្ជាប់ ហើយព្យាយាមម្តងទៀត។",
  ],
  retry: ["Retry", "ព្យាយាមម្តងទៀត"],
  // new
  no_property: [
    "Choose the Property in Settings first.",
    "សូមជ្រើសរើសអគារក្នុងការកំណត់ជាមុនសិន។",
  ],
  c_current: ["Current", "បច្ចុប្បន្ន"],
  c_current_s: ["Signed and running", "បានចុះហត្ថលេខា និងកំពុងដំណើរការ"],
  c_ending: ["Ending soon", "ជិតបញ្ចប់"],
  c_ending_s: ["End Date before {0}", "ថ្ងៃបញ្ចប់មុន {0}"],
  c_draft: ["Drafts", "សេចក្តីព្រាង"],
  c_draft_s: ["Not signed yet", "មិនទាន់ចុះហត្ថលេខា"],
  c_ended: ["Ended", "បានបញ្ចប់"],
  c_ended_s: [
    "Past End Date, terminated or cancelled",
    "ហួសថ្ងៃបញ្ចប់ បានបញ្ចប់ ឬបានលុបចោល",
  ],
  // new
  showing: ["Showing: {0}", "កំពុងបង្ហាញ៖ {0}"],
  // new
  show_all: ["Show all", "បង្ហាញទាំងអស់"],
  none: ["No Leases here.", "គ្មានកិច្ចសន្យានៅទីនេះទេ។"],
  n1: ["1 Lease", "កិច្ចសន្យា 1"],
  n: ["{0} Leases", "កិច្ចសន្យា {0}"],
  unit: ["Unit", "បន្ទប់"],
  primary: ["Primary Tenant", "អ្នកជួលចម្បង"],
  start: ["Start Date", "ថ្ងៃចាប់ផ្តើម"],
  end: ["End Date", "ថ្ងៃបញ្ចប់"],
  rent: ["Monthly Rent", "ថ្លៃឈ្នួលប្រចាំខែ"],
  period: ["Period", "រយៈពេល"],
  // new
  dash: ["{0} – {1}", "{0} – {1}"],
  // new
  deposit_short: ["Deposit", "ប្រាក់កក់"],
  status: ["Status", "ស្ថានភាព"],
  // new
  of: ["of {0}", "នៃ {0}"],
  // new
  plus_signers: ["+{0} Signer", "+អ្នកចុះហត្ថលេខា {0}"],
  k_current: ["Lease active", "កិច្ចសន្យាកំពុងអនុវត្ត"],
  k_ending: ["Ending soon", "ជិតបញ្ចប់"],
  k_draft: ["Draft", "សេចក្តីព្រាង"],
  k_ended: ["Ended", "បានបញ្ចប់"],
  k_terminated: ["Terminated", "បានបញ្ចប់មុនកំណត់"],
  k_cancelled: ["Cancelled", "បានលុបចោល"],
  // Lease page
  back: ["Back", "ត្រឡប់ក្រោយ"],
  title: ["Lease · {0}", "កិច្ចសន្យា · {0}"],
  rent_month: ["{0} a month", "{0} ក្នុងមួយខែ"],
  // new
  missing: [
    "This Lease was not found, or your account cannot open it.",
    "រកមិនឃើញកិច្ចសន្យានេះ ឬគណនីរបស់អ្នកមិនអាចបើកវាបានទេ។",
  ],
  // new
  load_failed: [
    "The Lease could not be read just now. Check the connection and try again.",
    "មិនអាចអានកិច្ចសន្យាបានទេឥឡូវនេះ។ សូមពិនិត្យការតភ្ជាប់ ហើយព្យាយាមម្តងទៀត។",
  ],
  // new
  loading_one: ["Loading the Lease…", "កំពុងផ្ទុកកិច្ចសន្យា…"],
  ending_banner: [
    "This Lease ends on {0} ({1}). Renew it with a new signed Lease, or plan the move-out. No Rent is billed after the End Date.",
    "កិច្ចសន្យានេះបញ្ចប់នៅ {0} ({1})។ បន្តដោយកិច្ចសន្យាថ្មីបានចុះហត្ថលេខា ឬរៀបចំការចាកចេញ។ គ្មានថ្លៃឈ្នួលបន្ទាប់ពីថ្ងៃបញ្ចប់ទេ។",
  ],
  draft_banner: [
    "Draft. Signers can still be changed. Nothing is billed until the Lease is signed.",
    "សេចក្តីព្រាង។ អ្នកចុះហត្ថលេខានៅអាចប្តូរបាន។ គ្មានការគិតប្រាក់រហូតដល់ចុះហត្ថលេខា។",
  ],
  no_movein_banner: [
    "Signed, Unit is Occupied. Record the move-in when the Customer receives the keys (Start Date {0}).",
    "បានចុះហត្ថលេខា បន្ទប់មានអ្នកជួល។ កត់ត្រាការចូលស្នាក់នៅពេលអតិថិជនទទួលកូនសោ (ថ្ងៃចាប់ផ្តើម {0})។",
  ],
  // new
  renewed_banner: [
    "A renewal Lease follows this one.",
    "មានកិច្ចសន្យាបន្តបន្ទាប់ពីកិច្ចសន្យានេះ។",
  ],
  details: ["Lease", "កិច្ចសន្យា"],
  rent_fixed: [
    "Fixed in the signed Lease",
    "កំណត់ក្នុងកិច្ចសន្យាបានចុះហត្ថលេខា",
  ],
  signed_on: ["Signed on", "ចុះហត្ថលេខានៅ"],
  not_signed: ["Not signed yet", "មិនទាន់ចុះហត្ថលេខា"],
  renewal_of: ["Renewal of", "បន្តពី"],
  // new
  renewed_by: ["Renewed by", "បន្តដោយ"],
  ended_on: ["Terminated as of {0}", "បញ្ចប់ត្រឹម {0}"],
  end_note: [
    "Reaching the End Date does not end the Lease by itself and does not start a month-to-month. A renewal is a new signed Lease.",
    "ការដល់ថ្ងៃបញ្ចប់មិនបញ្ចប់កិច្ចសន្យាដោយខ្លួនឯង និងមិនចាប់ផ្តើមការជួលខែទៅខែទេ។ ការបន្តគឺជាកិច្ចសន្យាថ្មីបានចុះហត្ថលេខា។",
  ],
  // new
  not_recorded: ["Not recorded", "មិនទាន់កត់ត្រា"],
  signers: ["Signers", "អ្នកចុះហត្ថលេខា"],
  signed: ["Signed", "បានចុះហត្ថលេខា"],
  to_sign: ["To sign", "ត្រូវចុះហត្ថលេខា"],
  signed_at: ["Signed {0}", "ចុះហត្ថលេខា {0}"],
  signers_note: [
    "Every Signer is responsible for the whole balance, not a share. A Signer need not live in the Unit.",
    "អ្នកចុះហត្ថលេខាម្នាក់ៗទទួលខុសត្រូវលើសមតុល្យទាំងមូល មិនមែនចំណែកទេ។ អ្នកចុះហត្ថលេខាមិនចាំបាច់រស់នៅក្នុងបន្ទប់ទេ។",
  ],
  signers_draft: [
    "Signers are added or removed only while the Lease is a draft.",
    "អ្នកចុះហត្ថលេខាបន្ថែម ឬដកបានតែពេលកិច្ចសន្យានៅជាសេចក្តីព្រាង។",
  ],
  // new
  primary_tag: ["Primary Tenant", "អ្នកជួលចម្បង"],
  occupants: ["Occupants", "អ្នករស់នៅ"],
  in_since: ["Moved in {0}", "ចូលស្នាក់នៅ {0}"],
  out_on: ["moved out {0}", "ចាកចេញ {0}"],
  no_movein_yet: ["Nobody has moved in yet.", "មិនទាន់មាននរណាចូលស្នាក់នៅ។"],
  // new
  planned: [
    "{0} planned to live there; moves in with the Lease.",
    "{0} នាក់គ្រោងរស់នៅ ចូលស្នាក់នៅជាមួយកិច្ចសន្យា។",
  ],
  occupants_note: [
    "Occupants who did not sign owe nothing. Each one starts on the real move-in date.",
    "អ្នករស់នៅដែលមិនបានចុះហត្ថលេខាមិនជំពាក់អ្វីទេ។ ម្នាក់ៗចាប់ផ្តើមនៅថ្ងៃចូលស្នាក់នៅពិត។",
  ],
  rent_t: ["Rent and services", "ថ្លៃឈ្នួល និងសេវា"],
  initial_rent: ["Initial Rent", "ថ្លៃឈ្នួលដំបូង"],
  prorated: ["{0} × {1} ÷ {2} days = {3}.", "{0} × {1} ÷ {2} ថ្ងៃ = {3}។"],
  plus_next: ["Plus the whole next month, {0}.", "បូកខែបន្ទាប់ទាំងមូល {0}។"],
  // new
  full_month: ["The whole month: {0}.", "ពេញមួយខែ៖ {0}។"],
  // new
  initial_total: [
    "Initial Rent {0}, due {1}.",
    "ថ្លៃឈ្នួលដំបូង {0} ត្រូវបង់ត្រឹម {1}។",
  ],
  // new
  initial_total_changed: [
    "Initial Rent {0}. Its Due Date was changed with approval; the Invoice shows it.",
    "ថ្លៃឈ្នួលដំបូង {0}។ ថ្ងៃផុតកំណត់របស់វាត្រូវបានប្តូរដោយមានការអនុម័ត វិក្កយបត្របង្ហាញវា។",
  ],
  // new
  history_incomplete: [
    "Some earlier events could not be read just now.",
    "ព្រឹត្តិការណ៍មុនៗខ្លះមិនអាចអានបានទេឥឡូវនេះ។",
  ],
  initial_due_note: [
    "Start Date + 5 days. No late charge on this Invoice; management is alerted the day after it is overdue.",
    "ថ្ងៃចាប់ផ្តើម + 5 ថ្ងៃ។ គ្មានថ្លៃពិន័យលើវិក្កយបត្រនេះទេ។ អ្នកគ្រប់គ្រងត្រូវបានជូនដំណឹងថ្ងៃបន្ទាប់ពីហួសកំណត់។",
  ],
  then: ["Then", "បន្ទាប់មក"],
  recurring: [
    "Rent Invoice on the 25th each month, due on the 5th. Nothing after the End Date without a signed renewal.",
    "វិក្កយបត្រថ្លៃឈ្នួលនៅថ្ងៃទី 25 រៀងរាល់ខែ ត្រូវបង់ត្រឹមថ្ងៃទី 5។ គ្មានអ្វីបន្ទាប់ពីថ្ងៃបញ្ចប់ បើគ្មានការបន្តបានចុះហត្ថលេខា។",
  ],
  services: ["Services", "សេវា"],
  services_note: [
    "Billed on the Rent Invoice each month.",
    "គិតលើវិក្កយបត្រថ្លៃឈ្នួលរៀងរាល់ខែ។",
  ],
  // new
  no_services: ["No services on this Lease.", "គ្មានសេវាលើកិច្ចសន្យានេះទេ។"],
  // new
  from_date: ["from {0}", "ចាប់ពី {0}"],
  // new
  from_to: ["{0} to {1}", "{0} ដល់ {1}"],
  deposits: ["Deposits", "ប្រាក់កក់"],
  dep_sec: ["Security Deposit", "ប្រាក់កក់សុវត្ថិភាព"],
  dep_pet: ["Pet Deposit", "ប្រាក់កក់សត្វចិញ្ចឹម"],
  dep_req: ["Required", "តម្រូវ"],
  dep_rcv: ["Received", "បានទទួល"],
  dep_out: ["Outstanding", "នៅសល់"],
  dep_rest_due: [
    "{0} due by {1}, with the Initial Rent.",
    "{0} ត្រូវបង់ត្រឹម {1} ជាមួយថ្លៃឈ្នួលដំបូង។",
  ],
  dep_full: ["Received in full.", "បានទទួលគ្រប់ចំនួន។"],
  no_pet: [
    "No pet approved, so no Pet Deposit.",
    "គ្មានសត្វចិញ្ចឹមអនុម័ត ដូច្នេះគ្មានប្រាក់កក់សត្វចិញ្ចឹម។",
  ],
  // new
  pet_approved: ["Pet approved: {0}", "សត្វចិញ្ចឹមបានអនុម័ត៖ {0}"],
  // new
  no_deposit: [
    "No Security Deposit is recorded for this Lease yet.",
    "មិនទាន់មានប្រាក់កក់សុវត្ថិភាពកត់ត្រាសម្រាប់កិច្ចសន្យានេះទេ។",
  ],
  // new
  deposits_hidden: [
    "Your account cannot see the deposits.",
    "គណនីរបស់អ្នកមិនអាចមើលប្រាក់កក់បានទេ។",
  ],
  // new
  deposits_failed: [
    "The deposits could not be read just now.",
    "មិនអាចអានប្រាក់កក់បានទេឥឡូវនេះ។",
  ],
  dep_note: [
    "Deposits are held, not income. They never pay ordinary Invoices and are settled only at the Final Settlement after move-out. An unpaid deposit does not block the move-in.",
    "ប្រាក់កក់ត្រូវបានរក្សា មិនមែនចំណូលទេ។ វាមិនដែលបង់វិក្កយបត្រធម្មតា និងទូទាត់តែក្នុងការទូទាត់ចុងក្រោយបន្ទាប់ពីចាកចេញ។ ប្រាក់កក់មិនទាន់បង់មិនរារាំងការចូលស្នាក់នៅទេ។",
  ],
  term_t: ["Termination", "ការបញ្ចប់មុនកំណត់"],
  term_date: ["Termination date", "ថ្ងៃបញ្ចប់"],
  // new
  term_recorded: ["Recorded on", "កត់ត្រានៅ"],
  moveout_on: ["Moved out on", "ចាកចេញនៅ"],
  still_in: ["Still in the Unit", "នៅក្នុងបន្ទប់"],
  history: ["History", "ប្រវត្តិ"],
  // new
  more: ["Show earlier events", "បង្ហាញព្រឹត្តិការណ៍មុនៗ"],
  // new
  h_none: ["Nothing recorded yet.", "មិនទាន់មានកំណត់ត្រាទេ។"],
  // new: history event names
  "e_lease.draft": ["Draft made", "សេចក្តីព្រាងបានធ្វើ"],
  "e_lease.draft.update": ["Draft changed", "សេចក្តីព្រាងបានកែ"],
  "e_lease.signer.add": ["Signer added", "បានបន្ថែមអ្នកចុះហត្ថលេខា"],
  "e_lease.signer.remove": ["Signer removed", "បានដកអ្នកចុះហត្ថលេខា"],
  "e_lease.signer.sign": ["Signer signed", "អ្នកចុះហត្ថលេខាបានចុះហត្ថលេខា"],
  "e_lease.sign": ["Lease signed", "កិច្ចសន្យាបានចុះហត្ថលេខា"],
  "e_lease.cancel": ["Draft cancelled", "សេចក្តីព្រាងបានលុបចោល"],
  "e_lease.terminate": ["Lease terminated", "កិច្ចសន្យាបានបញ្ចប់មុនកំណត់"],
  "e_lease.move_in": ["Move-in recorded", "បានកត់ត្រាការចូលស្នាក់នៅ"],
  "e_lease.termination_notice": [
    "Termination notice recorded",
    "បានកត់ត្រាការជូនដំណឹងបញ្ចប់",
  ],
  "e_lease.violation_warning": [
    "Rule warning recorded",
    "បានកត់ត្រាការព្រមានវិធាន",
  ],
  "e_lease.renewal_successor": [
    "Renewal Lease drafted",
    "កិច្ចសន្យាបន្តបានព្រាង",
  ],
  "e_lease.unpaid_initial_never_moved_in": [
    "Unpaid Initial Rent settled: never moved in",
    "ថ្លៃឈ្នួលដំបូងមិនទាន់បង់បានដោះស្រាយ៖ មិនបានចូលស្នាក់នៅ",
  ],
  "e_lease.unpaid_initial_moved_in_credit": [
    "Unpaid Initial Rent settled: Rent credited after termination",
    "ថ្លៃឈ្នួលដំបូងមិនទាន់បង់បានដោះស្រាយ៖ ថ្លៃឈ្នួលបានឥណទានក្រោយការបញ្ចប់",
  ],
  "e_lease.initial_rent_due_date_override": [
    "Initial Rent Due Date set",
    "បានកំណត់ថ្ងៃផុតកំណត់ថ្លៃឈ្នួលដំបូង",
  ],
  "e_lease.rent_nonpayment_twenty_day_warning": [
    "Day-20 Rent letter recorded",
    "បានកត់ត្រាលិខិតថ្លៃឈ្នួលថ្ងៃទី 20",
  ],
  "e_lease.rent_nonpayment_thirty_day_serious_default": [
    "Day-30 Rent letter recorded",
    "បានកត់ត្រាលិខិតថ្លៃឈ្នួលថ្ងៃទី 30",
  ],
  "e_lease.rent_nonpayment_cure": [
    "Unpaid Rent paid after a letter",
    "ថ្លៃឈ្នួលមិនទាន់បង់ត្រូវបានបង់ក្រោយលិខិត",
  ],
  "e_lease.rent_nonpayment_authorized_follow_up": [
    "Follow-up after the Rent letters recorded",
    "បានកត់ត្រាការតាមដានក្រោយលិខិតថ្លៃឈ្នួល",
  ],
  // new
  e_other: ["Lease event", "ព្រឹត្តិការណ៍កិច្ចសន្យា"],
  // new
  records: ["Earlier Lease forms", "ទម្រង់កិច្ចសន្យាពីមុន"],
  // new
  records_note: [
    "In English. New Lease, Sign, Record move-in, Renew, Terminate and Cancel draft stay here until they move into the new design in the next step.",
    "ជាភាសាអង់គ្លេស។ កិច្ចសន្យាថ្មី ចុះហត្ថលេខា កត់ត្រាការចូលស្នាក់នៅ បន្ត បញ្ចប់ និងលុបចោលសេចក្តីព្រាង នៅទីនេះ រហូតដល់ផ្លាស់ទៅរចនាថ្មីក្នុងជំហានបន្ទាប់។",
  ],
} as const;

export type LeaseTextKey = keyof typeof TEXT;

export function hasLeaseText(key: string): key is LeaseTextKey {
  return key in TEXT;
}

/** The text in the chosen language, with {0}, {1} filled in. */
export function lt(
  language: Language,
  key: LeaseTextKey,
  ...values: (string | number)[]
): string {
  return TEXT[key][language === "en" ? 0 : 1].replace(/\{(\d)\}/g, (_, n) =>
    String(values[Number(n)] ?? ""),
  );
}
