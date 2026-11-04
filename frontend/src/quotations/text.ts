// V1.1 part 6 (DL-123): the words of Office › Invoices › Quotations, in English and Khmer, from
// the mock-up round 16 (with the round 30 words: "New Quotation", "Customer declined"). Khmer
// marked "new" needs the native check.

import type { Language } from "../signInText";

const TEXT = {
  loading: ["Loading…", "កំពុងផ្ទុក…"],
  failed: ["This could not be read just now.", "មិនអាចអានបានទេឥឡូវនេះ។"],
  retry: ["Try again", "សាកម្តងទៀត"],
  back: ["Back to Quotations", "ត្រឡប់ទៅសម្រង់តម្លៃ"],
  no_property: [
    "Choose a Property first.",
    // new
    "សូមជ្រើសអចលនទ្រព្យជាមុន។",
  ],
  not_found: ["This Quotation was not found.", "រកមិនឃើញសម្រង់តម្លៃនេះទេ។"],
  // List
  sub: [
    "The Customer reads and signs the Quotation. Signing issues the Invoice at once.",
    "អតិថិជនអាន និងចុះហត្ថលេខាលើសម្រង់តម្លៃ។ ការចុះហត្ថលេខាចេញវិក្កយបត្រភ្លាម។",
  ],
  new_btn: ["New Quotation", "សម្រង់តម្លៃថ្មី"],
  c_all: ["All Quotations", "សម្រង់តម្លៃទាំងអស់"],
  c_all_s: ["The latest 300", "300 ចុងក្រោយ"],
  c_wait: ["Waiting for signature", "រង់ចាំហត្ថលេខា"],
  c_wait_s: [
    "Until their valid day",
    // new
    "រហូតដល់ថ្ងៃផុតសុពលភាព",
  ],
  c_signed: ["Signed", "បានចុះហត្ថលេខា"],
  c_signed_s: ["Invoice issued", "វិក្កយបត្រចេញរួច"],
  c_closed: ["Expired or declined", "ផុតកំណត់ ឬបដិសេធ"],
  c_closed_s: ["No Invoice", "គ្មានវិក្កយបត្រ"],
  showing: ["Showing: {0}", "កំពុងបង្ហាញ៖ {0}"],
  show_all: ["Show all", "បង្ហាញទាំងអស់"],
  col_no: ["No.", "លេខ"],
  col_cust: ["Customer", "អតិថិជន"],
  col_made: ["Made", "បង្កើត"],
  col_until: ["Valid until", "មានសុពលភាពដល់"],
  col_amount: ["Amount", "ចំនួនទឹកប្រាក់"],
  col_status: ["Status", "ស្ថានភាព"],
  n1: ["1 Quotation", "សម្រង់តម្លៃ 1"],
  n: ["{0} Quotations", "សម្រង់តម្លៃ {0}"],
  none: ["No Quotations here.", "គ្មានសម្រង់តម្លៃនៅទីនេះ។"],
  st_WAITING: ["Waiting for signature", "រង់ចាំហត្ថលេខា"],
  st_SIGNED: ["Signed", "បានចុះហត្ថលេខា"],
  st_REPLACED: ["Replaced", "ត្រូវបានជំនួស"],
  st_REFUSED: ["Customer declined", "អតិថិជនបដិសេធ"],
  st_EXPIRED: ["Expired", "ផុតកំណត់"],
  replaced_by: ["Replaced by {0}", "ជំនួសដោយ {0}"],
  replaces: ["Replaces {0}", "ជំនួស {0}"],
  // One Quotation
  p_Q: ["Quotation", "សម្រង់តម្លៃ"],
  p_S: ["Customer signs", "អតិថិជនចុះហត្ថលេខា"],
  p_I: ["Invoice issued", "ចេញវិក្កយបត្រ"],
  p_P: ["Paid, Receipt", "បានបង់ បង្កាន់ដៃ"],
  status: ["Status", "ស្ថានភាព"],
  sign: ["Customer signed", "អតិថិជនបានចុះហត្ថលេខា"],
  print: ["Print Quotation", "បោះពុម្ពសម្រង់តម្លៃ"],
  lower: ["Lower the price (new version)", "បញ្ចុះតម្លៃ (កំណែថ្មី)"],
  refuse: ["Customer declined", "អតិថិជនបដិសេធ"],
  again: ["Make a new Quotation", "ធ្វើសម្រង់តម្លៃថ្មី"],
  open_inv: ["Open Invoice {0}", "បើកវិក្កយបត្រ {0}"],
  open_next: ["Open {0}", "បើក {0}"],
  valid_until: ["Valid until {0}", "មានសុពលភាពដល់ {0}"],
  w3: [
    "When the Customer signs, tap Customer signed. The Invoice is issued at once, due in {0} days, and the items leave stock.",
    "ពេលអតិថិជនចុះហត្ថលេខា ចុច អតិថិជនបានចុះហត្ថលេខា។ វិក្កយបត្រចេញភ្លាម ត្រូវបង់ក្នុង {0} ថ្ងៃ ហើយទំនិញចេញពីស្តុក។",
  ],
  w3_plain: [
    "When the Customer signs, tap Customer signed. The Invoice is issued at once and the items leave stock.",
    // new
    "ពេលអតិថិជនចុះហត្ថលេខា ចុច អតិថិជនបានចុះហត្ថលេខា។ វិក្កយបត្រចេញភ្លាម ហើយទំនិញចេញពីស្តុក។",
  ],
  expired_n: [
    "This Quotation expired on {0}. Make a new Quotation if the Customer still wants it.",
    "សម្រង់តម្លៃនេះផុតកំណត់ថ្ងៃ {0}។ ធ្វើសម្រង់តម្លៃថ្មី បើអតិថិជននៅចង់បាន។",
  ],
  signed_n: [
    "Signed on {0}. Invoice {1} was issued at once.",
    "បានចុះហត្ថលេខាថ្ងៃ {0}។ វិក្កយបត្រ {1} ចេញភ្លាម។",
  ],
  voided_n: [
    "Invoice {0} was voided. The items went back to stock.",
    // new
    "វិក្កយបត្រ {0} ត្រូវបានទុកជាមោឃៈ។ ទំនិញត្រឡប់ទៅស្តុកវិញ។",
  ],
  refused_n: ["The Customer declined: {0}", "អតិថិជនបដិសេធ៖ {0}"],
  cust_t: ["Customer", "អតិថិជន"],
  open_customer: ["Open Customer", "បើកអតិថិជន"],
  history_t: ["History", "ប្រវត្តិ"],
  h_made: ["Quotation made by {0}", "សម្រង់តម្លៃធ្វើដោយ {0}"],
  h_made_plain: ["Quotation made", "សម្រង់តម្លៃត្រូវបានធ្វើ"],
  h_lowered: ["Lower price: {0}", "បញ្ចុះតម្លៃ៖ {0}"],
  h_signed: [
    "Customer signed; Invoice {0} issued",
    "អតិថិជនចុះហត្ថលេខា; ចេញវិក្កយបត្រ {0}",
  ],
  h_replaced: ["Replaced by {0}", "ជំនួសដោយ {0}"],
  h_refused: ["Customer declined: {0}", "អតិថិជនបដិសេធ៖ {0}"],
  lines_t: ["What is quoted", "អ្វីដែលបានសម្រង់តម្លៃ"],
  taken: ["Taken from {0} ({1})", "យកពី {0} ({1})"],
  service_line: ["Service, no stock", "សេវា គ្មានស្តុក"],
  // Sign dialog
  sign_t: ["Customer signed {0}", "អតិថិជនបានចុះហត្ថលេខា {0}"],
  sign_day: ["Day the Customer signed", "ថ្ងៃអតិថិជនចុះហត្ថលេខា"],
  e_day: ["Use a day from {0} to {1}.", "ប្រើថ្ងៃពី {0} ដល់ {1}។"],
  take: ["Take from: {0} × {1}", "យកពី៖ {0} × {1}"],
  take_pick: ["Choose a place", "ជ្រើសទីតាំង"],
  in_stock: ["{0} in stock", "មានក្នុងស្តុក {0}"],
  e_take: ["Choose where this item is taken from.", "ជ្រើសកន្លែងយកទំនិញនេះ។"],
  e_short: [
    "Only {0} at {1}. The Quotation waits until the items are in stock.",
    // new
    "មានតែ {0} នៅ {1}។ សម្រង់តម្លៃរង់ចាំរហូតដល់ទំនិញមានក្នុងស្តុក។",
  ],
  no_stock: [
    "{0} is not in stock anywhere. Buy it first in Building › Products; the Quotation waits.",
    // new
    "{0} មិនមានក្នុងស្តុកទេ។ ទិញវាជាមុនក្នុង អគារ › ផលិតផល; សម្រង់តម្លៃរង់ចាំ។",
  ],
  sign_h: [
    "The Invoice is issued now for {0}, due in {1} days. Items leave stock now. Print the Invoice next.",
    "វិក្កយបត្រចេញឥឡូវ សម្រាប់ {0} ត្រូវបង់ក្នុង {1} ថ្ងៃ។ ទំនិញចេញពីស្តុកឥឡូវ។ បន្ទាប់មកបោះពុម្ពវិក្កយបត្រ។",
  ],
  sign_ok: ["Issue Invoice", "ចេញវិក្កយបត្រ"],
  signed_toast: [
    "Invoice {0} issued. Print it for the Customer.",
    "ចេញវិក្កយបត្រ {0}។ បោះពុម្ពឲ្យអតិថិជន។",
  ],
  // Refuse dialog
  refuse_t: ["Customer declined {0}", "អតិថិជនបដិសេធ {0}"],
  refuse_r: ["What the Customer said", "អ្វីដែលអតិថិជននិយាយ"],
  e_reason: ["Enter what the Customer said.", "បញ្ចូលអ្វីដែលអតិថិជននិយាយ។"],
  refused_toast: [
    "{0} is closed: the Customer declined.",
    "{0} បានបិទ៖ អតិថិជនបដិសេធ។",
  ],
  // New Quotation
  new_t: ["New Quotation", "សម្រង់តម្លៃថ្មី"],
  new_sub: [
    "Pick products. Price comes from Products. The Customer signs the printed Quotation, then the Invoice is issued.",
    "ជ្រើសផលិតផល។ តម្លៃមកពីផលិតផល។ អតិថិជនចុះហត្ថលេខាលើសម្រង់តម្លៃដែលបានបោះពុម្ព បន្ទាប់មកវិក្កយបត្រត្រូវបានចេញ។",
  ],
  new_ver: ["New version of {0}", "កំណែថ្មីនៃ {0}"],
  new_ver_h: [
    "The old Quotation is kept and marked Replaced. Print the new one; the Customer signs it again.",
    "សម្រង់តម្លៃចាស់រក្សាទុក ហើយសម្គាល់ថាត្រូវបានជំនួស។ បោះពុម្ពថ្មី; អតិថិជនចុះហត្ថលេខាម្តងទៀត។",
  ],
  f_cust: ["Customer", "អតិថិជន"],
  f_choose: ["Choose…", "ជ្រើសរើស…"],
  required: ["Required", "ចាំបាច់"],
  optional: ["Optional", "ស្រេចចិត្ត"],
  no_customers: [
    "No Customer has a signed Lease yet, so no Quotation can be made.",
    // new
    "មិនទាន់មានអតិថិជនណាមានកិច្ចសន្យាជួលដែលបានចុះហត្ថលេខាទេ ដូច្នេះមិនអាចធ្វើសម្រង់តម្លៃបានទេ។",
  ],
  col_prod: ["Product", "ផលិតផល"],
  col_qty: ["Qty", "ចំនួន"],
  col_price: ["Price", "តម្លៃ"],
  col_amt: ["Amount", "ចំនួនទឹកប្រាក់"],
  remove: ["Remove", "ដកចេញ"],
  pick: ["Choose a product", "ជ្រើសផលិតផល"],
  opt_stock: ["{0} in stock", "ស្តុក {0}"],
  opt_no_price: ["no price yet", "មិនទាន់មានតម្លៃ"],
  total: ["Total", "សរុប"],
  price_lock: [
    "Price comes from Products. Only a Manager or the Owner can lower it.",
    "តម្លៃមកពីផលិតផល។ មានតែអ្នកគ្រប់គ្រង ឬម្ចាស់ទេដែលអាចបញ្ចុះ។",
  ],
  price_mgr: [
    "You can lower a price. A lowered price shows the list price next to it.",
    "អ្នកអាចបញ្ចុះតម្លៃ។ តម្លៃដែលបញ្ចុះបង្ហាញតម្លៃដើមក្បែរវា។",
  ],
  lowered: ["List price {0}", "តម្លៃតាមបញ្ជី {0}"],
  low_reason: ["Why the price is lower", "ហេតុអ្វីតម្លៃទាប"],
  low_reason_ph: [
    "For example: long-time tenant",
    // new
    "ឧទាហរណ៍៖ អ្នកជួលយូរ",
  ],
  note: ["Note for the Customer", "កំណត់សម្គាល់សម្រាប់អតិថិជន"],
  note_ph: [
    "For example: copy of the main door key",
    "ឧទាហរណ៍៖ ចម្លងសោទ្វារធំ",
  ],
  valid: [
    "A Quotation is valid for the Quotation days in Settings › Business (7 days unless the Owner changed it).",
    // new
    "សម្រង់តម្លៃមានសុពលភាពតាមចំនួនថ្ងៃក្នុង ការកំណត់ › អាជីវកម្ម (7 ថ្ងៃ លុះត្រាម្ចាស់បានប្តូរ)។",
  ],
  save: ["Save and print Quotation", "រក្សាទុក និងបោះពុម្ពសម្រង់តម្លៃ"],
  cancel: ["Cancel", "បោះបង់"],
  close: ["Close", "បិទ"],
  e_sum: ["Fix {0} things:", "កែ {0} ចំណុច៖"],
  e_sum1: ["Fix 1 thing:", "កែ 1 ចំណុច៖"],
  e_cust: ["Choose the Customer.", "ជ្រើសអតិថិជន។"],
  e_items: [
    "Add at least one product with a quantity from 1 to 999 and a price.",
    "បន្ថែមផលិតផលយ៉ាងហោចណាស់មួយ ជាមួយចំនួនពី 1 ដល់ 999 និងតម្លៃ។",
  ],
  e_up: [
    "A price cannot be above the list price.",
    "តម្លៃមិនអាចលើសតម្លៃតាមបញ្ជីទេ។",
  ],
  e_low_reason: [
    "Enter why the price is lower.",
    // new
    "បញ្ចូលហេតុអ្វីតម្លៃទាប។",
  ],
  e_max: ["At most 20 lines.", "យ៉ាងច្រើន 20 ជួរ។"],
  saved: [
    "Quotation {0} saved. Print it for the Customer to sign.",
    "បានរក្សាទុកសម្រង់តម្លៃ {0}។ បោះពុម្ពឲ្យអតិថិជនចុះហត្ថលេខា។",
  ],
  w_t: ["What happens next", "អ្វីកើតឡើងបន្ទាប់"],
  w1: [
    "Print the Quotation. The Customer reads it.",
    "បោះពុម្ពសម្រង់តម្លៃ។ អតិថិជនអានវា។",
  ],
  w2: [
    "If the Customer asks for a lower price and a Manager agrees, make a new version. The Customer signs the new one.",
    "បើអតិថិជនសុំបញ្ចុះតម្លៃ ហើយអ្នកគ្រប់គ្រងយល់ព្រម ធ្វើកំណែថ្មី។ អតិថិជនចុះហត្ថលេខាលើកំណែថ្មី។",
  ],
  w4: [
    "Print the Invoice. When the Customer pays, Receive payment prints the Receipt.",
    "បោះពុម្ពវិក្កយបត្រ។ ពេលអតិថិជនបង់ ទទួលការបង់ប្រាក់ បោះពុម្ពបង្កាន់ដៃ។",
  ],
  damage_moved: [
    "A Damage charge comes from the Move-out inspection.",
    // new
    "ថ្លៃខូចខាតមកពីការត្រួតពិនិត្យពេលចាកចេញ។",
  ],
  // Refusals
  f_right: [
    "You may not do this. Ask the Owner for the right in Roles.",
    // new
    "អ្នកមិនអាចធ្វើការនេះបានទេ។ សុំសិទ្ធិពីម្ចាស់ក្នុងតួនាទី។",
  ],
  f_stale: [
    "Someone changed this Quotation meanwhile. It was read again; check it and try again.",
    // new
    "មាននរណាម្នាក់បានប្តូរសម្រង់តម្លៃនេះ។ វាត្រូវបានអានម្តងទៀត; ពិនិត្យ ហើយសាកម្តងទៀត។",
  ],
  f_stock: [
    "An item is not in stock at that place. The Quotation waits; choose another place or buy the item first.",
    // new
    "ទំនិញមួយមិនមាននៅទីតាំងនោះទេ។ សម្រង់តម្លៃរង់ចាំ; ជ្រើសទីតាំងផ្សេង ឬទិញទំនិញជាមុន។",
  ],
  f_refused: [
    "The server refused this. Check the Quotation: it may have expired or a product may have no price.",
    // new
    "ម៉ាស៊ីនមេបានបដិសេធ។ ពិនិត្យសម្រង់តម្លៃ៖ វាអាចផុតកំណត់ ឬផលិតផលអាចគ្មានតម្លៃ។",
  ],
  f_failed: [
    "This was not saved. Check the connection and try again.",
    // new
    "មិនបានរក្សាទុកទេ។ ពិនិត្យការតភ្ជាប់ ហើយសាកម្តងទៀត។",
  ],
} as const satisfies Record<string, readonly [string, string]>;

export type QuotationsTextKey = keyof typeof TEXT;

/** The words in the chosen language, with {0}, {1} filled in. */
export function qt(
  language: Language,
  key: QuotationsTextKey,
  ...values: (string | number)[]
): string {
  const words: string = TEXT[key][language === "km" ? 1 : 0];
  return words.replace(/\{(\d+)\}/g, (match, index: string) => {
    const value = values[Number(index)];
    return value === undefined ? match : String(value);
  });
}
