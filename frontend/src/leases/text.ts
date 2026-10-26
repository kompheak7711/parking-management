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
    "In English. New Lease, Renew, Terminate, Signers and occupants stay here until they move into the new design, and so does a move-in the new dialog does not offer.",
    "ជាភាសាអង់គ្លេស។ កិច្ចសន្យាថ្មី បន្ត បញ្ចប់ អ្នកចុះហត្ថលេខា និងអ្នករស់នៅ នៅទីនេះ រហូតដល់ផ្លាស់ទៅរចនាថ្មី ហើយការចូលស្នាក់នៅដែលប្រអប់ថ្មីមិនផ្តល់ក៏ដូចគ្នា។",
  ],
  // Actions (L2)
  sign: ["Sign Lease", "ចុះហត្ថលេខាកិច្ចសន្យា"],
  edit_draft: ["Edit draft", "កែសេចក្តីព្រាង"],
  manager: ["Manager", "អ្នកគ្រប់គ្រង"],
  // new
  sign_title: ["Sign Lease · {0}", "ចុះហត្ថលេខាកិច្ចសន្យា · {0}"],
  sign_confirm: [
    "Each Signer has signed the paper Lease",
    "អ្នកចុះហត្ថលេខាម្នាក់ៗបានចុះហត្ថលេខាលើកិច្ចសន្យាក្រដាស",
  ],
  sign_all: [
    "Tick every Signer. The Lease is signed only when all have signed.",
    "សូមធីកអ្នកចុះហត្ថលេខាទាំងអស់។ កិច្ចសន្យាចុះហត្ថលេខាបានតែពេលទាំងអស់គ្នាបានចុះ។",
  ],
  // new
  sign_what: ["What happens when you save", "អ្វីកើតឡើងពេលអ្នករក្សាទុក"],
  sign_s1: [
    "{0} becomes Occupied now, before the move-in.",
    "{0} ក្លាយជា មានអ្នកជួល ឥឡូវ មុនការចូលស្នាក់នៅ។",
  ],
  // new: the mock-up line, shown when an active Reservation was found
  sign_s2: [
    "An active Reservation of this Customer for this Unit is completed in the same step; its deposit continues as the Security Deposit.",
    "ការកក់កំពុងដំណើរការរបស់អតិថិជននេះសម្រាប់បន្ទប់នេះ បានបញ្ចប់ក្នុងជំហានតែមួយ។ ប្រាក់កក់របស់វាបន្តជាប្រាក់កក់សុវត្ថិភាព។",
  ],
  // new: billing makes the Initial Rent Invoice after signing, not the signing itself
  sign_s3: [
    "Initial Rent of {0} becomes due {1}; billing makes its Invoice.",
    "ថ្លៃឈ្នួលដំបូង {0} ត្រូវបង់ត្រឹម {1}។ ការចេញវិក្កយបត្រធ្វើវិក្កយបត្ររបស់វា។",
  ],
  // new
  sign_s3_set: [
    "Initial Rent of {0} becomes due on the approved Due Date; billing makes its Invoice.",
    "ថ្លៃឈ្នួលដំបូង {0} ត្រូវបង់ត្រឹមថ្ងៃកំណត់ដែលបានអនុម័ត។ ការចេញវិក្កយបត្រធ្វើវិក្កយបត្ររបស់វា។",
  ],
  sign_s4: [
    "{0} of the Security Deposit is still due.",
    "{0} នៃប្រាក់កក់សុវត្ថិភាពនៅត្រូវបង់។",
  ],
  // new
  sign_res_check: [
    "Checking for a Reservation of this Customer…",
    "កំពុងពិនិត្យការកក់របស់អតិថិជននេះ…",
  ],
  // new
  sign_res_failed: [
    "The Reservations could not be read. If this Unit is Reserved, the signing will be refused; ask someone who can see Reservations.",
    "មិនអាចអានការកក់បានទេ។ បើបន្ទប់នេះត្រូវបានកក់ ការចុះហត្ថលេខានឹងត្រូវបដិសេធ។ សូមសួរអ្នកដែលអាចមើលការកក់។",
  ],
  // new
  sign_refused: [
    "The server refused the signing. Any signatures already recorded stay recorded and show on this Lease. Check the details, or ask the Owner.",
    "ម៉ាស៊ីនមេបានបដិសេធការចុះហត្ថលេខា។ ហត្ថលេខាដែលបានកត់ត្រារួច នៅតែកត់ត្រា ហើយបង្ហាញលើកិច្ចសន្យានេះ។ សូមពិនិត្យព័ត៌មាន ឬសួរម្ចាស់។",
  ],
  // new
  sign_already: ["signed {0}", "បានចុះហត្ថលេខា {0}"],
  sign_ok: ["Record signing", "កត់ត្រាការចុះហត្ថលេខា"],
  signed_toast: [
    "Lease signed. {0} is Occupied.",
    "កិច្ចសន្យាបានចុះហត្ថលេខា។ {0} មានអ្នកជួល។",
  ],
  // new
  edit_title: ["Edit draft · {0}", "កែសេចក្តីព្រាង · {0}"],
  // new
  edit_note: [
    "Only a draft can change. Signers are changed in the draft form for now.",
    "មានតែសេចក្តីព្រាងប៉ុណ្ណោះអាចប្តូរបាន។ អ្នកចុះហត្ថលេខាប្តូរក្នុងទម្រង់សេចក្តីព្រាងសិន។",
  ],
  // new
  why_change: ["Why it changed", "ហេតុអ្វីប្តូរ"],
  required: ["required", "ត្រូវតែបំពេញ"],
  // new
  save: ["Save", "រក្សាទុក"],
  // new
  draft_saved: ["The draft was saved.", "សេចក្តីព្រាងត្រូវបានរក្សាទុក។"],
  err_start: ["Enter the Start Date.", "សូមបញ្ចូលថ្ងៃចាប់ផ្តើម។"],
  err_end: [
    "The End Date must be after the Start Date and the last day of a month.",
    "ថ្ងៃបញ្ចប់ត្រូវតែក្រោយថ្ងៃចាប់ផ្តើម ហើយជាថ្ងៃចុងក្រោយនៃខែ។",
  ],
  err_rent: ["Enter the monthly Rent.", "សូមបញ្ចូលថ្លៃឈ្នួលប្រចាំខែ។"],
  // new
  err_reason: ["Say why it changed.", "សូមប្រាប់ហេតុអ្វីប្តូរ។"],
  // new
  close: ["Close", "បិទ"],
  // new
  saving: ["Saving…", "កំពុងរក្សាទុក…"],
  // new
  try_again: ["Try again", "ព្យាយាមម្តងទៀត"],
  // new
  unknown: [
    "We could not tell whether this was saved. “Try again” sends the very same request; it is never saved twice.",
    "យើងមិនអាចដឹងថាវាត្រូវបានរក្សាទុកឬអត់។ «ព្យាយាមម្តងទៀត» ផ្ញើសំណើដដែល វាមិនដែលរក្សាទុកពីរដងទេ។",
  ],
  // new
  refused: [
    "The server refused this. Nothing was saved. Check the details, or ask the Owner.",
    "ម៉ាស៊ីនមេបានបដិសេធ។ គ្មានអ្វីត្រូវបានរក្សាទុកទេ។ សូមពិនិត្យព័ត៌មាន ឬសួរម្ចាស់។",
  ],
  // new
  conflict: [
    "This Lease or its Unit changed meanwhile, so nothing more was saved. It was read again: check it and try again.",
    "កិច្ចសន្យានេះ ឬបន្ទប់របស់វាបានប្តូរក្នុងពេលនេះ ដូច្នេះគ្មានអ្វីបន្ថែមត្រូវបានរក្សាទុកទេ។ វាត្រូវបានអានម្តងទៀត៖ សូមពិនិត្យ ហើយព្យាយាមម្តងទៀត។",
  ],
  // L2b
  cancel_draft: ["Cancel draft", "លុបសេចក្តីព្រាង"],
  record_move_in: ["Record move-in", "កត់ត្រាការចូលស្នាក់នៅ"],
  // new
  cancel_title: ["Cancel draft · {0}", "លុបសេចក្តីព្រាង · {0}"],
  // new
  cancel_note: [
    "Only a draft is cancelled; a signed Lease never is. The Unit and any Booking stay as they are.",
    "មានតែសេចក្តីព្រាងប៉ុណ្ណោះដែលត្រូវលុប កិច្ចសន្យាដែលបានចុះហត្ថលេខាមិនដែលលុបទេ។ បន្ទប់ និងការកក់ណាមួយ នៅដដែល។",
  ],
  memo: ["Memo", "កំណត់ចំណាំ"],
  // new
  err_memo: ["Write why it is cancelled.", "សូមសរសេរហេតុអ្វីលុប។"],
  // new
  cancel_ok: ["Cancel the draft", "លុបសេចក្តីព្រាង"],
  // new
  cancelled_toast: ["The draft was cancelled.", "សេចក្តីព្រាងត្រូវបានលុប។"],
  // new
  movein_title: ["Record move-in · {0}", "កត់ត្រាការចូលស្នាក់នៅ · {0}"],
  movein_day: ["Move-in date", "ថ្ងៃចូលស្នាក់នៅ"],
  movein_who: ["Who moves in", "អ្នកណាចូលស្នាក់នៅ"],
  // new
  planned_tag: ["planned", "គ្រោងទុក"],
  // new
  occupant_unnamed: [
    "A Customer of this Lease",
    "អតិថិជនម្នាក់នៃកិច្ចសន្យានេះ",
  ],
  // new
  movein_others: [
    "To add someone not named in the Lease, ask a person who can see Customers.",
    "ដើម្បីបន្ថែមអ្នកដែលមិនមានឈ្មោះក្នុងកិច្ចសន្យា សូមសួរអ្នកដែលអាចមើលអតិថិជន។",
  ],
  // new
  note: ["Note (optional)", "កំណត់ចំណាំ (ស្រេចចិត្ត)"],
  // new
  movein_add: ["Someone else moves in too", "មានអ្នកផ្សេងទៀតចូលស្នាក់នៅដែរ"],
  // new
  movein_ok: ["Record move-in", "កត់ត្រាការចូលស្នាក់នៅ"],
  // new
  moved_in_toast: ["Move-in recorded.", "ការចូលស្នាក់នៅត្រូវបានកត់ត្រា។"],
  // new
  err_movein_day: [
    "Choose a date from {0} to {1}.",
    "សូមជ្រើសថ្ងៃពី {0} ដល់ {1}។",
  ],
  // new
  err_movein_early: [
    "The move-in can be recorded from {0}.",
    "ការចូលស្នាក់នៅអាចកត់ត្រាបានចាប់ពី {0}។",
  ],
  // new
  err_who: ["Tick who moves in.", "សូមធីកអ្នកដែលចូលស្នាក់នៅ។"],
  // L2b-2: New Lease and Renew
  new_lease: ["New Lease", "កិច្ចសន្យាថ្មី"],
  renew: ["Renew", "បន្ត"],
  open_moveout: ["Open move-out", "បើកការចាកចេញ"],
  new_title: ["New Lease", "កិច្ចសន្យាថ្មី"],
  // new
  renew_title: ["Renew Lease", "បន្តកិច្ចសន្យា"],
  // new
  new_sub: [
    "A draft first; it is signed when every Signer has signed the paper Lease.",
    "ជាសេចក្តីព្រាងសិន វាចុះហត្ថលេខាពេលអ្នកចុះហត្ថលេខាទាំងអស់បានចុះលើក្រដាស។",
  ],
  // new
  from_booking: [
    "From the Booking of {0}: the Unit, the Customer, the agreed Rent and the deposit come from it.",
    "ពីការកក់របស់ {0}៖ បន្ទប់ អតិថិជន ថ្លៃឈ្នួលដែលបានព្រមព្រៀង និងប្រាក់កក់ មកពីវា។",
  ],
  // new
  renew_sub: [
    "The new Lease for {0} starts the day after the old End Date and is linked to it. The Unit stays Occupied.",
    "កិច្ចសន្យាថ្មីសម្រាប់ {0} ចាប់ផ្តើមថ្ងៃបន្ទាប់ពីថ្ងៃបញ្ចប់ចាស់ ហើយភ្ជាប់ទៅវា។ បន្ទប់នៅតែមានអ្នកជួល។",
  ],
  // new
  form_failed: [
    "The Units and Customers could not be read just now. Check the connection and your access, and try again.",
    "មិនអាចអានបន្ទប់ និងអតិថិជនបានទេឥឡូវនេះ។ សូមពិនិត្យការតភ្ជាប់ និងសិទ្ធិរបស់អ្នក ហើយព្យាយាមម្តងទៀត។",
  ],
  terms: ["Lease terms", "លក្ខខណ្ឌកិច្ចសន្យា"],
  // new
  choose_unit: ["Choose a Unit", "ជ្រើសបន្ទប់"],
  // new
  unit_help: [
    "Vacant, cleaning or maintenance Units. A Reserved Unit gets its Lease from its Booking.",
    "បន្ទប់ទំនេរ កំពុងសម្អាត ឬកំពុងជួសជុល។ បន្ទប់ដែលបានកក់ ទទួលកិច្ចសន្យាពីការកក់របស់វា។",
  ],
  // new
  choose_customer: ["Choose a Customer", "ជ្រើសអតិថិជន"],
  other_signers: ["Other Signers", "អ្នកចុះហត្ថលេខាផ្សេងទៀត"],
  other_occupants: ["Other occupants", "អ្នករស់នៅផ្សេងទៀត"],
  // new
  add_person: ["Add a Customer…", "បន្ថែមអតិថិជន…"],
  add_button: ["Add", "បន្ថែម"],
  // new
  remove: ["Remove {0}", "ដក {0}"],
  // new
  end_help: [
    "Filled in as one year, to the last day of a month.",
    "បំពេញជាមួយឆ្នាំ ដល់ថ្ងៃចុងក្រោយនៃខែ។",
  ],
  pet_ok: ["A pet is approved", "សត្វចិញ្ចឹមត្រូវបានអនុញ្ញាត"],
  // new
  pet_what: ["Which pet", "សត្វចិញ្ចឹមអ្វី"],
  // new
  pet_help: [
    "A Pet Deposit is required; its amount is entered on the Lease after saving.",
    "ត្រូវការប្រាក់កក់សត្វចិញ្ចឹម ចំនួនរបស់វាបញ្ចូលលើកិច្ចសន្យាក្រោយរក្សាទុក។",
  ],
  // new
  err_pet: ["Say which pet.", "សូមប្រាប់សត្វចិញ្ចឹមអ្វី។"],
  // new
  err_unit: ["Choose the Unit.", "សូមជ្រើសបន្ទប់។"],
  // new
  err_tenant: ["Choose the Primary Tenant.", "សូមជ្រើសអ្នកជួលចម្បង។"],
  // new
  // new (R7b-6c)
  services_t: ["Services", "សេវា"],
  svc_loading: ["Reading the Services…", "កំពុងអានសេវា…"],
  svc_failed: [
    "The Services could not be read just now. Press Retry; the draft waits for them.",
    "មិនអាចអានសេវាបានទេឥឡូវនេះ។ សូមចុចព្យាយាមម្តងទៀត សេចក្តីព្រាងរង់ចាំវា។",
  ],
  svc_dates: [
    "Enter the Start Date and End Date to choose the Services.",
    "សូមបញ្ចូលថ្ងៃចាប់ផ្តើម និងថ្ងៃបញ្ចប់ ដើម្បីជ្រើសសេវា។",
  ],
  no_meter_e: [
    "This Unit has no electricity meter, so no electricity is billed. Add the meter in Utilities when it is put in.",
    "បន្ទប់នេះគ្មាននាឡិកាស្ទង់អគ្គិសនីទេ ដូច្នេះមិនគិតថ្លៃអគ្គិសនីទេ។ សូមបន្ថែមនាឡិកាស្ទង់ក្នុងទឹកភ្លើង ពេលដំឡើងរួច។",
  ],
  no_meter_w: [
    "This Unit has no water meter, so no water is billed. Add the meter in Utilities when it is put in.",
    "បន្ទប់នេះគ្មាននាឡិកាស្ទង់ទឹកទេ ដូច្នេះមិនគិតថ្លៃទឹកទេ។ សូមបន្ថែមនាឡិកាស្ទង់ក្នុងទឹកភ្លើង ពេលដំឡើងរួច។",
  ],
  no_meter_both: [
    "This Unit has no electricity or water meter, so no Utilities are billed. Add the meters in Utilities when they are put in.",
    "បន្ទប់នេះគ្មាននាឡិកាស្ទង់អគ្គិសនី ឬទឹកទេ ដូច្នេះមិនគិតថ្លៃទឹកភ្លើងទេ។ សូមបន្ថែមនាឡិកាស្ទង់ក្នុងទឹកភ្លើង ពេលដំឡើងរួច។",
  ],
  svc_new: ["New Service", "សេវាថ្មី"],
  svc_added: [
    "{0} added. Tick it below if this Lease uses it.",
    "បានបន្ថែម {0}។ សូមធីកខាងក្រោម ប្រសិនបើកិច្ចសន្យានេះប្រើវា។",
  ],
  svc_none: [
    "No Services are set up in Settings yet.",
    "មិនទាន់មានសេវាក្នុងការកំណត់នៅឡើយទេ។",
  ],
  svc_one: ["Only one", "តែមួយ"],
  svc_many: ["One or more", "មួយ ឬច្រើន"],
  svc_none_pick: ["None", "គ្មាន"],
  svc_rate: ["{0} a month", "{0} ក្នុងមួយខែ"],
  svc_no_rate: ["No rate yet", "មិនទាន់មានអត្រា"],
  svc_starts: ["Starts {0}", "ចាប់ផ្តើម {0}"],
  svc_closed: ["Not open for these dates", "មិនបើកសម្រាប់កាលបរិច្ឆេទទាំងនេះ"],
  err_svc_wait: [
    "The Services are not read yet. Press Retry above.",
    "សេវាមិនទាន់បានអានទេ។ សូមចុចព្យាយាមម្តងទៀតខាងលើ។",
  ],
  err_svc_greyed: [
    "A chosen Service cannot run for the whole Lease. Untick it or change the dates.",
    "សេវាដែលបានជ្រើសមិនអាចដំណើរការពេញកិច្ចសន្យាបានទេ។ សូមដកធីក ឬប្តូរកាលបរិច្ឆេទ។",
  ],
  pv_service: [
    "{0}: {1} a month from the Start Date, on the Rent Invoice.",
    "{0}៖ {1} ក្នុងមួយខែ ចាប់ពីថ្ងៃចាប់ផ្តើម នៅលើវិក្កយបត្រថ្លៃឈ្នួល។",
  ],
  pv_service_no_rate: [
    "{0}: no rate is set yet.",
    "{0}៖ មិនទាន់កំណត់អត្រានៅឡើយទេ។",
  ],
  confirm_services: ["Services: {0}.", "សេវា៖ {0}។"],
  svc_other: ["Other Services", "សេវាផ្សេងទៀត"],
  err_svc_many: [
    "A Lease can have at most 20 Services.",
    "កិច្ចសន្យាមួយអាចមានសេវាបានច្រើនបំផុត 20។",
  ],
  confirm_no_services: ["No Services.", "គ្មានសេវា។"],
  // new
  save_draft: ["Save draft", "រក្សាទុកសេចក្តីព្រាង"],
  preview: ["What will be billed", "អ្វីដែលនឹងចេញវិក្កយបត្រ"],
  // new
  preview_wait: [
    "Enter the Start Date and the Rent to see it.",
    "សូមបញ្ចូលថ្ងៃចាប់ផ្តើម និងថ្លៃឈ្នួល ដើម្បីមើល។",
  ],
  pv_initial: [
    "Initial Rent {0}, due {1}, with the rest of the Security Deposit.",
    "ថ្លៃឈ្នួលដំបូង {0} ត្រូវបង់ត្រឹម {1} រួមនឹងប្រាក់កក់សុវត្ថិភាពដែលនៅសល់។",
  ],
  pv_initial_how: [
    "{0} × {1} ÷ {2} days = {3}.",
    "{0} × {1} ÷ {2} ថ្ងៃ = {3}។",
  ],
  pv_next_month: [
    "It starts on day 21 or later, so the whole next month ({0}) is added.",
    "វាចាប់ផ្តើមថ្ងៃទី២១ ឬក្រោយ ដូច្នេះបន្ថែមខែបន្ទាប់ទាំងមូល ({0})។",
  ],
  pv_monthly: [
    "Then {0} on the 25th each month, due on the 5th.",
    "បន្ទាប់មក {0} នៅថ្ងៃទី២៥ រៀងរាល់ខែ ត្រូវបង់ត្រឹមថ្ងៃទី៥។",
  ],
  // new
  pv_deposit_walkin: [
    "Security Deposit: one month's Rent ({0}), entered after signing.",
    "ប្រាក់កក់សុវត្ថិភាព៖ ថ្លៃឈ្នួលមួយខែ ({0}) បញ្ចូលក្រោយចុះហត្ថលេខា។",
  ],
  // new
  pv_deposit_booking: [
    "Security Deposit: {0} received of {1} from the Booking; {2} still due by {3}.",
    "ប្រាក់កក់សុវត្ថិភាព៖ បានទទួល {0} នៃ {1} ពីការកក់ នៅត្រូវបង់ {2} ត្រឹម {3}។",
  ],
  // new
  booking_not_active: [
    "The Booking of {0} is no longer active, so a Lease cannot be made from it. Make a New Lease from the Leases page.",
    "ការកក់របស់ {0} លែងដំណើរការហើយ ដូច្នេះមិនអាចធ្វើកិច្ចសន្យាពីវាបានទេ។ សូមធ្វើកិច្ចសន្យាថ្មីពីទំព័រកិច្ចសន្យា។",
  ],
  // new
  err_renew_start: [
    "A renewal starts after the old End Date ({0}).",
    "ការបន្តចាប់ផ្តើមក្រោយថ្ងៃបញ្ចប់ចាស់ ({0})។",
  ],
  // new
  limit_reached: [
    "{0} is the most a Lease can have.",
    "{0} គឺច្រើនបំផុតដែលកិច្ចសន្យាអាចមាន។",
  ],
  // new
  pv_deposit_full: [
    "Security Deposit: {0} received in full from the Booking.",
    "ប្រាក់កក់សុវត្ថិភាព៖ បានទទួល {0} គ្រប់ចំនួនពីការកក់។",
  ],
  // new
  pv_renewal: [
    "Security Deposit: the old Lease's deposit does not move by itself.",
    "ប្រាក់កក់សុវត្ថិភាព៖ ប្រាក់កក់របស់កិច្ចសន្យាចាស់មិនផ្លាស់ទីដោយខ្លួនឯងទេ។",
  ],
  // new
  pv_pet: [
    "Pet Deposit as entered on the Lease.",
    "ប្រាក់កក់សត្វចិញ្ចឹមតាមដែលបញ្ចូលលើកិច្ចសន្យា។",
  ],
  pv_end: [
    "Nothing after {0} without a signed renewal.",
    "គ្មានអ្វីក្រោយ {0} ដោយគ្មានការបន្តដែលបានចុះហត្ថលេខា។",
  ],
  // new
  confirm_title: ["Save the draft · {0}?", "រក្សាទុកសេចក្តីព្រាង · {0}?"],
  // new
  confirm_note: [
    "Nothing is billed until the Lease is signed. The draft can still be changed or cancelled.",
    "គ្មានអ្វីចេញវិក្កយបត្ររហូតដល់កិច្ចសន្យាចុះហត្ថលេខា។ សេចក្តីព្រាងនៅតែអាចប្តូរ ឬលុបបាន។",
  ],
  // new
  draft_refused: [
    "The server refused the draft. Another Lease may already cover this Unit for these dates, or the details do not fit the rules. Nothing more was saved.",
    "ម៉ាស៊ីនមេបានបដិសេធសេចក្តីព្រាង។ កិច្ចសន្យាផ្សេងប្រហែលគ្របដណ្តប់បន្ទប់នេះសម្រាប់ថ្ងៃទាំងនេះរួចហើយ ឬព័ត៌មានមិនត្រូវតាមច្បាប់។ គ្មានអ្វីបន្ថែមត្រូវបានរក្សាទុកទេ។",
  ],
  // Terminate dialog (mock-up i18n3.js "tg_"; lines marked new are not in the mock-up)
  terminate: ["Terminate", "បញ្ចប់កិច្ចសន្យា"],
  tg_t: ["Terminate the Lease · {0}", "បញ្ចប់កិច្ចសន្យា · {0}"],
  tg_ground: ["Ground", "មូលដ្ឋាន"],
  tg_EARLY: ["Customer leaves early", "អតិថិជនចាកចេញមុនកំណត់"],
  tg_EARLY_s: [
    "Voluntary early termination at the Customer's request",
    "បញ្ចប់មុនកំណត់ដោយស្ម័គ្រចិត្ត តាមសំណើអតិថិជន",
  ],
  tg_VIOLATION: [
    "Lease violation after 3 written warnings",
    "បំពានកិច្ចសន្យា បន្ទាប់ពីព្រមាន 3 ដង",
  ],
  tg_VIOLATION_s: [
    "Includes pet-rule violations",
    "រួមទាំងការបំពានច្បាប់សត្វចិញ្ចឹម",
  ],
  // new
  tg_RENT: [
    "Rent unpaid after the day-30 notice",
    "ថ្លៃឈ្នួលមិនបង់ បន្ទាប់ពីលិខិតថ្ងៃទី៣០",
  ],
  // new
  tg_RENT_s: [
    "Needs the termination notice, the third letter, and its period to have ended",
    "ត្រូវមានការជូនដំណឹងបញ្ចប់ ជាលិខិតទីបី ហើយរយៈពេលរបស់វាបានផុត",
  ],
  tg_UNPAID: ["Initial Rent not paid", "ថ្លៃឈ្នួលដំបូងមិនបានបង់"],
  // new
  tg_UNPAID_s: [
    "The Initial Rent or the Security Deposit was not paid within 5 days",
    "ថ្លៃឈ្នួលដំបូង ឬប្រាក់កក់សុវត្ថិភាព មិនបានបង់ក្នុង 5 ថ្ងៃ",
  ],
  // new
  tg_UNPAID_wait: [
    "Possible from {0}, after the 5 days to pay",
    "អាចធ្វើបានពី {0} បន្ទាប់ពី 5 ថ្ងៃសម្រាប់បង់",
  ],
  // new
  tg_c1_unpaid: [
    "Whatever was received of the Security Deposit is kept and is not used for what the Customer owes.",
    "ប្រាក់កក់សុវត្ថិភាពដែលបានទទួល ត្រូវរក្សាទុក មិនប្រើសម្រាប់អ្វីដែលអតិថិជនជំពាក់។",
  ],
  // new
  tg_memo_e: ["Write the reason.", "សូមសរសេរមូលហេតុ។"],
  // new
  tg_ground_e: ["Choose the ground.", "សូមជ្រើសរើសមូលដ្ឋាន។"],
  tg_date: ["Termination date", "ថ្ងៃបញ្ចប់"],
  // new: the server records a termination on or after the day, never ahead.
  tg_date_help: [
    "The day the Lease ends, from {0} up to today. A later day goes in the termination notice.",
    "ថ្ងៃកិច្ចសន្យាបញ្ចប់ ពី {0} ដល់ថ្ងៃនេះ។ ថ្ងៃក្រោយត្រូវដាក់ក្នុងការជូនដំណឹងបញ្ចប់។",
  ],
  // new
  tg_bad: [
    "Enter a date from {0} up to today.",
    "បញ្ចូលថ្ងៃពី {0} ដល់ថ្ងៃនេះ។",
  ],
  tg_petrule: [
    "Pet-rule violation: keep the Pet Deposit too",
    "បំពានច្បាប់សត្វចិញ្ចឹម៖ រក្សាប្រាក់កក់សត្វចិញ្ចឹមដែរ",
  ],
  // new
  tg_warnings: ["Written warnings", "ការព្រមានជាលាយលក្ខណ៍អក្សរ"],
  // new
  tg_warning_line: ["Warning {0} · {1} · {2}", "ការព្រមាន {0} · {1} · {2}"],
  // new
  tg_warnings_e: [
    "Tick at least 3 written warnings.",
    "សូមធីកការព្រមានយ៉ាងហោចណាស់ 3។",
  ],
  // new
  tg_warnings_few: [
    "This Lease has {0} written warnings. A violation termination needs 3. Record them on the Letters page.",
    "កិច្ចសន្យានេះមានការព្រមាន {0}។ ការបញ្ចប់ដោយបំពានត្រូវការ 3។ សូមកត់ត្រានៅទំព័រលិខិត។",
  ],
  // new
  tg_notice: ["Termination notice", "ការជូនដំណឹងបញ្ចប់"],
  // new
  tg_notice_line: [
    "Given {0} · ends {1} · {2}",
    "ផ្តល់ {0} · បញ្ចប់ {1} · {2}",
  ],
  // new
  tg_notice_none: [
    "No termination notice yet. Record it first; the Lease can end when its period is over.",
    "មិនទាន់មានការជូនដំណឹងបញ្ចប់។ សូមកត់ត្រាវាជាមុន។ កិច្ចសន្យាអាចបញ្ចប់ពេលរយៈពេលរបស់វាផុត។",
  ],
  // new
  tg_notice_e: [
    "Choose the termination notice.",
    "សូមជ្រើសរើសការជូនដំណឹងបញ្ចប់។",
  ],
  // new
  tg_notice_wait: [
    "The notice period ends on {0}. Terminate on or after that day.",
    "រយៈពេលជូនដំណឹងបញ្ចប់នៅ {0}។ សូមបញ្ចប់នៅ ឬក្រោយថ្ងៃនោះ។",
  ],
  // new
  tg_evidence: ["Evidence", "ភស្តុតាង"],
  // new
  tg_evidence_help: [
    "For example the Customer's letter, the letter numbers or the payment record.",
    "ឧទាហរណ៍ លិខិតរបស់អតិថិជន លេខលិខិត ឬកំណត់ត្រាបង់ប្រាក់។",
  ],
  // new
  tg_evidence_e: ["Write the evidence.", "សូមសរសេរភស្តុតាង។"],
  tg_memo: ["Reason (written in the record)", "មូលហេតុ (សរសេរក្នុងកំណត់ត្រា)"],
  tg_c1: [
    "The Security Deposit is kept in full and is not used for what the Customer owes.",
    "ប្រាក់កក់សុវត្ថិភាពរក្សាទុកទាំងស្រុង មិនប្រើសម្រាប់អ្វីដែលអតិថិជនជំពាក់។",
  ],
  // new
  tg_c1_rent: [
    "The Security Deposit is kept in full when the day-30 notice is dated on or before the termination date.",
    "ប្រាក់កក់សុវត្ថិភាពរក្សាទុកទាំងស្រុង ពេលលិខិតថ្ងៃទី៣០ ចុះថ្ងៃនៅ ឬមុនថ្ងៃបញ្ចប់។",
  ],
  tg_c2: [
    "Rent for the termination month, Utilities and Services stay due. No later Rent is billed.",
    "ថ្លៃឈ្នួលខែបញ្ចប់ ទឹកភ្លើង និងសេវា នៅត្រូវបង់។ គ្មានថ្លៃឈ្នួលក្រោយទៀត។",
  ],
  tg_c3: [
    "The Pet Deposit pays pet damage first; the rest is refunded.",
    "ប្រាក់កក់សត្វចិញ្ចឹមបង់ខូចខាតដោយសត្វមុន; នៅសល់សងវិញ។",
  ],
  tg_pet_kept: [
    "The Pet Deposit is kept too (pet-rule termination).",
    "ប្រាក់កក់សត្វចិញ្ចឹមក៏រក្សាទុកដែរ (បញ្ចប់ព្រោះច្បាប់សត្វចិញ្ចឹម)។",
  ],
  tg_c4: [
    "The Unit stays Occupied until the hand-back is recorded.",
    "បន្ទប់នៅមានអ្នកជួល រហូតដល់កត់ត្រាការប្រគល់។",
  ],
  // new
  tg_c5: [
    "Never moved in: release the Unit and settle the Initial Rent Invoice in the next step.",
    "មិនដែលចូលស្នាក់នៅ៖ ដោះលែងបន្ទប់ និងដោះស្រាយវិក្កយបត្រថ្លៃឈ្នួលដំបូង នៅជំហានបន្ទាប់។",
  ],
  // new
  tg_final: [
    "This cannot be undone. A terminated Lease is never signed again.",
    "មិនអាចត្រឡប់វិញបានទេ។ កិច្ចសន្យាដែលបានបញ្ចប់ មិនអាចចុះហត្ថលេខាម្តងទៀតទេ។",
  ],
  tg_ok: ["Terminate", "បញ្ចប់"],
  tg_toast: [
    "Lease of {0} terminated as of {1}.",
    "កិច្ចសន្យា {0} បានបញ្ចប់ត្រឹម {1}។",
  ],
  // new
  tg_refused: [
    "The server refused the termination. The ground, the date, the warnings or the notice do not fit the rules, or the unpaid amount was paid meanwhile. Nothing was saved.",
    "ម៉ាស៊ីនមេបានបដិសេធការបញ្ចប់។ មូលដ្ឋាន ថ្ងៃ ការព្រមាន ឬការជូនដំណឹង មិនត្រូវតាមច្បាប់ ឬចំនួនមិនទាន់បង់ត្រូវបានបង់រួចហើយ។ គ្មានអ្វីត្រូវបានរក្សាទុកទេ។",
  ],
  // new
  tg_load_failed: [
    "The warnings or notices of this Lease could not be read just now.",
    "មិនអាចអានការព្រមាន ឬការជូនដំណឹងនៃកិច្ចសន្យានេះបានទេឥឡូវនេះ។",
  ],
  // new: Record termination notice
  nt_new: ["Record termination notice", "កត់ត្រាការជូនដំណឹងបញ្ចប់"],
  nt_t: ["Termination notice · {0}", "ការជូនដំណឹងបញ្ចប់ · {0}"],
  nt_note: [
    "The third letter after the day-20 and day-30 letters (DL-073). Recording it does not end the Lease; Terminate does, once its period is over.",
    "លិខិតទីបី បន្ទាប់ពីលិខិតថ្ងៃទី២០ និងថ្ងៃទី៣០។ ការកត់ត្រាវាមិនបញ្ចប់កិច្ចសន្យាទេ។ ប៊ូតុងបញ្ចប់ធ្វើវា ពេលរយៈពេលរបស់វាផុត។",
  ],
  nt_date: ["Date given", "ថ្ងៃផ្តល់"],
  nt_ends: ["Lease ends on", "កិច្ចសន្យាបញ្ចប់នៅ"],
  nt_ends_help: [
    "The standard Lease gives 30 days' landlord notice.",
    "កិច្ចសន្យាស្តង់ដារ ផ្តល់ការជូនដំណឹងពីម្ចាស់ 30 ថ្ងៃ។",
  ],
  nt_dates_e: [
    "The date given must be today or earlier, and the end on or after it.",
    "ថ្ងៃផ្តល់ត្រូវជាថ្ងៃនេះ ឬមុន ហើយថ្ងៃបញ្ចប់នៅ ឬក្រោយវា។",
  ],
  nt_number: ["Letter number", "លេខលិខិត"],
  nt_number_e: ["Write the letter number.", "សូមសរសេរលេខលិខិត។"],
  nt_text: ["What the letter says", "ខ្លឹមសារលិខិត"],
  nt_text_e: ["Write what the letter says.", "សូមសរសេរខ្លឹមសារលិខិត។"],
  nt_text_default: [
    "The Lease of {0} ends on {1} because the Rent is still unpaid after the day-20 warning letter and the day-30 default notice.",
    "កិច្ចសន្យា {0} បញ្ចប់នៅ {1} ព្រោះថ្លៃឈ្នួលនៅមិនទាន់បង់ បន្ទាប់ពីលិខិតព្រមានថ្ងៃទី២០ និងលិខិតថ្ងៃទី៣០។",
  ],
  nt_how_e: ["Choose how it was given.", "សូមជ្រើសរើសរបៀបផ្តល់។"],
  nt_details: ["Details", "ព័ត៌មានលម្អិត"],
  nt_details_e: ["Write the details.", "សូមសរសេរព័ត៌មានលម្អិត។"],
  nt_toast: [
    "Termination notice recorded for {0}.",
    "បានកត់ត្រាការជូនដំណឹងបញ្ចប់សម្រាប់ {0}។",
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
