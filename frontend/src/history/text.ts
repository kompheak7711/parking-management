// V1-058 R7c: the words of History in English and Khmer, from the owner's mock-up (i18n4.js,
// app4.js). Khmer needs the native check before the app is used. Lines marked "new" are not in
// the mock-up.

import type { Language } from "../signInText";
import { singular } from "../shell/plural";

const TEXT = {
  hi_title: ["Audit log", "ប្រវត្តិ"],
  hi_sub: [
    "Who did what and when, across the whole Property. Nothing here can be edited or deleted.",
    "អ្នកណាធ្វើអ្វី ពេលណា ទូទាំងអចលនទ្រព្យ។ គ្មានអ្វីនៅទីនេះកែ ឬលុបបានទេ។",
  ],
  hi_when: ["When", "ពេលណា"],
  hi_today: ["Today", "ថ្ងៃនេះ"],
  hi_7: ["7 days", "7 ថ្ងៃ"],
  hi_30: ["30 days", "30 ថ្ងៃ"],
  hi_all: ["All", "ទាំងអស់"],
  hi_who: ["Who", "អ្នកណា"],
  hi_anyone: ["Anyone", "អ្នកណាក៏បាន"],
  hi_kind: ["Action", "សកម្មភាព"],
  // new: the server finds events by Unit.
  hi_unit: ["Parking", "ចំណត"],
  // new
  hi_any_unit: ["All Parking", "គ្រប់ចំណត"],
  hi_search: ["Search", "ស្វែងរក"],
  hi_col_what: ["What happened", "មានអ្វីកើតឡើង"],
  hi_col_rec: ["Record", "កំណត់ត្រា"],
  hi_n1: ["1 event", "1 ព្រឹត្តិការណ៍"],
  hi_n: ["{0} events", "{0} ព្រឹត្តិការណ៍"],
  hi_none: ["No events match.", "គ្មានព្រឹត្តិការណ៍ត្រូវគ្នាទេ។"],
  hi_export: ["Export", "នាំចេញ"], // new
  ex_title: ["Export the audit log", "នាំចេញកំណត់ហេតុសវនកម្ម"], // new
  ex_as: ["File type", "ប្រភេទឯកសារ"], // new
  ex_same: [
    "The file uses the same days, person and Unit as the list.",
    "ឯកសារប្រើថ្ងៃ មនុស្ស និងបន្ទប់ ដូចបញ្ជីដែរ។",
  ], // new
  ex_close: ["Close", "បិទ"], // new
  hi_note: [
    "Each search here is itself recorded in the audit log. Record pages show the same events for one record.",
    "ការស្វែងរកនីមួយៗនៅទីនេះ ក៏សរសេរក្នុងប្រវត្តិដែរ។ ទំព័រកំណត់ត្រាបង្ហាញព្រឹត្តិការណ៍ដូចគ្នា សម្រាប់កំណត់ត្រាមួយ។",
  ],
  // new
  more: ["Show more", "បង្ហាញបន្ថែម"],
  // new
  loading: ["Loading the audit log…", "កំពុងអានប្រវត្តិ…"],
  // new
  failed: [
    "The audit log could not be loaded. Check the connection and try again.",
    "មិនអាចអានប្រវត្តិបានទេឥឡូវនេះ។ សូមពិនិត្យការតភ្ជាប់ ហើយព្យាយាមម្តងទៀត។",
  ],
  // new
  not_allowed: [
    "Your account cannot see the audit log. Use the menu to open your work.",
    "គណនីរបស់អ្នកមិនអាចមើលប្រវត្តិបានទេ។ សូមប្រើម៉ឺនុយ ដើម្បីបើកការងាររបស់អ្នក។",
  ],
  retry: ["Retry", "ព្យាយាមម្តងទៀត"],
  // new: a person the screen cannot name (the user list needs identity.manage_access).
  someone: ["A user ({0})", "អ្នកប្រើ ({0})"],
  // new
  me: ["{0} (you)", "{0} (អ្នក)"],
  // new
  reason: ["Reason: {0}", "មូលហេតុ៖ {0}"],
  // new
  refused: ["Rejected", "បានបដិសេធ"],
  // new
  ex_xlsx: ["Spreadsheet (.xlsx)", "សៀវភៅបញ្ជី (.xlsx)"],
  // new
  ex_pdf: ["PDF", "PDF"],
  // new
  ex_saved: [
    "{0} is ready. Its fingerprint is recorded in the audit log.",
    "{0} រួចរាល់។ ស្នាមម្រាមដៃរបស់វាត្រូវបានសរសេរក្នុងប្រវត្តិ។",
  ],
  // new
  ex_failed: [
    "The file could not be made just now. Try again.",
    "មិនអាចបង្កើតឯកសារបានទេឥឡូវនេះ។ សូមព្យាយាមម្តងទៀត។",
  ],
  // new
  ex_refused: [
    "This file cannot be made with these choices. Choose fewer days, or a spreadsheet instead of a PDF.",
    "មិនអាចបង្កើតឯកសារនេះជាមួយជម្រើសទាំងនេះបានទេ។ សូមជ្រើសថ្ងៃតិចជាងនេះ ឬសៀវភៅបញ្ជីជំនួស PDF។",
  ],
  // new: kinds of record (the server's entity type).
  k_invoice: ["Invoice", "វិក្កយបត្រ"],
  k_payment: ["Payment", "ការបង់ប្រាក់"],
  k_receipt: ["Receipt", "បង្កាន់ដៃ"],
  k_reservation: ["Reservation", "ការកក់"],
  k_lease: ["Lease", "កិច្ចសន្យា"],
  k_customer: ["Customer", "អតិថិជន"],
  k_unit: ["Unit", "បន្ទប់"],
  k_moveout: ["Move-outs", "ការចាកចេញ"],
  k_settle: ["Final Settlement", "ការទូទាត់ចុងក្រោយ"],
  k_deposit: ["Deposit", "ប្រាក់កក់"],
  k_credit: ["Credit", "ឥណទាន"],
  k_refund: ["Refund", "ការសងប្រាក់"],
  k_meter: ["Meter", "នាឡិកាស្ទង់"],
  k_setting: ["Settings", "ការកំណត់"],
  k_user: ["User", "អ្នកប្រើ"],
  k_export: ["Export or search", "នាំចេញ ឬស្វែងរក"],
  // new (Staff review fix 10): the Staff, Ledger and Telegram steps get their own tag.
  k_staff: ["Staff", "បុគ្គលិក"],
  k_ledger: ["Ledger", "សៀវភៅបញ្ជី"],
  k_telegram: ["Telegram", "តេឡេក្រាម"],
  // new (Staff review fix 11): the audit log's own searches are hidden unless asked for.
  hi_searches: ["Show searches", "បង្ហាញការស្វែងរក"],
  hi_searches_hidden: ["{0} searches hidden", "លាក់ការស្វែងរក {0}"],
  k_other: ["Other", "ផ្សេងទៀត"],
} as const satisfies Record<string, readonly [string, string]>;

