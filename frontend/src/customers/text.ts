// V1-058 R2: the words of the Customers screens in English and Khmer, from the owner's
// mock-up (i18n). Khmer needs the native check before the app is used. Lines marked "new"
// are not in the mock-up.

import type { Language } from "../signInText";

const TEXT = {
  sub: [
    "{0} people with a Lease, a Reservation or a history here",
    "មនុស្ស {0} នាក់ដែលមានកិច្ចសន្យា ការកក់ ឬប្រវត្តិនៅទីនេះ",
  ],
  add: ["Add Customer", "បន្ថែមអតិថិជន"],
  search: [
    "Search by name, phone, Parking or ID number",
    "ស្វែងរកតាមឈ្មោះ ទូរស័ព្ទ ចំណត ឬលេខអត្តសញ្ញាណ",
  ],
  search_button: ["Search", "ស្វែងរក"],
  // new
  clear_search: ["Clear search", "សម្អាតការស្វែងរក"],
  loading: ["Loading the Customers…", "កំពុងផ្ទុកអតិថិជន…"],
  // new
  failed: [
    "The Customers could not be read. Retry when the service is available.",
    "មិនអាចអានអតិថិជនបានទេ។ សូមព្យាយាមម្តងទៀតពេលសេវាអាចប្រើបាន។",
  ],
  // new
  search_failed: [
    "The search could not run. The list still filters by name, phone and Parking.",
    "មិនអាចស្វែងរកបានទេ។ បញ្ជីនៅតែត្រងតាមឈ្មោះ ទូរស័ព្ទ និងចំណត។",
  ],
  // new
  retry: ["Retry", "ព្យាយាមម្តងទៀត"],
  // new
  no_property: [
    "The Property is not known yet, so the Customers cannot be shown.",
    "មិនទាន់ស្គាល់អគារ ដូច្នេះមិនអាចបង្ហាញអតិថិជនបានទេ។",
  ],
  // new
  tenants_hidden: [
    "Your account cannot read Leases or Reservations, so Parking and Relationship show “—”.",
    "គណនីរបស់អ្នកមិនអាចអានកិច្ចសន្យា ឬការកក់បានទេ ដូច្នេះចំណត និងទំនាក់ទំនង បង្ហាញ “—”។",
  ],
  c_tenant: ["Current tenants", "អ្នកជួលបច្ចុប្បន្ន"],
  c_tenant_s: [
    "Primary Tenant on a signed Lease",
    "អ្នកជួលចម្បងលើកិច្ចសន្យាបានចុះហត្ថលេខា",
  ],
  c_other: ["Signers and occupants", "អ្នកចុះហត្ថលេខា និងអ្នករស់នៅ"],
  c_other_s: [
    "On a Lease, not the Primary Tenant",
    "នៅលើកិច្ចសន្យា មិនមែនអ្នកជួលចម្បង",
  ],
  c_res: ["Reservations", "ការកក់"],
  c_res_s: [
    "Holding a Parking, Lease not signed yet",
    "កំពុងកក់ចំណត មិនទាន់ចុះហត្ថលេខាកិច្ចសន្យា",
  ],
  c_former: ["Former", "ពីមុន"],
  c_former_s: [
    "No current Lease or Reservation",
    "គ្មានកិច្ចសន្យា ឬការកក់បច្ចុប្បន្ន",
  ],
  showing: ["Showing: {0}.", "កំពុងបង្ហាញ៖ {0}។"],
  show_all: ["Show all", "បង្ហាញទាំងអស់"],
  name: ["Legal name", "ឈ្មោះតាមច្បាប់"],
  phone: ["Phone", "ទូរស័ព្ទ"],
  unit: ["Parking", "ចំណត"],
  relationship: ["Relationship", "ទំនាក់ទំនង"],
  not_saved: ["Not saved", "មិនបានរក្សាទុក"],
  n1: ["1 Customer", "អតិថិជន 1"],
  n: ["{0} Customers", "អតិថិជន {0}"],
  none: ["No Customers match.", "គ្មានអតិថិជនត្រូវនឹងការស្វែងរកទេ។"],
  // new
  money_later: [
    "Unpaid and Customer Credit for each Customer show on the Customer page. The list columns come with Invoices and Payments (step R5).",
    "មិនទាន់បង់ និងឥណទានអតិថិជន បង្ហាញនៅទំព័រអតិថិជន។ ជួរឈរក្នុងបញ្ជីនឹងមកជាមួយវិក្កយបត្រ និងការបង់ប្រាក់ (ជំហាន R5)។",
  ],
  k_none: ["No Lease yet", "មិនទាន់មានកិច្ចសន្យា"],
  k_tenant: ["Tenant", "អ្នកជួល"],
  k_other: ["Signer or occupant", "អ្នកចុះហត្ថលេខា ឬអ្នករស់នៅ"],
  k_res: ["Reservation", "ការកក់"],
  k_former: ["Former", "ពីមុន"],
  // new
  deactivated: ["Deactivated", "បានបិទ"],
  back: ["Back", "ត្រឡប់ក្រោយ"],
  // new
  missing: [
    "This Customer was not found, or your account cannot open it.",
    "រកមិនឃើញអតិថិជននេះ ឬគណនីរបស់អ្នកមិនអាចបើកវាបានទេ។",
  ],
  role_primary: ["Primary Tenant", "អ្នកជួលចម្បង"],
  role_signer: ["Lease Signer", "អ្នកចុះហត្ថលេខាកិច្ចសន្យា"],
  role_occupant: ["Occupant", "អ្នករស់នៅ"],
  role_res: ["Reservation Customer", "អតិថិជនកក់"],
  role_former: ["Former tenant", "អ្នកជួលពីមុន"],
  no_rels: ["No Lease or Reservation yet.", "មិនទាន់មានកិច្ចសន្យា ឬការកក់។"],
  edit: ["Edit contact", "កែទំនាក់ទំនង"],
  contact: ["Contact and identity", "ទំនាក់ទំនង និងអត្តសញ្ញាណ"],
  contact_note: [
    "Changing contact details never changes past Invoices, Receipts or Leases.",
    "ការកែទំនាក់ទំនងមិនប្តូរវិក្កយបត្រ បង្កាន់ដៃ ឬកិច្ចសន្យាពីមុនទេ។",
  ],
  email: ["Email", "អ៊ីមែល"],
  address: ["Address", "អាសយដ្ឋាន"],
  dob: ["Date of birth", "ថ្ងៃខែឆ្នាំកំណើត"],
  gender: ["Gender", "ភេទ"],
  g_FEMALE: ["Female", "ស្រី"],
  g_MALE: ["Male", "ប្រុស"],
  nationality: ["Nationality", "សញ្ជាតិ"],
  idno: ["ID number / Passport number", "លេខអត្តសញ្ញាណ / លេខលិខិតឆ្លងដែន"],
  memo: ["Memo", "កំណត់ចំណាំ"],
  rels: ["Leases and Reservations", "កិច្ចសន្យា និងការកក់"],
  rels_note: [
    "One person, one record. Tenant, Signer, Occupant and Reservation Customer are relationships, not types of Customer.",
    "មនុស្សម្នាក់ កំណត់ត្រាមួយ។ អ្នកជួល អ្នកចុះហត្ថលេខា អ្នករស់នៅ និងអតិថិជនកក់ គឺជាទំនាក់ទំនង មិនមែនប្រភេទអតិថិជនទេ។",
  ],
  // new
  rels_unknown: [
    "Your account cannot read Leases or Reservations.",
    "គណនីរបស់អ្នកមិនអាចអានកិច្ចសន្យា ឬការកក់បានទេ។",
  ],
  reserved_until: ["Reserved until {0}", "កក់រហូតដល់ {0}"],
  lk_current: ["Lease active", "កិច្ចសន្យាកំពុងអនុវត្ត"],
  lk_draft: ["Draft", "សេចក្តីព្រាង"],
  lk_ended: ["Ended", "បានបញ្ចប់"],
  lk_terminated: ["Terminated", "បានបញ្ចប់មុនកំណត់"],
  lk_cancelled: ["Cancelled", "បានលុបចោល"],
  rs_active: ["Active", "កំពុងដំណើរការ"],
  money: ["Money", "ប្រាក់"],
  unpaid: ["Unpaid", "មិនទាន់បង់"],
  credit: ["Customer Credit", "ឥណទានអតិថិជន"],
  credit_note: [
    "Used on the next Invoices, with the Customer's agreement.",
    "ប្រើលើវិក្កយបត្របន្ទាប់ ដោយមានការយល់ព្រមពីអតិថិជន។",
  ],
  security: ["Security Deposit", "ប្រាក់កក់សុវត្ថិភាព"],
  dep_note: [
    "Held for the Lease. Never used to pay ordinary Invoices.",
    "រក្សាសម្រាប់កិច្ចសន្យា។ មិនដែលប្រើបង់វិក្កយបត្រធម្មតាទេ។",
  ],
  pet: ["Pet Deposit", "ប្រាក់កក់សត្វចិញ្ចឹម"],
  pet_note: [
    "Tracked separately from the Security Deposit.",
    "តាមដានដោយឡែកពីប្រាក់កក់សុវត្ថិភាព។",
  ],
  // new
  money_unknown: [
    "Your account cannot read this Customer's money.",
    "គណនីរបស់អ្នកមិនអាចអានប្រាក់របស់អតិថិជននេះបានទេ។",
  ],
  ledger: ["Customer Account Ledger", "បញ្ជីគណនីអតិថិជន"],
  readonly: ["Read only", "អានប៉ុណ្ណោះ"],
  // new
  open_ledger: ["Open the Account Ledger", "បើកបញ្ជីគណនី"],
  ledger_note: [
    "Every line comes from an Invoice or a Receipt. Nothing is edited here. Deposits and Credit are held separately and are not part of Owed.",
    "គ្រប់បន្ទាត់មកពីវិក្កយបត្រ ឬបង្កាន់ដៃ។ គ្មានការកែនៅទីនេះទេ។ ប្រាក់កក់ និងឥណទានត្រូវបានរក្សាដោយឡែក និងមិនរាប់ក្នុងប្រាក់ជំពាក់។",
  ],
  open_invoices: ["Unpaid Invoices", "វិក្កយបត្រមិនទាន់បង់"],
  receipts: ["Latest Receipts", "បង្កាន់ដៃចុងក្រោយ"],
  // new
  invoices_later: [
    "Each unpaid Invoice and the latest Receipts show here when Invoices and Payments are rebuilt (step R5).",
    "វិក្កយបត្រមិនទាន់បង់នីមួយៗ និងបង្កាន់ដៃចុងក្រោយនឹងបង្ហាញនៅទីនេះ ពេលរៀបចំវិក្កយបត្រ និងការបង់ប្រាក់ឡើងវិញ (ជំហាន R5)។",
  ],
  history: ["History", "ប្រវត្តិ"],
  // new
  history_none: ["No history yet.", "មិនទាន់មានប្រវត្តិ។"],
  // new
  h_created: ["Customer added.", "បានបន្ថែមអតិថិជន។"],
  // new
  h_updated: ["Contact details changed.", "បានកែទំនាក់ទំនង។"],
  // new
  h_deactivated: ["Customer deactivated: {0}", "បានបិទអតិថិជន៖ {0}"],
  // new
  h_other: ["{0}", "{0}"],
  // V1-058 R2 step C2: Add Customer, Edit contact, Deactivate.
  add_sub: [
    "One person, one record. Check the list first so the same person is not added twice.",
    "មនុស្សម្នាក់ កំណត់ត្រាមួយ។ សូមពិនិត្យបញ្ជីជាមុនសិន ដើម្បីកុំឱ្យបន្ថែមមនុស្សដដែលពីរដង។",
  ],
  required: ["required", "ត្រូវតែបំពេញ"],
  name_full: [
    "Legal name (last name, middle name, first name)",
    "ឈ្មោះតាមច្បាប់ (នាមត្រកូល នាមកណ្តាល នាមខ្លួន)",
  ],
  not_recorded: ["Not recorded", "មិនបានកត់ត្រា"],
  nationality_ph: ["Cambodian", "ខ្មែរ"],
  e_name: ["Enter the legal name.", "សូមបញ្ចូលឈ្មោះតាមច្បាប់។"],
  e_id: [
    "Enter the ID number or passport number.",
    "សូមបញ្ចូលលេខអត្តសញ្ញាណ ឬលេខលិខិតឆ្លងដែន។",
  ],
  e_phone: [
    "Use digits, spaces and + ( ) . - only.",
    "សូមប្រើតែលេខ ដកឃ្លា និង + ( ) . - ប៉ុណ្ណោះ។",
  ],
  e_email: [
    "Enter an email like name@example.com.",
    "សូមបញ្ចូលអ៊ីមែលដូចជា name@example.com។",
  ],
  e_dob: ["Pick a date.", "សូមជ្រើសរើសកាលបរិច្ឆេទ។"],
  e_id_taken: [
    "Another Customer already has this ID number or passport number.",
    "អតិថិជនម្នាក់ទៀតមានលេខអត្តសញ្ញាណ ឬលេខលិខិតឆ្លងដែននេះរួចហើយ។",
  ],
  id_taken_open: [
    "Use the existing Customer instead:",
    "សូមប្រើអតិថិជនដែលមានស្រាប់ជំនួសវិញ៖",
  ],
  maybe_same: [
    "A Customer with the same name or phone number already exists. Open that record if it is the same person:",
    "មានអតិថិជនដែលមានឈ្មោះ ឬលេខទូរស័ព្ទដូចគ្នារួចហើយ។ សូមបើកកំណត់ត្រានោះ ប្រសិនបើជាមនុស្សដដែល៖",
  ],
  distinct: [
    "This is a different person; save anyway",
    "នេះជាមនុស្សផ្សេង សូមរក្សាទុក",
  ],
  tick_distinct: [
    "Tick “This is a different person” or open the existing Customer.",
    "សូមធីក “នេះជាមនុស្សផ្សេង” ឬបើកអតិថិជនដែលមានស្រាប់។",
  ],
  blocked: [
    "Nothing was sent. Another Customer save is still waiting to be checked, or this browser cannot keep Customer saves safe. See “Earlier Customer form” below.",
    "មិនបានផ្ញើអ្វីទេ។ ការរក្សាទុកអតិថិជនមួយទៀតកំពុងរង់ចាំការពិនិត្យ ឬកម្មវិធីរុករកនេះមិនអាចរក្សាសុវត្ថិភាពការរក្សាទុកបានទេ។ សូមមើល “ទម្រង់អតិថិជនពីមុន” ខាងក្រោម។",
  ],
  unknown: [
    "We could not tell whether this was saved. “Try again” sends the very same save; it is never saved twice.",
    "យើងមិនអាចដឹងថាវាត្រូវបានរក្សាទុកឬអត់ទេ។ “ព្យាយាមម្តងទៀត” ផ្ញើការរក្សាទុកដដែល វាមិនត្រូវបានរក្សាទុកពីរដងទេ។",
  ],
  refused: [
    "The Customer was not saved. Check the details and try again.",
    "មិនបានរក្សាទុកអតិថិជនទេ។ សូមពិនិត្យព័ត៌មាន ហើយព្យាយាមម្តងទៀត។",
  ],
  cancel: ["Cancel", "បោះបង់"],
  saving: ["Saving…", "កំពុងរក្សាទុក…"],
  try_again: ["Try again", "ព្យាយាមម្តងទៀត"],
  save_customer: ["Save Customer", "រក្សាទុកអតិថិជន"],
  save: ["Save", "រក្សាទុក"],
  edit_title: ["Edit contact · {0}", "កែទំនាក់ទំនង · {0}"],
  nothing_changed: ["Nothing was changed.", "គ្មានអ្វីត្រូវបានកែទេ។"],
  deactivate: ["Deactivate", "បិទ"],
  deactivate_title: ["Deactivate · {0}", "បិទ · {0}"],
  deactivate_note: [
    "The Customer stays in the records with every Lease, Invoice and Receipt; nothing is deleted. A deactivated Customer cannot be changed again.",
    "អតិថិជននៅតែមានក្នុងកំណត់ត្រា ជាមួយកិច្ចសន្យា វិក្កយបត្រ និងបង្កាន់ដៃទាំងអស់ គ្មានអ្វីត្រូវលុបទេ។ អតិថិជនដែលបានបិទ មិនអាចកែម្តងទៀតបានទេ។",
  ],
  reason: ["Reason", "មូលហេតុ"],
  e_reason: ["Enter the reason.", "សូមបញ្ចូលមូលហេតុ។"],
  saved_new: ["{0} was added.", "បានបន្ថែម {0}។"],
  saved_edit: [
    "The contact details of {0} were saved.",
    "បានរក្សាទុកទំនាក់ទំនងរបស់ {0}។",
  ],
  saved_deactivated: ["{0} was deactivated.", "បានបិទ {0}។"],
  conflict: [
    "Someone else changed this Customer first. The page now shows the newest details; make your change again.",
    "មានអ្នកផ្សេងបានកែអតិថិជននេះមុន។ ទំព័រនេះបង្ហាញព័ត៌មានថ្មីបំផុតហើយ សូមកែម្តងទៀត។",
  ],
  waiting_check: [
    "A Customer save is waiting to be checked. Check it in the “Earlier Customer form” below before saving another.",
    "ការរក្សាទុកអតិថិជនមួយកំពុងរង់ចាំការពិនិត្យ។ សូមពិនិត្យវានៅ “ទម្រង់អតិថិជនពីមុន” ខាងក្រោម មុនពេលរក្សាទុកមួយទៀត។",
  ],
  // new
  records: ["Earlier Customer form", "ទម្រង់អតិថិជនពីមុន"],
  // new
  records_note: [
    "The earlier Customer form, in English. Use it to check a save whose result was not known, and for the full Account Ledger.",
    "ទម្រង់អតិថិជនពីមុន ជាភាសាអង់គ្លេស។ ប្រើវាដើម្បីពិនិត្យការរក្សាទុកដែលមិនដឹងលទ្ធផល និងសម្រាប់បញ្ជីគណនីពេញលេញ។",
  ],
  records_open: ["Show the earlier form", "បង្ហាញទម្រង់ពីមុន"],
  // Parking Step 4 (owner 2026-10-30): vehicles under a Customer. Khmer needs the owner's check.
  vehicles: ["Vehicles", "យានយន្ត"],
  add_vehicle: ["Add vehicle", "បន្ថែមយានយន្ត"],
  v_edit: ["Edit", "កែ"],
  v_none: ["No vehicle yet.", "មិនទាន់មានយានយន្តទេ។"],
  v_failed: ["The vehicles could not be read.", "មិនអាចអានយានយន្តបានទេ។"],
  v_type: ["Type", "ប្រភេទ"],
  v_plate: ["Plate", "ផ្លាកលេខ"],
  v_add_title: ["Add vehicle · {0}", "បន្ថែមយានយន្ត · {0}"],
  v_edit_title: ["Edit vehicle · {0}", "កែយានយន្ត · {0}"],
  v_plate_req: ["Type the plate.", "សូមវាយផ្លាកលេខ។"],
  v_dup: [
    "Another vehicle has this plate: {0}.",
    "យានយន្តមួយទៀតមានផ្លាកលេខនេះ៖ {0}។",
  ],
  v_save_anyway: ["Save anyway", "រក្សាទុកទោះយ៉ាងណា"],
  v_added: ["Vehicle {0} was added.", "យានយន្ត {0} ត្រូវបានបន្ថែម។"],
  v_saved: ["Vehicle {0} was saved.", "យានយន្ត {0} ត្រូវបានរក្សាទុក។"],
  v_note: [
    "Type and plate as typed, Khmer or Latin. Photos and documents come later.",
    "ប្រភេទ និងផ្លាកលេខដូចដែលបានវាយ ខ្មែរ ឬឡាតាំង។ រូបថត និងឯកសារនឹងមកពេលក្រោយ។",
  ],
  v_refused: [
    "The vehicle was not saved. Check the details and try again.",
    "យានយន្តមិនត្រូវបានរក្សាទុកទេ។ សូមពិនិត្យព័ត៌មាន រួចព្យាយាមម្តងទៀត។",
  ],
  vt_CAR: ["Car", "រថយន្ត"],
  vt_MOTORBIKE: ["Motorbike", "ម៉ូតូ"],
  vt_TUK_TUK: ["Tuk-tuk", "តុកតុក"],
  vt_FOOD_CART: ["Food cart", "រទេះលក់ម្ហូប"],
} as const;

export type CustomerTextKey = keyof typeof TEXT;

/** Parking Step 4: the vehicle type in the screen's words. */
export function vehicleTypeText(
  language: Language,
  vehicleType: "CAR" | "MOTORBIKE" | "TUK_TUK" | "FOOD_CART",
): string {
  return ct(language, `vt_${vehicleType}`);
}

/** The text in the chosen language, with {0}, {1} filled in. */
export function ct(
  language: Language,
  key: CustomerTextKey,
  ...values: (string | number)[]
): string {
  return TEXT[key][language === "en" ? 0 : 1].replace(/\{(\d)\}/g, (_, n) =>
    String(values[Number(n)] ?? ""),
  );
}
