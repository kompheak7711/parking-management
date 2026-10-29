// V1-058 R2: the words of the Units screens in English and Khmer, from the owner's mock-up
// (i18n). Khmer needs the native check before the app is used. Lines marked "new" are not in
// the mock-up.

import type { Language } from "../signInText";

const TEXT = {
  sub: ["{0} Parking at CHETANA Parking", "ចំណត {0} នៅ CHETANA Parking"],
  loading: ["Loading Parking…", "កំពុងផ្ទុកចំណត…"],
  // new
  failed: [
    "The Parking could not be read. Retry when the service is available.",
    "មិនអាចអានចំណតបានទេ។ សូមព្យាយាមម្តងទៀតពេលសេវាអាចប្រើបាន។",
  ],
  // new
  retry: ["Retry", "ព្យាយាមម្តងទៀត"],
  // new
  no_property: [
    "The Property is not known yet, so the Parking cannot be shown.",
    "មិនទាន់ស្គាល់អគារ ដូច្នេះមិនអាចបង្ហាញចំណតបានទេ។",
  ],
  // new
  lists_failed: [
    "The Settings lists could not be read, so Parking cannot be added or changed now.",
    "មិនអាចអានបញ្ជីការកំណត់បានទេ ដូច្នេះមិនអាចបន្ថែម ឬកែចំណតបានឥឡូវនេះ។",
  ],
  // new
  tenants_hidden: [
    "Your account cannot read Leases or Reservations, so Until shows “—”.",
    "គណនីរបស់អ្នកមិនអាចអានកិច្ចសន្យា ឬការកក់បានទេ ដូច្នេះរហូតដល់ បង្ហាញ “—”។",
  ],
  new_unit: ["New Parking", "ចំណតថ្មី"],
  all_floors: ["All floors", "គ្រប់ជាន់"],
  all_types: ["All types", "គ្រប់ប្រភេទ"],
  floor: ["Floor", "ជាន់"],
  floor_n: ["Floor {0}", "ជាន់ទី {0}"],
  type: ["Parking Type", "ប្រភេទចំណត"],
  c_occupied: ["Occupied", "មានអ្នកជួល"],
  c_occupied_s: ["A signed Lease is running", "មានកិច្ចសន្យាបានចុះហត្ថលេខា"],
  c_reserved: ["Reserved", "បានកក់"],
  c_reserved_s: [
    "An active Reservation holds the Parking",
    "ការកក់កំពុងរក្សាចំណត",
  ],
  c_vacant: ["Vacant", "ទំនេរ"],
  c_vacant_s: ["Ready to reserve or lease", "រួចរាល់សម្រាប់កក់ ឬជួល"],
  c_na: ["Not available", "មិនអាចប្រើបាន"],
  c_na_s: [
    "Cleaning, maintenance or out of service",
    "កំពុងសម្អាត ជួសជុល ឬឈប់ប្រើ",
  ],
  showing: ["Showing: {0}.", "កំពុងបង្ហាញ៖ {0}។"],
  show_all: ["Show all", "បង្ហាញទាំងអស់"],
  col_unit: ["Parking", "ចំណត"],
  col_status: ["Status", "ស្ថានភាព"],
  rent: ["Monthly Rent", "ថ្លៃឈ្នួលប្រចាំខែ"],
  until: ["Until", "រហូតដល់"],
  reserved_until: ["Reserved until", "កក់រហូតដល់"],
  n1: ["1 Parking", "ចំណត 1"],
  n: ["{0} Parking", "ចំណត {0}"],
  none: ["No Parking matches these filters.", "គ្មានចំណតត្រូវនឹងតម្រងនេះទេ។"],
  s_VACANT: ["Vacant", "ទំនេរ"],
  s_RESERVED: ["Reserved", "បានកក់"],
  s_OCCUPIED: ["Occupied", "មានអ្នកជួល"],
  s_CLEANING: ["Cleaning", "កំពុងសម្អាត"],
  s_UNDER_MAINTENANCE: ["Under maintenance", "កំពុងជួសជុល"],
  s_OUT_OF_SERVICE: ["Out of service", "ឈប់ប្រើ"],
  back: ["Back", "ត្រឡប់ក្រោយ"],
  // new
  unit_missing: [
    "This Parking was not found. Go back to the Parking list.",
    "រកមិនឃើញចំណតនេះទេ។ ត្រឡប់ទៅបញ្ជីចំណត។",
  ],
  make_reservation: ["Make Reservation", "ធ្វើការកក់"],
  new_lease: ["New Lease", "កិច្ចសន្យាថ្មី"],
  new_lease_from_res: ["New Lease from Reservation", "កិច្ចសន្យាថ្មីពីការកក់"],
  open_lease: ["Open Lease", "បើកកិច្ចសន្យា"],
  open_draft: ["Open draft Lease", "បើកសេចក្តីព្រាងកិច្ចសន្យា"],
  open_reservation: ["Open Reservation", "បើកការកក់"],
  change_status: ["Change status", "ប្តូរស្ថានភាព"],
  update_unit: ["Update Parking", "ធ្វើបច្ចុប្បន្នភាពចំណត"],
  details: ["Parking details", "ព័ត៌មានលម្អិតចំណត"],
  no_photo: ["No photo of this Parking yet.", "មិនទាន់មានរូបថតចំណតនេះទេ។"],
  // new
  photo_later: [
    "Adding a photo comes with the file storage step.",
    "ការបន្ថែមរូបថតនឹងមកជាមួយជំហានរក្សាទុកឯកសារ។",
  ],
  size: ["Size", "ទំហំ"],
  m2: ["{0} m²", "{0} ម²"],
  beds: ["Bedrooms", "បន្ទប់គេង"],
  baths: ["Bathrooms", "បន្ទប់ទឹក"],
  view: ["View", "ទេសភាព"],
  kitchen: ["Kitchen", "ផ្ទះបាយ"],
  features: ["Room features", "លក្ខណៈចំណត"],
  has: ["Yes", "មាន"],
  hasnt: ["No", "គ្មាន"],
  // new
  not_recorded: ["Not recorded", "មិនទាន់កត់ត្រា"],
  notes: ["Notes", "កំណត់ចំណាំ"],
  current_lease: ["Current Lease", "កិច្ចសន្យាបច្ចុប្បន្ន"],
  primary: ["Primary Tenant", "អ្នកជួលចម្បង"],
  period: ["Period", "រយៈពេល"],
  signers: ["Signers", "អ្នកចុះហត្ថលេខា"],
  occupants: ["Occupants", "អ្នករស់នៅ"],
  no_movein: ["Not moved in yet", "មិនទាន់ចូលស្នាក់នៅ"],
  reservation: ["Reservation", "ការកក់"],
  customer: ["Customer", "អតិថិជន"],
  reserved_on: ["Reserved on", "កក់នៅថ្ងៃ"],
  expires: ["Expires", "ផុតកំណត់"],
  agreed_rent: ["Agreed Rent", "ថ្លៃឈ្នួលបានព្រមព្រៀង"],
  deposit_received: ["Deposit received", "ប្រាក់កក់បានទទួល"],
  availability: ["Availability", "ភាពទំនេរ"],
  a_VACANT: [
    "This Parking is vacant. It can be reserved, or a Lease can be drafted for a walk-in Customer.",
    "ចំណតនេះទំនេរ។ អាចកក់ ឬព្រាងកិច្ចសន្យាសម្រាប់អតិថិជនដែលមកផ្ទាល់។",
  ],
  a_CLEANING: [
    "Being cleaned after a move-out. It becomes Vacant when it is ready. A walk-in Lease can still be signed.",
    "កំពុងសម្អាតបន្ទាប់ពីការចាកចេញ។ នឹងក្លាយជាទំនេរនៅពេលរួចរាល់។ នៅតែអាចចុះហត្ថលេខាកិច្ចសន្យាបាន។",
  ],
  a_UNDER_MAINTENANCE: [
    "Under maintenance. It cannot be reserved. A Manager restores it when the work is done.",
    "កំពុងជួសជុល។ មិនអាចកក់បានទេ។ អ្នកគ្រប់គ្រងដាក់ឱ្យប្រើវិញពេលការងាររួចរាល់។",
  ],
  a_OUT_OF_SERVICE: [
    "Out of service. It cannot be reserved or leased until a Manager restores it.",
    "ឈប់ប្រើ។ មិនអាចកក់ ឬជួលបានទេ រហូតដល់អ្នកគ្រប់គ្រងដាក់ឱ្យប្រើវិញ។",
  ],
  // new
  a_unknown: [
    "Your account cannot read Leases or Reservations for this Parking.",
    "គណនីរបស់អ្នកមិនអាចអានកិច្ចសន្យា ឬការកក់សម្រាប់ចំណតនេះបានទេ។",
  ],
  past_leases: ["Lease history", "ប្រវត្តិកិច្ចសន្យា"],
  no_past: ["No earlier Leases.", "គ្មានកិច្ចសន្យាពីមុន។"],
  start: ["Start Date", "ថ្ងៃចាប់ផ្តើម"],
  end: ["End Date", "ថ្ងៃបញ្ចប់"],
  invoices: ["Invoices for this Parking", "វិក្កយបត្រសម្រាប់ចំណតនេះ"],
  // new
  invoices_later: [
    "Unpaid Invoices for this Parking show here when Invoices are rebuilt (step R5).",
    "វិក្កយបត្រមិនទាន់បង់សម្រាប់ចំណតនេះនឹងបង្ហាញនៅទីនេះ ពេលរៀបចំវិក្កយបត្រឡើងវិញ (ជំហាន R5)។",
  ],
  history: ["History", "ប្រវត្តិ"],
  // new
  history_none: ["No history yet.", "មិនទាន់មានប្រវត្តិ។"],
  // new
  h_created: ["Parking created.", "បានបង្កើតចំណត។"],
  // new
  h_updated: ["Parking details updated.", "បានធ្វើបច្ចុប្បន្នភាពព័ត៌មានចំណត។"],
  // new
  h_status: ["Status changed to {0}: {1}", "ស្ថានភាពបានប្តូរទៅ {0}៖ {1}"],
  // new
  h_inventory: ["Parking inventory updated.", "បានធ្វើបច្ចុប្បន្នភាពសម្ភារៈ។"],
  h_signed: ["Lease signed by {0}.", "កិច្ចសន្យាបានចុះហត្ថលេខាដោយ {0}។"],
  h_movein: ["{0} moved in.", "{0} បានចូលស្នាក់នៅ។"],
  h_moveout: ["{0} moved out.", "{0} បានចាកចេញ។"],
  h_terminated: [
    "Lease of {0} terminated as of {1}.",
    "កិច្ចសន្យារបស់ {0} បានបញ្ចប់ត្រឹម {1}។",
  ],
  h_reserved: ["Reserved by {0} until {1}.", "បានកក់ដោយ {0} រហូតដល់ {1}។"],
  lk_current: ["Lease active", "កិច្ចសន្យាកំពុងអនុវត្ត"],
  lk_draft: ["Draft", "សេចក្តីព្រាង"],
  lk_ended: ["Ended", "បានបញ្ចប់"],
  lk_terminated: ["Terminated", "បានបញ្ចប់មុនកំណត់"],
  lk_cancelled: ["Cancelled", "បានលុបចោល"],
  rs_active: ["Active", "កំពុងដំណើរការ"],
  unit_no: ["Parking number", "លេខចំណត"],
  required: ["Required", "ចាំបាច់"],
  pick_floor: ["Choose a floor", "ជ្រើសជាន់"],
  no_req: ["Enter the Parking number.", "សូមបញ្ចូលលេខចំណត។"],
  floor_req: ["Choose the floor.", "សូមជ្រើសជាន់។"],
  // new
  no_features: [
    "No Room features are in Settings yet.",
    "មិនទាន់មានលក្ខណៈចំណតក្នុងការកំណត់ទេ។",
  ],
  // new
  new_note: [
    "A new Parking starts as Vacant with an empty inventory; add its items on the Parking page.",
    "ចំណតថ្មីចាប់ផ្តើមជាទំនេរ ជាមួយបញ្ជីសម្ភារៈទទេ; បន្ថែមសម្ភារៈនៅទំព័រចំណត។",
  ],
  edit_note: [
    "Changes are dated and kept in History. The Parking number cannot change.",
    "ការផ្លាស់ប្តូរមានកាលបរិច្ឆេទ និងរក្សាទុកក្នុងប្រវត្តិ។ លេខចំណតមិនអាចប្តូរបានទេ។",
  ],
  save: ["Save", "រក្សាទុក"],
  cancel: ["Cancel", "បោះបង់"],
  ok: ["OK", "យល់ព្រម"],
  new_saved: ["Parking {0} added as Vacant.", "បានបន្ថែមចំណត {0} ជាទំនេរ។"],
  saved: ["Parking {0} updated.", "បានធ្វើបច្ចុប្បន្នភាពចំណត {0}។"],
  // new
  invalid: [
    "Check the Parking details. The Parking number may already be used, or a list item may have been removed.",
    "សូមពិនិត្យព័ត៌មានចំណត។ លេខចំណតអាចត្រូវបានប្រើរួច ឬធាតុក្នុងបញ្ជីអាចត្រូវបានដកចេញ។",
  ],
  // new
  conflict: [
    "Someone else changed this Parking first. Its latest details are shown now; try again if needed.",
    "មាននរណាម្នាក់បានកែចំណតនេះមុន។ ព័ត៌មានចុងក្រោយត្រូវបានបង្ហាញឥឡូវ; សូមព្យាយាមម្តងទៀតបើចាំបាច់។",
  ],
  // new
  not_saved: [
    "The change was not saved. Retry when the service is available.",
    "ការផ្លាស់ប្តូរមិនត្រូវបានរក្សាទុកទេ។ សូមព្យាយាមម្តងទៀតពេលសេវាអាចប្រើបាន។",
  ],
  blocked_lease: [
    "This Parking has a signed Lease. Its status changes only through Move-out.",
    "ចំណតនេះមានកិច្ចសន្យាបានចុះហត្ថលេខា។ ស្ថានភាពប្តូរបានតែតាមរយៈការចាកចេញប៉ុណ្ណោះ។",
  ],
  blocked_res: [
    "This Parking has an active Reservation. Cancel the Reservation first.",
    "ចំណតនេះមានការកក់កំពុងដំណើរការ។ សូមលុបចោលការកក់ជាមុន។",
  ],
  new_status: ["New status", "ស្ថានភាពថ្មី"],
  reason: ["Reason", "មូលហេតុ"],
  reason_req: [
    "Give the reason for the change.",
    "សូមបញ្ជាក់មូលហេតុនៃការប្តូរ។",
  ],
  // new
  same_status: [
    "Choose a status different from the current one.",
    "សូមជ្រើសស្ថានភាពខុសពីស្ថានភាពបច្ចុប្បន្ន។",
  ],
  status_note: [
    "Occupied and Reserved are set by the app when a Lease is signed or a Reservation is made. Every change is kept in the history.",
    "មានអ្នកជួល និង បានកក់ ត្រូវបានកំណត់ដោយកម្មវិធី ពេលចុះហត្ថលេខាកិច្ចសន្យា ឬធ្វើការកក់។ ការប្តូរទាំងអស់ត្រូវបានរក្សាទុកក្នុងប្រវត្តិ។",
  ],
  status_saved: ["{0} is now {1}.", "{0} ឥឡូវ {1}។"],
  // new (V1-061, owner 29/10/2026): the Utility prices on the Units and Unit pages
  utilities: ["Electricity and water", "អគ្គិសនី និងទឹក"],
  prices_now: ["Utility prices now", "តម្លៃទឹកភ្លើងបច្ចុប្បន្ន"],
  u_el: ["Electricity", "អគ្គិសនី"],
  u_wa: ["Water", "ទឹក"],
  u_price: ["{0} per {1}", "{0} ក្នុង១{1}"],
  u_since: ["since {0}", "ចាប់ពី {0}"],
  u_next: ["From {0}: {1}", "ចាប់ពី {0}៖ {1}"],
  u_no_rate: ["No price set yet", "មិនទាន់កំណត់តម្លៃ"],
  u_meter: ["Meter {0}", "នាឡិកាស្ទង់ {0}"],
  u_working: ["Working", "ដំណើរការ"],
  u_broken: ["Broken since {0}", "ខូចតាំងពី {0}"],
  u_no_meter: [
    "No meter, so this Unit is not billed for it.",
    "គ្មាននាឡិកាស្ទង់ ដូច្នេះបន្ទប់នេះមិនត្រូវគិតថ្លៃនេះទេ។",
  ],
  u_cannot: [
    "Your account cannot read Utilities.",
    "គណនីរបស់អ្នកមិនអាចអានទឹកភ្លើងបានទេ។",
  ],
  u_failed: [
    "The Utility prices could not be read. Open this page again later.",
    "មិនអាចអានតម្លៃទឹកភ្លើងបានទេ។ សូមបើកទំព័រនេះម្តងទៀតពេលក្រោយ។",
  ],
  u_settings: [
    "Prices are set in Settings › Rates and services.",
    "តម្លៃត្រូវបានកំណត់នៅ ការកំណត់ › តម្លៃ និងសេវា។",
  ],
} as const;

export type UnitTextKey = keyof typeof TEXT;

/** The text in the chosen language, with {0}, {1} filled in. */
export function ut(
  language: Language,
  key: UnitTextKey,
  ...values: (string | number)[]
): string {
  return TEXT[key][language === "en" ? 0 : 1].replace(/\{(\d)\}/g, (_, n) =>
    String(values[Number(n)] ?? ""),
  );
}