export type HistoryTextKey = keyof typeof TEXT;

/** The words for `key`, with {0}, {1} … filled in. */
export function hit(
  language: Language,
  key: HistoryTextKey,
  ...values: (string | number)[]
): string {
  const text = TEXT[key][language === "km" ? 1 : 0];
  return singular(
    text.replace(/\{(\d+)\}/g, (match, index: string) => {
      const value = values[Number(index)];
      return value === undefined ? match : String(value);
    }),
  );
}

export type HistoryKind =
  | "invoice"
  | "payment"
  | "receipt"
  | "reservation"
  | "lease"
  | "customer"
  | "unit"
  | "moveout"
  | "settle"
  | "deposit"
  | "credit"
  | "refund"
  | "meter"
  | "setting"
  | "user"
  | "export"
  | "staff"
  | "ledger"
  | "telegram"
  | "other";

// The server's entity types, grouped as the mock-up's kinds. A type not listed is "Other".
const KINDS: readonly [RegExp, HistoryKind][] = [
  [/^final_settlement|^settlement_/, "settle"],
  [/^(move_out|physical_move_out|termination_notice)/, "moveout"],
  [/^(payment|payment_|unidentified_payment)/, "payment"],
  [/^receipt/, "receipt"],
  [/invoice|^late_payment|nonrecurring|initial_rent/, "invoice"],
  [/^reservation/, "reservation"],
  [/^lease|unpaid_initial/, "lease"],
  [/^customer_credit/, "credit"],
  [/^customer/, "customer"],
  [/^unit/, "unit"],
  [/deposit/, "deposit"],
  [/^refund/, "refund"],
  [/meter|^utility_(reading|baseline)|broken_meter/, "meter"],
  [
    /rate$|^ExchangeRateRecord$|^ServiceRate$|^UtilityRate$|^property|setting|unit_setup/,
    "setting",
  ],
  [/^(user|identity|role_bundle|session|account)/, "user"],
  [/^(audit|export|report)/, "export"],
];

// Staff review fix 10 (owner 16/11/2026): the Staff (HR), Ledger and Telegram records, found by
// the record's type or by the step's own first word.
const AREAS: readonly [RegExp, RegExp, HistoryKind][] = [
  [
    /^(employee|payroll|payslip|salary_|attendance|overtime|staff_request|hr_)/,
    /^hr\./,
    "staff",
  ],
  [
    /^(gl_|ledger|journal|expense|fixed_asset|bank_|petty_cash|budget|month_end)/,
    /^(gl|ledger)\./,
    "ledger",
  ],
  [/^(telegram|tg_)/, /^(telegram|tg)\./, "telegram"],
];

export function kindOf(resourceType: string, action = ""): HistoryKind {
  for (const [type, step, kind] of AREAS) {
    if (type.test(resourceType) || step.test(action)) return kind;
  }
  for (const [pattern, kind] of KINDS) {
    if (pattern.test(resourceType)) return kind;
  }
  return "other";
}

export function kindText(language: Language, kind: HistoryKind): string {
  return hit(language, `k_${kind}`);
}

/** "invoice.adjustment_reversed" → "Invoice adjustment reversed" (the server's own words). */
export function actionText(action: string): string {
  // Staff review fix 10: the area's short code ("hr.", "gl.", "identity.") is not read out.
  const words = action
    .replace(/^(hr|gl|identity)\./, "")
    .replace(/[._]+/g, " ")
    .trim()
    .replace(/\s+/g, " ")
    .toLowerCase()
    // The server's code name "unit" is the word "Parking" on the screen.
    .replace(/\bunits?\b/g, "parking");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * Staff review fix 10: a reason without the decision-log code the server adds to some of its
 * own reasons ("Audit search (DL-072 answer 14)" → "Audit search").
 */
export function reasonText(reason: string): string {
  return reason.replace(/\s*\(DL-\d+[^)]*\)/g, "").trim();
}
