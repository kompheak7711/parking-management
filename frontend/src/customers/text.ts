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
    "Search by name, phone, Unit or ID number",
    "ស្វែងរកតាមឈ្មោះ ទូរស័ព្ទ បន្ទប់ ឬលេខអត្តសញ្ញាណ",
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
    "The search could not run. The list still filters by name, phone and Unit.",
    "មិនអាចស្វែងរកបានទេ។ បញ្ជីនៅតែត្រងតាមឈ្មោះ ទូរស័ព្ទ និងបន្ទប់។",
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
    "Your account cannot read Leases or Reservations, so Unit and Relationship show “—”.",
    "គណនីរបស់អ្នកមិនអាចអានកិច្ចសន្យា ឬការកក់បានទេ ដូច្នេះបន្ទប់ និងទំនាក់ទំនង បង្ហាញ “—”។",
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
    "Holding a Unit, Lease not signed yet",
    "កំពុងកក់បន្ទប់ មិនទាន់ចុះហត្ថលេខាកិច្ចសន្យា",
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
  unit: ["Unit", "បន្ទប់"],
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
  // new
  records: ["Add or change Customers", "បន្ថែម ឬកែអតិថិជន"],
  // new
  records_note: [
    "Adding a Customer, Edit contact and deactivating still use the earlier form below. They move into dialogs in the next step (C2).",
    "ការបន្ថែមអតិថិជន ការកែទំនាក់ទំនង និងការបិទ នៅតែប្រើទម្រង់ពីមុនខាងក្រោម។ ពួកវានឹងផ្លាស់ទៅប្រអប់ក្នុងជំហានបន្ទាប់ (C2)។",
  ],
} as const;

export type CustomerTextKey = keyof typeof TEXT;

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
